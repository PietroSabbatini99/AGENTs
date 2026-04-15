"""User-facing configuration: provider, base URL, model, and API key.

Stored in `<workspace>/config.json` so the settings travel with the
workspace. Environment variables take precedence at startup so existing
`.env` users keep working.

Two providers are supported:

  - "ollama"    — local model via the Ollama OpenAI-compat endpoint.
  - "anthropic" — Claude via Anthropic's OpenAI-compat endpoint.

The UI lets the user switch between them with a radio toggle.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


# Ollama defaults — local, free, needs the daemon running.
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_OLLAMA_MODEL = "qwen3.5:4b"

# Anthropic defaults — hosted, needs an API key from the user.
# Anthropic exposes an OpenAI-compatible endpoint at /v1/ so we can reuse
# the same streaming code path as Ollama.
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1/"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"

DEFAULT_PROVIDER = "ollama"


@dataclass
class AppConfig:
    """User-editable runtime config."""

    provider: str = DEFAULT_PROVIDER               # "ollama" | "anthropic"
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    anthropic_api_key: str = ""
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL

    # ---- resolved fields used by the Team client ------------------------

    @property
    def base_url(self) -> str:
        if self.provider == "anthropic":
            return DEFAULT_ANTHROPIC_BASE_URL
        return self.ollama_base_url

    @property
    def model(self) -> str:
        if self.provider == "anthropic":
            return self.anthropic_model
        return self.ollama_model

    @property
    def api_key(self) -> str:
        if self.provider == "anthropic":
            return self.anthropic_api_key
        # Ollama ignores the key, but the OpenAI SDK requires a non-empty one.
        return "ollama"

    def public_dict(self) -> dict:
        """Config shape sent to the browser (API key redacted)."""
        return {
            "provider": self.provider,
            "ollama_base_url": self.ollama_base_url,
            "ollama_model": self.ollama_model,
            "anthropic_model": self.anthropic_model,
            "has_anthropic_key": bool(self.anthropic_api_key),
            # For display compatibility with existing code paths.
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

        # Backwards-compatibility: older configs stored `base_url` and
        # `model` at the top level. Map them into the Ollama slots.
        legacy_base = data.get("base_url", "").strip() if isinstance(data.get("base_url"), str) else ""
        legacy_model = data.get("model", "").strip() if isinstance(data.get("model"), str) else ""

        # Environment takes precedence over disk.
        env_provider = os.environ.get("AGENT_TEAM_PROVIDER", "").strip().lower()
        env_ollama_url = os.environ.get("AGENT_TEAM_BASE_URL", "").strip()
        env_ollama_model = os.environ.get("AGENT_TEAM_MODEL", "").strip()
        env_anthropic_key = os.environ.get("AGENT_TEAM_ANTHROPIC_API_KEY", "").strip()
        env_anthropic_model = os.environ.get("AGENT_TEAM_ANTHROPIC_MODEL", "").strip()

        provider = env_provider or data.get("provider", DEFAULT_PROVIDER)
        if provider not in ("ollama", "anthropic"):
            provider = DEFAULT_PROVIDER

        return AppConfig(
            provider=provider,
            ollama_base_url=env_ollama_url
                or data.get("ollama_base_url")
                or legacy_base
                or DEFAULT_OLLAMA_BASE_URL,
            ollama_model=env_ollama_model
                or data.get("ollama_model")
                or legacy_model
                or DEFAULT_OLLAMA_MODEL,
            anthropic_api_key=env_anthropic_key or data.get("anthropic_api_key", ""),
            anthropic_model=env_anthropic_model
                or data.get("anthropic_model")
                or DEFAULT_ANTHROPIC_MODEL,
        )

    def get(self) -> AppConfig:
        return self._config

    def update(
        self,
        *,
        provider: str | None = None,
        ollama_base_url: str | None = None,
        ollama_model: str | None = None,
        anthropic_api_key: str | None = None,
        anthropic_model: str | None = None,
    ) -> AppConfig:
        if provider is not None:
            p = provider.strip().lower()
            if p in ("ollama", "anthropic"):
                self._config.provider = p
        if ollama_base_url is not None and ollama_base_url.strip():
            self._config.ollama_base_url = ollama_base_url.strip().rstrip("/")
        if ollama_model is not None and ollama_model.strip():
            self._config.ollama_model = ollama_model.strip()
        if anthropic_api_key is not None:
            # Empty string clears the key intentionally.
            self._config.anthropic_api_key = anthropic_api_key.strip()
        if anthropic_model is not None and anthropic_model.strip():
            self._config.anthropic_model = anthropic_model.strip()
        self._save()
        return self._config

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(self._config), indent=2),
            encoding="utf-8",
        )
