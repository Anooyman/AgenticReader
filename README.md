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
- **Orchestrator**：Web 聊天的真正入口，ReAct 循环自主决定调用 `search_memory`（查长期记忆）、`deep_dive_document`（深挖某文档原文），会话勾了"网络搜索"时还能调 `search_web`（→ SearchAgent），多个工具调用并行执行；工具集按会话的启用勾选裁剪（前两个恒开，第三个要开关才进）

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
- 会话服务端落盘 `data/sessions/{session_id}.json` 平铺文件；浏览器端只保存界面偏好：主题存 `AgenticReader_theme`，中英文语言存 `AgenticReader_lang`

### 🌐 中英文界面
- 顶栏右侧新增语言切换按钮，可在中文 / English 之间切换；偏好会持久化到 `localStorage`
- 全局 i18n 覆盖主要页面：`/`、`/chat`、`/data`、`/config`、`/structure`、`/briefs`，动态插入的 UI 节点也会自动翻译
- LLM 回复正文、文档内容、模型/provider/env/namespace 等技术标识不强行翻译

### 🧠 长期记忆（src/memory/）
- 单 LanceDB 表 `memories`，按 namespace 隔离：`ai-research`（简报/文章摘要）、`webapp-chat`（对话历史）与 `AATF`（简报卡片导读轻量入库）
- **chat_ingest 后台车道**：周期扫描会话目录，把"有新内容 + 已静默 + 完整问答"的会话自动入库（按内容 hash 幂等去重，水位线在 `data/pipeline/chat_ingest_state.json`）
- **简报轻量入库**：`/briefs` 页"轻量入库(全天)"按钮把当天简报卡片的中文导读写进 `AATF`，重管线（`/load`）与轻量入库二选一或都点；走上游时它递的是"卡片 JSON + 上游 ingest"，会过一轮 LLM 抽取、幂等归上游（详见下方"记忆收敛"段的代价说明）
- **agentic_search**：semantic / keyword / keywords-pool / list-by-source 四工具的 ReAct 检索循环（上限 4 轮），供 Orchestrator 调用；缺省范围是 ai-research + webapp-chat，`AATF` 需在 `/chat` 的记忆范围里勾选
- `/data` 页 Memory tab 提供概览、检索、删除（单条 / 按来源 / 整个 namespace）

### 🧠 记忆收敛 Phase 1–2（写/读/删路由到上游 LLM-Memory）

本仓库的存储本身仍由 `src/memory/` 这层维护，外部 LLM-Memory 只是被寻址的上游；**在哪儿写、从哪儿读的决定点只有一个**——`src/memory/gateway.py` 的 **auto 路由**：`LLM_MEMORY_REPO` 有效且可达就走上游，否则回落原来的本地旧路并打 warning，调用方签名一律不动。看这把开关的是 `gateway.search()` / `gateway.ingest()` 加上一组 `gateway.delete_*`（mode 的取值也只在 `src/memory/config.py` 一处解析，非法值 warning→`auto`），再加上一组 `browse_*` 行级浏览原语（读路允许回落本地，但回落必留 warning）。Phase 1/2/3 的具体口径：

- **三条写通道都接上游**：管线 `ingest_source()`（`ai-research`）、chat_ingest 车道（`webapp-chat`），以及 `/briefs`"轻量入库(全天)"——后者现在递的是"卡片 JSON + 上游 `ingest(source_type=brief)`"，并且**沿用 item_id 当 source_id，id 空间没有换轨**（原先预告的 `aatf-<date>-<kind>` 因为上游补了 `source_id` 透传而省掉了）。写路上**不回落**：`LLM_MEMORY_REPO` 没设/无效（路由判定为不可用）时照旧写本地 `data/memory_db`，但上游可用却写失败时 gateway 直接把失败抛给调用方（chat_ingest 的水位线、job_runner 的任务账本照常记一笔），绝不顺手再写一份本地——那是双写，同一份内容两处落库而水位线照推。要把路由整体退回本地只有两条正经办法：重试，或者 unset `LLM_MEMORY_REPO`／设 `MEMORY_STORE_MODE=local`。除此之外，两个变量都不设时行为与收敛前逐字节一致，dev/CI 零变化、切换可逆。
- **检索通道可回落**：gateway 的 `search()` 上游可用即转上游（多 namespace 直接透传），上游不可用或这次检索没成则走本地 `agentic_search`——这是读写唯一的差别；上游返回的宽表行由映射层摊平成子 agent 一直在吃的形状，`occurred_at` 日期字段保留，`/briefs` 的按日聚合口径不变。形状层**保真优先**：上游 schema 里本就有的列（含 `chunk_hash`，summary 行取空串）给了就直接用真值，只有结果行没把某列交出来时才退回启发式，不多塞任何一个键。
- **存量不迁移，"删了重灌"**：`data/sessions/`、`data/pipeline/summaries/`、`BRIEFS_DIR` 本身就是可重建的事实源；`data/memory_db` 在收敛生效后只作为**只读兜底**存在，不是第二份真相。
- **重复 ingest 的幂等归上游**：走上游时 AR 侧不再自己算 chunk-hash，去重交给上游 ingest 自带的 hash-dedup（同一文件再递一次应返回 0 新增，这条由测试钉着）；回落本地旧路时仍按原来的内容 hash 幂等。论文"下载即入库"的 `POST /briefs/fetch-pdf` 与文档对话能力都不受影响。
- **删除面也接了上游，且这已是两个存储**：`/data` Memory tab 的三种 DELETE（单条 item / 按 source / 整个 namespace）走 `gateway.delete_*` → 上游 delete/delete_where，**同一条不回落纪律**，并且带着两个边界守卫——跨 namespace 的 id 直接拒（不许拿一个 id 去删掉别处的行）、unscoped 删除（既不给 id 也不给 namespace）一律拒，措辞与 `memory_browse` 期待的形状对齐。形状上有个例外值得记一笔：`gateway.delete_*` 三个函数**保持 sync**，不像 `search()`/`ingest()` 那样 async + `to_thread`——上游调用由线程池硬封顶，事件循环不被拖住由调用层保证。语义要说准：删的是**上游存储层**里的行，本地旧库 `data/memory_db` 的对应行**不受影响**——两个库现在是两套存储，别按"一个库里删掉了"去理解，也不存在"删了上游还能从本地捞回来"。
- **计数层并上了上游（只读）**：`/api/v1/memory/overview` 与 namespace 列表把上游 `namespaces()` 的行数并进来，`/data` 页能同时看到两边各自的计数；这纯粹是计数层的只读并列；行级浏览本身也已经上了路由——上游可用时翻的是真行，翻不动才回落本地，并且一定留一条 warning。
- **上游的配置由上游自己报**：`GET /api/v1/memory/upstream` 多了一个 `config` 块——存储目录、向量维度、embedding/chat/insert 用哪个模型、认哪些 `source_type`、版本号，全部来自 `MemoryClient.capabilities()` 的原文，AR 一个键名都不改；这一面读不到时只写 `config_note`，绝不拿本仓自己的常量凑一个像样的答案。
- **三条已知代价**（写明白，不算 bug）：① 记忆侧的 LLM/嵌入配置**归上游 config 管，`/config` 页管不到**，`/config` 的 provider 选择也不改变这一点——上游嵌入端点当前是局域网地址，机器不在该网段时上游路整体不可用，全靠上面的 auto 回落兜住；② AR 递过去的是"已摘要文件"，上游 ingest 会再抽一遍，同一份内容过两轮 LLM——**这句现在是有实测的，别把它当成已经省掉了**：拿一份真摘要 `data/pipeline/summaries/pdf/2607.24653.json`（`qa` 与 `qa_brief` 六个维度全都在）走 `ingest(source_type="ai_research")`，**94.3 秒、7 个 chunk 全新增、0 失败**。`qa`/`qa_brief` 确实传下去了，但它们进的是**正文**（每维度一个 `role=qa` unit、速览一个 `role=brief` unit），上游照旧对每个 chunk 跑一轮抽取；"显式传下去当现成摘要"这条路**目前不存在**，真要省这一轮得等 LLM-Memory 那边的 prepared 通道（见上游 `MEMORY-OWNERSHIP-AGENTICREADER.md` §8）。③ "轻量入库(全天)"**不再是零 LLM 调用**——那条旧承诺（"解析卡片直写、一次 LLM 都不调"）随上游 `source_type=brief` 通道**正式作废**：上游跑的是 agentic 抽取管线，一张卡片一轮抽取，卡片多的那天明显变慢。同时"这天/这卡是否已入库"的**判据也换了**：本地旧路看 chunk-hash，走上游后看的是上游报回来的 `chunks_added == 0`（那就是"已经在了"，不是失败也不是空跑）——别拿 chunk-hash 那套去推上游路上的状态。

要绕开上游按旧路跑，用 `MEMORY_STORE_MODE=local` 这个 kill switch（默认 `auto`）；它和 `LLM_MEMORY_REPO` 都不设，就是全部走旧路。

测试端也做了同一件事：`tests/conftest.py` 有个 autouse fixture 默认掐掉
`LLM_MEMORY_REPO` / `LLM_MEMORY_MCP_ENABLED` 并清空 SDK 单例，也就是说
**跑测试和跑应用共用一个真库这件事已经不是默认行为了**——哪怕你的 shell 里
设了这个变量，测试仍然是离线的（实测同一批用例在设与未设两种环境下都是
秒级完成）。需要接上游的用例自己 `setenv` + 塞假 `_client`，那是显式选择。

反方向也有一个档位：`MEMORY_STORE_MODE=upstream` 把回落本地这条路**明着关掉**——
上游不可达就抛错，而不是“这次先写本地”。差口从来不是路由接错造出来的，是一次次
“先写本地”攒出来的，所以想让“只认上游”有约束力，得让它在一处抛错，而不是在每个
调用点各自小心。`local` 仍是有效的逃生口：这不是不许有备用方案，是不许没有备用
方案却装作有。

上游那侧需要的三个改动（delete facade、`source_type=brief` 枚举、`ingest` 的 `source_id` 透传）**现在都已在上游 main 里**：用户侧自己把它们提交了（`888f966` 把三件全部纳入、`f181999` 补 docs，已推 github/main，HEAD `f181999`；AR 侧探对着新 HEAD 跑也是 15/15 过）。**这是用户侧的提交动作，不是本仓的**——本仓一条都没往上游合。`tools/upstream-patches/` 的副本已删——三件在上游既有，仓内留着没有继续存在的理由，需要回看当年的 diff 时 git 历史里捞。当时的路径是"先在 `/tmp` 干净克隆里叠 01 → 02 → 03 验一遍"（各自 `git apply --check` 干净通过、叠满后上游全量套件 2114 passed / 4 skipped 全绿，pyflakes 门与"不广告破坏性工具"那条 MCP 纪律都没被碰坏），验证完才由用户落进 main，所以现在没有"还得自己打补丁"这回事，也别把这三片当成待办清单。此前那句"三片还停在主干之外、要不要打上由用户自己定"的旧口径一并作废。阶段划分与裁决记录在 [PLAN-MEMORY-CONVERGENCE.md](PLAN-MEMORY-CONVERGENCE.md)。

### ♻️ 存量重灌（Phase 3 · `python -m src.memory.converge`）

存量**不迁移**——三个事实源本身就躺在本地，所以这里做的是"重灌"而不是"搬家"：`src/memory/converge.py` 是单文件 CLI，`data/memory_db` 的一行都不读、也不搬，收敛生效后它只是只读兜底。映射与三条常驻写通道**逐字对齐**，不另立 id 空间：`data/pipeline/summaries/{pdf,web}/ → ai_research / ai-research`、`data/sessions/*.json → webapp_chat / webapp-chat`、`BRIEFS_DIR/<date>/*.html` 卡片 `→ brief / AATF`，`source_id` 分别是 item_id / session_id / 卡片 item_id。

```bash
python -m src.memory.converge                              # 缺省＝dry-run：只枚举，零写入
python -m src.memory.converge --apply                      # 真递上游
python -m src.memory.converge --only briefs --limit 50     # 只推一路、每源各截前 N 条
python -m src.memory.converge --apply --retire-old-db      # 末位是占位：只打印，不执行
```

- **dry-run 一个字节都不写**：连 `MemoryClient` 都不构造——构造它看着无害，其实会让上游按自己的规矩把 store 目录撑开（`~/.llm-memory/` 下多出 `ingest_state` 之类的空脚手架，mtime 跟着动）。所以 dry-run 那道门只做**配置面**检查（env 有没有配、`<repo>/src` 在不在），打印的是"配置面就绪，未连接上游确认"——**通不等于已连上**，"上游可达"留给 `--apply` 那道门去判。
- **只写上游，不回退本地**：`LLM_MEMORY_REPO` 无效或 `MEMORY_STORE_MODE=local` 时直接退 1 并把拒跑理由一条条打出来（"这一条都不会递出去"），不做静默降级——半批进上游、半批进旧库是最难收场的局面。这也解释了它为什么调 `upstream.upstream_ingest()` 而不是 `gateway.ingest()`：gateway 的选路按调用点现探，跑到一半上游掉线时会按契约给那一条写本地，跟"整批只进上游"的批处理契约正相反。
- **计数形状**：每条印 `+N 新增 / M 已存在`，末尾汇总"调用次数 → 新增 / 幂等命中 / 失败"；单条失败记一笔继续往下跑，有失败退 1。幂等交给上游 hash-dedup，**没有断点账本，也不需要**——Ctrl-C 落在源边界，再跑一次自动续上（中断退 130，全绿退 0，`--dry-run` 与 `--apply` 同时给退 2）。
- **成本要写实**：`--since/--until` 是**闭区间**日期过滤，`--limit N` 对每个源分别截断，`--only {summaries,sessions,briefs}` 单独走一路。这层节流不是装饰——本机 `BRIEFS_DIR` 按 69 天存量算就是几千次 agentic 抽取（一天几十张卡片就是一轮一轮的 LLM 调用），想少花钱就先 dry-run 看规模、再按日期分片推。日期形状写错（不是 `YYYY-MM-DD`）直接报错，而不是"当作没有这天"静默滤掉——后者等于悄悄少灌一批。

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

在项目根目录创建 `.env`（代码经 python-dotenv 读取；也可用 shell 环境变量）。
**`.env` 只在服务启动的 import 期读一次**——settings 是 import 期定型的快照，
改完必须重启服务才生效，不是热更新；服务运行中途改 .env 不会有任何可见效果。
`run_server.py` 启动时会按当前 provider 检查所需 key（进程 env → 项目 .env →
模型注册表 override 三处），全空则打 WARNING 说明"对话将失败"，只警告不拦启动。

```bash
# === Azure OpenAI ===
CHAT_API_KEY=your_azure_api_key
CHAT_AZURE_ENDPOINT=https://your-endpoint.openai.azure.com/
CHAT_DEPLOYMENT_NAME=your_deployment_name
CHAT_API_VERSION=2024-02-15-preview
CHAT_MODEL_NAME=gpt-6-luna
EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_API_VERSION=2024-02-15-preview
EMBEDDING_AZURE_ENDPOINT=https://your-endpoint.openai.azure.com/
EMBEDDING_DEPLOYMENT=your_embedding_deployment

# === 或 OpenAI ===
# OPENAI_API_KEY=***            # 默认模型 gpt-6-luna / text-embedding-ada-002
# OPENAI_MODEL_NAME=gpt-6-luna
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
| 智能聊天 | `/chat` | WebSocket 实时对话（走 Orchestrator），Markdown/LaTeX 渲染，勾选工具与文档，消息带 MemorySearch/DeepDive/WebSearch 标签 |
| 数据管理 | `/data` | 存储总览、按文档删除四类产物（JSON/向量库/图片/摘要）、批量删除、智能清理、会话统计、Memory tab |
| 配置中心 | `/config` | 切换 provider、每 provider 多模型的注册表（增删/设为当前/一键测试）、系统设置（落 `data/config/app_config.json`） |
| 结构编辑器 | `/structure` | 编辑文档章节 structure.json 并重建摘要/索引，PDF 在线预览 |
| 每日简报 | `/briefs` | 双栏简报工作台：左侧日期状态日历展示 AATF/深度分析/运行中/错误/缺档日期，中间卡片流支持筛选、多选、批量入 AATF、深度精析，右侧任务抽屉统一展示后台任务；卡片里的论文可一键下载入库（`POST /briefs/fetch-pdf` → `data/pdf` + 后台索引） |
| ~~简报记忆桥接~~ | `/memory` | 已退役——职责并入 `/briefs`；外部 LLM-Memory 的 HTTP 桥也已退役，接入改走进程内 SDK / MCP 只读门面，老书签自动 302 |
| API 文档 | `/docs` `/redoc` | FastAPI 自动生成 |
| 健康检查 | `/health` | status / timestamp / version |

## 常见任务

**索引第一个 PDF**：把 PDF 放入 `data/pdf/`，在 `/` 页点索引（或 CLI 选 `i`）。日志按节点推进：解析 → 结构 → 分块 → 章节处理 → 建索引 → 摘要 → 注册。

**在聊天里利用长期记忆**：正常对话即可——回答结束后 chat_ingest 车道会在会话静默后自动入库；之后的提问 Orchestrator 可自主调用 `search_memory` 检索历史。

**问今天/昨天有哪些新论文或新闻**：在 `/chat` 的记忆范围里勾选 `AATF` 后再问，这样 Orchestrator 会优先检索简报卡片记忆；默认记忆范围仍不自动包含 `AATF`，避免每个普通问题都搜到简报库。

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
| `OPENAI_API_KEY` `OPENAI_MODEL_NAME`（默认 gpt-6-luna） `OPENAI_BASE_URL` | OpenAI |
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
| `LLM_MEMORY_REPO` | 上游 LLM-Memory 的 checkout 路径——只读门面（SDK 进程内为主 / 可选 MCP stdio 决策面）的唯一寻址点；未设或路径无效时上游一律报 `available:false` + note，本地功能零影响 |
| `LLM_MEMORY_MCP_ENABLED` | `=1` 时启用可选的 MCP stdio 决策面（`python -m llm_memoryd.mcp --tools memory_why,memory_pack`，why/pack 工具需显式开）；默认关闭——两个变量都不设，默认行为完全不受影响 |
| `MEMORY_STORE_MODE` | 记忆存储的路由开关：`auto`（**默认**）＝ gateway 一处决策点自动选路，`LLM_MEMORY_REPO` 可用走上游、否则回落本地旧路；`local` ＝ 强制本地旧路（排障/对照用的 kill switch，上游可用也不写上游）；`upstream` ＝ 反向的硬档，上游不可达就抛 `RuntimeError` 而不回落，这才是把“旧 workflow”真正关掉的那个开关。两个方向都是 env 级、都在 gateway 那**一处**判定，不是逐调用点的政策。它与 `LLM_MEMORY_REPO` 都不设＝全部走旧路，dev/CI 零变化。只影响写/读路由，**不**影响 `LLM_MEMORY_MCP_ENABLED` 那条只读决策面 |
| `DEBUG` | WebSocket 调试输出开关（`true` 开启），默认关闭 |

> 历史注记：旧的外部 LLM-Memory webui HTTP 桥（`MEMORY_BRIEF_DRIVER=bridge` + `LLM_MEMORY_URL`，
> 默认 `http://127.0.0.1:8765`）**已彻底退役**——`load_brief_date` 的 driver 白名单收敛为 `local`
> 一条路，显式设成 `bridge` 只会打 warning 后按 `local` 跑，仓内不再有任何出网调用。
> 另：外部"加载某天简报"的桥路退役后**没有任何替身**，brief 入库只此 `local` 一条路——
> 该能力缺位是裁决而非 regression，日后别找回来。

**两个常见误解**
- **没有 `LOGGING_LEVEL` 环境变量**：代码不读取它。应用日志级别写死在 `src/core/llm/client.py` 的 `logging.basicConfig(level=logging.INFO)`（全仓共 5 处同样的 basicConfig，只有第一个生效的算数），调 DEBUG 改这些行；uvicorn 自身的访问日志级别则读 `data/config/app_config.json` 的 `log_level` 键（`src/ui/run_server.py:resolve_log_level`，/config 页写入的就是这个键，无效值按 info 处理）。
- **没有前端会话存储**：会话一律服务端落盘，localStorage 仅保存界面偏好（`base.html` 的 `AgenticReader_theme` 与 `AgenticReader_lang` 键）。

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
│   └── orchestrator/           #   Orchestrator + sub_agents/（memory_search、deep_dive、search_web）
├── src/config/                 # settings.py（LLM/Embedding/MCP 配置）、constants.py、
│   └── prompts/                #   model_overrides.py；prompts 仅 metadata_prompts.py
├── src/core/
│   ├── document_management/    # registry（注册表）/ indexer / delete_service（唯一删除实现）/ manager
│   ├── llm/                    # client（LLMBase + 日志 + embeddings 缓存）/ providers / history
│   ├── parallel/               # indexing.py（ChapterProcessor）/ retrieval.py（ParallelRetrievalCoordinator）
│   └── vector_db/              # vector_db_client（FAISS + 轮次去重 + 索引缓存）/ metadata_db
├── src/memory/                 # LanceDB 长期记忆（config / gateway / ingest / search / brief_ingest / migrate_aatf / upstream / vector_store / adapters）
│                               #   upstream=外部 LLM-Memory 访问层（SDK 进程内 + 可选 MCP 决策面；
│                               #     写路也在这层，"只读"纪律因收敛有意反转）
│                               #   brief_ingest=「轻量入库(全天)」的实现体（卡片 JSON 交给上游
│                               #     ingest，本地直写是其回落形态）；
│                               #   migrate_aatf 是一次性 A→B 库迁移 CLI，
│                               #   用前先 --dry-run 看清单再实跑
├── src/pipeline/               # 简报管线（briefs_parser / queue_store / process_pdf_queue /
│                               #   process_web_queue / generate_qa_brief / render_report / sync_* / paths）
├── src/services/scraper/       # Playwright 抓取包（core/browser·downloader·extractor·anti_detection、
│                               #   storage、mcp_server/server·tools）
├── src/ui/
│   ├── run_server.py           # 启动入口（HOST/PORT、回环安全默认）
│   ├── backend/                # app.py（lifespan 起 job_runner + chat_ingest 两车道）、config.py
│   │   ├── api/                # pages（页面路由；/memory 302 到 /briefs）、websocket（/ws/chat）、v1/（documents chat pdf
│   │   │                       #   structure config sessions data·data_storage·data_ops·data_common
│   │   │                       #   briefs jobs memory speech）
│   │   └── services/           # chat_service（走 Orchestrator）、session_manager、chat_ingest、
│   │                           #   job_runner、memory_browse、task_service、briefs_data
│   ├── templates/              # base dashboard chat config manage structure_editor briefs
│   └── static/                 # css/（chat manage dashboard briefs …）js/（api chat i18n locales
│                               #   chat-enhancer manage config dashboard briefs …）
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

**对话数据流**：`/ws/chat` → `chat_service` → **Orchestrator.ask()**（ReAct：可自主调用 `search_memory` → `src/memory/search.py` 的 `agentic_search`、`deep_dive_document` → AnswerAgent 深挖原文、`search_web` → SearchAgent 联网搜索，后者按会话开关启用；带轮次/上下文/超时三重护栏）。长会话历史由 `session_manager.history_for_llm_async` 窗口化：最近 20 条原文 + 更早部分增量摘要，摘要失败退化为纯截断。CLI 则由 `main.py` 直接驱动 AnswerAgent / SearchAgent。

**索引数据流**：上传/选择 PDF → IndexingAgent 图（check_cache → parse → extract_structure → chunk → process_chapters → build_index → generate_brief_summary → register），出错短路直达 register 且不会标成 completed。

**MCP 服务**（`settings.py` 的 `MCP_CONFIG`）：`duckduckgo`（`uvx duckduckgo-mcp-server`）、`web_scraper`（本仓库自带 Playwright 抓取 MCP），以及默认关的 `llm_memory` 条目（`python -m llm_memoryd.mcp --tools memory_why,memory_pack`，由 `src/memory/upstream.py` 按 `LLM_MEMORY_MCP_ENABLED` 门控调用）。SearchAgent 的 MCP 客户端是 `src/agents/search/utils.py` 的 `SimpleMCPClient`（stdio）；`upstream.py` 的决策面客户端按同一 stdio 形状就地实现，不 import `src.agents`。

## REST API 速查

前缀均为 `/api/v1`：

```
documents  GET  /list /available-pdfs      POST /upload /index       DELETE /{doc_name}
chat       POST /initialize /clear         GET  /load-more-messages
sessions   GET  /list /{id}  DELETE /{id}  PATCH /{id}/rename /{id}/memory-scope
pdf        GET  /view/{doc_name}           # PDF 页面图
structure  GET|PUT /{doc_name}             POST /{doc_name}/rebuild
config     GET  ""                         POST /provider /system /reset
               GET  /models                POST /models /models/test
data       GET  /overview /documents /documents/{name}/summary /documents/pending
               /sessions/stats /tasks/{task_id}
           POST /documents/{filename}/index /cleanup/smart
           DELETE /pdfs /documents/{name}/parts /documents
briefs     GET  /dates /cards /memory-status   POST /load /sync-memory /light-load
                # GET /cards 支持 date、include_state=1、compact=1，返回卡片及可选 AATF/深度分析/任务态
                # GET /memory-status 支持 include_meta=1 返回 storage_mode、上游行数、HTML 日期覆盖与队列统计
                # AATF 行读不出来时不会报成「0 行＝都没入库」：响应仍 200、仍带 dates，另加 degraded:true 与 read_errors；下一次读成功这两个键自动消失
               POST /fetch-pdf                 # 论文 PDF 拉进 data/pdf 并触发后台索引
jobs       GET  ""                         POST /{job_id}/retry /cancel
memory     GET  /overview /namespace/{ns}  POST /search
           DELETE /item/{id} /namespace/{ns}/source/{source_id} /namespace/{ns}
                 # 收敛注记：写/读/删已按 gateway 的 auto 路由选上游——三种 DELETE
                 # 走上游 delete/delete_where（unscoped 与跨 ns 的 id 都被拒），删的是
                 # 上游存储层，本地旧库行不受影响；browse_* 走同一条路由，读路可回落本地
           GET  /upstream                  POST /upstream/search
                # 上游 LLM-Memory 只读门面：status 字段 available + namespaces/rows + version，
                # 内嵌 decision:{enabled,available,note}；检索缺省作用域=全局（scoped=False），
                # 显式 namespace 才收窄
           POST /upstream/decision         # 上游决策面一跳：memory_why/memory_pack 白名单，
                # 由 LLM_MEMORY_MCP_ENABLED 门控，未启用即折叠 unavailable+note
speech     POST /transcribe /synthesize
```

注意：会话端点是 list / get / delete / rename 加一个 `PATCH /{id}/memory-scope`（设定这条会话检索哪些记忆 namespace，缺省 ai-research + webapp-chat，AATF 需显式勾选）——**没有** import/export（曾有 current/info，因无消费者已删）；`/api/v1/memory` 没有单条 item 的 GET 读取端点；页面侧 `/memory` 已退役，302 重定向到 `/briefs`。三个删除端点（`item/{id}`、`namespace/{ns}/source/{id}`、`namespace/{ns}`）把失败分成两类如实返回：scope 给错（空 namespace 或 `*`）是 400 并带上护栏原话，上游/存储真的挂了是 502 并把原因写进 body——不再是只有一句`Internal Server Error`，UI 至少能说清该不该再点一次。两个读端点（`overview`、`namespace/{ns}`）守的是同一条线：**库里没有行**是 200 加空形状（状态查询本该如实说「没有」），**读不出来**才是 502 并带着原因——不然一次存储故障会被界面翻成「这里本来就没记忆」。`DELETE /sessions/{id}` 会顺带按 source 回收这条会话写进 `webapp-chat` 的记忆行并清理 chat_ingest 水位线（尽力而为，失败只记日志）。

## 安全说明

- 默认仅监听 `127.0.0.1`，CORS 默认只放行本机来源——应用面向本地使用，未做鉴权；改 `HOST` 对外暴露前请自行加防护。
- 所有按文档名拼数据目录的 API 都过 `safe_path()`（`src/utils/path_guard.py`）防目录穿越。
- 删除操作收敛在 `delete_service.py` 单点实现，配合路径校验。
- `POST /briefs/fetch-pdf` 是服务端发起的抓取：scheme 限 http(s)，目标主机解析后过内网/云元数据/保留地址黑名单，重定向由后端逐跳跟且每跳重校验（没有主机白名单，arxiv 与公网照常可达）；与 SearchAgent 的抓取面同级。

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
