from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from hh_agent.config import CandidateProfile, SearchRules, settings
from hh_agent.core.llm.local_client import LocalQwenClient
from hh_agent.core.llm.nim_client import NvidiaNimClient
from hh_agent.core.llm.schemas import DeepEmployerDossier, FastVacancyAnalysis
from hh_agent.core.storage.db import Database

logger = logging.getLogger(__name__)


class VacancyEvaluator:
    """Two-tier vacancy analyzer: Fast Qwen scoring -> Deep NVIDIA NIM dossier."""

    def __init__(
        self,
        local_client: LocalQwenClient,
        nim_client: NvidiaNimClient,
        db: Database,
        profile: CandidateProfile,
        rules: SearchRules,
    ):
        self.local_client = local_client
        self.nim_client = nim_client
        self.db = db
        self.profile = profile
        self.rules = rules

    async def evaluate_vacancy(
        self, vacancy_raw: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute 2-tier analysis:
        1. Fast Qwen extraction and scoring
        2. Deep NIM dossier if score passes threshold
        """
        hh_id = vacancy_raw["hh_id"]
        title = vacancy_raw.get("title", "")
        company = vacancy_raw.get("company_name", "")
        description = vacancy_raw.get("description", "")
        url = vacancy_raw.get("url", "")

        # -------------------------------------------------------------
        # Tier 1: Local Qwen 2.5 7B Fast Extraction & Preliminary Score
        # -------------------------------------------------------------
        try:
            fast_analysis: FastVacancyAnalysis = await self.local_client.analyze_vacancy(
                vacancy_title=title,
                vacancy_description=description,
                candidate_profile=self.profile,
                search_rules=self.rules,
            )
        except Exception as e:
            logger.warning("Local Qwen analysis error on vacancy %s: %s", hh_id, e)
            fast_analysis = FastVacancyAnalysis(
                match_score=50,
                summary_reasoning="Ошибка локального скоринга Qwen, назначен базовый балл",
                is_suitable=False,
            )

        score = fast_analysis.match_score
        dossier_text = ""
        verdict_text = ""
        cover_letter = ""
        status = "SKIPPED"

        if score < self.rules.thresholds.min_score_to_consider:
            status = "SKIPPED"
        else:
            status = "QUALIFIED"

        # -------------------------------------------------------------
        # Tier 2: Deep NVIDIA NIM Dossier (only if threshold met)
        # -------------------------------------------------------------
        if score >= self.rules.thresholds.min_score_for_nim_dossier:
            try:
                nim_dossier: DeepEmployerDossier = (
                    await self.nim_client.generate_deep_dossier(
                        vacancy_title=title,
                        company_name=company,
                        vacancy_description=description,
                        fast_analysis=fast_analysis,
                        candidate_profile=self.profile,
                    )
                )
                dossier_text = (
                    f"### Обзор компании:\n{nim_dossier.company_overview}\n\n"
                    f"### Плюсы:\n" + "\n".join(f"- {p}" for p in nim_dossier.pros) + "\n\n"
                    f"### Риски:\n" + "\n".join(f"- {c}" for c in nim_dossier.cons_and_risks) + "\n\n"
                    f"### Анализ зарплаты:\n{nim_dossier.salary_market_comparison}\n\n"
                    f"### Стратегия интервью:\n{nim_dossier.interview_strategy}"
                )
                verdict_text = nim_dossier.final_verdict
                cover_letter = nim_dossier.custom_cover_letter
                status = "DOSSIER_READY"
            except Exception as e:
                logger.error("NVIDIA NIM dossier generation error on vacancy %s: %s", hh_id, e)
                dossier_text = "NIM API недоступен, досье не сформировано."
                verdict_text = "Требуется ручной просмотр"

        # Save to database
        record = {
            "hh_id": hh_id,
            "title": title,
            "company_name": company,
            "company_url": vacancy_raw.get("company_url", ""),
            "salary_raw": vacancy_raw.get("salary_raw", ""),
            "salary_min": fast_analysis.salary_min or vacancy_raw.get("salary_min"),
            "salary_max": fast_analysis.salary_max or vacancy_raw.get("salary_max"),
            "currency": fast_analysis.currency or vacancy_raw.get("currency", "RUR"),
            "url": url,
            "description": description,
            "published_at": vacancy_raw.get("published_at", ""),
            "score": score,
            "red_flags": fast_analysis.red_flags_detected,
            "extracted_stack": fast_analysis.tech_stack,
            "dossier": dossier_text,
            "verdict": verdict_text,
            "status": status,
        }
        await self.db.save_vacancy(record)

        return {
            "record": record,
            "fast_analysis": fast_analysis,
            "cover_letter": cover_letter,
            "status": status,
        }
