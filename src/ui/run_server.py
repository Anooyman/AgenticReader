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


# chat 路各 provider 需要的 key env；None＝该 provider 不需要 key。
_CHAT_KEY_ENVS = {
    "openai": "OPENAI_API_KEY",
    "azure": "CHAT_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "ollama": None,
}


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


def resolve_log_level() -> str:
    """uvicorn 的日志级别：读 data/config/app_config.json 的 log_level 键
    （/config 页写入的即此键），无效/缺失一律退 "info"。

    注意这只是 uvicorn 自身访问日志的级别；应用日志级别写死在
    src/core/llm/client.py 的 basicConfig(level=INFO)（全仓另有多处各自
    basicConfig，见该文件注释的统一说明），两者是两回事。README 里宣传的
    LOGGING_LEVEL 环境变量已无任何代码读取，别再引用它。"""
    raw = ""
    try:
        import json
        from src.config.settings import APP_CONFIG_FILE  # 单一事实源
        if APP_CONFIG_FILE.exists():
            raw = str(json.loads(APP_CONFIG_FILE.read_text(encoding="utf-8"))
                      .get("log_level") or "")
    except Exception as e:  # 配置缺失/损坏不该挡住启动
        logging.getLogger(__name__).warning("读取 app_config.log_level 失败，用 info: %s", e)
    level = raw.strip().lower()
    if level not in {"critical", "error", "warning", "info", "debug", "trace"}:
        if raw:
            logging.getLogger(__name__).warning(
                "app_config.log_level=%r 不是 uvicorn 认可的级别，按 info 处理", raw)
        return "info"
    return level


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


def check_llm_credentials() -> None:
    """启动自检：当前解析出的 provider 在所有真源都拿不到 key 时打 warning。

    起因是 2026-11-25 的事故：服务重启后 shell 里 export 过的 OPENAI_API_KEY
    消失，ChatOpenAI 在第一条消息的构造期才炸，界面上只剩"处理失败"——
    诊断成本全花在"是不是代码改坏了"上。这条检查把"猜"变成"看"。

    检查链与运行期完全同构，别让它自说自话：
      * 进程环境——settings 的 load_dotenv(PROJECT_ENV_FILE) 会把项目 .env
        并进来，所以"env 里有没有"已含 .env 这条源；
      * app_config 模型注册表的 api_key override——providers.py 确实会采纳。
    ollama 无 key 一说，直接跳过。

    **只 warning 不退出**：/data、/briefs、任务侧栏这些不碰 LLM 的页面在
    缺 key 时照样有诊断/运维价值，拦死启动反而是更糟的失败模式。
    """
    try:
        from src.config.settings import get_model_registry, resolve_provider

        provider = resolve_provider(None)
        env_key = _CHAT_KEY_ENVS.get(provider)
        if not env_key or os.environ.get(env_key):
            return
        registry = get_model_registry() or {}
        entries = registry.get(provider) or {}
        covered = any(str(item.get("api_key") or "").strip()
                      for item in (entries.get("items") or []))
        if not covered:
            logging.warning(
                "⚠️  provider=%s 但 %s 未设置（查过：进程 env / 项目 .env / "
                "模型注册表 override 三处都空）——chat、索引摘要、记忆写入"
                "通道将全部失败。修复：项目根 .env 写 %s=<key>（settings "
                "是 import 期读定，改完需重启服务）或启动前 export",
                provider, env_key, env_key)
    except Exception as e:  # noqa: BLE001 —— 自检自身坏了不能拖累启动
        logging.debug("llm 凭证自检跳过: %s", e)


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 AgenticReader 服务器启动中...")
    print("=" * 60)
    print()

    # 应用平台优化
    setup_windows_optimizations()

    check_llm_credentials()

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
            log_level=resolve_log_level()
        )
    except KeyboardInterrupt:
        print("\n\n👋 服务器已停止")
    except Exception as e:
        print(f"\n❌ 服务器启动失败: {e}")
        import traceback
        traceback.print_exc()
