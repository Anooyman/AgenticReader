"""The cross-platform locking primitive, and the rule that keeps it the only one.

Vendored from upstream LLM-Memory (`llm_memoryd/common/filelock.py`), so the
tests are close relatives of the ones that live there — deliberately, not by
copy-paste habit. What is being protected against is a specific regression:
someone reaches for `fcntl.flock` again because it is one line, and the next
Windows run loses mutual exclusion without a single error being raised.
"""
import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.core import filelock  # noqa: E402

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"


def test_only_filelock_talks_to_the_kernel_locker():
    offenders = []
    for path in SRC_ROOT.rglob("*.py"):
        if path.name == "filelock.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "fcntl" not in text and "msvcrt" not in text:
            continue
        tree = ast.parse(text)
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        if "fcntl" in names or "msvcrt" in names or "fcntl." in text:
            offenders.append(str(path.relative_to(SRC_ROOT)))
    assert not offenders, (
        "platform-specific locking is being reached from outside src/core/filelock.py: "
        f"{sorted(offenders)}. The old registry.py pattern (try: import fcntl / except: "
        "threading.Lock) is exactly what these tests exist to prevent — it does not fail, "
        "it silently downgrades to in-process-only exclusion."
    )


def test_acquire_release_roundtrip(tmp_path):
    target = tmp_path / "coordinator.lock"
    fd = os.open(str(target), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        filelock.acquire(fd)
        filelock.release(fd)
        filelock.acquire(fd, non_blocking=True)
        filelock.release(fd)
    finally:
        os.close(fd)


@pytest.mark.skipif(filelock.IS_WINDOWS, reason=(
    "Windows signals a held lock after a ~10s retry window, not immediately — "
    "asserting immediate refusal there would be a claim about a platform that "
    "does not behave that way, not coverage."
))
def test_held_lock_refuses_a_second_non_blocking_writer(tmp_path):
    target = tmp_path / "holder.lock"
    first = os.open(str(target), os.O_RDWR | os.O_CREAT, 0o644)
    second = os.open(str(target), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        filelock.acquire(first)
        with pytest.raises(BlockingIOError):
            filelock.acquire(second, non_blocking=True)
    finally:
        os.close(first)
        os.close(second)


def test_a_file_object_works_as_well_as_an_fd(tmp_path):
    """`open()` handles and raw fds are both accepted.

    `flock` tolerates a file object; `msvcrt.locking` wants an fd. That
    asymmetry is the sort of thing that produces code working on one platform
    and raising TypeError on the other.
    """
    target = tmp_path / "handle.lock"
    target.write_text("", encoding="utf-8")
    with open(target, "a+b") as fh:
        filelock.acquire(fh)
        filelock.release(fh)
        filelock.acquire(fh, non_blocking=True)
        filelock.release(fh)


def test_the_lock_is_held_while_the_file_is_open(tmp_path):
    """The idiom the codebase already uses, checked against a real filesystem.

    Closing must release: if it did not, a crashed-out `with` block would
    permanently wedge the queue/registry paths it guards.
    """
    target = tmp_path / "scoped.lock"
    first = os.open(str(target), os.O_RDWR | os.O_CREAT, 0o644)
    filelock.acquire(first)
    os.close(first)                      # implicit release
    second = os.open(str(target), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        filelock.acquire(second, non_blocking=True)   # must not raise
    finally:
        filelock.release(second)
        os.close(second)
