from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
import httpx
from pydantic import ValidationError
from hh_agent.config import CandidateProfile, SearchRules, settings
from hh_agent.core.llm.prompts import (
    MESSAGE_CLASSIFICATION_SYSTEM,
    QUESTIONNAIRE_PARSER_SYSTEM,
    VACANCY_FAST_ANALYSIS_SYSTEM,
)
from hh_agent.core.llm.schemas import (
    FastVacancyAnalysis,
    MessageClassification,
    QuestionnaireSolution,
)


class LocalQwenClient:
    """Tier 1: Fast local inference via LM Studio (Qwen 2.5 7B / VL 7B)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = (base_url or settings.lm_studio_url).rstrip("/")
        self.model = model or settings.lm_studio_model
        self.timeout = timeout or settings.lm_studio_timeout

    def _extract_json_block(self, text: str) -> Dict[str, Any]:
        """Safely extract and parse JSON object from LLM response."""
        text = text.strip()
        # Look for ```json ... ``` blocks
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find first '{' and last '}'
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # Fallback to direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise ValueError(f"Could not parse valid JSON from local LLM output: {text[:200]}") from err

    async def check_health(self) -> bool:
        """Check if LM Studio server is running and accessible."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{self.base_url}/models")
                return res.status_code == 200
        except Exception:
            return False

    async def get_available_models(self) -> List[str]:
        """Fetch list of loaded models in LM Studio."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{self.base_url}/models")
                if res.status_code == 200:
                    data = res.json()
                    return [m.get("id", "") for m in data.get("data", [])]
        except Exception:
            pass
        return []

    async def _resolve_active_model(self) -> str:
        """Resolve active LLM model loaded in LM Studio."""
        available = await self.get_available_models()
        llms = [m for m in available if "embed" not in m.lower()]
        if not llms:
            return self.model
        # Check if current configured model is among loaded
        for m in llms:
            if self.model.lower() in m.lower():
                return m
        # Default to first active loaded LLM
        return llms[0]

    async def _chat_completion(
        self, messages: List[Dict[str, str]], temperature: float = 0.2
    ) -> str:
        """Send chat completion request to LM Studio with auto-detected model name."""
        active_model = await self._resolve_active_model()
        payload = {
            "model": active_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def analyze_vacancy(
        self,
        vacancy_title: str,
        vacancy_description: str,
        candidate_profile: CandidateProfile,
        search_rules: SearchRules,
    ) -> FastVacancyAnalysis:
        """Perform Tier 1 fast extraction and preliminary scoring on vacancy text."""
        # 1. Quick regex/string check for hard stop words (zero token cost)
        desc_lower = vacancy_description.lower() + " " + vacancy_title.lower()
        found_stops = [
            sw for sw in search_rules.hard_stop_words if sw.lower() in desc_lower
        ]
        if found_stops:
            return FastVacancyAnalysis(
                salary_min=None,
                salary_max=None,
                currency="RUR",
                tech_stack=[],
                red_flags_detected=[],
                stop_phrases_found=found_stops,
                match_score=0,
                summary_reasoning=f"Мгновенный отсев: обнаружены стоп-слова ({', '.join(found_stops)})",
                is_suitable=False,
            )

        # 2. Local Qwen 2.5 prompt
        user_prompt = f"""
ВАКАНСИЯ: {vacancy_title}
ТЕКСТ ВАКАНСИИ:
{vacancy_description[:3000]}

ПРОФИЛЬ КАНДИДАТА:
- Целевые роли: {', '.join(candidate_profile.career.target_roles)}
- Ожидаемая ЗП: {candidate_profile.career.target_salary_net_rub} руб. (мин: {candidate_profile.career.minimum_salary_net_rub})
- Основной стек: {', '.join(candidate_profile.skills.primary_stack)}
- Вторичный стек: {', '.join(candidate_profile.skills.secondary_stack)}
- Опыт: {candidate_profile.skills.years_of_experience} лет
- Формат: {', '.join(candidate_profile.career.work_format)}

СПИСОК ПОДОЗРИТЕЛЬНЫХ ФРАЗ ДЛЯ ПРОВЕРКИ:
{json.dumps(search_rules.red_flag_phrases, ensure_ascii=False)}

Проанализируй вакансию и верни JSON.
"""
        messages = [
            {"role": "system", "content": VACANCY_FAST_ANALYSIS_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        content = await self._chat_completion(messages, temperature=0.1)
        raw_json = self._extract_json_block(content)
        try:
            return FastVacancyAnalysis.model_validate(raw_json)
        except ValidationError:
            # Fallback if structure had partial mismatch
            return FastVacancyAnalysis(
                match_score=raw_json.get("match_score", 50),
                summary_reasoning=raw_json.get("summary_reasoning", "Извлечено с частичным совпадением"),
                is_suitable=raw_json.get("match_score", 50) >= 60,
                tech_stack=raw_json.get("tech_stack", []),
                red_flags_detected=raw_json.get("red_flags_detected", []),
            )

    async def classify_message(
        self,
        message_text: str,
        vacancy_title: str = "",
        company_name: str = "",
    ) -> MessageClassification:
        """Classify incoming negotiation message."""
        user_prompt = f"""
КОМПАНИЯ: {company_name}
ВАКАНСИЯ: {vacancy_title}
ТЕКСТ СООБЩЕНИЯ ОТ РАБОТОДАТЕЛЯ:
{message_text}

Классифицируй сообщение и верни JSON.
"""
        messages = [
            {"role": "system", "content": MESSAGE_CLASSIFICATION_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        content = await self._chat_completion(messages, temperature=0.1)
        raw_json = self._extract_json_block(content)
        try:
            return MessageClassification.model_validate(raw_json)
        except Exception:
            return MessageClassification(
                category="OTHER",
                short_summary=message_text[:120],
            )

    async def parse_questionnaire_facts(
        self,
        questions: List[str],
        candidate_profile: CandidateProfile,
    ) -> QuestionnaireSolution:
        """Map profile facts to standard screening questions."""
        user_prompt = f"""
ВОПРОСЫ РАБОТОДАТЕЛЯ:
{json.dumps(questions, ensure_ascii=False, indent=2)}

ФАКТЫ ИЗ ПРОФИЛЯ КАНДИДАТА:
{json.dumps(candidate_profile.model_dump(), ensure_ascii=False, indent=2)}

Подставь ответы на фактологические вопросы. Верни JSON.
"""
        messages = [
            {"role": "system", "content": QUESTIONNAIRE_PARSER_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        content = await self._chat_completion(messages, temperature=0.1)
        raw_json = self._extract_json_block(content)
        try:
            return QuestionnaireSolution.model_validate(raw_json)
        except Exception:
            return QuestionnaireSolution(
                answers={},
                requires_manual_check=True,
                notes="Требуется ручное заполнение",
            )
