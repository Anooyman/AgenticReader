# AgenticReader × LLM-Memory 整合实施蓝图

> 本文档由 team-agents 工作流（5 个分区分析师 + 1 个整合师，2026-11-13）交叉核对两仓代码后产出。
> 所有裁决点均附行号证据；执行前请先解决文末的阻塞决策项。

# AgenticReader × LLM-Memory 整合实施蓝图（终稿）

以下蓝图基于 5 份分区报告交叉核对产出。所有**裁决点**均经实际读取两仓代码核实（附行号证据），报告间矛盾处不照抄。

---

## 一、蓝图总述

**收敛目标**：按 D1，把"两套记忆系统"收敛为**一个 SDK 内核 + 两个宿主**。B 侧将 `common/vector + ingest_mid + retrieval/agent_search` 收进一个名为 `llmmemory` 的可 pin 包（公开 API 三件套：store / ingest / search），并以 git tag 形式 pin 进 A 的 `requirements.txt`；A 删除 `src/memory/` 中的存储、ingest 编排、检索实现，只保留 **policy 层**（`adapters/` 的两个切块策略、provider glue、`DEFAULT_SEARCH_NAMESPACES` 白名单常量）。**一份代码，两边复用**——桥只瘦身不加密。

**数据边界**（D4 铁律）：外部 AATF 简报数据**永远不进** AgenticReader 的 repo 或 `data/` 目录——本地 SDK 直写时落点在 **B 的 `DATA_DIR/memory`**（支持 env 覆盖，拒绝静默回退到 A 目录）；A 自己库中的 namespace 写入约定（`ai-research`/`webapp-chat`）不动；读侧缺省白名单成为"外部库不参与对话检索"的唯一防线。

**总体思路**：先用零 B 依赖的纯 A 改动打通 D2/D3 的两条"断线"（namespaces 透传、chat stop 代理），并行推进 B 侧建包；SDK tag 落地后做 A 内核替换，最后把 brief 加载 driver 从 HTTP 换成本地 SDK 执行，收尾清理零消费端点与过期文案。每一步都可独立回滚。

---

## 二、分阶段实施计划

### Phase 0 · 独立速改（无需任何前置）

**目标**：不动存储/检索内核，先把两处"已经铺好只差接通"的线和几处确定性 bug 修掉，为后续大动刀降风险。

| # | 改动 | 位置 |
|---|---|---|
| 0.1 | `DEFAULT_SEARCH_NAMESPACES = [NAMESPACE_AI_RESEARCH, NAMESPACE_WEBAPP_CHAT]` 常量 | `src/memory/config.py:27-28` 后 |
| 0.2 | `chat_service` 调 `orchestrator_ask(..., namespaces=session.get("memory_namespaces"))` —— D2 链路上唯一断的一跳 | `src/ui/backend/services/chat_service.py:230-238`。已核实该调用确实只传 5 个实参；`agent.py:118/68-70/188-189` 的注入链完整 |
| 0.3 | session 字段 + 写入口：两处 `create_session` dict 加 `memory_namespaces: None`；新增 `PATCH /sessions/{id}/memory-scope`（校验值 ∈ 本库常量 ∪ 已注册外部白名单） | `src/ui/backend/services/session_manager.py:162-174, 214-226`、`src/ui/backend/api/v1/sessions.py`（仿 `rename_session` 范式）。已核实现 session dict 无任何 namespace 字段，sessions.py 只有 rename |
| 0.4 | `memory_search` 工具描述删掉 "Searches across ALL memory by default"，改为"缺省检索本项目自有记忆" | `src/agents/orchestrator/sub_agents/memory_search.py:33-36`（已核实原文确如此）与 `:62` 的 `effective_namespace=None` 改缺省常量 |
| 0.5 | 补代理 `POST /api/chat/stop/{job_id}` → `_lm()` 纯透传 | `src/ui/backend/api/v1/llmmemory.py`。已核实 B `server.py:1573-1580` 端点存在（flag 写入式 cancel） |
| 0.6 | 修确定性 bug：`memory_browse.py:23` 的 `get_embedding_dimensions("azure")` 写死 → `resolve_provider(None)` | 已核实，ingest/search 两侧维度解析不一致的窗口确在此处 |
| 0.7 | 过期文档修正：A 侧"那边 brief load 没接任何并发上限"的两处注释（`llmmemory.py:71-82`、`brief_memory.py:6-11`）改为"那边有 per-registry cap=8（B `server.py:902-912` + `jobs.py:119-138` 已接入 `_reserve_job`），A 串行=1 仍是我们的闸门" | 已核实 B `_post_briefs_load` 确实走 `_reserve_job` |
| 0.8 | 前端配套：`api.js` 加 `stopChat`/`setMemoryScope` 封装；`/memory` 页 chat 加"停止"按钮（`memory.js:685-717` 把 timer 记入 state）；`/chat` 工具条加记忆范围浮层 + chips 显示 | `static/js/api.js`、`static/js/memory.js`、`static/js/chat-enhancer.js` |

**验收**：新增 `test_namespaces_default.py`（monkeypatch `agentic_search`，断言缺省恰为两自库）通过；`/memory` 页能停掉在飞的 chat job；provider 非 azure 时 `/data` Memory tab 不再维度错乱。**回滚点**：全部小 diff，revert 即净。

### Phase 1 · B 侧 SDK 建包（与 Phase 0 并行，B 侧主导）

**前置**：B 侧接受"包名 `llmmemory`、三件套公开面"的定案。

1. `pyproject.toml`：setuptools 映射式建包（`scripts/common→llmmemory/_core/store`、`scripts/ingest_mid→…/ingest`、`scripts/retrieval→…/search`），保留 compat 层保 B 自己 webui/CLI 在 164-commit 重构流中不断——已核实 B 现在全靠 `sys.path.insert` + `from common.x` 顶层包名，且 `common` 必撞名不能直发。
2. 公开 API 三件套：
   - `MemoryStore(data_dir, *, dimensions, embed=...)`——门面收敛构造面分歧（已核实 A 是 `(data_dir, dimensions)`、B 是 `(data_dir, config)` 且强制 `config["embedding"]["dimensions"]` 无默认，B `vector.py:431-446`）。
   - `ingest_source(path, source_type, namespace, *, store, adapter, ...)` + `SourceAdapter` 基类 + 内置 adapters（含 `BriefAdapter` 与 `briefs.run(root, namespace, store_dir, config, since, until, ...)` 入口——已核实 B `brief_ingest.run:356-359` 签名含 since/until/force，A 的"一天一 job"模型可原样保留）。
   - `agentic_search(query, *, store, namespaces=None, allowed=None, llm, max_iterations, deadline_s=None, cancel_check=None)`——**同时带 B 的 `allowed` 硬天花板（已核实 `agent_tools.py:59-86` 的 subset-reconcile 语义）与 wall-clock budget（已核实 `agent_search.py:343-357` O1 已落地）**。
3. SCHEMA_VERSION 双轨（文件标记 + 表列，B `vector.py:468-488` 迁移机制旁）；A 的旧 `data/memory_db` 首开认"无标记=v1"。
4. `scripts/tests/test_sdk_surface.py` 签名冻结测试；打 tag `v0.1.0`（基线见开放问题 OQ-9）。
5. **adapters 语义升级**：B 的 `UpdatePlan` 带 `stale_replacements` 门控、删除推迟到写入循环后（已核实 B `base.py:64-67`、`ingest.py:624-661`、`webapp_chat.py:159-164`）；A 现在 ingest 是先删后写且无门控（已核实 `src/memory/ingest.py:112-116`——一次 LLM 抽取失败即永久丢尾块，此缺陷随 SDK 换心自动消除）。
6. `occurred_at` 统一 UTC 归一化进 SDK（已核实 B `ingest.py:97-110` 的 `to_utc_iso`，A 现在透传原文）。
7. LICENSE 补齐排在"将来发 PyPI"之前即可，git-pin 阶段不阻塞。

**验收**：B 自己全仓测试绿（B 是唯一有真离线套件的端——已核实 `scripts/tests/` + fake LLM + temp DATA_DIR）；`pip install git+...@v0.1.0` 可装。

### Phase 2 · A 侧内核替换（依赖 Phase 1 的 tag + Phase 0）

**目标**：`src/memory/` 变成 glue + policy。

1. 新建 `src/memory/glue.py`（40-60 行）：`build_ingest_context(provider) -> (MEMORY_DB_DIR, get_embedding_dimensions(provider), LLMBase→SDK 协议的 embed/llm 适配器)`。收敛三处重复的"自建 LLMBase+维度+VectorStore"（已核实 `ingest.py:101-103`、`search.py:212-214`、`memory_browse.py:23`）。session 历史语义只在 glue 封装一次，不反向污染 SDK prompt 调用。
2. 删除：`vector_store.py`、`parsing.py`、`ingest.py:68-200`、`llm_condense.py` 的 prompt 与调用面——替换为 SDK 转发壳；`__init__.py` re-export 保住 `test_imports.py:30` 基线。
3. `adapters/` 改为 SDK `SourceAdapter` 子类的注册表（`source_id/parse/chunk/update_plan` 四方法形状，config 不进签名；B 的 7 个可选 hook 全用 no-op 默认，**刻意不引入 snapshot/rechunk/quality**）。注册表换到 SDK 注册面，`get_adapter` 名字不变。
4. 三个写入调用点换 SDK 入口 + glue，参数语义零变更：`src/pipeline/common.py:133-161`、`process_pdf_queue.py/process_web_queue.py`、`chat_ingest.py:153-160`、`sync_memory_ingest.py`。
5. `memory_browse.py:106-128` 逐条 delete 循环 → SDK `delete_where`（自带 unscoped 护栏），API `deleted` 计数形状不变。
6. requirements 加 `llmmemory @ git+https://github.com/...@v0.1.0` 行，lancedb/pyarrow 上界声明移交 SDK pyproject 并与 A 对齐（A 现 `<0.37/<24`，B 现无上界——已核实，这是两边共同的雷，必须在 Phase 1 的 pyproject 里就声明）。
7. **D2 硬天花板在 SDK 入口层落地**：A 的 glue 传 `allowed=DEFAULT_SEARCH_NAMESPACES`。语义约定定为 **`None`=自库缺省、`"*"`=全部**（底层 `_where` 的 None/* 不过滤含义不动，已核实 `vector_store.py:130-147` 把两者都当全库——不在底层拆，只在上层加 allowed 层，避免静默反转 browse/orchestrator 的"省略=全部"）。`/api/v1/memory` 的 `POST /search` 缺省改显式传 `"*"` 并加三态 UI。
8. `test_memory_sdk_smoke.py`（假 embed 端到端）+ 导入清单加 `llmmemory`。

**验收**：全量测试绿 + 冒烟全绿；同库读写行为与替换前 diff 收敛为零（除 schema 空列与 UTC 串两处预期变化）。
**回滚点**：转发壳替换是一次原子提交，revert 后回到 Phase 0/1 状态完全可运行。

### Phase 3 · D3 桥接瘦身（依赖 Phase 2）

**前置条件——store 落点必须先钉死**：`store_dir = os.environ.get("LLM_MEMORY_STORE_DIR") or <B 的 MEMORY_DATA_DIR>/memory`，**绝不允许缺省落到 A 的 `data/memory_db/`**；首跑用 `dry_run=True` 做落点自检。这一步前置于任何 driver 切换，防止"写错库"这种最难看的污染（错库的数据既不归 B 的 `/dates` 管、也不属 A 的两条 namespace）。

1. `brief_memory.load_date` 整文件重写：HTTP+轮询 → `run(root, namespace="AATF", store_dir=…, config=…, since=date, until=date)` + `to_thread` 包装（已核实 SDK 侧 `ingest_source_agentic`/`run` 全同步无 async——直接 await 会卡死 uvicorn 常驻 worker，必须仿 `render_report` 分支的 `to_thread` 范式）。契约 `{loaded, skipped, errors}` 不变，`loaded = bool(rep["processed_dates"] or rep["skipped_dates"])` 复刻 B `server.py:697-701` 映射，`skipped` 从此才有真值。
2. **一次性切 driver，不留双分支**（`retry_job` 会把历史失败 job 直投新 driver，双分支=未可测行为）；`_LOAD_KIND`、job 账本形状、`tests/test_brief_load_jobs.py:102` 的 monkeypatch 接缝全部保持，并加第四 case `loaded+skipped=True→ok` 与 driver 抛异常 case。
3. `/load` 退役：改 alias（`_normalize_dates` 后逐日 enqueue，返回体补 `job_id: None` 合成键防 KeyError）；`/load/progress` → 410 指向 `/api/v1/jobs`。已核实 `/load`、`/load/progress`、`/papers` 三条在 `api.js`/`memory.js` **确零消费**（`api.js:348` 的 `/api/v1/briefs/load` 是 A 自己 briefs 页的路由，不相干），退役无前端断供。
4. `/dates` `/papers` **维持透传不本地化**：已核实 B `server.py:615-637` 的 dates 数据源是 `brief_ingest._load_state()` + 目录扫描、papers 来自 `JSON_DIR/*.json` 文本解析——本地化等于在 A 里复刻 B 的目录布局知识，正是 D4"桥不引入新强耦合映射"要避免的。唯一连带义务：写侧注释钉死"本地 driver 与 B webui 必须指向同一 DATA_DIR"。
5. 文案：`templates/memory.html:38` 的 `namespace=AATF` 硬编码改常量可 env 覆盖；"外部那一轮无法中断"只对 load 保留（`to_thread` 线程不可被 `wait_for` 杀，取消=停止跟踪），chat 侧因 stop 代理落地改为真中断。`memory.js?v=4` bump。
6. 迁移顺序铁律：**store 落点定 → stop 代理 → 一次性切 driver → `/load` 转 alias**；并运维关停 B 的 load 入口防双跑窗口（B 的 `state["done"]` 是 check-then-act 无 flock，已核实 `brief_ingest.py:377-380`）。

**验收**：`test_brief_load_jobs.py` 四 case 绿；重复点"加载已加载日期"显示成功而非失败；B 的 `/dates` 徽章与新 job 账本一致。

### Phase 4 · 收尾（依赖 Phase 2/3）

- 零消费清理与 `api.js` 注释；`/config` 全局缺省 namespace 与 session 覆盖的优先级合并（见 OQ-7）；`/data` 检索测试显示命中 namespace + "跳过白名单"开关；`manage.html` 检索下拉三态化；若选 per-message 覆盖才需动 WS 协议（建议不做）。
- B 侧 webui/CLI 内部改吃 SDK 自己的包——属 B 侧重构项，不阻塞 A 的任何发布。

---

## 三、阶段依赖与建议执行顺序

```
Phase 0 (纯A速改) ──┐
                    ├──► Phase 2 (A内核替换) ──► Phase 3 (D3瘦身) ──► Phase 4 (收尾)
Phase 1 (B建包,tag) ┘
```

- **Phase 0 与 Phase 1 完全并行**（互不依赖）；Phase 0 的 0.2-0.5 甚至独立可先上线，其效果是"软缺省"，Phase 2 换 SDK 后升级为硬天花板——两处改动形状一致，不会返工。
- Phase 2 依赖 Phase 1 的 `v0.1.0` tag 与 Phase 0 的 glue 前置。
- Phase 3 唯一强依赖 Phase 2（需要 SDK 的 brief `run` 入口）；store 落点决议是它的硬前置。
- **建议执行顺序**：0.1/0.2/0.4 → 0.5/0.6 → 0.7/0.8（随 B 建包并行推进）→ 1 → 2 → 3 → 4。若 B 建包拖期，A 侧可长期停在"Phase 0 完成态"运行——功能不依赖 SDK。

---

## 四、风险清单

| 阶段 | 最大失败模式 | 缓解 | 回滚点 |
|---|---|---|---|
| Phase 0 | `namespaces` 注入误伤既有检索行为（LLM 显式传 namespace 的越界路径仍开放——注入语义本就是"补值"非"天花板"） | 白名单测试先跑；Phase 2 补硬层 | 单 commit revert |
| Phase 1 | compat shim 与真实包 import 双轨期，B 的 164-commit 重构流撞上路径守卫测试 | 签名冻结测试先行；重构窗口错峰合并 | tag 前每个 commit 都可 revert |
| Phase 2 | **维度/provider glue 错接** → 建表宽窄错乱、读写静默错位（写不进=好症状，能搜出错向量才是暗坑）；白名单语义反转使既有 browse 变"搜不到东西" | smoke 用确定性假 embed 断言向量宽度；三处调用面替换前 grep 清零；`"*"` 语义同步所有入口 | 转发壳替换 = 一次原子提交，revert 即回旧 fork |
| Phase 3 | **store 落点写错目录**（第三套库 / 写进 A 的 `data/` 直接违 D4，症状延迟到检索才发现）；双 driver 并存期同日期双跑；"已加载"徽章与 B 的 state 脱钩显示假状态 | dry_run 落点自检做进首版发版检查单；一次性切 driver；运维关停 B 的 load 入口 | driver 重写独立 commit，账本形状未变可放心 revert |
| Phase 4 | 删"零消费端点"误删手工脚本依赖 | 走 deprecation 头再删 | 纯删除类 commit |

---

## 五、开放问题（需用户拍板）

1. **本地 brief 写入的目标库**（阻塞项，最高优先级）：推荐 **写 B 的 store 目录**（`LLM_MEMORY_STORE_DIR` env 覆盖）——与"外部数据不进 A 的 data/"零冲突风险、读侧 `/dates /papers /chat` 保持纯透传；若改写 A 库则必须同时本地化 `/memory` 页 chat，否则出现"加载了但 chat 搜不到"的断链。附带结论：SDK 需内置跨进程 store_lock，否则切 driver 前必须运维关停 B 侧 load。
2. **SDK 的 LLM 注入面形状**：推荐"调用方传入协议实现"（glue 只薄薄一层），而非"config dict 内部建 client"（阻塞项）。
3. **importance 缺省 0.6（A `llm_condense.py:151`）vs 0.5（B `llm_ingest.py:596`）** 统一到哪侧；summary 下限 0.7 一并参数化进 SDK config 键。
4. **occurred_at 归一化是否回填老行**：建议不回填、留独立 backfill 动作。
5. **schema 宽度**：推荐接受 SDK 单套宽 schema（A 新行多出 tier/access_count 等空列，与"只一份存储代码"的收敛目的自洽）（阻塞项）。
6. **`None` vs `"*"` 的读侧新约定**：`None`=自库缺省、`"*"`=全部，底层 `_where` 不动——需同步 docstring、`/data` 检索三态 UI 与桥 chat 缺省。
7. **记忆范围粒度**：session 级字段命名 `memory_namespaces`（不与 `ask()` 形参撞名）；UI 落点工具条浮层 vs `doc-picker-modal` vs `/config` 全局层，优先级"session 覆盖 > 全局缺省"；per-message 覆盖建议明确不做。
8. **本地 load 的取消语义**：文档化"取消=停止跟踪"（零成本）还是要求 SDK `run()` 本轮就带 cooperative `cancel_check`。
9. **v0.1.0 tag 基线与 0.x 节奏**：B 高频重构中，tag 打 HEAD 还是 retrieval 冻结点；0.x 期间允许破坏性变更需配"A 的 pin 测试必须先红后绿"规矩。
10. **CI 真 git-pin 的鉴权**：A 的 CI 真 `pip install git+...` 需 PAT + https 镜像（remote 目前是 ssh 别名，pip 解析不了）vs 冒烟测试挪 B 仓跑、A 只留 import 断言。
11. **B 依赖上界**：B 现 `lancedb>=0.6.0` 无上界、A 现 `<0.37`——现在就在 SDK pyproject 对齐并写入 A 侧保留显式上界。
12. **是否顺带引入 B 的检索新能力**：budget / 统一 chat() / 分数合并三项随 SDK 白拿；`time_search` 本轮不进，日期继续靠"加载哪些天"隐式限定。
13. **`/load` 退役姿态**：推荐 alias 排本地 job（兼容手工 curl）；备选 410 硬切 / deprecation 头观察期。
14. **`/data` 页 Memory tab 的检索测试**是否豁免白名单（作为调试入口保留全库能力）。

以上第 **1、2、5** 项是 Phase 1/2 开工前的**阻塞决策**，其余可在对应 Phase 前分批定。
