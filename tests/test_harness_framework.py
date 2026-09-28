import pytest
from hh_agent.core.harness.loader import HarnessLoader
from hh_agent.core.harness.prompt_builder import PromptBuilder


def test_harness_loader():
    loader = HarnessLoader()
    # 1. PRD
    assert len(loader.prd.facts) >= 5
    assert loader.prd.wants.salary_net_min > 0
    assert len(loader.prd.never_disclose) >= 3

    # 2. Specs
    assert len(loader.specs.scenarios) >= 4
    cover_scenario = loader.specs.get_scenario("cover_letter")
    assert cover_scenario is not None
    assert cover_scenario.action == "draft_reply"

    test_scenario = loader.specs.get_scenario("complex_test")
    assert test_scenario is not None
    assert test_scenario.action == "REQUIRES_HUMAN"
    assert test_scenario.approval == "required"

    # 3. Tasks
    assert "score_vacancy" in loader.tasks
    assert "draft_reply" in loader.tasks
    assert "solve_form" in loader.tasks

    score_task = loader.tasks["score_vacancy"]
    assert score_task.model == "local"
    assert score_task.allowed_effects == []
    assert not score_task.is_effect_allowed("send_network_request")

    draft_task = loader.tasks["draft_reply"]
    assert draft_task.model == "nim"
    assert draft_task.is_effect_allowed("draft_db")

    # 4. Lessons
    assert "Клише" in loader.lessons or "Asyncio" in loader.lessons


def test_prd_tag_filtering():
    loader = HarnessLoader()
    # Filter backend facts
    backend_facts = loader.prd.get_facts_by_tags(["backend"])
    assert len(backend_facts) > 0
    for f in backend_facts:
        assert any(t in ["backend", "python", "db", "storage", "highload", "secondary"] for t in f.tags)

    # Filter forms facts
    form_facts = loader.prd.get_facts_by_tags(["forms"])
    assert len(form_facts) > 0
    form_ids = [f.id for f in form_facts]
    assert "english_level" in form_ids or "experience_years" in form_ids


def test_prompt_builder():
    loader = HarnessLoader()
    builder = PromptBuilder(loader)

    # Test score prompt
    score_prompt = builder.build_score_vacancy_prompt(
        vacancy_title="Senior Python Engineer",
        vacancy_description="Разработка сервисов на FastAPI и PostgreSQL.",
    )
    assert len(score_prompt) == 2
    assert "Senior Python Engineer" in score_prompt[1]["content"]
    assert "FastAPI" in score_prompt[1]["content"]

    # Test draft prompt
    draft_prompt = builder.build_draft_reply_prompt(
        context_type="cover_letter",
        target_text="Ищем разработчика с опытом в Kafka и Asyncio",
        company_name="Fintech LLC",
    )
    assert len(draft_prompt) == 2
    # Ensure lessons and never_disclose are injected into system prompt
    system_text = draft_prompt[0]["content"]
    assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО" in system_text
    assert "LESSONS.MD" in system_text
