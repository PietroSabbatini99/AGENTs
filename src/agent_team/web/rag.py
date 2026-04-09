"""A tiny per-agent RAG knowledge base.

Each agent gets a private folder under `<workspace>/rag/<agent_key>/` with:

  - `<source>.txt`           — the raw extracted text of an uploaded source
  - `index.json`             — metadata + chunk table for retrieval

Retrieval uses a BM25-lite scoring function implemented in pure Python so
there are no heavy ML dependencies. It is good enough for a few dozen
documents and makes it obvious how to swap in a vector store later.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _slugify(text: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len] or "source"


def _chunk_text(text: str, chunk_size: int = 900, overlap: int = 150) -> list[str]:
    """Split on paragraph boundaries, then greedy-pack into ~chunk_size windows."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if not current:
            current = para
            continue
        if len(current) + 2 + len(para) <= chunk_size:
            current = current + "\n\n" + para
        else:
            chunks.append(current)
            # Carry over the tail of the previous chunk for context overlap.
            tail = current[-overlap:] if overlap else ""
            current = (tail + "\n\n" + para).strip() if tail else para
    if current:
        chunks.append(current)
    return chunks


@dataclass
class Chunk:
    id: str
    source_id: str
    source_name: str
    text: str


@dataclass
class Source:
    id: str
    name: str
    kind: str  # "pdf" | "text" | "md" | etc.
    added_at: str
    chunk_count: int
    chunk_ids: list[str] = field(default_factory=list)


class AgentKnowledgeBase:
    """One per-agent BM25-backed knowledge base."""

    def __init__(self, root: Path, agent_key: str) -> None:
        self.agent_key = agent_key
        self.root = Path(root) / agent_key
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self.sources: dict[str, Source] = {}
        self.chunks: dict[str, Chunk] = {}
        self._load()

    # ---- persistence ----------------------------------------------------

    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for s in data.get("sources", []):
            try:
                self.sources[s["id"]] = Source(**s)
            except (TypeError, KeyError):
                continue
        for c in data.get("chunks", []):
            try:
                self.chunks[c["id"]] = Chunk(**c)
            except (TypeError, KeyError):
                continue

    def _save(self) -> None:
        data = {
            "sources": [asdict(s) for s in self.sources.values()],
            "chunks": [asdict(c) for c in self.chunks.values()],
        }
        self.index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ---- ingestion ------------------------------------------------------

    def add_source(self, name: str, kind: str, text: str, added_at: str) -> Source:
        chunks = _chunk_text(text)
        source_id = uuid.uuid4().hex[:12]
        chunk_ids: list[str] = []
        for piece in chunks:
            cid = uuid.uuid4().hex[:12]
            self.chunks[cid] = Chunk(
                id=cid,
                source_id=source_id,
                source_name=name,
                text=piece,
            )
            chunk_ids.append(cid)
        source = Source(
            id=source_id,
            name=name,
            kind=kind,
            added_at=added_at,
            chunk_count=len(chunk_ids),
            chunk_ids=chunk_ids,
        )
        self.sources[source_id] = source

        # Save the raw text for human inspection.
        raw_path = self.root / f"{_slugify(name)}-{source_id}.txt"
        raw_path.write_text(text, encoding="utf-8")

        self._save()
        return source

    def remove_source(self, source_id: str) -> bool:
        source = self.sources.pop(source_id, None)
        if source is None:
            return False
        for cid in source.chunk_ids:
            self.chunks.pop(cid, None)
        # Best-effort delete of the raw text file.
        for p in self.root.glob(f"*-{source_id}.txt"):
            try:
                p.unlink()
            except OSError:
                pass
        self._save()
        return True

    def list_sources(self) -> list[dict]:
        return [
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind,
                "added_at": s.added_at,
                "chunk_count": s.chunk_count,
            }
            for s in sorted(self.sources.values(), key=lambda s: s.added_at, reverse=True)
        ]

    # ---- retrieval ------------------------------------------------------

    def search(self, query: str, top_k: int = 4) -> list[Chunk]:
        """BM25-lite scoring over stored chunks."""
        if not self.chunks:
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        # Pre-compute per-chunk token counts and the corpus statistics.
        docs: list[tuple[str, list[str]]] = [
            (cid, _tokenize(chunk.text)) for cid, chunk in self.chunks.items()
        ]
        avgdl = sum(len(toks) for _, toks in docs) / max(len(docs), 1)
        df: dict[str, int] = {}
        for _, toks in docs:
            for term in set(toks):
                df[term] = df.get(term, 0) + 1
        N = len(docs)
        k1 = 1.4
        b = 0.75

        def idf(term: str) -> float:
            n = df.get(term, 0)
            return math.log(1 + (N - n + 0.5) / (n + 0.5))

        scored: list[tuple[float, str]] = []
        for cid, toks in docs:
            if not toks:
                continue
            dl = len(toks)
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            for q in q_tokens:
                if q not in tf:
                    continue
                f = tf[q]
                num = f * (k1 + 1)
                den = f + k1 * (1 - b + b * dl / max(avgdl, 1))
                score += idf(q) * (num / den)
            if score > 0:
                scored.append((score, cid))

        scored.sort(reverse=True)
        return [self.chunks[cid] for _, cid in scored[:top_k]]


class RagStore:
    """Routes per-agent knowledge bases and hands out the Team context hook."""

    def __init__(self, workspace_root: Path) -> None:
        self.root = Path(workspace_root) / "rag"
        self.root.mkdir(parents=True, exist_ok=True)
        self._bases: dict[str, AgentKnowledgeBase] = {}

    def kb(self, agent_key: str) -> AgentKnowledgeBase:
        if agent_key not in self._bases:
            self._bases[agent_key] = AgentKnowledgeBase(self.root, agent_key)
        return self._bases[agent_key]

    def drop(self, agent_key: str) -> None:
        self._bases.pop(agent_key, None)

    # ---- the Team context hook -----------------------------------------

    def context_for(self, profile, user_message: str, top_k: int = 4) -> str:
        kb = self.kb(profile.key)
        hits = kb.search(user_message, top_k=top_k)
        if not hits:
            return ""
        blocks = [
            "### Retrieved knowledge (from your private knowledge base)",
            "Use these excerpts when they are relevant. If you cite one, name the source.",
            "",
        ]
        for i, chunk in enumerate(hits, 1):
            blocks.append(f"**[{i}] {chunk.source_name}**")
            blocks.append(chunk.text.strip())
            blocks.append("")
        return "\n".join(blocks).strip()


# ---------------------------------------------------------------------------
# File extraction helpers used by the upload endpoint
# ---------------------------------------------------------------------------


def extract_text_from_upload(filename: str, data: bytes) -> tuple[str, str]:
    """Return (kind, text) for a freshly uploaded file.

    Kinds: "pdf", "text", "md". Raises ValueError on unsupported types.
    """
    lower = filename.lower()
    if lower.endswith(".pdf"):
        text = _extract_pdf_text(data)
        return "pdf", text
    if lower.endswith(".md") or lower.endswith(".markdown"):
        return "md", data.decode("utf-8", errors="replace")
    if lower.endswith((".txt", ".rst", ".csv", ".json", ".log", ".py")):
        return "text", data.decode("utf-8", errors="replace")
    # Last-ditch: try utf-8 decode and treat it as text if it's printable.
    try:
        text = data.decode("utf-8")
        return "text", text
    except UnicodeDecodeError as e:
        raise ValueError(
            f"Unsupported file type: {filename}. Upload PDF, text, or markdown."
        ) from e


def _extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError(
            "pypdf is required to read PDFs. Install with `pip install pypdf`."
        ) from e
    import io

    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n\n".join(p.strip() for p in pages if p.strip())
