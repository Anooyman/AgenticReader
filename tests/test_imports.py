"""
轻量冒烟测试：检查 src 各顶层模块能被正常 import。

特点：
    - 不联网、不调用任何 LLM / Embedding 服务
    - 只验证导入链本身（语法错误、坏 import、缺失依赖等都能在这里暴露）
    - 可通过 pytest 运行，也可作为脚本直接执行：
          python tests/test_imports.py

运行方式：
    .venv/bin/python tests/test_imports.py
    pytest tests/test_imports.py
"""
import importlib
import os
import sys

# 脚本方式直接运行时也要能 import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# src/ 下各顶层包 / 子包
TOP_LEVEL_MODULES = [
    "src",
    "src.config.settings",
    "src.config.constants",
    "src.core.llm.client",
    "src.core.document_management",
    "src.core.vector_db",
    "src.core.processing",
    "src.core.parallel",
    "src.agents",
    "src.agents.indexing",
    "src.agents.answer",
    "src.agents.retrieval",
    "src.agents.orchestrator",
    "src.agents.search",
    "src.services",
    "src.utils",
    "src.pipeline",
    "src.ui.backend.app",
]


def test_import_all_top_level_modules():
    """逐个 import 顶层模块，捕获 ImportError / ModuleNotFoundError"""
    failed = {}
    for name in TOP_LEVEL_MODULES:
        try:
            importlib.import_module(name)
            print(f"OK   {name}")
        except ImportError as exc:
            failed[name] = f"{type(exc).__name__}: {exc}"
            print(f"FAIL {name} -> {failed[name]}")
    assert not failed, "以下模块 import 失败：\n" + "\n".join(
        f"  {k}: {v}" for k, v in failed.items()
    )


def test_core_public_names_importable():
    """核心公共名字能被 import（防止导出路径被搬走导致测试 import 即失败）"""
    from src.agents.indexing import IndexingAgent  # noqa: F401
    from src.agents.answer import AnswerAgent  # noqa: F401
    from src.agents.retrieval import RetrievalAgent  # noqa: F401
    from src.core.document_management import DocumentRegistry  # noqa: F401


if __name__ == "__main__":
    test_import_all_top_level_modules()
    test_core_public_names_importable()
    print("\n✅ test_imports: 全部顶层模块导入正常")
