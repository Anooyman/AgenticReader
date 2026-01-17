# AgenticReader

[中文](README.md) | English

AgenticReader is an advanced document analysis and intelligent Q&A tool powered by large language models (LLM) and Multi-Agent architecture. Built on Agent orchestration patterns, it supports PDF document parsing, integrates multiple LLM providers (Azure OpenAI, OpenAI, Ollama), and automatically extracts content, generates summaries, builds vector databases, and supports multi-turn intelligent conversations.

---

## Key Features | Core Capabilities

### 🤖 Multi-Agent Architecture | Multi-Agent System
- **IndexingAgent**: Document indexing agent for PDF parsing, structure extraction, chunking, vectorization
- **AnswerAgent**: Q&A agent for intent analysis, answer generation, dialogue management
- **RetrievalAgent**: Retrieval agent for semantic search and context assembly
- **LangGraph Orchestration**: State machine workflow based on LangGraph, supports complex task orchestration

### 📄 Document Processing | Document Processing
- **Smart Indexing**: PDF to image + OCR content extraction
- **Structure Analysis**: Auto-detect document structure and chapter organization
- **Chunking**: Intelligent text splitting with chapter-level organization
- **Vector Database**: Efficient semantic search based on FAISS
- **Parallel Processing**: Async parallel chapter processing, significantly improved speed
- **Incremental Caching**: Stage-wise caching to avoid reprocessing

### 💬 Intelligent Q&A | Intelligent Q&A
- **Intent Recognition**: Auto-determine if document retrieval is needed
- **Context Management**: Smart caching of retrieval results for multi-turn dialogue
- **History Compression**: LLM auto-summarizes conversation history, saves context space (90%+ compression rate)
- **Document Summary**: Auto-generate brief summaries (brief_summary.md)
- **Multi-document Support**: Switch between multiple indexed documents

### 🌐 Modern Web Interface | Modern Web Interface
- **FastAPI + WebSocket**: Real-time chat communication
- **Session Persistence**: Auto-save, backup rotation (keeps latest 10), import/export
- **Dual Storage Architecture**: Client localStorage + server file storage
- **PDF Viewer**: Integrated online PDF preview with page navigation
- **Data Management System**: Granular data management with partial deletion, batch operations, smart cleanup
- **Responsive Design**: Mobile-friendly adaptive interface

---

## Quick Start | Quick Start

### Requirements | Requirements
- Python 3.12+
- Virtual environment (recommended)

<details>
<summary><b>📦 Installation & Configuration (Click to expand)</b></summary>

### Installation Steps

```bash
# 1. Clone repository
git clone <repository-url>
cd AgenticReader

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Create data directories
mkdir -p data/pdf data/pdf_image data/json_data data/vector_db data/output data/sessions data/sessions/backups data/sessions/exports

# 4. Configure environment variables (create .env file)
# See "Configuration" section below
```

### Configuration

Create a `.env` file in the project root:

```bash
# === LLM Service Configuration ===
# Azure OpenAI
CHAT_API_KEY=your_azure_api_key
CHAT_AZURE_ENDPOINT=https://your-endpoint.openai.azure.com/
CHAT_DEPLOYMENT_NAME=your_deployment_name
CHAT_API_VERSION=2024-02-15-preview
CHAT_MODEL_NAME=gpt-4

# Embedding Configuration
EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_MODEL=text-embedding-ada-002

# === Or use OpenAI ===
# CHAT_API_KEY=your_openai_api_key
# CHAT_MODEL_NAME=gpt-4
# OPENAI_BASE_URL=https://api.openai.com/v1/

# === Or use Ollama (Local) ===
# OLLAMA_BASE_URL=http://localhost:11434
# CHAT_MODEL_NAME=llama3

# === Optional Configuration ===
LOGGING_LEVEL=INFO
```

</details>

### Running the Application | Running the Application

#### Method 1: Web Interface (Recommended)
```bash
# Start FastAPI server
python src/ui/run_server.py

# Or use uvicorn (supports auto-reload)
uvicorn src.ui.backend.app:app --reload --host 0.0.0.0 --port 8000

# Access Web Interface
# http://localhost:8000
```

**Web Interface Features:**
- 📄 **PDF Processing**: Upload PDF → Auto-index → Start chat
- 💬 **Smart Dialogue**: Multi-turn Q&A, history management, session switching
- 📊 **Data Management**: View storage usage, delete document data, smart cleanup
- ⚙️ **Configuration Management**: Switch LLM providers, adjust parameters

#### Method 2: CLI Mode
```bash
# Interactive command-line interface
python main.py

# Workflow:
# 1. Select or index document
# 2. Start conversation
# 3. Enter questions, AI auto-retrieves and answers
```

---

<details>
<summary><b>📁 Project Structure (Click to expand)</b></summary>

```
AgenticReader/
├── main.py                        # CLI entry (uses AnswerAgent)
├── src/
│   ├── agents/                    # 🤖 Multi-Agent System
│   │   ├── indexing/              # IndexingAgent - Document indexing
│   │   │   ├── agent.py           # Indexing agent implementation
│   │   │   ├── state.py           # Indexing state definition
│   │   │   └── doc_registry.py    # Document registry
│   │   ├── answer/                # AnswerAgent - Intelligent Q&A
│   │   │   ├── agent.py           # Answer agent implementation
│   │   │   └── state.py           # Answer state definition
│   │   └── retrieval/             # RetrievalAgent - Document retrieval
│   │       ├── agent.py           # Retrieval agent implementation
│   │       └── state.py           # Retrieval state definition
│   ├── core/                      # Core functionality
│   │   ├── llm/                   # LLM abstraction layer
│   │   │   ├── client.py          # Unified LLM client
│   │   │   ├── providers.py       # Multi-provider support
│   │   │   └── history.py         # Conversation history management
│   │   ├── vector_db/             # Vector database
│   │   │   └── vector_db_client.py
│   │   └── processing/            # Document processing tools
│   │       ├── index_document.py  # Document indexing entry
│   │       ├── manage_documents.py # Document management tools
│   │       ├── parallel_processor.py # Parallel processor
│   │       └── text_splitter.py   # Text splitter
│   ├── config/                    # Configuration management
│   │   ├── settings.py            # Global configuration
│   │   ├── prompts/               # Prompt templates
│   │   └── tools/                 # Agent tool definitions
│   ├── services/                  # External services
│   │   └── mcp_client.py          # MCP client (retained)
│   ├── ui/                        # Web Interface
│   │   ├── run_server.py          # FastAPI startup script
│   │   ├── backend/               # Backend API
│   │   │   ├── app.py             # FastAPI application
│   │   │   ├── api/v1/            # API endpoints
│   │   │   │   ├── pdf.py         # PDF processing (uses IndexingAgent)
│   │   │   │   ├── chapters.py    # Chapter viewing
│   │   │   │   ├── chat.py        # WebSocket chat
│   │   │   │   └── data.py        # Data management
│   │   │   └── services/          # Service layer
│   │   │       ├── chat_service.py # Chat service (uses AnswerAgent)
│   │   │       ├── session_service.py # Session management
│   │   │       └── data_service.py    # Data management
│   │   ├── templates/             # Jinja2 templates
│   │   └── static/                # Static resources
│   └── utils/                     # Utility functions
├── data/                          # Data directory
│   ├── pdf/                       # PDF source files
│   ├── pdf_image/                 # PDF to images
│   ├── json_data/                 # Document data (organized by doc name)
│   │   └── {doc_name}/            # Document data folder
│   │       ├── data.json          # Raw extracted data
│   │       ├── structure.json     # Document structure
│   │       └── chunks.json        # Chunked data
│   ├── vector_db/                 # Vector database
│   ├── output/                    # Generated summary files
│   ├── sessions/                  # Session data
│   │   ├── backups/               # Session backups
│   │   └── exports/               # Session exports
│   └── doc_registry.json          # Document registry
└── requirements.txt               # Python dependencies
```

</details>

---

<details>
<summary><b>🏗️ Technical Architecture (Click to expand)</b></summary>

### Core Components

1. **Multi-Agent System** (src/agents/)
   - **IndexingAgent**: Document indexing workflow
     - Parse PDF → Extract structure → Chunk → Parallel process → Vectorize → Register
   - **AnswerAgent**: Intelligent Q&A workflow
     - Analyze intent → Retrieval decision → Generate answer → Evaluate result
   - **RetrievalAgent**: Document retrieval workflow
     - Semantic search → Context assembly → Result ranking

2. **LLM Abstraction** (src/core/llm/)
   - Unified interface supporting multiple providers (Azure OpenAI, OpenAI, Ollama)
   - Role-based prompt management
   - Session context auto-handling
   - Intelligent conversation history compression

3. **Vector Database** (src/core/vector_db/)
   - FAISS vector storage
   - Semantic similarity search
   - Chapter metadata management
   - Auto-load existing indexes

4. **Document Registry** (src/agents/indexing/doc_registry.py)
   - Centralized document metadata management
   - Track processing stage status
   - Record generated file paths
   - Support incremental indexing

5. **Web UI** (src/ui/)
   - FastAPI + WebSocket real-time communication
   - AnswerAgent-based chat service
   - IndexingAgent-based document processing
   - Data management system (granular control)

### Agent Workflows

#### IndexingAgent Workflow
```
PDF File
  → check_cache (Check stage-wise caching)
  → parse_document (Parse PDF)
  → extract_structure (Extract document structure)
  → chunk_text (Text chunking)
  → process_chapters (Parallel process chapters)
  → build_index (Build vector database)
  → generate_brief_summary (Generate summary)
  → register_document (Register to DocumentRegistry)
```

#### AnswerAgent Workflow
```
User Query
  → analyze_intent (Intent analysis)
  → retrieve_if_needed (Conditional retrieval)
  → generate_answer (Generate answer)
  → evaluate_result (Evaluate completeness)
  → Return to user
```

### Data Storage Architecture

**JSON Data** (organized by document):
```
data/json_data/{doc_name}/
├── data.json           # Raw extracted data
├── structure.json      # Document structure info
└── chunks.json         # Chunked data
```

**Advantages**:
- 📁 All JSON files centralized in document folder
- 🗑️ Direct folder deletion when removing, no file omissions
- 🔍 Easy to find and manage specific document data

</details>

---

<details>
<summary><b>🛠️ Development Guide (Click to expand)</b></summary>

### Adding New LLM Providers
1. Add provider implementation in `src/core/llm/providers.py`
2. Add configuration in `LLM_CONFIG` in `src/config/settings.py`
3. Update provider switching logic

### Adding New Agents
1. Create new agent directory under `src/agents/`
2. Create `agent.py` (inherit AgentBase) and `state.py` (define TypedDict)
3. Implement `build_graph()` method to define workflow
4. Integrate calls in other Agents

### Extending IndexingAgent
1. Add new processing nodes in `agent.py`
2. Connect new nodes in `build_graph()`
3. Update `IndexingState` to add new fields
4. Implement cache checking logic

### Extending Web API
1. Create new route file in `src/ui/backend/api/v1/`
2. Use Agents instead of directly calling processing logic
3. Register route in `src/ui/backend/app.py`
4. Follow RESTful conventions and FastAPI best practices

### Extending Data Management Features
1. Add new data types in `DataService.delete_document_data()`
2. Update `data_type_paths` dictionary mapping
3. Add corresponding endpoints in API
4. Display new types in frontend `renderDataDetail()`

### Debugging Tips
```bash
# Enable DEBUG logging
export LOGGING_LEVEL=DEBUG
python main.py

# FastAPI development mode (auto-reload)
uvicorn src.ui.backend.app:app --reload --host 0.0.0.0 --port 8000

# View API documentation
# http://localhost:8000/docs

# Test Agents
python -c "from src.agents.indexing import IndexingAgent; print('OK')"
python -c "from src.agents.answer import AnswerAgent; print('OK')"
```

</details>

---

<details>
<summary><b>❓ FAQ (Click to expand)</b></summary>

### 1. PDF file not recognized?
- Ensure file is placed in `data/pdf/` directory
- Check filename spelling is correct
- Supported format: `.pdf`

### 2. Indexing failed?
- Check LLM API configuration is correct
- Confirm network connection is normal
- View log output to locate errors
- Try using `LOGGING_LEVEL=DEBUG` for detailed info

### 3. How to manage conversation history?
- Automatically managed by `LLMBase.message_histories`
- LLM auto-summarizes history to save context
- Web interface supports viewing and clearing history

### 4. How to view indexed documents?
```bash
# CLI mode
python main.py
# Select 'm' to enter document management

# Web mode
Visit http://localhost:8000/data
```

### 5. How to delete documents?
```bash
# CLI mode
python -m src.core.processing.manage_documents

# Web mode
Visit http://localhost:8000/data
# Use granular deletion features
```

### 6. Session data lost, how to recover?
- Visit `data/sessions/backups/` directory
- Use web interface import function to restore backups
- Backup files named by timestamp, keeps max 10

### 7. How to switch LLM providers?
```bash
# Modify .env file
CHAT_API_KEY=your_api_key
CHAT_MODEL_NAME=your_model

# Or switch in web interface configuration page
```

### 8. How to clean old data to free space?
- Visit `http://localhost:8000/data` to enter data management interface
- Use "Smart Cleanup" to auto-clean data older than 30 days
- Or manually select documents and delete specific data types (e.g., delete images only)

### 9. How to recover accidentally deleted data?
- Session data can be recovered from `data/sessions/backups/`
- Document data recommended to use "Data Backup" feature regularly
- Backup files saved in `data/backups/` directory

### 10. IndexingAgent vs Old Reader?
- ✅ **IndexingAgent** (New): LangGraph-based state machine workflow, supports caching, incremental processing, stage tracking
- ❌ **PDFReader/WebReader** (Removed): Old class inheritance architecture, completely removed

</details>

---

<details>
<summary><b>📝 Changelog (Click to expand)</b></summary>

### 2026-01-17 - Major Architecture Refactor: Migration to Multi-Agent System
- 🏗️ **Architecture Refactor**
  - ✅ Completely removed old Reader architecture (PDFReader, WebReader, ReaderBase)
  - ✅ All functionality migrated to Multi-Agent architecture (IndexingAgent, AnswerAgent, RetrievalAgent)
  - ✅ LangGraph-based state machine workflow orchestration
  - ✅ UI backend migrated to use Agents (chat_service.py uses AnswerAgent, pdf.py uses IndexingAgent)
  - ✅ Deleted `src/readers/` directory, parallel_processor moved to `src/core/processing/`
  - ✅ Simplified chapters.py, temporarily removed chapter editing features
- 📁 **Data Storage Optimization**
  - ✅ JSON files organized by document: `data/json_data/{doc_name}/data.json`
  - ✅ Unified management of all JSON files for documents (data.json, structure.json, chunks.json)
  - ✅ Direct folder deletion when removing documents, no file omissions
- 🔄 **State Management Enhancement**
  - ✅ IndexingState added `is_complete` field to track completion status
  - ✅ DocumentRegistry auto-creates temporary records to track processing progress
  - ✅ Stage-wise cache checking to avoid reprocessing
- 🗑️ **Code Cleanup**
  - ❌ Deleted Web-related API and backend code (temporarily, to be redesigned)
  - ❌ Deleted ~1500+ lines of old Reader code
  - ✅ Retained MCP client (as requested)
  - ✅ Cleaner codebase, easier to maintain

### 2025-11-26 - Parallel Processing Optimization and Chapter Management UI
- ⚡ **Parallel Processing Optimization**
  - Added `src/utils/async_utils.py` - Generic async parallel processing utilities
  - Added `src/core/processing/parallel_processor.py` - Specialized parallel processor
  - Chapter summary and content refactoring now execute in parallel, 3-5x speed improvement
  - Detail summary generation parallelized with semaphore-controlled concurrency
- 📁 **Independent Chapter Management Interface**
  - New `/chapters` page - Parallel to config and data management
  - Integrated PDF preview with left chapter list + right PDF display
  - Support chapter edit, add, delete operations
  - Support batch rebuild of vector database and summaries
  - Processing progress indicators and chapter highlighting
- 🛠️ **Code Refactoring**
  - Extracted parallel processing logic into independent modules for better reusability

### 2025-11-19 - Data Management System
- ✨ **New Data Management Interface**
  - Real-time storage overview dashboard (document count, storage size, session stats)
  - Document detail display (JSON, Vector DB, Images, Summary shown independently)
  - **Granular partial deletion** - Delete specific data types for individual documents
  - Batch operations support - Select multiple documents for deletion
  - Cache management - View and clear PDF images, vector DB, JSON cache
  - Smart cleanup - Auto-delete data older than N days
  - Data backup functionality - Create session, output, config backups
  - Session statistics - Total sessions, messages, last activity, backup count

### 2025-10-31 - Session System Enhancement
- 🔄 **Session Persistence Optimization**
  - Dual storage architecture: Client localStorage + server file storage
  - Auto-backup rotation mechanism (keeps latest 10 backups)
  - Session import/export functionality
  - Storage location migration: `chat_sessions.json` → `sessions/backups/chat_sessions_current.json`
- 🛠️ **Backend Optimization**
  - SessionManager refactor with backup management support
  - Session format compatibility handling (supports dict and list formats)
  - Auto-migration of old session files

### 2025-09-15 - FastAPI Web Interface
- 🌐 **New Web Interface**
  - FastAPI + WebSocket real-time chat
  - Jinja2 templates + Vanilla JavaScript
  - Integrated online PDF preview
  - Responsive design, mobile-friendly

### 2025-08-20 - History Compression Optimization
- 🧠 **Intelligent History Management**
  - LLM auto-summarizes conversation history
  - 90%+ compression rate, significantly saves tokens
  - Maintains context coherence

### 2025-07-30 - Web Reader
- Added Web Reader functionality
- MCP service integration

</details>

---

## License | License

[MIT License](LICENSE)

## Contributing | Contributing

Welcome to submit Issues and Pull Requests!

## Acknowledgements | Acknowledgments

- [LangChain](https://github.com/langchain-ai/langchain) - Powerful LLM application development framework
- [LangGraph](https://github.com/langchain-ai/langgraph) - Multi-agent orchestration framework
- [FAISS](https://github.com/facebookresearch/faiss) - Efficient vector retrieval library
- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework
