"""配置管理API路由"""

import json
from pathlib import Path
from fastapi import APIRouter
from ...models.chat import ProviderConfig
from ...config.logging import get_logger
from ...config.settings import settings

logger = get_logger(__name__)
router = APIRouter()

# 配置文件路径
CONFIG_FILE = settings.data_dir / "config" / "app_config.json"

def load_config():
    """从文件加载配置"""
    # 默认配置 - 只包含需要持久化的设置
    persistent_config = {
        "provider": "openai",
        "pdf_preset": "high"
    }

    # 会话级别的状态 - 每次启动都重置
    session_state = {
        "current_doc_name": None,
        "has_pdf_reader": False,
        "has_web_reader": False
    }

    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                # 只保留持久化的设置，忽略文档状态
                persistent_config["provider"] = saved_config.get("provider", "openai")
                persistent_config["pdf_preset"] = saved_config.get("pdf_preset", "high")
                logger.info(f"📖 从文件加载持久配置: {persistent_config}")
        else:
            logger.info("📄 配置文件不存在，使用默认配置")
    except Exception as e:
        logger.error(f"❌ 加载配置文件失败: {e}")

    # 合并持久配置和会话状态
    final_config = {**persistent_config, **session_state}
    logger.info(f"🔄 会话状态已重置: current_doc_name=None, has_pdf_reader=False, has_web_reader=False")
    return final_config

def save_config(config):
    """保存配置到文件 - 只保存持久化设置，不保存文档状态"""
    try:
        # 只保存需要持久化的设置
        persistent_config = {
            "provider": config.get("provider", "openai"),
            "pdf_preset": config.get("pdf_preset", "high")
        }

        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(persistent_config, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 持久配置已保存到文件: {persistent_config}")
        logger.info("🔄 文档状态不会持久化，服务器重启后将重置")
    except Exception as e:
        logger.error(f"❌ 保存配置文件失败: {e}")

# 全局配置状态 - 从文件加载
_current_config = load_config()


@router.get("/config")
async def get_config():
    """获取当前配置"""
    return _current_config


@router.post("/config/provider")
async def update_provider(config: ProviderConfig):
    """更新LLM提供商配置"""
    try:
        global _current_config
        _current_config["provider"] = config.provider
        if config.pdf_preset:
            _current_config["pdf_preset"] = config.pdf_preset

        # 保存到文件
        save_config(_current_config)

        logger.info(f"更新配置: provider={config.provider}, pdf_preset={config.pdf_preset}")

        return {
            "status": "success",
            "provider": _current_config["provider"],
            "pdf_preset": _current_config["pdf_preset"]
        }
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        return {"status": "error", "message": str(e)}

def update_document_state(doc_name, has_pdf_reader=False, has_web_reader=False):
    """更新文档状态（供其他模块调用）"""
    global _current_config
    _current_config["current_doc_name"] = doc_name
    _current_config["has_pdf_reader"] = has_pdf_reader
    _current_config["has_web_reader"] = has_web_reader

    # 保存到文件
    save_config(_current_config)
    logger.info(f"📄 文档状态已更新: {_current_config}")


def get_current_provider() -> str:
    """获取当前配置的 LLM provider（供其他模块调用）"""
    return _current_config.get("provider", "openai")


def get_current_pdf_preset() -> str:
    """获取当前配置的 PDF preset（供其他模块调用）"""
    return _current_config.get("pdf_preset", "high")


def clear_document_state():
    """清除文档状态（供其他模块调用）"""
    global _current_config
    _current_config["current_doc_name"] = None
    _current_config["has_pdf_reader"] = False
    _current_config["has_web_reader"] = False

    # 注意：不保存到文件，因为文档状态不应该持久化
    logger.info(f"🗑️ 文档状态已清除（仅内存）: {_current_config}")

@router.post("/config/clear")
async def clear_config():
    """清除文档状态API端点"""
    try:
        clear_document_state()
        return {
            "status": "success",
            "message": "文档状态已清除",
            "config": _current_config
        }
    except Exception as e:
        logger.error(f"清除文档状态失败: {e}")
        return {"status": "error", "message": str(e)}