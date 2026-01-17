"""
多文档注册表

管理所有已索引文档的元数据
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)


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
        """从文件加载注册表"""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, 'r', encoding='utf-8') as f:
                    self._registry = json.load(f)
                logger.info(f"✅ 加载文档注册表: {len(self._registry)} 个文档")
            except Exception as e:
                logger.warning(f"⚠️ 加载注册表失败: {e}")
                self._registry = {}
        else:
            logger.info("📋 创建新的文档注册表")
            self._registry = {}

    def _save(self):
        """保存注册表到文件"""
        try:
            # 确保目录存在
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.registry_path, 'w', encoding='utf-8') as f:
                json.dump(self._registry, f, ensure_ascii=False, indent=2)

            logger.debug(f"💾 保存文档注册表: {len(self._registry)} 个文档")
        except Exception as e:
            logger.error(f"❌ 保存注册表失败: {e}")

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
            self._registry[doc_id].update({
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

            self._registry[doc_id] = doc_record
            logger.info(f"✅ 注册新文档: {doc_name} (ID: {doc_id})")

        # 保存
        self._save()

        return doc_id

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
        if doc_id in self._registry:
            doc_name = self._registry[doc_id]["doc_name"]
            del self._registry[doc_id]
            self._save()

            logger.info(f"🗑️ 删除文档记录: {doc_name} (ID: {doc_id})")
            return True
        else:
            logger.warning(f"⚠️ 文档不存在: {doc_id}")
            return False

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
        doc_info = self.get_by_name(doc_name)

        # 如果文档不存在，自动创建一个临时记录
        if not doc_info:
            logger.info(f"📝 文档 {doc_name} 尚未注册，创建临时记录以跟踪处理进度")
            doc_id = str(uuid.uuid4())
            self._registry[doc_id] = {
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
        if "processing_stages" not in self._registry[doc_id]:
            self._registry[doc_id]["processing_stages"] = {}

        # 更新阶段状态
        self._registry[doc_id]["processing_stages"][stage_name] = {
            "status": status,
            "output_files": output_files or [],
            "updated_at": datetime.now().isoformat()
        }

        # 保存
        self._save()

        logger.info(f"✅ 更新阶段状态: {doc_name} - {stage_name} = {status}")
        return True

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

    def is_stage_completed(self, doc_name: str, stage_name: str) -> bool:
        """
        检查某个阶段是否已完成

        Args:
            doc_name: 文档名称
            stage_name: 阶段名称

        Returns:
            是否已完成
        """
        stage_info = self.get_stage_status(doc_name, stage_name)
        if not stage_info:
            return False

        return stage_info.get("status") == "completed"


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

    def delete_all_files(self, doc_id: str, delete_source: bool = False) -> Dict[str, Any]:
        """
        删除文档的所有关联文件

        Args:
            doc_id: 文档ID
            delete_source: 是否删除源文件（PDF/URL）

        Returns:
            删除结果字典
            {
                "success": bool,
                "deleted_files": List[str],
                "failed_files": List[str],
                "errors": List[str]
            }
        """
        import shutil

        if doc_id not in self._registry:
            logger.warning(f"⚠️ 文档不存在: {doc_id}")
            return {
                "success": False,
                "deleted_files": [],
                "failed_files": [],
                "errors": [f"文档不存在: {doc_id}"]
            }

        doc = self._registry[doc_id]
        doc_name = doc.get("doc_name", "unknown")
        generated_files = doc.get("generated_files", {})

        deleted_files = []
        failed_files = []
        errors = []

        logger.info(f"🗑️ 开始删除文档关联文件: {doc_name} (ID: {doc_id})")

        # 1. 删除图片文件
        images = generated_files.get("images", [])
        if images:
            # 假设所有图片在同一目录，删除整个目录
            if images and len(images) > 0:
                image_dir = str(Path(images[0]).parent)
                try:
                    if Path(image_dir).exists():
                        shutil.rmtree(image_dir)
                        deleted_files.append(image_dir)
                        logger.info(f"✅ 删除图片目录: {image_dir}")
                except Exception as e:
                    failed_files.append(image_dir)
                    errors.append(f"删除图片目录失败: {e}")
                    logger.error(f"❌ 删除图片目录失败: {image_dir}, 错误: {e}")

        # 2. 删除JSON数据文件
        json_data = generated_files.get("json_data", "")
        if json_data and Path(json_data).exists():
            try:
                Path(json_data).unlink()
                deleted_files.append(json_data)
                logger.info(f"✅ 删除JSON文件: {json_data}")
            except Exception as e:
                failed_files.append(json_data)
                errors.append(f"删除JSON文件失败: {e}")
                logger.error(f"❌ 删除JSON文件失败: {json_data}, 错误: {e}")

        # 3. 删除向量数据库
        vector_db = generated_files.get("vector_db", "")
        if vector_db and Path(vector_db).exists():
            try:
                shutil.rmtree(vector_db)
                deleted_files.append(vector_db)
                logger.info(f"✅ 删除向量数据库: {vector_db}")
            except Exception as e:
                failed_files.append(vector_db)
                errors.append(f"删除向量数据库失败: {e}")
                logger.error(f"❌ 删除向量数据库失败: {vector_db}, 错误: {e}")

        # 4. 删除摘要文件
        summaries = generated_files.get("summaries", [])
        for summary_file in summaries:
            if Path(summary_file).exists():
                try:
                    Path(summary_file).unlink()
                    deleted_files.append(summary_file)
                    logger.info(f"✅ 删除摘要文件: {summary_file}")
                except Exception as e:
                    failed_files.append(summary_file)
                    errors.append(f"删除摘要文件失败: {e}")
                    logger.error(f"❌ 删除摘要文件失败: {summary_file}, 错误: {e}")

        # 5. 删除源文件（可选）
        if delete_source:
            doc_path = doc.get("doc_path", "")
            if doc_path and Path(doc_path).exists():
                try:
                    Path(doc_path).unlink()
                    deleted_files.append(doc_path)
                    logger.info(f"✅ 删除源文件: {doc_path}")
                except Exception as e:
                    failed_files.append(doc_path)
                    errors.append(f"删除源文件失败: {e}")
                    logger.error(f"❌ 删除源文件失败: {doc_path}, 错误: {e}")

        # 6. 从注册表中删除记录
        del self._registry[doc_id]
        self._save()

        success = len(failed_files) == 0
        logger.info(f"🗑️ 文档删除完成: 成功{len(deleted_files)}个, 失败{len(failed_files)}个")

        return {
            "success": success,
            "deleted_files": deleted_files,
            "failed_files": failed_files,
            "errors": errors
        }

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
