from __future__ import annotations

from typing import Any

from .models import AlertLevel, TradeSetup


LEVEL_COLORS = {
    AlertLevel.BUY_ZONE: 0x2ECC71,
    AlertLevel.WATCH: 0xF1C40F,
    AlertLevel.RISK: 0xE74C3C,
    AlertLevel.REPORT: 0x3498DB,
}


def _money(value: float | None) -> str:
    return "N/A" if value is None else f"{value:,.2f}"


def trade_alert_payload(setup: TradeSetup) -> dict[str, Any]:
    return {
        "title": "Hermes Buy-Zone Alert" if setup.level == AlertLevel.BUY_ZONE else "Hermes Trading Setup",
        "color": LEVEL_COLORS[setup.level],
        "fields": [
            ("Symbol", setup.symbol, True),
            ("Current", _money(setup.current_price), True),
            ("Entry Zone", f"{_money(setup.entry_low)} - {_money(setup.entry_high)}", True),
            ("Stop", _money(setup.stop_loss), True),
            ("Target 1", _money(setup.target_1), True),
            ("Target 2", _money(setup.target_2), True),
            ("R/R", "N/A" if setup.risk_reward is None else f"{setup.risk_reward:.2f}", True),
            ("Thesis", setup.thesis, False),
            ("Caution", setup.caution, False),
        ],
        "footer": "Research and paper trading only. No real trades are executed.",
    }


def report_payload(title: str, body: str) -> dict[str, Any]:
    return {
        "title": title,
        "description": body[:4096],
        "color": LEVEL_COLORS[AlertLevel.REPORT],
        "footer": "Hermes Trading AI - research only",
    }


def payload_to_embed(payload: dict[str, Any]):
    import discord

    embed = discord.Embed(
        title=payload.get("title", "Hermes Trading AI"),
        description=payload.get("description"),
        color=payload.get("color", 0x3498DB),
    )
    for name, value, inline in payload.get("fields", []):
        embed.add_field(name=name, value=str(value)[:1024], inline=bool(inline))
    footer = payload.get("footer")
    if footer:
        embed.set_footer(text=footer)
    return embed
