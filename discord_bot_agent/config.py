from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from hermes_constants import get_hermes_home


def _env_int(name: str, *fallback_names: str) -> int | None:
    raw = os.getenv(name, "").strip()
    for fallback_name in fallback_names:
        if raw:
            break
        raw = os.getenv(fallback_name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer Discord snowflake") from exc


def _env_time(name: str, default: str) -> time:
    raw = os.getenv(name, default).strip()
    try:
        hour_s, minute_s = raw.split(":", 1)
        return time(hour=int(hour_s), minute=int(minute_s))
    except Exception as exc:
        raise ValueError(f"{name} must use HH:MM 24-hour format") from exc


@dataclass(frozen=True)
class DiscordBotAgentConfig:
    token: str
    guild_id: int | None
    alert_channel_id: int
    report_channel_id: int
    # 채널별 세부 라우팅 (국내/해외 이원화)
    us_watchlist_channel_id: int | None
    kr_watchlist_channel_id: int | None
    us_signal_channel_id: int | None
    kr_signal_channel_id: int | None
    us_daily_report_channel_id: int | None
    kr_daily_report_channel_id: int | None
    us_weekly_report_channel_id: int | None
    kr_weekly_report_channel_id: int | None
    us_paper_channel_id: int | None
    kr_paper_channel_id: int | None
    us_scenario_channel_id: int | None
    kr_scenario_channel_id: int | None
    discovery_channel_id: int | None
    timezone: ZoneInfo
    daily_report_time: time
    weekly_report_time: time
    weekly_report_day: int
    database_path: Path
    sync_global_commands: bool


    @classmethod
    def from_env(cls) -> "DiscordBotAgentConfig":
        token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("DISCORD_BOT_TOKEN is required")

        alert_channel_id = _env_int("DISCORD_ALERT_CHANNEL_ID", "DISCORD_HOME_CHANNEL")
        report_channel_id = _env_int("DISCORD_REPORT_CHANNEL_ID", "DISCORD_HOME_CHANNEL")
        if alert_channel_id is None:
            raise ValueError("DISCORD_ALERT_CHANNEL_ID is required")
        if report_channel_id is None:
            raise ValueError("DISCORD_REPORT_CHANNEL_ID is required")

        tz_name = os.getenv("HERMES_TRADING_TIMEZONE") or os.getenv("TZ") or "UTC"
        db_path = os.getenv("HERMES_TRADING_AGENT_DB", "").strip()
        database_path = Path(db_path).expanduser() if db_path else get_hermes_home() / "trading_ai" / "discord_bot_agent.sqlite3"

        day_raw = os.getenv("HERMES_TRADING_WEEKLY_REPORT_DAY", "0").strip()
        try:
            weekly_day = int(day_raw)
        except ValueError as exc:
            raise ValueError("HERMES_TRADING_WEEKLY_REPORT_DAY must be 0-6, where 0 is Monday") from exc
        if weekly_day < 0 or weekly_day > 6:
            raise ValueError("HERMES_TRADING_WEEKLY_REPORT_DAY must be 0-6, where 0 is Monday")

        return cls(
            token=token,
            guild_id=_env_int("DISCORD_GUILD_ID"),
            alert_channel_id=alert_channel_id,
            report_channel_id=report_channel_id,
            us_watchlist_channel_id=_env_int("DISCORD_US_WATCHLIST_CHANNEL_ID", "DISCORD_WATCHLIST_CHANNEL_ID"),
            kr_watchlist_channel_id=_env_int("DISCORD_KR_WATCHLIST_CHANNEL_ID", "DISCORD_WATCHLIST_CHANNEL_ID"),
            us_signal_channel_id=_env_int("DISCORD_US_SIGNAL_CHANNEL_ID", "DISCORD_SIGNAL_CHANNEL_ID"),
            kr_signal_channel_id=_env_int("DISCORD_KR_SIGNAL_CHANNEL_ID", "DISCORD_SIGNAL_CHANNEL_ID"),
            us_daily_report_channel_id=_env_int("DISCORD_US_DAILY_REPORT_CHANNEL_ID", "DISCORD_DAILY_REPORT_CHANNEL_ID"),
            kr_daily_report_channel_id=_env_int("DISCORD_KR_DAILY_REPORT_CHANNEL_ID", "DISCORD_DAILY_REPORT_CHANNEL_ID"),
            us_weekly_report_channel_id=_env_int("DISCORD_US_WEEKLY_REPORT_CHANNEL_ID", "DISCORD_WEEKLY_REPORT_CHANNEL_ID"),
            kr_weekly_report_channel_id=_env_int("DISCORD_KR_WEEKLY_REPORT_CHANNEL_ID", "DISCORD_WEEKLY_REPORT_CHANNEL_ID"),
            us_paper_channel_id=_env_int("DISCORD_US_PAPER_CHANNEL_ID", "DISCORD_PAPER_CHANNEL_ID"),
            kr_paper_channel_id=_env_int("DISCORD_KR_PAPER_CHANNEL_ID", "DISCORD_PAPER_CHANNEL_ID"),
            us_scenario_channel_id=_env_int("DISCORD_US_SCENARIO_CHANNEL_ID", "DISCORD_SCENARIO_CHANNEL_ID"),
            kr_scenario_channel_id=_env_int("DISCORD_KR_SCENARIO_CHANNEL_ID", "DISCORD_SCENARIO_CHANNEL_ID"),
            discovery_channel_id=_env_int("DISCORD_DISCOVERY_CHANNEL_ID"),
            timezone=ZoneInfo(tz_name),
            daily_report_time=_env_time("HERMES_TRADING_DAILY_REPORT_TIME", "09:00"),
            weekly_report_time=_env_time("HERMES_TRADING_WEEKLY_REPORT_TIME", "09:00"),
            weekly_report_day=weekly_day,
            database_path=database_path,
            sync_global_commands=os.getenv("HERMES_TRADING_SYNC_GLOBAL_COMMANDS", "").lower() in {"1", "true", "yes", "on"},
        )

