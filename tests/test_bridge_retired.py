"""HTTP 桥（外部 webui 一跳）退役的结构级守卫。

双写法沿用仓内现成范式，各扫一遍指纹：
  * AST 标识符扫描（仿 tests/test_filelock.py:23-40）——桥名字不得以任何
    import/定义/属性/调用形式出现在 src/；
  * 纯文本扫描（仿 tests/test_store_path_resolution.py:46-53）——端口
    常量与脚本路径这类藏在字符串/注释里的痕迹也必须清零。
再加两份快照：gateway 上桥面 hasattr 清零、driver 白名单 {local} 的
行为枚举。这是 PLAN 验收口径 ② 的仓内版——验收 grep 同样会扫 tests/，
所以本文件的指纹串全部以相邻字面量拼接写成，自身不含原样字面量。

全程离线：driver 枚举里的 local 路径用假实现垫掉，老桥 URL 属性（若还
残留）一律改指必拒端口——任何尚未退干净的 bridge 分支只会让断言在
"没走 local"处失败，不会真的出网。
"""
import ast
import asyncio
import importlib.util
import inspect
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.memory import gateway  # noqa: E402

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"

# ---- 指纹（拼接形式，测试源码自身对验收 grep 免疫）----
NAME_FINGERPRINTS = ("bridge_" "request", "Bridge" "Error", "LLM_MEMORY_" "URL")
TEXT_FINGERPRINTS = NAME_FINGERPRINTS + ("87" "65", "scripts/" "webui")

# 桥退役前挂在 gateway 公开面上的全部名字（三个名字指纹 + 七个具名一跳）
GONE_ON_GATEWAY = NAME_FINGERPRINTS + (
    "brief_dates", "brief_papers", "brief_load", "brief_load_progress",
    "brief_chat", "brief_chat_progress", "brief_chat_stop",
)


def _src_py_files():
    return (p for p in SRC_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


# ------------------------------------------------------------- ① AST 标识符扫描
def test_bridge_names_absent_from_src_ast():
    """NAME_FINGERPRINTS 里的三个桥符号名在 src/ 全库不得以任何标识符形式
    存在——import、def、类名、属性访问、调用全算。注释和文档字符串里的
    历史叙述由 ② 的文本扫描兜底，这层只管代码符号。"""
    offenders = []
    for path in _src_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.alias):
                names.add(node.name)
            elif isinstance(node, ast.keyword) and node.arg:
                names.add(node.arg)
        hit = names & set(NAME_FINGERPRINTS)
        if hit:
            offenders.append(f"{path.relative_to(SRC_ROOT)}: {sorted(hit)}")
    assert not offenders, (
        "HTTP 桥退役是无条件裁决，src/ 里仍有引用以名字存在的桥指纹："
        + "; ".join(offenders))


# ------------------------------------------------------------- ② 文本指纹扫描
def test_bridge_fingerprints_absent_from_src_text():
    """端口常量与启动脚本路径连注释都不许留——留着它们就是在告诉后来人
    "这条路还在"，退役要退干净，历史叙述归 README/CLAUDE 的退役说明段。"""
    offenders = []
    for path in _src_py_files():
        text = path.read_text(encoding="utf-8")
        hits = [f for f in TEXT_FINGERPRINTS if f in text]
        if hits:
            offenders.append(f"{path.relative_to(SRC_ROOT)}: {hits}")
    assert not offenders, (
        "src/ 中残留外部桥指纹（端口/脚本路径/桥符号名）：" + "; ".join(offenders))


# ------------------------------------------------------------- gateway 面快照
def test_gateway_bridge_surface_has_been_retired():
    leftovers = [name for name in GONE_ON_GATEWAY if hasattr(gateway, name)]
    assert not leftovers, (
        f"gateway 上还挂着桥时代的服务面：{leftovers}——删除是计划 §1.2 的硬性项。")


def test_brief_memory_module_is_removed():
    """反向 import 的那半条债：src.ui 侧的 brief_memory 服务文件应整体删除，
    gateway.load_brief_date 的 bridge 分支随它一起注销。"""
    assert importlib.util.find_spec("src.ui.backend.services.brief_memory") is None


def test_load_brief_date_carries_no_reverse_import():
    """桥分支删干净后，load_brief_date 函数体不该再引用任何 UI 服务模块名；
    内核层反向 import src.ui 的债今天正式注销（计划 §1.2）。"""
    source = inspect.getsource(gateway.load_brief_date)
    assert "brief_memory" not in source, "load_brief_date 仍引用 brief_memory"


# ------------------------------------------------------------- driver 白名单快照
def _install_local_probe(monkeypatch):
    import src.memory.brief_ingest as bi

    seen = []

    async def fake_local(date, provider=None, **kw):
        seen.append(date)
        return {"loaded": True, "skipped": False, "errors": []}

    monkeypatch.setattr(bi, "load_brief_date_local", fake_local)
    return seen


@pytest.mark.parametrize("driver", [
    "", "   ", "local", "LOCAL", "local ", "bogus", "brdge",
    "bridge", "BRIDGE", "Bridge", "bridge ",
])
def test_driver_whitelist_snapshot_all_values_route_local(monkeypatch, driver):
    """{local} 白名单的行为快照：env 无论取什么值——包括曾经的合法值
    bridge——唯一结局都是走 local 实现。"白名单收敛"在行为面就是
    "零路由差异"，结构面由上面几项守卫钉死，这里不重复实现细节。"""
    seen = _install_local_probe(monkeypatch)
    # 万一 bridge 分支还在：把老桥 URL 改指必拒端口，失败只会发生在断言里。
    monkeypatch.setattr(gateway, "LLM_MEMORY_" "URL", "http://127.0.0.1:1",
                        raising=False)
    monkeypatch.delenv("MEMORY_BRIEF_DRIVER", raising=False)
    if driver:
        monkeypatch.setenv("MEMORY_BRIEF_DRIVER", driver)
    out = asyncio.run(gateway.load_brief_date("2026-11-16"))
    assert seen == ["2026-11-16"], f"driver={driver!r} 没有落到 local"
    assert out.get("loaded") is True
