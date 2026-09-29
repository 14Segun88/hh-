from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional
from hh_agent.config import CandidateProfile
from hh_agent.core.llm.local_client import LocalQwenClient
from hh_agent.core.llm.nim_client import NvidiaNimClient
from hh_agent.core.llm.schemas import DraftedReply, MessageClassification
from hh_agent.core.storage.db import Database

logger = logging.getLogger(__name__)


class ChatNegotiationAgent:
    """Two-tier negotiation agent: Qwen message classification -> NIM business reply drafting."""

    def __init__(
        self,
        local_client: LocalQwenClient,
        nim_client: NvidiaNimClient,
        db: Database,
        profile: CandidateProfile,
    ):
        self.local_client = local_client
        self.nim_client = nim_client
        self.db = db
        self.profile = profile

    async def process_incoming_thread(
        self, thread_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        1. Classify incoming message using Local Qwen.
        2. Draft response via NVIDIA NIM if it's an invite or inquiry.
        3. Store in DB.
        """
        topic_id = thread_data["hh_topic_id"]
        company = thread_data.get("company_name", "")
        vacancy_title = thread_data.get("vacancy_title", "")
        last_message = thread_data.get("last_message_text", "")

        # -------------------------------------------------------------
        # Tier 1: Local Qwen 2.5 7B Fast Message Classification
        # -------------------------------------------------------------
        try:
            classification: MessageClassification = await asyncio.wait_for(
                self.local_client.classify_message(
                    message_text=last_message,
                    vacancy_title=vacancy_title,
                    company_name=company,
                ),
                timeout=8.0,
            )
        except Exception as e:
            logger.warning("Local Qwen classification error/timeout on topic %s: %s", topic_id, e)
            category = "QUESTION" if ("?" in last_message or "анкет" in last_message.lower()) else "OTHER"
            classification = MessageClassification(
                category=category,
                short_summary=last_message[:100],
            )

        drafted_reply = ""
        status = "UNREAD"

        # -------------------------------------------------------------
        # Tier 2: Deep NVIDIA NIM Response Drafting (Invitations & Questions)
        # -------------------------------------------------------------
        if classification.category in ("INVITATION", "QUESTION", "OTHER"):
            try:
                reply_obj: DraftedReply = await self.nim_client.draft_negotiation_reply(
                    incoming_message=last_message,
                    classification=classification,
                    company_name=company,
                    vacancy_title=vacancy_title,
                    candidate_profile=self.profile,
                )
                drafted_reply = reply_obj.reply_text
                status = "DRAFTED"
            except Exception as e:
                logger.warning("NIM reply drafting error on topic %s: %s, using Qwen fallback", topic_id, e)
                try:
                    fallback_prompt = (
                        f"Ты карьерный агент Георгия Салюка (AI-инженер / LLM-разработчик). "
                        f"Работодатель {company} (вакансия {vacancy_title}) написал: «{last_message}». "
                        f"Напиши вежливый, уверенный и профессиональный ответ на русском языке. "
                        f"Факты: 3.5 года опыта, стек: Python, FastAPI, Llama-3.3, Weaviate RAG, Docker; "
                        f"проекты MOGE (оркестратор 8 агентов) и PD Document Analyzer. "
                        f"Ожидания: 220 000 руб. на руки, удаленно (Краснодар). Контакты: Telegram @Segun14, тел. +79180452504. "
                        f"Тон: деловой, дружелюбный, лаконичный. Верни ТОЛЬКО текст сообщения без кавычек и предисловий."
                    )
                    drafted_reply = await self.local_client._chat_completion(
                        messages=[{"role": "user", "content": fallback_prompt}],
                        temperature=0.3,
                    )
                    drafted_reply = drafted_reply.strip().strip('"')
                    status = "DRAFTED"
                except Exception as e2:
                    logger.error("Local fallback reply drafting error: %s", e2)
                    drafted_reply = (
                        f"Здравствуйте! Спасибо за обратную связь по позиции «{vacancy_title}». "
                        f"Я готов ответить на ваши вопросы и провести техническое интервью. "
                        f"Для оперативной связи: Telegram @Segun14 или телефон +7 (918) 045-25-04."
                    )
                    status = "DRAFTED"

        # Save to database
        record = {
            "hh_topic_id": topic_id,
            "company_name": company,
            "vacancy_title": vacancy_title,
            "vacancy_url": thread_data.get("topic_url", ""),
            "last_message_text": last_message,
            "last_message_sender": "employer",
            "last_message_time": "",
            "classification": classification.category,
            "extracted_questions": classification.extracted_questions,
            "extracted_dates": classification.proposed_dates_or_times,
            "drafted_response": drafted_reply,
            "status": status,
        }
        await self.db.save_negotiation(record)

        return {
            "record": record,
            "classification": classification,
            "drafted_reply": drafted_reply,
            "is_urgent": classification.is_urgent,
        }
