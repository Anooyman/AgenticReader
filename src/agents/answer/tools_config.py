"""
AnswerAgent Tools Configuration

定义 AnswerAgent 可用的所有工具配置。
每个工具直接绑定到 AnswerAgent 的工具方法（tools.py）。

Note: AnswerAgent 主要通过意图分析决定工作流，工具配置相对简单。
"""

from typing import Dict, Any, List

# 工具配置列表
ANSWER_TOOLS_CONFIG: List[Dict[str, Any]] = [
    {
        "name": "call_retrieval",
        "method_name": "call_retrieval",
        "description": "调用检索Agent获取相关文档内容。当需要基于文档内容回答问题时使用。",
        "parameters": {
            "query": "用户的查询问题"
        },
        "enabled": True,
        "priority": 1,
    },
    {
        "name": "direct_answer",
        "method_name": "direct_answer",
        "description": "直接回答用户问题，不需要检索文档。适用于问候、一般性问题、或已有足够上下文的情况。",
        "parameters": {
            "query": "用户的问题"
        },
        "enabled": True,
        "priority": 2,
    },
]


def get_enabled_tools() -> List[Dict[str, Any]]:
    """获取所有启用的工具配置"""
    enabled = [tool for tool in ANSWER_TOOLS_CONFIG if tool.get("enabled", True)]
    enabled.sort(key=lambda x: x.get("priority", 999))
    return enabled


def get_tool_by_name(tool_name: str) -> Dict[str, Any]:
    """根据工具名称获取工具配置"""
    for tool in ANSWER_TOOLS_CONFIG:
        if tool["name"] == tool_name:
            return tool
    return None


def format_tool_description(tool: Dict[str, Any]) -> str:
    """格式化单个工具的描述文本"""
    params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
    tool_desc = f"""
工具名称: {tool['name']}
功能描述: {tool['description']}
参数: {params_desc}
"""
    return tool_desc.strip()


def format_all_tools_for_llm() -> str:
    """将所有启用的工具格式化为 LLM 可理解的文本描述"""
    enabled_tools = get_enabled_tools()
    tool_descriptions = [format_tool_description(tool) for tool in enabled_tools]
    return "\n\n".join(tool_descriptions)


TOOL_METADATA = {
    "version": "1.0.0",
    "last_updated": "2025-01-19",
    "agent": "AnswerAgent",
    "total_tools": len(ANSWER_TOOLS_CONFIG),
    "enabled_tools": len(get_enabled_tools()),
}
