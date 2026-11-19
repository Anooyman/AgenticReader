"""本地简报轻量入库——gateway._local_brief_load 的实现体。

把 BRIEFS_DIR 某一天 HTML 里的卡片直接写进 A 自库 data/memory_db/ 的
namespace AATF（DA 裁决：本地 brief 加载落 A 自库，与对话同库，只是
namespace 隔离）。设计上刻意走"轻量"路线，与 /briefs 页的重管线
（download → IndexingAgent → 多维 QA → ingest_source）互为两档：

* **零 LLM 调用**：简报卡片本身就是人工写好的中文导读，不再做
  ingest_source 的逐 chunk condense 与 source-summary 生成；直接 embed
  导读正文。一天的量只有几十次 embedding 请求，串行都嫌快。
* **幂等**：按 (namespace, source_id=card item_id) 取已有行，chunk 内容
  hash 相同的跳过——重复点"加载"不会写重复行，与 ingest_source 的去重
  语义一致（那边靠 adapter.update_plan 比 chunk_hash，这边直接比）。
* **失败隔离**：单卡失败记进 errors 继续跑下一张，返回契约
  {"loaded","skipped","errors"}，job_runner 的 load_brief_date 消费端
  不用分支。

record 字段与 ingest.ingest_source 逐一对齐（memory_type/abstract/detail/
raw_source/keywords/importance/chunk_hash/occurred_at...），检索工具
（agentic_search 的 semantic/keyword/keywords-pool/list-by-source）与
/data Memory tab 浏览都无需感知写入方是谁。

不 import src.ui——本模块住记忆内核侧；解析复用 pipeline.briefs_parser
（与批处理同一 item_id 推导，两边算出的 ID 恒一致）。
"""
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.config.settings import resolve_provider
from src.memory.config import (
    MEMORY_DB_DIR,
    NAMESPACE_AATF,
    get_embedding_dimensions,
)
from src.memory.vector_store import VectorStore, dump_json_list

logger = logging.getLogger(__name__)

_SOURCE_TYPE = "brief"
# 轻量入库没有 importance 打分，给一个中性偏上的固定值：导读卡片的检索
# 价值等同于"值得看的摘要"，0.7 与 ingest 里 source-summary 的下限一致。
_IMPORTANCE = 0.7


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _occurred_at(coverage_date: str) -> str:
    """卡片归属日期（当天零点 UTC）。解析失败退回当前时间。"""
    try:
        return datetime.strptime(coverage_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return _now()


def _chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _card_text(card: Dict[str, Any]) -> str:
    """把一张卡片拼成"可检索全文"：标题 + 链接 + 中文导读各行 + 主题。

    排序有讲究：标题与链接在前（semantic 命中时可先看到出处），导读按
    label 出现顺序逐行——这就是整条记录的事实来源，没有别的内容可喂。
    """
    lines: List[str] = [f"标题：{card.get('title') or card.get('item_id', '')}"]
    if card.get("url"):
        lines.append(f"链接：{card['url']}")
    if card.get("pdf_url") and card["pdf_url"] != card.get("url"):
        lines.append(f"PDF：{card['pdf_url']}")
    cn = card.get("cn") or {}
    for label, body in cn.items():
        if body and str(body).strip():
            lines.append(f"{label}：{str(body).strip()}")
    themes = card.get("themes") or []
    if themes:
        lines.append("主题：" + "、".join(str(t).strip() for t in themes if str(t).strip()))
    return "\n".join(lines)


def _card_keywords(card: Dict[str, Any]) -> List[str]:
    """keywords 只取现成的 themes——没有 LLM 就没有词法分析，宁缺毋滥。"""
    return [str(t).strip() for t in (card.get("themes") or []) if str(t).strip()]


def _build_record(card: Dict[str, Any], text: str, *, namespace: str) -> Dict[str, Any]:
    """record 形状逐字段对照 ingest.ingest_source 写入的那一条。

    abstract 是 embedding 的载体，也进检索结果列表；没有 condense 阶段
    时就用"标题 + 首条导读"充当摘要，detail 放全文，保证列表可读、
    详情完整。
    """
    abstract = text[:300]
    return {
        "id": str(uuid.uuid4()),
        "vector": None,  # 调用方 embed 后回填
        "namespace": namespace,
        "memory_type": "episodic",
        "abstract": abstract,
        "detail": text,
        "raw_source": text,
        "keywords": dump_json_list(_card_keywords(card)),
        "importance": _IMPORTANCE,
        "created_at": _now(),
        "source_type": _SOURCE_TYPE,
        "source_id": str(card["item_id"]),
        "chunk_hash": _chunk_hash(text),
        "occurred_at": _occurred_at(card.get("coverage_date") or ""),
    }


async def load_brief_date_local(
    date: str,
    provider: Optional[str] = None,
    *,
    briefs_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """把一天的简报卡片轻量写入 A 自库 AATF。

    返回 {"loaded": bool, "skipped": bool, "errors": [str, ...]}，这是
    load_brief_date 的固定契约（原 bridge 驱动已退役，形状沿用不变），
    job_runner / 前端不区分驱动来源。解析不到任何卡片按 skipped 处理
    ——日期目录空/HTML 缺失不算失败，别把"这天本来就没简报"报成错误。
    """
    # 函数级 import：pipeline 与 memory 之间没有硬依赖顺序，这样放在模块级
    # 反而给 pipeline 的入口 import 链添堵；且只有本函数用得到解析器。
    from src.pipeline.paths import BRIEFS_DIR
    from src.pipeline.briefs_parser import parse_briefs_dir
    from src.core.llm import LLMBase

    if not date:
        raise ValueError("load_brief_date_local: date 不能为空")

    parsed = parse_briefs_dir(briefs_dir or BRIEFS_DIR, date)
    cards = list(parsed.get("pdf") or []) + list(parsed.get("web") or [])
    if not cards:
        logger.info("本地轻量入库 %s：这一天没有解析到卡片，跳过", date)
        return {"loaded": False, "skipped": True, "errors": []}

    resolved = resolve_provider(provider)
    # 与 ingest_source 同源：LLMBase 的 embedding 客户端是懒加载 property，
    # 首张卡才真正建连。
    llm = LLMBase(provider=resolved)
    store = VectorStore(MEMORY_DB_DIR, get_embedding_dimensions(resolved))

    loaded_any = False
    errors: List[str] = []

    for card in cards:
        item_id = str(card.get("item_id") or "")
        if not item_id:
            errors.append("跳过一张缺 item_id 的卡片")
            continue
        try:
            text = _card_text(card)
            chunk_hash = _chunk_hash(text)
            existing = store.rows_for_source(NAMESPACE_AATF, item_id)
            if any(r.get("chunk_hash") == chunk_hash for r in existing):
                # 幂等快路：内容没变就跳过——与 ingest_source 的
                # update_plan"chunk_hash 相同即 skip"同义。
                continue
            # embed 先行再动库：旧行 hash 不同（HTML 重新生成过）时，若先删
            # 后 embed，embedding 一炸这个 source 的既有条目就白没了。
            vector = await llm.embedding_model.aembed_query(text)
            for stale_id in (r.get("id") for r in existing if r.get("id")):
                try:
                    store.delete(stale_id)
                except Exception as e:  # noqa: BLE001 - 删不掉不挡新行
                    errors.append(f"删除 {item_id} 的过期行失败: {e}")
            record = _build_record(card, text, namespace=NAMESPACE_AATF)
            record["vector"] = vector
            store.add(record)
            loaded_any = True
        except Exception as e:  # noqa: BLE001 - 单卡失败不打断整天
            errors.append(f"{item_id}: {e}")
            logger.warning("轻量入库 %s 失败: %s", item_id, e)

    # skipped 的判定与 bridge 端对齐：没写入任何一行且没出错，就是"全都
    # 早就最新"——重复点加载走的就是这条路。
    return {"loaded": loaded_any, "skipped": not loaded_any and not errors,
            "errors": errors}
