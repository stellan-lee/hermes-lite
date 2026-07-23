"""Persistent, group-scoped access grants for messaging gateways.

The first consumer is Telegram's ``/access`` command.  Runtime grants live
outside ``config.yaml`` so a group administrator can add or remove a user
without rewriting operator-owned configuration or restarting the gateway.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from marlow_constants import get_marlow_home
from utils import atomic_replace


GROUP_ACCESS_PATH = (
    get_marlow_home() / "platforms" / "telegram" / "group-access.json"
)
_SCHEMA_VERSION = 1


def _secure_write(path: Path, data: str) -> None:
    """Atomically write *data* with owner-only file permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class GroupAccessStore:
    """Manage durable user grants scoped to an exact platform group."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or GROUP_ACCESS_PATH
        self._lock = threading.RLock()

    @staticmethod
    def _normalize_id(value: Any) -> str:
        return str(value or "").strip()

    def _empty_data(self) -> dict[str, Any]:
        return {"version": _SCHEMA_VERSION, "groups": {}}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_data()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty_data()
        if not isinstance(loaded, dict) or not isinstance(loaded.get("groups"), dict):
            return self._empty_data()
        return loaded

    def _save(self, data: dict[str, Any]) -> None:
        data["version"] = _SCHEMA_VERSION
        _secure_write(
            self.path,
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
        )

    def is_granted(self, platform: str, chat_id: str, user_id: str) -> bool:
        """Return whether *user_id* has a runtime grant in this exact group."""
        platform_key = self._normalize_id(platform).lower()
        chat_key = self._normalize_id(chat_id)
        user_key = self._normalize_id(user_id)
        if not platform_key or not chat_key or not user_key:
            return False
        with self._lock:
            groups = self._load().get("groups", {})
            users = groups.get(f"{platform_key}:{chat_key}", {})
            return isinstance(users, dict) and user_key in users

    def grant(
        self,
        platform: str,
        chat_id: str,
        user_id: str,
        *,
        user_name: str = "",
        granted_by: str,
        granted_by_name: str = "",
    ) -> bool:
        """Grant access and return ``True`` when a new entry was created."""
        platform_key = self._normalize_id(platform).lower()
        chat_key = self._normalize_id(chat_id)
        user_key = self._normalize_id(user_id)
        grantor_key = self._normalize_id(granted_by)
        if not platform_key or not chat_key or not user_key or not grantor_key:
            raise ValueError("platform, chat_id, user_id, and granted_by are required")

        with self._lock:
            data = self._load()
            groups = data.setdefault("groups", {})
            group_key = f"{platform_key}:{chat_key}"
            users = groups.setdefault(group_key, {})
            if not isinstance(users, dict):
                users = {}
                groups[group_key] = users
            created = user_key not in users
            users[user_key] = {
                "user_name": str(user_name or "").strip(),
                "granted_by": grantor_key,
                "granted_by_name": str(granted_by_name or "").strip(),
                "granted_at": time.time(),
            }
            self._save(data)
            return created

    def revoke(self, platform: str, chat_id: str, user_id: str) -> bool:
        """Remove an exact group grant and return whether it existed."""
        platform_key = self._normalize_id(platform).lower()
        chat_key = self._normalize_id(chat_id)
        user_key = self._normalize_id(user_id)
        if not platform_key or not chat_key or not user_key:
            return False

        with self._lock:
            data = self._load()
            groups = data.get("groups", {})
            group_key = f"{platform_key}:{chat_key}"
            users = groups.get(group_key, {})
            if not isinstance(users, dict) or user_key not in users:
                return False
            del users[user_key]
            if not users:
                groups.pop(group_key, None)
            self._save(data)
            return True

    def list_grants(self, platform: str, chat_id: str) -> list[dict[str, Any]]:
        """List runtime grants for an exact group, ordered by grant time."""
        platform_key = self._normalize_id(platform).lower()
        chat_key = self._normalize_id(chat_id)
        if not platform_key or not chat_key:
            return []
        with self._lock:
            groups = self._load().get("groups", {})
            users = groups.get(f"{platform_key}:{chat_key}", {})
            if not isinstance(users, dict):
                return []
            result = []
            for user_id, raw_info in users.items():
                info = raw_info if isinstance(raw_info, dict) else {}
                result.append({"user_id": user_id, **info})

            def _sort_key(item: dict[str, Any]) -> tuple[float, str]:
                try:
                    granted_at = float(item.get("granted_at", 0) or 0)
                except (TypeError, ValueError):
                    granted_at = 0
                return granted_at, str(item.get("user_id", ""))

            return sorted(
                result,
                key=_sort_key,
            )


__all__ = ["GROUP_ACCESS_PATH", "GroupAccessStore"]
