from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FactItem(BaseModel):
    id: str
    tags: List[str] = Field(default_factory=list)
    text: str


class WantsConfig(BaseModel):
    target_roles: List[str] = Field(default_factory=list)
    format: List[str] = Field(default_factory=lambda: ["remote"])
    salary_net_min: int = 250000
    salary_net_target: int = 300000
    currency: str = "RUR"
    contracts_allowed: List[str] = Field(default_factory=list)
    stop_words: List[str] = Field(default_factory=list)


class PRDConfig(BaseModel):
    facts: List[FactItem] = Field(default_factory=list)
    wants: WantsConfig = Field(default_factory=WantsConfig)
    never_disclose: List[str] = Field(default_factory=list)

    def get_facts_by_tags(self, tags: List[str]) -> List[FactItem]:
        """Filter verified facts by tag match (e.g. ['backend', 'python'])."""
        if not tags:
            return self.facts
        matched = []
        tags_set = set(t.lower() for t in tags)
        for f in self.facts:
            f_tags = set(t.lower() for t in f.tags)
            if tags_set.intersection(f_tags):
                matched.append(f)
        return matched


class ScenarioSpec(BaseModel):
    id: str
    description: str = ""
    detect: Dict[str, Any] = Field(default_factory=dict)
    action: str
    task: Optional[str] = None
    approval: str = "none"  # "none", "semi_auto", "required"


class SpecsConfig(BaseModel):
    scenarios: List[ScenarioSpec] = Field(default_factory=list)

    def get_scenario(self, scenario_id: str) -> Optional[ScenarioSpec]:
        for s in self.scenarios:
            if s.id == scenario_id:
                return s
        return None


class TaskDefinition(BaseModel):
    id: str
    description: str = ""
    model: str = "local"  # "local" (LM Studio Qwen) или "nim" (NVIDIA NIM)
    input_sources: List[Any] = Field(default_factory=list)
    max_input_tokens: int = 1000
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    allowed_effects: List[str] = Field(default_factory=list)

    def is_effect_allowed(self, effect_name: str) -> bool:
        return effect_name in self.allowed_effects
