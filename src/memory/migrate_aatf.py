"""一次性迁移：外部 LLM-Memory 库的 AATF 行 → A 自库 data/memory_db。

背景：bridge 时代的简报加载由外部 LLM-Memory（B 侧）写进它自己的
store（AATF namespace 数百行、覆盖几十个日期）。本地 driver 实装后
所有读写都收在 A 自库，这批历史数据成了"在应用里看不见"的孤儿
（/memory 页与 /api/v1/llmmemory/* 已退役，A 侧读 B 库的通路为零）。

    NOTE（2026-11-24，只记现状不改行为）：这段"往 A 自库搬"的方向和后来的
    记忆收敛正好**相反**——收敛之后写路是 A→B（`gateway.ingest(source_type=
    "brief")` 递上游），A 自库 `data/memory_db` 本身也在退役名单上。所以这个
    脚本现在是一台**倒着开的车**：它不会自己启动（一次性 CLI，没人自动调它），
    但谁真跑一次，就会把一批 1536 维的旧行塞进一个"已经不该存在"的库里，
    还顺手把 `LLM_MEMORY_STORE_DIR` / `MEMORY_DATA_DIR` 这两个本该由上游
    决定的存储位置又读了一遍。有存量要动之前先看
    LLM-Memory 仓库的 `MEMORY-OWNERSHIP-AGENTICREADER.md` §6——那套走的是
    "从事实源重灌"，不是从这里搬。

本脚本把 B 库 namespace=AATF 的行**原样搬家**进 A 自库同名 namespace：

* 字段逐列映射到 A 的 memories 表形状（vector + 文本列 + importance，
  见 vector_store._schema），B 侧多出的列忽略，A 缺列补空串；
* **维度铁律**：B 行的向量长度必须等于 A 侧当前 embedding 维度，
  任一不符即整体中止——静默换库只会造出"能搜但向量错位"的暗坑，
  宁可让人来看；两侧模型不同时用 `--reembed`：元数据逐列照搬，
  向量按 A 当前 embedding 模型对正文重算（复用 brief_ingest 同一
  embed 入口），重算失败单行记 error 继续，不阻塞其余行；
* **幂等**：按 source_id 去重（AATF 一行一卡片，source_id=item_id），
  A 库已有的 source_id 整行跳过——重复执行不翻倍；B 行缺 source_id
  的极端情况按 id 比对兜底；
* --dry-run 只报数不写：B 侧 AATF 行数 / 覆盖日期分布 / 将迁移数 /
  因已存在跳过的数，核对量级用这个。

用法：
    python -m src.memory.migrate_aatf --dry-run
    python -m src.memory.migrate_aatf                 # 实跑（同维度直接搬）
    python -m src.memory.migrate_aatf --reembed       # 维度不同，重算向量
    python -m src.memory.migrate_aatf --source /path  # 显式指定 B 库目录

B 库缺省落点解析顺序（见 _resolve_b_dir）：--source 参数 > env
LLM_MEMORY_STORE_DIR > env MEMORY_DATA_DIR 下的 memory 子目录 >
~/.llm-memory/memory（上游的机器级存储）。这里刻意不写死任何一个路径：
B 侧的存储位置已经搬过一次家，写死的结果是"迁移脚本读到空库、报告无需
迁移"，那比直接报错难发现得多。跑通后用 GET /api/v1/briefs/memory-status
的 aatf 计数复核。
"""
import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

import lancedb

from src.config.settings import resolve_provider
from src.memory.config import MEMORY_DB_DIR, NAMESPACE_AATF, get_embedding_dimensions
from src.memory.vector_store import _TEXT_FIELDS, VectorStore

# 上游的库位置是**会移动的**：它原来是某个 checkout 里的 data/memory，后来
# 变成机器级单一存储。所以这里没有"一个默认路径"，只有解析顺序——写死任何
# 一处都会在某次上游搬家之后静默读到空库，那比报错糟糕得多。
_DEFAULT_B_DIR = os.path.expanduser("~/.llm-memory/memory")


def _resolve_b_dir(source: Optional[str] = None) -> str:
    """--source > LLM_MEMORY_STORE_DIR > MEMORY_DATA_DIR/<memory> > 机器级默认。"""
    for candidate in (
        source,
        os.environ.get("LLM_MEMORY_STORE_DIR"),
        (os.environ.get("MEMORY_DATA_DIR") + "/memory") if os.environ.get("MEMORY_DATA_DIR") else None,
        _DEFAULT_B_DIR,
    ):
        if candidate and os.path.isdir(candidate):
            return candidate
    # 最后一个候选即便不存在也返回它：_read_b_rows 会给出"目录不存在"的明确
    # 报错（含是哪个路径），比在这里猜一个更省排查时间。
    return _DEFAULT_B_DIR
_BATCH = 200


def _as_text(value: Any) -> str:
    """把源行的文本列收敛成 A 的形状：None→""、list→json 串、原串不动。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    if isinstance(value, str):
        return value
    return str(value)


def _read_b_rows(b_dir: str) -> List[Dict[str, Any]]:
    if not os.path.isdir(b_dir):
        raise SystemExit(f"❌ B 库目录不存在: {b_dir}")
    db = lancedb.connect(b_dir)  # 只读用途：全程只 search/to_list，绝不写 B 库
    if "memories" not in db.list_tables().tables:
        raise SystemExit(f"❌ B 库里没有 memories 表: {b_dir}")
    tbl = db.open_table("memories")
    rows = tbl.search().where(f"namespace = '{NAMESPACE_AATF}'").limit(1_000_000).to_list()
    return rows


def _map_row(row: Dict[str, Any], dimensions: int,
             reembed: bool = False) -> Optional[Dict[str, Any]]:
    """B 行 → A 形状记录。非 reembed 模式要求向量逐行等维（调用方已先抽检，
    这里逐行兜底）；reembed 模式向量留 None，由调用方 embed 后回填。
    返回 None 表示该行向量维度异常且处于 reembed 模式（正文也会重算，
    直接继续）。"""
    vector = [float(x) for x in (row.get("vector") or [])]
    if len(vector) != dimensions and not reembed:
        raise SystemExit(
            f"❌ 维度不符：B 行向量 {len(vector)} 维 ≠ A 当前 {dimensions} 维——"
            "两侧 embedding 模型不一致，直接搬会静默错位。"
            "确认要用 A 侧 embedding 重算向量的话，加 --reembed 重跑。"
        )
    out: Dict[str, Any] = {}
    for name in _TEXT_FIELDS:
        out[name] = _as_text(row.get(name))
    out["namespace"] = NAMESPACE_AATF  # 铁定归位，防 B 侧脏值
    try:
        out["importance"] = float(row.get("importance", 0.5))
    except (TypeError, ValueError):
        out["importance"] = 0.5
    out["vector"] = vector if not reembed else None
    return out


def _reembed_text(row: Dict[str, Any]) -> str:
    """重算向量的喂料：正文优先，退 abstract / raw_source——与检索命中的
    内容层一致，重算后 semantic 命中面才和原库相当。"""
    for field in ("detail", "abstract", "raw_source"):
        text = _as_text(row.get(field)).strip()
        if text:
            return text
    return ""


async def _reembed_all(rows: List[Dict[str, Any]]) -> List[str]:
    """给 rows 就地回填 vector，返回错误信息列表。并发 8，失败单行隔离。"""
    from src.core.llm import LLMBase

    llm = LLMBase(provider=resolve_provider(None))
    errors: List[str] = []

    async def embed_row(row: Dict[str, Any]) -> None:
        text = _reembed_text(row)
        if not text:
            errors.append(f"{row.get('source_id') or row.get('id')}: 无正文可重算向量")
            return
        row["vector"] = [float(x) for x in await llm.embedding_model.aembed_query(text)]

    for i in range(0, len(rows), 8):
        batch = rows[i:i + 8]
        done = await asyncio.gather(*(embed_row(r) for r in batch), return_exceptions=True)
        for r, res in zip(batch, done):
            if isinstance(res, Exception):
                errors.append(f"{r.get('source_id') or r.get('id')}: embed 失败 {res}")
            elif r.get("vector") is None:
                errors.append(f"{r.get('source_id') or r.get('id')}: embed 返回空")
        print(f"  embed 进度 {min(i + 8, len(rows))}/{len(rows)} ...", flush=True)
    return errors


def _upstream_is_the_owner() -> bool:
    """这台机器上是不是已经把 LLM-Memory 定成了记忆的归属地。

    这个脚本比收敛早，它只会写 A 侧本地库——在归属未定之前那是它的全部职责，
    归属已定之后再跑它，就等于**绕过路由**往一个不该再有记忆的库里写记忆。
    所以我们不改它的逻辑（迁移本身还是合法的运维工具），只在真要写的时候
    问一句：现在还是你说了算吗？
    """
    from src.memory.upstream import upstream_available_sync  # 函数级 import：--dry-run 不该拖上游内核
    return bool(upstream_available_sync())


async def _migrate(source: Optional[str], dry_run: bool, reembed: bool,
                   force_local: bool = False) -> None:
    b_dir = _resolve_b_dir(source)
    dimensions = get_embedding_dimensions(resolve_provider(None))
    b_rows = _read_b_rows(b_dir)
    if not b_rows:
        print("ℹ️  B 库 AATF 为空（或日期全部未加载过），无需迁移。")
        return

    store_a = VectorStore(MEMORY_DB_DIR, dimensions)
    existing_rows = store_a.all_rows(NAMESPACE_AATF)
    existing_ids = ({r.get("source_id") for r in existing_rows if r.get("source_id")}
                    | {r.get("id") for r in existing_rows if r.get("id")})

    # 先抽一行判维，dry-run 也能把"要不要 --reembed"在报数里说清楚，
    # 而不是写到一半才撞 SystemExit。
    sample_vec = next((list(r.get("vector") or []) for r in b_rows if r.get("vector")), [])
    dims_mismatch = len(sample_vec) != dimensions
    if dims_mismatch and not reembed and not dry_run:
        print(f"❌ 维度不符：B 行向量 {len(sample_vec)} 维 ≠ A 当前 {dimensions} 维——"
              "两侧 embedding 模型不一致，直接搬会静默错位。"
              "确认要用 A 侧 embedding 重算向量的话，加 --reembed 重跑。")
        return

    days: Dict[str, int] = {}
    todo: List[Dict[str, Any]] = []
    skipped = 0
    for row in b_rows:
        day = _as_text(row.get("occurred_at"))[:10] or "(无日期)"
        days[day] = days.get(day, 0) + 1
        key = _as_text(row.get("source_id")) or _as_text(row.get("id"))
        if key and key in existing_ids:
            skipped += 1
            continue
        # dry-run 一律按"不写"处理向量：reembed 模式跳过向量搬运，
        # 其余保持原样——mapped 只用来计数，不会真的落库。
        mapped = _map_row(row, dimensions, reembed=reembed or (dry_run and dims_mismatch))
        if mapped is not None:
            todo.append(mapped)

    print(f"源库: {b_dir}")
    print(f"A 自库: {MEMORY_DB_DIR} (dimensions={dimensions})")
    print(f"B 侧 AATF 行数: {len(b_rows)}，覆盖日期 {len(days)} 个")
    if len(days) <= 12:
        print("日期分布: " + ", ".join(f"{d}: {n}" for d, n in sorted(days.items())))
    else:
        print("日期分布: " + ", ".join(f"{d}: {n}" for d, n in sorted(days.items())[:6]) + " …")
    print(f"A 已存有相同 source_id 跳过: {skipped}；待写入: {len(todo)}"
          + ("（--reembed：向量按 A 侧 embedding 重算）" if reembed else ""))
    if dims_mismatch and dry_run and not reembed:
        print(f"ℹ️  两侧向量维度不同（B={len(sample_vec)} 维, A={dimensions} 维），"
              "实跑需加 --reembed 重算向量。")

    if dry_run:
        print("（dry-run，未写入）")
        return
    if not todo:
        print("✅ 没有需要新增的行，A 自库 AATF 已覆盖 B 库内容。")
        return

    if reembed:
        errors = await _reembed_all(todo)
        todo = [r for r in todo if r.get("vector")]
        if errors:
            print(f"⚠️ {len(errors)} 行重算向量失败：")
            for e in errors[:10]:
                print(f"   - {e}")
            if len(errors) > 10:
                print(f"   …另 {len(errors) - 10} 条略")
        if not todo:
            print("❌ 全部重算失败，未写入任何行——先检查 embedding 凭据/模型。")
            return

    if not dry_run and not force_local and _upstream_is_the_owner():
        print("❌ 已拒绝写入：这台机器上记忆的归属地已经是 LLM-Memory 的库，"
              "而这个脚本只会写 AR 自己的 data/memory_db。\n"
              "   要么先 unset LLM_MEMORY_REPO 再跑，要么确认你确实是在做一次性"
              "本地迁移并加 --force-local。\n"
              "   需要走「把存量递进上游」那条路的话，用 src/memory/converge.py"
              "——那才是收敛认的通道。")
        return

    tbl = store_a._table()
    for i in range(0, len(todo), _BATCH):
        tbl.add(todo[i:i + _BATCH])
    after = len(store_a.all_rows(NAMESPACE_AATF))
    print(f"✅ 迁移完成：写入 {len(todo)} 行，A 自库 AATF 现共 {after} 行。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="B 侧 AATF → A 自库一次性迁移")
    parser.add_argument("--source", help="B 库目录（memories.lance 所在目录）")
    parser.add_argument("--dry-run", action="store_true", help="只报数不写入")
    parser.add_argument("--reembed", action="store_true",
                        help="两侧 embedding 模型不同时，按 A 侧模型重算向量")
    parser.add_argument("--force-local", action="store_true",
                        help="明知 LLM-Memory 已被配成记忆归属地，仍坚持写 AR 本地库")
    args = parser.parse_args()
    rc = 0 if asyncio.run(_migrate(args.source, args.dry_run, args.reembed,
                                   force_local=args.force_local)) is None else 1
    sys.exit(rc)
