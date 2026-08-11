"""对话自动入库——把 chat 会话记录持续同步进 src.memory。

改自 ai-research-pipeline 的 webapp/services/chat_ingest.py。原实现里
"ingest_session() 通过 subprocess 调用 LLM-Memory 的 ingest CLI" 的部分，
合并进 AgenticReader 后改为直接调用 src.memory.ingest.ingest_source()——
两者现在同进程运行，不再需要跨 venv 的 subprocess 调用。

Chat 页面合一之后，所有对话都落盘在 SessionManager 的 `data/sessions/`
（不再有独立的 research chat session 目录）——这里扫的就是那个目录。
`webapp_chat` adapter（src/memory/adapters/webapp_chat.py）读的字段
（title/doc_name/messages[].{role,content,timestamp}）与 SessionManager
的 session 文件格式兼容，只是消息里的 `sources_used` 字段在这里叫
`agents_used`；adapter 对缺失字段容错（默认空列表），不影响入库，只是
旧版进度不会在记忆摘要里带上"[sources: ...]"这行标注。

## 触发方式：周期扫描，不是每轮对话直接 ingest

worker 每 SWEEP_INTERVAL 秒扫一遍 session 目录，挑出满足
全部条件的会话逐个（串行）ingest：

  1. updated_at > last_ingested_at —— 有新内容
  2. now - updated_at >= QUIET_PERIOD —— 已经安静了一会儿
  3. 消息数 >= MIN_MESSAGES —— 至少有一轮完整问答

条件 2 是这里的去抖动机制：正在进行中的对话不会每个 tick 都被重新分块，
等你停下来才入库，一串连续问答因此合并成一次 ingest。用"扫描 + 静默期"
而不是"事件触发打脏标记"，是因为脏标记并不能缩短延迟（一样要等下个
tick），却多出一份内存状态；而扫描是纯粹从磁盘推导的，服务重启后自动
补齐，也能覆盖被外部改动的 session，正确性不依赖任何进程内状态。

last_ingested_at 落盘在 data/pipeline/chat_ingest_state.json —— 与其他
状态分开存，因为它不是"任务"，是同步水位线。

## 幂等性

同一个会话反复 ingest 是安全且廉价的：src.memory.ingest 按 chunk 内容
hash 去重，已入库的块直接跳过（不重复付出 LLM 抽取成本），只有还在增长的
尾块会被重算，并且它的上一版会被 stale_ids 清掉（见
src/memory/adapters/webapp_chat.py 的 update_plan），不会在库里留下一堆
互相包含的近重复行。
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config.settings import DATA_ROOT
from src.memory.config import NAMESPACE_WEBAPP_CHAT
from src.memory.ingest import ingest_source
from src.pipeline.paths import write_json_atomic

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path(DATA_ROOT) / "sessions"
STATE_PATH = Path(DATA_ROOT) / "pipeline" / "chat_ingest_state.json"

SWEEP_INTERVAL = 60      # 秒；扫描间隔
QUIET_PERIOD = 120       # 秒；会话最后更新后要安静这么久才入库（去抖动）
INGEST_TIMEOUT = 600     # 秒；单次 ingest 墙钟上限，超时视为失败
MIN_MESSAGES = 2         # 至少一问一答才值得入库


# ---- 同步水位线的读写 ----

def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"sessions": {}}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # 状态文件损坏不该让整个入库功能瘫掉——最坏情况是重新 ingest 一遍，
        # 而 ingest 本身是幂等的。
        logger.warning("chat_ingest 状态文件无法解析，按空状态重来: %s", STATE_PATH)
        return {"sessions": {}}
    data.setdefault("sessions", {})
    return data


def _save_state(state: dict) -> None:
    write_json_atomic(STATE_PATH, state)


def _parse_ts(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# ---- 选出该入库的会话 ----

def due_sessions(now: datetime = None) -> list:
    """返回 [(session_id, path, updated_at_iso), ...]，按更新时间升序。

    纯函数式地从磁盘推导，不依赖任何进程内状态——这正是重启后能自动补齐
    积压会话的原因。

    `now` 必须是 naive datetime（不带时区），与 session_manager.py 写入
    updated_at 时用的 datetime.now().isoformat()（本地时间、无时区）保持
    同一形式——之前这里用 datetime.now(timezone.utc) 与 naive 的
    updated_dt 相减，每轮 sweep 必抛 TypeError，被 run_forever() 的
    except 吞掉后台静默失败，导致对话从未真正入库过。
    """
    now = now or datetime.now()
    state = _load_state().get("sessions", {})
    if not SESSIONS_DIR.exists():
        return []

    due = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                session = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue  # 单个坏文件不影响其余会话

        session_id = session.get("session_id")
        if not session_id:
            continue
        if len(session.get("messages") or []) < MIN_MESSAGES:
            continue

        updated_at = session.get("updated_at") or ""
        updated_dt = _parse_ts(updated_at)
        if updated_dt is None:
            continue
        # 还在活跃对话中，等它安静下来再入库，避免每个 tick 重算尾块
        if now - updated_dt < timedelta(seconds=QUIET_PERIOD):
            continue

        last_ingested = state.get(session_id, {}).get("last_ingested_at") or ""
        if last_ingested and not (updated_at > last_ingested):
            continue

        due.append((session_id, path, updated_at))

    due.sort(key=lambda item: item[2])
    return due


# ---- 单个会话入库 ----

async def ingest_session(session_id: str, path: Path, updated_at: str) -> dict:
    """跑一次 src.memory.ingest，成功后推进水位线。"""
    state = _load_state()
    entry = state["sessions"].setdefault(session_id, {})
    entry["last_attempt_at"] = datetime.now(timezone.utc).astimezone().isoformat()

    try:
        report = await asyncio.wait_for(
            ingest_source(
                str(path), source_type="webapp_chat",
                namespace=NAMESPACE_WEBAPP_CHAT, provider="openai", source_id=session_id,
            ),
            timeout=INGEST_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001
        entry["last_error"] = str(e)
        _save_state(state)
        logger.warning("对话入库失败 %s: %s", session_id, e)
        return {"error": str(e)}

    # 水位线记 updated_at（这次入库覆盖到的内容位置），而不是"当前时间"——
    # 否则 ingest 期间新到的消息会被误判为已同步而永远漏掉。
    entry["last_ingested_at"] = updated_at
    entry["last_error"] = None
    _save_state(state)

    logger.info(
        "对话入库完成 %s: +%s 块 / 跳过 %s / 删除 %s",
        session_id, report.get("chunks_added"), report.get("chunks_skipped"),
        report.get("chunks_deleted"),
    )
    return report


async def sweep_once() -> int:
    """扫一轮，把到期的会话逐个入库。返回成功入库的数量。"""
    due = await asyncio.to_thread(due_sessions)
    if not due:
        return 0
    logger.info("对话入库：本轮 %d 个会话待同步", len(due))
    count = 0
    for session_id, path, updated_at in due:
        outcome = await ingest_session(session_id, path, updated_at)
        if "error" not in outcome:
            count += 1
    return count


async def run_forever() -> None:
    """常驻 worker。异常绝不能逃出这个循环——asyncio task 里未被 await 的
    异常会被静默吞掉，worker 就此死掉而外部毫无察觉。"""
    logger.info("对话自动入库 worker 已启动（每 %d 秒扫描一次）", SWEEP_INTERVAL)
    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL)
            await sweep_once()
        except asyncio.CancelledError:
            logger.info("对话自动入库 worker 停止")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("对话入库扫描出错，本轮跳过，worker 继续运行")
