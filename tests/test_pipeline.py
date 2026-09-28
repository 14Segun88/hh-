import asyncio
import pytest
from pathlib import Path
from hh_agent.config import load_candidate_profile, load_search_rules
from hh_agent.core.storage.db import Database
from hh_agent.core.llm.schemas import (
    FastVacancyAnalysis,
    DeepEmployerDossier,
    MessageClassification,
    DraftedReply,
    QuestionnaireSolution,
)
from hh_agent.core.analyzer.vacancy_eval import VacancyEvaluator
from hh_agent.core.analyzer.chat_agent import ChatNegotiationAgent


class MockLocalQwenClient:
    async def analyze_vacancy(self, vacancy_title, vacancy_description, candidate_profile, search_rules):
        desc_lower = vacancy_description.lower() + " " + vacancy_title.lower()
        for sw in search_rules.hard_stop_words:
            if sw.lower() in desc_lower:
                return FastVacancyAnalysis(
                    match_score=0,
                    is_suitable=False,
                    stop_phrases_found=[sw],
                    summary_reasoning="Стоп-слово найдено",
                )
        return FastVacancyAnalysis(
            salary_min=280000,
            salary_max=360000,
            currency="RUR",
            tech_stack=["Python", "FastAPI", "PostgreSQL", "Docker"],
            red_flags_detected=[],
            stop_phrases_found=[],
            match_score=88,
            summary_reasoning="Отличное совпадение по стеку и зарплате",
            is_suitable=True,
        )

    async def classify_message(self, message_text, vacancy_title="", company_name=""):
        if "собеседован" in message_text.lower() or "созвон" in message_text.lower():
            return MessageClassification(
                category="INVITATION",
                is_urgent=True,
                extracted_questions=["Удобно ли завтра?"],
                proposed_dates_or_times=["завтра в 14:00"],
                short_summary="Приглашение на интервью",
            )
        return MessageClassification(
            category="OTHER",
            is_urgent=False,
            short_summary=message_text[:50],
        )

    def _extract_json_block(self, text: str):
        import json
        return json.loads(text)

    async def _chat_completion(self, messages, temperature=0.1):
        import json
        user_content = messages[-1]["content"] if messages else ""
        # Check if the vacancy itself (not the wants instructions) contains stop-words
        if "Junior Стажер" in user_content or "1C Developer" in user_content:
            return json.dumps({
                "salary_min": None,
                "salary_max": None,
                "currency": "RUR",
                "tech_stack": [],
                "red_flags": ["Стажировка"],
                "match_score": 0,
                "summary_reasoning": "Стоп-слова",
                "is_suitable": False,
            })
        return json.dumps({
            "salary_min": 280000,
            "salary_max": 360000,
            "currency": "RUR",
            "tech_stack": ["Python", "FastAPI", "PostgreSQL"],
            "red_flags": [],
            "match_score": 88,
            "summary_reasoning": "Отличное совпадение",
            "is_suitable": True,
        })

    async def parse_questionnaire_facts(self, questions, candidate_profile):
        return QuestionnaireSolution(
            answers={"Опыт": f"{candidate_profile.skills.years_of_experience} лет"},
            requires_manual_check=False,
        )


class MockNvidiaNimClient:
    def _extract_json_block(self, text: str):
        import json
        return json.loads(text)

    async def _chat_completion(self, messages, temperature=0.3):
        import json
        return json.dumps({
            "reply_text": "Добрый день! Имею более 6 лет опыта в Python бэкенде...",
            "tone": "Деловой, уверенный",
            "key_points": ["FastAPI", "PostgreSQL"],
        })

    async def generate_deep_dossier(self, vacancy_title, company_name, vacancy_description, fast_analysis, candidate_profile):
        return DeepEmployerDossier(
            company_overview="Крупная FinTech компания с современным стеком.",
            pros=["Белая зарплата", "ДМС", "Сильная команда"],
            cons_and_risks=["Высокая нагрузка"],
            salary_market_comparison="Выше рынка на 15%",
            interview_strategy="Уточнить архитектуру очередей сообщений и дежурства.",
            final_verdict="Рекомендуется откликаться",
            custom_cover_letter="Добрый день! Имею более 6 лет опыта в Python бэкенде...",
        )

    async def draft_negotiation_reply(self, incoming_message, classification, company_name, vacancy_title, candidate_profile):
        return DraftedReply(
            reply_text="Добрый день! Спасибо за приглашение, готов созвониться завтра в 14:00.",
            tone="Деловой",
        )


def test_config_loading():
    profile = load_candidate_profile()
    assert profile.skills.years_of_experience >= 1
    assert len(profile.skills.primary_stack) > 0

    rules = load_search_rules()
    assert len(rules.search.queries) > 0
    assert "Junior" in rules.hard_stop_words or "Стажер" in rules.hard_stop_words


@pytest.mark.asyncio
async def test_database_and_evaluator(tmp_path: Path):
    db_file = tmp_path / "test.db"
    db = Database(db_path=db_file)
    await db.init_db()

    profile = load_candidate_profile()
    rules = load_search_rules()

    local_mock = MockLocalQwenClient()
    nim_mock = MockNvidiaNimClient()

    evaluator = VacancyEvaluator(
        local_client=local_mock,
        nim_client=nim_mock,
        db=db,
        profile=profile,
        rules=rules,
    )

    # 1. Test suitable vacancy
    vac1 = {
        "hh_id": "12345678",
        "title": "Senior Python Backend Developer",
        "company_name": "Tech Corp",
        "company_url": "https://hh.ru/employer/1",
        "salary_raw": "от 300 000 руб.",
        "description": "Разработка микросервисов на FastAPI и PostgreSQL. Удаленно.",
        "url": "https://hh.ru/vacancy/12345678",
        "published_at": "Сегодня",
    }
    res1 = await evaluator.evaluate_vacancy(vac1)
    assert res1["status"] == "DOSSIER_READY"
    assert res1["record"]["score"] == 88
    assert "Рекомендуется откликаться" in res1["record"]["verdict"]
    assert "Добрый день!" in res1["cover_letter"]

    # Verify saved in DB
    exists = await db.vacancy_exists("12345678")
    assert exists is True

    # 2. Test stop-word vacancy (instant reject)
    vac2 = {
        "hh_id": "87654321",
        "title": "Junior Стажер 1C Developer",
        "company_name": "Old Corp",
        "salary_raw": "от 20 000 руб.",
        "description": "Ищем стажера для поддержки 1С Битрикс.",
        "url": "https://hh.ru/vacancy/87654321",
        "published_at": "Вчера",
    }
    res2 = await evaluator.evaluate_vacancy(vac2)
    assert res2["status"] == "SKIPPED"
    assert res2["record"]["score"] == 0

    # 3. Test chat agent
    chat_agent = ChatNegotiationAgent(
        local_client=local_mock,
        nim_client=nim_mock,
        db=db,
        profile=profile,
    )
    thread = {
        "hh_topic_id": "topic_999",
        "company_name": "Tech Corp",
        "vacancy_title": "Senior Python Backend Developer",
        "last_message_text": "Добрый день! Хотели бы пригласить вас на собеседование. Удобно ли завтра в 14:00?",
        "topic_url": "https://hh.ru/applicant/negotiations?topicId=topic_999",
    }
    chat_res = await chat_agent.process_incoming_thread(thread)
    assert chat_res["classification"].category == "INVITATION"
    assert chat_res["is_urgent"] is True
    assert "готов созвониться" in chat_res["drafted_reply"]

    # 4. Check stats summary
    stats = await db.get_stats_summary()
    assert stats["total_vacancies"] == 2
    assert stats["top_score_count"] == 1
    assert stats["invitations_count"] == 1
