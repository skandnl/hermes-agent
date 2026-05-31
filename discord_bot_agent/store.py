from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import PaperPosition, PaperTrade


DEFAULT_WATCHLIST = ["NVDA", "AAPL", "MSFT", "TSLA", "005930.KS"]


class TradingStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol TEXT PRIMARY KEY,
                    sector TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_watchlist (
                    user_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    sector TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, symbol)
                );
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
                    symbol TEXT NOT NULL,
                    quantity REAL NOT NULL CHECK (quantity > 0),
                    price REAL NOT NULL CHECK (price > 0),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS youtubers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    channel_id TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS youtube_scan_log (
                    video_id TEXT PRIMARY KEY,
                    youtuber_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    tickers TEXT NOT NULL,
                    scanned_at TEXT NOT NULL
                );
                """
            )
            # channel_id 컬럼 및 sector 컬럼 마이그레이션
            try:
                conn.execute("ALTER TABLE youtubers ADD COLUMN channel_id TEXT")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE watchlist ADD COLUMN sector TEXT")
            except Exception:
                pass

            now = datetime.now(timezone.utc).isoformat()
            for symbol in DEFAULT_WATCHLIST:
                conn.execute(
                    "INSERT OR IGNORE INTO watchlist(symbol, created_at) VALUES (?, ?)",
                    (symbol.upper(), now),
                )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES ('alerts_enabled', '1')"
            )


    def alerts_enabled(self) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'alerts_enabled'"
            ).fetchone()
        return row is None or row["value"] == "1"

    def set_alerts_enabled(self, enabled: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES ('alerts_enabled', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("1" if enabled else "0",),
            )

    def watchlist(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT symbol FROM watchlist ORDER BY symbol").fetchall()
        return [str(row["symbol"]) for row in rows]

    def watchlist_details(self) -> list[dict]:
        """관심종목 상세 정보(symbol, sector, created_at) 목록 반환."""
        with self.connect() as conn:
            rows = conn.execute("SELECT symbol, sector, created_at FROM watchlist ORDER BY sector, symbol").fetchall()
        return [dict(row) for row in rows]

    def user_watchlist(self, user_id: str) -> list[str]:
        """특정 사용자의 관심종목 티커 목록 반환."""
        uid = str(user_id).strip()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT symbol FROM user_watchlist WHERE user_id = ? ORDER BY symbol", (uid,)
            ).fetchall()
        return [str(row["symbol"]) for row in rows]

    def user_watchlist_details(self, user_id: str) -> list[dict]:
        """특정 사용자의 관심종목 상세 정보(symbol, sector, created_at) 목록 반환."""
        uid = str(user_id).strip()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT symbol, sector, created_at FROM user_watchlist WHERE user_id = ? ORDER BY sector, symbol",
                (uid,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_to_user_watchlist(self, user_id: str, symbol: str, sector: str | None = None) -> bool:
        """사용자별 관심종목 추가. 새로 추가되면 True, 이미 존재하면 False."""
        uid = str(user_id).strip()
        sym = symbol.upper().strip()
        if not sym or not uid:
            raise ValueError("user_id와 symbol은 필수입니다")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            result = conn.execute(
                "INSERT INTO user_watchlist(user_id, symbol, sector, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, symbol) DO UPDATE SET sector = excluded.sector",
                (uid, sym, sector, now),
            )
        return result.rowcount == 1

    def remove_from_user_watchlist(self, user_id: str, symbol: str) -> bool:
        """사용자별 관심종목 제거. 제거되면 True, 없었으면 False."""
        uid = str(user_id).strip()
        sym = symbol.upper().strip()
        with self.connect() as conn:
            result = conn.execute(
                "DELETE FROM user_watchlist WHERE user_id = ? AND symbol = ?",
                (uid, sym),
            )
        return result.rowcount == 1

    def all_users_in_watchlist(self) -> list[str]:
        """관심종목을 1개 이상 등록해 둔 고유 사용자 ID 목록 반환."""
        with self.connect() as conn:
            rows = conn.execute("SELECT DISTINCT user_id FROM user_watchlist").fetchall()
        return [str(row["user_id"]) for row in rows]

    def add_to_watchlist(self, symbol: str, sector: str | None = None) -> bool:
        """Add a symbol. Returns True if newly added, False if already present."""
        symbol = symbol.upper().strip()
        if not symbol:
            raise ValueError("symbol is required")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            result = conn.execute(
                "INSERT INTO watchlist(symbol, sector, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET sector = excluded.sector",
                (symbol, sector, now),
            )
        return result.rowcount == 1

    def remove_from_watchlist(self, symbol: str) -> bool:
        """Remove a symbol. Returns True if removed, False if it wasn't in the list."""
        symbol = symbol.upper().strip()
        with self.connect() as conn:
            result = conn.execute(
                "DELETE FROM watchlist WHERE symbol = ?",
                (symbol,),
            )
        return result.rowcount == 1

    # ── 유튜버 트래킹 ──────────────────────────────────────────────

    def add_youtuber(self, name: str, url: str, note: str = "") -> bool:
        """유튜버 등록. 이미 있으면 False 반환."""
        name = name.strip()
        url = url.strip()
        if not name or not url:
            raise ValueError("name과 url은 필수입니다")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            result = conn.execute(
                "INSERT OR IGNORE INTO youtubers(name, url, note, created_at) VALUES (?, ?, ?, ?)",
                (name, url, note.strip(), now),
            )
        return result.rowcount == 1

    def youtubers(self) -> list[dict]:
        """등록된 유튜버 목록 반환."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, url, channel_id, note, created_at FROM youtubers ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_youtuber_channel_id(self, name: str, channel_id: str) -> None:
        """유튜버의 YouTube channel_id를 저장."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE youtubers SET channel_id = ? WHERE name = ?",
                (channel_id, name.strip()),
            )

    def remove_youtuber(self, name: str) -> bool:
        """이름으로 유튜버 삭제. 성공하면 True."""
        with self.connect() as conn:
            result = conn.execute(
                "DELETE FROM youtubers WHERE name = ?",
                (name.strip(),),
            )
        return result.rowcount == 1

    # ── YouTube 스캔 로그 ──────────────────────────────────────────

    def is_video_processed(self, video_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM youtube_scan_log WHERE video_id = ?", (video_id,)
            ).fetchone()
        return row is not None

    def log_video(self, video_id: str, youtuber_name: str, title: str, tickers: list[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO youtube_scan_log(video_id, youtuber_name, title, tickers, scanned_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (video_id, youtuber_name, title, ",".join(tickers), now),
            )

    def recent_scan_logs(self, limit: int = 20) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM youtube_scan_log ORDER BY scanned_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


    def record_paper_trade(self, side: str, symbol: str, quantity: float, price: float) -> PaperTrade:
        side = side.lower().strip()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        symbol = symbol.upper().strip()
        if not symbol:
            raise ValueError("symbol is required")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if price <= 0:
            raise ValueError("price must be positive")

        created_at = datetime.now(timezone.utc)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO paper_trades(side, symbol, quantity, price, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (side, symbol, quantity, price, created_at.isoformat()),
            )
        return PaperTrade(side=side, symbol=symbol, quantity=quantity, price=price, created_at=created_at)

    def positions(self) -> list[PaperPosition]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT side, symbol, quantity, price FROM paper_trades ORDER BY id"
            ).fetchall()

        state: dict[str, dict[str, float]] = {}
        for row in rows:
            symbol = str(row["symbol"])
            bucket = state.setdefault(symbol, {"qty": 0.0, "cost": 0.0, "pnl": 0.0})
            quantity = float(row["quantity"])
            price = float(row["price"])
            if row["side"] == "buy":
                bucket["cost"] += quantity * price
                bucket["qty"] += quantity
                continue

            sell_qty = min(quantity, bucket["qty"])
            avg = bucket["cost"] / bucket["qty"] if bucket["qty"] else 0.0
            bucket["pnl"] += sell_qty * (price - avg)
            bucket["qty"] -= sell_qty
            bucket["cost"] -= sell_qty * avg

        positions: list[PaperPosition] = []
        for symbol, bucket in sorted(state.items()):
            qty = bucket["qty"]
            avg = bucket["cost"] / qty if qty else 0.0
            positions.append(
                PaperPosition(
                    symbol=symbol,
                    quantity=qty,
                    average_price=avg,
                    realized_pnl=bucket["pnl"],
                )
            )
        return positions
