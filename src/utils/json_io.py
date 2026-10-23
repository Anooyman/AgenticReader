"""共享状态 JSON 的原子落盘实现。

放在 utils 层的原因：此前唯一实现藏在 src/pipeline/paths.py 里，
core/document_management/registry.py 为了复用它形成了 core→pipeline 的模块级
反向依赖（只为一个十行函数）。现把实现挪到与本包 path_guard.py 同层的这里，
pipeline.paths 保留同名 re-export，所有既有 `from src.pipeline.paths import
write_json_atomic` 的调用方零改动。

范式（与 registry._transaction / queue_store.queue_transaction 一致）：
tmp 文件 + os.replace 防"写到一半崩溃"；跨进程并发另靠 .lock 文件的 flock，
两者互补，本模块只负责前者。
"""
import json
import os
import threading
from pathlib import Path


def write_json_atomic(path: Path, data) -> None:
    """先写 .tmp 再原子替换——进程在写入途中被杀时，原文件保持完好，
    不会留下半截 JSON。queue/summary/sessions/tasks/app_config 的落盘
    统一用这一个实现。

    tmp 名带 pid+线程 id：同进程多线程（如 asyncio.to_thread 里的会话保存）
    并发写同一目标时不会互抢同一个 .tmp——此前固定名会让先完成方的 rename
    把还在写的手里的 tmp 抢走（FileNotFoundError / 半截替换）。同 fs 上
    os.replace 仍是原子的，多线程竞态的结果是"最后完成者胜"，与语义相符。

    注意它只防"写到一半崩溃"和"半截文件"，不防"两个进程读-改-写交错"——
    后者要靠 queue_transaction / registry._transaction 那类锁，两者互补。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(
        path.suffix + f".tmp.{os.getpid()}.{threading.get_ident()}"
    )
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path.replace(path)
    finally:
        # 极端情况（dump 中途抛异常）不留孤儿 tmp；成功路径下 tmp 已被 rename，
        # unlink(missing_ok) 是 no-op。
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
