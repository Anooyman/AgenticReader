"""清理中转目录这件事的工具行为。

**所有用例都写在 tmp 里**；`data/memory_staging` 这台机器上有 1718 个文件，
那是一台还在跑的机器攒出来的，没有任何一条测试有权利去删它。
"""
import os
import time

import pytest

tools = pytest.importorskip("tools.prune_memory_staging")

@pytest.fixture(autouse=True)
def _project_root_is_tmp(tmp_path, monkeypatch):
    """让工具以为 tmp_path 这棵树就是项目根——它的路径闸就是这么设计的，
    而测试永远不该往真的 data/memory_staging 里伸手。"""
    monkeypatch.setattr(tools, "AR", str(tmp_path))
    monkeypatch.setattr(tools, "DEFAULT_STAGING", str(tmp_path / "staging"))


def _seed(tmp_path, ages):
    root = tmp_path / "staging"
    root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for i, age in enumerate(ages):
        f = root / f"c{i}.json"
        f.write_text("{}", encoding="utf-8")
        os.utime(f, (now - age, now - age))
    return root


def test_dry_run_deletes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tools, "DEFAULT_STAGING", str(tmp_path / "staging"))
    monkeypatch.setattr(tools, "_upstream_reachable", lambda: True)
    root = _seed(tmp_path, [10 * 86400, 10 * 86400, 0.1 * 86400])
    assert tools.main(["--staging", str(root)]) == 0
    assert len(list(root.glob("*.json"))) == 3
    assert "dry-run" in capsys.readouterr().out


def test_apply_only_removes_files_past_the_quiet_window(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "DEFAULT_STAGING", str(tmp_path / "staging"))
    monkeypatch.setattr(tools, "_upstream_reachable", lambda: True)
    root = _seed(tmp_path, [10 * 86400, 2 * 86400, 0.2 * 86400])
    assert tools.main(["--staging", str(root), "--apply", "--min-age-days", "1"]) == 0
    left = sorted(f.name for f in root.glob("*.json"))
    assert left == ["c2.json"], f"太新的那个必须还留着，它可能还在路上：{left}"


def test_it_refuses_when_there_is_no_upstream_to_re_send_to(tmp_path, monkeypatch, capsys):
    """拆桥之前得先确认桥还在——上游不通的时候，这些信封是唯一还能再递一次的东西。"""
    monkeypatch.setattr(tools, "_upstream_reachable", lambda: False)
    root = _seed(tmp_path, [10 * 86400])
    assert tools.main(["--staging", str(root), "--apply"]) == 3
    assert len(list(root.glob("*.json"))) == 1
    assert "不拆桥" in capsys.readouterr().out


def test_a_path_outside_the_project_is_refused(tmp_path, monkeypatch):
    elsewhere = tmp_path.parent / "outside-the-project"
    elsewhere.mkdir(parents=True, exist_ok=True)
    (elsewhere / "a.json").write_text("{}", encoding="utf-8")
    assert tools.main(["--staging", str(elsewhere), "--apply"]) == 2
    assert (elsewhere / "a.json").exists(), "被拒就得真的没动过它"


def test_a_missing_directory_is_reported_as_nothing_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "AR", str(tmp_path))
    assert tools.main(["--staging", str(tmp_path / "nope")]) == 0
