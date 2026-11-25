"""验收工具不许有能力碰到真实本地库——这条是被一次真实事故逼出来的。

2026-11-24 那一版 `tools/check_memory_integration.py` 里，有一项检查去调
`delete_source("", ...)` / `delete_namespace("*")`，理由写的是"反正一定会被
护栏拒绝"。护栏确实存在——但只装在上游那条分支里。于是没接上游的那次运行里，
这条"无害的"检查真的按行删掉了 `data/memory_db` 的 87 条记录，而且脚本自己
一声不响（版本时间线 v101–v187 全是它留下的）。

所以这里守的**不是**"护栏在不在"——那是 `test_delete_guard_precedes_route.py`
的事。这里守的是**工具本身的安全帽**：

* 打 delete 之前，`gateway._store` 必须已经被换成沙箱——真库根本不该有出场机会；
* 沙箱用完必须换回去，别让后面所有调用都跑在一个假库上；
* "本地库没被碰过"这项断言只在**该走上游**的时候才成立，否则它就是永远
  在喊错的噪声，而一个总在喊错的检查最后谁都不看。
"""
import json

import pytest

import src.memory.gateway as gateway

tools = pytest.importorskip("tools.check_memory_integration")


class _Poison:
    """任何一次调用都算对方犯了错。"""

    def __init__(self):
        self.calls = []

    def _boom(self, *a, **kw):
        self.calls.append((a, tuple(sorted(kw))))
        raise AssertionError("验收脚本把删除打到了真实本地库上")

    all_rows = delete = rows_for_source = delete_source = delete_namespace = _boom
    def add(self, *a, **kw):
        self._boom(*a, **kw)


def test_the_delete_check_never_hands_the_real_store_the_microphone(monkeypatch):
    poison = _Poison()
    monkeypatch.setattr(gateway, "_store", lambda provider=None: poison)

    ok, note = tools.check_delete_guard()
    assert poison.calls == [], f"沙箱没起作用，真实库被叫到了：{poison.calls}"
    assert "沙箱" in note, f"这条检查得自证它落在哪儿：{note}"
    assert ok is True


def test_the_delete_check_gives_the_store_back_afterwards(monkeypatch):
    def before(*_a, **_kw):
        raise AssertionError("这里不该被调用")

    monkeypatch.setattr(gateway, "_store", before)
    tools.check_delete_guard()
    assert gateway._store is before, "检查做完了却把全局 _store 留在了沙箱上"


def test_the_local_isolation_assertion_knows_when_it_is_allowed_to_lie(monkeypatch, tmp_path):
    """未接上游时本地库被打开是**对的**——这项检查此时必须说"不适用"，
    不是 FAIL。噪声比缺失更贵：它会让人学会忽略这个工具说的所有话。

    "未接"必须是**全部**寻址面为空：routing_state 按 AR 的规矩把 `.env`
    也算数，只 delenv 而仓库根恰好有份真配置的机器会把这条测挂——所以这里
    把 .env 的可见性也掐掉，让"没接上游"成为测试自己构造出来的状态。
    """
    import os

    import tools.check_memory_drift as drift
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    _dot = os.path.join(os.path.dirname(os.path.dirname(drift.__file__)), ".env")
    _real_isfile = os.path.isfile
    monkeypatch.setattr(os.path, "isfile",
                        lambda p: False if str(p) == _dot else _real_isfile(p))
    ok, note = tools.check_no_local_touch()
    assert ok is True and "不适用" in note

    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    ok, note = tools.check_no_local_touch()
    assert ok is True and "没有一次" in note


def test_the_tool_reports_machine_readable_verdicts(capsys, monkeypatch):
    """工具除了给人看，还得给 CI 一个能吃的形状：`--json` 的键哪天被顺手改了，
    挂在 CI 上的那一步要能立刻发现。"""
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    monkeypatch.setattr(gateway, "_store", lambda provider=None: _Poison())

    import src.memory.upstream as upstream
    monkeypatch.setattr(upstream, "_client", None)

    rc = tools.main(["--json"])
    out = capsys.readouterr().out
    payload = json.loads(next(line for line in out.splitlines() if line.startswith("{")))
    assert {"passed", "checks"} <= set(payload)
    names = {c["name"] for c in payload["checks"]}
    assert {"路由", "自述", "删除护栏", "本地隔离"} <= names
    assert payload["passed"] is (rc == 0)


def test_the_tool_describes_its_own_side_effects_accurately():
    """脚本怎么描述自己，也是它的行为之一。

    这里不许它自称"全程只读 / 一个字节都不碰"——被打开过的库会在 `__manifest`
    里留下 version hint / txn 一类的元数据（实测过），那是真会发生的事。
    一句过头的自我保证，最后砸的是所有其他保证的信誉。
    """
    import pathlib

    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "check_memory_integration.py").read_text(encoding="utf-8")
    assert "全程只读" not in text, "这句在元数据层面不成立，别再印一次"
    assert "manifest" in text.lower(), "页脚要把元数据痕迹说清楚"


def test_the_read_shape_leg_tells_an_empty_store_apart_from_a_lying_reader(monkeypatch):
    """这格以前对两种"0"一视同仁，所以它既会误报也会漏报：
    库真的空了算它失败（那是没人灌数据，不是坏了）；读路悄悄回落本地时
    它也只是一句"空"，把最该抓的情形放过去了。分开才有意义。"""
    from tools import check_memory_integration as tool
    from src.memory import gateway, upstream

    monkeypatch.setattr(gateway, "browse_all_rows", lambda *a, **kw: [])
    monkeypatch.setattr(upstream, "upstream_browse_all_rows", lambda *a, **kw: {"total": 0})
    ok, note = tool.check_read_shapes()
    assert ok is True and "空的" in note

    monkeypatch.setattr(upstream, "upstream_browse_all_rows", lambda *a, **kw: {"total": 12})
    ok2, note2 = tool.check_read_shapes()
    assert ok2 is False and "12" in note2, "上游说有 12 行而这里读出 0——那必须是失败，不能又写成'空'"
