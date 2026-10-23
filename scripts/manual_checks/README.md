# scripts/manual_checks

这里放的是**手工演示脚本，不是自动化测试**。

它们来自 `tests/`（原先被 pytest 收集，会造成"假绿灯"）：全文只有 `print()`，
没有任何 `assert`，也不 import 任何项目模块——跑绿了并不代表系统行为正确。
所以从 `tests/` 移到本目录（`pytest.ini` 的 `testpaths = tests` 天然不再收集它们）。

## 文件

| 文件 | 用途 |
|---|---|
| `test_cross_doc_flow.py` | 用硬编码的假数据打印演示跨文档检索 state 的数据流（RetrievalAgent → ParallelCoordinator → 跨文档合成），用眼看输出是否符合预期 |
| `test_parallel_logging.py` | 对比打印"修改前 / 修改后"的并行检索日志样式，说明每条日志带文档名标识的效果 |

## 用法

直接当脚本跑，不经过 pytest：

```bash
.venv/bin/python scripts/manual_checks/test_cross_doc_flow.py
.venv/bin/python scripts/manual_checks/test_parallel_logging.py
```

两者都在 `if __name__ == "__main__":` 里调用自己的函数，无参数、无退出码语义
（永远返回 0），因此**不要**把它们接进 CI。

## 要写成真正的测试怎么办

把演示里的假数据换成真实调用，并把 `print(f"✅ ...")` 那类结论改写成 `assert`，
再放回 `tests/`（需要 LLM / Embedding 凭据的文件请在
`tests/conftest.py` 的 `LLM_DEPENDENT_FILES` 里登记，缺凭据时会自动 skip）。
