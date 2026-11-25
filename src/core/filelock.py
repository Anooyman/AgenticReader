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
* Windows `msvcrt.locking()` locks one byte at offset zero (a byte-range lock).
  Its blocking form (`LK_LOCK`) gives up after roughly ten seconds — which on
  POSIX would read as "queued behind a long writer", but here as "your write
  failed". Since 2026-11-25 the blocking path is a wait-then-retry loop with an
  explicit budget (see `LOCK_WAIT_BUDGET_S`) that mirrors POSIX semantics: a
  blocked writer waits, and only a genuinely stuck one surfaces an error.

Callers should not assume the lock is mandatory. It is the coordination point,
not a guarantee against a process that declined to coordinate.
"""
from __future__ import annotations

import os

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:  # pragma: no cover - exercised only on Windows hosts
    import msvcrt
    import time

    # Windows 阻塞锁语义对齐 POSIX（2026-11-25，review 尾巴⑥）：msvcrt 的
    # LK_LOCK 阻塞形态只试 ~10s 就 raise——在 POSIX 上这只是"排队"，在
    # Windows 上却是"锁被占用 ⇒ 你的写失败"。indexer 的 update_stage_status
    # 这类调用点都是直接记账失败，一次并发注册表写者就能把整次索引判死。
    # 改法不靠 LK_LOCK 的黑盒重试，自己排：NBLCK 轮询、间隔数秒、预算给足
    # （300s——本仓库的关键区都是一次 JSON 读写，等这个数还没等到，问题
    # 就不是"等等就好"了），预算耗尽才把最后一个 OSError 原样递出去。
    LOCK_RETRY_WAIT_S = 5.0
    LOCK_WAIT_BUDGET_S = 300.0

    def _lock(fd: int, non_blocking: bool) -> None:
        if non_blocking:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                # A held lock must look like the POSIX result: refused now.
                raise BlockingIOError(str(exc)) from exc
            return
        deadline = time.monotonic() + LOCK_WAIT_BUDGET_S
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(min(LOCK_RETRY_WAIT_S, max(0.1, deadline - time.monotonic())))

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
