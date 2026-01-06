"""
history.py - Chat message history management with smart truncation and LLM summarization

This module provides advanced message history management for LLM conversations:
- Token and message count limits
- Simple truncation strategy
- LLM-based intelligent summarization
- Automatic history cleanup

Classes:
    LimitedChatMessageHistory: Enhanced message history with multiple management strategies
"""
import logging
from typing import Any, Optional, List
from pydantic import Field
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.chat_history import InMemoryChatMessageHistory

from src.config.constants import ProcessingLimits, LLMConstants

logger = logging.getLogger(__name__)


class LimitedChatMessageHistory(InMemoryChatMessageHistory):
    """
    带有限制功能的聊天消息历史记录管理类

    扩展InMemoryChatMessageHistory，增加以下功能：
    - 消息数量限制：通过max_messages参数控制最大消息条数
    - Token数量限制：通过max_tokens参数控制总Token数不超过模型上下文窗口
    - 自动清理：当消息数量或Token数超出限制时，自动移除最早的消息或使用LLM进行智能总结
    - LLM总结：支持使用LLM对历史消息进行智能总结，而非简单截断

    Attributes:
        max_messages (int): 最大消息数量限制，默认从ProcessingLimits.DEFAULT_MAX_MESSAGES获取
        max_tokens (int): 最大Token数量限制，默认从ProcessingLimits.DEFAULT_MAX_TOKENS获取
        encoding_name (str): Token编码名称，默认从LLMConstants.DEFAULT_ENCODING获取
        use_llm_summary (bool): 是否使用LLM进行历史总结，默认False
        llm_client (Any): LLM客户端实例，用于执行总结任务
        summary_threshold (int): 触发总结的消息数量阈值
    """

    # 使用Pydantic字段定义自定义属性
    max_messages: int = Field(default_factory=lambda: ProcessingLimits.DEFAULT_MAX_MESSAGES)
    max_tokens: int = Field(default_factory=lambda: ProcessingLimits.DEFAULT_MAX_TOKENS)
    encoding_name: str = Field(default_factory=lambda: LLMConstants.DEFAULT_ENCODING)
    use_llm_summary: bool = Field(default=False)
    llm_client: Optional[Any] = Field(default=None)
    summary_threshold: int = Field(default=10)

    def __init__(self, max_messages: int = None, max_tokens: int = None,
                 encoding_name: str = None, use_llm_summary: bool = False,
                 llm_client: Any = None, summary_threshold: int = 10, **kwargs):
        """
        初始化限制型聊天消息历史

        Args:
            max_messages (int): 最大消息数量限制
            max_tokens (int): 最大Token数量限制
            encoding_name (str): Token编码名称
            use_llm_summary (bool): 是否使用LLM进行历史总结
            llm_client (Any): LLM客户端实例
            summary_threshold (int): 触发总结的消息数量阈值
            **kwargs: 传递给父类的其他参数
        """
        # 设置自定义字段的值
        if max_messages is not None:
            kwargs['max_messages'] = max_messages
        if max_tokens is not None:
            kwargs['max_tokens'] = max_tokens
        if encoding_name is not None:
            kwargs['encoding_name'] = encoding_name
        kwargs['use_llm_summary'] = use_llm_summary
        kwargs['llm_client'] = llm_client
        kwargs['summary_threshold'] = summary_threshold

        super().__init__(**kwargs)

        logger.debug(f"LimitedChatMessageHistory初始化: max_messages={self.max_messages}, "
                    f"max_tokens={self.max_tokens}, encoding={self.encoding_name}, "
                    f"use_llm_summary={self.use_llm_summary}")

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

    def _trim_history_by_truncation(self):
        """
        通过简单截断来修剪历史消息

        该方法实现两级截断策略：
        1. 按消息数量截断：保留最新的max_messages条消息
        2. 按Token数量截断：循环移除最早的消息直到Token总数低于max_tokens
        """
        # 1. 限制消息条数 - 保留最新的max_messages条消息
        if len(self.messages) > self.max_messages:
            logger.info(f"[Truncation] 消息数量超出限制({self.max_messages})，截断至最新 {self.max_messages} 条。")
            self.messages = self.messages[-self.max_messages:]

        # 2. 限制Token总数 - 循环移除最早消息直到Token数达标
        removed_count = 0
        while self._total_tokens() > self.max_tokens and len(self.messages) > 1:
            self.messages.pop(0)
            removed_count += 1

        if removed_count > 0:
            logger.info(f"[Truncation] Token总数超出限制({self.max_tokens})，已移除最早的 {removed_count} 条消息。")

    def _summarize_history_with_llm(self):
        """
        使用LLM对历史消息进行智能总结

        当对话轮数超过summary_threshold时，使用LLM对所有消息进行总结，
        将所有历史消息压缩为一条总结消息，完全清空原始对话，从而最大化节省上下文空间。

        压缩策略：
        1. **总结所有消息**：将所有消息通过LLM总结为1条SystemMessage
        2. **不保留原始对话**：清空所有原始消息，只保留总结
        3. **最大化压缩**：压缩后只有1条总结消息，压缩率最高

        示例：
            - 当前有12条消息（6轮对话），summary_threshold=5
            - 触发压缩：超过5轮，需要总结
            - 总结所有12条消息
            - 清空所有原始消息
            - 结果：只有1条总结消息（压缩率：91.7%）

        Note:
            summary_threshold 表示对话轮数，每轮包含一个问题和一个回答（2条消息）
            例如 summary_threshold=5 表示允许最多 5 轮对话（10条消息）不压缩
            压缩后完全清空历史，后续对话将基于总结继续
        """
        # 计算当前对话轮数（向下取整，一轮 = 2条消息）
        conversation_rounds = len(self.messages) // 2

        # 检查是否需要总结（基于对话轮数）
        if conversation_rounds <= self.summary_threshold:
            return

        # 检查LLM客户端是否可用
        if not self.llm_client:
            logger.warning("[LLM Summary] LLM客户端未配置，回退到截断模式")
            self._trim_history_by_truncation()
            return

        try:
            # 压缩策略：总结所有消息，不保留任何原始对话
            # 完全清空对话历史，只保留LLM生成的总结

            # 要总结的消息 = 所有消息
            messages_to_summarize = self.messages

            if len(messages_to_summarize) < 2:  # 至少需要2条消息才有总结的意义
                logger.info("[LLM Summary] 消息数量不足，使用截断模式")
                self._trim_history_by_truncation()
                return

            logger.info(f"[LLM Summary] 准备总结所有 {len(messages_to_summarize)} 条消息，"
                       f"不保留原始对话")

            # 构建总结提示词
            conversation_text = self._format_messages_for_summary(messages_to_summarize)
            summary_prompt = f"""请总结以下对话历史，保留关键信息、重要观点和上下文：

{conversation_text}

请提供一个简洁但全面的总结，包括：
1. 主要讨论的话题
2. 关键信息和决策
3. 重要的上下文背景

总结："""

            # 调用LLM进行总结
            summary = self._call_llm_for_summary(summary_prompt)

            if summary:
                # 创建总结消息
                summary_message = SystemMessage(content=f"[对话历史总结]\n{summary}")

                # 替换消息历史：清空所有原始消息，只保留总结
                # 这样可以实现最大化压缩效果，所有对话内容都浓缩在总结中
                self.messages = [summary_message]

                logger.info(f"[LLM Summary] 总结完成，压缩 {len(messages_to_summarize)} 条 → 1 条总结，"
                           f"已清空所有原始对话，当前总消息数：{len(self.messages)}")

                # 如果总结后仍然超过token限制，进行额外的截断
                if self._total_tokens() > self.max_tokens:
                    logger.warning("[LLM Summary] 总结后仍超过token限制，进行额外截断")
                    self._trim_history_by_truncation()
            else:
                logger.warning("[LLM Summary] 总结失败，回退到截断模式")
                self._trim_history_by_truncation()

        except Exception as e:
            logger.error(f"[LLM Summary] 总结过程出错: {e}，回退到截断模式")
            self._trim_history_by_truncation()

    def _format_messages_for_summary(self, messages: List) -> str:
        """
        将消息列表格式化为可读的对话文本

        Args:
            messages: 消息列表

        Returns:
            格式化后的对话文本
        """
        formatted_lines = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                role = "用户"
            elif isinstance(msg, AIMessage):
                role = "助手"
            elif isinstance(msg, SystemMessage):
                role = "系统"
            else:
                role = "未知"

            content = getattr(msg, 'content', '')
            if content:
                formatted_lines.append(f"{role}: {content}")

        return "\n".join(formatted_lines)

    def _call_llm_for_summary(self, prompt: str) -> str:
        """
        调用LLM生成总结

        Args:
            prompt: 总结提示词

        Returns:
            LLM生成的总结文本
        """
        try:
            # 使用同步调用（如果需要异步，可以改为async方法）
            if hasattr(self.llm_client, 'chat_model'):
                response = self.llm_client.chat_model.invoke(prompt)
                if hasattr(response, 'content'):
                    return response.content
                return str(response)
            else:
                logger.error("[LLM Summary] LLM客户端格式不正确")
                return ""
        except Exception as e:
            logger.error(f"[LLM Summary] LLM调用失败: {e}")
            return ""

    def add_message(self, message):
        """
        添加消息到历史，并自动进行历史管理

        根据配置，使用以下两种策略之一：
        1. LLM智能总结：使用LLM对历史消息进行总结压缩
        2. 简单截断：移除最早的消息
        """
        super().add_message(message)

        # 根据配置选择历史管理策略
        if self.use_llm_summary and self.llm_client:
            self._summarize_history_with_llm()
        else:
            self._trim_history_by_truncation()

    def delete_last_message(self):
        """删除最后一条消息"""
        if self.messages:
            removed_message = self.messages.pop()
            logger.info(f"[LimitedChatMessageHistory] 删除最后一条消息: {removed_message}")
        else:
            logger.warning("[LimitedChatMessageHistory] 无消息可删除。")
