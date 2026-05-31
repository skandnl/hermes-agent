from __future__ import annotations

from datetime import datetime

from .models import AlertLevel, TradeSetup
from .store import TradingStore


def is_korean_symbol(symbol: str) -> bool:
    sym = symbol.upper().strip()
    if sym.isdigit() and len(sym) == 6:
        return True
    if sym.endswith(".KS") or sym.endswith(".KQ"):
        return True
    return False


def generate_daily_report(
    store: TradingStore, now: datetime | None = None, is_kr: bool | None = None
) -> str:
    now = now or datetime.now()
    all_symbols = store.watchlist()
    if is_kr is True:
        symbols_list = [s for s in all_symbols if is_korean_symbol(s)]
        title = "Hermes Daily Trading Research (국내 주식) 📅"
    elif is_kr is False:
        symbols_list = [s for s in all_symbols if not is_korean_symbol(s)]
        title = "Hermes Daily Trading Research (해외 주식) 📅"
    else:
        symbols_list = all_symbols
        title = "Hermes Daily Trading Research 📅"

    symbols = ", ".join(symbols_list) if symbols_list else "등록된 종목 없음"
    alerts = "on" if store.alerts_enabled() else "off"
    return (
        f"{title} - {now:%Y-%m-%d}\n\n"
        f"Watchlist: {symbols}\n"
        f"Alerts: {alerts}\n\n"
        "Focus:\n"
        "- Prefer planned entries near support or predefined buy zones.\n"
        "- Avoid chase buys after extended moves.\n"
        "- Treat all output as research and paper-trading context only."
    )


def generate_weekly_report(
    store: TradingStore, now: datetime | None = None, is_kr: bool | None = None
) -> str:
    now = now or datetime.now()
    all_positions = store.positions()
    if is_kr is True:
        positions = [p for p in all_positions if is_korean_symbol(p.symbol)]
        title = "Hermes Weekly Trading Research (국내 주식) 📊"
    elif is_kr is False:
        positions = [p for p in all_positions if not is_korean_symbol(p.symbol)]
        title = "Hermes Weekly Trading Research (해외 주식) 📊"
    else:
        positions = all_positions
        title = "Hermes Weekly Trading Research 📊"

    if positions:
        position_lines = [
            f"- {p.symbol}: qty {p.quantity:g}, avg {p.average_price:.2f}, realized PnL {p.realized_pnl:.2f}"
            for p in positions
        ]
    else:
        position_lines = ["- No paper positions recorded."]

    return (
        f"{title} - week of {now:%Y-%m-%d}\n\n"
        "Paper portfolio:\n"
        + "\n".join(position_lines)
        + "\n\nRisk rules:\n"
        "- No real trades are executed by this bot.\n"
        "- Size entries before the alert, not after price expansion.\n"
        "- If price is above the planned zone, wait for a reset."
    )


def fetch_eod_data(symbol: str) -> dict | None:
    """yfinance를 활용하여 종목의 최근 20영업일 종가, 지지선, 저항선, 변동성을 계산해 반환."""
    import yfinance as yf
    clean = symbol.upper().strip()
    
    # 한국 주식/국내 ETF의 경우 .KS 접미사 보정
    ticker_sym = clean
    if clean.isdigit() and len(clean) == 6:
        ticker_sym = f"{clean}.KS"

    try:
        ticker = yf.Ticker(ticker_sym)
        # 최근 30일 데이터를 가져와서 실 20영업일 데이터 확보
        hist = ticker.history(period="1mo")
        if hist.empty or len(hist) < 5:
            return None
        
        # 최근 20영업일 슬라이싱
        df = hist.tail(20)
        
        current_price = float(df["Close"].iloc[-1])
        support = float(df["Low"].min())       # 최근 20일 최저가 (지지선)
        resistance = float(df["High"].max())    # 최근 20일 최고가 (저항선, 1차 익절목표)
        
        # 일평균 변동폭 (고가 - 저가) 으로 ATR 대용 변동성 계산
        daily_ranges = df["High"] - df["Low"]
        volatility = float(daily_ranges.mean())
        
        return {
            "current_price": current_price,
            "support": support,
            "resistance": resistance,
            "volatility": volatility
        }
    except Exception:
        # 야후 파이낸스 장애 또는 비상장 주식 시 None 반환 (예외 안전장치)
        return None


def build_stock_scenario(symbol: str) -> TradeSetup:
    clean = symbol.upper().strip()
    data = fetch_eod_data(clean)
    
    if not data:
        # 데이터가 없을 때의 Fallback 템플릿
        return TradeSetup(
            symbol=clean,
            current_price=None,
            entry_low=None,
            entry_high=None,
            stop_loss=None,
            target_1=None,
            target_2=None,
            risk_reward=None,
            thesis="데이터를 불러올 수 없습니다. 비상장 주식이거나 야후 파이낸스 티커 확인이 필요합니다.",
            caution="관찰 필요. 수동으로 타점과 손익비를 계산해보세요.",
            level=AlertLevel.WATCH
        )
    
    current = data["current_price"]
    support = data["support"]
    resistance = data["resistance"]
    vol = data["volatility"]
    
    # 지지선 기준 2% 위 영역을 진입 상단으로 잡음
    entry_low = support
    entry_high = support * 1.02
    
    # 손절가 = 지지선 - 1.5 * vol (변동성을 고려한 합리적 지점)
    stop_loss = support - (1.5 * vol)
    if stop_loss >= support:
        stop_loss = support * 0.95  # 최소 5% 버퍼 확보
        
    # 목표가
    target_1 = resistance
    target_2 = resistance * 1.05
    
    # 손익비 연산
    risk = entry_high - stop_loss
    reward = target_1 - entry_high
    risk_reward = round(reward / risk, 2) if risk > 0 else 1.0
    
    # 현재가가 진입구간에 위치해 있는지 판별
    if current <= entry_high and current >= stop_loss:
        level = AlertLevel.BUY_ZONE
        thesis = f"🟢 **타점 도달!** 현재가({current:,.2f})가 20일 swing 최저점 지지선({support:,.2f}) 대비 2% 이내 진입 타점 구간({entry_low:,.2f} ~ {entry_high:,.2f})에 완벽히 머물고 있습니다."
        caution = f"적극 진입 추천 구간입니다. 손절선({stop_loss:,.2f})을 이탈하면 정직하게 손절 탈출하시기 바랍니다."
    else:
        level = AlertLevel.WATCH
        thesis = f"🟡 **관망 상태.** 최근 종가({current:,.2f})가 진입 구간({entry_low:,.2f} ~ {entry_high:,.2f}) 위에 머물고 있습니다. 지지선 근처까지 되돌림(눌림목)을 차분히 기다리세요."
        caution = f"추격 매수는 손익비를 크게 훼손시킵니다. 목표 돌파가 아닐 시 대기하십시오."
        
    return TradeSetup(
        symbol=clean,
        current_price=current,
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        risk_reward=risk_reward,
        thesis=thesis,
        caution=caution,
        level=level
    )


def scan_watchlist(store: TradingStore) -> list[TradeSetup]:
    setups: list[TradeSetup] = []
    for symbol in store.watchlist():
        setup = build_stock_scenario(symbol)
        setups.append(setup)
    return setups
