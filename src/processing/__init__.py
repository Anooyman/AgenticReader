"""
统一处理层

包含：
- PDF处理：pdf/extractor.py, pdf/image_processor.py, pdf/metadata.py
- Web处理：web/extractor.py, web/mcp_integration.py
- 文本处理：text/splitter.py, text/chunker.py, text/cleaner.py
- Embedding：embedding/generator.py
"""

from .text.splitter import StrictOverlapSplitter

__all__ = ['StrictOverlapSplitter']
