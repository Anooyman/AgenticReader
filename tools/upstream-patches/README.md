# 上游 LLM-Memory 补丁集（Phase 2 · 删除面 / brief 通道 / source_id 透传）

本目录里的三个 `.patch` 是**给上游 `/Users/edward_ke/Documents/GitHub/LLM-Memory` 的小 PR**，
不是给 AgenticReader 的。AR 仓在打这些补丁时保持零改动——补丁只碰上游自己的文件，
每个补丁 = 代码 + 它自己的测试，测试全绿后从上游 `main` 的当前 HEAD 生成。

- 生成基线：`main` @ `901eab12e64460d26ff33aa9e116154908d6072c`
  （`docs: README.md is the Chinese main document, README_en.md the English twin`）
- 生成方式：在 `/tmp` 的一次干净 clone（只读地 `git clone` 上游，从不写上游工作树）里
  做三个**堆叠提交**，再逐段 `git diff` 出来。
- 依赖关系（实测，不是猜的）：**01 与 02 各自都能单独打到干净的 `main` 上**，
  **03 的测试文件那一块假设 01 已经在**（追加位置接着 01 写的 delete 测试），
  它的 `api.py` / `mcp.py` 改动本身是独立的。所以按 **01 → 02 → 03** 顺序打最省事；
  顺序打错时 `git apply` 会在**干净失败**里告诉你哪里不行，不会打坏东西——
  它不会把 03 的测试块半贴进 01 还没有的那片区域去。

| 补丁 | 上游改了哪 | AR 侧拿到什么 |
|---|---|---|
| `01-delete-facade.patch` | `api.py` 加 `MemoryClient.delete()` / `delete_where()` + `_checked_id` / `_checked_namespace` 两个边界守卫；`scripts/tests/api/test_memory_client.py` 加 delete 侧测试 | 上游终于有了删除面，`gateway.delete_*` 可以走 SDK，`DELETE /sessions/{id}` 的记忆回收段闭环 |
| `02-brief-source-type.patch` | `api.py` 的 `SOURCE_TYPES` 加 `"brief"`；`mcp.py` 的 `memory_ingest` schema enum 同步；`README.md` / `README_en.md` 各加一段；新增 `scripts/tests/test_source_types_are_one_contract.py` | `source_type="brief"` 进得来，`/briefs` 轻量入库可以从"本地直写"改成"卡片 JSON + 上游 ingest" |
| `03-source-id.patch` | `api.py` 的 `MemoryClient.ingest()` 透传 `source_id=`（`ingest_source_agentic` 一直有这个形参，缺的是门面那层）；`mcp.py` 只加一段"为什么这里不广告 source_id"的注释；`scripts/tests/api/test_memory_client.py` 加 ingest 侧测试 | 上游写入的 `source_id` 可控，AR 的寻址主键不用赌"多数情况相等" |

三个补丁都**没有**在 MCP 面上开任何删除工具：上游 `scripts/tests/test_mcp_server.py::test_tools_exclude_destructive_operations`
钉死了"广告的工具里不许出现 delete/rebuild/patch"，本补丁刻意绕开这条纪律——
删除面只走库面（SDK），这正是 AR 收敛计划里"传输以 SDK 为主"的口径。

---

## 我这边验到了什么、没验到什么

**验过的**（都在一个从上游 HEAD 新 clone 的目录里做，上游工作树一个字节没动）：

- `git apply --check` 三个都干净通过，再真打，`git status` 之后改动文件就是
  `api.py` / `mcp.py` / `README.md` / `README_en.md` / `test_memory_client.py` + 一个新测试文件。
  打完 01+02+03 的全量套件：**2114 passed / 4 skipped**（4 跳是上游本来就跳的那类）。
- **pyflakes 门**（`scripts/tests/common/test_pyflakes_clean.py`）：全绿。它不认 `# noqa`，
  我第一版一个用不上的 import 被它当场拦下——这条是真起作用的门，不是我顺手跑的装饰。
- **MCP 面没被碰坏**：`test_mcp_server.py`（含"不广告破坏性操作"那条）、`test_mcp_is_a_shell.py`
  （壳子里不许有第二份实现）都过。
- **枚举三处对齐**：新加的 `test_source_types_are_one_contract.py` 同时读枚举、MCP schema、
  adapter 注册表和文档，跑绿；顺带证实了一个事实——`SKILL.md` 和 `README_zh.md` 早就把
  `brief` 写进去了，缺的只有代码那两处，所以 02 是个"补齐"而不是"新增"。
- AR 侧接口形状：`verify_ar_faces.py`（就在本目录）拿打过补丁的上游源码起一个 `MemoryClient`，
  按 AR 未来要用的三种调用面实打实跑了一遍：

  ```bash
  # 在**打过补丁**的上游 checkout 上跑；不需要 key、不联网、只写 temp
  python3 /Users/edward_ke/Desktop/AgenticReader/tools/upstream-patches/verify_ar_faces.py \
      /path/to/LLM-Memory
  ```

  它查的是：
  `delete(id)` / `delete_where(namespace=, source_id=)` 的真实行删改（含跨 namespace 的断言拒删）、
  unscoped 删除一律按 `memory_browse` 期待的措辞被拒、`source_type="brief"` 在枚举与 MCP schema
  两边都在、`inspect.signature(MemoryClient.ingest)` 现在**看得到** `source_id`——
  AR 的 `upstream.py` 里那条探测分支会自己翻成 True，那条 warning 自己消失，不需要改 AR 代码。

**没验到的**，别当成验过了：

- **AR 自己的测试套件没跑**：本阶段不许动 AR 代码，接线动作是留给后续阶段的。
  `verify_ar_faces.py` 只证明"上游这侧的接口形状与护栏对得上 AR 将来要用的调用面"，
  不等于 `gateway.delete_*` 接上去以后 AR 的测试还是绿的。
- **真实 brief 入库没跑**：02 开的是入口闸门，跑通一张真卡片要真 LLM 与真嵌入端点
  （上游嵌入端点在局域网地址上，机器不在网段就全挂），那属阶段 3 的重灌验证。
- **上游 pre-push 那道检索回归门没跑**：`.git/hooks/pre-push` 是
  `llm_memoryd.eval.prepush_gate`，要真实 LLM + 真实 store，不属于"补丁对不对"的范围。
  真要推代码时它会自己触发，跳过口径是 `MEMORY_PREPUSH_SKIP=1`。
- **并发与锁**只做到"门面确实在 `store_lock()` 里进出"这一层（用 spy 测过调用次序），
  没有做多进程真抢锁的压力测试。

---

## 怎么应用

打补丁前先确认基线，别在脏工作树上打：

```bash
cd /Users/edward_ke/Documents/GitHub/LLM-Memory
git status --short          # 必须是干净的；不干净就先 stash/commit
git log --oneline -1        # 期望 901eab1（或它之后的祖先）
git fetch --all --tags

# 三个补丁依次应用（--check 先看，--check 干净再真打）
for p in 01-delete-facade 02-brief-source-type 03-source-id; do
  git apply --check /Users/edward_ke/Desktop/AgenticReader/tools/upstream-patches/$p.patch || break
  git apply         /Users/edward_ke/Desktop/AgenticReader/tools/upstream-patches/$p.patch
done
git diff --stat            # 应为 api.py / mcp.py / 两个 README / 两个测试文件
```

想先看改动不想落盘：`git apply --stat <patch>` 看清单，
`git apply --check <patch>` 只做"能不能打上"的检验，
`git apply --3way <patch>` 给冲突处留下冲突标记（上游若已漂开就用这个）。

> 打之前**建议开一个分支**（`git switch -c ar-phase2`），这样回退就是 `git switch main`，
> 不用记 patch 顺序。

## 上游测试怎么跑

上游的测试全在 `scripts/tests/`，`pyproject.toml` 里 `testpaths=["scripts/tests"]`、
`pythonpath=["src"]`，所以**从仓根直接跑就行**，不必装成包：

```bash
cd /Users/edward_ke/Documents/GitHub/LLM-Memory
.venv/bin/python -m pytest -q            # 全量，本机实测约 2 分 15 秒
.venv/bin/python -m pytest -q scripts/tests/api scripts/tests/test_source_types_are_one_contract.py
```

两个环境坑（和本补丁无关，但会误报成"改坏了"）：

1. **`config.json` 不入库**：`scripts/tests/common/test_config_keys_are_consumed.py` 与
   `test_config_drift.py` 里共 4 条要读 `<repo>/config.json`，`git clone` 出来的新目录里没有，
   会报 `FileNotFoundError`。`cp config.json.example config.json` 就绿（我在验证时就是这么做的）。
2. **`policies/` 目录也不入库**：`test_config_drift.py::test_the_checkout_default_is_never_used`
   拿"仓内那份 ledger"当事实来源，新 clone 里没有 `policies/` 会失败，`mkdir -p policies` 即可。

上游自带的两道门，本补丁都过过：

- **pyflakes 门**：`scripts/tests/common/test_pyflakes_clean.py` 对 `scripts/` 与
  `src/llm_memoryd/` 全树做 pyflakes 检查，**它不认 `# noqa`**（我第一版加了个用不上的 import，
  就是被它当场抓出来的）。补丁最终状态：全绿。
- **pre-push 门**：`.git/hooks/pre-push` 是 dsh-coding-memory 装的
  `llm_memoryd.eval.prepush_gate`（检索回归，需要真实 LLM 与 store；跑不起来时它自己 fail-open，
  只有"命中率掉了"才真的拦）。这条我**没有跑**——它要联网调模型，不属于"补丁对不对"的检验范围。
  真要过它就是 `git push` 时自动触发，跳过是 `MEMORY_PREPUSH_SKIP=1`。

补丁状态下的实测结果（干净 clone + 上面那两个目录补好之后；三个数都是**全量**跑，
含各自新增的测试）：

| 状态 | 全量结果 |
|---|---|
| 基线 `901eab1`（未打任何补丁，同一环境） | `2096 passed / 4 skipped` |
| 只打 01 | `2105 passed / 4 skipped` |
| 打完 01+02 | `2110 passed / 4 skipped` |
| 打完 01+02+03 | `2114 passed / 4 skipped` |

四行的差都对得上补丁自己新增的测试（01 加 9 条、02 加 5 条、03 加 4 条），
**没有一条基线测试被改红或改少**。`4 skipped` 是上游本来就跳的（缺 LLM 凭据那一类）。

## 失效风险：上游 main 动过怎么办

这三个补丁都**没有**碰并发、配置、schema 迁移这类容易互相踩的模块，风险集中在四处具体位置：

| 位置 | 上游如果动了它 | 打不上的表现 | 谁替你兜住 |
|---|---|---|---|
| `api.py:47` `SOURCE_TYPES` | 上游自己加了第七个类型 | 02 的 hunk 冲突 | 新增的 `test_source_types_are_one_contract.py` 会同时读枚举/MCP schema/adapter 注册表/文档四处，哪一处先漂移它就红在哪 |
| `api.py` 的 `ingest()` | 上游加了新形参，或把 `ingest_source_agentic` 改名 | 03 的 hunk 冲突或 import 期报错 | `test_ingest_forwards_an_explicit_source_id` 之类的三条：形参没接上就红 |
| `api.py` 类尾 | 上游自己写了一个 `delete()` | 01 冲突（最可能的一处，因为这是同一个能力的正面竞争） | 若上游已有自己的删除面，**这个补丁就该撤**，别硬合——看它有没有 `store_lock` 与 unscoped 护栏，没有就把护栏补到它身上 |
| `common/vector.py` 的 `delete` / `delete_where` | 签名变了，或 `ID_RE` / `_where()` 的护栏改了 | 门面接的是个空层：错误照旧，护栏没了 | `test_delete_where_refuses_every_unscoped_shape` 与 `test_delete_rejects_an_id_the_store_could_not_filter_on` |

重打一遍的实操做法：

```bash
# 0) 先看基线差多远
git log --oneline 901eab1..HEAD -- src/llm_memoryd/api.py src/llm_memoryd/mcp.py

# 1) 冲突时用 3way 留标记，别硬猜
git apply --3way 01-delete-facade.patch

# 2) 语义漂移（能打上但行为变了）只能靠跑：
.venv/bin/python -m pytest -q scripts/tests/api scripts/tests/test_source_types_are_one_contract.py \
                            scripts/tests/test_mcp_server.py scripts/tests/common/test_vector.py
```

补丁里所有"上游纪律"的部分都是照抄现成规矩，所以最容易失效的其实是**护栏而不是代码**：
`VectorStore.delete_where` 拒 unscoped（`common/vector.py:1028` 起）、`_where()` 对 namespace
与 source_id 都过 `_validate_id`（`ID_RE`，`common/vector.py:198`）、写路径一律 `store_lock()`
（`common/store_lock.py`，ingest 的提交段与 `knowledge/write.py` 都拿它）。
这三条哪条在上游被改弱，`01` 的门面就跟着变松——补丁里我把这层关系写在了方法 docstring 里，
将来对着 docstring 逐条核比翻 diff 快。

## 怎么回退

推荐顺序（从最省事到最彻底）：

```bash
# A. 打完但先不 push：直接回到分支起点
git switch main                       # 前提：你是在 ar-phase2 分支上打的
# B. 已经落在工作树里：反向打
git apply -R 03-source-id 02-brief-source-type 01-delete-facade.patch
# 注意 -R 也要按**逆序**来（03→02→01），且必须打的就是当时那三份；上游若又前进了就退回 C
# C. 最稳：扔掉工作树改动
git checkout -- src/llm_memoryd/api.py src/llm_memoryd/mcp.py README.md README_en.md \
               scripts/tests/api/test_memory_client.py
git clean -n scripts/tests/test_source_types_are_one_contract.py   # 新文件，确认后 -f 删掉
```

回退**不需要 AR 配合**：这三个补丁全在上游侧，AR 没接上之前行为一个字都不变
（AR 的 gateway 走的是 auto 路由 + 本地回落，上游有没有这些方法它都不关心）。
AR 侧接线之后要回退，改的是 AR 自己的开关：`MEMORY_STORE_MODE=local` 强制回旧路，
或 unset `LLM_MEMORY_REPO` 让上游入口整体降级为 `available:false`。

## 应用之后：AR 侧要接线的三处

补丁进上游之后 AR 才有这些东西可用；**现在（补丁未落地时）AR 一律保持 local 现状 + 明确 note，
不造假**，这是 PLAN 阶段 2 的验收第 4 条。下面三处按"接谁"排：

1. **`src/memory/gateway.py` 的 `delete_item` / `delete_source` / `delete_namespace` 切上游**
   （依赖补丁 **01**）。形状近乎直接搬：`delete_item(id)` → `client.delete(id)`，
   `delete_source(ns, source_id)` → `client.delete_where(namespace=ns, source_id=sid)`，
   `delete_namespace(ns)` → `client.delete_where(namespace=ns)`——正好对上门面"namespace 必须显式"
   那条比存储层更严的规矩，service 层三种 DELETE 的签名不用动，
   `DELETE /sessions/{id}` 的记忆回收段随之闭环。
   两处要注意：① 别学现在的"取行 + 逐删"，上游是**一次提交**删完一片，返回值就是条数，
   `_delete_rows` 那套 skip-and-count 在上游路上纯属多余；② **失败语义是 AR 自己要拍的板**，
   不是补丁给的——AR 现在写路"不回落"（`gateway.ingest` 上游炸了就 `raise RuntimeError`，
   绝不顺手写一份本地），而会话回收那一段又是尽力而为、失败只 log。删除落在两者中间，
   建议按各自的调用点分开走（回收段跟着现状走 log-and-continue，
   `/data` 页显式删除跟着写路纪律走 raise），别一处开关把两种语义都改了——
   选哪种都不影响本补丁，只是别在接线时顺手发明第三种。

2. **`/briefs` 的"轻量入库"从 local 直写切成"卡片 JSON 文件 + 上游 ingest"**
   （依赖补丁 **02**，`source_type="brief"` 现在进得来）。代价两条，PLAN 里已经声明过：
   ① 不再是零 LLM（上游 ingest 是 agentic 管线），② `AATF` 的 id 空间换轨成
   `aatf-<date>-<kind>` 之后，"这一天是否已入库"的比对和 `/briefs` 的 `memory-status` 日期聚合
   都要换口径——**先做双读兼容再切**，别直接改判定。
   如果补丁 **03** 也落地了，AR 完全可以**不换 id 空间**：把卡片现有的 `item_id` 当 `source_id`
   递下去，上游就按你要的 key 落行，"是否已入库"继续按老 key 比（这条能省掉整段 id 换轨工程，
   是 03 顺带给的好处，别浪费）。
   另外 `upstream.py` 已经有一条 `inspect.signature` 探测：上游接不接受 `source_id` 它自己会试，
   补丁落地后那条 warning 会自己消失，不用改 AR 代码。

3. **`src/memory/upstream.py` 的写路把 `source_id` 从"尽力递"升级成"契约"**
   （依赖补丁 **03**）。现状是：AR 递 `source_id`，上游签名里没有这一位，
   于是 `upstream_ingest` 打 warning 说"本次写入的 source_id 由上游 adapter 自己派生"——
   这等于承认 AR 的寻址主键靠"多数情况相等"兜着。补丁落地后这一位真的透传了，
   gateway / `memory_browse` / `DELETE /sessions/{id}` 回收段对 source_id 的依赖
   就从"校验"降级为"断言"：可以按"删了 0 行 = 这个 key 不存在"下结论，
   不用再留"可能是它派生的 id 和我们的不一样"这类免责话。
   接线动作只有两件：把 `upstream.py` 里那条 warning 与探测分支的注释改成"契约成立"的口径，
   以及给 `_map_upstream_ingest_report` 的 `requested_source_id` 加一条
   "上游 echo 回来的 id ≠ 我们递下去的 id" 的 warning——上游现在会
   在返回里带 `source_id` 字段（就是它实际用的那个 key），拿它当权威来对照。

## 三个补丁里刻意没做的事

- **MCP 面没有加删除工具**，`memory_ingest` 的 schema 里也没有 `source_id`：
  前者的纪律来自上游那条 destructive-op 测试，后者记在 `mcp.py::_call_memory_ingest` 的
  docstring 里——工具调用方是模型，它没有依据替一条未来的 delete 选 storage key，
  人类操作面（CLI 的 `--source-id`，上游本来就有）才该有这一位。
- **webui 的下拉没动**：`src/llm_memoryd/webui/index.html` 的 ingest 类型框本来就只列
  `conversation`/`openclaw`/`repo` 三种需要路径提示的类型，它是策展列表不是枚举镜像，
  新加的对齐测试刻意不去读它（读了要么逼 UI 去列它没有占位符的类型，要么逼枚举缩小）。
- **没有做迁移**：`brief` 通了之后存量 AATF 行仍是本地直写的形状，重灌属 PLAN 阶段 3。
