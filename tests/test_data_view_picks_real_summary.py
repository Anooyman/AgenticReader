"""`/data` 的 namespace 视图：每组挑哪一行当摘要，**依据必须是真列**。

这个视图的"卡片"是按 `source_id` 分好组的，每组显示一句话描述。挑哪一条，
UI 上有两种实现：
  (a) 认真列——`chunk_hash == ""` 就是 source-summary 行（上游写入时的约定）；
  (b) 启发式——"keywords 空 + detail 长"之类的猜测，`search()` 那条路只能用这个。

走上游 browse 之后这里**应该是 (a)**：真实计数对得上游的摘要行数，一个不多
一个不少。写成用例是因为这格坏过——坏的时候不会报错，只会让每个组的"摘要"
变成"组内排第一的那条"，看上去还是有一句摘要，没人看得出那是猜的。

顺带钉住没有摘要行的那种组：退化用组内最早的一条，这是**写下来的行为**，
不是巧合，所以也不能哪天被顺手改掉就没人管。
"""
import pytest

from src.memory import gateway
from src.ui.backend.services import memory_browse


def _row(row_id, source_id, chunk_hash, abstract, created_at, keywords='["k"]'):
    return {"id": row_id, "namespace": "AATF", "source_id": source_id,
            "source_type": "brief", "chunk_hash": chunk_hash, "abstract": abstract,
            "detail": "x" * 400 if chunk_hash else "", "keywords": keywords,
            "created_at": created_at, "occurred_at": created_at,
            "importance": 0.5, "score": 0.9, "memory_type": "semantic",
            "raw_source": ""}


_ROWS = [
    # 组 doc-1：一条真摘要 + 两条普通 chunk
    _row("s1", "doc-1", "", "摘要：这一篇讲了什么", "2026-11-20T00:00:00+00:00"),
    _row("c1", "doc-1", "aa11", "第一个 chunk 的正文", "2026-11-20T00:00:01+00:00"),
    _row("c2", "doc-1", "bb22", "第二个 chunk 的正文", "2026-11-20T00:00:02+00:00"),
    # 组 doc-2：没有摘要行，退化成最早那条
    _row("c3", "doc-2", "cc33", "这组只有 chunk，没有摘要", "2026-11-19T00:00:00+00:00"),
    _row("c4", "doc-2", "dd44", "另一条 chunk", "2026-11-19T00:00:05+00:00"),
]


@pytest.fixture()
def routed(monkeypatch):
    """视图读到的行 = 路由之后的行，本用例里由这里全权提供。"""
    monkeypatch.setattr(gateway, "browse_all_rows",
                        lambda namespace="*": [dict(r) for r in _ROWS])
    return monkeypatch


def test_summary_line_comes_from_the_real_column_not_from_a_guess(routed):
    view = memory_browse._build_namespace_list("AATF")
    by_id = {g["source_id"]: g for g in view["groups"]}

    assert by_id["doc-1"]["representative_abstract"] == "摘要：这一篇讲了什么"
    picked = [it for it in by_id["doc-1"]["items"] if it["is_summary"]]
    assert [it["id"] for it in picked] == ["s1"], "挑中的必须是真的那条 summary 行"


def test_a_group_without_a_summary_row_falls_back_to_the_earliest_chunk(routed):
    view = memory_browse._build_namespace_list("AATF")
    by_id = {g["source_id"]: g for g in view["groups"]}
    g = by_id["doc-2"]
    assert not any(it["is_summary"] for it in g["items"])
    assert g["representative_abstract"] == "这组只有 chunk，没有摘要", "写下来的退化行为"


def test_the_view_counts_whatever_the_route_returned(routed):
    view = memory_browse._build_namespace_list("AATF")
    assert view["total"] == len(_ROWS) == 5
    assert len(view["groups"]) == 2
    # 组内按创建时间排， newest-first 的组排序也照写下来的规矩来
    assert [g["source_id"] for g in view["groups"]] == ["doc-1", "doc-2"]


def test_a_long_detail_row_with_keywords_is_never_mistaken_for_the_summary(routed):
    """启发式最容易翻车的位置：keywords 还在、detail 很长的那条普通 chunk，
    绝不该被当成摘要——那正是"看上去像摘要"的行。"""
    routed.setattr(gateway, "browse_all_rows", lambda namespace="*": [
        _row("s9", "doc-9", "", "真摘要", "2026-11-21T00:00:00+00:00"),
        _row("c9", "doc-9", "ff99", "很长的正文，keywords 也齐全",
             "2026-11-21T00:00:01+00:00", keywords='["a", "b", "c"]'),
    ])
    view = memory_browse._build_namespace_list("doc-9")
    g = view["groups"][0]
    assert g["representative_abstract"] == "真摘要"
    assert [it["id"] for it in g["items"] if it["is_summary"]] == ["s9"]
