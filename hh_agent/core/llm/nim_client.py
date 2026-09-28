from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
import httpx
from pydantic import ValidationError
from hh_agent.config import CandidateProfile, settings
from hh_agent.core.llm.prompts import (
    NIM_DEEP_DOSSIER_SYSTEM,
    NIM_REPLY_DRAFT_SYSTEM,
)
from hh_agent.core.llm.schemas import (
    DeepEmployerDossier,
    DraftedReply,
    FastVacancyAnalysis,
    MessageClassification,
)


class NvidiaNimClient:
    """Tier 2: Deep reasoning & synthesis via NVIDIA NIM API (Llama 3.3 70B / Nemotron / R1)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.api_key = api_key or settings.nvidia_api_key
        self.base_url = (base_url or settings.nvidia_base_url).rstrip("/")
        self.model = model or settings.nvidia_model
        self.timeout = timeout or settings.nvidia_timeout

    def _extract_json_block(self, text: str) -> Dict[str, Any]:
        """Safely extract and parse JSON object from LLM response."""
        text = text.strip()
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise ValueError(f"Could not parse valid JSON from NIM output: {text[:200]}") from err

    async def check_health(self) -> bool:
        """Verify NVIDIA NIM API credentials and availability."""
        if not self.api_key:
            return False
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(f"{self.base_url}/models", headers=headers)
                return res.status_code in (200, 201)
        except Exception:
            return False

    async def _chat_completion(
        self, messages: List[Dict[str, str]], temperature: float = 0.3
    ) -> str:
        """Call NVIDIA NIM API with streaming turned off and proper headers."""
        if not self.api_key:
            raise ValueError("NVIDIA_API_KEY is not configured in .env or environment")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": 0.9,
            "max_tokens": 2048,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def generate_deep_dossier(
        self,
        vacancy_title: str,
        company_name: str,
        vacancy_description: str,
        fast_analysis: FastVacancyAnalysis,
        candidate_profile: CandidateProfile,
    ) -> DeepEmployerDossier:
        """Create a thorough dossier on the company, pros/risks, interview strategy, and tailored cover letter."""
        user_prompt = f"""
РАБОТОДАТЕЛЬ: {company_name}
ВАКАНСИЯ: {vacancy_title}

ТЕКСТ ВАКАНСИИ:
{vacancy_description[:4000]}

ПРЕДВАРИТЕЛЬНЫЙ АНАЛИЗ ЛОКАЛЬНОЙ МОДЕЛИ (QWEN):
- Оценка соответствия: {fast_analysis.match_score}/100
- Стек: {', '.join(fast_analysis.tech_stack)}
- Обнаруженные красные флаги: {', '.join(fast_analysis.red_flags_detected) or 'не обнаружены'}
- Резюме оценки: {fast_analysis.summary_reasoning}

ОПЫТ И ПРОФИЛЬ КАНДИДАТА:
- Имя: {candidate_profile.personal_info.full_name}
- Целевой доход: {candidate_profile.career.target_salary_net_rub} руб.
- Ключевой опыт: {candidate_profile.experience_summary}
- Стек: {', '.join(candidate_profile.skills.primary_stack + candidate_profile.skills.secondary_stack)}
- Формат: {', '.join(candidate_profile.career.work_format)}

Сформируй глубокое досье, финальный вердикт и напиши естественное сильное сопроводительное письмо без клише. Верни JSON.
"""
        messages = [
            {"role": "system", "content": NIM_DEEP_DOSSIER_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        content = await self._chat_completion(messages, temperature=0.3)
        raw_json = self._extract_json_block(content)
        try:
            return DeepEmployerDossier.model_validate(raw_json)
        except ValidationError:
            return DeepEmployerDossier(
                company_overview=raw_json.get("company_overview", ""),
                pros=raw_json.get("pros", []),
                cons_and_risks=raw_json.get("cons_and_risks", []),
                salary_market_comparison=raw_json.get("salary_market_comparison", ""),
                interview_strategy=raw_json.get("interview_strategy", ""),
                final_verdict=raw_json.get("final_verdict", "Рекомендуется откликаться"),
                custom_cover_letter=raw_json.get("custom_cover_letter", ""),
            )

    async def draft_negotiation_reply(
        self,
        incoming_message: str,
        classification: MessageClassification,
        company_name: str,
        vacancy_title: str,
        candidate_profile: CandidateProfile,
    ) -> DraftedReply:
        """Draft a polite, confident, high-stakes reply in business Russian."""
        user_prompt = f"""
РАБОТОДАТЕЛЬ: {company_name}
ВАКАНСИЯ: {vacancy_title}

ВХОДЯЩЕЕ СООБЩЕНИЕ:
{incoming_message}

КЛАССИФИКАЦИЯ (Tier 1):
- Категория: {classification.category}
- Срочность: {classification.is_urgent}
- Заданные вопросы: {json.dumps(classification.extracted_questions, ensure_ascii=False)}
- Предложенные слоты: {json.dumps(classification.proposed_dates_or_times, ensure_ascii=False)}

ФАКТЫ О КАНДИДАТЕ:
- Имя: {candidate_profile.personal_info.full_name}
- Зарплатные ожидания: от {candidate_profile.career.minimum_salary_net_rub} до {candidate_profile.career.target_salary_net_rub} руб. на руки
- Контакты для связи: Telegram {candidate_profile.personal_info.contact_telegram}, телефон {candidate_profile.personal_info.contact_phone}
- Формат: {', '.join(candidate_profile.career.work_format)}

Составь идеальный черновик ответа в деловом русском тоне. Верни JSON.
"""
        messages = [
            {"role": "system", "content": NIM_REPLY_DRAFT_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        content = await self._chat_completion(messages, temperature=0.3)
        raw_json = self._extract_json_block(content)
        try:
            return DraftedReply.model_validate(raw_json)
        except Exception:
            return DraftedReply(
                reply_text=raw_json.get("reply_text", "Добрый день! Спасибо за приглашение. Готов обсудить детали."),
                tone="Деловой",
            )

    async def solve_open_test_questions(
        self,
        open_questions: List[str],
        candidate_profile: CandidateProfile,
        vacancy_title: str,
    ) -> Dict[str, str]:
        """Draft professional responses to technical or behavioral screening questions."""
        user_prompt = f"""
ВАКАНСИЯ: {vacancy_title}

ВОПРОСЫ РАБОТОДАТЕЛЯ:
{json.dumps(open_questions, ensure_ascii=False, indent=2)}

ОПЫТ И СТЕК КАНДИДАТА:
{candidate_profile.experience_summary}
Стек: {', '.join(candidate_profile.skills.primary_stack)}

Дай краткие, предметные и технически грамотные ответы от первого лица разработчика.
Верни JSON: {{"answers": {{"вопрос 1": "ответ 1", ...}}}}
"""
        messages = [
            {
                "role": "system",
                "content": "Ты — опытный инженер, дающий четкие ответы на технические и скрининг-вопросы.",
            },
            {"role": "user", "content": user_prompt},
        ]
        content = await self._chat_completion(messages, temperature=0.2)
        raw_json = self._extract_json_block(content)
        return raw_json.get("answers", {})
