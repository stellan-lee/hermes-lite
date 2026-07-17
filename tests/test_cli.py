from __future__ import annotations

import copy

from cli import HermesCLI, build_parser, main
from hermes_cli.config import DEFAULT_CONFIG, load_config
from hermes_state import SessionDB


class FakeAgent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []

    def run_conversation(self, prompt, conversation_history=None):
        self.calls.append((prompt, list(conversation_history or [])))
        return {"final_response": f"reply: {prompt}"}


def configured(tmp_path, monkeypatch):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["inference"]["model"] = "model"
    config["tools"]["workspace"] = str(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    return config


def test_parser_defaults_to_chat():
    assert build_parser().parse_args([]).command is None
    parsed = build_parser().parse_args(["ask", "hello", "world"])
    assert parsed.command == "ask"
    assert parsed.prompt == ["hello", "world"]


def test_cli_passes_every_runtime_config_field_and_persists(tmp_path, monkeypatch):
    config = configured(tmp_path, monkeypatch)
    config["inference"].update(
        {"base_url": "https://host/v1", "temperature": 0.7, "api_key_env": "CUSTOM_KEY"}
    )
    config["agent"].update({"max_iterations": 4, "system_prompt": "custom"})
    workspace = tmp_path / "work"
    workspace.mkdir()
    config["tools"].update({"enabled": ["read_file"], "workspace": str(workspace)})
    config["tools"]["terminal"].update({"enabled": False, "confirm": False, "timeout_seconds": 7})
    monkeypatch.setenv("CUSTOM_KEY", "custom-key")
    fake_agents = []

    def factory(**kwargs):
        agent = FakeAgent(**kwargs)
        fake_agents.append(agent)
        return agent

    with (
        SessionDB(tmp_path / "sessions.db") as database,
        HermesCLI(config, agent_factory=factory, session_db=database) as cli,
    ):
        assert database.list_sessions() == []
        assert cli.ask("hello") == "reply: hello"
        assert cli.ask("again") == "reply: again"
        messages = database.load_messages(cli.session_id)
        assert messages[-1] == {"role": "assistant", "content": "reply: again"}
        assert fake_agents[0].calls[1][1] == messages[:2]
        assert database.list_sessions()[0].title == "hello"

    kwargs = fake_agents[0].kwargs
    assert kwargs == {
        "model": "model",
        "api_key": "custom-key",
        "base_url": "https://host/v1",
        "system_prompt": "custom",
        "max_iterations": 4,
        "temperature": 0.7,
        "enabled_tools": ["read_file"],
        "workspace": str(tmp_path / "work"),
        "terminal_enabled": False,
        "terminal_confirm": False,
        "terminal_timeout_seconds": 7,
        "approval_callback": cli._approve_terminal,
    }


def test_terminal_approval_is_explicit(tmp_path, monkeypatch):
    config = configured(tmp_path, monkeypatch)
    answers = iter(["no", "yes"])
    with SessionDB(tmp_path / "sessions.db") as database:
        cli = HermesCLI(
            config,
            input_fn=lambda _prompt: next(answers),
            agent_factory=FakeAgent,
            session_db=database,
        )
        assert cli._approve_terminal("command") is False
        assert cli._approve_terminal("command") is True


def test_init_config_and_version_do_not_require_api_key(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    assert main(["--config", str(config_path), "init", "--model", "m"]) == 0
    assert load_config(config_path)["inference"]["model"] == "m"
    assert main(["version"]) == 0
    assert "0.15.1" in capsys.readouterr().out


def test_missing_model_is_a_clear_cli_error(tmp_path, isolated_hermes_home, capsys):
    assert main(["--config", str(tmp_path / "missing.yaml"), "chat"]) == 2
    assert "no model configured" in capsys.readouterr().err
    assert not isolated_hermes_home.exists()


def test_config_command_does_not_create_runtime_state(tmp_path, isolated_hermes_home, capsys):
    assert main(["--config", str(tmp_path / "missing.yaml"), "config"]) == 0
    assert "inference:" in capsys.readouterr().out
    assert not isolated_hermes_home.exists()


def test_disabled_sessions_ignore_an_injected_database(tmp_path, monkeypatch):
    config = configured(tmp_path, monkeypatch)
    config["sessions"]["enabled"] = False
    with (
        SessionDB(tmp_path / "sessions.db") as database,
        HermesCLI(config, agent_factory=FakeAgent, session_db=database) as cli,
    ):
        assert cli.ask("hello") == "reply: hello"
        assert cli.session_id is None
        assert database.list_sessions() == []
