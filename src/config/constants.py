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
    DEFAULT_MAX_MESSAGES = 20  # 聊天历史默认最大消息数
    DEFAULT_MAX_TOKENS = 65536 # 聊天历史默认最大Token数

    # 重试和超时
    MAX_MCP_ATTEMPTS = 10  # MCP服务最大调用尝试次数
    DEFAULT_SEARCH_K = 10  # 默认检索结果数量
    DEFAULT_RECURSION_LIMIT = 50  # 图执行递归限制


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