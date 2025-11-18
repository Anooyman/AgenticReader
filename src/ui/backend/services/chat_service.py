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

    def initialize_web_reader(self, doc_name: str, provider: str = "openai") -> bool:
        """初始化Web阅读器"""
        try:
            # 导入WebReader
            from src.readers.web import WebReader

            # 检查是否已处理过该文档
            json_path = settings.data_dir / "json_data" / f"{doc_name}.json"
            if not json_path.exists():
                logger.error(f"文档 {doc_name} 的JSON数据不存在，无法初始化聊天")
                return False

            # 初始化WebReader
            self.web_reader = WebReader(provider=provider)

            # 处理/加载文档数据 (需要根据WebReader的实际API调整)
            try:
                # 注意：WebReader可能有不同的加载方式，需要检查其实际方法
                # 这里先假设使用类似的模式，如果WebReader API不同需要调整
                if hasattr(self.web_reader, 'process_url'):
                    # 如果WebReader有process_url方法
                    logger.warning(f"⚠️ WebReader集成需要进一步调整API")
                else:
                    # 暂时设置基础状态，待后续完善WebReader集成
                    pass

                self.current_doc_name = doc_name
                self.reader_type = 'web'
                logger.info(f"✅ Web聊天服务初始化成功: {doc_name}")
                return True

            except Exception as e:
                logger.error(f"❌ Web数据处理失败: {doc_name}, 错误: {str(e)}")
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