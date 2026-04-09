# AGENTs — A Team of Five Specialist AI Collaborators

Five AI specialists that share a workspace and work together on your ideas and
projects. Each one is primed with the canonical literature, frameworks, and
working habits of its field.

| Agent     | Role               | Grounded in                                                                 |
| --------- | ------------------ | --------------------------------------------------------------------------- |
| Atlas     | Financial Expert   | Damodaran, Graham, Buffett/Munger, CFA curriculum, Kahneman, IFRS/GAAP      |
| Iris      | Creative Director  | Ogilvy, Bernbach, Paula Scher, Dieter Rams, Neumeier, Kapferer, McKee       |
| Vitruvio  | Architect          | Vitruvius, Christopher Alexander, Le Corbusier, Zumthor, LEED/Passivhaus    |
| Nova      | Project Manager    | PMBOK, PRINCE2, Scrum Guide, Lean, Goldratt, OKRs, Accelerate               |
| Solon     | Law Expert         | IRAC, Restatements, UCC, Delaware GCL, GDPR/CCPA, Model Rules               |

> Solon is an informational research agent. Nothing it produces is legal
> advice. Every legal deliverable ships with that disclaimer baked in.

## Shared workspace — the "cloud space"

Every agent reads from and writes to `workspace/`:

```
workspace/
├── messages/     # inter-agent chat, timestamped and attributed
├── documents/    # shared artifacts — briefs, memos, models, moodboards
└── decisions/    # decision log with rationale and dissent
```

This is how the team "speaks" with itself. Before an agent answers, it sees
the recent messages, the document list, and the decision log. After it answers,
its reply is posted to `messages/` so the others can read it next turn. The
workspace is deliberately file-based so you can swap it for S3, Redis, or a
database later without touching the agents.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env         # optional: put ANTHROPIC_API_KEY here, or set it in the UI
```

## Web UI

```bash
team serve                   # http://127.0.0.1:8000
team serve --host 0.0.0.0 --port 9000
```

The UI has four panels:

- **Chat** — a group chat with the whole team. Plain text → `/brief` (team
  weighs in). `@Atlas what's the unit economics?` → single specialist.
  `/ask Iris ...`, `/brief ...`, `/discuss <topic> --rounds 2` also work.
  Attach or drag-and-drop PDFs, markdown, and text files to share them with
  the team as workspace documents.
- **Knowledge** — a private RAG library per specialist. Upload PDFs or text;
  relevant excerpts are retrieved (BM25) and injected into that agent's
  system prompt on every reply.
- **Team** — view the roster and add your own specialists with a name, role,
  and system prompt. The collaboration preamble is wrapped in automatically.
- **Settings** — paste your Anthropic API key and pick a model. Stored in
  `workspace/config.json` with 0600 permissions. Environment variables
  (`ANTHROPIC_API_KEY`, `AGENT_TEAM_MODEL`) take precedence at startup.

## CLI

```bash
# Kick off a new project — every specialist weighs in from their angle
team brief "A zero-waste urban coffee shop chain in Milan"

# Open-ended round-robin discussion (default: 2 rounds)
team discuss "Should we bootstrap or raise a seed round?" --rounds 3

# Single specialist
team ask atlas "Sketch a 3-year P&L for a 50-seat cafe in Milan"
team ask solon "What are the main risks in a standard Italian commercial lease?"

# Interactive REPL — pick who speaks, read the workspace live
team repl

# Wipe the workspace (keeps .gitkeep files)
team reset
```

## Extending the team

- **Add a specialist** — use the **Team** tab in the web UI, or add a new
  entry to `AGENT_PROFILES` in `src/agent_team/profiles.py` to ship one with
  the package. The orchestrator, CLI, and UI will pick it up automatically.
- **Swap the workspace backend** — re-implement `Workspace` in
  `src/agent_team/workspace.py`. The rest of the team depends only on its
  public methods (`post_message`, `read_messages`, `save_document`, …).
- **Swap the RAG backend** — replace `AgentKnowledgeBase` in
  `src/agent_team/web/rag.py` with a vector store (Chroma, sqlite-vss,
  pgvector). The rest of the system only calls `context_for(profile, query)`.
- **Add tools** — specialists currently work from context alone. To give them
  real tools (web search, calculators, DB lookups), wire the Anthropic SDK's
  tool use into `Team._run_specialist` in `src/agent_team/team.py`.
