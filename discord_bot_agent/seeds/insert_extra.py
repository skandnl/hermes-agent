"""
discord_bot_agent/seeds/insert_extra.py
────────────────────────────────────────
추가 요청 국내 주식 ETF 종목을 SQLite DB에 일괄 주입하는 시드 스크립트.

사용법:
    python -m discord_bot_agent.seeds.insert_extra
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

db_path = Path("/Users/nsh/.hermes/trading_ai/discord_bot_agent.sqlite3")

# 추가 요청된 국내 주식 ETF 종목 매핑
extra_data = [
    ("483160", "전력"),   # 코덱스 AI 핵심전력설비 (KODEX AI전력핵심인프라)
    ("466920", "조선"),   # SOL TOP3 조선 (SOL 조선TOP3플러스)
    ("475370", "고배당"), # Rise 고배당 10tr (RISE 고배당주선별10TR)
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

    print("=== 추가 요청 국내 ETF 일괄 주입 시작 ===")
    for symbol, sector in extra_data:
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
    print(f"\n완료: 추가 신규 {inserted_count}개 추가 / 기존 {updated_count}개 업데이트 완료.")


if __name__ == "__main__":
    main()
