"""Small, idempotent logging setup for Hermes Lite."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from hermes_constants import get_hermes_home, get_log_path

_HANDLER_MARKER = "_hermes_lite_handler"


def setup_logging(
    level: str = "WARNING",
    *,
    file_enabled: bool = True,
    log_path: Path | None = None,
) -> logging.Logger:
    """Configure the ``hermes`` logger once and return it."""

    logger = logging.getLogger("hermes")
    resolved_level = getattr(logging, level.upper(), logging.WARNING)
    logger.setLevel(resolved_level)
    logger.propagate = False

    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    handler: logging.Handler
    if file_enabled:
        if log_path is None:
            get_hermes_home(create=True)
            resolved_path = get_log_path()
        else:
            resolved_path = log_path.expanduser().resolve()
            resolved_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        handler = logging.FileHandler(resolved_path, encoding="utf-8")
        os.chmod(resolved_path, 0o600)
    else:
        handler = logging.StreamHandler()

    setattr(handler, _HANDLER_MARKER, True)
    handler.setLevel(resolved_level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    return logger
