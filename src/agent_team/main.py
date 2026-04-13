"""CLI entry point for the agent team.

Subcommands:
    team brief "<idea>"                 — every specialist gives a first take
    team discuss "<topic>" [--rounds N] — round-robin discussion
    team ask <specialist> "<question>"  — single specialist
    team repl                           — interactive REPL
    team serve [--host H --port P]      — launch the web UI
    team list                           — show the team roster
    team workspace                      — print the workspace snapshot
    team reset                          — wipe the workspace
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_team.profiles import AGENT_PROFILES
from agent_team.workspace import Workspace


# Resolve the workspace directory relative to the project root, regardless
# of where the user invoked the CLI from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKSPACE = PROJECT_ROOT / "workspace"


# ---------------------------------------------------------------------------
# Output helpers — minimal ANSI to keep the team's voices distinct.
# ---------------------------------------------------------------------------

_AGENT_COLORS = {
    "atlas":    "\033[36m",   # cyan
    "iris":     "\033[35m",   # magenta
    "vitruvio": "\033[33m",   # yellow
    "nova":     "\033[32m",   # green
    "solon":    "\033[34m",   # blue
}
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _color_for(agent_key: str) -> str:
    return _AGENT_COLORS.get(agent_key, "")


_current_speaker: dict[str, str | None] = {"key": None}


def _stream_print(agent_key: str, agent_name: str, chunk: str) -> None:
    """Stream callback used by the CLI: print headers when the speaker changes."""
    if _current_speaker["key"] != agent_key:
        if _current_speaker["key"] is not None:
            print("\n")
        color = _color_for(agent_key)
        print(f"{color}{_BOLD}── {agent_name} ──{_RESET}\n", flush=True)
        _current_speaker["key"] = agent_key
    print(chunk, end="", flush=True)


def _end_stream() -> None:
    if _current_speaker["key"] is not None:
        print("\n")
        _current_speaker["key"] = None


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_list(_: argparse.Namespace, __: Team) -> None:
    print(f"\n{_BOLD}The team:{_RESET}\n")
    for profile in AGENT_PROFILES.values():
        color = _color_for(profile.key)
        print(f"  {color}{_BOLD}{profile.name:<10}{_RESET} {profile.role}")
    print()


def cmd_brief(args: argparse.Namespace, team: Team) -> None:
    print(f"\n{_BOLD}New project brief:{_RESET} {args.idea}\n")
    print("Each specialist will weigh in. They read each other's posts as they go.\n")
    team.brief(args.idea, on_stream=_stream_print)
    _end_stream()


def cmd_discuss(args: argparse.Namespace, team: Team) -> None:
    print(f"\n{_BOLD}Topic:{_RESET} {args.topic}\n")
    print(f"Discussion will run for {args.rounds} round(s).\n")
    team.discuss(args.topic, rounds=args.rounds, on_stream=_stream_print)
    _end_stream()


def cmd_ask(args: argparse.Namespace, team: Team) -> None:
    try:
        team.ask(args.specialist, args.question, on_stream=_stream_print)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    _end_stream()


def cmd_repl(_: argparse.Namespace, team: Team) -> None:
    print(f"\n{_BOLD}Agent team REPL{_RESET}")
    print("Commands inside the REPL:")
    print("  ask <specialist> <question>     — single specialist")
    print("  brief <idea>                    — open a new project")
    print("  discuss <topic>                 — round-robin (2 rounds)")
    print("  workspace                       — print workspace snapshot")
    print("  list                            — show the roster")
    print("  reset                           — wipe the workspace")
    print("  quit / exit                     — leave the REPL\n")

    while True:
        try:
            line = input(f"{_BOLD}team>{_RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("quit", "exit"):
            return

        parts = line.split(maxsplit=1)
        command = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        try:
            if command == "ask":
                bits = rest.split(maxsplit=1)
                if len(bits) < 2:
                    print("usage: ask <specialist> <question>")
                    continue
                team.ask(bits[0], bits[1], on_stream=_stream_print)
                _end_stream()
            elif command == "brief":
                if not rest:
                    print("usage: brief <idea>")
                    continue
                team.brief(rest, on_stream=_stream_print)
                _end_stream()
            elif command == "discuss":
                if not rest:
                    print("usage: discuss <topic>")
                    continue
                team.discuss(rest, rounds=2, on_stream=_stream_print)
                _end_stream()
            elif command == "workspace":
                print()
                print(team.workspace.snapshot())
                print()
            elif command == "list":
                cmd_list(argparse.Namespace(), team)
            elif command == "reset":
                team.workspace.reset()
                print("Workspace cleared.\n")
            else:
                print(f"unknown command: {command}")
        except KeyError as e:
            print(f"Error: {e}")
        except KeyboardInterrupt:
            _end_stream()
            print("(interrupted)")


def cmd_workspace(_: argparse.Namespace, team: Team) -> None:
    print()
    print(team.workspace.snapshot())
    print()


def cmd_reset(_: argparse.Namespace, team: Team) -> None:
    team.workspace.reset()
    print("Workspace cleared.")


def cmd_serve(args: argparse.Namespace) -> None:
    """Launch the web UI. Does not need a Team — the app builds its own per request."""
    try:
        import uvicorn
    except ImportError as e:
        print(
            "The web UI needs `fastapi` and `uvicorn`. Install them with:\n"
            "    pip install -e .",
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    from agent_team.web.app import create_app

    workspace_root = args.workspace.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    app = create_app(workspace_root)

    print(f"\n{_BOLD}Agent Team UI{_RESET}")
    print(f"  workspace: {workspace_root}")
    print(f"  open:      http://{args.host}:{args.port}\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="team",
        description="Run a five-specialist AI team that shares a workspace.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help=f"Workspace directory (default: {DEFAULT_WORKSPACE})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_brief = sub.add_parser("brief", help="Start a new project — every specialist weighs in.")
    p_brief.add_argument("idea", help="The project brief, in quotes.")
    p_brief.set_defaults(func=cmd_brief)

    p_discuss = sub.add_parser("discuss", help="Round-robin discussion across the team.")
    p_discuss.add_argument("topic", help="The discussion topic, in quotes.")
    p_discuss.add_argument("--rounds", type=int, default=2, help="Number of rounds (default 2).")
    p_discuss.set_defaults(func=cmd_discuss)

    p_ask = sub.add_parser("ask", help="Ask a single specialist directly.")
    p_ask.add_argument(
        "specialist",
        help="One of: " + ", ".join(AGENT_PROFILES.keys()),
    )
    p_ask.add_argument("question", help="The question, in quotes.")
    p_ask.set_defaults(func=cmd_ask)

    p_repl = sub.add_parser("repl", help="Interactive REPL.")
    p_repl.set_defaults(func=cmd_repl)

    p_serve = sub.add_parser("serve", help="Launch the web UI.")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8000, help="Bind port (default 8000)")
    p_serve.set_defaults(func=cmd_serve)

    p_list = sub.add_parser("list", help="Show the team roster.")
    p_list.set_defaults(func=cmd_list)

    p_ws = sub.add_parser("workspace", help="Print the current workspace snapshot.")
    p_ws.set_defaults(func=cmd_workspace)

    p_reset = sub.add_parser("reset", help="Wipe the workspace.")
    p_reset.set_defaults(func=cmd_reset)

    return parser


def main() -> None:
    # Lazy imports so `python -m agent_team.main --help` and the parser tests
    # work in environments that don't yet have openai / python-dotenv
    # installed. The full CLI requires both, installed via `pip install -e .`.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    parser = build_parser()
    args = parser.parse_args()

    # `serve` launches the web UI and does not need a pre-built Team — the
    # app instantiates one per request using the saved settings.
    if args.command == "serve":
        args.func(args)
        return

    from agent_team.team import Team

    workspace = Workspace(args.workspace)
    team = Team(workspace=workspace)

    args.func(args, team)


if __name__ == "__main__":
    main()
