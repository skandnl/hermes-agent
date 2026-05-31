"""
Discord 서버 채널 재구축 스크립트
실행: python -m discord_bot_agent.setup_channels
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, ".")


async def setup_channels():
    try:
        from hermes_cli.env_loader import load_hermes_dotenv
        load_hermes_dotenv()
    except Exception:
        pass

    import discord

    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    guild_id = int(os.environ.get("DISCORD_GUILD_ID", "0"))
    if not token or not guild_id:
        print("ERROR: DISCORD_BOT_TOKEN / DISCORD_GUILD_ID 필요", file=sys.stderr)
        sys.exit(1)

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    result: dict[str, int] = {}

    @client.event
    async def on_ready():
        guild = client.get_guild(guild_id)
        if guild is None:
            print("ERROR: guild를 찾을 수 없습니다", file=sys.stderr)
            await client.close()
            return

        # 봇 권한 오브젝트
        bot_member = guild.me
        everyone = guild.default_role

        # ── 기존 #일반 채널 이름 변경 ──────────────────────────────
        for ch in guild.text_channels:
            if ch.name == "일반" and ch.category and ch.category.name == "채팅 채널":
                await ch.edit(name="리서치-홈", topic="@남대리 자유대화 — 무엇이든 물어보세요")
                result["리서치_홈"] = ch.id
                print(f"  ✎ 기존 #일반 → #리서치-홈  (id={ch.id})")
                break

        # ── 카테고리 + 채널 정의 ────────────────────────────────────
        # (카테고리명, [(채널명, 토픽, 봇전용쓰기)])
        STRUCTURE = [
            ("📺 종목 발굴 & 설정", [
                ("리서치-홈",     "이미 있음 — skip",                          False),
                ("종목-발굴",     "유튜버 언급 종목 메모 + 스캔 결과",           False),
                ("유튜버-트래킹", "관심 유튜버 목록 관리 (/hermes youtuber)",    False),
                ("봇-명령어",     "슬래시 커맨드 전용 채널",                    False),
            ]),
            ("🌐 해외 주식 AI 비서", [
                ("해외-watchlist",    "해외 관심종목 변경 자동 알림",             True),
                ("해외-시나리오",     "/hermes stock, /hermes scan 결과",          True),
                ("해외-진입-시그널",   "해외 진입 시그널 알림 — 봇 전용",          True),
                ("해외-일간리포트",   "해외 매일 09:00 자동 발송",                 True),
                ("해외-주간리포트",   "해외 매주 월요일 09:00 자동 발송",          True),
                ("해외-paper-trades", "해외 /hermes paper buy/sell 기록",      True),
                ("해외-포트폴리오",   "해외 페이퍼 포지션 현황",                  True),
            ]),
            ("🇰🇷 국내 주식 AI 비서", [
                ("국내-watchlist",    "국내 관심종목 변경 자동 알림",             True),
                ("국내-시나리오",     "/hermes stock, /hermes scan 결과",          True),
                ("국내-진입-시그널",   "국내 진입 시그널 알림 — 봇 전용",          True),
                ("국내-일간리포트",   "국내 매일 09:00 자동 발송",                 True),
                ("국내-주간리포트",   "국내 매주 월요일 09:00 자동 발송",          True),
                ("국내-paper-trades", "국내 /hermes paper buy/sell 기록",      True),
                ("국내-포트폴리오",   "국내 페이퍼 포지션 현황",                  True),
            ]),
        ]

        # 기존 카테고리 맵
        existing_cats = {c.name: c for c in guild.categories}
        existing_text = {c.name: c for c in guild.text_channels}

        for cat_name, channels in STRUCTURE:
            # 카테고리 생성 또는 재사용
            if cat_name in existing_cats:
                cat = existing_cats[cat_name]
                print(f"\n[카테고리] {cat_name} — 이미 존재")
            else:
                cat = await guild.create_category(cat_name)
                print(f"\n[카테고리] {cat_name} — 생성 (id={cat.id})")

            for ch_name, topic, bot_only in channels:
                # 리서치-홈은 이미 위에서 처리
                if ch_name == "리서치-홈":
                    if "리서치_홈" not in result:
                        for ch in guild.text_channels:
                            if ch.name == "리서치-홈":
                                await ch.edit(category=cat)
                                result["리서치_홈"] = ch.id
                    continue

                if ch_name in existing_text:
                    ch = existing_text[ch_name]
                    print(f"  ✓ #{ch_name} — 이미 존재 (id={ch.id})")
                else:
                    overwrites = {}
                    if bot_only:
                        overwrites[everyone] = discord.PermissionOverwrite(send_messages=False)
                        overwrites[bot_member] = discord.PermissionOverwrite(send_messages=True)

                    ch = await guild.create_text_channel(
                        ch_name,
                        category=cat,
                        topic=topic,
                        overwrites=overwrites,
                    )
                    print(f"  + #{ch_name} — 생성 (id={ch.id}){' [봇전용]' if bot_only else ''}")

                # 결과 키 매핑 (이원화 적용)
                key_map = {
                    "해외-watchlist":    "DISCORD_US_WATCHLIST_CHANNEL_ID",
                    "국내-watchlist":    "DISCORD_KR_WATCHLIST_CHANNEL_ID",
                    "해외-진입-시그널":  "DISCORD_US_SIGNAL_CHANNEL_ID",
                    "국내-진입-시그널":  "DISCORD_KR_SIGNAL_CHANNEL_ID",
                    "해외-일간리포트":  "DISCORD_US_DAILY_REPORT_CHANNEL_ID",
                    "국내-일간리포트":  "DISCORD_KR_DAILY_REPORT_CHANNEL_ID",
                    "해외-주간리포트":  "DISCORD_US_WEEKLY_REPORT_CHANNEL_ID",
                    "국내-주간리포트":  "DISCORD_KR_WEEKLY_REPORT_CHANNEL_ID",
                    "해외-paper-trades": "DISCORD_US_PAPER_CHANNEL_ID",
                    "국내-paper-trades": "DISCORD_KR_PAPER_CHANNEL_ID",
                    "해외-시나리오":     "DISCORD_US_SCENARIO_CHANNEL_ID",
                    "국내-시나리오":     "DISCORD_KR_SCENARIO_CHANNEL_ID",
                    "해외-포트폴리오":   "DISCORD_US_PORTFOLIO_CHANNEL_ID",
                    "국내-포트폴리오":   "DISCORD_KR_PORTFOLIO_CHANNEL_ID",
                    "종목-발굴":        "DISCORD_DISCOVERY_CHANNEL_ID",
                    "유튜버-트래킹":    "DISCORD_YOUTUBER_CHANNEL_ID",
                    "봇-명령어":        "DISCORD_BOT_CMD_CHANNEL_ID",
                }
                if ch_name in key_map:
                    result[key_map[ch_name]] = ch.id

        print("\n\n=== 생성된 채널 ID (env 형식) ===")
        for k, v in result.items():
            if k.startswith("DISCORD_"):
                print(f"{k}={v}")

        # JSON으로도 저장
        out_path = "/tmp/discord_channels.json"
        with open(out_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n채널 ID 저장: {out_path}")

        await client.close()

    await client.start(token)


if __name__ == "__main__":
    asyncio.run(setup_channels())
