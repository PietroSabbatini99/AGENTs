"""User-facing configuration: base URL, API key, and model selection.

Stored in `<workspace>/config.json` so the settings travel with the
workspace. Environment variables take precedence at startup so existing
`.env` users keep working.

Defaults to a local Ollama instance (http://localhost:11434/v1) with the
qwen3.5:4b model. The API key is optional — Ollama ignores it.
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
    api_key: str = ""
    model: str = DEFAULT_MODEL

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def effective_api_key(self) -> str:
        """Return the real key or a dummy for local servers that don't need one."""
        return self.api_key.strip() or "ollama"

    def public_dict(self) -> dict:
        """Safe-to-send-to-browser view: the key is masked."""
        masked = ""
        if self.api_key:
            key = self.api_key
            masked = f"{key[:7]}…{key[-4:]}" if len(key) > 12 else "set"
        return {
            "base_url": self.base_url,
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

        # Environment takes precedence over disk.
        env_url = os.environ.get("AGENT_TEAM_BASE_URL", "").strip()
        env_key = os.environ.get("AGENT_TEAM_API_KEY", "").strip()
        env_model = os.environ.get("AGENT_TEAM_MODEL", "").strip()

        return AppConfig(
            base_url=env_url or data.get("base_url", DEFAULT_BASE_URL),
            api_key=env_key or data.get("api_key", ""),
            model=env_model or data.get("model", DEFAULT_MODEL),
        )

    def get(self) -> AppConfig:
        return self._config

    def update(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> AppConfig:
        if base_url is not None and base_url.strip():
            self._config.base_url = base_url.strip().rstrip("/")
        if api_key is not None:
            self._config.api_key = api_key.strip()
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
        # Tighten permissions — this file may contain a secret.
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
