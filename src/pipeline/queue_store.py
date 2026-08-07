"""pipeline_queue.json 这本状态账本的读写与状态机——批处理与 webapp 共用。

改自 ai-research-pipeline 的 pipeline/queue_store.py，逻辑原样保留（并发
模型已经用真实负载验证过），只是路径来源换成本项目的 src.pipeline.paths。

并发模型见 queue_transaction 的说明——这是全项目唯一允许写 queue 的路径。
"""
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path

from src.pipeline.paths import STATE_DIR, write_json_atomic

QUEUE_PATH = STATE_DIR / "pipeline_queue.json"
QUEUE_LOCK_PATH = STATE_DIR / "pipeline_queue.lock"

MAX_ATTEMPTS = 3


def load_queue() -> dict:
    if not QUEUE_PATH.exists():
        return {}
    with open(QUEUE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_queue(queue: dict) -> None:
    write_json_atomic(QUEUE_PATH, queue)


@contextmanager
def queue_transaction():
    """排他锁横跨"读 queue → 修改 → 写回"整个过程。

        with queue_transaction() as queue:
            queue[item_id]["pipeline_status"] = "in_progress"
        # 退出 with 时自动落盘并释放锁

    **为什么必须横跨、而不是只给 load/save 各加一把锁**：queue 是整文件
    读写，每个进程手里都是一份完整副本。如果只在单次 load 和单次 save
    期间持锁，两个进程仍然可以各自读到同一份快照、各改各的、后写的那个
    把先写的改动整体回滚掉（lost update）——锁必须一直握到写回完成，中间
    不能给别人插进来读的机会。

    锁文件与 queue 同目录、单独一个 .lock（不直接锁 queue 文件本身：
    write_json_atomic 是 tmp+rename，rename 之后原来的 inode 就换了，
    锁在旧 inode 上会失效）。

    flock 是阻塞的，且是进程级建议锁——同一进程内嵌套调用会自己锁死自己，
    所以不要在 with 块里再调一次。异步调用方需要放进 asyncio.to_thread，
    别在事件循环里直接阻塞。
    """
    QUEUE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(QUEUE_LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        queue = load_queue()
        yield queue
        save_queue(queue)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ---- 条目与状态机 ----

def new_queue_item(item_id: str, item_type: str, url: str, title: str,
                   coverage_date: str, pdf_url: str = None) -> dict:
    return {
        "item_id": item_id,
        "type": item_type,
        "url": url,
        "pdf_url": pdf_url,
        "title": title,
        "coverage_date": coverage_date,
        "pipeline_status": "pending",
        "pipeline_stage": None,
        "attempts": 0,
        "last_error": None,
        "artifacts": {},
    }


def mark_failed(item: dict, error: str) -> None:
    item["attempts"] = item.get("attempts", 0) + 1
    item["last_error"] = str(error)
    if item["attempts"] >= MAX_ATTEMPTS:
        item["pipeline_status"] = "failed_permanent"
    else:
        item["pipeline_status"] = "failed_retryable"


def reset_stale_in_progress(queue: dict, item_type: str = None) -> int:
    """启动时把上次异常中断遗留的 in_progress 重置为 pending。返回重置数量。

    `item_type`：只重置指定 type 的条目。pdf/web 两个处理器共享同一个
    queue 文件，各自启动时只应重置自己负责的类型——否则 A 处理器启动时
    会把 B 处理器正在处理中的条目误判为"遗留"重置掉。传 None 保持旧行为
    （全部重置），仅供确认没有并发运行时的手动修复场景使用。"""
    count = 0
    for item in queue.values():
        if item.get("pipeline_status") != "in_progress":
            continue
        if item_type is not None and item.get("type") != item_type:
            continue
        item["pipeline_status"] = "pending"
        count += 1
    return count


# ---- 处理循环的短事务辅助 ----
#
# 处理一个条目要十几到几十分钟，期间绝不能把整个 queue 攥在内存里：那正是
# lost update 的成因。所以拆成三个短事务：选取、认领、回写，中间那段长时间
# 处理不持锁、也不持有整表，只带走单个条目的副本。

def select_processable(item_type: str, limit: int = 0, item_id: str = None) -> list:
    """短事务：重置本类型遗留的 in_progress，返回待处理的 item_id 列表。"""
    with queue_transaction() as queue:
        reset_count = reset_stale_in_progress(queue, item_type=item_type)
        if item_id is not None:
            item = queue.get(item_id)
            ids = [item_id] if item and item.get("type") == item_type else []
        else:
            ids = [
                key for key, value in queue.items()
                if value.get("type") == item_type
                and value.get("pipeline_status") in ("pending", "failed_retryable")
            ]
            if limit:
                ids = ids[:limit]
    if reset_count:
        print(f"重置了 {reset_count} 个遗留 in_progress 条目为 pending")
    return ids


def claim_item(item_id: str) -> dict:
    """短事务：把条目标记为 in_progress，返回它的独立副本供处理使用。"""
    with queue_transaction() as queue:
        item = queue.get(item_id)
        if item is None:
            return None
        item["pipeline_status"] = "in_progress"
        return json.loads(json.dumps(item))


def finish_item(item_id: str, processed: dict) -> None:
    """短事务：把处理后的字段写回磁盘上的最新版本。"""
    with queue_transaction() as queue:
        live = queue.get(item_id)
        if live is None:
            return
        live.update(processed)


def fail_item(item_id: str, error) -> None:
    """短事务：在磁盘最新版本上记一次失败。"""
    with queue_transaction() as queue:
        live = queue.get(item_id)
        if live is None:
            return
        mark_failed(live, error)
