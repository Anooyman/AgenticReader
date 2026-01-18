"""
AnswerAgent 辅助方法

内部辅助工具，不对外暴露
"""

from __future__ import annotations
from typing import TYPE_CHECKING
import logging

from .state import AnswerState

if TYPE_CHECKING:
    from .agent import AnswerAgent

logger = logging.getLogger(__name__)


class AnswerUtils:
    """AnswerAgent 辅助工具集合"""

    def __init__(self, agent: 'AnswerAgent'):
        """
        Args:
            agent: AnswerAgent实例（依赖注入）
        """
        self.agent = agent

    def validate_state(self, state: AnswerState) -> None:
        """
        验证state的完整性

        Args:
            state: AnswerState对象

        Raises:
            ValueError: 缺少必需字段时抛出异常
        """

        required_fields = ['user_query']

        for field in required_fields:
            if field not in state:
                raise ValueError(f"❌ [Validate] State缺少必需字段: {field}")

        # 验证字段类型和值
        if not isinstance(state.get('user_query', ''), str) or not state.get('user_query', '').strip():
            raise ValueError("❌ [Validate] user_query字段必须是非空字符串")

        logger.debug(f"✅ [Validate] State验证通过")
