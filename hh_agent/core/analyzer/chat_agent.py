from __future__ import annotations

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
            classification: MessageClassification = (
                await self.local_client.classify_message(
                    message_text=last_message,
                    vacancy_title=vacancy_title,
                    company_name=company,
                )
            )
        except Exception as e:
            logger.warning("Local Qwen classification error on topic %s: %s", topic_id, e)
            classification = MessageClassification(
                category="OTHER",
                short_summary=last_message[:100],
            )

        drafted_reply = ""
        status = "UNREAD"

        # -------------------------------------------------------------
        # Tier 2: Deep NVIDIA NIM Response Drafting (Invitations & Questions)
        # -------------------------------------------------------------
        if classification.category in ("INVITATION", "QUESTION"):
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
                logger.error("NIM reply drafting error on topic %s: %s", topic_id, e)
                drafted_reply = "Добрый день! Спасибо за обратную связь. Готов обсудить детали."

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
