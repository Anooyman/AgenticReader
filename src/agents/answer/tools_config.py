"""
AnswerAgent Tools Configuration

定义 AnswerAgent 可用的所有工具配置。
工具通过注册机制接入，新增工具只需在 ANSWER_TOOLS 中添加配置。

工具调用架构：LLM 根据工具描述动态决定调用哪些工具。
"""

from typing import Dict, Any, List, Optional


# 工具注册表
ANSWER_TOOLS: Dict[str, Dict[str, Any]] = {
    "retrieve_documents": {
        "name": "retrieve_documents",
        "description": "从已索引的PDF文档中检索相关内容。支持单文档和多文档检索。当用户的问题需要参考文档内容时使用。",
        "parameters": {
            "query": {
                "type": "string",
                "required": True,
                "description": "检索查询，描述需要从文档中查找的信息"
            },
            "doc_names": {
                "type": "array",
                "items": "string",
                "required": False,
                "description": "指定要检索的文档名列表。不提供则自动选择最相关的文档。"
            },
            "max_docs": {
                "type": "integer",
                "required": False,
                "default": 5,
                "description": "自动选择模式下最多选择的文档数量"
            }
        },
        "enabled": True,
        "priority": 1,
    },
    "search_web": {
        "name": "search_web",
        "description": "搜索互联网获取最新信息，或分析指定URL的网页内容。当用户的问题需要最新资讯或文档中没有的外部信息时使用。",
        "parameters": {
            "query": {
                "type": "string",
                "required": True,
                "description": "搜索查询"
            },
            "target_urls": {
                "type": "array",
                "items": "string",
                "required": False,
                "description": "指定要分析的URL列表"
            }
        },
        "enabled": True,  # 已启用，使用 SearchAgent
        "priority": 2,
    },
}


def get_enabled_tools() -> List[Dict[str, Any]]:
    """获取所有启用的工具配置，按优先级排序"""
    enabled = [tool for tool in ANSWER_TOOLS.values() if tool.get("enabled", True)]
    enabled.sort(key=lambda x: x.get("priority", 999))
    return enabled


def get_tool_by_name(tool_name: str) -> Optional[Dict[str, Any]]:
    """根据工具名称获取工具配置"""
    return ANSWER_TOOLS.get(tool_name)


def is_tool_enabled(tool_name: str) -> bool:
    """检查工具是否启用"""
    tool = ANSWER_TOOLS.get(tool_name)
    return tool.get("enabled", False) if tool else False


def get_enabled_tool_names() -> List[str]:
    """获取所有启用的工具名称"""
    return [name for name, tool in ANSWER_TOOLS.items() if tool.get("enabled", True)]


def format_tool_for_llm(tool: Dict[str, Any]) -> str:
    """格式化单个工具描述为 LLM 可理解的文本"""
    params_lines = []
    for param_name, param_info in tool["parameters"].items():
        required = "必填" if param_info.get("required", False) else "可选"
        param_type = param_info.get("type", "string")
        default = param_info.get("default")
        desc = param_info.get("description", "")

        line = f"  - {param_name} ({param_type}, {required}): {desc}"
        if default is not None:
            line += f" (默认: {default})"
        params_lines.append(line)

    params_text = "\n".join(params_lines)
    return f"""工具名称: {tool['name']}
功能描述: {tool['description']}
参数:
{params_text}"""


def format_all_tools_for_llm() -> str:
    """将所有启用的工具格式化为 LLM 可理解的文本描述"""
    enabled_tools = get_enabled_tools()
    if not enabled_tools:
        return "当前没有可用的工具。"

    tool_descriptions = []
    for i, tool in enumerate(enabled_tools, 1):
        tool_descriptions.append(f"【工具{i}】\n{format_tool_for_llm(tool)}")

    return "\n\n".join(tool_descriptions)
