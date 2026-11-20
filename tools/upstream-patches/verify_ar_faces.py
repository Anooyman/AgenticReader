#!/usr/bin/env python3
"""Apply-after probe: do the patched upstream interfaces look like what AgenticReader
will call? Run this AFTER the three patches are applied to an upstream checkout.

    LLM_MEMORY_REPO=/path/to/LLM-Memory python3 verify_ar_faces.py

It writes nothing outside a temp dir, makes no network calls and needs no API keys.
The point is not "the upstream tests pass" (they do, see README.md) — it is that the
three call shapes AgenticReader's Phase 2 wiring needs are actually there, so that
`gateway.delete_*`, the `upstream.py` source_id probe, and `/briefs` light-ingest all
have a real upstream surface to land on.

What each check means for AgenticReader:
  * delete / delete_where signatures  -> gateway.delete_item / delete_source / delete_namespace
  * unscoped refusal wording          -> memory_browse's 400-style guard expectations
  * brief in enum + MCP schema        -> /briefs light-load can switch to upstream ingest
  * inspect.signature(ingest)         -> upstream.py's existing source_id probe flips to True
"""
import inspect
import os
import sys
import tempfile

REPO = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LLM_MEMORY_REPO")
if REPO:
    sys.path.insert(0, os.path.join(REPO, "src"))

# Set BEFORE importing anything upstream: `common.paths` snapshots its data root
# at import time, and the store lock file lives under it. Without this the probe
# would reach into ~/.llm-memory — a real store — instead of this temp tree.
os.environ.setdefault("MEMORY_DATA_DIR", tempfile.mkdtemp(prefix="ar-faces-data-"))

from llm_memoryd import mcp                                  # noqa: E402
from llm_memoryd.api import SOURCE_TYPES, MemoryClient        # noqa: E402

CONFIG = {
    "embedding": {"model": "probe-only", "dimensions": 8, "endpoint": "unused"},
    "llm": {"endpoint": "unused", "api_key": "unused", "model": "unused"},
    "knowledge": {"extract_model": "unused"},
}
ROW = {"id": "aatf-20261119-paper", "vector": [0.1] * 8, "namespace": "AATF",
       "tier": "mid", "memory_type": "semantic", "abstract": "a", "detail": "d",
       "abstracts_chain": "[]", "keywords": '["k"]', "importance": 0.5,
       "access_count": 0, "last_accessed_at": "",
       "created_at": "2026-11-19T00:00:00+00:00",
       "tier_updated_at": "2026-11-19T00:00:00+00:00", "source": "probe",
       "session_id": "", "occurred_at": "2026-11-19",
       "source_id": "aatf-20261119", "source_type": "brief"}

failures = []


def check(label, ok, detail=""):
    print(f"[{'ok  ' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="ar-faces-")
    client = MemoryClient(config=CONFIG, store_dir=os.path.join(tmp, "store"))

    # 1. The delete facade, shaped the way gateway.delete_* wants to call it.
    check("MemoryClient.delete exists", callable(getattr(client, "delete", None)),
          str(inspect.signature(client.delete)))
    check("MemoryClient.delete_where exists", callable(getattr(client, "delete_where", None)),
          str(inspect.signature(client.delete_where)))

    # 2. Unscoped deletes are refused with wording a UI/handler can pattern-match.
    for bad in ({}, {"namespace": "*"}, {"namespace": ""}, {"namespace": None}):
        try:
            client.delete_where(**bad)
        except ValueError as exc:
            check(f"unscoped {bad} refused", "namespace" in str(exc), str(exc)[:60])
        else:
            check(f"unscoped {bad} refused", False, "ACCEPTED — the guard is gone")

    # 3. The brief channel is open at both places a caller can discover.
    check("brief in api.SOURCE_TYPES", "brief" in SOURCE_TYPES, str(SOURCE_TYPES))
    ingest_tool = next((t for t in mcp.TOOLS if t["name"] == "memory_ingest"), None)
    advertised = (ingest_tool or {}).get("inputSchema", {}).get(
        "properties", {}).get("source_type", {}).get("enum", [])
    check("brief in MCP ingest schema", "brief" in advertised, str(advertised))

    # 4. ingest() now takes the source_id AgenticReader addresses rows by. The
    #    probe is exactly the one src/memory/upstream.py already runs.
    probe = "source_id" in inspect.signature(client.ingest).parameters
    check("upstream.py's source_id probe", probe, "signature has the parameter"
          if probe else "probe would still warn and let the adapter derive")

    # 5. Real row lifecycle through the facade (the store, not a mock).
    try:
        from llm_memoryd.common.vector import VectorStore
    except Exception as exc:                       # lancedb absent: shapes still matter
        check("store-backed lifecycle", False, f"skipped: {exc}")
    else:
        store = VectorStore(os.path.join(tmp, "store"), CONFIG)
        store.add(dict(ROW))
        out = client.delete(ROW["id"], namespace="AATF")
        check("delete one row", out.get("deleted") is True, str(out))
        store.add(dict(ROW))
        out = client.delete_where(namespace="AATF", source_id=ROW["source_id"])
        check("delete_where by (namespace, source_id)", out.get("deleted") == 1, str(out))
        check("scope emptied", len(store.all_rows("AATF")) == 0)

        store.add(dict(ROW))
        try:
            client.delete(ROW["id"], namespace="webapp-chat")
        except ValueError as exc:
            check("cross-namespace assertion refuses", True, str(exc)[:70])
        else:
            check("cross-namespace assertion refuses", False, "deleted a row it was not told about")

        store.add(dict(ROW))
        before = len(store.all_rows("AATF"))
        out = client.delete_where(namespace="AATF", dry_run=True)
        left = len(store.all_rows("AATF"))
        check("dry_run previews without deleting",
              out.get("dry_run") is True and out.get("deleted") == before and left == before,
              f"{out} rows_before={before} rows_after={left}")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed — do not wire AgenticReader against this build.")
        return 1
    print("All checks passed: the patched upstream exposes the surface AgenticReader needs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
