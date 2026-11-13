"""AgenticReader 接入 LLM-Memory 的唯一接口层（收敛层）。

一切对本仓记忆内核（src/memory/{ingest,search,vector_store}）与外部
LLM-Memory webui 桥的访问都从这里进出：
  * 读：search()            —— D-B 三态作用域解析的唯一实现处
  * 写：ingest()            —— 摘要/对话入库
  * 浏览/删：browse_* / delete_* —— /data Memory tab 的 rows 原语
  * 桥：bridge_request()    —— 外部 webui 一跳到 gateway 收敛
  * DA 槽位：load_brief_date() —— bridge|local 分派，local 本轮只占位
将来接 B 侧 SDK 时，替换的只是本文件函数体内的转发目标；公开签名、返回
形状、namespace/作用域语义不变。

本文件自身遵守两条线：
  * 不 import src.ui / src.agents 模块级（ui 侧 import 全在函数体内，与
    job_runner 的既有风格一致），也不 import fastapi——HTTPException 映射
    属 api 层，src/memory 不沾 web 框架；
  * namespace 常量一律定义在 src/memory/config.py（policy 层），这里只
    做别名暴露，将来"内核替换"只动本文件内部。
"""
import logging
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

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
NAMESPACE_AATF: str = NAMESPACE_AATF                  # "AATF"（DA 预留；桥 chat 缺省）
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
    """统一写入口：直通 ingest.ingest_source，provider=None 时先
    resolve_provider(None)——与现调用点语义等值（chat_ingest 已是
    resolve_provider(None)，pipeline 传的是已解析值，gateway 对非 None
    值直通不二次解析）。返回 report dict 形状逐字不变
    （chunks_added/chunks_skipped/chunks_deleted/...）。
    """
    return await _ingest_source(
        path, source_type=source_type, namespace=namespace,
        provider=resolve_provider(provider) if provider is None else provider,
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
    deleted = 0
    for row in rows:
        try:
            store.delete(row.get("id", ""))
            deleted += 1
        except Exception:  # noqa: BLE001 —— 单条失败不阻断其余
            logger.warning("gateway.delete_source: 删除失败 id=%s", row.get("id"), exc_info=True)
    return deleted


def delete_namespace(namespace: str) -> int:
    """清空 namespace，取行+逐删策略同 delete_source。"""
    store = _store()
    deleted = 0
    for row in store.all_rows(namespace):
        try:
            store.delete(row.get("id", ""))
            deleted += 1
        except Exception:  # noqa: BLE001
            logger.warning("gateway.delete_namespace: 删除失败 id=%s", row.get("id"), exc_info=True)
    return deleted


# ---- 桥（外部 LLM-Memory webui 访问的唯一收敛点）----
class BridgeError(Exception):
    """一跳到外部 webui 的 transport 级失败：status_code 固定 502，detail
    逐字保留旧 _lm 文案（"LLM-Memory webui 不可达（URL）：exc. 请确认已
    运行: python scripts/webui/server.py --port 8765"）。HTTP 级失败不在
    这里抛——由 bridge_request 原样返回 (status, body)，映射属调用端点层
    的形状（api 层再转 HTTPException）。"""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# 全仓唯一读取点；llmmemory.py / brief_memory.py 的旧常量退役为本别名。
LLM_MEMORY_URL: str = os.environ.get("LLM_MEMORY_URL", "http://127.0.0.1:8765").rstrip("/")

# 与旧 llmmemory._TIMEOUT 同形状；brief_memory 有自己的 (15, read=30) 会显式传入。
_DEFAULT_BRIDGE_TIMEOUT = httpx.Timeout(15.0, read=180.0)


async def bridge_request(
    method: str, path: str, *, timeout: Optional[httpx.Timeout] = None, **kw,
) -> Tuple[int, Any]:
    """外部 webui 一跳：单发 httpx 请求，返回 (status_code, 解析后的 json
    body)；body 解析失败时退化为 {"detail": text[:300]}（旧 _lm 逐字同构）。
    连接失败等 transport 错误 raise BridgeError。本层绝不 import fastapi。"""
    try:
        async with httpx.AsyncClient(timeout=timeout or _DEFAULT_BRIDGE_TIMEOUT) as client:
            resp = await client.request(method, f"{LLM_MEMORY_URL}{path}", **kw)
    except httpx.HTTPError as exc:
        raise BridgeError(
            502,
            f"LLM-Memory webui 不可达（{LLM_MEMORY_URL}）：{exc}. "
            f"请确认已运行: python scripts/webui/server.py --port 8765",
        ) from exc
    try:
        body = resp.json()
    except ValueError:
        body = {"detail": resp.text[:300]}
    return resp.status_code, body


# ---- 桥服务面：外部 webui 各端点的具名一跳 ----
# 外部路由的 URL 与请求体在这里逐字组装——api 层（llmmemory.py）与
# service 层（brief_memory.py）都不再自己拼外部路径，只把 (status, body)
# 映射成自己需要的形状（transport 错误统一 raise BridgeError）。
# B 侧 SDK 化时，这批方法名就是 SDK 方法面的镜像，改动只落本文件。

async def brief_dates(**kw) -> Tuple[int, Any]:
    """GET /api/briefs/dates —— 日期列表及其加载状态。"""
    return await bridge_request("GET", "/api/briefs/dates", **kw)


async def brief_papers(dates: str = "", **kw) -> Tuple[int, Any]:
    """GET /api/briefs/papers?dates=... —— 指定日期的论文清单。"""
    return await bridge_request(
        "GET", "/api/briefs/papers", params={"dates": dates}, **kw)


async def brief_load(dates: List[str], **kw) -> Tuple[int, Any]:
    """POST /api/briefs/load {dates:[...]} —— 请求外部服务加载简报。
    （job_runner 驱动的逐日加载走 brief_memory.load_date，经本函数发这一跳；
    路由 /load 的多日期一次请求也走这里。）"""
    return await bridge_request("POST", "/api/briefs/load",
                                json={"dates": dates}, **kw)


async def brief_load_progress(job_id: str, **kw) -> Tuple[int, Any]:
    """GET /api/briefs/load/progress/{job_id} —— 外部加载 job 的进度。"""
    return await bridge_request("GET", f"/api/briefs/load/progress/{job_id}", **kw)


async def brief_chat(message: str, history: List[dict],
                     namespace: List[str], **kw) -> Tuple[int, Any]:
    """POST /api/chat {message, history, namespace} —— 外部对话 job 注册。"""
    return await bridge_request("POST", "/api/chat", json={
        "message": message, "history": history, "namespace": namespace,
    }, **kw)


async def brief_chat_progress(job_id: str, **kw) -> Tuple[int, Any]:
    """GET /api/chat/progress/{job_id} —— 外部对话 job 的进度。"""
    return await bridge_request("GET", f"/api/chat/progress/{job_id}", **kw)


async def brief_chat_stop(job_id: str, **kw) -> Tuple[int, Any]:
    """POST /api/chat/stop/{job_id} —— flag 式取消：外部 job 在下一次检索
    检查点自行收尾。A 侧只透传，不发明第二套取消语义。"""
    return await bridge_request("POST", f"/api/chat/stop/{job_id}", **kw)


async def deepread_download(url: str, **kw) -> Tuple[int, Any]:
    """POST /api/deepread/download {url} —— 外部侧把 PDF 写进 data/pdf/。"""
    return await bridge_request("POST", "/api/deepread/download",
                                json={"url": url}, **kw)


# ---- DA：brief 加载驱动槽位 ----
BRIEF_DRIVER_ENV = "MEMORY_BRIEF_DRIVER"  # "bridge"（缺省）| "local"


async def load_brief_date(date: str) -> Dict[str, Any]:
    """DA 分派：env MEMORY_BRIEF_DRIVER。
    bridge → 懒 import brief_memory 模块，属性调用 brief_memory.load_date(date)。
      ★必须是 brief_memory.load_date(...) 属性访问形式，不得写成
      from-import 绑定函数对象——tests/test_brief_load_jobs.py 靠 patch
      模块属性驱动这条链路，形状不能动。
    local → _local_brief_load(date)。
    返回契约恒为 {"loaded","skipped","errors"}（job_runner 的判定只认这三键）。
    """
    driver = (os.environ.get(BRIEF_DRIVER_ENV) or "bridge").strip().lower()
    if driver == "local":
        return await _local_brief_load(date)
    from src.ui.backend.services import brief_memory  # 函数级，防 ui→memory→ui 环
    return await brief_memory.load_date(date)


async def _local_brief_load(date: str) -> Dict[str, Any]:
    """预留实现位（DA）：本轮不执行。将来写 A 自库 data/memory_db/ 的
    NAMESPACE_AATF——DA 已裁决落点为 A 自库（覆盖了 blueprint Phase 3 的
    "store 落点=B 目录"条目）。函数体只留 raise；保留签名与 docstring 作为
    接口位，SDK 内核替换落地时在此接本地 ingest。"""
    raise NotImplementedError(
        "local brief driver（写 A 自库 namespace AATF）随 B SDK 内核替换落地，"
        "本轮仅预留接口位；现驱动走 bridge。"
    )


# ---- 服务面工厂 ----
class MemoryService:
    """把上面的模块级函数收拢成一层的实例 façade。

    存在理由：B 侧 SDK 化时替换的是 gateway 内部实现，消费方拿这个工厂
    返回的对象即可，调用形态不用逐处改 import；与模块级函数逐一对应，
    不叠加任何第二语义。"""

    def search(self, query: str, **kw) -> Any:
        return search(query, **kw)

    def ingest(self, path: str, source_type: str, namespace: str, **kw) -> Any:
        return ingest(path, source_type=source_type, namespace=namespace, **kw)

    def browse_all_rows(self, namespace: Union[str, List[str]] = "*") -> List[Dict[str, Any]]:
        return browse_all_rows(namespace)

    def browse_rows_for_source(self, namespace: Union[str, List[str]], source_id: str) -> List[Dict[str, Any]]:
        return browse_rows_for_source(namespace, source_id)

    def delete_item(self, memory_id: str) -> None:
        return delete_item(memory_id)

    def delete_source(self, namespace: str, source_id: str) -> int:
        return delete_source(namespace, source_id)

    def delete_namespace(self, namespace: str) -> int:
        return delete_namespace(namespace)

    def load_brief_date(self, date: str) -> Any:
        return load_brief_date(date)

    def bridge_request(self, method: str, path: str, **kw) -> Any:
        return bridge_request(method, path, **kw)

    # 桥服务面具名方法：与模块级函数逐一对应，不叠加第二语义。
    def brief_dates(self, **kw) -> Any:
        return brief_dates(**kw)

    def brief_papers(self, dates: str = "", **kw) -> Any:
        return brief_papers(dates, **kw)

    def brief_load(self, dates, **kw) -> Any:
        return brief_load(dates, **kw)

    def brief_load_progress(self, job_id: str, **kw) -> Any:
        return brief_load_progress(job_id, **kw)

    def brief_chat(self, message: str, history, namespace, **kw) -> Any:
        return brief_chat(message, history, namespace, **kw)

    def brief_chat_progress(self, job_id: str, **kw) -> Any:
        return brief_chat_progress(job_id, **kw)

    def brief_chat_stop(self, job_id: str, **kw) -> Any:
        return brief_chat_stop(job_id, **kw)

    def deepread_download(self, url: str, **kw) -> Any:
        return deepread_download(url, **kw)


_MEMORY_SERVICE: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    """缺省服务实例（无状态 façade，单例足够；需要注入别的实现时
    直接构造 MemoryService() 或替换 gateway 内部即可）。"""
    global _MEMORY_SERVICE
    if _MEMORY_SERVICE is None:
        _MEMORY_SERVICE = MemoryService()
    return _MEMORY_SERVICE
