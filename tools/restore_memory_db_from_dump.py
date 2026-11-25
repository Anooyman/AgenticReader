#!/usr/bin/env python3
"""把 2026-11-24 被误删的那批 AATF 行放回 AR 自己的 `data/memory_db`。

先说这个文件**为什么会存在**：`tools/check_memory_integration.py` 第一版里有一项
"注定会被护栏挡住"的删除探针，护栏当时只装在上游分支里，于是那次没接上游的运行
把 `data/memory_db` 的 87 条 AATF 行按行删掉了（LanceDB 版本线 v101–v187 就是那
一次留下的）。恢复数据来自时间旅行到 v100 的导出：`data/recovery/memory_db_v100.json`，
**87 行，向量列原样在（1536 维）**——所以这是一次直写恢复，不需要重新抽取，也不需要
问任何模型要东西。

规矩（这几条不是礼貌，是这个工具唯一存在的理由）：

* **缺省 dry-run**，一行都不写；连目标表都以只读方式打开。
* `--apply` 才动手，而且动手前先过三道闸：目标必须是**本地那个库**
  （绝不是上游——本仓的库归本仓的 SDK 面，写它等于替上游做决定）、表得存在、
  表里**必须是 0 行**（已经恢复过再跑一次就是重复，宁可停下来问）。
* 宽度必须对得上：导出里的向量是 1536，目标表若被谁换成别的宽度，那就不是
  "恢复"而是"把不兼容的东西塞进去"，直接拒。
* 写完立刻自己核对一遍条数，报的是**量到的**数字，不是"应当有"的数字。

真正动手之前请自己确认一次：这批行归 AR 的旧库，不是要搬进上游。这次事故的
教训就是"顺手写到另一个地方去"比"写错了"更难发现——所以恢复也只回到它来的地方。
"""
import argparse
import json
import os
import sys

AR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DUMP = os.path.join(AR, "data", "recovery", "memory_db_v100.json")
DEFAULT_TARGET = os.path.join(AR, "data", "memory_db")
TABLE = "memories"


def _open_read_only(path):
    """开表但**不**创建——这条工具自己也得守，否则它就成了第二个副作用源。"""
    import lancedb

    if not os.path.isdir(path):
        raise FileNotFoundError(f"目标库不存在：{path}（不是空库，是根本没这个目录）")
    db = lancedb.connect(path)
    names = db.list_tables()
    names = names.tables if hasattr(names, "tables") else names
    names = [n if isinstance(n, str) else n[0] for n in names]
    if TABLE not in names:
        raise RuntimeError(f"{path} 里没有 {TABLE} 表；恢复需要一个已存在的表，"
                           "建表请走 LLM-Memory 的 ensure_ready，不该由这个脚本来做")
    return db.open_table(TABLE)


def _width(tbl):
    for field in tbl.schema:
        if hasattr(field.type, "list_size"):
            return int(field.type.list_size)
    return None


def _dump_rows(dump_path):
    if not os.path.isfile(dump_path):
        raise FileNotFoundError(f"恢复文件不在：{dump_path}")
    rows = json.loads(open(dump_path, encoding="utf-8").read())
    if not isinstance(rows, list) or not rows:
        raise ValueError("恢复文件形状不对：应是非空的行列表")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=DEFAULT_DUMP)
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--apply", action="store_true",
                    help="真的写。缺省只报告将要做什么。")
    args = ap.parse_args(argv)

    rows = _dump_rows(args.dump)
    want_width = len(rows[0].get("vector") or [])
    ids = [r.get("id") for r in rows]
    print(f"恢复文件：{args.dump}")
    print(f"  行数 {len(rows)}｜向量宽 {want_width or '无列'}｜"
          f"namespace {sorted({r.get('namespace') for r in rows})}")
    print(f"目标库：{args.target}")

    if os.path.abspath(args.target).startswith(os.path.expanduser("~/.llm-memory")):
        # 这条检查不是形式：那个库归上游的 SDK 面，绕过它去写就是替上游决定它
        # 该存什么，正是整套收敛最不该发生的事。
        print("拒绝：目标是上游的库。本工具只负责把行放回 AR 自己的旧库。")
        return 2

    try:
        tbl = _open_read_only(args.target)
    except Exception as exc:  # noqa: BLE001 - 打不开就明说，别当空库
        print(f"拒绝：目标开不了——{type(exc).__name__}: {exc}")
        return 2

    have = tbl.count_rows()
    print(f"  现有行数 {have}｜表宽 {_width(tbl)}")
    if want_width and _width(tbl) and want_width != _width(tbl):
        print(f"拒绝：宽度不同（导出 {want_width}，目标 {_width(tbl)}）——"
              "那不是恢复，是往一张不相容的表里塞行。")
        return 3
    if have:
        print(f"拒绝：目标表已经有 {have} 行。要么已经恢复过，要么这里在长新东西——"
              "两种情况都不该由这个脚本闷头再写一遍。")
        return 4

    if not args.apply:
        print(f"\ndry-run：将写入 {len(rows)} 行到 {args.target}/{TABLE}；"
              "确认无误加 --apply。（本模式一行都不写，也没建过任何东西）")
        return 0

    tbl.add(rows)
    after = tbl.count_rows()
    if after != have + len(rows):
        print(f"注意：写入后数到 {after} 行，期望 {have + len(rows)}——去查这张表的版本线。")
        return 1
    print(f"已恢复 {len(rows)} 行（{have} → {after}）。"
          "记得用 check_memory_drift.py 复核，别看文件写了就以为落进去了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
