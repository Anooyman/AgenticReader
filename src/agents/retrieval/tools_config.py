"""
RetrievalAgent Tools Configuration

定义 RetrievalAgent 可用的所有工具配置。
每个工具直接绑定到 RetrievalAgent 的工具方法（tools.py）。

添加新工具的步骤：
1. 在 RETRIEVAL_TOOLS_CONFIG 中添加工具配置
2. 在 src/agents/retrieval/tools.py 中实现对应的方法
3. 工具会自动加载，无需修改其他代码
"""

from typing import Dict, Any, List

# 工具配置列表
RETRIEVAL_TOOLS_CONFIG: List[Dict[str, Any]] = [
    {
        "name": "search_by_context",
        "method_name": "search_by_context",
        "description": """基于上下文的语义检索工具。通过向量相似度搜索在文档中查找与查询语义相关的内容段落。

**使用场景**:
- 查找特定概念、主题、原理的相关内容
- 回答"什么是XX"、"如何做XX"、"为什么XX"等问题
- 需要语义匹配而非精确章节匹配的查询

**适用查询类型**:
- 概念性查询: "注意力机制的原理"
- 方法性查询: "如何训练模型"
- 主题性查询: "文档中关于XX的内容"

**使用时机**:
- 首次检索: 当查询是概念性、主题性的，且不涉及特定章节时
- 后续检索: 如果之前已使用此工具，可继续使用（调整查询参数以检索不同角度）
""",
        "parameters": {
            "query": "要搜索的查询字符串，应该包含要查找的主题或关键信息"
        },
        "enabled": True,
        "priority": 1,
        "requires_summary": True,
    },
    {
        "name": "extract_titles_from_structure",
        "method_name": "extract_titles_from_structure",
        "description": """从文档结构中智能提取标题列表。根据用户查询，从文档目录中提取最相关的章节标题。

**核心功能**:
- 自动获取文档结构（内部调用，无需先执行 get_document_structure）
- 使用 LLM 智能分析用户查询意图
- 返回与查询最相关的章节标题列表（通常 2-5 个章节）

**使用场景**:
- 需要基于章节结构进行系统性检索的查询
- 文档总结类查询（需要覆盖多个核心章节）
- 需要找到与查询相关的所有章节标题
- 用户查询涉及多个主题或需要综合多个章节的内容

**适用查询类型**:
- 综合性查询: "总结文档主要内容"、"文档讲了什么"
- 多主题查询: "介绍XX和YY的区别"
- 需要多章节支持的查询: "从理论到实践的完整过程"

**前置条件**:
- **无硬性前置条件**: 此工具会自动获取文档结构
- **可选**: 如果已执行 get_document_structure，其结果可用于参考，但不是必需的

**后续步骤**:
- 此工具会返回章节标题列表
- **必须**: 下一步应使用 search_by_title，传入提取的标题列表来检索具体内容
- **不要**: 提取标题后又切换到 search_by_context（会破坏结构化检索的一致性）

**典型工作流（推荐）**:
1. extract_titles_from_structure（智能提取相关标题）← 当前工具
2. search_by_title（检索这些章节的具体内容）

**可选工作流**（如果用户明确询问结构）:
1. get_document_structure（展示完整目录给用户）
2. extract_titles_from_structure（基于查询提取相关标题）
3. search_by_title（检索内容）

**注意事项**:
- 返回的是**标题列表**（结构化数据），不包含实际内容
- 智能匹配：根据查询选择最相关的章节，通常不会返回所有章节
- 后续必须使用 search_by_title 来获取实际内容""",
        "parameters": {
            "query": "用户查询字符串，描述查询意图和需要查找的主题"
        },
        "enabled": True,
        "priority": 2,
        "requires_summary": False,
    },
    {
        "name": "search_by_title",
        "method_name": "search_by_title",
        "description": """基于标题列表的精确检索工具。根据给定的标题列表，在向量数据库中精确匹配这些标题并检索对应内容。

**使用场景**:
- 已知章节标题，需要检索对应内容
- 完成 extract_titles_from_structure 后的下一步
- 需要系统性地检索多个章节的内容

**前置条件**:
- **必须**: 已执行 extract_titles_from_structure 获取标题列表
- 或者手动指定已知的章节标题

**参数格式**:
- title_list: JSON格式的字符串数组，如 ["第一章 引言", "第三章 方法论"]
- 标题必须与文档中的实际章节标题匹配

**典型工作流**:
1. get_document_structure（可选，了解整体结构）
2. extract_titles_from_structure（提取标题列表）
3. search_by_title（使用提取的标题检索内容）← 当前工具

**后续步骤**:
- 如果内容不够，可以继续使用 search_by_title 检索其他章节
- **不要**: 检索部分章节后切换到 search_by_context（策略不一致）""",
        "parameters": {
            "title_list": "章节标题列表，JSON格式的字符串数组，例如: [\"第一章\", \"第二章\"]"
        },
        "enabled": True,
        "priority": 3,
        "requires_summary": True,
    },
    {
        "name": "get_document_structure",
        "method_name": "get_document_structure",
        "description": """获取文档的目录结构工具。返回文档的完整章节结构，包括所有章节标题和页码信息。

**核心功能**:
- 展示文档的完整章节目录
- 返回所有章节标题和对应页码
- 帮助用户了解文档的整体组织结构

**使用场景**:
- 用户**明确询问**文档结构、目录、章节组织
- 用户想要知道"文档有哪些部分"、"有哪些章节"
- 需要向用户展示文档的完整框架

**适用查询**:
- "这个文档有哪些章节？"
- "文档的目录是什么？"
- "文档结构如何组织？"
- "给我看看文档的大纲"

**不适用场景**:
- **不应作为其他工具的前置步骤**：extract_titles_from_structure 会自动获取结构，无需先调用此工具
- 用户并未明确询问结构时，直接使用其他检索工具即可

**后续步骤**:
- **如果用户只是想了解结构**：执行此工具后即可结束，向用户展示目录
- **如果需要进一步检索内容**：
  1. 使用 extract_titles_from_structure 提取相关标题（它会自动获取结构）
  2. 使用 search_by_title 检索具体内容
- **不要**: 获取结构后直接切换到 search_by_context（会破坏结构化检索的一致性）

**工作流建议**:

**场景A - 用户明确询问结构**:
1. get_document_structure（展示完整目录）← 当前工具
2. 结束（如果用户只是想知道结构）

**场景B - 用户询问结构后要求总结**:
1. get_document_structure（展示完整目录）
2. extract_titles_from_structure（提取相关标题）
3. search_by_title（检索内容）

**场景C - 用户直接要求总结（未询问结构）**:
1. extract_titles_from_structure（直接提取标题，无需先获取结构）
2. search_by_title（检索内容）

**注意事项**:
- 此工具返回的是**结构信息**（标题+页码），不包含具体内容
- 返回完整目录，不筛选章节
- 是否执行此工具取决于用户是否明确询问结构""",
        "parameters": {
            "query": "查询参数（此工具不需要具体查询内容，保留用于接口兼容）"
        },
        "enabled": True,
        "priority": 4,
        "requires_summary": False,
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
    "last_updated": "2025-01-19",
    "total_tools": len(RETRIEVAL_TOOLS_CONFIG),
    "enabled_tools": len(get_enabled_tools()),
}


if __name__ == "__main__":
    """测试工具配置"""
    print("=" * 60)
    print("RetrievalAgent 工具配置测试")
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
