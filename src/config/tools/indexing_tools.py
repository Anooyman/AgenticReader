"""
Indexing Tools Configuration

定义 IndexingAgent 可用的所有工具
每个工具直接绑定到 IndexingAgent 的方法
"""

from typing import Dict, Any, List

# 工具配置列表
INDEXING_TOOLS_CONFIG: List[Dict[str, Any]] = [
    {
        "name": "extract_basic_info",
        "method_name": "extract_basic_info",
        "description": "提取文档的基本信息，包括标题、作者、主题等元数据。适用于初始化文档处理时获取文档概览。",
        "parameters": {
            "query": "文档名称或内容的简要描述"
        },
        "enabled": True,
        "priority": 1,
    },
    {
        "name": "detect_chapters",
        "method_name": "detect_chapters",
        "description": "检测文档的章节结构，识别标题层级和章节划分。适用于分析文档的组织结构。",
        "parameters": {
            "query": "文档名称或内容"
        },
        "enabled": True,
        "priority": 2,
    },
    {
        "name": "build_vector_index",
        "method_name": "build_vector_index",
        "description": "为文档内容构建向量索引，用于后续的语义检索。这是索引文档的核心步骤。",
        "parameters": {
            "query": "文档名称"
        },
        "enabled": True,
        "priority": 3,
    },
    {
        "name": "generate_summary",
        "method_name": "generate_summary",
        "description": "生成文档的摘要，包括简要摘要和详细摘要。适用于快速了解文档主要内容。",
        "parameters": {
            "query": "文档名称"
        },
        "enabled": True,
        "priority": 4,
    },
    {
        "name": "auto_tag_document",
        "method_name": "auto_tag_document",
        "description": "自动为文档生成分类标签，帮助文档分类和组织。",
        "parameters": {
            "query": "文档名称"
        },
        "enabled": True,
        "priority": 5,
    },
]


def get_enabled_tools() -> List[Dict[str, Any]]:
    """获取所有启用的工具配置"""
    enabled = [tool for tool in INDEXING_TOOLS_CONFIG if tool.get("enabled", True)]
    enabled.sort(key=lambda x: x.get("priority", 999))
    return enabled


def get_tool_by_name(tool_name: str) -> Dict[str, Any]:
    """根据工具名称获取工具配置"""
    for tool in INDEXING_TOOLS_CONFIG:
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
    "agent": "IndexingAgent",
    "total_tools": len(INDEXING_TOOLS_CONFIG),
    "enabled_tools": len(get_enabled_tools()),
}
