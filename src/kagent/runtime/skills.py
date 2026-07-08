from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

_SAFE_SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


class RuntimeSkillRegistry:
    def __init__(self, skills_dir: str | Path) -> None:
        self.skills_dir = Path(skills_dir)

    def list_skills(self) -> list[Dict[str, Any]]:
        if not self.skills_dir.exists():
            return []
        skills = []
        for path in sorted(self.skills_dir.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            skill = self._read_skill_file(path)
            skills.append(
                {
                    "name": skill["name"],
                    "description": skill["description"],
                    "tags": skill.get("tags", []),
                }
            )
        return skills

    def get_skill(self, name: str) -> Dict[str, Any]:
        normalized_name = self._validate_skill_name(name)
        path = self.skills_dir / f"{normalized_name}.json"
        if path.is_symlink():
            raise ValueError("skill file must not be a symlink")
        if not path.exists():
            raise ValueError(f"skill does not exist: {normalized_name}")
        return self._read_skill_file(path)

    def _read_skill_file(self, path: Path) -> Dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("skill payload must be an object")
        name = self._validate_skill_name(str(payload.get("name", "")))
        description = str(payload.get("description", "")).strip()
        instructions = str(payload.get("instructions", "")).strip()
        if not description:
            raise ValueError(f"skill description is required: {name}")
        if not instructions:
            raise ValueError(f"skill instructions are required: {name}")
        tags = payload.get("tags", [])
        if not isinstance(tags, list):
            raise ValueError(f"skill tags must be an array: {name}")
        return {
            "name": name,
            "description": description,
            "instructions": instructions,
            "tags": [str(tag) for tag in tags],
        }

    def _validate_skill_name(self, name: str) -> str:
        normalized = str(name).strip()
        if not _SAFE_SKILL_NAME.match(normalized):
            raise ValueError("skill name must be a safe identifier")
        return normalized
