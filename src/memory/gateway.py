"""AgenticReader 记忆系统的唯一接口层（收敛层），两段职责：

一、本仓记忆内核（src/memory/{ingest,search,vector_store}）：
  * 读：search()            —— D-B 三态作用域解析的唯一实现处
  * 写：ingest()            —— 摘要/对话入库
  * 浏览/删：browse_* / delete_* —— /data Memory tab 的 rows 原语
  * DA 槽位：load_brief_date() —— 恒为 local（写 A 自库 AATF，见
    brief_ingest）；外部桥 driver 已退役，白名单只剩 {"local"}。
二、上游 LLM-Memory 只读门面（transport 住在 upstream.py）：
  * upstream_status / upstream_namespaces / upstream_search /
    upstream_available —— 本层做 namespace 收敛（复用
    resolve_search_namespaces 语义），与 browse_*/delete_* 的
    "policy 在本层 / 执行在别处"分工同构。只读，无写上游路径。

替换实现时动的只是本文件函数体内的转发目标；公开签名、返回形状、
namespace/作用域语义不变。

本文件自身遵守两条线：
  * 不 import src.ui / src.agents 模块级（ui 侧 import 全在函数体内，与
    job_runner 的既有风格一致），也不 import fastapi——HTTPException 映射
    属 api 层，src/memory 不沾 web 框架；
  * namespace 常量一律定义在 src/memory/config.py（policy 层），这里只
    做别名暴露，将来"内核替换"只动本文件内部。
"""
import logging
import os
from typing import Any, Dict, List, Optional, Union

from src.config.settings import resolve_provider
from src.memory.config import (
    DEFAULT_SEARCH_NAMESPACES,
    EXTERNAL_SEARCH_NAMESPACES,
    MEMORY_DB_DIR,
    NAMESPACE_AATF,
    NAMESPACE_AI_RESEARCH,
    NAMESPACE_WEBAPP_CHAT,
    get_embedding_dimensions,
)
from src.memory.ingest import ingest_source as _ingest_source
from src.memory.search import agentic_search as _agentic_search
from src.memory.vector_store import (
    VectorStore,
    is_summary_row,   # 纯函数 re-export：memory_browse 改从 gateway 取
    load_json_list,   # 同上
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


# ---- 读 ----
async def search(
    query: str,
    *,
    namespaces: Optional[Union[str, List[str]]] = None,
    provider: Optional[str] = None,
    max_iterations: Optional[int] = None,
) -> Dict[str, Any]:
    """统一读入口。namespaces=None → 自库白名单（D-B，见
    resolve_search_namespaces）。provider 在这里 resolve_provider(provider)
    一次——调用方语义：有就传、None 走全局解析，与现调用点
    resolve_provider(None) 等值。返回形状逐字等于 agentic_search
    （answer/results/iterations/tool_calls_made）。
    LLM 在工具循环内显式传的 namespace 仍按其请求生效——"补值"语义在
    sub-agent 层，硬天花板属 SDK 替换时 allowed= 参数的职责，本轮不拦。
    """
    ns = resolve_search_namespaces(namespaces)
    kwargs = {"provider": resolve_provider(provider)}
    if max_iterations is not None:
        kwargs["max_iterations"] = max_iterations
    return await _agentic_search(query, namespace=ns, **kwargs)


# ---- 写 ----
async def ingest(
    path: str,
    source_type: str,
    namespace: str,
    *,
    provider: Optional[str] = None,
    source_id: Optional[str] = None,
) -> Dict[str, Any]:
    """统一写入口：直通 ingest.ingest_source。provider 与 search() 同源，
    一律先过 resolve_provider(provider)——None 走全局解析，显式值做
    strip+lower 归一。读写两侧的 provider 字符串因此恒等价；否则 SDK
    替换后若调用方传 "Azure" 这类未归一值，embedding 维度会经
    get_embedding_dimensions(未归一值) 错开分支。返回 report dict 形状
    逐字不变（chunks_added/chunks_skipped/chunks_deleted/...）。
    """
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


def delete_item(memory_id: str) -> None:
    """单条删除；表不存在时静默返回（=VectorStore.delete 现行为）。"""
    _store().delete(memory_id)


def delete_source(namespace: str, source_id: str) -> int:
    """按 (namespace, source_id) 取行逐删，返回删除条数。取行+逐删的策略
    住在这里——SDK 替换时此函数一处改成 delete_where（自带 unscoped
    护栏），service 层形状不动。"""
    store = _store()
    rows = store.rows_for_source(namespace, source_id)
    return _delete_rows(store, rows, "delete_source")


def delete_namespace(namespace: str) -> int:
    """清空 namespace，取行+逐删策略同 delete_source。"""
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
    """DA 分派：env MEMORY_BRIEF_DRIVER，显式白名单 {local}。
    桥 driver 已退役——白名单只剩 local 一条路，任何其它取值（包括退役
    前的旧值 "bridge"）都 warning 后按 local 跑，非法值兜底语义与桥时代
    完全一致，只是"兜底"的另一侧没有了。
    local → _local_brief_load(date)：写 A 自库 namespace AATF，实现在
    brief_ingest（内核侧自给自足，不碰 src.ui）。
    返回契约恒为 {"loaded","skipped","errors"}（job_runner 的判定只认这三键）。
    """
    driver = (os.environ.get(BRIEF_DRIVER_ENV) or "local").strip().lower()
    if driver != "local":
        logger.warning("%s 取值 %r 不在白名单 ['local']，按 local 运行",
                       BRIEF_DRIVER_ENV, driver)
    return await _local_brief_load(date)


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


# ---- 上游 LLM-Memory 只读门面 ----
# 分工与 browse_*/delete_* 同构：policy（namespace 收敛）住在 gateway，
# transport 住在 src/memory/upstream.py——本文件不 import 上游细节，
# upstream.py 也不 import 本层以外的东西。全段只读：AR 没有任何写上游的
# 路径（上游 ingest 门面也拒 "brief" source_type），这里只是自库之外的
# 一扇观察窗。
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



