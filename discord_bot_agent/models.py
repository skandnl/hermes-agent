from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AlertLevel(str, Enum):
    BUY_ZONE = "buy_zone"
    WATCH = "watch"
    RISK = "risk"
    REPORT = "report"


@dataclass(frozen=True)
class TradeSetup:
    symbol: str
    current_price: float | None
    entry_low: float | None
    entry_high: float | None
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    risk_reward: float | None
    thesis: str
    caution: str
    level: AlertLevel = AlertLevel.WATCH


@dataclass(frozen=True)
class PaperTrade:
    side: str
    symbol: str
    quantity: float
    price: float
    created_at: datetime


@dataclass(frozen=True)
class PaperPosition:
    symbol: str
    quantity: float
    average_price: float
    realized_pnl: float
