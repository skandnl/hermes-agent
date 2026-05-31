"""Shared helper classes for gateway platform adapters.

Extracts common patterns that were duplicated across 5-7 adapters:
message deduplication, text batch aggregation, markdown stripping,
and thread participation tracking.
"""

import asyncio
import json
import logging
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

from utils import atomic_json_write

if TYPE_CHECKING:
    from gateway.platforms.base import MessageEvent

logger = logging.getLogger(__name__)


# ─── Message Deduplication ────────────────────────────────────────────────────


class MessageDeduplicator:
    """TTL-based message deduplication cache.

    Replaces the identical ``_seen_messages`` / ``_is_duplicate()`` pattern
    previously duplicated in discord, slack, dingtalk, wecom, weixin,
    mattermost, and feishu adapters.

    Usage::

        self._dedup = MessageDeduplicator()

        # In message handler:
        if self._dedup.is_duplicate(msg_id):
            return

    Cross-process persistence
    -------------------------
    Pass ``persist=True`` (with a distinct ``namespace`` per platform) to
    back the cache with a small SQLite table at
    ``~/.hermes/message_dedup.db``.  This stops a *second* gateway process
    — e.g. one that briefly co-exists with the old one during a launchd/CD
    restart, whose websocket is still delivering events — from re-handling a
    message the first process already claimed.  The in-memory ``_seen`` dict
    is per-process, so without the shared table two overlapping gateways each
    treat the same message id as new and both act on it (e.g. Discord creates
    two auto-threads + replies).  The SQLite claim is atomic
    (``INSERT … ON CONFLICT`` serialised by SQLite), so exactly one process
    wins each message.
    """

    def __init__(
        self,
        max_size: int = 2000,
        ttl_seconds: float = 300,
        *,
        persist: bool = False,
        namespace: str = "default",
        persist_path: Optional[Path] = None,
    ):
        self._seen: Dict[str, float] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._namespace = namespace
        self._conn: Optional[sqlite3.Connection] = None
        self._db_lock = threading.Lock()
        self._prune_counter = 0
        if persist:
            self._init_persist(persist_path)

    def _init_persist(self, persist_path: Optional[Path]) -> None:
        """Open (and lazily create) the shared SQLite dedup table.

        Best-effort: any failure leaves ``self._conn = None`` so the
        deduplicator silently falls back to in-memory-only behaviour rather
        than breaking message handling.
        """
        try:
            if persist_path is None:
                from hermes_constants import get_hermes_home

                persist_path = get_hermes_home() / "message_dedup.db"
            conn = sqlite3.connect(
                str(persist_path), timeout=5.0, check_same_thread=False
            )
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                # WAL unavailable on this filesystem (NFS/SMB/FUSE) — the
                # default rollback journal still serialises writers, which
                # is all the atomic claim needs.
                pass
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS message_dedup ("
                "namespace TEXT NOT NULL, "
                "msg_id TEXT NOT NULL, "
                "ts REAL NOT NULL, "
                "PRIMARY KEY (namespace, msg_id))"
            )
            conn.commit()
            self._conn = conn
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(
                "MessageDeduplicator: cross-process persistence disabled (%s)", e
            )
            self._conn = None

    def _claim_persist(self, msg_id: str, now: float) -> bool:
        """Atomically claim *msg_id* in the shared table.

        Returns True if it was ALREADY claimed (by this or another process)
        within the TTL window — i.e. the caller should treat it as a
        duplicate. Returns False if this call won the claim (fresh message).
        """
        cutoff = now - self._ttl
        with self._db_lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO message_dedup (namespace, msg_id, ts) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(namespace, msg_id) DO UPDATE SET ts=excluded.ts "
                    "WHERE message_dedup.ts < ?",
                    (self._namespace, msg_id, now, cutoff),
                )
                self._conn.commit()
                # rowcount == 1 -> fresh INSERT, or an expired row re-claimed.
                # rowcount == 0 -> conflict on a still-fresh row => duplicate.
                duplicate = cur.rowcount == 0
                self._prune_counter += 1
                if self._prune_counter >= 500:
                    self._prune_counter = 0
                    self._conn.execute(
                        "DELETE FROM message_dedup WHERE ts < ?", (cutoff,)
                    )
                    self._conn.commit()
                return duplicate
            except sqlite3.Error as e:
                logger.debug("MessageDeduplicator persist claim failed: %s", e)
                # On DB error, fall back to in-memory-only (don't drop the msg).
                return False

    def is_duplicate(self, msg_id: str) -> bool:
        """Return True if *msg_id* was already seen within the TTL window."""
        if not msg_id:
            return False
        now = time.time()
        if msg_id in self._seen:
            if now - self._seen[msg_id] < self._ttl:
                return True
            # Entry has expired — remove it and treat as new
            del self._seen[msg_id]
        # Cross-process atomic claim (only when persistence is enabled).
        if self._conn is not None and self._claim_persist(msg_id, now):
            # Another (or this) process already owns it — remember locally so
            # future same-process hits skip the DB entirely.
            self._seen[msg_id] = now
            return True
        self._seen[msg_id] = now
        if len(self._seen) > self._max_size:
            cutoff = now - self._ttl
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}
            if len(self._seen) > self._max_size:
                # TTL pruning alone does not cap the cache when every entry is
                # still fresh. Keep the newest entries so the helper's
                # max_size bound is enforced under sustained traffic.
                newest = sorted(
                    self._seen.items(),
                    key=lambda item: item[1],
                )[-self._max_size:]
                self._seen = dict(newest)
        return False

    def clear(self):
        """Clear all tracked messages."""
        self._seen.clear()


# ─── Text Batch Aggregation ──────────────────────────────────────────────────


class TextBatchAggregator:
    """Aggregates rapid-fire text events into single messages.

    Replaces the ``_enqueue_text_event`` / ``_flush_text_batch`` pattern
    previously duplicated in telegram, discord, matrix, wecom, and feishu.

    Usage::

        self._text_batcher = TextBatchAggregator(
            handler=self._message_handler,
            batch_delay=0.6,
            split_threshold=1900,
        )

        # In message dispatch:
        if msg_type == MessageType.TEXT and self._text_batcher.is_enabled():
            self._text_batcher.enqueue(event, session_key)
            return
    """

    def __init__(
        self,
        handler,
        *,
        batch_delay: float = 0.6,
        split_delay: float = 2.0,
        split_threshold: int = 4000,
    ):
        self._handler = handler
        self._batch_delay = batch_delay
        self._split_delay = split_delay
        self._split_threshold = split_threshold
        self._pending: Dict[str, "MessageEvent"] = {}
        self._pending_tasks: Dict[str, asyncio.Task] = {}

    def is_enabled(self) -> bool:
        """Return True if batching is active (delay > 0)."""
        return self._batch_delay > 0

    def enqueue(self, event: "MessageEvent", key: str) -> None:
        """Add *event* to the pending batch for *key*."""
        chunk_len = len(event.text or "")
        existing = self._pending.get(key)
        if not existing:
            event._last_chunk_len = chunk_len  # type: ignore[attr-defined]
            self._pending[key] = event
        else:
            existing.text = f"{existing.text}\n{event.text}"
            existing._last_chunk_len = chunk_len  # type: ignore[attr-defined]

        # Cancel prior flush timer, start a new one
        prior = self._pending_tasks.get(key)
        if prior and not prior.done():
            prior.cancel()
        self._pending_tasks[key] = asyncio.create_task(self._flush(key))

    async def _flush(self, key: str) -> None:
        """Wait then dispatch the batched event for *key*."""
        current_task = self._pending_tasks.get(key)
        pending = self._pending.get(key)
        last_len = getattr(pending, "_last_chunk_len", 0) if pending else 0

        # Use longer delay when the last chunk looks like a split message
        delay = self._split_delay if last_len >= self._split_threshold else self._batch_delay
        await asyncio.sleep(delay)

        event = self._pending.pop(key, None)
        if event:
            try:
                await self._handler(event)
            except Exception:
                logger.exception("[TextBatchAggregator] Error dispatching batched event for %s", key)

        if self._pending_tasks.get(key) is current_task:
            self._pending_tasks.pop(key, None)

    def cancel_all(self) -> None:
        """Cancel all pending flush tasks."""
        for task in self._pending_tasks.values():
            if not task.done():
                task.cancel()
        self._pending_tasks.clear()
        self._pending.clear()


# ─── Markdown Stripping ──────────────────────────────────────────────────────

# Pre-compiled regexes for performance
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_RE_ITALIC_STAR = re.compile(r"\*(.+?)\*", re.DOTALL)
_RE_BOLD_UNDER = re.compile(r"\b__(?![\s_])(.+?)(?<![\s_])__\b", re.DOTALL)
_RE_ITALIC_UNDER = re.compile(r"\b_(?![\s_])(.+?)(?<![\s_])_\b", re.DOTALL)
_RE_CODE_BLOCK = re.compile(r"```[a-zA-Z0-9_+-]*\n?")
_RE_INLINE_CODE = re.compile(r"`(.+?)`")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_LINK = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
_RE_MULTI_NEWLINE = re.compile(r"\n{3,}")


def strip_markdown(text: str) -> str:
    """Strip markdown formatting for plain-text platforms (SMS, iMessage, etc.).

    Replaces the identical ``_strip_markdown()`` functions previously
    duplicated in sms.py, bluebubbles.py, and feishu.py.
    """
    text = _RE_BOLD.sub(r"\1", text)
    text = _RE_ITALIC_STAR.sub(r"\1", text)
    text = _RE_BOLD_UNDER.sub(r"\1", text)
    text = _RE_ITALIC_UNDER.sub(r"\1", text)
    text = _RE_CODE_BLOCK.sub("", text)
    text = _RE_INLINE_CODE.sub(r"\1", text)
    text = _RE_HEADING.sub("", text)
    text = _RE_LINK.sub(r"\1", text)
    text = _RE_MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


# ─── Thread Participation Tracking ───────────────────────────────────────────


class ThreadParticipationTracker:
    """Persistent tracking of threads the bot has participated in.

    Replaces the identical ``_load/_save_participated_threads`` +
    ``_mark_thread_participated`` pattern previously duplicated in
    discord.py and matrix.py.

    Usage::

        self._threads = ThreadParticipationTracker("discord")

        # Check membership:
        if thread_id in self._threads:
            ...

        # Mark participation:
        self._threads.mark(thread_id)
    """

    _MAX_TRACKED = 500

    def __init__(self, platform_name: str, max_tracked: int = 500):
        self._platform = platform_name
        self._max_tracked = max_tracked
        self._threads: dict[str, None] = {
            str(thread_id): None for thread_id in self._load()
        }

    def _state_path(self) -> Path:
        from hermes_constants import get_hermes_home
        return get_hermes_home() / f"{self._platform}_threads.json"

    def _load(self) -> list[str]:
        path = self._state_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [str(thread_id) for thread_id in data]
            except Exception:
                pass
        return []

    def _save(self) -> None:
        path = self._state_path()
        thread_list = list(self._threads)
        if len(thread_list) > self._max_tracked:
            thread_list = thread_list[-self._max_tracked:]
            self._threads = dict.fromkeys(thread_list)
        atomic_json_write(path, thread_list, indent=None)

    def mark(self, thread_id: str) -> None:
        """Mark *thread_id* as participated and persist."""
        if thread_id not in self._threads:
            self._threads[thread_id] = None
            self._save()

    def __contains__(self, thread_id: str) -> bool:
        return thread_id in self._threads

    def clear(self) -> None:
        self._threads.clear()


# ─── Phone Number Redaction ──────────────────────────────────────────────────


def redact_phone(phone: str) -> str:
    """Redact a phone number for logging, preserving country code and last 4.

    Replaces the identical ``_redact_phone()`` functions in signal.py,
    sms.py, and bluebubbles.py.
    """
    if not phone:
        return "<none>"
    if len(phone) <= 8:
        return phone[:2] + "****" + phone[-2:] if len(phone) > 4 else "****"
    return phone[:4] + "****" + phone[-4:]
