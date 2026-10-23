"""数据管理 API 的跨模块共享 helper（REFACTOR_REPORT P2-4 拆分产物）

本模块只放被 documents / storage / ops 三个 /data 子模块共同使用的
纯工具函数，避免模块之间为一个小函数互相 import 造成循环依赖。
"""

from pathlib import Path


def get_dir_size(path: Path) -> float:
    """
    计算目录大小（MB）

    Args:
        path: 目录路径

    Returns:
        目录大小（MB）
    """
    if not path.exists():
        return 0.0

    total_size = 0
    if path.is_file():
        total_size = path.stat().st_size
    elif path.is_dir():
        for item in path.rglob('*'):
            if item.is_file():
                try:
                    total_size += item.stat().st_size
                except (OSError, PermissionError):
                    continue

    return total_size / (1024 * 1024)  # Convert to MB
