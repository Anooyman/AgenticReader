"""启动脚本（跨平台优化版）"""

import uvicorn
import sys
import os
import logging
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 默认只监听本机回环地址，避免局域网/外部直接访问（本地应用无需完整鉴权）
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
# 视为「仅本机」的地址集合，其余地址会打 WARNING
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def resolve_host() -> str:
    """解析监听地址：默认 127.0.0.1，可用环境变量 HOST 覆盖；非本机地址打 WARNING"""
    host = (os.environ.get("HOST") or "").strip() or DEFAULT_HOST
    if host.lower() not in LOCAL_HOSTS:
        logging.warning(
            "检测到非本机监听地址 HOST=%s：服务将暴露给局域网/外部网络，"
            "本应用按本地应用设计，没有鉴权，请确认这是预期行为",
            host,
        )
    return host


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

    host = resolve_host()
    try:
        port = int(os.environ.get("PORT") or DEFAULT_PORT)
    except ValueError:
        print(f"⚠️  PORT 配置无效，使用默认端口 {DEFAULT_PORT}")
        port = DEFAULT_PORT

    display_host = "localhost" if host.lower() in ("127.0.0.1", "localhost", "::1") else host

    print(f"🌐 服务器地址: http://{display_host}:{port}")
    print(f"📊 API 文档: http://{display_host}:{port}/docs")
    print()
    print("💡 按 Ctrl+C 停止服务器")
    print("=" * 60)
    print()

    try:
        uvicorn.run(
            "src.ui.backend.app:app",
            host=host,
            port=port,
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
