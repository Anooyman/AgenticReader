"""
文档元数据向量数据库

存储和检索文档元数据的语义向量，用于智能文档选择
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class MetadataVectorDB:
    """文档元数据向量数据库"""

    def __init__(self):
        """初始化元数据向量数据库"""
        from src.config.settings import DATA_ROOT

        self.index_path = Path(DATA_ROOT) / "vector_db" / "_metadata"
        self.vector_client = None
        self._initialize()

    def _initialize(self):
        """初始化向量数据库"""
        from src.core.vector_db.vector_db_client import VectorDBClient
        from src.core.llm import get_embeddings

        # 确保目录存在
        self.index_path.mkdir(parents=True, exist_ok=True)

        # 获取 embedding 模型
        embedding_model = get_embeddings()

        # 创建 VectorDBClient（会自动尝试加载已存在的数据库）
        try:
            self.vector_client = VectorDBClient(
                db_path=str(self.index_path),
                embedding_model=embedding_model
            )
            logger.info(f"✅ 初始化元数据向量数据库: {self.index_path}")
        except Exception as e:
            logger.error(f"❌ 初始化向量数据库失败: {e}")
            self.vector_client = None

    def document_exists(self, doc_id: str) -> bool:
        """
        检查文档是否已存在于元数据向量数据库

        Args:
            doc_id: 文档ID

        Returns:
            bool: 是否存在
        """
        if not self.vector_client or not self.vector_client.vector_db:
            return False

        try:
            # 使用元数据过滤搜索，查找指定 doc_id
            from src.core.document_management import DocumentRegistry

            registry = DocumentRegistry()
            doc_info = registry.get(doc_id)

            if not doc_info:
                return False

            doc_name = doc_info.get("doc_name")

            # 搜索该文档名，检查是否存在
            results = self.vector_client.search_with_metadata_filter(
                query=doc_name,
                k=10,
                field_name="doc_id",
                field_value=doc_id,
                enable_dedup=False
            )

            exists = len(results) > 0
            if exists:
                logger.debug(f"📌 [MetadataDB] 文档已存在: {doc_name} (ID: {doc_id})")

            return exists

        except Exception as e:
            logger.debug(f"❌ [MetadataDB] 检查文档是否存在失败: {e}")
            return False

    def add_document(self, doc_id: str, doc_name: str, embedding_summary: str, update_if_exists: bool = True):
        """
        添加文档到元数据索引（支持去重）

        Args:
            doc_id: 文档ID
            doc_name: 文档名称
            embedding_summary: 用于向量化的文本（title + keywords + abstract）
            update_if_exists: 如果文档已存在，是否更新（删除旧的再添加新的）
        """
        if not self.vector_client:
            logger.error("❌ [MetadataDB] 向量数据库未初始化")
            return

        if not embedding_summary or not embedding_summary.strip():
            logger.warning(f"⚠️ [MetadataDB] 文档 {doc_name} 的 embedding_summary 为空，跳过")
            return

        try:
            # 检查是否已存在
            if update_if_exists and self.document_exists(doc_id):
                logger.info(f"🔄 [MetadataDB] 文档 {doc_name} 已存在，将更新元数据")
                # 删除旧的元数据（通过重建索引）
                self.delete_document(doc_id)

            from langchain.docstore.document import Document

            # 使用特殊的 type="metadata" 标记
            metadata = {
                "type": "metadata",
                "doc_id": doc_id,
                "doc_name": doc_name,
                "refactor": embedding_summary  # 复用现有字段
            }

            # 创建 Document 对象
            doc = Document(
                page_content=embedding_summary,
                metadata=metadata
            )

            # 添加到向量数据库
            if self.vector_client.vector_db is None:
                # 第一次添加，构建数据库
                self.vector_client.build_vector_db([doc])
                logger.info(f"✅ [MetadataDB] 创建元数据向量数据库并添加文档: {doc_name}")
            else:
                # 已有数据库，添加新文档
                self.vector_client.add_data(self.vector_client.vector_db, [doc])
                logger.info(f"✅ [MetadataDB] 添加文档元数据到向量索引: {doc_name} (ID: {doc_id})")

        except Exception as e:
            logger.error(f"❌ [MetadataDB] 添加文档失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    def search_similar_docs(
        self,
        query: str,
        top_k: int = 10,
        enable_dedup: bool = False
    ) -> List[Dict[str, Any]]:
        """
        根据查询语义搜索相关文档

        Args:
            query: 搜索查询
            top_k: 返回文档数量
            enable_dedup: 是否去重（元数据检索通常不需要）

        Returns:
        [
            {
                "doc_id": "xxx",
                "doc_name": "xxx",
                "similarity_score": 0.85,
                "metadata": {...}
            },
            ...
        ]
        """
        if not self.vector_client:
            logger.error("❌ [MetadataDB] 向量数据库未初始化")
            return []

        if not query or not query.strip():
            logger.warning("⚠️ [MetadataDB] 查询字符串为空")
            return []

        try:
            logger.info(f"🔍 [MetadataDB] 检索相关文档: {query[:50]}...")

            # 在向量数据库中检索（type="metadata"）
            doc_res = self.vector_client.search_with_metadata_filter(
                query=query,
                k=top_k,
                field_name="type",
                field_value="metadata",
                enable_dedup=enable_dedup
            )

            if not doc_res or len(doc_res) == 0:
                logger.warning("⚠️ [MetadataDB] 未找到任何相关文档")
                return []

            # 解析结果
            from src.core.document_management import DocumentRegistry

            registry = DocumentRegistry()
            similar_docs = []

            for idx, doc_item in enumerate(doc_res):
                try:
                    # search_with_metadata_filter 返回 (Document, score) tuple
                    if isinstance(doc_item, tuple) and len(doc_item) >= 2:
                        document = doc_item[0]
                        score = doc_item[1]
                    else:
                        # 兼容其他格式
                        document = doc_item[0] if isinstance(doc_item, tuple) else doc_item
                        score = 1.0

                    metadata = document.metadata
                    doc_id = metadata.get("doc_id")
                    doc_name = metadata.get("doc_name", "未知文档")

                    if not doc_id:
                        logger.warning(f"⚠️ [MetadataDB] 第 {idx+1} 个结果缺少 doc_id，跳过")
                        continue

                    # 从 registry 获取完整文档信息
                    doc_info = registry.get(doc_id)
                    if doc_info:
                        similar_docs.append({
                            "doc_id": doc_id,
                            "doc_name": doc_info["doc_name"],
                            "similarity_score": float(score),  # 余弦相似度分数
                            "metadata": doc_info.get("metadata_enhanced", {})
                        })
                    else:
                        logger.warning(f"⚠️ [MetadataDB] 文档 {doc_id} 在注册表中不存在")

                except Exception as e:
                    logger.error(f"❌ [MetadataDB] 处理第 {idx+1} 个检索结果失败: {e}")
                    import traceback
                    logger.debug(traceback.format_exc())
                    continue

            logger.info(f"✅ [MetadataDB] 检索完成，返回 {len(similar_docs)} 个相关文档")

            return similar_docs

        except Exception as e:
            logger.error(f"❌ [MetadataDB] 检索失败: {e}", exc_info=True)
            return []

    def delete_document(self, doc_id: str) -> bool:
        """
        删除文档的元数据

        通过重建索引实现删除（过滤掉要删除的文档）

        Args:
            doc_id: 文档ID

        Returns:
            bool: 是否成功删除
        """
        if not self.vector_client:
            logger.error("❌ [MetadataDB] 向量数据库未初始化")
            return False

        try:
            from src.core.document_management import DocumentRegistry

            # 获取文档名用于日志
            registry = DocumentRegistry()
            doc_info = registry.get(doc_id)
            doc_name = doc_info.get("doc_name", "未知") if doc_info else "未知"

            logger.info(f"🗑️  [MetadataDB] 开始删除文档元数据: {doc_name} (ID: {doc_id})")

            # 获取所有文档（从 DocumentRegistry）
            all_docs = registry.list_all()

            if not all_docs:
                logger.warning(f"⚠️  [MetadataDB] 文档注册表为空")
                return False

            # 过滤掉要删除的文档，重建索引
            from langchain.docstore.document import Document

            documents = []
            excluded_count = 0

            for doc in all_docs:
                current_doc_id = doc.get("doc_id")
                current_doc_name = doc.get("doc_name")
                metadata_enhanced = doc.get("metadata_enhanced", {})

                # 跳过要删除的文档
                if current_doc_id == doc_id:
                    excluded_count += 1
                    logger.debug(f"   - 跳过文档: {current_doc_name} (ID: {doc_id})")
                    continue

                # 只添加有 embedding_summary 的文档
                embedding_summary = metadata_enhanced.get("embedding_summary", "")
                if embedding_summary and embedding_summary.strip():
                    metadata = {
                        "type": "metadata",
                        "doc_id": current_doc_id,
                        "doc_name": current_doc_name,
                        "refactor": embedding_summary
                    }
                    documents.append(Document(
                        page_content=embedding_summary,
                        metadata=metadata
                    ))

            # 重建向量数据库
            if documents:
                # 清空现有索引
                import shutil
                if self.index_path.exists():
                    shutil.rmtree(self.index_path)
                self.index_path.mkdir(parents=True, exist_ok=True)

                # 重新初始化
                self._initialize()

                if not self.vector_client:
                    logger.error("❌ [MetadataDB] 重新初始化失败")
                    return False

                # 批量构建
                self.vector_client.build_vector_db(documents)
                logger.info(f"✅ [MetadataDB] 元数据索引已重建，排除了 {excluded_count} 个文档")
                logger.info(f"   - 剩余文档数: {len(documents)}")
            else:
                # 没有剩余文档，清空索引
                import shutil
                if self.index_path.exists():
                    shutil.rmtree(self.index_path)
                logger.info(f"✅ [MetadataDB] 元数据索引已清空（无剩余文档）")

            return True

        except Exception as e:
            logger.error(f"❌ [MetadataDB] 删除文档失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False

    def rebuild_index(self):
        """
        重建整个元数据索引

        从 DocumentRegistry 读取所有文档的元数据，重新构建向量索引
        """
        from src.core.document_management import DocumentRegistry
        from langchain.docstore.document import Document

        logger.info("🔄 [MetadataDB] 开始重建元数据索引")

        try:
            # 清空现有索引
            import shutil
            if self.index_path.exists():
                shutil.rmtree(self.index_path)
            self.index_path.mkdir(parents=True, exist_ok=True)

            # 重新初始化
            self._initialize()

            if not self.vector_client:
                logger.error("❌ [MetadataDB] 重新初始化失败")
                return

            # 从注册表获取所有文档
            registry = DocumentRegistry()
            all_docs = registry.list_all()

            logger.info(f"📚 [MetadataDB] 找到 {len(all_docs)} 个文档")

            # 收集所有有效的文档
            documents = []
            for doc in all_docs:
                doc_id = doc.get("doc_id")
                doc_name = doc.get("doc_name")
                metadata_enhanced = doc.get("metadata_enhanced", {})

                embedding_summary = metadata_enhanced.get("embedding_summary", "")

                if embedding_summary and embedding_summary.strip():
                    # 创建 Document 对象
                    metadata = {
                        "type": "metadata",
                        "doc_id": doc_id,
                        "doc_name": doc_name,
                        "refactor": embedding_summary
                    }
                    documents.append(Document(
                        page_content=embedding_summary,
                        metadata=metadata
                    ))
                else:
                    logger.warning(f"⚠️ [MetadataDB] 文档 {doc_name} 缺少 embedding_summary，跳过")

            # 批量构建向量数据库
            if documents:
                self.vector_client.build_vector_db(documents)
                logger.info(f"✅ [MetadataDB] 元数据索引重建完成，共添加 {len(documents)} 个文档")
            else:
                logger.warning("⚠️ [MetadataDB] 没有可用的文档元数据")

        except Exception as e:
            logger.error(f"❌ [MetadataDB] 重建索引失败: {e}", exc_info=True)

    def get_stats(self) -> Dict[str, Any]:
        """
        获取元数据数据库统计信息

        Returns:
            统计信息字典
        """
        stats = {
            "index_path": str(self.index_path),
            "index_exists": (self.index_path / "index.faiss").exists(),
            "total_documents": 0
        }

        if self.vector_client and self.vector_client.vector_db:
            try:
                # 尝试获取文档数量
                # FAISS 向量数据库的 index 属性
                if hasattr(self.vector_client.vector_db, 'index'):
                    faiss_index = self.vector_client.vector_db.index
                    if hasattr(faiss_index, 'ntotal'):
                        stats["total_documents"] = faiss_index.ntotal
            except Exception as e:
                logger.debug(f"获取统计信息失败: {e}")

        return stats
