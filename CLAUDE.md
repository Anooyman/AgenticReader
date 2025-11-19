# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgenticReader is an advanced document analysis and intelligent Q&A tool powered by large language models. It supports PDF and web content parsing with multiple LLM providers (Azure OpenAI, OpenAI, Ollama). The system automatically extracts content, generates summaries, builds vector databases, and supports multi-turn intelligent conversations with an intelligent memory system based on multi-agent architecture.

## Development Commands

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Create data directories (if they don't exist)
mkdir -p data/pdf data/pdf_image data/json_data data/vector_db data/output data/memory data/sessions data/sessions/backups data/sessions/exports data/config

# Check current git status and branch
git status
git branch

# Optional: Install MCP services (required for Web Reader and Memory features)
# Option 1: Use Playwright MCP (recommended)
# npx @playwright/mcp@latest

# Option 2: Use DuckDuckGo MCP
uv pip install duckduckgo-mcp-server

# Install Memory service
npm install -g rag-memory-mcp
```

### Running the Application

**CLI Mode:**
```bash
# Run main application (handles both PDF and URL inputs)
python main.py

# Test specific module
python src/chat/memory_agent.py  # Test memory agent
python src/chat/chat.py          # Test multi-agent system
```

**UI Mode (FastAPI + WebSocket):**
```bash
# Launch FastAPI web interface (recommended for development)
python src/ui/run_server.py

# Or use uvicorn directly with auto-reload
uvicorn src.ui.backend.app:app --reload --host 0.0.0.0 --port 8000

# Access at http://localhost:8000
# API Documentation: http://localhost:8000/docs
# Data Management: http://localhost:8000/data

# Features:
# - Modern FastAPI backend with WebSocket real-time communication
# - Jinja2 template-based frontend with vanilla JavaScript
# - Persistent session storage with dual storage architecture
# - PDF viewer integration with page navigation
# - Session management with import/export functionality
# - Automatic data backup and recovery system
# - Data management with granular deletion control
```

### Development and Testing
```bash
# Run with debug logging (set in your environment)
export LOGGING_LEVEL=DEBUG
python main.py

# Test specific reader components
python -c "from src.readers.pdf import PDFReader; reader = PDFReader(); print('PDF Reader initialized')"
python -c "from src.readers.web import WebReader; reader = WebReader(); print('Web Reader initialized')"

# Test LLM providers
python -c "from src.core.llm.client import LLMBase; client = LLMBase(provider='azure'); print('LLM client initialized')"
```

## High-Level Architecture

### Core Architecture Patterns

**1. Multi-Agent System (src/chat/)**
- **PlanAgent**: Top-level coordinator that analyzes queries, creates execution plans, and evaluates results
- **ExecutorAgent**: Mid-level executor that manages sub-agents and coordinates plan execution
- **MemoryAgent**: Specialized agent for intelligent memory management with semantic search
- Built on **LangGraph** framework with asynchronous state graph processing
- Uses typed state classes (PlanState, ExecutorState) and Command objects for control flow
- All agent communications are async using `astream()` pattern

**2. Reader-Based Processing (src/readers/)**
- **ReaderBase**: Abstract base class providing common functionality (content extraction, summarization, vector DB interaction)
- **PDFReader**: Handles PDF documents with image extraction and OCR capabilities
- **WebReader**: Processes web content via MCP services with automatic text chunking
- All readers support caching, vector database building, and automatic summary generation

**3. LLM Abstraction Layer (src/core/llm/)**
- **LLMBase**: Unified interface supporting multiple providers (Azure OpenAI, OpenAI, Ollama)
- Role-based prompt management with specialized prompts for different tasks (image extraction, summarization, Q&A)
- Session-based conversation management with automatic context handling

**4. Vector Database Integration (src/core/vector_db/)**
- FAISS-based vector storage with automatic indexing
- Semantic similarity search for content retrieval
- Chapter-based organization with metadata preservation
- Auto-loading of existing vector databases on initialization (vector_db_client.py:23-30)

**5. UI System (src/ui/)**
- **FastAPI Backend (backend/app.py)**: Modern async web framework with WebSocket support for real-time chat
  - Modular API structure: `/api/v1/` endpoints for sessions, config, PDF, chat, web, and data management
  - Health check endpoint: `/health` for monitoring
  - Auto-generated OpenAPI documentation at `/docs` and `/redoc`
- **SessionManager (backend/services/session_service.py)**: Comprehensive session persistence with JSON file storage, backup creation, and import/export
- **DataService (backend/services/data_service.py)**: Granular data management with support for partial deletion of document components
- **Dual Storage Architecture**: Client-side localStorage + server-side file storage for data redundancy
- **Jinja2 Templates**: Server-side rendering with template inheritance and component modularity
- **Vanilla JavaScript Frontend**: ES6 class-based architecture with session management and real-time updates
- **PDF Viewer Integration**: Client-side PDF display with page navigation and image fallback support
- **Data Management UI**: Comprehensive interface for viewing and managing all document data with granular control

### Data Flow Architecture

1. **Input Processing**: PDF/URL → Content Extraction → Text Chunking
2. **Content Analysis**: Basic Info Extraction → Chapter Structure Detection → Content Summarization
3. **Vector Storage**: Embedding Generation → Vector DB Building → Indexing
4. **Query Processing**: User Query → Relevant Chapter Retrieval → Context Assembly → LLM Response
5. **Memory System**: Multi-agent coordination → Intent recognition → Storage/Retrieval operations

### Multi-Agent Workflow

```
User Query → PlanAgent (analyze & plan) → ExecutorAgent (coordinate execution)
    ↓
Sub-Agents (MemoryAgent, etc.) → Results Collection → PlanAgent (evaluate)
    ↓
Final Answer Generation → Response to User
```

## Configuration Architecture

### Settings Structure (src/config/settings.py)
- **LLM_CONFIG**: Azure OpenAI, OpenAI, and Ollama configuration via environment variables
- **SYSTEM_PROMPT_CONFIG**: Role-based prompts for different processing stages
- **MCP_CONFIG**: External service configurations for web fetching and memory services
- **Data Paths**: Configurable storage locations for all generated content

### Key Environment Variables
**LLM Service Configuration:**
- `CHAT_API_KEY`, `CHAT_AZURE_ENDPOINT`, `CHAT_MODEL_NAME`: LLM service configuration
- `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`: Vector embedding service setup
- `CHAT_DEPLOYMENT_NAME`: Azure OpenAI deployment name
- `CHAT_API_VERSION`: Azure OpenAI API version

**Optional Configuration:**
- `LOGGING_LEVEL`: Set to `DEBUG` for detailed logging
- Environment variables can be set via `.env` file (loaded via python-dotenv)

**Provider Support:**
- OpenAI (default): Requires API key
- Azure OpenAI: Requires API key and endpoint
- Ollama: Requires local installation and running service

**Default Provider Note**:
- Code default is `openai` (see `src/readers/base.py:33` and `src/readers/pdf.py:37`)
- Can be changed by passing `provider` parameter: `PDFReader(provider="azure")`

## Key Data Structures

### Processing Pipeline State
- **raw_data_dict**: Original extracted content organized by chapters
- **agenda_dict**: Document structure with chapter titles and page numbers
- **total_summary**: Chapter-wise summaries for Q&A context
- **retrieval_data_dict**: Cached retrieval results for conversation continuity

### Multi-Agent State Management
- **PlanState**: Top-level state with question, plan, execution_results, and final_answer
- **ExecutorState**: Execution-level state with plan tracking and results collection
- **Memory Integration**: Semantic search with metadata organization (time, location, person, tags)

### UI Session Management
- **SessionManager State**: Comprehensive JSON file-based storage with backup rotation and import/export
- **AppState**: FastAPI application state with PDF/Web readers, chat history, and session tracking
- **Client-side Storage**: localStorage-based session persistence with automatic sync mechanisms
- **Dual Storage Architecture**: Backend file storage + frontend localStorage for redundancy and offline capability

## Content Processing Workflow

### Document Processing Stages
1. **Content Extraction**: PDF-to-image conversion → OCR → Raw text extraction
2. **Structure Analysis**: Basic info extraction → Chapter/agenda detection → Content chunking
3. **Intelligent Processing**: Chapter-wise summarization → Content refactoring → Vector embedding
4. **Storage & Export**: Vector DB building → Summary file generation (MD/PDF) → Cache management

### Memory System Integration
- **Intent Recognition**: Automatic classification of storage vs. retrieval requests
- **Multi-dimensional Tagging**: Time, location, person, tag-based metadata organization
- **Semantic Retrieval**: Vector-based content matching with knowledge graph enhancement
- **Asynchronous Processing**: Background execution with state management

### UI Data Flow
1. **Session Persistence**: Client localStorage → Server file storage → Backup rotation
2. **Document Processing**: File upload → Backend processing → Summary generation → PDF viewer
3. **Real-time Chat**: WebSocket connection → Message processing → LLM response → Auto-save trigger
4. **State Synchronization**: localStorage changes → Server API calls → File system updates
5. **Session Management**: Import/Export → Session switching → History restoration

## Special Implementation Notes

### Performance Optimizations
- **Caching Strategy**: Multi-level caching (images, JSON data, vector databases, summaries)
- **Async Processing**: All LLM calls and agent communications are asynchronous
- **Chunking Logic**: Intelligent text splitting with MAX_CHAPTER_LEN limits and sub-chapter detection
- **Resource Management**: Automatic directory creation and file existence checking

### Error Handling Patterns
- **Graceful Degradation**: Single agent failures don't crash the entire system
- **Retry Mechanisms**: Built-in retry logic for LLM calls and external services
- **State Recovery**: Exception handling maintains conversation state and partial results
- **Logging Strategy**: Comprehensive logging with different levels for debugging and monitoring

### MCP Service Integration
- **Web Content Fetching**: Two options available
  - Playwright MCP service (`npx @playwright/mcp@latest`) - Recommended
  - DuckDuckGo MCP service (`uv pip install duckduckgo-mcp-server`) - Alternative option
- **Memory Management**: RAG-memory-mcp service (`npx -y rag-memory-mcp`)
- **Configuration**: Toggle between services in `src/config/settings.py` under `MCP_CONFIG`
  - Playwright config is commented out by default
  - DuckDuckGo config is currently active (requires separate installation)
- **Note**: MCP services are optional but required for Web Reader and Memory Agent features
- Extensible service configuration for future integrations

### UI Features (FastAPI Interface)
- **Modern Web Architecture**: FastAPI backend + Jinja2 templates + vanilla JavaScript frontend
- **Real-time Communication**: WebSocket-based chat with immediate response streaming
- **Session Persistence**: Comprehensive session management with automatic saving and recovery
- **Dual Storage System**: Client localStorage + server file storage for data redundancy
- **PDF Integration**: Built-in PDF viewer with page navigation and image conversion fallback
- **Multi-session Support**: Session switching, import/export, and history management
- **Auto-save Mechanism**: LLM-response-triggered saving with backup rotation (keeps 10 most recent)
- **Data Directory Structure**:
  - `data/sessions/backups/chat_sessions_current.json` - Main session storage (refactored location)
  - `data/sessions/backups/` - Automatic backup rotation (keeps 10 most recent timestamped backups)
  - `data/sessions/exports/` - User-initiated exports
  - **Migration Note**: Old `chat_sessions.json` files are automatically migrated to new location on startup
- **Responsive Design**: Mobile-friendly interface with adaptive layouts
- **State Synchronization**: Automatic sync between client and server state

### Data Management System (NEW)
Access via: `http://localhost:8000/data`

**Granular Data Control:**
Each processed document generates multiple data types that can be managed independently:
- **JSON Data** - Parsed document content and metadata (`.json` files in `data/json_data/`)
- **Vector Database** - FAISS index files (directories in `data/vector_db/`)
- **PDF Images** - Converted image files (directories in `data/pdf_image/`)
- **Summary Files** - Generated summaries in MD/PDF format (files in `data/output/`)

**Features:**
- **Storage Overview Dashboard** - Real-time statistics on total documents, storage size, sessions, and last cleanup
- **Document List View** - Detailed breakdown showing size and status of each data type per document
- **Partial Deletion** - Delete specific data types (e.g., only images or only summaries) while preserving others
- **Batch Operations** - Select multiple documents for bulk deletion
- **Cache Management** - View and clear PDF image cache, vector DB cache, and JSON cache separately
- **Smart Cleanup** - Automatically delete data older than N days (default: 30)
- **Data Backup** - Create backups of sessions, output, and config
- **Session Statistics** - View total sessions, messages, last activity, and backup count

**API Endpoints:**
```
GET    /api/v1/data/overview                    - Storage overview stats
GET    /api/v1/data/documents                   - List all documents with detailed data breakdown
GET    /api/v1/data/cache/{type}                - Cache info (pdf_image, vector_db, json_data)
GET    /api/v1/data/sessions/stats              - Session statistics

DELETE /api/v1/data/documents/{name}/parts      - Delete specific data types (granular control)
       Body: ["json", "vector_db", "images", "summary", "all"]
DELETE /api/v1/data/documents                   - Batch delete entire documents
       Body: ["doc1", "doc2", ...]
DELETE /api/v1/data/cache/{type}                - Clear cache

POST   /api/v1/data/cleanup/smart?days=30       - Smart cleanup old data
POST   /api/v1/data/backup                      - Create data backup
POST   /api/v1/data/reset?confirm=CONFIRM_RESET - Full system reset
```

**Use Cases:**
- Delete large image files to free space while keeping JSON/summaries
- Clear vector DB to rebuild indexes
- Remove old summaries before regenerating
- Batch cleanup of multiple documents
- Regular maintenance with smart cleanup

## Development Patterns

### Adding New Agents
1. Create agent class inheriting from GraphBase
2. Implement build_graph() and core processing methods
3. Add agent configuration to AgentCard in settings.py
4. Update ExecutorAgent._create_agent() to handle the new agent type

### Extending Reader Functionality
1. Inherit from ReaderBase for common functionality
2. Implement provider-specific content extraction
3. Override get_data_from_json_dict() if needed for custom processing
4. Add to main.py routing logic

### LLM Provider Integration
1. Extend LLMBase with provider-specific client initialization
2. Add configuration section to LLM_CONFIG
3. Update provider switching logic in base classes

### UI Development Patterns

**Backend Development (FastAPI):**
1. Add new API endpoints following RESTful conventions in `src/ui/backend/app.py`
2. Extend SessionManager for new data persistence requirements
3. Use async/await patterns for all I/O operations and LLM calls
4. Follow WebSocket message type conventions: `user_message`, `assistant_message`, `status`, `error`

**Frontend Development (JavaScript):**
1. Extend AgenticReaderApp or AgenticReaderChatApp classes in respective JS files
2. Use localStorage keys prefixed with `AgenticReader_` for client-side persistence
3. Implement UUID generation for session/chat IDs using existing patterns
4. Follow dual-storage approach: always sync localStorage with server API calls

**Template Development (Jinja2):**
1. Extend base templates in `src/ui/templates/` with template inheritance
2. Use CSS custom properties (variables) for consistent theming
3. Follow BEM naming convention for CSS classes
4. Ensure responsive design with mobile-first approach

**Session Management Extensions:**
1. Add new session data fields to SessionManager.add_session()
2. Update backup/export logic to handle new data structures
3. Implement data migration for session format changes
4. Test import/export compatibility with existing session files

**MCP Service Configuration:**
1. Choose between Playwright or DuckDuckGo for web content fetching
2. Update `MCP_CONFIG` in `src/config/settings.py` to enable/disable services
3. Playwright: Uncomment the `playwright` section (lines 21-27 in settings.py)
4. DuckDuckGo: Ensure `duckduckgo-mcp-server` is installed via `uv pip install`
5. Test MCP connectivity before running Web Reader features

**Data Management Extensions:**
1. Add new data types to `DataService.delete_document_data()` in `src/ui/backend/services/data_service.py`
2. Update data type paths mapping in the `data_type_paths` dictionary
3. Add corresponding API endpoint in `src/ui/backend/api/v1/data.py`
4. Update frontend `renderDataDetail()` in `src/ui/static/js/data.js` to display new data type
5. Session format compatibility: Handle both dict and list formats for sessions (see `get_session_stats()`)
6. All deletion operations should log actions and return detailed results including freed space

## Input Processing Behavior

### CLI Mode (main.py)
```bash
python main.py
# Prompts for input with available PDF files listed
# - PDF files: Detects .pdf extension and uses PDFReader
# - URLs: Any non-PDF input is treated as URL and uses WebReader
# - Exit commands: "退出", "再见", "bye", "exit", "quit"
```

### Input Routing Logic
- **PDF Processing**: Input ending with `.pdf` → PDFReader with sync processing
- **URL Processing**: Any other input → WebReader with async processing (`asyncio.run()`)
- **File Detection**: Lists available PDF files from `data/pdf/` directory
- **Auto-save**: PDF processing includes `save_data_flag=True` by default

## Testing and Debugging

The codebase includes comprehensive logging with module-level loggers. Set `LOGGING_LEVEL=DEBUG` for detailed execution traces. Each major component (readers, agents, LLM clients) includes standalone testing capabilities that can be run independently.

**Standalone Testing:**
```bash
# Memory agent testing
python src/chat/memory_agent.py

# Multi-agent system testing
python src/chat/chat.py

# Individual reader testing (via import and initialization)
python -c "from src.readers.pdf import PDFReader; PDFReader()"
python -c "from src.readers.web import WebReader; WebReader()"

```

**UI Testing:**
```bash
# Test server with uvicorn launcher (recommended for quick testing)
python src/ui/run_server.py

# Development mode with auto-reload (recommended for active development)
uvicorn src.ui.backend.app:app --reload --host 0.0.0.0 --port 8000

# Access FastAPI automatic documentation
# Swagger UI: http://localhost:8000/docs
# ReDoc: http://localhost:8000/redoc

# Test WebSocket connections (requires browser dev tools or WebSocket client)
# Connect to: ws://localhost:8000/ws/chat

# Test session management APIs
curl http://localhost:8000/api/v1/config
curl http://localhost:8000/api/v1/sessions/list
curl http://localhost:8000/health
```

**UI Debugging:**
- **Browser DevTools**: Monitor WebSocket messages, localStorage state, and network requests
- **Server Logs**: FastAPI automatically logs requests and responses with timestamps
- **Session Files**: Inspect `data/sessions/backups/chat_sessions_current.json` for session state debugging
- **Backup Recovery**: Use backup files in `data/sessions/backups/` (timestamped files) for data recovery testing
- **Session Migration**: Check logs for automatic migration messages from old to new storage location

**MCP Service Testing:**
```bash
# Test Playwright MCP
npx @playwright/mcp@latest

# Test DuckDuckGo MCP (if installed)
# Note: Requires duckduckgo-mcp-server to be installed
uvx duckduckgo-mcp-server

# Test Memory service
npx -y rag-memory-mcp

# Verify MCP configuration in settings
grep -A 10 "MCP_CONFIG" src/config/settings.py
```

## Code Organization Principles

### Module Hierarchy
- **src/config/**: Configuration management (settings.py, constants.py, app_settings.py)
- **src/core/**: Core functionality (llm/, processing/, vector_db/)
- **src/readers/**: Document processing (base.py, pdf.py, web.py)
- **src/chat/**: Multi-agent system (chat.py, memory_agent.py)
- **src/services/**: External service integration (mcp_client.py)
- **src/utils/**: Utility functions (helpers.py, validators.py, error_handler.py)
- **src/ui/**: FastAPI web system (backend/, templates/, static/)

### Key Files to Understand
- **main.py**: CLI entry point with PDF/URL routing logic (lines 17-32)
- **src/readers/base.py**: ReaderBase class with common document processing
- **src/chat/chat.py**: Multi-agent system with PlanAgent/ExecutorAgent
- **src/config/settings.py**: Configuration hub with LLM_CONFIG, SYSTEM_PROMPT_CONFIG, MCP_CONFIG
- **src/ui/backend/app.py**: FastAPI application setup and routing

### State Management Pattern
The multi-agent system uses LangGraph's StateGraph with typed state classes:
- PlanState (PlanAgent level): question, plan, execution_results, is_complete, final_answer
- ExecutorState (ExecutorAgent level): plan, current_plan_index, results, formatted_inputs
- State flows through graph nodes with Command objects controlling routing

### Async Patterns
- All LLM calls are async: use `await` or `asyncio.run()` when calling from sync context
- Graph execution: `async for event in self.graph.astream(...)` pattern
- Reader main methods: PDFReader.main() is sync, WebReader.main() is async
