"""
pytest 全局配置：为依赖真实 LLM / Embedding 凭据的测试文件做自动跳过。

背景：
    tests/ 下大部分脚本式测试（test_llm_client.py、test_answer_agent.py 等）
    在运行时会真实调用 LLM 服务，没有 API key 的机器上必然失败。
    这里在收集阶段统一处理：缺少凭据时给对应用例打上 skip 标记，
    而不是让它们报错，方便本地 / CI 跑纯逻辑用例。

凭据判定依据 src/config/settings.py 里 LLM_CONFIG / LLM_EMBEDDING_CONFIG
实际读取的环境变量（未新增任何自定义开关）：
    CHAT_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / EMBEDDING_API_KEY
"""
import os

import pytest

# settings.py 实际读取的凭据类环境变量
LLM_CREDENTIAL_ENVS = (
    "CHAT_API_KEY",       # Azure OpenAI / 通用 chat 配置
    "OPENAI_API_KEY",     # OpenAI 直连
    "GEMINI_API_KEY",     # Gemini 直连
    "EMBEDDING_API_KEY",  # 向量 embedding 服务
)

# 需要真实 LLM / Embedding 调用的测试文件（文件名 -> 跳过原因）
# 其余测试文件视为离线可跑（纯逻辑 / mock / 纯打印模拟），不做跳过
LLM_DEPENDENT_FILES = {
    "test_answer_agent.py": "需要真实 LLM 凭据",
    "test_indexing_agent.py": "需要真实 LLM 凭据（解析与向量化）",
    "test_retrieval_agent.py": "需要真实 LLM 凭据",
    "test_llm_client.py": "需要真实 LLM 凭据",
    "test_llm_providers.py": "需要真实 LLM Provider 配置",
    "test_history_compression.py": "LLM 总结模式需要真实 LLM 凭据",
    "test_multi_pdf.py": "需要真实 LLM / Embedding 凭据",
    "test_manual_selection_mode.py": "需要真实 LLM 凭据",
    "test_metadata_dedup.py": "重建元数据索引需要 Embedding 凭据",
    "test_vector_db_content.py": "需要 Embedding 凭据",
}

# 上述文件的模块名（不含 .py），供 fixture 二次兜底
LLM_DEPENDENT_STEMS = {name[:-3] for name in LLM_DEPENDENT_FILES}


def has_llm_credentials() -> bool:
    """仓库未设置任何 API key 环境变量时返回 False"""
    return any(os.environ.get(key) for key in LLM_CREDENTIAL_ENVS)


def pytest_collection_modifyitems(config, items):
    """收集阶段：缺凭据时对 LLM 依赖文件的用例自动加 skip 标记"""
    if has_llm_credentials():
        return
    for item in items:
        # pytest 9 起 item.fspath 已被移除，改用 item.path（pathlib.Path）
        path = getattr(item, "path", None)
        filename = path.name if path is not None else ""
        reason = LLM_DEPENDENT_FILES.get(filename)
        if reason is not None:
            item.add_marker(
                pytest.mark.skip(
                    reason=f"{reason}；缺少环境变量 {list(LLM_CREDENTIAL_ENVS)} 之一，跳过"
                )
            )


@pytest.fixture(autouse=True)
def skip_without_llm_credentials(request):
    """兜底：即便用例通过其他方式被直接收集，也避免在无凭据时真实发起 LLM 调用"""
    nodeid = getattr(getattr(request, "node", None), "nodeid", "") or ""
    module = nodeid.split("::")[0].split("/")[-1]
    if module[:-3] in LLM_DEPENDENT_STEMS and not has_llm_credentials():
        pytest.skip("缺少 LLM 凭据环境变量，跳过依赖真实 LLM 的用例")


@pytest.fixture(autouse=True)
def _memory_upstream_off_by_default(monkeypatch):
    """测试期**默认**把上游 LLM-Memory 的寻址掐掉，除非这条用例自己把它接上。

    起因很实际：有人在 shell 里 `export LLM_MEMORY_REPO=...` 之后跑测试，
    那一轮就从"离线跑逻辑"变成"读写你机器上那个真库"——慢是真慢（一次
    `all_rows` 就是五千多行），更糟的是失败原因长得像被测代码有 bug，其实
    只是运行环境和别人共用了一个存储。路由测试自己会 `setenv`，那是它们的
    自由；剩下的用例一个都不该被卷进去。

    这里三件事一起做，少一件都还不算离线：
      * 掐 `LLM_MEMORY_REPO` —— 没有寻址就没有客户端
      * 掐 `LLM_MEMORY_MCP_ENABLED` —— 决策面也不该在测试里拉起子进程
      * 把 `upstream._client` 归零 —— 它是进程级单例，前面某个用例留下的
        真客户端会让这一条测试哪怕 env 已经没了还在用它

    想要上游的用例请自己显式 `monkeypatch.setenv(...)` + 假 `_client`，
    顺序上它们在这个 fixture 之后跑，覆盖了这里掐掉的东西——这正是要的
    默认：**离线是默认值，接上游是个要写明白的选择。**
    """
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("LLM_MEMORY_MCP_ENABLED", raising=False)
    try:
        from src.memory import upstream

        monkeypatch.setattr(upstream, "_client", None, raising=False)
    except Exception:  # noqa: BLE001 —— 记忆层根本没装上的环境里也别拦测试
        pass
