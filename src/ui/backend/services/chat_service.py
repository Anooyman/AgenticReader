"""聊天服务 - 使用 AnswerAgent 的聊天功能"""

import sys
from pathlib import Path
from typing import Optional, Any

# 添加项目根路径到sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ..config.logging import get_logger
from ..config import settings

logger = get_logger(__name__)


class ChatService:
    """聊天服务类 - 基于 AnswerAgent"""

    def __init__(self):
        self.answer_agent = None
        self.current_doc_name = None
        self.doc_type = None  # 'pdf' or 'web'

    def initialize_chat(self, doc_name: str, doc_type: str = "pdf") -> bool:
        """
        初始化聊天服务（统一接口，支持PDF和Web）

        Args:
            doc_name: 文档名称
            doc_type: 文档类型 ('pdf' 或 'web')

        Returns:
            bool: 初始化是否成功
        """
        try:
            # 检查文档是否已索引（检查向量数据库是否存在）
            vector_db_path = settings.data_dir / "vector_db" / f"{doc_name}_data_index"
            if not vector_db_path.exists():
                logger.error(f"文档 {doc_name} 的向量数据库不存在，无法初始化聊天")
                logger.error(f"请先索引该文档")
                return False

            # 导入 AnswerAgent
            from src.agents.answer import AnswerAgent

            # 初始化 AnswerAgent
            self.answer_agent = AnswerAgent(doc_name=doc_name)

            # 更新当前文档状态
            old_doc = self.current_doc_name
            self.current_doc_name = doc_name
            self.doc_type = doc_type

            logger.info(f"✅ 聊天服务初始化成功: {doc_name} (类型: {doc_type})")
            if old_doc and old_doc != doc_name:
                logger.info(f"🔄 ChatService文档已切换: {old_doc} -> {doc_name}")

            return True

        except ImportError as e:
            logger.error(f"❌ 无法导入 AnswerAgent: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ 初始化聊天服务失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def initialize_pdf_reader(self, doc_name: str, provider: str = "openai", pdf_preset: str = "high") -> bool:
        """初始化PDF阅读器（向后兼容接口）"""
        logger.info(f"📄 初始化PDF聊天: {doc_name}")
        return self.initialize_chat(doc_name, doc_type="pdf")

    async def initialize_web_reader(self, doc_name: str, url: str = None, provider: str = "openai") -> bool:
        """初始化Web阅读器（向后兼容接口）"""
        logger.info(f"🌐 初始化Web聊天: {doc_name}")
        return self.initialize_chat(doc_name, doc_type="web")

    async def chat(self, message: str) -> Optional[str]:
        """
        执行聊天对话

        Args:
            message: 用户消息

        Returns:
            str: AI回复
        """
        if not self.current_doc_name or not self.answer_agent:
            return "❌ 聊天服务未初始化，请先处理文档"

        try:
            logger.info(f"💬 处理聊天消息 - 文档: {self.current_doc_name}, 消息: {message[:50]}...")

            # 调用 AnswerAgent
            result = await self.answer_agent.graph.ainvoke({
                "user_query": message,
                "current_doc": self.current_doc_name,
                "needs_retrieval": False,
                "is_complete": False
            })

            # 提取回答
            final_answer = result.get("final_answer", "")

            if not final_answer:
                logger.warning("⚠️ AnswerAgent 返回空回答")
                return "抱歉，我暂时无法回答这个问题。"

            logger.info(f"📝 聊天回复生成成功，长度: {len(final_answer)} 字符")
            return final_answer

        except Exception as e:
            logger.error(f"❌ 聊天处理失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return f"❌ 聊天处理时发生错误: {str(e)}"

    def get_status(self) -> dict:
        """获取聊天服务状态"""
        return {
            "initialized": self.current_doc_name is not None,
            "doc_name": self.current_doc_name,
            "doc_type": self.doc_type,
            # 保持向后兼容，外部部分代码使用 reader_type
            "reader_type": self.doc_type,
            "has_agent": self.answer_agent is not None
        }

    def reset(self):
        """重置聊天服务"""
        self.answer_agent = None
        self.current_doc_name = None
        self.doc_type = None
        logger.info("🔄 聊天服务已重置")


# 全局聊天服务实例
chat_service = ChatService()
