"""src/memory/ 子系统的配置桥接层。

不重新发明凭证体系——复用 AgenticReader 已有的 LLM_CONFIG/LLM_EMBEDDING_CONFIG
（src/config/settings.py）和 LLMBase（src/core/llm/client.py）。这里只额外提供
两件事：
1. 记忆库自己的存储路径、namespace 常量；
2. 每个 embedding 模型对应的向量维度——LanceDB 建表时需要固定 schema 宽度，
   且这个数字不能从 LLMBase 的懒加载 embedding_model 实例反向推导（推导需要
   先真的调一次 API），所以在这里维护一份显式映射。
"""
import os
from typing import Optional

from src.config.settings import DATA_ROOT, LLM_EMBEDDING_CONFIG

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
}

_DEFAULT_DIMENSIONS = 1536  # ada-002 是当前配置里两个 provider 的共同默认


def get_embedding_dimensions(provider: str = "azure") -> int:
    """按当前配置的 embedding 模型名解析向量维度。解析不到时回退到 1536
    （text-embedding-ada-002 的维度，也是本项目目前所有 provider 的默认模型），
    不抛异常——维度只影响建表 schema，不该在配置加载阶段就让整个记忆子系统
    无法初始化。"""
    provider = (provider or "azure").lower()
    if provider == "azure":
        model_name = LLM_EMBEDDING_CONFIG.get("model")
    elif provider == "openai":
        model_name = LLM_EMBEDDING_CONFIG.get("openai_embedding_model")
    elif provider == "gemini":
        model_name = LLM_EMBEDDING_CONFIG.get("gemini_embedding_model")
    else:
        model_name = None
    return _KNOWN_DIMENSIONS.get(model_name, _DEFAULT_DIMENSIONS)
