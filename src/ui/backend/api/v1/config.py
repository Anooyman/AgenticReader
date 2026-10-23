"""配置管理 API"""

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

from ...config import DATA_DIR
from src.utils.json_io import write_json_atomic

router = APIRouter()

# 配置文件路径
CONFIG_FILE = DATA_DIR / "config" / "app_config.json"


class ProviderConfig(BaseModel):
    """LLM提供商配置"""
    provider: str
    pdf_preset: Optional[str] = "high"


class SystemConfig(BaseModel):
    """系统配置"""
    auto_save_outputs: bool = True
    enable_notifications: bool = True
    log_level: str = "INFO"


def load_config() -> Dict[str, Any]:
    """从文件加载配置"""
    default_config = {
        "provider": "openai",
        "pdf_preset": "high",
        "auto_save_outputs": True,
        "enable_notifications": True,
        "log_level": "INFO"
    }

    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                default_config.update(saved_config)
                print(f"✅ 从文件加载配置: {CONFIG_FILE}")
        else:
            print("📄 配置文件不存在，使用默认配置")
    except Exception as e:
        print(f"❌ 加载配置文件失败: {e}")

    return default_config


def save_config(config: Dict[str, Any]):
    """保存配置到文件"""
    try:
        write_json_atomic(CONFIG_FILE, config)
        print(f"✅ 配置已保存到文件: {CONFIG_FILE}")
    except Exception as e:
        print(f"❌ 保存配置文件失败: {e}")
        raise


# 全局配置状态
_current_config = load_config()


@router.get("")
async def get_config() -> Dict[str, Any]:
    """获取当前配置"""
    return _current_config


@router.post("/provider")
async def update_provider(config: ProviderConfig) -> Dict[str, Any]:
    """更新LLM提供商配置"""
    try:
        global _current_config
        _current_config["provider"] = config.provider
        if config.pdf_preset:
            _current_config["pdf_preset"] = config.pdf_preset

        # 保存到文件
        save_config(_current_config)

        print(f"✅ 更新配置: provider={config.provider}, pdf_preset={config.pdf_preset}")

        return {
            "status": "success",
            "message": "配置已更新",
            "config": _current_config
        }
    except Exception as e:
        print(f"❌ 更新配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/system")
async def update_system_config(config: SystemConfig) -> Dict[str, Any]:
    """更新系统配置"""
    try:
        global _current_config
        _current_config["auto_save_outputs"] = config.auto_save_outputs
        _current_config["enable_notifications"] = config.enable_notifications
        _current_config["log_level"] = config.log_level

        # 保存到文件
        save_config(_current_config)

        print(f"✅ 更新系统配置: {config.dict()}")

        return {
            "status": "success",
            "message": "系统配置已更新",
            "config": _current_config
        }
    except Exception as e:
        print(f"❌ 更新系统配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
async def reset_config() -> Dict[str, Any]:
    """重置配置为默认值"""
    try:
        global _current_config
        _current_config = {
            "provider": "openai",
            "pdf_preset": "high",
            "auto_save_outputs": True,
            "enable_notifications": True,
            "log_level": "INFO"
        }

        # 保存到文件
        save_config(_current_config)

        print("✅ 配置已重置为默认值")

        return {
            "status": "success",
            "message": "配置已重置为默认值",
            "config": _current_config
        }
    except Exception as e:
        print(f"❌ 重置配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def get_current_provider() -> str:
    """获取当前配置的 LLM provider（供其他模块调用）。

    单一事实源在 settings.resolve_provider()——它直接读 app_config.json 再
    回退 env；本函数只是它的别名，避免再维护一份内存缓存导致漂移。"""
    from src.config.settings import get_default_provider
    return get_default_provider()


def get_current_pdf_preset() -> str:
    """获取当前配置的 PDF preset（供其他模块调用）"""
    return _current_config.get("pdf_preset", "high")
