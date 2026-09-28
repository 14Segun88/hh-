from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional
from hh_agent.core.harness.loader import HarnessLoader
from hh_agent.core.harness.models import ScenarioSpec, TaskDefinition
from hh_agent.core.harness.prompt_builder import PromptBuilder
from hh_agent.core.llm.local_client import LocalQwenClient
from hh_agent.core.llm.nim_client import NvidiaNimClient

logger = logging.getLogger(__name__)


class TaskRunner:
    """
    Executes Atomic Tasks with strict model routing, schema enforcement,
    and code-level safety boundaries (allowed_effects).
    """

    def __init__(
        self,
        loader: HarnessLoader,
        local_client: LocalQwenClient,
        nim_client: NvidiaNimClient,
    ):
        self.loader = loader
        self.local_client = local_client
        self.nim_client = nim_client
        self.prompt_builder = PromptBuilder(loader)

    async def run_score_vacancy(
        self, vacancy_title: str, vacancy_description: str
    ) -> Dict[str, Any]:
        """Execute score_vacancy task on Local Qwen (0 external effects)."""
        task = self.loader.tasks.get("score_vacancy")
        if not task:
            raise ValueError("Task 'score_vacancy' not found in config/tasks/")

        messages = self.prompt_builder.build_score_vacancy_prompt(
            vacancy_title=vacancy_title,
            vacancy_description=vacancy_description,
        )

        # Route to Local Qwen
        raw_content = await self.local_client._chat_completion(messages, temperature=0.1)
        parsed = self.local_client._extract_json_block(raw_content)

        return {
            "task_id": task.id,
            "model_used": "local_qwen",
            "result": parsed,
            "allowed_effects": task.allowed_effects,
        }

    async def run_draft_reply(
        self,
        context_type: str,
        target_text: str,
        company_name: str,
        scenario_id: str = "cover_letter",
    ) -> Dict[str, Any]:
        """Execute draft_reply task on NVIDIA NIM."""
        task = self.loader.tasks.get("draft_reply")
        if not task:
            raise ValueError("Task 'draft_reply' not found in config/tasks/")

        scenario = self.loader.specs.get_scenario(scenario_id)
        messages = self.prompt_builder.build_draft_reply_prompt(
            context_type=context_type,
            target_text=target_text,
            company_name=company_name,
            scenario_id=scenario_id,
        )

        # Route to Cloud NVIDIA NIM
        raw_content = await self.nim_client._chat_completion(messages, temperature=0.3)
        parsed = self.nim_client._extract_json_block(raw_content)

        return {
            "task_id": task.id,
            "model_used": "nvidia_nim",
            "scenario": scenario_id,
            "approval_policy": scenario.approval if scenario else "none",
            "result": parsed,
            "allowed_effects": task.allowed_effects,
        }

    async def run_solve_form(
        self, questions: list[str]
    ) -> Dict[str, Any]:
        """Execute solve_form task on Local Qwen with strict factual grounding."""
        task = self.loader.tasks.get("solve_form")
        if not task:
            raise ValueError("Task 'solve_form' not found in config/tasks/")

        messages = self.prompt_builder.build_solve_form_prompt(questions=questions)
        raw_content = await self.local_client._chat_completion(messages, temperature=0.1)
        parsed = self.local_client._extract_json_block(raw_content)

        return {
            "task_id": task.id,
            "model_used": "local_qwen",
            "result": parsed,
            "allowed_effects": task.allowed_effects,
        }
