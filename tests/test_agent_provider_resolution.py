"""Agent 构造点的 provider 归一：缺省 None 必须走 resolve_provider 链。

以前 AgentBase / 四个子类 / index_pdf_document 都写死 `'openai'` 字面量
默认——env PROVIDER 与 app_config.json 对"没传 provider 的入口"（CLI
main.py 的 AnswerAgent / 索引路径 / 延迟构造）完全无效，同文件搜索那条
路却走 resolve_provider，行为自相矛盾。现在解析统一收在 AgentBase 一处。
"""
import pytest

from src.agents.base import AgentBase
from src.config import settings


class _CaptureLLM:
    def __init__(self, provider=None, model=None):
        self.provider = provider
        self.model = model


@pytest.fixture()
def spy_llm(monkeypatch, tmp_path):
    monkeypatch.setattr("src.core.llm.LLMBase", _CaptureLLM, raising=False)
    # 断掉 app_config 这一层：测试进程的仓库里可能躺着真 app_config.json，
    # 它按优先级会盖过 env——这里要的是"配置链可验证"，不是本机现状
    monkeypatch.setattr(settings, "APP_CONFIG_FILE", tmp_path / "absent.json")


async def test_default_provider_follows_env_provider(spy_llm, monkeypatch):
    monkeypatch.setenv("PROVIDER", "ollama")
    agent = AgentBase(name="prov-test")
    assert agent.llm.provider == "ollama"


async def test_explicit_provider_normalized(spy_llm, monkeypatch):
    monkeypatch.setenv("PROVIDER", "ollama")
    agent = AgentBase(name="prov-test", provider="Azure")
    assert agent.llm.provider == "azure", "显式值应归一为小写且原样采纳"


async def test_app_config_takes_precedence_over_env(spy_llm, monkeypatch, tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"provider": "GEMINI"}', encoding="utf-8")
    monkeypatch.setattr(settings, "APP_CONFIG_FILE", cfg)
    monkeypatch.setenv("PROVIDER", "ollama")
    agent = AgentBase(name="prov-test")
    assert agent.llm.provider == "gemini", "优先级应为 app_config > env"


async def test_final_fallback_is_openai(spy_llm, monkeypatch, tmp_path):
    monkeypatch.delenv("PROVIDER", raising=False)
    agent = AgentBase(name="prov-test")
    assert agent.llm.provider == "openai"
