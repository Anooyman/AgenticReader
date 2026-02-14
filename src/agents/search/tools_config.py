"""
SearchAgent 工具配置

定义所有可用工具的描述、参数和使用场景
"""

from typing import Dict, List


# ========== 工具配置字典 ==========

SEARCH_TOOLS_CONFIG: Dict[str, Dict] = {
    # ========== 搜索引擎工具 ==========
    "web_search": {
        "name": "web_search",
        "description": "使用搜索引擎查找相关网页",
        "use_case": "search",  # 仅用于搜索引擎检索模式
        "parameters": {
            "query": {
                "type": "string",
                "description": "搜索查询关键词",
                "required": True
            },
            "max_results": {
                "type": "integer",
                "description": "返回的最大结果数（默认10）",
                "required": False,
                "default": 10
            }
        },
        "returns": {
            "type": "list",
            "description": "搜索结果列表，每项包含 title, url, snippet"
        },
        "example": {
            "query": "2024 诺贝尔物理学奖",
            "max_results": 10
        }
    },

    # ========== 网页爬取工具 ==========
    "scrape_single_url": {
        "name": "scrape_single_url",
        "description": "爬取单个网页的内容（HTML、文本、JSON）",
        "use_case": "both",  # 两种模式都可用
        "parameters": {
            "url": {
                "type": "string",
                "description": "目标网页URL",
                "required": True
            },
            "content_types": {
                "type": "array",
                "description": "要提取的内容类型列表：html, text, json, screenshot",
                "required": False,
                "default": ["html", "text"]
            },
            "wait_for": {
                "type": "string",
                "description": "等待的CSS选择器（用于动态加载内容）",
                "required": False
            },
            "timeout": {
                "type": "integer",
                "description": "超时时间（毫秒），默认30000",
                "required": False,
                "default": 30000
            }
        },
        "returns": {
            "type": "object",
            "description": "包含 success, content, files, metadata 的结果对象"
        },
        "example": {
            "url": "https://example.com/article",
            "content_types": ["html", "text"],
            "timeout": 30000
        }
    },

    "scrape_batch_urls": {
        "name": "scrape_batch_urls",
        "description": "批量爬取多个网页",
        "use_case": "search",  # 主要用于搜索引擎模式
        "parameters": {
            "urls": {
                "type": "array",
                "description": "URL列表",
                "required": True
            },
            "content_types": {
                "type": "array",
                "description": "要提取的内容类型",
                "required": False,
                "default": ["html", "text"]
            },
            "concurrent_limit": {
                "type": "integer",
                "description": "并发数限制（默认3）",
                "required": False,
                "default": 3
            },
            "delay_between": {
                "type": "integer",
                "description": "请求间延迟（毫秒），默认2000",
                "required": False,
                "default": 2000
            }
        },
        "returns": {
            "type": "object",
            "description": "批量爬取结果，包含 total, succeeded, failed, results"
        },
        "example": {
            "urls": ["https://site1.com", "https://site2.com"],
            "content_types": ["text"],
            "concurrent_limit": 3
        }
    },

    # ========== 资源下载工具（可选）==========
    "download_resources": {
        "name": "download_resources",
        "description": "从网页下载图片、PDF等资源文件",
        "use_case": "url_analysis",  # 主要用于URL分析模式
        "parameters": {
            "url": {
                "type": "string",
                "description": "目标网页URL",
                "required": True
            },
            "resource_types": {
                "type": "array",
                "description": "资源类型：images, pdfs, videos, all",
                "required": False,
                "default": ["images"]
            },
            "selector": {
                "type": "string",
                "description": "CSS选择器过滤",
                "required": False
            },
            "max_files": {
                "type": "integer",
                "description": "最大下载数量（默认50）",
                "required": False,
                "default": 50
            }
        },
        "returns": {
            "type": "object",
            "description": "下载结果，包含 downloaded_files, count, metadata"
        },
        "example": {
            "url": "https://example.com/gallery",
            "resource_types": ["images"],
            "max_files": 20
        }
    }
}


# ========== 辅助函数 ==========

def format_all_tools_for_llm() -> str:
    """
    格式化所有工具配置为LLM可读的描述

    Returns:
        格式化的工具描述字符串
    """
    tool_descriptions = []

    for tool_name, config in SEARCH_TOOLS_CONFIG.items():
        # 工具名称和描述
        desc = f"### {config['name']}\n"
        desc += f"**描述**: {config['description']}\n"
        desc += f"**适用场景**: {config['use_case']}\n\n"

        # 参数说明
        desc += "**参数**:\n"
        for param_name, param_info in config['parameters'].items():
            required_tag = "必需" if param_info.get('required', False) else "可选"
            param_desc = param_info.get('description', '')
            param_type = param_info.get('type', 'unknown')

            desc += f"- `{param_name}` ({param_type}, {required_tag}): {param_desc}"

            # 默认值
            if 'default' in param_info:
                desc += f" [默认: {param_info['default']}]"

            desc += "\n"

        # 示例
        if 'example' in config:
            import json
            desc += f"\n**示例**:\n```json\n{json.dumps(config['example'], indent=2, ensure_ascii=False)}\n```\n"

        desc += "\n---\n"
        tool_descriptions.append(desc)

    return "\n".join(tool_descriptions)


def get_tool_by_name(tool_name: str) -> Dict:
    """
    根据工具名称获取工具配置

    Args:
        tool_name: 工具名称

    Returns:
        工具配置字典，如果不存在返回空字典
    """
    return SEARCH_TOOLS_CONFIG.get(tool_name, {})


def get_tools_by_use_case(use_case: str) -> List[str]:
    """
    根据使用场景获取可用工具列表

    Args:
        use_case: 使用场景 ("search" 或 "url_analysis")

    Returns:
        工具名称列表
    """
    available_tools = []

    for tool_name, config in SEARCH_TOOLS_CONFIG.items():
        tool_use_case = config.get('use_case', 'both')

        if tool_use_case == 'both' or tool_use_case == use_case:
            available_tools.append(tool_name)

    return available_tools


def validate_tool_parameters(tool_name: str, params: Dict) -> tuple[bool, str]:
    """
    验证工具参数是否合法

    Args:
        tool_name: 工具名称
        params: 参数字典

    Returns:
        (是否合法, 错误信息)
    """
    config = get_tool_by_name(tool_name)

    if not config:
        return False, f"未知工具: {tool_name}"

    # 检查必需参数
    for param_name, param_info in config['parameters'].items():
        if param_info.get('required', False) and param_name not in params:
            return False, f"缺少必需参数: {param_name}"

    return True, ""
