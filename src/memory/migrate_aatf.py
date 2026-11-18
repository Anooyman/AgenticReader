"""一次性迁移：外部 LLM-Memory 库的 AATF 行 → A 自库 data/memory_db。

背景：bridge 时代的简报加载由外部 LLM-Memory（B 侧）写进它自己的
store（AATF namespace 数百行、覆盖几十个日期）。本地 driver 实装后
所有读写都收在 A 自库，这批历史数据成了"在应用里看不见"的孤儿
（/memory 页与 /api/v1/llmmemory/* 已退役，A 侧读 B 库的通路为零）。
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

B 库缺省落点解析顺序：--source 参数 > env LLM_MEMORY_STORE_DIR >
~/Documents/GitHub/LLM-Memory/data/memory（B 侧 webui 的 MEMORY_DATA_DIR
惯例位置）。跑通后用 GET /api/v1/briefs/memory-status 的 aatf 计数复核。
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

_DEFAULT_B_DIR = os.path.expanduser("~/Documents/GitHub/LLM-Memory/data/memory")
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


async def _migrate(source: Optional[str], dry_run: bool, reembed: bool) -> None:
    b_dir = source or os.environ.get("LLM_MEMORY_STORE_DIR") or _DEFAULT_B_DIR
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
    args = parser.parse_args()
    sys.exit(0 if asyncio.run(_migrate(args.source, args.dry_run, args.reembed)) is None else 1)
