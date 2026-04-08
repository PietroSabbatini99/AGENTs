"""A team of specialist AI agents that collaborate through a shared workspace.

The package is intentionally lazy: importing `agent_team` does not pull in
`anthropic`, so the Workspace and profiles are usable as standalone library
pieces (handy for tests and for swapping the LLM backend).
"""

from agent_team.profiles import AGENT_PROFILES, AgentProfile
from agent_team.workspace import Workspace

__all__ = ["AGENT_PROFILES", "AgentProfile", "Team", "Workspace"]


def __getattr__(name: str):
    if name == "Team":
        from agent_team.team import Team

        return Team
    raise AttributeError(f"module 'agent_team' has no attribute {name!r}")
