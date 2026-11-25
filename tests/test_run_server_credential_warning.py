"""run_server 启动自检的钉（2026-11-25 事故的事后补票）。

当天 provider=openai 但 OPENAI_API_KEY 三处皆空，ChatOpenAI 到第一条消息
才炸、界面只剩"处理失败"，排查先绕了一大圈代码嫌疑。这条检查的验收线就两条：
缺 key 必须有一行说得清出路的 WARNING；任何不该响的情形都不许响——
尤其不许拦启动（缺 key 时 /data /briefs 照样有运维价值，fail-fast 是更糟的
失败模式）。
"""
import logging

import pytest

import src.config.settings as settings
import src.ui.run_server as run_server


def _run(monkeypatch, caplog, *, env=None, registry=None):
    monkeypatch.setattr(settings, "resolve_provider", lambda p: "openai")
    monkeypatch.setattr(settings, "get_model_registry",
                        lambda: registry if registry is not None else {})
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    with caplog.at_level(logging.WARNING):
        run_server.check_llm_credentials()
    return caplog.text


def test_missing_key_warns_and_points_to_fix(monkeypatch, caplog):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    text = _run(monkeypatch, caplog)
    assert "OPENAI_API_KEY" in text
    assert "重启" in text, "warning 里要把'改 .env 要重启'说明白"


def test_env_key_present_is_quiet(monkeypatch, caplog):
    text = _run(monkeypatch, caplog, env={"OPENAI_API_KEY": "sk-test"})
    assert "未设置" not in text


def test_registry_override_counts_as_present(monkeypatch, caplog):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    text = _run(monkeypatch, caplog, registry={
        "openai": {"items": [{"name": "m", "api_key": "sk-from-registry"}]},
    })
    assert "OPENAI_API_KEY" not in text, "providers.py 会采纳注册表覆盖，自检不许误报"


def test_check_never_raises_even_when_registry_broken(monkeypatch, caplog):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "resolve_provider", lambda p: "openai")

    def boom():
        raise RuntimeError("registry 读崩了")

    monkeypatch.setattr(settings, "get_model_registry", boom)
    run_server.check_llm_credentials()  # 不许把异常带到启动路径上
