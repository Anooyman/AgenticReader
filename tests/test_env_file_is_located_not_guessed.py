"""`.env` 是**被指到**的，不是被猜到的。

这条测试存在的起因是一次很安静的失败：AR 根目录明明写了 `LLM_MEMORY_REPO=…`，
`load_dotenv()` 却没有加载它——因为那句无参调用是靠"调用栈的源文件在哪"往上摸，
摸空之后它什么都不说。于是一个被重起的服务就悄悄退回了"全部走本地"，
屏幕上没有任何东西报错，测试也全绿。

这里钉两件事：
1. 项目根 `.env` 的位置是从代码位置**算**出来的，跟进程从哪儿启动无关；
2. 进程环境里**已经有**的值优先，dotenv 不许覆盖它——那是运维的表达方式。
"""
import os
import subprocess
import sys

import pytest

from src.config import settings

AR_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(settings.__file__)).replace(
    os.path.join("src", "config"), ""))


def test_the_env_file_is_pinned_by_path_not_by_guessing():
    assert os.path.isabs(settings.PROJECT_ENV_FILE)
    assert os.path.basename(settings.PROJECT_ENV_FILE) == ".env"
    assert os.path.dirname(settings.PROJECT_ENV_FILE) == AR_ROOT, \
        "它必须指着项目根那份，指到别处就是又一次'靠运气找到'"


def test_the_repo_resolves_even_when_the_process_starts_somewhere_else(tmp_path):
    """真正的回归点：从**别的工作目录**起进程，还是得认这份 .env。

    旧写法（`load_dotenv()`）在这里就会静默失败——而静默失败正是这个坑
    最贵的地方：它不是报错，是路由悄悄退回了本地。
    """
    env = {k: v for k, v in os.environ.items() if k != "LLM_MEMORY_REPO"}
    env["PYTHONPATH"] = AR_ROOT
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r);"
         "from src.config.settings import get_llm_memory_repo;"
         "print(get_llm_memory_repo() or '')" % AR_ROOT],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, proc.stderr[-300:]
    got = proc.stdout.strip()
    # 子进程里被我们抹掉了这个变量，所以"还答得出来"只能来自那份 .env——
    # 拿它和文件里的原文对，才是真断言；写成"不为空"就只是看着像检查。
    expected = ""
    for line in open(os.path.join(AR_ROOT, ".env"), encoding="utf-8"):
        if line.strip().startswith("LLM_MEMORY_REPO="):
            expected = line.strip().split("=", 1)[1]
            break
    assert got == expected, f"文件里写的是 {expected!r}，进程从别处起却读到 {got!r}"


def test_an_explicit_shell_value_wins_and_dotenv_does_not_stamp_over_it(monkeypatch):
    """`.env` 里写了什么不重要：谁在进程外先说了话，谁就是那一句。
    反向覆盖会悄悄把运维的一次性开关洗掉。"""
    monkeypatch.setenv("LLM_MEMORY_REPO", "/some/override/from/shell")
    from src.config.settings import get_llm_memory_repo
    assert get_llm_memory_repo() == "/some/override/from/shell"
