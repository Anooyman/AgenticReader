# Memory 收敛到 LLM-Memory 实施计划

> 裁决记录（Lead 按团队调研定的缺省，均可复核，改判需用户点名）：
> - **namespace 模型**：保留 AATF / ai-research / webapp-chat 三个**显式**名字
>   （SDK 构造期/调用期传参，`test_memory_client.py:178` 钉着"显式优先于 cwd 派生"；
>   ID_RE `^[\w][\w.\-@/]{0,127}$` 三者合法）。不用"单 slug-<digest>+source_type 分档"
>   方案——那会重做 sessions.py 校验、/data 分组与 memory-scope 浮层，收益只有
>   "why/pack 可见"，代价太大。decision 面（why/pack/remember）继续走路径派生 ns，
>   与 memory 三名字分家是已知且接受的格局。
> - **传输**：SDK 为主（写/浏览面比 MCP 宽，且 `src/memory/upstream.py` 门面已就位）；
>   MCP 维持现状当决策面，不扩。
> - **存量处置**：不迁移——"删了重灌"路线：ai-research/webapp-chat 本就能从
>   `data/pipeline/summaries/` 与 `data/sessions/` 经上游 ingest 重建，AATF 从 BRIEFS_DIR。
>   旧库 `data/memory_db` 收敛生效后转只读兜底。
> - **§0 三禁令**：#1 作废（re-ingest + 旧库退役，不是整库塞进去）；#2 改写为
>   "一切经 SDK 面，AR 进程不读不写 ~/.llm-memory"；#3 豁免（写路径接上游 ingest
>   正是收敛本身），豁免的对价 = 上游幂等/去重新契约要有测试钉住。

## 分工原则

- 两条写通道天然文件驱动：chat_ingest 递 `data/sessions/{id}.json` 路径、
  pipeline 递摘要 JSON 路径——上游 `MemoryClient.ingest(path, source_type, namespace)`
  的形状与 AR 现在 `ingest_source(path, ...)` 同构，source_type 字面量本来就在
  上游枚举里（`api.py:47`）。**收敛的主战场是 gateway 的路由，不是调用方。**
- `upstream.py` 的"全段只读"纪律**有意反转**：写入也走它，统一 to_thread +
  折叠纪律，gateway 签名不动。
- 所有上游路径带 **auto 路由**：`LLM_MEMORY_REPO` 有效 → 走上游；未设/不可达 →
  回落本地旧路并 warning（dev/CI 零变化，缺省行为可逆）。

## 阶段 1 · AR 侧路由收敛（本轮实施）

1. `src/memory/upstream.py`
   - 加写路：`upstream_ingest(path, source_type, namespace, source_id)`
     → `to_thread(client.ingest, ...)`；幂等口径交给上游（AR 侧不再算 chunk-hash，
     上游 ingest 自带 hash-dedup，重复递同一文件应返回 0 新增——这条要实测钉死）。
   - 读路补多 ns：search 显式 namespaces= 直传（上游支持，`api.py` search 签名）。
   - 写失败折叠形状与读路同构，不 raise 不上浮到 UI。
2. `src/memory/gateway.py`
   - `search()` / `ingest()` 加路由：上游可用→转 upstream，否则本地旧路。
   - search 返回形状：上游 33 列行 → gateway 映射层摊平成 memory_search 子 agent
     现在吃的 14 列形状（`occurred_at/source_id/abstract/detail/keywords/
     raw_source/memory_type/source_type` 全留，`chunk_hash==""` 的 summary 行
     在上游 schema 无此列，映射层按"keywords 空 + detail 长"启发式模拟，
     并在 /briefs 日期聚合处保持 `occurred_at[:10]` 可用——上游有这列）。
   - `browse_*` / `delete_*` 暂留本地（阶段 2 接上游 delete facade）。
3. 三个写调用点（chat_ingest / pipeline×2 / sync_memory_ingest）**签名零改动**，
   只被 gateway 路由牵着走。
4. `GET /api/v1/memory/upstream` 与 decision 面不动（本轮只扩写路，门面形状不破坏）。

## 阶段 2 · 上游 PR 落地后的收尾（补丁就绪即做）

- **P1 删除面**：`api.py` 包一层 `delete(memory_id)` / `delete_where(namespace,
  source_id|namespace)` + 测试；然后 gateway 的 delete_* 走上游，
  DELETE /sessions/{id} 的回收段随之闭环。
- **P2 brief 通道**：`SOURCE_TYPES` + `mcp.py` ingest enum 加 `"brief"`
  （BriefAdapter 已注册，逻辑全在上游）；然后 /briefs 轻量入库从 local 直写
  改为"卡片 JSON 文件 + 上游 ingest"。注意 id 空间换轨：上游约定
  `aatf-<date>-<kind>`，AR 现为每卡一行——"是否已入库"的比对与 memory-status
  日期聚合要换口径，先做双读兼容再切换。
  代价声明：轻量入库不再是零 LLM（上游 ingest 是 agentic 管线）。
- 上游补丁**已经全部落在 LLM-Memory 的 main 里**，AR 侧不再留一份 `.patch` 副本
  （原先那个 `tools/upstream-patches/` 目录连同 `verify_ar_faces.py` 手动探针已删除：
  它做的事后来由上游自己的测试面接管，见 LLM-Memory `scripts/tests/api/`——
  "跑的时候才想起来"的探针不是联动，落在哪一侧有 CI 才算）。

## 阶段 3 · 存量重灌（补丁落地后，跑 destructive 操作前须用户点一次头）

- `python -m src.memory.converge --dry-run | --apply`：
  ① `data/pipeline/summaries/{pdf,web}/*.json` → ai_research 入
  ② `data/sessions/*.json` → webapp_chat 入（跳过水位线未过的可 --force 全量）
  ③ BRIEFS_DIR → brief 入（依赖 P2）
- 完成后 `data/memory_db` 移入 `data/memory_db.legacy` 只读保留一个发布周期，
  回退 = 把路径改回来，无数据损失（重建不依赖删除）。

## 已知代价（写进文档，不算 bug）

- 记忆的 LLM/嵌入配置归上游 config 管，AR /config 页管不到记忆侧
  （上游嵌入端点当前是局域网地址，机器不在该网段则上游路全挂，靠 auto 回落兜住）。
- AR 递"已摘要文件"，上游 ingest 会再抽一遍——同一份内容过两轮 LLM，
  token/时延涨，qa/qa_brief 字段可显式传给上游当现成摘要以省掉二次抽取
  （ingest 有该通道则用它，调研显示 upstream 的 ai_research adapter 直接吃
  qa 字段，属利好）。
- 上游全同步，写路也全程 to_thread，写超时没有 cancel 通道，只有等待侧硬 cap。

## 验收

1. 未设 `LLM_MEMORY_REPO`：全量测试与行为逐字节同今天。
2. 设了 repo：chat_ingest/pipeline 新行落上游库（namespaces() 里 ai-research /
   webapp-chat 行数在涨），search_memory 命中上游行，旧库只读兜底可关。
3. 重复 ingest 同一会话文件不产生重复行（上游幂等实测）。
4. 阶段 2 的删除/brief 在上游补丁 apply 前保持 local 现状 + 明确 note，不造假。
