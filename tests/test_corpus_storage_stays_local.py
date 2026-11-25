"""**语料库这半边不跟着路由走**——这条要说得出来，才配说"记忆归上游"。

objective 的原话是"AR 只保留自己 repo 里的 PDF 语料库存储"。前半句已经反复验过
（记忆确实走上游），但这半句一直是靠架构说法撑着：没人写过一条测试去确认
`data/vector_db/` 的解析**不会**被 `LLM_MEMORY_REPO` 影响。这类事情的危险在于
它现在大概率是对的，于是没人再去看它——等到哪天某个"顺手统一路径"的改动把它
接进配置块，测试不会响，语料库就先一步离家了。

所以这里钉的是**否**：
* 不管上游设没设、可用不可用，语料库路径都还在 AR 自己的 data 下面；
* 语料库这一侧的解析过程**一次都不该去问上游**——问了就炸给它看；
* 记忆侧的 env 旋钮转不动这半边。
"""
import os

import pytest

from src.config import constants as const


def _corpus_root():
    return os.path.abspath(str(const.get_data_root()))


def test_the_corpus_dir_lives_under_agenticreader_regardless_of_upstream(monkeypatch):
    monkeypatch.delenv("LLM_MEMORY_REPO", raising=False)
    monkeypatch.delenv("MEMORY_STORE_MODE", raising=False)
    root = _corpus_root()
    assert os.path.abspath(str(const.get_vector_db_dir())).startswith(root)
    assert not os.path.abspath(str(const.get_vector_db_dir())).startswith(
        os.path.expanduser("~/.llm-memory"))


@pytest.mark.parametrize("mode", ["auto", "local", "upstream"])
def test_flipping_the_memory_router_does_not_move_the_corpus(monkeypatch, tmp_path, mode):
    """把记忆侧那个旋钮从左拨到右，语料库一个字节的落点都不该变。"""
    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))
    monkeypatch.setenv("MEMORY_STORE_MODE", mode)

    before = os.path.abspath(str(const.get_vector_db_dir()))
    root = os.path.abspath(str(const.get_data_root()))
    after = os.path.abspath(str(const.get_vector_db_dir()))
    assert before == after == os.path.join(root, const.PathConstants.VECTOR_DB_DIR)


def test_corpus_path_resolution_never_asks_upstream_a_single_question(monkeypatch, tmp_path):
    """这条比断言值更要紧：**问都没问**才算边界干净。

    做法是把上游那一侧的入口全换成"被调用就炸"的版本，然后照常解析语料库路径。
    任何一次越界的调用都会变成 AssertionError，而不是一句悄悄生效的路径。
    """
    repo = tmp_path / "llm-memory"
    (repo / "src" / "llm_memoryd").mkdir(parents=True)
    monkeypatch.setenv("LLM_MEMORY_REPO", str(repo))

    import src.memory.upstream as upstream

    def _boom(*a, **kw):
        raise AssertionError("语料库这一侧的路径解析居然去问了上游——边界破了")

    for name in dir(upstream):
        if name.startswith("upstream_"):
            monkeypatch.setattr(upstream, name, _boom)

    assert os.path.abspath(str(const.get_vector_db_dir()))
    assert os.path.abspath(str(const.get_data_root()))


def test_the_corpus_constant_is_a_plain_relative_name(monkeypatch):
    """它不是从配置块里拿出来的：是一个相对名字，锚在 data root 上——
    这就是"语料库归 AR"这件事在代码里唯一存在的形式，别把它换成绝对路径。"""
    assert not os.path.isabs(const.PathConstants.VECTOR_DB_DIR)
    assert const.PathConstants.VECTOR_DB_DIR == "vector_db"
