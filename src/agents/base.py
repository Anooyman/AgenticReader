"""
Agent基类

提供Agent的基础功能，包括：
- LLM实例管理
- LangGraph workflow构建
"""

from langgraph.graph import StateGraph
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class AgentBase:
    """
    Agent基类，所有Agent都应继承此类

    功能：
    - 管理LLM和embedding模型实例
    - 提供workflow构建抽象
    - 工具方法直接在Agent类中实现

    使用方式:
    ```python
    class MyAgent(AgentBase):
        def __init__(self):
            super().__init__(name="MyAgent", provider="openai")
            self.graph = self.build_graph()

        # 工具方法直接在Agent类中实现
        async def my_tool(self, query: str):
            # 可以直接访问 self.llm 和 self.embedding_model
            result = await self.llm.async_get_response(query)
            return result

        def build_graph(self) -> StateGraph:
            # 构建LangGraph workflow
            workflow = StateGraph(MyState)
            ...
            return workflow.compile()
    ```
    """

    def __init__(
        self,
        name: str,
        provider: str = 'openai',
        model: Optional[str] = None
    ):
        """
        初始化Agent

        Args:
            name: Agent名称
            provider: LLM提供商 ('azure', 'openai', 'ollama')
            model: 覆盖该 provider 默认使用的模型名（可选）。省略时按
                src.config.model_overrides.AGENT_MODEL_OVERRIDES 里以 name
                为键查找配置好的覆盖值；两者都没有则沿用 provider 的
                环境变量默认模型。显式传入的 model 优先于配置表。
        """
        self.name = name

        if model is None:
            from src.config.model_overrides import AGENT_MODEL_OVERRIDES
            model = AGENT_MODEL_OVERRIDES.get(name)

        # 初始化LLM实例（Agent级别，供所有工具方法复用）
        from src.core.llm import LLMBase
        self.llm = LLMBase(provider=provider, model=model)
        # embedding 客户端不再在这里取值：LLMBase.embedding_model 是懒加载
        # property，构造期取一次就把 provider 的 embedding 客户端急切建出来了
        # （多数 Agent 一生都不做向量化）。改为下面的 property 按次转发，
        # 首次真正用到时才构造，取的仍是 LLMBase 内部缓存的同一个实例。

        logger.info(
            f"✅ {self.name} initialized with LLM provider: {provider}"
            f"{f', model: {model}' if model else ''}"
        )

        self.graph: Optional[StateGraph] = None

        logger.debug(f"🤖 Initialized {self.name}")

    @property
    def embedding_model(self):
        """
        懒加载 embedding 客户端

        构造 Agent 时不再急切创建（那是网络/凭据相关最贵的一步），首次访问
        时才向 LLMBase 取——LLMBase 内部同样懒加载并缓存，所以多次访问拿到的是
        同一个实例，切换 provider 后也能跟着刷新（LLMBase 会重置它的缓存）。
        """
        return self.llm.embedding_model

    def build_graph(self) -> StateGraph:
        """
        构建LangGraph workflow

        子类必须实现此方法

        Returns:
            编译后的StateGraph对象

        Raises:
            NotImplementedError: 子类未实现此方法
        """
        raise NotImplementedError(
            f"{self.name} must implement build_graph() method"
        )

    def __repr__(self) -> str:
        """字符串表示"""
        return f"<{self.__class__.__name__}(name='{self.name}')>"

    def __str__(self) -> str:
        """可读字符串"""
        return f"{self.name} Agent"
