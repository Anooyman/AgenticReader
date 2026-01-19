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
# Health Check: http://localhost:8000/health

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

# Test agent components
python tests/test_indexing_agent.py     # Test IndexingAgent
python tests/test_answer_agent.py       # Test AnswerAgent
python tests/test_retrieval_agent.py    # Test RetrievalAgent

# Test LLM providers
python tests/test_llm_client.py         # Test LLM client
python tests/test_llm_providers.py      # Test provider implementations
```

## Architecture Overview

### Modular Agent-Centric Design

The codebase follows a **fully modularized, agent-centric architecture** where each agent is a self-contained module with all its configuration colocated:

```
src/agents/
├── common/           # Shared utilities across agents
│   └── prompts.py    # Common prompts (CommonRole)
├── indexing/         # Self-contained IndexingAgent
│   ├── prompts.py    # Indexing-specific prompts
│   └── agent.py, nodes.py, tools.py, utils.py, state.py
├── answer/           # Self-contained AnswerAgent
│   ├── prompts.py    # Answer-specific prompts
│   ├── tools_config.py
│   └── agent.py, nodes.py, tools.py, utils.py, state.py
└── retrieval/        # Self-contained RetrievalAgent
    ├── prompts.py    # Retrieval-specific prompts
    ├── tools_config.py
    └── agent.py, nodes.py, tools.py, utils.py, state.py
```

**Key Principles:**
- **Modularity**: Each agent owns its prompts, tools, and logic
- **Cohesion**: All agent-related code is in one directory
- **Clarity**: Easy to find and modify agent-specific configurations
- **Scalability**: New agents can be added without touching global configs

**Import Examples:**
```python
# Agent-specific imports
from src.agents.common.prompts import CommonRole
from src.agents.indexing.prompts import IndexingRole
from src.agents.answer.prompts import AnswerRole
from src.agents.answer.tools_config import ANSWER_TOOLS_CONFIG
from src.agents.retrieval.prompts import RetrievalRole
from src.agents.retrieval.tools_config import RETRIEVAL_TOOLS_CONFIG

# Multi-agent coordination (config level)
from src.config.prompts.agent_prompts import AgentType
```

## High-Level Architecture

### Core Architecture Patterns

**1. Multi-Agent System (src/agents/)** - Fully Modularized Architecture
- **IndexingAgent**: Document indexing agent responsible for PDF parsing, structure extraction, chunking, and vectorization
- **AnswerAgent**: User-facing Q&A agent that handles intent analysis, retrieval decision-making, and answer generation
- **RetrievalAgent**: Document retrieval agent for semantic search and context assembly
- **AgentBase**: Base class providing LLM instance management and LangGraph workflow building
- **CommonModule**: Shared prompts and utilities used across multiple agents
- Built on **LangGraph** framework with asynchronous state graph processing
- Uses typed state dictionaries (IndexingState, AnswerState, RetrievalState) defined with TypedDict
- All agent workflows compiled as StateGraph objects with nodes, edges, and conditional routing
- **Self-Contained Modules**: Each agent is fully self-contained with its own:
  - `prompts.py`: Agent-specific system prompts and role definitions
  - `tools_config.py`: Tool configurations with descriptions and parameters
  - `agent.py`, `nodes.py`, `tools.py`, `utils.py`, `state.py`: Core agent logic
  - This modular design allows for easy agent management, testing, and extension

**2. Document Registry System (src/agents/indexing/doc_registry.py)**
- **DocumentRegistry**: Centralized metadata management for all indexed documents
- Tracks processing stages, output files, and document status
- Supports incremental indexing and cache validation
- JSON-based storage in `data/doc_registry.json`

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
  - Modular API structure: `/api/v1/` endpoints for sessions, config, PDF, chat, web, chapters, and data management
  - Health check endpoint: `GET /health` for monitoring (returns app name, version, status)
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

**IndexingAgent Workflow:**
```
PDF File → check_cache → parse_document → extract_structure → chunk_text
   → process_chapters (parallel) → build_index → generate_brief_summary → register_document
```

**AnswerAgent Workflow:**
```
User Query → analyze_intent (需要检索?) → retrieve (RetrievalAgent) → generate_answer → Response
              ↓ (直接回答)              ↓
              └──────────────────────────┘
```

**RetrievalAgent Workflow:**
```
Query + Doc → semantic_search (vector DB) → assemble_context → ranked results
```

## Configuration Architecture

### Settings Structure (src/config/settings.py)
- **LLM_CONFIG**: Azure OpenAI, OpenAI, and Ollama configuration via environment variables
- **LLM_EMBEDDING_CONFIG**: Embedding model configuration for vector generation
- **Prompt System**: Role-based prompts organized by agent modularity
  - Agent-specific prompts are located in their respective agent directories:
    - `src/agents/common/prompts.py`: Shared prompts used across multiple agents
    - `src/agents/indexing/prompts.py`: IndexingAgent prompts for document parsing and extraction
    - `src/agents/answer/prompts.py`: AnswerAgent prompts for intent analysis and Q&A
    - `src/agents/retrieval/prompts.py`: RetrievalAgent prompts for intelligent retrieval
  - Multi-agent coordination prompts remain in `src/config/prompts/`:
    - `agent_prompts.py`: Prompts for PlanAgent, ExecutorAgent, MemoryAgent coordination
- **Tools Configuration**: Agent-specific tool configs moved to agent directories
  - `src/agents/answer/tools_config.py`: AnswerAgent tool configurations
  - `src/agents/retrieval/tools_config.py`: RetrievalAgent tool configurations
- **MCP_CONFIG**: External service configurations for web fetching and memory services
- **Data Paths**: Configurable storage locations for all generated content
- **Constants**: Centralized in `src/config/constants.py` with organized classes

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
- Code default is `openai` (see `src/agents/base.py` and agent implementations)
- Can be changed by passing `provider` parameter: `IndexingAgent(provider="azure")`

## Key Data Structures

### Agent State Structures (TypedDict-based)

**IndexingState** (src/agents/indexing/state.py):
- `pdf_name`: Document name being indexed
- `pdf_path`: Full path to PDF file
- `data`: Parsed document data organized by chapters
- `structure`: Document structure (agenda) with chapter titles and page ranges
- `chunks`: Text chunks for vector DB
- `summaries`: Chapter-wise summaries
- `index_path`: Path to built vector database
- `brief_summary`: Short summary for document registry
- `is_complete`: Processing completion flag
- `error`: Error message if processing fails

**AnswerState** (src/agents/answer/state.py):
- `user_query`: User's question
- `current_doc`: Document name context
- `needs_retrieval`: Boolean flag for retrieval decision
- `analysis_reason`: Reason for retrieval decision
- `retrieved_context`: Context from RetrievalAgent
- `final_answer`: Generated answer
- `is_complete`: Completion flag

**RetrievalState** (src/agents/retrieval/state.py):
- `query`: Search query
- `doc_name`: Document to search
- `k`: Number of results to return
- `retrieved_chunks`: List of relevant text chunks
- `context`: Formatted context string

### UI Session Management
- **SessionManager State**: Comprehensive JSON file-based storage with backup rotation and import/export
- **AppState**: FastAPI application state with PDF/Web readers, chat history, and session tracking
- **Client-side Storage**: localStorage-based session persistence with automatic sync mechanisms
- **Dual Storage Architecture**: Backend file storage + frontend localStorage for redundancy and offline capability

## Content Processing Workflow

### Document Processing Stages
1. **Content Extraction**: PDF-to-image conversion → OCR → Raw text extraction
2. **Structure Analysis**: Basic info extraction → Chapter/agenda detection → Content chunking
3. **Intelligent Processing**: Chapter-wise summarization → Content refactoring → Vector embedding (parallel processing)
4. **Storage & Export**: Vector DB building → Summary file generation (MD/PDF) → Cache management
5. **Registration**: Document metadata stored in DocumentRegistry

### Data Storage Organization (IMPORTANT)
JSON files are now organized by document for easier management:
```
data/json_data/{doc_name}/
├── data.json           # Original extracted content
├── structure.json      # Document structure (agenda)
└── chunks.json         # Text chunks for vector DB
```

**Benefits:**
- All JSON files for a document in one folder
- Easy deletion: remove entire folder without missing files
- Clear organization for finding specific document data
- Aligns with vector DB and output directory structure

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
# Data Management
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

# Chapter Management
GET    /api/v1/chapters/{doc_name}              - Get document chapter information

# Health Check
GET    /health                                   - Application health status monitoring
```

**Use Cases:**
- Delete large image files to free space while keeping JSON/summaries
- Clear vector DB to rebuild indexes
- Remove old summaries before regenerating
- Batch cleanup of multiple documents
- Regular maintenance with smart cleanup

## Development Patterns

### Adding New Agents
1. Create agent directory under `src/agents/new_agent/`
2. Create `state.py` with TypedDict definition for agent state
3. Create `prompts.py` with agent-specific system prompts and role constants
4. Create `tools_config.py` if the agent uses tools (define tool configurations)
5. Create `agent.py` inheriting from AgentBase, implement `build_graph()` method
6. Create `nodes.py` with node function implementations
7. Create `tools.py` and `utils.py` as needed
8. Create `__init__.py` to export agent class and state
9. Follow dependency injection pattern: tools/utils take agent instance in constructor
10. Import prompts from local `prompts.py` using `from .prompts import YourRole`

### Extending Document Processing
1. Modify IndexingAgent workflow by adding new nodes in `src/agents/indexing/nodes.py`
2. Update IndexingState in `state.py` if new fields are needed
3. Add new tools in `tools.py` following existing patterns
4. Update DocumentRegistry schema if new metadata is tracked
5. Add corresponding tests in `tests/test_indexing_agent.py`

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
- **PDF Processing**: User selects from available PDFs → IndexingAgent (if not indexed) → AnswerAgent
- **Document Selection**: Lists indexed documents from DocumentRegistry
- **Interactive Options**:
  - `i` - Index new document
  - `m` - Manage documents (view/delete)
  - `0` - General chat mode (no document context)
- **Chat Commands**: 'clear' to reset history, 'quit'/'exit' to end session

## Testing and Debugging

The codebase includes comprehensive logging with module-level loggers. Set `LOGGING_LEVEL=DEBUG` for detailed execution traces. Each major component (readers, agents, LLM clients) includes standalone testing capabilities that can be run independently.

**Standalone Testing:**
```bash
# Agent testing
python tests/test_indexing_agent.py     # Test PDF indexing workflow
python tests/test_answer_agent.py       # Test Q&A workflow
python tests/test_retrieval_agent.py    # Test retrieval workflow

# LLM testing
python tests/test_llm_client.py         # Test LLM client
python tests/test_llm_providers.py      # Test provider switching
python tests/test_history_compression.py # Test conversation history compression

# Vector DB testing
python tests/test_vector_db_content.py  # Test FAISS vector database

# Individual agent initialization
python -c "from src.agents.indexing import IndexingAgent; agent = IndexingAgent(); print('OK')"
python -c "from src.agents.answer import AnswerAgent; agent = AnswerAgent(); print('OK')"
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

# Test health check
curl http://localhost:8000/health

# Test chapter API
curl http://localhost:8000/api/v1/chapters/your_document_name
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
- **src/config/**: Configuration management
  - `settings.py`: Main settings and LLM config
  - `constants.py`: Organized constants classes (MCPConstants, ProcessingLimits, PathConstants, etc.)
  - `prompts/`: Multi-agent coordination prompts only
    - `agent_prompts.py`: Prompts for PlanAgent, ExecutorAgent, MemoryAgent
  - `tools/`: Empty directory (legacy, kept for reference)
- **src/agents/**: Multi-agent system (fully modularized)
  - `base.py`: AgentBase class with LLM management
  - `common/`: Shared utilities and prompts
    - `prompts.py`: Common prompts used across multiple agents
  - `indexing/`: IndexingAgent (self-contained module)
    - `prompts.py`: IndexingAgent-specific prompts
    - `agent.py`, `nodes.py`, `tools.py`, `utils.py`, `state.py`, `doc_registry.py`
  - `answer/`: AnswerAgent (self-contained module)
    - `prompts.py`: AnswerAgent-specific prompts
    - `tools_config.py`: AnswerAgent tool configurations
    - `agent.py`, `nodes.py`, `tools.py`, `utils.py`, `state.py`
  - `retrieval/`: RetrievalAgent (self-contained module)
    - `prompts.py`: RetrievalAgent-specific prompts
    - `tools_config.py`: RetrievalAgent tool configurations
    - `agent.py`, `nodes.py`, `tools.py`, `utils.py`, `state.py`
- **src/core/**: Core functionality
  - `llm/`: LLM abstraction (client.py, providers.py, history.py)
  - `processing/`: Document processing utilities (index_document.py, manage_documents.py, parallel_processor.py, text_splitter.py)
  - `vector_db/`: FAISS vector database client
- **src/ui/**: FastAPI web system
  - `backend/app.py`: FastAPI application
  - `backend/api/v1/`: API endpoints (pdf.py, chat.py, data.py, chapters.py, structure.py)
  - `backend/services/`: Service layer (chat_service.py, data_service.py, session_service.py)
  - `templates/`: Jinja2 HTML templates
  - `static/`: CSS and JavaScript files
- **src/services/**: External services (MCP client)
- **src/utils/**: Utility functions
- **tests/**: Comprehensive test suite

### Key Files to Understand
- **main.py**: CLI entry point using AnswerAgent
- **src/agents/base.py**: AgentBase class providing LLM instances and graph building
- **src/agents/indexing/agent.py**: IndexingAgent with full document processing workflow
- **src/agents/answer/agent.py**: AnswerAgent with intent analysis and retrieval coordination
- **src/agents/indexing/doc_registry.py**: DocumentRegistry for metadata management
- **src/config/settings.py**: Configuration hub with LLM_CONFIG, MCP_CONFIG
- **src/core/llm/client.py**: LLMBase with provider management and history
- **src/core/processing/index_document.py**: Document indexing entry point
- **src/ui/backend/app.py**: FastAPI application setup
- **src/ui/backend/services/chat_service.py**: Chat service using AnswerAgent
- **src/ui/backend/services/data_service.py**: Data management service

### State Management Pattern
The agent system uses LangGraph's StateGraph with TypedDict state definitions:
- Each agent has its own state TypedDict (IndexingState, AnswerState, RetrievalState)
- States flow through graph nodes defined in `nodes.py` modules
- Conditional routing based on state fields (e.g., `needs_retrieval` in AnswerAgent)
- Tools and utilities injected into agents via dependency injection pattern

### Agent Architecture Pattern
Each agent follows a consistent, self-contained structure:
- `agent.py`: Main agent class inheriting from AgentBase, builds LangGraph workflow
- `state.py`: TypedDict definition for agent state
- `nodes.py`: Graph node implementations (entry points for workflow steps)
- `tools.py`: Tool functions that agents can use (if applicable)
- `utils.py`: Helper utilities for the agent
- `prompts.py`: Agent-specific system prompts and role definitions
- `tools_config.py`: Tool configurations with descriptions and parameters (for agents with tools)

### Async Patterns
- All LLM calls are async: use `await` or `asyncio.run()` when calling from sync context
- Graph execution: `await self.graph.ainvoke(state)` or `async for event in self.graph.astream(state)`
- Main entry point (main.py) uses `asyncio.run(main_async())` for async support
- UI backend uses async/await throughout (FastAPI is async-native)
