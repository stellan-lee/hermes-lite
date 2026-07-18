"""Tests for retained Docker config propagation in file tools."""

import threading
from unittest.mock import MagicMock, patch

import tools.file_tools as file_tools


def _make_env_config(**overrides):
    config = {
        "env_type": "docker",
        "docker_image": "test-image:latest",
        "cwd": "/workspace",
        "host_cwd": None,
        "timeout": 180,
        "container_cpu": 2,
        "container_memory": 4096,
        "container_disk": 20480,
        "container_persistent": False,
        "docker_volumes": [],
        "docker_mount_cwd_to_workspace": True,
        "docker_forward_env": ["MY_SECRET", "API_KEY"],
    }
    config.update(overrides)
    return config


def _capture_container_config(env_config, task_id):
    captured = {}

    def fake_create_env(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    with (
        patch("tools.terminal_tool._get_env_config", return_value=env_config),
        patch("tools.terminal_tool._task_env_overrides", {}),
        patch("tools.terminal_tool._active_environments", {}),
        patch("tools.terminal_tool._creation_locks", {}),
        patch("tools.terminal_tool._creation_locks_lock", threading.Lock()),
        patch("tools.terminal_tool._create_environment", side_effect=fake_create_env),
        patch("tools.terminal_tool._start_cleanup_thread"),
        patch("tools.file_tools._file_ops_cache", {}),
        patch("tools.file_tools._file_ops_lock", threading.Lock()),
    ):
        file_tools._get_file_ops(task_id)
    return captured.get("container_config", {})


def test_docker_config_is_forwarded():
    config = _capture_container_config(
        _make_env_config(
            docker_mount_cwd_to_workspace=True,
            docker_forward_env=["MY_SECRET"],
        ),
        "docker-config",
    )
    assert config["docker_mount_cwd_to_workspace"] is True
    assert config["docker_forward_env"] == ["MY_SECRET"]


def test_docker_config_defaults_are_lightweight():
    raw = _make_env_config()
    raw.pop("docker_mount_cwd_to_workspace")
    raw.pop("docker_forward_env")
    config = _capture_container_config(raw, "docker-defaults")
    assert config["docker_mount_cwd_to_workspace"] is False
    assert config["docker_forward_env"] == []
