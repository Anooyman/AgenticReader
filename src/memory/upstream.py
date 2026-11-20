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
_SEARCH_DEADLINE_S = 20.0
_SEARCH_HARD_CAP_S = 90.0
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
        from llm_memoryd.common import paths  # noqa: PLC0415——纯诊断，失败可弃
        rule = ("MEMORY_DATA_DIR 已设，data_dir 取该值" if os.environ.get("MEMORY_DATA_DIR")
                else "MEMORY_DATA_DIR 未设，data_dir 取机根 ~/.llm-memory")
        return f"store 根={paths.store_dir()}（{rule}）"
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
        # "无此 ns" vs "空库"的可判别位：交叉一次 store 级视图
        if namespace and out["total"] == 0:
            out["ns_present"] = False
            try:
                store = await asyncio.to_thread(client.status)
                seen = {str(n) for n in (store.get("namespaces") or {})}
                if int(store.get("total") or 0) == 0:
                    out["note"] = "store 为空（0 行）——上游库未接入/未入库，非该 ns 独有"
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
                             deadline_s=_SEARCH_DEADLINE_S,
                             cancel_check=cancel.is_set)

    try:
        result = await asyncio.wait_for(asyncio.to_thread(_run),
                                        timeout=_SEARCH_HARD_CAP_S)
    except asyncio.TimeoutError:
        # 硬 cap 到点：置位让线程下一轮自己收尾，这边走超时折叠（不是
        # _fail——没有异常可打，是"我们到点了"的语义）。
        cancel.set()
        logger.warning("上游 search 超过 %ss 硬上限，已置 cancel flag 等线程收尾",
                       _SEARCH_HARD_CAP_S)
        return {"available": False, "error": "TimeoutError",
                "note": (f"上游 search 超 {int(_SEARCH_HARD_CAP_S)}s 未回，"
                         f"已置取消标志（soft deadline {_SEARCH_DEADLINE_S}s），"
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

# source_id 透传的探测结果缓存：None=还没探测，True/False=上游签名收不收。
_ingest_accepts_source_id: Optional[bool] = None
# "这条写路认不认我们给的 id"的 warning 只需说一次（结构性事实，不是每单事件）。
_ingest_source_id_warned = False


def _call_ingest(client: Any, path: str, source_type: str, namespace: Optional[str],
                 source_id: Optional[str]) -> Any:
    """同步调 client.ingest（在 to_thread 里跑）。

    上游 SDK 面的 ingest 签名**今天**只有 (path, source_type, namespace,
    dry_run/enable_rechunk/enable_quality_check/on_step)——没有 source_id，
    行里的 source_id 由 adapter.source_id(path) 自己派生。这里用 inspect 探测
    签名：上游若打了 source_id 透传补丁（Phase 2 的第一条）就自动带上，本文件
    不必再动。探测不到而调用方递了 source_id 时打一条 warning，说清"ns 是显式
    给的、id 是上游派生的"，绝不假装这条写路认我们给的 id。
    """
    global _ingest_accepts_source_id
    if source_id and _ingest_accepts_source_id is None:
        try:
            import inspect  # 标准库，纯签名探测，不碰运行时行为
            _ingest_accepts_source_id = (
                "source_id" in inspect.signature(client.ingest).parameters)
        except (TypeError, ValueError):  # 拿不准签名＝按不支持走，别瞎猜
            _ingest_accepts_source_id = False
    if source_id and not _ingest_accepts_source_id:
        # 一次进程一条就够：这是签名层面的结构性事实，不是每次都不同的事件。
        global _ingest_source_id_warned
        if not _ingest_source_id_warned:
            _ingest_source_id_warned = True
            logger.warning("上游 ingest 不接受 source_id 参数，本进程里写上游的 "
                           "source_id 一律由上游 adapter 按 path 派生（调用方给的 id "
                           "只进日志，例如 ns=%s id=%s）——跨系统按 id 联查时以库里"
                           "的实际值为准，上游打了透传补丁后这条自动消失",
                           namespace, source_id)
    if source_id and _ingest_accepts_source_id:
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
    return {**result, "available": True}


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


def _mcp_server_params():
    """从 settings.MCP_CONFIG["llm_memory"] 单源构建 stdio 参数——本文件
    不拼第二份 command/args/env。env 以 os.environ 为底再叠 config env
    （mcp 库的默认环境合并丢 API key，必须显式并表）；MEMORY_DATA_DIR 与
    上游 install.py 挂载块同形：父 env 有则已随 os.environ 带入，没有则
    钉一个派生等价形状——注意我们**显式钉**它，而不是赌子进程继承到一个
    恰好正确的 shell。"""
    from mcp import StdioServerParameters
    from src.config.settings import MCP_CONFIG
    cfg = MCP_CONFIG.get("llm_memory") or {}
    command = cfg.get("command") or sys.executable
    args = list(cfg.get("args") or ["-m", "llm_memoryd.mcp", "--tools",
                                    ",".join(DECISION_TOOLS)])
    env = {**os.environ, **(cfg.get("env") or {})}
    if not env.get("PYTHONPATH"):
        env["PYTHONPATH"] = _repo_src() or ""
    if not os.environ.get("MEMORY_DATA_DIR"):
        # 等价形状：上游未设 MEMORY_DATA_DIR 时 data_dir()==~/.llm-memory
        # （common/paths.py 实测）；显式钉死，脱离子 shell 的子进程与父进程
        # 看同一个库，note 里也会把这个根显示出来。
        env["MEMORY_DATA_DIR"] = os.path.join(os.path.expanduser("~"), ".llm-memory")
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
