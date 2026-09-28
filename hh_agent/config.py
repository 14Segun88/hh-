from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
BROWSER_PROFILE_DIR = DATA_DIR / "browser_profile"


class PersonalInfo(BaseModel):
    full_name: str = "Кандидат"
    contact_phone: str = ""
    contact_telegram: str = ""
    email: str = ""
    city: str = "Москва"
    citizenship: str = "РФ"
    relocation_ready: bool = False
    work_permit: List[str] = Field(default_factory=lambda: ["РФ"])


class CareerConfig(BaseModel):
    target_roles: List[str] = Field(default_factory=list)
    target_salary_net_rub: int = 250000
    minimum_salary_net_rub: int = 200000
    preferred_currency: str = "RUR"
    employment_type: List[str] = Field(default_factory=list)
    work_format: List[str] = Field(default_factory=list)
    legal_entities_allowed: List[str] = Field(default_factory=list)


class SkillsConfig(BaseModel):
    primary_stack: List[str] = Field(default_factory=list)
    secondary_stack: List[str] = Field(default_factory=list)
    years_of_experience: int = 5


class CandidateProfile(BaseModel):
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    career: CareerConfig = Field(default_factory=CareerConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    experience_summary: str = ""
    questionnaire_facts: Dict[str, Any] = Field(default_factory=dict)


class SearchConfig(BaseModel):
    queries: List[str] = Field(default_factory=lambda: ["Python Senior"])
    area_id: int = 113
    only_remote: bool = True
    order_by: str = "publication_time"
    experience: List[str] = Field(default_factory=lambda: ["between3And6", "moreThan6"])


class RulesThresholds(BaseModel):
    min_score_to_consider: int = 60
    min_score_for_nim_dossier: int = 70


class SearchRules(BaseModel):
    search: SearchConfig = Field(default_factory=SearchConfig)
    hard_stop_words: List[str] = Field(default_factory=list)
    red_flag_phrases: List[str] = Field(default_factory=list)
    thresholds: RulesThresholds = Field(default_factory=RulesThresholds)


class Settings(BaseModel):
    # Tier 1: Local LM Studio
    lm_studio_url: str = Field(
        default_factory=lambda: os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
    )
    lm_studio_model: str = Field(
        default_factory=lambda: os.getenv("LM_STUDIO_MODEL", "qwen2.5-7b-instruct")
    )
    lm_studio_timeout: float = Field(
        default_factory=lambda: float(os.getenv("LM_STUDIO_TIMEOUT", "60.0"))
    )

    # Tier 2: Remote NVIDIA NIM
    nvidia_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("NVIDIA_API_KEY")
    )
    nvidia_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
        )
    )
    nvidia_model: str = Field(
        default_factory=lambda: os.getenv(
            "NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"
        )
    )
    nvidia_timeout: float = Field(
        default_factory=lambda: float(os.getenv("NVIDIA_TIMEOUT", "120.0"))
    )

    # Telegram
    telegram_bot_token: Optional[str] = Field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN")
    )
    telegram_chat_id: Optional[str] = Field(
        default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID")
    )

    # Operational settings
    application_mode: str = Field(
        default_factory=lambda: os.getenv("APPLICATION_MODE", "semi_auto")
    )
    headless_browser: bool = Field(
        default_factory=lambda: os.getenv("HEADLESS_BROWSER", "false").lower() == "true"
    )
    score_threshold: int = Field(
        default_factory=lambda: int(os.getenv("SCORE_THRESHOLD", "70"))
    )
    max_vacancies_per_batch: int = Field(
        default_factory=lambda: int(os.getenv("MAX_VACANCIES_PER_BATCH", "40"))
    )
    search_window_hours: int = Field(
        default_factory=lambda: int(os.getenv("SEARCH_WINDOW_HOURS", "48"))
    )

    # DB & paths
    db_path: Path = DATA_DIR / "hh_agent.sqlite3"
    browser_profile_dir: Path = BROWSER_PROFILE_DIR


def load_candidate_profile() -> CandidateProfile:
    profile_file = CONFIG_DIR / "candidate_profile.yaml"
    if not profile_file.exists():
        return CandidateProfile()
    with open(profile_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return CandidateProfile.model_validate(data)


def load_search_rules() -> SearchRules:
    rules_file = CONFIG_DIR / "search_rules.yaml"
    if not rules_file.exists():
        return SearchRules()
    with open(rules_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return SearchRules.model_validate(data)


# Global instances
settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
