"""Where a store is found, and why no path may be written down.

`migrate_aatf` reads the upstream LLM-Memory store. Upstream has moved its data
root twice (checkout-local `data/memory` -> a per-machine `MEMORY_DATA_DIR` ->
the machine-level `~/.llm-memory/memory`), and every one of those moves left a
stale hardcoded string behind in a tool that reads that store.

The failure mode that makes this worth a test: a hardcoded path that still
*exists* on disk as an empty directory, or that simply no longer exists, yields
"0 rows, nothing to migrate" — a successful-looking run that silently imports
nothing. An error naming the path is the acceptable outcome here.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.memory import migrate_aatf  # noqa: E402


def test_explicit_source_is_untouched(tmp_path):
    assert migrate_aatf._resolve_b_dir(str(tmp_path)) == str(tmp_path)


def test_the_store_dir_env_var_is_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MEMORY_STORE_DIR", str(tmp_path))
    monkeypatch.delenv("MEMORY_DATA_DIR", raising=False)
    assert migrate_aatf._resolve_b_dir() == str(tmp_path)


def test_memory_data_dir_resolves_to_its_memory_child(tmp_path, monkeypatch):
    """Upstream's own `MEMORY_DATA_DIR` names the data ROOT, not the store."""
    (tmp_path / "memory").mkdir()
    monkeypatch.setenv("MEMORY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_MEMORY_STORE_DIR", raising=False)
    assert migrate_aatf._resolve_b_dir() == str(tmp_path / "memory")


def test_the_machine_root_is_the_last_resort(monkeypatch):
    monkeypatch.delenv("LLM_MEMORY_STORE_DIR", raising=False)
    monkeypatch.delenv("MEMORY_DATA_DIR", raising=False)
    assert migrate_aatf._DEFAULT_B_DIR == os.path.expanduser("~/.llm-memory/memory")


def test_no_source_file_hardcodes_a_checkout_local_store_path():
    """A specific path is not allowed to stand in for "where the store is"."""
    offenders = []
    for path in (pathlib.Path(__file__).resolve().parents[1] / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "GitHub/LLM-Memory/data" in text or "LLM-Memory/data/memory" in text:
            offenders.append(str(path))
    assert not offenders, f"hardcoded upstream store paths in: {offenders}"
