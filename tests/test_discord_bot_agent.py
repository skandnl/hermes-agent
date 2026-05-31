from datetime import datetime

from discord_bot_agent.config import DiscordBotAgentConfig
from discord_bot_agent.embeds import trade_alert_payload
from discord_bot_agent.models import AlertLevel, TradeSetup
from discord_bot_agent.reports import generate_daily_report, generate_weekly_report
from discord_bot_agent.store import TradingStore


def test_trade_alert_payload_contains_research_only_footer():
    setup = TradeSetup(
        symbol="NVDA",
        current_price=950,
        entry_low=920,
        entry_high=940,
        stop_loss=895,
        target_1=1020,
        target_2=1080,
        risk_reward=3.2,
        thesis="Sector strength and support retest.",
        caution="Use staged entry only.",
        level=AlertLevel.BUY_ZONE,
    )

    payload = trade_alert_payload(setup)

    assert payload["title"] == "Hermes Buy-Zone Alert"
    assert payload["color"] == 0x2ECC71
    assert "No real trades" in payload["footer"]
    assert ("Symbol", "NVDA", True) in payload["fields"]


def test_store_records_paper_trades_and_positions(tmp_path):
    store = TradingStore(tmp_path / "trading.sqlite3")

    store.record_paper_trade("buy", "nvda", 10, 950)
    store.record_paper_trade("sell", "NVDA", 4, 1000)

    positions = store.positions()
    nvda = next(position for position in positions if position.symbol == "NVDA")
    assert nvda.quantity == 6
    assert nvda.average_price == 950
    assert nvda.realized_pnl == 200


def test_reports_include_watchlist_and_paper_trading_context(tmp_path):
    store = TradingStore(tmp_path / "trading.sqlite3")
    store.record_paper_trade("buy", "AAPL", 2, 180)

    daily = generate_daily_report(store, datetime(2026, 5, 31))
    weekly = generate_weekly_report(store, datetime(2026, 5, 31))

    assert "Watchlist" in daily
    assert "research" in daily.lower()
    assert "AAPL" in weekly
    assert "No real trades" in weekly


def test_config_uses_home_channel_as_trading_channel_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123")
    monkeypatch.setenv("DISCORD_HOME_CHANNEL", "456")
    monkeypatch.setenv("HERMES_TRADING_AGENT_DB", str(tmp_path / "agent.sqlite3"))

    config = DiscordBotAgentConfig.from_env()

    assert config.guild_id == 123
    assert config.alert_channel_id == 456
    assert config.report_channel_id == 456


def test_youtube_tracker_ticker_extraction():
    from discord_bot_agent.youtube_tracker import extract_tickers

    # 한국어 매핑 테스트
    assert "NVDA" in extract_tickers("오늘 엔비디아 주가 폭등")
    assert "000660" in extract_tickers("sk하이닉스 실적 대박")

    # 미국 티커 대문자 패턴 및 $ 패턴 테스트
    assert "PLTR" in extract_tickers("Palantir Technologies $PLTR to the moon")
    assert "TSLA" in extract_tickers("TSLA Q3 earnings discussion")

    # 등록되지 않은 임의의 대문자는 오탐 방지를 위해 무시되어야 함
    assert "RANDOM" not in extract_tickers("This is RANDOM text without a dollar sign")


def test_store_handles_youtubers_and_video_logs(tmp_path):
    store = TradingStore(tmp_path / "trading.sqlite3")

    # 유튜버 CRUD
    assert store.add_youtuber("테스트유튜버", "https://youtube.com/@test", "메모") is True
    assert store.add_youtuber("테스트유튜버", "https://youtube.com/@test", "중복") is False

    yts = store.youtubers()
    assert len(yts) == 1
    assert yts[0]["name"] == "테스트유튜버"
    assert yts[0]["url"] == "https://youtube.com/@test"
    assert yts[0]["note"] == "메모"

    # 채널 ID 업데이트
    store.update_youtuber_channel_id("테스트유튜버", "UC_TEST12345")
    yts = store.youtubers()
    assert yts[0]["channel_id"] == "UC_TEST12345"

    # 비디오 로그 및 중복 방지
    assert store.is_video_processed("vid_1") is False
    store.log_video("vid_1", "테스트유튜버", "영상 제목", ["NVDA", "AAPL"])
    assert store.is_video_processed("vid_1") is True

    # 최근 스캔 로그 확인
    logs = store.recent_scan_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["video_id"] == "vid_1"
    assert logs[0]["youtuber_name"] == "테스트유튜버"
    assert logs[0]["title"] == "영상 제목"
    assert logs[0]["tickers"] == "NVDA,AAPL"

    # 유튜버 삭제
    assert store.remove_youtuber("테스트유튜버") is True
    assert store.remove_youtuber("테스트유튜버") is False
    assert len(store.youtubers()) == 0
