"""这个恢复工具的行为契约——它处理的是一次真实的数据损失，所以它自己绝不能
成为第二次损失来源。

这里测的都是"不肯写"的情形：dry-run 一个字节都不动、目标已经有货就停手、
宽度对不上就拒、指到上游库就拒。**唯一让它真写的测试，写的是 tmp_path 下
临时造的一张表**——不是 `data/memory_db`，也不是 `~/.llm-memory/memory`：
这台机器上那两个库都不该被我在测试里碰。
"""
import json
import os

import pytest

tools = pytest.importorskip("tools.restore_memory_db_from_dump")

DIM = 8
COLS = ["abstract", "chunk_hash", "created_at", "detail", "id", "importance",
        "keywords", "memory_type", "namespace", "occurred_at", "raw_source",
        "source_id", "source_type"]


def _dump(tmp_path, n=2, dim=DIM, ns="AATF"):
    rows = [{c: ("" if c != "id" and c != "importance" else
                 (f"r{i}" if c == "id" else 0.5)) for c in COLS} | 
            {"id": f"r{i}", "importance": 0.5, "namespace": ns,
             "vector": [0.25] * dim} for i in range(n)]
    path = tmp_path / "dump.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _store(tmp_path, dim=DIM, rows=0, name="memories"):
    import lancedb
    import pyarrow as pa

    # COLS 里本来就有 importance（当字符串塞进行数据没问题，schema 里不能再有
    # 第二个同名字段——那会让 LanceDB 在 create_table 里就炸掉，看起来像工具的问题）
    schema = pa.schema([pa.field(c, pa.string()) for c in COLS if c != "importance"]
                       + [pa.field("importance", pa.float32())]
                       + [pa.field("vector", pa.list_(pa.float32(), dim))])
    db = lancedb.connect(str(tmp_path / "store"))
    data = []
    for i in range(rows):
        item = {c: f"s{i}" for c in COLS}
        item["id"] = f"s{i}"
        item["importance"] = 0.1
        item["vector"] = [0.0] * dim
        data.append(item)
    db.create_table(name, data=data or None, schema=schema)
    return tmp_path / "store"


def test_dry_run_writes_absolutely_nothing(tmp_path):
    dump = _dump(tmp_path)
    store = _store(tmp_path)
    assert tools.main(["--dump", str(dump), "--target", str(store)]) == 0
    import lancedb
    tbl = lancedb.connect(str(store)).open_table("memories")
    assert tbl.count_rows() == 0, "写着 dry-run 的结果居然是写进去了"


def test_apply_puts_the_rows_back_into_the_temp_table(tmp_path):
    dump = _dump(tmp_path, n=2)
    store = _store(tmp_path)
    assert tools.main(["--dump", str(dump), "--target", str(store), "--apply"]) == 0
    import lancedb
    tbl = lancedb.connect(str(store)).open_table("memories")
    assert tbl.count_rows() == 2
    ids = set(tbl.to_pandas()["id"])
    assert {"r0", "r1"} <= ids


def test_a_second_apply_refuses_rather_than_doubling_the_rows(tmp_path):
    dump = _dump(tmp_path, n=2)
    store = _store(tmp_path)
    tools.main(["--dump", str(dump), "--target", str(store), "--apply"])
    assert tools.main(["--dump", str(dump), "--target", str(store), "--apply"]) == 4
    import lancedb
    assert lancedb.connect(str(store)).open_table("memories").count_rows() == 2, \
        "拒绝之后行数应该一模一样——否则那个「拒绝」只是句客套"


def test_a_width_mismatch_is_refused_instead_of_squeezing_rows_in(tmp_path):
    dump = _dump(tmp_path, dim=1536)
    store = _store(tmp_path, dim=64)
    assert tools.main(["--dump", str(dump), "--target", str(store), "--apply"]) == 3
    import lancedb
    assert lancedb.connect(str(store)).open_table("memories").count_rows() == 0


def test_pointing_at_the_upstream_library_is_refused_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "home-scaffold"))
    (tmp_path / "home-scaffold").mkdir()
    dump = _dump(tmp_path)
    rc = tools.main(["--dump", str(dump), "--target",
                     str(tmp_path / "home-scaffold" / "memory"), "--apply"])
    assert rc == 2, "那是上游的库，归上游的 SDK 面——绕过它写就是把决定权抢过来"
    assert not (tmp_path / "home-scaffold" / "memory").exists()


def test_a_target_without_a_table_is_refused_without_mkdir(tmp_path):
    dump = _dump(tmp_path)
    missing = tmp_path / "not-a-store"
    assert tools.main(["--dump", str(dump), "--target", str(missing)]) == 2
    assert not missing.exists(), "它自己说过不建库，那就得真不建"
