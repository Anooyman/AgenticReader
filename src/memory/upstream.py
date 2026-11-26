"""外部 LLM-Memory 的访问层——gateway 上游门面段的实现体。

两条通道，均按裁决落地：
  * SDK 主通道（缺省即开）：env LLM_MEMORY_REPO 指向上游 checkout，把
    <repo>/src 注入 sys.path 后 `from llm_memoryd.api import MemoryClient`。
    跨 venv 实测：AR 的 3.12 venv 直接 import 成功、依赖全有，无需装包。
    构造期**不传 namespace/cwd**——构造期 ns 是"显式逃生阀"，不传才由
    cwd 派生出 slug-<digest> 之类的名字，那是上游给"那台机器上的仓库"
    起的，不是我们要的缺省。**缺省作用域=全局搜**（不给上游传任何作用
    域，它自己报 scoped=False 并明说"跨 store"）；只有调用方显式给
    namespace/namespaces 才收窄。"默认拿自库白名单去搜上游"是错的——
    上游实测 ns 全是派生名，白名单名喂过去必然 0 命中还谎报 scoped=True。
  * MCP 决策面（可选，默认关）：env LLM_MEMORY_MCP_ENABLED=1 且 repo 有效
    时，stdio 子进程起 `python -m llm_memoryd.mcp --tools memory_why,
    memory_pack`。**子进程的 command/args/env 单源构建自
    settings.MCP_CONFIG["llm_memory"]**，本文件不拼第二份；env 以
    os.environ 为底再叠 config 的 env（mcp 库的默认环境合并会丢掉
    OPENAI_API_KEY/EMBEDDING_*，所以显式并表）。MEMORY_DATA_DIR 与上游
    install.py 的挂载块同形——钉一个"父 env 有就照取、没有就钉机根派生
    值"的等价形状（脱离子进程没 shell 可继承），note 里显示解析到的
    store 根。

纪律（写死在这里，别回头补）：
  * 读面 + 一条写路。"全段只读"的旧纪律因收敛裁决**有意反转**：ingest 也走
    SDK 面（见 SDK 写面段）。remember 仍不碰；MCP 面继续只限 why/pack 两件
    决策工具，写工具一个都不在面上（纵深：API 侧另有一道同名单）。
  * 不 import src.ui / src.agents / fastapi；上游与 mcp 的 import 全部
    函数级惰性——本模块在任何 env/安装状态下都必须可 import。
  * 上游 SDK 全同步，公开函数一律 asyncio.to_thread 包裹 + 宽 except 折叠
    成 {"available": False, "error"|"note": ...}，绝不让异常裸穿到 UI。
    **body 只装异常类型名 + 一句可读 note，完整异常文本（可能带主机绝对
    路径）只进 logger**——对齐上游 mcp.py 的 _client_error_message 口径：
    ValueError 是写给调用方的话可透传，其余一律"internal error: <类型>"。
    写路同构，但"要不要回落本地"不在本层——那是 gateway 的 policy。
  * search 接取消：上游 agentic_search 的 cancel_check 在每轮开头轮询
    （agent_search.py 实测：置位即强制收尾返回 best-effort，status=
    "cancelled"，不抛异常）。外层 wait_for 超时即置位这个 flag，让线程
    在轮次边界自行收尾，消灭僵尸线程。deadline 与 cancel 双保险。
    写路**没有**这个通道：ingest 签名里根本没有 cancel_check，超时只能
    放弃等待，线程照旧跑完它自己的管线。
  * 寻址不写死任何默认绝对路径（教训同 migrate_aatf）。
"""
import asyncio
import logging
import os
import sys
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# SDK 调用期护栏：soft deadline 走上游自己的 deadline_s（agent 循环在轮次
# 边界检查），硬 cap 用 wait_for 兜底并联动 cancel——超时不是"等死了"，
# 而是置位取消标志、线程自己收尾。
#
# 2026-11-26 调参，根因是一条被当代码 bug 报了半天的"查不到"：上游
# agent_search 缺省 6 轮、实测 133s 跑完 103 条命中，而 AR 的硬 cap 是
# 90s——每次都在**注定能成功**的检索上到点，然后按读路回落本地旧库
# （AATF 在那边是 0 行），chat 于是永远答"没找到"。三根旋钮各管一段：
#   * max_rounds：掐上游的腿。缺省 3 轮（实测 ~22s/轮 ≈ 66s，留给硬 cap
#     的余量翻倍）；MEMORY_SEARCH_MAX_ROUNDS 可调 1-8。
#   * deadline_s：软门，让还在跑的循环在轮次边界自己收，60s。
#   * hard cap：兜底等待 150s——仍在 retrieval 的 600s 预算与 chat 900s
#     墙钟之内，但它只是最后一道，正常路径靠前两根就收敛了。
_SEARCH_DEADLINE_S = 60.0
_SEARCH_HARD_CAP_S = 150.0
_SEARCH_MAX_ROUNDS_DEFAULT = 3


def _search_env_float(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, "") or default)
    except ValueError:
        logger.warning("%s 不是数字，用默认值 %s", name, default)
        return default
    return v if v > 0 else default


def _search_deadline_s() -> float:
    return _search_env_float("MEMORY_SEARCH_DEADLINE_S", _SEARCH_DEADLINE_S)


def _search_hard_cap_s() -> float:
    return _search_env_float("MEMORY_SEARCH_HARD_CAP_S", _SEARCH_HARD_CAP_S)


def _search_max_rounds() -> int:
    """上游检索允许烧几轮 agentic 循环。1-8 钳位，非法值回默认 3。"""
    raw = os.environ.get("MEMORY_SEARCH_MAX_ROUNDS", "").strip()
    if not raw:
        return _SEARCH_MAX_ROUNDS_DEFAULT
    try:
        return max(1, min(8, int(raw)))
    except ValueError:
        logger.warning("MEMORY_SEARCH_MAX_ROUNDS=%r 不是整数，用默认 %d",
                       raw, _SEARCH_MAX_ROUNDS_DEFAULT)
        return _SEARCH_MAX_ROUNDS_DEFAULT


_MCP_TIMEOUT_S = 15.0

# MCP 决策面只读白名单——写工具（remember/ingest/chat）不在这里，也不该
# 出现在任何地方（API 侧另有一道同名单，纵深防御）。
DECISION_TOOLS = ("memory_why", "memory_pack")

_NOTE_NO_REPO = ("未配置上游 LLM-Memory：环境变量 LLM_MEMORY_REPO 未设置"
                 "或指向的目录无效（它是唯一寻址点）。上游只读视图处于关闭"
                 "状态，本地记忆功能不受影响。")

# SDK client 惰性单例：只有构造成功才缓存——失败不持久化锁死（env 后来
# 补上了就该活）；锁防并发首建双构造，shutdown() 供应用退出时清缓存。
_client: Optional[Any] = None
_client_lock = threading.Lock()
_path_lock = threading.Lock()


# ------------------------------------------------------------------ 寻址/构造

def _repo_src() -> Optional[str]:
    """env LLM_MEMORY_REPO（strip）→ <repo>/src 绝对路径；无效返回 None。"""
    from src.config.settings import get_llm_memory_repo  # 函数级，settings 不往模块级拖
    repo = get_llm_memory_repo()
    if not repo:
        return None
    src = os.path.join(repo, "src")
    return src if os.path.isdir(src) else None


def _ensure_src_on_path(src: str) -> None:
    """把 <repo>/src 幂等地插进 sys.path（一次，带锁防并发重复注入）。"""
    with _path_lock:
        if src not in sys.path:
            sys.path.insert(0, src)


def _build_client() -> Optional[Any]:
    """构造并缓存 MemoryClient。未配置返回 None；构造/import 失败**向上
    raise**，由 _client_for 折叠——不吞异常地当 None 会丢掉"为什么失败"。
    ★不传 namespace=/cwd=：作用域全在调用期显式传，构造期派生名不是缺省。
    """
    global _client
    with _client_lock:
        if _client is not None:
            return _client
        src = _repo_src()
        if not src:
            return None
        _ensure_src_on_path(src)
        from llm_memoryd.api import MemoryClient  # 函数级惰性，失败由外层折叠
        _client = MemoryClient()
        return _client


def shutdown() -> None:
    """清 client 缓存——app.py lifespan 关闭时调，别把上游 SDK 对象带进
    解释器退出。sys.path 注入保持不动：幂等、无害，撤回它反而制造
    "同进程两阶段 import 不同视图"的暗坑。"""
    global _client
    with _client_lock:
        _client = None


# ------------------------------------------------------------------ 折叠口径

def _fail_note(exc: BaseException) -> str:
    """进 body 的一句话 note（对齐上游 mcp.py _client_error_message 的
    取舍）：ValueError 是写给调用方的话可透传（截 200 防它自己带长路径）；
    其余只报类型——OSError 之类 routinely 携带主机绝对路径。"""
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return f"internal error: {type(exc).__name__}（详情见服务端日志）"


def _fail(context: str, exc: BaseException) -> Dict[str, Any]:
    """宽 except 折叠点：logger 留完整文本，body 只装类型名 + 可读 note。"""
    logger.warning("上游 LLM-Memory %s 失败：%s: %s",
                   context, type(exc).__name__, exc)
    return {"available": False, "error": type(exc).__name__,
            "note": _fail_note(exc)}


def _store_root_note() -> str:
    """"按什么规则解析到了哪个 store 根"（构造失败时的诊断信息）。
    函数级 import 上游 common.paths——它 stdlib-only，注入成功就能算；
    算不动就明说算不出，不猜。"""
    try:
        src = _repo_src()
        if not src:
            return "store 根算不出：LLM_MEMORY_REPO 未配置"
        _ensure_src_on_path(src)
        # 先问那张嘴自己：能问到就用**上游报出来的**路径和它的来路，
        # 自己拿 paths 现算是最后一条退路——理由和这整件事一样：规则在上游手里，
        # 我在诊断串里重算一遍它的规则，规则一变这里就开始替上游编答案。
        if _client is not None:
            try:
                cap = _client.capabilities()
                if cap.get("store_dir"):
                    return (f"store 根={cap['store_dir']}"
                            f"（上游自报，source={cap.get('store_source', 'unknown')}）")
            except Exception:  # noqa: BLE001——自报失败就退回下面那条现算
                pass
        from llm_memoryd.common import paths  # noqa: PLC0415——纯诊断，失败可弃
        return f"store 根={paths.store_dir()}（未经 client 自报，按上游 paths 现算）"
    except Exception as exc:  # noqa: BLE001
        return f"store 根算不出（{type(exc).__name__}）"


def _client_fail(exc: BaseException) -> Dict[str, Any]:
    """client 构造期失败的折叠形状：note 里追加 store 根解析，运维一眼看出
    是"没配 repo"还是"配了但库打不开"。"""
    folded = _fail("client 构造", exc)
    folded["note"] = f"{folded['note']}；{_store_root_note()}"
    return folded


def _unavailable() -> Dict[str, Any]:
    return {"available": False, "note": _NOTE_NO_REPO}


async def _client_for() -> tuple:
    """(client, failure)：
    * (client, None)   —— 可用；
    * (None, None)     —— 未配置：调用方给 unavailable note；
    * (None, dict)     —— 构造失败，已折叠（含 store 根解析）。
    """
    try:
        return await asyncio.to_thread(_build_client), None
    except Exception as exc:  # noqa: BLE001
        return None, _client_fail(exc)


# ------------------------------------------------------------------ SDK 只读面

async def upstream_available() -> bool:
    """上游是否可达（repo 有效 + MemoryClient 构造成功）。"""
    client, _failure = await _client_for()
    return client is not None


def upstream_available_sync() -> bool:
    """`upstream_available()` 的同步版本，判定规则完全同一条，只是不碰事件
    循环——gateway 那三个 delete_* 原语是 sync 函数，选路时没法 await。"""
    client, _failure = _client_sync()
    return client is not None


async def upstream_status(namespace: Optional[str] = None) -> Dict[str, Any]:
    """上游 store 视图。单 ns 过滤且 0 行时，**必须**与"空库"分得开——
    做法：再拿 store 级视图交叉一次（先实读上游 common/stats.py：
    namespace_stats 按过滤取行，不存在的 ns 与空库的回车形状都是
    total=0/namespaces={}，只能靠 ns 在不在 store 的 ns 清单里判别）。
    """
    client, failure = await _client_for()
    if failure is not None:
        return failure
    if client is None:
        return _unavailable()
    try:
        stats = await asyncio.to_thread(client.status, namespace)
        rows_map = stats.get("namespaces") or {}
        namespaces = [{"name": str(n), "rows": int(c or 0)}
                      for n, c in sorted(rows_map.items(), key=lambda kv: str(kv[0]))]
        version = ""
        mod = sys.modules.get("llm_memoryd")
        if mod is not None:
            version = str(getattr(mod, "__version__", "") or "")
        out: Dict[str, Any] = {"available": True, "namespaces": namespaces,
                               "total": int(stats.get("total") or 0),
                               "empty": bool(stats.get("empty")),
                               "store_dir": stats.get("store_dir"),
                               "version": version or None,
                               "read_only": True}
        # "无此 ns" vs "空库"的可判别位：交叉一次 store 级视图。
        # ns_present 只能由 store 级清单回答：`namespace in seen`。**不能**先
        # 无条件写 False 再等着修饰——"ns 存在但恰好 0 行"是最常见的一种空，
        # 拿 False 说它"清单里没有"就是撒谎，note 也会把排查往错方向带。
        if namespace and out["total"] == 0:
            try:
                store = await asyncio.to_thread(client.status)
                seen = {str(n) for n in (store.get("namespaces") or {})}
                present = namespace in seen
                out["ns_present"] = present
                if int(store.get("total") or 0) == 0:
                    out["note"] = ("store 为空（0 行）——上游库未接入/未入库，"
                                   "非该 ns 独有"
                                   + ("（ns 清单里有它，只是没行）" if present else ""))
                elif present:
                    out["note"] = (f"该 ns 在此 store 中存在，但当前 0 行："
                                   f"store 共 {store.get('total')} 行"
                                   f"（可选：{sorted(seen) or '空'}）")
                else:
                    out["note"] = (f"该 ns 在此 store 中无行：store 共 "
                                   f"{store.get('total')} 行、ns 清单里没有 "
                                   f"{namespace!r}（可选：{sorted(seen) or '空'}）")
            except Exception as exc:  # noqa: BLE001 —— 交叉判定失败不影响主结果
                logger.warning("上游 status 的 store 级交叉判定失败（折叠）：%s: %s",
                               type(exc).__name__, exc)
                out["ns_present"] = None  # 诚实说"判不出来"，不假装有结论
        return out
    except Exception as exc:  # noqa: BLE001
        return _fail("status", exc)


async def upstream_capabilities() -> Dict[str, Any]:
    """上游的**自述**：这个库在哪个目录、多少维、embedding/chat/insert 各用
    什么模型、认哪些 source_type、开了哪些 MCP 工具、版本号多少。

    这是"记忆配置不归 AR 管"这句话唯一能被程序化引用的地方，所以这里的纪律
    比 status/search 还严：**不做任何本地加工**，也不拿 AR 自己的常量去补一个
    "看起来一样"的默认值——上游没这个面就按 `_fail` 折叠，缺哪个键就是缺哪个。
    上游那份白名单刻意不含 API key 之类的东西，但我们这边同样只当它是文本，
    原样转发，别在这里替前端做"哪些看起来敏感"的判断。
    """
    client, failure = await _client_for()
    if failure is not None:
        return failure
    if client is None:
        return _unavailable()
    try:
        _require_method(client, "capabilities")
        payload = await asyncio.to_thread(client.capabilities)
        if not isinstance(payload, dict):
            raise TypeError(f"capabilities 返回了 {type(payload).__name__}")
        return {"available": True, **payload, "read_only": True}
    except Exception as exc:  # noqa: BLE001 —— 折叠成 {available:false,...}，不外抛
        return _fail("capabilities", exc)


async def upstream_namespaces() -> List[Dict[str, Any]]:
    """上游 namespace 列表 [{name, rows}]；不可用/失败一律空列表——
    这个入口的形状是"列表"，折叠语义走 status/search，这里不另造形状。"""
    client, failure = await _client_for()
    if failure is not None:
        logger.warning("上游 namespaces 折叠进空列表：%s", failure.get("note"))
        return []
    if client is None:
        return []
    try:
        entries = await asyncio.to_thread(client.namespaces)
        out = []
        for entry in entries or []:
            name = entry.get("name") if isinstance(entry, dict) else None
            if name is None:
                continue
            rows = entry.get("row_count")
            out.append({"name": str(name), "rows": int(rows or 0)})
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("上游 LLM-Memory namespaces() 失败（折叠为空列表）：%s: %s",
                       type(exc).__name__, exc)
        return []


async def upstream_search(query: str, *, namespace: Optional[str] = None,
                          namespaces: Optional[List[str]] = None) -> Dict[str, Any]:
    """上游 agentic 检索直通。作用域由调用方（gateway 的 D-B 收敛）定：
      * 两者皆空 → **不传作用域**，上游全局搜，scoped=False；
      * namespace="x" / namespaces=[...] → 显式收窄，scoped=True。
    返回形状：{**上游 result, "available": True, "scoped": ...}——门面位
    放在**最后**，上游 result 里哪怕撞出同名键也压不倒 available/scoped。
    取消：外层 wait_for 超时 → 置 cancel flag → 上游线程在轮次边界自行
    收尾（agent_search.py 实测 cancel_check 每轮开头轮询，置位即
    best-effort 返回不抛异常），消灭僵尸线程。
    """
    client, failure = await _client_for()
    if failure is not None:
        return failure
    if client is None:
        return _unavailable()
    cancel = threading.Event()

    def _run():
        return client.search(query, namespace=namespace, namespaces=namespaces,
                             deadline_s=_search_deadline_s(),
                             max_iterations=_search_max_rounds(),
                             cancel_check=cancel.is_set)

    try:
        result = await asyncio.wait_for(asyncio.to_thread(_run),
                                        timeout=_search_hard_cap_s())
    except asyncio.TimeoutError:
        # 硬 cap 到点：置位让线程下一轮自己收尾，这边走超时折叠（不是
        # _fail——没有异常可打，是"我们到点了"的语义）。
        cancel.set()
        logger.warning("上游 search 超过 %ss 硬上限，已置 cancel flag 等线程收尾",
                       _search_hard_cap_s())
        return {"available": False, "error": "TimeoutError",
                "note": (f"上游 search 超 {int(_search_hard_cap_s())}s 未回，"
                         f"已置取消标志（soft deadline {int(_search_deadline_s())}s，"
                         f"轮数上限 {_search_max_rounds()}），"
                         f"线程将在轮次边界自行收尾")}
    except Exception as exc:  # noqa: BLE001
        return _fail("search", exc)
    if not isinstance(result, dict):
        result = {"result": result}
    scoped = bool(namespace) or bool(namespaces)
    return {**result, "available": True, "scoped": scoped}


# ------------------------------------------------------------- SDK 写面（收敛）

# 写路硬 cap。上游 ingest 是完整 agentic 管线（解析→逐块抽取→摘要），单文件
# 分钟级是常态，所以这里的数字比 search 宽一个量级；调用方（chat_ingest 的
# wait_for、job_runner 的任务超时）通常比我们先到期，这里的 cap 只兜"上游
# 根本不该再等下去"的漏网情况。
_INGEST_HARD_CAP_S = 600.0

def _ingest_accepts_source_id(client: Any) -> bool:
    """这个 client 的 ingest 签名收不收 source_id——**按实例**记，不落全局。

    原先是一个模块级 `_ingest_accepts_source_id` 全局缓存，那是个错：缓存的
    key 应该是"哪一个 client"，不是"这个进程里曾经有过任何一个 client"。
    实测这条会在两种情况下说谎：同一进程里换过 client（测试夹具在两个路由
    阶段之间换假 SDK、运维把 repo 指到另一个 checkout），以及 shutdown 之后
    重建。误判的结局是**静默的**：明明能把 id 递下去却不递，行里的 id 交给
    adapter 派生，跨系统按 id 联查看到的和递下去的不是一回事。
    """
    cached = getattr(client, "_ar_accepts_source_id", None)
    if cached is not None:
        return bool(cached)
    verdict = False
    try:
        import inspect  # 标准库：只探签名，不碰任何运行时行为
        verdict = "source_id" in inspect.signature(client.ingest).parameters
    except (TypeError, ValueError):
        verdict = False
    try:
        client._ar_accepts_source_id = verdict
    except Exception:  # noqa: BLE001 —— 挂不上就每探一次，不拿这个当功能开关
        pass
    if not verdict:
        logger.info("这个上游 build 的 ingest 不接 source_id 参数：行里的 id 由上游 "
                    "adapter 按 path 派生，我们递下去的 id 只对得上有透传的 build")
    return verdict


def _call_ingest(client: Any, path: str, source_type: str, namespace: Optional[str],
                 source_id: Optional[str]) -> Any:
    """同步调 client.ingest（在 to_thread 里跑）。

    source_id 透传是"上游有没有这个能力"的问题，不是"我们要不要递"的问题：
    签名里有就递（补丁打过之后本来就该递，id 是我们的地址），没有就不递
    （这种 build 里 id 由 adapter 按 path 自己派生）。探测按实例走，见
    `_ingest_accepts_source_id`——不递的这条只在日志里留一次 info，真正的
    校验在结果侧：`upstream_ingest` 拿 report 里 echo 回来的 id 跟我们递的
    比，对不上才 warning。
    """
    if source_id and _ingest_accepts_source_id(client):
        return client.ingest(path, source_type, namespace=namespace,
                             source_id=source_id)
    return client.ingest(path, source_type, namespace=namespace)



async def upstream_ingest(path: str, source_type: str, namespace: str,
                          source_id: Optional[str] = None) -> Dict[str, Any]:
    """上游 ingest 直通——写路也走本层，"全段只读"的旧纪律按收敛裁决有意反转。

    三条写死的口径：
      * **幂等整个交给上游**自带的 hash-dedup：AR 侧不再算 chunk-hash，也不做
        任何本地补算。"重复递同一文件应返回 0 新增"是要被测试钉死的上游契约
        （不是本层能自证的承诺），这里只如实转达上游报的计数。
      * 失败折叠形状与只读路同构：{"available": False, "error", "note"}，不
        raise、不上浮到 UI。**要不要回落本地属 gateway 的 policy**，本层只管
        "写上游成了没有"，绝不偷偷再写一份本地（没有双写这回事）。
      * 上游 ingest 没有 cancel_check 这个参数（search 才有），所以写路只有
        等待侧硬 cap：wait_for 到点我们只能放弃等待，后台线程仍会把剩下的
        管线跑完——这条不是取消通道，别当它用。
    返回形状 {**result, "available": True}：门面位放最后，上游 result 里撞出
    同名键也压不倒 available。
    """
    client, failure = await _client_for()
    if failure is not None:
        return failure
    if client is None:
        return _unavailable()
    # namespace 空值先在这儿挡掉：上游拿不到显式 ns 会退到"按 path 派生"的
    # slug-<digest>，那是一次**静默**写到别的 ns 里——比失败更难查。AR 这边
    # 三个名字都是调用点显式给的，永远不该走到那条派生路。
    if not (namespace or "").strip():
        return {"available": False, "error": "ValueError",
                "note": "namespace 为空：上游会退化成按 path 派生 slug 名，"
                        "这是静默写错库而不是失败，已拒绝"}
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_call_ingest, client, str(path), str(source_type),
                              str(namespace) if namespace else None, source_id),
            timeout=_INGEST_HARD_CAP_S)
    except asyncio.TimeoutError:
        logger.warning("上游 ingest 超过 %ss 硬上限放弃等待（写路无 cancel 通道，"
                       "后台线程仍在跑完自己的管线）：%s", _INGEST_HARD_CAP_S, path)
        return {"available": False, "error": "TimeoutError",
                "note": (f"上游 ingest 超 {int(_INGEST_HARD_CAP_S)}s 未回——写路没有"
                         f"取消通道，已停止等待但上游侧可能仍在写，重试前先确认"
                         f"上游有没有落行")}
    except Exception as exc:  # noqa: BLE001
        folded = _fail("ingest", exc)
        # 构造期已知的诊断信息：为什么这单文件写不进去（too large / blocked /
        # unsupported source_type 都是 ValueError 原文可透传），补一条"是哪个
        # 文件"的可定位线索，路径本身进 note 是安全的（我们自己的路径，不是
        # 远端主机的异常文本）。
        folded["note"] = f"{folded['note']}（source_type={source_type} ns={namespace}）"
        return folded
    if not isinstance(result, dict):
        result = {"result": result}
    _assert_source_id_echo(result, source_id)
    return {**result, "available": True}


def _assert_source_id_echo(result: Dict[str, Any], requested: Optional[str]) -> None:
    """Phase 2 的降级收尾：递下去的 source_id 与上游 echo 回来的应该**相等**。

    原来那条 warning 说的是"我递不了 id"（SDK 签名没这个参数），03 号补丁
    打上之后那句话就过期了——现在真正要盯的是另一种失败：id 递出去了，
    上游回给你别的 id。字段名不确定就 present-only 地翻两处（外层与 report
    里各放一份都常见），翻不到就不下断言——"上游没报 id"和"上游报了个不同
    的 id"是两件事，别把前者写成后者。
    """
    if not requested:
        return
    inner = result.get("report") if isinstance(result.get("report"), dict) else {}
    echoed = inner.get("source_id") or result.get("source_id")
    if echoed and str(echoed) != str(requested):
        logger.warning("上游 ingest echo 回来的 source_id=%r 与递下去的 %r 不一致——"
                       "这单写进去的行不是按我们的 id 寻址的，按 source 检索/联查"
                       "前请先确认上游那边的 id 语义", echoed, requested)



# ------------------------------------------------------------- SDK 删除面

# 删除是**单次提交**的存储动作（delete_where 一个 commit 落定，不像 ingest
# 要走完整条 agentic 管线），30s 足够封顶，留硬 cap 只为兜"上游卡死"。
_DELETE_HARD_CAP_S = 30.0


def _client_sync() -> tuple:
    """同步版 (client, failure)——给 gateway 那三个 **sync** 删除原语用。
    它们今天就是这样被调用的：memory_browse 把整个 `_delete_*` 包进
    asyncio.to_thread，chat_service 的会话删除段本来就在同步方法里；把
    gateway.delete_* 改成 async 才是去动三个不在我 scope 里的调用点。
    锁与惰性构造都复用 _build_client，行为与 _client_for 完全一致，只是
    不经过事件循环。"""
    try:
        return _build_client(), None
    except Exception as exc:  # noqa: BLE001
        return None, _client_fail(exc)


def _require_method(client: Any, name: str) -> Any:
    """取上游 SDK 上的一个方法，没有就折成可读失败——补丁没应用/upstream
    checkout 太旧时，调用方看到的是一条"这个 SDK 不带 delete 面"的话，
    不是 AttributeError。"""
    fn = getattr(client, name, None)
    if not callable(fn):
        # ValueError 而不是 AttributeError：_fail_note 的口径是"ValueError 是
        # 写给调用方的话"，这条恰恰就是——补丁没上/checkout 太旧，运维需要
        # 一眼看懂这句话，不该退化成"internal error: AttributeError"。
        raise ValueError(
            f"上游 MemoryClient 没有 {name}()——这个 LLM_MEMORY_REPO 的 SDK 面"
            f"还没有该能力（需要 delete facade 补丁）")
    return fn


def _call_with_cap(fn: Any, kwargs: Dict[str, Any], tag: str) -> Dict[str, Any]:
    """同步调一次上游 SDK，套硬 cap，异常原样带回来（折叠归调用方）。

    cap 只封顶**等待**：到点拿不到结果就返回超时折叠，工作线程不会被取消
    （上游 SDK 没有 cancel 通道，与写路同一条事实，别在这里假装能取消）。
    线程池用完即 `shutdown(wait=False)`——用默认的那句隐含 `wait=True`
    等于白设 cap：`with` 退出会一直等到任务真跑完，事件循环该被拖还是被拖。
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"mem-{tag}")
    try:
        future = pool.submit(fn, **kwargs)
        try:
            return {"_value": future.result(timeout=_DELETE_HARD_CAP_S)}
        except FutureTimeout:
            logger.warning("上游 %s 超过 %ss 硬上限放弃等待（无取消通道，"
                           "后台线程仍可能把这单执行完）", tag, _DELETE_HARD_CAP_S)
            return {"_timeout": True}
        except Exception as exc:  # noqa: BLE001 —— 线程里的异常在这里现身
            return {"_error": exc}
    finally:
        pool.shutdown(wait=False)


def _fold_call(tag: str, folded: Dict[str, Any]) -> Dict[str, Any]:
    """把 _call_with_cap 的三种结局收敛成门面形状。"""
    if folded.get("_timeout"):
        return {"available": False, "error": "TimeoutError",
                "note": (f"上游 {tag} 超 {int(_DELETE_HARD_CAP_S)}s 未回，已停止等待"
                         f"（无取消通道，上游侧可能仍在执行，重试前先确认状态）")}
    if "_error" in folded:
        return _fail(tag, folded["_error"])
    result = folded.get("_value")
    if not isinstance(result, dict):
        result = {"result": result}
    return {**result, "available": True}


def upstream_delete(memory_id: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    """按 id 删一行（同步入口，理由见 `_client_sync`）。

    折叠形状与读路/写路同构：{"available": False, "error", "note"}，本层
    不 raise——raise 与否归 gateway。上游的"这行本来就没有"**不是错误**：
    它回 {"deleted": False, "reason": "no row with this id"}，语义上是
    "你要的状态已经满足了"，所以这里原样带出 available=True + deleted=False，
    留给调用方自己决定要不要在 UI 上喊一声。namespace= 在上游是一条**断言**
    而非过滤器：行在别的 ns 里会 raise ValueError（拒绝，不是静默成功）。
    """
    client, failure = _client_sync()
    if failure is not None:
        return failure
    if client is None:
        return _unavailable()
    kwargs: Dict[str, Any] = {"memory_id": str(memory_id)}
    if namespace:
        kwargs["namespace"] = str(namespace)
    try:
        fn = _require_method(client, "delete")
    except Exception as exc:  # noqa: BLE001
        return _fail("delete", exc)
    return _fold_call("delete", _call_with_cap(fn, kwargs, "delete"))


def upstream_delete_where(namespace: Optional[str] = None, source_id: Optional[str] = None,
                          source_type: Optional[str] = None, tier: Optional[str] = None,
                          dry_run: bool = False) -> Dict[str, Any]:
    """按 (namespace, source_id|source_type|tier) 整片删，一次提交，返回
    删掉的行数（`deleted`）。同步入口，折叠形状同上。

    上游在这里比它的存储层更严：**namespace 必填且必须具体**——空串与 "*"
    一律 ValueError("refusing to delete '*'/empty: pass one exact namespace
    name")，`source_id="*"` 同样拒。这不是啰嗦：source_id 是个项目内字符串
    （"main" 之类的都可能撞上），不带 ns 就等于跨机器全库删。这四种坏输入
    都由上游拒，措辞归上游，我们原样转达，不自己另写一套拒绝话——原先那支
    AR 侧的手动探针已经不在了，现在盯这件事的是上游的
    `scripts/tests/api/test_memory_browse_facade.py` 与本仓的
    `tests/test_delete_guard_precedes_route.py`。
    """
    client, failure = _client_sync()
    if failure is not None:
        return failure
    if client is None:
        return _unavailable()
    kwargs = {}
    if namespace is not None:
        kwargs["namespace"] = str(namespace)
    if source_id is not None:
        kwargs["source_id"] = str(source_id)
    if source_type is not None:
        kwargs["source_type"] = str(source_type)
    if tier is not None:
        kwargs["tier"] = str(tier)
    if dry_run:
        kwargs["dry_run"] = True
    try:
        fn = _require_method(client, "delete_where")
    except Exception as exc:  # noqa: BLE001
        return _fail("delete_where", exc)
    return _fold_call("delete_where", _call_with_cap(fn, kwargs, "delete_where"))


# ------------------------------------------------- 整片浏览（gateway.browse_* 的上面那层）

def _scope_kwargs(namespace: Any) -> Dict[str, Any]:
    """把 gateway 已经收敛好的作用域翻译成上游 `all_rows` 的参数形状。

    `"*"` / `None` → **不传作用域**：上游把 "*" 当作"这里没有 scope 这回事"，
    返回 `scoped=False`，这正是浏览面要的语义；`browse_all_rows("*")` 是
    memory_browse 的默认调用，别在这里把它翻成一个真实的名字。
    单个字符串 → `namespace=`（走上游那条会校验形状/在册的窄路）；
    列表 → `namespaces=[...]`（上游那条目前不逐个校验，与 search 复数路同形）。
    """
    if namespace is None:
        return {}
    if isinstance(namespace, str):
        text = namespace.strip()
        return {} if not text or text == "*" else {"namespace": text}
    if isinstance(namespace, (list, tuple, set)):
        names = [str(n) for n in namespace
                 if n is not None and str(n).strip() and str(n).strip() != "*"]
        return {"namespaces": names} if names else {}
    return {"namespace": str(namespace)}


def _browse(tag: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """同步调一次上游浏览面，折叠形状与 delete_* 完全同构。

    `limit` 一律显式传 `None`：`MemoryClient.all_rows` 有个默认封顶
    （`MAX_ROWS_PER_CALL`）用来防"一个字没点就先把机器库搬进内存"，但
    `browse_*` 的既有契约是"这个 namespace 里有什么就给我什么"——AATF 单库
    五千行出头，照默认走就会在计数上静默少算，而 /briefs 的日期格和卡片上的
    "已入简报速览库"恰恰都是拿 browse 的行数当答案的。所以这里宁可让上游把
    `truncated` 说给我们听，也不接一个悄悄截过的分页；真被截了，日志会喊。
    """
    client, failure = _client_sync()
    if failure is not None:
        return failure
    if client is None:
        return _unavailable()
    try:
        fn = _require_method(client, tag)
    except Exception as exc:  # noqa: BLE001 —— 没有这面的旧 checkout 要说人话
        return _fail(tag, exc)
    kwargs.setdefault("limit", None)
    out = _fold_call(tag, _call_with_cap(fn, kwargs, tag))
    if out.get("available") and out.get("truncated"):
        logger.warning("上游 %s 返回被截断：%s/%s 行——浏览面板能画，但拿它做"
                       "入库计数会偏少", tag, out.get("returned"), out.get("total"))
    return out


def upstream_browse_all_rows(namespace: Any = "*", columns=None) -> Dict[str, Any]:
    """整片浏览，形状 `{available, rows, total, returned, truncated,
    namespaces, store_dir, scoped}`。同步入口，折叠形状同 `upstream_delete*`。

    这面存在的原因是 gateway 的 `browse_*` 一直是"行级"原语，而它原先只认
    本地库：搜索/写/删都接了上游之后，"哪些行还没入库"这种问题就会一半走上游
    一半走本地，两半的答案还不一样——那比谁都没接更糟。
    """
    kwargs = dict(_scope_kwargs(namespace))
    # 投影：像"每天各多少条"这种计数只要 `occurred_at` 一列，却要付整行的钱。
    # 上游的整行面认 `columns=`，所以这里给它一条明路——少拿的不是"大概"，
    # 是"计数根本不需要的那些列"，返回的行数与口径一个字都不变。
    if columns:
        kwargs["columns"] = list(columns)
    return _browse("all_rows", kwargs)


def upstream_browse_rows_for_source(namespace: Any, source_id: str) -> Dict[str, Any]:
    """一个 source 的全部行（每个 chunk + 那条 summary 行）。折叠形状同上。

    `source_id="*"` 由上游拒（它的删除面也拒这个），我们原样转达，不自建一套
    拒绝话——理由在 `upstream_delete_where` 的注释里说过了。
    """
    kwargs = _scope_kwargs(namespace)
    kwargs["source_id"] = str(source_id or "")
    return _browse("rows_for_source", kwargs)


# ----------------------------------------------------- MCP 决策面（可选，默认关）

def _decision_gate() -> Dict[str, Any]:
    """决策面开关的诚实答案，不碰子进程：
    {enabled, available, note?}——未启用/未配置都直说，不做假探测。
    enabled 时 available 留 None：待探测，由连接函数定案。"""
    from src.config.settings import is_llm_memory_mcp_enabled  # 函数级
    enabled = is_llm_memory_mcp_enabled()
    if not enabled:
        return {"enabled": False, "available": False,
                "note": "MCP 决策面默认关闭（env LLM_MEMORY_MCP_ENABLED=1 且 "
                        "LLM_MEMORY_REPO 有效才启用）"}
    if not _repo_src():
        return {"enabled": True, "available": False, "note": _NOTE_NO_REPO}
    # 开着但还没探测：available 留 None，同时把解析到的 store 根报出来
    # （子进程 env 就钉在这个根上，见 _mcp_server_params）。
    return {"enabled": True, "available": None, "store_root": _store_root_note()}


_MCP_PIN_WARNED = False


def _mcp_server_params():
    """从 settings.MCP_CONFIG["llm_memory"] 单源构建 stdio 参数——本文件
    不拼第二份 command/args/env。env 以 os.environ 为底再叠 config env
    （mcp 库的默认环境合并会丢 API key，所以必须显式并表）。

    这里**刻意不钉 MEMORY_DATA_DIR**：数据根由上游那套 paths 决定，一个消费者
    替它选路，结局就是两套存储被悄悄并成一套——上游 README/AGENT-SETUP 里也是
    同一条禁令。子进程照样继承 os.environ：用户真设了这个变量，上游认它；
    没设，上游落回它自己的机器默认根，效果与"猜一个等价形状钉死"一样，
    差别只在我们不必把那句话写进自己的代码。AR 递出去的是代码位置
    （`_repo_src` 那条链），不是数据位置——这本来就是收敛的第一条边界。
    """
    from mcp import StdioServerParameters
    from src.config.settings import MCP_CONFIG
    cfg = MCP_CONFIG.get("llm_memory") or {}
    command = cfg.get("command") or sys.executable
    args = list(cfg.get("args") or ["-m", "llm_memoryd.mcp", "--tools",
                                    ",".join(DECISION_TOOLS)])
    cfg_env = dict(cfg.get("env") or {})
    # 归属的那一句话在这里有个很安静的外科伤口：AR 递出去的是"代码在哪"，
    # 而不是"数据在哪"。要是有人把 MEMORY_DATA_DIR / MEMORY_CONFIG 塞进这段
    # config env，子进程就被钉到某个自定的根上——和 SDK 面各读一套还不吭声。
    # 我们不悄悄删掉它（那是运维的选择），但要让它说出来：一次性的 warning，
    # 比在注释里写一句"别忘了这条禁令"管用。
    pinned = sorted(k for k in ("MEMORY_DATA_DIR", "MEMORY_CONFIG") if k in cfg_env)
    if pinned:
        global _MCP_PIN_WARNED
        if not _MCP_PIN_WARNED:
            _MCP_PIN_WARNED = True
            logger.warning(
                "MCP config env 里钉了 %s：决策面的子进程会按这个根找库，"
                "可能和 SDK 面走的不是同一个存储——数据根的归属在上游，不在这里。",
                "、".join(pinned))
    env = {**os.environ, **cfg_env}
    if not env.get("PYTHONPATH"):
        env["PYTHONPATH"] = _repo_src() or ""
    return StdioServerParameters(command=command, args=args, env=env)


async def upstream_decision_status() -> Dict[str, Any]:
    """探测一次 stdio 会话：initialize + tools/list，看 memory_why /
    memory_pack 是否真被 --tools 端上了桌。失败折叠成 available=False +
    error，绝不 hang（硬超时 _MCP_TIMEOUT_S）。note 带 store 根。"""
    gate = _decision_gate()
    if gate["available"] is not None:
        return gate
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async def _probe():
            async with stdio_client(_mcp_server_params()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    return {t.name for t in getattr(listed, "tools", [])}

        served = await asyncio.wait_for(_probe(), timeout=_MCP_TIMEOUT_S)
        missing = [t for t in DECISION_TOOLS if t not in served]
        gate["available"] = not missing
        gate["tools"] = sorted(served)
        if missing:
            gate["note"] = "--tools 未暴露决策工具 " + ",".join(missing)
        return gate
    except Exception as exc:  # noqa: BLE001
        folded = _fail("mcp 探测", exc)
        gate["available"] = False
        gate["error"] = folded["error"]
        gate["note"] = folded["note"]
        return gate


async def upstream_decision_call(tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """决策工具的一跳直通，只服务 DECISION_TOOLS 白名单（API 层另有同名
    校验，这里是内核侧的第二道闸）。"""
    if tool not in DECISION_TOOLS:
        return {"available": False,
                "note": f"工具 {tool!r} 不在只读决策面白名单 {list(DECISION_TOOLS)}"}
    gate = _decision_gate()
    if gate["available"] is not None:
        return gate
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async def _call():
            async with stdio_client(_mcp_server_params()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await session.call_tool(tool, arguments)

        result = await asyncio.wait_for(_call(), timeout=_MCP_TIMEOUT_S)
        texts = []
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                texts.append(text)
        return {"available": True, "text": "\n".join(texts),
                "structured": getattr(result, "structuredContent", None)}
    except Exception as exc:  # noqa: BLE001
        folded = _fail("mcp call", exc)
        gate["available"] = False
        gate["error"] = folded["error"]
        gate["note"] = folded["note"]
        return gate
