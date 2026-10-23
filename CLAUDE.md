# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 本文档按当前代码实地重写（旧版与本仓库已严重脱节）。关键更正：`DocumentRegistry` 在 `src/core/document_management/registry.py`（不是 `src/agents/indexing/doc_registry.py`）；`src/config/prompts/` 下只剩 `metadata_prompts.py`（PlanAgent/ExecutorAgent/MemoryAgent/AgentType 均不存在）；`src/config/tools/` 目录不存在；`src/core/processing/`、`src/config/app_settings.py`、`src/services/mcp_client.py`、`src/services/duckduckgo_mcp_server.py`、`src/ui/backend/api/v1/chapters.py`、`src/ui/static/js/dashboard.js` 等历史孤儿模块已在重构中删除；UI 服务层是 `session_manager.py`（无 `data_service.py`）；PDFReader/WebReader 类不存在；memory 子系统已实际接入（非 planned）。

## Project Overview

AgenticReader 是 LLM 驱动的文档分析与智能问答工具：解析 PDF / 网页内容，构建 FAISS 向量索引，支持多轮对话式问答。支持的 provider：Azure OpenAI、OpenAI、Ollama、Gemini。

当前代码包含三块实际能力（不只是一个问答器）：
1. **五个 LangGraph Agent**（indexing / answer / retrieval / search / orchestrator），负责索引、文档问答、ReAct 检索、网络搜索与 URL 分析、UI 侧编排。
2. **长期记忆子系统 `src/memory/`**（LanceDB，`data/memory_db/`，改自 LLM-Memory），已由 chat_ingest 车道与 Orchestrator 的 `search_memory` 子 agent 实际接入。
3. **每日简报批处理管线 `src/pipeline/`**（改自 ai-research-pipeline，已合并进同仓库同进程运行），由 UI 后台 job_runner 车道驱动。

## Development Commands

### 环境准备
```bash
# 安装依赖
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pytest / pytest-asyncio 等

# 创建数据目录（目录不存在时多数组件会自动创建，但建议先建好）
mkdir -p data/pdf data/pdf_image data/json_data data/vector_db data/output \
         data/config data/sessions data/memory_db data/pipeline

# Playwright（web_scraper MCP 需要，见 "MCP Services"）
playwright install chromium
```

### 运行应用

**CLI 模式：**
```bash
python main.py     # 交互式菜单：单文档/跨文档/手动选文档/网络搜索/通用对话
```

**UI 模式（FastAPI + WebSocket）：**
```bash
# 推荐启动方式（跨平台优化，Windows 控制台适配）
python src/ui/run_server.py

# 默认监听 http://127.0.0.1:8000（仅回环，见下），可用环境变量覆盖：
#   HOST=0.0.0.0  （非本机地址会打 WARNING——应用按本地无鉴权设计）
#   PORT=8080
# 等价的手动方式（uvicorn 默认 host 也是 127.0.0.1）：
uvicorn src.ui.backend.app:app --reload --port 8000

# 页面：/ Dashboard、/chat、/config、/data（数据管理，含 Memory tab）、
#       /structure 结构编辑器、/briefs 每日简报、/memory 简报记忆桥接页
# API 文档：/docs、/redoc；健康检查：/health（status/timestamp/version）
```

注意两点与旧文档不同的事实：
- `LOGGING_LEVEL` 环境变量现在**没有被任何代码读取**（README 里仍提及，属过时说明）。日志级别写死在 `src/core/llm/client.py:43` 的 `basicConfig(level=INFO)`，要调 DEBUG 需改这里或在入口自行配置。
- 前端**没有** localStorage 双存储架构——localStorage 仅用于主题偏好（`src/ui/templates/base.html:12` 的 `AgenticReader_theme`），会话数据一律服务端落盘。

### 测试
```bash
# 全量（pytest.ini 已配置 testpaths=tests、pythonpath=.、asyncio_mode=auto）
pytest

# conftest.py 会在缺少 LLM/Embedding 凭据
# （CHAT_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / EMBEDDING_API_KEY）时
# 自动 skip 需要真实调用的脚本式测试文件，无需额外配置。

# 纯 import 冒烟（不联网、不调 LLM）：
.venv/bin/python tests/test_imports.py
# 其余测试大多也是 print 式脚本，可直接 python tests/test_xxx.py 运行
```

## Module Hierarchy

```
src/
├── agents/                   # 五个 Agent + 基类
│   ├── base.py               # AgentBase：provider 选择、LLMBase 创建、
│   │                         #   AGENT_MODEL_OVERRIDES 按 name 查表覆盖模型
│   ├── common/               # 跨 agent 共享 prompts + tool_response_format
│   ├── indexing/             # IndexingAgent（解析→结构→摘要→向量化→注册）
│   │   └── components/metadata_extractor.py  # 注册时的元数据提取
│   ├── answer/               # AnswerAgent（确定性 plan→execute→evaluate→generate）
│   │   └── components/       # document_selector / cross_doc_synthesizer / formatter
│   ├── retrieval/            # RetrievalAgent（ReAct 单文档/多文档检索）
│   ├── search/               # SearchAgent（搜索引擎 + URL 分析，MCP 驱动）
│   └── orchestrator/         # Orchestrator（UI chat 的入口，ReAct 编排）
│       └── sub_agents/       # memory_search（→src.memory）、deep_dive（→AnswerAgent）
├── config/
│   ├── settings.py           # LLM_CONFIG / LLM_EMBEDDING_CONFIG / MCP_CONFIG / 路径
│   ├── constants.py          # ProcessingLimits / RetrievalDedupConfig / PathConstants 等
│   ├── model_overrides.py    # AGENT_MODEL_OVERRIDES：每 agent 单独指定模型
│   └── prompts/              # 仅 metadata_prompts.py（+惰性 SYSTEM_PROMPT_CONFIG 聚合）
├── core/
│   ├── document_management/  # registry.py(DocumentRegistry) / indexer.py / manager.py
│   ├── llm/                  # client.py(LLMBase) / providers.py(azure|openai|ollama|gemini) / history.py
│   ├── parallel/             # indexing.py(ChapterProcessor 等) / retrieval.py(ParallelRetrievalCoordinator)
│   └── vector_db/            # vector_db_client.py(FAISS+轮次去重) / metadata_db.py
├── memory/                   # LanceDB 长期记忆（见 "Memory System"）
│   └── adapters/             # ai_research / webapp_chat / chunking / base
├── pipeline/                 # 每日简报批处理（briefs_parser / queue_store / process_pdf_queue /
│                             #   process_web_queue / sync_* / generate_qa_brief / render_report / paths）
├── services/
│   └── scraper/              # Playwright 网页抓取器包：core(browser/downloader/extractor/
│                             #   anti_detection) / storage / mcp_server(可作 stdio MCP 启动)
├── ui/
│   ├── run_server.py         # 启动入口：HOST/PORT env、reload、Windows 优化
│   ├── backend/
│   │   ├── app.py            # FastAPI 应用 + lifespan（job_runner + chat_ingest 两车道）
│   │   ├── config.py         # CORS_ORIGINS env、默认只放行 localhost 来源
│   │   ├── api/pages.py      # 7 个页面路由；api/websocket.py /ws/chat
│   │   ├── api/v1/           # documents chat pdf structure config
│   │   │                     #   sessions data briefs jobs memory speech llmmemory
│   │   └── services/         # session_manager chat_service chat_ingest job_runner
│   │                         #   memory_browse task_service briefs_data
│   ├── templates/            # base dashboard chat config manage structure_editor briefs memory
│   └── static/               # css/ + js/（api/chat-enhancer/chat/manage/config/structure_editor/briefs）
└── utils/                    # path_guard(safe_path 防目录穿越)、helpers、validators、
                              #   async_utils、json_io(write_json_atomic 唯一实现)
```

各 agent 包遵循同一套结构：`agent.py / nodes.py / tools.py / utils.py / state.py / prompts.py`，agent 类继承 `AgentBase`，nodes 等模块通过构造参数持有 agent 实例（依赖注入）。

## Key Files to Understand

| 文件 | 作用 |
|---|---|
| `main.py` | CLI 入口：菜单选择模式后驱动 AnswerAgent / SearchAgent |
| `src/agents/answer/agent.py:80-126` | AnswerAgent 的图：`rewrite_query → plan →(execute→evaluate→generate \| generate)→ END`，plan 是**确定性**的（按 `enabled_tools` 构造调用，无 LLM 决策），evaluate 只作终止标记、不回环 |
| `src/agents/indexing/agent.py:118-207` | IndexingAgent 主图与 rebuild 图；`_route_on_error` 使任一节点出错都短路直达 register |
| `src/agents/indexing/nodes.py:986-1001` | `register_document` 的失败守卫：state 里有 error 就不把文档注册为 completed |
| `src/core/document_management/registry.py:47` | `DocumentRegistry`：`data/doc_registry.json`，fcntl 跨进程锁 + 原子落盘，锁内重读-改-写事务 |
| `src/core/document_management/indexer.py:123` | `index_pdf_document()`；agents 是函数体内延迟 import（`registry`/`indexer`/`manager` 都不在模块级 import `src.agents`） |
| `src/core/vector_db/vector_db_client.py:46` | FAISS 客户端；检索去重按对话轮次，窗口大小 `RETRIEVAL_DEDUP_WINDOW` |
| `src/agents/orchestrator/agent.py:113` | `ask()`——UI chat 真正的问答路径（ReAct + bind_tools，子 agent 并行执行，轮次/上下文/超时三重护栏） |
| `src/ui/backend/services/chat_service.py:6,231` | UI 聊天全部走 `orchestrator_ask`，AnswerAgent 仅用于手动选文档的校验 |
| `src/ui/backend/app.py:23-54` | lifespan 起两条后台车道：job_runner（串行，写 pipeline_queue）+ chat_ingest（对话入库） |
| `src/ui/backend/services/session_manager.py:93` | 会话落盘为 `data/sessions/{session_id}.json` 平铺文件（旧 mode 子目录自动迁移） |
| `src/config/settings.py:134-162` | embedding provider/模型名/环境变量的**唯一**读取入口 `get_embedding_provider()/get_embedding_model_name()` |
| `src/config/model_overrides.py` | 各 Agent 单独换模型的调优入口（按 AgentBase 的 name 查表） |
| `src/utils/path_guard.py:43` | `safe_path()`：所有按 doc_name 拼数据目录的 API 都要过它（documents/pdf/structure/data 等模块已在用） |

## Key Data Structures

Agent 状态全部是 TypedDict（各 agent 包内 `state.py`），直接喂给 LangGraph 图：

**IndexingState**：`doc_name / doc_path / doc_type("pdf"|"url") / pdf_data_list(逐页解析结果) /
agenda_dict(目录 {title:[pages]}) / has_toc / stage_status(缓存跳过分) / agenda_data_list(章节数据) /
chapter_summaries + chapter_refactors / brief_summary / generated_files /
index_path / status / error / is_complete`。`error` 被置位即触发各节点的 `_route_on_error` 短路。

**AnswerState**：`user_query / rewritten_query(rewrite_query 节点产物) / enabled_tools /
selected_docs / tool_calls([{tool,args}]) / tool_results([{tool,args,result,success}]) /
final_answer / is_complete / error`（`current_iteration/max_iterations` 仅为兼容保留字段，单轮架构
不再有多轮回环）。

**RetrievalState**（ReAct 循环用）：`query / rewritten_query / doc_name(None=多文档) /
actions / observations / current_tool / retrieved_content / intermediate_summary /
reason(evaluate 输出) / final_summary / selected_pages / is_complete`。

**SearchState**：`query / use_case / detected_use_case / search_engine_results / selected_urls /
scraped_results / content_size / processing_strategy("direct_chat"|"index_then_chat") /
should_call_indexing / web_content_json / final_answer / sources / warnings`。

**DocumentRegistry 记录**（`data/doc_registry.json`，schema 见 `registry.py:52-78` 类注释）：
`doc_id / doc_name / doc_path / doc_type / index_path / brief_summary / status / metadata /
generated_files{images,json_data,vector_db,summaries} / processing_stages{stage: {status,
output_files, updated_at}}`。CLI 与 UI 都只信 `index_path` 存在且向量库目录实际存在的记录。

## Architecture Patterns

- **LangGraph StateGraph + TypedDict 状态**：每个 agent 图在 `build_graph()` 编译；state 即 agent 包的 `state.py`。
- **确定性与 ReAct 的分工**：AnswerAgent 的 plan 是纯代码按 `enabled_tools` 生成工具调用（工具名见 `src/agents/answer/tools_config.py` 的 `ANSWER_TOOLS`：`retrieve_documents` / `search_web`）；RetrievalAgent、Orchestrator、`src/memory/search.agentic_search` 才是 LLM 自主决策的 ReAct 循环。
- **core/config 与 agents 的模块级 import 已断开**：`src/core/**` 与 `src/config/**` 现在**零处**在模块级 import `src.agents`——全部延迟到函数体内（例如 `src/core/document_management/indexer.py:62`、`src/core/parallel/indexing.py:79-82`、`src/config/prompts/__init__.py` 的 `_build_system_prompt_config()` 惰性聚合各 agent prompts）。新增这类 import 时务必保持函数级，否则会重新拖上 langgraph 依赖链。
- **并发写 JSON 状态文件的统一范式**：`write_json_atomic()`（唯一实现在 `src/utils/json_io.py`，tmp+os.replace，tmp 名带 pid+tid 防多线程抢写；`src/pipeline/paths.py` 保留 re-export 兼容）+ 独立 `.lock` 文件的 flock 事务，DocumentRegistry、pipeline queue_store、会话/任务/app_config 落盘共用同一套；POSIX 下 fcntl，Windows 退化进程内锁（见 registry.py 注释）。
- **并发检索**：`src/core/parallel/`——索引期 ChapterProcessor 并行章节摘要/重构，检索期 ParallelRetrievalCoordinator 多文档并行调 RetrievalAgent。
- **检索去重是"按轮次窗口"而非永久黑名单**：`RetrievalDedupConfig`（`src/config/constants.py:36-53`，默认 5 轮，env `RETRIEVAL_DEDUP_WINDOW` 可覆盖），超窗记录自动淘汰。
- **Orchestrator 的护栏**：`MAX_ITERATIONS=15`、累计上下文 >120k 字符强制收尾、整轮工具全错连续 2 次提前收尾、900s 墙钟预算（`src/agents/orchestrator/agent.py:32-41`）。多个 tool_calls 一律 `asyncio.gather` 并行。
- **Provider 单一入口**：代码兜底默认一律是 `openai`（AgentBase / LLMBase / `load_config()`），
  但"这次用哪个 provider"的决定权统一收在 `settings.resolve_provider()`——见 Env Variables
  的 Provider 一节；新增构造点不要自己写死字面量。

## Data Flow

### 文档索引（UI 与 CLI 共用同一条图）
```
UI: /api/v1/documents/upload → documents.py 落盘 data/pdf/
    /index → IndexingAgent.graph
CLI: main.py [i] → core/document_management/indexer.py index_pdf_document()
两者最终都走：
  check_cache → parse → extract_structure → chunk → process_chapters
  → build_index → generate_brief_summary → register
任何节点置 error → 短路直达 register，且 register 的守卫保证失败文档
不会被标成 completed / 不会出现在可检索列表里。
产物：data/pdf_image/、data/json_data/{doc}/、data/vector_db/{doc}_data_index/、
     data/output/、data/doc_registry.json（status/processing_stages 跟踪）。
```

### 对话
- **CLI**（`main.py`）：四种绑定模式最终都调 `AnswerAgent.query()` / graph.ainvoke——单文档、跨文档自动选档（DocumentSelector 按 registry 的 brief_summary 选）、跨文档手动选档、通用模式；网络搜索模式 [w] 直接调 `SearchAgent.search()`（provider 走 `settings.resolve_provider(None)`：app_config.json → env `PROVIDER` → openai）。
- **UI**：`/ws/chat` 或 `/api/v1/chat/initialize` → `chat_service.chat()` → **Orchestrator.ask()**。Orchestrator 的 LLM 自主决定调用 `search_memory`（同进程直调 `src.memory.search.agentic_search`，namespace 缺省全部）和/或 `deep_dive_document`（调 AnswerAgent 深挖某 doc 原文）。会话消息经 SessionManager 存 `data/sessions/{id}.json`，消息带 `agents_used` 展示标签。
- **SearchAgent**（`src/agents/search/`）：双 use case——搜索引擎检索（DuckDuckGo MCP 搜索 → 选 URL → web_scraper MCP 爬取）或 URL 分析（直接爬取；内容超阈值自动调 IndexingAgent 索引后转文档对话式回答，策略字段 `index_then_chat`/`direct_chat`）。

### 每日简报管线（UI 后台驱动）
```
BRIEFS_DIR 下 HTML（env BRIEFS_DIR，默认 ~/Desktop/AATF-Intelligence-Briefs）
→ briefs 页面 /api/v1/briefs 勾选"加载"（或 CLI python -m src.pipeline.sync_pipeline_queue）
→ data/pipeline/pipeline_queue.json（queue_store.py 是唯一允许写它的模块）
→ job_runner 后台车道（串行 + asyncio.wait_for 超时，状态落 data/pipeline/webapp_jobs.json）
→ process_pdf_queue / process_web_queue：下载/爬取 → IndexingAgent+AnswerAgent(+SearchAgent)
  六/五维度问答 → generate_qa_brief 提炼 → 摘要 JSON 落 data/pipeline/summaries/{pdf,web}/
  → ingest_source() 写入 memory namespace "ai-research" → 失败超 MAX_ATTEMPTS=3 转 failed_permanent
→ 独立 CLI 可选：python -m src.pipeline.render_report / sync_memory_ingest / generate_qa_brief
```

## Memory System

`src/memory/` 已实际接入（不是 planned），独立 LanceDB 库 `data/memory_db/`（表 `memories`，单表单层，namespace 隔离）：

- **namespace 约定**（`src/memory/config.py:27-28`）：`ai-research`（论文/文章摘要，source_id=doc_name）与 `webapp-chat`（对话历史）。
- **两条写入通道**：
  1. 管线：`process_pdf_queue`/`process_web_queue` 处理完即调 `ingest_source()`；`src/pipeline/sync_memory_ingest.py` 补历史欠账。
  2. **chat_ingest 车道**（`src/ui/backend/services/chat_ingest.py`）：与 job_runner 并行的独立后台任务，周期扫描 `data/sessions/` 把"有新内容 + 已静默一段时间 + 至少一轮完整问答"的会话写入 `webapp-chat`；水位线记 `data/pipeline/chat_ingest_state.json`；按 chunk 内容 hash 幂等去重。
- **读取路径**：Orchestrator 的 `search_memory` 子 agent → `agentic_search()`（semantic/keyword/keywords-pool/list-by-source 四工具的 ReAct 循环，MAX_ITERATIONS=4）。
- **浏览/管理 API**：`/api/v1/memory/*`（overview / namespace 列表 / search / 删除——含 item、
  namespace、按 source 三种 DELETE；单条 item 的 GET 读取端点已删），供 `/data` 页 Memory tab
  使用，实现是 `services/memory_browse.py` 同进程直调。
- **LLM-Memory 桥**：`/api/v1/llmmemory/*` 是对**外部** LLM-Memory webui（env `LLM_MEMORY_URL`，默认 `http://127.0.0.1:8765`）的透明 HTTP 代理，供 `/memory` 页简报管线用——与本仓库的 src/memory 是两套东西，别混。
- **Embedding 维度**：LanceDB 建表需要固定维度，`src/memory/config.py` 维护模型名→维度映射表；配置缺失只 warning 并按默认 1536 建表。改 embedding 模型名务必走 `settings.get_embedding_model_name()`。

## MCP Services

`MCP_CONFIG`（`src/config/settings.py`）当前启用的条目：
- `"duckduckgo"`：`uvx duckduckgo-mcp-server`（SearchAgent 的 web_search 用它，需单独安装 uvx/该包）。
- `"web_scraper"`：`sys.executable -m scraper.mcp_server.server`，env `PYTHONPATH=src/services`——即 `src/services/scraper/` 自带的 Playwright 抓取 MCP server。
- 历史的 `"ddg-search"` 本地脚本条目（`src/services/duckduckgo_mcp_server.py`）与 `mcp_server_fetch` 注释条目已随重构删除。

MCP 客户端实现是 `src/agents/search/utils.py` 里的 `SimpleMCPClient`（stdio 传输，
`mcp` 库的 ClientSession；历史上的 `src/services/mcp_client.py` 已删除——它只被
SearchAgent 用到 stdio 一种传输，薄封装就地维护即可）。

## Environment Variables

**LLM 凭据/模型（settings.py）**：
- Azure：`CHAT_API_KEY`、`CHAT_API_VERSION`、`CHAT_AZURE_ENDPOINT`、`CHAT_DEPLOYMENT_NAME`、`CHAT_MODEL_NAME`
- OpenAI：`OPENAI_API_KEY`、`OPENAI_MODEL_NAME`（默认 gpt-3.5-turbo）、`OPENAI_BASE_URL`
- Ollama：`OLLAMA_BASE_URL`（默认 :11434）、`OLLAMA_MODEL_NAME`
- Gemini：`GEMINI_API_KEY`、`GEMINI_MODEL_NAME`、`GEMINI_BASE_URL`
- Embedding：`EMBEDDING_API_KEY/API_VERSION/AZURE_ENDPOINT/DEPLOYMENT/MODEL`、`OPENAI_EMBEDDING_MODEL`、`OLLAMA_EMBEDDING_MODEL`、`GEMINI_EMBEDDING_MODEL`、`EMBEDDING_PROVIDER`（默认 openai——该键以前不存在，现是 provider 选择的唯一入口）

**运行时行为**：
- `HOST` / `PORT`：`run_server.py`，默认 `127.0.0.1`/`8000`，非回环 HOST 打 WARNING
- `CORS_ORIGINS`：逗号分隔来源列表，默认只放行 localhost/127.0.0.1:8000；含 `*` 时自动关闭 `allow_credentials`
- `RETRIEVAL_DEDUP_WINDOW`：检索去重轮次窗口（默认 5）
- `BRIEFS_DIR`：简报 HTML 目录
- `LLM_MEMORY_URL`：外部 LLM-Memory webui 地址（/memory 页桥接）

**Provider 配置来源——CLI 与 UI 的差异**：
- **唯一入口**：`settings.resolve_provider(provider)` / `get_default_provider()`
  （`src/config/settings.py`）。优先级：显式传参 > `data/config/app_config.json`
  的 provider > env `PROVIDER` > `"openai"`。所有此前写死 "openai" 的链路
  （chat_ingest、job_runner、memory 搜索 API、process_web_queue、Orchestrator
  及其子 agent、CLI 搜索、IndexRequest）都已改走这个入口。
- UI：`/config` 页 → `/api/v1/config` 读写 `app_config.json`；chat_service 把
  load_config() 的 provider 传给 `Orchestrator.ask(provider=...)`，ask 解析一次
  并下发给 deep_dive_document / search_memory 子 agent——一次提问全链路同一个
  provider；AnswerAgent 校验实例按 provider 缓存，换配置自然失效。
- CLI（main.py）：无 UI 配置时按 env `PROVIDER` 回退；模型名由 env 变量 +
  `model_overrides.py` 控制。

## REST API Quick Reference（当前全部实际路由）

前缀均为 `/api/v1`，注册于 `app.py:89-103`。`/` 开头的是页面路由。

```
Pages:   GET /  /chat  /config  /data  /structure  /briefs  /memory
WS:      /ws/chat                     # 唯一的 WebSocket（origin 校验见 websocket.py）
Health:  GET /health                  # app.py 内联定义

documents: GET /list /available-pdfs | POST /upload /index | DELETE /{doc_name}
chat:      POST /initialize /clear    | GET  /load-more-messages
sessions:  GET /list /current/info /{id} | DELETE /{id} | PATCH /{id}/rename
pdf:       GET /view/{doc_name}                   # 页面图（专用 images/image 路由已删，走 view 降级）
structure: GET|PUT /{doc_name} | POST /{doc_name}/rebuild
config:    GET "" | POST /provider /system /reset       # 落 data/config/app_config.json
data:      GET /overview /documents /documents/{name}/summary /documents/pending
           /sessions/stats /tasks/{task_id}
           POST /documents/{name}/index  DELETE /pdfs /documents/{name}/parts /documents
           POST /cleanup/smart?days=N
briefs:    GET /dates /cards  | POST /load /sync-memory # 数据层 services/briefs_data.py
jobs:      GET "" | POST /{job_id}/retry /cancel        # 任务账本见 job_runner + webapp_jobs.json
memory:    GET /overview /namespace/{ns} / POST /search
           DELETE /item/{id} /namespace/{ns}/source/{source_id} /namespace/{ns}
speech:    POST /transcribe /synthesize
llmmemory: GET /dates /papers ... 等                    # 外部 webui 透传代理（见上节）
```

## UI Features（现状速览）

- FastAPI + Jinja2 + 原生 ES6 JS，无框架；WebSocket `/ws/chat` 实时对话，REST 做初始化/历史分页。
- **UI 聊天走 Orchestrator 而非 AnswerAgent**：`enabled_tools`/`selected_docs` 只是透传给会话上下文的元数据，真正的工具决策在 Orchestrator 的 ReAct 循环里；`agents_used` 由子 agent name 映射成展示标签（MemorySearch/DeepDive）。
- 会话存储：`data/sessions/{session_id}.json` 平铺（SessionManager 自动迁移旧 mode 子目录）；会话 API 为 list/current-info/get/delete/rename——**没有** import/export 端点。
- 数据管理页 `/data`：总览、按文档列 JSON/向量库/图片/摘要四类产物、部分/批量删除（`/api/v1/data/documents/{name}/parts`）、smart cleanup、sessions stats，以及 Memory tab（缓存查看/清理、backup、危险的全量 reset 端点已删）。
- PDF 查看：`/api/v1/pdf/view/{doc_name}`（页面图，图片降级内建于 view）。
- 结构编辑器 `/structure`：编辑 structure.json 后走 rebuild 图重生成摘要/索引。
- `/config` 页读写 provider 与系统设置；`/briefs` 页加载简报条目进管线队列；`/memory` 页桥接外部 LLM-Memory。
- 语音：`/api/v1/speech/transcribe|synthesize`（需 OPENAI_API_KEY）。
- 安全面：默认仅回环监听 + 本地 CORS；`safe_path()` 统一防 doc_name 目录穿越。

## Development Patterns

- **给 AnswerAgent 加新工具**：三处要一致——`tools_config.py` 的 `ANSWER_TOOLS` 注册表（描述/参数）、
  `tools.py` 的工具实现、`nodes.py` 的 `_dispatch_tool` 分发；且 `plan` 节点的
  `_build_tool_calls_from_user_selection` 是逐条 if/elif 按 `enabled_tools` 名字构造调用的
  （nodes.py:377-398 现只有 `retrieve_documents`/`search_web` 两分支），新工具要在那里加分支，
  并同步前端可选工具列表（chat-enhancer / chat.js）。
- **新增顶层 Agent**：建 `src/agents/<name>/` 六件套包 → `agent.py` 继承 `AgentBase`（name 参数同时
  用于 `AGENT_MODEL_OVERRIDES` 查表）→ 需要被 Orchestrator 调用的话在 `sub_agents/` 实现 SubAgent
  子类并注册进 `SUB_AGENTS` 字典 → 在 `tests/test_imports.py` 的模块清单里加一行。
- **写新的共享状态 JSON**：一律用 `src/utils/json_io.py:write_json_atomic()`（`src.pipeline.paths` 亦有 re-export）+ 独立 `.lock` 文件
  的 flock 事务（参考 `registry.py:_transaction` 与 `queue_store.queue_transaction`），不要裸
  open+json.dump 写状态文件。
- **新数据目录**：路径常量加进 `src/config/constants.py:PathConstants`，需要自动创建的在入口
  `makedir()`（indexing 的 `_setup_pdf_config` 是现成示例）。
- **UI 加 API 端点**：`api/v1/<module>.py` 加路由 → `app.py` include_router（若整个新模块）→ 前端
  在对应 js 里走 `api.js` 封装；涉及 doc_name 拼路径必过 `safe_path()`。

## Testing Notes

- `pytest.ini` + `tests/conftest.py`：缺 LLM 凭据时相关脚本式测试自动 skip；纯逻辑用例可直接跑。
- `tests/test_imports.py` 是零依赖冒烟基线，重构后先跑它。
- 涉及索引/问答的脚本测试（test_indexing_agent.py 等）会真实调 LLM，需凭据。
```
