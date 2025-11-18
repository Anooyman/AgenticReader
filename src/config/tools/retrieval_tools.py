"""
Retrieval Tools Configuration

This module defines all available retrieval tools for the RetrievalAgent.
Each tool is configured with its name, description, parameters, and method name.

Adding new tools:
1. Add a new entry to RETRIEVAL_TOOLS_CONFIG
2. Implement the corresponding method in RetrievalAgent class
3. The tool will be automatically available in the ReAct framework
"""

from typing import Dict, Any, List

# 工具配置字典
RETRIEVAL_TOOLS_CONFIG: List[Dict[str, Any]] = [
    {
        "name": "retrieval_data_by_context",
        "method_name": "retrieval_data_by_context",  # RetrievalAgent 中的方法名
        "description": "基于上下文的语义检索工具。通过向量相似度搜索在文档中查找与查询语义相关的内容段落。适用于查找与特定概念、主题相关的内容。",
        "parameters": {
            "query": "要搜索的查询字符串，应该包含要查找的主题或关键信息"
        },
        "enabled": True,  # 是否启用此工具
        "priority": 1,  # 优先级（数字越小优先级越高）
    },
    {
        "name": "retrieval_data_by_title",
        "method_name": "retrieval_data_by_title",
        "description": "基于标题的精确检索工具。首先使用LLM从用户查询中智能提取相关的章节标题关键词，然后在向量数据库中精确匹配这些标题来检索对应的文档内容。适用于查找特定章节或已知标题的内容。",
        "parameters": {
            "query": "包含章节标题信息的查询字符串"
        },
        "enabled": True,
        "priority": 2,
    },
    {
        "name": "get_document_structure",
        "method_name": "get_document_structure",
        "description": "获取文档的目录结构工具。返回当前PDF文档的完整目录（章节）结构，包括所有章节标题和对应的页码信息。适用于用户想要了解文档整体结构、查看有哪些章节、或者需要确定某个主题在文档中的位置时使用。",
        "parameters": {
            "query": "查询参数（此工具不需要具体查询内容，任何输入都会返回完整的文档目录结构）"
        },
        "enabled": True,
        "priority": 3,
    },

    # ==================== 示例：如何添加新工具 ====================
    # {
    #     "name": "retrieval_by_keyword",
    #     "method_name": "retrieval_by_keyword",
    #     "description": "基于关键词的精确匹配检索。在文档中搜索包含特定关键词的段落。",
    #     "parameters": {
    #         "keywords": "要搜索的关键词列表",
    #         "match_mode": "匹配模式：'exact'（精确匹配）或 'partial'（部分匹配）"
    #     },
    #     "enabled": False,  # 暂时禁用
    #     "priority": 4,
    # },
    #
    # {
    #     "name": "retrieval_by_page_range",
    #     "method_name": "retrieval_by_page_range",
    #     "description": "基于页码范围的检索。检索指定页码范围内的所有内容。",
    #     "parameters": {
    #         "start_page": "起始页码",
    #         "end_page": "结束页码"
    #     },
    #     "enabled": False,
    #     "priority": 5,
    # },
]


def get_enabled_tools() -> List[Dict[str, Any]]:
    """
    获取所有启用的工具配置

    Returns:
        List[Dict[str, Any]]: 启用的工具配置列表，按优先级排序
    """
    enabled = [tool for tool in RETRIEVAL_TOOLS_CONFIG if tool.get("enabled", True)]
    # 按优先级排序
    enabled.sort(key=lambda x: x.get("priority", 999))
    return enabled


def get_tool_by_name(tool_name: str) -> Dict[str, Any]:
    """
    根据工具名称获取工具配置

    Args:
        tool_name (str): 工具名称

    Returns:
        Dict[str, Any]: 工具配置，如果未找到则返回 None
    """
    for tool in RETRIEVAL_TOOLS_CONFIG:
        if tool["name"] == tool_name:
            return tool
    return None


def format_tool_description(tool: Dict[str, Any]) -> str:
    """
    格式化单个工具的描述文本

    Args:
        tool (Dict[str, Any]): 工具配置

    Returns:
        str: 格式化后的工具描述
    """
    params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
    tool_desc = f"""
工具名称: {tool['name']}
功能描述: {tool['description']}
参数: {params_desc}
"""
    return tool_desc.strip()


def format_all_tools_for_llm() -> str:
    """
    将所有启用的工具格式化为 LLM 可理解的文本描述

    Returns:
        str: 格式化后的所有工具描述文本
    """
    enabled_tools = get_enabled_tools()
    tool_descriptions = [format_tool_description(tool) for tool in enabled_tools]
    return "\n\n".join(tool_descriptions)


# ==================== 工具元数据 ====================

TOOL_METADATA = {
    "version": "1.0.0",
    "last_updated": "2025-01-17",
    "total_tools": len(RETRIEVAL_TOOLS_CONFIG),
    "enabled_tools": len(get_enabled_tools()),
}


if __name__ == "__main__":
    """测试工具配置"""
    print("=" * 60)
    print("检索工具配置测试")
    print("=" * 60)

    print(f"\n工具元数据:")
    for key, value in TOOL_METADATA.items():
        print(f"  {key}: {value}")

    print(f"\n启用的工具列表:")
    for i, tool in enumerate(get_enabled_tools(), 1):
        print(f"  [{i}] {tool['name']} (优先级: {tool['priority']})")

    print(f"\n格式化的工具描述:")
    print(format_all_tools_for_llm())

    print(f"\n测试获取特定工具:")
    tool = get_tool_by_name("retrieval_data_by_context")
    if tool:
        print(f"  找到工具: {tool['name']}")
        print(f"  方法名: {tool['method_name']}")
    else:
        print("  未找到工具")
