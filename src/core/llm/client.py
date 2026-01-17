"""
client.py - Main LLM client for managing conversations and providers

This module provides the main LLMBase class for managing chat conversations,
integrating with different LLM providers and handling message history.

Enhanced Features:
- Multi-provider support (Azure, OpenAI, Ollama)
- Tool calling support for MCP integration
- Async operations support
- Session-based message history management
- Smart history management with LLM summarization
- Enhanced error handling and logging
- Flexible configuration management

Note:
    - Message history management moved to history.py
    - Provider implementations moved to providers.py
"""
import asyncio
import logging
from typing import Any, Optional, List, Dict
from langchain_openai import AzureOpenAIEmbeddings, OpenAIEmbeddings
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory

from src.config.settings import LLM_EMBEDDING_CONFIG
from src.config.prompts import SYSTEM_PROMPT_CONFIG
from src.config.constants import SessionHistoryConfig

# Import from refactored modules
from src.core.llm.history import LimitedChatMessageHistory
from src.core.llm.providers import (
    AzureLLMProvider,
    OpenAILLMProvider,
    OllamaLLMProvider
)

logging.basicConfig(
    level=logging.INFO,  # 可根据需要改为 DEBUG
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


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
        tools: Optional[List[Dict]] = None,
        enable_llm_summary: bool = True
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
            enable_llm_summary: 是否启用LLM历史总结（默认True，False则使用长度截断）

        Returns:
            Any: LLM 响应对象
        """
        # 预先创建消息历史（如果不存在），以便控制 LLM 总结功能
        if session_id not in self.message_histories:
            self.get_message_history(session_id, enable_llm_summary=enable_llm_summary)

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

    def clear_session_history(self, session_id: str) -> bool:
        """
        清空指定 session_id 的所有历史消息

        Args:
            session_id (str): 会话ID

        Returns:
            bool: 是否成功清空（如果会话不存在则返回False）
        """
        if session_id in self.message_histories:
            message_count = self.message_histories[session_id].clear_all_messages()
            logger.info(f"✅ 会话 {session_id} 的历史已清空，共删除 {message_count} 条消息")
            return True
        else:
            logger.warning(f"❌ 会话 {session_id} 不存在，无法清空")
            return False

    def print_session_history(self, session_id: str, detailed: bool = False) -> str:
        """
        打印指定 session_id 的所有历史消息

        Args:
            session_id (str): 会话ID
            detailed (bool): 是否显示详细信息（消息类型、token数等），默认False

        Returns:
            str: 格式化的消息历史字符串，如果会话不存在则返回错误信息
        """
        if session_id in self.message_histories:
            logger.info(f"📜 打印会话 {session_id} 的历史消息")
            return self.message_histories[session_id].print_all_messages(detailed=detailed)
        else:
            error_msg = f"❌ 会话 {session_id} 不存在，无法打印历史"
            logger.warning(error_msg)
            print(error_msg)
            return error_msg

    def copy_session_history(self, source_session_id: str, target_session_id: str,
                            replace: bool = False) -> bool:
        """
        将源 session_id 的所有消息复制到目标 session_id

        Args:
            source_session_id (str): 源会话ID
            target_session_id (str): 目标会话ID
            replace (bool): 是否替换目标会话的现有消息（默认False，追加模式）

        Returns:
            bool: 是否成功复制
        """
        # 检查源会话是否存在
        if source_session_id not in self.message_histories:
            logger.warning(f"❌ 源会话 {source_session_id} 不存在，无法复制")
            return False

        # 获取或创建目标会话
        target_history = self.get_message_history(target_session_id)

        # 如果是替换模式，先清空目标会话
        if replace:
            target_history.clear_all_messages()
            logger.info(f"🔄 替换模式：已清空目标会话 {target_session_id} 的原有消息")

        # 执行复制
        source_history = self.message_histories[source_session_id]
        copied_count = source_history.copy_messages_to(target_history)

        logger.info(f"✅ 成功将 {copied_count} 条消息从会话 {source_session_id} "
                   f"复制到会话 {target_session_id} (replace={replace})")
        return True

    def export_session_history(self, session_id: str, include_metadata: bool = False) -> List[Dict[str, Any]]:
        """
        导出指定 session_id 的所有历史消息为结构化数据

        Args:
            session_id (str): 会话ID
            include_metadata (bool): 是否包含元数据（token数、类型等），默认False

        Returns:
            List[Dict[str, Any]]: 消息列表，每条消息为一个字典
                基础字段：
                    - index (int): 消息索引（从1开始）
                    - role (str): 角色名称 ("user", "assistant", "system", "unknown")
                    - content (str): 消息内容
                如果 include_metadata=True，还包括：
                    - type (str): 消息类型
                    - token_count (int): Token数量
                    - tool_calls (list): 工具调用信息（如果存在）
                    - tool_call_id (str): 响应的工具调用ID（如果存在）
                    - additional_kwargs (dict): 额外参数（如果存在）

        Example:
            >>> llm_client.export_session_history("session_1")
            [
                {"index": 1, "role": "user", "content": "你好"},
                {"index": 2, "role": "assistant", "content": "你好！有什么可以帮助你的？"}
            ]

            >>> llm_client.export_session_history("session_1", include_metadata=True)
            [
                {
                    "index": 1,
                    "role": "user",
                    "content": "你好",
                    "type": "HumanMessage",
                    "token_count": 2
                },
                ...
            ]

        Note:
            - 如果会话不存在，返回空列表
            - 返回的数据可以直接序列化为JSON
            - 保留了所有角色信息和对话顺序
        """
        if session_id not in self.message_histories:
            logger.warning(f"❌ 会话 {session_id} 不存在，无法导出历史")
            return []

        logger.info(f"📤 导出会话 {session_id} 的历史消息 (include_metadata={include_metadata})")
        exported_data = self.message_histories[session_id].export_messages(include_metadata=include_metadata)

        logger.info(f"✅ 成功导出 {len(exported_data)} 条消息")
        return exported_data

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

    def get_message_history(self, session_id=None, enable_llm_summary=True):
        """
        获取指定 session_id 的消息历史，没有则自动创建。

        Args:
            session_id: 会话ID
            enable_llm_summary: 是否为新创建的历史启用LLM总结功能（默认True）

        Returns:
            LimitedChatMessageHistory 实例
        """
        if session_id not in self.message_histories:
            # 从统一配置中获取参数
            config = SessionHistoryConfig.get_config(session_id)

            self.message_histories[session_id] = LimitedChatMessageHistory(
                max_messages=config["max_messages"],
                max_tokens=config["max_tokens"],
                use_llm_summary=enable_llm_summary and config["use_llm_summary"],
                llm_client=self if enable_llm_summary and config["use_llm_summary"] else None,
                summary_threshold=config["summary_threshold"]
            )

            logger.debug(f"创建新的消息历史 - session_id: {session_id}, "
                        f"max_messages: {config['max_messages']}, "
                        f"max_tokens: {config['max_tokens']}, "
                        f"summary_threshold: {config['summary_threshold']}")

        return self.message_histories[session_id]

    def add_message_to_history(self, session_id=None, message=None, enable_llm_summary=True):
        """
        向指定 session_id 的历史添加消息。

        Args:
            session_id: 会话ID
            message: 要添加的消息
            enable_llm_summary: 如果需要创建新历史，是否启用LLM总结功能（默认True）
        """
        if message is None:
            message = HumanMessage("")  # 或 SystemMessage("")，根据你的业务场景

        if session_id not in self.message_histories:
            logger.warning(f"Can't find {session_id}, in current history. Create a new history.")

            # 从统一配置中获取参数
            config = SessionHistoryConfig.get_config(session_id)

            self.message_histories[session_id] = LimitedChatMessageHistory(
                max_messages=config["max_messages"],
                max_tokens=config["max_tokens"],
                use_llm_summary=enable_llm_summary and config["use_llm_summary"],
                llm_client=self if enable_llm_summary and config["use_llm_summary"] else None,
                summary_threshold=config["summary_threshold"]
            )

            logger.debug(f"创建新的消息历史 - session_id: {session_id}, "
                        f"max_messages: {config['max_messages']}, "
                        f"max_tokens: {config['max_tokens']}, "
                        f"summary_threshold: {config['summary_threshold']}")

        self.message_histories[session_id].add_message(message)

    def enable_llm_summary_for_session(self, session_id: str, summary_threshold: int = None):
        """
        为指定会话启用LLM智能总结功能

        Args:
            session_id: 会话ID
            summary_threshold: 触发总结的消息数量阈值（默认None，使用配置中的值）

        Returns:
            bool: 是否成功启用
        """
        # 如果未指定阈值，从配置中获取
        if summary_threshold is None:
            config = SessionHistoryConfig.get_config(session_id)
            summary_threshold = config["summary_threshold"]
        if session_id in self.message_histories:
            history = self.message_histories[session_id]
            history.use_llm_summary = True
            history.llm_client = self
            history.summary_threshold = summary_threshold
            logger.info(f"✅ 会话 {session_id} 已启用 LLM 总结功能 (阈值={summary_threshold})")
            return True
        else:
            logger.warning(f"❌ 会话 {session_id} 不存在，无法启用 LLM 总结")
            return False

    def disable_llm_summary_for_session(self, session_id: str):
        """
        为指定会话禁用LLM智能总结功能

        Args:
            session_id: 会话ID

        Returns:
            bool: 是否成功禁用
        """
        if session_id in self.message_histories:
            history = self.message_histories[session_id]
            history.use_llm_summary = False
            history.llm_client = None
            logger.info(f"✅ 会话 {session_id} 已禁用 LLM 总结功能")
            return True
        else:
            logger.warning(f"❌ 会话 {session_id} 不存在，无法禁用 LLM 总结")
            return False

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
        tools: Optional[List[Dict]] = None,
        enable_llm_summary: bool = True
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
            enable_llm_summary: 是否启用LLM历史总结（默认True，False则使用长度截断）

        Returns:
            Any: LLM 响应对象
        """
        # 预先创建消息历史（如果不存在），以便控制 LLM 总结功能
        if session_id not in self.message_histories:
            self.get_message_history(session_id, enable_llm_summary=enable_llm_summary)

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

            # 从统一配置中获取参数
            config = SessionHistoryConfig.get_config(session_id)

            self.message_histories[session_id] = LimitedChatMessageHistory(
                max_messages=config["max_messages"],
                max_tokens=config["max_tokens"],
                use_llm_summary=config["use_llm_summary"],
                llm_client=self if config["use_llm_summary"] else None,
                summary_threshold=config["summary_threshold"]
            )

            logger.debug(f"创建新的消息历史 - session_id: {session_id}, "
                        f"max_messages: {config['max_messages']}, "
                        f"max_tokens: {config['max_tokens']}, "
                        f"summary_threshold: {config['summary_threshold']}")

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