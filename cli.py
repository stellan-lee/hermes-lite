"""Plain terminal interface for Hermes Lite."""

from __future__ import annotations

import argparse
import copy
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml

from hermes_cli import __version__
from hermes_cli.config import (
    ConfigError,
    load_config,
    load_env_file,
    write_default_config,
)
from hermes_logging import setup_logging
from hermes_state import SessionDB
from run_agent import AgentError, AIAgent

InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]


class HermesCLI:
    """Interactive and one-shot orchestration around ``AIAgent``."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        session_id: str | None = None,
        resume_latest: bool = False,
        assume_yes: bool = False,
        input_fn: InputFunction = input,
        output_fn: OutputFunction = print,
        agent_factory: Callable[..., AIAgent] = AIAgent,
        session_db: SessionDB | None = None,
    ) -> None:
        self.config = copy.deepcopy(config)
        self.input = input_fn
        self.output = output_fn
        self.assume_yes = assume_yes
        self._agent_factory = agent_factory
        self._session_db = session_db if self.config["sessions"]["enabled"] else None
        self._owns_session_db = False
        self.agent = self._build_agent()

        try:
            if self.config["sessions"]["enabled"] and self._session_db is None:
                self._session_db = SessionDB()
                self._owns_session_db = True
            self.session_id = self._select_session(session_id, resume_latest)
        except Exception:
            if self._owns_session_db and self._session_db is not None:
                self._session_db.close()
            raise

    def _select_session(self, requested: str | None, resume_latest: bool) -> str | None:
        if self._session_db is None:
            return None
        if requested:
            if not self._session_db.has_session(requested):
                raise ConfigError(f"unknown session: {requested}")
            return requested
        if resume_latest or self.config["sessions"]["resume_latest"]:
            latest = self._session_db.latest_session_id()
            if latest:
                return latest
        return None

    def _build_agent(self) -> AIAgent:
        inference = self.config["inference"]
        agent = self.config["agent"]
        tools = self.config["tools"]
        terminal = tools["terminal"]
        model = inference["model"].strip()
        if not model:
            raise ConfigError(
                "no model configured; run `hermes init --model MODEL` or set HERMES_MODEL"
            )
        api_key_name = inference["api_key_env"]
        api_key = os.environ.get(api_key_name)
        if not api_key:
            raise ConfigError(f"missing API key environment variable: {api_key_name}")
        return self._agent_factory(
            model=model,
            api_key=api_key,
            base_url=inference["base_url"] or None,
            system_prompt=agent["system_prompt"],
            max_iterations=agent["max_iterations"],
            temperature=inference["temperature"],
            enabled_tools=tools["enabled"],
            workspace=tools["workspace"],
            terminal_enabled=terminal["enabled"],
            terminal_confirm=terminal["confirm"] and not self.assume_yes,
            terminal_timeout_seconds=terminal["timeout_seconds"],
            approval_callback=self._approve_terminal,
        )

    def _approve_terminal(self, command: str) -> bool:
        if self.assume_yes:
            return True
        answer = self.input(f"Allow terminal command?\n  {command}\n[y/N] ")
        return answer.strip().lower() in {"y", "yes"}

    def _history(self) -> list[dict[str, str]]:
        if self._session_db is None or self.session_id is None:
            return []
        return self._session_db.load_messages(self.session_id)

    def ask(self, prompt: str) -> str:
        history = self._history()
        result = self.agent.run_conversation(prompt, conversation_history=history)
        response = result["final_response"]
        if self._session_db is not None:
            if self.session_id is None:
                self.session_id = self._session_db.create_session(prompt.strip()[:80])
            if not history:
                self._session_db.set_title(self.session_id, prompt.strip()[:80])
            self._session_db.add_turn(self.session_id, prompt, response)
        return response

    def new_session(self) -> str | None:
        if self._session_db is None:
            return None
        self.session_id = self._session_db.create_session()
        return self.session_id

    def show_sessions(self) -> None:
        if self._session_db is None:
            self.output("Session persistence is disabled.")
            return
        for session in self._session_db.list_sessions():
            marker = "*" if session.id == self.session_id else " "
            self.output(
                f"{marker} {session.id}  {session.updated_at}  "
                f"{session.message_count:>3} messages  {session.title}"
            )

    def interactive(self) -> int:
        self.output("Hermes Lite — /help for commands, /quit to exit")
        while True:
            try:
                prompt = self.input("hermes> ").strip()
            except EOFError:
                self.output("")
                return 0
            except KeyboardInterrupt:
                self.output("\nInterrupted. Use /quit to exit.")
                continue
            if not prompt:
                continue
            if prompt in {"/quit", "/exit"}:
                return 0
            if prompt == "/help":
                self.output("/new  start a fresh session\n/sessions  list sessions\n/quit  exit")
                continue
            if prompt == "/new":
                identifier = self.new_session()
                message = f"New session: {identifier}" if identifier else "Sessions are disabled."
                self.output(message)
                continue
            if prompt == "/sessions":
                self.show_sessions()
                continue
            try:
                self.output(self.ask(prompt))
            except AgentError as exc:
                self.output(f"Error: {exc}")

    def close(self) -> None:
        if self._owns_session_db and self._session_db is not None:
            self._session_db.close()

    def __enter__(self) -> HermesCLI:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes",
        description="A small local coding agent for OpenAI-compatible models.",
    )
    parser.add_argument("--config", type=Path, help="Path to config.yaml")
    parser.add_argument("--model", help="Override inference.model")
    parser.add_argument("--base-url", help="Override inference.base_url")
    parser.add_argument("--workspace", type=Path, help="Override the tool workspace")
    parser.add_argument("--no-tools", action="store_true", help="Disable all model tools")
    parser.add_argument("--no-terminal", action="store_true", help="Disable terminal execution")
    parser.add_argument("--no-sessions", action="store_true", help="Disable session persistence")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Approve terminal commands without asking",
    )

    commands = parser.add_subparsers(dest="command")
    chat = commands.add_parser("chat", help="Start the interactive CLI (default)")
    chat.add_argument("--session", help="Resume a session by ID")
    chat.add_argument("--resume", action="store_true", help="Resume the latest session")

    ask = commands.add_parser("ask", help="Run one prompt and exit")
    ask.add_argument("prompt", nargs="+", help="Prompt text")
    ask.add_argument("--session", help="Continue a session by ID")
    ask.add_argument("--resume", action="store_true", help="Continue the latest session")

    init = commands.add_parser("init", help="Create the minimal config file")
    init.add_argument("--force", action="store_true", help="Replace an existing config")
    init.add_argument("--model", dest="init_model", help="Set inference.model")
    init.add_argument("--base-url", dest="init_base_url", help="Set inference.base_url")

    commands.add_parser("config", help="Print the effective non-secret config")

    sessions = commands.add_parser("sessions", help="List or delete local sessions")
    sessions_commands = sessions.add_subparsers(dest="sessions_command")
    sessions_commands.add_parser("list", help="List sessions (default)")
    delete = sessions_commands.add_parser("delete", help="Delete one session")
    delete.add_argument("session_id")

    commands.add_parser("version", help="Print the version")
    return parser


def _apply_cli_overrides(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    if args.model:
        config["inference"]["model"] = args.model
    if args.base_url:
        config["inference"]["base_url"] = args.base_url
    if args.workspace:
        config["tools"]["workspace"] = str(args.workspace.expanduser().resolve())
    if args.no_tools:
        config["tools"]["enabled"] = []
    if args.no_terminal:
        config["tools"]["terminal"]["enabled"] = False
    if args.no_sessions:
        config["sessions"]["enabled"] = False
    return config


def _print_warning(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "chat"
    if command == "version":
        print(__version__)
        return 0
    load_env_file()

    try:
        if command == "init":
            path = write_default_config(
                args.config,
                model=args.init_model or args.model or "",
                base_url=args.init_base_url or args.base_url or "",
                force=args.force,
            )
            print(f"Wrote {path}")
            return 0

        config = _apply_cli_overrides(load_config(args.config, warn=_print_warning), args)
        if command == "config":
            print(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), end="")
            return 0
        if command == "sessions":
            if not config["sessions"]["enabled"]:
                raise ConfigError("session persistence is disabled")
            with SessionDB() as session_db:
                if args.sessions_command == "delete":
                    deleted = session_db.delete_session(args.session_id)
                    print("Deleted." if deleted else "Session not found.")
                    return 0 if deleted else 1
                for session in session_db.list_sessions():
                    print(
                        f"{session.id}  {session.updated_at}  "
                        f"{session.message_count:>3} messages  {session.title}"
                    )
            return 0

        with HermesCLI(
            config,
            session_id=getattr(args, "session", None),
            resume_latest=getattr(args, "resume", False),
            assume_yes=args.yes,
        ) as cli:
            setup_logging(config["logging"]["level"], file_enabled=config["logging"]["file"])
            if command == "ask":
                print(cli.ask(" ".join(args.prompt)))
                return 0
            return cli.interactive()
    except (ConfigError, AgentError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
