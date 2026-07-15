"""Focused regression tests for the shared interprocess file lock."""

import subprocess
import sys
import threading
import time
from pathlib import Path

from utils import interprocess_file_lock


def test_interprocess_file_lock_is_same_thread_reentrant(tmp_path):
    lock_path = tmp_path / "state.lock"
    completed = threading.Event()
    errors = []

    def nested_acquire():
        try:
            with interprocess_file_lock(lock_path):
                with interprocess_file_lock(lock_path):
                    completed.set()
        except BaseException as exc:  # pragma: no cover - assertion aid
            errors.append(exc)

    thread = threading.Thread(target=nested_acquire, daemon=True)
    thread.start()
    thread.join(timeout=2)

    assert not thread.is_alive(), "nested acquisition self-deadlocked"
    assert completed.is_set()
    assert errors == []


def test_interprocess_file_lock_excludes_peer_threads(tmp_path):
    lock_path = tmp_path / "state.lock"
    outer_entered = threading.Event()
    release_outer = threading.Event()
    inner_entered = threading.Event()

    def owner():
        with interprocess_file_lock(lock_path):
            outer_entered.set()
            release_outer.wait(timeout=2)

    def waiter():
        outer_entered.wait(timeout=2)
        with interprocess_file_lock(lock_path):
            inner_entered.set()

    first = threading.Thread(target=owner, daemon=True)
    second = threading.Thread(target=waiter, daemon=True)
    first.start()
    second.start()
    assert outer_entered.wait(timeout=2)
    assert not inner_entered.wait(timeout=0.1)
    release_outer.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert inner_entered.is_set()


def test_interprocess_file_lock_retains_cross_process_exclusion(tmp_path):
    lock_path = tmp_path / "state.lock"
    ready = tmp_path / "child-ready"
    marker = tmp_path / "child-entered"
    script = (
        "from pathlib import Path\n"
        "from utils import interprocess_file_lock\n"
        f"Path({str(ready)!r}).write_text('ready', encoding='utf-8')\n"
        f"with interprocess_file_lock({str(lock_path)!r}):\n"
        f"    Path({str(marker)!r}).write_text('entered', encoding='utf-8')\n"
    )

    with interprocess_file_lock(lock_path):
        child = subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 2
        while (
            not ready.exists()
            and child.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert ready.exists(), child.communicate(timeout=1)
        assert child.poll() is None
        assert not marker.exists()

    stdout, stderr = child.communicate(timeout=5)
    assert child.returncode == 0, (stdout, stderr)
    assert marker.read_text(encoding="utf-8") == "entered"
