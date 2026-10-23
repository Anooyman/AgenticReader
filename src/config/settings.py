import os
import sys
import logging
from dotenv import load_dotenv
from .constants import PathConstants, PDFConstants

logger = logging.getLogger(__name__)

load_dotenv()

MCP_CONFIG = {
  # ===== SearchAgent MCP 服务（顶层配置）=====
  # DuckDuckGo 搜索引擎
  "duckduckgo": {
    "type": "stdio",
    "command": "uvx",
    "args": ["duckduckgo-mcp-server"],
    "env": {}
  },
  # Web Scraper 服务
  "web_scraper": {
    "type": "stdio",
    "command": sys.executable,
    "args": ["-m", "scraper.mcp_server.server"],
    "env": {"PYTHONPATH": "src/services"}
  },
    #"fetch": {
    #  "command": "python",
    #  "args": [
    #    "-m",
    #    "mcp_server_fetch"
    #  ]
    #},
}


LLM_CONFIG = {
    # Azure OpenAI 配置
    "api_key": os.getenv("CHAT_API_KEY"),
    "api_version": os.getenv("CHAT_API_VERSION"),
    "azure_endpoint": os.getenv("CHAT_AZURE_ENDPOINT"),
    "deployment_name": os.getenv("CHAT_DEPLOYMENT_NAME"),
    "model_name": os.getenv("CHAT_MODEL_NAME"),

    # OpenAI 配置
    "openai_api_key": os.getenv("OPENAI_API_KEY"),
    "openai_model_name": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
    "openai_base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/"),

    # Ollama 配置
    "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    "ollama_model_name": os.getenv("OLLAMA_MODEL_NAME", "llama3"),

    # Gemini 配置
    "gemini_api_key": os.getenv("GEMINI_API_KEY"),
    "gemini_model_name": os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-pro"),
    "gemini_base_url": os.getenv("GEMINI_BASE_URL"),
}

LLM_EMBEDDING_CONFIG = {
    # Azure OpenAI Embedding 配置
    "api_key": os.getenv("EMBEDDING_API_KEY"),
    "api_version": os.getenv("EMBEDDING_API_VERSION"),
    "azure_endpoint": os.getenv("EMBEDDING_AZURE_ENDPOINT"),
    "deployment": os.getenv("EMBEDDING_DEPLOYMENT"),
    "model": os.getenv("EMBEDDING_MODEL"),

    # OpenAI Embedding 配置
    "openai_api_key": os.getenv("OPENAI_API_KEY"),
    "openai_embedding_model": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-ada-002"),

    # Ollama Embedding 配置
    "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    "ollama_model": os.getenv("OLLAMA_EMBEDDING_MODEL", "llama3"),

    # Gemini Embedding 配置
    "gemini_api_key": os.getenv("GEMINI_API_KEY"),
    "gemini_embedding_model": os.getenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004"),
    "gemini_base_url": os.getenv("GEMINI_BASE_URL"),

    # 嵌入模型使用的 provider。以前这个键在 settings 里不存在，get_embeddings()
    # 的 .get("provider", "openai") 只能永远走默认值；这里补成真正的配置项，
    # 默认值仍是 "openai"（与旧行为一致）。
    "provider": os.getenv("EMBEDDING_PROVIDER", "openai"),
}

# ==================== Embedding 模型名的单一读取来源 ====================
# 历史上模型名在各处各读各的：settings 定义的是 "openai_embedding_model"
# （env OPENAI_EMBEDDING_MODEL），而 core/llm/client.py 与 core/llm/providers.py
# 读的是 settings 里根本不存在的 "openai_model" —— 结果用户通过环境变量配的
# openai embedding 模型被静默忽略、落回 text-embedding-ada-002。memory 侧读的是
# 正确的键，于是"用的模型"和"建表用的维度"可能各说各话，写坏 LanceDB 库。
# 下面三个函数是所有地方取 embedding provider / 模型名 / 对应环境变量的唯一入口，
# 新代码不要再直接 LLM_EMBEDDING_CONFIG.get("<模型名键>")。

# provider -> (settings 键, 对应环境变量, 代码默认模型名)
# 环境变量名只用于报错时告诉用户"该改哪一条"，不参与读取。
_EMBEDDING_MODEL_FIELDS = {
    "azure": ("model", "EMBEDDING_MODEL", None),
    "openai": ("openai_embedding_model", "OPENAI_EMBEDDING_MODEL", "text-embedding-ada-002"),
    "ollama": ("ollama_model", "OLLAMA_EMBEDDING_MODEL", "llama3"),
    "gemini": ("gemini_embedding_model", "GEMINI_EMBEDDING_MODEL", "text-embedding-004"),
}


def get_embedding_provider(default: str = "openai") -> str:
    """当前配置里嵌入模型使用的 provider（小写，默认 openai）。"""
    provider = LLM_EMBEDDING_CONFIG.get("provider") or default
    return str(provider).strip().lower()


def get_embedding_model_name(provider: str = "openai"):
    """取该 provider 配置的 embedding 模型名；配置缺失时回退到代码默认值。

    provider 名不认识时记录错误并返回 None（调用方应意识到自己传错了 provider，
    而不是悄悄拿一个别的 provider 的值）。
    """
    key = str(provider or "").strip().lower()
    fields = _EMBEDDING_MODEL_FIELDS.get(key)
    if fields is None:
        logger.error(
            "get_embedding_model_name: 未知的 embedding provider %r，"
            "支持的取值: %s",
            provider, sorted(_EMBEDDING_MODEL_FIELDS),
        )
        return None
    cfg_key, _env_var, fallback = fields
    return LLM_EMBEDDING_CONFIG.get(cfg_key) or fallback


def get_embedding_model_env_var(provider: str = "openai") -> str:
    """该 provider 的 embedding 模型名对应的环境变量名（仅用于错误/日志提示）。"""
    fields = _EMBEDDING_MODEL_FIELDS.get(str(provider or "").strip().lower())
    return fields[1] if fields else "EMBEDDING_MODEL"

# SYSTEM_PROMPT_CONFIG 现在从 prompts 模块导入
# 所有提示词配置已移至 src/config/prompts/ 目录
# 数据根目录 - 使用常量定义
DATA_ROOT = PathConstants.DATA_ROOT
PDF_IMAGE_PATH = f"{DATA_ROOT}/{PathConstants.PDF_IMAGE_DIR}"
JSON_DATA_PATH = f"{DATA_ROOT}/{PathConstants.JSON_DATA_DIR}"
PDF_PATH = f"{DATA_ROOT}/{PathConstants.PDF_DIR}"

# PDF转图片质量配置 - 使用常量定义
PDF_IMAGE_CONFIG = {
    "dpi": PDFConstants.DEFAULT_DPI,
    "quality": "high",
    "presets": PDFConstants.QUALITY_LEVELS
}

# ==================== 跨文档检索配置 ====================
CROSS_DOC_CONFIG = {
    "max_parallel_retrievals": 3,      # 最大并行检索数
    "retrieval_timeout": 1200,          # 单个检索超时（秒）
    "max_iterations": 10,              # 每个Retrieval Agent的最大迭代次数
}