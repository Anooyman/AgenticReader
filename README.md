# AgenticReader

中文 | [English](README_EN.md)

AgenticReader 是基于大语言模型（LLM）的智能文档分析与问答工具：解析 PDF、构建 FAISS 向量索引，由五个 LangGraph Agent 驱动多轮智能问答。除了文档问答，它还有三块实际能力：

- **长期记忆**（`src/memory/`）：基于 LanceDB 的跨会话记忆（`data/memory_db/`），对话自动入库、问答时由 Agent 自主检索；
- **每日简报管线**（`src/pipeline/`）：简报 HTML 批量入队 → 下载/爬取 → 多维 QA 摘要 → 自动写入长期记忆；
- **网页抓取服务**（`src/services/scraper/`）：Playwright 反检测抓取器，可作 stdio MCP 服务启动。

支持 Azure OpenAI、OpenAI、Ollama、Gemini 四种 provider；提供 **CLI 命令行** 与 **Web 界面** 两种使用方式。

> 开发者向的架构细节（模块层级、开发范式、测试注意事项）见仓库根目录 [CLAUDE.md](CLAUDE.md)。

---

## 核心特性

### 🤖 五个 LangGraph Agent
- **IndexingAgent**：PDF 解析 → 结构提取 → 分块 → 并行章节处理 → 向量化 → 注册（任一节点出错短路直达注册，失败文档不会出现在可检索列表）
- **AnswerAgent**：确定性单轮问答图——`rewrite_query → plan → (execute → generate | generate) → END`；plan 按用户勾选的工具纯代码构造调用（无 LLM 决策、无回环）
- **RetrievalAgent**：单/多文档 ReAct 检索循环（语义检索 + 观察 + 总结）
- **SearchAgent**：网络搜索与 URL 分析（DuckDuckGo MCP 搜索 + web_scraper MCP 爬取；大内容自动转索引后对话）
- **Orchestrator**：Web 聊天的真正入口，ReAct 循环自主决定调用 `search_memory`（查长期记忆）和/或 `deep_dive_document`（深挖某文档原文），多个工具调用并行执行

### 📄 文档处理
- PDF 转图片逐页解析、目录/章节结构自动检测、章节级分块
- FAISS 向量检索（索引与 embeddings 客户端均有进程级 LRU 缓存）
- 章节摘要/重构并行处理（`ChapterProcessor`）、多文档并行检索（`ParallelRetrievalCoordinator`）
- 各阶段缓存：重复索引自动跳过已完成阶段
- 文档注册表 `data/doc_registry.json`：并发安全（flock + 原子落盘），跟踪处理状态

### 💬 智能问答
- **CLI 五种入口**：单文档 / 跨文档智能选档 / 跨文档手动选档 / 网络搜索与 URL 分析 / 通用对话
- **工具系统**：`retrieve_documents`（文档检索）、`search_web`（网络搜索），聊天界面可勾选启用
- **长期记忆加持**：对话自动沉淀到 LanceDB（`webapp-chat` namespace），提问时 Orchestrator 可自动检索历史记忆
- 对话历史 LLM 压缩，节省上下文；检索结果按对话轮次窗口去重（`RETRIEVAL_DEDUP_WINDOW`，默认 5 轮）
- 会话服务端落盘 `data/sessions/{session_id}.json` 平铺文件；浏览器端仅主题偏好使用 localStorage（`AgenticReader_theme` 键）

### 🧠 长期记忆（src/memory/）
- 单 LanceDB 表 `memories`，按 namespace 隔离：`ai-research`（简报/文章摘要）与 `webapp-chat`（对话历史）
- **chat_ingest 后台车道**：周期扫描会话目录，把"有新内容 + 已静默 + 完整问答"的会话自动入库（按内容 hash 幂等去重，水位线在 `data/pipeline/chat_ingest_state.json`）
- **agentic_search**：semantic / keyword / keywords-pool / list-by-source 四工具的 ReAct 检索循环（上限 4 轮），供 Orchestrator 调用
- `/data` 页 Memory tab 提供概览、检索、删除（单条 / 按来源 / 整个 namespace）

### 📰 每日简报管线（src/pipeline/）
- `BRIEFS_DIR` 下的简报 HTML 解析入队（`data/pipeline/pipeline_queue.json`）
- job_runner 后台车道串行处理：下载/爬取 → IndexingAgent + AnswerAgent（+ SearchAgent）多维 QA → `generate_qa_brief` 提炼摘要
- 摘要落 `data/pipeline/summaries/{pdf,web}/` 并自动写入记忆 `ai-research` namespace；单条失败重试，超过 `MAX_ATTEMPTS = 3` 转永久失败
- 独立 CLI 可选：`python -m src.pipeline.sync_pipeline_queue` / `render_report` / `sync_memory_ingest` / `generate_qa_brief`

### 🕷️ 网页抓取（src/services/scraper/）
- Playwright（Chromium）抓取：浏览器管理、下载、内容提取、反检测四模块
- 可作 stdio MCP 服务启动：`python -m scraper.mcp_server.server`（`PYTHONPATH=src/services`，已配进 `MCP_CONFIG` 的 `web_scraper` 条目，供 SearchAgent 调用）

---

## 快速开始

### 环境要求
- Python 3.12+（推荐虚拟环境）
- 至少一家 LLM provider 的 API 凭据（Azure OpenAI / OpenAI / Ollama / Gemini）

### 安装

```bash
# 1. 克隆项目
git clone <repository-url>
cd AgenticReader

# 2. 安装依赖
pip install -r requirements.txt
pip install -r requirements-dev.txt   # 仅测试需要（pytest / pytest-asyncio）

# 3. 创建数据目录（多数组件会自动创建，建议先建好）
mkdir -p data/pdf data/pdf_image data/json_data data/vector_db data/output \
         data/config data/sessions data/memory_db data/pipeline

# 4. 安装 Playwright 浏览器（web_scraper MCP 抓取需要）
playwright install chromium

# 5. 网络搜索功能依赖 DuckDuckGo MCP（uvx 启动，需安装 uv）
#    uvx duckduckgo-mcp-server 能被拉起即可，无需单独配置
```

### 配置环境变量

在项目根目录创建 `.env`（代码经 python-dotenv 读取；也可用 shell 环境变量）：

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

# === 或 OpenAI ===
# OPENAI_API_KEY=***            # 默认模型 gpt-3.5-turbo / text-embedding-ada-002
# OPENAI_MODEL_NAME=gpt-4o
# OPENAI_BASE_URL=https://api.openai.com/v1/

# === 或 Ollama（本地） ===
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_MODEL_NAME=llama3
# OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# === 或 Gemini ===
# GEMINI_API_KEY=***
# GEMINI_MODEL_NAME=gemini-1.5-pro
# GEMINI_EMBEDDING_MODEL=text-embedding-004

# === Provider 选择（CLI 无 UI 配置时的回退） ===
# PROVIDER=openai          # azure | openai | ollama | gemini
# EMBEDDING_PROVIDER=openai
```

### 启动 Web 界面

```bash
python src/ui/run_server.py
# → http://127.0.0.1:8000
```

`run_server.py` 是推荐入口（跨平台、Windows 控制台适配、自动重载）。默认**只监听 127.0.0.1 回环地址**——应用按本地无鉴权设计。可用环境变量覆盖：`HOST=0.0.0.0`（监听非本机地址时启动会打 WARNING，请自行评估风险）、`PORT=8080`。等价手动方式（uvicorn 默认 host 同样是 127.0.0.1）：

```bash
uvicorn src.ui.backend.app:app --reload --port 8000
```

### 启动 CLI

```bash
python main.py
```

主菜单：输入文档编号进入单文档对话；`c` 跨文档智能对话（按各文档 brief_summary 自动选档）；`s` 跨文档手动多选；`w` 网络搜索与 URL 分析（SearchAgent）；`0` 通用对话；`i` 索引 `data/pdf/` 里的新文档；`m` 查看/删除文档。对话中输入 `clear` 清历史、`switch` 换模式、`main` 回主菜单、`quit` 退出。

### 运行测试

```bash
pytest                     # 全量：缺少 LLM 凭据时，需要真实调用的脚本式测试自动 skip（credential-free 可跑）
python tests/test_imports.py   # 零依赖 import 冒烟，不联网不调 LLM
```

---

## 页面一览

| 页面 | 地址 | 用途 |
|---|---|---|
| 仪表板 | `/` | 已索引文档概览、快速索引、进入聊天 |
| 智能聊天 | `/chat` | WebSocket 实时对话（走 Orchestrator），Markdown/LaTeX 渲染，勾选工具与文档，消息带 MemorySearch/DeepDive 标签 |
| 数据管理 | `/data` | 存储总览、按文档删除四类产物（JSON/向量库/图片/摘要）、批量删除、智能清理、会话统计、Memory tab |
| 配置中心 | `/config` | 切换 provider、系统设置（落 `data/config/app_config.json`） |
| 结构编辑器 | `/structure` | 编辑文档章节 structure.json 并重建摘要/索引，PDF 在线预览 |
| 每日简报 | `/briefs` | 浏览 `BRIEFS_DIR` 简报条目，勾选加载进管线队列，查看后台任务 |
| 简报记忆桥接 | `/memory` | 桥接**外部** LLM-Memory webui（`LLM_MEMORY_URL`，默认 `http://127.0.0.1:8765`），与内置 `src/memory/` 是两套东西 |
| API 文档 | `/docs` `/redoc` | FastAPI 自动生成 |
| 健康检查 | `/health` | status / timestamp / version |

## 常见任务

**索引第一个 PDF**：把 PDF 放入 `data/pdf/`，在 `/` 页点索引（或 CLI 选 `i`）。日志按节点推进：解析 → 结构 → 分块 → 章节处理 → 建索引 → 摘要 → 注册。

**在聊天里利用长期记忆**：正常对话即可——回答结束后 chat_ingest 车道会在会话静默后自动入库；之后的提问 Orchestrator 可自主调用 `search_memory` 检索历史。

**让回答同时查文档和搜网页**：在 `/chat` 勾选 📎文档检索 与 🌐网络搜索 两个工具；CLI 网络搜索用 `w` 模式。

**切换 LLM provider**：Web 端在 `/config` 页选择（写入 `data/config/app_config.json`，一次提问全链路同一 provider）；CLI 端按环境变量 `PROVIDER`。优先级：显式传参 > `app_config.json` > env `PROVIDER` > `openai`。

**删除/清理数据**：`/data` 页支持只删某文档的 Images 或 Vector DB（释放空间而保留解析结果，重建索引免重解析）、批量删除、`cleanup/smart` 按天数清理；所有删除收敛到唯一实现 `src/core/document_management/delete_service.py`。

**跑每日简报**：把简报 HTML 放入 `BRIEFS_DIR`（env 可改，默认 `~/Desktop/AATF-Intelligence-Briefs`）→ `/briefs` 页勾选"加载" → 后台 job_runner 自动处理，摘要进 `data/pipeline/summaries/` 并写入记忆。

**给不同 Agent 换不同模型**：编辑 `src/config/model_overrides.py` 的 `AGENT_MODEL_OVERRIDES`（按 agent 名查表）。

**用语音**：`/api/v1/speech/transcribe|synthesize`（需 `OPENAI_API_KEY`）。

---

## 配置说明（环境变量全清单）

**对话模型凭据（`src/config/settings.py`）**

| 变量 | 说明 |
|---|---|
| `CHAT_API_KEY` `CHAT_API_VERSION` `CHAT_AZURE_ENDPOINT` `CHAT_DEPLOYMENT_NAME` `CHAT_MODEL_NAME` | Azure OpenAI |
| `OPENAI_API_KEY` `OPENAI_MODEL_NAME`（默认 gpt-3.5-turbo） `OPENAI_BASE_URL` | OpenAI |
| `OLLAMA_BASE_URL`（默认 `http://localhost:11434`） `OLLAMA_MODEL_NAME`（默认 llama3） | Ollama |
| `GEMINI_API_KEY` `GEMINI_MODEL_NAME`（默认 gemini-1.5-pro） `GEMINI_BASE_URL` | Gemini |

**Embedding（模型名/环境的唯一读取入口是 `settings.get_embedding_provider()` / `get_embedding_model_name()`）**

| 变量 | 说明 |
|---|---|
| `EMBEDDING_PROVIDER` | embedding 的 provider 选择（默认 openai） |
| `EMBEDDING_API_KEY` `EMBEDDING_API_VERSION` `EMBEDDING_AZURE_ENDPOINT` `EMBEDDING_DEPLOYMENT` `EMBEDDING_MODEL` | Azure embedding |
| `OPENAI_EMBEDDING_MODEL`（默认 text-embedding-ada-002） | OpenAI embedding |
| `OLLAMA_EMBEDDING_MODEL`（默认 llama3） | Ollama embedding |
| `GEMINI_EMBEDDING_MODEL`（默认 text-embedding-004） | Gemini embedding |

**运行时行为**

| 变量 | 说明 |
|---|---|
| `HOST` / `PORT` | `run_server.py` 监听地址/端口，默认 `127.0.0.1` / `8000`；非回环 HOST 打 WARNING |
| `CORS_ORIGINS` | 逗号分隔来源列表，默认只放行 localhost/127.0.0.1:8000；含 `*` 时自动关闭凭据 |
| `PROVIDER` | CLI 等无 UI 配置时的 provider 回退 |
| `RETRIEVAL_DEDUP_WINDOW` | 检索去重的轮次窗口，默认 5 |
| `BRIEFS_DIR` | 简报 HTML 目录，默认 `~/Desktop/AATF-Intelligence-Briefs` |
| `LLM_MEMORY_URL` | 外部 LLM-Memory webui 地址（`/memory` 页桥接），默认 `http://127.0.0.1:8765` |
| `DEBUG` | WebSocket 调试输出开关（`true` 开启），默认关闭 |

**两个常见误解**
- **没有 `LOGGING_LEVEL` 环境变量**：代码不读取它，日志级别写死在 `src/core/llm/client.py` 的 `logging.basicConfig(level=logging.INFO)`，调 DEBUG 需改这一行。
- **没有前端会话存储**：会话一律服务端落盘，localStorage 仅保存主题偏好（`base.html` 的 `AgenticReader_theme` 键）。

---

## 架构速览

```
AgenticReader/
├── main.py                     # CLI 入口（驱动 AnswerAgent / SearchAgent）
├── src/agents/                 # 五个 Agent（各包含 agent/nodes/tools/state/prompts）
│   ├── base.py                 #   AgentBase：provider 选择、按名查表覆盖模型
│   ├── indexing/               #   IndexingAgent（含 components/metadata_extractor.py）
│   ├── answer/                 #   AnswerAgent（tools_config.py 注册工具；components/ 选档·综合·格式化）
│   ├── retrieval/              #   RetrievalAgent（ReAct 检索）
│   ├── search/                 #   SearchAgent（utils.py 内置 SimpleMCPClient，stdio 传输）
│   └── orchestrator/           #   Orchestrator + sub_agents/（memory_search、deep_dive）
├── src/config/                 # settings.py（LLM/Embedding/MCP 配置）、constants.py、
│   └── prompts/                #   model_overrides.py；prompts 仅 metadata_prompts.py
├── src/core/
│   ├── document_management/    # registry（注册表）/ indexer / delete_service（唯一删除实现）/ manager
│   ├── llm/                    # client（LLMBase + 日志 + embeddings 缓存）/ providers / history
│   ├── parallel/               # indexing.py（ChapterProcessor）/ retrieval.py（ParallelRetrievalCoordinator）
│   └── vector_db/              # vector_db_client（FAISS + 轮次去重 + 索引缓存）/ metadata_db
├── src/memory/                 # LanceDB 长期记忆（config / ingest / search / vector_store / adapters）
├── src/pipeline/               # 简报管线（briefs_parser / queue_store / process_pdf_queue /
│                               #   process_web_queue / generate_qa_brief / render_report / sync_* / paths）
├── src/services/scraper/       # Playwright 抓取包（core/browser·downloader·extractor·anti_detection、
│                               #   storage、mcp_server/server·tools）
├── src/ui/
│   ├── run_server.py           # 启动入口（HOST/PORT、回环安全默认）
│   ├── backend/                # app.py（lifespan 起 job_runner + chat_ingest 两车道）、config.py
│   │   ├── api/                # pages（7 页面）、websocket（/ws/chat）、v1/（documents chat pdf
│   │   │                       #   structure config sessions data·data_storage·data_ops·data_common
│   │   │                       #   briefs jobs memory speech llmmemory）
│   │   └── services/           # chat_service（走 Orchestrator）、session_manager、chat_ingest、
│   │                           #   job_runner、memory_browse、task_service、briefs_data、brief_memory
│   ├── templates/              # base dashboard chat config manage structure_editor briefs memory
│   └── static/                 # css/（chat manage dashboard briefs memory …）js/（api chat
│                               #   chat-enhancer manage config dashboard briefs memory …）
├── src/utils/                  # json_io（write_json_atomic 唯一实现）、path_guard（safe_path 防目录穿越）等
└── data/                       # 运行时数据（见下）
```

**数据目录**（全部平铺在 `data/` 下，共 9 个）：

```
data/
├── pdf/            # 待索引 PDF 源文件
├── pdf_image/      # PDF 逐页图片（按文档分文件夹）
├── json_data/      # 解析数据（{doc}/data.json、structure.json、chunks.json）
├── vector_db/      # FAISS 索引（{doc}_data_index/）
├── output/         # brief_summary.md 等摘要产物
├── config/         # app_config.json（provider/系统设置）
├── sessions/       # 会话 {session_id}.json 平铺（旧 mode 子目录会自动迁移）
├── memory_db/      # LanceDB 长期记忆库
├── pipeline/       # pipeline_queue.json、webapp_jobs.json、chat_ingest_state.json、summaries/
└── doc_registry.json  # 文档注册表
```

**对话数据流**：`/ws/chat` → `chat_service` → **Orchestrator.ask()**（ReAct：可自主调用 `search_memory` → `src/memory/search.py` 的 `agentic_search`，`deep_dive_document` → AnswerAgent 深挖原文；带轮次/上下文/超时三重护栏）。CLI 则由 `main.py` 直接驱动 AnswerAgent / SearchAgent。

**索引数据流**：上传/选择 PDF → IndexingAgent 图（check_cache → parse → extract_structure → chunk → process_chapters → build_index → generate_brief_summary → register），出错短路直达 register 且不会标成 completed。

**MCP 服务**（`settings.py` 的 `MCP_CONFIG`）：`duckduckgo`（`uvx duckduckgo-mcp-server`）与 `web_scraper`（本仓库自带 Playwright 抓取 MCP）。MCP 客户端是 `src/agents/search/utils.py` 的 `SimpleMCPClient`（stdio）。

## REST API 速查

前缀均为 `/api/v1`：

```
documents  GET  /list /available-pdfs      POST /upload /index       DELETE /{doc_name}
chat       POST /initialize /clear         GET  /load-more-messages
sessions   GET  /list /current/info /{id}  DELETE /{id}  PATCH /{id}/rename
pdf        GET  /view/{doc_name}           # PDF 页面图
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
llmmemory  # 外部 LLM-Memory webui 的透传代理（/memory 页）
```

注意：会话端点只有 list / current-info / get / delete / rename 五个，**没有** import/export；`/api/v1/memory` 没有单条 item 的 GET 读取端点。

## 安全说明

- 默认仅监听 `127.0.0.1`，CORS 默认只放行本机来源——应用面向本地使用，未做鉴权；改 `HOST` 对外暴露前请自行加防护。
- 所有按文档名拼数据目录的 API 都过 `safe_path()`（`src/utils/path_guard.py`）防目录穿越。
- 删除操作收敛在 `delete_service.py` 单点实现，配合路径校验。

---

## 许可证 | License

[MIT License](LICENSE)

## 贡献 | Contributing

欢迎提交 Issue 和 Pull Request！

## 致谢 | Acknowledgments

- [LangChain](https://github.com/langchain-ai/langchain) / [LangGraph](https://github.com/langchain-ai/langgraph) - LLM 应用与多智能体编排框架
- [FAISS](https://github.com/facebookresearch/faiss) - 高效的向量检索库
- [FastAPI](https://fastapi.tiangolo.com/) - 现代化的 Web 框架
- [LanceDB](https://lancedb.com/) - 嵌入式向量数据库（长期记忆存储）
- [Playwright](https://playwright.dev/) - 浏览器自动化（网页抓取）
