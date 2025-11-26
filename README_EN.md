# AgenticReader

[中文](README.md) | English

AgenticReader is an intelligent document analysis and Q&A tool powered by large language models. It supports PDF and web content parsing with multiple LLM providers (Azure OpenAI, OpenAI, Ollama), automatic content extraction, summary generation, vector database building, and multi-turn intelligent conversations.

---

## Key Features

### Document Processing
- **Multi-format Support**: PDF documents and web URL content parsing
- **Smart Extraction**: PDF to image + OCR, web content via MCP services
- **Auto Chunking**: Intelligent text splitting based on content length
- **Vector Database**: Efficient semantic search based on FAISS
- **Parallel Processing**: Async parallel processing for chapter summaries and content generation, significantly improving processing speed

### Intelligent Q&A
- **Multi-turn Dialogue**: Auto-caching retrieval results for continuous context conversations
- **Chapter-based Search**: Recommend asking with chapter names for better retrieval
- **Auto Summary**: Generate brief and detailed summaries
- **Multi-format Export**: Support Markdown and PDF format exports

### Modern Web Interface
- **FastAPI + WebSocket**: Real-time chat communication
- **Session Persistence**: Auto-save, backup rotation (keeps latest 10), import/export
- **Dual Storage Architecture**: Client localStorage + server file storage
- **PDF Viewer**: Integrated online PDF preview with page navigation
- **Chapter Management System**: Independent chapter editing interface with CRUD operations and batch rebuild
- **Data Management System**: Granular data management with partial deletion, batch operations, and smart cleanup
- **Responsive Design**: Mobile-friendly adaptive interface

---

## Quick Start

### Requirements
- Python 3.12+
- Node.js (optional, for MCP services)
- Virtual environment (recommended)

<details>
<summary><b>📦 Installation & Configuration (Click to expand)</b></summary>

### Installation Steps

```bash
# 1. Clone the repository
git clone <repository-url>
cd AgenticReader

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Create data directories
mkdir -p data/pdf data/pdf_image data/json_data data/vector_db data/output data/memory data/sessions data/sessions/backups data/sessions/exports data/config

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

### Running the Application

#### Method 1: Web Interface (Recommended)
```bash
# Start FastAPI server
python src/ui/run_server.py

# Access URLs
# Homepage: http://localhost:8000
# Chat Interface: http://localhost:8000/chat
# Configuration: http://localhost:8000/config
# Data Management: http://localhost:8000/data
# Chapter Management: http://localhost:8000/chapters
# Health Check: http://localhost:8000/health
# API Docs: http://localhost:8000/docs
# ReDoc: http://localhost:8000/redoc
```

#### Method 2: CLI Mode
```bash
# Run main program
python main.py

# Follow prompts to:
# - Enter PDF filename (e.g., paper.pdf)
# - Enter web URL (e.g., https://example.com/article)
# - Ask questions for multi-turn dialogue
# - Enter "exit", "bye", "quit" to exit
```

---

<details>
<summary><b>💡 Usage Examples (Click to expand)</b></summary>

### PDF Document Analysis
```bash
# 1. Place PDF file in data/pdf/ directory
cp your_paper.pdf data/pdf/

# 2. Run main.py and enter filename
python main.py
# Input: your_paper.pdf

# 3. System auto-processes and generates summaries
# Output location: data/output/your_paper/
#   - brief_summary.md / brief_summary.pdf
#   - detail_summary.md / detail_summary.pdf
```

### Web Content Analysis
```bash
# Install MCP service (first time)
# Option 1: Playwright MCP (recommended)
npx @playwright/mcp@latest

# Option 2: DuckDuckGo MCP
uv pip install duckduckgo-mcp-server

# Run and enter URL
python main.py
# Input: https://arxiv.org/abs/1706.03762
```

### Intelligent Q&A
```bash
# Question examples (better with chapter names)
You: Explain the core ideas in the Introduction section
You: What are the main contributions mentioned in the Abstract?
You: Compare the content of Method and Conclusion sections
```

### Web Interface Usage
1. **Upload Document**: Click to upload PDF or enter URL
2. **View Summary**: Auto-generated document summary and structure
3. **Smart Chat**: Ask questions in chat box, supports multi-turn dialogue
4. **Session Management**: Save, export, import chat sessions
5. **PDF Preview**: View PDF documents online
6. **Data Management**: View and manage all document data with granular deletion

</details>

<details>
<summary><b>📊 Data Management Features (Click to expand)</b></summary>

Access `http://localhost:8000/data` to enter data management interface:

**Features:**
- **Storage Overview**: Real-time view of document count, storage size, session statistics
- **Document Management**: Detailed data classification display (JSON, Vector DB, Images, Summary)
- **Chapter Information**: View document chapter structure and detailed information
- **Partial Deletion**: Delete specific data types for individual documents (e.g., delete images only while keeping other data)
- **Batch Operations**: Multi-select documents for batch deletion
- **Cache Management**: Independent management of PDF image cache, vector DB cache, JSON data cache
- **Smart Cleanup**: Auto-cleanup of data older than 30 days
- **Data Backup**: Create backups of sessions and configurations
- **Health Check**: `/health` endpoint for monitoring application status

**Use Cases:**
- Free up disk space: Delete large files (images) while keeping other data
- Rebuild index: Delete vector database then rebuild
- Update summary: Delete old summary and regenerate
- Regular maintenance: Use smart cleanup to auto-clean expired data

</details>

---

<details>
<summary><b>📁 Project Structure (Click to expand)</b></summary>

```
AgenticReader/
├── main.py                    # CLI entry point
├── requirements.txt           # Python dependencies
├── CLAUDE.md                  # Claude Code development guide
├── README.md                  # Project documentation (Chinese)
├── README_EN.md               # Project documentation (English)
├── LICENSE                    # Open source license
│
├── src/
│   ├── config/                # Configuration files
│   │   ├── settings.py        # Main config (LLM, MCP, paths)
│   │   ├── constants.py       # Constants definition
│   │   └── prompts/           # Prompt configurations
│   │
│   ├── core/                  # Core functionality
│   │   ├── llm/               # LLM client (multi-provider support)
│   │   ├── processing/        # Text processing (tokenization, chunking)
│   │   └── vector_db/         # Vector database (FAISS)
│   │
│   ├── readers/               # Document readers
│   │   ├── base.py            # Base reader class
│   │   ├── pdf.py             # PDF reader
│   │   ├── web.py             # Web reader
│   │   └── parallel_processor.py  # Chapter parallel processor
│   │
│   ├── chat/                  # Multi-agent system
│   │   ├── chat.py            # PlanAgent + ExecutorAgent
│   │   └── memory_agent.py    # Memory agent
│   │
│   ├── services/              # External services
│   │   └── mcp_client.py      # MCP service client
│   │
│   ├── ui/                    # Web interface
│   │   ├── backend/           # FastAPI backend
│   │   │   ├── app.py         # Main application
│   │   │   ├── api/           # API routes
│   │   │   │   └── v1/        # API v1 version
│   │   │   │       ├── data.py      # Data management API
│   │   │   │       ├── chat.py      # Chat API
│   │   │   │       ├── pdf.py       # PDF processing API
│   │   │   │       ├── web.py       # Web processing API
│   │   │   │       ├── chapters.py  # Chapters API
│   │   │   │       ├── sessions.py  # Sessions API
│   │   │   │       └── config.py    # Configuration API
│   │   │   ├── services/      # Business logic
│   │   │   │   ├── data_service.py  # Data management service
│   │   │   │   └── session_service.py # Session management service
│   │   │   └── models/        # Data models
│   │   ├── templates/         # Jinja2 templates
│   │   ├── static/            # Static assets (CSS, JS)
│   │   │   └── js/
│   │   │       └── data.js    # Data management frontend
│   │   └── run_server.py      # Server startup script
│   │
│   └── utils/                 # Utility functions
│
└── data/                      # Data directory (runtime generated)
    ├── pdf/                   # PDF file storage
    ├── pdf_image/             # PDF to image cache
    ├── json_data/             # Extracted content JSON
    ├── vector_db/             # Vector database files
    ├── output/                # Generated summary files
    ├── memory/                # Memory system data
    └── sessions/              # Web interface session data
        ├── backups/
        │   └── chat_sessions_current.json  # Current sessions
        └── exports/           # Exported sessions
```

</details>

---

<details>
<summary><b>🏗️ Technical Architecture (Click to expand)</b></summary>

### Core Components

1. **Reader System** (src/readers/)
   - ReaderBase: Abstract base class providing common processing flow
   - PDFReader: PDF document processing (PyMuPDF + OCR)
   - WebReader: Web content processing (MCP services)

2. **LLM Abstraction** (src/core/llm/)
   - Unified interface supporting multiple providers (Azure OpenAI, OpenAI, Ollama)
   - Role-based prompt management
   - Automatic session context handling

3. **Vector Database** (src/core/vector_db/)
   - FAISS vector storage
   - Semantic similarity search
   - Chapter metadata management

4. **Web UI** (src/ui/)
   - FastAPI + WebSocket real-time communication
   - Session persistence (dual storage architecture)
   - Data management system (granular control)
   - Modular API design

### Data Flow

```
Input (PDF/URL)
  → Content Extraction
  → Text Chunking
  → Chapter Detection
  → Content Summary
  → Vectorization
  → Store to FAISS

User Query
  → Chapter Retrieval
  → Context Assembly
  → LLM Response Generation
  → Return to User
```

</details>

---

<details>
<summary><b>🛠️ Development Guide (Click to expand)</b></summary>

### Adding New LLM Providers
1. Extend `LLMBase` in `src/core/llm/client.py`
2. Add configuration to `LLM_CONFIG` in `src/config/settings.py`
3. Update provider switching logic

### Adding New Agents
1. Inherit from `GraphBase` to create agent class
2. Implement `build_graph()` and core processing methods
3. Add agent configuration to `AgentCard` in `src/config/settings.py`
4. Handle new agent type in `ExecutorAgent._create_agent()`

### Extending Web API
1. Create new route file in `src/ui/backend/api/v1/`
2. Register route in `src/ui/backend/app.py`
3. Follow RESTful conventions and FastAPI best practices

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

# Test specific modules
python src/chat/memory_agent.py
python src/chat/chat.py
```

</details>

---

<details>
<summary><b>❓ FAQ (Click to expand)</b></summary>

### 1. PDF file not recognized?
- Ensure file is placed in `data/pdf/` directory
- Check filename spelling is correct
- Supported format: `.pdf`

### 2. LLM API errors?
- Check if API key in `.env` file is correct
- Verify endpoint and model name configuration
- Confirm account has sufficient quota

### 3. Vector database loading failed?
- First use auto-creates, no need to worry
- To rebuild: Delete `data/vector_db/<document_name>` folder then rerun
- Or use data management interface to delete vector database

### 4. Web interface won't start?
```bash
# Check if dependencies are complete
pip install fastapi uvicorn jinja2 python-multipart websockets

# Check if port is occupied
lsof -i :8000

# View detailed error logs
python src/ui/run_server.py
```

### 5. MCP service connection failed?
- Confirm Node.js is installed
- Check if MCP service is correctly installed
- Review MCP configuration in `src/config/settings.py`

### 6. Session data lost?
- Check backup files in `data/sessions/backups/` directory
- Use web interface import function to restore backups
- Backup files named by timestamp, keeps max 10

### 7. How to switch LLM providers?
```python
# Specify in code
from src.readers.pdf import PDFReader
pdf_reader = PDFReader(provider="azure")  # or "openai", "ollama"

# Default uses openai (see src/readers/base.py:35)
```

### 8. How to clean old data to free space?
- Access `http://localhost:8000/data` to enter data management interface
- Use "Smart Cleanup" to auto-clean data older than 30 days
- Or manually select documents and delete specific data types (e.g., delete images only)

### 9. How to recover accidentally deleted data?
- Session data can be recovered from `data/sessions/backups/`
- Document data recommended to use "Data Backup" feature regularly
- Backup files saved in `data/backups/` directory

</details>

---

<details>
<summary><b>📝 Changelog (Click to expand)</b></summary>

### 2025-11-26 - Parallel Processing Optimization and Chapter Management UI
- ⚡ **Parallel Processing Optimization**
  - Added `src/utils/async_utils.py` - Generic async parallel processing utilities
  - Added `src/readers/parallel_processor.py` - Reader-specific parallel processor
  - Chapter summary and content refactoring now execute in parallel, 3-5x speed improvement
  - Detail summary generation parallelized with semaphore-controlled concurrency
- 📁 **Independent Chapter Management Interface**
  - New `/chapters` page - Parallel to config management and data management
  - Integrated PDF preview with left chapter list + right PDF display
  - Support chapter edit, add, delete operations
  - Support batch rebuild of vector database and summaries
  - Processing progress indicators and chapter highlighting
- 🛠️ **Code Refactoring**
  - Extracted parallel processing logic into independent modules for better reusability
  - Optimized chapter processing flow in `base.py`

### 2025-11-19 - Data Management System
- ✨ **New Data Management Interface**
  - Real-time storage overview dashboard (document count, storage size, session stats)
  - Document detail display (JSON, Vector DB, Images, Summary shown independently)
  - **Granular partial deletion** - Delete specific data types for individual documents
  - Batch selection and deletion operations
  - Cache management (PDF images, vector DB, JSON data managed independently)
  - Smart cleanup (auto-clean data older than N days)
  - Data backup and full reset functionality
- 📊 **New Service Layer**
  - `DataService` - File system operations and data management logic
  - Session format compatibility handling
- 🎨 **Frontend Optimization**

### 2025-11-05 - Web Interface Refactor
- Added FastAPI + WebSocket modern web interface
- Implemented session persistence management and dual storage architecture
- Integrated online PDF viewer
- Added auto-backup and import/export functionality

### 2025-07-30 - Web Reader
- Added Web Reader functionality
- Support parsing web content via URL
- Integrated MCP services

### 2025-07-23 - Summary Export
- Added summary file export functionality
- Support Markdown and PDF formats
- Added `save_data_flag` control parameter

</details>

---

<details>
<summary><b>🤝 Contributing (Click to expand)</b></summary>

Welcome to submit Issues and Pull Requests!

### Development Process
1. Fork this repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Create Pull Request

### Code Standards
- Follow PEP 8 Python code style
- Add necessary comments and docstrings
- Ensure all tests pass
- Update relevant documentation

</details>

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) file for details.

---

## Acknowledgements

- [LangChain](https://github.com/langchain-ai/langchain) - LLM application development framework
- [LangGraph](https://github.com/langchain-ai/langgraph) - Multi-agent state graph management
- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework
- [FAISS](https://github.com/facebookresearch/faiss) - Efficient vector retrieval
- [PyMuPDF](https://pymupdf.readthedocs.io/) - PDF processing
- [Model Context Protocol](https://modelcontextprotocol.io/) - MCP services

---

## Contact

For questions or suggestions, please contact via:
- Submit GitHub Issue
- Start a Discussion

---

**⭐ If this project helps you, please give it a Star!**
