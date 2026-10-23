# AgenticReader 框架重构审计报告

> 生成日期：2026-10-22 · 方法：Agent Teams（7 个域扫描 agent + 7 个对抗复核 agent，共 14 个视角；另加主线程 AST 静态基线 + 手工抽查）
> 规模：`src/` Python ≈ 34,200 行（171 个模块）+ 前端 13,100 行（8 模板 / 10 JS / 5 CSS），73 个 HTTP 路由 + 1 个 WebSocket
> 定位：**上一份 `ANALYSIS_REPORT.md`（2026-10-21）以"正确性/安全"为主**，其中 path_guard 目录穿越、CORS、并行 session 污染、embedding 配置键、indexing 失败仍注册等问题已由 `4942dd1` 修复。本报告只做**重构优化**：可删的死代码、无用的 UI/接口、重复实现、结构性优化，不重复旧报告的 bug 清单。
> **交叉验证**：本报告定稿后，另有 5 个独立维度 agent（py / fw / ui / cfg / hyg）对全部核心清单做了二次并行审查——结论 **100% 同向、零冲突**（dashboard.js、utils 死岛、mcp_client、scraper 死策略层、api.js 伪封装、17 个零消费 API、11 组重复实现、死配置键均被独立复现）；其独有的 4 项增量已并入 §9（D5/D6）与 §10（路线图），原 `REFACTOR_ADDENDUM.md` 已合并至本文。口径说明：独立轮按「HEAD 下 grep 零引用」计 ≈2,600 行，本文 4,796+3,200 含接线型死码与 docstring 行数——两侧各自成立，执行以本文文件级清单为准。

---

## 1. 结论速览

| 指标 | 结论 |
|---|---|
| **可删除代码** | **≈ 8,000 行（占 `src/` 约 23%）**：16 个整文件 4,796 行 + 函数级 ≈ 3,200 行（逐域明细合计 8,700 的上限含保守估值，取 8,000 为可执行口径） |
| **前端零调用的 API** | 66 个 API 路由里 **17 个**（约 26%），其中 12 个建议直接删、5 个需先决定产品能力 |
| **整文件可删** | 16 个（含 `dashboard.js` 1,162 行、"测试框架死岛" 1,503 行、`mcp_client.py` 386 行、scraper `fallback+retry` 598 行） |
| **主要重复实现** | 11 组（原子写+flock、provider 解析、向量库路径、文档索引/删除、JSON 清洗、进度上报、前端 toast/转义/分页、PDF 渲染、两套 MCP 客户端、两套抓取栈、REPL） |
| **顺带发现的真实缺陷** | 4 条（索引入口漏 `doc_type` 必失败、删除路径缺 `_data_index` 后缀、重建清理路径错、测试假绿灯） |
| **性能热点** | 3 处（每次构造 VectorDB 都 `FAISS.load_local` + 真实 embedding 探针；聊天每问重建 LLM/图；`/data` 首屏 6 次全量扫描） |

**一句话结论**：这套框架**不需要重写**，但需要一次"**删一半 + 收口**"的手术——把三条已经废弃的并行实现（MCP 客户端、抓取栈、配置层）和两个已经迁走的旧前端（`dashboard.js`）清掉，再把 11 组"复制粘贴"收敛到单一实现。做完后代码量降 20%+，而"改一处要改三处"的问题基本消失。

### 三条最值得做的重构

1. **删死岛**（半天，零风险）：`src/utils/` 里 1,503 行零引用模块 + 前端 `dashboard.js` + `mcp_client.py` + scraper 死策略层 + `search/tools_config.py` + `chapters.py`。
2. **文档生命周期收口**：把"索引/删除"从 4 份/3 份副本收敛为 `core/document_management` 里一个无交互 service（现在 `documents.py` 与 `data.py` 两套已实际分叉，其中一份是错的）。
3. **配置与并发原语收口**：`provider` 单一解析入口（现在 14 处硬编码，`/config` 页设置对聊天不生效）+ `write_json_atomic`/`flock` 下沉到 `src/utils` 并被所有状态文件复用。

---

## 2. 方法与可信度

| 域 | 覆盖范围 | 发现 | 复核确认 | 复核修正 | 被推翻 | 复核补漏 |
|---|---|---|---|---|---|---|
| agents | `src/agents/**`（5 个 agent + common） | 12 | 10 | 2 | 0 | 2 |
| core-config | `src/core/**` + `src/config/**` | 10 | 9 | 1 | 0 | 3 |
| ui-backend | `src/ui/backend/**` | 10 | 8 | 2 | 0 | 3 |
| ui-frontend | `templates` + `static/js` + `static/css` | 10 | 8 | 2 | 0 | 3 |
| memory-pipeline-services | `src/memory/**` + `src/pipeline/**` + `src/services/**` | 10 | 6 | 4 | 0 | 3 |
| utils-entry-tests | `src/utils/**` + `main.py` + `tests/**` | 10 | 4 | 6 | 0 | 3 |
| crosscut | 全仓横切 + 文档 | 10 | 7 | 3 | 0 | 3 |
| **合计** | | **72** | **52** | **20** | **0** | **20** |

- 每个域都是"扫描 agent → 独立红队 agent"，红队专门找反证：动态引用（`__init__` 再导出 / `getattr` / `importlib` / 字符串分发）、Jinja 模板、前端模板字符串拼出的 URL、MCP/CLI/pytest 入口、LangGraph `add_node`。
- **可信度标记**：✅ = 复核确认；⚠️ = 复核修正（描述或数字有偏差，方向成立）；🔬 = 主线程亲手实测。
- 主线程另做了两件事：AST 引用扫描（`_audit/baseline_report.md`）与 12 处关键结论抽查（第 12 节列出）。**没有一条发现被推翻**，但有 20 条需要修正数字或因果——报告里已按复核结果写。

---

## 3. 度量基线

### 3.1 规模

| 包 | 文件 | 行数 | 本报告结论 |
|---|---|---|---|
| `src/agents` | 49 | 12,870 | 结构规范，但门面层/state/prompts 有 ~1,200 行死面 |
| `src/utils` | 11 | 3,894 | **重灾区**：约 73% 不可达 |
| `src/ui`（后端） | 30 | 5,407 | 端点重复与死端点集中 |
| `src/core` | 14 | 5,034 | 基础扎实，缺缓存与统一原语 |
| `src/services` | 18 | 3,272 | 两套 MCP/抓取栈，scraper 策略层未接线 |
| `src/memory` | 12 | 1,516 | 分层最干净，读路径缺缓存 |
| `src/pipeline` | 11 | 1,383 | 两个队列 45-80 行同构 |
| `src/config` | 6 | 788 | 有一层休眠配置 + 14 个零读取常量 |
| 前端 | 23 | 13,100 | `dashboard.js` 整体死亡；共享层被绕开 |

### 3.2 包级依赖（AST 实测，模块级 vs 函数内延迟）

```
agents  → config 5(顶层) /16(延迟)   core 3/12   utils 5   memory 1
config  → agents 0(顶层) / 4(延迟)   ← 层间方向干净
core    → config 6/5    agents 0/5    pipeline 1(顶层!)    utils 1
memory  → core 3        config 1
pipeline→ memory 6      agents 5      core 2
services→ core 1        utils 1
ui      → pipeline 5    agents 2      memory 4    core 2  config 2  utils 5
utils   → config 3
```

顶层没有任何 `core → agents` 或 `config → agents` 边，这一点做得好。**但运行时被一处细节击穿**：

- 🔬 实测 `from src.config.prompts import SYSTEM_PROMPT_CONFIG` 会触发模块 `__getattr__`，**立即**执行 `_build_system_prompt_config()`，加载 **31 个 `src.agents` 模块 + langgraph**（对照：`import src.config.prompts` 只加载 0 个）。`src/core/llm/client.py:31` 正是这种写法，所以"惰性聚合"名存实亡。
- `src/core/document_management/registry.py:19` 在模块级 `from src.pipeline.paths import write_json_atomic`——核心层反向依赖管线层，只为一个 10 行函数。

### 3.3 路由面

74 条路由 = 7 个页面 + 1 个 WebSocket + 66 个 API。逐条比对 `static/js` 与 `templates` 后，**17 个 API 前端零调用**（见第 6 节）。

---

## 4. 整文件级结论：16 个文件的去留

| # | 文件 | 行数 | 为什么是死的 | 处置 |
|---|---|---|---|---|
| 1 | `src/ui/static/js/dashboard.js` | 1,162 | 无任何模板 `<script src>` 加载；它查询的 27 个 DOM id 在 `dashboard.html` 中一个都不存在（该页已改用 `manage.js`） | **删** ✅ |
| 2 | `src/utils/test_framework.py` | 368 | 全文件零导入；`src/utils/` 无 `__init__.py`、pytest `testpaths=tests`、无 CI 入口，没有任何再导出路径 | **删** ✅ |
| 3 | `src/utils/config_validator.py` | 437 | 唯一引用者是 `test_framework.py`（死文件），随其死亡 | **删** ✅ |
| 4 | `src/utils/common.py` | 299 | 全仓零引用 | **删** ✅ |
| 5 | `src/utils/performance_monitor.py` | 399 | 全仓零引用；且依赖**未声明也未安装**的 `psutil`（🔬 实测 `import psutil` → ModuleNotFoundError） | **删** ✅ |
| 6 | `src/services/mcp_client.py` | 386 | 全仓零 import；现役 MCP 客户端是 `agents/search/utils.py:70` 的 `SimpleMCPClient`（只有 docstring 和 CLAUDE.md 还提 MCPClient） | **删** ✅ |
| 7 | `src/services/scraper/core/retry.py` | 283 | `RetryStrategy` 从未实例化；`core/__init__.py:6-7` 的 eager 导入让 server 启动即加载它 | **删** ✅ |
| 8 | `src/services/scraper/core/fallback.py` | 315 | `FallbackHandler` 从未实例化，`mcp_server/tools.py` 的 `page.goto` 无任何重试/回退 | **删** ✅ |
| 9 | `src/services/duckduckgo_mcp_server.py` | 249 | `MCP_CONFIG` 里它嵌在 `MCPToolName.WEB_SEARCH`（值 `"web_search"`）之下，而唯一读取点只按 `"duckduckgo"`/`"web_scraper"` 取键 → 永远取不到该条目 | **删**（连 `settings.py:19-40` 嵌套块） ✅ |
| 10 | `src/agents/search/tools_config.py` | 261 | 零 import；`SEARCH_TOOLS_CONFIG` 连本文件内都没被使用 | **删** ✅ |
| 11 | `src/agents/indexing/utils.py` | 82 | `IndexingUtils.should_skip_stage` 零调用，`check_cache` 节点自己读 registry | **删** ✅ |
| 12 | `src/agents/answer/utils.py` | 50 | `AnswerUtils.validate_state` 零调用（唯一实例化点 `agent.py:71` 之后再无访问） | **删** ✅ |
| 13 | `src/core/processing/text_splitter.py` | 126 | 整模块零引用；连 `__init__.py` 都没有（namespace package），`test_imports.py` 里的 `src.core.processing` 只建包不加载文件 | **删**（整目录） ✅ |
| 14 | `src/config/app_settings.py` | 228 | "第二套配置系统"：`settings.py:10-14` try-import 后全文零读取；却在 **import 期 mkdir 12 个目录**，且 `host=0.0.0.0`、`cors=["*"]`、`memory_dir=data/memory` 三处默认值与真实实现**正好相反** | **删**（连 try-import 6 行） ✅ |
| 15 | `src/ui/backend/api/v1/chapters.py` | 70 | 整模块零调用（前端只走 `/structure` 与 `/data`） | **删**（连 `app.py:94` 挂载 + `api.js` 封装） ✅ |
| 16 | `src/pipeline/sync_pipeline_queue.py` | 77 | 仓库内零 import，但与 `briefs_data._register` 逻辑重复 | **保留**：它是 `python -m` 文档化 CLI；若要留就改成 5 行 thin wrapper 复用 `briefs_data._register` ⚠️ |
| | **合计** | **4,796** | | 15 删 / 1 收敛 |

> 注：`src/core/processing/` 删掉后整个目录消失；`dashboard.js` 的 1,162 行是**前端总量的 8.8%**。

---

## 5. 函数级死代码（按域）

### 5.1 agents（≈ 1,600 行，其中整文件 261 行）

| ID | 内容 | 位置 | 行数 | 复核 |
|---|---|---|---|---|
| A-01 | `search/tools_config.py` 整文件 | 见上表 | 261 | ✅ |
| A-02 | `IndexingAgent` 五个门面方法 + `process_documents_batch` + `IndexingUtils` | `indexing/agent.py:211-300`、`indexing/tools.py:487-551` | 239 | ✅ |
| A-03 | `search/utils.py` 五个"只写不读"函数 | `normalize_url`(315)、`extract_key_info_from_html`(462)、`load_search_cache`(612)、`has_search_cache`(654)、`load_web_content`(723) | 136 | ✅ |
| A-04 | `AnswerAgent` 五个访问器 + `AnswerUtils` | `answer/agent.py:130-165, 202-272`、`answer/utils.py` | 157 | ✅ |
| A-05 | 确定性改造后失效的 prompt 常量 | `search/prompts.py` 4 个（171 行）、`retrieval/prompts.py:496-567`、`indexing/prompts.py:120-133,165-194` | 287 | ✅ |
| A-06 | 每个 agent 实例都急切构造 embedding 客户端 | `agents/base.py:72` | 5 | ✅ |
| A-07 | 单文档检索样板两份（逐字相同） | `answer/tools.py:272-330` vs `core/parallel/retrieval.py:202-250` | 45 | ✅ |
| A-08 | `_send_progress` ×3、LLM JSON 清洗 ×4 | `answer/nodes.py:33`、`answer/tools.py:497`、`retrieval/nodes.py:43`；`search/utils.py:28` 是唯一能解 ```` ```json ```` 围栏的实现 | 60 | ✅ |
| A-09 | 向量库目录 `f"{doc}_data_index"` 手抄 7-8 处 | `retrieval/utils.py:40`、`indexing/tools.py:109`、`indexing/nodes.py:61/772/851`、`data.py:196/762`、`manager.py:84` | 10 | ⚠️（规模低估；`rebuild` 清理用相对路径且缺后缀，**永远删不到旧索引**） |
| A-10 | 4 个 State 里 16+ 个"只写不读"字段 | `AnswerState.thoughts/max_iterations`、`RetrievalState.selected_pages`、`SearchState` 的 6+5 个、`IndexingState.raw_data/vector_db_docs/doc_id` | 20 | ✅（复核补 `SearchState.observations`） |
| A-11 | AnswerAgent 图里 `evaluate` 节点恒真、`plan` 的"已有工具结果"分支不可达 | `answer/nodes.py:519-556`、`336-343`、`agent.py:120` | 60 | ✅ |
| A-12 | 零散死函数 6 组 | `orchestrator/agent.py:52-54`、`retrieval/agent.py:117-127`、`search/agent.py:260-286`、`formatter.py:213-265`、`answer/tools_config.py:63-72,81-117`、`retrieval/tools_config.py:246-280` | 124 | ⚠️（**不要**整段删 63-117，`is_tool_enabled` 是活的） |
| M-01 | `SearchTools.download_resources` | `search/tools.py:492-630` | 139 | 复核补 |
| M-02 | `build_vector_index_impl`（与 `nodes.build_index` 是第二套索引实现） | `indexing/tools.py:84-164` | 81 | 复核补 |

### 5.2 core / config（≈ 1,000 行，其中整文件 360 行）

| ID | 内容 | 位置 | 行数 | 复核 |
|---|---|---|---|---|
| CC-03 | `LLMBase` 8 个 history 方法 + `history.py` 4 个连带方法 | `client.py:295,318,338,372,517,543,563,572`；`history.py:305,325,408,458` | 426 | ✅（比初估 250 多，含 docstring） |
| CC-05 | `parallel/indexing.py` 三个 `run_parallel_*` 同步包装（只有 `__all__` 自指） | `193-233/236-276/414-448` | 123 | ✅（连带 `async_utils.run_async`） |
| CC-09 | 三个零调用访问器 | `vector_db_client.py:418-447,612-623`、`registry.py:431-447` | 59 | ✅ |
| CC-07 | 14 个从未读取的常量/配置键 | `constants.py:13,14,20,21,22,94,99,107-110,113,114,188,189`、`settings.py:174,186,195` | 23 | ⚠️（14 个，不是 13） |
| CC-10 | 模块 import 期 `basicConfig` 共 4 处（core 域） | `client.py:43`、`vector_db_client.py:13`、`manager.py:38`、`indexer.py:41` | 14 | ⚠️（实际 4 处，非 2 处；入口没配日志的是 `run_server.py`） |
| CC-01/02/04/06/08 | 见第 4、7 节 | | | ✅ |

### 5.3 memory / pipeline / services（≈ 75 行函数级，另有整文件 1,488 行）

| ID | 内容 | 位置 | 行数 | 复核 |
|---|---|---|---|---|
| MPS-10 | `VectorStore.chunk_hashes` / `count_rows` / `get_by_ids` | `memory/vector_store.py:130-137,231-235,247-252` | 30 | ⚠️（`get_by_ids` 唯一链路挂在无前端调用的 `GET /memory/item`） |
| MPS-04 | `process_pdf_queue` / `process_web_queue` 收尾段同构 | 两个文件各 ~25 行 | 45 | ⚠️（不是逐行相同，净删 45-50） |
| MPS-07 | `sync_pipeline_queue` 与 `briefs_data._register` 重复 | 见上表 #16 | 0 | ⚠️（保留 CLI，改为薄封装） |
| MPS-08 | `process_web_queue` 6 处 `provider="openai"` | `:39,60,81,99,156,166` | 0 | ⚠️（真正问题是 **UI 配置的 provider 从未进入任何管线车道**，`job_runner.py:220` 的 pdf 也写死） |
| MPS-M2 | `job_runner` 的 `render_report` 作业类型无入队方 | `job_runner.py` | 0 | 复核补（二选一：接按钮或删分支） |

### 5.4 ui-backend（≈ 450 行，其中整文件 70 行）

| ID | 内容 | 位置 | 行数 | 复核 |
|---|---|---|---|---|
| UB-01 | 5 个运维端点前端零调用 | `data.py:688-703`（GET tasks）、`944-1043`（cache 读写）、`1122-1225`（backup+reset） | 218 | ✅ |
| UB-02 | `chapters` 整模块 + `pdf` 图片两端点 + `structure` 删章节 | `chapters.py`、`pdf.py:45-121`、`structure.py:309-384` | 223 | ✅（含上表 #15 的 70 行） |
| UB-06 | `llmmemory` 的 `/load` 与 `/load/progress` 残留 | `llmmemory.py:59-67` | 9 | ⚠️（代码里明写"刻意保留"，删前需确认） |
| UB-09 | `SessionManager._session_cache` 只写不读（7 处赋值 0 处读取） | `session_manager.py:24,78,143,168,220,235,416` | 0 | ✅ |
| UB-10 | `auto_save_outputs`/`enable_notifications`/`log_level` 三个开关后端从不读 | `config.py:25-27,105-107` | 0 | ⚠️（`DEBUG` 分支不是死代码，是"没文档的 env 开关"） |
| UB-M1 | `GET /memory/item/{id}` 整条链零调用 | `memory.py:25-30` + `memory_browse._build_detail/fetch_detail` | 0 | 复核补 |

### 5.5 ui-frontend（≈ 390 行函数级 + 1,162 行整文件 + 119 行 CSS）

| ID | 内容 | 位置 | 行数 | 复核 |
|---|---|---|---|---|
| UI-01 | `dashboard.js` 整文件 | 见上表 | 1,162 | ✅ |
| UI-02 | `api.js` 15 个方法中 **11 个**零调用者；`/data`、`/config` 两页加载它却从不使用 | `api.js:14-69,104-176` | 125 | ⚠️（实际在用 4 个：`documents.list`、`chat.initialize`、`chat.loadMoreMessages`、`sessions.list`） |
| UI-05 | `chat-enhancer.js` 6 个成员零调用（含被注释掉的 `addScrollToTopButton`） | `:13-14,21-75,212-302` | 146 | ✅ |
| UI-08 | CSS 24 个规则块 + 8 个自定义属性零引用 | `chat-enhanced.css`、`structure_editor.css`、`variables.css` | 119 | ✅ |
| UI-06 | PDF 按页渲染三份同源实现 | `chat.js:675-930`、`structure_editor.js:215-410`、`dashboard.js:960-1100` | 0（重构） | ⚠️（核心算法同源，但两份有实质差异，不能"逐行合并"） |
| UI-07 | toast ×4、escapeHtml ×3、分页 ×2、全选 ×2 | `utils.js:9`、`manage.js:1392-1440`、`structure_editor.js:902`、`chat-enhancer.js:212`、`briefs.js:24`、`dashboard.html:389` | 96 | ✅ |
| UI-04 | `manage.js` 完全绕过 `api.js`/`ui-components.js`/`utils.js`（22 处裸 fetch） | `manage.js` 全文 | 0（重构） | ✅ |
| UI-10 | `base.html` 在 7 个页面无条件扫 pending PDF；`/jobs` 被 3 处各自轮询 | `base.html:84-110` | 0 | ✅ |
| MF-03 | 模板内联 `<style>`/`<script>` ≈ 3,200 行（chat.html 964 行 CSS、memory.html 734 行 JS、manage.html 503 行 CSS） | 模板 | 0 | 复核补（体积最大的一块，绕开缓存） |

### 5.6 utils / main / tests（≈ 2,300 行，其中整文件 1,503 行）

| ID | 内容 | 位置 | 行数 | 复核 |
|---|---|---|---|---|
| UET-01 | `test_framework.py` 死岛入口 | 见上表 | 368 | ✅ |
| UET-02 | `common.py` + `performance_monitor.py` | 见上表 | 698 | ✅（🔬 psutil 确实不存在） |
| UET-03 | `validators.py` 仅 `validate_file_path` 活；`file_operations.py` 仅 `ensure_directory` 活；`error_handler.py` 活面 3 个装饰器 | 三文件 | ~800 | ⚠️（`safe_execute` 的唯一调用者也在待删函数里） |
| UET-05 | `helpers.py` 9 个零引用函数 | `list_pdf_files`(16)、`load_json_file`(32)、`load_md_file`(53)、`get_pdf_name`(116)、`parse_latest_plugin_call`(353)、`add_data_keep_order`(609)、`is_file_exists`(626)、`extract_name_from_url`(656)、`save_data`(712) | 215 | ✅ |
| UET-04 | `main.py:685` 手拼 `AnswerState` 直接 `graph.ainvoke`，绕过 `AnswerAgent.query()`（丢掉轮次记账） | `main.py:685-689` | 0 | ✅ |
| UET-07 | 3 套 REPL 循环复制同一套 `quit/clear/main` 解析 | `main.py:421-521`、`658-714`、`760-847` | 80 | ⚠️（是 3 套不是 4 套；`manager.interactive_manage` 是第 4 份菜单副本，另算） |
| UET-09 | 假绿灯测试 | `test_cross_doc_flow.py`（110 行，0 import 0 assert）；`test_parallel_logging.py`（56 行，无 `test_` 函数，pytest 收集 0） | 166 | ⚠️（后者根本没被收集） |
| UET-10 | pytest 会收集交互式 `test_menu`（`input()` 死等）与旧 schema 断言 | `test_multi_pdf.py:378-443`、`test_manual_selection_mode.py` | ~50 | ⚠️ |
| UET-M02 | `test_indexing_agent.py` / `test_vector_db_content.py` 768 行里 pytest 收集 0 个用例 | tests | 0 | 复核补 |
| UET-M03 | `manager.interactive_manage()` 是 `main.py:53-130` 的第 4 份副本且零调用 | `manager.py` | 78 | 复核补 |

---

## 6. 无用 UI / 接口清单

### 6.1 前端零调用的 17 个 API

判定方式：在 `static/js/*.js` 与 `templates/*.html` 里搜端点片段，并排除 `api.js` 中本身无人调用的封装方法；复核 agent 另外查了 `src/pipeline`、`tools_*.py`、tests 是否有外部 HTTP 调用（只有 `tests/test_brief_load_jobs.py` 打 llmmemory，与下表无关）。

| 分类 | 端点 | 建议 |
|---|---|---|
| **直接删（12）** | `GET/DELETE /data/cache/{type}`、`POST /data/backup`、`POST /data/reset`、`GET /data/tasks`（列表）、`GET /chapters/.../chapters`（整模块）、`GET /pdf/images/{doc}`、`GET /pdf/image/{doc}/{file}`、`DELETE /structure/{doc}/chapter/{title}`、`GET /memory/item/{id}`、`GET /sessions/current/info`、`GET /documents/available-pdfs` | 运维能力挪到 `scripts/` CLI，不占 Web 路由；删路由时连 Pydantic 模型与 `api.js` 封装一起删 |
| **先决定能力（4）** | `POST /documents/upload`、`POST /documents/index`、`DELETE /documents/{doc_name}`、`POST /llmmemory/load` + `/load/progress` | 见 6.3 的两个功能缺口 |

> `/documents/upload|index` 属"后端还活着、前端已失联"：`api.js` 有封装但无人调用，且**全部模板中已无 `<input type="file">`**（🔬 实测零命中）——产品的上传入口随着 `dashboard.js` 一起消失了。

### 6.2 前端资源层面的死面

| 资源 | 行数 | 状态 |
|---|---|---|
| `dashboard.js` | 1,162 | 无模板加载，整文件死 ✅ |
| `api.js` 的 11 个方法 | 125 | 仅 4 个在用；`/data`、`/config` 两页加载它却从不调用 ✅ |
| `chat-enhancer.js` 的 6 个成员 | 146 | 含 55 行与 `chat.js:250` 功能重复的 `scroll-to-top` ✅ |
| CSS 未引用规则 | 119 | 24 个规则块 + 8 个变量 ✅ |
| 模板内联 CSS/JS | ≈3,200 | 不是死代码，但应外链成 `memory.js` / 合并进 `components.css`（缓存+可维护性） |

### 6.3 两个必须一并决策的功能缺口

1. **PDF 上传入口已消失**：`dashboard.js` 是唯一 `type="file"` 的宿主，删掉后没有任何页面能上传。要么在 `/data` 页补一个最小上传控件（复用 `documents.py:108` 的 `_sanitize_upload_filename`），要么明确"只支持手工投放 + `data/pdf` 扫描"并同步删端点与文档。
2. **`POST /documents/index` 是坏的**：`documents.py:222-226` 只传 `doc_name/doc_path/is_complete`，**漏了 `doc_type`**，而 `parse` 节点会抛"不支持的文档类型: None"（`data.py:592-598` 的对照版本传了 `doc_type` 与 `status`）。这个端点前端又恰好零调用，所以长期没人发现。

---

## 7. 重复实现：11 组应收敛为单一实现

| # | 逻辑 | 现有份数 | 位置 | 收敛方案 |
|---|---|---|---|---|
| 1 | 状态文件原子写 | 4 份写 JSON（`write_json_atomic` + 3 处裸 `json.dump`） | `pipeline/paths.py:27`、`session_manager.py:110`、`task_service.py:38`、`config.py`/`search_cache` | `write_json_atomic` 下沉到 `src/utils/json_io.py`（与 `path_guard` 同层），`pipeline.paths` 只 re-export |
| 2 | 文件锁事务 | 3 份 | `registry.py:132-158`（唯一带 Windows 兜底）、`queue_store.py:8,55-64`（顶层裸 `import fcntl`，Windows 直接 ImportError）、`memory/ingest.py:45-61` | 提 `locked_json_transaction(path, load, save)` |
| 3 | provider 解析 | 3 张表 + **14 处硬编码** `"openai"` | `client.py:83-88`、`client.py:803-808`、`settings.py:126-131`；硬编码见 `memory.py:61`、`chat_ingest.py:157`、`job_runner.py:220,243`、`process_web_queue.py:39,60,81,99,156,166`、`orchestrator/agent.py:136`、`memory_search.py:71`、`deep_dive.py:51`、`main.py:744` | `settings.get_provider()` 单入口；删两套 config 读法 |
| 4 | 向量库路径 `f"{doc}_data_index"` | 7-8 处手抄 | `retrieval/utils.py:40`、`indexing/tools.py:109`、`indexing/nodes.py:61/772/851`、`data.py:196/762`、`manager.py:84`；而 `constants.py:188` 的 `VECTOR_DB_SUFFIX` **零引用** | `get_vector_db_path(doc_name)` helper，用上已定义的后缀常量 |
| 5 | 文档索引 | 4 份，state 键已分叉 | `core/indexer.py:123`、`documents.py:207`、`data.py:558`、`process_pdf_queue.py:72` | `index_document_service()` 唯一实现，UI/管线都调它 |
| 6 | 文档删除 | 3 份，其中 1 份路径错 | `manager.py:238`、`documents.py:240`、`data.py:706` | `delete_document_service(confirm=False)`；路径统一 |
| 7 | LLM 返回 JSON 清洗 | 4 份，只有 1 份能解围栏 | `search/utils.py:28`（好）、`retrieval/nodes.py:430,973`（`startswith('{')`）、`metadata_extractor.py:107`（正则） | 提到 `agents/common/`，4 处替换 |
| 8 | 进度上报 `_send_progress` | 3 份 payload 各不相同 | `answer/nodes.py:33`、`answer/tools.py:497`、`retrieval/nodes.py:43` | `ProgressReporter(callback, agent, doc_name)` |
| 9 | 会话统计 | 2 套独立扫描 | `data.py:225-275` vs `session_manager.py:358-393` | 下沉为 `SessionManager.stats()` |
| 10 | 前端 toast/转义/分页/PDF 渲染 | 4/3/2/3 份 | 见 5.5 | `ui-feedback.js` + `pdf-viewer.js` |
| 11 | 两套 MCP 客户端 / 两套抓取栈 / 两套 llmmemory 协议 / 两套 REPL | 各 2-4 份 | `mcp_client.py` vs `SimpleMCPClient`；`scraper/` vs `search/utils.py`；`llmmemory.py:/load` vs `brief_memory.py` | 删旧留新（见第 4 节与路线图） |

---

## 8. 架构与性能

### 8.1 依赖方向的两处地雷

1. `core → pipeline` 的模块级依赖（`registry.py:19`），只为一个函数；下沉 `write_json_atomic` 后自然消失。
2. `client.py:31` 的 `from src.config.prompts import SYSTEM_PROMPT_CONFIG` 击穿惰性聚合（🔬 实测拉起 31 个 agent 模块 + langgraph）。改成 `from src.config import prompts` + 函数内访问即可。

### 8.2 每请求/每任务重复的昂贵构造

| 热点 | 现状 | 影响 |
|---|---|---|
| `VectorDBClient` 构造 | `FAISS.load_local` 全索引 + `embed_query("test")` **真实网络探针**（`vector_db_client.py:53-69,97,352`），全仓 `lru_cache` 命中 0 | 删除文档、建索引、每次跨文档选档都付一次 |
| `MetadataVectorDB` | 每次 `new`，内部再 `get_embeddings()` 新建模型实例 | `/data` 删除接口、CLI 自动选档 |
| 聊天热路径 | 每次 `ask()` 新建 `LLMBase`（`orchestrator/agent.py:135`）；每轮 ReAct 再 `get_chat_model_with_tools()` 新建 ChatOpenAI；`build_graph` 重编译 | 每问固定开销 |
| `deep_dive` | 每次工具调用 `new AnswerAgent(...)` → 新 LLMBase + 新 `DocumentRegistry()` + 重读注册表 JSON | 一轮多文档深挖成倍放大 |
| `/data` 首屏 | 并发打 `/overview` + `/documents`，各自 `rglob` 全目录、逐文件 `stat`，无缓存 | 实测 21 个向量库目录 × 多轮扫描 |

### 8.3 State 与图：可以更简单

- `AnswerAgent` 是 `rewrite → plan → execute → evaluate → generate`，其中 `evaluate` 三个分支全部只写 `is_complete=True` 后返回，且出边无条件——**它只是一个 40 行日志节点**。`plan` 里"已有工具结果"的分支不可达（图不会二次进入 `plan`）。整图可退化为 `rewrite → execute(可空) → generate`。
- 4 个 state 里有 16+ 个字段只写不读；`vector_db_docs` 还把整份 `Document` 列表塞回 state，随图复制。删掉这些字段比"补文档"更划算。
- 8 处调用方各自手拼 state dict（`documents.py` 那份就漏了 `doc_type`），应改为 `new_*_state()` 构造器。

### 8.4 单一的配置事实来源

- `provider`：`/config` 页写入 `data/config/app_config.json`，但聊天（`orchestrator/agent.py:136`）、上传索引（`documents.py:219`）、管线（`job_runner.py:220,243`）、CLI 搜索（`main.py:744`）全部写死 `openai`——**用户在页面上切 provider 实际上只影响文档校验用的 AnswerAgent**。
- `log_level`：`/config` 页有控件，后端不读；日志级别由 4 处模块级 `basicConfig` 抢先定死（谁最后被 import 谁说了算）。
- `embedding` 模型名已单源化（之前的 bug 已修），可作为其他配置项的范式。

---

## 9. 顺带发现的 4 个真实缺陷（重构时一并修）

| # | 问题 | 位置 | 影响 | 修法 |
|---|---|---|---|---|
| D1 | `POST /documents/index` 漏传 `doc_type` | `documents.py:222-226` | 索引必然失败（`parse` 抛"不支持的文档类型: None"） | 补 `"doc_type": "pdf"`；根治靠 D2 的服务层收敛 |
| D2 | `DELETE /documents/{doc_name}` 向量库/摘要路径错误 | `documents.py:274`：`VECTOR_DB_DIR / doc_name_base`（缺 `_data_index`）；摘要路径缺 `_brief_summary` | 🔬 `data/vector_db` 下 21 个目录**全部**带 `_data_index` → 删除只清 JSON/图片，FAISS 与摘要成孤儿 | 走 `get_vector_db_path()`；删除实现合并到 `data.py` 那份 |
| D3 | `rebuild` 清理旧索引用相对路径且缺后缀 | `indexing/tools.py:626-637` | 🔬 同一类问题：`os.path.join(PathConstants.VECTOR_DB_DIR, doc_name)` 永远匹配不到实际目录 | 同上，统一 helper |
| D4 | 测试假绿灯 | `test_cross_doc_flow.py`（110 行 0 断言却报 passed）、`test_parallel_logging.py`（0 用例）、`test_multi_pdf.py::test_menu`（`input()` 死等，有凭据的环境会挂住） | 覆盖率幻觉 + CI 可能卡死 | 删/改写成断言式 pytest |
| D5 🔴 | **真实密钥在工作区裸奔**（交叉验证轮发现） | `src/.env.bak-20260901-094129` | untracked 但 `.gitignore` 挡不住（现有规则只匹配 `.env` 精确名），内含真实 Azure/OpenAI/Gemini key；一次 `git add -A` 即入历史（`git log --all -- 'src/.env*'` 已确认历史干净） | 删文件；`.gitignore` 补 `.env*` `*.bak*` + 审计产物（`ANALYSIS_REPORT.*` / `tools_build_report_html.py` / `_audit/`）；唯一该入库的 untracked 是 `tests/test_brief_load_jobs.py`（连同其配套未提交功能改动一起提交） |
| D6 | pytest 9 下自动 skip 静默失效（4 个测试 error 的根因） | `tests/conftest.py` | `item.fspath` 已被 pytest 9.1.1 移除 → `getattr(item,'fspath','')` 得空串 → LLM_DEPENDENT skip marker 从未生效（表现为 fixture error 而非 skipped）；另一半根因是 `test_answer_agent`×3 / `test_retrieval_agent`×1 的 fixture 本就未定义 | 一行改 `item.path`；补 fixture 或改无参内建构造；`test_menu` mock stdin 或标 skip；两个零断言 print 脚本移出 tests/ |

---

## 10. 重构路线图

> **执行状态（截至本轮重构收尾）**：P0 全部完成（提交 af5708b / d5f7291 / UI-F1 /
> 81c7fe2），P1 的 1–3 完成（4a2b1fc 原子写、d4c056c 路径 helper+D2/D3、
> e90fb2c provider 单入口），R1 检索单入口（retrieval/agent.py `retrieve()`）与
> R2 索引单入口（`index_document()`）也已落地。累计净删约 9,200 行，修复 3 个
> 真实缺陷（D1/D2/D3）+ 1 个并发缺陷（write_json_atomic 固定 .tmp 名多线程抢写，
> 冒烟测试中抓到并修复）。P1-4 的"JSON 清洗 4→1、`_send_progress` 3→1"与
> P1-5 部分决策、全部 P2/P3 未动，列为下一轮候选。CLAUDE.md 已同步实况
> （9fc8fcb）。

### P0 — 纯删除（半天，零风险，≈ -6,400 行）

| 动作 | 净删 | 验证 |
|---|---|---|
| 删 15 个整文件（第 4 节，`sync_pipeline_queue` 除外） | 4,719 | `pytest tests/test_imports.py` + 启动 UI 走一遍 7 个页面 |
| 删 `data.py` 5 个运维端点、`pdf` 图片两端点、`structure` 删章节、`llmmemory` `/load` | ~380 | `curl` 打一遍剩余端点 |
| 删 prompts 死常量、4 个 state 的只写字段、零散死函数 | ~700 | 跑一次索引 + 问答 |
| 删 `api.js` 11 个方法、`chat-enhancer` 6 个成员、CSS 死规则 | ~390 | 浏览器控制台无 404/报错 |
| 删 2 个假绿灯测试文件 + `test_menu` 改交互脚本 | ~180 | `pytest --collect-only` 无 `input()` |
| 删 `.env.bak` + `.gitignore` 补 `.env*`/`*.bak*`/审计产物（D5） | 2 文件 | `git status` 无 untracked 敏感项 |
| conftest `item.path` 一行修 + 3 处 fixture 补定义（D6） | ~12 | 无凭据机 `pytest` 干净 skipped 而非 4 errors |
| requirements：删 streamlit/weasyprint/mcp-server-fetch 3 死条目、lancedb/pyarrow 加上界（唯二无界，LanceDB 维度固定是难排查故障源）、补 psutil/chardet 反向缺口 | ~8 行 | `pip check` 通过且应用可启动 |
| 合计 | **≈ 6,400** | |

### P1 — 收口（1-2 天，≈ -1,200 行，风险中低）

1. ✅ `provider` 单入口，删 14 处硬编码；`/config` 生效。（e90fb2c：
   `settings.resolve_provider()`，Orchestrator 解析一次下发子 agent，
   `IndexRequest` 默认值也改走链）
2. ✅ `write_json_atomic` + `flock` 下沉 `src/utils/json_io.py`，4 份写 JSON 全改。
   （4a2b1fc：session/task/app_config/search_cache 全部原子化，`paths.py` 留
   re-export；顺带修掉 core→pipeline 反向依赖与 task_service 启动恢复）
3. ✅ `get_vector_db_path()` / `get_output_dir()` helper，修 D2/D3。（d4c056c）
4. ✅ `helpers.py` 9 个死函数已删（d5f7291）；JSON 清洗 4→1 与 `_send_progress`
   3→1 已由波次 5-A 完成（4cfe1e4：`src/agents/common/json_utils.py` 统一清洗
   入口 + `common/progress.py` 唯一 emitter，三处 `_send_progress` 签名保留薄
   委托，失败路径语义逐点对齐，88 项断言回归）。
5. ◐ `GET /documents/index` 误列为 GET 的疑虑已随 R2 消除（`documents.py` 现
   调 `index_document()`）；`_session_cache` 与三个空配置开关保留（低风险、
   有注释），`/sessions/current/info` 无消费者但删除需要单独授权——留待决策。

### P2 — 结构（3-5 天，风险中）——2 已完（16a5ccb），余 1/3/4/5 待动

1. ✅（R2 d4c056c + 波次6-B）索引与删除双双收敛：`IndexingAgent.index_document()` 与
   core 层 `delete_service.delete_document_service()` 为唯一实现，三份删除实现并集对齐，
   顺带修掉 4 个真缺陷（CLI 无 safe_path 防护、CLI 漏删 5 个历史摘要命名、三路都漏删
   registry 登记产物、data 端点带 .pdf 请求漏注销 registry）；并与 5-B 缓存协同失效。
2. ✅（波次 5-B，16a5ccb）缓存只收 FAISS 反序列化产物 + embedding 身份指纹进
   key（(mtime_ns,size) 双文件指纹失效），**壳 client 保持每会话新建**——轮次去重
   是实例态，全局单例会造成并行 session 污染（历史缺陷同类）；写路径先 clone 脱离
   共享对象；真实索引热构造 ≈55×。`MetadataVectorDB` 刻意不缓存实例。
3. ✅（波次6-A，6c502fb + 19e067c）evaluate 纯标记节点删除（核实无 LLM 调用、写的
   is_complete 无人消费）、`_build_initial_state()` 统一且全仓测试收口、deep_dive
   按 (doc_name, provider) LRU-32 复用（error/全失败即剔除）。
4. 前端共享层：`api.js` 唯一出口 + `ui-feedback.js` + `pdf-viewer.js`；`data.py` 按 documents/storage/ops 拆三模块。
5. 模板内联 3,200 行外链化。

### P3 — 按需（不阻塞）——未动

- 抓取栈二选一（保留 `scraper/`，把 `search` 内部的 `SimpleMCPClient` 归并过去）。
- `process_pdf_queue` / `process_web_queue` 抽 `pipeline/common.py`。
- README（1,045 行）与 `README_EN`（800 行）重写或标注 deprecated：两份都 0 次提及 memory/pipeline/scraper，且列出 7 个已删模块。**交叉验证轮给出的 8 处实锤失实清单**（以 CLAUDE.md 为底稿逐项修）：① AnswerAgent 写成 ReAct 循环 ×6 处（实为确定性 plan 单轮）② 会话 import/export 端点 ×4 处宣称（sessions.py 实际只有 list/current-info/get/delete/rename）③ localStorage 双存储（全仓仅主题键一处）④ LOGGING_LEVEL ×4 处推荐（代码 0 读取，级别写死在 client.py basicConfig）⑤ 目录树幽灵文件 `config/prompts/agent_prompts.py`、`core/parallel/processor.py` ⑥ 会话按 `{mode}/` 子目录存储的旧说法 + mkdir 指引带 backups/exports ⑦ 代码读取的 31 个 env 有 12 个完全未记载（HOST/CORS_ORIGINS/RETRIEVAL_DEDUP_WINDOW/BRIEFS_DIR/LLM_MEMORY_URL/EMBEDDING_PROVIDER 等），而 `EMBEDDING_DEPLOYMENT` vs `EMBEDDING_DEPLOYMENT_NAME` 两种拼法并存 ⑧ uvicorn 示例 `--host 0.0.0.0` 与仅回环设计相悖。

---

## 11. 不建议做的事

| 想法 | 为什么不做 |
|---|---|
| 引入 React/Vue 重写前端 | 原生 JS 的问题不是框架，是"共享层被绕开"；补 3 个共享文件即可，重写成本 >> 收益 |
| 把 LangGraph 全部换成手写状态机 | 5 个 agent 的图结构本身没问题，只有 AnswerAgent 的 `evaluate` 值得简化；其余（Indexing/Retrieval/Orchestrator）保留 |
| 删掉 CLI（`main.py`） | 仍然有用（批量、无头环境）；只需收敛 3 套 REPL 与 `graph.ainvoke` 手拼 state |
| 删 `/data` 的 `backup`/`reset` 而不留出口 | 有运维价值；挪到 CLI 或加确认页，而不是无声消失 |
| 动记忆子系统的锁语义 | `memory/ingest` 的 `_source_lock` 逻辑正确，只是缺 Windows 兜底；抽公共实现即可，不要改行为 |
| 把 `src/utils` 整个删掉 | `path_guard`、`helpers` 的部分函数、`async_utils` 仍在用；只删该死岛 |
| 追着 prompts 做"提示词工程优化" | 本报告只判断"是否有人读"；prompt 内容优劣需要评测集，不在静态审计范围 |

---

## 12. 附录

### 12.1 主线程实测清单（🔬）

| 结论 | 验证方式 |
|---|---|
| `from src.config.prompts import SYSTEM_PROMPT_CONFIG` 拉起 31 个 agent 模块 + langgraph | `.venv/bin/python` 两个进程对比 `sys.modules` |
| `mcp_client.py` 零 import | 全仓 grep `MCPClient`/`import mcp_client`，只命中 docstring 与文档 |
| `dashboard.js` 无模板加载 | `grep '<script src' templates/*.html` 汇总，无 `dashboard.js` |
| `data/vector_db` 全部带 `_data_index` | `ls data/vector_db` |
| 模板无 `<input type="file">` | 全模板 grep `type="file"` |
| `documents.py` 索引 state 缺 `doc_type` | 读 `documents.py:222-226` 对照 `data.py:592-598` |
| `psutil` 未安装 | `.venv/bin/python -c "import psutil"` |
| `search/tools_config.py`、`download_resources`、`build_vector_index_impl` 零调用 | grep 调用点 |
| `AnswerUtils`/`IndexingUtils` 只被实例化不被使用 | grep `agent.utils` |
| utils 模块依赖簇（test_framework → config_validator/error_handler/file_operations/validators/exceptions） | 逐模块 grep importer |
| `helpers.py` 每函数外部引用数 | AST + grep 统计脚本 |
| 上一轮报告结论现状：H2/H4/H5/H7/H8/H15 已修（`path_guard`、session_id 唯一化、`reset_retrieval_history` 已接、embedding 键单一化、register 守卫、provider 缓存字段） | 逐条读码 |

### 12.2 原始证据

- `_audit/baseline_report.md`：AST 扫描（152 个零引用符号、349 个仅本文件引用、71 个不可达模块）
- `_audit/team/<domain>-scan.json` / `<domain>-verify.json`：7 个域的扫描与红队复核原文（含反证）
- `_audit/baseline_reach.json` / `baseline_deadscan.json`：机读版

### 12.3 各域综合评分（主线程按复核后结论归一化，10 = 最健康）

| 域 | 评分 | 一句话 |
|---|---|---|
| agents | 5.5 | 结构规范，但门面层/state/prompts 大量死面，检索入口两套 |
| core/config | 5.5 | 基础扎实，缺缓存；有一层休眠配置 + 14 个零读取常量 |
| ui-backend | 4.0 | 端点重复与死端点集中，`data.py` 1225 行该拆 |
| ui-frontend | 3.5 | 一个 1,162 行死文件 + 共享层形同虚设 |
| memory/pipeline/services | 5.0 | 两套 MCP/抓取栈，scraper 策略层未接线 |
| utils/utils-entry-tests | 3.0 | 约 73% 不可达，是最大的一块可删面积 |
| 横切 | 3.5 | 单一事实来源被破坏（provider/路径/原子写） |

### 12.4 范围外提醒

上一轮报告的「全部 API 与 WebSocket 零鉴权」已按**本地应用设计决策**处置：默认仅回环监听（HOST 可覆盖且打 WARNING）+ 本地 CORS 白名单（含 `*` 自动关 credentials）+ WS Origin 校验；127.0.0.1 场景下无需鉴权框架。若未来需要非回环暴露，必须先补鉴权（破坏性端点尤其）。与本报告重构项相互独立。
