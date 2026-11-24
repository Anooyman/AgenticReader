"""上游只读门面的契约测试——全程离线，不碰上游真实库、不发网络。

两层分开钉：
  * src/memory/upstream.py 的 SDK 面——注入面是模块全局 `_client`
    （_make_client 首行短路：非 None 即直接采用，不碰 env / sys.path /
    llm_memoryd import），假 MemoryClient 顶替真 SDK，形状与折叠语义
    全在假数据上断言；
  * gateway 的门面段——四个公开名字存在、其余三个面属性转发、
    search 的作用域过 resolve_search_namespaces 收敛后才离开门面
    （"*" 的落点是"空作用域=全局搜"，由 upstream.py 的 scoped 语义
    定调，不把魔法字符串喂给上游）。

未配置降级一项不注入：delenv LLM_MEMORY_REPO + _client 复位 None，
一切入口 available=False + note、绝不 raise——这条链路由 settings 的
env 读取函数把关（计划 §1.5），settings 侧没就位时它会红，属"等 src
落地"，不是测试该绕开的洞。
"""
import asyncio
import json

import pytest

from src.config import settings
from src.memory import gateway
from src.memory import upstream


def _run(coro):
    """async 门面与可能的同步转发都接得住。"""
    if hasattr(coro, "__await__"):
        return asyncio.run(coro)
    return coro


class FakeMemoryClient:
    """上游 MemoryClient 只读面的替身：记录每次调用的作用域参数，
    返回可辨识的假数据；failures 里点名哪个方法，该方法就按指定
    异常原地炸开（模拟上游 SDK 同步方法的真实故障形状）。"""

    def __init__(self, failures=None):
        self.calls = []
        self._failures = dict(failures or {})
        self.status_result = {"namespaces": {"ai-research": 12, "webapp-chat": 3},
                              "total": 15, "empty": False,
                              "store_dir": "/fake/store"}
        self.namespaces_result = [{"name": "ai-research", "row_count": 12},
                                  {"name": "webapp-chat", "row_count": 3}]
        self.search_result = {"results": [{"text": "fake hit"}], "mode": "semantic"}

    def status(self, namespace=None, **kw):
        self.calls.append({"method": "status", "namespace": namespace, "kw": kw})
        self._boom("status")
        return dict(self.status_result)

    def namespaces(self):
        self.calls.append({"method": "namespaces"})
        self._boom("namespaces")
        return list(self.namespaces_result)

    def search(self, query, namespace=None, namespaces=None, deadline_s=None, **kw):
        self.calls.append({"method": "search", "query": query, "namespace": namespace,
                           "namespaces": namespaces, "kw": kw})
        self._boom("search")
        return dict(self.search_result)

    def _boom(self, name):
        exc = self._failures.get(name)
        if exc is not None:
            raise exc

    # ---- 断言辅助 ----
    def last(self, method):
        return next(c for c in reversed(self.calls) if c["method"] == method)

    def scope_of(self, method="search"):
        call = self.last(method)
        nss, ns = call.get("namespaces"), call.get("namespace")
        if nss:
            return sorted(nss)
        if ns:
            return [ns]
        return []  # 空作用域 = 上游默认跨 store 全量


@pytest.fixture()
def fake(monkeypatch):
    """把 upstream 的 client 注入面换成假 MemoryClient。"""
    def install(**spec):
        client = FakeMemoryClient(**spec)
        monkeypatch.setattr(upstream, "_client", client)
        return client
    return install


# ---------------------------------------------------------------- 公开面
def test_public_read_only_names_exist():
    for name in ("upstream_available", "upstream_status",
                 "upstream_namespaces", "upstream_search"):
        assert callable(getattr(upstream, name, None)), f"upstream.{name} 缺失"


def test_available_true_when_client_injected(fake):
    fake()
    assert _run(upstream.upstream_available()) is True


def test_status_shape_and_namespace_forwarding(fake):
    client = fake()
    out = _run(upstream.upstream_status())
    assert isinstance(out, dict) and out["available"] is True
    # 计划 §1.1：status 返回各 ns 行数——假数据必须原样可见，不许静默吞掉
    assert "ai-research" in json.dumps(out, default=str)
    _run(upstream.upstream_status(namespace="ai-research"))
    call = client.last("status")
    assert call["namespace"] == "ai-research"


def test_namespaces_returns_list_of_entries(fake):
    fake()
    out = _run(upstream.upstream_namespaces())
    assert isinstance(out, list)
    assert "ai-research" in json.dumps(out, default=str)


def test_search_passthrough_and_scoped_flag(fake):
    client = fake()
    out = _run(upstream.upstream_search("attention", namespace="ai-research"))
    call = client.last("search")
    assert call["query"] == "attention"
    assert client.scope_of() == ["ai-research"]
    assert out["available"] is True
    # 计划 §1.1 钉的形状位：scoped——有显式作用域 True，无作用域 False
    assert out["scoped"] is True
    out2 = _run(upstream.upstream_search("attention"))
    assert out2["scoped"] is False


# ---------------------------------------------------------------- 异常折叠
@pytest.mark.parametrize("entry,args", [
    ("upstream_status", ()),
    ("upstream_search", ("q",)),
    ("upstream_namespaces", ()),
])
def test_upstream_exceptions_fold_not_bare_through(fake, entry, args):
    """上游 SDK 同步方法的任何异常必须折叠，绝不让 traceback 裸穿到 UI。
    namespaces 面的折叠语义是空列表（docstring 定案），status/search 是
    {"available": False, note?/error?}——形状统一是"报状态不报细节"，
    细节文案的去向由下一条 test_fail_body_has_type_not_raw_text 钉。"""
    fake(failures={"status": RuntimeError("上游炸了"),
                   "namespaces": RuntimeError("上游炸了"),
                   "search": RuntimeError("上游炸了")})
    out = _run(getattr(upstream, entry)(*args))
    if isinstance(out, dict):
        assert out["available"] is False
        assert "error" in out or "note" in out  # 折叠形状必须有可解释的位
    else:
        assert not out  # 折叠为空列表——同样不许 raise


def test_fail_note_passes_valuerror_falls_back_on_the_rest(fake):
    """折叠 note 的取舍分界（对齐上游 mcp 的 _client_error_message）：
    ValueError 是写给调用方的话，允许截断透传；其余类型只报类型名——
    OSError 之类的 str() 常常把主机绝对路径捎带进 UI。"""
    client = fake(failures={"search": ValueError("query 太长，请控制在 4k 字以内")})
    out = _run(upstream.upstream_search("q"))
    blob = json.dumps(out, ensure_ascii=False)
    assert "query 太长" in blob               # 面向调用方的话必须看得见
    client2 = fake(failures={"search": OSError("socket closed by 10.0.0.1:29100")})
    out2 = _run(upstream.upstream_search("q"))
    blob2 = json.dumps(out2, ensure_ascii=False)
    assert "OSError" in blob2                 # 类型名照报
    assert "10.0.0.1" not in blob2            # 裸 socket 细节留在日志侧


# ---------------------------------------------------------------- 未配置降级
@pytest.mark.parametrize("entry,args", [
    ("upstream_available", ()),
    ("upstream_status", ()),
    ("upstream_namespaces", ()),
    ("upstream_search", ("q",)),
])
def test_unconfigured_degrades_with_note(monkeypatch, entry, args):
    """LLM_MEMORY_REPO 未设 = 上游整体关闭：一切入口 available=False +
    note，不 raise、不 traceback、零本地影响（计划 §1.1 解析链的承诺）。
    寻址读取走 settings 的 env 函数，若那条链没就位这里会直接 raise——
    那是待落地的实现缺口，测试保持原样不弱化。"""
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.setattr(upstream, "_client", None)
    out = _run(getattr(upstream, entry)(*args))
    if isinstance(out, dict):
        assert not out.get("available")
        assert "note" in out or "error" in out
    else:
        assert not out  # available→False / namespaces→[] 都是合法降级形状


# ---------------------------------------------------------------- gateway 门面
def test_gateway_exposes_upstream_facade():
    for name in ("upstream_available", "upstream_status",
                 "upstream_namespaces", "upstream_search"):
        assert callable(getattr(gateway, name, None)), (
            f"gateway.{name} 缺失——门面段应与 browse_*/delete_* 同构地挂在 gateway")


def test_gateway_forwards_facade_calls(monkeypatch):
    """gateway `from src.memory import upstream` 后按属性调用转发——
    patch upstream 模块属性即应生效，写成 from-import 绑定会在这里露馅。"""
    hits = []

    async def spy_available():
        hits.append("available")
        return True

    async def spy_status(namespace=None):
        hits.append("status")
        return {"available": True}

    async def spy_namespaces():
        hits.append("namespaces")
        return []

    monkeypatch.setattr(upstream, "upstream_available", spy_available)
    monkeypatch.setattr(upstream, "upstream_status", spy_status)
    monkeypatch.setattr(upstream, "upstream_namespaces", spy_namespaces)
    assert _run(gateway.upstream_available()) is True
    _run(gateway.upstream_status())
    _run(gateway.upstream_namespaces())
    assert set(hits) == {"available", "status", "namespaces"}


# ---------------------------------------------------------------- 修复轮新增形状钉
def test_facade_keys_win_when_flattening_client_result(fake):
    """摊平形状的门面条款：上游 result 若自带 available/scoped 这类键，
    必须被门面自己算的值覆盖——**result 放在最后的写法在这里翻车。
    门面位恒为门面算的 bool，透传位只许出现在 result 自己的键里。"""
    client = fake()
    client.search_result = {"available": "client-claims", "scoped": "client-lies",
                            "results": [1]}
    out = _run(upstream.upstream_search("q", namespace="ai-research"))
    assert isinstance(out, dict)
    assert isinstance(out["available"], bool) and out["available"] is True
    assert isinstance(out["scoped"], bool) and out["scoped"] is True
    assert out["results"] == [1]           # result 本体照摊平透传
    out2 = _run(upstream.upstream_search("q"))
    assert out2["scoped"] is False         # 无作用域位也不许被 client 顶掉


@pytest.mark.parametrize("entry,args", [
    ("upstream_status", ()),
    ("upstream_search", ("q",)),
])
def test_fail_body_has_type_not_raw_text(fake, caplog, entry, args):
    """_fail 新口径：body 只报异常类型名 + 通用 note——异常原文经常裹着
    上游机器的绝对路径/内部文件名，不许原样流进 UI 响应；细节由
    logger.warning 留痕，走 caplog 见真章。"""
    marker = "/var/folders/x7q/llm_memoryd/store/open.lance: boom"
    fake(failures={"status": RuntimeError(marker), "search": RuntimeError(marker)})
    with caplog.at_level("WARNING"):
        out = _run(getattr(upstream, entry)(*args))
    assert isinstance(out, dict) and not out["available"]
    blob = json.dumps(out, ensure_ascii=False, default=str)
    assert "RuntimeError" in blob      # 类型名必须报得出
    assert "boom" not in blob          # 异常原文退出 body
    assert marker not in blob          # 疑似绝对路径退出 body
    assert marker in caplog.text       # 细节全在日志侧


# ---------------------------------------------------------------- decision 面
def test_gateway_forwards_decision_facade(monkeypatch, tmp_path):
    """gateway 若按门面段同构补上 upstream_decision_status / upstream_decision_call，
    必须是属性转发到 upstream 模块（与 browse_*/delete_* 的分工同构，
    门控归 settings 的 env 函数，这里预先打开闸门并给足寻址目录，
    保证断言测的是"转发"不是"门控拦截"）。"""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    monkeypatch.setattr(settings, "is_llm_memory_mcp_enabled", lambda: True)

    hits = []

    async def spy_status():
        hits.append("status")
        return {"enabled": True, "available": None}

    async def spy_call(tool, arguments):
        hits.append(("call", tool, arguments))
        return {"available": True, "text": "stub"}

    monkeypatch.setattr(upstream, "upstream_decision_status", spy_status)
    monkeypatch.setattr(upstream, "upstream_decision_call", spy_call)
    assert callable(getattr(gateway, "upstream_decision_status", None))
    assert callable(getattr(gateway, "upstream_decision_call", None))
    _run(gateway.upstream_decision_status())
    _run(gateway.upstream_decision_call("memory_why", {"q": 1}))
    assert hits[0] == "status"
    assert hits[1] == ("call", "memory_why", {"q": 1})


def test_search_passes_cancel_flag_when_wired(fake):
    """可选补强：SDK 若接线了上游 search 的 cancel_check 逃生阀，
    调用必须带上它；还没接线时明确 skip——这是实现细节不是契约，
    等接上自然变绿，不该拿红测出个"缺失"吓验收人。"""
    import inspect as _inspect
    if "cancel_check" not in _inspect.getsource(upstream):
        pytest.skip("cancel_check 尚未接线——契约未钉，接线后此用例自动生效")
    client = fake()
    _run(upstream.upstream_search("q", namespace="ns"))
    call = client.last("search")
    assert call.get("kw", {}).get("cancel_check") is not None
@pytest.mark.parametrize("requested,expected", [
    (None, []),                 # 缺省 = 全局搜，不自作主张套自库白名单
    ("*", []),                  # 显式全部 = 同样不传，魔法字符串不许喂上游
    ("x", ["x"]),               # 显式单 ns
    (["x", " x ", "y"], ["x", "y"]),  # 显式列表：strip / 去重后才出域
])
def test_gateway_search_namespace_convergence(fake, requested, expected):
    # 装一次假 client，然后走完整链：gateway 收敛 → upstream 直通 SDK，
    # 作用域的最终形状在假 client 的调用记录里见真章。
    # （若 gateway 写成 from-import 绑定而非属性调用 upstream.upstream_search，
    # 这里读到的还是真寻址失败的空实例——同样会红，正是想要暴露的偏离。）
    client = fake()
    _run(gateway.upstream_search("q", namespace=requested))
    assert client.scope_of() == expected
