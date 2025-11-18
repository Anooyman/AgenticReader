"""
配置验证工具

提供配置文件验证、环境变量检查和系统设置验证功能
"""
import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .exceptions import ConfigurationError, ValidationError
from .validators import validate_config_dict

logger = logging.getLogger(__name__)


class ConfigValidator:
    """配置验证器类"""

    def __init__(self):
        self.validation_errors: List[str] = []
        self.warnings: List[str] = []

    def add_error(self, message: str):
        """添加验证错误"""
        self.validation_errors.append(message)
        logger.error(f"配置验证错误: {message}")

    def add_warning(self, message: str):
        """添加验证警告"""
        self.warnings.append(message)
        logger.warning(f"配置验证警告: {message}")

    def clear_results(self):
        """清空验证结果"""
        self.validation_errors.clear()
        self.warnings.clear()

    def has_errors(self) -> bool:
        """检查是否有验证错误"""
        return len(self.validation_errors) > 0

    def get_summary(self) -> Dict[str, Any]:
        """获取验证结果摘要"""
        return {
            "errors": self.validation_errors,
            "warnings": self.warnings,
            "error_count": len(self.validation_errors),
            "warning_count": len(self.warnings),
            "is_valid": not self.has_errors()
        }


class LLMConfigValidator(ConfigValidator):
    """LLM配置验证器"""

    REQUIRED_AZURE_FIELDS = [
        'CHAT_API_KEY', 'CHAT_AZURE_ENDPOINT', 'CHAT_DEPLOYMENT_NAME',
        'EMBEDDING_API_KEY', 'EMBEDDING_AZURE_ENDPOINT', 'EMBEDDING_DEPLOYMENT_NAME'
    ]

    REQUIRED_OPENAI_FIELDS = [
        'CHAT_API_KEY', 'CHAT_MODEL_NAME', 'EMBEDDING_API_KEY', 'EMBEDDING_MODEL'
    ]

    REQUIRED_OLLAMA_FIELDS = [
        'CHAT_MODEL_NAME', 'EMBEDDING_MODEL', 'OLLAMA_BASE_URL'
    ]

    VALID_PROVIDERS = {'azure', 'openai', 'ollama'}

    def validate_provider(self, provider: str) -> bool:
        """
        验证LLM提供商配置

        Args:
            provider: LLM提供商名称

        Returns:
            验证是否通过
        """
        if provider not in self.VALID_PROVIDERS:
            self.add_error(f"不支持的LLM提供商: {provider}")
            return False

        if provider == 'azure':
            return self._validate_azure_config()
        elif provider == 'openai':
            return self._validate_openai_config()
        elif provider == 'ollama':
            return self._validate_ollama_config()

        return True

    def _validate_azure_config(self) -> bool:
        """验证Azure OpenAI配置"""
        missing_fields = []

        for field in self.REQUIRED_AZURE_FIELDS:
            if not os.getenv(field):
                missing_fields.append(field)

        if missing_fields:
            self.add_error(f"Azure配置缺少必需的环境变量: {missing_fields}")
            return False

        # 验证endpoint格式
        endpoint = os.getenv('CHAT_AZURE_ENDPOINT')
        if endpoint and not endpoint.startswith('https://'):
            self.add_warning("Azure endpoint应以'https://'开头")

        return True

    def _validate_openai_config(self) -> bool:
        """验证OpenAI配置"""
        missing_fields = []

        for field in self.REQUIRED_OPENAI_FIELDS:
            if not os.getenv(field):
                missing_fields.append(field)

        if missing_fields:
            self.add_error(f"OpenAI配置缺少必需的环境变量: {missing_fields}")
            return False

        return True

    def _validate_ollama_config(self) -> bool:
        """验证Ollama配置"""
        missing_fields = []

        for field in self.REQUIRED_OLLAMA_FIELDS:
            if not os.getenv(field):
                missing_fields.append(field)

        if missing_fields:
            self.add_error(f"Ollama配置缺少必需的环境变量: {missing_fields}")
            return False

        # 验证base URL格式
        base_url = os.getenv('OLLAMA_BASE_URL')
        if base_url and not (base_url.startswith('http://') or base_url.startswith('https://')):
            self.add_warning("Ollama base URL应以'http://'或'https://'开头")

        return True


class PathConfigValidator(ConfigValidator):
    """路径配置验证器"""

    def validate_data_paths(self, paths: Dict[str, str]) -> bool:
        """
        验证数据路径配置

        Args:
            paths: 路径配置字典

        Returns:
            验证是否通过
        """
        all_valid = True

        for name, path in paths.items():
            if not self._validate_single_path(name, path):
                all_valid = False

        return all_valid

    def _validate_single_path(self, name: str, path: str) -> bool:
        """验证单个路径"""
        if not path:
            self.add_error(f"路径 {name} 不能为空")
            return False

        try:
            path_obj = Path(path)

            # 检查父目录是否存在
            if not path_obj.parent.exists():
                self.add_warning(f"路径 {name} 的父目录不存在: {path_obj.parent}")

            # 检查路径是否可写
            if path_obj.exists() and not os.access(path, os.W_OK):
                self.add_error(f"路径 {name} 无写入权限: {path}")
                return False

            # 检查磁盘空间（如果路径存在）
            if path_obj.exists():
                try:
                    import shutil
                    free_space = shutil.disk_usage(path).free
                    if free_space < 100 * 1024 * 1024:  # 100MB
                        self.add_warning(f"路径 {name} 磁盘空间不足100MB: {path}")
                except:
                    pass

        except Exception as e:
            self.add_error(f"路径 {name} 验证失败: {e}")
            return False

        return True


class SystemConfigValidator(ConfigValidator):
    """系统配置验证器"""

    MIN_PYTHON_VERSION = (3, 8)
    REQUIRED_PACKAGES = [
        'langchain', 'openai', 'faiss-cpu', 'streamlit',
        'fastapi', 'uvicorn', 'pymupdf'
    ]

    def validate_system_requirements(self) -> bool:
        """验证系统要求"""
        all_valid = True

        if not self._validate_python_version():
            all_valid = False

        if not self._validate_required_packages():
            all_valid = False

        if not self._validate_system_resources():
            all_valid = False

        return all_valid

    def _validate_python_version(self) -> bool:
        """验证Python版本"""
        import sys

        current_version = sys.version_info[:2]
        if current_version < self.MIN_PYTHON_VERSION:
            self.add_error(
                f"Python版本过低: {current_version}, "
                f"最低要求: {self.MIN_PYTHON_VERSION}"
            )
            return False

        return True

    def _validate_required_packages(self) -> bool:
        """验证必需的包"""
        missing_packages = []

        for package in self.REQUIRED_PACKAGES:
            try:
                __import__(package.replace('-', '_'))
            except ImportError:
                missing_packages.append(package)

        if missing_packages:
            self.add_error(f"缺少必需的包: {missing_packages}")
            return False

        return True

    def _validate_system_resources(self) -> bool:
        """验证系统资源"""
        import psutil

        # 检查内存
        memory = psutil.virtual_memory()
        if memory.total < 2 * 1024 * 1024 * 1024:  # 2GB
            self.add_warning("系统内存少于2GB，可能影响性能")

        # 检查磁盘空间
        disk = psutil.disk_usage('/')
        if disk.free < 1 * 1024 * 1024 * 1024:  # 1GB
            self.add_warning("磁盘可用空间少于1GB")

        return True


class ConfigFileValidator:
    """配置文件验证器"""

    @staticmethod
    def validate_json_config(file_path: str, schema: Optional[Dict] = None) -> Tuple[bool, Dict[str, Any]]:
        """
        验证JSON配置文件

        Args:
            file_path: 配置文件路径
            schema: 可选的配置模式

        Returns:
            (是否有效, 配置数据)
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            if schema:
                # 这里可以集成jsonschema库进行更详细的验证
                missing_keys = set(schema.keys()) - set(config.keys())
                if missing_keys:
                    logger.error(f"配置文件缺少必需的键: {missing_keys}")
                    return False, {}

            logger.info(f"配置文件验证成功: {file_path}")
            return True, config

        except FileNotFoundError:
            logger.error(f"配置文件不存在: {file_path}")
            return False, {}
        except json.JSONDecodeError as e:
            logger.error(f"配置文件JSON格式错误: {e}")
            return False, {}
        except Exception as e:
            logger.error(f"配置文件验证失败: {e}")
            return False, {}

    @staticmethod
    def validate_env_file(file_path: str) -> bool:
        """
        验证.env文件格式

        Args:
            file_path: .env文件路径

        Returns:
            验证是否通过
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line_num, line in enumerate(lines, 1):
                line = line.strip()

                # 跳过空行和注释
                if not line or line.startswith('#'):
                    continue

                # 检查格式
                if '=' not in line:
                    logger.warning(f".env文件第{line_num}行格式错误: {line}")
                    continue

                key, value = line.split('=', 1)
                key = key.strip()

                # 检查键名格式
                if not key.isupper() or not key.replace('_', '').isalnum():
                    logger.warning(f".env文件第{line_num}行键名不规范: {key}")

            logger.info(f".env文件验证完成: {file_path}")
            return True

        except FileNotFoundError:
            logger.warning(f".env文件不存在: {file_path}")
            return True  # .env文件是可选的
        except Exception as e:
            logger.error(f".env文件验证失败: {e}")
            return False


def validate_complete_config(provider: str = "azure") -> Dict[str, Any]:
    """
    完整的配置验证函数

    Args:
        provider: LLM提供商

    Returns:
        验证结果摘要
    """
    # LLM配置验证
    llm_validator = LLMConfigValidator()
    llm_valid = llm_validator.validate_provider(provider)

    # 路径配置验证
    from ..config.settings import (
        JSON_DATA_PATH, OUTPUT_PATH, VECTOR_DB_PATH,
        PDF_IMAGE_PATH, MEMORY_PATH, SESSION_PATH
    )

    paths = {
        "JSON_DATA_PATH": JSON_DATA_PATH,
        "OUTPUT_PATH": OUTPUT_PATH,
        "VECTOR_DB_PATH": VECTOR_DB_PATH,
        "PDF_IMAGE_PATH": PDF_IMAGE_PATH,
        "MEMORY_PATH": MEMORY_PATH,
        "SESSION_PATH": SESSION_PATH
    }

    path_validator = PathConfigValidator()
    path_valid = path_validator.validate_data_paths(paths)

    # 系统要求验证
    system_validator = SystemConfigValidator()
    system_valid = system_validator.validate_system_requirements()

    # 合并结果
    all_errors = (llm_validator.validation_errors +
                 path_validator.validation_errors +
                 system_validator.validation_errors)

    all_warnings = (llm_validator.warnings +
                   path_validator.warnings +
                   system_validator.warnings)

    overall_valid = llm_valid and path_valid and system_valid

    summary = {
        "overall_valid": overall_valid,
        "llm_config_valid": llm_valid,
        "path_config_valid": path_valid,
        "system_requirements_valid": system_valid,
        "total_errors": len(all_errors),
        "total_warnings": len(all_warnings),
        "errors": all_errors,
        "warnings": all_warnings
    }

    # 记录验证结果
    if overall_valid:
        logger.info("所有配置验证通过")
    else:
        logger.error(f"配置验证失败，共 {len(all_errors)} 个错误")

    if all_warnings:
        logger.warning(f"配置验证完成，共 {len(all_warnings)} 个警告")

    return summary


# 导出验证函数供其他模块使用
__all__ = [
    'ConfigValidator',
    'LLMConfigValidator',
    'PathConfigValidator',
    'SystemConfigValidator',
    'ConfigFileValidator',
    'validate_complete_config'
]