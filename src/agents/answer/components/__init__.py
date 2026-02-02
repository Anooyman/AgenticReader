"""
AnswerAgent 业务组件

包含问答阶段的复杂业务逻辑组件：
- DocumentSelector: 智能文档选择器
- CrossDocumentSynthesizer: 跨文档综合器
- AnswerFormatter: 答案格式化工具
"""

from .document_selector import DocumentSelector
from .cross_doc_synthesizer import CrossDocumentSynthesizer
from .formatter import AnswerFormatter

__all__ = [
    'DocumentSelector',
    'CrossDocumentSynthesizer',
    'AnswerFormatter',
]
