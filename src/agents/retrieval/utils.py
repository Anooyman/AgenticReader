"""
RetrievalAgent 辅助方法

内部辅助工具，不对外暴露
"""

from typing import Dict, Any, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .agent import RetrievalAgent

logger = logging.getLogger(__name__)


class RetrievalUtils:
    """RetrievalAgent 辅助工具集合"""

    def __init__(self, agent: 'RetrievalAgent'):
        """
        Args:
            agent: RetrievalAgent实例（依赖注入）
        """
        self.agent = agent

    def get_db_path_from_doc_name(self, doc_name: str) -> str:
        """
        将文档名称转换为向量数据库路径

        Args:
            doc_name: 文档名称

        Returns:
            向量数据库的完整路径
        """
        from pathlib import Path
        from src.config.settings import DATA_ROOT

        # 注意：必须与 IndexingAgent 的路径格式保持一致
        db_path = Path(DATA_ROOT) / "vector_db" / f"{doc_name}_data_index"
        return str(db_path)

    def create_vector_db_client(self, doc_name: str):
        """
        创建 VectorDBClient 实例

        Args:
            doc_name: 文档名称

        Returns:
            VectorDBClient: 向量数据库客户端实例
        """
        from src.core.vector_db.vector_db_client import VectorDBClient

        db_path = self.get_db_path_from_doc_name(doc_name)

        # 使用依赖注入，传入 embedding_model
        client = VectorDBClient(
            db_path=db_path,
            embedding_model=self.agent.embedding_model
        )

        logger.info(f"✅ [VectorDB] 已创建向量数据库客户端: {doc_name}")
        return client

    def get_agenda_dict_from_vector_db(self) -> Dict[str, Any]:
        """
        从向量数据库获取 agenda_dict（内部方法）

        从 type="structure" 文档中提取 agenda_dict 元数据。

        Returns:
            agenda_dict 字典，如果获取失败返回空字典
        """
        if not self.agent.vector_db_client:
            logger.warning("⚠️ [_get_agenda_dict_from_vector_db] VectorDBClient 未初始化")
            return {}

        try:
            doc_res = self.agent.vector_db_client.search_with_metadata_filter(
                query="",
                k=1,
                field_name="type",
                field_value="structure",
                enable_dedup=False
            )

            if doc_res and len(doc_res) > 0:
                document = doc_res[0][0] if isinstance(doc_res[0], tuple) else doc_res[0]
                agenda_dict = document.metadata.get("agenda_dict", {})
                logger.debug(f"✅ [_get_agenda_dict_from_vector_db] 获取到 agenda_dict，共 {len(agenda_dict)} 个章节")
                return agenda_dict
            else:
                logger.warning("⚠️ [_get_agenda_dict_from_vector_db] 未找到文档结构信息")
                return {}

        except Exception as e:
            logger.error(f"❌ [_get_agenda_dict_from_vector_db] 获取 agenda_dict 失败: {e}")
            return {}

    def build_retrieval_tools(self) -> Dict[str, Dict]:
        """
        从配置文件构建检索工具字典

        工具配置来源：src/agents/retrieval/tools_config.py

        Returns:
            工具字典，key为工具名称，value包含工具详细信息
        """
        from .tools_config import get_enabled_tools

        tools = {}
        enabled_tools = get_enabled_tools()

        for tool_config in enabled_tools:
            tool_name = tool_config["name"]
            method_name = tool_config["method_name"]

            # 获取对应的方法
            if hasattr(self.agent.tools, method_name):
                tool_method = getattr(self.agent.tools, method_name)

                tools[tool_name] = {
                    "name": tool_name,
                    "description": tool_config["description"],
                    "parameters": tool_config["parameters"],
                    "function": tool_method,
                    "priority": tool_config.get("priority", 999),
                }

                logger.debug(f"已加载工具: {tool_name} (方法: {method_name})")
            else:
                logger.warning(f"工具 '{tool_name}' 配置的方法 '{method_name}' 未找到")

        logger.info(f"成功加载 {len(tools)} 个检索工具")
        return tools

    def validate_state(self, state: 'RetrievalState') -> None:
        """
        验证state的完整性

        Args:
            state: RetrievalState对象

        Raises:
            ValueError: 缺少必需字段时抛出异常
        """
        from .state import RetrievalState

        required_fields = ['query', 'max_iterations']

        for field in required_fields:
            if field not in state:
                raise ValueError(f"❌ [Validate] State缺少必需字段: {field}")

        # 验证字段类型和值
        if not isinstance(state.get('query', ''), str) or not state.get('query', '').strip():
            raise ValueError("❌ [Validate] query字段必须是非空字符串")

        max_iterations = state.get('max_iterations', 0)
        if not isinstance(max_iterations, int) or max_iterations <= 0:
            raise ValueError("❌ [Validate] max_iterations必须是正整数")

        logger.debug(f"✅ [Validate] State验证通过")
