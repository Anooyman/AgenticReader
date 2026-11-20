"""AgenticReader 记忆系统的唯一接口层（收敛层），两段职责：

一、本仓记忆内核（src/memory/{ingest,search,vector_store}）：
  * 读：search()            —— D-B 三态作用域解析的唯一实现处 **+ 选路决策点**
  * 写：ingest()            —— 摘要/对话入库 **+ 选路决策点**
  * 浏览/删：browse_* / delete_* —— /data Memory tab 的 rows 原语（**恒为本地
    路**：上游 delete facade 属 Phase 2，落地前不接、也不造假）
  * DA 槽位：load_brief_date() —— 恒为 local（写 A 自库 AATF，见
    brief_ingest）；外部桥 driver 已退役，白名单只剩 {"local"}。
二、上游 LLM-Memory 门面（transport 住在 upstream.py）：
  * 选路：search()/ingest() 的 auto 路由（下面"路由"段）
  * 形状：上游 33 列行 → 本地 14 列形状（下面"形状映射层"段）
  * 观察窗：upstream_status / upstream_namespaces / upstream_search /
    upstream_available —— 本层做 namespace 收敛（复用
    resolve_search_namespaces 语义），与 browse_*/delete_* 的
    "policy 在本层 / 执行在别处"分工同构。

替换实现时动的只是本文件函数体内的转发目标；公开签名、返回形状、
namespace/作用域语义不变。

本文件自身遵守两条线：
  * 不 import src.ui / src.agents 模块级（ui 侧 import 全在函数体内，与
    job_runner 的既有风格一致），也不 import fastapi——HTTPException 映射
    属 api 层，src/memory 不沾 web 框架；
  * namespace 常量一律定义在 src/memory/config.py（policy 层），这里只
    做别名暴露，将来"内核替换"只动本文件内部。路由开关的取值常量也在
    config（MEMORY_STORE_MODE），本层只消费不发明。
"""
import logging
import os
from typing import Any, Dict, List, Optional, Union

from src.config.settings import resolve_provider
from src.memory.config import (
    DEFAULT_SEARCH_NAMESPACES,
    EXTERNAL_SEARCH_NAMESPACES,
    MEMORY_DB_DIR,
    MEMORY_MODE_AUTO,
    MEMORY_STORE_MODE_ENV,
    NAMESPACE_AATF,
    NAMESPACE_AI_RESEARCH,
    NAMESPACE_WEBAPP_CHAT,
    get_embedding_dimensions,
    get_memory_store_mode,
)
from src.memory.ingest import ingest_source as _ingest_source
from src.memory.search import agentic_search as _agentic_search
from src.memory.vector_store import (
    VectorStore,
    dump_json_list,     # 形状映射层归一 keywords 用
    is_summary_row,     # 纯函数 re-export：memory_browse 改从 gateway 取  # noqa: F401
    load_json_list,     # 同上
)

logger = logging.getLogger(__name__)

# ---- 常量别名（policy 定义仍在 config，消费方只认 gateway）----
NAMESPACE_AI_RESEARCH: str = NAMESPACE_AI_RESEARCH    # "ai-research"
NAMESPACE_WEBAPP_CHAT: str = NAMESPACE_WEBAPP_CHAT    # "webapp-chat"
NAMESPACE_AATF: str = NAMESPACE_AATF                  # "AATF"（local driver 轻量入库写入自库）
DEFAULT_SEARCH_NAMESPACES: List[str] = DEFAULT_SEARCH_NAMESPACES
EXTERNAL_SEARCH_NAMESPACES: List[str] = EXTERNAL_SEARCH_NAMESPACES  # 现恒为 []


# ---- D-B 解析 ----
def resolve_search_namespaces(
    requested: Optional[Union[str, List[str]]],
) -> Union[str, List[str]]:
    """D-B 三态解析的唯一实现处，逻辑钉死：
    (a) None / "" / [] / [""] → list(DEFAULT_SEARCH_NAMESPACES)   # 自库白名单
    (b) "*" / ["*"] / 任何含 "*" 的列表 → 返回字符串 "*"           # 全部；
        底层 _where 对 "*" 不生成过滤（vector_store.py 已核实），
        天花板加在本层而非底层，browse 的"省略=全部"不反转。
    (c) 其余显式列表 → 先 str() 再 strip 去空项，再保序去重，返回 list。
        显式列表按原样子集生效——"天花板"语义由 (a) 分支承担，这里不套娃。
    单字符串先归一化为单元素列表再走 (b)/(c) 判定。
    """
    if not requested:
        return list(DEFAULT_SEARCH_NAMESPACES)
    items: List[str]
    if isinstance(requested, str):
        items = [requested]
    else:
        items = [str(n) for n in requested if n and str(n).strip()]
    items = [n.strip() for n in items if n.strip()]
    if not items:
        return list(DEFAULT_SEARCH_NAMESPACES)
    if "*" in items:
        return "*"
    seen, out = set(), []
    for n in items:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


# ---- 形状映射层：上游行 → 本地形状（私有纯函数）----
# 上游 common/vector.py 的 _TEXT_FIELDS 是 30 个 text 列，加 vector /
# importance / access_count 共 33 列；本仓 vector_store 是 12 text + vector +
# importance = 14 列。原则一句话：**本地形状一个键都不换，多余的列整列丢掉**
# ——memory_search 子 agent 与 /briefs 的日期聚合（occurred_at[:10]）零改动
# 可跑是这层的验收线，形状层任何"顺手多给一列"都算越界。
#
# chunk_hash 的口径（这里比文档原文更精确）：上游**schema 里有**这列
# （vector.py:53 注记 "summary 行时为 ''"），但 agentic_search 返回的行经它
# 自己的 shape_result_row 裁过，**不带** chunk_hash——所以"保真优先"就是
# 先按 row 里在不在这一列来分：在就用它（真值），不在才动用启发式。
# 启发式 "keywords 空 + detail 长 → 像是整篇摘要行" 是**模拟不是保真**，
# 只在上游没把列交出来时兜底，别拿它当上游语义。
_SUMMARY_ROW_DETAIL_CHARS = 2000


def _map_upstream_row(row: Any) -> Dict[str, Any]:
    """一行上游行 → 本地 14 列形状。输入不是 dict 就给一个全空行（宁可
    空，不 raise——形状层的失败不该把整次检索拖成异常）。"""
    if not isinstance(row, dict):
        row = {}
    keywords_raw = row.get("keywords", "")
    # 本地库里 keywords 是 JSON 文本（dump_json_list 写过的那套），消费方
    # （shape_result_row / memory_browse）拿 load_json_list 去解。上游的形状
    # 行里它可能已经是 list——归一成 JSON 文本，别把 list 递给解 JSON 的人。
    if isinstance(keywords_raw, (list, tuple)):
        keywords = dump_json_list(list(keywords_raw))
    else:
        keywords = keywords_raw if isinstance(keywords_raw, str) else ""
    created_at = str(row.get("created_at") or "")
    detail = str(row.get("detail") or "")
    if "chunk_hash" in row:
        chunk_hash = str(row.get("chunk_hash") or "")
    else:
        # 列没交出来：只有"keywords 空 + detail 明显偏长"才敢猜它是摘要行
        # （摘要行的特征是没抽 keyword 却带了长 detail）。猜错只影响
        # is_summary_row 的展示位，检索命中不受影响。
        chunk_hash = "" if (not load_json_list(keywords)
                            and len(detail) >= _SUMMARY_ROW_DETAIL_CHARS) else "unknown"
    return {
        "id": str(row.get("id") or ""),
        "namespace": str(row.get("namespace") or ""),
        "memory_type": str(row.get("memory_type") or ""),
        "abstract": str(row.get("abstract") or ""),
        "detail": detail,
        "keywords": keywords,
        "created_at": created_at,
        # /briefs 的日期聚合按 [:10] 取日，occurred_at 缺则退 created_at——
        # 与本地 vector_store.shape_result_row 那条 fallback 完全同构。
        "occurred_at": str(row.get("occurred_at") or "") or created_at,
        "source_type": str(row.get("source_type") or ""),
        "source_id": str(row.get("source_id") or ""),
        "chunk_hash": chunk_hash,
        "raw_source": str(row.get("raw_source") or ""),
        "importance": _as_float(row.get("importance"), 0.5),
        "score": _as_float(row.get("score"), 0.0),
    }


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _map_upstream_search_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """上游 search 结果 → agentic_search 的四键形状，逐字对齐本地返回形状
    （answer / results / iterations / tool_calls_made），**一个额外键都不
    加**——调用方按这个形状写死，加键就是改契约。走没走上游只进日志。
    上游多出来的 status / detail_level / clarifying_question / synthesis 全
    部落在这层：有信息价值，但没有本地形状的对应槽位，留给日志。"""
    rows = payload.get("results")
    answer = str(payload.get("answer") or "")
    if not answer:
        # 上游按 clarifying 收尾时 answer 是空的，只留 clarifying_question——
        # 本地形状没有第二个槽位，就把它并到 answer 里，否则子 agent 拿到
        # "空答案 + 有命中"会当成检索失败，比多几个字的 answer 更糟。
        answer = str(payload.get("clarifying_question") or "")
    return {
        "answer": answer,
        "results": [_map_upstream_row(r) for r in rows] if isinstance(rows, list) else [],
        "iterations": int(_as_float(payload.get("iterations"), 0.0)),
        "tool_calls_made": int(_as_float(payload.get("tool_calls_made"), 0.0)),
    }


def _map_upstream_ingest_report(payload: Dict[str, Any],
                                requested_source_id: Optional[str] = None) -> Dict[str, Any]:
    """上游 ingest 的 report → 调用方吃的 report 形状（见
    ingest.ingest_source 的 docstring 那十个键）。上游的 report 套在一层
    {source_type, namespace, report} 里，先剥一层再摊平。

    两条刻意的设计，别回头改回去：
      * **计数器只带上游真报的那几个**：present-only。缺 `chunks_added` 就
        整个键不写，而不是补一个 0——"上游没报这个数"和"上游报了 0 新增"
        是两回事，写成后者就是造假（调用方 .get(..., 0) 的读法也不受影响，
        它本来就把缺键当 0）。今天上游 report 十个键都在，所以正常路径下
        形状与本地路逐字相同。
      * **上游多出来的列原样带过**（stale_kept / dry_run / chunk_sizes /
        将来任何新键）：扩展位在这儿是白送的可观测性，而且万一日后计数器
        改名，幂等信号还留在形状里，不会被映射层悄悄抹成 0。
    本地那十个键的名字一个都不换——调用方按它们写死。

    source_id 有个已知的不对称：上游 SDK 面**今天**不接受 source_id（Phase 2
    的第一条补丁就是补这个透传），行里的 id 由上游 adapter 按 path 自己派生。
    这里在"请求 id ≠ 实际 id"时打 warning 而不是造一个假 id 字段——落库事实
    以上游报回来的为准。"""
    inner = payload.get("report")
    if not isinstance(inner, dict):
        inner = payload
    report: Dict[str, Any] = {}
    # 身份三件：外层报的多，内层也有一份，取非空的那个。
    for key in ("source_type", "namespace"):
        value = payload.get(key) or inner.get(key)
        if value:
            report[key] = str(value)
    source_id = inner.get("source_id") or payload.get("source_id")
    if source_id:
        report["source_id"] = str(source_id)
    # 计数器：present-only，见上。
    for key in ("units", "chunks_total", "chunks_added", "chunks_skipped", "chunks_deleted"):
        if isinstance(inner.get(key), (int, float)) and not isinstance(inner.get(key), bool):
            report[key] = int(inner[key])
    # 其余（含 summary_id 与非 list 的怪形状）原样带上，留给日志与将来。
    for key, value in inner.items():
        report.setdefault(key, value)
    # source_id 的一致性断言不住在这层：`upstream_ingest` 拿到 echo 就会比
    # （transport 层看得见 echo，映射层看不见增量信息），这里再打一条只会
    # 让同一件事刷两遍日志。
    return report


# ---- 路由：唯一决策点 ----
# 决策只在这一个函数里做，search()/ingest() 各自消费它的布尔答案，绝不出现
# 两处选路逻辑漂移。日志里带"这次为什么走这条"，出问题时不用猜。
_ROUTED_KEYS_LOGGED: set = set()


def _note_once(key: str, message: str) -> None:
    """每个进程 × 每个原因只说一次，免得 chat_ingest 每 60s 一轮就刷一屏。"""
    if key in _ROUTED_KEYS_LOGGED:
        return
    _ROUTED_KEYS_LOGGED.add(key)
    logger.warning(message)


async def _route_is_upstream(where: str) -> bool:
    """auto 路由的唯一答案：
      * MEMORY_STORE_MODE=local → False（kill switch，上游再可用也不写上游）
      * 上游不可达（repo 未设/无效、client 构造失败）→ False + 一句 warning
      * 否则 True

    "False 之后要不要回落本地"由调用方自己定：读可以回落，**写不能**——
    见 ingest() 的注释。这条函数只回答"上游这条路开不开"。
    """
    mode = get_memory_store_mode()
    if mode != MEMORY_MODE_AUTO:
        # 今天白名单里只有 local 会走到这，措辞不写死取值：将来加模式也不用改话。
        _note_once(f"mode:{mode}",
                   f"记忆读写按 {MEMORY_STORE_MODE_ENV}={mode} 走本地旧路，"
                   f"上游即使可用也不走（kill switch）")
        return False
    if await _upstream_available():
        return True
    _note_once("unavailable",
               "上游 LLM-Memory 不可用（LLM_MEMORY_REPO 未设置/无效，或 MemoryClient "
               "构造失败），本次记忆读写走本地旧库 data/memory_db；"
               "想强制本地还有 MEMORY_STORE_MODE=local 这把 kill switch")
    return False


async def _upstream_available() -> bool:
    """转发位：测试可以只 patch 这一处来钉路由，不必装一个假 SDK。"""
    return await _upstream.upstream_available()


# ---- 读 ----
async def search(
    query: str,
    *,
    namespaces: Optional[Union[str, List[str]]] = None,
    provider: Optional[str] = None,
    max_iterations: Optional[int] = None,
) -> Dict[str, Any]:
    """统一读入口，内含 auto 路由（上游可用→上游路，否则本地旧路）。
    namespaces=None → 自库白名单（D-B，见 resolve_search_namespaces）。
    provider 在这里 resolve_provider(provider) 一次——调用方语义：有就传、
    None 走全局解析，与现调用点 resolve_provider(None) 等值。返回形状逐字
    等于 agentic_search（answer/results/iterations/tool_calls_made）：走上游
    时由形状映射层把上游行摊成同一形状，**不多给任何一个键**。
    LLM 在工具循环内显式传的 namespace 仍按其请求生效——"补值"语义在
    sub-agent 层，硬天花板属 SDK 替换时 allowed= 参数的职责，本轮不拦。

    上游路失败**允许**回落到本地：读是幂等的，回落只是"少看到一批上游行"，
    不会造成任何写侧的双写或漏账，代价只是一条 warning。
    """
    ns = resolve_search_namespaces(namespaces)
    if await _route_is_upstream("search"):
        scoped = "*" if ns == "*" else (ns if isinstance(ns, list) else None)
        payload = await _upstream_search_scoped(query, scoped)
        if payload.get("available"):
            logger.debug("gateway.search 走上游路（ns=%s）", "全局" if scoped is None else scoped)
            return _map_upstream_search_result(payload)
        logger.warning("上游 search 未成，本次检索回落本地旧库：%s",
                       payload.get("note") or payload.get("error") or "无 note")
    kwargs = {"provider": resolve_provider(provider)}
    if max_iterations is not None:
        kwargs["max_iterations"] = max_iterations
    return await _agentic_search(query, namespace=ns, **kwargs)


async def _upstream_search_scoped(query: str,
                                  ns: Optional[Union[str, List[str]]]) -> Dict[str, Any]:
    """把已收敛好的作用域递给上游：None / "*" → 不传作用域（上游全局），
    单元素列表升格成 str，其余按 namespaces 列表显式收窄。与门面位
    upstream_search() 共用同一个收敛器，不另写一套。

    这里**刻意**沿用 D-B 的补值结果（None → 自库白名单），不是门面那条
    "缺省=全局"：`search()` 是会话里的检索入口，天花板语义归它管——真一句
    "那个论文" 没勾 AATF 时，走上游也必须只搜 ai-research + webapp-chat；
    不传作用域＝让上游跨 store 全量搜，等于绕过天花板把 AATF 也捎上。"全部"
    这个语义只属于显式的 "*"。
    """
    if not ns or ns == "*":
        return await _upstream.upstream_search(query)
    if isinstance(ns, (list, tuple)):
        if len(ns) == 1:
            return await _upstream.upstream_search(query, namespace=str(ns[0]))
        return await _upstream.upstream_search(query, namespaces=[str(n) for n in ns])
    return await _upstream.upstream_search(query, namespace=str(ns))


# ---- 写 ----
async def ingest(
    path: str,
    source_type: str,
    namespace: str,
    *,
    provider: Optional[str] = None,
    source_id: Optional[str] = None,
) -> Dict[str, Any]:
    """统一写入口，内含 auto 路由：上游可用就交 `upstream_ingest`，否则直通
    `ingest.ingest_source`。provider 与 search() 同源，一律先过
    resolve_provider(provider)——None 走全局解析，显式值做 strip+lower 归一。
    读写两侧的 provider 字符串因此恒等价；否则 SDK 替换后若调用方传 "Azure"
    这类未归一值，embedding 维度会经 get_embedding_dimensions(未归一值)
    错开分支。返回 report dict 形状逐字不变（chunks_added/chunks_skipped/
    chunks_deleted/...），走上游时由映射层从上游 report 摊平出同样十个键。

    **写路不回落**，这是与 search() 唯一的行为差别，也是刻意的：上游写失败就
    如实抛，让调用方（chat_ingest 的水位线、job_runner 的任务账本）照常记一
    笔失败，绝不在这里悄悄再写一份本地——"上游炸了顺手写本地"看着顺眼，实际
    是双写：同一份内容两处落库、水位线还照推进，下次补灌时谁都不知道该怪谁。
    上游写路失败时想回旧路只有两条正经办法：重试，或者 unset LLM_MEMORY_REPO
    （设 MEMORY_STORE_MODE=local 也行）让路由整体退回本地。
    """
    if await _route_is_upstream("ingest"):
        payload = await _upstream.upstream_ingest(path, source_type, namespace, source_id)
        if not payload.get("available"):
            note = payload.get("note") or payload.get("error") or "无 note"
            # 抛出去而不是返回 error 形状：三个调用方都是 try/except 记账，
            # 返回 dict 会被它们当成成功（common.py 直接置 memory_ingested=True）。
            raise RuntimeError(f"上游 memory ingest 失败（{source_type}/{namespace}）：{note}")
        logger.debug("gateway.ingest 走上游路：ns=%s src=%s", namespace, source_type)
        return _map_upstream_ingest_report(payload, requested_source_id=source_id)
    return await _ingest_source(
        path, source_type=source_type, namespace=namespace,
        provider=resolve_provider(provider),
        source_id=source_id,
    )



# ---- 浏览/删除原语（供 memory_browse 组合，形状留在 service 层）----
def _store(provider: Optional[str] = None) -> VectorStore:
    """唯一的 VectorStore 组装点：维度按 resolve_provider(provider) 解析
    ——替代 memory_browse 旧 _vs() 写死 "azure" 的逻辑。"""
    return VectorStore(MEMORY_DB_DIR, get_embedding_dimensions(resolve_provider(provider)))


def browse_all_rows(namespace: Union[str, List[str]] = "*") -> List[Dict[str, Any]]:
    return _store().all_rows(namespace)


def browse_rows_for_source(namespace: Union[str, List[str]], source_id: str) -> List[Dict[str, Any]]:
    return _store().rows_for_source(namespace, source_id)


# ---- 同步侧的选路 ----
# delete_* 三个原语是 sync 函数，不能 await 一个 async 决策点，所以这里放一份
# 只读的同步版本：同样的 mode 判定，同样的"上游开不开"答案，只是 availability
# 探测走 _upstream.upstream_available_sync（线程安全、无事件循环依赖）。
# 两套实现共享同一条规则，规则改了必须两边一起改——见下面的成对注释。
def _route_is_upstream_sync(where: str) -> bool:
    mode = get_memory_store_mode()
    if mode != MEMORY_MODE_AUTO:
        _note_once(f"mode:{mode}",
                   f"记忆读写按 {MEMORY_STORE_MODE_ENV}={mode} 走本地旧路，"
                   f"上游即使可用也不走（kill switch）")
        return False
    if _upstream_available_sync():
        return True
    _note_once("unavailable",
               "上游 LLM-Memory 不可用（LLM_MEMORY_REPO 未设置/无效，或 MemoryClient "
               "构造失败），本次记忆读写走本地旧库 data/memory_db；"
               "想强制本地还有 MEMORY_STORE_MODE=local 这把 kill switch")
    return False


def _upstream_available_sync() -> bool:
    """转发位：与 `_upstream_available()` 成对，测试同样可以只 patch 这里。"""
    return _upstream.upstream_available_sync()


# 删除面共用的护栏。上游的 delete/delete_where 自己就拒 unscoped 与跨 ns 的
# id，但那两道闸是**上游**给的；这里在选路之前先把空/`*` 的 namespace 挡下来，
# 于是"上游开不开"都会得到同一句拒绝——否则同一个请求会因为路由不同而
# 一次报错一次删穿全库，那是最难查的那种不一致。
def _guard_scoped_namespace(namespace: str, what: str) -> str:
    name = str(namespace or "").strip()
    if not name or name == "*":
        # 措辞对齐上游 _checked_namespace 与 memory_browse 的期待，UI 侧
        # pattern-match 不用认两套话。
        raise ValueError(f"refusing to delete {what} with namespace={namespace!r}: "
                         "pass one exact namespace name")
    return name


# ---- 删除原语（写语义：不回落）----
# 三个都保持 sync：调用方一是 memory_browse 的 asyncio.to_thread 包装，
# 二是 chat_service.delete_session 那种本来就是同步方法的会话回收，
# 把它们 async 化等于去动两个不在本轮 scope 里的调用点。上游调用由
# upstream.py 的线程池硬封顶，不阻塞事件循环这件事由调用层保证。
def delete_item(memory_id: str) -> None:
    """单条删除。表不存在时静默返回（=VectorStore.delete 现行为）。

    走上游时这是一次**写**：失败就 raise，不回落本地。上游把"这行本来
    就没有"报成 {deleted: False, reason: ...}——那是状态已满足，不是错误，
    照本地语义当成功收下，只打一条 info 让运维看得见。
    """
    if _route_is_upstream_sync("delete_item"):
        payload = _upstream.upstream_delete(memory_id)
        if not payload.get("available"):
            raise RuntimeError(f"上游 delete 失败（id={memory_id}）："
                               f"{payload.get('note') or payload.get('error') or '无 note'}")
        if not payload.get("deleted"):
            logger.info("上游 delete：%s 无此行，视为已删除（reason=%s）",
                        memory_id, payload.get("reason") or "未给出")
        return
    _store().delete(memory_id)


def delete_source(namespace: str, source_id: str) -> int:
    """按 (namespace, source_id) 删一片，返回删除条数。

    本地路：取行 + 逐删（策略住这里，SDK 替换只改本函数一处）。
    上游路：交给 delete_where 的一次提交，并把 namespace 先过护栏——
    上游的 namespace 是**必填且必须具体**的，空串或 "*" 直接被拒。
    """
    if _route_is_upstream_sync("delete_source"):
        name = _guard_scoped_namespace(namespace, "source")
        payload = _upstream.upstream_delete_where(namespace=name, source_id=source_id)
        if not payload.get("available"):
            raise RuntimeError(f"上游 delete_where 失败（ns={name} source_id={source_id}）："
                               f"{payload.get('note') or payload.get('error') or '无 note'}")
        return int(payload.get("deleted") or 0)
    store = _store()
    rows = store.rows_for_source(namespace, source_id)
    return _delete_rows(store, rows, "delete_source")


def delete_namespace(namespace: str) -> int:
    """清空一个 namespace。

    上游路上这是**整个 ns 级别**的删除，护栏先挡住空串与 "*"（挡住的是
    "顺手清空全库"，本地那条取行逐删的路今天也不该拿 "*" 当输入跑）；
    剩下的语义与本地一致：删掉多少行报多少，失败就 raise 不回落。
    """
    if _route_is_upstream_sync("delete_namespace"):
        name = _guard_scoped_namespace(namespace, "namespace")
        payload = _upstream.upstream_delete_where(namespace=name)
        if not payload.get("available"):
            raise RuntimeError(f"上游 delete_where 失败（ns={name}）："
                               f"{payload.get('note') or payload.get('error') or '无 note'}")
        return int(payload.get("deleted") or 0)
    store = _store()
    return _delete_rows(store, store.all_rows(namespace), "delete_namespace")


def _delete_rows(store: VectorStore, rows: List[Dict[str, Any]],
                 tag: str) -> int:
    """逐删共用实现：缺 id 的行跳过并 warning（旧代码 row["id"] 在这里会
    KeyError，改 skip 后计数也只记真删，不把幻影行算进 deleted 返回给 UI）。"""
    deleted = 0
    for row in rows:
        row_id = row.get("id")
        if not row_id:
            logger.warning("gateway.%s: 行缺少 id，跳过（不计入删除数）：%s", tag, row)
            continue
        try:
            store.delete(row_id)
            deleted += 1
        except Exception:  # noqa: BLE001 —— 单条失败不阻断其余
            logger.warning("gateway.%s: 删除失败 id=%s", tag, row_id, exc_info=True)
    return deleted


# ---- 桥段已随 HTTP 桥退役整体删除 ----
# （原"桥"段的 transport 异常类、地址常量、一跳函数与七个 brief_* 具名
#  封装全部移除：外部 webui 的简报端点实测 500，这条路本就不通，删除不
#  损失可用功能，仓内也不再有对它的任何调用点。）


# ---- DA：brief 加载驱动槽位 ----
BRIEF_DRIVER_ENV = "MEMORY_BRIEF_DRIVER"  # 唯一合法取值 "local"（缺省即 local）


async def load_brief_date(date: str) -> Dict[str, Any]:
    """DA 分派：先按 auto 路由定"这天的卡片往哪儿写"，再看
    env MEMORY_BRIEF_DRIVER 的显式驱动白名单 {local}。

    两条正交的东西别混：driver 决定"由谁去加载"（外部桥已退役，白名单
    只剩 local 一条路，非法值 warning 后照跑），路由决定"写进哪个库"
    （上游可用 → 卡片 JSON 递上游 ingest(source_type=brief)；否则本地
    直写 AATF）。非法 driver 值不影响选路——它兜底的还是同一条 local。

    返回契约恒为 {"loaded","skipped","errors"}（job_runner 的判定只认这三键）。
    """
    driver = (os.environ.get(BRIEF_DRIVER_ENV) or "local").strip().lower()
    if driver != "local":
        logger.warning("%s 取值 %r 不在白名单 ['local']，按 local 运行",
                       BRIEF_DRIVER_ENV, driver)
    if await _route_is_upstream("load_brief_date"):
        return await _upstream_brief_load(date)
    return await _local_brief_load(date)


async def _upstream_brief_load(date: str) -> Dict[str, Any]:
    """上游实现位：解析卡片 → 中转摘要 JSON → upstream ingest。

    与本地版的两处既定差别：不再零 LLM（上游是 agentic 抽取），"这卡进没
    进"看上游报的 chunks_added 而不是自算 chunk-hash。失败不回落——
    brief_ingest 里写清楚了为什么这里也不许写一份本地。
    """
    from src.memory.brief_ingest import load_brief_date_upstream
    return await load_brief_date_upstream(date)


async def _local_brief_load(date: str) -> Dict[str, Any]:
    """本地驱动实现位（DA 裁决已落地）：写 A 自库 data/memory_db/ 的
    NAMESPACE_AATF——与对话记忆同库，只靠 namespace 隔离，不再维护第二套
    存储（"不想长期维护两套 memory"的收敛结果）。

    实现在 brief_ingest.load_brief_date_local：解析 BRIEFS_DIR 该天的
    HTML 卡片，逐卡写一行（source_id=item_id，chunk 内容 hash 幂等，
    零 LLM 调用——简报本身就是人写的中文导读，再做 condense 纯属浪费）。
    """
    from src.memory.brief_ingest import load_brief_date_local
    return await load_brief_date_local(date)



# ---- 计数层的接缝在哪儿 ----
# 计数层不在这里另起一个函数：memory_browse.fetch_overview 直接调本模块已有的
# `upstream_namespaces()` 只读枚举（失败折叠成空列表），把两边计数并列出来。
# 在这里再包一层"合并好的列表"看着方便，其实是多一个没人养的公开函数——
# 只有 /data 那一个消费者，形不形式上都在 memory_browse 那侧收口更诚实。


# ---- 上游 LLM-Memory 门面 ----
# 分工与 browse_*/delete_* 同构：policy（namespace 收敛、选路）住在 gateway，
# transport 住在 src/memory/upstream.py——本文件不 import 上游细节，
# upstream.py 也不 import 本层以外的东西。写路也在这扇窗里（"全段只读"的旧
# 纪律按收敛裁决有意反转：ingest 走 upstream_ingest，remember 仍不碰），
# 上游 ingest 门面照旧拒 "brief" 之类的非枚举 source_type，写进去的只是
# ai-research / webapp-chat 两条通道；AATF 轻量入库仍由 local 直写（Phase 2）。
from src.memory import upstream as _upstream  # 模块级安全：upstream 只有 stdlib 的模块级 import


async def upstream_available() -> bool:
    """上游 SDK 通道是否可达（env LLM_MEMORY_REPO 有效且 MemoryClient 可用）。"""
    return await _upstream.upstream_available()


async def upstream_status(namespace: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
    """上游 store 视图：{available, namespaces:[{name,rows}], total, ...}。
    namespace 走 D-B 三态收敛——单元素列表升格为显式单 ns 视图，"*" 与其
    余多元素列表都按"看整个 store"处理（status 本来就是 store 级）。"""
    resolved = resolve_search_namespaces(namespace)
    single = resolved[0] if isinstance(resolved, list) and len(resolved) == 1 else None
    return await _upstream.upstream_status(single)


async def upstream_namespaces() -> List[Dict[str, Any]]:
    """上游 namespace 清单 [{name, rows}]；不可用返回 []（形状稳定优先）。"""
    return await _upstream.upstream_namespaces()


async def upstream_search(query: str,
                          namespace: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
    """上游 agentic 检索。**缺省不传作用域**（全局搜，上游报 scoped=False
    + "跨 store"自述）——上游实测 ns 全是 slug-<digest> 派生名，把自库
    白名单喂过去必然 0 命中还谎报 scoped=True，所以 None 路绝不走
    resolve_search_namespaces 的补值。显式作用域三态与本地 search 的解析
    器共用同一实现（*不碰 resolve_search_namespaces 本体*）：
      * "*" / 含 "*" 的列表 → 同样不传作用域（"全部"在上游就是全局）；
      * 单元素列表 → namespace=str；
      * 其余显式列表 → namespaces=list。
    返回形状为 upstream 的折叠结果原样（不套 (status, body) 的 HTTP 形状
    ——那是退役桥的遗产），失败映射成什么状态码归 api 层。
    """
    if not namespace:
        return await _upstream.upstream_search(query)
    resolved = resolve_search_namespaces(namespace)
    if resolved == "*":
        return await _upstream.upstream_search(query)
    if isinstance(resolved, list) and len(resolved) == 1:
        return await _upstream.upstream_search(query, namespace=resolved[0])
    return await _upstream.upstream_search(query, namespaces=list(resolved))


# 决策面转发（MCP 工具调用面在 upstream.py 的白名单闸内；gateway 这里只
# 转发不复制——command/args/env 的单源也在 upstream.py 的 MCP_CONFIG 读取，
# 两层各留一道白名单是纵深不是重复实现）。
async def upstream_decision_status() -> Dict[str, Any]:
    """决策面开关的诚实答案。未启用只回 gate（不起子进程）；启用才探测。"""
    return await _upstream.upstream_decision_status()


async def upstream_decision_call(tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """memory_why / memory_pack 的一跳直通。写工具进不来。"""
    return await _upstream.upstream_decision_call(tool, arguments)



