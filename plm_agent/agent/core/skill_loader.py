# -*- coding: utf-8 -*-
"""
Agent-level Skill Loader.

Discovers, parses, and composes agent-level skills from SKILL.md files.
Reuses the same frontmatter parsing logic as the sandbox SkillManager.

Skills are instruction documents (not code) that teach the LLM how to
perform domain-specific tasks. Each skill is a directory containing a
SKILL.md file with YAML frontmatter (name, description) and a markdown body.
"""

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from tools.sandbox.skill_manager import _parse_frontmatter

logger = logging.getLogger(__name__)


@dataclass
class AgentSkill:
    """Parsed agent-level skill metadata and content."""
    name: str
    description: str
    body: str           # Markdown instruction content (after frontmatter)
    directory: str      # Absolute path to the skill directory


class AgentSkillLoader:
    """
    Agent-level skill loader. Can be used by any Agent that needs
    skill-driven behavior.

    Usage:
        loader = AgentSkillLoader("/path/to/skills/")
        skills = loader.load_all()
        prompt_fragment = loader.compose_prompt(skills)
    """

    def __init__(self, skills_dir: str):
        self._skills_dir = skills_dir
        self._skills: Optional[Dict[str, AgentSkill]] = None

    def discover(self) -> Dict[str, AgentSkill]:
        """
        Scan the skills directory and parse all SKILL.md files.
        Results are cached after first call.
        """
        if self._skills is not None:
            return self._skills

        self._skills = {}

        if not os.path.isdir(self._skills_dir):
            logger.info(
                f"[AgentSkillLoader] Skills directory not found: {self._skills_dir}. "
                "No skills loaded."
            )
            return self._skills

        for entry in sorted(os.listdir(self._skills_dir)):
            skill_dir = os.path.join(self._skills_dir, entry)
            if not os.path.isdir(skill_dir):
                continue

            skill_md_path = os.path.join(skill_dir, "SKILL.md")
            if not os.path.isfile(skill_md_path):
                continue

            try:
                with open(skill_md_path, "r", encoding="utf-8") as f:
                    content = f.read()

                metadata, body = _parse_frontmatter(content)
                if metadata is None:
                    logger.warning(
                        f"[AgentSkillLoader] No frontmatter in {skill_md_path}, skipping"
                    )
                    continue

                name = metadata.get("name", entry)
                description = metadata.get("description", "")

                self._skills[name] = AgentSkill(
                    name=name,
                    description=description,
                    body=body.strip(),
                    directory=skill_dir,
                )
                logger.debug(f"[AgentSkillLoader] Discovered skill: {name}")

            except Exception as e:
                logger.warning(
                    f"[AgentSkillLoader] Failed to parse {skill_md_path}: {e}"
                )

        logger.info(
            f"[AgentSkillLoader] Discovered {len(self._skills)} skills: "
            f"{list(self._skills.keys())}"
        )
        return self._skills

    def load(self, *skill_names: str) -> List[AgentSkill]:
        """Load specific skills by name."""
        skills = self.discover()
        result = []
        for name in skill_names:
            if name in skills:
                result.append(skills[name])
            else:
                logger.warning(f"[AgentSkillLoader] Skill not found: {name}")
        return result

    def load_all(self) -> List[AgentSkill]:
        """Load all discovered skills."""
        skills = self.discover()
        return list(skills.values())

    def compose_prompt(self, skills: List[AgentSkill]) -> str:
        """
        Compose skills into a system prompt fragment.

        Each skill becomes a section with its name as the header,
        followed by the skill body content.
        """
        if not skills:
            return ""
        sections = []
        for skill in skills:
            sections.append(f"## Skill: {skill.name}\n\n{skill.body}")
        return "\n\n---\n\n".join(sections)
