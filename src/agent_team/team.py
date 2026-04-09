"""The team orchestrator.

Wraps the Anthropic SDK and the shared Workspace into a small set of
collaboration patterns:

    Team.ask(specialist, question)         — single specialist replies
    Team.brief(project_idea)               — every specialist weighs in once
    Team.discuss(topic, rounds=2)          — round-robin discussion

Each call streams the agent's response to a user-supplied callback (the CLI
prints it live), then posts the reply to the shared workspace so the next
agent can read it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

import anthropic

from agent_team.profiles import (
    AGENT_PROFILES,
    DEFAULT_ROUND_ORDER,
    AgentProfile,
)
from agent_team.workspace import Workspace


DEFAULT_MODEL = os.environ.get("AGENT_TEAM_MODEL", "claude-opus-4-6")
DEFAULT_MAX_TOKENS = 2048


# Optional callback shape: (agent_key, agent_name, text_chunk) -> None
StreamCallback = Callable[[str, str, str], None]

# Optional RAG hook: (profile, user_message) -> extra system context (may be "").
ContextProvider = Callable[[AgentProfile, str], str]


@dataclass
class Reply:
    """A specialist's reply, returned and also persisted to the workspace."""

    agent_key: str
    agent_name: str
    role: str
    content: str


class Team:
    """A team of five specialists that share one Workspace."""

    def __init__(
        self,
        workspace: Workspace,
        client: anthropic.Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        profiles: Mapping[str, AgentProfile] | None = None,
        default_order: Iterable[str] | None = None,
        context_provider: ContextProvider | None = None,
    ) -> None:
        self.workspace = workspace
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        # Allow callers (the web UI) to pass a live registry that includes
        # user-added agents. Defaults to the built-in five.
        self._profiles: Mapping[str, AgentProfile] = (
            profiles if profiles is not None else AGENT_PROFILES
        )
        self._default_order: list[str] = (
            list(default_order) if default_order is not None else list(DEFAULT_ROUND_ORDER)
        )
        self.context_provider = context_provider

    # ---- agent lookup ---------------------------------------------------

    def get_profile(self, key_or_name: str) -> AgentProfile:
        k = key_or_name.lower().strip()
        if k in self._profiles:
            return self._profiles[k]
        for profile in self._profiles.values():
            if profile.name.lower() == k:
                return profile
        valid = ", ".join(self._profiles.keys())
        raise KeyError(f"Unknown specialist {key_or_name!r}. Try one of: {valid}")

    @property
    def profiles(self) -> list[AgentProfile]:
        order = [k for k in self._default_order if k in self._profiles]
        # Append any registered profiles not explicitly in the order.
        for k in self._profiles.keys():
            if k not in order:
                order.append(k)
        return [self._profiles[k] for k in order]

    @property
    def default_order(self) -> list[str]:
        return [k for k in self._default_order if k in self._profiles] + [
            k for k in self._profiles.keys() if k not in self._default_order
        ]

    # ---- core single-call -----------------------------------------------

    def _run_specialist(
        self,
        profile: AgentProfile,
        user_message: str,
        on_stream: StreamCallback | None = None,
    ) -> str:
        """Call one specialist with the current workspace context.

        Streams the response so the CLI can print it live, and returns the
        full text once the stream completes.
        """
        # Inject the workspace state into the system prompt. This is the
        # mechanism by which agents "see" what each other have written.
        snapshot = self.workspace.snapshot()

        # Let the context provider (e.g. the web UI's RAG store) add any
        # retrieved knowledge for this agent. Empty string if disabled.
        extra = ""
        if self.context_provider is not None:
            try:
                extra = self.context_provider(profile, user_message) or ""
            except Exception:
                extra = ""

        system_parts = [profile.system_prompt, "---", snapshot]
        if extra.strip():
            system_parts.extend(["---", extra.strip()])
        system_parts.append(
            f"You are {profile.name}, the {profile.role}. Reply in your own voice."
        )
        system = "\n\n".join(system_parts)

        chunks: list[str] = []
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                chunks.append(text)
                if on_stream is not None:
                    on_stream(profile.key, profile.name, text)

        return "".join(chunks).strip()

    # ---- public collaboration patterns ----------------------------------

    def ask(
        self,
        specialist: str,
        question: str,
        on_stream: StreamCallback | None = None,
    ) -> Reply:
        """Send a question to a single specialist."""
        profile = self.get_profile(specialist)

        # Persist the user's question first so it shows up in the workspace
        # for any future round.
        self.workspace.post_message(
            sender_key="user",
            sender_name="User",
            content=question,
        )

        text = self._run_specialist(profile, question, on_stream)
        self.workspace.post_message(
            sender_key=profile.key,
            sender_name=profile.name,
            content=text,
        )
        return Reply(
            agent_key=profile.key,
            agent_name=profile.name,
            role=profile.role,
            content=text,
        )

    def brief(
        self,
        project_idea: str,
        on_stream: StreamCallback | None = None,
        order: Iterable[str] | None = None,
    ) -> list[Reply]:
        """Open a new project. Every specialist gives their first take.

        Each agent reads everything posted before them — so Iris frames the
        creative angle first, Vitruvio responds in the physical/spatial
        register, Atlas works the numbers, Nova plans the execution, Solon
        flags the legal exposure.
        """
        order_keys = list(order) if order is not None else self.default_order

        # Post the brief itself as a user message.
        self.workspace.post_message(
            sender_key="user",
            sender_name="User",
            content=f"NEW PROJECT BRIEF: {project_idea}",
        )

        prompt = (
            f"The user has just shared a new project brief:\n\n"
            f"  {project_idea}\n\n"
            f"Give your first take from your specialty, in roughly one screen "
            f"of text. Read what teammates have already posted in the workspace "
            f"snapshot above and build on it — do not repeat their points. "
            f"End with the two or three questions you most need answered to "
            f"go further."
        )

        replies: list[Reply] = []
        for key in order_keys:
            profile = self.get_profile(key)
            text = self._run_specialist(profile, prompt, on_stream)
            self.workspace.post_message(
                sender_key=profile.key,
                sender_name=profile.name,
                content=text,
            )
            replies.append(
                Reply(
                    agent_key=profile.key,
                    agent_name=profile.name,
                    role=profile.role,
                    content=text,
                )
            )
        return replies

    def discuss(
        self,
        topic: str,
        rounds: int = 2,
        on_stream: StreamCallback | None = None,
        order: Iterable[str] | None = None,
    ) -> list[Reply]:
        """Round-robin discussion. Each specialist speaks once per round.

        Round 1 is each agent's opening view. Round 2+ is rebuttals and
        synthesis — each agent has now read every other agent's prior posts.
        """
        order_keys = list(order) if order is not None else self.default_order

        self.workspace.post_message(
            sender_key="user",
            sender_name="User",
            content=f"DISCUSSION TOPIC: {topic}",
        )

        replies: list[Reply] = []
        for round_idx in range(rounds):
            round_label = f"Round {round_idx + 1} of {rounds}"
            for key in order_keys:
                profile = self.get_profile(key)
                if round_idx == 0:
                    prompt = (
                        f"{round_label}. The team is discussing:\n\n"
                        f"  {topic}\n\n"
                        f"Give your opening position from your specialty. "
                        f"Be concrete and brief."
                    )
                else:
                    prompt = (
                        f"{round_label}. The team is still discussing:\n\n"
                        f"  {topic}\n\n"
                        f"Read the prior round in the workspace snapshot above. "
                        f"Respond to the points your teammates raised — agree, "
                        f"disagree, refine, or extend. Do not repeat your "
                        f"opening verbatim."
                    )
                text = self._run_specialist(profile, prompt, on_stream)
                self.workspace.post_message(
                    sender_key=profile.key,
                    sender_name=profile.name,
                    content=text,
                )
                replies.append(
                    Reply(
                        agent_key=profile.key,
                        agent_name=profile.name,
                        role=profile.role,
                        content=text,
                    )
                )
        return replies
