"""
多文档注册表

管理所有已索引文档的元数据
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
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
            "tags": List[str],
            "brief_summary": str,
            "created_at": str,
            "indexed_at": str,
            "metadata": Dict
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
        tags: List[str],
        brief_summary: str,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        注册新文档

        Args:
            doc_name: 文档名称
            doc_path: 文档路径
            doc_type: 文档类型（pdf/url）
            index_path: 索引路径
            tags: 标签列表
            brief_summary: 简要摘要
            metadata: 额外的元数据

        Returns:
            文档ID
        """
        # 生成唯一ID
        doc_id = str(uuid.uuid4())

        # 创建文档记录
        doc_record = {
            "doc_id": doc_id,
            "doc_name": doc_name,
            "doc_path": doc_path,
            "doc_type": doc_type,
            "index_path": index_path,
            "tags": tags,
            "brief_summary": brief_summary,
            "created_at": datetime.now().isoformat(),
            "indexed_at": datetime.now().isoformat(),
            "metadata": metadata or {}
        }

        # 添加到注册表
        self._registry[doc_id] = doc_record

        # 保存
        self._save()

        logger.info(f"✅ 注册文档: {doc_name} (ID: {doc_id})")

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

    def search_by_tags(self, tags: List[str], match_all: bool = False) -> List[Dict]:
        """
        根据标签搜索文档

        Args:
            tags: 标签列表
            match_all: True=必须匹配所有标签，False=匹配任一标签

        Returns:
            文档记录列表
        """
        results = []

        for doc in self._registry.values():
            doc_tags = set(doc.get("tags", []))

            if match_all:
                # 必须包含所有标签
                if set(tags).issubset(doc_tags):
                    results.append(doc)
            else:
                # 包含任一标签
                if any(tag in doc_tags for tag in tags):
                    results.append(doc)

        return results

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

    def update_tags(self, doc_id: str, tags: List[str]) -> bool:
        """
        更新文档标签

        Args:
            doc_id: 文档ID
            tags: 新的标签列表

        Returns:
            是否更新成功
        """
        if doc_id not in self._registry:
            logger.warning(f"⚠️ 文档不存在: {doc_id}")
            return False

        self._registry[doc_id]["tags"] = tags
        self._save()

        logger.info(f"✅ 更新标签: {doc_id} -> {tags}")
        return True

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

    def get_all_tags(self) -> List[str]:
        """
        获取所有标签（去重）

        Returns:
            标签列表
        """
        all_tags = set()
        for doc in self._registry.values():
            all_tags.update(doc.get("tags", []))

        return sorted(list(all_tags))

    def get_statistics(self) -> Dict:
        """
        获取统计信息

        Returns:
            统计信息字典
        """
        total_docs = self.count()
        all_tags = self.get_all_tags()

        # 按类型统计
        type_counts = {}
        for doc in self._registry.values():
            doc_type = doc.get("doc_type", "unknown")
            type_counts[doc_type] = type_counts.get(doc_type, 0) + 1

        return {
            "total_documents": total_docs,
            "total_tags": len(all_tags),
            "all_tags": all_tags,
            "by_type": type_counts
        }
