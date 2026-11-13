import os
import sys
import logging
from typing import Any, Dict
from dotenv import load_dotenv
from .constants import PathConstants, PDFConstants, get_data_root

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
    "openai_model_name": os.getenv("OPENAI_MODEL_NAME", "gpt-6-luna"),
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

# —— 对话侧 provider 的唯一选择入口（REFACTOR_REPORT §8.4）——
# 背景：/config 页把 provider 持久化进 data/config/app_config.json（见
# src/ui/backend/api/v1/config.py），但 chat_ingest/job_runner/memory 搜索/
# 管线脚本/Orchestrator 及其子 agent 一度写死 "openai" 十余处，页面上切
# provider 只影响文档校验用的 AnswerAgent，其余链路全部无感。现所有"默认
# provider"的消费者一律走 resolve_provider()。优先级：
#   显式非空参数 > app_config.json 的 provider > env PROVIDER > "openai"
# 后两级让 CLI（无配置文件）也能不改代码换 provider。
APP_CONFIG_FILE = get_data_root() / "config" / "app_config.json"


def get_default_provider() -> str:
    """缺省 provider：app_config.json -> env PROVIDER -> "openai"。

    文件缺失/坏损/无 provider 键时静默按优先级回退——这些函数被后台车道和
    CLI 共用，配置问题不应该炸掉一次问答，回退 + 上层日志即可。"""
    try:
        if APP_CONFIG_FILE.exists():
            import json as _json
            with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = _json.load(f)
            value = cfg.get("provider") if isinstance(cfg, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
    except Exception:
        logger.debug("app_config.json 读取失败，provider 回退到 env/默认值", exc_info=True)
    env_value = os.environ.get("PROVIDER", "").strip()
    if env_value:
        return env_value.lower()
    return "openai"


def resolve_provider(provider=None) -> str:
    """显式传入非空 provider 时原样采用（小写化），否则走 get_default_provider()。

    既有显式传参的调用方（tests、agent 间互调）行为不变——这是本函数存在的
    前提：它只做"缺省补全"，不做"强制覆盖"。"""
    if provider and str(provider).strip():
        return str(provider).strip().lower()
    return get_default_provider()


# ==================== 模型注册表（UI 可配置的多模型列表） ====================
# 背景：此前每个 provider 只有一个模型名（env 变量 / 代码默认值），想换模型
# 只能改 .env 重启。现在支持在 /config 页给每个 provider 登记多个模型
# （名字 + 模型名 + 可选 base_url / api_key 覆盖），选一个作为该 provider
# 的"当前模型"，LLM 构造链路（providers.py）从注册表读取覆盖值。
# 持久化位置与 provider 选择同文件：data/config/app_config.json 的
# "models" 键（{"<provider>": {"current": "<注册名>", "items": [...]}}），
# 未配置时完全回退到原有 env/默认值行为——零配置安装不受影响。

_VALID_MODEL_PROVIDERS = ("azure", "openai", "ollama", "gemini")


def _read_app_config() -> dict:
    """读 app_config.json 原始内容；文件缺失/坏损时返回空 dict（静默回退，
    与 get_default_provider 的容错哲学一致）。"""
    try:
        if APP_CONFIG_FILE.exists():
            import json as _json
            with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = _json.load(f)
                if isinstance(cfg, dict):
                    return cfg
    except Exception:
        logger.debug("app_config.json 读取失败（模型注册表回退到 env/默认）", exc_info=True)
    return {}


def get_model_registry() -> Dict[str, Dict[str, Any]]:
    """模型注册表：{provider: {"current": 注册名|None, "items": [注册项...]}}。

    只返回四个合法 provider 的条目；结构坏损的条目跳过不抛异常。
    注册项字段：name（显示名，provider 内唯一）/ model（模型名）/
    base_url / api_key（均可选，None=沿用 env/默认）。api_key 只落盘不回显，
    序列化由 UI API 层负责打码。"""
    cfg = _read_app_config()
    raw = cfg.get("models")
    registry: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, dict):
        for provider, entry in raw.items():
            key = str(provider or "").strip().lower()
            if key not in _VALID_MODEL_PROVIDERS or not isinstance(entry, dict):
                continue
            items = entry.get("items")
            clean_items = []
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    model = str(item.get("model") or "").strip()
                    if not name or not model:
                        continue  # name/model 是必填项，缺一个整条作废
                    clean_items.append({
                        "name": name,
                        "model": model,
                        "base_url": (str(item.get("base_url")).strip()
                                     if item.get("base_url") else None),
                        "api_key": (str(item.get("api_key")).strip()
                                    if item.get("api_key") else None),
                    })
            current = entry.get("current")
            current = str(current).strip() if isinstance(current, str) else None
            # current 必须指向现存条目，否则视为未选择（回退 env/默认值）
            if current and not any(i["name"] == current for i in clean_items):
                current = None
            registry[key] = {"current": current, "items": clean_items}
    return registry


def resolve_model_config(provider: str) -> Dict[str, Any]:
    """某 provider 当前生效的模型配置（LLM 构造链路的唯一读取入口）。

    返回 {"model": 注册的模型名, "base_url": ...|None, "api_key": ...|None}；
    该 provider 没有注册表条目或没选 current 时返回空 dict——调用方按
    "键不存在"回退到原有 env/默认值逻辑。"""
    entry = get_model_registry().get(str(provider or "").strip().lower())
    if not entry or not entry.get("current"):
        return {}
    for item in entry["items"]:
        if item["name"] == entry["current"]:
            return {
                "model": item["model"],
                "base_url": item.get("base_url"),
                "api_key": item.get("api_key"),
            }
    return {}  # 防御：current 指向的条目已在清洗中被剔除

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