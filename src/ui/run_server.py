"""启动脚本（跨平台优化版）"""

import uvicorn
import sys
import os
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def setup_windows_optimizations():
    """Windows 平台优化配置"""
    if sys.platform != "win32":
        return

    print("🔧 检测到 Windows 系统，应用优化配置...")

    # 1. 禁用快速编辑模式（防止点击控制台导致卡住）
    try:
        import ctypes
        from ctypes import wintypes

        STD_INPUT_HANDLE = -10
        ENABLE_QUICK_EDIT_MODE = 0x0040
        ENABLE_EXTENDED_FLAGS = 0x0080

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)

        mode = wintypes.DWORD()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))

        new_mode = mode.value & ~ENABLE_QUICK_EDIT_MODE
        new_mode |= ENABLE_EXTENDED_FLAGS

        if kernel32.SetConsoleMode(handle, new_mode):
            print("   ✅ 已禁用控制台快速编辑模式")
        else:
            print("   ⚠️  无法修改控制台模式（如遇卡顿，请手动禁用快速编辑模式）")
    except Exception as e:
        print(f"   ⚠️  控制台配置失败: {e}")

    # 2. 配置异步事件循环策略
    try:
        import asyncio
        if sys.version_info >= (3, 8):
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            print("   ✅ 已配置 ProactorEventLoop 策略")
    except Exception as e:
        print(f"   ⚠️  事件循环配置失败: {e}")

    # 3. 禁用输出缓冲
    os.environ["PYTHONUNBUFFERED"] = "1"
    print("   ✅ 已禁用输出缓冲")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 AgenticReader 服务器启动中...")
    print("=" * 60)
    print()

    # 应用平台优化
    setup_windows_optimizations()

    print("🌐 服务器地址: http://localhost:8000")
    print("📊 API 文档: http://localhost:8000/docs")
    print()
    print("💡 按 Ctrl+C 停止服务器")
    print("=" * 60)
    print()

    try:
        uvicorn.run(
            "src.ui.backend.app:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            reload_excludes=["*.pyc", "__pycache__", ".venv/*", ".git/*", "*.egg-info"],
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n\n👋 服务器已停止")
    except Exception as e:
        print(f"\n❌ 服务器启动失败: {e}")
        import traceback
        traceback.print_exc()
