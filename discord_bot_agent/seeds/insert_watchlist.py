"""
discord_bot_agent/seeds/insert_watchlist.py
────────────────────────────────────────────
초기 관심종목(watchlist) 섹터별 데이터를 SQLite DB에 일괄 주입하는 시드 스크립트.

사용법:
    python -m discord_bot_agent.seeds.insert_watchlist
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

db_path = Path("/Users/nsh/.hermes/trading_ai/discord_bot_agent.sqlite3")

# 섹터별 종목 데이터 매핑
watchlist_data = [
    # ── 우주섹터 ──────────────────────────────────────────────────
    ("RKLB", "우주섹터"),
    ("PL", "우주섹터"),
    ("FLY", "우주섹터"),
    ("LUNR", "우주섹터"),
    ("ASTS", "우주섹터"),
    ("FTC", "우주섹터"),
    ("BKSY", "우주섹터"),
    ("VNP", "우주섹터"),
    ("VSAT", "우주섹터"),

    # ── 반도체 ───────────────────────────────────────────────────
    ("479860", "반도체"),  # SOL AI반도체TOP2플러스
    ("468350", "반도체"),  # PLUS 글로벌HBM반도체
    ("381180", "반도체"),  # TIGER 미국필라델피아반도체나스닥

    # ── 광통신 ───────────────────────────────────────────────────
    ("LITE", "광통신"),    # Lumentum Holdings
    ("COHR", "광통신"),    # Coherent Corp.
    ("MRVL", "광통신"),    # Marvell Technology
    ("483160", "광통신"),  # KODEX 미국AI전력핵심인프라

    # ── 네트워크 ──────────────────────────────────────────────────
    ("480110", "네트워크"),  # RISE 네트워크인프라

    # ── 우주 (ETF) ────────────────────────────────────────────────
    ("482520", "우주"),    # KODEX 미국우주항공 ETF

    # ── 전력 ──────────────────────────────────────────────────────
    ("479900", "전력"),    # HANARO 전력설비투자

    # ── 원자력 ────────────────────────────────────────────────────
    ("475270", "원자력"),  # ACE 원자력TOP10
]


def main() -> None:
    if not db_path.exists():
        print(f"에러: 데이터베이스 파일이 존재하지 않습니다: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # sector 컬럼 존재 여부 재확인 및 추가 (하위 호환 마이그레이션)
    try:
        cursor.execute("ALTER TABLE watchlist ADD COLUMN sector TEXT")
        print("watchlist 테이블에 sector 컬럼이 추가되었습니다.")
    except sqlite3.OperationalError:
        pass  # 이미 존재함

    now = datetime.now(timezone.utc).isoformat()
    inserted_count = 0
    updated_count = 0

    print("=== 관심종목 섹터별 일괄 추가 시작 ===")
    for symbol, sector in watchlist_data:
        symbol = symbol.upper().strip()
        cursor.execute("SELECT symbol, sector FROM watchlist WHERE symbol = ?", (symbol,))
        row = cursor.fetchone()

        if row is None:
            cursor.execute(
                "INSERT INTO watchlist (symbol, sector, created_at) VALUES (?, ?, ?)",
                (symbol, sector, now),
            )
            print(f"  [신규 추가] {symbol} → 섹터: {sector}")
            inserted_count += 1
        else:
            cursor.execute(
                "UPDATE watchlist SET sector = ? WHERE symbol = ?",
                (sector, symbol),
            )
            print(f"  [섹터 업데이트] {symbol} → {row[1]} 에서 {sector} 로 변경")
            updated_count += 1

    conn.commit()
    conn.close()
    print(f"\n완료: 신규 {inserted_count}개 추가 / 기존 {updated_count}개 업데이트 완료.")


if __name__ == "__main__":
    main()
