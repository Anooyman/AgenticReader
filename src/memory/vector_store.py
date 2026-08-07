"""AgenticReader 专属的 LanceDB 记忆存储层。

改自 LLM-Memory 的 common/vector.py，仅保留本项目实际用到的部分：单表
memories、单层记忆（不区分 mid/long tier，不做衰减/压缩/consolidation——
论文/文章摘要本身已经是压缩产物，不是需要长期演化的原始对话记录），
namespace 隔离，semantic_search/keyword_search/list_by_source/keyword_pool
四个检索原语（agent_search 需要的最小集合），不包含 repo 专属字段
（git_meta/imports/file_path 等）、time_search、author_pool。

独立数据库路径（data/memory_db/），与 LLM-Memory 自己的 data/memory/ 完全
隔离，不共享同一个库。
"""
import json
import os
from typing import Any, Dict, List, Optional, Union

import lancedb
import pyarrow as pa

NamespaceArg = Optional[Union[str, List[str]]]

TABLE_NAME = "memories"

_TEXT_FIELDS = [
    "id", "namespace", "memory_type", "abstract", "detail", "keywords",
    "created_at", "source_type", "source_id", "chunk_hash", "raw_source",
    "occurred_at",
]


def _schema(dimensions: int) -> pa.Schema:
    fields = [pa.field("vector", pa.list_(pa.float32(), dimensions))]
    fields += [pa.field(name, pa.string()) for name in _TEXT_FIELDS]
    fields.append(pa.field("importance", pa.float64()))
    return pa.schema(fields)


def _esc(value: str) -> str:
    return value.replace("'", "''")


def _sim_from_distance(distance: float) -> float:
    """余弦距离 [0,2] 映射到相似度 [0,1]。"""
    return max(0.0, min(1.0, 1.0 - float(distance) / 2.0))


def load_json_list(raw: Optional[str]) -> list:
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


def dump_json_list(values: Optional[list]) -> str:
    return json.dumps(values or [], ensure_ascii=False)


def is_summary_row(row: Dict[str, Any]) -> bool:
    """chunk_hash 为空即为该 source 的整篇摘要行（ingest 每次运行重新生成）。"""
    return not row.get("chunk_hash")


def shape_result_row(row: Dict[str, Any], include_raw: bool = False) -> Dict[str, Any]:
    """裁剪成返回给检索调用方的形状——三层递进（abstract / +detail+keywords）。"""
    item = {
        "id": row["id"],
        "namespace": row.get("namespace", ""),
        "abstract": row.get("abstract", ""),
        "created_at": row.get("created_at", ""),
        "occurred_at": row.get("occurred_at") or row.get("created_at", ""),
        "importance": float(row.get("importance", 0.5)),
        "score": round(float(row.get("score", 0.0)), 4),
    }
    if row.get("source_type"):
        item["source_type"] = row["source_type"]
    if row.get("source_id"):
        item["source_id"] = row["source_id"]
    if include_raw:
        item["detail"] = row.get("detail", "")
        item["keywords"] = load_json_list(row.get("keywords"))
    return item


def _strip_vector(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("vector", "_distance")}


class VectorStore:
    def __init__(self, data_dir: str, dimensions: int):
        self.data_dir = data_dir
        self.dimensions = dimensions
        os.makedirs(data_dir, exist_ok=True)
        self._conn = None

    def _db(self):
        if self._conn is None:
            self._conn = lancedb.connect(self.data_dir)
        return self._conn

    def _table(self):
        db = self._db()
        if TABLE_NAME not in db.list_tables().tables:
            db.create_table(TABLE_NAME, schema=_schema(self.dimensions))
        return db.open_table(TABLE_NAME)

    def _table_or_none(self):
        db = self._db()
        if TABLE_NAME not in db.list_tables().tables:
            return None
        return db.open_table(TABLE_NAME)

    # ---- 写 ----

    def add(self, record: Dict[str, Any]):
        tbl = self._table()
        row = {"vector": [float(x) for x in record["vector"]]}
        for name in _TEXT_FIELDS:
            row[name] = record.get(name, "") or ""
        row["importance"] = float(record.get("importance", 0.5))
        tbl.add([row])

    def delete(self, memory_id: str):
        tbl = self._table_or_none()
        if tbl is None:
            return
        tbl.delete(f"id = '{_esc(memory_id)}'")

    # ---- 读 ----

    def get_by_ids(self, ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """按 id 精确取行，返回 {id: row}。用于详情页/单条查看。"""
        tbl = self._table_or_none()
        if tbl is None or not ids:
            return {}
        clause = " OR ".join(f"id = '{_esc(i)}'" for i in ids)
        rows = tbl.search().where(clause).limit(len(ids)).to_list()
        return {r["id"]: _strip_vector(r) for r in rows}

    def _where(self, namespace: NamespaceArg, extra: Optional[str] = None,
               source_type: Optional[str] = None,
               source_id: Optional[str] = None) -> Optional[str]:
        parts = []
        if isinstance(namespace, (list, tuple, set)):
            names = [n for n in namespace if n and n != "*"]
            if names:
                in_list = ", ".join(f"'{_esc(n)}'" for n in names)
                parts.append(f"namespace IN ({in_list})")
        elif namespace and namespace != "*":
            parts.append(f"namespace = '{_esc(namespace)}'")
        if source_type:
            parts.append(f"source_type = '{_esc(source_type)}'")
        if source_id:
            parts.append(f"source_id = '{_esc(source_id)}'")
        if extra:
            parts.append(f"({extra})")
        return " AND ".join(parts) if parts else None

    def semantic_search(self, query_vector: List[float], namespace: NamespaceArg = None,
                        top_k: int = 8, source_type: Optional[str] = None,
                        source_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """向量相似度检索。namespace=None（或 "*"）检索所有 namespace。"""
        tbl = self._table_or_none()
        if tbl is None:
            return []
        q = tbl.search([float(x) for x in query_vector]).metric("cosine")
        where = self._where(namespace, source_type=source_type, source_id=source_id)
        if where:
            q = q.where(where)
        rows = q.limit(top_k).to_list()
        out = []
        for r in rows:
            distance = next(
                (r[k] for k in ("_distance", "score", "distance") if r.get(k) is not None), 2.0,
            )
            item = _strip_vector(r)
            item["semantic_score"] = _sim_from_distance(distance)
            out.append(item)
        return out

    def keyword_search(self, keywords: List[str], namespace: NamespaceArg = None,
                       top_k: int = 10, source_type: Optional[str] = None,
                       source_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """关键词/摘要子串匹配（ILIKE），keywords 字段权重2，abstract 字段权重1。"""
        tbl = self._table_or_none()
        clean_keywords = [kw.strip() for kw in keywords if (kw or "").strip()]
        if tbl is None or not clean_keywords:
            return []
        max_possible = len(clean_keywords) * 2.0
        scores: Dict[str, Dict] = {}
        for kw in clean_keywords:
            e = _esc(kw)
            like = f"keywords ILIKE '%{e}%' OR abstract ILIKE '%{e}%'"
            where = self._where(namespace, extra=like, source_type=source_type, source_id=source_id)
            rows = tbl.search().where(where).limit(top_k * 2).to_list()
            for r in rows:
                rid = r["id"]
                if rid not in scores:
                    scores[rid] = _strip_vector(r)
                    scores[rid]["keyword_score"] = 0.0
                kws = r.get("keywords") or ""
                weight = 2.0 if kw.casefold() in kws.casefold() else 1.0
                scores[rid]["keyword_score"] += weight
        for row in scores.values():
            row["keyword_score_normalized"] = min(1.0, row["keyword_score"] / max_possible)
        ranked = sorted(scores.values(), key=lambda x: x["keyword_score"], reverse=True)
        return ranked[:top_k]

    def keyword_pool(self, namespace: NamespaceArg = None) -> List[str]:
        """已入库的关键词全集（检索时喂给 LLM，让它只挑数据库里真实存在的词）。"""
        tbl = self._table_or_none()
        if tbl is None:
            return []
        where = self._where(namespace)
        q = tbl.search().select(["keywords"])
        if where:
            q = q.where(where)
        rows = q.limit(1_000_000).to_list()
        pool = set()
        for r in rows:
            pool.update(load_json_list(r.get("keywords")))
        return sorted(pool)

    def rows_for_source(self, namespace: NamespaceArg, source_id: str) -> List[Dict[str, Any]]:
        tbl = self._table_or_none()
        if tbl is None or not source_id:
            return []
        where = self._where(namespace, source_id=source_id)
        rows = tbl.search().where(where).limit(1_000_000).to_list()
        return [_strip_vector(r) for r in rows]

    def chunk_hashes(self, namespace: str, source_id: str) -> set:
        return {
            r.get("chunk_hash") for r in self.rows_for_source(namespace, source_id)
            if r.get("chunk_hash")
        }

    def all_rows(self, namespace: NamespaceArg = "*") -> List[Dict[str, Any]]:
        tbl = self._table_or_none()
        if tbl is None:
            return []
        where = self._where(namespace)
        q = tbl.search()
        if where:
            q = q.where(where)
        return [_strip_vector(r) for r in q.limit(1_000_000).to_list()]

    def count_rows(self, namespace: NamespaceArg = "*") -> int:
        tbl = self._table_or_none()
        if tbl is None:
            return 0
        where = self._where(namespace)
        return tbl.count_rows(filter=where) if where else tbl.count_rows()
