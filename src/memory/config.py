"""src/memory/ 子系统的配置桥接层。

不重新发明凭证体系——复用 AgenticReader 已有的 LLM_CONFIG/LLM_EMBEDDING_CONFIG
（src/config/settings.py）和 LLMBase（src/core/llm/client.py）。这里只额外提供
两件事：
1. 记忆库自己的存储路径、namespace 常量；
2. 每个 embedding 模型对应的向量维度——LanceDB 建表时需要固定 schema 宽度，
   且这个数字不能从 LLMBase 的懒加载 embedding_model 实例反向推导（推导需要
   先真的调一次 API），所以在这里维护一份显式映射。
"""
import logging
import os
from typing import Optional

from src.config.settings import (
    DATA_ROOT,
    get_embedding_model_env_var,
    get_embedding_model_name,
)

logger = logging.getLogger(__name__)

MEMORY_DB_DIR = os.path.join(DATA_ROOT, "memory_db")

# 每篇论文/文章一个 source_id（=doc_name），namespace 用来把"论文/文章摘要"
# 和"webapp 对话历史"分开检索（两者语义不同，混在一起会互相污染 top-k）。
NAMESPACE_AI_RESEARCH = "ai-research"
NAMESPACE_WEBAPP_CHAT = "webapp-chat"

# 已知 embedding 模型 -> 向量维度。新增模型时在这里补一条即可。
_KNOWN_DIMENSIONS = {
    "text-embedding-ada-002": 1536,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-004": 768,
    # Ollama 侧常见的 embedding 模型（settings 默认的 llama3 不是 embedding
    # 模型，维度未知，落到默认值并被下面的校验报错）。
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
    "snowflake-arctic-embed": 1024,
}

_DEFAULT_DIMENSIONS = 1536  # ada-002 是当前配置里两个 provider 的共同默认

# 每个 provider 在不配任何环境变量时实际会用的模型名，用来区分
# "用户没配"（只警告）和"用户配了一个我们不知道维度的模型"（报错）。
_PROVIDER_DEFAULT_MODELS = {
    "azure": None,  # azure 侧 EMBEDDING_MODEL 本来就没有默认值
    "openai": "text-embedding-ada-002",
    "ollama": "llama3",
    "gemini": "text-embedding-004",
}

# 维度校验的报错只打一次，避免 ingest/search 每次调用都刷日志。
_DIMENSION_CHECK_LOGGED = set()


def _log_dimension_check(provider: str, model_name: Optional[str]) -> None:
    """静态维度一致性校验（不打 API）。

    LanceDB 建表时把向量列宽度写死，若建表用的维度和模型真实输出维度不一致，
    写入不会报错但库里的向量是错的——检索会静默给出无关结果，比崩掉更难查。
    这里只能做映射表层面的静态校验：模型名在 _KNOWN_DIMENSIONS 里就有明确
    维度可对照，否则只能按默认 1536 建表，所以必须把风险说清楚。
    真做实际 probe 代价太大（要联网打一次 embedding API），留在这里不做。
    # TODO: 若以后需要在首次建表前做真 probe（例如对未知模型打一次
    # embed_query 拿 len(result[0]) 与 _KNOWN_DIMENSIONS 对照），应加在 memory
    # 库初始化路径上且带超时，而不是每次 ingest/search 都打 API。
    """
    if model_name is not None and model_name in _KNOWN_DIMENSIONS:
        return
    key = (provider, model_name)
    if key in _DIMENSION_CHECK_LOGGED:
        return
    _DIMENSION_CHECK_LOGGED.add(key)

    env_var = get_embedding_model_env_var(provider)
    known = ", ".join(f"{k}={v}" for k, v in sorted(_KNOWN_DIMENSIONS.items()))
    if model_name is None:
        # 该 provider 没有默认模型名（azure 侧 EMBEDDING_MODEL 未设）：此时按
        # 本项目文档化的默认（ada-002 / 1536 维）建表是有意行为，不算配错，
        # 所以只给 warning 提示可以改哪条 env，避免默认安装下每开一次 /memory
        # 页面就刷一条 ERROR。
        logger.warning(
            "Embedding 维度校验：provider=%s 未配置 embedding 模型名，按本项目默认"
            " %d 维（text-embedding-ada-002）建表。若你实际用的是其它维度"
            "模型，请设置环境变量 %s。",
            provider, _DEFAULT_DIMENSIONS, env_var,
        )
    else:
        logger.error(
            "Embedding 维度校验：provider=%s 配置的模型 %r 不在已知维度表中，"
            "LanceDB 记忆库会按 %d 维建表；若该模型实际输出维度不是 %d 维，"
            "写入会静默失败或写坏记忆库。请改环境变量 %s，或把该模型的维度"
            "补进 src/memory/config.py 的 _KNOWN_DIMENSIONS（已知：%s）。",
            provider, model_name, _DEFAULT_DIMENSIONS, _DEFAULT_DIMENSIONS,
            env_var, known,
        )


def get_embedding_dimensions(provider: str = "azure") -> int:
    """按当前配置的 embedding 模型名解析向量维度。解析不到时回退到 1536
    （text-embedding-ada-002 的维度，也是本项目目前所有 provider 的默认模型），
    不抛异常——维度只影响建表 schema，不该在配置加载阶段就让整个记忆子系统
    无法初始化。

    模型名走 settings.get_embedding_model_name()，与 client.py / providers.py
    创建 embedding 实例时读到的是同一个值；模型名不在已知维度表里时打 ERROR
    （见 _log_dimension_check），避免静默按 1536 建表写坏 LanceDB 库。"""
    provider = (provider or "azure").lower()
    model_name = get_embedding_model_name(provider)
    _log_dimension_check(provider, model_name)
    if model_name is None:
        # 配置缺失，沿用默认；同时说明"如果本意是别的模型请改 env"
        default_model = _PROVIDER_DEFAULT_MODELS.get(provider)
        if default_model and default_model in _KNOWN_DIMENSIONS:
            return _KNOWN_DIMENSIONS[default_model]
        return _DEFAULT_DIMENSIONS
    return _KNOWN_DIMENSIONS.get(model_name, _DEFAULT_DIMENSIONS)

