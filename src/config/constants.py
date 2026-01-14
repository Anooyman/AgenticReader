"""
LLMReader 项目常量配置
常量定义文件，用于集中管理项目中的各种配置常量，避免硬编码魔术数字
"""

# === 处理限制常量 ===
class ProcessingLimits:
    """处理过程中的各种限制常量"""

    # PDF处理相关
    MAX_CHAPTER_LENGTH = 10  # 章节最大长度限制
    DEFAULT_CHUNK_SIZE = 20  # PDF分块处理的默认大小

    # Token相关限制
    MAX_TOKEN_COUNT = 3000  # Web内容最大Token数

    # 重试和超时
    MAX_MCP_ATTEMPTS = 10  # MCP服务最大调用尝试次数
    DEFAULT_SEARCH_K = 10  # 默认检索结果数量
    DEFAULT_RECURSION_LIMIT = 50  # 图执行递归限制

    # 注意：会话历史相关配置（max_messages, max_tokens）已移至 SessionHistoryConfig


# === 文件和路径常量 ===
class PathConstants:
    """文件路径相关常量"""

    # 数据目录结构
    DATA_ROOT = "data"
    PDF_DIR = "pdf"
    PDF_IMAGE_DIR = "pdf_image"
    JSON_DATA_DIR = "json_data"
    VECTOR_DB_DIR = "vector_db"
    OUTPUT_DIR = "output"
    MEMORY_DIR = "memory"


# === PDF处理常量 ===
class PDFConstants:
    """PDF处理相关常量"""

    # PDF转图片质量配置
    DEFAULT_DPI = 300
    QUALITY_LEVELS = {
        "low": {"dpi": 150, "scale": 2.0},
        "medium": {"dpi": 200, "scale": 3.0},
        "high": {"dpi": 300, "scale": 4.0},
        "ultra": {"dpi": 600, "scale": 5.0}
    }

    # 支持的图片格式
    SUPPORTED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.bmp', '.gif']


# === MCP和工具常量 ===
class MCPConstants:
    """MCP服务相关常量"""

    # 工具标识
    TOOL_STOP_FLAG = "Observation"  # MCP工具调用停止标识符

    # 工具名称
    class ToolNames:
        WEB_SEARCH = "web search"
        MEMORY = "memory"


# === LLM相关常量 ===
class LLMConstants:
    """LLM处理相关常量"""

    # 提供商类型
    class Providers:
        AZURE = "azure"
        OPENAI = "openai"
        OLLAMA = "ollama"

    # 默认配置
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_RETRIES = 5
    DEFAULT_ENCODING = "o200k_base"


# === 会话历史管理常量 ===
class SessionHistoryConfig:
    """会话历史管理配置

    定义不同类型会话的消息历史管理参数。
    每种会话类型包含以下配置：
    - max_messages: 最大消息数量（兜底值，当LLM总结失败时使用）
    - max_tokens: 最大Token数量限制（超过则触发截断）
    - summary_threshold: 触发LLM总结的对话轮数阈值
    - use_llm_summary: 是否启用LLM智能总结（默认True）

    Note:
        - 对话轮数 = 消息数量 / 2（一轮对话包含1个问题和1个回答）
        - summary_threshold=3 表示第4轮对话时触发总结（即超过3轮）
        - max_messages 应设置为远大于 summary_threshold*2 的值，作为总结失败的兜底
        - max_tokens 用于控制总Token数，防止超过LLM上下文窗口限制
    """

    # Web Chat Session 配置（session_id="chat"）
    # 用于 UI 的 Web 内容对话，使用较宽松的限制
    WEB_CHAT = {
        "max_messages": 10,           # 兜底值：总结失败时的硬上限
        "max_tokens": 65536,           # 最大Token数（Claude 3.5 Sonnet上下文窗口）
        "summary_threshold": 3,        # 5轮对话后触发总结（10条消息）
        "use_llm_summary": True,       # 启用LLM智能总结
    }

    # PDF Chat Session 配置（session_id="answer"等）
    # 用于 PDF 文档对话（CLI 和 UI），使用较严格的限制
    PDF_CHAT = {
        "max_messages": 10,            # 兜底值：总结失败时的硬上限
        "max_tokens": 65536,           # 最大Token数（Claude 3.5 Sonnet上下文窗口）
        "summary_threshold": 3,        # 3轮对话后触发总结（6条消息）
        "use_llm_summary": True,       # 启用LLM智能总结
    }

    # 默认 Session 配置
    # 用于其他未明确分类的会话
    DEFAULT = {
        "max_messages": 10,            # 兜底值：总结失败时的硬上限
        "max_tokens": 65536,           # 最大Token数（Claude 3.5 Sonnet上下文窗口）
        "summary_threshold": 3,        # 3轮对话后触发总结（6条消息）
        "use_llm_summary": True,       # 启用LLM智能总结
    }

    # Session ID 到配置的映射
    SESSION_TYPE_MAP = {
        "chat": WEB_CHAT,              # Web Chat UI
        "answer": PDF_CHAT,            # PDF Chat (UI & CLI)
    }

    @classmethod
    def get_config(cls, session_id: str) -> dict:
        """
        根据 session_id 获取对应的配置

        Args:
            session_id: 会话ID

        Returns:
            配置字典，包含 max_messages, summary_threshold, use_llm_summary
        """
        return cls.SESSION_TYPE_MAP.get(session_id, cls.DEFAULT)


# === Reader处理常量 ===
class ReaderConstants:
    """Reader相关常量"""
    
    # 文件后缀
    VECTOR_DB_SUFFIX = "_data_index"  # 向量数据库路径后缀
    FORMAT_DATA_SUFFIX = "_format_data.json"  # 格式化数据文件后缀
    
    # 分块处理
    DEFAULT_CHUNK_COUNT = 20  # PDF分块处理的默认大小


# === 安全相关常量 ===
class SecurityConstants:
    """安全验证相关常量"""

    # 文件大小限制
    MAX_FILE_SIZE_MB = 100  # 文件最大大小（MB）

    # URL长度限制
    MAX_URL_LENGTH = 2048  # URL最大长度

    # 输入长度限制
    MAX_INPUT_LENGTH = 10000  # 一般输入的最大长度

    # 支持的文件扩展名
    ALLOWED_EXTENSIONS = {
        '.pdf', '.txt', '.md', '.json', '.csv',
        '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx',
        '.jpg', '.jpeg', '.png', '.gif', '.bmp',
        '.mp3', '.mp4', '.wav', '.avi'
    }