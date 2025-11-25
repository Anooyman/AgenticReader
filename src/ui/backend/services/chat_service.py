"""聊天服务 - 集成PDFReader和WebReader的聊天功能"""

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
    """聊天服务类"""

    def __init__(self):
        self.pdf_reader = None
        self.web_reader = None
        self.current_doc_name = None
        self.reader_type = None  # 'pdf' or 'web'

    def initialize_pdf_reader(self, doc_name: str, provider: str = "openai", pdf_preset: str = "high") -> bool:
        """初始化PDF阅读器"""
        try:
            # 导入PDFReader
            from src.readers.pdf import PDFReader

            # 检查是否已处理过该文档
            json_path = settings.data_dir / "json_data" / f"{doc_name}.json"
            if not json_path.exists():
                logger.error(f"文档 {doc_name} 的JSON数据不存在，无法初始化聊天")
                return False

            # 初始化PDFReader
            self.pdf_reader = PDFReader(provider=provider, pdf_preset=pdf_preset)

            # 处理/加载文档数据 (save_data_flag=False 避免重新生成文件，只加载现有数据)
            try:
                self.pdf_reader.process_pdf(doc_name, save_data_flag=False)

                # 验证必要的数据是否已加载
                if hasattr(self.pdf_reader, 'agenda_dict') and self.pdf_reader.agenda_dict:
                    # 重要：确保当前文档状态已更新
                    old_doc = self.current_doc_name
                    self.current_doc_name = doc_name
                    self.reader_type = 'pdf'

                    logger.info(f"✅ PDF聊天服务初始化成功: {doc_name}")
                    logger.info(f"📊 已加载agenda_dict，章节数: {len(self.pdf_reader.agenda_dict)}")
                    if old_doc and old_doc != doc_name:
                        logger.info(f"🔄 ChatService文档已切换: {old_doc} -> {doc_name}")
                    return True
                else:
                    logger.error(f"❌ PDF数据加载不完整，agenda_dict缺失: {doc_name}")
                    return False

            except Exception as e:
                logger.error(f"❌ PDF数据处理失败: {doc_name}, 错误: {str(e)}")
                return False

        except ImportError as e:
            logger.error(f"❌ 无法导入PDFReader: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ 初始化PDF聊天服务失败: {e}")
            return False

    async def initialize_web_reader(self, doc_name: str, url: str = None, provider: str = "openai") -> bool:
        """
        初始化Web阅读器

        Args:
            doc_name: 文档名称（从URL提取）
            url: 原始URL（如果需要重新处理）
            provider: LLM提供商，默认为openai

        Returns:
            bool: 初始化是否成功
        """
        try:
            # 导入WebReader
            from src.readers.web import WebReader
            import json
            import os
            from pathlib import Path

            # 🔥 向后兼容：检查多种可能的文件名格式
            json_data_dir = settings.data_dir / "json_data"
            json_path = json_data_dir / f"{doc_name}.json"
            
            # 如果标准文件名不存在，尝试查找包含特殊字符的旧文件名
            if not json_path.exists():
                logger.warning(f"标准文件名不存在: {json_path.name}")
                logger.info(f"🔍 尝试在 {json_data_dir} 中查找匹配的文件...")
                
                # 查找所有可能匹配的 JSON 文件（文件名开头匹配）
                if json_data_dir.exists():
                    # 规范化 doc_name 用于比较（移除空格）
                    doc_name_normalized = doc_name.replace(' ', '').lower()
                    
                    for candidate in json_data_dir.glob("*.json"):
                        # 规范化候选文件名用于比较
                        candidate_normalized = candidate.stem.replace(' ', '').lower()
                        
                        # 如果候选文件名以 doc_name 开头（忽略特殊字符）
                        if candidate_normalized.startswith(doc_name_normalized):
                            json_path = candidate
                            logger.info(f"✅ 找到匹配文件: {json_path.name}")
                            break
            
            if not json_path.exists():
                logger.error(f"文档 {doc_name} 的JSON数据不存在，无法初始化聊天")
                return False

            # 初始化WebReader
            self.web_reader = WebReader(provider=provider)

            # 加载JSON数据
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    web_content = json.load(f)

                # 检查是否有向量数据库（大文件）
                vector_db_path = settings.data_dir / "vector_db" / f"{doc_name}_vector_db"

                # 🔥 初始化聊天历史（无论大小文件都需要）
                from langchain.memory import ChatMessageHistory
                if not hasattr(self.web_reader, 'message_history') or self.web_reader.message_history is None:
                    self.web_reader.message_history = {}
                if "chat" not in self.web_reader.message_history:
                    self.web_reader.message_history["chat"] = ChatMessageHistory()

                if vector_db_path.exists():
                    # 大文件模式：使用向量数据库
                    from src.core.vector_db.vector_db_client import VectorDBClient
                    self.web_reader.vector_db_obj = VectorDBClient(str(vector_db_path), provider=provider)

                    # 加载向量数据库数据
                    self.web_reader.get_data_from_vector_db()

                    logger.info(f"✅ Web内容已从向量数据库加载: {doc_name}")
                else:
                    # 小文件模式：直接使用内容
                    content_str = ', '.join(web_content) if isinstance(web_content, list) else str(web_content)
                    self.web_reader.web_content = content_str

                    logger.info(f"✅ Web内容已直接加载: {doc_name}, 长度: {len(content_str)} 字符")
                
                logger.info(f"✅ 聊天历史已初始化")

                # 更新当前文档状态
                old_doc = self.current_doc_name
                self.current_doc_name = doc_name
                self.reader_type = 'web'

                if old_doc and old_doc != doc_name:
                    logger.info(f"🔄 ChatService文档已切换: {old_doc} -> {doc_name}")

                logger.info(f"✅ Web聊天服务初始化成功: {doc_name}")
                return True

            except Exception as e:
                logger.error(f"❌ Web数据加载失败: {doc_name}, 错误: {str(e)}")
                return False

        except ImportError as e:
            logger.error(f"❌ 无法导入WebReader: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ 初始化Web聊天服务失败: {e}")
            return False

    def chat(self, message: str) -> Optional[str]:
        """执行聊天对话"""
        if not self.current_doc_name:
            return "❌ 聊天服务未初始化，请先处理文档"

        try:
            if self.reader_type == 'pdf' and self.pdf_reader:
                # 验证PDF阅读器状态
                if not hasattr(self.pdf_reader, 'agenda_dict') or not self.pdf_reader.agenda_dict:
                    logger.error(f"❌ PDF阅读器状态异常，agenda_dict缺失: {self.current_doc_name}")
                    return "❌ PDF阅读器状态异常，请重新初始化文档"

                logger.info(f"💬 处理PDF聊天消息 - 文档: {self.current_doc_name}, 消息: {message[:50]}...")
                response = self.pdf_reader.chat(message)
                logger.info(f"📝 PDF聊天回复生成成功，消息长度: {len(str(response))}")
                return str(response)
            elif self.reader_type == 'web' and self.web_reader:
                logger.info(f"💬 处理Web聊天消息 - 文档: {self.current_doc_name}, 消息: {message[:50]}...")
                response = self.web_reader.chat(message)
                logger.info(f"📝 Web聊天回复生成成功，消息长度: {len(str(response))}")
                return str(response)
            else:
                logger.error(f"❌ 聊天服务状态异常 - reader_type: {self.reader_type}, pdf_reader: {self.pdf_reader is not None}, web_reader: {self.web_reader is not None}")
                return "❌ 聊天服务状态异常，请重新加载文档"

        except Exception as e:
            logger.error(f"❌ 聊天处理失败: {e}")
            return f"❌ 聊天处理时发生错误: {str(e)}"

    def get_status(self) -> dict:
        """获取聊天服务状态"""
        return {
            "initialized": self.current_doc_name is not None,
            "doc_name": self.current_doc_name,
            "reader_type": self.reader_type,
            "has_pdf_reader": self.pdf_reader is not None,
            "has_web_reader": self.web_reader is not None
        }

    def reset(self):
        """重置聊天服务"""
        self.pdf_reader = None
        self.web_reader = None
        self.current_doc_name = None
        self.reader_type = None
        logger.info("🔄 聊天服务已重置")


# 全局聊天服务实例
chat_service = ChatService()