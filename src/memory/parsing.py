"""纯文本解析辅助函数（无网络调用），从 LLM-Memory 的 common/parsing.py 原样搬入。
把 LLM 的自由格式文本响应解析成结构化数据，对模型偶尔不遵守格式的输出保持
宽容（返回空/默认值而不是抛异常）——这是原实现已经验证过的容错策略。
"""
import json
import re
from typing import Any, Dict, List


def clean_text_response(content: str) -> str:
    """去除 markdown 代码块围栏和首尾空白/引号。"""
    content = content.strip()
    content = re.sub(r'^```\w*\s*', '', content)
    content = re.sub(r'\s*```$', '', content)
    content = content.strip()
    if len(content) >= 2 and content[0] == content[-1] and content[0] in ('"', "'"):
        content = content[1:-1].strip()
    return content


def parse_keyword_lines(content: str) -> List[str]:
    """每行一个关键词，容忍模型加的编号/引号/逗号拼接等格式噪音。"""
    keywords = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r'^[-*•\d]+[.)]?\s*', '', line)
        line = line.strip().strip('"\'').strip()
        if not line:
            continue
        if ',' in line and len(line) < 200:
            keywords.extend(p.strip().strip('"\'').strip() for p in line.split(','))
        else:
            keywords.append(line)
    return [k for k in keywords if k]


def parse_kv_lines(content: str) -> Dict[str, str]:
    """解析 "key: value" 形式的行，key 统一转小写。"""
    result = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or ':' not in line:
            continue
        key, _, value = line.partition(':')
        key = key.strip().lower().lstrip('-*• ').strip()
        value = value.strip().strip('"\'').strip()
        if key and value:
            result[key] = value
    return result


def parse_sections(content: str, tags: List[str]) -> Dict[str, str]:
    """按 "===TAG===" 标记行切分成多个命名段落。"""
    pattern = re.compile(
        r'^\s*=+\s*(' + '|'.join(re.escape(t) for t in tags) + r')\s*=+\s*$',
        re.IGNORECASE,
    )
    sections: Dict[str, List[str]] = {}
    current = None
    for line in content.splitlines():
        m = pattern.match(line)
        if m:
            current = m.group(1).upper()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {tag: "\n".join(lines).strip() for tag, lines in sections.items()}


def safe_float(d: Any, key: str, default: float) -> float:
    """防御式读取一个 float 字段，裁剪到 [0, 1]。"""
    if not isinstance(d, dict):
        return default
    v = d.get(key, default)
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default
