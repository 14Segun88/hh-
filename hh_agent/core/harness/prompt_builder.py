from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from hh_agent.core.harness.loader import HarnessLoader
from hh_agent.core.harness.models import ScenarioSpec, TaskDefinition


class PromptBuilder:
    """
    Assembles ultra-compact, grounded prompts by:
    - selecting only relevant tagged facts from PRD (preventing hallucinations)
    - attaching scenario constraints from Specs
    - injecting empirical feedback from lessons.md
    - maintaining a minimal token footprint for LM Studio.
    """

    def __init__(self, loader: HarnessLoader):
        self.loader = loader

    def build_score_vacancy_prompt(
        self,
        vacancy_title: str,
        vacancy_description: str,
    ) -> List[Dict[str, str]]:
        """Assemble lean prompt for task: score_vacancy (Qwen Local)."""
        prd = self.loader.prd
        # Filter facts relevant to candidate core competencies
        facts = prd.get_facts_by_tags(["ai", "agents", "llm", "rag", "ml", "python", "backend", "architecture", "reasoning", "automation", "core"])
        facts_text = "\n".join(f"- {f.text}" for f in facts)

        wants_summary = (
            f"Целевые роли: {', '.join(prd.wants.target_roles)}\n"
            f"Формат: {', '.join(prd.wants.format)}\n"
            f"Мин. зарплата: {prd.wants.salary_net_min} руб. net\n"
            f"Стоп-слова: {', '.join(prd.wants.stop_words)}"
        )

        system_msg = (
            "Ты — строгий технический скринер и эксперт по AI/LLM. Твоя задача — сопоставить вакансию с проверенными фактами кандидата.\n"
            "ПРАВИЛО: Опирайся ТОЛЬКО на предоставленные факты кандидата. Не додумывай несуществующий опыт.\n"
            "Верни СТРОГО валидный JSON без markdown:\n"
            "{\n"
            '  "salary_min": 200000 или null,\n'
            '  "salary_max": 280000 или null,\n'
            '  "currency": "RUR",\n'
            '  "tech_stack": ["Python", "AI Agents", "LLM", "RAG", "FastAPI"],\n'
            '  "red_flags": [],\n'
            '  "match_score": 88,\n'
            '  "summary_reasoning": "Четкое обоснование соответствия стека и задач",\n'
            '  "is_suitable": true\n'
            "}"
        )

        user_msg = (
            f"ВАКАНСИЯ: {vacancy_title}\n\n"
            f"ТЕКСТ ВАКАНСИИ:\n{vacancy_description[:2500]}\n\n"
            f"ТРЕБОВАНИЯ КАНДИДАТА (PRD WANTS):\n{wants_summary}\n\n"
            f"ПОДТВЕРЖДЕННЫЕ ФАКТЫ О КАНДИДАТЕ:\n{facts_text}\n"
        )

        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

    def build_draft_reply_prompt(
        self,
        context_type: str,
        target_text: str,
        company_name: str,
        scenario_id: str = "cover_letter",
    ) -> List[Dict[str, str]]:
        """Assemble prompt for task: draft_reply (NVIDIA NIM)."""
        prd = self.loader.prd
        scenario = self.loader.specs.get_scenario(scenario_id)
        lessons = self.loader.lessons

        # Select relevant facts
        facts = prd.get_facts_by_tags(["ai", "agents", "llm", "rag", "ml", "python", "backend", "portfolio", "code"])
        facts_text = "\n".join(f"- {f.text}" for f in facts)

        never_disclose_text = "\n".join(f"- {nd}" for f in prd.never_disclose for nd in [f])

        system_msg = (
            "Ты — карьерный агент кандидата. Твоя задача — составить сильное, естественное сообщение работодателю.\n\n"
            "ЖЕСТКИЕ ПРАВИЛА БЕЗОПАСНОСТИ:\n"
            "1. Используй ТОЛЬКО проверенные факты кандидата. Никаких выдуманных компаний или технологий!\n"
            "2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО разглашать:\n"
            f"{never_disclose_text}\n\n"
            f"ВЫВОДЫ ИЗ ПРАКТИКИ (LESSONS.MD):\n{lessons}\n\n"
            "Верни СТРОГО валидный JSON:\n"
            '{"reply_text": "...", "tone": "Деловой, уверенный", "key_points": ["..."]}'
        )

        user_msg = (
            f"КОНТЕКСТ: {context_type}\n"
            f"РАБОТОДАТЕЛЬ: {company_name}\n"
            f"ИСХОДНЫЙ ТЕКСТ (ВАКАНСИЯ / СООБЩЕНИЕ HR):\n{target_text[:3000]}\n\n"
            f"ПРОВЕРЕННЫЕ ФАКТЫ О КАНДИДАТЕ ИЗ PRD:\n{facts_text}\n\n"
            f"ОЖИДАНИЯ ПО ЗАРПЛАТЕ: от {prd.wants.salary_net_min} до {prd.wants.salary_net_target} руб. net\n"
        )

        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

    def build_solve_form_prompt(
        self,
        questions: List[str],
    ) -> List[Dict[str, str]]:
        """Assemble lean prompt for task: solve_form (Qwen Local)."""
        prd = self.loader.prd
        form_facts = prd.get_facts_by_tags(["forms", "legal", "general", "availability"])
        facts_text = "\n".join(f"- [{f.id}]: {f.text}" for f in form_facts)
        never_disclose_text = "\n".join(f"- {nd}" for nd in prd.never_disclose)

        system_msg = (
            "Ты — автоматический заполнитель анкет соискателя.\n"
            "ПРАВИЛА:\n"
            "1. Отвечай на вопросы ТОЛЬКО фактами из списка ниже.\n"
            "2. Если вопрос требует конфиденциальных данных (паспорт, ИНН, точный адрес) "
            "или сложного тестового кода — установи requires_human = true.\n"
            "3. Если вопрос не покрыт фактами — занеси его в missing_facts.\n\n"
            "СТРОГО ЗАПРЕЩЕННЫЕ ДАННЫЕ:\n"
            f"{never_disclose_text}\n\n"
            "Верни СТРОГО JSON:\n"
            '{"answers": {"вопрос 1": "ответ", ...}, "missing_facts": [], "requires_human": false}'
        )

        user_msg = (
            f"ВОПРОСЫ РАБОТОДАТЕЛЯ:\n{json.dumps(questions, ensure_ascii=False, indent=2)}\n\n"
            f"ДОСТУПНЫЕ ФАКТЫ ИЗ PRD:\n{facts_text}\n"
        )

        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
