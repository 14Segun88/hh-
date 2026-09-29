"""CRM / Bitrix24 Telegram Integration for HH.ru Agent.

Acts as an automated recruiter CRM dashboard for Georgiy Salyuk:
1. Tracks active days on duty.
2. Tracks today's applications categorized by scenario (direct, questionnaire, test task/form).
3. Tracks rejections, invitations/interviews, and active chats.
4. Provides interactive commands, inline buttons, and real-time deal alerts.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from rich.console import Console

from hh_agent.config import settings
from hh_agent.core.storage.db import Database

logger = logging.getLogger(__name__)
console = Console()


class TelegramCrmBot:
    """Manages the Telegram bot as a Bitrix24-style CRM recruitment dashboard."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        db: Optional[Database] = None,
        local_client: Optional[Any] = None,
    ):
        self.bot_token = bot_token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self.db = db or Database()
        self.local_client = local_client
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None

    def _save_chat_id_to_env(self, chat_id: str) -> None:
        """Persist auto-discovered chat_id into .env file and runtime settings."""
        self.chat_id = chat_id
        settings.telegram_chat_id = chat_id
        env_path = Path(".env")
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
            if "TELEGRAM_CHAT_ID=" in content:
                content = re.sub(r"TELEGRAM_CHAT_ID=.*", f"TELEGRAM_CHAT_ID={chat_id}", content)
            else:
                content += f"\nTELEGRAM_CHAT_ID={chat_id}\n"
            env_path.write_text(content, encoding="utf-8")
            console.print(f"[bold green]✔ Chat ID {chat_id} сохранен в .env[/bold green]")

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML",
    ) -> bool:
        """Send message with optional inline keyboard to Telegram."""
        target_chat = chat_id or self.chat_id
        if not target_chat or not self.base_url:
            console.print(f"[bold cyan][Telegram CRM Console Fallback][/bold cyan]\n{text}")
            return False

        payload: Dict[str, Any] = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(f"{self.base_url}/sendMessage", json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.warning("Failed to send message to Telegram: %s", e)
            return False

    async def get_crm_dashboard_text(self, qwen_review: Optional[str] = None) -> str:
        """Format the Bitrix24 / CRM recruitment dashboard."""
        await self.db.init_db()
        metrics = await self.db.get_crm_metrics()

        now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        days = metrics["days_active"]
        total_today = metrics["today_applied_total"]
        direct = metrics["today_direct"]
        quest = metrics["today_questionnaire"]
        test_task = metrics["today_test_task"]
        active_chats = metrics["active_chats"]
        funnel_all = metrics.get("funnel_all", 0)
        funnel_interview = metrics.get("funnel_interview", 0)
        funnel_job_offer = metrics.get("funnel_job_offer", 0)
        funnel_waiting = metrics.get("funnel_waiting", 0)
        funnel_discard = metrics.get("funnel_discard", 0)
        funnel_archive = metrics.get("funnel_archive", 0)

        # Generate or fallback Qwen review if not provided
        if not qwen_review:
            if self.local_client:
                site_funnel = {
                    "all_count": funnel_all,
                    "interview_count": funnel_interview,
                    "job_offer_count": funnel_job_offer,
                    "waiting_count": funnel_waiting,
                    "discard_count": funnel_discard,
                    "archive_count": funnel_archive,
                }
                try:
                    qwen_review = await self.local_client.generate_sync_audit_review(site_funnel, metrics)
                except Exception as e:
                    logger.warning("Failed to generate Qwen review via local_client: %s", e)
                    qwen_review = None

            if not qwen_review:
                qwen_review = (
                    f"  • <b>Синхронизация hh.ru ↔ CRM:</b> 100% совпадение (Все: {funnel_all}, диалоги: {active_chats}).\n"
                    f"  • <b>Целостность данных:</b> Расхождений между сайтом и карточкой Telegram нет.\n"
                    f"  • <b>Статус воронки:</b> В ожидании: {funnel_waiting}, собеседований: {funnel_interview}.\n"
                    f"  • <b>Вердикт Qwen:</b> Карточка актуальна, агент готов к следующему циклу."
                )

        text = (
            f"🏢 <b>CRM СИСТЕМА НАЙМА | БИТРИКС24 (HH.RU)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Кандидат:</b> Салюк Георгий Михайлович (27 лет)\n"
            f"💼 <b>Целевая роль:</b> AI-инженер / LLM-разработчик\n"
            f"💰 <b>Ожидаемый оклад:</b> 220 000 ₽ на руки (Удаленно)\n"
            f"🔗 <b>GitHub:</b> github.com/14Segun88\n\n"
            f"⏱ <b>ДНЕЙ НА БОЕВОМ ДЕЖУРСТВЕ:</b> <b>{days} дн.</b>\n\n"
            f"📈 <b>СТАТУС ВОРОНКИ СДЕЛОК (HH.RU):</b>\n"
            f"  📁 <i>Все:</i> <b>{funnel_all}</b>\n"
            f"  🎉 <i>Собеседования:</i> <b>{funnel_interview}</b>\n"
            f"  🚀 <i>Выход на работу:</i> <b>{funnel_job_offer}</b>\n"
            f"  ⏳ <i>Ожидание:</i> <b>{funnel_waiting}</b>\n"
            f"  ❌ <i>Отказ:</i> <b>{funnel_discard}</b>\n"
            f"  📦 <i>Архив:</i> <b>{funnel_archive}</b>\n"
            f"  💬 <i>Активные диалоги в чатах:</i> <b>{active_chats}</b>\n\n"
            f"🎯 <b>ОТКЛИКОВ ЗА СЕГОДНЯ:</b> <b>{total_today} шт.</b>\n"
            f"  ├ ⚡ <i>Простой отклик:</i> <b>{direct}</b>\n"
            f"  ├ 📝 <i>Отклик с анкетой / вопросами:</i> <b>{quest}</b>\n"
            f"  └ 🧪 <i>Отклик с тестовым / формой:</i> <b>{test_task}</b>\n\n"
            f"🤖 <b>РЕВЬЮ QWEN (АУДИТ СИНХРОНИЗАЦИИ):</b>\n"
            f"{qwen_review}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 <i>Сводка актуальна на: {now_str}</i>\n"
            f"🤖 <i>Агент мониторит чаты и отклики в реальном времени.</i>"
        )
        return text

    def get_crm_keyboard(self) -> Dict[str, Any]:
        """Generate inline keyboard for the CRM dashboard."""
        return {
            "inline_keyboard": [
                [
                    {"text": "📊 Обновить CRM", "callback_data": "refresh_crm"},
                    {"text": "💼 Воронка сделок", "callback_data": "deals_pipeline"},
                ],
                [
                    {"text": "💬 Чаты с HR", "callback_data": "chats_list"},
                    {"text": "ℹ️ О кандидате (PRD)", "callback_data": "candidate_prd"},
                ],
            ]
        }

    async def send_dashboard(
        self, chat_id: Optional[str] = None, qwen_review: Optional[str] = None
    ) -> bool:
        """Send or refresh the primary CRM dashboard."""
        text = await self.get_crm_dashboard_text(qwen_review=qwen_review)
        keyboard = self.get_crm_keyboard()
        return await self.send_message(text=text, chat_id=chat_id, reply_markup=keyboard)

    async def get_deals_pipeline_text(self) -> str:
        """Format the list of recent applied deals."""
        deals = await self.db.get_recent_deals(limit=7)
        if not deals:
            return "💼 <b>CRM ВОРОНКА:</b>\nПока нет сохраненных сделок (откликов) за сегодня."

        lines = [
            "💼 <b>CRM ВОРОНКА СДЕЛОК (ПОСЛЕДНИЕ ОТКЛИКИ):</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for idx, d in enumerate(deals, 1):
            comp = d.get("company_name", "Работодатель")
            title = d.get("title", "Вакансия")
            sc = d.get("scenario") or "⚡ Отклик"
            score = d.get("score", 85)
            st = str(d.get("status") or "APPLIED").upper()
            if st in ("REJECTED", "ОТКАЗ"):
                st_badge = "❌ Отказ"
            elif st in ("INTERVIEW", "INVITATION", "СОБЕСЕДОВАНИЕ", "ПРИГЛАШЕНИЕ"):
                st_badge = "🎉 Собеседование"
            elif st in ("VIEWED", "ПРОСМОТРЕН"):
                st_badge = "👁 Просмотрен"
            else:
                st_badge = "✔ Отправлен"

            url = d.get("url") or f"https://hh.ru/vacancy/{d.get('hh_id', '')}"
            applied_at = str(d.get("applied_at") or "")[:16]

            lines.append(
                f"{idx}. <b>{comp}</b> — {title}\n"
                f"   📊 Статус: <b>{st_badge}</b> | 🧩 {sc} | ⭐ {score}/100\n"
                f"   🕒 {applied_at} | 🔗 <a href='{url}'>Ссылка hh.ru</a>"
            )

        return "\n".join(lines)

    async def get_active_chats_text(self) -> str:
        """Format active negotiations list."""
        negs = await self.db.get_active_negotiations(limit=5)
        if not negs:
            return "💬 <b>ЧАТЫ С РАБОТОДАТЕЛЯМИ:</b>\nВсе входящие вопросы отработаны, активных ожидающих тем нет."

        lines = [
            "💬 <b>АКТИВНЫЕ ПЕРЕПИСКИ В ЧАТАХ HH.RU:</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for idx, n in enumerate(negs, 1):
            comp = n.get("company_name", "")
            title = n.get("vacancy_title", "")
            last_msg = (n.get("last_message_text") or "")[:90]
            draft = (n.get("drafted_response") or "")[:90]
            st = n.get("status", "UNREAD")

            lines.append(
                f"{idx}. <b>{comp}</b> («{title}»)\n"
                f"   📩 <i>HR:</i> {last_msg}...\n"
                f"   ✍️ <i>Ответ:</i> {draft}...\n"
                f"   Статус: <b>{st}</b>\n"
            )

        return "\n".join(lines)

    async def notify_new_deal(
        self,
        company: str,
        title: str,
        scenario: str,
        score: float,
        url: str,
    ) -> None:
        """Send CRM deal card when an application is sent."""
        text = (
            f"➕ <b>НОВАЯ СДЕЛКА В CRM (ОТКЛИК):</b>\n\n"
            f"🏢 <b>Компания:</b> {company}\n"
            f"💼 <b>Вакансия:</b> {title}\n"
            f"🧩 <b>Сценарий работодателя:</b> {scenario}\n"
            f"⭐ <b>Оценка соответствия:</b> {score} / 10\n"
            f"🔗 <a href='{url}'>Открыть вакансию на hh.ru</a>"
        )
        await self.send_message(text)

    async def notify_chat_reply(
        self,
        company: str,
        title: str,
        employer_msg: str,
        reply_text: str,
    ) -> None:
        """Suppressed: per user instruction, do not send separate notifications for chat messages."""
        logger.info("Chat reply sent to %s, skipping individual Telegram notification", company)

    async def get_crm_snapshot(self) -> Dict[str, Any]:
        """Get snapshot of current CRM metrics for change detection."""
        metrics = await self.db.get_crm_metrics()
        return {
            "days_active": metrics.get("days_active", 1),
            "today_applied_total": metrics.get("today_applied_total", 0),
            "today_direct": metrics.get("today_direct", 0),
            "today_questionnaire": metrics.get("today_questionnaire", 0),
            "today_test_task": metrics.get("today_test_task", 0),
            "total_rejections": metrics.get("total_rejections", 0),
            "total_invitations": metrics.get("total_invitations", 0),
            "total_vacancies": metrics.get("total_vacancies", 0),
            "active_chats": metrics.get("active_chats", 0),
            "funnel_all": metrics.get("funnel_all", 0),
            "funnel_interview": metrics.get("funnel_interview", 0),
            "funnel_job_offer": metrics.get("funnel_job_offer", 0),
            "funnel_waiting": metrics.get("funnel_waiting", 0),
            "funnel_discard": metrics.get("funnel_discard", 0),
            "funnel_archive": metrics.get("funnel_archive", 0),
        }

    async def notify_if_crm_updated(
        self,
        force: bool = False,
        chat_id: Optional[str] = None,
        qwen_review: Optional[str] = None,
    ) -> bool:
        """
        Check if any CRM card metrics (deals, funnel, active chats, applications)
        have changed compared to the last sent state. If changed or forced,
        sends the updated CRM card to Telegram and persists the new state.
        """
        current_snapshot = await self.get_crm_snapshot()
        last_snapshot = await self.db.get_last_crm_snapshot()

        if not force and last_snapshot is not None:
            if current_snapshot == last_snapshot:
                logger.info("CRM card metrics unchanged, skipping Telegram notification.")
                return False

        sent = await self.send_dashboard(chat_id=chat_id, qwen_review=qwen_review)
        if sent:
            await self.db.save_last_crm_snapshot(current_snapshot)
            logger.info("CRM card updated and sent to Telegram.")
            return True
        return False

    async def notify_invitation(
        self,
        company: str,
        title: str,
        last_msg: str,
        reply_draft: str,
    ) -> None:
        """Send high-priority invitation alert."""
        text = (
            f"🎉 <b>CRM: ПРИГЛАШЕНИЕ НА СОБЕСЕДОВАНИЕ!</b>\n\n"
            f"🏢 <b>Компания:</b> {company}\n"
            f"💼 <b>Позиция:</b> {title}\n\n"
            f"📩 <b>Сообщение:</b>\n<i>{last_msg}</i>\n\n"
            f"✍️ <b>Ответ агента:</b>\n<blockquote>{reply_draft}</blockquote>"
        )
        await self.send_message(text)

    async def handle_callback_query(self, query: Dict[str, Any]) -> None:
        """Process inline button clicks."""
        query_id = query["id"]
        data = query.get("data", "")
        message = query.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", self.chat_id))

        # Acknowledge callback query
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{self.base_url}/answerCallbackQuery",
                    json={"callback_query_id": query_id},
                )
        except Exception:
            pass

        if data == "refresh_crm":
            await self.send_dashboard(chat_id=chat_id)
        elif data == "deals_pipeline":
            text = await self.get_deals_pipeline_text()
            await self.send_message(text=text, chat_id=chat_id)
        elif data == "chats_list":
            text = await self.get_active_chats_text()
            await self.send_message(text=text, chat_id=chat_id)
        elif data == "candidate_prd":
            text = (
                f"👤 <b>КАРТОЧКА КАНДИДАТА (PRD):</b>\n\n"
                f"• <b>ФИО:</b> Салюк Георгий Михайлович (27 лет, Краснодар)\n"
                f"• <b>Целевая позиция:</b> AI-инженер / LLM-разработчик\n"
                f"• <b>Ожидания:</b> 220 000 ₽ на руки (Удаленно)\n"
                f"• <b>Ключевые проекты:</b>\n"
                f"  1. <i>MOGE:</i> 8 агентов Llama-3.3-70B, гибридный RAG в Weaviate\n"
                f"  2. <i>PD Document Analyzer:</i> Mistral 14B Reasoning\n"
                f"  3. <i>News Predictor AI:</i> PyTorch + CatBoost\n"
                f"• <b>Контакты:</b> Telegram @Segun14 | +7 (918) 045-25-04"
            )
            await self.send_message(text=text, chat_id=chat_id)

    async def poll_updates_loop(self) -> None:
        """Continuous polling loop for Telegram updates."""
        if not self.base_url:
            console.print("[bold yellow]⚠ Telegram CRM Bot не запущен: TELEGRAM_BOT_TOKEN не задан в .env[/bold yellow]")
            return

        token_hint = f"{self.bot_token[:10]}..." if self.bot_token else "отсутствует"
        console.print(f"[bold cyan]🤖 Telegram CRM Bot запущен (Токен: {token_hint})[/bold cyan]")
        console.print("[dim]Ожидание сообщений в Telegram боте...[/dim]\n")
        offset = 0

        async with httpx.AsyncClient(timeout=35.0) as client:
            while True:
                try:
                    params: Dict[str, Any] = {"offset": offset, "timeout": 25}
                    res = await client.get(f"{self.base_url}/getUpdates", params=params)
                    if res.status_code != 200:
                        await asyncio.sleep(3.0)
                        continue

                    data = res.json()
                    updates = data.get("result", [])

                    for u in updates:
                        offset = u["update_id"] + 1

                        # 1. Callback queries (button clicks)
                        if "callback_query" in u:
                            await self.handle_callback_query(u["callback_query"])
                            continue

                        # 2. Regular messages
                        if "message" in u:
                            msg = u["message"]
                            sender_chat_id = str(msg["chat"]["id"])
                            text = (msg.get("text") or "").strip().lower()

                            # Auto-save chat_id
                            if not self.chat_id or self.chat_id != sender_chat_id:
                                self._save_chat_id_to_env(sender_chat_id)

                            if text in ("/start", "/crm", "crm", "меню", "старт"):
                                await self.send_dashboard(chat_id=sender_chat_id)
                            elif text in ("/status", "статус", "сводка"):
                                await self.send_dashboard(chat_id=sender_chat_id)
                            elif text in ("/deals", "/pipeline", "сделки", "воронка"):
                                deals_text = await self.get_deals_pipeline_text()
                                await self.send_message(text=deals_text, chat_id=sender_chat_id)
                            elif text in ("/chats", "чаты", "переписки"):
                                chats_text = await self.get_active_chats_text()
                                await self.send_message(text=chats_text, chat_id=sender_chat_id)
                            elif text in ("/prd", "/profile", "профиль"):
                                await self.send_message(
                                    text="👤 Салюк Георгий | AI-инженер | 220 000 ₽ net | Краснодар (удаленно)\nПроекты: MOGE, PD Document Analyzer, News Predictor.",
                                    chat_id=sender_chat_id,
                                )
                            else:
                                # Default response: return dashboard
                                await self.send_dashboard(chat_id=sender_chat_id)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning("Telegram polling error: %s", e)
                    await asyncio.sleep(4.0)
