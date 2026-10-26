"""
多文档注册表

管理所有已索引文档的元数据
"""

import copy
import json
import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime
import uuid

# 原子落盘（tmp + os.replace），与 queue_store/registry 同一套范式。
# 实现放在 src/utils/json_io（与 path_guard 同层）——从 pipeline.paths 导入会形成
# core→pipeline 反向依赖，只为一行函数不值得。
from src.utils.json_io import write_json_atomic

try:
    import fcntl  # POSIX 下才有：跨进程排他锁
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - Windows 平台没有 fcntl
    fcntl = None  # type: ignore
    _HAS_FCNTL = False

logger = logging.getLogger(__name__)

# 进程内互斥锁表：按注册表文件路径分桶，不同路径（比如测试用的临时目录）
# 之间互不干扰。只在 Windows 缺 fcntl 时用作兜底——POSIX 下 flock 对同一
# 文件的两个 fd 同样互斥，同进程内的线程竞争已经挡住了。
_THREAD_LOCKS: Dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(path: Path) -> threading.Lock:
    key = str(Path(path).resolve())
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


class DocumentRegistry:
    """
    文档注册表

    存储结构：
    {
        "doc_id": {
            "doc_id": str,
            "doc_name": str,
            "doc_path": str,
            "doc_type": str,
            "index_path": str,
            "brief_summary": str,
            "created_at": str,
            "indexed_at": str,
            "metadata": Dict,
            "generated_files": {
                "images": List[str],      # PDF转图片文件路径列表
                "json_data": str,         # JSON数据文件路径
                "vector_db": str,         # 向量数据库路径
                "summaries": List[str],   # 摘要文件路径列表（md, pdf）
            },
            "processing_stages": {
                "parse": {"status": "completed"|"pending"|"failed", "output_files": [...]},
                "extract_structure": {"status": ..., "output_files": [...]},
                "chunk_text": {"status": ..., "output_files": [...]},
                "process_chapters": {"status": ..., "output_files": [...]},
                "generate_summary": {"status": ..., "output_files": [...]},
                "build_index": {"status": ..., "output_files": [...]},
            }
        }
    }
    """

    def __init__(self, registry_path: Optional[str] = None):
        """
        初始化文档注册表

        实例本身是无状态的——构造时加载一份快照只服务只读方法（get/list_all 等），
        所有写方法都在事务锁内重新加载磁盘上的最新版本再改（见 _transaction），
        所以不同调用点各 new 一个实例完全没问题，也不需要有共享单例。

        Args:
            registry_path: 注册表文件路径（默认使用DATA_ROOT/doc_registry.json）
        """
        if registry_path is None:
            from src.config.settings import DATA_ROOT
            self.registry_path = Path(DATA_ROOT) / "doc_registry.json"
        else:
            self.registry_path = Path(registry_path)

        self._registry: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        """从文件加载注册表

        注意：写事务每次都会重新 load，这里不再是低频的一次性操作，
        日志一律 DEBUG，免得把调用方的 INFO 淹掉。
        """
        if self.registry_path.exists():
            try:
                with open(self.registry_path, 'r', encoding='utf-8') as f:
                    self._registry = json.load(f)
                logger.debug(f"✅ 加载文档注册表: {len(self._registry)} 个文档")
            except Exception as e:
                logger.warning(f"⚠️ 加载注册表失败: {e}")
                self._registry = {}
        else:
            logger.debug("📋 创建新的文档注册表")
            self._registry = {}

    def _save(self):
        """保存注册表到文件

        tmp + os.replace 原子替换，进程中途被杀不会留下半截 JSON。
        它只防"写到一半崩溃"，不防并发写——并发靠 _transaction 的锁。
        """
        try:
            write_json_atomic(self.registry_path, self._registry)
            logger.debug(f"💾 保存文档注册表: {len(self._registry)} 个文档")
        except Exception as e:
            logger.error(f"❌ 保存注册表失败: {e}")

    @contextmanager
    def _advisory_lock(self):
        """跨进程排他锁，锁文件与注册表同目录（doc_registry.json.lock）。

        不直接锁 json 文件本身：write_json_atomic 是 tmp+rename，rename 之后
        原来的 inode 就换了，锁在旧 inode 上会失效——这点和 queue_store 一致。

        flock 只在 POSIX 可用。Windows 上没有 fcntl，退化为进程内 threading.Lock：
        此时只能保证同进程内线程互斥，跨进程写仍然可能互相覆盖，这是缺 fcntl
        时能做到的最好保证（本项目运行环境以 POSIX 为主）。
        """
        if not _HAS_FCNTL:
            # Windows fallback：仅进程内互斥
            with _thread_lock_for(self.registry_path):
                yield
            return

        # 直接拼后缀，不用 with_suffix：后者会把 "doc.registry.json" 的后缀
        # 当成 ".json" 换掉，落到意料之外的文件名上。
        lock_path = Path(str(self.registry_path) + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _transaction(self, callback: Callable[[Dict[str, Dict]], Any]) -> Any:
        """一次完整的写事务：排他锁 → 重新 load → callback 改 → 原子写 → 放锁。

        锁必须横跨"读-改-写"全程，而不是给 _load / _save 各加一把：registry 是
        整文件读写，每个调用方手里都是一份完整快照，分开加锁照样 lost update
        （两边读到同一份快照、各改各的，后写的把先写的整体回滚掉）。范式沿用
        src/pipeline/queue_store.py 的 queue_transaction。

        callback 收到的是 self._registry（同一个字典对象），原地修改；它的返回值
        原样回传给调用方。只有真改动过才落盘，异常时不写。
        flock 不可重入——callback 里不要再调本类其它写方法。
        """
        with self._advisory_lock():
            self._load()
            before = copy.deepcopy(self._registry)
            result = callback(self._registry)
            if self._registry != before:
                self._save()
            return result

    def register(
        self,
        doc_name: str,
        doc_path: str,
        doc_type: str,
        index_path: str,
        brief_summary: str,
        metadata: Optional[Dict] = None,
        generated_files: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        注册新文档（如果已存在临时记录则更新）

        Args:
            doc_name: 文档名称
            doc_path: 文档路径
            doc_type: 文档类型（pdf/url）
            index_path: 索引路径
            brief_summary: 简要摘要
            metadata: 额外的元数据
            generated_files: 生成的文件路径字典
                {
                    "images": List[str],      # 图片文件列表
                    "json_data": str,         # JSON数据文件
                    "vector_db": str,         # 向量数据库路径
                    "summaries": List[str],   # 摘要文件列表
                }

        Returns:
            文档ID
        """
        # ========== 并发安全：整个"读-改-写"都在事务锁内完成 ==========
        # 替代原先"先 _load 再改再 _save"的写法——那只缩小了竞争窗口，
        # 两个任务仍能各自拿到同一份快照后互相覆盖（lost update）。
        def _apply(registry: Dict[str, Dict]) -> str:
            # 检查是否已存在（可能是临时记录）
            existing_doc = self.get_by_name(doc_name)

            if existing_doc:
                # 更新现有记录
                doc_id = existing_doc["doc_id"]
                logger.info(f"📝 发现已存在的记录，更新文档信息: {doc_name} (ID: {doc_id})")

                # 保留 created_at 和 processing_stages
                created_at = existing_doc.get("created_at", datetime.now().isoformat())
                processing_stages = existing_doc.get("processing_stages", {})

                # 更新记录
                registry[doc_id].update({
                    "doc_name": doc_name,
                    "doc_path": doc_path,
                    "doc_type": doc_type,
                    "index_path": index_path,
                    "brief_summary": brief_summary,
                    "created_at": created_at,  # 保留原始创建时间
                    "indexed_at": datetime.now().isoformat(),
                    "status": "completed",  # 更新状态为已完成
                    "metadata": metadata or {},
                    "generated_files": generated_files or {
                        "images": [],
                        "json_data": "",
                        "vector_db": "",
                        "summaries": []
                    },
                    "processing_stages": processing_stages  # 保留处理阶段信息
                })
            else:
                # 创建新记录
                doc_id = str(uuid.uuid4())

                doc_record = {
                    "doc_id": doc_id,
                    "doc_name": doc_name,
                    "doc_path": doc_path,
                    "doc_type": doc_type,
                    "index_path": index_path,
                    "brief_summary": brief_summary,
                    "created_at": datetime.now().isoformat(),
                    "indexed_at": datetime.now().isoformat(),
                    "status": "completed",
                    "metadata": metadata or {},
                    "generated_files": generated_files or {
                        "images": [],
                        "json_data": "",
                        "vector_db": "",
                        "summaries": []
                    }
                }

                registry[doc_id] = doc_record
                logger.info(f"✅ 注册新文档: {doc_name} (ID: {doc_id})")

            return doc_id

        return self._transaction(_apply)

    def get(self, doc_id: str) -> Optional[Dict]:
        """
        获取文档信息

        Args:
            doc_id: 文档ID

        Returns:
            文档记录字典，如果不存在返回None
        """
        return self._registry.get(doc_id)

    def get_by_name(self, doc_name: str) -> Optional[Dict]:
        """
        根据文档名称获取文档信息

        Args:
            doc_name: 文档名称

        Returns:
            文档记录字典，如果不存在返回None
        """
        for doc in self._registry.values():
            if doc["doc_name"] == doc_name:
                return doc
        return None


    def list_all(self, sort_by: str = "indexed_at") -> List[Dict]:
        """
        列出所有文档

        Args:
            sort_by: 排序字段（indexed_at, doc_name, created_at）

        Returns:
            文档记录列表
        """
        docs = list(self._registry.values())

        # 排序
        if sort_by in ["indexed_at", "created_at"]:
            docs.sort(key=lambda x: x.get(sort_by, ""), reverse=True)
        elif sort_by == "doc_name":
            docs.sort(key=lambda x: x.get(sort_by, ""))

        return docs


    def delete(self, doc_id: str) -> bool:
        """
        删除文档记录

        Args:
            doc_id: 文档ID

        Returns:
            是否删除成功
        """
        # ========== 并发安全：删除也是事务操作，锁内先重读再删 ==========
        def _apply(registry: Dict[str, Dict]) -> bool:
            if doc_id not in registry:
                logger.warning(f"⚠️ 文档不存在: {doc_id}")
                return False

            doc_name = registry[doc_id]["doc_name"]
            del registry[doc_id]
            logger.info(f"🗑️ 删除文档记录: {doc_name} (ID: {doc_id})")
            return True

        return self._transaction(_apply)

    def count(self) -> int:
        """
        获取文档总数

        Returns:
            文档数量
        """
        return len(self._registry)

    def update_stage_status(
        self,
        doc_name: str,
        stage_name: str,
        status: str,
        output_files: Optional[List[str]] = None
    ) -> bool:
        """
        更新文档处理阶段状态

        Args:
            doc_name: 文档名称
            stage_name: 阶段名称 (parse, extract_structure, chunk_text, process_chapters, generate_summary, build_index)
            status: 状态 (pending, completed, failed)
            output_files: 该阶段生成的文件路径列表

        Returns:
            是否更新成功
        """
        # ========== 并发安全：整个"读-改-写"在事务锁内完成 ==========
        # 索引时多个阶段、多个文档会并行更新同一个 registry 文件，
        # 原先"load→改→save"之间插进来的其它写会被后写者整体覆盖掉。
        def _apply(registry: Dict[str, Dict]) -> bool:
            doc_info = self.get_by_name(doc_name)

            # 如果文档不存在，自动创建一个临时记录
            if not doc_info:
                logger.info(f"📝 文档 {doc_name} 尚未注册，创建临时记录以跟踪处理进度")
                doc_id = str(uuid.uuid4())
                registry[doc_id] = {
                    "doc_id": doc_id,
                    "doc_name": doc_name,  # 注意：使用 doc_name 而不是 name
                    "doc_type": "pdf",  # 默认类型，使用 doc_type
                    "created_at": datetime.now().isoformat(),
                    "status": "indexing",  # 索引中
                    "processing_stages": {}
                }
            else:
                doc_id = doc_info["doc_id"]

            # 初始化 processing_stages（如果不存在）
            if "processing_stages" not in registry[doc_id]:
                registry[doc_id]["processing_stages"] = {}

            # 更新阶段状态
            registry[doc_id]["processing_stages"][stage_name] = {
                "status": status,
                "output_files": output_files or [],
                "updated_at": datetime.now().isoformat()
            }

            logger.info(f"✅ 更新阶段状态: {doc_name} - {stage_name} = {status}")
            return True

        return self._transaction(_apply)

    def get_stage_status(self, doc_name: str, stage_name: str) -> Optional[Dict]:
        """
        获取文档处理阶段状态

        Args:
            doc_name: 文档名称
            stage_name: 阶段名称

        Returns:
            阶段状态字典，如果不存在返回None
        """
        doc_info = self.get_by_name(doc_name)
        if not doc_info:
            return None

        stages = doc_info.get("processing_stages", {})
        return stages.get(stage_name)


    def get_statistics(self) -> Dict:
        """
        获取统计信息

        Returns:
            统计信息字典
        """
        total_docs = self.count()

        # 按类型统计
        type_counts = {}
        for doc in self._registry.values():
            doc_type = doc.get("doc_type", "unknown")
            type_counts[doc_type] = type_counts.get(doc_type, 0) + 1

        return {
            "total_documents": total_docs,
            "by_type": type_counts
        }

    def update_metadata(self, doc_id: str, metadata_key: str, metadata_value: Any) -> bool:
        """
        安全地更新文档元数据（并发安全）

        Args:
            doc_id: 文档ID
            metadata_key: 元数据字段名
            metadata_value: 元数据值

        Returns:
            是否更新成功
        """
        # ========== 并发安全：锁内重读最新版再改，避免覆盖并发改动 ==========
        def _apply(registry: Dict[str, Dict]) -> bool:
            if doc_id not in registry:
                logger.warning(f"⚠️ 文档不存在: {doc_id}")
                return False

            # 更新元数据
            registry[doc_id][metadata_key] = metadata_value

            logger.info(f"✅ 更新文档元数据: {doc_id} - {metadata_key}")
            return True

        return self._transaction(_apply)

    def get_file_stats(self, doc_id: str) -> Optional[Dict]:
        """
        获取文档的文件统计信息

        Args:
            doc_id: 文档ID

        Returns:
            文件统计信息字典，如果文档不存在返回None
        """
        if doc_id not in self._registry:
            return None

        doc = self._registry[doc_id]
        generated_files = doc.get("generated_files", {})

        stats = {
            "doc_id": doc_id,
            "doc_name": doc.get("doc_name", ""),
            "images_count": len(generated_files.get("images", [])),
            "has_json": bool(generated_files.get("json_data", "")),
            "has_vector_db": bool(generated_files.get("vector_db", "")),
            "summaries_count": len(generated_files.get("summaries", [])),
            "total_files": 0
        }

        # 计算总文件数
        stats["total_files"] = (
            stats["images_count"] +
            (1 if stats["has_json"] else 0) +
            (1 if stats["has_vector_db"] else 0) +
            stats["summaries_count"]
        )

        return stats
