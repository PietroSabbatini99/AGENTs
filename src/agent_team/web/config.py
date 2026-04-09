"""User-facing configuration: API key and model selection.

Stored in `<workspace>/config.json` so the settings travel with the
workspace. Environment variables take precedence at startup so existing
`.env` users keep working.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_MODEL = "claude-opus-4-6"


@dataclass
class AppConfig:
    """User-editable runtime config."""

    anthropic_api_key: str = ""
    model: str = DEFAULT_MODEL

    @property
    def has_api_key(self) -> bool:
        return bool(self.anthropic_api_key.strip())

    def public_dict(self) -> dict:
        """Safe-to-send-to-browser view: the key is masked."""
        masked = ""
        if self.anthropic_api_key:
            key = self.anthropic_api_key
            masked = f"{key[:7]}…{key[-4:]}" if len(key) > 12 else "set"
        return {
            "api_key_set": self.has_api_key,
            "api_key_masked": masked,
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

        # Environment takes precedence over disk so deploys with secrets
        # in env vars keep working.
        env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        env_model = os.environ.get("AGENT_TEAM_MODEL", "").strip()

        return AppConfig(
            anthropic_api_key=env_key or data.get("anthropic_api_key", ""),
            model=env_model or data.get("model", DEFAULT_MODEL),
        )

    def get(self) -> AppConfig:
        return self._config

    def update(self, *, api_key: str | None = None, model: str | None = None) -> AppConfig:
        if api_key is not None:
            self._config.anthropic_api_key = api_key.strip()
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
        # Tighten permissions — this file contains a secret.
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
