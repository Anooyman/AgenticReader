"""
client.py - Main LLM client for managing conversations and providers

This module provides the main LLMBase class for managing chat conversations,
integrating with different LLM providers and handling message history.

Enhanced Features:
- Multi-provider support (Azure, OpenAI, Ollama, Gemini)
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
import threading
from collections import OrderedDict
from typing import Any, Optional, List, Dict, Tuple
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory

# get_embeddings() 里的 provider / 模型名解析全部走 settings 的这两个函数，
# 本模块不再直接读 LLM_EMBEDDING_CONFIG 的任何键（缓存 key 也只取这两个函数的结果）。
from src.config.settings import get_embedding_provider, get_embedding_model_name
from src.config.prompts import SYSTEM_PROMPT_CONFIG
from src.config.constants import SessionHistoryConfig

# Import from refactored modules
from src.core.llm.history import LimitedChatMessageHistory
from src.core.llm.providers import (
    AzureLLMProvider,
    OpenAILLMProvider,
    OllamaLLMProvider,
    GeminiLLMProvider
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
    # provider 内部对"模型名"参数的命名不统一（Azure/Gemini 用 model_name，
    # OpenAI/Ollama 用 model）；对外统一用 model 一个入口，这里做映射。
    _MODEL_KWARG_BY_PROVIDER = {
        "azure": "model_name",
        "openai": "model_name",
        "ollama": "model",
        "gemini": "model_name",
    }

    def __init__(self, provider: str, model: Optional[str] = None) -> None:
        """
        Args:
            provider (str): 'azure', 'openai', 'ollama', 'gemini'
            model (str, optional): 覆盖该 provider 默认使用的模型名
                （不传则沿用 LLM_CONFIG 里对应 provider 的环境变量默认值）。
        """
        self.message_histories = {}
        self.provider = provider.lower()
        self.model = model

        # 懒加载Provider实例：只在需要时创建（性能优化）
        self._provider_instances = {}
        self._provider_classes = {
            "azure": AzureLLMProvider,
            "openai": OpenAILLMProvider,
            "ollama": OllamaLLMProvider,
            "gemini": GeminiLLMProvider,
        }

        # Validate provider
        self._validate_provider()

        # 懒加载模型：只在首次调用时初始化（性能优化）
        self._chat_model = None
        self._embedding_model = None

        logger.info(
            f"LLMBase initialized with provider: {self.provider}"
            f"{f', model override: {self.model}' if self.model else ''} (lazy loading enabled)"
        )

    def _validate_provider(self):
        """验证当前 provider 是否有效。"""
        if self.provider not in self._provider_classes:
            logger.error(f"Unknown provider: {self.provider}")
            raise ValueError(f"Unknown provider: {self.provider}")

    def _get_provider(self):
        """懒加载：获取当前provider实例（仅在首次调用时创建）"""
        if self.provider not in self._provider_instances:
            logger.debug(f"Creating provider instance for: {self.provider}")
            self._provider_instances[self.provider] = self._provider_classes[self.provider]()
        return self._provider_instances[self.provider]

    @property
    def chat_model(self):
        """懒加载：获取chat model（仅在首次调用时初始化）"""
        if self._chat_model is None:
            logger.debug(f"Initializing chat model for provider: {self.provider}")
            self._chat_model = self.get_chat_model()
        return self._chat_model

    @property
    def embedding_model(self):
        """懒加载：获取embedding model（仅在首次调用时初始化）"""
        if self._embedding_model is None:
            logger.debug(f"Initializing embedding model for provider: {self.provider}")
            self._embedding_model = self.get_embedding_model()
        return self._embedding_model

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
            # 切换了 provider，清掉旧 provider 的实例缓存，
            # 否则 _get_provider() 仍会命中旧 provider 的实例。
            self._provider_instances.clear()

        # 重新初始化模型。
        # 注意：chat_model / embedding_model 是只读的懒加载 property（没有 setter），
        # 对外赋值会直接抛 AttributeError；这里写它们背后真正的缓存字段
        # _chat_model / _embedding_model，property 之后读到的就是新 provider 的模型。
        self._chat_model = None
        self._embedding_model = None
        try:
            self._chat_model = self.get_chat_model(**config_updates)
            self._embedding_model = self.get_embedding_model(**config_updates)
            logger.info("Models reinitialized with new configuration")
        except Exception as e:
            # 构造失败时把缓存留在 None，后续经 property 懒加载时重新尝试，
            # 不会让调用方继续拿到上一个 provider 的旧模型。
            self._chat_model = None
            self._embedding_model = None
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
            "available_providers": list(self._provider_classes.keys()),
            "session_count": len(self.message_histories)
        }

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

        若初始化时传入了 model 覆盖值，且调用方没有显式传入该 provider
        对应的模型名 kwarg，则在这里补上——调用方显式传入的值优先。
        """
        self._validate_provider()
        if self.model:
            model_kwarg = self._MODEL_KWARG_BY_PROVIDER[self.provider]
            kwargs.setdefault(model_kwarg, self.model)
        return self._get_provider().get_chat_model(**kwargs)

    def get_embedding_model(self, **kwargs):
        """
        获取当前 provider 的 embedding model。
        """
        self._validate_provider()
        return self._get_provider().get_embedding_model(**kwargs)

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


# ============================================================================
# get_embeddings() 的进程级实例缓存（REFACTOR_REPORT §8.2 / 波次5-B）
# ============================================================================
# embeddings 对象本身无业务状态（构造时才读配置、建 SDK client），可以安全共享；
# 真正不能共享的是 VectorDBClient 的轮次去重状态——那部分刻意留在实例上，
# 见 src/core/vector_db/vector_db_client.py 的文件头注释。
# 逃生口：clear_embeddings_cache()。
# ----------------------------------------------------------------------------

#: embeddings 实例缓存最多保留多少条（LRU；正常只有 1~2 条，兜住滥用场景）
_EMBEDDINGS_CACHE_MAX_ENTRIES = 32

_embeddings_cache: "OrderedDict[Tuple, Any]" = OrderedDict()
_embeddings_cache_lock = threading.RLock()


def _embeddings_cache_key(provider: str, provider_class: type, kwargs: Dict[str, Any]) -> Optional[Tuple]:
    """算 get_embeddings() 的缓存 key（配置指纹 + 显式 kwargs）。

    key 覆盖"影响构造结果"的配置：
      - provider（settings.get_embedding_provider 的唯一入口）
      - provider 类（防止显式指定 provider 类时串味）
      - 该 provider 配置的 embedding 模型名（settings.get_embedding_model_name，
        模型名直接决定维度，是必须进 key 的那一项）
      - 调用方显式传入的 kwargs（同名字段可覆盖默认配置）
    未进 key 的构造期配置（api_key / azure_endpoint / base_url / max_retries 等）
    来自 settings 模块导入时读到的环境变量，本来就要求重启进程才生效；
    若确实有人在运行时改这些值，用 clear_embeddings_cache() 强制失效。

    取不到可靠指纹（value 不可 repr 等）时返回 None —— 宁可不缓存也不能串。
    """
    try:
        model_name = get_embedding_model_name(provider)
    except Exception:  # pragma: no cover - settings 侧已兜底，这里只防意外
        model_name = None

    frozen_items: List[Tuple] = []
    for name in sorted(kwargs):
        value = kwargs[name]
        if value is None or isinstance(value, (str, int, float, bool)):
            frozen_items.append((name, value))
            continue
        try:
            frozen_items.append((name, repr(value)))
        except Exception:  # pragma: no cover - 极端对象
            return None

    return (provider, provider_class.__name__, model_name, tuple(frozen_items))


def clear_embeddings_cache() -> int:
    """逃生口：清空 ``get_embeddings()`` 的进程级实例缓存（测试与运维用）。

    用途：
      - 测试里 monkeypatch embedding 配置（API key / base_url / 模型名）之后，
        让下一次 ``get_embeddings()`` 真正重新构造；
      - 运维上改了不进缓存 key 的构造期配置时，手工强制失效。

    只影响本模块的 embeddings 实例；向量库索引对象的缓存在
    ``src.core.vector_db.vector_db_client.clear_vector_db_caches()`` 里，
    两者一起调即可完全复位本波次引入的全部进程级缓存。

    Returns:
        int: 被清除的条目数。
    """
    with _embeddings_cache_lock:
        removed = len(_embeddings_cache)
        _embeddings_cache.clear()
    logger.info(f"🧹 已清空 embedding 模型实例缓存（{removed} 条）")
    return removed


# 兼容任务书里的通用命名（clear_caches() 之类的逃生口）
clear_caches = clear_embeddings_cache


def get_embeddings(**kwargs):
    """
    获取全局嵌入模型实例（进程级记忆化，REFACTOR_REPORT §8.2 / 波次5-B）

    根据配置返回对应的嵌入模型（azure / openai / ollama / gemini），实现细节
    全部交给对应的 Provider，与 LLMBase.get_embedding_model() 共用同一份配置
    读取逻辑（settings.get_embedding_model_name / get_embedding_provider），
    避免各处各读一个键名导致配置被静默忽略。

    缓存语义：
    - 每次问答 / 每次 ``MetadataVectorDB()`` 构造都会走到这里，而构造一个
      OpenAIEmbeddings 之类要连带重建 SDK client——属于每请求最贵的重复构造之一。
      故按"配置指纹"记忆化：同 provider + 同模型名 + 同显式 kwargs ⇒ 返回**同一个实例**。
    - 返回的是共享实例，**调用方不得原地修改它**（不要 setattr、不要往上面挂属性）。
      全仓唯一调用方（``src/core/vector_db/metadata_db.py`` → VectorDBClient）只做
      只读调用（embed_query / embed_documents），因此共享是安全的；日后若出现要改
      配置的调用方，请通过 kwargs 落到另一个缓存条目，而不是改对象。
    - 失效：provider 与 embedding 模型名（settings.get_embedding_provider /
      get_embedding_model_name）在 key 里，改了自然落到新条目；但 **API key /
      azure endpoint / base_url 这类不进 key 的构造期配置在运行时改动不会让缓存失效**
      （与"embedding 维度固定、换模型必须重建索引"的既有限制同源）——需要立刻生效
      就调 ``clear_embeddings_cache()``，或按既有约定重启进程。
    - 逃生口：本模块 ``clear_embeddings_cache()``（测试/运维用），以及向量库侧
      ``src.core.vector_db.vector_db_client.clear_vector_db_caches()``。

    Args:
        **kwargs: 传递给嵌入模型的额外参数。会进入缓存 key；不可哈希/不可 repr 的
                  值会使本次结果不进缓存（仍照常构造并返回）。

    Returns:
        嵌入模型实例
    """
    provider = get_embedding_provider()

    provider_classes = {
        "azure": AzureLLMProvider,
        "openai": OpenAILLMProvider,
        "ollama": OllamaLLMProvider,
        "gemini": GeminiLLMProvider,
    }
    provider_class = provider_classes.get(provider)
    if provider_class is None:
        logger.error(
            f"未知的嵌入模型 provider: {provider}，"
            f"支持的取值: {sorted(provider_classes)}，默认使用 OpenAI"
        )
        provider_class = OpenAILLMProvider

    cache_key = _embeddings_cache_key(provider, provider_class, kwargs)
    if cache_key is not None:
        with _embeddings_cache_lock:
            cached = _embeddings_cache.get(cache_key)
            if cached is not None:
                try:
                    _embeddings_cache.move_to_end(cache_key)
                except KeyError:  # pragma: no cover - 并发淘汰
                    cached = None
            if cached is not None:
                logger.debug(f"♻️ 复用进程级缓存中的 embedding 模型实例 (provider={provider})")
                return cached

    embedding_model = provider_class().get_embedding_model(**kwargs)

    if cache_key is not None:
        with _embeddings_cache_lock:
            _embeddings_cache[cache_key] = embedding_model
            _embeddings_cache.move_to_end(cache_key)
            while len(_embeddings_cache) > _EMBEDDINGS_CACHE_MAX_ENTRIES:
                _embeddings_cache.popitem(last=False)

    return embedding_model