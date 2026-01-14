"""
Retrieval Agent状态定义
"""

from typing import TypedDict, Optional, List, Dict, Any


class RetrievalState(TypedDict, total=False):
    """
    Retrieval Agent的状态（ReAct模式）

    工作流程（ReAct Loop）：
    think → act → observe → evaluate → (continue/finish)
    """

    # ============ 输入 ============
    query: str  # 用户查询
    doc_name: Optional[str]  # 指定文档名（None=多文档检索）
    tags: Optional[List[str]]  # 文档标签过滤
    max_iterations: int  # 最大迭代次数

    # ============ ReAct Loop 状态 ============
    thoughts: List[str]  # 思考过程
    actions: List[Dict]  # 执行的动作 [{"tool": str, "params": dict}, ...]
    observations: List[str]  # 观察结果
    current_iteration: int  # 当前迭代次数

    # ============ 当前步骤 ============
    current_tool: Optional[str]  # 当前选择的工具
    current_params: Optional[Dict]  # 当前工具的参数
    last_result: Optional[Any]  # 上一步的结果

    # ============ 输出 ============
    retrieved_content: Dict  # 检索到的内容 {source: content, ...}
    final_summary: str  # LLM格式化的最终总结（包含来源信息和内容摘要）
    is_complete: bool  # 是否完成检索
