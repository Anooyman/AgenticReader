"""Memory 浏览/搜索/删除 REST API——供 /data 页面的 Memory tab 查看
src.memory 向量库的内容。改自 ai-research-pipeline 的 webapp/api/memory.py。

原实现的跨 venv subprocess 调用（memory_browse.py 的 fetch_* 函数）在
合并进 AgenticReader 后已经改为同进程直接调用（见 services/memory_browse.py
的说明），这里的路由/错误处理逻辑基本不变。
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from src.ui.backend.services import memory_browse

logger = logging.getLogger(__name__)

router = APIRouter()


async def _run_read(fn, *args):
    """读端点的失败形状，与下面 `_run_delete` 同一条规矩。

    分得清"这个库里没有行"和"这个库今天读不出来"是本 API 最要紧的一件事：
    空结果可以 200 交差，那本来就是状态查询的诚实答案；**故障**不行——
    故障必须让 body 里带一句话，否则前端显示"暂无记忆"就等于替一次真实故障
    撒谎。`MEMORY_STORE_MODE=upstream` 这一档现在会让路由直接抛错，那种错
    在这里必须看得见，不能落回一个空列表。
    """
    try:
        return await fn(*args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("记忆读取出错：%s: %s", type(exc).__name__, exc)
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc


@router.get("/overview")
async def get_overview():
    return await _run_read(memory_browse.fetch_overview)


@router.get("/namespace/{namespace}")
async def get_namespace(namespace: str):
    return await _run_read(memory_browse.fetch_namespace, namespace)


async def _run_delete(fn, *args):
    """删除类操作的失败形状：把原因带出来，而不是让它变成一句"Internal Server Error"。

    分两类是因为它们**本来就不是一回事**：`ValueError` 是调用方给错了 scope
    （空 namespace / `*`），那是 400，写日志也不需要堆栈；其余的是"上游或库
    自己出问题了"，那是 5xx，而且理由必须进 body——UI 上一句"删除失败"和一句
    "上游 delete_where 没成：namespace 未注册"之差，就是用户要不要再点一遍的差别。
    """
    try:
        return await fn(*args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("记忆删除失败：%s: %s", type(exc).__name__, exc)
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc


@router.delete("/item/{memory_id}")
async def delete_item(memory_id: str):
    return await _run_delete(memory_browse.delete_memory, memory_id)


@router.delete("/namespace/{namespace}/source/{source_id}")
async def delete_source(namespace: str, source_id: str):
    """删掉一个来源（一篇论文/一段对话）在该 namespace 下的全部记忆行——
    对应 UI 上"删除整组"按钮，一次删掉一张 group 卡片的所有 chunk。"""
    return await _run_delete(memory_browse.delete_source, namespace, source_id)


@router.delete("/namespace/{namespace}")
async def delete_namespace(namespace: str):
    """清空一个 namespace 下的全部记忆。"""
    return await _run_delete(memory_browse.delete_namespace, namespace)


@router.post("/search")
async def post_search(body: dict):
    """手动执行一次检索测试——复用 agentic_search，验证效果。"""
    query = (body or {}).get("query")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    namespace = (body or {}).get("namespace")

    from src.memory import gateway

    from src.config.settings import resolve_provider
    # 检索测试口保持"缺省=全库"的现行为：不传 namespace 时显式用 "*"
    # （gateway 层 "*" 与 None 在底层 vector_store._where 都不生成过滤）。
    result = await gateway.search(query,
                                  namespaces=[namespace] if namespace else "*",
                                  provider=resolve_provider(None))
    return result


# ---- 上游 LLM-Memory 只读面（SDK 为主 + 可选 MCP 决策面，均经 gateway 门面）----
# 路由只做输入校验与失败→状态码的映射；作用域规则住在 gateway（缺省
# 不传作用域=全局搜，显式 str/列表/"*" 才收窄），这里不另立规则，也不
# import 上游细节——src/memory 不沾 fastapi，映射归本层。
# 两个 POST 的 body 故意不走 FastAPI 的类型校验：dict 注解会让框架在
# 路由函数之前就 422 掉数组类畸形 body——虽然那也不是 500，但"是不是
# 我们的输入校验在把关"就成了框架的事。这里收 Request 后自己
# .json()，非法 JSON / 非对象 body 统一 400 归我们，语义可预期。
# （本文件早先的 /search 端点保持原 dict 签名不动。）

# 只读决策面白名单：why/pack 两个读工具。API 层先挡一道，
# src/memory/upstream.py 还有第二道同名单（纵深不是重复）。
_DECISION_TOOLS = ("memory_why", "memory_pack")


@router.get("/upstream")
async def get_upstream(namespace: Optional[str] = None):
    """上游状态视图：{available, namespaces:[{name,rows}], total, version?,
    decision:{enabled, available, note}, note?|error?}。
    这是一个**状态查询**，不是操作——未配置/不可达也如实返回 200 +
    available:false，前端据此渲染灰徽章，不该拿 4xx/5xx 谎报"接口坏了"。
    decision 位只报开关的诚实答案：未启用时是纯 gate 答案，不会顺手起
    子进程探测（探测发生在 POST /upstream/decision 或显式打开之后）。
    """
    from src.memory import gateway  # 函数级：api 层不往模块级拖记忆内核
    status = await gateway.upstream_status(namespace)
    status["decision"] = await gateway.upstream_decision_status()
    # 配置自述：库在哪个目录、几维、用什么模型、认哪些 source_type。这些
    # 一律由上游回答，AR 只搬运不解释——缺这个面就写一句"读不到"，绝不拿
    # AR 自己的常量凑一个像样的答案（凑出来的那份迟早会跟上游说的不一样）。
    if status.get("available"):
        caps = await gateway.upstream_capabilities()
        if caps.get("available"):
            status["config"] = {k: v for k, v in caps.items()
                                if k not in ("available", "read_only")}
        else:
            status["config_note"] = caps.get("note") or caps.get("error") or "上游未提供配置自述"
    return status


def _bad_body(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


async def _json_object_body(request: Request) -> dict:
    """把请求体收成 dict：空体按 {}；非法 JSON / 数组 / 标量都算调用方
    的输入错误，统一 400——绝不让 .get 撞上 AttributeError→500。"""
    raw = await request.body()
    if not raw:
        return {}
    try:
        body = json.loads(raw)
    except ValueError:
        raise _bad_body("body must be valid JSON")
    if not isinstance(body, dict):
        raise _bad_body("body must be a JSON object")
    return body


@router.post("/upstream/search")
async def post_upstream_search(request: Request):
    """对上游做一次只读检索：body {query, namespace?}。
    query 非空 str；namespace 只接受 str / list[str] / 省略——缺省**不传
    作用域**（全局搜，返回里 scoped=False），显式列表或 "*" 才收窄，
    规则全在 gateway。结果形状为门面原样（available + scoped + 上游
    result 摊平，门面位压后防上游撞键）。失败折叠在 body 里，本层映射：
    运行时错误→502（上游回了坏东西），未配置→503（服务在但门关着）。
    """
    body = await _json_object_body(request)
    query = body.get("query")
    if not isinstance(query, str) or not query.strip():
        raise _bad_body("query is required (non-empty string)")
    namespace = body.get("namespace")
    if namespace is not None and not isinstance(namespace, (str, list)):
        raise _bad_body("namespace must be a string or list of strings")

    from src.memory import gateway

    result = await gateway.upstream_search(query.strip(), namespace)
    if not result.get("available"):
        status = 502 if "error" in result else 503
        raise HTTPException(
            status_code=status,
            detail=result.get("error") or result.get("note") or "上游 LLM-Memory 不可用",
        )
    return result


@router.post("/upstream/decision")
async def post_upstream_decision(request: Request):
    """MCP 决策面一跳直通：body {tool, args?}。
    tool 限白名单 _DECISION_TOOLS——不是白名单的工具（含一切写工具）
    直接 403，压根不碰内核；白名单内但决策面未启用→503（诚实的 gate
    答案，不装成 502"上游坏了"）；启用后运行时错误→502。
    """
    body = await _json_object_body(request)
    tool = body.get("tool")
    if not isinstance(tool, str) or tool not in _DECISION_TOOLS:
        raise HTTPException(
            status_code=403,
            detail=f"tool {tool!r} not in read-only decision whitelist {list(_DECISION_TOOLS)}",
        )
    args = body.get("args", {})
    if not isinstance(args, dict):
        raise _bad_body("args must be a JSON object")

    from src.memory import gateway

    result = await gateway.upstream_decision_call(tool, args)
    if not result.get("available"):
        raise HTTPException(
            status_code=502 if "error" in result else 503,
            detail=result.get("error") or result.get("note") or "MCP 决策面不可用",
        )
    return result
