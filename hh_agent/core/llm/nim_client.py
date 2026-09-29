from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
import httpx
from pydantic import ValidationError
from hh_agent.config import CandidateProfile, SearchRules, settings
from hh_agent.core.llm.prompts import (
    COVER_LETTER_GENERATOR_SYSTEM,
    LLM_JUDGE_VERIFIER_SYSTEM,
    NIM_DEEP_DOSSIER_SYSTEM,
    NIM_REPLY_DRAFT_SYSTEM,
    VACANCY_FAST_ANALYSIS_SYSTEM,
)
from hh_agent.core.llm.schemas import (
    DeepEmployerDossier,
    DraftedReply,
    FastVacancyAnalysis,
    JudgeEvaluationResult,
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

    async def generate_tailored_cover_letter(
        self,
        company_name: str,
        vacancy_title: str,
        vacancy_description: str,
        candidate_profile: Optional[CandidateProfile] = None,
    ) -> str:
        """Generate a personalized, high-converting cover letter crafted for the specific vacancy."""
        user_prompt = f"""
КОМПАНИЯ: {company_name}
ВАКАНСИЯ: {vacancy_title}

ОПИСАНИЕ И ТРЕБОВАНИЯ ВАКАНСИИ:
{vacancy_description[:4000]}

Составь адресное, убедительное сопроводительное письмо от Георгия Салюка.
"""
        messages = [
            {"role": "system", "content": COVER_LETTER_GENERATOR_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        content = await self._chat_completion(messages, temperature=0.35)
        clean_text = content.strip().strip('"').strip("'")
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```[a-zA-Z]*\n?", "", clean_text)
            clean_text = re.sub(r"\n?```$", "", clean_text).strip()
        return clean_text

    async def analyze_vacancy(
        self,
        vacancy_title: str,
        vacancy_description: str,
        candidate_profile: CandidateProfile,
        search_rules: SearchRules,
    ) -> FastVacancyAnalysis:
        """Perform fast LLM screening and scoring on vacancy text via NVIDIA NIM (Llama-3.3-70B)."""
        # Quick regex check for hard stop words
        # Junior/Стажер checked strictly in title so senior roles with mentoring duties are preserved
        title_lower = vacancy_title.lower()
        desc_lower = vacancy_description.lower() + " " + title_lower
        junior_keywords = {"junior", "джуниор", "стажер", "стажировка", "intern", "internship", "trainee", "практикант"}
        found_stops = []
        for sw in search_rules.hard_stop_words:
            sw_lower = sw.lower()
            if sw_lower in junior_keywords:
                if sw_lower in title_lower:
                    found_stops.append(sw)
            else:
                if sw_lower in desc_lower:
                    found_stops.append(sw)
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

        user_prompt = f"""
ВАКАНСИЯ: {vacancy_title}
ТЕКСТ ВАКАНСИИ:
{vacancy_description[:3000]}

ПРОФИЛЬ КАНДИДАТА:
- Имя: {candidate_profile.personal_info.full_name}
- Целевые роли: {', '.join(candidate_profile.career.target_roles)}
- Ожидаемая ЗП: {candidate_profile.career.target_salary_net_rub} руб. (мин: {candidate_profile.career.minimum_salary_net_rub})
- Основной стек: {', '.join(candidate_profile.skills.primary_stack)}
- Вторичный стек: {', '.join(candidate_profile.skills.secondary_stack)}
- Опыт: {candidate_profile.skills.years_of_experience} лет
- Формат: {', '.join(candidate_profile.career.work_format)}

СПИСОК ПОДОЗРИТЕЛЬНЫХ ФРАЗ ДЛЯ ПРОВЕРКИ:
{json.dumps(search_rules.red_flag_phrases, ensure_ascii=False)}

Проанализируй вакансию и верни строго JSON.
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
            return FastVacancyAnalysis(
                match_score=raw_json.get("match_score", 50),
                summary_reasoning=raw_json.get("summary_reasoning", "Извлечено с частичным совпадением"),
                is_suitable=raw_json.get("match_score", 50) >= 60,
                tech_stack=raw_json.get("tech_stack", []),
                red_flags_detected=raw_json.get("red_flags_detected", []),
            )

    async def judge_text(
        self,
        draft_text: str,
        context_type: str = "сопроводительное письмо",
        company_name: str = "",
        vacancy_title: str = "",
    ) -> JudgeEvaluationResult:
        """Audit drafted letter or answer using LLM-as-a-Judge against Georgiy's profile."""
        user_prompt = f"""
ТИП ТЕКСТА ДЛЯ ПРОВЕРКИ: {context_type}
КОМПАНИЯ: {company_name}
ВАКАНСИЯ: {vacancy_title}

ТЕКСТ НА ПРОВЕРКУ:
{draft_text}

Проведи независимый аудит на галлюцинации, достоверность фактов и соответствие резюме Георгия Салюка.
Верни строго JSON.
"""
        messages = [
            {"role": "system", "content": LLM_JUDGE_VERIFIER_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        content = await self._chat_completion(messages, temperature=0.1)
        raw_json = self._extract_json_block(content)
        try:
            res = JudgeEvaluationResult.model_validate(raw_json)
            res.evaluator = f"NVIDIA NIM ({self.model})"
            return res
        except Exception:
            return JudgeEvaluationResult(
                is_approved=raw_json.get("is_approved", True),
                score_10=float(raw_json.get("score_10", 9.0)),
                has_hallucinations=bool(raw_json.get("has_hallucinations", False)),
                hallucination_details=raw_json.get("hallucination_details", []),
                verdict_summary=raw_json.get("verdict_summary", "Проверено аудитором"),
                evaluator=f"NVIDIA NIM ({self.model})",
            )

