from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from hh_agent.config import CandidateProfile
from hh_agent.core.llm.local_client import LocalQwenClient
from hh_agent.core.llm.nim_client import NvidiaNimClient
from hh_agent.core.llm.schemas import QuestionnaireSolution
from hh_agent.core.storage.db import Database

logger = logging.getLogger(__name__)


class TestQuestionnaireAgent:
    """Two-tier test & questionnaire solver: Qwen factual mapping -> NIM open technical questions."""

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

    async def solve_questionnaire(
        self,
        vacancy_id: str,
        vacancy_title: str,
        questions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        1. Local Qwen maps simple factual questions from candidate_profile.
        2. Unanswered / open-ended questions are sent to NVIDIA NIM for drafting.
        3. Answers are saved to DB.
        """
        question_texts = [q.get("text", "") for q in questions if q.get("text")]

        # Tier 1: Qwen factual answers
        qwen_solution: QuestionnaireSolution = (
            await self.local_client.parse_questionnaire_facts(
                questions=question_texts,
                candidate_profile=self.profile,
            )
        )

        final_answers: Dict[str, str] = dict(qwen_solution.answers)

        # Check for open/technical questions needing NIM
        unanswered_texts = [
            text for text in question_texts
            if not any(text.lower() in k.lower() or k.lower() in text.lower() for k in final_answers.keys())
        ]

        if unanswered_texts:
            try:
                nim_answers = await self.nim_client.solve_open_test_questions(
                    open_questions=unanswered_texts,
                    candidate_profile=self.profile,
                    vacancy_title=vacancy_title,
                )
                final_answers.update(nim_answers)
            except Exception as e:
                logger.error("NIM test answering error on vacancy %s: %s", vacancy_id, e)

        # Save to database
        await self.db.save_questionnaire(
            hh_vacancy_id=vacancy_id,
            questions=questions,
            answers=final_answers,
        )

        return {
            "vacancy_id": vacancy_id,
            "answers": final_answers,
            "requires_manual_check": qwen_solution.requires_manual_check or bool(unanswered_texts),
        }
