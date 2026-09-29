from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FastVacancyAnalysis(BaseModel):
    """Tier 1: Qwen 2.5 7B fast extraction & preliminary scoring."""
    salary_min: Optional[int] = Field(default=None, description="Нижняя граница вилки")
    salary_max: Optional[int] = Field(default=None, description="Верхняя граница вилки")
    currency: str = Field(default="RUR", description="Валюта (RUR, USD, EUR)")
    tech_stack: List[str] = Field(default_factory=list, description="Выделенный технологический стек")
    red_flags_detected: List[str] = Field(default_factory=list, description="Найденные красные флаги и сомнительные требования")
    stop_phrases_found: List[str] = Field(default_factory=list, description="Стоп-слова/стоп-фразы")
    match_score: int = Field(default=0, ge=0, le=100, description="Оценка соответствия профилю от 0 до 100")
    summary_reasoning: str = Field(default="", description="Краткое обоснование оценки на русском языке")
    is_suitable: bool = Field(default=False, description="Подходит ли вакансия для дальнейшего рассмотрения")


class DeepEmployerDossier(BaseModel):
    """Tier 2: NVIDIA NIM (Llama 70B / Nemotron) deep analysis & verdict."""
    company_overview: str = Field(default="", description="Анализ компании, масштаб, специфика бизнеса")
    pros: List[str] = Field(default_factory=list, description="Плюсы вакансии и работодателя")
    cons_and_risks: List[str] = Field(default_factory=list, description="Риски, подводные камни, красные флаги")
    salary_market_comparison: str = Field(default="", description="Оценка адекватности зарплатной вилки рынку")
    interview_strategy: str = Field(default="", description="Рекомендации к собеседованию, о чем спросить работодателя")
    final_verdict: str = Field(default="Пропустить", description="Вердикт: Рекомендуется / С оговорками / Пропустить")
    custom_cover_letter: str = Field(default="", description="Персонализированное сопроводительное письмо (живой деловой русский)")


class MessageClassification(BaseModel):
    """Tier 1: Qwen 2.5 7B incoming chat classification."""
    category: str = Field(
        default="OTHER",
        description="Категория: INVITATION (приглашение/интервью), QUESTION (вопрос/анкета), REJECTION (отказ), SPAM (рассылка), OTHER"
    )
    is_urgent: bool = Field(default=False, description="Требует ли срочного ответа (напр. приглашение на завтра)")
    extracted_questions: List[str] = Field(default_factory=list, description="Вопросы, заданные работодателем в сообщении")
    proposed_dates_or_times: List[str] = Field(default_factory=list, description="Предложенные даты/время интервью")
    short_summary: str = Field(default="", description="Суть сообщения в 1-2 предложениях")


class DraftedReply(BaseModel):
    """Tier 2: NVIDIA NIM polite business response draft."""
    reply_text: str = Field(default="", description="Текст ответа на грамотном деловом русском языке")
    tone: str = Field(default="Деловой, уверенный, вежливый")
    clarifications_needed: List[str] = Field(default_factory=list, description="Вопросы кандидату, если не хватает данных")


class FormQuestionItem(BaseModel):
    """Parsed question from employer questionnaire."""
    question_id: str
    question_text: str
    field_type: str = "text"  # text, radio, checkbox, number
    options: List[str] = Field(default_factory=list)
    is_factual: bool = True  # Can be answered from candidate_profile.yaml directly
    suggested_answer: Optional[str] = None


class QuestionnaireSolution(BaseModel):
    """Answers for employer test/form."""
    answers: Dict[str, str] = Field(default_factory=dict, description="Словарь {question_id: answer_text}")
    requires_manual_check: bool = Field(default=False, description="Нужно ли ручное подтверждение перед отправкой")
    notes: str = Field(default="")


class JudgeEvaluationResult(BaseModel):
    """LLM-as-a-Judge evaluation of drafted cover letter or answer."""
    is_approved: bool = Field(default=True, description="Одобрено ли письмо/ответ к отправке")
    score_10: float = Field(default=9.0, ge=0.0, le=10.0, description="Оценка от 0.0 до 10.0")
    has_hallucinations: bool = Field(default=False, description="Обнаружены ли вымышленные факты/технологии")
    hallucination_details: List[str] = Field(default_factory=list, description="Список найденных несоответствий или галлюцинаций")
    verdict_summary: str = Field(default="", description="Резюме проверки аудитора")
    evaluator: str = Field(default="LLM-Judge", description="Имя проверяющей модели")

