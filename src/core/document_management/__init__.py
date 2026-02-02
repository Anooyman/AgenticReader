"""
Document Management Module

文档管理核心模块，提供文档的索引、查询、删除等完整生命周期管理。

主要组件：
- DocumentRegistry: 文档注册表，管理所有已索引文档的元数据
- indexer: 文档索引相关函数
- manager: 文档管理相关函数

使用示例：
    from src.core.document_management import DocumentRegistry

    # 创建注册表
    registry = DocumentRegistry()

    # 列出所有文档
    docs = registry.list_all()

    # 获取文档信息
    doc_info = registry.get_by_name("document_name")
"""

from .registry import DocumentRegistry

# 导出主要类和函数
__all__ = [
    'DocumentRegistry',
]

# 模块元数据
__version__ = '1.0.0'
__author__ = 'AgenticReader Team'
