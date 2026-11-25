"""`/briefs` 那几个格子到底在数谁的行。

这个页面的"某天是否已入库"是**行级**判据，不是任务账本——这条本身是对的
（bridge 时代 done 满屏、A 库 0 行那次审计就是它逼出来的）。但它数的是
`gateway.browse_all_rows` 的结果，所以自打 browse 上路由之后，这里数的
**应该是上游**；要是哪天有人把 browse 挪回本地，页面不会报错，只会安静地
把"已入库"说成"没入库"——正是这套改动最该防住的那类回归。

三种情形分别钉：
* 路由走上游 → 日期格按上游的行数与 `occurred_at` 归日；
* 上游浏览挂了（gateway 内部回落到本地也算失败面） → 该维度按 0 计、
  接口不炸，`heavy_done` 仍照给；
* 页面上"这张卡片在不在库里"的集合判断 → 取的是**路由之后**的 source_id。
"""
from src.memory import gateway
from src.ui.backend.services import briefs_data


def _row(source_id, occurred_at, namespace="AATF"):
    return {"id": f"u-{source_id}", "namespace": namespace, "source_id": source_id,
            "source_type": "brief", "occurred_at": occurred_at,
            "created_at": occurred_at, "chunk_hash": "ab12", "abstract": "a",
            "detail": "d", "keywords": [], "importance": 0.5, "score": 0.9,
            "memory_type": "semantic", "raw_source": ""}


def test_date_counts_come_from_whichever_library_the_route_picked(monkeypatch):
    seen = {}

    def fake_browse(namespace="*", columns=None):
        seen["namespace"] = namespace
        return [_row("2611.27924", "2026-11-23T00:00:00+00:00"),
                _row("2611.27905", "2026-11-23T00:00:00+00:00"),
                _row("2611.26916", "2026-11-19T00:00:00+00:00")]

    monkeypatch.setattr(gateway, "browse_all_rows", fake_browse)
    monkeypatch.setattr(briefs_data, "load_queue", lambda: {})

    counts = briefs_data.date_memory_counts()
    assert seen["namespace"] == "AATF", "日期格读错库了"
    assert counts["2026-11-23"]["aatf"] == 2
    assert counts["2026-11-19"]["aatf"] == 1
    assert counts["2026-11-23"]["heavy_done"] == 0


def test_a_broken_browse_degrades_to_zero_instead_of_closing_the_page(monkeypatch, caplog):
    def explode(namespace="*", columns=None):
        raise RuntimeError("上游 browse 与本地旧库都没成")

    monkeypatch.setattr(gateway, "browse_all_rows", explode)
    monkeypatch.setattr(briefs_data, "load_queue", lambda: {
        "q1": {"coverage_date": "2026-11-23", "pipeline_status": "done"}})

    with caplog.at_level("WARNING"):
        counts = briefs_data.date_memory_counts()
    assert counts["2026-11-23"]["aatf"] == 0
    assert counts["2026-11-23"]["heavy_done"] == 1
    assert any("AATF" in r.getMessage() for r in caplog.records), "少了一整个维度还不吭声"


def test_the_card_in_library_check_reads_the_routed_rows(monkeypatch):
    monkeypatch.setattr(gateway, "browse_all_rows", lambda namespace="*", columns=None: [
        _row("2611.27924", "2026-11-23T00:00:00+00:00"),
        _row("", "2026-11-20T00:00:00+00:00"),      # 无 id 的行不该混进集合
    ])
    got = briefs_data._local_memory_source_ids("AATF")
    assert got == {"2611.27924"}


def test_a_row_without_a_date_is_never_piled_under_the_name_None(monkeypatch):
    """日期格认的是 `occurred_at[:10]`。缺日期就是缺日期——归进一个叫
    "None" 的假日期，比整个维度少一格难查得多。"""
    monkeypatch.setattr(gateway, "browse_all_rows", lambda namespace="*", columns=None: [
        {"source_id": "x", "occurred_at": None}, {"source_id": "y", "occurred_at": ""}])
    monkeypatch.setattr(briefs_data, "load_queue", lambda: {})
    counts = briefs_data.date_memory_counts()
    assert "None" not in counts
    assert all(v["aatf"] == 0 for v in counts.values())


def test_a_row_without_an_id_still_counts_toward_its_day_but_not_the_card_set(monkeypatch):
    """两处判据用的是不同列，别混：日期格只看 `occurred_at`，卡片是否"在库里"
    看 `source_id`。所以一条没 id 的合法日期的行，该在日期格里、不该在
    集合里——把它俩当一件事的实现迟早会写错其中一个。"""
    rows = [{"id": "u-1", "namespace": "AATF", "source_id": None,
             "occurred_at": "2026-11-23T00:00:00+00:00"}]
    monkeypatch.setattr(gateway, "browse_all_rows", lambda namespace="*", columns=None: list(rows))
    monkeypatch.setattr(briefs_data, "load_queue", lambda: {})

    counts = briefs_data.date_memory_counts()
    assert counts["2026-11-23"]["aatf"] == 1, "日期格只该看 occurred_at"

    monkeypatch.setattr(gateway, "browse_all_rows", lambda namespace="*", columns=None: list(rows))
    assert briefs_data._local_memory_source_ids("AATF") == set()
