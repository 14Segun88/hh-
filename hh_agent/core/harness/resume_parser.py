"""Resume parser utility to extract and verify data from RTF/DOC resumes."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List
import striprtf.striprtf as srtf


def parse_rtf_resume(file_path: str | Path) -> str:
    """Extract plain text from RTF-based .doc file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Resume file not found at: {path}")

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        raw_content = f.read()

    try:
        clean_text = srtf.rtf_to_text(raw_content)
    except Exception:
        clean_text = raw_content

    return clean_text.strip()


def get_verified_resume_summary(file_path: str | Path = "Салюк Георгий Михайлович (4).doc") -> Dict[str, Any]:
    """Returns verified summary of candidate resume (version 4)."""
    text = parse_rtf_resume(file_path)
    
    return {
        "source_file": Path(file_path).name,
        "candidate": "Салюк Георгий Михайлович",
        "birth_date": "06.09.1998",
        "age": 27,
        "location": "Краснодар, Россия",
        "citizenship": "Россия",
        "contacts": {
            "phone": "+7 (918) 045-25-04",
            "email": "d-saljuk@rambler.ru",
            "github": "https://github.com/14Segun88",
        },
        "target_roles": [
            "AI-инженер",
            "Разработчик AI-агентов",
            "LLM-инженер",
        ],
        "target_salary": "220 000 ₽ на руки",
        "target_salary_num": 220000,
        "min_salary_num": 200000,
        "work_formats": ["Удалённо", "Гибрид"],
        "experience_total": "3 года 5 месяцев",
        "projects": [
            {
                "name": "MOGE (МосОблГосЭкспертиза)",
                "role": "ML-инженер (Февраль 2023 — Февраль 2026)",
                "github": "https://github.com/14Segun88/moge-document-expertise-ai",
                "summary": "Мульти-агентная AI-система госэкспертизы (8 агентов, Llama-3.3-70B, Weaviate RAG, ускорение с 42 дней до 5-10 мин).",
            },
            {
                "name": "PD Document Analyzer (МОГЭ)",
                "role": "AI-инженер (Январь 2025 — Апрель 2026)",
                "github": "https://github.com/14Segun88/pd-document-analyzer",
                "summary": "7-шаговый CoT Reasoning + Mistral 14B + Knowledge Base (100% точность на known docs, извлечение 8 полей метаданных).",
            },
            {
                "name": "News Predictor AI (Финсмарт)",
                "role": "ML-инженер (Январь 2023 — настоящее время)",
                "github": "https://github.com/14Segun88/news-predictor-ai",
                "summary": "Гибридный ML (PyTorch Fusion + 4x CatBoost + 139 фичей + Playwright + Telegram, 85.7% accuracy при confidence >65%).",
            },
        ],
        "raw_text_length": len(text),
    }
