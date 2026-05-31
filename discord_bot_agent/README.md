# Hermes Trading Discord Bot Agent

Standalone Discord bot for trading research, alerts, reports, and paper trading.
It never executes real trades.

## Run

```bash
python -m discord_bot_agent
```

After reinstalling the editable package, the console script is also available:

```bash
hermes-trading-discord
```

## Required Environment

```bash
DISCORD_BOT_TOKEN=...
DISCORD_GUILD_ID=...
DISCORD_ALERT_CHANNEL_ID=...
DISCORD_REPORT_CHANNEL_ID=...
```

If `DISCORD_ALERT_CHANNEL_ID` or `DISCORD_REPORT_CHANNEL_ID` is omitted, the
bot falls back to `DISCORD_HOME_CHANNEL`.

## Optional Environment

```bash
HERMES_TRADING_TIMEZONE=UTC
HERMES_TRADING_DAILY_REPORT_TIME=09:00
HERMES_TRADING_WEEKLY_REPORT_TIME=09:00
HERMES_TRADING_WEEKLY_REPORT_DAY=0
HERMES_TRADING_AGENT_DB=~/.hermes/trading_ai/discord_bot_agent.sqlite3
HERMES_TRADING_SYNC_GLOBAL_COMMANDS=false
```

`DISCORD_GUILD_ID` is recommended because guild command sync is immediate.
Global Discord command sync can take much longer.

## Slash Commands

```text
/hermes report daily
/hermes report weekly
/hermes watchlist
/hermes scan
/hermes stock NVDA
/hermes alert on
/hermes alert off
/hermes paper buy NVDA 10 950
/hermes paper sell NVDA 10 1050
```
