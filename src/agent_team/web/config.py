"""User-facing configuration: base URL and model selection.

Stored in `<workspace>/config.json` so the settings travel with the
workspace. Environment variables take precedence at startup so existing
`.env` users keep working.

Defaults to a local Ollama instance (http://localhost:11434/v1) with the
qwen3.5:4b model.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen3.5:4b"


@dataclass
class AppConfig:
    """User-editable runtime config."""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL

    def public_dict(self) -> dict:
        return {
            "base_url": self.base_url,
            "model": self.model,
        }


class ConfigStore:
    """Reads / writes the config JSON next to the workspace."""

    def __init__(self, workspace_root: Path) -> None:
        self.path = Path(workspace_root) / "config.json"
        self._config = self._load()

    def _load(self) -> AppConfig:
        data: dict = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}

        # Environment takes precedence over disk.
        env_url = os.environ.get("AGENT_TEAM_BASE_URL", "").strip()
        env_model = os.environ.get("AGENT_TEAM_MODEL", "").strip()

        return AppConfig(
            base_url=env_url or data.get("base_url", DEFAULT_BASE_URL),
            model=env_model or data.get("model", DEFAULT_MODEL),
        )

    def get(self) -> AppConfig:
        return self._config

    def update(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
    ) -> AppConfig:
        if base_url is not None and base_url.strip():
            self._config.base_url = base_url.strip().rstrip("/")
        if model is not None and model.strip():
            self._config.model = model.strip()
        self._save()
        return self._config

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(self._config), indent=2),
            encoding="utf-8",
        )
