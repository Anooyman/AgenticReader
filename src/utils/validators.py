"""
输入验证工具

提供统一的输入验证功能，确保数据安全和正确性
"""
import os
import re
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from .exceptions import ValidationError
from ..config.constants import SecurityConstants


def validate_file_path(file_path: str, check_exists: bool = True, is_directory: bool = False) -> str:
    """
    验证文件路径的有效性和安全性

    Args:
        file_path (str): 要验证的文件路径
        check_exists (bool): 是否检查文件存在性
        is_directory (bool): 是否为目录路径（如果为True，跳过扩展名检查）

    Returns:
        str: 标准化后的文件路径

    Raises:
        ValidationError: 文件路径无效或不安全
    """
    if not file_path or not isinstance(file_path, str):
        raise ValidationError("文件路径不能为空")

    # 转换为Path对象进行标准化
    try:
        path = Path(file_path).resolve()
        # 特殊处理：如果路径中包含数字和点，但不是文件扩展名的情况
        # 例如: data/pdf_image/1706.03762v7 这样的目录路径
        if not check_exists and not path.suffix and '.' in path.name:
            # 这可能是一个包含版本号的目录名，不是文件扩展名
            pass
    except (OSError, ValueError) as e:
        raise ValidationError(f"文件路径格式无效: {e}")

    # 检查路径遍历攻击
    if ".." in str(path):
        raise ValidationError("检测到路径遍历攻击尝试")

    # 检查文件大小限制
    if check_exists and path.exists():
        if path.is_file():
            file_size_mb = path.stat().st_size / (1024 * 1024)
            if file_size_mb > SecurityConstants.MAX_FILE_SIZE_MB:
                raise ValidationError(f"文件大小超过限制 ({file_size_mb:.2f}MB > {SecurityConstants.MAX_FILE_SIZE_MB}MB)")
        elif not path.is_dir():
            raise ValidationError("路径既不是文件也不是目录")

    # 检查文件扩展名 - 只对明确的文件进行扩展名检查
    if not is_directory and path.suffix:
        # 检查文件是否存在且确实是文件
        if check_exists and path.exists():
            if path.is_file():
                # 对于存在的文件，检查扩展名
                if path.suffix.lower() not in SecurityConstants.ALLOWED_EXTENSIONS:
                    raise ValidationError(f"不支持的文件类型: {path.suffix}")
            elif path.is_dir():
                # 如果是目录，不检查扩展名
                pass
        elif not check_exists:
            # 对于不存在的路径，只有在明确不是目录时才检查扩展名
            # 如果扩展名看起来像版本号（包含数字），则跳过检查
            suffix = path.suffix.lower()
            if suffix and not re.match(r'^\.\d+[\w\d]*', suffix):
                # 只检查非数字开头的扩展名
                if suffix not in SecurityConstants.ALLOWED_EXTENSIONS:
                    raise ValidationError(f"不支持的文件类型: {suffix}")

    return str(path)


def validate_url(url: str) -> str:
    """
    验证URL的有效性和安全性

    Args:
        url (str): 要验证的URL

    Returns:
        str: 验证后的URL

    Raises:
        ValidationError: URL无效或不安全
    """
    if not url or not isinstance(url, str):
        raise ValidationError("URL不能为空")

    if len(url) > SecurityConstants.MAX_URL_LENGTH:
        raise ValidationError(f"URL长度超过限制 ({len(url)} > {SecurityConstants.MAX_URL_LENGTH})")

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValidationError(f"URL格式无效: {e}")

    if not parsed.scheme or not parsed.netloc:
        raise ValidationError("URL格式不完整，缺少协议或域名")

    if parsed.scheme not in ['http', 'https']:
        raise ValidationError(f"不支持的协议: {parsed.scheme}")

    return url


def validate_json_data(data: str) -> Dict[str, Any]:
    """
    验证和解析JSON数据

    Args:
        data (str): JSON字符串

    Returns:
        Dict[str, Any]: 解析后的数据

    Raises:
        ValidationError: JSON数据无效
    """
    if not data or not isinstance(data, str):
        raise ValidationError("JSON数据不能为空")

    if len(data) > SecurityConstants.MAX_INPUT_LENGTH:
        raise ValidationError(f"JSON数据长度超过限制 ({len(data)} > {SecurityConstants.MAX_INPUT_LENGTH})")

    try:
        parsed_data = json.loads(data)
    except json.JSONDecodeError as e:
        raise ValidationError(f"JSON格式无效: {e}")

    return parsed_data


def validate_text_input(text: str, max_length: Optional[int] = None) -> str:
    """
    验证文本输入

    Args:
        text (str): 要验证的文本
        max_length (Optional[int]): 最大长度限制

    Returns:
        str: 验证后的文本

    Raises:
        ValidationError: 文本输入无效
    """
    if not isinstance(text, str):
        raise ValidationError("输入必须是字符串类型")

    max_len = max_length or SecurityConstants.MAX_INPUT_LENGTH
    if len(text) > max_len:
        raise ValidationError(f"文本长度超过限制 ({len(text)} > {max_len})")

    # 检查是否包含潜在的危险字符
    dangerous_patterns = [
        r'<script[^>]*>.*?</script>',  # 脚本标签
        r'javascript:',                # JavaScript协议
        r'vbscript:',                 # VBScript协议
        r'on\w+\s*=',                 # 事件处理器
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            raise ValidationError("检测到潜在的危险内容")

    return text.strip()


def validate_email(email: str) -> str:
    """
    验证邮箱格式

    Args:
        email (str): 邮箱地址

    Returns:
        str: 验证后的邮箱

    Raises:
        ValidationError: 邮箱格式无效
    """
    if not email or not isinstance(email, str):
        raise ValidationError("邮箱地址不能为空")

    email = email.strip().lower()
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    if not re.match(email_pattern, email):
        raise ValidationError("邮箱格式无效")

    return email


def validate_config_dict(config: Dict[str, Any], required_keys: List[str]) -> Dict[str, Any]:
    """
    验证配置字典

    Args:
        config (Dict[str, Any]): 配置字典
        required_keys (List[str]): 必需的键列表

    Returns:
        Dict[str, Any]: 验证后的配置

    Raises:
        ValidationError: 配置无效
    """
    if not isinstance(config, dict):
        raise ValidationError("配置必须是字典类型")

    missing_keys = [key for key in required_keys if key not in config]
    if missing_keys:
        raise ValidationError(f"缺少必需的配置项: {missing_keys}")

    # 检查值是否为空
    empty_keys = [key for key in required_keys if not config.get(key)]
    if empty_keys:
        raise ValidationError(f"以下配置项不能为空: {empty_keys}")

    return config


def sanitize_filename(filename: str) -> str:
    """
    清理和标准化文件名

    Args:
        filename (str): 原始文件名

    Returns:
        str: 清理后的文件名

    Raises:
        ValidationError: 文件名无效
    """
    if not filename or not isinstance(filename, str):
        raise ValidationError("文件名不能为空")

    # 移除危险字符
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

    # 移除控制字符
    filename = ''.join(char for char in filename if ord(char) >= 32)

    # 限制长度
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        max_name_len = 255 - len(ext)
        filename = name[:max_name_len] + ext

    # 移除前导和尾随空格/点
    filename = filename.strip('. ')

    if not filename:
        raise ValidationError("清理后的文件名为空")

    return filename


def validate_pagination(page: int, page_size: int, max_page_size: int = 100) -> tuple[int, int]:
    """
    验证分页参数

    Args:
        page (int): 页码
        page_size (int): 每页大小
        max_page_size (int): 最大每页大小

    Returns:
        tuple[int, int]: 验证后的页码和每页大小

    Raises:
        ValidationError: 分页参数无效
    """
    if not isinstance(page, int) or page < 1:
        raise ValidationError("页码必须是大于0的整数")

    if not isinstance(page_size, int) or page_size < 1:
        raise ValidationError("每页大小必须是大于0的整数")

    if page_size > max_page_size:
        raise ValidationError(f"每页大小不能超过 {max_page_size}")

    return page, page_size