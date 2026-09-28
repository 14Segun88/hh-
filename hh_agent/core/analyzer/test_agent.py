from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from hh_agent.config import CandidateProfile
from hh_agent.core.harness.loader import HarnessLoader
from hh_agent.core.harness.task_runner import TaskRunner
from hh_agent.core.llm.local_client import LocalQwenClient
from hh_agent.core.llm.nim_client import NvidiaNimClient
from hh_agent.core.llm.schemas import QuestionnaireSolution
from hh_agent.core.storage.db import Database

logger = logging.getLogger(__name__)


class TestQuestionnaireAgent:
    """Two-tier test & questionnaire solver grounded in PRD facts and Specs."""

    def __init__(
        self,
        local_client: LocalQwenClient,
        nim_client: NvidiaNimClient,
        db: Database,
        profile: CandidateProfile,
        harness_loader: Optional[HarnessLoader] = None,
    ):
        self.local_client = local_client
        self.nim_client = nim_client
        self.db = db
        self.profile = profile
        self.harness_loader = harness_loader or HarnessLoader()
        self.task_runner = TaskRunner(
            loader=self.harness_loader,
            local_client=self.local_client,
            nim_client=self.nim_client,
        )

    async def solve_questionnaire(
        self,
        vacancy_id: str,
        vacancy_title: str,
        questions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        1. Atomic Task solve_form: Qwen maps verified PRD facts to questions.
        2. Unanswered open-ended questions are routed to NIM.
        3. Form answers are stored in DB.
        """
        question_texts = [q.get("text", "") for q in questions if q.get("text")]

        final_answers: Dict[str, str] = {}
        requires_human = False

        # Tier 1: Task solve_form (Local Qwen grounded in PRD facts)
        try:
            form_res = await self.task_runner.run_solve_form(questions=question_texts)
            parsed = form_res["result"]
            final_answers = parsed.get("answers", {})
            requires_human = parsed.get("requires_human", False)
            unanswered_texts = parsed.get("missing_facts", [])
        except Exception as e:
            logger.warning("Harness solve_form error, falling back: %s", e)
            qwen_solution: QuestionnaireSolution = (
                await self.local_client.parse_questionnaire_facts(
                    questions=question_texts,
                    candidate_profile=self.profile,
                )
            )
            final_answers = dict(qwen_solution.answers)
            requires_human = qwen_solution.requires_manual_check
            unanswered_texts = [
                text for text in question_texts
                if not any(text.lower() in k.lower() or k.lower() in text.lower() for k in final_answers.keys())
            ]

        # Tier 2: Open technical / situational questions -> NVIDIA NIM
        if unanswered_texts and not requires_human:
            try:
                nim_answers = await self.nim_client.solve_open_test_questions(
                    open_questions=unanswered_texts,
                    candidate_profile=self.profile,
                    vacancy_title=vacancy_title,
                )
                final_answers.update(nim_answers)
            except Exception as e:
                logger.error("NIM test answering error on vacancy %s: %s", vacancy_id, e)
                requires_human = True

        # Save to database
        await self.db.save_questionnaire(
            hh_vacancy_id=vacancy_id,
            questions=questions,
            answers=final_answers,
        )

        return {
            "vacancy_id": vacancy_id,
            "answers": final_answers,
            "requires_manual_check": requires_human,
        }
