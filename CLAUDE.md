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
#       /structure 结构编辑器、/briefs 每日简报（含轻量入库）；/memory 已退役→302 到 /briefs
# API 文档：/docs、/redoc；健康检查：/health（status/timestamp/version）
```

注意两点与旧文档不同的事实：
- `LOGGING_LEVEL` 环境变量现在**没有被任何代码读取**（README 里仍提及，属过时说明）。应用日志级别来自各入口的 `logging.basicConfig(level=INFO)`——全仓 5 处（`src/core/llm/client.py:45`、`src/core/vector_db/vector_db_client.py:16`、`src/core/document_management/{indexer,manager}.py:41/45`、`main.py:32`），Python 语义下只有第一个生效者算数，其余静默无效；uvicorn 的访问日志级别则读 `data/config/app_config.json` 的 `log_level` 键（`src/ui/run_server.py:resolve_log_level`，/config 页写入的就是它，无效值退 info）。
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
│   ├── answer/               # AnswerAgent（确定性 plan→execute→generate，evaluate 节点已删）
│   │   └── components/       # document_selector / cross_doc_synthesizer / formatter
│   ├── retrieval/            # RetrievalAgent（ReAct 单文档/多文档检索）
│   ├── search/               # SearchAgent（搜索引擎 + URL 分析，MCP 驱动）
│   └── orchestrator/         # Orchestrator（UI chat 的入口，ReAct 编排）
│       └── sub_agents/       # memory_search（→src.memory）、deep_dive（→AnswerAgent）
│                             #   search_web（→SearchAgent；要会话开开关才进）
│                             #   ALWAYS_ON_TOOLS = 前两个，恒开
├── config/
│   ├── settings.py           # LLM_CONFIG / LLM_EMBEDDING_CONFIG / MCP_CONFIG / 路径
│   ├── constants.py          # ProcessingLimits / RetrievalDedupConfig / PathConstants 等
│   ├── model_overrides.py    # AGENT_MODEL_OVERRIDES：每 agent 单独指定模型
│   └── prompts/              # 仅 metadata_prompts.py（+惰性 SYSTEM_PROMPT_CONFIG 聚合）
├── core/
│   ├── document_management/  # registry.py(DocumentRegistry) / indexer.py(index_pdf_document) /
│   │                         #   delete_service.py(delete_document_service 唯一删除实现) / manager.py
│   ├── llm/                  # client.py(LLMBase) / providers.py(azure|openai|ollama|gemini) / history.py
│   ├── parallel/             # indexing.py(ChapterProcessor 等) / retrieval.py(ParallelRetrievalCoordinator)
│   └── vector_db/            # vector_db_client.py(FAISS+轮次去重) / metadata_db.py
├── memory/                   # LanceDB 长期记忆（见 "Memory System"）
│   ├── gateway.py            # 读写/浏览/删除的唯一出入口 + 上游/本地选路的唯一决策点
│   │                        #   （search/ingest 的 auto 路由；delete_* 已接上游且保持 sync；
│   │                        #    browse_* 仍是本地库原语）
│   │                        #   + load_brief_date 驱动分派
│   │                        #   + 上游 LLM-Memory 门面转发（namespace 收敛在这层做）
│   ├── upstream.py           # 外部 LLM-Memory 访问层：SDK 进程内为主 + 可选 MCP stdio 决策面
│   │                        #   （写路也在此层，"只读"纪律因收敛有意反转——见 Memory System）
│   ├── brief_ingest.py      # /briefs"轻量入库"的实现体：卡片解析后交上游 ingest(source_type=brief)
│   │                        #   （旧的"零 LLM 直写 AATF"承诺已作废，见 Memory System 收敛段；
│   │                        #    本地直写只是上游不可用时的回落形态）
│   │                        #   （一次性 A→B 库迁移另见 migrate_aatf.py，
│   │                        #    python -m src.memory.migrate_aatf --dry-run）
│   ├── converge.py           # 存量重灌（Phase 3）单文件 CLI：三源整批递上游，只写上游不回退本地
│   │                        #   （dry-run 缺省·零写入连 MemoryClient 都不构造；--apply 逐条计数；
│   │                        #    --only/--since/--until/--limit 节流；--retire-old-db 只是占位）
│   └── adapters/             # ai_research / webapp_chat / chunking / base
├── pipeline/                 # 每日简报批处理（briefs_parser / queue_store / common(队列处理骨架) / process_pdf_queue /
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
│   │   │                     #   sessions data+data_storage+data_ops+data_common
│   │   │                     #   briefs jobs memory speech（llmmemory 已随 /memory 页退役）
│   │   └── services/         # session_manager chat_service chat_ingest job_runner
│   │                         #   memory_browse task_service briefs_data
│   ├── templates/            # base dashboard chat config manage structure_editor briefs
│   └── static/               # css/（base/components/variables/api/chat/chat-enhanced/
│                             #   config/dashboard/manage/briefs 等）+ js/
│                             #   （api=fetch 唯一出口 / ui-feedback=共享 toast /
│                             #   pdf-viewer=pdf.js 原语 / utils / ui-components /
│                             #   chat-enhancer/chat/manage/config/structure_editor/
│                             #   briefs/dashboard/base-badge）
└── utils/                    # path_guard(safe_path 防目录穿越)、helpers、validators、
                              #   async_utils、json_io(write_json_atomic 唯一实现)、
                              #   file_operations（其中 read_file_with_encoding_detection
                              #   目前全仓零调用点，chardet 降级路因此静默——见 Testing Notes）
```

各 agent 包遵循同一套结构：`agent.py / nodes.py / tools.py / utils.py / state.py / prompts.py`，agent 类继承 `AgentBase`，nodes 等模块通过构造参数持有 agent 实例（依赖注入）。

## Key Files to Understand

| 文件 | 作用 |
|---|---|
| `main.py` | CLI 入口：菜单选择模式后驱动 AnswerAgent / SearchAgent |
| `src/agents/answer/agent.py:113-154` | AnswerAgent 的图：`rewrite_query → plan →(execute→generate \| generate)→ END`，plan 是**确定性**的（按 `enabled_tools` 构造调用，无 LLM 决策），单轮无回环（execute 之后直接进 generate，不再经过 evaluate 节点） |
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
| `src/memory/gateway.py` | 记忆的唯一出入口 **+ 上游/本地选路的唯一决策点**：`search()`/`ingest()` 内含 auto 路由（上游可用→转 `upstream.py`，否则本地旧路 + warning），`delete_*` 走上游且保持 sync；`MEMORY_STORE_MODE=local` 是强制旧路的 kill switch；上游 33 列行→14 列形状也在这层的映射层摊平。调用方（chat_ingest / pipeline×2 / sync_memory_ingest）签名不动 |

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
- **UI**：`/ws/chat` 或 `/api/v1/chat/initialize` → `chat_service.chat()` → **Orchestrator.ask()**。Orchestrator 的 LLM 自主决定调用 `search_memory`（同进程直调 `src.memory.search.agentic_search`，缺省作用域是自库白名单 ai-research + webapp-chat，session 级 `memory_namespaces` 可放宽到 AATF）、`deep_dive_document`（调 AnswerAgent 深挖某 doc 原文）与第三个子 agent `search_web`（→ `src.agents.search.SearchAgent`：DuckDuckGo MCP 搜索 / URL 抓取；仅在会话开启网络搜索时才进工具集）。长会话历史由 `session_manager.history_for_llm_async` 做窗口化——最近 20 条原文 + 更早部分做增量摘要，`MAX_CONTEXT_CHARS` 从首轮请求就检查，摘要失败退化为纯截断。会话消息经 SessionManager 存 `data/sessions/{id}.json`，消息带 `agents_used` 展示标签与本轮 `memory_hits`（供 UI 渲染"提及论文"条目）。
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

- **namespace 约定**（`src/memory/config.py:27-33`）：`ai-research`（论文/文章摘要，source_id=doc_name）、`webapp-chat`（对话历史）与 `AATF`（本地简报卡片导读，source_id=item_id；DA 裁决"本地 brief 落对话同库"的落点）。
- **三条写入通道**：
  1. 管线：`process_pdf_queue`/`process_web_queue` 处理完即调 `ingest_source()`（`ai-research`）；`src/pipeline/sync_memory_ingest.py` 补历史欠账。
  2. **chat_ingest 车道**（`src/ui/backend/services/chat_ingest.py`）：与 job_runner 并行的独立后台任务，周期扫描 `data/sessions/` 把"有新内容 + 已静默一段时间 + 至少一轮完整问答"的会话写入 `webapp-chat`；水位线记 `data/pipeline/chat_ingest_state.json`；按 chunk 内容 hash 幂等去重。
  3. **轻量入库**（`src/memory/brief_ingest.py`，由 `/briefs` 页"轻量入库(全天)"经 `job_runner` 的 `load_brief_date` 任务触发）：解析 `BRIEFS_DIR` 该天 HTML 卡片——**收敛后这不再是"零 LLM 直写 AATF"**，卡片交出去走上游 `ingest(source_type=brief)` 的 agentic 抽取，本地直写只是上游不可用时的回落形态；"这卡/这天入库了没有"的判据也跟着从 chunk-hash 换成上游报回来的 `chunks_added == 0`。
- **读取路径**：Orchestrator 的 `search_memory` 子 agent → `agentic_search()`（semantic/keyword/keywords-pool/list-by-source 四工具的 ReAct 循环，MAX_ITERATIONS=4）；缺省作用域是自库白名单（ai-research + webapp-chat），AATF 需在 /chat 的记忆范围浮层里勾选。
- **浏览/管理 API**：`/api/v1/memory/*`（overview / namespace 列表 / search / 删除——含 item、
  namespace、按 source 三种 DELETE；单条 item 的 GET 读取端点已删），供 `/data` 页 Memory tab
  使用，实现是 `services/memory_browse.py` 同进程直调。
- **外部 LLM-Memory 上游门面**：上游 LLM-Memory 走**进程内 SDK 为主**（env `LLM_MEMORY_REPO` 指向上游 checkout，向 `sys.path` 注入 `<repo>/src` 后 `from llm_memoryd.api import MemoryClient`，未设/路径无效即一律降级为 `available:false` + note，不 raise 不出网）+ **可选 MCP stdio 决策面**（env `LLM_MEMORY_MCP_ENABLED=1`，子进程按 `settings.MCP_CONFIG["llm_memory"]` 单源构建并继承 `os.environ`，起 `python -m llm_memoryd.mcp --tools memory_why,memory_pack`——why/pack 要 `--tools` 显式开，默认关）。只读面三端点，全走 gateway 门面：`GET /api/v1/memory/upstream`（status 字段 available + namespaces/rows + version，内嵌 `decision:{enabled,available,note}` 开关位）、`POST /api/v1/memory/upstream/search`、`POST /api/v1/memory/upstream/decision`（memory_why/memory_pack 白名单一跳直通，remember/ingest 这类写工具不在面上）。**上游只读检索缺省作用域=全局**——不给 namespace 就跨 store 全量、返回 `scoped=False`，显式单 ns 或列表才收窄；**没有"默认按自库白名单搜上游"这回事**，文档/测试都别再钉那个错语义。版本显示口径：SDK 面报 `llm_memoryd.__version__`（实测量级 0.1.0），上游 stdio 面 serverInfo 报 1.0.0——上游自己的常量漂移，AR 侧只如实显示不作映射，排查时知道这两处数字不会一致即可。**旧 webui HTTP 桥已彻底退役**：`load_brief_date` driver 白名单收敛为 `local` 一条路，`MEMORY_BRIEF_DRIVER=bridge` 与 `LLM_MEMORY_URL` 双双退役（设了也 warning→local，仓内无任何对 8765 的调用）；外部"加载某天简报"这条**桥路**能力退役后**没有任何 HTTP 替身**（仓内不再有人调 8765）——注意退役的是"经桥读写"，brief 入库这条写路本身还在，只是收敛后经 `gateway.ingest()` 递上游 `ingest(source_type=brief)`，本地直写退居回落；缺的是桥，不是入库能力；原 `/memory` 页与其透明 HTTP 代理 `/api/v1/llmmemory/*` 先一步退役，页面职责并进了 `/briefs`（重管线 = `/load`，轻量入库 = `/light-load`；老书签 `/memory` 302 到 `/briefs`）。
- **Embedding 维度**：LanceDB 建表需要固定维度，`src/memory/config.py` 维护模型名→维度映射表；配置缺失只 warning 并按默认 1536 建表。改 embedding 模型名务必走 `settings.get_embedding_model_name()`。

### 记忆收敛（Phase 1–3 · 写/读/删路由到上游 + 存量重灌）

存储层仍由本层（`src/memory/`）维护，外部 LLM-Memory 只是被寻址的上游；**新增的唯一决策点是 gateway 的 auto 路由**——`search()` / `ingest()` 内部选路（上游可用→转 `upstream.py`，否则本地旧路 + warning），四个调用方（chat_ingest / `process_pdf_queue` / `process_web_queue` / `sync_memory_ingest`）**签名零改动**。

- **写路也在 `upstream.py`**：`upstream_ingest(path, source_type, namespace, source_id)` → `to_thread(client.ingest, ...)`。该层"全段只读"的旧纪律**有意反转**——写也走它，统一 to_thread + 失败折叠（这层返回 `{available:false, error, note}` 形状，不 raise、不上浮）。
- **读写唯一的语义差别：写不回落**。`_route_is_upstream()` 只回答"上游这条路开不开"，回落与否由调用侧自己定：`search()` 上游不可用/这次没成可以回落本地，`ingest()` **绝不**——上游可用但写失败时 gateway 把折叠结果 `raise RuntimeError` 出去（返回 dict 会被三个调用方当成功，`common.py` 直接置 `memory_ingested=True`），让 chat_ingest 的水位线与 job_runner 的任务账本照常记一笔失败，不"顺手写一份本地"（那是双写：同一份内容两处落库、水位线还照推，补灌时说不清该怪谁）。要整体退回本地只有重试或 unset `LLM_MEMORY_REPO`／`MEMORY_STORE_MODE=local`。
- **通道现状**：看这把开关的是 `gateway.search()` / `gateway.ingest()` **加上** `gateway.delete_*` 一组，`browse_*` 浏览原语与 `load_brief_date` 的驱动分派仍不碰它；mode 取值单一来源在 `src/memory/config.py` 的 `get_memory_store_mode()`（非法取值按白名单 warning→`auto`，消费方只有 gateway 一处）。三条写通道都已接 auto 路由：管线 `ai-research`、chat_ingest `webapp-chat`、`/briefs` 轻量入库 `AATF`。轻量入库递的是"卡片 JSON + 上游 `ingest(source_type=brief)`"，**source_id 沿用 item_id，id 空间没有换轨**——原先预告的 `aatf-<date>-<kind>` 因上游补了 `source_id` 透传而省掉，"先做双读兼容再切"那句一并作废（代价是轻量入库不再是零 LLM，见已知代价）。
- **PDF 对话侧不住这层，也不是"另一个记忆库"**：文档索引/对话的持久化是 `data/vector_db/{doc}_data_index/` 的 per-doc FAISS 加 `data/sessions/{id}.json` 会话落盘，本次收敛一个字节都没碰——"PDF 对话 memory 保持独立"这条约束落在**架构分层**（两套东西）上，别在文档里另开一段去找一个不存在的第三库。
- **读路映射层**：上游 33 列的行在 gateway 摊平成子 agent 现在吃的 14 列形状（本地形状 = 12 text + vector + importance；`occurred_at/source_id/abstract/detail/keywords/raw_source/memory_type/source_type` 全留，多出的 tier/abstracts_chain/session_id 之类列**整列丢掉**——"不多给任何一个键"是这层的验收线，"顺手多给一列"算越界）。`chunk_hash` 的口径要说准：**上游 schema 里有这列**（summary 行取 `""`），只是它自己的 `shape_result_row` 裁过输出、不把这列交给结果行——所以映射层是**保真优先**：`row` 里带了 `chunk_hash` 就直接用真值，交不出来时才动用"keywords 空 + detail 偏长（≥2000 字）→ 像是整篇摘要行"的启发式，猜不准填 `"unknown"`；启发式是**模拟不是保真**，别把它当上游语义。summary 判据在本地是 `chunk_hash==""`，这层只是把同一判据换个来源喂进去，猜错只影响 `is_summary_row` 的展示位、不影响检索命中。`occurred_at` 为空时回退 `created_at`（与 `src/memory/search.py:168` 与本地 `vector_store.shape_result_row` 那条 fallback 同构），`/briefs` 的按日聚合照旧可用。
- **幂等归上游**：走上游时 AR 侧不再自己算 chunk-hash，去重交给上游 ingest 的 hash-dedup（同一文件再递一次应返回 0 新增，这条要由测试钉死；豁免旧禁令 #3 的对价就是这个新契约）。**"是否已入库"的判据跟着变了**：上游路上看的是 report 里的 `chunks_added == 0`（等价于"东西早就在了"，不是失败也不是空跑），而不是 chunk-hash；`/briefs` 的 memory-status 之类"这一天进没进来"的口径要用这个数，别拿旧 chunk-hash 那套去推。回落本地旧路时，原来的内容 hash 幂等依旧成立——上面"三条写入通道"里写的 chunk-hash 说法对 local 路仍然正确。
- **delete_* 已接上游，browse_* 仍本地**：三种 DELETE（item / namespace / source）走 `gateway.delete_*` → 上游 `delete`/`delete_where`，带两个边界守卫——**跨 namespace 的 id 直接拒**（一个 id 不该能删掉别处的行）、**unscoped 删除一律拒**（既不给 id 也不给 namespace 就被拒，措辞对齐 `memory_browse` 的期待），删除面同样**不回落**；`DELETE /sessions/{id}` 的记忆回收段跟着走上游。**形状有个反直觉的地方：`gateway.delete_*` 三个函数保持 sync**，不是像 `search()`/`ingest()` 那样 async + `to_thread`——上游调用由线程池硬封顶，不让事件循环被拖住的保证交给调用层，别顺手"为了一致性"把它们 async 化。语义要点：删的是**上游存储层**的行，`data/memory_db` 的对应行**不受影响**——两个库现在是两套存储，别按"同一个库里删掉了"理解，也别指望删完还能从本地捞回来。`browse_*` 行级浏览仍是本地库的原语，只是 **overview/namespace 列表的计数层**把上游只读 `namespaces()` 的行数并进来，`/data` 页能同时看到两边各自的计数——那是纯只读的计数并列，不是把行去上游翻一遍。
- **存量不迁移，Phase 3 是"重灌"而不是"搬家"**：`data/sessions/`、`data/pipeline/summaries/{pdf,web}/`、`BRIEFS_DIR` 本身就是可重建的事实源；`data/memory_db` 在收敛生效后转**只读兜底**，回退＝把路径改回来，无数据损失。落地它的单文件 CLI 是 `src/memory/converge.py`：
  - **缺省＝`--dry-run`，一个字节都不写，连 `MemoryClient` 都不构造**——构造它会顺手让上游把 store 目录撑开（`~/.llm-memory/` 里多出 `ingest_state` 之类的空脚手架、mtime 跟着动），与"零写入"的承诺对不上。所以 dry-run 的门只查配置面（env 与 `<repo>/src` 存在性），打印的是"配置面就绪，未连接上游确认"——**通不等于已连上**，可达性留给 `--apply` 那道门。
  - **`--apply` 逐条递**：形状是 `＋N 新增 / M 已存在` 每条一行，末尾汇总"调用次数 → 新增 / 幂等命中 / 失败"；单条失败记一笔继续跑（一个坏文件不该让整批停摆），有失败退 1、全绿退 0、中断退 130、`--dry-run` 与 `--apply` 同时给退 2。
  - **拒跑纪律**：`LLM_MEMORY_REPO` 无效或 `MEMORY_STORE_MODE=local` 时**退 1 并打印理由**——这条批路的契约是"只写上游，不回退本地"，半批进上游半批进旧库最难收场。也因为这个它刻意调 `upstream.upstream_ingest()` 而非 `gateway.ingest()`：gateway 按调用点现探选路，中途上游掉线会照常驻契约把那一条写本地，方向正好相反。
  - **节流旗标**：`--only {summaries,sessions,briefs}`、`--since/--until`（**闭区间**日期，形状写错直接报错、不当"没有这天"静默略过）、`--limit N`（每个源分别截断）。成本是实打实的：`BRIEFS_DIR` 按 69 天存量算就是几千次 agentic 抽取，先 dry-run 看规模再分片推。
  - **幂等靠上游 hash-dedup**，没有断点账本也不需要——Ctrl-C 落在源边界，再跑一次自动续上。
  - **`--retire-old-db` 是占位**：只打印"未执行"。旧库退役（把 `data/memory_db` 改名）是 `--apply` 之后**单独**的一步，做不做、怎么做由用户拍板，CLI 不代做。
- **已知代价（文档级事实，不是 bug）**：① 记忆侧 LLM/嵌入配置归**上游 config** 管，AR 的 `/config` 页与 `resolve_provider` 链都管不到记忆侧——选路只决定"写哪读哪"，provider 解析链不改这一点；上游嵌入端点当前是局域网地址，机器不在该网段则**路由层面就判不可用**、整条记忆读写落本地旧库（写侧这类"没开起来"是落本地的，"开起来了但写失败"才 raise，见上）。② AR 递"已摘要文件"，上游 ingest 会再抽一遍，同一份内容过两轮 LLM（`qa`/`qa_brief` 字段可显式传下去当现成摘要省掉二次抽取，ai_research adapter 直接吃这字段）。③ 上游全同步、写路也全程 `to_thread`，写超时**没有** cancel 通道，只有等待侧硬 cap；`gateway.delete_*` 这组是例外——它们**保持 sync**，上游调用由线程池硬封顶，事件循环不被拖住的保证交给调用层。④ **"轻量入库(全天)"的零 LLM 旧承诺作废**——上游跑 agentic 抽取，一张卡片一轮，卡片多的那天明显变慢；"这天/这卡进没进"的判据也从 chunk-hash 换成上游报的 `chunks_added == 0`。
- **上游补丁的状态（已更新，别再用旧口径）**：delete facade、`source_type=brief` 枚举、`ingest` 的 `source_id` 透传这三件**已经在上游 main 里**——是用户侧自己提交的（`888f966` 把三件全部纳入，`f181999` 补 docs，已推 github/main，HEAD `f181999`；AR 侧探针对新 HEAD 也 15/15 过），**不是本仓做的合入**，本仓一条都没往上游推。`tools/upstream-patches/` 的三片保留作**历史参照**：当时的走法是在 `/tmp` 干净克隆里叠 01 → 02 → 03 先验一遍（各自 `git apply --check` 干净、叠满后上游全量套件 2114 passed / 4 skipped 绿，pyflakes 门与"不广告破坏性工具"的 MCP 纪律都没碰坏），验完才由用户落进 main。**此前那句"三片还停在主干之外、要不要打上由用户自己定"的旧口径已作废**——文档现在既不该写成"等打补丁"，也不该暗示这三片还是待办；写代码时按"这三件上游已具备"来推理。
- **验收锚点**：`LLM_MEMORY_REPO` 未设 → 全量测试与行为逐字节同今天；设了 → `namespaces()` 里 ai-research / webapp-chat 行数在涨、`search_memory` 命中上游行、旧库只读兜底可关；重复 ingest 同一会话文件不产生重复行。
- **与历史裁决的冲突注记**：本小节依据的收敛裁决**取代** HANDOFF §0 三禁令里的 #1 与 #3——#1 作废（走 re-ingest + 旧库退役，不是把整库塞进上游），#3 豁免（写路径接上游 ingest 正是收敛本身）；#2 不是被推翻而是改写为"一切经 SDK 面，AR 进程不读不写 `~/.llm-memory`"。历史冲突文本不做抹除，每条裁决的原文、理由与改判条件都记在 [PLAN-MEMORY-CONVERGENCE.md](PLAN-MEMORY-CONVERGENCE.md) 的"裁决记录"段（改判需用户点名）。另：上游写面与只读检索面的 namespace 是两套——SDK 面传三个显式名字，decision 面（why/pack/remember）走上游路径派生 ns，这个分家是已知且接受的格局，别去"统一"。

## MCP Services

`MCP_CONFIG`（`src/config/settings.py`）当前启用的条目：
- `"duckduckgo"`：`uvx duckduckgo-mcp-server`（SearchAgent 的 web_search 用它，需单独安装 uvx/该包）。
- `"web_scraper"`：`sys.executable -m scraper.mcp_server.server`，env `PYTHONPATH=src/services`——即 `src/services/scraper/` 自带的 Playwright 抓取 MCP server。
- `"llm_memory"`：`sys.executable -m llm_memoryd.mcp --tools memory_why,memory_pack`，env `PYTHONPATH=<LLM_MEMORY_REPO>/src`——上游 LLM-Memory 的可选决策面，**默认不启用**。本条目是子进程参数的**单源**：`upstream.py` 直接据此构建 StdioServerParameters 并继承 `os.environ`，不再自带副本；实际是否拉起由 `upstream.py` 按 `LLM_MEMORY_MCP_ENABLED` 门控，why/pack 工具要 `--tools` 显式点名才 served（上游 MCP 默认只暴露 search/ingest/list_* 四件）。
- 历史的 `"ddg-search"` 本地脚本条目（`src/services/duckduckgo_mcp_server.py`）与 `mcp_server_fetch` 注释条目已随重构删除。

MCP 客户端实现是 `src/agents/search/utils.py` 里的 `SimpleMCPClient`（stdio 传输，
`mcp` 库的 ClientSession；历史上的 `src/services/mcp_client.py` 已删除——它只被
SearchAgent 用到 stdio 一种传输，薄封装就地维护即可）。上游 LLM-Memory 的决策面
客户端在 `src/memory/upstream.py` 里按同一 stdio 形状就地实现
（initialize/call_tool/硬超时），分层纪律决定它不 import `src.agents`。

## Environment Variables

**LLM 凭据/模型（settings.py）**：
- Azure：`CHAT_API_KEY`、`CHAT_API_VERSION`、`CHAT_AZURE_ENDPOINT`、`CHAT_DEPLOYMENT_NAME`、`CHAT_MODEL_NAME`
- OpenAI：`OPENAI_API_KEY`、`OPENAI_MODEL_NAME`（默认 gpt-6-luna）、`OPENAI_BASE_URL`
- Ollama：`OLLAMA_BASE_URL`（默认 :11434）、`OLLAMA_MODEL_NAME`
- Gemini：`GEMINI_API_KEY`、`GEMINI_MODEL_NAME`、`GEMINI_BASE_URL`
- Embedding：`EMBEDDING_API_KEY/API_VERSION/AZURE_ENDPOINT/DEPLOYMENT/MODEL`、`OPENAI_EMBEDDING_MODEL`、`OLLAMA_EMBEDDING_MODEL`、`GEMINI_EMBEDDING_MODEL`、`EMBEDDING_PROVIDER`（默认 openai——该键以前不存在，现是 provider 选择的唯一入口）

**运行时行为**：
- `HOST` / `PORT`：`run_server.py`，默认 `127.0.0.1`/`8000`，非回环 HOST 打 WARNING
- `CORS_ORIGINS`：逗号分隔来源列表，默认只放行 localhost/127.0.0.1:8000；含 `*` 时自动关闭 `allow_credentials`
- `RETRIEVAL_DEDUP_WINDOW`：检索去重轮次窗口（默认 5）
- `BRIEFS_DIR`：简报 HTML 目录
- `LLM_MEMORY_REPO`：上游 LLM-Memory checkout 路径——上游只读门面（SDK / 可选 MCP）的唯一寻址点；未设或无效即全部上游入口报 `available:false` + note，本地功能零影响
- `LLM_MEMORY_MCP_ENABLED`：`=1` 时启用可选 MCP stdio 决策面（`python -m llm_memoryd.mcp --tools memory_why,memory_pack`）；默认关闭，不设即默认行为不受影响
- `MEMORY_STORE_MODE`：记忆读写路由的 kill switch，**默认 `auto`**（gateway 一处决策点：`LLM_MEMORY_REPO` 可用走上游、否则本地旧路 + warning）；设 `local` 即强制本地旧路，上游可用也不写上游。它和 `LLM_MEMORY_REPO` 都不设＝全走旧路，dev/CI 行为零变化。只作用于写/读路由，管不到 `LLM_MEMORY_MCP_ENABLED` 那条只读决策面
- （历史注记：`MEMORY_BRIEF_DRIVER` 的 `bridge` 兜底路与 `LLM_MEMORY_URL` 已随 HTTP 桥退役——driver 白名单只剩 `local`，旧值 warning→local）

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

前缀均为 `/api/v1`，注册于 `app.py:92-109`。`/` 开头的是页面路由。

```
Pages:   GET /  /chat  /config  /data  /structure  /briefs  /memory→302 到 /briefs
WS:      /ws/chat                     # 唯一的 WebSocket（origin 校验见 websocket.py）
Health:  GET /health                  # app.py 内联定义

documents: GET /list /available-pdfs | POST /upload /index | DELETE /{doc_name}
chat:      POST /initialize /clear    | GET  /load-more-messages
sessions:  GET /list /{id} | DELETE /{id} | PATCH /{id}/rename /{id}/memory-scope
pdf:       GET /view/{doc_name}                   # 页面图（专用 images/image 路由已删，走 view 降级）
structure: GET|PUT /{doc_name} | POST /{doc_name}/rebuild
config:    GET "" | GET /models | POST /provider /system /reset /models /models/test
           # 落 data/config/app_config.json；/models 是每 provider 多模型的
           # 注册表读写，/models/test 用它发一次最小对话验通。
           # POST /models 若读到的是坏掉的 app_config.json 会拒绝写入并回
           # 500 + warning——绝不以空 dict 起盘回写，那样会把 provider 等
           # 其它键一起抹掉
data:      GET /overview /documents /documents/{name}/summary /documents/pending
           /sessions/stats /tasks/{task_id}
           POST /documents/{name}/index  DELETE /pdfs /documents/{name}/parts /documents
           POST /cleanup/smart?days=N
briefs:    GET /dates /cards /memory-status  | POST /load /sync-memory /light-load /fetch-pdf
           # 数据层 services/briefs_data.py；/light-load 是日期级轻量入库
           # （load_brief_date 任务，写 AATF）；/memory-status 返回各日期
           # 真实入库计数 {dates:{d:{aatf,heavy_done}}}——按 A 自库行+queue
           # 事实而非任务账本（旧 bridge 时代 done ≠ A 自库有数据——桥已退役，按事实计数仍保留）
           # /fetch-pdf 下载并索引论文 PDF，与 documents 共用同一条
           # IndexingAgent 后台流。终态行为：
           #   * 临时文件唯一名 `{name}.part.{pid}.{tid}.{uuid8}` +
           #     os.replace 原子换名，清理只删自己那一份——路由虽是 async，
           #     同一 doc 的并发请求会落在同一线程上，pid+tid 撞车概率不为零，
           #     所以再加 uuid 熵。
           #   * SSRF 加严：scheme 限 http(s)；主机解析后过黑名单，拦
           #     127/8、::1、RFC1918、169.254/16（云元数据）、100.64/10、
           #     ULA 与文档保留段，::ffff: 映射按 IPv4 判。**没有做白名单**，
           #     arxiv 与公网照常可达；重定向由后端自己逐跳跟（httpx 的
           #     follow_redirects 已关），每跳重过同一道校验。
           #   * 已声明的信任边界：抓取面与 SearchAgent 同级；DNS 重绑定的
           #     TOCTOU 窗口承认存在，不为此单造锁。
           #   * exists 分支返回四态 indexed / not_indexed / indexed_elsewhere
           #     / unknown 加 note；`force:true` 是重下入口，前端只在确认
           #     "文件在但没索引"后才带 force 重试。indexed_elsewhere 的
           #     语义定调为**不谎称已索引、不补排**——registry 里带版本号
           #     的名字对应另一个文件，补排等于多花一份 LLM 成本并在
           #     registry 里裂出条目，所以前端只展示真名。
           #   * pdf_preset 取 /config 当前值（config.get_current_pdf_preset），
           #     provider 走 resolve_provider 链——此前写死 preset 的问题已修。
jobs:      GET "" | POST /{job_id}/retry /cancel        # 任务账本见 job_runner + webapp_jobs.json
memory:    GET /overview /namespace/{ns} / POST /search
           DELETE /item/{id} /namespace/{ns}/source/{source_id} /namespace/{ns}
           # 收敛注记：三种 DELETE 走 gateway.delete_* → 上游 delete/delete_where
           # （跨 ns 的 id 与 unscoped 删除都被守卫拒掉，且**不回落**；三个函数保持
           # sync 不是 async+to_thread），删的是上游存储层，data/memory_db 的对应
           # 行不受影响；`DELETE /sessions/{id}` 的记忆回收段同指上游。
           # browse_* 的行级浏览仍是本地库原语，只有 overview / namespace 列表的
           # 计数层并上游只读 namespaces() 的计数——/data 页两边计数都可见。
           GET /upstream / POST /upstream/search   # 上游只读门面（status 内嵌 decision 开关位；
           POST /upstream/decision                 #   检索缺省全局 scoped=False；why/pack 白名单一跳）
speech:    POST /transcribe /synthesize
```

## UI Features（现状速览）

- FastAPI + Jinja2 + 原生 ES6 JS，无框架；WebSocket `/ws/chat` 实时对话，REST 做初始化/历史分页。
- **UI 聊天走 Orchestrator 而非 AnswerAgent**：工具决策在 Orchestrator 的 ReAct 循环里，而 **`enabled_tools` 现在真的决定广告给模型的工具集**——`search_memory` 与 `deep_dive_document` 恒开，`search_web` 只有会话勾了"网络搜索"才进（`ALWAYS_ON_TOOLS | (enabled_tools ∩ _TOOL_SCHEMAS)`，`enabled_tools=None` 表示调用方不管工具这回事＝全开，保持老行为）；`selected_docs` 仍是会话上下文元数据并派生出 doc_name 供深挖用。`agents_used` 标签集合：MemorySearch / DeepDive / **WebSearch**（manage.js 暂无该图标，纯文本显示）。
- 会话存储：`data/sessions/{session_id}.json` 平铺（SessionManager 自动迁移旧 mode 子目录）；会话 API 为 list/get/delete/rename 外加 `PATCH /{id}/memory-scope`（该会话检索哪些记忆 namespace，缺省 ai-research + webapp-chat，AATF 需显式勾选，校验集合见 sessions.py）——**没有** import/export，原 current/info 端点因无消费者已删。**DELETE `/sessions/{id}`** 现在还会按 source 回收这条会话写进 `webapp-chat` 的记忆行并清掉 chat_ingest 的水位线条目（顺序固定：先删文件→再清记忆→最后清水位线；后两步尽力而为，失败只打日志不把删除拖失败）。
- 数据管理页 `/data`：总览、按文档列 JSON/向量库/图片/摘要四类产物、部分/批量删除（`/api/v1/data/documents/{name}/parts`）、smart cleanup、sessions stats，以及 Memory tab（缓存查看/清理、backup、危险的全量 reset 端点已删）。
- PDF 查看：`/api/v1/pdf/view/{doc_name}`（页面图，图片降级内建于 view）。
- 结构编辑器 `/structure`：编辑 structure.json 后走 rebuild 图重生成摘要/索引。
- `/config` 页读写 provider 与系统设置（含模型注册表）；`/briefs` 页加载简报条目进管线队列，并有"轻量入库(全天)"把当天卡片写进 `AATF`（收敛后经上游 `ingest(source_type=brief)` 抽取，本地直写只是回落）——原 `/memory` 页已退役并入这里（老书签 302）。
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
  open+json.dump 写状态文件。索引期产物落盘也已收进这一套，共五处：
  `indexing/nodes.py` 的 data.json / 两处 structure.json / chunk json，
  `indexing/tools.py` 的 image_content_list，以及 `structure.py` 保存结构的那一处——
  注意它只防"写到一半崩溃"，读-改-写交错仍要靠锁。
- **新数据目录**：路径常量加进 `src/config/constants.py:PathConstants`，需要自动创建的在入口
  `makedir()`（indexing 的 `_setup_pdf_config` 是现成示例）。
- **UI 加 API 端点**：`api/v1/<module>.py` 加路由 → `app.py` include_router（若整个新模块）→ 前端
  在对应 js 里走 `api.js` 封装；涉及 doc_name 拼路径必过 `safe_path()`。

## Testing Notes

- `pytest.ini` + `tests/conftest.py`：缺 LLM 凭据时相关脚本式测试自动 skip；纯逻辑用例可直接跑。
- `tests/test_imports.py` 是零依赖冒烟基线，重构后先跑它。
- 涉及索引/问答的脚本测试（test_indexing_agent.py 等）会真实调 LLM，需凭据。
- **数据根有两个入口且不同源，写测试要两处都钉**：`constants.get_data_root()` 动态读
  `PathConstants.DATA_ROOT`，而 `DocumentRegistry()` 不传 path 时默认路径来自
  `src.config.settings.DATA_ROOT`——那是 import 期就固化的快照。只 patch
  `PathConstants` 的话 delete/registry 类用例会照旧读写仓库真实的 `data/`，删除路径
  与注册表路径也会各指一处。范式抄 `tests/test_delete_service.py` 的 `data_root`
  fixture（两个都 monkeypatch），并由 `test_data_root_knobs_agree` 守着这个不变式；
  新测试直接沿用该 fixture，别只 patch 一边。
- `src/utils/file_operations.py:read_file_with_encoding_detection` 全仓零调用点，
  所以 chardet 缺失时那条 ImportError→UTF-8 降级路今天完全静默、也没有任何测试覆盖它。
  requirements 里已注明该依赖"故意不装"，要启用就显式 `pip install chardet`。
```
