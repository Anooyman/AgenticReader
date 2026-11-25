"""`fetch_overview` 的两账并列：本地那本账必须是本地行数。

`browse_*` 上了 auto 路由之后，行级**明细**（`_build_namespace_list`）走
"实际存在哪看哪"是对的；但**计数层**如果也顺手拿路由版的行，本地 `total`
会被上游行数冒充，再叠一层 `upstream_total`，同一份数报两遍——`/data` 页
会画出"本地 0 行"根本不可能出现的形状，"只在上游有的 ns"那条分支也永远
到不了。这条是 2026-11-25 修 overview 重复计数的回归钉。
"""
import pytest

from src.ui.backend.services import memory_browse as mb


def _row(i, ns, created):
    return {"id": f"{ns}-{i}", "namespace": ns, "importance": 0.5,
            "created_at": created, "source_type": "ai_research"}


async def test_overview_local_total_stays_local_and_upstream_separate(monkeypatch):
    local_rows = [_row(0, "ai-research", "2026-11-10")]
    routed_rows = [_row(i, "ai-research", "2026-11-20") for i in range(3)]

    def routed_browse(namespace="*"):
        raise AssertionError("overview 计数层不该走路由版 browse_all_rows——"
                             "用它数行等于把上游行数报两遍")

    monkeypatch.setattr(mb.gateway, "browse_all_rows", routed_browse)
    monkeypatch.setattr(mb.gateway, "browse_all_rows_local",
                        lambda namespace="*": local_rows)

    async def upstream_ns_counts():
        return [{"name": "ai-research", "rows": 3},
                {"name": "webapp-chat", "rows": 7}]

    monkeypatch.setattr(mb.gateway, "upstream_namespaces", upstream_ns_counts)

    ov = await mb.fetch_overview()
    by_name = {e["name"]: e for e in ov["namespaces"]}

    # 两边都有的 ns：本地 total 不动（1 行），上游计数单独进 upstream_total
    ar = by_name["ai-research"]
    assert ar["total"] == 1, "本地行数被路由 browse 冒充了"
    assert ar.get("upstream_total") == 3
    # 只在上游有的 ns：total 记 0 + source 标记，不能从"本地行"里凭空出现
    wc = by_name["webapp-chat"]
    assert wc["total"] == 0
    assert wc.get("upstream_total") == 7
    assert wc.get("source") == "upstream"
    assert ov["total_namespaces"] == 2


async def test_namespace_detail_still_follows_the_route(monkeypatch):
    """明细视图保持路由语义——这条别被上修误伤：`/data` 的命名空间行列表
    本来就该"实际存在哪看哪"。"""
    monkeypatch.setattr(mb.gateway, "browse_all_rows",
                        lambda namespace="*": [_row(1, namespace, "2026-11-21")])
    out = await mb.fetch_namespace("ai-research")
    assert out["total"] == 1
    assert out["groups"][0]["source_id"] == "ai-research-1"
