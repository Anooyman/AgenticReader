# AgenticReader

[中文](README.md) | English

AgenticReader is an LLM-powered document analysis and Q&A tool: it parses PDFs, builds FAISS vector indexes, and drives multi-turn intelligent conversations through five LangGraph agents. Beyond document Q&A it ships three real subsystems:

- **Long-term memory** (`src/memory/`): LanceDB-backed cross-session memory (`data/memory_db/`) — conversations are ingested automatically and retrieved by agents during Q&A;
- **Daily brief pipeline** (`src/pipeline/`): brief HTML files are queued in batch → downloaded/scraped → multi-dimensional QA summaries → automatically written into long-term memory;
- **Web scraping service** (`src/services/scraper/`): a Playwright-based anti-detection scraper that also runs as a stdio MCP server.

Supports Azure OpenAI, OpenAI, Ollama and Gemini providers; usable via **CLI** and **Web UI**.

> Developer-oriented architecture details (module hierarchy, dev patterns, testing notes) live in [CLAUDE.md](CLAUDE.md) at the repo root.

---

## Key Features

### 🤖 Five LangGraph Agents
- **IndexingAgent**: PDF parse → structure extraction → chunking → parallel chapter processing → vectorization → registration (any node error short-circuits straight to register; failed documents never appear in the searchable list)
- **AnswerAgent**: deterministic single-turn graph — `rewrite_query → plan → (execute → generate | generate) → END`; `plan` builds tool calls in plain code from the user-selected tools (no LLM decision, no loop)
- **RetrievalAgent**: ReAct retrieval loop over single/multiple documents (semantic search + observation + summary)
- **SearchAgent**: web search & URL analysis (DuckDuckGo MCP search + web_scraper MCP crawling; large content is auto-indexed then answered)
- **Orchestrator**: the real entry point of the web chat — a ReAct loop that autonomously calls `search_memory` (queries long-term memory) and/or `deep_dive_document` (deep-dive into one document); multiple tool calls run in parallel

### 📄 Document Processing
- Page-by-page PDF-to-image parsing, automatic TOC/chapter structure detection, chapter-level chunking
- FAISS semantic search (index and embeddings clients both have process-level LRU caches)
- Parallel chapter summaries/refactoring (`ChapterProcessor`), parallel multi-document retrieval (`ParallelRetrievalCoordinator`)
- Stage-wise caching: re-indexing skips completed stages automatically
- Concurrency-safe document registry `data/doc_registry.json` (flock + atomic writes), tracking processing state

### 💬 Intelligent Q&A
- **Five CLI entry modes**: single document / cross-document auto-selection / cross-document manual multi-select / web search & URL analysis / general chat
- **Tool system**: `retrieve_documents` and `search_web`, togglable in the chat UI
- **Memory-augmented**: conversations are persisted to LanceDB (`webapp-chat` namespace) and the Orchestrator can retrieve past memory during answers
- LLM-based conversation-history compression; retrieval results deduplicated per conversation round window (`RETRIEVAL_DEDUP_WINDOW`, default 5)
- Sessions are stored server-side as flat `data/sessions/{session_id}.json` files; the browser only stores UI preferences: theme in `AgenticReader_theme` and language in `AgenticReader_lang`

### 🌐 UI Language
- A header language button toggles Chinese / English; the choice is persisted to `localStorage`
- Global i18n covers the main pages (`/`, `/chat`, `/data`, `/config`, `/structure`, `/briefs`) and dynamically inserted UI nodes too
- LLM answers, document content, model/provider/env/namespace identifiers are not force-translated

### 🧠 Long-Term Memory (src/memory/)
- A single LanceDB table `memories`, isolated by namespace: `ai-research` (brief/article summaries), `webapp-chat` (conversation history) and `AATF` (light-ingested brief card digests)
- **chat_ingest background lane**: periodically scans the sessions directory and ingests sessions that are "updated + idle + containing a complete Q&A round" (content-hash idempotent dedup; watermark in `data/pipeline/chat_ingest_state.json`)
- **Light ingestion**: the "轻量入库(全天)" (light-load) button on `/briefs` writes that day's brief-card digests into `AATF`; pick the heavy pipeline (`/load`), light-load, or both. On the upstream path it hands over "card JSON + upstream ingest", so it does go through one round of LLM extraction and its idempotency belongs to upstream (see the cost note under the memory-convergence section below)
- **agentic_search**: a ReAct loop over four tools (semantic / keyword / keywords-pool / list-by-source), capped at 4 iterations, used by the Orchestrator; the default scope is ai-research + webapp-chat, `AATF` must be ticked in the `/chat` memory-scope picker
- The Memory tab on `/data` offers overview, search and deletion (single item / by source / whole namespace)

### 🧠 Memory convergence, Phase 1–2 (write/read/delete routing to the upstream LLM-Memory)

The storage layer itself stays owned by `src/memory/`; the external LLM-Memory is only an addressed upstream. There is now **exactly one decision point** for "where do we write / where do we read" — the **auto routing** inside `src/memory/gateway.py`: if `LLM_MEMORY_REPO` points at a reachable upstream checkout the call goes upstream, otherwise it falls back to the legacy local path with a warning, and caller signatures never change. What consults this switch is `gateway.search()` / `gateway.ingest()` plus the `gateway.delete_*` group (the mode value itself is parsed in one single place, `src/memory/config.py`, with illegal values warning→`auto`); the `browse_*` row-level primitives stay local. Phase 1 + Phase 2 in detail:

- **All three write channels are routed upstream**: the pipeline's `ingest_source()` (`ai-research`), the chat_ingest lane (`webapp-chat`), and the `/briefs` "light-load (whole day)" button — the last one now hands over "card JSON + `ingest(source_type=brief)`" upstream and **keeps using item_id as source_id, so the id space did not move** (the `aatf-<date>-<kind>` re-keying announced earlier was dropped, because the upstream patch added `source_id` pass-through). **Writes do not fall back**: when `LLM_MEMORY_REPO` is unset/invalid (routing decides "upstream unavailable") they write to the local `data/memory_db` as before, but when upstream is reachable and the write itself fails, gateway raises it to the caller (chat_ingest's watermark and job_runner's job ledger record the failure as usual) and never silently writes a local copy — that would be a double write, with the same content landing in two stores while the watermark still advances. The only clean ways to send routing back to local are to retry or to unset `LLM_MEMORY_REPO` / set `MEMORY_STORE_MODE=local`. Otherwise, with neither variable set, behavior is byte-for-byte what it was before convergence — dev/CI change nothing and the switch is reversible.
- **The read channel does fall back**: gateway `search()` forwards to upstream when it is available (passing multiple namespaces through) and runs the local `agentic_search` when upstream is unavailable or that particular search fails — this is the only read/write difference; the upstream wide-table rows are flattened by a mapping layer into the shape the sub-agent already consumes, `occurred_at` is preserved and the `/briefs` per-day aggregation stays the same. The mapping layer is **fidelity-first**: columns that upstream's schema does have (including `chunk_hash`, empty on summary rows) are used as-is when present in the result row, and heuristics only step in when a column isn't handed over — no extra keys are ever invented.
- **Existing rows are not migrated — delete and re-ingest**: `data/sessions/`, `data/pipeline/summaries/` and `BRIEFS_DIR` are the rebuildable sources of truth. Once convergence is in effect `data/memory_db` remains only as a **read-only fallback**, never a second source of truth.
- **Duplicate-ingest idempotency now belongs to upstream**: on the upstream path AR stops computing its own chunk-hash and relies on the upstream ingest's hash-dedup (feeding the same file twice must report 0 new rows — this is pinned by a test); while falling back to the legacy local path the previous content-hash idempotency still applies. The paper "download-and-ingest" flow (`POST /briefs/fetch-pdf`) and document-chat keep working untouched.
- **The delete surface is wired to upstream too, and these are now two stores**: the three DELETE flavours on the `/data` Memory tab (single item / by source / whole namespace) run through `gateway.delete_*` → upstream `delete`/`delete_where`, under the **same no-fallback discipline** and with two boundary guards — cross-namespace ids are rejected (one id must not be able to delete a row living elsewhere) and unscoped deletes (neither id nor namespace given) are always rejected, worded the way `memory_browse` expects. One shape note worth recording: the three `gateway.delete_*` functions **stay synchronous**, unlike `search()`/`ingest()` they are not `async` + `to_thread` — upstream calls are hard-capped by a thread pool and keeping the event loop unblocked is the caller's job. To be precise about semantics: what gets deleted is the row in the **upstream store**; the matching rows in the local `data/memory_db` are **untouched** — the two databases are now two separate stores, so don't read this as "one store where a row vanished" and don't expect to fish a deleted row back out of the local copy.
- **Counting now includes upstream (read-only)**: `/api/v1/memory/overview` and the namespace list merge the row counts from upstream `namespaces()`, so `/data` shows both sides' numbers side by side. This is purely a read-only merge at the counting layer — `browse_*` still reads rows out of the local library, nobody goes paging through rows under the numbers.
- **Three known costs** (documented, not bugs): ① the LLM/embedding config used for memory is **owned by the upstream config — the `/config` page cannot reach it**, and the `/config` provider choice does not change that either; the upstream embedding endpoint currently sits on a LAN address, so a machine outside that segment finds the upstream path entirely unavailable and the auto fallback is what absorbs it; ② AR hands over *already-summarized* files and the upstream ingest summarizes again — the same content goes through two rounds of LLM (passing `qa`/`qa_brief` explicitly can be used as the ready-made summary to skip the second extraction); ③ **"light-load (whole day)" is no longer a zero-LLM operation** — that old promise ("parse the cards and write them directly, without a single LLM call") is **officially retired** by the upstream `source_type=brief` channel: upstream runs its agentic extraction pipeline, one extraction round per card, so a day with many cards is noticeably slower. The **"is this day/card already ingested?" test changes too**: the local path looks at chunk-hash, while the upstream path reads the reported `chunks_added == 0` (that means "already there", not a failure and not an empty run) — don't infer upstream-path state from the chunk-hash rules.

To run the old path deliberately, use the `MEMORY_STORE_MODE=local` kill switch (default `auto`); leaving it unset along with `LLM_MEMORY_REPO` means everything goes the legacy route.

The three changes the upstream needed (a delete facade, the `source_type=brief` enum, `source_id` pass-through in `ingest`) **are now all in upstream main**: the user committed them themselves (`888f966` landed all three, `f181999` added the docs, pushed to github/main, HEAD `f181999`; the AR-side probe against that new HEAD also passes 15/15). **This is the user's own commit action, not this repository's** — this repo merged nothing upstream. The three files under `tools/upstream-patches/` stay as a **historical reference**: the path taken back then was "stack 01 → 02 → 03 in a clean `/tmp` clone and verify first" (each passed `git apply --check` cleanly, and after stacking all three the full upstream suite was green at 2114 passed / 4 skipped, with the pyflakes gate and the "no destructive tools advertised" MCP rule intact), and only after that verification did the user land them in main — so there is no "still need to apply the patches" task left, and don't treat those three files as a to-do list. The older phrasing — that the three files were still sitting outside the trunk and it was the user's call whether their worktree carried them — is retired. What to run, what was verified and what was not: [tools/upstream-patches/README.md](tools/upstream-patches/README.md); the phase breakdown and rulings live in [PLAN-MEMORY-CONVERGENCE.md](PLAN-MEMORY-CONVERGENCE.md).

### ♻️ Re-ingesting the backlog (Phase 3 · `python -m src.memory.converge`)

The backlog is **not migrated** — the three sources of truth already sit on disk, so this CLI re-ingests rather than relocates: `src/memory/converge.py` never reads or moves a single row of `data/memory_db`, which stays a read-only fallback once convergence is in effect. Its mapping is **aligned word for word** with the three standing write channels — no second id space: `data/pipeline/summaries/{pdf,web}/ → ai_research / ai-research`, `data/sessions/*.json → webapp_chat / webapp-chat`, `BRIEFS_DIR/<date>/*.html` cards `→ brief / AATF`, with `source_id` being item_id / session_id / the card's item_id respectively.

```bash
python -m src.memory.converge                              # default = dry-run: enumerate only, zero writes
python -m src.memory.converge --apply                      # actually deliver upstream
python -m src.memory.converge --only briefs --limit 50     # one source, first N items per source
python -m src.memory.converge --apply --retire-old-db      # trailing flag is a placeholder: printed, not executed
```

- **dry-run writes not a single byte**: it does not even construct a `MemoryClient` — doing that looks harmless but lets upstream expand the store directories by its own rules (empty scaffolding such as `ingest_state` appears under `~/.llm-memory/`, and mtimes move with it). So the dry-run gate only inspects the **configuration surface** (whether the env var is set, whether `<repo>/src` exists) and prints "configuration looks ready, upstream not contacted to confirm" — **ready is not the same as connected**, and "is upstream reachable" is left to the `--apply` gate.
- **Writes upstream only, never locally**: with `LLM_MEMORY_REPO` invalid or `MEMORY_STORE_MODE=local` it exits 1 and prints each reason ("not a single item will be delivered") instead of degrading silently — half the batch upstream and half in the old database is the mess that is hardest to clean up afterwards. That is also why it calls `upstream.upstream_ingest()` rather than `gateway.ingest()`: gateway decides per call site, so if upstream drops mid-run it would write that one item locally per its contract, which is exactly backwards from a batch contract that says "the whole batch goes upstream or nowhere".
- **Counter shape**: each item prints `+N added / M already present`, and the run ends with a summary of "calls → added / idempotent hits / failed"; a single failure is recorded and the batch continues, with failures yielding exit code 1. Idempotency belongs to upstream's hash-dedup — **there is no resume ledger and none is needed**: Ctrl-C lands on a source boundary and simply running it again picks up where it left off (interrupt exits 130, all-green exits 0, `--dry-run` together with `--apply` exits 2).
- **The cost has to be spelled out**: `--since/--until` filter dates as a **closed interval**, `--limit N` truncates each source separately, and `--only {summaries,sessions,briefs}` runs a single channel. These throttles are not decoration — with roughly 69 days of `BRIEFS_DIR` backlog on this machine that is thousands of agentic extractions (a few dozen cards in one day already means that many rounds of LLM calls), so to spend less, first check the scale in dry-run and then push it in date slices. A malformed date (anything but `YYYY-MM-DD`) errors out rather than silently acting like that day does not exist — the silent version would quietly skip a batch.

### 📰 Daily Brief Pipeline (src/pipeline/)
- Brief HTML files under `BRIEFS_DIR` are parsed into a queue (`data/pipeline/pipeline_queue.json`)
- The job_runner background lane processes the queue serially: download/scrape → IndexingAgent + AnswerAgent (+ SearchAgent) multi-dimensional QA → `generate_qa_brief` condenses a summary
- Summaries land in `data/pipeline/summaries/{pdf,web}/` and are written into the `ai-research` memory namespace; a failing item retries until `MAX_ATTEMPTS = 3`, then turns permanently failed
- Optional standalone CLIs: `python -m src.pipeline.sync_pipeline_queue` / `render_report` / `sync_memory_ingest` / `generate_qa_brief`

### 🕷️ Web Scraping (src/services/scraper/)
- Playwright (Chromium) scraping: browser management, download, content extraction and anti-detection modules
- Runnable as a stdio MCP server: `python -m scraper.mcp_server.server` (`PYTHONPATH=src/services`, already wired into the `web_scraper` entry of `MCP_CONFIG` for SearchAgent)

---

## Quick Start

### Requirements
- Python 3.12+ (virtual environment recommended)
- API credentials for at least one LLM provider (Azure OpenAI / OpenAI / Ollama / Gemini)

### Installation

```bash
# 1. Clone the repository
git clone <repository-url>
cd AgenticReader

# 2. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt   # only needed for tests (pytest / pytest-asyncio)

# 3. Create data directories (most components auto-create them, but create upfront is recommended)
mkdir -p data/pdf data/pdf_image data/json_data data/vector_db data/output \
         data/config data/sessions data/memory_db data/pipeline

# 4. Install the Playwright browser (required by the web_scraper MCP)
playwright install chromium

# 5. Web search relies on DuckDuckGo MCP launched via uvx (install `uv`)
#    as long as `uvx duckduckgo-mcp-server` can start, no further setup is needed
```

### Environment Variables

Create a `.env` file in the project root (loaded via python-dotenv; plain shell env vars also work):

```bash
# === Azure OpenAI ===
CHAT_API_KEY=your_azure_api_key
CHAT_AZURE_ENDPOINT=https://your-endpoint.openai.azure.com/
CHAT_DEPLOYMENT_NAME=your_deployment_name
CHAT_API_VERSION=2024-02-15-preview
CHAT_MODEL_NAME=gpt-6-luna
EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_API_VERSION=2024-02-15-preview
EMBEDDING_AZURE_ENDPOINT=https://your-endpoint.openai.azure.com/
EMBEDDING_DEPLOYMENT=your_embedding_deployment

# === Or OpenAI ===
# OPENAI_API_KEY=***            # defaults: gpt-6-luna / text-embedding-ada-002
# OPENAI_MODEL_NAME=gpt-6-luna
# OPENAI_BASE_URL=https://api.openai.com/v1/

# === Or Ollama (local) ===
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_MODEL_NAME=llama3
# OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# === Or Gemini ===
# GEMINI_API_KEY=***
# GEMINI_MODEL_NAME=gemini-1.5-pro
# GEMINI_EMBEDDING_MODEL=text-embedding-004

# === Provider selection (fallback when no UI config exists) ===
# PROVIDER=openai          # azure | openai | ollama | gemini
# EMBEDDING_PROVIDER=openai
```

### Start the Web UI

```bash
python src/ui/run_server.py
# → http://127.0.0.1:8000
```

`run_server.py` is the recommended entry point (cross-platform, Windows console handling, auto-reload). By default it **binds only to the 127.0.0.1 loopback address** — the app is designed for local, unauthenticated use. Override with env vars: `HOST=0.0.0.0` (starting with a non-loopback HOST prints a WARNING; assess the risk yourself), `PORT=8080`. Equivalent manual start (uvicorn's default host is also 127.0.0.1):

```bash
uvicorn src.ui.backend.app:app --reload --port 8000
```

### Start the CLI

```bash
python main.py
```

Main menu: enter a document number for single-document chat; `c` for cross-document auto-selected chat (picks documents by their brief summaries); `s` for cross-document manual multi-select; `w` for web search & URL analysis (SearchAgent); `0` for general chat; `i` to index a new PDF from `data/pdf/`; `m` to view/delete documents. Inside a conversation: `clear` history, `switch` mode, `main` back to menu, `quit` to exit.

### Run Tests

```bash
pytest                         # full run: script-style tests needing real LLM calls are auto-skipped
                               # when credentials are missing — runs fine credential-free
python tests/test_imports.py   # zero-dependency import smoke test, no network, no LLM calls
```

---

## Page Tour

| Page | Path | Purpose |
|---|---|---|
| Dashboard | `/` | Indexed-document overview, quick indexing, jump to chat |
| Chat | `/chat` | Real-time WebSocket conversation (served by the Orchestrator), Markdown/LaTeX rendering, tool & document toggles, MemorySearch/DeepDive/WebSearch tags on messages |
| Data Management | `/data` | Storage overview, per-document deletion of the four artifact types (JSON / vector DB / images / summaries), batch delete, smart cleanup, session stats, Memory tab |
| Configuration | `/config` | Provider switching, per-provider model registry (add/remove, set current, one-click test), system settings (persisted to `data/config/app_config.json`) |
| Structure Editor | `/structure` | Edit a document's structure.json and rebuild summaries/index; online PDF preview |
| Daily Briefs | `/briefs` | Two-pane brief workbench: left date-status calendar showing AATF / deep-analysis / running / error / missing dates, center card feed with filters, multi-select, bulk AATF import and deep analysis, right job drawer for background tasks; cards can download+ingest papers (`POST /briefs/fetch-pdf` → `data/pdf` + background indexing) |
| ~~Brief–Memory Bridge~~ | `/memory` | Retired — merged into `/briefs`; the external LLM-Memory HTTP bridge is retired as well, replaced by the in-process SDK / MCP read-only facade; old bookmarks 302-redirect |
| API docs | `/docs` `/redoc` | Generated by FastAPI |
| Health check | `/health` | status / timestamp / version |

## Common Tasks

**Index your first PDF**: drop it into `data/pdf/`, click index on `/` (or pick `i` in the CLI). Node-by-node progress logs: parse → structure → chunk → chapters → index → summary → register.

**Use long-term memory in chat**: just chat — after replies, the chat_ingest lane ingests idle complete sessions automatically; later questions may have the Orchestrator autonomously call `search_memory` over your history.

**Ask what new papers or news arrived today/yesterday**: tick `AATF` in the `/chat` memory-scope picker before asking, so the Orchestrator searches the brief-card memory first. The default memory scope still does not include `AATF`, because ordinary questions should not always search the brief library.

**Combine document retrieval and web search in one answer**: tick the 📎 document-retrieval and 🌐 web-search tools in `/chat`; in the CLI use mode `w` for pure web search.

**Switch LLM provider**: in the web UI pick it on `/config` (written to `data/config/app_config.json`; one question uses the same provider across the whole chain); in the CLI fall back to env `PROVIDER`. Priority: explicit argument > `app_config.json` > env `PROVIDER` > `openai`.

**Delete / clean data**: `/data` supports deleting only a document's images or vector DB (freeing space while keeping parsed results so re-indexing skips re-parsing), batch delete, and `cleanup/smart` by age; all deletions funnel through the single implementation `src/core/document_management/delete_service.py`.

**Run the daily brief pipeline**: put brief HTMLs under `BRIEFS_DIR` (env-overridable; default `~/Desktop/AATF-Intelligence-Briefs`) → check "load" on `/briefs` → job_runner processes them in the background; summaries land in `data/pipeline/summaries/` and enter memory.

**Use a different model per agent**: edit `AGENT_MODEL_OVERRIDES` in `src/config/model_overrides.py` (looked up by agent name).

**Use speech**: `/api/v1/speech/transcribe|synthesize` (requires `OPENAI_API_KEY`).

---

## Configuration Reference (full env var list)

**Chat model credentials (`src/config/settings.py`)**

| Variable | Notes |
|---|---|
| `CHAT_API_KEY` `CHAT_API_VERSION` `CHAT_AZURE_ENDPOINT` `CHAT_DEPLOYMENT_NAME` `CHAT_MODEL_NAME` | Azure OpenAI |
| `OPENAI_API_KEY` `OPENAI_MODEL_NAME` (default gpt-6-luna) `OPENAI_BASE_URL` | OpenAI |
| `OLLAMA_BASE_URL` (default `http://localhost:11434`) `OLLAMA_MODEL_NAME` (default llama3) | Ollama |
| `GEMINI_API_KEY` `GEMINI_MODEL_NAME` (default gemini-1.5-pro) `GEMINI_BASE_URL` | Gemini |

**Embedding (the single read entry point for provider/model name is `settings.get_embedding_provider()` / `get_embedding_model_name()`)**

| Variable | Notes |
|---|---|
| `EMBEDDING_PROVIDER` | embedding provider selection (default openai) |
| `EMBEDDING_API_KEY` `EMBEDDING_API_VERSION` `EMBEDDING_AZURE_ENDPOINT` `EMBEDDING_DEPLOYMENT` `EMBEDDING_MODEL` | Azure embedding |
| `OPENAI_EMBEDDING_MODEL` (default text-embedding-ada-002) | OpenAI embedding |
| `OLLAMA_EMBEDDING_MODEL` (default llama3) | Ollama embedding |
| `GEMINI_EMBEDDING_MODEL` (default text-embedding-004) | Gemini embedding |

**Runtime behavior**

| Variable | Notes |
|---|---|
| `HOST` / `PORT` | `run_server.py` bind address/port, default `127.0.0.1` / `8000`; non-loopback HOST prints a WARNING |
| `CORS_ORIGINS` | comma-separated origins; defaults allow only localhost/127.0.0.1:8000; `*` disables credentials automatically |
| `PROVIDER` | provider fallback for the CLI and other paths without UI config |
| `RETRIEVAL_DEDUP_WINDOW` | retrieval dedup round window, default 5 |
| `BRIEFS_DIR` | brief HTML directory, default `~/Desktop/AATF-Intelligence-Briefs` |
| `LLM_MEMORY_REPO` | path to the upstream LLM-Memory checkout — the single addressing point for the read-only facade (in-process SDK primary, optional MCP stdio decision plane); unset or invalid means upstream reports `available:false` + note, local features entirely unaffected |
| `LLM_MEMORY_MCP_ENABLED` | `=1` enables the optional MCP stdio decision plane (`python -m llm_memoryd.mcp --tools memory_why,memory_pack` — the why/pack tools must be explicitly opened); off by default — with neither variable set, default behavior is entirely unaffected |
| `MEMORY_STORE_MODE` | memory storage routing switch: `auto` (**default**) = the single gateway decision point picks the route, upstream when `LLM_MEMORY_REPO` is usable and the legacy local path otherwise; `local` = force the legacy local path (a debugging/comparison kill switch — upstream is not written to even when available). Leaving it unset together with `LLM_MEMORY_REPO` means every route stays legacy, zero change for dev/CI. It affects write/read routing only and does **not** touch the `LLM_MEMORY_MCP_ENABLED` read-only decision plane |
| `DEBUG` | WebSocket debug-output switch (`true` to enable), off by default |

> Historical note: the old external LLM-Memory webui HTTP bridge (`MEMORY_BRIEF_DRIVER=bridge` +
> `LLM_MEMORY_URL`, default `http://127.0.0.1:8765`) is **fully retired** — the `load_brief_date`
> driver whitelist converged to `local` only; explicitly setting `bridge` just logs a warning and
> runs `local` instead, with no outbound HTTP calls anywhere left in the repo.
> Also: the external "load briefs for a given date" bridge has **no substitute at all** —
> brief ingestion runs on the `local` path only; this missing capability is a ruling,
> not a regression, so don't go looking for it.

**Two common misconceptions**
- **There is no `LOGGING_LEVEL` env var**: no code reads it; the app log level is hardcoded in `logging.basicConfig(level=logging.INFO)` in `src/core/llm/client.py` (five such calls exist across the repo and only the first one imported takes effect). uvicorn's own access-log level does come from the `log_level` key of `data/config/app_config.json` (`src/ui/run_server.py:resolve_log_level`; that is exactly what the `/config` page writes), with any invalid value falling back to `info`.
- **There is no client-side session storage**: sessions live server-side only; localStorage stores only UI preferences (`AgenticReader_theme` for theme and `AgenticReader_lang` for language).

---

## Architecture at a Glance

```
AgenticReader/
├── main.py                     # CLI entry (drives AnswerAgent / SearchAgent)
├── src/agents/                 # Five agents (each with agent/nodes/tools/state/prompts)
│   ├── base.py                 #   AgentBase: provider selection, per-name model overrides
│   ├── indexing/               #   IndexingAgent (incl. components/metadata_extractor.py)
│   ├── answer/                 #   AnswerAgent (tools_config.py registry; components/ selector·synthesizer·formatter)
│   ├── retrieval/              #   RetrievalAgent (ReAct retrieval)
│   ├── search/                 #   SearchAgent (utils.py holds SimpleMCPClient, stdio transport)
│   └── orchestrator/           #   Orchestrator + sub_agents/ (memory_search, deep_dive, search_web)
├── src/config/                 # settings.py (LLM/Embedding/MCP config), constants.py,
│   └── prompts/                #   model_overrides.py; prompts only metadata_prompts.py
├── src/core/
│   ├── document_management/    # registry / indexer / delete_service (the single delete implementation) / manager
│   ├── llm/                    # client (LLMBase + logging + embeddings cache) / providers / history
│   ├── parallel/               # indexing.py (ChapterProcessor) / retrieval.py (ParallelRetrievalCoordinator)
│   └── vector_db/              # vector_db_client (FAISS + round dedup + index cache) / metadata_db
├── src/memory/                 # LanceDB long-term memory (config / gateway / ingest / search / brief_ingest / migrate_aatf / upstream / vector_store / adapters)
│                               #   upstream = access layer for the external LLM-Memory (in-process SDK + optional MCP plane;
│                               #     the write path lives here too — its "read-only only" discipline is
│                               #     deliberately reversed by the convergence ruling)
│                               #   brief_ingest = the "light-load (whole day)" implementation (card JSON handed to the
│                               #     upstream ingest; local direct writing is its fallback shape);
│                               #   migrate_aatf is a one-shot A→B library migration CLI —
│                               #   run it with --dry-run first to see the plan
├── src/pipeline/               # brief pipeline (briefs_parser / queue_store / process_pdf_queue /
│                               #   process_web_queue / generate_qa_brief / render_report / sync_* / paths)
├── src/services/scraper/       # Playwright scraper package (core/browser·downloader·extractor·anti_detection,
│                               #   storage, mcp_server/server·tools)
├── src/ui/
│   ├── run_server.py           # launch entry (HOST/PORT, loopback-safe default)
│   ├── backend/                # app.py (lifespan starts the job_runner + chat_ingest lanes), config.py
│   │   ├── api/                # pages (page routes; /memory 302s to /briefs), websocket (/ws/chat), v1/ (documents chat pdf
│   │   │                       #   structure config sessions data·data_storage·data_ops·data_common
│   │   │                       #   briefs jobs memory speech)
│   │   └── services/           # chat_service (routes to Orchestrator), session_manager, chat_ingest,
│   │                           #   job_runner, memory_browse, task_service, briefs_data
│   ├── templates/              # base dashboard chat config manage structure_editor briefs
│   └── static/                 # css/ (chat manage dashboard briefs …) js/ (api chat i18n locales
│                               #   chat-enhancer manage config dashboard briefs …)
├── src/utils/                  # json_io (the single write_json_atomic implementation), path_guard (safe_path) etc.
└── data/                       # runtime data (see below)
```

**Data directories** (all flat under `data/`, 9 in total):

```
data/
├── pdf/            # PDF sources to index
├── pdf_image/      # per-page PDF images (folder per document)
├── json_data/      # parsed data ({doc}/data.json, structure.json, chunks.json)
├── vector_db/      # FAISS indexes ({doc}_data_index/)
├── output/         # brief_summary.md and other summary artifacts
├── config/         # app_config.json (provider / system settings)
├── sessions/       # flat {session_id}.json sessions (legacy per-mode subdirs auto-migrated)
├── memory_db/      # LanceDB long-term memory store
├── pipeline/       # pipeline_queue.json, webapp_jobs.json, chat_ingest_state.json, summaries/
└── doc_registry.json  # document registry
```

**Chat data flow**: `/ws/chat` → `chat_service` → **Orchestrator.ask()** (ReAct: may autonomously call `search_memory` → `agentic_search` in `src/memory/search.py`, `deep_dive_document` → AnswerAgent deep-dive into one document, and `search_web` → SearchAgent for live web search — the last one only when the session has web search enabled; guarded by round/context/timeout limits). Long conversations are windowed by `session_manager.history_for_llm_async`: the most recent 20 messages verbatim plus incremental summaries of older parts, degrading to plain truncation if summarization fails. The CLI drives AnswerAgent / SearchAgent directly from `main.py`.

**Indexing data flow**: upload/select a PDF → the IndexingAgent graph (check_cache → parse → extract_structure → chunk → process_chapters → build_index → generate_brief_summary → register); errors short-circuit straight to register and are never marked completed.

**MCP services** (`MCP_CONFIG` in `settings.py`): `duckduckgo` (`uvx duckduckgo-mcp-server`), `web_scraper` (this repo's own Playwright scraping MCP), and the default-off `llm_memory` entry (`python -m llm_memoryd.mcp --tools memory_why,memory_pack`, invoked by `src/memory/upstream.py` behind the `LLM_MEMORY_MCP_ENABLED` gate). SearchAgent's MCP client is `SimpleMCPClient` in `src/agents/search/utils.py` (stdio); upstream's decision-plane client is implemented in place in the same stdio shape and does not import `src.agents`.

## REST API Quick Reference

All prefixed with `/api/v1`:

```
documents  GET  /list /available-pdfs      POST /upload /index       DELETE /{doc_name}
chat       POST /initialize /clear         GET  /load-more-messages
sessions   GET  /list /{id}  DELETE /{id}  PATCH /{id}/rename /{id}/memory-scope
pdf        GET  /view/{doc_name}           # PDF page images
structure  GET|PUT /{doc_name}             POST /{doc_name}/rebuild
config     GET  ""                         POST /provider /system /reset
               GET  /models                POST /models /models/test
data       GET  /overview /documents /documents/{name}/summary /documents/pending
               /sessions/stats /tasks/{task_id}
           POST /documents/{filename}/index /cleanup/smart
           DELETE /pdfs /documents/{name}/parts /documents
briefs     GET  /dates /cards /memory-status   POST /load /sync-memory /light-load
                # GET /cards accepts date, include_state=1 and compact=1, returning cards plus optional AATF / deep-analysis / job state
                # GET /memory-status accepts include_meta=1, returning storage_mode, upstream row counts, HTML-date coverage and queue stats
               POST /fetch-pdf                 # pull a paper PDF into data/pdf + background indexing
jobs       GET  ""                         POST /{job_id}/retry /cancel
memory     GET  /overview /namespace/{ns}  POST /search
           DELETE /item/{id} /namespace/{ns}/source/{source_id} /namespace/{ns}
                 # convergence note: writes/reads/deletes now follow the gateway's auto
                 # routing upstream — the three DELETE flavours run through upstream
                 # delete/delete_where (unscoped and cross-namespace ids are rejected),
                 # deleting removes the upstream-store row while the local legacy rows
                 # stay put; browse_* remains a local primitive
           GET  /upstream                  POST /upstream/search
                # upstream read-only facade: status fields available + namespaces/rows +
                # version, embedding decision:{enabled,available,note}; searches default to
                # global scope (scoped=False), narrowing only on an explicit namespace
           POST /upstream/decision         # upstream decision-plane passthrough: memory_why/memory_pack
                # whitelist, gated by LLM_MEMORY_MCP_ENABLED, folded unavailable+note when off
speech     POST /transcribe /synthesize
```

Note: the sessions API is list / get / delete / rename plus `PATCH /{id}/memory-scope` (which memory namespaces this session searches — defaults to ai-research + webapp-chat, AATF must be opted in) — there are **no** import/export endpoints (the former current/info was removed as unused); `/api/v1/memory` has no single-item GET endpoint; the `/memory` page itself is retired and 302-redirects to `/briefs`. `DELETE /sessions/{id}` also reclaims this session's memory rows in `webapp-chat` by source and drops its chat_ingest watermark entry (best-effort; failures are only logged).

## Security Notes

- Binds only to `127.0.0.1` by default and CORS allows only local origins — the app targets local use and has no authentication; add your own protection before exposing it via `HOST`.
- Every API that builds data paths from a document name passes through `safe_path()` (`src/utils/path_guard.py`) to prevent path traversal.
- All deletions funnel through the single `delete_service.py` implementation, combined with path validation.
- `POST /briefs/fetch-pdf` is a server-side fetch: http(s) only, the target host is validated after resolution against a denylist of loopback / private / link-local / cloud-metadata / reserved addresses, and redirects are followed hop-by-hop by us with that check re-run per hop (no host allowlist — arxiv and the public internet still work); this is the same trust boundary as the SearchAgent fetch surface.

---

## License

[MIT License](LICENSE)

## Contributing

Issues and pull requests are welcome!

## Acknowledgments

- [LangChain](https://github.com/langchain-ai/langchain) / [LangGraph](https://github.com/langchain-ai/langgraph) - LLM application and multi-agent orchestration frameworks
- [FAISS](https://github.com/facebookresearch/faiss) - efficient vector search library
- [FastAPI](https://fastapi.tiangolo.com/) - modern web framework
- [LanceDB](https://lancedb.com/) - embedded vector database (long-term memory storage)
- [Playwright](https://playwright.dev/) - browser automation (web scraping)
