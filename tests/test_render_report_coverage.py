"""render_report 的 coverage-date 必须是过滤器，不是标题装饰。

`--coverage-date X` 在 CLI 上承诺"出 X 日的报告"；旧实现只把 X 写进
<title>/<meta> 和目录名，卡片集合是全部历史——每次用它出日报都会静默
交一份混了别家日期的 HTML，看起来完全正常，错得无声无息。
"""
import json

import src.pipeline.render_report as rr


def _seed(tmp_path, monkeypatch):
    for sub in ("pdf", "web"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    def w(sub, name, doc):
        (tmp_path / sub / name).write_text(json.dumps(doc), encoding="utf-8")

    w("pdf", "a.json", {"title": "ALPHA-DOC", "doc_name": "a", "coverage_date": "2026-11-01", "url": "u"})
    w("pdf", "b.json", {"title": "BETA-DOC", "doc_name": "b", "coverage_date": "2026-11-02", "url": "u"})
    w("web", "c.json", {"title": "GAMMA-DOC", "doc_name": "c", "coverage_date": "2026-11-02"})
    monkeypatch.setattr(rr, "SUMMARIES_DIR", tmp_path)


def test_coverage_date_actually_filters(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    html1 = rr.render_report("2026-11-01")
    assert "ALPHA-DOC" in html1 and "BETA-DOC" not in html1
    assert "共 1 篇论文" in html1  # 不是全部历史
    html2 = rr.render_report("2026-11-02")
    assert "BETA-DOC" in html2 and "GAMMA-DOC" in html2 and "ALPHA-DOC" not in html2


def test_all_flag_keeps_whole_history(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    html = rr.render_report("2026-11-99", all_entries=True)
    assert "ALPHA-DOC" in html and "BETA-DOC" in html and "GAMMA-DOC" in html
