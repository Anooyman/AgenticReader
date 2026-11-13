"""配置管理 API"""

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from ...config import DATA_DIR
from src.utils.json_io import write_json_atomic
from src.config.settings import get_model_registry

router = APIRouter()

# 配置文件路径
CONFIG_FILE = DATA_DIR / "config" / "app_config.json"

# 模型注册表支持的 provider（与 settings._VALID_MODEL_PROVIDERS 对齐）
_MODEL_PROVIDERS = ("azure", "openai", "ollama", "gemini")


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


# ============================================================================
# 模型注册表（UI 可配置的多模型列表，类似 DSH 的 provider+model 组合方式）
#
# 数据落在 app_config.json 的 "models" 键：
#   {"models": {"openai": {"current": "GPT-6", "items": [
#       {"name": "GPT-6", "model": "gpt-6-luna",
#        "base_url": null, "api_key": "..."}]}}}
# LLM 构造链路经 settings.resolve_model_config() 读取覆盖值。
# ============================================================================


class ModelEntry(BaseModel):
    """注册表里的单个模型条目"""
    name: str                      # 显示名，provider 内唯一（如 "GPT-6 via Trend"）
    model: str                     # 模型名（如 "gpt-6-luna"）
    base_url: Optional[str] = None # 覆盖该 provider 的 base_url / endpoint
    api_key: Optional[str] = None  # 覆盖 API key（只写不回显）


class ModelRegistryUpdate(BaseModel):
    """整个 provider 的注册表更新（items 全量替换）"""
    provider: str
    current: Optional[str] = None  # 当前选中的注册名；None=未选择（回退 env/默认）
    items: List[ModelEntry] = []


def _sanitize_registry_for_ui(registry: Dict[str, Any]) -> Dict[str, Any]:
    """给前端的注册表视图：api_key 打码成布尔 has_api_key，避免密钥回显。"""
    safe = {}
    for provider, entry in registry.items():
        items = []
        for item in entry.get("items", []):
            safe_item = dict(item)
            has_key = bool(safe_item.pop("api_key", None))
            safe_item["has_api_key"] = has_key
            items.append(safe_item)
        safe[provider] = {"current": entry.get("current"), "items": items}
    return safe


def _validate_registry_update(update: ModelRegistryUpdate) -> str:
    """provider 合法性 + 注册名唯一性校验；出错时抛 HTTPException。"""
    provider = (update.provider or "").strip().lower()
    if provider not in _MODEL_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 provider: {update.provider!r}（可选: {', '.join(_MODEL_PROVIDERS)}）",
        )
    names = [item.name.strip() for item in update.items]
    if len(names) != len(set(names)):
        raise HTTPException(status_code=400, detail="同一 provider 下的模型显示名不能重复")
    if update.current and update.current not in names:
        raise HTTPException(
            status_code=400,
            detail=f"current 指向的 {update.current!r} 不在 items 里",
        )
    for item in update.items:
        if not item.model.strip():
            raise HTTPException(status_code=400, detail=f"{item.name!r} 缺少模型名")
    return provider


@router.get("/models")
async def get_models() -> Dict[str, Any]:
    """获取模型注册表（api_key 打码为 has_api_key）+ 各 provider 现有配置。

    env_defaults：每个 provider 从环境变量/代码默认值解析出来的"内置默认"
    配置（model + base_url），供前端作为一条只读条目展示——这就是"已有的
    配置"，用户不用翻 .env 也能看到当前 provider 接的是哪个模型、哪个端点。
    effective：现在实际生效的模型名（注册表 current 或内置默认）。"""
    registry = get_model_registry()
    effective: Dict[str, Optional[str]] = {}
    env_defaults: Dict[str, Dict[str, Optional[str]]] = {}
    try:
        from src.config.settings import resolve_model_config, LLM_CONFIG
        # 内置默认 = providers.py 在无注册表覆盖时会用到的值
        env_defaults = {
            "azure": {
                "model": LLM_CONFIG.get("model_name") or LLM_CONFIG.get("deployment_name"),
                "base_url": LLM_CONFIG.get("azure_endpoint"),
            },
            "openai": {
                "model": LLM_CONFIG.get("openai_model_name"),
                "base_url": LLM_CONFIG.get("openai_base_url"),
            },
            "ollama": {
                "model": LLM_CONFIG.get("ollama_model_name"),
                "base_url": LLM_CONFIG.get("ollama_base_url"),
            },
            "gemini": {
                "model": LLM_CONFIG.get("gemini_model_name"),
                "base_url": LLM_CONFIG.get("gemini_base_url"),
            },
        }
        for provider in _MODEL_PROVIDERS:
            override = resolve_model_config(provider)
            effective[provider] = (override.get("model")
                                   or (env_defaults.get(provider) or {}).get("model"))
    except Exception:
        pass

    return {
        "registry": _sanitize_registry_for_ui(registry),
        "effective": effective,
        "env_defaults": env_defaults,
    }


@router.post("/models")
async def update_models(update: ModelRegistryUpdate) -> Dict[str, Any]:
    """更新某 provider 的模型注册表（items 全量替换 + 可选切换 current）。

    与 /provider 端点一样写 app_config.json；注意 _current_config 是模块级
    缓存，这里改的是同一文件的另一个键，需要同步进缓存避免下次
    /provider 保存时把 models 键抹掉。"""
    provider = _validate_registry_update(update)

    try:
        # 读最新文件（而非模块缓存），避免与其它写入方互相覆盖
        cfg = {}
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        cfg = loaded
        except Exception:
            cfg = {}

        models = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
        models[provider] = {
            "current": update.current,
            "items": [item.dict() for item in update.items],
        }
        cfg["models"] = models

        write_json_atomic(CONFIG_FILE, cfg)
        # 同步模块缓存里的 models 键（/provider、/system 保存走的是这个缓存）
        _current_config["models"] = models

        print(f"✅ 模型注册表已更新: provider={provider}, "
              f"current={update.current!r}, {len(update.items)} 个条目")

        return {
            "status": "success",
            "message": "模型注册表已更新",
            "registry": _sanitize_registry_for_ui(get_model_registry()),
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 更新模型注册表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ModelTestRequest(BaseModel):
    """测试连接请求：直接带条目字段（不必先保存）"""
    provider: str
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None


@router.post("/models/test")
async def test_model(req: ModelTestRequest) -> Dict[str, Any]:
    """测试模型配置是否可用：真实发一次最小对话请求。

    api_key 为空时回退该 provider 的 env 凭据——这样"只加模型名"的条目
    也能测。失败返回 200 + ok:false（这是探测结果不是接口错误）。"""
    from src.config.settings import LLM_CONFIG

    provider = (req.provider or "").strip().lower()
    if provider not in _MODEL_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"不支持的 provider: {req.provider!r}")
    if not req.model.strip():
        raise HTTPException(status_code=400, detail="缺少模型名")

    # api_key / base_url 缺省回退 env（与 get_chat_model 的回退顺序一致）
    api_key = req.api_key
    base_url = req.base_url
    if provider == "openai":
        api_key = api_key or LLM_CONFIG.get("openai_api_key")
        base_url = base_url or LLM_CONFIG.get("openai_base_url")
    elif provider == "azure":
        api_key = api_key or LLM_CONFIG.get("api_key")
    elif provider == "ollama":
        base_url = base_url or LLM_CONFIG.get("ollama_base_url", "http://localhost:11434")
    elif provider == "gemini":
        api_key = api_key or LLM_CONFIG.get("gemini_api_key")

    try:
        model = _build_test_chat_model(provider, req.model.strip(), api_key, base_url)
        resp = await model.ainvoke("Reply with the single word: OK")
        text = (getattr(resp, "content", "") or "").strip()
        return {
            "ok": True,
            "reply": text[:200],
            "model": req.model.strip(),
            "provider": provider,
        }
    except Exception as e:
        print(f"❌ 模型测试失败 ({provider}/{req.model}): {e}")
        return {"ok": False, "error": str(e)[:500],
                "model": req.model.strip(), "provider": provider}


def _build_test_chat_model(provider: str, model: str, api_key: Optional[str],
                           base_url: Optional[str]):
    """为测试构造最小 chat model 实例（temperature=0，不走注册表）。"""
    from src.config.settings import LLM_CONFIG

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, openai_api_key=api_key, base_url=base_url,
                          temperature=0, max_retries=1, timeout=30)
    if provider == "azure":
        from langchain_openai import AzureChatOpenAI
        return AzureChatOpenAI(
            openai_api_key=api_key,
            openai_api_version=LLM_CONFIG.get("api_version"),
            azure_endpoint=LLM_CONFIG.get("azure_endpoint"),
            deployment_name=LLM_CONFIG.get("deployment_name") or model,
            model_name=model,
            temperature=0, max_retries=1, timeout=30)
    if provider == "ollama":
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(base_url=base_url, model=model, temperature=0)
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        config = {"google_api_key": api_key, "model": model,
                  "temperature": 0, "max_retries": 1}
        if base_url:
            config["client_options"] = {"api_endpoint": base_url}
        return ChatGoogleGenerativeAI(**config)
    raise HTTPException(status_code=400, detail=f"不支持的 provider: {provider!r}")
