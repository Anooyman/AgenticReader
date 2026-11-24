"""settings 层两个上游 env 的解析用例——寻址与开关的唯一读取入口。

get_llm_memory_repo() 是 strip 后的原文透传（"唯一寻址点"的纪律：这里
不判存在性、不补默认值，存在性判定归 upstream._repo_src——两处各管一段，
别在这里提前"好心"地做 isdir）。
is_llm_memory_mcp_enabled() 是布尔闸门：认 1/true/yes/on（大小写不敏感、
容忍空白），其余一律 False——缺省必须落在 False 上，"默认关"是整个
MCP 决策面的第一裁决。
"""
import pytest

from src.config import settings


def test_repo_unset_is_empty_string(monkeypatch):
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    assert settings.get_llm_memory_repo() == ""


def test_repo_whitespace_is_stripped(monkeypatch):
    monkeypatch.setenv("LLM_MEMORY_REPO", "  /opt/llm-memory  ")
    assert settings.get_llm_memory_repo() == "/opt/llm-memory"


def test_repo_explicit_empty_stays_empty(monkeypatch):
    monkeypatch.setenv("LLM_MEMORY_REPO", "")
    assert settings.get_llm_memory_repo() == ""
    monkeypatch.setenv("LLM_MEMORY_REPO", "   ")
    assert settings.get_llm_memory_repo() == ""


@pytest.mark.parametrize("raw,expected", [
    # 开关认的词表：1/true/yes/on，大小写随意、前后空白容忍
    ("1", True), ("true", True), ("True", True), ("TRUE", True),
    ("yes", True), ("YES", True), ("on", True), ("On", True),
    (" 1 ", True), ("\ttrue\n", True),
    # 其余取值一律 False——包括"差一点像"的和未设置的
    ("0", False), ("false", False), ("no", False), ("off", False),
    ("maybe", False), ("", False), ("   ", False), ("2", False),
    ("yes!", False), ("truthy", False),
])
def test_mcp_gate_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("LLM_MEMORY_MCP_ENABLED", raw)
    assert settings.is_llm_memory_mcp_enabled() is expected


def test_mcp_gate_unset_defaults_false(monkeypatch):
    """缺省关是第一裁决——env 完全不设时必须 False，而不是 KeyError 或 None。"""
    monkeypatch.delenv("LLM_MEMORY_MCP_ENABLED", raising=False)
    assert settings.is_llm_memory_mcp_enabled() is False


def test_both_helpers_read_env_lively(monkeypatch):
    """调用期现读（不像 MCP_CONFIG 子进程参数那样 import 期固化）：
    env 中途变了这里必须跟着变，否则 upstream 的降级/启用判定会拿旧值。"""
    monkeypatch.setenv("LLM_MEMORY_REPO", "/a")
    monkeypatch.setenv("LLM_MEMORY_MCP_ENABLED", "0")
    assert settings.get_llm_memory_repo() == "/a"
    assert settings.is_llm_memory_mcp_enabled() is False
    monkeypatch.setenv("LLM_MEMORY_REPO", "/b")
    monkeypatch.setenv("LLM_MEMORY_MCP_ENABLED", "1")
    assert settings.get_llm_memory_repo() == "/b"
    assert settings.is_llm_memory_mcp_enabled() is True
