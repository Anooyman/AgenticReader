"""pipeline 两个批处理处理器（process_pdf_queue / process_web_queue）的公共骨架。

对应 REFACTOR_REPORT 的 P3（MPS-04："process_pdf_queue / process_web_queue
收尾段同构"）。两个文件处理的条目类型不同（pdf_arxiv / web_article），领域步骤
也完全不同（下载 + IndexingAgent 索引 + 六维度问答 vs 探测 + 爬取 + 五维度问答），
真正逐行重复的是外面那圈队列状态机推进的壳：

    select_processable → claim_item → 处理单条 → finish_item / fail_item → 计数汇总

以及几条固定口径的日志行。这里只抽这层壳，领域步骤留在各自文件里。

**不接管任何 queue 写盘**：pipeline_queue.json 的唯一写者仍然是 queue_store
（flock 短事务），本模块只是按顺序调用它的 claim_item / finish_item / fail_item。
**条目状态机语义的唯一定义处也在 queue_store**：`fail_item` → `mark_failed` 里
attempts 累加，累计到 MAX_ATTEMPTS(=3) 时 pipeline_status 转 failed_permanent，
否则转 failed_retryable；`select_processable` 只挑 pending / failed_retryable。
所以重试上限天然由 queue_store 保证，本模块不再另设一套计数、也不读 attempts。
"""
from collections.abc import Awaitable, Callable
from pathlib import Path

from src.agents.answer import AnswerAgent
from src.memory.ingest import ingest_source
from src.pipeline.queue_store import claim_item, fail_item, finish_item, select_processable

# 单条目的领域处理函数：async (item) -> None。
# 正常返回即视为成功，抛异常即记一次失败（记账由本模块负责）。
ItemHandler = Callable[[dict], Awaitable[None]]


# ---- 公共日志口径 ----
#
# 原来两个文件各自用 f-string 手拼同一批前缀（`  [id] ...`、`\n=== 处理 id: ... ===`、
# `汇总: 成功 x / 失败 y / 共处理 z 条`），这里统一成函数，措辞与旧输出逐字一致。
# pdf 侧原先用 doc_name 当括号里的标签，而 doc_name 就是 item["item_id"]
# （process_pdf_queue.process_item 开头那一行），所以统一用 item_id 输出一字不差。

def log_item(item_id: str, message: str) -> None:
    """条目内部某个步骤的进度行：`  [item_id] ...`。"""
    print(f"  [{item_id}] {message}")


def log_item_start(item_id: str, label: str) -> None:
    """开始处理某条的表头行。label 由调用方决定展示哪个字段（title / url）。"""
    print(f"\n=== 处理 {item_id}: {label} ===")


def log_item_missing(item_id: str) -> None:
    """claim 时条目已不在 queue 里（被别的车道删了）——跳过。"""
    print(f"\n=== 跳过 {item_id}：条目已不存在 ===")


def log_item_failed(item_id: str, error: BaseException | str) -> None:
    log_item(item_id, f"❌ 失败: {error}")


def log_item_done(item_id: str, summary_path: Path | str) -> None:
    log_item(item_id, f"✅ 完成，摘要已落盘: {summary_path}")


# ---- 单条处理骨架（取条目 → 处理 → 成功/失败记账） ----

async def process_one_item(item_id: str, handler: ItemHandler, label_key: str) -> str:
    """认领一条 → 交给 handler → 按结果记账。返回 "done" / "failed" / "skipped"。

    认领与回写刻意分成两个短事务（理由见 queue_store 的说明）：中间那次 handler
    动辄跑几十分钟，期间既不持锁也不持有整表，只带走单个条目的独立副本，处理完
    再 finish_item 把改动合并回磁盘上的最新版本，从而不会用旧快照覆盖别人的改动。

    finish_item 特意留在 try 里面：回写本身出错也应算这条失败（与重构前的两文件
    一致），而不是让整个批次炸掉。
    """
    item = claim_item(item_id)
    if item is None:
        log_item_missing(item_id)
        return "skipped"

    log_item_start(item_id, item.get(label_key, ""))
    try:
        await handler(item)
        finish_item(item_id, item)
    except Exception as e:
        log_item_failed(item_id, e)
        fail_item(item_id, e)
        return "failed"
    return "done"


async def process_queue_batch(
    item_type: str,
    handler: ItemHandler,
    label_key: str,
    *,
    limit: int = 0,
    item_id: str = None,
) -> tuple:
    """按类型跑一轮批处理：选取 → 逐条 process_one_item → 打印汇总。

    - `item_type`：queue 条目的 type（"pdf_arxiv" / "web_article"）。
    - `handler`：单条目的领域处理函数 `async (item) -> None`。它只管改自己那份
      item 副本（含把 pipeline_status 置成 done），不碰 queue 文件。
    - `label_key`：表头行展示条目的哪个字段（pdf 用 "title"，web 用 "url"）。
    - `limit` / `item_id`：原样透传给 select_processable。

    返回 `(done_count, failed_count)`，调用方可忽略。跳过的条目（已不在 queue 里）
    两个计数都不算——与重构前一致。

    注意 failed_retryable 也会被 select_processable 选进来重试：mark_failed 在
    attempts 达到 MAX_ATTEMPTS 时把状态转成 failed_permanent，而 failed_permanent
    不在选取范围内，所以重试上限天然由 queue_store 收口。
    """
    item_ids = select_processable(item_type, limit=limit, item_id=item_id)
    print(f"待处理 {item_type} 条目数: {len(item_ids)}")

    done_count, failed_count = 0, 0
    for iid in item_ids:
        outcome = await process_one_item(iid, handler, label_key)
        if outcome == "done":
            done_count += 1
        elif outcome == "failed":
            failed_count += 1

    print(f"\n汇总: 成功 {done_count} / 失败 {failed_count} / 共处理 {len(item_ids)} 条")
    return done_count, failed_count


# ---- 单条收尾的两个公共动作 ----
#
# 这两个函数刻意保持"薄"：摘要 JSON 的字段构成、落在 summaries/{pdf,web}/ 下的
# 哪个子目录、用什么文件名、以及"什么时候灌 memory"这些领域决定仍然留在两个
# 处理器里；这里只收掉两边逐字相同的记账与日志。

async def ingest_summary_to_memory(
    item: dict,
    summary_path: Path | str,
    *,
    provider: str,
    source_id: str,
    source_type: str,
    namespace: str,
) -> None:
    """摘要落盘之后把那份 JSON 灌进 src.memory，失败只记账不抛。

    刻意不阻断整条流程：摘要文件已经写出去了，简报页照常显示"已完成"，只是暂时
    搜不到。留空 memory_ingested（False）的条目下次跑批处理时会被
    sync_memory_ingest 的补灌逻辑捡起来重试。

    调用时机由领域文件保证：必须在 write_json_atomic 之后、置 pipeline_status=done
    之前（两个处理器原本就是这个顺序）。
    """
    log_item(item["item_id"], "写入 memory...")
    try:
        memory_report = await ingest_source(
            str(summary_path), source_type=source_type,
            namespace=namespace, provider=provider, source_id=source_id,
        )
        item["artifacts"]["memory_ingested"] = True
        item["artifacts"]["memory_chunks_added"] = memory_report.get("chunks_added", 0)
    except Exception as e:
        log_item(item["item_id"], f"⚠️  memory 写入失败（不影响本条完成）: {e}")
        item["artifacts"]["memory_ingested"] = False


async def answer_qa_loop(
    doc_name: str,
    questions: list,
    get_provider: Callable[[], str],
) -> dict:
    """按 `(key, question)` 清单对同一个已索引文档逐题跑 AnswerAgent 检索问答。

    pdf 的六维度与 web index_then_chat 的五维度共用这套循环；题目清单本身留在各自
    领域文件里（那是产品口径，不是技术重复）。

    provider 用 `get_provider()` **逐题现取**、而不是进循环前取一次：两个调用方的
    来源本就不同——pdf 拿的是 CLI / job_runner 传下来的固定值，web 每题现查
    `settings.resolve_provider(None)`（UI 中途改配置时下一题就换 provider）。
    保留"逐题调用"这一形式，两边行为才能与重构前一字不差。
    """
    qa = {}
    for key, question in questions:
        agent = AnswerAgent(doc_name=doc_name, provider=get_provider())
        result = await agent.query(
            user_query=question,
            enabled_tools=["retrieve_documents"],
            selected_docs=[doc_name],
        )
        qa[key] = result.get("final_answer", "")
        agent.reset_history()
    return qa
