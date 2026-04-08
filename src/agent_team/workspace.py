"""The shared workspace.

This is the "cloud space" where the five specialists communicate. It is
deliberately a thin file-based abstraction so the rest of the system depends
only on its public methods. To swap the backend for S3, Redis, a database,
or a real cloud workspace, re-implement this class with the same surface.

Layout:

    workspace/
    ├── messages/     individual JSON files, one per posted message
    ├── documents/    Markdown artifacts produced by the team
    └── decisions/    JSON files in the decision log
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class Message:
    """A single chat-style message in the shared space."""

    timestamp: str        # ISO 8601 UTC
    sender: str           # agent key, or "user", or "system"
    sender_name: str      # display name
    content: str
    in_reply_to: str | None = None  # filename of the message this replies to

    def to_markdown(self) -> str:
        when = self.timestamp.replace("T", " ").split(".")[0] + "Z"
        return f"**[{when}] {self.sender_name}:** {self.content}"


@dataclass
class Document:
    """A shared artifact produced by the team."""

    name: str
    author: str
    created_at: str
    content: str


@dataclass
class Decision:
    """An entry in the decision log."""

    timestamp: str
    title: str
    decision: str
    rationale: str
    proposed_by: str
    dissent: str = ""
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len] or "item"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_compact() -> str:
    # Filename-safe timestamp like 20260408T184205Z
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class Workspace:
    """A shared workspace backed by the file system.

    Public surface used by the rest of the system:
        post_message, read_messages, recent_messages_text
        save_document, read_document, list_documents, documents_index_text
        log_decision, read_decisions, decisions_index_text
        snapshot, reset
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.messages_dir = self.root / "messages"
        self.documents_dir = self.root / "documents"
        self.decisions_dir = self.root / "decisions"
        for d in (self.messages_dir, self.documents_dir, self.decisions_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- messages -------------------------------------------------------

    def post_message(
        self,
        sender_key: str,
        sender_name: str,
        content: str,
        in_reply_to: str | None = None,
    ) -> Message:
        msg = Message(
            timestamp=_now_iso(),
            sender=sender_key,
            sender_name=sender_name,
            content=content.strip(),
            in_reply_to=in_reply_to,
        )
        filename = f"{_now_compact()}-{_slugify(sender_key)}.json"
        path = self.messages_dir / filename
        # If the slug collides within the same second, add a counter
        i = 1
        while path.exists():
            path = self.messages_dir / f"{_now_compact()}-{_slugify(sender_key)}-{i}.json"
            i += 1
        path.write_text(json.dumps(asdict(msg), indent=2), encoding="utf-8")
        return msg

    def read_messages(self, limit: int | None = None) -> list[Message]:
        files = sorted(self.messages_dir.glob("*.json"))
        if limit is not None:
            files = files[-limit:]
        out: list[Message] = []
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                out.append(Message(**data))
            except (json.JSONDecodeError, TypeError):
                # Skip corrupted entries rather than blowing up the team.
                continue
        return out

    def recent_messages_text(self, limit: int = 12) -> str:
        msgs = self.read_messages(limit=limit)
        if not msgs:
            return "(no messages yet)"
        return "\n\n".join(m.to_markdown() for m in msgs)

    # ---- documents ------------------------------------------------------

    def save_document(self, name: str, author: str, content: str) -> Document:
        doc = Document(
            name=name,
            author=author,
            created_at=_now_iso(),
            content=content.strip() + "\n",
        )
        filename = f"{_slugify(name)}.md"
        path = self.documents_dir / filename
        # Don't overwrite — append a counter if needed.
        i = 1
        stem = path.stem
        while path.exists():
            path = self.documents_dir / f"{stem}-{i}.md"
            i += 1
        header = (
            f"# {doc.name}\n\n"
            f"_Author: {author} · Created: {doc.created_at}_\n\n---\n\n"
        )
        path.write_text(header + doc.content, encoding="utf-8")
        return doc

    def read_document(self, name: str) -> str | None:
        path = self.documents_dir / f"{_slugify(name)}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def list_documents(self) -> list[str]:
        return sorted(p.name for p in self.documents_dir.glob("*.md"))

    def documents_index_text(self) -> str:
        names = self.list_documents()
        if not names:
            return "(no documents yet)"
        return "\n".join(f"- {n}" for n in names)

    # ---- decisions ------------------------------------------------------

    def log_decision(
        self,
        title: str,
        decision: str,
        rationale: str,
        proposed_by: str,
        dissent: str = "",
        tags: Iterable[str] = (),
    ) -> Decision:
        d = Decision(
            timestamp=_now_iso(),
            title=title,
            decision=decision.strip(),
            rationale=rationale.strip(),
            proposed_by=proposed_by,
            dissent=dissent.strip(),
            tags=list(tags),
        )
        filename = f"{_now_compact()}-{_slugify(title)}.json"
        path = self.decisions_dir / filename
        path.write_text(json.dumps(asdict(d), indent=2), encoding="utf-8")
        return d

    def read_decisions(self) -> list[Decision]:
        files = sorted(self.decisions_dir.glob("*.json"))
        out: list[Decision] = []
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                out.append(Decision(**data))
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    def decisions_index_text(self) -> str:
        decisions = self.read_decisions()
        if not decisions:
            return "(no decisions logged yet)"
        lines = []
        for d in decisions:
            when = d.timestamp.replace("T", " ").split("+")[0] + "Z"
            lines.append(f"- [{when}] {d.title} — {d.decision} (by {d.proposed_by})")
        return "\n".join(lines)

    # ---- snapshots and reset --------------------------------------------

    def snapshot(self, recent_messages: int = 12) -> str:
        """Render the workspace as the context block injected into each agent."""
        return (
            "## Shared workspace snapshot\n\n"
            "### Recent messages\n"
            f"{self.recent_messages_text(limit=recent_messages)}\n\n"
            "### Documents in workspace/documents\n"
            f"{self.documents_index_text()}\n\n"
            "### Decision log\n"
            f"{self.decisions_index_text()}\n"
        )

    def reset(self) -> None:
        """Wipe everything except .gitkeep markers."""
        for d in (self.messages_dir, self.documents_dir, self.decisions_dir):
            for p in d.iterdir():
                if p.name == ".gitkeep":
                    continue
                if p.is_file():
                    p.unlink()
