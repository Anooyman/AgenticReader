"""
client.py - LLM provider and message history management for LLMReader

This module provides classes for managing chat message history with limits, and for abstracting over different LLM providers (Azure, OpenAI, Ollama).

Enhanced Features:
- Tool calling support for MCP integration
- Async operations support
- Enhanced error handling and logging
- Flexible configuration management
"""
import asyncio
import logging
from typing import Any, Optional, List, Dict, Union
from pydantic import Field
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import OllamaEmbeddings

from abc import ABC, abstractmethod

from src.config.settings import (
    LLM_CONFIG,
    LLM_EMBEDDING_CONFIG,
)
from src.config.prompts import SYSTEM_PROMPT_CONFIG
from src.config.constants import ProcessingLimits, LLMConstants
logging.basicConfig(
    level=logging.INFO,  # 可根据需要改为 DEBUG
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class LimitedChatMessageHistory(InMemoryChatMessageHistory):
    """
    带有限制功能的聊天消息历史记录管理类

    扩展InMemoryChatMessageHistory，增加以下功能：
    - 消息数量限制：通过max_messages参数控制最大消息条数
    - Token数量限制：通过max_tokens参数控制总Token数不超过模型上下文窗口
    - 自动清理：当消息数量或Token数超出限制时，自动移除最早的消息

    Attributes:
        max_messages (int): 最大消息数量限制，默认从ProcessingLimits.DEFAULT_MAX_MESSAGES获取
        max_tokens (int): 最大Token数量限制，默认从ProcessingLimits.DEFAULT_MAX_TOKENS获取
        encoding_name (str): Token编码名称，默认从LLMConstants.DEFAULT_ENCODING获取
    """

    # 使用Pydantic字段定义自定义属性
    max_messages: int = Field(default_factory=lambda: ProcessingLimits.DEFAULT_MAX_MESSAGES)
    max_tokens: int = Field(default_factory=lambda: ProcessingLimits.DEFAULT_MAX_TOKENS)
    encoding_name: str = Field(default_factory=lambda: LLMConstants.DEFAULT_ENCODING)

    def __init__(self, max_messages: int = None, max_tokens: int = None,
                 encoding_name: str = None, **kwargs):
        """
        初始化限制型聊天消息历史

        Args:
            max_messages (int): 最大消息数量限制
            max_tokens (int): 最大Token数量限制
            encoding_name (str): Token编码名称
            **kwargs: 传递给父类的其他参数
        """
        # 设置自定义字段的值
        if max_messages is not None:
            kwargs['max_messages'] = max_messages
        if max_tokens is not None:
            kwargs['max_tokens'] = max_tokens
        if encoding_name is not None:
            kwargs['encoding_name'] = encoding_name
            
        super().__init__(**kwargs)

        logger.debug(f"LimitedChatMessageHistory初始化: max_messages={self.max_messages}, "
                    f"max_tokens={self.max_tokens}, encoding={self.encoding_name}")

    def _count_tokens(self, message):
        """
        计算单条消息的Token数量
        Args:
            message: 聊天消息对象，需包含content属性
        Returns:
            int: 消息内容的Token数量
        Note:
            优先使用tiktoken进行精确计算，如未安装则使用字符数/4进行估算
        """
        try:
            import tiktoken
            encoding = tiktoken.get_encoding(self.encoding_name)
            if hasattr(message, "content"):
                return len(encoding.encode(message.content))
            else:
                return 0
        except ImportError:
            logger.warning("tiktoken not installed, using rough token estimate.")
            if hasattr(message, "content"):
                return len(message.content) // 4
            else:
                return 0
        except Exception as e:
            logger.error(f"Error counting tokens: {e}")
            return 0

    def _total_tokens(self):
        """计算所有消息的总Token数"""
        return sum(self._count_tokens(m) for m in self.messages)

    def add_message(self, message):
        """
        添加消息到历史，并自动根据 max_messages 和 max_tokens 进行裁剪。
        """
        super().add_message(message)
        # 1. 限制消息条数 - 保留最新的max_messages条消息
        if len(self.messages) > self.max_messages:
            logger.info(f"[LimitedChatMessageHistory] 消息数量超出限制({self.max_messages})，已截断。")
            self.messages = self.messages[-self.max_messages:]
        # 2. 限制Token总数 - 循环移除最早消息直到Token数达标
        while self._total_tokens() > self.max_tokens and len(self.messages) > 1:
            logger.info(f"[LimitedChatMessageHistory] Token总数超出限制({self.max_tokens})，移除最早消息。")
            self.messages.pop(0)
    
    def delete_last_message(self):
        """删除最后一条消息"""
        if self.messages:
            removed_message = self.messages.pop()
            logger.info(f"[LimitedChatMessageHistory] 删除最后一条消息: {removed_message}")
        else:
            logger.warning("[LimitedChatMessageHistory] 无消息可删除。")

class LLMProviderBase(ABC):
    """
    LLM Provider 抽象基类，定义统一接口。
    """
    @abstractmethod
    def get_chat_model(self, **kwargs):
        pass

    @abstractmethod
    def get_embedding_model(self, **kwargs):
        pass

class AzureLLMProvider(LLMProviderBase):

    def get_chat_model(self, **kwargs):
        return AzureChatOpenAI(
            openai_api_key=kwargs.get("openai_api_key", LLM_CONFIG.get("api_key")),
            openai_api_version=kwargs.get("openai_api_version", LLM_CONFIG.get("api_version")),
            azure_endpoint=kwargs.get("azure_endpoint", LLM_CONFIG.get("azure_endpoint")),
            deployment_name=kwargs.get("deployment_name", LLM_CONFIG.get("deployment_name")),
            model_name=kwargs.get("model_name", LLM_CONFIG.get("model_name")),
            temperature=kwargs.get("temperature", 0.7),
            max_retries=kwargs.get("max_retries", 5)
        )

    def get_embedding_model(self, **kwargs):
        return AzureOpenAIEmbeddings(
            openai_api_key=kwargs.get("openai_api_key", LLM_EMBEDDING_CONFIG.get("api_key")),
            openai_api_version=kwargs.get("openai_api_version", LLM_EMBEDDING_CONFIG.get("api_version")),
            azure_endpoint=kwargs.get("azure_endpoint", LLM_EMBEDDING_CONFIG.get("azure_endpoint")),
            deployment=kwargs.get("deployment", LLM_EMBEDDING_CONFIG.get("deployment")),
            model=kwargs.get("model", LLM_EMBEDDING_CONFIG.get("model")),
            max_retries=kwargs.get("max_retries", 5)
        )

class OpenAILLMProvider(LLMProviderBase):
    def get_chat_model(self, **kwargs):
        return ChatOpenAI(
            model=kwargs.get("model_name", LLM_CONFIG.get("openai_model_name")),
            openai_api_key=kwargs.get("openai_api_key", LLM_CONFIG.get("openai_api_key")),
            base_url=kwargs.get("openai_base_url", LLM_CONFIG.get("openai_base_url")),
            temperature=kwargs.get("temperature", 0.7),
            max_retries=kwargs.get("max_retries", 5)
        )

    def get_embedding_model(self, **kwargs):
        return OpenAIEmbeddings(
            openai_api_key=kwargs.get("openai_api_key", LLM_EMBEDDING_CONFIG.get("openai_api_key")),
            model=kwargs.get("model", LLM_EMBEDDING_CONFIG.get("openai_model", "text-embedding-ada-002")),
            max_retries=kwargs.get("max_retries", 5)
        )

class OllamaLLMProvider(LLMProviderBase):
    def get_chat_model(self, **kwargs):
        return ChatOllama(
            base_url=kwargs.get("base_url", LLM_CONFIG.get("ollama_base_url", "http://localhost:11434")),
            model=kwargs.get("model", LLM_CONFIG.get("ollama_model_name", "llama3")),
            temperature=kwargs.get("temperature", 0.7)
        )

    def get_embedding_model(self, **kwargs):
        return OllamaEmbeddings(
            base_url=kwargs.get("base_url", LLM_EMBEDDING_CONFIG.get("ollama_base_url", "http://localhost:11434")),
            model=kwargs.get("model", LLM_EMBEDDING_CONFIG.get("ollama_model", "llama3")),
        )

class LLMBase:
    """
    LLMBase 统一调度各类 LLMProvider。
    管理多会话历史，支持不同 LLM provider。
    
    Enhanced Features:
    - Tool calling support for MCP integration
    - Async operations
    - Better error handling
    - Flexible configuration
    """
    def __init__(self, provider: str) -> None:
        """
        Args:
            provider (str): 'azure', 'openai', 'ollama'
        """
        self.message_histories = {}
        self.provider = provider.lower()
        self.providers = {
            "azure": AzureLLMProvider(),
            "openai": OpenAILLMProvider(),
            "ollama": OllamaLLMProvider(),
        }
        
        # Validate provider
        self._validate_provider()
            
        # Initialize models
        self.chat_model = self.get_chat_model()
        self.embedding_model = self.get_embedding_model()
        
        logger.info(f"LLMBase initialized with provider: {self.provider}")

    def _validate_provider(self):
        """验证当前 provider 是否有效。"""
        if self.provider not in self.providers:
            logger.error(f"Unknown provider: {self.provider}")
            raise ValueError(f"Unknown provider: {self.provider}")

    def _format_system_prompt(self, role: str, system_format_dict: dict = None) -> str:
        """
        格式化系统提示词。
        
        Args:
            role: 角色标识
            system_format_dict: 格式化参数字典
            
        Returns:
            格式化后的系统提示词
        """
        system_prompt = SYSTEM_PROMPT_CONFIG.get(role, "")
        
        if system_format_dict:
            try:
                system_prompt = system_prompt.format(**system_format_dict)
            except KeyError as e:
                logger.error(f"系统提示词格式化失败，缺少参数: {e}")
        
        return system_prompt

    def get_chat_model_with_tools(self, tools: Optional[List[Dict]] = None, **kwargs):
        """
        Get chat model with optional tool binding support for MCP integration.
        
        Args:
            tools: List of tool definitions for binding
            **kwargs: Additional model parameters
            
        Returns:
            Chat model instance with tools bound if provided
        """
        model = self.get_chat_model(**kwargs)

        if tools and hasattr(model, 'bind_tools'):
            try:
                bound_model = model.bind_tools(tools)
                return bound_model
            except Exception as e:
                logger.warning(f"工具绑定失败: {e}")
                return model
        elif tools and not hasattr(model, 'bind_tools'):
            logger.warning(f"模型 {type(model).__name__} 不支持工具绑定")

        return model

    async def async_call_llm_chain(
        self,
        role: str,
        input_prompt: str,
        session_id: str,
        output_parser=StrOutputParser(),
        system_format_dict: dict = None,
        tools: Optional[List[Dict]] = None
    ) -> Any:
        """
        主要的异步 LLM 调用方法，支持工具调用。
        
        Args:
            role (str): PDFReaderRole 枚举值
            input_prompt (str): 输入提示
            session_id (str): 会话 ID
            output_parser: 输出解析器
            system_format_dict: 系统提示词格式化参数
            tools: 工具定义列表
            
        Returns:
            Any: LLM 响应对象
        """
        # Format system prompt
        system_prompt = self._format_system_prompt(role, system_format_dict)

        # Get model with tools if provided
        if tools:
            chat_model = self.get_chat_model_with_tools(tools)
        else:
            chat_model = self.chat_model

        chain = self.build_chain(
            client=chat_model,
            system_prompt=system_prompt,
            output_parser=output_parser,
            tools=tools
        )

        try:
            # Use async invoke if available
            if hasattr(chain, 'ainvoke'):
                response = await chain.ainvoke(
                    {"input_prompt": input_prompt},
                    config={"configurable": {"session_id": session_id}}
                )
            else:
                # Fallback to sync invoke in executor
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: chain.invoke(
                        {"input_prompt": input_prompt},
                        config={"configurable": {"session_id": session_id}}
                    )
                )

            return response

        except Exception as e:
            logger.error(f"{role} 异步调用LLM报错: {e}")
            return ""

    def update_provider_config(self, provider: str = None, **config_updates):
        """
        动态更新provider配置并重新初始化模型。
        
        Args:
            provider: 新的provider类型（可选）
            **config_updates: 配置更新参数
        """
        if provider and provider.lower() != self.provider:
            self.provider = provider.lower()
            self._validate_provider()
            logger.info(f"Provider updated to: {self.provider}")
        
        # 重新初始化模型
        try:
            self.chat_model = self.get_chat_model(**config_updates)
            self.embedding_model = self.get_embedding_model(**config_updates)
            logger.info("Models reinitialized with new configuration")
        except Exception as e:
            logger.error(f"Failed to reinitialize models: {e}")
            raise

    def get_provider_info(self) -> Dict[str, Any]:
        """
        获取当前provider的详细信息。
        
        Returns:
            Dict: Provider信息字典
        """
        return {
            "provider": self.provider,
            "chat_model_type": type(self.chat_model).__name__,
            "embedding_model_type": type(self.embedding_model).__name__,
            "available_providers": list(self.providers.keys()),
            "session_count": len(self.message_histories)
        }

    def clear_all_histories(self):
        """清空所有会话历史。"""
        self.message_histories.clear()
        logger.info("All message histories cleared")

    def get_session_info(self, session_id: str = None) -> Dict[str, Any]:
        """
        获取会话信息。
        
        Args:
            session_id: 会话ID，None则返回所有会话信息
            
        Returns:
            Dict: 会话信息
        """
        if session_id:
            if session_id in self.message_histories:
                history = self.message_histories[session_id]
                return {
                    "session_id": session_id,
                    "message_count": len(history.messages),
                    "max_messages": getattr(history, 'max_messages', None),
                    "max_tokens": getattr(history, 'max_tokens', None)
                }
            else:
                return {"session_id": session_id, "exists": False}
        else:
            return {
                "total_sessions": len(self.message_histories),
                "sessions": list(self.message_histories.keys())
            }

    def get_message_history(self, session_id=None):
        """
        获取指定 session_id 的消息历史，没有则自动创建。
        """
        if session_id not in self.message_histories:
            if session_id in ["chat"]:
                self.message_histories[session_id] = LimitedChatMessageHistory()
            else:
                self.message_histories[session_id] = LimitedChatMessageHistory(max_messages=5)
        return self.message_histories[session_id]

    def add_message_to_history(self, session_id=None, message=None):
        """
        向指定 session_id 的历史添加消息。
        """
        if message is None:
            message = HumanMessage("")  # 或 SystemMessage("")，根据你的业务场景
        if session_id not in self.message_histories:
            logger.warning(f"Can't find {session_id}, in current history. Create a new history.")
            if session_id in ["chat"]:
                self.message_histories[session_id] = LimitedChatMessageHistory()
            else:
                self.message_histories[session_id] = LimitedChatMessageHistory(max_messages=5)
        self.message_histories[session_id].add_message(message)

    def delete_last_message_in_history(self, session_id=None):
        """
        删除指定 session_id 的历史中的最后一条消息。
        """
        if session_id in self.message_histories:
            self.message_histories[session_id].delete_last_message()
        else:
            logger.warning(f"Can't find {session_id}, in current history. No message deleted.")

    def is_content_in_history(self, content, session_id=None, exact_match=False):
        """
        判断 content 是否在 session_id 的历史消息中出现过。
        Args:
            content (str): 要查找的内容。
            session_id (Any): 会话ID。
            exact_match (bool): 是否要求完全匹配（默认False，表示只要包含即可）。
        Returns:
            bool: True 表示找到匹配内容，False 表示未找到。
        """
        history = self.get_message_history(session_id)
        for idx, msg in enumerate(history.messages):
            if hasattr(msg, "content"):
                if exact_match:
                    if msg.content == content:
                        logger.info(f"[is_content_in_history] 完全匹配成功，索引: {idx}")
                        return True
                else:
                    if content in msg.content:
                        logger.info(f"[is_content_in_history] 包含关系匹配成功，索引: {idx}")
                        return True
        logger.info("[is_content_in_history] 未找到匹配内容。")
        return False

    def build_chain(
        self,
        client,
        system_prompt: str = "",
        output_parser=None,
        tools=None,
    ):
        """
        构建带有 system_prompt、tools、session_id 以及可选 output_format 的对话链。
        output_format: 可选，字符串，指定输出格式说明，会拼接到 system_prompt 后面。
        """
        # 1. 当有工具时，不使用 StrOutputParser 以保留工具调用信息
        if tools:
            # 工具调用模式：不使用输出解析器，保持原始响应
            output_parser = None
            logger.debug("工具调用模式：不使用输出解析器")
        elif not output_parser:
            output_parser = StrOutputParser()
            logger.debug("标准模式：使用 StrOutputParser")
        
        # 2. 构建 prompt，包含 system prompt、历史消息和用户输入
        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            HumanMessagePromptTemplate.from_template("{input_prompt}"),
        ])
        
        # 3. 根据是否有输出解析器构建不同的 runnable
        if output_parser:
            runnable = prompt | client | output_parser
        else:
            runnable = prompt | client
       
        return RunnableWithMessageHistory(
            runnable,
            self.get_message_history,
            input_messages_key="input_prompt",
            history_messages_key="chat_history"
        )

    def get_chat_model(self, **kwargs):
        """
        获取当前 provider 的 chat model。
        """
        self._validate_provider()
        return self.providers[self.provider].get_chat_model(**kwargs)

    def get_embedding_model(self, **kwargs):
        """
        获取当前 provider 的 embedding model。
        """
        self._validate_provider()
        return self.providers[self.provider].get_embedding_model(**kwargs)

    def call_llm_chain(
        self,
        role: str,
        input_prompt: str,
        session_id: str,
        output_parser=StrOutputParser(),
        system_format_dict: dict = None,
        tools: Optional[List[Dict]] = None
    ) -> Any:
        """
        同步版本的 LLM 调用方法，适用于非异步环境。

        Args:
            role (str): PDFReaderRole 枚举值
            input_prompt (str): 输入提示
            session_id (str): 会话 ID
            output_parser: 输出解析器
            system_format_dict: 系统提示词格式化参数
            tools: 工具定义列表

        Returns:
            Any: LLM 响应对象
        """
        # 调试：检查调用前的消息历史
        if session_id in self.message_histories:
            history = self.message_histories[session_id]
            logger.info(f"📜 [HISTORY CHECK] 会话 {session_id} 当前有 {len(history.messages)} 条消息")
            #for idx, msg in enumerate(history.messages):
            #    msg_type = type(msg).__name__
            #    has_tool_calls = hasattr(msg, 'tool_calls') and msg.tool_calls
            #    has_tool_call_id = hasattr(msg, 'tool_call_id')
            #    logger.info(f"  [{idx}] {msg_type} | tool_calls={has_tool_calls} | tool_call_id={has_tool_call_id}")
            #    if has_tool_calls:
            #        for tc in msg.tool_calls:
            #            tc_id = tc.get('id') if isinstance(tc, dict) else getattr(tc, 'id', 'unknown')
            #            tc_name = tc.get('name') if isinstance(tc, dict) else getattr(tc, 'name', 'unknown')
            #            logger.info(f"      → tool_call: id={tc_id}, name={tc_name}")
            #    if has_tool_call_id:
            #        logger.info(f"      → responding to: {msg.tool_call_id}")
        else:
            logger.info(f"📜 [HISTORY CHECK] 会话 {session_id} 尚未创建")

        # Format system prompt
        system_prompt = self._format_system_prompt(role, system_format_dict)

        # Get model with tools if provided
        if tools:
            chat_model = self.get_chat_model_with_tools(tools)
        else:
            chat_model = self.chat_model

        chain = self.build_chain(
            client=chat_model,
            system_prompt=system_prompt,
            output_parser=output_parser,
            tools=tools
        )

        try:
            # 直接使用同步调用
            response = chain.invoke(
                {"input_prompt": input_prompt},
                config={"configurable": {"session_id": session_id}}
            )

            return response

        except Exception as e:
            logger.error(f"{role} 同步调用LLM报错: {e}")
            return ""

    def add_messages_to_history(self, session_id: str, messages: List) -> None:
        """
        将多条消息添加到指定会话的历史记录中

        用于工具调用场景：需要将 AIMessage（带tool_calls）和 ToolMessage 都添加到历史

        Args:
            session_id (str): 会话 ID
            messages (List): 消息列表，可以包含 AIMessage, ToolMessage 等
        """
        logger.info(f"📝 [ADD MESSAGES] 准备将 {len(messages)} 条消息添加到会话 {session_id}")

        if session_id not in self.message_histories:
            logger.warning(f"会话 {session_id} 不存在，创建新会话")
            self.message_histories[session_id] = LimitedChatMessageHistory(
                max_messages=ProcessingLimits.MAX_MESSAGES,
                max_tokens=LLMConstants.MAX_CONTEXT_TOKENS
            )

        history = self.message_histories[session_id]
        logger.info(f"📝 [BEFORE ADD] 会话当前有 {len(history.messages)} 条消息")

        for idx, msg in enumerate(messages):
            msg_type = type(msg).__name__
            history.add_message(msg)

            # 详细记录每条消息的信息
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                logger.info(f"📝 [{idx+1}/{len(messages)}] 添加 {msg_type} (包含 {len(msg.tool_calls)} 个 tool_calls)")
                for tc in msg.tool_calls:
                    tc_id = tc.get('id') if isinstance(tc, dict) else getattr(tc, 'id', 'unknown')
                    tc_name = tc.get('name') if isinstance(tc, dict) else getattr(tc, 'name', 'unknown')
                    logger.info(f"      → tool_call: id={tc_id}, name={tc_name}")
            elif hasattr(msg, 'tool_call_id'):
                logger.info(f"📝 [{idx+1}/{len(messages)}] 添加 {msg_type} (响应 tool_call_id={msg.tool_call_id})")
            else:
                logger.info(f"📝 [{idx+1}/{len(messages)}] 添加 {msg_type}")

        logger.info(f"📝 [AFTER ADD] 会话现在有 {len(history.messages)} 条消息")


def get_embeddings(**kwargs):
    """
    获取全局嵌入模型实例
    
    根据配置返回对应的嵌入模型（Azure OpenAI 或 OpenAI）
    
    Args:
        **kwargs: 传递给嵌入模型的额外参数
        
    Returns:
        嵌入模型实例（AzureOpenAIEmbeddings 或 OpenAIEmbeddings）
    """
    provider = LLM_EMBEDDING_CONFIG.get("provider", "openai").lower()
    
    if provider == "azure":
        return AzureOpenAIEmbeddings(
            openai_api_key=kwargs.get("openai_api_key", LLM_EMBEDDING_CONFIG.get("api_key")),
            openai_api_version=kwargs.get("openai_api_version", LLM_EMBEDDING_CONFIG.get("api_version")),
            azure_endpoint=kwargs.get("azure_endpoint", LLM_EMBEDDING_CONFIG.get("azure_endpoint")),
            deployment=kwargs.get("deployment", LLM_EMBEDDING_CONFIG.get("deployment")),
            model=kwargs.get("model", LLM_EMBEDDING_CONFIG.get("model")),
            max_retries=kwargs.get("max_retries", 5)
        )
    elif provider == "openai":
        return OpenAIEmbeddings(
            openai_api_key=kwargs.get("openai_api_key", LLM_EMBEDDING_CONFIG.get("openai_api_key")),
            model=kwargs.get("model", LLM_EMBEDDING_CONFIG.get("openai_model", "text-embedding-ada-002")),
            max_retries=kwargs.get("max_retries", 5)
        )
    else:
        # 默认使用 OpenAI
        logger.warning(f"未知的嵌入模型 provider: {provider}，默认使用 OpenAI")
        return OpenAIEmbeddings(
            openai_api_key=kwargs.get("openai_api_key", LLM_EMBEDDING_CONFIG.get("openai_api_key")),
            model=kwargs.get("model", LLM_EMBEDDING_CONFIG.get("openai_model", "text-embedding-ada-002")),
            max_retries=kwargs.get("max_retries", 5)
        )