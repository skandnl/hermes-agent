#!/usr/bin/env python3
"""
discord_bot_agent/scripts/discord_daily_report.py
──────────────────────────────────────────────────
Hermes cron no_agent 스크립트: 일간 리포트 + YouTube 스캔 (KST 06:30 실행)

이 파일은 setup_cron.py 에 의해 ~/.hermes/scripts/ 에 복사됩니다.
직접 편집하지 말고 이 소스 파일을 수정 후 setup_cron.py 를 재실행하세요.
"""
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent  # hermes-agent 루트

result = subprocess.run(
    [sys.executable, "-m", "discord_bot_agent", "--daily"],
    cwd=str(PROJECT),
    capture_output=True,
    text=True,
)

if result.returncode != 0:
    print(f"[ERROR] discord daily report failed (exit {result.returncode})")
    print(result.stderr[-2000:] if result.stderr else "(no stderr)")
    sys.exit(result.returncode)

print("[OK] discord daily report + youtube scan completed")
if result.stdout:
    print(result.stdout[-1000:])
