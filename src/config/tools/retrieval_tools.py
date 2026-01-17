"""
Retrieval Tools Configuration

定义 RetrievalAgent 可用的所有工具
每个工具直接绑定到 RetrievalAgent 的方法

添加新工具的步骤：
1. 在 RETRIEVAL_TOOLS_CONFIG 中添加工具配置
2. 在 RetrievalAgent 类中实现对应的方法
3. 工具会自动加载，无需修改其他代码
"""

from typing import Dict, Any, List

# 工具配置列表
RETRIEVAL_TOOLS_CONFIG: List[Dict[str, Any]] = [
    {
        "name": "search_by_context",
        "method_name": "search_by_context",
        "description": "基于上下文的语义检索工具。通过向量相似度搜索在文档中查找与查询语义相关的内容段落。适用于查找与特定概念、主题相关的内容。",
        "parameters": {
            "query": "要搜索的查询字符串，应该包含要查找的主题或关键信息"
        },
        "enabled": True,
        "priority": 1,
        "requires_summary": True,  # 返回内容需要总结
    },
    {
        "name": "extract_titles_from_structure",
        "method_name": "extract_titles_from_structure",
        "description": "从文档结构中智能提取标题列表。根据用户查询，从文档目录中提取相关的章节标题。适用于需要根据用户意图匹配章节标题的场景。",
        "parameters": {
            "query": "用户查询字符串，描述要查找的章节主题"
        },
        "enabled": True,
        "priority": 2,
        "requires_summary": False,  # 仅返回标题列表，不需要总结
    },
    {
        "name": "search_by_title",
        "method_name": "search_by_title",
        "description": "基于标题列表的精确检索工具。根据给定的标题列表，在向量数据库中精确匹配这些标题并检索对应内容。需要先使用 extract_titles_from_structure 获取标题列表。",
        "parameters": {
            "title_list": "章节标题列表，JSON格式的字符串数组，例如: [\"第一章\", \"第二章\"]"
        },
        "enabled": True,
        "priority": 3,
        "requires_summary": True,  # 返回内容需要总结
    },
    {
        "name": "get_document_structure",
        "method_name": "get_document_structure",
        "description": "获取文档的目录结构工具。返回文档的完整章节结构，包括所有章节标题和页码信息。适用于用户想要了解文档整体结构。",
        "parameters": {
            "query": "查询参数（此工具不需要具体查询内容）"
        },
        "enabled": True,
        "priority": 4,
        "requires_summary": False,  # 返回结构信息，不需要总结
    },
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
    tool = get_tool_by_name("search_by_context")
    if tool:
        print(f"  找到工具: {tool['name']}")
        print(f"  方法名: {tool['method_name']}")
        print(f"  优先级: {tool['priority']}")
    else:
        print("  未找到工具")

    print("\n" + "=" * 60)
