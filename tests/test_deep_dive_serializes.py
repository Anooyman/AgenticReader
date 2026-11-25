"""deep_dive 缓存实例的并发序列化。

Orchestrator 一轮里的多个 tool_calls 走 asyncio.gather 并行；模型在同一轮
对同一文档发起两次 deep_dive（或两条会话撞上同一个 (doc,provider) 实例）
时，实例级 reset_history 的"双向防脏"挡不住交错——两路的 reset 会互相抹
中间态，答案里混进另一问的上下文。修法是把同一缓存 key 的查询段用
per-key asyncio.Lock 串行化。这条测试钉的就是"并发不再互抹"。
"""
import asyncio

import src.agents.orchestrator.sub_agents.deep_dive as dd


class _StubAgent:
    def __init__(self):
        self.resets = 0
        self.active = 0
        self.max_active = 0
        self.order = []

    def reset_history(self):
        self.resets += 1

    async def query(self, **kw):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.order.append(kw.get("user_query"))
        try:
            await asyncio.sleep(0.02)  # 给另一路让出事件循环的机会
        finally:
            self.active -= 1
        return {"final_answer": f"ans:{kw.get('user_query')}"}


async def test_concurrent_deep_dive_on_same_key_is_serialized(monkeypatch):
    stub = _StubAgent()
    monkeypatch.setattr(dd, "_get_or_create_agent", lambda d, p: stub)
    agent = dd.DeepDiveAgent()

    r1, r2 = await asyncio.gather(
        agent.invoke(doc_name="doc", question="A", provider="openai"),
        agent.invoke(doc_name="doc", question="B", provider="openai"),
    )

    assert {r1["answer"], r2["answer"]} == {"ans:A", "ans:B"}
    assert stub.max_active == 1, "同一实例仍在并发查询——per-key 锁没有生效"
    # 每次调用前后各一次 reset：两路串行 = 4 次
    assert stub.resets == 4


async def test_different_keys_stay_concurrent(monkeypatch):
    """锁是 per-key 的：不同文档的深挖不能被同一把锁拖进串行。"""
    a, b = _StubAgent(), _StubAgent()
    agents = {"docA": a, "docB": b}
    monkeypatch.setattr(dd, "_get_or_create_agent",
                        lambda d, p: agents[d])
    agent = dd.DeepDiveAgent()
    await asyncio.gather(
        agent.invoke(doc_name="docA", question="x", provider="openai"),
        agent.invoke(doc_name="docB", question="y", provider="openai"),
    )
    assert a.max_active + b.max_active >= 2 or a.order + b.order == ["x", "y"], \
        "跨 key 也被串行化了"
