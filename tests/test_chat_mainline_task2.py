"""聊天主线四项收尾的回归测试（task-2）：

  * 工具开关真的进工具集——search_web 只有在会话启用时才被广告给编排模型
    （前端那个「🌐 网络搜索」toggle 以前只是元数据透传）；
  * 新子 agent 的返回形状与失败契约；
  * 会话历史不再是"整段原样重发"：窗口化 + 早期摘要 + 摘要失败时的纯截断
    兜底，摘要只算一次；
  * 首轮请求也要落在 MAX_CONTEXT_CHARS 预算内（超长历史从最老处裁掉）；
  * 删除会话时回收 webapp-chat 记忆行并清掉 chat_ingest 水位线条目；
  * provider 读取收在 resolve_provider 一处，不再各读各的 app_config。

全部用假对象，不联网、不调 LLM、不碰真实 data/ 目录。
"""
import asyncio

import pytest

from src.agents.orchestrator import agent as orch
from src.agents.orchestrator import sub_agents
from src.agents.orchestrator.sub_agents import web_search as ws


# ---------------------------------------------------------------- 工具开关
def test_registered_tool_names_stable():
    """三个子 agent 都在，且恒开集合不含 search_web——它是"要开关才开"的那类。"""
    assert set(sub_agents.SUB_AGENTS) == {"search_memory", "deep_dive_document", "search_web"}
    assert sub_agents.ALWAYS_ON_TOOLS == frozenset({"search_memory", "deep_dive_document"})


@pytest.mark.parametrize("enabled, expected", [
    # None = 调用方不管工具，全开（老调用点/tests 的行为不变）
    (None, {"search_memory", "deep_dive_document", "search_web"}),
    # 给了值就按值来：[] 里不该冒出 search_web
    ([], {"search_memory", "deep_dive_document"}),
    (["search_web"], {"search_memory", "deep_dive_document", "search_web"}),
    # 认不出的名字（AnswerAgent 那侧的 retrieve_documents）既不报错也不放大权限
    (["retrieve_documents"], {"search_memory", "deep_dive_document"}),
    (["search_web", "bogus"], {"search_memory", "deep_dive_document", "search_web"}),
])
def test_advertised_tools_follow_enabled_tools(enabled, expected):
    names = {t["function"]["name"] for t in orch._advertised_tools(enabled)}
    assert names == expected
    assert frozenset(names) == orch._allowed_tool_names(enabled)


def test_disabled_tool_is_not_executed_even_if_model_calls_it():
    """模型凭空编一个没广告过的工具名时也要挡住——只靠"unknown tool"那条分支
    分辨不了"不存在"和"本会话不该用"。"""
    out = asyncio.run(orch._safe_invoke("search_web", None, {"query": "x"},
                                        allowed=frozenset({"search_memory"})))
    assert "not enabled" in out["error"]

    # 反过来：启用时能走到 agent.invoke
    seen = {}

    class FakeAgent:
        async def invoke(self, on_progress=None, **kw):
            seen.update(kw)
            return {"answer": "ok"}

    saved = sub_agents.SUB_AGENTS.get("search_web")
    sub_agents.SUB_AGENTS["search_web"] = FakeAgent()
    try:
        out = asyncio.run(orch._safe_invoke("search_web", None, {"query": "q"},
                                            allowed=frozenset({"search_web"})))
    finally:
        sub_agents.SUB_AGENTS["search_web"] = saved
    assert out == {"answer": "ok"}
    assert seen.get("query") == "q"


def test_run_tool_calls_reports_disallowed_tool_as_error_round():
    """整轮都因为"没开这个工具"失败时，_all_errored 能如实数出来（护栏靠它）。"""
    tc = {"id": "1", "name": "search_web", "args": {"query": "x"}}
    msgs, sources, hits = asyncio.run(orch._run_tool_calls([tc], None, None, None,
                                                           frozenset({"search_memory"})))
    assert "not enabled" in msgs[0].content
    assert sources == ["search_web"]
    assert hits == []


# ---------------------------------------------------------------- 新子 agent
def test_web_search_tool_schema_shape():
    schema = ws.WebSearchAgent().tool_schema()
    fn = schema["function"]
    assert fn["name"] == "search_web"
    assert fn["parameters"]["required"] == ["query"]
    assert "query" in fn["parameters"]["properties"]


def test_web_search_requires_query():
    assert "query" in asyncio.run(ws.WebSearchAgent().invoke(query="   "))["error"]


def test_web_search_maps_searchagent_result():
    class FakeSearch:
        def __init__(self):
            self.calls = []

        async def search(self, query, target_urls=None, use_case=None, max_iterations=10):
            self.calls.append((query, target_urls))
            return {"success": True, "answer": "外部世界的结论",
                    "sources": ["https://a", "", None, "https://b"],
                    "use_case": "search", "processing_strategy": "direct_chat",
                    "warnings": [], "scraped_count": 2}

    fake = FakeSearch()
    saved = ws._SEARCH_AGENTS.get("openai")
    ws._SEARCH_AGENTS["openai"] = fake
    try:
        out = asyncio.run(ws.WebSearchAgent().invoke(query="最新进展", provider="openai"))
    finally:
        ws._SEARCH_AGENTS.pop("openai", None)
        if saved is not None:
            ws._SEARCH_AGENTS["openai"] = saved

    assert fake.calls == [("最新进展", None)]
    assert out["answer"].startswith("外部世界")
    assert out["sources"] == ["https://a", "https://b"]      # 空串/None 被滤掉
    assert "hits" not in out                                  # 网页来源不进"提及论文"条目
    assert out["processing_strategy"] == "direct_chat"


def test_web_search_error_paths():
    class Boom:
        async def search(self, query, target_urls=None, use_case=None, max_iterations=10):
            raise RuntimeError("MCP 起不来")

    class Empty:
        async def search(self, query, target_urls=None, use_case=None, max_iterations=10):
            return {"success": True, "answer": "", "sources": []}

    class Errored:
        async def search(self, query, target_urls=None, use_case=None, max_iterations=10):
            return {"success": False, "error": "搜索引擎超时", "answer": "", "sources": []}

    for cls, keyword in ((Boom, "MCP"), (Empty, "没有返回任何内容"), (Errored, "搜索引擎超时")):
        saved = ws._SEARCH_AGENTS.get("openai")
        ws._SEARCH_AGENTS["openai"] = cls()
        try:
            out = asyncio.run(ws.WebSearchAgent().invoke(query="q", provider="openai"))
        finally:
            ws._SEARCH_AGENTS.pop("openai", None)
            if saved is not None:
                ws._SEARCH_AGENTS["openai"] = saved
        assert "error" in out, cls.__name__
        assert keyword in out["error"], cls.__name__


def test_web_search_accepts_urls():
    got = {}

    class FakeSearch:
        async def search(self, query, target_urls=None, use_case=None, max_iterations=10):
            got["urls"] = target_urls
            return {"success": True, "answer": "a", "sources": ["https://x"]}

    saved = ws._SEARCH_AGENTS.get("openai")
    ws._SEARCH_AGENTS["openai"] = FakeSearch()
    try:
        asyncio.run(ws.WebSearchAgent().invoke(query="分析这个页面", provider="openai",
                                               urls=[" https://x ", "", None]))
    finally:
        ws._SEARCH_AGENTS.pop("openai", None)
        if saved is not None:
            ws._SEARCH_AGENTS["openai"] = saved
    assert got["urls"] == ["https://x"]


# ---------------------------------------------------------------- 历史摘要
def _session(n_messages, session_id="s1"):
    return {"session_id": session_id,
            "messages": [{"role": "user" if i % 2 == 0 else "assistant",
                          "content": f"第 {i} 条"} for i in range(n_messages)]}


@pytest.fixture(autouse=True)
def _clear_summary_cache():
    from src.ui.backend.services import session_manager as sm
    sm._HISTORY_SUMMARIES.clear()
    yield
    sm._HISTORY_SUMMARIES.clear()


@pytest.fixture
def manager(tmp_path):
    """一个只认 tmp 目录的 SessionManager——历史摘要那几个用例不需要真实
    data/sessions，落盘位置也顺带隔离掉了。"""
    from src.ui.backend.services import session_manager as sm
    return sm.SessionManager(base_dir=str(tmp_path / "sessions"))


def test_short_history_passes_through_untouched(manager, monkeypatch):
    from src.ui.backend.services import session_manager as sm
    calls = []
    monkeypatch.setattr(sm, "_summarize_new_prefix",
                        lambda *a, **k: calls.append(1) or "SUMMARY")
    out = asyncio.run(manager.history_for_llm_async(_session(6)))
    assert [m["content"] for m in out] == [f"第 {i} 条" for i in range(6)]
    assert calls == []            # 没超窗口就不该惊动摘要

    # 短会话的角色映射：缺 role / 缺 content 都不能炸
    odd = asyncio.run(manager.history_for_llm_async(
        {"session_id": "s", "messages": [{}, {"content": "x"}, {"role": None}]}))
    assert odd[0]["role"] == "assistant" and odd[0]["content"] == ""
    assert odd[2]["role"] == "assistant" and odd[2]["content"] == ""


def test_long_history_is_windowed_and_summarized_once(manager, monkeypatch):
    from src.ui.backend.services import session_manager as sm
    calls = []

    def fake(dropped, covered, provider, previous):
        calls.append((len(dropped), covered, previous))
        return "早期要点"

    monkeypatch.setattr(sm, "_summarize_new_prefix", fake)
    s = _session(sm.HISTORY_WINDOW_MESSAGES + 30)
    out = asyncio.run(manager.history_for_llm_async(s))

    head = out[0]
    assert head["role"] == "system"
    assert "早期对话摘要" in head["content"] and "早期要点" in head["content"]
    assert f"{30} 条" in head["content"]        # 交代了省略了多少条
    kept = out[1:]
    assert len(kept) == sm.HISTORY_WINDOW_MESSAGES
    assert kept[-1]["content"] == f"第 {sm.HISTORY_WINDOW_MESSAGES + 30 - 1} 条"

    # 第二次问同一会话：缓存还在，不该再打一次 LLM
    asyncio.run(manager.history_for_llm_async(s))
    assert len(calls) == 1

    # 会话变长了（又多掉出 2 条）：增量摘要，covered 从上一轮接上
    s["messages"].extend([{"role": "user", "content": "新 1"},
                          {"role": "assistant", "content": "新 2"}])
    out2 = asyncio.run(manager.history_for_llm_async(s))
    assert len(calls) == 2
    assert calls[-1][1] == 30               # 只算新掉出的那一段
    assert calls[-1][2] == "早期要点"       # 已有摘要作为 previous 传进去
    assert out2[0]["role"] == "system"


def test_summary_failure_falls_back_to_truncation_note(manager, monkeypatch):
    from src.ui.backend.services import session_manager as sm
    monkeypatch.setattr(sm, "_summarize_new_prefix", lambda *a, **k: "")
    s = _session(sm.HISTORY_WINDOW_MESSAGES + 12)
    out = asyncio.run(manager.history_for_llm_async(s))
    assert out[0]["role"] == "system"
    assert "早期历史已省略" in out[0]["content"] and "12" in out[0]["content"]
    assert len(out) - 1 == sm.HISTORY_WINDOW_MESSAGES


def test_summarize_new_prefix_swallows_llm_failures(monkeypatch):
    """_summarize_new_prefix 是同步函数、由线程池调用，任何异常都不能冒到
    一次正常提问的请求路径上。"""
    from src.core.llm import history as hist_mod
    from src.ui.backend.services import session_manager as sm

    class ExplodingHistory:
        def __init__(self, *a, **k):
            raise RuntimeError("no llm configured")

    monkeypatch.setattr(hist_mod, "LimitedChatMessageHistory", ExplodingHistory)
    dropped = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    assert sm._summarize_new_prefix(dropped, 0, "openai", "旧摘要") == "旧摘要"


# ---------------------------------------------------------------- 首轮预算
def test_compose_keeps_small_history_intact():
    history_msgs = [orch.HumanMessage(content=f"第 {i} 句") for i in range(6)]
    q = orch.HumanMessage(content="提问")
    msgs = orch._compose_messages(orch.SYSTEM_PROMPT, history_msgs, q)
    assert len(msgs) == len(history_msgs) + 2          # system + 6 + 提问
    assert "Context budget" not in msgs[0].content     # 没裁就不该吓唬模型


def test_compose_drops_oldest_when_over_budget():
    # 每条 9k 字符、共 60 条——远超 MAX_CONTEXT_CHARS，逼出裁剪分支
    history_msgs = [orch.HumanMessage(content=("x" * 9_000)) for _ in range(60)]
    q = orch.HumanMessage(content="提问")
    msgs = orch._compose_messages(orch.SYSTEM_PROMPT, history_msgs, q)
    assert orch._context_chars(msgs) <= orch.MAX_CONTEXT_CHARS
    assert "Context budget" in msgs[0].content         # 如实说明丢了几条
    assert msgs[-1] is q                                # 提问永远不动
    assert len(msgs) - 2 >= orch.MIN_HISTORY_MESSAGES   # 保命线还在
    # 丢的是最老的，不是最近的
    assert msgs[1].content.startswith("x") and msgs[-2].content.startswith("x")


# ---------------------------------------------------------------- 删除回收
def test_delete_session_purges_memory_and_watermark(monkeypatch, tmp_path):
    from src.ui.backend.services import chat_ingest, session_manager as sm
    from src.memory import gateway

    manager = sm.SessionManager(base_dir=str(tmp_path / "sessions"))
    session = manager.create_session(mode="cross", title="待删")
    sid = session["session_id"]

    deleted = {}

    def fake_delete_source(namespace, source_id):
        deleted["args"] = (namespace, source_id)
        return 3

    forgetted = []
    monkeypatch.setattr(gateway, "delete_source", fake_delete_source)
    monkeypatch.setattr(chat_ingest, "forget_session",
                        lambda s: forgetted.append(s) or True)

    from src.ui.backend.services.chat_service import chat_service
    saved_manager = chat_service.session_manager
    chat_service.session_manager = manager
    try:
        chat_service.delete_session(sid)
    finally:
        chat_service.session_manager = saved_manager

    assert deleted["args"] == (gateway.NAMESPACE_WEBAPP_CHAT, sid)
    assert forgetted == [sid]
    assert not manager._get_session_path(sid).exists()

    # 会话不存在的删除要照旧抛 FileNotFoundError（API 层据此回 404），
    # 而且不能顺手去做"回收"。
    deleted.clear()
    with pytest.raises(FileNotFoundError):
        chat_service.delete_session("no-such-session-xyz")
    assert deleted == {}


def test_chat_ingest_forget_session_removes_watermark(tmp_path, monkeypatch):
    from src.ui.backend.services import chat_ingest as ci

    state_file = tmp_path / "chat_ingest_state.json"
    monkeypatch.setattr(ci, "STATE_PATH", state_file)
    state_file.write_text('{"sessions": {"a": {"last_ingested_at": "x"}, "b": {}}}',
                          encoding="utf-8")

    assert ci.forget_session("a") is True
    import json
    assert json.loads(state_file.read_text())["sessions"] == {"b": {}}
    # 不存在的会话不该制造一次多余的写
    assert ci.forget_session("a") is False


# ---------------------------------------------------------------- provider 单点
def test_chat_service_reads_provider_from_resolve_provider(monkeypatch, tmp_path):
    """initialize 里的 provider 读取必须走 resolve_provider(None)，而不是
    load_config().get("provider", "openai")——后者因为默认字典恒含该键，
    会把 env PROVIDER 这一级从聊天主线上抹掉。"""
    import src.ui.backend.services.chat_service as cs
    from src.ui.backend.services import session_manager as sm

    seen = []
    monkeypatch.setattr(cs, "resolve_provider",
                        lambda p=None: seen.append(p) or "gemini")
    cs.AnswerAgent = lambda provider: _FakeValidator()

    manager = sm.SessionManager(base_dir=str(tmp_path / "sessions"))
    manager.create_session(mode="manual", selected_docs=["a.pdf"],
                           enabled_tools=["retrieve_documents"])
    saved = cs.chat_service.session_manager
    cs.chat_service.session_manager = manager
    try:
        out = cs.chat_service.initialize(enabled_tools=["retrieve_documents"],
                                         selected_docs=["a.pdf"])
    finally:
        cs.chat_service.session_manager = saved

    assert out["success"] is True
    assert seen, "initialize 没有经 resolve_provider 取 provider"
    assert seen[0] is None                      # 缺省解析，不写死任何值
    # 模块级不再有 load_config 这条旁路
    assert not hasattr(cs, "load_config")


class _FakeValidator:
    def validate_manual_selected_docs(self, docs):
        return list(docs), []
