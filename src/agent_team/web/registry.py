"""Agent registry: built-in profiles + user-added custom agents.

Custom agents are persisted in `<workspace>/custom_agents.json` so they
survive restarts and can be edited by hand if needed.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from agent_team.profiles import (
    AGENT_PROFILES,
    COLLABORATION_PREAMBLE,
    DEFAULT_ROUND_ORDER,
    AgentProfile,
)


_KEY_RE = re.compile(r"[^a-z0-9_]+")


def _keyify(name: str) -> str:
    k = _KEY_RE.sub("_", name.lower()).strip("_")
    return k or "agent"


class AgentRegistry:
    """Merges built-in AGENT_PROFILES with custom JSON-backed entries."""

    def __init__(self, workspace_root: Path) -> None:
        self.path = Path(workspace_root) / "custom_agents.json"
        self._custom: dict[str, AgentProfile] = {}
        self._load()

    # ---- persistence ----------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for entry in raw.get("agents", []):
            try:
                profile = AgentProfile(
                    key=entry["key"],
                    name=entry["name"],
                    role=entry["role"],
                    system_prompt=entry["system_prompt"],
                )
            except KeyError:
                continue
            self._custom[profile.key] = profile

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"agents": [asdict(p) for p in self._custom.values()]}
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ---- public API -----------------------------------------------------

    def all(self) -> dict[str, AgentProfile]:
        """Built-ins first, then custom agents, keyed by their unique key."""
        merged: dict[str, AgentProfile] = dict(AGENT_PROFILES)
        for key, profile in self._custom.items():
            merged[key] = profile
        return merged

    def default_order(self) -> list[str]:
        order = [k for k in DEFAULT_ROUND_ORDER if k in AGENT_PROFILES]
        for key in self._custom:
            if key not in order:
                order.append(key)
        return order

    def get(self, key_or_name: str) -> AgentProfile | None:
        merged = self.all()
        k = key_or_name.lower().strip()
        if k in merged:
            return merged[k]
        for profile in merged.values():
            if profile.name.lower() == k:
                return profile
        return None

    def is_custom(self, key: str) -> bool:
        return key in self._custom

    def add(self, name: str, role: str, system_prompt: str) -> AgentProfile:
        """Create a new custom agent. The system prompt is wrapped in the
        shared collaboration preamble so newcomers still follow team norms.
        """
        name = name.strip()
        role = role.strip()
        body = system_prompt.strip()
        if not name or not role or not body:
            raise ValueError("name, role, and system_prompt are all required")

        key = _keyify(name)
        # Avoid collisions with built-ins or existing customs.
        base = key
        merged = self.all()
        i = 2
        while key in merged:
            key = f"{base}_{i}"
            i += 1

        wrapped_prompt = (
            COLLABORATION_PREAMBLE
            + f"\n\nYou are {name.upper()}, the team's {role}.\n\n"
            + body
        )
        profile = AgentProfile(
            key=key,
            name=name,
            role=role,
            system_prompt=wrapped_prompt,
        )
        self._custom[key] = profile
        self._save()
        return profile

    def remove(self, key: str) -> bool:
        if key in self._custom:
            del self._custom[key]
            self._save()
            return True
        return False

    def list_keys(self) -> Iterable[str]:
        return self.all().keys()
