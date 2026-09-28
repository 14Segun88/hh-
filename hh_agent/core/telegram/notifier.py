from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from rich.console import Console
from hh_agent.config import settings

logger = logging.getLogger(__name__)
console = Console()


class TelegramNotifier:
    """Sends immediate alerts and structured batch summaries to Telegram."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.bot_token = bot_token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send message to configured Telegram chat."""
        if not self.base_url or not self.chat_id:
            # Fallback to local console log if Telegram is not configured
            console.print(f"[bold cyan][Telegram Fallback][/bold cyan]\n{text}")
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                )
                return res.status_code == 200
        except Exception as e:
            logger.warning("Failed to send Telegram message: %s", e)
            return False

    async def alert_invitation(
        self, company: str, vacancy: str, last_msg: str, drafted_reply: str
    ) -> None:
        """Send immediate notification about an interview invitation."""
        text = (
            f"🎯 <b>НОВОЕ ПРИГЛАШЕНИЕ НА СОБЕСЕДОВАНИЕ!</b>\n\n"
            f"🏢 <b>Компания:</b> {company}\n"
            f"💼 <b>Позиция:</b> {vacancy}\n\n"
            f"💬 <b>Сообщение от HR:</b>\n<i>{last_msg}</i>\n\n"
            f"✍️ <b>Подготовленный черновик ответа (NIM):</b>\n"
            f"<blockquote>{drafted_reply}</blockquote>"
        )
        await self.send_message(text)

    async def send_session_digest(
        self,
        stats: Dict[str, Any],
        top_vacancies: List[Dict[str, Any]],
        incoming_chats: List[Dict[str, Any]],
    ) -> None:
        """Send comprehensive batch digest (yesterday + today)."""
        lines = [
            "🚀 <b>ОТЧЕТ РАБОТЫ HH.RU HARNESS АГЕНТА</b>",
            f"Период: вчера + сегодня (окно 48ч)\n",
            "📊 <b>Статистика сессии:</b>",
            f"• Всего обработано вакансий: <b>{stats.get('processed_count', 0)}</b>",
            f"• Отсеяно стоп-словами / низким баллом: <b>{stats.get('skipped_count', 0)}</b>",
            f"• Высокий скоринг (прошли порог): <b>{stats.get('top_matches_count', 0)}</b>",
            f"• Отправлено откликов: <b>{stats.get('applied_count', 0)}</b>",
            f"• Входящих сообщений/приглашений: <b>{len(incoming_chats)}</b>\n",
        ]

        # Top vacancies
        if top_vacancies:
            lines.append("🌟 <b>ТОП-ВАКАНСИИ С ДОСЬЕ (NIM + QWEN):</b>\n")
            for idx, vac in enumerate(top_vacancies[:5], 1):
                salary = vac.get("salary_raw") or "ЗП не указана"
                score = vac.get("score", 0)
                title = vac.get("title", "")
                company = vac.get("company_name", "")
                url = vac.get("url", "")
                verdict = vac.get("verdict", "")

                lines.append(
                    f"{idx}. <b>{title}</b> ({score}/100)\n"
                    f"🏢 {company} | 💰 {salary}\n"
                    f"💡 <i>Вердикт:</i> {verdict}\n"
                    f"🔗 <a href='{url}'>Открыть вакансию на hh.ru</a>\n"
                )

        # Incoming messages
        if incoming_chats:
            lines.append("📨 <b>ВХОДЯЩИЕ ДИАЛОГИ И ПРИГЛАШЕНИЯ:</b>\n")
            for chat in incoming_chats[:5]:
                cat = chat.get("classification", "OTHER")
                comp = chat.get("company_name", "")
                pos = chat.get("vacancy_title", "")
                draft = chat.get("drafted_response", "")

                lines.append(
                    f"• [{cat}] <b>{comp}</b> — {pos}\n"
                    f"<i>Черновик ответа готов в базе</i>\n"
                )

        full_text = "\n".join(lines)

        # Always save markdown copy locally as well
        digest_file = settings.db_path.parent / "latest_session_digest.md"
        with open(digest_file, "w", encoding="utf-8") as f:
            f.write(full_text.replace("<b>", "**").replace("</b>", "**").replace("<i>", "*").replace("</i>", "*"))

        await self.send_message(full_text)
