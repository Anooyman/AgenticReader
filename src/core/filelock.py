"""Advisory exclusive locking that works on POSIX and Windows.

Vendored from `llm_memoryd/common/filelock.py` (upstream LLM-Memory). It is a
single stdlib-only file on purpose: nothing here imports lancedb, openai, or any
of the upstream package's surface, so this module can be used for a store that is
deliberately NOT upstream's (which is the case here — the PDF/vector corpus stays
its own store). Provenance is recorded rather than hidden so a future update can
be diffed against the original instead of guessed at.

Why this file exists at all: three places in this codebase called
`fcntl.flock` directly, and one of them (`document_management/registry.py`)
caught ImportError on Windows and fell back to a `threading.Lock`. That fallback
is the dangerous shape — it does not fail, it silently downgrades from
cross-process exclusion to in-process exclusion, so two processes both believe
they hold the lock and their writes overwrite each other forever.

Both differences from the POSIX original are stated rather than smoothed over:

* POSIX `flock()` is an advisory whole-file lock held by the open file
  description; it does not stop a process that chose to ignore it.
* Windows `msvcrt.locking()` locks one byte at offset zero (a byte-range lock),
  and the blocking form retries for roughly ten seconds before raising instead of
  waiting forever. Every critical section in this repo is a read-modify-write of
  a small JSON file or a LanceDB append, so ten seconds is a generous ceiling —
  and the two properties callers rely on hold either way: a blocked writer
  eventually proceeds, a non-blocking writer is refused immediately.

Callers should not assume the lock is mandatory. It is the coordination point,
not a guarantee against a process that declined to coordinate.
"""
from __future__ import annotations

import os

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:  # pragma: no cover - exercised only on Windows hosts
    import msvcrt

    def _lock(fd: int, non_blocking: bool) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK if non_blocking else msvcrt.LK_LOCK, 1)
        except OSError as exc:
            # A held lock must look like the POSIX result: BlockingIOError on a
            # non-blocking attempt, otherwise let the real error surface.
            if non_blocking:
                raise BlockingIOError(str(exc)) from exc
            raise

    def _unlock(fd: int) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            # Closing the fd releases it anyway; failing to unlock an
            # already-released lock is not a writer that kept running.
            pass
else:
    import fcntl

    def _lock(fd: int, non_blocking: bool) -> None:
        flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if non_blocking else 0)
        fcntl.flock(fd, flags)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _fileno(target) -> int:
    """Accepts an fd or anything with `.fileno()` (a file object)."""
    fileno = getattr(target, "fileno", None)
    return int(fileno()) if callable(fileno) else int(target)


def acquire(fd, *, non_blocking: bool = False) -> None:
    """Take the exclusive lock, optionally refusing when it is already held.

    A refused non-blocking attempt raises `BlockingIOError` on both platforms —
    that uniformity is what lets a caller say "another writer is active" instead
    of translating platform errnos.
    """
    _lock(_fileno(fd), bool(non_blocking))


def release(fd) -> None:
    """Give the lock up early; closing the file is still the real release."""
    _unlock(_fileno(fd))
