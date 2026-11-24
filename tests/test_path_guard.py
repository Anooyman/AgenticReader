"""path_guard.safe_path 的直接用例——安全关键件此前 0 覆盖。

这个函数是全仓"按 doc_name 拼数据目录"的唯一守卫：documents / pdf / structure
/ data / briefs 各 API 都靠它把用户可控的名字挡在数据根外面。它被换坏的形态
不是"报错变多了"，而是"某条拒绝分支消失、路径安静地落在外面"——那正好是
读起来最像正常工作的一种，所以这里按**它宣称的规则**逐条钉，而不是挑几个好
跑的输入：

  1. 合法名字返回 base 之下的已解析路径；
  2. 名字里出现任何路径分隔符就拒（`/` 与 `\\` 两种，Windows 风格变体也要拒）；
  3. 以点开头的名字拒；剥离已知后缀后为空拒；空/空白拒；
  4. resolve() 之后仍要在 base 之内——符号链接不豁免这一条。

其中两条曾被钉成已知缺陷（见 test_rejects_none_like_input / test_rejects_non_string_input）：
函数入口原先用 `str(name)` 做规范化，None/True/3 会被收编成"合法"名字。
2026-11 Lead 已落地 isinstance 类型门，这两条从 xfail 翻成正式防线。
"""
import os
import sys
from pathlib import Path

import pytest

from src.utils.path_guard import normalize_doc_name, safe_path

# 这个函数是全仓"按 doc_name 拼数据目录"的唯一守卫，测试按它 docstring 里
# 宣称的规则逐条钉，而不是挑几个好跑的输入——理由见模块开头。


@pytest.fixture
def base(tmp_path):
    """一个真实存在的基目录，测试都围绕它做。"""
    root = tmp_path / "data"
    root.mkdir()
    return root.resolve()


def assert_inside(candidate: Path, root: Path) -> None:
    """返回值必须在允许根之内——这条断言比"长得像"严格。"""
    assert candidate.is_absolute()
    assert candidate.is_relative_to(root), f"{candidate} 落在 {root} 之外"


# ---------------------------------------------------------------- 合法路径
def test_legal_names_resolve_under_base(base):
    for name in ("paper.pdf", "paper", "doc-2024", "报告", "a.b.c", "x_1", "  spaced  "):
        got = safe_path(base, name)
        assert_inside(got, base)
        assert got.parent == base or got.name == normalize_doc_name(name)


def test_doc_name_is_normalized_once_at_the_tail(base):
    """后缀只在结尾剥一次：中间的 .pdf 不能被吃掉。"""
    assert normalize_doc_name("foo.pdf") == "foo"
    assert normalize_doc_name("FOO.PDF") == "FOO"          # 大小写不敏感
    assert normalize_doc_name("  foo.PDF  ") == "foo"      # 先 trim
    assert normalize_doc_name("foo.pdf.pdf") == "foo.pdf"  # 只剥一次
    assert normalize_doc_name("a.pdf.b") == "a.pdf.b"      # 结尾不是后缀就不动
    assert normalize_doc_name("no-suffix") == "no-suffix"


def test_suffix_stripping_is_consistent_with_the_returned_path(base):
    """"foo.pdf" 与 "foo" 必须落到同一个路径——各处依赖这个等价性。"""
    assert safe_path(base, "foo.pdf") == safe_path(base, "foo")
    assert safe_path(base, "FOO.pdf").name == safe_path(base, "FOO").name


def test_nonexistent_base_still_returns_an_in_root_path(base):
    """守卫不建目录，也不该因为目录还没建就拒绝：这是"将要写入"的路径，
    不是"已存在"的路径。"""
    missing = base / "json_data"
    assert not missing.exists()
    assert_inside(safe_path(missing, "paper"), missing.resolve())


# ---------------------------------------------------------------- 分隔符
@pytest.mark.parametrize("name", [
    "../etc/passwd",        # 经典跨目录
    "data/../etc/passwd",
    "/",
    "\\",
    "/etc/passwd",          # 绝对路径
    "C:/Windows/win.ini",   # Windows 绝对路径
    "\\\\host\\share\\f",    # UNC
    "pdf\\paper.pdf",       # Windows 风格相对穿越
    "./x",
    "x/./y",
    "..\\..\\etc",
    "a/b",
    "\n/x",                 # 换行后面埋一个分隔符，别指望 startswith 之类的把戏
])
def test_any_path_separator_is_rejected(base, name):
    with pytest.raises(ValueError):
        safe_path(base, name)


def test_dot_only_names_are_rejected(base):
    # "." 与 ".." 都靠"不能以点开头"这条挡下；写成两条断言反而看不见这个共因
    for name in (".", "..", "...", ".hidden", ".pdf", ".PDF", "  ..  "):
        with pytest.raises(ValueError):
            safe_path(base, name)


def test_empty_and_suffix_only_names_are_rejected(base):
    for name in ("", "   ", "\t", ".pdf", ".PDF", " .pdf "):
        with pytest.raises(ValueError):
            safe_path(base, name)


# ---------------------------------------------------------------- 空字节
@pytest.mark.parametrize("name", ["\x00", "a\x00b", "paper.pdf\x00", "\x00paper"])
def test_embedded_nul_is_rejected(base, name):
    """NUL 不是空白，`raw.strip()` 挡不住它——现在靠 resolve() 撞 OSError 后
    转成 ValueError，虽然理由绕了一层，但结论是对的：拒。"""
    with pytest.raises(ValueError):
        safe_path(base, name)


@pytest.mark.skipif(os.name == "nt", reason="Windows 下空字节的行为由 API 层决定，这里只测 POSIX")
def test_nul_byte_never_becomes_a_written_file(base):
    """拒绝之外再加一条：不许有任何东西落在 base 之外，也不许有空名文件。"""
    with pytest.raises(ValueError):
        safe_path(base, "\x00secret")
    assert list(base.iterdir()) == []


# ---------------------------------------------------------------- 类型门
# 曾经是 strict xfail（`raw = str(name)` 把 None/True/3 收编成合法名），
# 2026-11 Lead 落地 isinstance 类型门后翻为正式断言——这两条现在是防线本身。
def test_rejects_none_like_input(base):
    with pytest.raises(ValueError):
        safe_path(base, None)


def test_rejects_non_string_input(base):
    for value in (True, 3, 3.5, ["paper"], {"n": 1}):
        with pytest.raises(ValueError):
            safe_path(base, value)


# ---------------------------------------------------------------- 符号链接
def _try_symlink(target: Path, link: Path) -> bool:
    """平台不支持符号链接时返回 False，让调用方 skip 而不是假失败。"""
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # Windows 无特权时是 OSError [WinError 1314]
        return False
    return True


def test_symlink_inside_base_pointing_outside_is_rejected(base, tmp_path):
    """名字里一个分隔符都没有，但 resolve() 会跟着链接跑到外面——
    这条正说明为什么最后必须拿 is_relative_to 兜一层，前几条规则挡不住它。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    if not _try_symlink(outside, base / "link"):
        pytest.skip("该平台不允许创建符号链接（通常是 Windows 缺开发者模式/非管理员）")
    with pytest.raises(ValueError):
        safe_path(base, "link")


def test_symlink_from_base_to_sibling_still_allowed(base, tmp_path):
    """base 自己是一条链接时守卫照常工作：它比的是 resolve 之后的绝对前缀，
    不是"base 是不是真身"。生产里 base 都是实打实的数据目录，这条是把
    resolve 那一步的语义钉住，别哪天有人把 base 换成未 resolve 的版本。"""
    real = tmp_path / "real"
    real.mkdir()
    link_base = tmp_path / "base_link"
    if not _try_symlink(real, link_base):
        pytest.skip("该平台不允许创建符号链接")
    got = safe_path(link_base, "paper.pdf")
    # 注意名字里的 .pdf 是被剥掉的，所以真身那边叫 paper 而不是 paper.pdf
    assert got == (real / "paper")
    assert got.parent == real.resolve()  # base 的解析版本，不是链接自己的路径


def test_hardlinked_name_changes_nothing_about_the_guard(base):
    """硬链接不是路径穿越，但值得钉一下：同一个 inode 换个名字，守卫看的是
    名字形状，所以两条路都合法且都落在 base 内。"""
    try:
        (base / "orig.pdf").write_text("x", encoding="utf-8")
        os.link(base / "orig.pdf", base / "alias.pdf")
    except (OSError, NotImplementedError):
        pytest.skip("该平台不支持硬链接")
    assert safe_path(base, "orig").is_relative_to(base)
    assert safe_path(base, "alias").is_relative_to(base)


# ---------------------------------------------------------------- 拒绝面要广
def test_every_rejected_input_leaves_the_base_untouched(base):
    """拒绝语义的另一半：不许留副作用。空目录是这里期望的状态。"""
    bad = [
        "../etc/passwd", "a/b", "x\\y", "/etc/passwd", "C:/x", " UNC",
        "", " ", "..", ".hidden", "\x00", ".pdf", "./x", "\\",
    ]
    for name in bad:
        try:
            safe_path(base, name)
        except ValueError:
            pass
    assert list(base.iterdir()) == []


def test_rejections_raise_valueerror_not_something_else(base):
    """调用方普遍按 ValueError 走 4xx 分支；这里把异常类型钉住，
    防止哪天改成 OSError/自定义异常后前端 500 掉。"""
    for name in ("../x", "a/b", "", ".hidden"):
        with pytest.raises(ValueError):
            safe_path(base, name)


@pytest.mark.skipif(sys.platform == "darwin", reason=(
    "macOS 的 /tmp 本身就是 /private/tmp 的符号链接，"
    "\"base 落在 /tmp 下\"的这组对照在这里没有独立信息量——Linux CI 才跑得动"
))
def test_relative_base_is_honoured(tmp_path, monkeypatch):
    """生产里有些调用方传的是相对 Path；resolve() 之后同样要判在根内。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "root").mkdir()
    got = safe_path(Path("root"), "paper.pdf")
    assert got.is_absolute()
    assert got.is_relative_to((tmp_path / "root").resolve())
