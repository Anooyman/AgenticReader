import logging
import os
import hashlib
from typing import List, Dict, Optional, Any, Callable, Set

from langchain.docstore.document import Document
from langchain_community.vectorstores import FAISS

# 注意：不再继承 LLMBase，改用组合模式（依赖注入）

logging.basicConfig(
    level=logging.INFO,  # 可根据需要改为 DEBUG
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

class VectorDBClient:
    """
    向量数据库客户端（纯数据访问层）

    职责：
    - FAISS向量数据库的CRUD操作
    - 元数据过滤检索
    - 去重机制
    - 数据持久化

    使用组合模式，通过依赖注入获取 embedding_model
    """
    def __init__(self, db_path: str, embedding_model) -> None:
        """
        初始化向量数据库客户端

        Args:
            db_path: 向量数据库存储路径
            embedding_model: 外部传入的 embedding 模型实例
                           （通常来自 LLMBase.embedding_model）
        """
        self.db_path = db_path
        self.embedding_model = embedding_model  # 组合模式，注入依赖
        self.vector_db: Optional[FAISS] = None

        # 用于存储已检索文档的哈希值，防止重复检索
        self._retrieved_doc_hashes: Set[str] = set()

        # 尝试自动加载已存在的向量数据库
        if os.path.exists(db_path):
            try:
                self.load_vector_db()
                logger.info(f"✅ 成功加载已存在的向量数据库: {db_path}")
            except Exception as e:
                logger.warning(f"⚠️ 加载向量数据库失败（可能尚未创建）: {e}")
                self.vector_db = None

    def build_vector_db(self, content_docs: List[Document]) -> FAISS:
        """
        构建向量数据库。
        Build a vector database from document list.
        Args:
            content_docs (List[Document]): 文档列表。
        Returns:
            FAISS: 构建的向量数据库对象。
        """
        logger.info(f"开始构建向量数据库，文档数: {len(content_docs)}")
        self.vector_db = FAISS.from_documents(content_docs, self.embedding_model)
        self.vector_db.save_local(self.db_path)
        logger.info(f"向量数据库已保存到: {self.db_path}")
 
    def load_vector_db(self) -> FAISS:
        """
        加载本地向量数据库。
        Load local vector database.
        Args:
            vector_db_path: 向量数据库路径。
        Returns:
            FAISS: 加载的向量数据库对象。
        """
        logger.info(f"加载本地向量数据库: {self.db_path}")
        self.vector_db = FAISS.load_local(self.db_path, self.embedding_model, allow_dangerous_deserialization=True)

    def add_data(self, vector_db, data_docs):
        """
        向现有向量数据库添加新文档

        Args:
            vector_db (FAISS): 向量数据库实例
            data_docs: 要添加的文档列表
        """
        vector_db.add_documents(data_docs)
        vector_db.save_local(self.db_path)
        # 如果传入的是当前实例的 vector_db，保持同步
        if vector_db is self.vector_db:
            logger.info(f"已添加 {len(data_docs)} 个文档到向量数据库")

    def make_metadata_filter(self, field_name: str, target_value: str) -> Callable[[Dict[str, Any]], bool]:
        """
        创建元数据过滤函数

        生成一个用于向量数据库检索的元数据过滤函数，
        该函数检查指定字段是否包含目标值。

        Args:
            field_name (str): 要过滤的元数据字段名 (如 "pdf_name", "location", "person")
            target_value (str): 目标值

        Returns:
            Callable: 元数据过滤函数，接受metadata参数，返回bool值

        使用示例:
        ```python
        filter_func = client.make_metadata_filter("pdf_name", "research_paper")
        results = vector_db.similarity_search_with_score(
            query, k=5, filter=filter_func
        )
        ```
        """
        def metadata_filter(metadata: Dict[str, Any]) -> bool:
            field_data = metadata.get(field_name, [])

            # 处理字符串和列表两种格式
            if isinstance(target_value, str):
                # 单个目标值
                if isinstance(field_data, str):
                    return target_value == field_data
                elif isinstance(field_data, list):
                    return target_value in field_data
                else:
                    return False

            elif isinstance(target_value, list):
                # 多个目标值，只要匹配其中一个即可
                if isinstance(field_data, str):
                    return field_data in target_value
                elif isinstance(field_data, list):
                    return any(item in field_data for item in target_value)
                else:
                    return False
            else:
                return False

        logger.debug(f"创建元数据过滤器 - 字段: {field_name}, 目标值: {target_value}")
        return metadata_filter

    def make_dedup_filter(self) -> Callable[[Dict[str, Any]], bool]:
        """
        创建去重过滤函数

        生成一个用于向量数据库检索的去重过滤函数，
        该函数检查文档内容是否已被检索过。

        Returns:
            Callable: 去重过滤函数，接受metadata参数，返回bool值

        使用示例:
        ```python
        dedup_filter = client.make_dedup_filter()
        results = vector_db.similarity_search_with_score(
            query, k=5, filter=dedup_filter
        )
        ```
        """
        def dedup_filter(metadata: Dict[str, Any]) -> bool:
            # 获取文档内容
            refactor_data = metadata.get("refactor", "")

            # 如果内容为空，允许通过
            if not refactor_data:
                return True

            # 检查是否已检索过
            return not self.is_document_retrieved(refactor_data)

        logger.debug("创建去重过滤器")
        return dedup_filter

    def combine_filters(self, *filters: Callable[[Dict[str, Any]], bool]) -> Callable[[Dict[str, Any]], bool]:
        """
        组合多个过滤函数

        将多个过滤函数组合成一个，所有过滤条件必须同时满足（AND 逻辑）。

        Args:
            *filters: 多个过滤函数

        Returns:
            Callable: 组合后的过滤函数

        使用示例:
        ```python
        metadata_filter = client.make_metadata_filter("type", "context")
        dedup_filter = client.make_dedup_filter()
        combined_filter = client.combine_filters(metadata_filter, dedup_filter)
        results = vector_db.similarity_search_with_score(
            query, k=5, filter=combined_filter
        )
        ```
        """
        def combined_filter(metadata: Dict[str, Any]) -> bool:
            # 所有过滤器都必须通过
            return all(f(metadata) for f in filters)

        logger.debug(f"组合了 {len(filters)} 个过滤器")
        return combined_filter

    def search_with_metadata_filter(
        self,
        query: str,
        k: int = 5,
        field_name: Optional[str] = None,
        field_value: Optional[Any] = None,
        fetch_k: Optional[int] = None,
        enable_dedup: bool = True
    ) -> List[tuple]:
        """
        使用元数据过滤进行向量检索

        Args:
            query (str): 搜索查询
            k (int): 返回结果数量，默认5
            field_name (str, optional): 字段名
            field_value (Any, optional): 字段值
            fetch_k (int, optional): 过滤前获取的文档数量。如果使用过滤器但未指定，
                                     默认为 k*4 和 100 中的较大值，以确保有足够的候选文档
            enable_dedup (bool): 是否启用去重过滤，默认 True

        Returns:
            List[tuple]: 检索结果列表，每个元素为 (Document, score) 格式

        使用示例:
        ```python
        results = client.search_with_metadata_filter(
            query="查询内容", k=5,
            field_name="type", field_value="title"
        )
        ```
        """
        if self.vector_db is None:
            raise ValueError("向量数据库未加载，请先调用 load_vector_db() 或 build_vector_db()")

        try:
            # 构建过滤器列表
            filters = []

            # 添加元数据过滤器
            if field_name and field_value is not None:
                metadata_filter = self.make_metadata_filter(field_name, field_value)
                filters.append(metadata_filter)

            # 添加去重过滤器
            if enable_dedup:
                dedup_filter = self.make_dedup_filter()
                filters.append(dedup_filter)

            # 根据是否有过滤器决定检索策略
            if not filters:
                # 没有过滤条件，执行普通检索
                logger.debug("执行普通向量检索（无过滤条件）")
                results = self.vector_db.similarity_search_with_score(query, k=k)
            else:
                # 组合所有过滤器
                combined_filter = self.combine_filters(*filters)

                # 如果使用过滤器但未指定 fetch_k，设置一个足够大的默认值
                # 因为启用了去重，需要更大的候选池
                if fetch_k is None:
                    # 根据是否启用去重调整 fetch_k
                    multiplier = 8 if enable_dedup else 4
                    fetch_k = max(k * multiplier, 100)
                    logger.debug(f"自动设置 fetch_k={fetch_k} (k={k}, 去重={'启用' if enable_dedup else '禁用'})")

                filter_desc = []
                if field_name:
                    filter_desc.append(f"{field_name}={field_value}")
                if enable_dedup:
                    filter_desc.append("去重")
                logger.info(f"执行过滤检索 - 条件: {', '.join(filter_desc)}, fetch_k={fetch_k}")

                # 执行带过滤的检索
                results = self.vector_db.similarity_search_with_score(
                    query, k=k, filter=combined_filter, fetch_k=fetch_k
                )

            # 将检索到的文档标记为已检索
            if enable_dedup and results:
                for doc_item in results:
                    document = doc_item[0] if isinstance(doc_item, tuple) else doc_item
                    refactor_data = document.metadata.get("refactor", "")
                    if refactor_data:
                        self.mark_document_as_retrieved(refactor_data)

            logger.info(f"过滤检索完成，返回 {len(results)} 个结果")
            return results

        except Exception as e:
            logger.error(f"元数据过滤检索失败: {e}")
            # 失败时执行普通检索作为备选
            logger.info("执行备选普通检索")
            return self.vector_db.similarity_search_with_score(query, k=k)

    def search_by_pdf_name(
        self,
        query: str,
        pdf_name: str,
        k: int = 99,
        fetch_k: Optional[int] = None,
        enable_dedup: bool = True
    ) -> List[tuple]:
        """
        按PDF名称过滤进行检索的便利方法

        Args:
            query (str): 搜索查询
            pdf_name (str): PDF文档名称
            k (int): 返回结果数量，默认99
            fetch_k (int, optional): 过滤前获取的文档数量
            enable_dedup (bool): 是否启用去重过滤，默认 True

        Returns:
            List[tuple]: 检索结果列表
        """
        return self.search_with_metadata_filter(
            query=query, k=k,
            field_name="pdf_name", field_value=pdf_name,
            fetch_k=fetch_k,
            enable_dedup=enable_dedup
        )

    def search_by_title(
        self,
        title: str,
        doc_type: str = "title",
        k: int = 1,
        fetch_k: Optional[int] = None,
        enable_dedup: bool = True
    ) -> List[tuple]:
        """
        按标题检索文档的便利方法

        Args:
            title (str): 标题（用作搜索查询）
            doc_type (str): 文档类型，默认为 "title"
            k (int): 返回结果数量，默认99
            fetch_k (int, optional): 过滤前获取的文档数量。如果未指定，
                                     默认为 k*4 和 100 中的较大值
            enable_dedup (bool): 是否启用去重过滤，默认 True

        Returns:
            List[tuple]: 检索结果列表
        """
        return self.search_with_metadata_filter(
            query=title, k=k,
            field_name="type", field_value=doc_type,
            fetch_k=fetch_k,
            enable_dedup=enable_dedup
        )

    def _compute_document_hash(self, content: str) -> str:
        """
        计算文档内容的哈希值

        使用 SHA256 对文档内容进行哈希，用于去重检测。

        Args:
            content (str): 文档内容

        Returns:
            str: 十六进制格式的哈希值
        """
        if not content:
            return ""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def is_document_retrieved(self, content: str) -> bool:
        """
        检查文档是否已被检索过

        Args:
            content (str): 文档内容

        Returns:
            bool: True 表示已检索过，False 表示未检索过
        """
        if not content:
            return False
        doc_hash = self._compute_document_hash(content)
        return doc_hash in self._retrieved_doc_hashes

    def mark_document_as_retrieved(self, content: str) -> None:
        """
        将文档标记为已检索

        Args:
            content (str): 文档内容
        """
        if content:
            doc_hash = self._compute_document_hash(content)
            self._retrieved_doc_hashes.add(doc_hash)
            logger.debug(f"文档已标记为已检索 (hash: {doc_hash[:8]}...)")

    def reset_retrieval_history(self) -> None:
        """
        重置检索历史

        清除所有已检索文档的哈希记录，允许在新的查询会话中重新检索相同的文档。
        建议在开始新的用户查询会话时调用此方法。
        """
        count = len(self._retrieved_doc_hashes)
        self._retrieved_doc_hashes.clear()
        logger.info(f"✅ 已重置检索历史，清除了 {count} 个文档哈希记录")

    def get_retrieval_stats(self) -> Dict[str, int]:
        """
        获取检索统计信息

        Returns:
            Dict[str, int]: 包含已检索文档数量的统计信息
        """
        return {
            "retrieved_documents_count": len(self._retrieved_doc_hashes)
        }

