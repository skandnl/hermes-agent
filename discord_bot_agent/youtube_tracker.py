"""
YouTube RSS 기반 종목 발굴 트래커
- API 키 없이 YouTube RSS 피드로 신규 영상 감지
- 영상 제목/설명에서 종목 코드 추출
"""
from __future__ import annotations

import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import TradingStore

logger = logging.getLogger(__name__)

# ── 한국어 종목명 → 티커 매핑 ─────────────────────────────────────
KR_TICKER_MAP: dict[str, str] = {
    # 미국 빅테크
    "엔비디아": "NVDA", "nvidia": "NVDA",
    "테슬라": "TSLA", "tesla": "TSLA",
    "애플": "AAPL", "apple": "AAPL",
    "마이크로소프트": "MSFT", "microsoft": "MSFT",
    "구글": "GOOGL", "알파벳": "GOOGL", "google": "GOOGL",
    "아마존": "AMZN", "amazon": "AMZN",
    "메타": "META", "meta": "META",
    "넷플릭스": "NFLX", "netflix": "NFLX",
    "브로드컴": "AVGO", "broadcom": "AVGO",
    "AMD": "AMD", "어드밴스드마이크로": "AMD",
    "인텔": "INTC", "intel": "INTC",
    "퀄컴": "QCOM", "qualcomm": "QCOM",
    "ARM": "ARM",
    "팔란티어": "PLTR", "palantir": "PLTR",
    "코인베이스": "COIN", "coinbase": "COIN",
    "마이크론": "MU", "micron": "MU",
    "어플라이드머티리얼즈": "AMAT",
    "ASML": "ASML",
    # ETF
    "QQQ": "QQQ", "SPY": "SPY", "SOXL": "SOXL", "TQQQ": "TQQQ",
    "SQQQ": "SQQQ", "FNGU": "FNGU",
    # 한국 종목
    "삼성전자": "005930",
    "SK하이닉스": "000660", "하이닉스": "000660",
    "카카오": "035720",
    "네이버": "035420", "NAVER": "035420",
    "현대차": "005380", "현대자동차": "005380",
    "기아": "000270", "기아차": "000270",
    "LG에너지솔루션": "373220",
    "셀트리온": "068270",
    "삼성바이오": "207940",
    "포스코": "005490", "POSCO": "005490",
    "KB금융": "105560",
    "신한지주": "055550",
    "하나금융": "086790",
    "크래프톤": "259960",
}

# 공지된 미국 주요 티커 허용 목록 (오탐 방지)
KNOWN_US_TICKERS: set[str] = {
    "NVDA", "TSLA", "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META",
    "NFLX", "AVGO", "AMD", "INTC", "QCOM", "ARM", "PLTR", "COIN",
    "MU", "AMAT", "ASML", "TSM", "SMCI", "MSTR", "HOOD", "RBLX",
    "UBER", "LYFT", "SNAP", "PINS", "SPOT", "SQ", "PYPL", "SHOP",
    "CRM", "NOW", "SNOW", "DDOG", "ZS", "CRWD", "S", "PANW",
    "QQQ", "SPY", "SOXL", "TQQQ", "SQQQ", "FNGU", "UPRO", "LABU",
    "GLD", "SLV", "TLT", "HYG", "XLK", "XLF", "XLE", "XBI",
    "BABA", "JD", "PDD", "BIDU", "NIO", "LI", "XPEV",
    "JPM", "GS", "BAC", "MS", "C", "WFC",
    "BRK", "V", "MA", "AXP",
    "UNH", "LLY", "JNJ", "PFE", "ABBV", "MRK",
    "XOM", "CVX", "COP",
    "BA", "LMT", "RTX", "NOC",
    "DIS", "CMCSA", "PARA",
    "BTC", "ETH",  # 암호화폐도 포함
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

RSS_NS = "http://www.w3.org/2005/Atom"


@dataclass
class VideoResult:
    video_id: str
    youtuber_name: str
    title: str
    url: str
    published: datetime
    tickers: list[str]


def resolve_channel_id(youtube_url: str) -> str | None:
    """
    YouTube @handle URL에서 channel_id(UCxxxx) 추출.
    HTML에서 직접 파싱하므로 API 키 불필요.
    """
    url = youtube_url.rstrip("/")
    if not url.startswith("http"):
        url = "https://www.youtube.com/" + url.lstrip("/")

    # 한글(비아스키) 경로 문자 처리를 위해 인코딩
    parsed = urllib.parse.urlparse(url)
    encoded_path = urllib.parse.quote(parsed.path)
    url = urllib.parse.urlunparse(parsed._replace(path=encoded_path))

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")

        # 방법 1: "channelId":"UCxxxx"
        m = re.search(r'"channelId"\s*:\s*"(UC[A-Za-z0-9_\-]{22})"', html)
        if m:
            return m.group(1)

        # 방법 2: /channel/UCxxxx
        m = re.search(r'/channel/(UC[A-Za-z0-9_\-]{22})', html)
        if m:
            return m.group(1)

        # 방법 3: externalId
        m = re.search(r'"externalId"\s*:\s*"(UC[A-Za-z0-9_\-]{22})"', html)
        if m:
            return m.group(1)

    except Exception as e:
        logger.warning("채널 ID 조회 실패 (%s): %s", youtube_url, e)

    return None


def fetch_rss_videos(channel_id: str, since_hours: int = 48) -> list[dict]:
    """
    YouTube RSS 피드에서 최근 영상 목록 반환.
    """
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        req = urllib.request.Request(rss_url, headers=_HEADERS)
        xml_data = urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        logger.warning("RSS 수신 실패 (channel_id=%s): %s", channel_id, e)
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        logger.warning("RSS XML 파싱 실패: %s", e)
        return []

    ns = {"atom": RSS_NS, "yt": "http://www.youtube.com/xml/schemas/2015"}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    videos = []

    for entry in root.findall("atom:entry", ns):
        video_id_el = entry.find("yt:videoId", ns)
        title_el = entry.find("atom:title", ns)
        published_el = entry.find("atom:published", ns)
        link_el = entry.find("atom:link", ns)

        if video_id_el is None or title_el is None or published_el is None:
            continue

        try:
            pub_str = published_el.text or ""
            # ISO 8601 파싱
            pub_str = pub_str.replace("Z", "+00:00")
            published = datetime.fromisoformat(pub_str)
        except Exception:
            continue

        if published < cutoff:
            continue

        videos.append({
            "video_id": video_id_el.text or "",
            "title": title_el.text or "",
            "published": published,
            "url": link_el.get("href", "") if link_el is not None else
                   f"https://www.youtube.com/watch?v={video_id_el.text}",
        })

    return videos


def extract_tickers(text: str) -> list[str]:
    """
    텍스트에서 종목 코드 추출.
    """
    found: set[str] = set()

    # 1. $TICKER 패턴
    for m in re.finditer(r'\$([A-Z]{1,5})', text):
        t = m.group(1)
        if t in KNOWN_US_TICKERS:
            found.add(t)

    # 2. 대문자 2~5글자 (허용 목록 기준)
    for m in re.finditer(r'\b([A-Z]{2,5})\b', text):
        t = m.group(1)
        if t in KNOWN_US_TICKERS:
            found.add(t)

    # 3. 한국 6자리 숫자 코드
    for m in re.finditer(r'\b(\d{6})\b', text):
        found.add(m.group(1))

    # 4. 한국어 종목명 → 티커 변환
    text_lower = text.lower()
    for kor_name, ticker in KR_TICKER_MAP.items():
        if kor_name.lower() in text_lower:
            found.add(ticker)

    return sorted(found)


def scan_youtubers(store: "TradingStore", since_hours: int = 48) -> list[VideoResult]:
    """
    등록된 유튜버 전체를 스캔해 신규 영상의 종목을 추출.
    이미 처리한 영상은 건너뜀.
    """
    results: list[VideoResult] = []

    for yt in store.youtubers():
        name = yt["name"]
        url = yt["url"]
        channel_id = yt.get("channel_id")

        # channel_id 없으면 URL에서 해석
        if not channel_id:
            logger.info("[YouTube] %s 채널 ID 조회 중...", name)
            channel_id = resolve_channel_id(url)
            if channel_id:
                store.update_youtuber_channel_id(name, channel_id)
                logger.info("[YouTube] %s → channel_id=%s", name, channel_id)
            else:
                logger.warning("[YouTube] %s 채널 ID 해석 실패, 건너뜀", name)
                continue

        videos = fetch_rss_videos(channel_id, since_hours=since_hours)
        logger.info("[YouTube] %s: 최근 %dh 내 영상 %d개", name, since_hours, len(videos))

        for v in videos:
            if store.is_video_processed(v["video_id"]):
                continue

            tickers = extract_tickers(v["title"])
            store.log_video(v["video_id"], name, v["title"], tickers)

            results.append(VideoResult(
                video_id=v["video_id"],
                youtuber_name=name,
                title=v["title"],
                url=v["url"],
                published=v["published"],
                tickers=tickers,
            ))

    return results
