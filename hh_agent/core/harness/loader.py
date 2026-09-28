from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional
import yaml
from hh_agent.config import CONFIG_DIR
from hh_agent.core.harness.models import PRDConfig, SpecsConfig, TaskDefinition


class HarnessLoader:
    """Loads and validates PRD, Specs, Tasks, and Lessons from config directory."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or CONFIG_DIR
        self.tasks_dir = self.config_dir / "tasks"

        self.prd: PRDConfig = self._load_prd()
        self.specs: SpecsConfig = self._load_specs()
        self.tasks: Dict[str, TaskDefinition] = self._load_tasks()
        self.lessons: str = self._load_lessons()

    def _load_prd(self) -> PRDConfig:
        prd_file = self.config_dir / "prd.yaml"
        if not prd_file.exists():
            return PRDConfig()
        with open(prd_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return PRDConfig.model_validate(data)

    def _load_specs(self) -> SpecsConfig:
        specs_file = self.config_dir / "specs.yaml"
        if not specs_file.exists():
            return SpecsConfig()
        with open(specs_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return SpecsConfig.model_validate(data)

    def _load_tasks(self) -> Dict[str, TaskDefinition]:
        tasks = {}
        if not self.tasks_dir.exists():
            return tasks
        for path in self.tasks_dir.glob("*.yaml"):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            task = TaskDefinition.model_validate(data)
            tasks[task.id] = task
        return tasks

    def _load_lessons(self) -> str:
        lessons_file = self.config_dir / "lessons.md"
        if not lessons_file.exists():
            return ""
        with open(lessons_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def reload(self) -> None:
        """Hot-reload all configs on the fly."""
        self.prd = self._load_prd()
        self.specs = self._load_specs()
        self.tasks = self._load_tasks()
        self.lessons = self._load_lessons()
