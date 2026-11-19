# LLM-Memory 接入改造实施计划（HTTP 桥 → SDK/MCP）

> 裁决记录（用户已确认）：①主通道 = **SDK 进程内为主 + MCP stdio 为可选决策面**；
> ②bridge 兜底路 **彻底删除**，`load_brief_date` driver 收敛为 **{local}**；
> ③上游记忆只读暴露：gateway 新增上游门面 + **1 个只读 API**（status/namespaces/search），
> UI 前端除注释外零改动。
> 基线：全量 pytest **316 passed / 6 skipped / 0 failed**（HEAD 58ece3b，ar-scout 实跑）。
> 交接文档的三条禁令继续有效：不共用表、AR 不读上游数据根 env、不把 AR 写路径接进上游 ingest。

## 上游接口事实（upstream-scout 实读实证的，直接用，别再考古）

- 仓库：`/Users/edward_ke/Documents/GitHub/LLM-Memory`，branch main。
- **SDK**：`from llm_memoryd.api import MemoryClient`，方法全同步：
  `remember/ingest/resolve_scope/search/why/pack/status/ensure_ready/namespaces/topics/chat`
  （api.py:159-548 签名）。`search(query, *, namespace=…, on_step=…, cancel_check=…, deadline_s=…)`，
  `status(namespace=?)` 返回各 ns 行数，`namespaces()` 列表。**构造期 `namespace=` 是显式逃生阀**：
  传 "AATF"/"ai-research" 这类字符串合法（ID_RE `^[\w][\w.\-@/]{0,127}$`，vector.py:198），
  **不传才落到 cwd 派生的 `agenticreader-<digest>`**（git.py:210-216；test_memory_client.py:178 钉着）。
  `ingest` 门面层拒绝 `brief` source_type（api.py:301-302）——不要碰这条。
- **MCP**：stdio only。推荐入口 `python -m llm_memoryd.mcp`（`scripts/mcp_server.py` 是 shim 别用）。
  `main()` 只有 `--config/--tools`；默认只暴露 memory_search/ingest/list_topics/list_namespaces
  （mcp.py:94-95），**why/pack 要显式 `--tools` 打开**；`install.py:397-416` 的官方挂载块格式：
  stdio + `env.PYTHONPATH=<repo>/src` + `--tools memory_why,memory_pack,memory_remember,memory_search`
  + `toolCallTimeoutMs`。无 progress/cancel/job 通道（软 deadline 默认 3 轮/20s）。
- **跨 venv 实测**：AR 的 venv（Python 3.12）`PYTHONPATH=<repo>/src python -c "import llm_memoryd.api"`
  直接成功，依赖全有，无需装包——SDK 路就是这么走。
- **旧 webui 已死**：`http://127.0.0.1:8765` 的 `/api/briefs/*` 实测 500；MCP/SDK 无简报加载对应物。
  外部简报加载这条能力**今天就不通**，删除 bridge 不损失可用功能。
- 上游 config 有个反向依赖键 `agentic_reader.pdf_dir/ui_url`——本轮不碰，别把它当 AR 的配置。

## 阶段 1 · 代码（owner: impl-code，write scope: `src/`）

### 1.1 新文件 `src/memory/upstream.py`（~120-160 行）
上游 LLM-Memory 的访问层。**分层纪律**：不 import src.ui / src.agents / fastapi；函数级 import 上游。
- 解析链（仿 migrate_aatf.py:51-59 的多级风格，但**不写死默认绝对路径**）：
  env `LLM_MEMORY_REPO`（strip 后）→ 未设或目录无效 → 上游 **unavailable**，
  一切入口返回 `{"available": False, "note": ...}`，不 raise、不 traceback 刷屏。
- SDK 通道：`_client()` 惰性单例——把 `<repo>/src` 注入 `sys.path`（一次），
  `from llm_memoryd.api import MemoryClient`，构造传 `namespace=None`（调用期再传 ns）。
  上游全同步 → 全部公开 async 函数用 `asyncio.to_thread` 包裹，异常折叠为
  `{"available": False, "error": ...}` 形状，绝不让上游异常裸穿到 UI。
- 公开函数（只读面）：
  `upstream_available() -> bool`、
  `upstream_status(namespace=None) -> dict`（available/namespace 列表/行数/版本+note），
  `upstream_namespaces() -> list`，
  `upstream_search(query, namespace=None) -> dict`。
  namespace 参数经 gateway 的 `resolve_search_namespaces` 语义收敛后传入；
  返回形状里带 `scoped` 提示位，方便 UI 显示"全局搜"。
- MCP 决策面（可选，默认关）：env `LLM_MEMORY_MCP_ENABLED=1` 且 repo 有效时，
  用 stdio 子进程起 `python -m llm_memoryd.mcp --tools memory_why,memory_pack`
  （client 逻辑抄 `src/agents/search/utils.py:39-161` 的 SimpleMCPClient 的 initialize/call_tool/超时
  思路，但**就地写在 upstream.py 或同包新文件**，不 import src.agents——layering）。
  默认路径下这些函数不启用、只返回 unavailable note；接不进去就先按 disabled 实现，
  保证 `upstream_decision_available()` 有个诚实的答案。
- 上游进程会开自己数据根的 app.log——本机沙箱禁写 `~/.llm-memory/app.log` 时，
  SDK import 应仍成功、search/status 失败要折叠成 note，不许 hang。

### 1.2 `src/memory/gateway.py` 收口
- **删除** 187-298 整段：`BridgeError`、`LLM_MEMORY_URL`、`_DEFAULT_BRIDGE_TIMEOUT`、
  `bridge_request`、七个具名一跳 `brief_dates/brief_papers/brief_load/brief_load_progress/brief_chat/brief_chat_progress/brief_chat_stop`、295-297 注记。
- `load_brief_date`（300-328）：白名单改 **("local",)**；`BRIEF_DRIVER_ENV` 常量保留；
  bridge/任何其它值 → warning + 按 local 跑（非法值兜底语义不变）。
  327-328 的反向 import brief_memory 随桥分支一起删——这条"债"正式注销。
- 新增 upstream 门面段：`from src.memory import upstream`，转发
  `upstream_status / upstream_namespaces / upstream_search / upstream_available`
  （gateway 做 namespace 收敛，upstream.py 做 transport；与 browse_*/delete_* 的分工同构）。
- 1-20 docstring：删"webui 桥"表述，改写为"内核 + 上游只读门面"两段。
- 56-186 的 search/ingest/browse_*/delete_*/resolve_search_namespaces **一行都不动**。

### 1.3 删除 `src/ui/backend/services/brief_memory.py` 整文件
全仓引用只有 gateway.py:327（本阶段删）与 tests/test_gateway_semantics.py:66（tests 负责人删）。
删前 grep `brief_memory` 确认 src/ 内无漏网。

### 1.4 只读 API（`src/ui/backend/api/v1/memory.py` 内加路由，不新开 router）
- `GET  /api/v1/memory/upstream` → `{available, note?, namespaces:[{name,rows}], version?}`
- `POST /api/v1/memory/upstream/search` body `{query, namespace?}` → gateway 门面结果原样
  （不返回 (status_code, body) 这种 HTTP 形状——那是旧桥的遗产，别带进新面）。
- 端点走 gateway，不 import 上游细节；失败映射 502/503 由 api 层决定，src/memory 不沾 fastapi。
- 注意 safe_path/输入校验惯例：query 只做非空 str 校验；namespace 走 gateway 三态语义。

### 1.5 配置
- `src/config/settings.py` MCP_CONFIG 加 `"llm_memory"` stdio 条目，形状仿 duckduckgo/web_scraper
  （command=`sys.executable`, args=`["-m","llm_memoryd.mcp","--tools","memory_why,memory_pack"]`,
  env.PYTHONPATH 由 `LLM_MEMORY_REPO` env 派生）。
- 新增 env 文档位：`LLM_MEMORY_REPO`（上游 checkout 路径，唯一寻址点）、
  `LLM_MEMORY_MCP_ENABLED`（可选决策面开关）。这两个替代 LLM_MEMORY_URL 的全部出现位置。
- job_runner.py:60-62 的 load_brief_date 20min 超时**收紧**（local 直写无 LLM，改 10min 或原值均可，
  加一句注释说明 bridge 已删）。

### 1.6 注释清理（src/ 内，一次做完）
briefs.py:122-123、brief_ingest.py:15+126、job_runner.py:272-274、briefs_data.py:34-36、
sessions.py:123——bridge 措辞改"已退役"或删。api.js:132-134 归 docs 负责人。
migrate_aatf.py 与 tests/test_store_path_resolution.py **不动**。

## 阶段 2 · 测试（owner: impl-tests，write scope: `tests/`）
- 删 `tests/test_gateway_bridge_shape.py` 整文件。
- `tests/test_gateway_semantics.py`：bridge 用例（62-76）改写为"driver=bridge 是非法值→warning→local"；
  白名单快照断言 `{"local"}`；66 行对 brief_memory 的 patch 引用随文件删除重写。
- `tests/test_brief_load_jobs.py`：只改 189-192 文案断言，kind=load_brief_date 与三键契约不动。
- 新增 `tests/test_bridge_retired.py`，仿 test_filelock.py:23-40（AST）+ test_store_path_resolution.py:46-53（文本）双写法：
  ① AST 扫 src/：`bridge_request`/`BridgeError`/`LLM_MEMORY_URL` 名字与 `httpx` 对 8765 常量的引用不得出现
  （gateway 的 `hasattr` 快照断言也放这里）；
  ② 文本扫 src/：`8765`、`scripts/webui` 不得出现；
  ③ driver 白名单快照。
- 新增 `tests/test_upstream_facade.py`：假 MemoryClient 注入（monkeypatch upstream 的 client 工厂）
  测 available/状态形状/search 直通/异常折叠/未配置降级 note，全程离线不碰上游库。
- `tests/test_imports.py` 模块清单加 `src.memory.upstream` 一行。
- 每步先跑桥契约组，收尾跑全量（基线 316/6 对齐）。

## 阶段 3 · 文档（owner: impl-docs，write scope: README*.md、CLAUDE.md、api.js 注释行）
- README.md:163,217-218 + README_EN.md:164,218-219：删 MEMORY_BRIEF_DRIVER/LLM_MEMORY_URL 两行，
  换成 `LLM_MEMORY_REPO` / `LLM_MEMORY_MCP_ENABLED` 说明 + "外部桥已退役"一段。
- CLAUDE.md:244（LLM-Memory 桥段重写）、272-273（env 表两行换名）、103 附近 gateway 描述句。
- src/ui/static/js/api.js:132-134 注释里"外部桥仍可达"的暗示删净。
- 注意 README 里"整库测试数量"之类的旧数字别照抄，基线以 316/6 为准。

## 验收
1. 全量 pytest ≥ 基线（316/6 量级，允许新增测试使 passed 上升）。
2. `grep -r "8765\|scripts/webui\|bridge_request\|LLM_MEMORY_URL" src/ tests/` 命中为零
   （README/CLAUDE 的历史叙述允许出现，写清楚是退役说明即可）。
3. 默认（不设 env）行为零变化：local 加载、自库检索、Orchestrator 一切照旧；
   上游门面报 available=False + note。
4. `MEMORY_BRIEF_DRIVER=bridge` 只降级为 warning→local，不再有任何出网 HTTP 调用。
```
```
