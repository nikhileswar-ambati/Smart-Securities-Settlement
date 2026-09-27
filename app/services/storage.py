from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

from app.schemas import Project


class ProjectStore:
    def __init__(self) -> None:
        self.root = Path(os.getenv("APP_DATA_DIR", "data"))
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def save(self, project: Project) -> None:
        with self._lock:
            (self.root / f"{project.id}.json").write_text(
                project.model_dump_json(indent=2), encoding="utf-8"
            )

    def get(self, project_id: str) -> Project:
        if not project_id or any(char not in "0123456789abcdef-" for char in project_id.lower()):
            raise KeyError(project_id)
        path = self.root / f"{project_id}.json"
        if not path.exists():
            raise KeyError(project_id)
        return Project.model_validate_json(path.read_text(encoding="utf-8"))

    def export(self, project: Project) -> dict:
        return json.loads(project.model_dump_json())

    def list(self) -> list[Project]:
        projects = []
        for path in self.root.glob("*.json"):
            try:
                projects.append(Project.model_validate_json(path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue
        return sorted(projects, key=lambda project: project.created_at, reverse=True)
