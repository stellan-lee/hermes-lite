from __future__ import annotations

import logging

from hermes_logging import setup_logging


def test_custom_log_path_is_private_and_does_not_create_home(tmp_path, isolated_hermes_home):
    path = tmp_path / "logs" / "agent.log"
    logger = setup_logging("INFO", file_enabled=True, log_path=path)
    logger.info("hello")
    for handler in logger.handlers:
        handler.flush()
    assert path.read_text(encoding="utf-8").endswith("INFO hermes: hello\n")
    assert path.stat().st_mode & 0o777 == 0o600
    assert not isolated_hermes_home.exists()

    # Leave no marked file descriptor behind for another test or embedder.
    setup_logging("WARNING", file_enabled=False)
    assert any(type(handler) is logging.StreamHandler for handler in logger.handlers)
