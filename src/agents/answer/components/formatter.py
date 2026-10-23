"""
Answer Formatter - 答案格式化工具

负责将LLM生成的答案格式化为更友好的Markdown格式，优化UI展示效果。
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AnswerFormatter:
    """答案格式化工具"""

    @staticmethod
    def format_answer(answer: str, enhance_math: bool = True, enhance_structure: bool = True) -> str:
        """
        格式化答案，优化展示效果

        Args:
            answer: 原始答案文本
            enhance_math: 是否增强数学公式展示
            enhance_structure: 是否增强结构化展示

        Returns:
            格式化后的答案
        """
        if not answer:
            return answer

        formatted = answer

        # 1. 增强数学公式展示
        if enhance_math:
            formatted = AnswerFormatter._enhance_math_formulas(formatted)

        # 2. 增强结构化展示
        if enhance_structure:
            formatted = AnswerFormatter._enhance_structure(formatted)

        # 3. 美化代码块
        formatted = AnswerFormatter._enhance_code_blocks(formatted)

        # 4. 优化列表格式
        formatted = AnswerFormatter._enhance_lists(formatted)

        # 5. 美化引用块
        formatted = AnswerFormatter._enhance_quotes(formatted)

        return formatted

    @staticmethod
    def _enhance_math_formulas(text: str) -> str:
        """
        增强数学公式展示

        处理场景：
        1. 确保行内公式使用 $ ... $
        2. 确保块级公式使用 $$ ... $$
        3. 处理常见的LaTeX符号和公式
        4. 美化公式周围的空白
        """
        # 处理已经有LaTeX标记的公式（保持不变）
        # 只优化周围的空白

        # 块级公式：确保前后有空行
        text = re.sub(r'([^\n])\n\$\$', r'\1\n\n$$', text)  # 公式前加空行
        text = re.sub(r'\$\$\n([^\n])', r'$$\n\n\1', text)  # 公式后加空行

        # 检测可能的公式模式（未使用LaTeX标记）
        # 例如：Attention(Q, K, V) = softmax(...)
        # 注意：这种检测要谨慎，避免误判

        # 检测常见数学符号和公式模式
        math_patterns = [
            # 矩阵乘法、转置等：Q K^T, W^O, etc.
            (r'([A-Z])\s*\^\s*([A-Z])', r'$\1^\2$'),
            # 根号：sqrt(...)
            (r'\bsqrt\(([^)]+)\)', r'$\\sqrt{\1}$'),
            # 分数：... / sqrt(...)
            (r'([^\s]+)\s*/\s*sqrt\(([^)]+)\)', r'$\\frac{\1}{\\sqrt{\2}}$'),
        ]

        # 暂时不自动转换，因为可能误判
        # for pattern, replacement in math_patterns:
        #     text = re.sub(pattern, replacement, text)

        return text

    @staticmethod
    def _enhance_structure(text: str) -> str:
        """
        增强结构化展示

        处理场景：
        1. 美化章节标题
        2. 添加视觉分隔
        3. 优化段落间距
        """
        lines = text.split('\n')
        enhanced_lines = []

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 处理主标题（# 标题）
            if stripped.startswith('# ') and not stripped.startswith('## '):
                # 主标题前加分隔线（除非是第一行）
                if i > 0 and enhanced_lines and enhanced_lines[-1].strip():
                    enhanced_lines.append('')
                    enhanced_lines.append('---')
                    enhanced_lines.append('')
                enhanced_lines.append(line)
                # 主标题后加空行
                if i < len(lines) - 1 and lines[i + 1].strip():
                    enhanced_lines.append('')

            # 处理二级标题（## 标题）
            elif stripped.startswith('## '):
                # 二级标题前确保有空行
                if i > 0 and enhanced_lines and enhanced_lines[-1].strip():
                    enhanced_lines.append('')
                enhanced_lines.append(line)
                # 二级标题后加空行
                if i < len(lines) - 1 and lines[i + 1].strip():
                    enhanced_lines.append('')

            else:
                enhanced_lines.append(line)

        return '\n'.join(enhanced_lines)

    @staticmethod
    def _enhance_code_blocks(text: str) -> str:
        """
        美化代码块

        处理场景：
        1. 确保代码块有语言标识
        2. 美化代码块周围的空白
        """
        # 确保代码块前后有空行
        text = re.sub(r'([^\n])\n```', r'\1\n\n```', text)  # 代码块前加空行
        text = re.sub(r'```\n([^\n])', r'```\n\n\1', text)  # 代码块后加空行

        # 检测没有语言标识的代码块，添加通用标识
        text = re.sub(r'```\n(?![a-z])', r'```text\n', text)

        return text

    @staticmethod
    def _enhance_lists(text: str) -> str:
        """
        优化列表格式

        处理场景：
        1. 确保列表项之间的间距合理
        2. 美化嵌套列表
        """
        lines = text.split('\n')
        enhanced_lines = []
        in_list = False
        prev_indent = 0

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 检测列表项（- 或 1. 等）
            is_list_item = bool(re.match(r'^(\s*)[-*+]|\d+\.', line))

            if is_list_item:
                # 计算缩进级别
                indent = len(line) - len(line.lstrip())

                # 如果是列表的开始，前面加空行
                if not in_list and i > 0 and enhanced_lines and enhanced_lines[-1].strip():
                    enhanced_lines.append('')

                in_list = True
                prev_indent = indent
                enhanced_lines.append(line)

            else:
                # 非列表项
                if in_list and stripped:
                    # 列表结束后加空行
                    if enhanced_lines and enhanced_lines[-1].strip():
                        enhanced_lines.append('')

                in_list = False
                enhanced_lines.append(line)

        return '\n'.join(enhanced_lines)

    @staticmethod
    def _enhance_quotes(text: str) -> str:
        """
        美化引用块

        处理场景：
        1. 确保引用块周围有适当间距
        """
        # 引用块前加空行
        text = re.sub(r'([^\n])\n>', r'\1\n\n>', text)
        # 引用块后加空行
        text = re.sub(r'>\s*([^\n>])', r'>\n\n\1', text)

        return text

    @staticmethod
    def format_cross_doc_synthesis(synthesis: str, doc_names: list = None) -> str:
        """
        格式化跨文档综合答案

        Args:
            synthesis: 跨文档综合的原始答案
            doc_names: 涉及的文档名列表

        Returns:
            格式化后的答案
        """
        if not synthesis:
            return synthesis

        formatted = synthesis

        # 1. 添加跨文档标识头部
        if doc_names and len(doc_names) > 1:
            header = f"**🔗 跨文档综合回答**（基于 {len(doc_names)} 个文档）\n\n"
            if not formatted.startswith("**🔗"):
                formatted = header + formatted

        # 2. 格式化答案主体
        formatted = AnswerFormatter.format_answer(formatted)

        # 3. 添加文档来源（如果有）
        if doc_names:
            footer = f"\n\n---\n\n**📄 参考文档**: {', '.join(doc_names)}"
            if "参考文档" not in formatted:
                formatted += footer

        return formatted
