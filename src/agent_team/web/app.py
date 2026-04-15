"""FastAPI app for the agent team UI.

Routes:

    GET  /                    — the single-page UI
    GET  /api/state           — team + config snapshot
    POST /api/config          — set base URL / model
    GET  /api/agents          — list all agents (built-in + custom)
    POST /api/agents          — add a custom agent
    DELETE /api/agents/{key}  — remove a custom agent
    POST /api/chat            — send a chat message, streams reply (SSE)
    POST /api/upload          — upload a file/pdf as a shared workspace doc
    GET  /api/workspace       — current workspace snapshot
    POST /api/workspace/reset — wipe the workspace
    GET  /api/rag/{agent}     — list knowledge sources for one agent
    POST /api/rag/{agent}     — upload a source into one agent's knowledge base
    DELETE /api/rag/{agent}/{source_id} — remove one source
"""

from __future__ import annotations

import json
import queue
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from agent_team.web.config import ConfigStore
from agent_team.web.orchestrator import ParsedCommand, parse_command
from agent_team.web.rag import RagStore, extract_text_from_upload
from agent_team.web.registry import AgentRegistry
from agent_team.web.router import route_query
from agent_team.workspace import Workspace


WEB_ROOT = Path(__file__).resolve().parent
STATIC_DIR = WEB_ROOT / "static"
TEMPLATES_DIR = WEB_ROOT / "templates"


def create_app(workspace_root: Path) -> FastAPI:
    """Build a configured FastAPI app bound to `workspace_root`."""
    workspace = Workspace(workspace_root)
    config_store = ConfigStore(workspace.root)
    registry = AgentRegistry(workspace.root)
    rag_store = RagStore(workspace.root)

    app = FastAPI(title="Agent Team", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ---- lazy Team builder -------------------------------------------------
    # We construct a fresh Team per request because (a) the config may have
    # just changed on the settings screen and (b) the registry may include a
    # just-added custom agent. The client is cheap to instantiate.

    def build_team():
        from openai import OpenAI

        from agent_team.team import Team

        cfg = config_store.get()
        if cfg.provider == "anthropic" and not cfg.anthropic_api_key:
            raise HTTPException(
                status_code=400,
                detail="Anthropic is selected but no API key is set. Add one in Settings.",
            )
        client = OpenAI(
            base_url=cfg.base_url,
            api_key=cfg.api_key,
        )
        return Team(
            workspace=workspace,
            client=client,
            model=cfg.model,
            profiles=registry.all(),
            default_order=registry.default_order(),
            context_provider=rag_store.context_for,
        )

    # ---- serialization helpers --------------------------------------------

    def agent_to_dict(key: str) -> dict:
        profile = registry.all()[key]
        return {
            "key": profile.key,
            "name": profile.name,
            "role": profile.role,
            "is_custom": registry.is_custom(profile.key),
        }

    def all_agents_payload() -> list[dict]:
        order = registry.default_order()
        return [agent_to_dict(k) for k in order]

    # ---- static / index ---------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        # Render the index template directly — we don't actually need any
        # Jinja substitutions since the UI hydrates from /api/state on load.
        return HTMLResponse((TEMPLATES_DIR / "index.html").read_text(encoding="utf-8"))

    # ---- state / config ---------------------------------------------------

    @app.get("/api/state")
    def get_state():
        return {
            "agents": all_agents_payload(),
            "config": config_store.get().public_dict(),
        }

    @app.post("/api/config")
    async def update_config(request: Request):
        body = await request.json()
        cfg = config_store.update(
            provider=body.get("provider"),
            ollama_base_url=body.get("ollama_base_url"),
            ollama_model=body.get("ollama_model"),
            anthropic_api_key=body.get("anthropic_api_key"),
            anthropic_model=body.get("anthropic_model"),
        )
        return {"config": cfg.public_dict()}

    # ---- agents -----------------------------------------------------------

    @app.get("/api/agents")
    def list_agents():
        return {"agents": all_agents_payload()}

    @app.post("/api/agents")
    async def add_agent(request: Request):
        body = await request.json()
        try:
            profile = registry.add(
                name=body.get("name", ""),
                role=body.get("role", ""),
                system_prompt=body.get("system_prompt", ""),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"agent": agent_to_dict(profile.key)}

    @app.delete("/api/agents/{key}")
    def delete_agent(key: str):
        if not registry.is_custom(key):
            raise HTTPException(
                status_code=400,
                detail="Only custom agents can be removed.",
            )
        registry.remove(key)
        rag_store.drop(key)
        return {"ok": True}

    # ---- chat (SSE stream) ------------------------------------------------

    @app.post("/api/chat")
    async def chat(request: Request):
        body = await request.json()
        raw = body.get("message", "")
        known_names = [a["name"] for a in all_agents_payload()]
        try:
            cmd = parse_command(raw, known_names)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

        try:
            team = build_team()
        except HTTPException as e:
            return JSONResponse({"error": e.detail}, status_code=e.status_code)

        return StreamingResponse(
            _run_command_stream(team, cmd),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- workspace --------------------------------------------------------

    @app.get("/api/workspace")
    def workspace_snapshot():
        return {
            "snapshot": workspace.snapshot(),
            "documents": workspace.list_documents(),
        }

    @app.post("/api/workspace/reset")
    def workspace_reset():
        workspace.reset()
        return {"ok": True}

    # ---- chat file upload → workspace document ---------------------------

    @app.post("/api/upload")
    async def upload_to_chat(file: UploadFile = File(...)):
        data = await file.read()
        try:
            kind, text = extract_text_from_upload(file.filename or "upload", data)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))

        name = file.filename or "uploaded-file"
        doc = workspace.save_document(
            name=name,
            author="User (upload)",
            content=text,
        )
        # Post a short notice in the chat so agents see the upload inline.
        preview = text[:400] + ("…" if len(text) > 400 else "")
        workspace.post_message(
            sender_key="user",
            sender_name="User",
            content=(
                f"[uploaded {kind.upper()}] **{name}** saved to documents/.\n\n"
                f"Preview:\n\n{preview}"
            ),
        )
        return {
            "name": doc.name,
            "kind": kind,
            "chars": len(text),
        }

    # ---- per-agent RAG knowledge bases ------------------------------------

    @app.get("/api/rag/{agent_key}")
    def list_rag(agent_key: str):
        if agent_key not in registry.all():
            raise HTTPException(status_code=404, detail=f"unknown agent: {agent_key}")
        kb = rag_store.kb(agent_key)
        return {"sources": kb.list_sources()}

    @app.post("/api/rag/{agent_key}")
    async def add_rag(agent_key: str, file: UploadFile = File(...)):
        if agent_key not in registry.all():
            raise HTTPException(status_code=404, detail=f"unknown agent: {agent_key}")
        data = await file.read()
        try:
            kind, text = extract_text_from_upload(file.filename or "source", data)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not text.strip():
            raise HTTPException(status_code=400, detail="no text could be extracted.")

        kb = rag_store.kb(agent_key)
        source = kb.add_source(
            name=file.filename or "source",
            kind=kind,
            text=text,
            added_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        return {
            "source": {
                "id": source.id,
                "name": source.name,
                "kind": source.kind,
                "added_at": source.added_at,
                "chunk_count": source.chunk_count,
            }
        }

    @app.delete("/api/rag/{agent_key}/{source_id}")
    def delete_rag(agent_key: str, source_id: str):
        if agent_key not in registry.all():
            raise HTTPException(status_code=404, detail=f"unknown agent: {agent_key}")
        kb = rag_store.kb(agent_key)
        if not kb.remove_source(source_id):
            raise HTTPException(status_code=404, detail="source not found")
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# SSE helper: bridges the Team's blocking stream callback into an async gen.
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _run_command_stream(team, cmd: ParsedCommand):
    """Generator that runs a Team command on a worker thread and yields SSE.

    The Team's `on_stream` callback is synchronous, so we push tokens into
    a thread-safe queue and drain the queue in the async generator.
    """
    q: "queue.Queue[tuple[str, dict] | None]" = queue.Queue()
    error: dict = {}

    def on_stream(agent_key: str, agent_name: str, chunk: str) -> None:
        q.put(("token", {"agent_key": agent_key, "agent_name": agent_name, "text": chunk}))

    def run() -> None:
        try:
            kind = cmd.kind
            content = cmd.content
            specialist = cmd.specialist
            rounds = cmd.rounds
            order = None

            # Auto-routing: ask the model who should answer.
            if kind == "auto":
                q.put(("speaker", {"label": "→ routing…"}))
                route = route_query(
                    client=team.client,
                    model=team.model,
                    query=content,
                    profiles=team._profiles,
                )
                kind = route.mode
                order = route.agents
                label = {
                    "ask": f"→ routed to {order[0]}",
                    "brief": f"→ routed to {', '.join(order)}",
                    "discuss": f"→ discussion among {', '.join(order)}",
                }.get(kind, "→ routing")
                if route.why:
                    label = f"{label}  ({route.why})"
                q.put(("speaker", {"label": label}))
                if kind == "ask":
                    specialist = team.get_profile(order[0]).name

            if kind == "ask":
                q.put((
                    "speaker",
                    {"agent_name": specialist, "label": f"→ asking {specialist}"},
                ))
                team.ask(specialist, content, on_stream=on_stream)
            elif kind == "brief":
                if order is None:
                    q.put(("speaker", {"label": "→ briefing the team"}))
                team.brief(content, on_stream=on_stream, order=order)
            elif kind == "discuss":
                if order is None:
                    q.put((
                        "speaker",
                        {"label": f"→ discussion ({rounds} round{'s' if rounds > 1 else ''})"},
                    ))
                team.discuss(content, rounds=rounds, on_stream=on_stream, order=order)
            else:
                error["message"] = f"unknown command kind: {kind}"
        except Exception as e:  # noqa: BLE001 — surface to the browser
            error["message"] = f"{type(e).__name__}: {e}"
        finally:
            q.put(None)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()

    def stream_iter():
        # Echo the parsed command so the UI can render a "system" notice.
        yield _sse(
            "start",
            {
                "kind": cmd.kind,
                "content": cmd.content,
                "specialist": cmd.specialist,
                "rounds": cmd.rounds,
            },
        )
        while True:
            item = q.get()
            if item is None:
                break
            event, data = item
            yield _sse(event, data)
        if error:
            yield _sse("error", error)
        yield _sse("done", {})

    return stream_iter()
