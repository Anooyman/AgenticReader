# AgenticReader

[中文](README.md) | English

AgenticReader is an advanced document analysis and intelligent Q&A tool powered by large language models (LLM) and Multi-Agent architecture. Built on Agent orchestration patterns, focused on **deep PDF document parsing**, integrates multiple LLM providers (Azure OpenAI, OpenAI, Ollama, Gemini), and automatically extracts content, generates summaries, builds vector databases, and supports multi-turn intelligent conversations. Offers both **CLI command-line** and **Web interface** modes.

---

## Key Features | Core Capabilities

### 🤖 Multi-Agent Architecture | Multi-Agent System
- **IndexingAgent**: Document indexing agent for PDF parsing, structure extraction, chunking, vectorization
- **AnswerAgent**: Q&A agent for intent analysis, answer generation, dialogue management, tool invocation
- **RetrievalAgent**: Retrieval agent for semantic search and context assembly
- **SearchAgent**: Web search agent for search engine retrieval and URL content analysis
- **LangGraph Orchestration**: State machine workflow based on LangGraph, supports complex task orchestration

### 📄 Document Processing | Document Processing
- **Smart Indexing**: PDF to image + OCR content extraction
- **Structure Analysis**: Auto-detect document structure and chapter organization
- **Chunking**: Intelligent text splitting with chapter-level organization
- **Vector Database**: Efficient semantic search based on FAISS
- **Parallel Processing**: Async parallel chapter processing, significantly improved speed
- **Incremental Caching**: Stage-wise caching to avoid reprocessing

### 💬 Intelligent Q&A | Intelligent Q&A
- **Four Dialogue Modes**:
  - Single Document Mode - Deep Q&A for specific documents
  - Cross-Document Intelligent Mode - Auto-select relevant documents for retrieval
  - Cross-Document Manual Mode - Manually specify multiple documents as background knowledge
  - General Mode - Free conversation without binding to specific documents
- **Smart Tool System**:
  - 📎 Document Retrieval Tool (retrieve_documents) - Retrieve relevant content from indexed documents
  - 🌐 Web Search Tool (search_web) - Search the internet for latest information or analyze specified URLs
  - Users can enable/disable tools via UI buttons
  - Support tool combination (document retrieval + web search simultaneously)
- **Intent Recognition**: Auto-determine if document retrieval is needed
- **Context Management**: Smart caching of retrieval results for multi-turn dialogue
- **History Compression**: LLM auto-summarizes conversation history, saves context space (90%+ compression rate)
- **Document Summary**: Auto-generate brief summaries (brief_summary.md)

### 🌐 Dual Operation Modes | Dual Operation Modes
- **CLI Command-line Mode**:
  - Interactive menu system supporting document indexing, management, and dialogue
  - Free switching between four dialogue modes
  - Real-time view of document selection and retrieval process
  - Suitable for technical users and automation scenarios
- **Web Interface Mode**:
  - **Dashboard**: Document overview, quick indexing, mode selection
  - **Smart Chat**: WebSocket real-time communication, supports Markdown/LaTeX rendering
  - **Real-time Progress Visualization**:
    - 📊 **Node Flow Diagram**: Visual representation of Agent execution flow (Rewrite→Think→Act→Evaluate→Format)
    - 🔄 **Iteration Progress**: Real-time display of retrieval iteration count and percentage
    - 🛠️ **Tool Invocation**: Show current retrieval tools and detailed information
    - 🎨 **Modern Design**: Gradient backgrounds, smooth animations, micro-interactions
  - **Parallel Retrieval Visualization**:
    - 📚 **Multi-document Concurrency**: Display all document retrieval progress simultaneously in cross-doc mode
    - 🔽 **Collapse/Expand**: Independent progress cards for each document, collapsible for detailed flow
    - ⚡ **Incremental Updates**: Flicker-free real-time updates without interrupting user viewing
    - 🎯 **Independent Flow**: Each PDF has its own node flow visualization
  - **Session Management**: Three modes with independent session storage, support import/export
  - **Data Management**: Granular data control with partial deletion, batch operations, smart cleanup
  - **Configuration Center**: LLM provider switching, parameter adjustment
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

# === Or use Gemini (Google) ===
# GEMINI_API_KEY=your_gemini_api_key
# GEMINI_MODEL_NAME=gemini-1.5-pro
# GEMINI_EMBEDDING_MODEL=text-embedding-004
# GEMINI_BASE_URL=your_gemini_api_endpoint

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

# Access: http://localhost:8000
```

**📊 Dashboard (/) - Main Menu**
- Document list and overview
- Quick indexing (batch/single)
- Mode selection (Single/Cross/Manual)
- Quick access to chat page

**💬 Chat Page (/chat) - Intelligent Dialogue**

Three chat modes:
- **Single Mode**: Select specific document for deep Q&A
- **Cross Mode**: Auto-select relevant documents (intelligent decision)
- **Manual Mode**: Manually specify multiple documents as background

Features:
- WebSocket real-time communication
- Markdown and LaTeX formula rendering
- Timestamp display (year/month/day hour:minute:second)
- **Smart Scrolling & Navigation**:
  - 🎯 Smart Scroll: Auto-scroll only when user is at bottom, never interrupts history browsing
  - ⬆⬇ Quick Navigation Buttons: Jump to earliest message or latest reply
  - 💡 New Content Notification: Animated alerts with unread badge when viewing history
  - 📍 Precise Positioning: "View Latest" jumps to top of latest assistant reply (not bottom)
- Session persistence (three modes independently managed)
- Clear history (clears both file and memory)
- Display selected documents and similarity scores

**📁 Data Management (/data) - Documents & Sessions**

Document Management:
- View all indexed documents and storage usage
- **Granular partial deletion**: Delete specific data types for individual documents
  - JSON data, Vector DB, Images, Summary
- Batch operations: Select multiple documents for deletion
- Smart cleanup: Auto-clean data older than N days (default 30)

Session Management:
- View all mode sessions (Single/Cross/Manual)
- Session detail view (Markdown/LaTeX rendering support)
- Delete specific sessions
- Import/export session data

**⚙️ Configuration Center (/config) - LLM Settings**
- Switch LLM providers (Azure OpenAI, OpenAI, Ollama, Gemini)
- Adjust model parameters
- API Key management

**🔧 Structure Editor (/structure) - Document Structure**
- View and edit document chapter structure
- PDF online preview
- Rebuild vector database

---

#### Method 2: CLI Command-line Mode

```bash
# Start interactive CLI
python main.py
```

**Four Dialogue Modes:**

1. **Single Mode** - Select specific document
   ```
   [Single (doc.pdf)] 👤 Query: What is this document about?
   🤖 Assistant: This document discusses...
   ```

2. **Cross Mode** - Auto-select relevant documents
   ```
   [Cross Mode] 👤 Query: Compare the viewpoints
   📚 Selected Documents (2):
      - doc1.pdf (similarity: 0.856)
      - doc2.pdf (similarity: 0.742)
   🤖 Assistant: Based on retrieval...
   ```

3. **Manual Mode** - Manually select multiple documents
   ```
   Select documents: 1,2 (or 'all')
   [Manual (2 docs)] 👤 Query: Summarize both
   🤖 Assistant: Comprehensive summary...
   ```

4. **General Mode** - Free conversation
   ```
   [General Mode] 👤 Query: What is machine learning?
   🤖 Assistant: Machine learning is...
   ```

**Commands:**
- `i` - Index new document
- `m` - Manage documents (view/delete)
- `clear` - Clear conversation history
- `switch` - Switch mode
- `main` - Return to main menu
- `quit`/`exit` - Exit program

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
│   │   │   ├── tools.py           # Answer tools
│   │   │   ├── tools_config.py    # Tool configuration
│   │   │   └── state.py           # Answer state definition
│   │   ├── retrieval/             # RetrievalAgent - Document retrieval
│   │   │   ├── agent.py           # Retrieval agent implementation
│   │   │   └── state.py           # Retrieval state definition
│   │   └── search/                # SearchAgent - Web search agent
│   │       ├── agent.py           # Search agent implementation
│   │       ├── tools.py           # Search and scraping tools
│   │       ├── utils.py           # MCP client and utilities
│   │       ├── README.md          # SearchAgent documentation
│   │       └── state.py           # Search state definition
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
   - **AnswerAgent**: Intelligent Q&A workflow (ReAct Architecture)
     - Tool planning (plan) → Tool execution (execute) → Result evaluation (evaluate) → Answer generation (generate)
     - Supported tools: Document retrieval (retrieve_documents), Web search (search_web)
   - **RetrievalAgent**: Document retrieval workflow
     - Semantic search → Context assembly → Result ranking
   - **SearchAgent**: Web search workflow
     - Search engine retrieval (search) → URL selection → Content scraping → Info extraction → Answer generation
     - URL content analysis (url_analysis) → Content scraping → Size evaluation → Direct chat/Indexing processing

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

#### AnswerAgent Workflow (ReAct Loop)
```
User Query + enabled_tools
  → plan (Tool planning - Construct calls based on user-enabled tools)
  → execute_tools (Execute tool calls in parallel)
      ├─ retrieve_documents (Document retrieval)
      └─ search_web (Web search)
  → evaluate (Evaluate if sufficient information)
  → generate_answer (Generate final answer)
  → Return to user
```

#### SearchAgent Workflow
```
Search Mode (search):
  Query → web_search (Search engine) → select_urls (Select relevant URLs)
      → scrape_content (Scrape content) → extract_info (Extract info)
      → format_answer (Generate answer)

URL Analysis Mode (url_analysis):
  URL list → scrape_content (Scrape content) → evaluate_size (Evaluate content size)
      ├─ Small content → direct_chat (Direct chat)
      └─ Large content → index_then_chat (Index then chat)
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

### 1. What file formats are supported?
- ✅ **PDF files**: Fully supported, auto-extract text, images, structure
- ❌ **URL/Web pages**: Temporarily not supported (Web Reader feature removed)
- ❌ **Word/PPT**: Not supported yet (planned)

### 2. What's the difference between the four dialogue modes?
- **Single (Single Document)**: Deep Q&A for specific document, all retrieval limited to selected document
- **Cross (Cross-Document Intelligent)**: System auto-selects relevant documents for retrieval and synthesis
- **Manual (Cross-Document Manual Selection)**: Manually specify multiple documents as background knowledge
- **General (General Conversation)**: Free conversation without binding to specific documents

**Recommended scenarios:**
- Learning specific document content → Single mode
- Exploratory research, uncertain which document to use → Cross mode
- Clearly need to compare multiple documents → Manual mode
- General questions, chitchat → General mode

### 3. How to index new documents?
**CLI Mode:**
```bash
python main.py
# Select 'i' - Index new document
# Choose file from data/pdf/ directory
# Wait for indexing (auto parse, chunk, vectorize)
```

**Web Mode:**
```
Visit http://localhost:8000/
Click "Batch Index" or "Single Index"
Upload PDF file
Wait for background processing
```

### 4. How to view and manage indexed documents?
**CLI Mode:**
```bash
python main.py
# Select 'm' - Manage documents
# View document list and storage usage
# Can delete specific documents
```

**Web Mode:**
```
Visit http://localhost:8000/data
View all documents and data types
Use granular deletion (delete only specific data types)
Or batch delete multiple documents
```

### 5. What is "granular deletion"?
**Traditional deletion**: Deletes all related data when deleting document

**Granular deletion**: Selectively delete specific data types, for example:
- Delete Images only → Free up most space
- Delete Vector DB only → Use when rebuilding index
- Delete Summary only → Use when regenerating summary
- Keep JSON data → Avoid re-parsing PDF

**Usage scenarios:**
- Insufficient space but want to keep document → Delete Images
- Index corrupted, need rebuild → Delete Vector DB
- Optimize index parameters → Delete Vector DB and Chunks, keep JSON

### 6. How to manage conversation history?
**Automatic management:**
- LLM auto-summarizes conversation history (90%+ compression)
- Maintains context coherence while saving tokens

**Manual clearing:**
- **CLI**: Enter `clear` command
- **Web**: Click "Clear History" button
- Clear operation clears both file and memory, and re-instantiates Agent

**Session persistence:**
- All conversations auto-saved to `data/sessions/{mode}/` directory
- Three modes stored independently: single, cross, manual
- Single mode: One session file per document (doc_name.json)
- Cross/Manual mode: One file per session (session_id.json)

### 7. How to switch LLM providers?
**Method 1: Modify .env file**
```bash
# Azure OpenAI
CHAT_API_KEY=your_azure_key
CHAT_AZURE_ENDPOINT=https://your-endpoint.openai.azure.com/
CHAT_DEPLOYMENT_NAME=gpt-4
CHAT_API_VERSION=2024-02-15-preview

# OpenAI
CHAT_API_KEY=your_openai_key
CHAT_MODEL_NAME=gpt-4
OPENAI_BASE_URL=https://api.openai.com/v1/

# Ollama (Local)
OLLAMA_BASE_URL=http://localhost:11434
CHAT_MODEL_NAME=llama3

# Gemini
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL_NAME=gemini-1.5-pro
```

**Method 2: Web Configuration Page**
```
Visit http://localhost:8000/config
Select LLM provider
Fill in API Key and configuration
Save and restart
```

### 8. How to clean old data to free space?
**Smart Cleanup (Recommended):**
```
Visit http://localhost:8000/data
Click "Smart Cleanup"
Set days (default 30 days)
System auto-cleans old data
```

**Manual Cleanup:**
- Select specific document → Granular deletion (delete only Images/Vector DB)
- Batch select → Delete multiple documents at once
- Cache management → Clear PDF image cache, JSON cache

**Most space-consuming data types:**
1. Images (PDF pictures) - Usually 60-70% of space
2. Vector DB (Vector index) - Usually 20-30% of space
3. JSON data - Usually 5-10% of space
4. Summary - Usually 1-2% of space

### 9. Why was Web Reader feature removed?
- Focus on deep PDF document parsing and Q&A
- Web content structure is complex with varying quality
- Planning to redesign better web content processing in the future

</details>

---

<details>
<summary><b>📝 Changelog (Click to expand)</b></summary>

### 2026-02-24 - Session Management UI Optimization & SearchAgent Fixes
- 🎨 **Session Management Modal Integration**
  - ✅ Added session management modal on homepage (no page navigation required)
  - ✅ Session statistics dashboard (total, single-doc, multi-doc, pure chat)
  - ✅ Real-time search and filter sessions
  - ✅ Batch delete functionality (parallel processing)
  - ✅ Session detail panel (slides in from right, full conversation history)
  - ✅ URL hash support (`/#sessions` auto-opens modal)
  - ✅ Keyboard shortcuts (ESC to close, click outside to close)
- 📊 **Enhanced Session Card Information**
  - ✅ Display session mode badges (🎯Single/🔀Cross/✋Manual)
  - ✅ Display enabled tools (📚Document Retrieval/🌐Web Search)
  - ✅ Display invoked Agents (🔍Retrieval Agent/🌐Search Agent)
  - ✅ Enhanced time display (show both created and updated timestamps)
  - ✅ Unified card styles between homepage modal and data management page
- 🤖 **Agent Invocation Recording System**
  - ✅ Auto-record Agents used per message (RetrievalAgent, SearchAgent)
  - ✅ Session-level statistics of all Agents used
  - ✅ Display Agent usage in cards and detail panels
  - ✅ Yellow badges to distinguish Agent info (different from tool badges)
- 🐛 **SearchAgent Content Truncation Fix**
  - ✅ Fixed 2000-character hard limit issue in `format_answer` method
  - ✅ Changed to smart dynamic allocation strategy (max 100,000 characters total)
  - ✅ Single source no longer limited to 2000 characters, dynamically allocated based on total length
  - ✅ Support long-text URL content full save and analysis (e.g., lengthy news, reports)
  - ✅ Optimized logging to display merged content length

### 2026-02-14 - SearchAgent Integration into AnswerAgent
- 🌐 **Web Search Tool Launch**
  - ✅ Integrated SearchAgent into AnswerAgent's tool system
  - ✅ Enabled `search_web` tool in `tools_config.py`
  - ✅ Implemented `AnswerTools.search_web()` method, calling SearchAgent
  - ✅ Added `search_agent` instance to AnswerAgent (lazy initialization)
  - ✅ Support two search modes: search engine retrieval and URL content analysis
- 🔧 **Tool Invocation Architecture**
  - ✅ AnswerAgent adopts ReAct loop: plan → execute → evaluate → generate
  - ✅ Users enable/disable web search tool via UI button (🌐)
  - ✅ Support tool combination: document retrieval + web search simultaneously
  - ✅ Progress callback integration for real-time UI updates

### 2026-02-04 - Chat Interface UX Optimization
- 🎨 **Smart Scrolling System**
  - ✅ Progress updates auto-scroll only when user is at bottom, avoiding interruption of history browsing
  - ✅ Added `isNearBottom()` logic (100px threshold from bottom)
  - ✅ All scroll operations changed to smart scroll (`smartScrollToBottom()`)
- 🧭 **Quick Navigation Buttons**
  - ✅ Added "⬆ Earliest Message" button: Jump to conversation top
  - ✅ Added "⬇ View Latest Content" button: Jump to top of latest assistant reply (not bottom)
  - ✅ Buttons below input box, universal for three chat modes
  - ✅ Show only when user not at bottom, auto-hide/show
- 💬 **New Content Notification System**
  - ✅ Visual alerts when viewing history and new reply arrives
  - ✅ Dynamic button text: "View Latest Content" → "New Content, Click to View"
  - ✅ Pulse glow animation + arrow bounce animation + red unread count badge
  - ✅ Unread count auto-increments, resets when clicking button or scrolling back to bottom
- 🎭 **Visual & Interaction Optimization**
  - ✅ Two buttons with different gradient colors (purple vs blue-purple)
  - ✅ Smooth animation effects (slideDown, pulseButton, pulseBadge, bounceIcon)
  - ✅ Button hover float effect, click feedback animation
  - ✅ Removed duplicate scroll button in chat-enhancer.js to avoid conflicts

### 2026-01-29 - Batch Indexing and Session Management Enhancements
- 🐛 **Batch Indexing Fixes**
  - ✅ Fixed concurrent write race condition during batch PDF indexing
  - ✅ Enhanced DocumentRegistry concurrent safety (reload-before-save pattern)
  - ✅ Ensured all documents register correctly when indexing multiple PDFs simultaneously
  - ✅ Added `update_metadata()` method for safe metadata updates
- 💬 **Session Management Optimization**
  - ✅ Fixed chat history clearing (clears both file and memory)
  - ✅ Re-instantiate AnswerAgent and RetrievalAgent when clearing history
  - ✅ Fixed memory-file synchronization (update `current_session` to prevent stale data)
  - ✅ Fixed single-mode session detail loading (support session_id lookup)
- 🎨 **UI Enhancements**
  - ✅ Added timestamp display to all chat modes (format: year/month/day hour:minute:second)
  - ✅ Session detail modal supports Markdown and LaTeX rendering
  - ✅ Historical messages display original timestamps (not current time)
- 🔧 **Code Improvements**
  - ✅ Unified AnswerAgent initialization parameters (only uses `doc_name`)
  - ✅ Enhanced data consistency guarantees in concurrent environments

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
