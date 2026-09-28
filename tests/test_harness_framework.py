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
    assert "github" in loader.lessons.lower() or "moge" in loader.lessons.lower()


def test_prd_tag_filtering():
    loader = HarnessLoader()
    # Filter AI / Agent facts
    ai_facts = loader.prd.get_facts_by_tags(["ai"])
    assert len(ai_facts) > 0
    for f in ai_facts:
        assert any(t in ["ai", "agents", "llm", "rag", "ml", "architecture"] for t in f.tags)

    # Filter forms facts
    form_facts = loader.prd.get_facts_by_tags(["forms"])
    assert len(form_facts) > 0
    form_ids = [f.id for f in form_facts]
    assert "location_city" in form_ids or "full_name" in form_ids or "driver_license" in form_ids


def test_prompt_builder():
    loader = HarnessLoader()
    builder = PromptBuilder(loader)

    # Test score prompt
    score_prompt = builder.build_score_vacancy_prompt(
        vacancy_title="Разработчик AI-агентов (Multi-Agent)",
        vacancy_description="Разработка автономных агентов на базе Llama 3 и Weaviate.",
    )
    assert len(score_prompt) == 2
    assert "Разработчик AI-агентов" in score_prompt[1]["content"]
    assert "Weaviate" in score_prompt[1]["content"]

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
