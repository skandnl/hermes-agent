#!/usr/bin/env python3
"""
discord_bot_agent/setup_cron.py
────────────────────────────────
Hermes 맥미니 초기 셋업 스크립트.

git pull 후 이 스크립트를 한 번 실행하면:
  1. ~/.hermes/scripts/ 에 cron 실행 스크립트를 복사
  2. hermes cron 에 일간/주간 잡이 없을 경우 자동 등록

사용법:
    cd /path/to/hermes-agent
    python discord_bot_agent/setup_cron.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# ── 경로 정의 ──────────────────────────────────────────────────────────────
REPO_ROOT    = Path(__file__).resolve().parent.parent
AGENT_DIR    = REPO_ROOT / "discord_bot_agent"
HERMES_HOME  = Path.home() / ".hermes"
SCRIPTS_DIR  = HERMES_HOME / "scripts"
JOBS_FILE    = HERMES_HOME / "cron" / "jobs.json"

# ── 배포할 스크립트 목록 (repo 내 소스 → ~/.hermes/scripts/ 대상) ──────────
SCRIPT_SOURCES = {
    "discord_daily_report.py":  REPO_ROOT / "discord_bot_agent" / "scripts" / "discord_daily_report.py",
    "discord_weekly_report.py": REPO_ROOT / "discord_bot_agent" / "scripts" / "discord_weekly_report.py",
}

# ── 등록할 cron 잡 정의 ────────────────────────────────────────────────────
CRON_JOBS = [
    {
        "name":     "Discord 일간 리포트 (KST 06:30)",
        "schedule": "30 21 * * *",
        "script":   "discord_daily_report.py",
    },
    {
        "name":     "Discord 주간 리포트 (월KST 06:30)",
        "schedule": "30 21 * * 0",
        "script":   "discord_weekly_report.py",
    },
]


def _hermes_cmd() -> list[str]:
    """현재 venv 의 hermes 실행 경로 반환."""
    venv = REPO_ROOT / ".venv" / "bin" / "hermes"
    if venv.exists():
        return [str(venv)]
    return ["hermes"]


def step1_copy_scripts() -> None:
    """cron 실행 스크립트를 ~/.hermes/scripts/ 에 복사."""
    print("\n[1/2] ~/.hermes/scripts/ 에 cron 스크립트 복사 중...")
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    for dest_name, src_path in SCRIPT_SOURCES.items():
        dest = SCRIPTS_DIR / dest_name
        if not src_path.exists():
            print(f"  ⚠️  소스 없음 (건너뜀): {src_path}")
            continue
        shutil.copy2(src_path, dest)
        print(f"  ✅  {src_path.name} → {dest}")


def step2_register_cron_jobs() -> None:
    """hermes cron 잡이 없으면 등록."""
    print("\n[2/2] Hermes cron 잡 확인 및 등록...")

    # 기존 잡 이름 목록 조회
    existing_names: set[str] = set()
    if JOBS_FILE.exists():
        try:
            data = json.loads(JOBS_FILE.read_text())
            existing_names = {j.get("name", "") for j in data.get("jobs", [])}
        except Exception as e:
            print(f"  ⚠️  jobs.json 읽기 실패 (무시하고 계속): {e}")

    hermes = _hermes_cmd()
    for job in CRON_JOBS:
        if job["name"] in existing_names:
            print(f"  ℹ️  이미 등록됨 (건너뜀): {job['name']}")
            continue

        cmd = [
            *hermes, "cron", "create",
            "--name",   job["name"],
            "--script", job["script"],
            "--no-agent",
            job["schedule"],
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if result.returncode == 0:
            print(f"  ✅  등록 완료: {job['name']}")
            print(f"      {result.stdout.strip()}")
        else:
            print(f"  ❌  등록 실패: {job['name']}")
            print(f"      {result.stderr.strip()}")


def main() -> None:
    print("=" * 60)
    print("  Hermes Discord Bot Agent — Cron 셋업")
    print(f"  repo: {REPO_ROOT}")
    print("=" * 60)

    step1_copy_scripts()
    step2_register_cron_jobs()

    print("\n✅ 셋업 완료!")
    print("   hermes cron list 로 등록된 잡을 확인하세요.\n")


if __name__ == "__main__":
    main()
