import logging
import os
import hashlib
from typing import List, Dict, Optional, Any, Callable

from langchain.docstore.document import Document
from langchain_community.vectorstores import FAISS

from src.config.constants import RetrievalDedupConfig

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
        # 结构：doc_hash -> 最近一次命中的对话轮次号
        # 仅保留最近 RETRIEVAL_DEDUP_WINDOW 轮的记录，更早的记录自动淘汰，
        # 避免多轮对话中检索空间被去重集合单调收窄
        self._retrieved_doc_hashes: Dict[str, int] = {}

        # 当前对话轮次（由检索链路在检索前同步进来，默认第 0 轮）
        self._current_turn: int = 0

        # 尝试自动加载已存在的向量数据库
        # 检查 index.faiss 文件是否存在（而不仅仅是目录）
        index_file = os.path.join(db_path, "index.faiss")
        if os.path.exists(index_file):
            try:
                self.load_vector_db()
                logger.info(f"✅ 成功加载已存在的向量数据库: {db_path}")
            except Exception as e:
                logger.warning(f"⚠️ 加载向量数据库失败（可能已损坏）: {e}")
                self.vector_db = None
        elif os.path.exists(db_path):
            logger.debug(f"📁 向量数据库目录存在但索引文件未创建: {db_path}")

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
        try:
            self.vector_db = FAISS.load_local(self.db_path, self.embedding_model, allow_dangerous_deserialization=True)

            # 验证embedding维度是否匹配
            if hasattr(self.vector_db, 'index') and hasattr(self.vector_db.index, 'd'):
                stored_dim = self.vector_db.index.d
                # 获取当前embedding模型的维度
                test_embedding = self.embedding_model.embed_query("test")
                current_dim = len(test_embedding)

                if stored_dim != current_dim:
                    error_msg = (
                        f"❌ Embedding维度不匹配！\n"
                        f"向量数据库维度: {stored_dim}\n"
                        f"当前Embedding模型维度: {current_dim}\n"
                        f"数据库路径: {self.db_path}\n\n"
                        f"可能原因：\n"
                        f"1. 索引时使用的embedding模型与当前配置的模型不同\n"
                        f"2. embedding模型配置已更改\n\n"
                        f"解决方案：\n"
                        f"1. 使用与索引时相同的embedding模型配置\n"
                        f"2. 删除旧的向量数据库并重新索引文档\n"
                        f"   删除路径: {self.db_path}\n"
                        f"   重新运行索引命令"
                    )
                    logger.error(error_msg)
                    raise ValueError(error_msg)

                logger.info(f"✅ Embedding维度验证通过: {current_dim}")
        except ValueError:
            # 重新抛出维度不匹配错误
            raise
        except Exception as e:
            logger.error(f"❌ 加载向量数据库失败: {e}")
            raise

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
        enable_dedup: bool = True,
        conversation_turn: Optional[int] = None
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
            conversation_turn (int, optional): 当前对话轮次。传入后会用它更新
                                     去重窗口（更老的命中记录会被淘汰）；
                                     不传则沿用客户端已有的轮次

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
            # 检查当前对话轮次：如果上层显式传入，则同步进来
            # （轮次变化时会自动淘汰超出窗口的旧去重记录）
            if conversation_turn is not None:
                self.set_current_turn(conversation_turn)

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

        except AssertionError as e:
            # FAISS 维度不匹配错误
            if hasattr(self.vector_db, 'index') and hasattr(self.vector_db.index, 'd'):
                stored_dim = self.vector_db.index.d
                test_embedding = self.embedding_model.embed_query("test")
                current_dim = len(test_embedding)

                error_msg = (
                    f"❌ Embedding维度不匹配！\n"
                    f"向量数据库维度: {stored_dim}\n"
                    f"当前Embedding模型维度: {current_dim}\n"
                    f"数据库路径: {self.db_path}\n\n"
                    f"请删除旧的向量数据库并重新索引文档，或使用与索引时相同的embedding模型。"
                )
                logger.error(error_msg)
                raise ValueError(error_msg) from e
            else:
                raise

        except Exception as e:
            logger.error(f"元数据过滤检索失败: {e}")
            # 维度不匹配 / 参数非法等严重错误一律上抛，不做任何降级
            if isinstance(e, (ValueError, AssertionError)):
                raise

            # 兜底策略（防御性）：
            #   1) 字段过滤（type / pdf_name / doc_id 等）必须保留——它决定结果归属，
            #      一旦丢失，调用方拿到的就是未经筛选的噪声；
            #   2) 去重过滤只是"尽力而为"，允许在降级时放宽（仅影响重复率，不影响归属）；
            #   3) 若既没有字段过滤、也没有去重可放宽，"兜底"就等价于
            #      similarity_search_with_score(query, k)——完全无过滤的检索，
            #      会被调用方误当成正常结果，因此直接抛原始异常交上层处理。
            if not (field_name and field_value is not None):
                logger.error(
                    f"❌ 过滤检索失败且无字段过滤可保留（field_name={field_name}），"
                    f"拒绝无过滤兜底，抛出原始异常由上层处理"
                )
                raise
            # 若本次就没启用去重，则降级路径与正常路径参数完全一致，
            # 重试只是白跑一遍——同样抛原始异常，由上层决定重试或降级策略。
            if not enable_dedup:
                logger.error(
                    f"❌ 过滤检索失败且本次未启用去重，无放宽空间"
                    f"（{field_name}={field_value}），拒绝无意义重试，抛出原始异常"
                )
                raise

            # 唯一的降级形态：保留字段过滤、放宽去重，并明确标记——
            # 调用方即便把返回值当"正常"，也应能从日志看到「降级」告警。
            logger.warning(
                f"⚠️ [降级检索] 组合过滤检索失败，降级为「仅保留字段过滤 "
                f"{field_name}={field_value}」的检索（去重被放宽，非正常结果，"
                f"原始异常: {e}）"
            )
            try:
                metadata_filter = self.make_metadata_filter(field_name, field_value)
                fallback_fetch_k = fetch_k if fetch_k is not None else max(k * 4, 100)
                results = self.vector_db.similarity_search_with_score(
                    query, k=k, filter=metadata_filter, fetch_k=fallback_fetch_k
                )
                logger.warning(
                    f"⚠️ [降级检索] 完成，返回 {len(results)} 个结果"
                    f"（字段过滤仍生效，但去重未生效，请勿按正常去重结果使用）"
                )
                return results
            except Exception as fallback_error:
                # 保留字段过滤后仍然失败，说明检索本身不可用，不再兜底
                logger.error(f"❌ 降级检索同样失败: {fallback_error}，抛出原始异常")
                raise

    def search_by_pdf_name(
        self,
        query: str,
        pdf_name: str,
        k: int = 99,
        fetch_k: Optional[int] = None,
        enable_dedup: bool = True,
        conversation_turn: Optional[int] = None
    ) -> List[tuple]:
        """
        按PDF名称过滤进行检索的便利方法

        Args:
            query (str): 搜索查询
            pdf_name (str): PDF文档名称
            k (int): 返回结果数量，默认99
            fetch_k (int, optional): 过滤前获取的文档数量
            enable_dedup (bool): 是否启用去重过滤，默认 True
            conversation_turn (int, optional): 当前对话轮次，透传给底层检索

        Returns:
            List[tuple]: 检索结果列表
        """
        return self.search_with_metadata_filter(
            query=query, k=k,
            field_name="pdf_name", field_value=pdf_name,
            fetch_k=fetch_k,
            enable_dedup=enable_dedup,
            conversation_turn=conversation_turn
        )

    def search_by_title(
        self,
        title: str,
        doc_type: str = "title",
        k: int = 1,
        fetch_k: Optional[int] = None,
        enable_dedup: bool = True,
        conversation_turn: Optional[int] = None
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
            conversation_turn (int, optional): 当前对话轮次，透传给底层检索

        Returns:
            List[tuple]: 检索结果列表
        """
        return self.search_with_metadata_filter(
            query=title, k=k,
            field_name="type", field_value=doc_type,
            fetch_k=fetch_k,
            enable_dedup=enable_dedup,
            conversation_turn=conversation_turn
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

    def set_current_turn(self, turn: int) -> None:
        """
        设置当前对话轮次

        轮次变化时会自动淘汰超出窗口的旧去重记录，
        因此对话再久去重集合也不会无限增长、导致检索空间单调收窄。

        Args:
            turn (int): 当前对话轮次（从 0 开始）
        """
        if not isinstance(turn, int) or turn < 0:
            logger.debug(f"忽略非法的对话轮次值: {turn!r}")
            return

        if turn < self._current_turn:
            # 轮次回退意味着这是一个新的对话会话：整体清空去重历史
            logger.info(
                f"🔄 检测到对话轮次回退（{self._current_turn} → {turn}），"
                f"按新会话清空检索去重历史"
            )
            self._retrieved_doc_hashes.clear()
            self._current_turn = turn
            return

        if turn == self._current_turn:
            return

        self._current_turn = turn
        logger.debug(f"🔄 检索去重轮次更新为第 {turn} 轮")
        self._prune_expired_dedup_records()

    def _prune_expired_dedup_records(self) -> int:
        """
        淘汰超出窗口（最近 RETRIEVAL_DEDUP_WINDOW 轮）的旧去重记录

        记录本身按命中轮次单调递增，因此可从队首连续淘汰。

        Returns:
            int: 被淘汰的记录数量
        """
        window = max(int(getattr(RetrievalDedupConfig, "WINDOW", 5)), 1)
        cutoff_turn = self._current_turn - window + 1
        if cutoff_turn <= 0:
            return 0

        removed = 0
        for doc_hash in list(self._retrieved_doc_hashes.keys()):
            if self._retrieved_doc_hashes[doc_hash] < cutoff_turn:
                # 该记录已超出窗口：后续轮次会重新把它视为“未检索过”
                del self._retrieved_doc_hashes[doc_hash]
                removed += 1
            else:
                # 轮次递增序列，后续都不会再落入过期区间
                break

        if removed:
            logger.info(
                f"🧹 检索去重窗口淘汰：第 {self._current_turn} 轮，"
                f"丢弃 {removed} 条超出 {window} 轮窗口的旧命中记录，"
                f"剩余 {len(self._retrieved_doc_hashes)} 条"
            )
        return removed

    def is_document_retrieved(self, content: str) -> bool:
        """
        检查文档在当前去重窗口内是否已被检索过

        Args:
            content (str): 文档内容

        Returns:
            bool: True 表示窗口内已检索过，False 表示窗口内未检索过
        """
        if not content:
            return False
        doc_hash = self._compute_document_hash(content)
        hit_turn = self._retrieved_doc_hashes.get(doc_hash)
        if hit_turn is None:
            return False

        # 超出窗口的记录不再视为“已检索过”（正常已由淘汰逻辑清理，这里兜底）
        window = max(int(getattr(RetrievalDedupConfig, "WINDOW", 5)), 1)
        if self._current_turn - hit_turn >= window:
            self._retrieved_doc_hashes.pop(doc_hash, None)
            return False
        return True

    def mark_document_as_retrieved(self, content: str) -> None:
        """
        将文档标记为已检索（记录为当前对话轮次）

        Args:
            content (str): 文档内容
        """
        if content:
            doc_hash = self._compute_document_hash(content)
            # 重新命中时移到末尾，保证淘汰时队首始终是最早命中的记录
            self._retrieved_doc_hashes.pop(doc_hash, None)
            self._retrieved_doc_hashes[doc_hash] = self._current_turn
            logger.debug(f"文档已标记为已检索 (轮次: {self._current_turn}, hash: {doc_hash[:8]}...)")
            self._prune_expired_dedup_records()

    def reset_retrieval_history(self) -> None:
        """
        重置检索历史

        清除所有已检索文档的轮次记录并复位轮次计数，允许在新的查询会话中
        重新检索相同的文档。
        建议在新会话开始 / 切换文档 / 清空对话历史时调用此方法。
        """
        count = len(self._retrieved_doc_hashes)
        self._retrieved_doc_hashes.clear()
        self._current_turn = 0
        logger.info(f"✅ 已重置检索历史，清除了 {count} 个文档哈希记录（轮次归零）")

    def get_retrieval_stats(self) -> Dict[str, int]:
        """
        获取检索统计信息

        Returns:
            Dict[str, int]: 包含已检索文档数量、当前轮次与去重窗口的统计信息
        """
        return {
            "retrieved_documents_count": len(self._retrieved_doc_hashes),
            "current_turn": self._current_turn,
            "dedup_window": max(int(getattr(RetrievalDedupConfig, "WINDOW", 5)), 1)
        }

