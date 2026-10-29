"""Progressive disclosure for plain-text ARYA skills."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    tools: tuple[str, ...]
    body: str


class SkillsRuntime:
    def __init__(self, root: Path, max_active: int = 3):
        self.root = root
        self.max_active = max_active
        self.skills = self._read_skills()

    def _read_skills(self) -> dict[str, Skill]:
        skills: dict[str, Skill] = {}
        for path in sorted(self.root.glob("*/SKILL.md")):
            source = path.read_text(encoding="utf-8")
            if not source.startswith("---\n"):
                raise ValueError(f"Skill frontmatter is missing: {path}")
            _, frontmatter, body = source.split("---", 2)
            metadata = yaml.safe_load(frontmatter) or {}
            name = metadata.get("name")
            description = metadata.get("description")
            tool_names = metadata.get("tools", [])
            if isinstance(tool_names, str):
                tool_names = [item.strip() for item in tool_names.replace("\n", " ").split(",") if item.strip()]
            if not isinstance(name, str) or not isinstance(description, str):
                raise ValueError(f"Skill name and description must be strings: {path}")
            if not isinstance(tool_names, list) or not all(isinstance(item, str) for item in tool_names):
                raise ValueError(f"Skill tools must be a list of strings: {path}")
            skills[name] = Skill(name, description, tuple(tool_names), body.strip())
        return skills

    @property
    def index(self) -> str:
        return "\n".join(f"{item.name}: {item.description}" for item in self.skills.values())

    def activate(self, names: Iterable[str]) -> list[str]:
        active: list[str] = []
        for name in names:
            if name in self.skills and name not in active:
                active.append(name)
            if len(active) >= self.max_active:
                break
        return active

    def load(self, name: str, active: Iterable[str]) -> tuple[str, list[str]]:
        skill = self.skills.get(name)
        if skill is None:
            raise ValueError(f"Unknown skill: {name}")
        active_names = list(active)
        if name not in active_names and len(active_names) >= self.max_active:
            raise ValueError(f"At most {self.max_active} skills can be active in a turn")
        if name not in active_names:
            active_names.append(name)
        return skill.body, active_names

    def tool_names(self, active: Iterable[str]) -> set[str]:
        return {
            tool_name
            for skill_name in active
            for tool_name in self.skills[skill_name].tools
        }

    def context(self, active: Iterable[str]) -> str:
        return "\n\n".join(
            f"### {self.skills[name].name}\n{self.skills[name].body}"
            for name in active
            if name in self.skills
        )
