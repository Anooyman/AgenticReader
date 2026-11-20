"""本地简报轻量入库 / 上游简报轻量入库——gateway.load_brief_date 的实现体。

两条路，由 gateway 的 auto 路由选一条（MEMORY_STORE_MODE / LLM_MEMORY_REPO）：

* **上游路** `load_brief_date_upstream`：把每张卡片落一份"摘要 JSON"
  （形状照上游 BriefAdapter 认的那套：item_id / generated_at / coverage_date /
  qa / qa_brief），再递 `upstream_ingest(source_type="brief", namespace=AATF,
  source_id=item_id)`。**原先的"零 LLM 直写"承诺在这里正式作废**——上游
  ingest 是一条 agentic 抽取管线，一张卡一轮抽取，代价是这一档不再是"几十次
  embedding 串行都嫌快"的轻量档；重复递同一张卡靠上游自带 hash-dedup
  兜住，chunks_added==0 就是"早就在了"，所以"是否已入库"不再自己算
  chunk-hash。id 空间没换轨：source_id 沿用 briefs_parser 算出的 item_id
  （上游补了 source_id 透传，原先预告的 `aatf-<date>-<kind>` 不必做了）。

* **本地路** `load_brief_date_local`：下面这套旧逻辑，直写 A 自库
  data/memory_db/ 的 namespace AATF（DA 裁决：本地 brief 加载落 A 自库，
  与对话同库，只靠 namespace 隔离）。设计仍是"轻量"两字——
  **零 LLM 调用**，简报卡片本身就是人工写好的中文导读，不做逐 chunk
  condense 与 source-summary 生成，直接 embed 导读正文；幂等按
  (namespace, source_id=item_id) 取已有行比 chunk 内容 hash，重复点
  "加载"不会多写一行；单卡失败记进 errors 继续下一张，返回契约
  {"loaded","skipped","errors"}，job_runner 的消费端不用分支。

两条路都**不 import src.ui**：本模块住记忆内核侧，卡片解析复用
pipeline.briefs_parser（与批处理同一 item_id 推导，两边算出的 ID 恒一致）。
"""
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config.settings import resolve_provider
from src.memory.config import (
    MEMORY_DB_DIR,
    MEMORY_STAGING_DIR,
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


# ---- 上游路：卡片 JSON → upstream ingest(source_type=brief) ----

def _card_generated_at(card: Dict[str, Any]) -> str:
    """上游把 chunk 的 occurred_at 取自 summary JSON 的 `generated_at`
    （ai_research 的既有语义：那才是"内容发生在什么时候"）。

    本地路用的是 coverage_date 零点，两条路得给同一个值，否则 /briefs 的
    按日聚合（occurred_at[:10]）会在上游路上退化到"入库那天"——同一天灌
    昨天的简报就会分错日。所以这里把 coverage_date 当 generated_at 递下去，
    解析不出来才退当前时间。
    """
    coverage = str(card.get("coverage_date") or card.get("date") or "")
    try:
        return datetime.strptime(coverage[:10], "%Y-%m-%d").replace(
            tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return _now()


def _card_summary_json(card: Dict[str, Any]) -> Dict[str, Any]:
    """一张卡片 → 上游 BriefAdapter 认的那份摘要 JSON。

    形状照抄 pipeline 摘要文件（item_id / generated_at / coverage_date /
    title / url / qa / qa_brief），因为上游的 BriefAdapter 就是
    AIResearchAdapter 的子类，parse() 读的就是这几个键；多余字段留着不碍事。

    * qa 优先按卡片现成的 `cn`（导读逐条）切——每个 label 一个 chunk，
      与 pipeline 摘要的"每维度一块"同构；`cn` 空时退一整块导读正文，
      保证再空的卡也有内容可抽，不至于交个空文件上去。
    * `themes` 单列一条：本地那边它是 keywords 的唯一来源，上游没有对应
      列位，就别让它在 JSON 里丢掉。
    * 链接单独一块，写法照 `_card_text` 那两句"链接：/PDF："——
      search_memory 的 _extract_row_url 认的就是这个形状，命中条目才能
      带上"按需下载入库"那个按钮。
    """
    text = _card_text(card)
    qa: Dict[str, str] = {}
    for label, body in (card.get("cn") or {}).items():
        if body and str(body).strip():
            qa[str(label)] = str(body).strip()
    links = []
    if card.get("url"):
        links.append(f"链接：{card['url']}")
    if card.get("pdf_url") and card.get("pdf_url") != card.get("url"):
        links.append(f"PDF：{card['pdf_url']}")
    if links:
        qa["链接"] = "\n".join(links)
    themes = _card_keywords(card)
    if themes:
        qa["主题"] = "、".join(themes)
    if not qa:
        qa["导读"] = text

    title = str(card.get("title") or card.get("item_id") or "")
    return {
        "item_id": str(card.get("item_id") or ""),
        "title": title,
        "type": "brief",
        "url": str(card.get("url") or ""),
        "generated_at": _card_generated_at(card),
        "coverage_date": str(card.get("coverage_date") or card.get("date") or ""),
        "qa": qa,
        # 速览块：标题 + 归属日期，一张卡最紧凑的一版，上游会单独成 chunk。
        "qa_brief": {"速览": f"{title}（{card.get('coverage_date') or card.get('date') or ''}）"}
        if title else {},
    }


def _stage_brief_card(card: Dict[str, Any]) -> str:
    """把一张卡片写成中转 JSON，返回路径。

    写盘走 write_json_atomic 那套（tmp+os.replace），文件名用 item_id——
    同一张卡反复入库落的是同一个文件，上游那边按内容 hash 去重，留一份
    可读的中转文件也方便事后查"我们到底递上去的是什么"。
    """
    from src.utils.json_io import write_json_atomic

    item_id = str(card.get("item_id") or "card")
    # item_id 会被拼进路径：只留安全字符，别拿卡片标题里的空格/斜杠去撞目录。
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in item_id)[:120]
    path = Path(MEMORY_STAGING_DIR) / f"{safe}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, _card_summary_json(card))
    return str(path)


async def load_brief_date_upstream(
    date: str,
    provider: Optional[str] = None,
    *,
    briefs_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """上游版轻量入库——与 local 那版同名同契约，只是写法换了。

    代价写在这里，别拿旧文档的口径来对：
      * **零 LLM 这条旧承诺作废**。上游 ingest 是一条 agentic 抽取管线，
        一张卡片一轮抽取（外加它自己的 source-summary 行），一天的卡片
        跑下来比本地"几十次 embedding 串行"重得多，前端那两句"轻量/很快"
        的话到了这条路上不该再说。
      * **幂等不自己算**。AR 侧不再算 chunk-hash、也不再取已有行比对，
        重复递同一张卡由上游自带的 hash-dedup 兜：report 里
        chunks_added==0 就是"内容早就在了"，不是失败也不是空跑。
      * **id 空间没换轨**。source_id 直接沿用 briefs_parser 算出的
        item_id（上游补了 source_id 透传，不必换 `aatf-<date>-<kind>`），
        与本地路的行仍然对得上。
      * **写失败不回落**。单卡失败照旧记进 errors 继续下一张（"这天没进
        来"比"这卡炸了整批停摆"好），但绝不在上游可用时顺手再写一份本地
        ——那还是双写。

    返回契约与 local 版逐字相同 {"loaded","skipped","errors"}。
    """
    from src.pipeline.paths import BRIEFS_DIR
    from src.pipeline.briefs_parser import parse_briefs_dir
    from src.memory import upstream

    if not date:
        raise ValueError("load_brief_date_upstream: date 不能为空")

    parsed = parse_briefs_dir(briefs_dir or BRIEFS_DIR, date)
    cards = list(parsed.get("pdf") or []) + list(parsed.get("web") or [])
    if not cards:
        logger.info("上游轻量入库 %s：这一天没有解析到卡片，跳过", date)
        return {"loaded": False, "skipped": True, "errors": []}

    loaded_any = False
    errors: List[str] = []

    for card in cards:
        item_id = str(card.get("item_id") or "")
        if not item_id:
            errors.append("跳过一张缺 item_id 的卡片")
            continue
        try:
            payload = await upstream.upstream_ingest(
                _stage_brief_card(card), "brief", NAMESPACE_AATF, item_id)
            if not payload.get("available"):
                # 上游可用但这一单没写成：如实记一笔，不去写本地。
                errors.append(f"{item_id}: {payload.get('note') or payload.get('error') or '无 note'}")
                continue
            report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
            added = int(report.get("chunks_added") or 0)
            if added > 0:
                loaded_any = True
            logger.info("上游轻量入库 %s：%s 新增 %s / 跳过 %s",
                        item_id, NAMESPACE_AATF, added,
                        int(report.get("chunks_skipped") or 0))
        except Exception as e:  # noqa: BLE001 —— 单卡失败不打断整天
            errors.append(f"{item_id}: {e}")
            logger.warning("上游轻量入库 %s 失败: %s", item_id, e)

    return {"loaded": loaded_any, "skipped": not loaded_any and not errors,
            "errors": errors}

