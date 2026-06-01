"""
discord_bot_agent/seeds/insert_defense.py
──────────────────────────────────────────
방산섹터 (국내/해외) 종목을 SQLite DB에 일괄 주입하는 시드 스크립트.

사용법:
    python -m discord_bot_agent.seeds.insert_defense
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

db_path = Path("/Users/nsh/.hermes/trading_ai/discord_bot_agent.sqlite3")

# 방산섹터 국내 및 해외 종목 매핑
defense_data = [
    # ── 방산 (해외) ───────────────────────────────────────────────
    ("LMT", "방산(해외)"),   # 록히드 마틴
    ("RTX", "방산(해외)"),   # RTX (레이시온)
    ("NOC", "방산(해외)"),   # 노스롭 그루만
    ("GD", "방산(해외)"),    # 제너럴 다이내믹스
    ("LHX", "방산(해외)"),   # 엘쓰리해리스
    ("BA", "방산(해외)"),    # 보잉

    # ── 방산 (국내) ───────────────────────────────────────────────
    ("047810", "방산(국내)"),  # 한국항공우주 (KAI)
    ("012450", "방산(국내)"),  # 한화에어로스페이스
    ("079550", "방산(국내)"),  # LIG넥스원
    ("009830", "방산(국내)"),  # 한화시스템
    ("064350", "방산(국내)"),  # 현대로템
]


def main() -> None:
    if not db_path.exists():
        print(f"에러: 데이터베이스 파일이 존재하지 않습니다: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    now = datetime.now(timezone.utc).isoformat()
    inserted_count = 0
    updated_count = 0

    print("=== 방산섹터 (국내/해외) 일괄 추가 시작 ===")
    for symbol, sector in defense_data:
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
    print(f"\n완료: 방산 신규 {inserted_count}개 추가 / 기존 {updated_count}개 업데이트 완료.")


if __name__ == "__main__":
    main()
