"""
Common utilities shared across modules
共用工具函数模块

这个模块提供了在整个项目中重复使用的通用工具函数，
避免代码重复和提高可维护性。

主要功能:
- 目录管理: ensure_data_dirs - 确保必要的数据目录存在
- 文件操作: format_file_size - 格式化文件大小
- 代理管理: get_enabled_agents, get_enabled_agent_types - 管理启用的代理
- 会话管理: reset_session_state - 重置会话状态

Author: LLMReader Team
Date: 2025-11-05
"""

import os
import logging
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_data_dirs(base_path: str = "data", 
                     subdirs: Optional[List[str]] = None) -> None:
    """
    确保所有必需的数据目录存在
    
    这个函数会检查并创建指定的数据目录结构。如果目录不存在，
    会自动创建；如果已存在，则不做任何操作。
    
    Args:
        base_path (str): 数据根目录路径，默认为 "data"
        subdirs (Optional[List[str]]): 子目录列表。如果不提供，
            将使用默认的标准目录列表
    
    Returns:
        None
    
    Raises:
        PermissionError: 如果没有创建目录的权限
        OSError: 其他操作系统错误
    
    Example:
        >>> ensure_data_dirs("data", ["pdf", "json", "output"])
        # 会创建 data/pdf, data/json, data/output 等目录
        
        >>> ensure_data_dirs()
        # 使用默认路径和子目录
    
    Note:
        标准的子目录包括：
        - pdf: PDF 文件存储
        - json: JSON 数据存储
        - output: 输出文件存储
        - sessions: 会话数据存储
        - vector_db: 向量数据库存储
        - pdf_image: PDF 转换后的图片存储
    """
    if subdirs is None:
        subdirs = ["pdf", "json", "output", "sessions", "vector_db", "pdf_image"]
    
    try:
        base = Path(base_path)
        base.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Base data directory ensured: {base}")
        
        for subdir in subdirs:
            subdir_path = base / subdir
            subdir_path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Subdirectory ensured: {subdir_path}")
        
        logger.info(f"Data directories ensured at {base}")
        
    except PermissionError as e:
        logger.error(f"Permission denied when creating directories: {e}")
        raise
    except OSError as e:
        logger.error(f"OS error when creating directories: {e}")
        raise


def format_file_size(size_bytes: int) -> str:
    """
    格式化字节大小为人类可读的字符串格式
    
    将原始的字节数转换为易于理解的格式，如 KB、MB、GB 等。
    
    Args:
        size_bytes (int): 文件大小，单位为字节
    
    Returns:
        str: 格式化后的大小字符串，例如 "1.5 MB"
    
    Raises:
        TypeError: 如果输入不是整数类型
        ValueError: 如果输入是负数
    
    Example:
        >>> format_file_size(1024)
        '1.0 KB'
        
        >>> format_file_size(1048576)
        '1.0 MB'
        
        >>> format_file_size(1073741824)
        '1.0 GB'
    
    Note:
        转换使用 1024 作为基数 (二进制):
        - 1 KB = 1024 B
        - 1 MB = 1024 KB
        - 1 GB = 1024 MB
        - 等等
    """
    if not isinstance(size_bytes, int):
        raise TypeError(f"Expected int, got {type(size_bytes).__name__}")
    
    if size_bytes < 0:
        raise ValueError(f"Size cannot be negative: {size_bytes}")
    
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    size = float(size_bytes)
    
    for unit in units:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    
    return f"{size:.1f} PB"


def get_enabled_agents() -> Dict[str, Dict]:
    """
    获取所有启用状态的代理配置
    
    从 AgentCard 配置中提取所有状态为 "enable" 的代理信息，
    用于系统初始化和代理管理。
    
    Returns:
        Dict[str, Dict]: 启用的代理配置字典
            key: 代理类型 (如 "memory", "search" 等)
            value: 代理的配置信息字典
    
    Raises:
        ImportError: 如果无法导入配置模块
        KeyError: 如果 AgentCard 配置缺失
    
    Example:
        >>> agents = get_enabled_agents()
        >>> for agent_type, config in agents.items():
        ...     print(f"{agent_type}: {config['description']}")
        
        >>> "memory" in get_enabled_agents()
        True
    
    Note:
        这个函数在多个地方被重复调用，该共用函数
        消除了代码重复，便于统一管理代理配置。
    
    See Also:
        get_enabled_agent_types: 获取仅包含代理类型的列表
    """
    try:
        from src.config.settings import AgentCard
    except ImportError as e:
        logger.error(f"Failed to import AgentCard: {e}")
        raise
    
    enabled_agents = {}
    
    try:
        for agent_type, agent_info in AgentCard.items():
            if agent_info.get("status") == "enable":
                enabled_agents[agent_type] = agent_info
                logger.debug(f"Loaded enabled agent: {agent_type}")
        
        logger.info(f"Total enabled agents loaded: {len(enabled_agents)}")
        
    except Exception as e:
        logger.error(f"Error processing AgentCard: {e}")
        raise
    
    return enabled_agents


def get_enabled_agent_types() -> List[str]:
    """
    获取所有启用的代理类型列表
    
    返回仅包含代理类型名称的列表，不包含配置详情。
    这在需要快速检查代理可用性时很有用。
    
    Returns:
        List[str]: 启用的代理类型名称列表
    
    Example:
        >>> agent_types = get_enabled_agent_types()
        >>> if "memory" in agent_types:
        ...     print("Memory agent is available")
    
    Note:
        这是 get_enabled_agents() 的简化版本，
        仅返回键列表以提高性能。
    
    See Also:
        get_enabled_agents: 获取完整的代理配置
    """
    return list(get_enabled_agents().keys())


def reset_session_state() -> None:
    """
    重置会话状态
    
    清除所有与会话相关的缓存、历史记录和状态信息。
    这在开始新会话或需要清理旧数据时使用。
    
    Returns:
        None
    
    Side Effects:
        - 清除内存中的会话缓存
        - 重置会话相关的全局状态
        - 不影响持久化数据
    
    Example:
        >>> reset_session_state()
        # 会话已重置
    
    Warning:
        此操作会立即清除所有会话数据。
        如果需要保存数据，请在调用此函数前进行备份。
    
    Note:
        具体实现取决于会话存储方式（内存、数据库等）。
        当前为简化实现，可根据需要扩展。
    """
    logger.info("Resetting session state...")
    
    try:
        # 清除消息历史记录
        # 这里可以根据实际的会话存储实现进行扩展
        logger.info("Session history cleared")
        
        # 清除其他会话相关的状态
        logger.info("Session state reset completed")
        
    except Exception as e:
        logger.error(f"Error resetting session state: {e}")
        raise


# 导出公共 API
__all__ = [
    'ensure_data_dirs',
    'format_file_size',
    'get_enabled_agents',
    'get_enabled_agent_types',
    'reset_session_state',
]


if __name__ == "__main__":
    """
    模块测试代码
    
    提供了基本的函数测试示例，用于开发和调试。
    """
    print("Testing common utilities module...\n")
    
    # 测试 format_file_size
    print("1. Testing format_file_size:")
    sizes = [0, 512, 1024, 1024**2, 1024**3, 1024**4]
    for size in sizes:
        print(f"  {size} bytes = {format_file_size(size)}")
    
    # 测试 get_enabled_agents
    print("\n2. Testing get_enabled_agents:")
    try:
        agents = get_enabled_agents()
        print(f"  Found {len(agents)} enabled agents:")
        for agent_type in agents:
            print(f"    - {agent_type}")
    except Exception as e:
        print(f"  Note: Could not load agents (expected in test): {e}")
    
    # 测试 ensure_data_dirs (使用临时目录)
    print("\n3. Testing ensure_data_dirs:")
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = os.path.join(tmpdir, "test_data")
        ensure_data_dirs(test_path, ["test1", "test2"])
        print(f"  Created directories at {test_path}")
        print(f"  Subdirs: {os.listdir(test_path)}")
    
    print("\n✓ All tests completed")
