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
        title_lower = vacancy_title.lower()
        desc_lower = vacancy_description.lower() + " " + title_lower
        junior_keywords = {"junior", "джуниор", "стажер", "стажировка", "intern", "internship", "trainee", "практикант"}
        for sw in search_rules.hard_stop_words:
            sw_lower = sw.lower()
            if sw_lower in junior_keywords:
                if sw_lower in title_lower:
                    return FastVacancyAnalysis(
                        match_score=0,
                        is_suitable=False,
                        stop_phrases_found=[sw],
                        summary_reasoning="Стоп-слово найдено в названии",
                    )
            else:
                if sw_lower in desc_lower:
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

    async def generate_sync_audit_review(self, site_funnel, crm_metrics):
        return (
            "  • <b>Синхронизация hh.ru ↔ CRM:</b> 100% совпадение (Все: 3, диалоги: 0).\n"
            "  • <b>Целостность данных:</b> Расхождений между сайтом и Telegram нет.\n"
            "  • <b>Вердикт Qwen:</b> Воронка актуальна, агент готов к следующему циклу."
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

    # 5. Check CRM metrics accuracy (strictly real green badges, no dummy fallbacks or plain replies)
    crm_metrics = await db.get_crm_metrics()
    assert crm_metrics["total_invitations"] == 0  # In chat (DRAFTED), not yet green badge on hh.ru
    assert crm_metrics["active_chats"] == 1       # Active chat dialogue
    assert crm_metrics["total_rejections"] == 0   # No rejections
    assert crm_metrics["days_active"] >= 1

    # When hh.ru sets the official green badge 'СОБЕСЕДОВАНИЕ'
    await db.save_negotiation({
        "hh_topic_id": "topic_999",
        "company_name": "Tech Corp",
        "vacancy_title": "Senior Python Backend Developer",
        "status": "СОБЕСЕДОВАНИЕ",
    })
    crm_metrics_after = await db.get_crm_metrics()
    assert crm_metrics_after["total_invitations"] == 1


@pytest.mark.asyncio
async def test_green_badge_status_extraction():
    from unittest.mock import AsyncMock, MagicMock
    from hh_agent.core.browser.negotiations import NegotiationsBrowser

    browser = NegotiationsBrowser(page=None)

    # 1. Card with green interview badge
    card_interview = MagicMock()
    card_interview.locator = MagicMock(side_effect=lambda sel: MagicMock(
        count=AsyncMock(return_value=1 if "interview" in sel else 0),
        inner_text=AsyncMock(return_value="Собеседование"),
    ))
    status = await browser._extract_status_from_card(card_interview)
    assert status == "СОБЕСЕДОВАНИЕ"

    # 2. Card with discard badge
    card_discard = MagicMock()
    card_discard.locator = MagicMock(side_effect=lambda sel: MagicMock(
        count=AsyncMock(return_value=1 if "discard" in sel else 0),
        inner_text=AsyncMock(return_value="Отказ"),
    ))
    status = await browser._extract_status_from_card(card_discard)
    assert status == "ОТКАЗ"

    # 3. Card without status badge (plain application)
    card_plain = MagicMock()
    card_plain.locator = MagicMock(side_effect=lambda sel: MagicMock(
        count=AsyncMock(return_value=0),
    ))
    status = await browser._extract_status_from_card(card_plain)
    assert status == "ОТКЛИК"


def test_questionnaire_answer_resolver():
    from hh_agent.core.live_runner import LiveVisualRunner
    runner = LiveVisualRunner()

    # 1. Salary questions
    ans_sal_num = runner._resolve_question_answer("Желаемый уровень зарплаты, руб", is_textarea=False, is_numeric=True)
    assert ans_sal_num == "220000"
    ans_sal_text = runner._resolve_question_answer("Укажите ваши зарплатные ожидания", is_textarea=True)
    assert "220 000" in ans_sal_text

    # 2. Experience questions
    ans_exp_num = runner._resolve_question_answer("Сколько лет релевантного опыта?", is_numeric=True)
    assert ans_exp_num == "4"
    ans_exp_text = runner._resolve_question_answer("Опишите ваш опыт в IT", is_textarea=True)
    assert "3.5 года" in ans_exp_text

    # 3. Portfolio / GitHub / AI Prototyping (DEREVO PARK scenario)
    ans_portfolio = runner._resolve_question_answer("Приложите ссылку на портфолио или GitHub с вашими проектами", is_textarea=True)
    assert "github.com/14Segun88" in ans_portfolio
    assert "MOGE" in ans_portfolio

    ans_ai_proto = runner._resolve_question_answer("Какой у вас опыт в AI-прототипировании и агентных системах?", is_textarea=True)
    assert "MOGE" in ans_ai_proto
    assert "PD Document Analyzer" in ans_ai_proto

    # 4. Contacts and location
    ans_phone = runner._resolve_question_answer("Контактный телефон для связи")
    assert "+7 (918) 045-25-04" in ans_phone
    ans_tg = runner._resolve_question_answer("Ваш Telegram")
    assert "@saljuk_gm" in ans_tg
    ans_loc = runner._resolve_question_answer("Ваш город проживания / формат работы")
    assert "Краснодар" in ans_loc


@pytest.mark.asyncio
async def test_funnel_metrics_db_and_dashboard(tmp_path: Path):
    from hh_agent.core.telegram.crm_bot import TelegramCrmBot

    db_file = tmp_path / "test_funnel.db"
    db = Database(db_path=db_file)
    await db.init_db()

    # Save funnel metrics
    funnel_data = {
        "all_count": 3,
        "interview_count": 1,
        "job_offer_count": 0,
        "waiting_count": 2,
        "discard_count": 0,
        "archive_count": 39,
    }
    await db.save_funnel_metrics(funnel_data)

    retrieved = await db.get_funnel_metrics()
    assert retrieved == funnel_data

    metrics = await db.get_crm_metrics()
    assert metrics["funnel_all"] == 3
    assert metrics["funnel_interview"] == 1
    assert metrics["funnel_job_offer"] == 0
    assert metrics["funnel_waiting"] == 2
    assert metrics["funnel_discard"] == 0
    assert metrics["funnel_archive"] == 39

    bot = TelegramCrmBot(db=db)
    dashboard_text = await bot.get_crm_dashboard_text()
    assert "СТАТУС ВОРОНКИ СДЕЛОК (HH.RU):" in dashboard_text
    assert "📁 <i>Все:</i> <b>3</b>" in dashboard_text
    assert "🎉 <i>Собеседования:</i> <b>1</b>" in dashboard_text
    assert "🚀 <i>Выход на работу:</i> <b>0</b>" in dashboard_text
    assert "⏳ <i>Ожидание:</i> <b>2</b>" in dashboard_text
    assert "❌ <i>Отказ:</i> <b>0</b>" in dashboard_text
    assert "📦 <i>Архив:</i> <b>39</b>" in dashboard_text
    assert "💬 <i>Активные диалоги в чатах:</i> <b>0</b>" in dashboard_text
    assert "🎯 <b>ОТКЛИКОВ ЗА СЕГОДНЯ:</b>" in dashboard_text
    assert "🤖 <b>РЕВЬЮ QWEN (АУДИТ СИНХРОНИЗАЦИИ):</b>" in dashboard_text

    # Verify user-requested layout order: Funnel first, then Today's applied, then Qwen Review
    funnel_idx = dashboard_text.find("СТАТУС ВОРОНКИ СДЕЛОК (HH.RU):")
    today_idx = dashboard_text.find("ОТКЛИКОВ ЗА СЕГОДНЯ:")
    qwen_idx = dashboard_text.find("РЕВЬЮ QWEN (АУДИТ СИНХРОНИЗАЦИИ):")
    assert funnel_idx < today_idx < qwen_idx


@pytest.mark.asyncio
async def test_qwen_sync_audit_review_resilience():
    from hh_agent.core.llm.local_client import LocalQwenClient

    # Test formatter
    raw = (
        "Конечно, вот краткий отчет:\n"
        "1. **Синхронизация 100%**: данные совпадают.\n"
        "2. **Воронка**: все стабильно.\n"
    )
    formatted = LocalQwenClient._format_telegram_review(raw)
    assert "• <b>Синхронизация 100%</b>: данные совпадают." in formatted
    assert "Конечно" not in formatted

    # Test client fallback on offline/unreachable host
    client = LocalQwenClient(base_url="http://127.0.0.1:9999/v1", timeout=0.5)
    site_funnel = {"all_count": 9, "waiting_count": 9, "interview_count": 0, "discard_count": 0, "archive_count": 39}
    crm_metrics = {"active_chats": 3, "today_applied_total": 0, "today_direct": 0, "today_questionnaire": 0, "today_test_task": 0}
    review = await client.generate_sync_audit_review(site_funnel, crm_metrics)
    assert "Синхронизация hh.ru ↔ CRM" in review
    assert "Все: 9" in review
    assert "диалоги: 3" in review


@pytest.mark.asyncio
async def test_extract_funnel_metrics():
    from unittest.mock import AsyncMock, MagicMock
    from hh_agent.core.browser.negotiations import NegotiationsBrowser

    def make_mock_tab(label: str, count_str: str):
        tab = MagicMock()
        tab.inner_text = AsyncMock(return_value=f"{label} {count_str}".strip())
        lbl_loc = MagicMock(
            count=AsyncMock(return_value=1),
            inner_text=AsyncMock(return_value=label),
        )
        post_loc = MagicMock(
            count=AsyncMock(return_value=1 if count_str else 0),
            inner_text=AsyncMock(return_value=count_str if count_str else ""),
        )
        tab.locator = MagicMock(side_effect=lambda sel: lbl_loc if "tab-label" in sel else (post_loc if "tab-postfix" in sel else MagicMock(count=AsyncMock(return_value=0))))
        return tab

    mock_tabs = [
        make_mock_tab("Все", "3"),
        make_mock_tab("Приглашение", ""),
        make_mock_tab("Собеседование", "1"),
        make_mock_tab("Выход на работу", ""),
        make_mock_tab("Ожидание", "2"),
        make_mock_tab("Отказ", ""),
        make_mock_tab("Удалённые", "39"),
        make_mock_tab("Архив", ""),
    ]

    mock_page = MagicMock()
    mock_page.url = "https://hh.ru/applicant/negotiations"
    mock_page.locator = MagicMock(return_value=MagicMock(all=AsyncMock(return_value=mock_tabs)))

    browser = NegotiationsBrowser(page=mock_page)
    funnel = await browser.extract_funnel_metrics()

    assert funnel["all_count"] == 3
    assert funnel["interview_count"] == 1
    assert funnel["job_offer_count"] == 0
    assert funnel["waiting_count"] == 2
    assert funnel["discard_count"] == 0
    assert funnel["archive_count"] == 39


@pytest.mark.asyncio
async def test_notify_if_crm_updated(tmp_path: Path):
    from unittest.mock import AsyncMock, patch
    from hh_agent.core.telegram.crm_bot import TelegramCrmBot

    db_file = tmp_path / "test_crm_updates.db"
    db = Database(db_path=db_file)
    await db.init_db()

    bot = TelegramCrmBot(db=db)

    with patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True

        # 1. notify_chat_reply should be suppressed (no messages sent)
        await bot.notify_chat_reply(
            company="Test Company",
            title="AI Engineer",
            employer_msg="Привет",
            reply_text="Добрый день",
        )
        assert mock_send.call_count == 0

        # 2. First CRM update notification should send dashboard
        updated = await bot.notify_if_crm_updated()
        assert updated is True
        assert mock_send.call_count == 1

        # 3. Second call with unchanged metrics should return False (no spam)
        updated2 = await bot.notify_if_crm_updated()
        assert updated2 is False
        assert mock_send.call_count == 1  # Still 1

        # 4. Now modify CRM metrics (e.g. apply to a vacancy)
        await db.save_vacancy({
            "hh_id": "999888",
            "title": "LLM Dev",
            "company_name": "New Corp",
            "status": "APPLIED",
        })
        await db.update_vacancy_status("999888", "APPLIED", applied=True)

        # 5. notify_if_crm_updated detects metric change and notifies
        updated3 = await bot.notify_if_crm_updated()
        assert updated3 is True
        assert mock_send.call_count == 2


@pytest.mark.asyncio
async def test_50_50_pool_balancing():
    from unittest.mock import AsyncMock, patch
    from hh_agent.core.live_runner import LiveVisualRunner

    runner = LiveVisualRunner()

    async def mock_fetch(page, query, target_count, seen_ids, search_period_days, badge_color):
        return [
            {
                "hh_id": f"{query}_{i}",
                "title": f"Position {query} {i}",
                "company": f"Company {i}",
                "url": f"https://hh.ru/vacancy/{query}_{i}",
                "query": query,
            }
            for i in range(target_count)
        ]

    with patch.object(runner, "_fetch_vacancies_for_query", side_effect=mock_fetch):
        pool = await runner.collect_fresh_pool(
            page=None,
            target_pool_size=35,
            primary_query_1="AI-инженер",
            primary_query_2="LLM",
        )

        assert len(pool) == 35
        ai_items = [item for item in pool if item["query"] == "AI-инженер"]
        llm_items = [item for item in pool if item["query"] == "LLM"]

        # Exactly 50/50 balance (18 + 17 = 35)
        assert len(ai_items) == 18
        assert len(llm_items) == 17

        # Strictly interleaved order [AI, LLM, AI, LLM...]
        for idx, item in enumerate(pool):
            if idx % 2 == 0:
                assert item["query"] == "AI-инженер"
            else:
                assert item["query"] == "LLM"


def test_evaluate_vacancy_against_resume():
    from hh_agent.core.live_runner import LiveVisualRunner

    runner = LiveVisualRunner()

    # 1. Matching AI/LLM vacancy
    ai_vac = runner._evaluate_vacancy_against_resume(
        title="AI-инженер / LLM-разработчик",
        description="Ищем инженера для разработки мультиагентных систем на базе Llama и Qwen, внедрения RAG в Weaviate и бэкенда на Python/FastAPI. Удаленная работа.",
        company="Tech AI Corp",
    )
    assert ai_vac["is_suitable"] is True
    assert ai_vac["score_10"] >= 7.0
    assert "Python" in ai_vac["matching_skills"]
    assert "LLM / GenAI" in ai_vac["matching_skills"]

    # 2. Non-engineering sales vacancy (should be rejected)
    sales_vac = runner._evaluate_vacancy_against_resume(
        title="Менеджер по продажам AI/LLM решений",
        description="Холодные звонки, выполнение плана продаж B2B, встречи с клиентами.",
        company="Sales AI Ltd",
    )
    assert sales_vac["is_suitable"] is False
    assert sales_vac["score_10"] <= 3.0

    # 3. Pure Java Backend without AI (should be rejected)
    java_vac = runner._evaluate_vacancy_against_resume(
        title="Senior Java Developer",
        description="Разработка высоконагруженных систем на Java, Spring Boot, Hibernate, Kafka. Без ML/AI.",
        company="Bank Corp",
    )
    assert java_vac["is_suitable"] is False
    assert java_vac["score_10"] <= 4.0

    # 4. Stop-words vacancy (Junior / 1C)
    junior_vac = runner._evaluate_vacancy_against_resume(
        title="Junior Стажер 1C Developer",
        description="Обучение стажеров 1С.",
        company="1C Soft",
    )
    assert junior_vac["is_suitable"] is False
    assert junior_vac["score_10"] == 0.0

    # 5. Senior role with mentoring/junior mentions in description (MUST NOT be rejected!)
    senior_mentor_vac = runner._evaluate_vacancy_against_resume(
        title="Senior AI Engineer",
        description="Разработка мульти-агентных систем на Python и FastAPI, гибридный RAG в Weaviate. "
                    "В обязанности входит менторство и обучение junior-разработчиков, кураторство стажеров.",
        company="AI Innovation Labs",
    )
    assert senior_mentor_vac["is_suitable"] is True
    assert senior_mentor_vac["score_10"] >= 7.0

@pytest.mark.asyncio
async def test_evaluate_vacancy_with_llm():
    from hh_agent.core.live_runner import LiveVisualRunner
    from hh_agent.core.llm.schemas import FastVacancyAnalysis

    runner = LiveVisualRunner()

    # Fast discard without calling LLM
    sales_res = await runner._evaluate_vacancy_with_llm(
        title="Менеджер по продажам LLM",
        description="Холодные продажи",
        company="Sales Inc",
    )
    assert sales_res["is_suitable"] is False
    assert sales_res["evaluator"] == "Быстрый фильтр"

    # LLM evaluation on valid AI engineer vacancy (with mocked nim client)
    async def mock_nim_analyze(*args, **kwargs):
        return FastVacancyAnalysis(
            match_score=90,
            summary_reasoning="Отличный стек: Python, Agents, RAG",
            is_suitable=True,
            tech_stack=["Python", "RAG", "FastAPI"],
        )

    runner.nim_client.analyze_vacancy = mock_nim_analyze
    ai_res = await runner._evaluate_vacancy_with_llm(
        title="AI-инженер",
        description="Разработка LLM агентов на Python и FastAPI",
        company="AI Labs",
    )
    assert ai_res["is_suitable"] is True
    assert ai_res["score_10"] == 9.0
    assert "NVIDIA NIM" in ai_res["evaluator"]


@pytest.mark.asyncio
async def test_audit_generated_text_with_judge():
    from hh_agent.core.live_runner import LiveVisualRunner
    from hh_agent.core.llm.schemas import JudgeEvaluationResult

    runner = LiveVisualRunner()

    # 1. Reject invalid letter with female verb / low salary / office hallucination
    bad_letter = "Здравствуйте! Я разработала проект на PHP и согласна на оклад 50 000 руб в офисе."
    bad_res = await runner._audit_generated_text_with_judge(
        draft_text=bad_letter,
        context_type="сопроводительное письмо",
        company_name="Test Corp",
        vacancy_title="AI-инженер",
    )
    assert bad_res.is_approved is False
    assert bad_res.has_hallucinations is True
    assert len(bad_res.hallucination_details) > 0

    # 2. Approve valid male PRD letter with mock judge
    good_letter = (
        "Здравствуйте, команда Tech AI! Меня заинтересовала вакансия AI-инженер. "
        "Более 3.5 лет я проектировал мульти-агентные системы MOGE и RAG в Weaviate. "
        "GitHub: github.com/14Segun88. С уважением, Георгий Салюк"
    )

    async def mock_nim_judge(*args, **kwargs):
        return JudgeEvaluationResult(
            is_approved=True,
            score_10=9.5,
            has_hallucinations=False,
            hallucination_details=[],
            verdict_summary="Полное соответствие профилю Георгия Салюка.",
            evaluator="NVIDIA NIM (Judge)",
        )

    runner.nim_client.judge_text = mock_nim_judge
    good_res = await runner._audit_generated_text_with_judge(
        draft_text=good_letter,
        context_type="сопроводительное письмо",
        company_name="Tech AI",
        vacancy_title="AI-инженер",
    )
    assert good_res.is_approved is True
    assert good_res.score_10 >= 9.0
    assert good_res.has_hallucinations is False


def test_multiple_experience_search_url():
    from unittest.mock import MagicMock
    from hh_agent.config import SearchConfig
    from hh_agent.core.browser.vacancies import VacancyBrowser

    mock_page = MagicMock()
    browser = VacancyBrowser(mock_page)

    config = SearchConfig(
        queries=["AI-инженер"],
        experience=["between1And3", "between3And6"],
        only_remote=True,
    )
    url = browser.build_search_url("AI-инженер", config)

    # Verify both experience query params exist in the URL
    assert "experience=between1And3" in url
    assert "experience=between3And6" in url
    assert url.count("experience=") == 2


@pytest.mark.asyncio
async def test_junior_intern_filter_strictly_in_title():
    from unittest.mock import AsyncMock
    from hh_agent.config import CandidateProfile, SearchRules
    from hh_agent.core.llm.local_client import LocalQwenClient
    from hh_agent.core.llm.nim_client import NvidiaNimClient
    from hh_agent.core.live_runner import LiveVisualRunner

    rules = SearchRules(
        hard_stop_words=["Junior", "Стажер", "1C", "PHP"],
        min_salary=200000,
    )
    profile = CandidateProfile(
        name="Георгий Салюк",
        years_experience=3.5,
        target_role="AI-инженер",
    )

    # 1. LocalQwenClient tests
    local_client = LocalQwenClient(base_url="http://localhost:8000/v1")
    # Title has Junior -> instant reject
    res_jr_title = await local_client.analyze_vacancy(
        vacancy_title="Junior AI-инженер",
        vacancy_description="Разработка моделей на Python",
        candidate_profile=profile,
        search_rules=rules,
    )
    assert res_jr_title.is_suitable is False
    assert any("Junior" in sw for sw in res_jr_title.stop_phrases_found)

    # Title is Senior, description mentions mentoring juniors -> must NOT trigger stop phrases
    local_client._chat_completion = AsyncMock(return_value='{"is_suitable": true, "match_score": 85, "tech_stack": ["Python"], "red_flags_detected": [], "summary_reasoning": "Good fit"}')
    res_sr_desc = await local_client.analyze_vacancy(
        vacancy_title="Senior AI-инженер",
        vacancy_description="Разработка мульти-агентных систем. Менторство junior разработчиков и стажеров.",
        candidate_profile=profile,
        search_rules=rules,
    )
    assert len(res_sr_desc.stop_phrases_found) == 0

    # 2. NvidiaNimClient tests
    nim_client = NvidiaNimClient(api_key="mock_key")
    # Title has Стажер -> instant reject
    res_intern_title = await nim_client.analyze_vacancy(
        vacancy_title="Стажер ML разработчик",
        vacancy_description="Разработка моделей на Python",
        candidate_profile=profile,
        search_rules=rules,
    )
    assert res_intern_title.is_suitable is False
    assert any("Стажер" in sw for sw in res_intern_title.stop_phrases_found)

    # Title is Lead, description mentions стажеров -> must NOT trigger stop phrases
    nim_client._chat_completion = AsyncMock(return_value='{"is_suitable": true, "match_score": 90, "tech_stack": ["Python"], "red_flags_detected": [], "summary_reasoning": "Good fit"}')
    res_lead_desc = await nim_client.analyze_vacancy(
        vacancy_title="Lead AI-инженер",
        vacancy_description="Проектирование LLM решений. Курирование стажеров и джуниоров команды.",
        candidate_profile=profile,
        search_rules=rules,
    )
    assert len(res_lead_desc.stop_phrases_found) == 0

    # 3. LiveVisualRunner tests
    runner = LiveVisualRunner()
    sr_res = runner._evaluate_vacancy_against_resume(
        title="Senior LLM Architect",
        description="Разработка LLM агентов на Python и FastAPI, Weaviate RAG. Обучение junior коллег и курирование стажеров.",
        company="NeuroTech",
    )
    assert sr_res["is_suitable"] is True
    assert sr_res["score_10"] >= 7.0


@pytest.mark.asyncio
async def test_async_timed_input_confirm_timeout():
    from unittest.mock import patch
    from hh_agent.core.live_runner import async_timed_input

    # 1. Test timeout default value (simulating user not typing anything)
    with patch("select.select", return_value=([], [], [])):
        res = await async_timed_input("Prompt: ", timeout=0.05, default="y")
        assert res == "y"

    # 2. Test user enters 'n' within timeout -> should reject
    with patch("select.select", return_value=([True], [], [])), \
         patch("sys.stdin.readline", return_value="n\n"):
        res_no = await async_timed_input("Prompt: ", timeout=0.05, default="y")
        assert res_no == "n"
        should_send = res_no.strip().lower() != "n"
        assert should_send is False

    # 3. Test user enters 'y' within timeout -> should accept
    with patch("select.select", return_value=([True], [], [])), \
         patch("sys.stdin.readline", return_value="y\n"):
        res_yes = await async_timed_input("Prompt: ", timeout=0.05, default="y")
        assert res_yes == "y"
        should_send = res_yes.strip().lower() != "n"
        assert should_send is True

    # 4. Test EOF / daemon mode (empty readline from closed pipe / /dev/null)
    with patch("select.select", return_value=([True], [], [])), \
         patch("sys.stdin.readline", return_value=""):
        res_eof = await async_timed_input("Prompt: ", timeout=0.05, default="y")
        assert res_eof == "y"
        should_send = res_eof.strip().lower() != "n"
        assert should_send is True


