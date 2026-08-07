"""QA 维度 key -> 中文展示标签的唯一定义处。

Python 侧统一 `from src.pipeline.qa_labels import QA_LABELS`；前端由
pages.py 渲染 report.html 时注入 window.QA_LABELS，不再自带副本。

与 src/memory/adapters/ai_research.py 里的同名映射保持一致——两处都需要
（这里给 report/render_report 用，memory 那边给 chunk 分段用），修改维度名
时要同步改两处。
"""

QA_LABELS = {
    # pdf_arxiv 的六维度
    "full_content": "完整内容脉络",
    "innovation": "核心创新点",
    "experiments": "实验设置与结果",
    "algorithm_detail": "算法/方法实现细节",
    "advantages": "优势与局限",
    "key_takeaways": "重要结论",
    # web_article 的五维度
    "overview": "内容概述",
    "key_claims": "主要观点",
    "evidence_quality": "论据/来源可信度",
    "relevance": "参考价值",
    "caveats": "需谨慎对待之处",
}
