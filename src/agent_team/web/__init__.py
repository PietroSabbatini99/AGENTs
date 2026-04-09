"""Web UI for the agent team.

A thin FastAPI app on top of the `agent_team` core: a group chat with the
five specialists, file and PDF uploads, a per-agent RAG knowledge base, a
form to add new agents, and a settings screen to link an Anthropic account.

The web module is optional — the package's core (profiles, workspace,
team) still runs without FastAPI installed.
"""

from __future__ import annotations


def __getattr__(name: str):
    if name == "create_app":
        from agent_team.web.app import create_app

        return create_app
    raise AttributeError(f"module 'agent_team.web' has no attribute {name!r}")
