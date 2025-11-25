import logging
import os
from typing import List, Dict, Optional, Any, Callable

from langchain.docstore.document import Document
from langchain_community.vectorstores import FAISS

from src.core.llm.client import LLMBase

logging.basicConfig(
    level=logging.INFO,  # 可根据需要改为 DEBUG
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

class VectorDBClient(LLMBase):
    """向量数据库客户端基类"""
    def __init__(self, db_path: str, provider: str = 'openai') -> None:
        super().__init__(provider)
        self.db_path = db_path
        self.vector_db: Optional[FAISS] = None

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

    def search_with_metadata_filter(
        self,
        query: str,
        k: int = 5,
        field_name: Optional[str] = None,
        field_value: Optional[Any] = None,
        fetch_k: Optional[int] = None
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
            if not field_name or field_value is None:
                # 没有过滤条件，执行普通检索
                logger.debug("执行普通向量检索（无过滤条件）")
                return self.vector_db.similarity_search_with_score(query, k=k)
            
            # 创建过滤函数
            filter_func = self.make_metadata_filter(field_name, field_value)

            # 如果使用过滤器但未指定 fetch_k，设置一个足够大的默认值
            if fetch_k is None:
                fetch_k = max(k * 4, 100)
                logger.debug(f"自动设置 fetch_k={fetch_k} (k={k})")

            logger.info(f"执行元数据过滤检索 - 过滤条件: {field_name}={field_value}, fetch_k={fetch_k}")

            # 执行带过滤的检索
            results = self.vector_db.similarity_search_with_score(
                query, k=k, filter=filter_func, fetch_k=fetch_k
            )

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
        fetch_k: Optional[int] = None
    ) -> List[tuple]:
        """
        按PDF名称过滤进行检索的便利方法

        Args:
            query (str): 搜索查询
            pdf_name (str): PDF文档名称
            k (int): 返回结果数量，默认99
            fetch_k (int, optional): 过滤前获取的文档数量

        Returns:
            List[tuple]: 检索结果列表
        """
        return self.search_with_metadata_filter(
            query=query, k=k,
            field_name="pdf_name", field_value=pdf_name,
            fetch_k=fetch_k
        )

    def search_by_title(
        self,
        title: str,
        doc_type: str = "title",
        k: int = 99,
        fetch_k: Optional[int] = None
    ) -> List[tuple]:
        """
        按标题检索文档的便利方法

        Args:
            title (str): 标题（用作搜索查询）
            doc_type (str): 文档类型，默认为 "title"
            k (int): 返回结果数量，默认99
            fetch_k (int, optional): 过滤前获取的文档数量。如果未指定，
                                     默认为 k*4 和 100 中的较大值

        Returns:
            List[tuple]: 检索结果列表
        """
        return self.search_with_metadata_filter(
            query=title, k=k,
            field_name="type", field_value=doc_type,
            fetch_k=fetch_k
        )