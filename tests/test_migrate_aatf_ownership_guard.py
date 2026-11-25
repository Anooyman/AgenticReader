"""老迁移脚本的所有权重：它写的是 `data/memory_db`，而归属已经不在那里了。

这个脚本比收敛早，功能上仍然是合法的运维工具，所以**没有拆它的逻辑**——只在
它真要动手写的那一刻加了一道问句："这台机器上记忆还归你说了算吗？"
（判据用的是运行时那条同一个探针 `upstream_available_sync()`，不是另起一支
 env 检查——两处各说各话迟早会分家。）

测试全部写在 `tmp_path` 下现造的表上；`MEMORY_DB_DIR` 在每条用例里都被换掉，
所以这台机器上的 `data/memory_db` 一个字节都不会被这个测试改到。
"""
import asyncio

import pytest

import src.memory.migrate_aatf as m


def _b_rows(n=1):
    return [{"id": f"a{i}", "namespace": "AATF", "source_id": f"d{i}",
             "vector": [0.5] * 12, "abstract": "x", "detail": "y", "keywords": "",
             "importance": 0.5, "memory_type": "decision", "occurred_at": "2026-11-01",
             "raw_source": "", "source_type": "brief", "created_at": "2026-11-01",
             "chunk_hash": f"h{i}"} for i in range(n)]


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    # A 侧指到临时目录；B 侧由 _read_b_rows 直接喂数据，省掉再建一个库
    monkeypatch.setattr(m, "MEMORY_DB_DIR", str(tmp_path / "a_store"))
    monkeypatch.setattr(m, "_read_b_rows", lambda _d: _b_rows())
    monkeypatch.setattr(m, "get_embedding_dimensions", lambda *_a, **_k: 12)
    monkeypatch.setattr(m, "resolve_provider", lambda _p=None: "stub")
    calls = []

    def _probe():
        calls.append(1)
        return sandbox.on
    sandbox.calls = calls
    sandbox.root = tmp_path
    monkeypatch.setattr("src.memory.upstream.upstream_available_sync", _probe)
    return sandbox


def _table_built(sandbox):
    """`store_a._table()` 会顺手建表，所以"有没有这张表"才是写入的真实痕迹。

    注意目录本身可能是被 `lancedb.connect()` 开出来的——那是另一回事，
    这里问的是**行有没有落进去**。
    """
    return (sandbox.root / "a_store" / "memories.lance").exists()


sandbox.on = True


def test_it_refuses_to_write_when_the_upstream_owns_memory(sandbox, capsys):
    asyncio.run(m._migrate("unused", dry_run=False, reembed=False))
    out = capsys.readouterr().out
    assert "已拒绝写入" in out
    assert "converge" in out, "要给一条真出路，不能让拒绝变成死路一条"
    assert not _table_built(sandbox), "被拒之后表还被建出来了，那道闸等于没关"
    assert sandbox.calls, "判据应当来自那条运行时探针"


def test_dry_run_still_runs_when_upstream_is_the_owner(sandbox, capsys):
    """拒绝的是**写**，不是"这个脚本不许跑"——dry-run 的报数本来就是它的用处。"""
    sandbox.on = True
    asyncio.run(m._migrate("unused", dry_run=True, reembed=False))
    assert "已拒绝写入" not in capsys.readouterr().out
    assert not _table_built(sandbox), "dry-run 不该建表"


def test_force_local_lets_the_operator_actually_finish_the_migration(sandbox, capsys):
    """这道闸不许变成关不掉的教条：加 `--force-local` 就得真的写下去，
    否则"运维还有路可走"这句话只是句安慰。"""
    sandbox.on = True
    asyncio.run(m._migrate("unused", dry_run=False, reembed=False, force_local=True))
    assert "已拒绝写入" not in capsys.readouterr().out
    assert _table_built(sandbox), "加了 --force-local 却没写下去，闸就变成教条了"


def test_no_guard_at_all_when_upstream_is_not_configured(sandbox, capsys):
    """归属还没定的那台机器上，这个脚本的行为**逐字节**应该是它原来的样子。"""
    sandbox.on = False
    asyncio.run(m._migrate("unused", dry_run=False, reembed=False))
    assert "已拒绝写入" not in capsys.readouterr().out
    assert _table_built(sandbox)
