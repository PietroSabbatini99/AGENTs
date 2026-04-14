"""Lightweight LLM-based query router.

Given a plain-text user query and the available agents, calls the LLM with
a small, strict prompt to decide:

  - mode:   "ask" (one specialist) | "brief" (several) | "discuss" (debate)
  - agents: which agent keys should answer
  - why:    a short explanation (for UI feedback)

The routing call uses the same local model as the agents themselves, but
with a small max_tokens budget and a JSON-only instruction. Failures fall
back to "brief with everyone" so the team never goes silent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Mapping

from agent_team.profiles import AgentProfile


# Keep these tiny so qwen3.5:4b can route in well under a second.
ROUTER_MAX_TOKENS = 200


@dataclass
class Route:
    mode: str            # "ask" | "brief" | "discuss"
    agents: list[str]    # agent keys, in order
    why: str             # short reasoning for the UI


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _build_prompt(query: str, profiles: Mapping[str, AgentProfile]) -> str:
    roster = "\n".join(
        f"- {p.key}: {p.name} — {p.role}" for p in profiles.values()
    )
    keys = ", ".join(f'"{k}"' for k in profiles.keys())
    return (
        "You route user queries to the right specialist(s) on an AI team.\n\n"
        f"Team:\n{roster}\n\n"
        f"User query:\n{query!r}\n\n"
        "Rules:\n"
        '  - If the query clearly belongs to ONE specialist, mode="ask" and agents=[that one].\n'
        '  - If it spans 2-3 domains, mode="brief" and agents=[those].\n'
        '  - If it is a debate / tradeoff / comparison, mode="discuss" and agents=[relevant ones].\n'
        '  - If it is a broad project brief or unclear, mode="brief" and agents=[all].\n'
        f"  - Use ONLY agent keys from this list: [{keys}].\n\n"
        "Reply with ONLY a single JSON object, no markdown, no commentary, like:\n"
        '{"mode":"ask","agents":["atlas"],"why":"financial question"}\n'
    )


def _parse_route(raw: str, profiles: Mapping[str, AgentProfile]) -> Route | None:
    m = _JSON_RE.search(raw or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

    mode = str(data.get("mode", "")).strip().lower()
    if mode not in ("ask", "brief", "discuss"):
        return None

    raw_agents = data.get("agents") or []
    if not isinstance(raw_agents, list):
        return None
    keys: list[str] = []
    for a in raw_agents:
        if not isinstance(a, str):
            continue
        k = a.strip().lower()
        # Accept either the key or the display name.
        if k in profiles:
            keys.append(k)
        else:
            for key, p in profiles.items():
                if p.name.lower() == k and key not in keys:
                    keys.append(key)
                    break
    # "ask" needs exactly one; fallback to "brief" if the model picked many.
    if mode == "ask" and len(keys) != 1:
        if len(keys) > 1:
            mode = "brief"
        else:
            return None
    if not keys:
        return None

    why = str(data.get("why", "")).strip()[:200]
    return Route(mode=mode, agents=keys, why=why)


def route_query(
    client,
    model: str,
    query: str,
    profiles: Mapping[str, AgentProfile],
) -> Route:
    """Ask the model which specialist(s) should handle this query.

    Returns a Route. On any failure (malformed JSON, connection error, etc.)
    falls back to a whole-team brief so the team never goes silent.
    """
    prompt = _build_prompt(query, profiles)
    fallback = Route(
        mode="brief",
        agents=list(profiles.keys()),
        why="router fallback — whole team",
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=ROUTER_MAX_TOKENS,
            messages=[
                {
                    "role": "system",
                    "content": "You are a silent router. Reply with ONLY a JSON object.",
                },
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )
        raw = resp.choices[0].message.content or ""
    except Exception:
        return fallback

    route = _parse_route(raw, profiles)
    return route or fallback
