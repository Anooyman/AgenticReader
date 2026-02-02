"""
RetrievalAgent 工具返回格式规范

所有检索工具必须返回统一的标准格式，以便 summary 节点统一处理。
"""

from typing import TypedDict, List, Dict, Any, Literal


class ToolResponse(TypedDict, total=False):
    """
    工具返回的统一格式

    所有 RetrievalAgent 的工具都应该返回这个格式
    """
    type: Literal["content", "metadata", "structure"]  # 返回数据类型
    tool: str  # 工具名称
    items: List[Any]  # 数据项列表
    metadata: Dict[str, Any]  # 可选的元数据（如 reason 等）


# ==================== 类型说明 ====================

# type="content": 内容检索工具（返回文档内容）
# items 格式: List[Dict]，每个 Dict 包含：
# {
#     "content": str,      # 内容文本
#     "title": str,        # 章节标题
#     "pages": List[int],  # 页码列表
#     "raw_data": Dict     # 原始数据
# }
#
# 示例：
# {
#     "type": "content",
#     "tool": "search_by_context",
#     "items": [
#         {
#             "content": "这是第2章的内容...",
#             "title": "第2章 Architecture",
#             "pages": [12, 13, 14],
#             "raw_data": {...}
#         },
#         ...
#     ]
# }


# type="metadata": 元数据提取工具（返回标题、结构等元信息）
# items 格式: List[str]，章节标题列表
# metadata 格式: {"reason": str, ...}，可选的附加信息
#
# 示例：
# {
#     "type": "metadata",
#     "tool": "extract_titles_from_structure",
#     "items": ["第1章 引言", "第2章 背景", "第5章 实验"],
#     "metadata": {"reason": "这些章节与查询最相关"}
# }


# type="structure": 文档结构工具（返回完整的文档结构）
# items 格式: List[str]，所有章节标题列表
#
# 示例：
# {
#     "type": "structure",
#     "tool": "get_document_structure",
#     "items": ["第1章 引言", "第2章 背景", "第3章 方法", ...]
# }


def create_content_response(
    tool_name: str,
    content_items: List[Dict[str, Any]]
) -> ToolResponse:
    """
    创建内容类型的响应

    Args:
        tool_name: 工具名称
        content_items: 内容项列表，每项包含 content, title, pages, raw_data

    Returns:
        标准格式的工具响应
    """
    return {
        "type": "content",
        "tool": tool_name,
        "items": content_items
    }


def create_metadata_response(
    tool_name: str,
    items: List[str],
    metadata: Dict[str, Any] = None
) -> ToolResponse:
    """
    创建元数据类型的响应

    Args:
        tool_name: 工具名称
        items: 项目列表（如章节标题列表）
        metadata: 可选的元数据（如 reason 等）

    Returns:
        标准格式的工具响应
    """
    response: ToolResponse = {
        "type": "metadata",
        "tool": tool_name,
        "items": items
    }
    if metadata:
        response["metadata"] = metadata
    return response


def create_structure_response(
    tool_name: str,
    structure_items: List[str]
) -> ToolResponse:
    """
    创建文档结构类型的响应

    Args:
        tool_name: 工具名称
        structure_items: 结构项列表（章节标题列表）

    Returns:
        标准格式的工具响应
    """
    return {
        "type": "structure",
        "tool": tool_name,
        "items": structure_items
    }
