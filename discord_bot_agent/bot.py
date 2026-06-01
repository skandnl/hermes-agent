from __future__ import annotations

import asyncio
import argparse
import logging
import sys
from datetime import datetime
import discord
from discord.ext import commands

from .config import DiscordBotAgentConfig
from .embeds import payload_to_embed, report_payload, trade_alert_payload
from .models import TradeSetup
from .reports import build_stock_scenario, generate_daily_report, generate_weekly_report, scan_watchlist
from .store import TradingStore
from .youtube_tracker import VideoResult, scan_youtubers

logger = logging.getLogger(__name__)


async def send_discord_embed(bot, channel_id: int, payload: dict) -> None:
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    await channel.send(embed=payload_to_embed(payload))


async def send_discord_text(bot, channel_id: int, text: str, view: discord.ui.View | None = None) -> None:
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    await channel.send(text, view=view)


class YoutubeDiscoveryView(discord.ui.View):
    def __init__(self, tickers: list[str], store: TradingStore, bot, bot_instance):
        super().__init__(timeout=None)
        self.store = store
        self.bot = bot
        self.bot_instance = bot_instance

        for ticker in tickers:
            btn = discord.ui.Button(
                label=f"➕ {ticker} 승인 (Watchlist 추가)",
                style=discord.ButtonStyle.success,
                custom_id=f"approve_{ticker}"
            )
            btn.callback = self.create_callback(ticker)
            self.add_item(btn)

    def create_callback(self, ticker: str):
        async def callback(interaction: discord.Interaction):
            is_kr = self.bot_instance.is_korean(ticker)
            sector = "방산(국내)" if "012450" in ticker or "079550" in ticker else ("국내 주식" if is_kr else "해외 주식")
            success = self.store.add_to_watchlist(ticker, sector)
            if success:
                target_ch = self.bot_instance.watchlist_ch(ticker)
                await interaction.response.send_message(
                    f"✅ **{interaction.user.display_name}**님이 **{ticker}** 추가를 승인하셨습니다! "
                    f"종목이 <#{target_ch}> 에 추가되었습니다."
                )
                # 해당 전용 채널에 알림
                watch_channel = self.bot.get_channel(target_ch)
                if watch_channel is None:
                    watch_channel = await self.bot.fetch_channel(target_ch)
                await watch_channel.send(
                    f"📈 **[종목 추가 완료]** **{ticker}**가 유튜버 언급에서 승인되어 관심종목에 등록되었습니다."
                )
            else:
                await interaction.response.send_message(
                    f"ℹ️ **{ticker}**는 이미 관심종목에 등록되어 있습니다.",
                    ephemeral=True
                )
        return callback


class HermesTradingDiscordBot:
    def __init__(self, config: DiscordBotAgentConfig):
        intents = discord.Intents.default()
        self.discord = discord
        self.config = config
        self.store = TradingStore(config.database_path)
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self._last_daily_key: str | None = None
        self._last_weekly_key: str | None = None
        self._register_events()
        self._register_commands()

    # ── 채널 ID 헬퍼 (국내/해외 이원화 동적 라우팅) ──────────────────────
    def is_korean(self, symbol: str) -> bool:
        """티커가 국내 종목인지 여부 판별 (숫자 6자리 혹은 KS/KQ 접미사)."""
        sym = symbol.upper().strip()
        if sym.isdigit() and len(sym) == 6:
            return True
        if sym.endswith(".KS") or sym.endswith(".KQ"):
            return True
        return False

    def _ch(self, specific: int | None, fallback: int) -> int:
        """specific 채널이 설정돼 있으면 사용, 없으면 fallback."""
        return specific if specific is not None else fallback

    def watchlist_ch(self, symbol: str) -> int:
        """해당 종목 전용 관심종목 채널 ID 반환."""
        if self.is_korean(symbol):
            return self._ch(self.config.kr_watchlist_channel_id, self.config.report_channel_id)
        return self._ch(self.config.us_watchlist_channel_id, self.config.report_channel_id)

    def signal_ch(self, symbol: str) -> int:
        """해당 종목 전용 시그널 채널 ID 반환."""
        if self.is_korean(symbol):
            return self._ch(self.config.kr_signal_channel_id, self.config.alert_channel_id)
        return self._ch(self.config.us_signal_channel_id, self.config.alert_channel_id)

    def daily_ch(self, symbol: str) -> int:
        """해당 종목 전용 일간 리포트 채널 ID 반환."""
        if self.is_korean(symbol):
            return self._ch(self.config.kr_daily_report_channel_id, self.config.report_channel_id)
        return self._ch(self.config.us_daily_report_channel_id, self.config.report_channel_id)

    def weekly_ch(self, symbol: str) -> int:
        """해당 종목 전용 주간 리포트 채널 ID 반환."""
        if self.is_korean(symbol):
            return self._ch(self.config.kr_weekly_report_channel_id, self.config.report_channel_id)
        return self._ch(self.config.us_weekly_report_channel_id, self.config.report_channel_id)

    def paper_ch(self, symbol: str) -> int:
        """해당 종목 전용 페이퍼 트레이딩 채널 ID 반환."""
        if self.is_korean(symbol):
            return self._ch(self.config.kr_paper_channel_id, self.config.report_channel_id)
        return self._ch(self.config.us_paper_channel_id, self.config.report_channel_id)

    @property
    def _discovery_ch(self) -> int:
        """#종목-발굴 채널 ID (DISCORD_DISCOVERY_CHANNEL_ID 또는 report_channel fallback)."""
        disc_id = getattr(self.config, "discovery_channel_id", None)
        return self._ch(disc_id, self.config.report_channel_id)

    # ── 이벤트 등록 ────────────────────────────────────────────────
    def _register_events(self) -> None:
        @self.bot.event
        async def setup_hook():
            guild = self.discord.Object(id=self.config.guild_id) if self.config.guild_id else None
            if guild is not None:
                try:
                    self.bot.tree.copy_global_to(guild=guild)
                    synced = await self.bot.tree.sync(guild=guild)
                    logger.info("Synced %d guild Discord commands", len(synced))
                except Exception as e:
                    logger.warning(
                        "Guild command sync failed (%s). Falling back to global sync.", e
                    )
                    synced = await self.bot.tree.sync()
                    logger.info("Synced %d global Discord commands as fallback", len(synced))
            else:
                synced = await self.bot.tree.sync()
                logger.info("Synced %d global Discord commands", len(synced))

        @self.bot.event
        async def on_ready():
            logger.info("Hermes Trading Discord Bot connected as %s", self.bot.user)

    # ── 슬래시 커맨드 등록 ─────────────────────────────────────────
    def _register_commands(self) -> None:
        from discord import app_commands

        hermes = app_commands.Group(name="hermes", description="Hermes Trading AI")
        report_grp = app_commands.Group(name="report", description="리포트 발송", parent=hermes)
        alert_grp = app_commands.Group(name="alert", description="알림 제어", parent=hermes)
        paper_grp = app_commands.Group(name="paper", description="페이퍼 트레이딩", parent=hermes)
        watchlist_grp = app_commands.Group(name="watchlist", description="관심종목 관리", parent=hermes)
        youtuber_grp = app_commands.Group(name="youtuber", description="참고 유튜버 관리", parent=hermes)
        youtube_grp = app_commands.Group(name="youtube", description="YouTube 종목 발굴", parent=hermes)

        # ── /hermes report ─────────────────────────────────────────
        # ── /hermes report ─────────────────────────────────────────
        @report_grp.command(name="daily", description="일간 리서치 리포트 즉시 발송")
        async def daily_report(interaction):
            await interaction.response.defer()
            # 1. 해외 일간 종합 텍스트 리포트 발송
            body_us = generate_daily_report(self.store, datetime.now(self.config.timezone), is_kr=False)
            ch_us = self.config.us_daily_report_channel_id or self.config.report_channel_id
            await send_discord_embed(self.bot, ch_us, report_payload("📅 해외 일간 종합 리서치", body_us))

            # 2. 국내 일간 종합 텍스트 리포트 발송
            body_kr = generate_daily_report(self.store, datetime.now(self.config.timezone), is_kr=True)
            ch_kr = self.config.kr_daily_report_channel_id or self.config.report_channel_id
            await send_discord_embed(self.bot, ch_kr, report_payload("📅 국내 일간 종합 리서치", body_kr))

            # 3. 관심종목 전체를 동적 분석하여 개별 분석 카드 순차적 자동 발행!
            all_symbols = self.store.watchlist()
            us_count = 0
            kr_count = 0
            for symbol in all_symbols:
                is_kr = self.is_korean(symbol)
                target_ch = self.config.kr_daily_report_channel_id if is_kr else self.config.us_daily_report_channel_id
                target_ch = target_ch or self.config.report_channel_id
                
                # 시세 퀀트 분석 수행
                setup = build_stock_scenario(symbol)
                # 개별 분석 카드 송출
                await send_discord_embed(self.bot, target_ch, trade_alert_payload(setup))
                if is_kr:
                    kr_count += 1
                else:
                    us_count += 1

            await interaction.followup.send(
                f"✅ 종합 리포트 및 관심종목 {len(all_symbols)}개(해외 {us_count}개, 국내 {kr_count}개)의 "
                f"개별 퀀트 시나리오 분석 카드 자동 발행을 완료했습니다!"
            )

        @report_grp.command(name="weekly", description="주간 리서치 리포트 즉시 발송")
        async def weekly_report(interaction):
            await interaction.response.defer()
            # 1. 해외 주간 리포트 발송
            body_us = generate_weekly_report(self.store, datetime.now(self.config.timezone), is_kr=False)
            payload_us = report_payload("📊 해외 주간 리포트", body_us)
            ch_us = self.config.us_weekly_report_channel_id or self.config.report_channel_id
            await send_discord_embed(self.bot, ch_us, payload_us)

            # 2. 국내 주간 리포트 발송
            body_kr = generate_weekly_report(self.store, datetime.now(self.config.timezone), is_kr=True)
            payload_kr = report_payload("📊 국내 주간 리포트", body_kr)
            ch_kr = self.config.kr_weekly_report_channel_id or self.config.report_channel_id
            await send_discord_embed(self.bot, ch_kr, payload_kr)

            await interaction.followup.send(f"✅ 해외 주간 리포트(<#{ch_us}>) 및 국내 주간 리포트(<#{ch_kr}>) 발송을 완료했습니다.")

        # ── /hermes watchlist ──────────────────────────────────────
        @watchlist_grp.command(name="show", description="현재 관심종목 목록 보기 (개인화)")
        async def watchlist_show(interaction):
            user_id = str(interaction.user.id)
            details = self.store.user_watchlist_details(user_id)
            if not details:
                await interaction.response.send_message("📋 관심종목이 비어 있습니다. `/hermes watchlist add` 로 추가해보세요!")
                return

            # 섹터별 그룹화
            groups = {}
            for item in details:
                sec = item["sector"] or "미분류"
                if sec not in groups:
                    groups[sec] = []
                groups[sec].append(item["symbol"])

            lines = [f"📋 **{interaction.user.display_name}**님의 개인 관심종목 (총 {len(details)}개)\n"]
            for sec, syms in groups.items():
                lines.append(f"■ **{sec}**")
                lines.append("\n".join(f"  • **{s}**" for s in syms))
                lines.append("")

            await interaction.response.send_message("\n".join(lines)[:2000])

        @watchlist_grp.command(name="add", description="개인 관심종목 추가")
        @app_commands.describe(symbol="종목 코드 (예: NVDA, 005930.KS)", sector="섹터/카테고리 (예: 우주섹터, 반도체)")
        async def watchlist_add(interaction, symbol: str, sector: str = None):
            user_id = str(interaction.user.id)
            sym = symbol.upper().strip()
            # 만약 섹터가 전달되지 않았다면 동적으로 기본 국내/해외 주식 섹터 할당
            if not sector:
                sector = "국내 주식" if self.is_korean(sym) else "해외 주식"
            added = self.store.add_to_user_watchlist(user_id, sym, sector)
            sec_str = f" [{sector}]" if sector else ""
            if added:
                target_ch = self.watchlist_ch(sym)
                await interaction.response.send_message(f"✅ **{sym}**{sec_str} 개인 관심종목 추가 완료!")
                # 서버 전용 #watchlist 채널에도 자동 알림 (공동 채널 공유 알림 유지)
                await send_discord_text(
                    self.bot, target_ch,
                    f"📥 **{interaction.user.display_name}**님이 **{sym}** 이(가){sec_str} 관심종목에 추가했습니다."
                )
            else:
                await interaction.response.send_message(f"ℹ️ **{sym}** 은(는) 이미 관심종목에 있습니다.")

        @watchlist_grp.command(name="remove", description="개인 관심종목 제거")
        @app_commands.describe(symbol="종목 코드 (예: TSLA)")
        async def watchlist_remove(interaction, symbol: str):
            user_id = str(interaction.user.id)
            sym = symbol.upper().strip()
            removed = self.store.remove_from_user_watchlist(user_id, sym)
            if removed:
                target_ch = self.watchlist_ch(sym)
                await interaction.response.send_message(f"🗑️ **{sym}** 관심종목에서 제거 완료!")
                await send_discord_text(
                    self.bot, target_ch,
                    f"📤 **{interaction.user.display_name}**님이 **{sym}** 이(가) 관심종목에서 제거했습니다."
                )
            else:
                await interaction.response.send_message(f"⚠️ **{sym}** 은(는) 관심종목에 없습니다.")

        # ── /hermes scan / stock ───────────────────────────────────
        @hermes.command(name="scan", description="관심종목 전체 시나리오 스캔")
        async def scan(interaction):
            await interaction.response.defer()
            setups = scan_watchlist(self.store)
            text = "\n".join(f"- **{setup.symbol}**: {setup.caution}" for setup in setups)
            await interaction.followup.send(text[:2000] or "관심종목이 없습니다.")

        @hermes.command(name="stock", description="종목 시나리오 카드 보기")
        @app_commands.describe(symbol="종목 코드 (예: NVDA)")
        async def stock(interaction, symbol: str):
            await interaction.response.defer()
            sym = symbol.upper().strip()
            setup = build_stock_scenario(sym)
            embed = payload_to_embed(trade_alert_payload(setup))
            await interaction.followup.send(embed=embed)
            
            # 국내/해외 전용 #시나리오 채널에도 기록 미러링 포스팅
            is_kr = self.is_korean(sym)
            target_ch = self._ch(
                self.config.kr_watchlist_channel_id if is_kr else self.config.us_watchlist_channel_id,
                self.config.report_channel_id
            )
            # 설정 상 kr_scenario_channel_id / us_scenario_channel_id 가 존재하므로 동적 get
            scen_ch_key = "kr_scenario_channel_id" if is_kr else "us_scenario_channel_id"
            scen_ch_id = getattr(self.config, scen_ch_key, None) or target_ch
            
            await send_discord_embed(self.bot, scen_ch_id, trade_alert_payload(setup))

        # ── /hermes alert ──────────────────────────────────────────
        @alert_grp.command(name="on", description="진입 시그널 알림 활성화")
        async def alert_on(interaction):
            self.store.set_alerts_enabled(True)
            await interaction.response.send_message("🔔 진입 시그널 알림이 **활성화**되었습니다.")

        @alert_grp.command(name="off", description="진입 시그널 알림 비활성화")
        async def alert_off(interaction):
            self.store.set_alerts_enabled(False)
            await interaction.response.send_message("🔕 진입 시그널 알림이 **비활성화**되었습니다.")

        # ── /hermes paper ──────────────────────────────────────────
        @paper_grp.command(name="buy", description="페이퍼 매수 기록")
        @app_commands.describe(symbol="종목 코드", quantity="수량", price="매수 가격")
        async def paper_buy(interaction, symbol: str, quantity: float, price: float):
            trade = self.store.record_paper_trade("buy", symbol, quantity, price)
            msg = (
                f"📈 **페이퍼 매수** 기록\n"
                f"종목: **{trade.symbol}**  |  수량: {trade.quantity:g}주  |  가격: {trade.price:,.2f}"
            )
            await interaction.response.send_message(msg)
            # 국내/해외 전용 #paper-trades 채널에 자동 포스팅
            target_ch = self.paper_ch(trade.symbol)
            await send_discord_text(self.bot, target_ch, msg)

        @paper_grp.command(name="sell", description="페이퍼 매도 기록")
        @app_commands.describe(symbol="종목 코드", quantity="수량", price="매도 가격")
        async def paper_sell(interaction, symbol: str, quantity: float, price: float):
            trade = self.store.record_paper_trade("sell", symbol, quantity, price)
            msg = (
                f"📉 **페이퍼 매도** 기록\n"
                f"종목: **{trade.symbol}**  |  수량: {trade.quantity:g}주  |  가격: {trade.price:,.2f}"
            )
            await interaction.response.send_message(msg)
            target_ch = self.paper_ch(trade.symbol)
            await send_discord_text(self.bot, target_ch, msg)

        @paper_grp.command(name="positions", description="현재 페이퍼 포지션 조회")
        async def paper_positions(interaction):
            positions = self.store.positions()
            if not positions:
                await interaction.response.send_message("💼 보유 페이퍼 포지션이 없습니다.")
                return
            lines = [
                f"• **{p.symbol}**  {p.quantity:g}주  avg {p.average_price:,.2f}  실현PnL {p.realized_pnl:+,.2f}"
                for p in positions if p.quantity > 0
            ]
            closed = [p for p in positions if p.quantity <= 0 and p.realized_pnl != 0]
            text = "💼 **페이퍼 포지션**\n" + ("\n".join(lines) if lines else "보유 없음")
            if closed:
                text += "\n\n📋 **청산 종목 (실현 손익)**\n"
                text += "\n".join(f"• **{p.symbol}**  실현PnL {p.realized_pnl:+,.2f}" for p in closed)
            await interaction.response.send_message(text[:2000])

        # ── /hermes youtuber ───────────────────────────────────────
        @youtuber_grp.command(name="add", description="참고 유튜버 등록")
        @app_commands.describe(name="유튜버 이름", url="유튜브 채널 URL", note="메모 (예: 미국주식 전문, 선택)")
        async def youtuber_add(interaction, name: str, url: str, note: str = ""):
            added = self.store.add_youtuber(name, url, note)
            if added:
                msg = f"✅ **{name}** 유튜버 등록 완료!\n🔗 {url}"
                if note:
                    msg += f"\n📝 {note}"
                await interaction.response.send_message(msg)
            else:
                await interaction.response.send_message(f"ℹ️ **{name}** 은(는) 이미 등록된 유튜버입니다.")

        @youtuber_grp.command(name="list", description="등록된 유튜버 목록 보기")
        async def youtuber_list(interaction):
            yt_list = self.store.youtubers()
            if not yt_list:
                await interaction.response.send_message("📺 등록된 유튜버가 없습니다.\n`/hermes youtuber add` 로 추가하세요.")
                return
            lines = []
            for yt in yt_list:
                line = f"• **{yt['name']}** — {yt['url']}"
                if yt["note"]:
                    line += f"\n  └ {yt['note']}"
                lines.append(line)
            await interaction.response.send_message(
                f"📺 **참고 유튜버 ({len(yt_list)}명)**\n" + "\n".join(lines)
            )

        @youtuber_grp.command(name="remove", description="유튜버 삭제")
        @app_commands.describe(name="삭제할 유튜버 이름")
        async def youtuber_remove(interaction, name: str):
            removed = self.store.remove_youtuber(name)
            if removed:
                await interaction.response.send_message(f"🗑️ **{name}** 유튜버를 삭제했습니다.")
            else:
                await interaction.response.send_message(f"⚠️ **{name}** 은(는) 등록되지 않은 유튜버입니다.")

        # ── /hermes youtube ───────────────────────────────────────
        @youtube_grp.command(name="scan", description="유튜버 최신 영상 스캔 (수동)")
        @app_commands.describe(hours="탐색 범위 (시간, 기본 48h)")
        async def youtube_scan(interaction, hours: int = 48):
            await interaction.response.defer()
            results = await asyncio.get_event_loop().run_in_executor(
                None, lambda: scan_youtubers(self.store, since_hours=hours)
            )
            if not results:
                await interaction.followup.send(f"ℹ️ 최근 {hours}h 내 신규 영상이 없거나 이미 스캔한 영상입니다.")
                return
            await self._post_youtube_results(results)
            await interaction.followup.send(f"✅ {len(results)}개 영상 스캔 완료 → <#{self._discovery_ch}> 확인")

        @youtube_grp.command(name="recent", description="최근 스캔 결과 보기")
        async def youtube_recent(interaction):
            logs = self.store.recent_scan_logs(limit=10)
            if not logs:
                await interaction.response.send_message("📺 스캔 이력이 없습니다. `/hermes youtube scan` 을 먼저 실행하세요.")
                return
            lines = []
            for log in logs:
                tickers = log["tickers"]
                ticker_str = f"  ↳ 종목: `{tickers}`" if tickers else "  ↳ 종목 미발갬"
                lines.append(f"▪️ **{log['youtuber_name']}** [{log['title'][:40]}]\n{ticker_str}")
            await interaction.response.send_message(
                f"📺 **최근 스캔 ({len(logs)}건)**\n" + "\n".join(lines)
            )

        self.bot.tree.add_command(hermes)

    # ── 자동 발송 메서드 ───────────────────────────────────────────
    async def send_trade_alert(self, setup: TradeSetup) -> None:
        if not self.store.alerts_enabled():
            logger.info("Skipping trade alert for %s because alerts are disabled", setup.symbol)
            return
        target_ch = self.signal_ch(setup.symbol)
        await send_discord_embed(self.bot, target_ch, trade_alert_payload(setup))

    async def send_daily_report(self) -> None:
        # ── 공용 채널 브리핑 ──────────────────────────────────────────
        # 1. 해외 일간 종합 텍스트 리포트
        body_us = generate_daily_report(self.store, datetime.now(self.config.timezone), is_kr=False)
        ch_us = self.config.us_daily_report_channel_id or self.config.report_channel_id
        await send_discord_embed(self.bot, ch_us, report_payload("📅 해외 일간 종합 리서치", body_us))

        # 2. 국내 일간 종합 텍스트 리포트
        body_kr = generate_daily_report(self.store, datetime.now(self.config.timezone), is_kr=True)
        ch_kr = self.config.kr_daily_report_channel_id or self.config.report_channel_id
        await send_discord_embed(self.bot, ch_kr, report_payload("📅 국내 일간 종합 리서치", body_kr))

        # 3. 공용 관심종목 전체를 순회하며 개별 주가 퀀트 시나리오 분석 카드 백그라운드 자동 발행!
        all_symbols = self.store.watchlist()
        for symbol in all_symbols:
            is_kr = self.is_korean(symbol)
            target_ch = self.config.kr_daily_report_channel_id if is_kr else self.config.us_daily_report_channel_id
            target_ch = target_ch or self.config.report_channel_id
            setup = build_stock_scenario(symbol)
            await send_discord_embed(self.bot, target_ch, trade_alert_payload(setup))

        # ── 개인 1:1 DM 브리핑 배달 ────────────────────────────────────
        logger.info("[DM] 사용자별 개인화 1:1 장마감 브리핑 배달 시작")
        user_ids = self.store.all_users_in_watchlist()
        for uid_str in user_ids:
            try:
                user_id = int(uid_str)
                user = await self.bot.fetch_user(user_id)
                if user is None:
                    continue

                user_symbols = self.store.user_watchlist(uid_str)
                if not user_symbols:
                    continue

                # DM 룸 생성
                dm_channel = user.dm_channel
                if dm_channel is None:
                    dm_channel = await user.create_dm()

                logger.info("[DM] 사용자 %s(%s) 님에게 %d개 종목 브리핑 발송 중...", user.name, uid_str, len(user_symbols))
                
                # 개인화 웰컴 헤더 전송
                header = (
                    f"🔔 **{user.display_name}**님만을 위한 오늘의 1:1 맞춤형 주식 퀀트 브리핑 대령했습니다!\n"
                    f"구독하신 {len(user_symbols)}개 관심종목의 최신 장마감 분석 카드를 확인하세요."
                )
                await dm_channel.send(header)

                for symbol in user_symbols:
                    # 야후 파이낸스 분석 실행
                    setup = build_stock_scenario(symbol)
                    # DM으로 개별 퀀트 분석 카드 다이렉트 전송!
                    embed_payload = trade_alert_payload(setup)
                    await dm_channel.send(embed=payload_to_embed(embed_payload))
                    
                logger.info("[DM] 사용자 %s님에게 배달 완료", user.name)
            except Exception as e:
                logger.warning("[DM] 사용자 %s 님에게 DM 발송 중 오류 발생: %s", uid_str, e)

    async def send_weekly_report(self) -> None:
        # 1. 해외 주간 리포트
        body_us = generate_weekly_report(self.store, datetime.now(self.config.timezone), is_kr=False)
        ch_us = self.config.us_weekly_report_channel_id or self.config.report_channel_id
        await send_discord_embed(self.bot, ch_us, report_payload("📊 해외 주간 리포트", body_us))

        # 2. 국내 주간 리포트
        body_kr = generate_weekly_report(self.store, datetime.now(self.config.timezone), is_kr=True)
        ch_kr = self.config.kr_weekly_report_channel_id or self.config.report_channel_id
        await send_discord_embed(self.bot, ch_kr, report_payload("📊 국내 주간 리포트", body_kr))

    async def send_youtube_scan(self) -> None:
        """YouTube RSS 스캔 실행 후 #종목-발굴에 포스팅."""
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, lambda: scan_youtubers(self.store, since_hours=25)
        )
        if results:
            await self._post_youtube_results(results)
            logger.info("[YouTube] 스케줄 스캔: %d개 신규 영상 발견", len(results))
        else:
            logger.info("[YouTube] 스케줄 스캔: 신규 영상 없음")

    async def _post_youtube_results(self, results: list[VideoResult]) -> None:
        """VideoResult 목록을 #종목-발굴 채널에 embed로 포스팅."""
        ch_id = self._discovery_ch
        for r in results:
            ticker_str = ", ".join(f"`{t}`" for t in r.tickers) if r.tickers else "종목 미발갬"
            pub_kst = r.published.astimezone(self.config.timezone)
            text = (
                f"📺 **[{r.youtuber_name}]** {r.title}\n"
                f"🔗 {r.url}\n"
                f"⏰ {pub_kst:%Y-%m-%d %H:%M}\n"
                f"📌 발견 종목: {ticker_str}"
            )
            view = None
            if r.tickers:
                view = YoutubeDiscoveryView(
                    tickers=r.tickers,
                    store=self.store,
                    bot=self.bot,
                    bot_instance=self
                )
            await send_discord_text(self.bot, ch_id, text, view=view)



    def run(self) -> None:
        self.bot.run(self.config.token)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hermes-trading-discord",
        description="Hermes Trading AI Discord bot. Use --daily/--weekly/--youtube-scan for Hermes cron one-shot tasks.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate required environment variables and exit without connecting to Discord.",
    )
    # ── Hermes cron one-shot 모드 ──────────────────────────────────────
    # 이 플래그들은 Hermes cron 스케줄러가 직접 호출합니다.
    # 봇에 로그인 후 해당 리포트/스캔을 1회 실행하고 즉시 종료합니다.
    parser.add_argument(
        "--daily",
        action="store_true",
        help="(Hermes cron) 일간 리포트 + YouTube 스캔을 1회 실행하고 종료.",
    )
    parser.add_argument(
        "--weekly",
        action="store_true",
        help="(Hermes cron) 주간 리포트를 1회 실행하고 종료.",
    )
    parser.add_argument(
        "--youtube-scan",
        action="store_true",
        help="(Hermes cron) YouTube RSS 스캔을 1회 실행하고 종료.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        from hermes_cli.env_loader import load_hermes_dotenv
        load_hermes_dotenv()
    except Exception as exc:
        logger.debug("Could not load Hermes .env before starting trading bot: %s", exc)

    try:
        config = DiscordBotAgentConfig.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if args.check_config:
        print("Hermes Trading Discord Bot configuration OK")
        print(f"Guild ID          : {config.guild_id or 'global sync disabled by default'}")
        print(f"Alert channel     : {config.alert_channel_id}")
        print(f"Report channel    : {config.report_channel_id}")
        print(f"Watchlist channel : {config.watchlist_channel_id or '(→ report_channel fallback)'}")
        print(f"Signal channel    : {config.signal_channel_id or '(→ alert_channel fallback)'}")
        print(f"Daily report ch   : {config.daily_report_channel_id or '(→ report_channel fallback)'}")
        print(f"Weekly report ch  : {config.weekly_report_channel_id or '(→ report_channel fallback)'}")
        print(f"Paper trades ch   : {config.paper_channel_id or '(→ report_channel fallback)'}")
        print(f"Database          : {config.database_path}")
        return

    # ── Hermes cron one-shot 실행 모드 ────────────────────────────────
    if args.daily or args.weekly or args.youtube_scan:
        bot_instance = HermesTradingDiscordBot(config)

        async def _run_once() -> None:
            """봇 로그인 후 지정 작업을 1회 실행하고 종료."""
            async with bot_instance.bot:
                await bot_instance.bot.login(config.token)
                # wait_until_ready 없이 내부 상태 초기화
                if args.daily:
                    logger.info("[cron] --daily: 일간 리포트 + YouTube 스캔 실행")
                    await bot_instance.send_daily_report()
                    await bot_instance.send_youtube_scan()
                if args.weekly:
                    logger.info("[cron] --weekly: 주간 리포트 실행")
                    await bot_instance.send_weekly_report()
                if args.youtube_scan:
                    logger.info("[cron] --youtube-scan: YouTube RSS 스캔 실행")
                    await bot_instance.send_youtube_scan()

        asyncio.run(_run_once())
        return

    # ── 상시 봇 모드 (슬래시 커맨드 서빙) ────────────────────────────
    HermesTradingDiscordBot(config).run()
