"""MCP 子进程的环境里，AR 到底替上游决定了什么。

这条用例守的是收敛的第一条边界："存储位置归上游"——所以 AR 可以递出去的是
**代码在哪**（`_repo_src` 那条寻址链，最终变成 `PYTHONPATH`），不该是
**数据在哪**。`MEMORY_DATA_DIR` 是上游 `common/paths.py` 的顶层旋钮：消费者
替它钉一个"自认为等价的形状"，哪怕结果今天碰巧一样，语义上已经把两处
写在一起的权限拿到了手，第二套存储往往就是从这种"顺手对齐"里长出来的。

两种情形分别验：

* 环境里没有这个变量 → 子进程的环境里也**不该出现**它，让上游自己落回
  机器默认根（`~/.llm-memory`）；
* 环境里真有 → 原样透传，不改写、不追加、不"再钉一次"。用户既然设了，
  决定权在他和上游之间，不在这里。
"""
import pytest

upstream = pytest.importorskip("src.memory.upstream")

StdioServerParameters = pytest.importorskip("mcp").StdioServerParameters


def test_ar_does_not_pin_the_upstream_data_root(monkeypatch):
    monkeypatch.delenv("MEMORY_DATA_DIR", raising=False)
    params = upstream._mcp_server_params()
    assert isinstance(params, StdioServerParameters)
    assert "MEMORY_DATA_DIR" not in params.env, (
        f"AR 又替上游选了数据根：{params.env.get('MEMORY_DATA_DIR')!r}")


def test_a_user_set_data_root_is_passed_through_unchanged(monkeypatch):
    monkeypatch.setenv("MEMORY_DATA_DIR", "/srv/llm-memory-root")
    params = upstream._mcp_server_params()
    assert params.env.get("MEMORY_DATA_DIR") == "/srv/llm-memory-root", (
        "设了就应当原样交给上游，别在这里改写成另一个'等价'路径")


def test_the_addressing_that_does_get_sent_is_the_code_root(monkeypatch):
    """反面对照：唯一合法传出去的位置类旋钮是 PYTHONPATH，由 settings 派生。"""
    monkeypatch.delenv("MEMORY_DATA_DIR", raising=False)
    params = upstream._mcp_server_params()
    assert "PYTHONPATH" in params.env
    assert all(not (str(k).endswith("_DATA_DIR") or str(k).endswith("_STORE_DIR"))
               for k in params.env), sorted(params.env)


def test_ar_default_config_never_pins_the_upstream_data_root():
    """默认那份 MCP 配置只能递"代码在哪"，不许递"数据在哪"。

    这条不是形式：一旦 `env` 里出现 `MEMORY_DATA_DIR` / `MEMORY_CONFIG`，
    决策面的子进程就会照着那个根找库，而 SDK 面走的是上游自己的缺省——
    两边各读一套、页面上还都显示"接上了上游"。
    """
    from src.config.settings import MCP_CONFIG

    env = (MCP_CONFIG.get("llm_memory") or {}).get("env") or {}
    for key in ("MEMORY_DATA_DIR", "MEMORY_CONFIG"):
        assert key not in env, f"默认配置里钉了 {key}，数据根就从这里被抢走了"


def test_a_pinned_data_root_in_config_env_says_so_instead_of_silently_diverging(monkeypatch, caplog):
    """运维真钉了也行，但得说出来——归属不是靠删掉别人的配置来守的。"""
    import logging

    import src.config.settings as settings
    from src.memory import upstream as up

    monkeypatch.setitem(settings.MCP_CONFIG, "llm_memory",
                        {"command": "python", "args": ["-m", "llm_memoryd.mcp"],
                         "env": {"MEMORY_DATA_DIR": "/some/other/root"}})
    monkeypatch.setattr(up, "_MCP_PIN_WARNED", False)
    up._mcp_server_params()
    warned = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("MEMORY_DATA_DIR" in m for m in warned), "该出声的时候一声不响就是错的那一半"
