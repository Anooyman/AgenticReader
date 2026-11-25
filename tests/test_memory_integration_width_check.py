"""验收脚本的"宽度"这一格——它不是在测通不通，是在测一句话到底算不算数。

`tools/check_memory_integration.py` 前面几项说的是"这条联动通不通"：路由、
自述、计数、形状、护栏。这一格问的是另一个问题：**上游接不上的时候，本地
那份还算不算"同一批东西"**。答案由两个数字决定，而这两个数字平时没人看：

* 上游的宽度在 `capabilities().dimensions` 里，那是本仓 config 定的，权威；
* AR 自己旧库的宽度写在它那张表的 schema 里，由它 provider 的配置决定。

对上 → 回落是同一批数据的另一副本；对不上 → 回落只是接口语义，行本身在
另一个向量空间里。**量不到就说量不到**，这一格不许用"大概都是 1536"或者
"上游应该也是这个"来填空。
"""
import pytest

import tools.check_memory_integration as tool


def _stub_upstream(monkeypatch, dims):
    """把 gateway 的那层纯转发换成一个定尺寸的上游。"""

    async def fake():
        if dims is None:
            raise RuntimeError("未配置上游 LLM-Memory")
        return {"dimensions": dims}

    monkeypatch.setattr("src.memory.gateway.upstream_capabilities", fake)


def test_the_same_width_on_both_sides_is_the_quiet_case(monkeypatch, tmp_path):
    _stub_upstream(monkeypatch, 512)
    monkeypatch.setattr("tools.check_memory_drift.probe_vector_width", lambda _p: 512)
    ok, note = tool.check_width_agreement()
    assert ok is True
    assert "同宽" in note and "512" in note


def test_a_mismatch_says_rows_are_not_portable(monkeypatch):
    _stub_upstream(monkeypatch, 512)
    monkeypatch.setattr("tools.check_memory_drift.probe_vector_width", lambda _p: 1536)
    ok, note = tool.check_width_agreement()
    assert ok is False, "宽度不同却报 PASS，等于把'回落即数据兜底'这句话放过去"
    assert "互不可移植" in note
    assert "重新抽取" in note, "要顺带说清它在补灌上的代价"


def test_upstream_being_unaddressable_makes_this_inapplicable_not_failed(monkeypatch):
    """没接上游时这格不该喊 FAIL——它本来就不适用，喊了就是噪声。"""
    _stub_upstream(monkeypatch, None)
    monkeypatch.setattr("tools.check_memory_drift.probe_vector_width", lambda _p: 1536)
    ok, note = tool.check_width_agreement()
    assert ok is True and "不适用" in note


def test_a_store_without_a_vector_column_reads_as_unknown_not_zero(monkeypatch):
    _stub_upstream(monkeypatch, 512)
    monkeypatch.setattr("tools.check_memory_drift.probe_vector_width", lambda _p: None)
    ok, note = tool.check_width_agreement()
    assert ok is True
    assert "量不到" in note and "None" in note, "别把没有向量列读成宽度 0"


def test_the_width_check_is_wired_into_the_tool(tmp_path, monkeypatch, capsys):
    """它得真的在那串检查里——否则这格会变成"代码里有、屏幕上没有"。"""
    _stub_upstream(monkeypatch, 512)
    monkeypatch.setattr("tools.check_memory_drift.probe_vector_width", lambda _p: 1536)
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    tool.main(["--json"])
    import json
    payload = json.loads(next(line for line in capsys.readouterr().out.splitlines()
                              if line.startswith("{")))
    assert "宽度" in {c["name"] for c in payload["checks"]}
