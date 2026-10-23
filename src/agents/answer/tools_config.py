"""
AnswerAgent Tools Configuration

定义 AnswerAgent 可用的所有工具配置。
工具通过注册机制接入，新增工具只需在 ANSWER_TOOLS 中添加配置。

工具调用架构：plan 节点按用户启用的 enabled_tools 确定性构造工具调用
（不再由 LLM 动态决策调用哪些工具），execute 节点并行执行这些调用。
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
