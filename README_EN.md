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
- Sessions are stored server-side as flat `data/sessions/{session_id}.json` files; the browser uses localStorage only for the theme preference (the `AgenticReader_theme` key)

### 🧠 Long-Term Memory (src/memory/)
- A single LanceDB table `memories`, isolated by namespace: `ai-research` (brief/article summaries) and `webapp-chat` (conversation history)
- **chat_ingest background lane**: periodically scans the sessions directory and ingests sessions that are "updated + idle + containing a complete Q&A round" (content-hash idempotent dedup; watermark in `data/pipeline/chat_ingest_state.json`)
- **agentic_search**: a ReAct loop over four tools (semantic / keyword / keywords-pool / list-by-source), capped at 4 iterations, used by the Orchestrator
- The Memory tab on `/data` offers overview, search and deletion (single item / by source / whole namespace)

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
CHAT_MODEL_NAME=gpt-4
EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_API_VERSION=2024-02-15-preview
EMBEDDING_AZURE_ENDPOINT=https://your-endpoint.openai.azure.com/
EMBEDDING_DEPLOYMENT=your_embedding_deployment

# === Or OpenAI ===
# OPENAI_API_KEY=***            # defaults: gpt-3.5-turbo / text-embedding-ada-002
# OPENAI_MODEL_NAME=gpt-4o
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
| Chat | `/chat` | Real-time WebSocket conversation (served by the Orchestrator), Markdown/LaTeX rendering, tool & document toggles, MemorySearch/DeepDive tags on messages |
| Data Management | `/data` | Storage overview, per-document deletion of the four artifact types (JSON / vector DB / images / summaries), batch delete, smart cleanup, session stats, Memory tab |
| Configuration | `/config` | Provider switching, system settings (persisted to `data/config/app_config.json`) |
| Structure Editor | `/structure` | Edit a document's structure.json and rebuild summaries/index; online PDF preview |
| Daily Briefs | `/briefs` | Browse `BRIEFS_DIR` brief entries, check-and-load into the pipeline queue, watch background jobs |
| Brief–Memory Bridge | `/memory` | Bridges an **external** LLM-Memory webui (`LLM_MEMORY_URL`, default `http://127.0.0.1:8765`) — a different system from the built-in `src/memory/` |
| API docs | `/docs` `/redoc` | Generated by FastAPI |
| Health check | `/health` | status / timestamp / version |

## Common Tasks

**Index your first PDF**: drop it into `data/pdf/`, click index on `/` (or pick `i` in the CLI). Node-by-node progress logs: parse → structure → chunk → chapters → index → summary → register.

**Use long-term memory in chat**: just chat — after replies, the chat_ingest lane ingests idle complete sessions automatically; later questions may have the Orchestrator autonomously call `search_memory` over your history.

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
| `OPENAI_API_KEY` `OPENAI_MODEL_NAME` (default gpt-3.5-turbo) `OPENAI_BASE_URL` | OpenAI |
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
| `LLM_MEMORY_URL` | external LLM-Memory webui address (bridged by the `/memory` page), default `http://127.0.0.1:8765` |
| `DEBUG` | WebSocket debug-output switch (`true` to enable), off by default |

**Two common misconceptions**
- **There is no `LOGGING_LEVEL` env var**: no code reads it; the log level is hardcoded in `logging.basicConfig(level=logging.INFO)` in `src/core/llm/client.py` — change that line for DEBUG.
- **There is no client-side session storage**: sessions live server-side only; localStorage stores just the theme preference (the `AgenticReader_theme` key in `base.html`).

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
│   └── orchestrator/           #   Orchestrator + sub_agents/ (memory_search, deep_dive)
├── src/config/                 # settings.py (LLM/Embedding/MCP config), constants.py,
│   └── prompts/                #   model_overrides.py; prompts only metadata_prompts.py
├── src/core/
│   ├── document_management/    # registry / indexer / delete_service (the single delete implementation) / manager
│   ├── llm/                    # client (LLMBase + logging + embeddings cache) / providers / history
│   ├── parallel/               # indexing.py (ChapterProcessor) / retrieval.py (ParallelRetrievalCoordinator)
│   └── vector_db/              # vector_db_client (FAISS + round dedup + index cache) / metadata_db
├── src/memory/                 # LanceDB long-term memory (config / ingest / search / vector_store / adapters)
├── src/pipeline/               # brief pipeline (briefs_parser / queue_store / process_pdf_queue /
│                               #   process_web_queue / generate_qa_brief / render_report / sync_* / paths)
├── src/services/scraper/       # Playwright scraper package (core/browser·downloader·extractor·anti_detection,
│                               #   storage, mcp_server/server·tools)
├── src/ui/
│   ├── run_server.py           # launch entry (HOST/PORT, loopback-safe default)
│   ├── backend/                # app.py (lifespan starts the job_runner + chat_ingest lanes), config.py
│   │   ├── api/                # pages (7 pages), websocket (/ws/chat), v1/ (documents chat pdf
│   │   │                       #   structure config sessions data·data_storage·data_ops·data_common
│   │   │                       #   briefs jobs memory speech llmmemory)
│   │   └── services/           # chat_service (routes to Orchestrator), session_manager, chat_ingest,
│   │                           #   job_runner, memory_browse, task_service, briefs_data, brief_memory
│   ├── templates/              # base dashboard chat config manage structure_editor briefs memory
│   └── static/                 # css/ (chat manage dashboard briefs memory …) js/ (api chat
│                               #   chat-enhancer manage config dashboard briefs memory …)
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

**Chat data flow**: `/ws/chat` → `chat_service` → **Orchestrator.ask()** (ReAct: may autonomously call `search_memory` → `agentic_search` in `src/memory/search.py`, and `deep_dive_document` → AnswerAgent deep-dive into one document; guarded by round/context/timeout limits). The CLI drives AnswerAgent / SearchAgent directly from `main.py`.

**Indexing data flow**: upload/select a PDF → the IndexingAgent graph (check_cache → parse → extract_structure → chunk → process_chapters → build_index → generate_brief_summary → register); errors short-circuit straight to register and are never marked completed.

**MCP services** (`MCP_CONFIG` in `settings.py`): `duckduckgo` (`uvx duckduckgo-mcp-server`) and `web_scraper` (this repo's own Playwright scraping MCP). The MCP client is `SimpleMCPClient` in `src/agents/search/utils.py` (stdio).

## REST API Quick Reference

All prefixed with `/api/v1`:

```
documents  GET  /list /available-pdfs      POST /upload /index       DELETE /{doc_name}
chat       POST /initialize /clear         GET  /load-more-messages
sessions   GET  /list /current/info /{id}  DELETE /{id}  PATCH /{id}/rename
pdf        GET  /view/{doc_name}           # PDF page images
structure  GET|PUT /{doc_name}             POST /{doc_name}/rebuild
config     GET  ""                         POST /provider /system /reset
data       GET  /overview /documents /documents/{name}/summary /documents/pending
               /sessions/stats /tasks/{task_id}
           POST /documents/{filename}/index /cleanup/smart
           DELETE /pdfs /documents/{name}/parts /documents
briefs     GET  /dates /cards              POST /load /sync-memory
jobs       GET  ""                         POST /{job_id}/retry /cancel
memory     GET  /overview /namespace/{ns}  POST /search
           DELETE /item/{id} /namespace/{ns}/source/{source_id} /namespace/{ns}
speech     POST /transcribe /synthesize
llmmemory  # transparent proxy to an external LLM-Memory webui (for the /memory page)
```

Note: the sessions API has exactly five endpoints — list / current-info / get / delete / rename — there are **no** import/export endpoints; `/api/v1/memory` has no single-item GET endpoint.

## Security Notes

- Binds only to `127.0.0.1` by default and CORS allows only local origins — the app targets local use and has no authentication; add your own protection before exposing it via `HOST`.
- Every API that builds data paths from a document name passes through `safe_path()` (`src/utils/path_guard.py`) to prevent path traversal.
- All deletions funnel through the single `delete_service.py` implementation, combined with path validation.

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
