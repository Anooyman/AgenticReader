import os
from dotenv import load_dotenv
from .constants import MCPConstants, ProcessingLimits, PathConstants, PDFConstants, LLMConstants

# 导入统一的应用设置 (新增，支持 Pydantic 配置管理)
try:
    from .app_settings import AppSettings as PydanticAppSettings, settings as pydantic_settings
except ImportError:
    PydanticAppSettings = None
    pydantic_settings = None

load_dotenv()

# 导入 AgentType 用于 AgentCard 配置
from .prompts.agent_prompts import AgentType

# 使用常量文件中的定义，保持向后兼容性
class MCPToolName:
    WEB_SEARCH = MCPConstants.ToolNames.WEB_SEARCH
    MEMORY = MCPConstants.ToolNames.MEMORY

MCP_CONFIG = {
  MCPToolName.WEB_SEARCH: {
    #"playwright": {
    #    "type": "stdio",
    #    "command": "npx",
    #    "args": [
    #        "@playwright/mcp@latest"
    #    ]
    #}
    "ddg-search": {
        "type": "stdio",
        "command": "python",
        "args": ["src/services/duckduckgo_mcp_server.py"]
    },
  },
  MCPToolName.MEMORY: {
    "rag-memory": {
      "command": "npx",
      "args": ["-y", "rag-memory-mcp"],
      "type": "stdio",
    }
  },
    #"fetch": {
    #  "command": "python",
    #  "args": [
    #    "-m",
    #    "mcp_server_fetch"
    #  ]
    #},
}

# AgentCard 配置保留在这里，因为它是业务逻辑配置而非提示词
AgentCard = {
  AgentType.MEMORY:{
    "name": AgentType.MEMORY,
    "description": "MemoryAgent是负责管理、检索和处理各类记忆信息的核心组件。",
    "status": "enable",
    "tools": [
      {
        "search": "检索已有的记忆内容",
      },
      {
        "add": "更新已有的记忆"
      }
    ]
  },
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
}

# SYSTEM_PROMPT_CONFIG 现在从 prompts 模块导入
# 所有提示词配置已移至 src/config/prompts/ 目录
# 数据根目录 - 使用常量定义
DATA_ROOT = PathConstants.DATA_ROOT
PDF_IMAGE_PATH = f"{DATA_ROOT}/{PathConstants.PDF_IMAGE_DIR}"
JSON_DATA_PATH = f"{DATA_ROOT}/{PathConstants.JSON_DATA_DIR}"
PDF_PATH = f"{DATA_ROOT}/{PathConstants.PDF_DIR}"
VECTOR_DB_PATH = f"{DATA_ROOT}/{PathConstants.VECTOR_DB_DIR}"
OUTPUT_PATH = f"{DATA_ROOT}/{PathConstants.OUTPUT_DIR}"

WEB_MAX_TOKEN_COUNT = ProcessingLimits.MAX_TOKEN_COUNT

MEMORY_PATH = f"{DATA_ROOT}/{PathConstants.MEMORY_DIR}"

# PDF转图片质量配置 - 使用常量定义
PDF_IMAGE_CONFIG = {
    "dpi": PDFConstants.DEFAULT_DPI,
    "quality": "high",
    "presets": PDFConstants.QUALITY_LEVELS
}

MEMORY_VECTOR_DB_CONFIG = {
  "db_path": f"{MEMORY_PATH}/longterm_index",
  "location": {
    "file_path": f"{MEMORY_PATH}/location.json"
  },
  "person": {
    "file_path": f"{MEMORY_PATH}/person.json"
  },
  "date": {
    "file_path": f"{MEMORY_PATH}/date.json"
  },
  "tag": {
    "file_path": f"{MEMORY_PATH}/tag.json"
  }
}