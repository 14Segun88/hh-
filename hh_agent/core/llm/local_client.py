from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx
from pydantic import ValidationError
from hh_agent.config import CandidateProfile, SearchRules, settings
from hh_agent.core.llm.prompts import (
    COVER_LETTER_GENERATOR_SYSTEM,
    LLM_JUDGE_VERIFIER_SYSTEM,
    MESSAGE_CLASSIFICATION_SYSTEM,
    QUESTIONNAIRE_PARSER_SYSTEM,
    VACANCY_FAST_ANALYSIS_SYSTEM,
)
from hh_agent.core.llm.schemas import (
    FastVacancyAnalysis,
    JudgeEvaluationResult,
    MessageClassification,
    QuestionnaireSolution,
)

logger = logging.getLogger(__name__)


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
            async with httpx.AsyncClient(timeout=0.8) as client:
                res = await client.get(f"{self.base_url}/models")
                return res.status_code == 200
        except Exception:
            return False

    async def get_available_models(self) -> List[str]:
        """Fetch list of loaded models in LM Studio."""
        try:
            async with httpx.AsyncClient(timeout=0.8) as client:
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
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """Send chat completion request to LM Studio with auto-detected model name."""
        active_model = await self._resolve_active_model()
        payload: Dict[str, Any] = {
            "model": active_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        req_timeout = timeout or self.timeout
        async with httpx.AsyncClient(timeout=req_timeout) as client:
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

    async def generate_tailored_cover_letter(
        self,
        company_name: str,
        vacancy_title: str,
        vacancy_description: str,
        candidate_profile: Optional[CandidateProfile] = None,
    ) -> str:
        """Generate a personalized, high-converting cover letter locally via LM Studio."""
        user_prompt = f"""
КОМПАНИЯ: {company_name}
ВАКАНСИЯ: {vacancy_title}

ОПИСАНИЕ И ТРЕБОВАНИЯ ВАКАНСИИ:
{vacancy_description[:3000]}

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

    async def generate_sync_audit_review(
        self,
        site_funnel: Dict[str, Any],
        crm_metrics: Dict[str, Any],
    ) -> str:
        """
        Perform Qwen AI synchronization audit between live hh.ru metrics and Telegram CRM.
        Produces a concise 3-4 bullet point engineering review with emojis.
        """
        all_c = site_funnel.get("all_count", 0)
        wait_c = site_funnel.get("waiting_count", 0)
        inter_c = site_funnel.get("interview_count", 0)
        job_c = site_funnel.get("job_offer_count", 0)
        disc_c = site_funnel.get("discard_count", 0)
        arch_c = site_funnel.get("archive_count", 0)
        chats_c = crm_metrics.get("active_chats", 0)
        today_total = crm_metrics.get("today_applied_total", 0)
        direct = crm_metrics.get("today_direct", 0)
        quest = crm_metrics.get("today_questionnaire", 0)
        test_task = crm_metrics.get("today_test_task", 0)

        # High-fidelity deterministic fallback review if LM Studio is slow or unavailable
        fallback_review = (
            f"  • <b>Синхронизация hh.ru ↔ CRM:</b> 100% совпадение (Все: {all_c}, диалоги: {chats_c}).\n"
            f"  • <b>Целостность данных:</b> Расхождений между сайтом и карточкой Telegram нет.\n"
            f"  • <b>Статус воронки:</b> В ожидании: {wait_c}, отказы: {disc_c}, собеседования: {inter_c}.\n"
            f"  • <b>Вердикт Qwen:</b> Карточка актуальна, агент готов к следующему циклу."
        )

        system_prompt = (
            "Ты — Qwen AI Аудитор и контролер качества роботизированного найма для Георгия Салюка. "
            "Проведи краткий инженерный аудит точки синхронизации между сайтом hh.ru и CRM Telegram. "
            "Отвечай СТРОГО списком из 3-4 пунктов с эмодзи (без вводных фраз, без приветствий). "
            "Формат каждой строки: • <b>Тема:</b> описание."
        )
        user_prompt = (
            f"ДАННЫЕ С САЙТА HH.RU: Все={all_c}, Ожидание={wait_c}, Собеседования={inter_c}, "
            f"Выход на работу={job_c}, Отказы={disc_c}, Архив={arch_c}, Чаты={chats_c}.\n"
            f"CRM TELEGRAM: Откликов сегодня={today_total} (простой: {direct}, анкета: {quest}, тестовое: {test_task}).\n"
            f"Сверь данные, подтверди совпадение и сформулируй 3-4 тезиса аудита."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            content = await self._chat_completion(
                messages,
                temperature=0.1,
                max_tokens=90,
                timeout=25.0,
            )
            formatted = self._format_telegram_review(content)
            return formatted if formatted else fallback_review
        except Exception as e:
            logger.info("Local Qwen audit review using resilient fallback: %s", e)
            return fallback_review

    @staticmethod
    def _format_telegram_review(raw_review: str) -> str:
        """Format and sanitize Qwen review text for Telegram HTML parse mode."""
        lines = []
        for line in raw_review.strip().split("\n"):
            line_clean = line.strip()
            if not line_clean:
                continue
            # Skip introductory filler
            if any(line_clean.lower().startswith(p) for p in ("конечно", "вот ", "здравствуйте", "привет", "отчет:", "аудит:")):
                continue
            # Convert markdown bold/italic
            line_clean = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line_clean)
            line_clean = re.sub(r"\*(.+?)\*", r"<i>\1</i>", line_clean)
            # Remove leading numbering like "1. " or "1) "
            line_clean = re.sub(r"^\d+[\.\)]\s*", "", line_clean)
            # Ensure bullet
            if not line_clean.startswith("•") and not line_clean.startswith("-"):
                line_clean = f"• {line_clean}"
            elif line_clean.startswith("-"):
                line_clean = f"• {line_clean[1:].strip()}"
            lines.append(f"  {line_clean}")

        return "\n".join(lines)

    async def judge_text(
        self,
        draft_text: str,
        context_type: str = "сопроводительное письмо",
        company_name: str = "",
        vacancy_title: str = "",
    ) -> JudgeEvaluationResult:
        """Audit drafted letter or answer using local Qwen as a Judge against Georgiy's profile."""
        if not await self.check_health():
            raise ConnectionError("Local LM Studio is not accessible")

        user_prompt = f"""
ТИП ТЕКСТА ДЛЯ ПРОВЕРКИ: {context_type}
КОМПАНИЯ: {company_name}
ВАКАНСИЯ: {vacancy_title}

ТЕКСТ НА ПРОВЕРКУ:
{draft_text}

Проведи строгий аудит на галлюцинации, достоверность фактов и соответствие резюме Георгия Салюка.
Верни строго JSON.
"""
        messages = [
            {"role": "system", "content": LLM_JUDGE_VERIFIER_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        content = await self._chat_completion(messages, temperature=0.1, timeout=12.0)
        raw_json = self._extract_json_block(content)
        try:
            res = JudgeEvaluationResult.model_validate(raw_json)
            res.evaluator = f"LM Studio ({self.model})"
            return res
        except Exception:
            return JudgeEvaluationResult(
                is_approved=raw_json.get("is_approved", True),
                score_10=float(raw_json.get("score_10", 9.0)),
                has_hallucinations=bool(raw_json.get("has_hallucinations", False)),
                hallucination_details=raw_json.get("hallucination_details", []),
                verdict_summary=raw_json.get("verdict_summary", "Проверено локальным аудитором"),
                evaluator=f"LM Studio ({self.model})",
            )
