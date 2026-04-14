"""Chat command orchestrator.

Parses a user chat message and dispatches it to the right Team pattern:

  /ask <name> <question>     → team.ask(name, question)
  @<Name> <question>         → team.ask(Name, question)
  /brief <idea>              → team.brief(idea)          [whole team]
  /discuss <topic> [--rounds N] → team.discuss(topic, rounds=N)
  (plain text)               → kind="auto"               [router decides]

The orchestrator itself never calls the model — it just normalizes the
command. When the kind is "auto" the web layer calls `router.route_query`
to pick the specialist(s), then runs the chosen pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedCommand:
    kind: str               # "ask" | "brief" | "discuss" | "auto"
    content: str            # the question / idea / topic, trimmed
    specialist: str | None = None   # only for "ask"
    rounds: int = 2                  # only for "discuss"


_DISCUSS_ROUNDS_RE = re.compile(r"\s*--rounds\s+(\d+)\s*$")


def parse_command(raw: str, known_names: list[str]) -> ParsedCommand:
    """Parse a chat input into a command for the Team.

    `known_names` is the list of all agent display names (e.g. ["Atlas",
    "Iris", ...]) — used to recognize `@Atlas` mentions and `/ask Atlas ...`
    even though the user typed the capitalized display name, not the key.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty message")

    lower_names = {n.lower(): n for n in known_names}

    # /ask <name> <question>
    if text.lower().startswith("/ask"):
        rest = text[len("/ask"):].strip()
        if not rest:
            raise ValueError("usage: /ask <specialist> <question>")
        bits = rest.split(maxsplit=1)
        if len(bits) < 2:
            raise ValueError("usage: /ask <specialist> <question>")
        name = bits[0].lstrip("@")
        if name.lower() not in lower_names:
            raise ValueError(
                f"unknown specialist '{name}'. Try one of: {', '.join(known_names)}"
            )
        return ParsedCommand(kind="ask", specialist=lower_names[name.lower()], content=bits[1].strip())

    # /brief <idea>
    if text.lower().startswith("/brief"):
        content = text[len("/brief"):].strip()
        if not content:
            raise ValueError("usage: /brief <project idea>")
        return ParsedCommand(kind="brief", content=content)

    # /discuss <topic> [--rounds N]
    if text.lower().startswith("/discuss"):
        body = text[len("/discuss"):].strip()
        rounds = 2
        match = _DISCUSS_ROUNDS_RE.search(body)
        if match:
            rounds = max(1, min(int(match.group(1)), 6))
            body = body[: match.start()].strip()
        if not body:
            raise ValueError("usage: /discuss <topic> [--rounds N]")
        return ParsedCommand(kind="discuss", content=body, rounds=rounds)

    # @Name <question>
    if text.startswith("@"):
        bits = text[1:].split(maxsplit=1)
        if len(bits) >= 1 and bits[0].lower() in lower_names:
            question = bits[1].strip() if len(bits) > 1 else ""
            if not question:
                raise ValueError(f"mention @{bits[0]} needs a question after it")
            return ParsedCommand(
                kind="ask",
                specialist=lower_names[bits[0].lower()],
                content=question,
            )

    # Default: let the router decide who should answer.
    return ParsedCommand(kind="auto", content=text)
