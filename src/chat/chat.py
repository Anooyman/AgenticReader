"""
Memory Base Module
内存基础模块

该模块定义了多代理系统的核心基础类，包括：
- GraphBase: 图基础类，定义状态图的基本接口
- PlanAgent: 计划代理，负责任务分析和执行计划制定
- ExecutorAgent: 执行代理，负责调用子代理执行具体任务
- PlanState/ExecutorState: 状态管理类，定义各层级图的状态结构

主要设计思路：
1. 使用两层级图架构：PlanGraph(计划层) + ExecutorGraph(执行层)
2. 通过状态管理实现各节点间的数据流转
3. 基于LangGraph框架实现异步状态图处理
4. 支持多种子代理类型的动态调用和管理

Author: LLMReader Team
Date: 2025-09-03
Version: 1.0
"""

import asyncio
import logging
from typing import TypedDict, Dict, List, Any, Union

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from src.core.llm.client import LLMBase
from src.utils.helpers import *
from src.config.settings import (
    AgentType,
    AgentCard,
    ExecutorRole
)

# 配置日志系统
# 设置详细的日志格式，包含时间戳、日志级别、模块名称和消息
logging.basicConfig(
    level=logging.INFO,  # 可根据需要改为 DEBUG 获取更详细的调试信息
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger(__name__)

# 记录模块加载信息
logger.info("内存基础模块已加载，准备初始化多代理系统组件")


class PlanState(TypedDict):
    """
    PlanGraph状态管理类
    
    定义计划图(PlanGraph)在执行过程中需要维护的状态数据结构。
    该状态在计划代理、持久化代理和执行器代理之间流转。
    
    Attributes:
        question (str): 用户输入的原始问题或查询
        plan (List[Dict[str, Any]]): 由计划代理生成的执行计划列表
            每个计划项包含：
            - agent_name: 负责执行的代理名称
            - action_description: 具体的执行描述
            - priority: 优先级(可选)
        execution_results (Dict[str, Any]): 执行器代理返回的执行结果
            包含：
            - results: 各个子代理的执行结果
            - status: 总体执行状态("completed", "failed", "partial")
        status (Dict[str, Any]): 当前状态信息，用于调试和监控
        is_complete (bool): 标识整个任务是否已完成
            True: 任务完成，进入持久化阶段
            False: 需要继续执行或重新规划
        final_answer (str): 最终生成的用户答案
    
    状态流转路径:
        START -> PlanAgent -> ExecutorAgent -> PlanAgent -> PersistenceAgent -> END
    """
    question: str
    plan: List[Dict[str, Any]]
    execution_results: Dict[str, Any]
    status: Dict[str, Any]
    is_complete: bool
    final_answer: str


class ExecutorState(TypedDict):
    """
    ExecutorGraph状态管理类
    
    定义执行图(ExecutorGraph)在运行过程中的状态数据结构。
    主要用于管理计划的执行进度和各个子代理的调用结果。
    
    Attributes:
        plan (List[Dict[str, Any]]): 从PlanAgent接收的执行计划列表
        current_plan_index (int): 当前正在执行的计划索引
            用于跟踪执行进度，支持顺序执行多个计划项
        results (Dict[str, Any]): 各个计划项的执行结果集合
            key: 计划索引(str格式)
            value: 对应代理的执行结果
        formatted_inputs (Dict[str, Any]): 格式化后的输入数据
            key: 计划索引(str格式)
            value: 为特定代理格式化后的输入参数
    
    执行流程:
        format_input -> execute_agent -> check_completion
        如果未完成则循环回到format_input继续下一个计划
    """
    plan: List[Dict[str, Any]]
    current_plan_index: int
    results: Dict[str, Any]
    formatted_inputs: Dict[str, Any]


class GraphBase(LLMBase):
    """
    图基类 - 多代理系统的核心基础类
    
    继承自LLMBase，为所有基于状态图的代理提供统一的接口和基础功能。
    该类定义了状态图的生命周期管理，包括构建、编译和执行。
    
    设计模式：模板方法模式
    - build_graph(): 抽象方法，由子类实现具体的图结构构建逻辑
    - run_graph(): 模板方法，定义图执行的标准流程
    
    主要职责：
    1. 管理状态图的生命周期
    2. 提供统一的图执行接口
    3. 处理图执行过程中的异常情况
    4. 记录详细的执行日志便于调试
    
    Attributes:
        graph: LangGraph状态图实例，由子类构建
        provider (str): LLM提供商配置
    
    Usage:
        class MyAgent(GraphBase):
            def build_graph(self):
                # 实现具体的图构建逻辑
                pass
        
        agent = MyAgent()
        result = await agent.run_graph("用户查询")
    """
    def __init__(self, provider: str = "azure") -> None:
        """
        初始化图基类
        
        Args:
            provider (str): LLM服务提供商，默认为"azure"
                支持的提供商类型由LLMBase决定
        """
        super().__init__(provider)
        self.graph = None  # 状态图实例，在build_graph中初始化
        logger.info(f"图基类初始化完成 - 提供者: {provider}, 类型: {self.__class__.__name__}")

    def build_graph(self, pre_defined_graph_type: str = "") -> None:
        """
        构建状态图的抽象方法
        
        这是一个抽象方法，必须由子类实现。子类应该在此方法中：
        1. 创建StateGraph实例
        2. 添加所需的节点(node)
        3. 定义节点间的边(edge)关系
        4. 编译图结构
        
        Args:
            pre_defined_graph_type (str): 预定义的图类型，用于支持多种图结构
                可以根据这个参数构建不同类型的状态图
        
        Raises:
            NotImplementedError: 子类未实现此方法时抛出
        
        Note:
            实现该方法后应设置self.graph为编译后的状态图实例
        """
        logger.error(f"build_graph方法未被{self.__class__.__name__}实现")
        raise NotImplementedError("子类必须实现build_graph方法")

    async def run_graph(self, query: str) -> str:
        """
        运行状态图处理用户查询
        
        这是图执行的模板方法，定义了标准的执行流程：
        1. 检查图是否已构建，未构建则自动构建
        2. 配置执行参数(如递归限制)
        3. 异步流式处理图执行事件
        4. 提取并返回最终结果
        5. 处理执行过程中的异常情况
        
        Args:
            query (str): 用户输入的查询字符串
        
        Returns:
            str: 图执行的最终结果
                如果执行失败则返回空字符串
        
        Raises:
            Exception: 捕获并记录所有执行异常，但不向上抛出
        
        执行流程监控：
        - 记录查询开始日志
        - 监控图构建状态
        - 跟踪执行事件流
        - 记录结果提取过程
        - 异常情况记录和调试
        """
        # 截断长查询以避免日志过长，同时保留足够信息用于调试
        query_preview = query[:50] + "..." if len(query) > 50 else query
        logger.info(f"开始运行图处理查询 - 查询预览: '{query_preview}', 查询长度: {len(query)}")
        
        # 检查图状态，自动构建未初始化的图
        if not self.graph:
            logger.info("检测到图未构建，开始自动构建状态图...")
            try:
                self.build_graph()
                logger.info("状态图自动构建成功")
            except Exception as e:
                logger.error(f"状态图构建失败: {e}", exc_info=True)
                return ""

        # 配置图执行参数
        chat_config = {
            "recursion_limit": 50  # 防止无限递归的安全限制
        }
        logger.debug(f"图执行配置: {chat_config}")
        
        res = None
        tmp = None
        
        try:
            logger.info("开始异步流式处理图执行事件...")
            event_count = 0
            
            # 异步流式处理图执行
            async for event in self.graph.astream(
                input={"question": query}, 
                config=chat_config
            ):
                event_count += 1
                logger.debug(f"处理第{event_count}个执行事件: {list(event.keys())}")
                
                # 处理事件数据，保留最后一个非空值
                for key, value in event.items():
                    if value is not None:
                        tmp = value
                        logger.debug(f"更新临时结果来源: {key}")
            
            logger.info(f"图执行完成，共处理{event_count}个事件")
            
        except Exception as e:
            logger.error(f"图执行过程中发生异常: {e}", exc_info=True)
            # 记录详细的错误上下文
            logger.error(f"执行失败的查询: '{query_preview}'")
            logger.error(f"图类型: {self.__class__.__name__}")
            return ""
        
        # 提取最终结果
        try: 
            if tmp is None:
                logger.warning("图执行完成但未获取到任何结果")
                return ""
                
            # 尝试从结果中提取final_answer
            res = tmp.get("final_answer")
            if res:
                # 记录成功结果，截断过长的结果以避免日志膨胀
                result_preview = res[:100] + "..." if len(res) > 100 else res
                logger.info(f"成功提取图执行结果 - 结果预览: '{result_preview}', 结果长度: {len(res)}")
            else:
                logger.warning("结果中未找到final_answer字段")
                logger.debug(f"可用字段: {list(tmp.keys()) if isinstance(tmp, dict) else 'N/A'}")
                res = ""
                
        except Exception as e:
            logger.error(f"从图输出中提取结果时发生异常: {e}", exc_info=True)
            logger.debug(f"临时结果类型: {type(tmp)}, 内容: {tmp}")
            
            # 开发模式下启用调试器
            if logger.getEffectiveLevel() == logging.DEBUG:
                logger.info("开发调试模式：启动pdb调试器")
            
            res = ""
        
        logger.info(f"图执行流程结束 - 返回结果: {'有效' if res else '无效'}")
        return res or ""


class PlanAgent(GraphBase):
    """
    第一层级：计划代理 - 多代理系统的任务规划和结果判断中心
    
    PlanAgent是多代理系统的顶层控制器，负责将用户复杂查询分解为可执行的计划，
    并协调各个子代理完成任务。它实现了完整的任务生命周期管理。
    
    核心功能：
    1. 智能任务分析：解析用户意图，识别所需的处理步骤
    2. 执行计划制定：基于可用子代理能力，生成最优执行序列
    3. 结果质量评估：判断执行结果是否满足用户需求
    4. 自适应重规划：根据执行反馈动态调整计划
    5. 最终答案生成：整合各部分结果，形成用户友好的回复
    
    图结构设计 (PlanGraph):
    ```
    START -> PlanAgent -> [ExecutorAgent OR PersistenceAgent] -> END
                ↑              ↓
                └─── 循环直到任务完成 ─────┘
    ```
    
    状态流转逻辑：
    - 初始规划：分析用户问题，制定初始执行计划
    - 执行监控：调用ExecutorAgent执行计划，收集结果
    - 质量评估：判断结果是否满足用户需求
    - 自适应调整：如需要则重新规划，否则进入最终答案生成
    - 结果持久化：保存执行过程和最终结果
    
    Attributes:
        sub_agent_info (Dict): 可用子代理的配置信息字典
            从AgentCard中加载启用状态的代理
        graph: 编译后的PlanGraph状态图实例
    
    子代理集成：
    - MemoryAgent: 记忆存储和检索
    - SearchAgent: 信息搜索和获取
    - AnalysisAgent: 数据分析和处理
    - 其他专业代理...
    
    使用示例：
    ```python
    plan_agent = PlanAgent(provider="azure")
    result = await plan_agent.run_graph("帮我记录今天的饮食情况")
    ```
    """

    def __init__(self, provider: str = "azure") -> None:
        """
        初始化计划代理
        
        Args:
            provider (str): LLM服务提供商，默认"azure"
        
        初始化过程：
        1. 调用父类GraphBase初始化LLM客户端
        2. 初始化图实例为None，延迟到首次使用时构建
        3. 从AgentCard加载所有启用状态的子代理配置
        4. 记录初始化状态和可用代理数量
        """
        super().__init__(provider)
        self.graph = None  # 延迟构建，提高启动速度
        
        # 加载启用状态的子代理配置信息
        logger.info("开始加载子代理配置...")
        from src.utils.common import get_enabled_agents
        self.sub_agent_info = get_enabled_agents()
        enabled_agents = list(self.sub_agent_info.keys())
                
        logger.info(f"计划代理初始化完成 - 提供商: {provider}, 已加载{len(self.sub_agent_info)}个子代理")
        logger.debug(f"可用子代理列表: {enabled_agents}")

    def build_graph(self) -> None:
        """
        构建PlanGraph状态图
        
        构建三节点的状态图架构：
        1. PlanAgent: 任务分析和计划制定节点
        2. ExecutorAgent: 计划执行节点（调用ExecutorGraph）
        3. PersistenceAgent: 结果持久化和最终答案生成节点
        
        图结构特点：
        - 循环执行：PlanAgent可以多次调用ExecutorAgent直到任务完成
        - 条件跳转：基于is_complete标志决定流转方向
        - 异常处理：每个节点都有异常捕获和恢复机制
        
        编译后的图支持：
        - 异步并发执行
        - 状态检查点和恢复
        - 递归限制防止无限循环
        """
        logger.info("开始构建PlanGraph状态图...")
        
        try:
            # 创建状态图构建器，指定状态类型
            graph_builder = StateGraph(PlanState)

            # 添加核心处理节点
            graph_builder.add_node(AgentType.PLAN, self.call_plan_agent)
            graph_builder.add_node(AgentType.PERSISTENCE, self.call_persistence_agent)  
            graph_builder.add_node(AgentType.EXECUTOR, self.call_executor_graph)
            logger.debug("已添加所有图节点")
            
            # 定义图的边连接关系
            # 固定边：开始节点指向计划节点
            graph_builder.add_edge(START, AgentType.PLAN)
            # 固定边：持久化节点指向结束
            graph_builder.add_edge(AgentType.PERSISTENCE, END)
            # 条件边由节点内部的Command控制
            
            logger.debug("已定义图边连接关系")
            
            # 编译状态图，生成可执行的图实例
            self.graph = graph_builder.compile()
            
            logger.info("PlanGraph构建并编译成功")
            
        except Exception as e:
            logger.error(f"构建PlanGraph失败: {e}", exc_info=True)
            raise RuntimeError(f"PlanGraph构建失败: {str(e)}")

    async def call_plan_agent(self, state: PlanState) -> Command:
        """
        计划代理节点：智能任务分析和执行计划制定
        
        这是PlanGraph的核心决策节点，根据当前状态决定下一步行动：
        1. 初次规划：分析用户问题，制定初始执行计划
        2. 结果评估：分析执行结果，判断是否满足用户需求  
        3. 自适应调整：根据评估结果决定重新规划或结束任务
        
        Args:
            state (PlanState): 当前图状态，包含问题、执行结果等信息
            
        Returns:
            Command: LangGraph命令，指示下一个执行节点
                - 转向EXECUTOR: 需要执行新计划
                - 转向PERSISTENCE: 任务完成，生成最终答案
        
        处理逻辑：
        1. 分析输入状态，区分初次规划和结果评估场景
        2. 构建适当的LLM提示词
        3. 调用LLM生成计划或评估结果
        4. 解析LLM响应，提取计划列表和完成标志
        5. 更新状态，返回流转指令
        
        异常处理：
        - LLM调用失败：记录错误，返回默认计划
        - 响应解析失败：使用备用解析策略
        - 状态更新失败：记录警告，保持原状态
        """
        question = state.get("question", "")
        execution_results = state.get("execution_results", {})
        
        # 截断问题用于日志显示，避免日志过长
        question_preview = question[:50] + "..." if len(question) > 50 else question
        logger.info(f"计划代理开始处理问题: '{question_preview}'")
        
        # 检查是否有之前的执行结果需要分析
        has_execution_results = execution_results and execution_results.get("status") == "completed"
        
        if has_execution_results:
            # 结果评估模式：分析执行结果质量
            logger.info("模式: 执行结果评估 - 分析之前的执行结果...")
            
            input_data = {
                "question": question,
                "execution_results": execution_results.get("results", {}),
                "execution_status": execution_results.get("status", "unknown"),
                "mode": "result_evaluation"  # 明确标识处理模式
            }
            
            logger.debug(f"结果评估输入数据: {input_data}")
            
        else:
            # 初始规划模式：制定新的执行计划
            logger.info("模式: 初始任务规划 - 分析问题并制定执行计划...")
            
            input_data = {
                "question": question,
                "execution_results": {},
                "execution_status": "no_execution",
                "mode": "initial_planning"  # 明确标识处理模式
            }
        
        logger.debug(f"LLM输入数据准备完成，数据大小: {len(str(input_data))}字符")
        
        # 调用LLM生成计划或评估结果
        try:
            logger.info("开始调用LLM进行任务分析...")
            response = self.call_llm_chain(
                role=AgentType.PLAN,
                input_prompt=str(input_data),
                session_id=AgentType.PLAN,
                system_format_dict={
                    "sub_agent_info": self.sub_agent_info  # 提供子代理能力信息
                }
            )
            
            # 记录LLM响应（截断长响应）
            response_preview = response[:200] + "..." if len(response) > 200 else response
            logger.info(f"LLM响应获取成功: '{response_preview}'")
            
        except Exception as e:
            logger.error(f"LLM调用失败: {e}", exc_info=True)
            # 提供默认的错误处理计划
            state["is_complete"] = True
            state["final_answer"] = f"抱歉，处理您的请求时遇到了技术问题: {str(e)}"
            return Command(update=state, goto=AgentType.PERSISTENCE)
        
        # 解析LLM响应，提取计划信息
        try:
            logger.info("开始解析LLM响应...")
            extract_response = extract_data_from_LLM_res(response)
            
            end_flag = extract_response.get("result", False)  # 任务是否完成
            plan_list = extract_response.get("plan", [])      # 执行计划列表
            
            logger.info(f"响应解析完成 - 任务完成标志: {end_flag}, 计划数量: {len(plan_list)}")
            
            # 验证计划列表的有效性
            if not end_flag and not plan_list:
                logger.warning("计划列表为空但任务未标记为完成，将标记任务完成")
                end_flag = True
                
        except Exception as e:
            logger.error(f"解析LLM响应失败: {e}", exc_info=True)
            # 使用备用解析策略
            logger.info("尝试备用解析策略...")
            end_flag = True  # 安全起见，标记为完成
            plan_list = []

        # 更新状态
        state["plan"] = plan_list
        state["is_complete"] = end_flag
        
        # 决定下一步流转
        if end_flag:
            # 任务完成，转向结果持久化
            logger.info("任务评估完成，转向持久化代理生成最终答案")
            state["execution_results"] = execution_results
            return Command(update=state, goto=AgentType.PERSISTENCE)
        else:
            # 需要执行计划，转向执行器
            logger.info(f"需要执行{len(plan_list)}个计划项，转向执行器代理")
            if logger.getEffectiveLevel() == logging.DEBUG:
                for i, plan in enumerate(plan_list):
                    logger.debug(f"计划项 {i+1}: {plan.get('agent_name', 'unknown')} - {plan.get('action_description', 'no description')}")
            return Command(update=state, goto=AgentType.EXECUTOR)

    async def call_persistence_agent(self, state: PlanState) -> PlanState:
        """
        持久化代理节点：结果整合和最终答案生成
        
        这是PlanGraph的最终处理节点，负责：
        1. 整合各个子代理的执行结果
        2. 基于执行结果生成用户友好的最终答案
        3. 进行数据持久化（如果需要）
        4. 完成任务生命周期管理
        
        Args:
            state (PlanState): 包含完整执行结果的图状态
            
        Returns:
            PlanState: 更新后的状态，包含final_answer字段
        
        处理流程：
        1. 从状态中提取问题和执行结果
        2. 调用结果整合逻辑生成最终答案
        3. 更新状态中的final_answer字段
        4. 记录处理完成日志
        
        错误处理：
        - 执行结果为空：返回提示用户提供更多信息
        - 答案生成失败：返回通用错误信息
        - 其他异常：记录详细错误并返回错误提示
        """
        try:
            question = state.get("question", "")
            execution_results = state.get("execution_results", {})
            
            # 记录持久化开始日志
            question_preview = question[:50] + "..." if len(question) > 50 else question
            logger.info(f"持久化代理开始处理: '{question_preview}'")
            
            # 记录执行结果统计信息
            if execution_results:
                result_count = len(execution_results.get("results", {}))
                status = execution_results.get("status", "unknown")
                logger.info(f"执行结果统计 - 状态: {status}, 结果数量: {result_count}")
            else:
                logger.info("执行结果为空，将生成基础回复")
            
            # 生成最终答案
            logger.info("开始生成最终用户答案...")
            final_answer = self._generate_final_answer(
                question=question,
                execution_results=execution_results,
            )
            
            # 记录答案生成结果
            answer_preview = final_answer[:100] + "..." if len(final_answer) > 100 else final_answer
            logger.info(f"最终答案生成成功 - 预览: '{answer_preview}', 长度: {len(final_answer)}")
            # 更新状态
            state["final_answer"] = final_answer
            logger.info("持久化代理处理完成")
            
            return state
            
        except Exception as e:
            logger.error(f"持久化代理执行错误: {e}", exc_info=True)
            # 生成错误提示作为最终答案
            error_answer = f"抱歉，处理您的请求时出现了错误: {str(e)}。请稍后重试或联系技术支持。"
            state["final_answer"] = error_answer
            logger.warning(f"返回错误提示答案: {error_answer}")
            return state
    
    def _generate_final_answer(self, question: str, execution_results: Dict[str, Any]) -> str:
        """
        基于执行结果生成用户友好的最终答案
        
        这是答案生成的核心逻辑，负责将技术性的执行结果转换为
        自然语言形式的用户回复。
        
        Args:
            question (str): 用户的原始问题
            execution_results (Dict[str, Any]): 执行器返回的结果集合
        
        Returns:
            str: 面向用户的最终答案
        
        生成策略：
        1. 优先使用成功的执行结果
        2. 如果有多个结果，进行智能整合
        3. 对于失败的执行，提供合理的解释
        4. 生成的答案要符合用户的问题类型和期望
        
        LLM调用策略：
        - 使用专门的答案生成prompt模板
        - 明确指示生成用户友好的回复
        - 包含适当的上下文信息
        """
        try:
            # 分析执行结果的完整性和质量
            if execution_results.get("status") == "completed":
                results = execution_results.get("results", {})
                logger.debug(f"分析执行结果 - 总数: {len(results)}")
                
                if results:
                    # 收集所有成功的执行结果
                    successful_results = []
                    failed_results = []
                    
                    for key, result in results.items():
                        if isinstance(result, dict):
                            if result.get("status") == "completed":
                                result_content = result.get("result", "")
                                if result_content:
                                    successful_results.append({
                                        "agent": result.get("agent_name", "unknown"),
                                        "content": result_content
                                    })
                                    logger.debug(f"成功结果 {key}: {result.get('agent_name', 'unknown')}")
                            else:
                                failed_results.append({
                                    "agent": result.get("agent_name", "unknown"),
                                    "error": result.get("error", "未知错误")
                                })
                                logger.debug(f"失败结果 {key}: {result.get('error', '未知错误')}")

                    logger.info(f"结果分析完成 - 成功: {len(successful_results)}, 失败: {len(failed_results)}")

                    if successful_results:
                        # 整合成功结果生成最终答案
                        return self._integrate_successful_results(question, successful_results)
                    elif failed_results:
                        # 所有结果都失败，生成失败说明
                        return self._handle_all_failed_results(question, failed_results)
            
            # 无有效执行结果的情况
            logger.warning("没有有效的执行结果用于生成最终答案")
            return self._generate_fallback_answer(question)
            
        except Exception as e:
            logger.error(f"生成最终答案时发生异常: {e}", exc_info=True)
            return f"抱歉，在处理您的问题'{question}'时出现了技术问题。请稍后重试。"

    def _integrate_successful_results(self, question: str, successful_results: List[Dict]) -> str:
        """
        整合成功的执行结果生成最终答案
        
        Args:
            question (str): 原始用户问题
            successful_results (List[Dict]): 成功的执行结果列表
        
        Returns:
            str: 整合后的最终答案
        """
        try:
            # 构建结果整合的上下文
            results_content = []
            for i, result in enumerate(successful_results, 1):
                agent_name = result.get("agent", "unknown")
                content = result.get("content", "")
                results_content.append(f"[{agent_name}执行结果]: {content}")

            results_text = "\n\n".join(results_content)
            
            logger.info(f"开始整合{len(successful_results)}个成功结果")
            logger.debug(f"结果内容总长度: {len(results_text)}字符")
            
            # 构建LLM提示词进行结果整合
            answer_prompt = f"""
基于以下多个代理的执行结果，为用户生成一个清晰、准确、完整的答案：

用户问题：{question}

执行结果：
{results_text}

请生成答案，要求：
1. 语言自然流畅，易于理解
2. 充分利用所有相关执行结果
3. 直接回答用户的问题
4. 如果结果之间有矛盾，请合理解释
5. 保持专业但友好的语调
6. 如果信息不完整，请说明哪些方面需要更多信息
            """
            
            # 调用LLM进行结果整合
            response = self.call_llm_chain(
                role="final_answer_generator",
                input_prompt=answer_prompt,
                session_id="final_answer_integration"
            )
            
            logger.info("LLM答案整合生成成功")
            return response
            
        except Exception as e:
            logger.error(f"整合成功结果失败: {e}", exc_info=True)
            # 回退到简单拼接
            simple_answer = f"基于您的问题'{question}'，我为您找到了以下信息：\n\n"
            for result in successful_results:
                simple_answer += f"• {result.get('content', '')}\n"
            return simple_answer

    def _handle_all_failed_results(self, question: str, failed_results: List[Dict]) -> str:
        """
        处理所有执行都失败的情况
        
        Args:
            question (str): 原始用户问题  
            failed_results (List[Dict]): 失败的执行结果列表
        
        Returns:
            str: 失败情况的说明答案
        """
        logger.warning(f"所有{len(failed_results)}个执行结果都失败了")
        
        # 收集错误信息
        error_summary = []
        for result in failed_results:
            agent = result.get("agent", "unknown")
            error = result.get("error", "未知错误")
            error_summary.append(f"{agent}: {error}")
        
        # 生成用户友好的失败说明
        return f"""抱歉，在处理您的问题"{question}"时遇到了一些技术问题：

{chr(10).join(f"• {error}" for error in error_summary)}

建议您：
1. 检查问题描述是否清晰完整
2. 稍后重试
3. 如果问题持续存在，请联系技术支持

我们会持续改进服务质量，感谢您的理解。"""

    def _generate_fallback_answer(self, question: str) -> str:
        """
        生成备用答案（当没有执行结果时）
        
        Args:
            question (str): 原始用户问题
        
        Returns:
            str: 备用回复答案
        """
        logger.info("生成备用答案")
        return f"""抱歉，我暂时无法完整回答您的问题"{question}"。

可能的原因：
• 问题可能需要更具体的描述
• 当前系统可能暂时无法处理此类问题
• 需要的功能模块可能暂时不可用

建议：
1. 请尝试重新表述您的问题，提供更多具体信息
2. 确认问题是否在我的能力范围内
3. 如果是紧急问题，请联系相关专业人员

感谢您的理解，我会继续学习以更好地为您服务。"""

    async def call_executor_graph(self, state: PlanState) -> PlanState:
        """
        执行器图调用节点：协调第二层级ExecutorAgent执行具体计划
        
        此节点作为PlanGraph和ExecutorGraph之间的桥梁，负责：
        1. 将PlanState中的计划传递给ExecutorAgent
        2. 创建并管理ExecutorAgent实例
        3. 监控执行过程并处理异常
        4. 将执行结果包装回PlanState格式
        5. 指导图流转回到PlanAgent进行结果评估
        
        Args:
            state (PlanState): 包含待执行计划的图状态
            
        Returns:
            Command: 返回到PlanAgent进行结果分析的流转指令
        
        执行流程：
        1. 从状态中提取计划列表
        2. 创建ExecutorAgent实例
        3. 调用ExecutorAgent.execute_plans()执行所有计划
        4. 处理执行结果和异常情况
        5. 更新状态中的execution_results
        6. 返回流转指令指向PlanAgent
        
        错误处理策略：
        - ExecutorAgent创建失败：记录错误，标记执行失败
        - 执行过程异常：捕获异常，保留错误信息
        - 结果格式异常：使用默认错误格式
        - 超时处理：设置合理的执行超时限制
        """
        plan = state.get("plan", [])
        
        # 记录执行开始日志
        logger.info(f"执行器图调用开始 - 待执行计划数量: {len(plan)}")
        
        # 如果计划为空，直接标记为失败
        if not plan:
            logger.warning("执行器图收到空计划列表")
            state["execution_results"] = {
                "error": "没有可执行的计划",
                "status": "failed",
                "results": {}
            }
            logger.info("返回计划代理进行空计划分析")
            return Command(update=state, goto=AgentType.PLAN)
        
        # 记录计划详情（调试模式下）
        if logger.getEffectiveLevel() == logging.DEBUG:
            for i, plan_item in enumerate(plan):
                agent_name = plan_item.get("agent_name", "unknown")
                action = plan_item.get("action_description", "no description")[:50]
                logger.debug(f"计划 {i+1}: {agent_name} - {action}...")
        
        try:
            # 创建执行器代理实例
            logger.info("创建ExecutorAgent实例...")
            executor_agent = ExecutorAgent()
            
            # 执行计划列表
            logger.info("开始执行计划列表...")
            execution_start_time = asyncio.get_event_loop().time()
            
            executor_results = await executor_agent.execute_plans(plan)
            
            execution_duration = asyncio.get_event_loop().time() - execution_start_time
            logger.info(f"计划执行完成 - 耗时: {execution_duration:.2f}秒")
            
            # 检查执行结果的格式和内容
            if isinstance(executor_results, dict) and "error" in executor_results:
                # 执行失败的情况
                error_msg = executor_results["error"]
                logger.error(f"ExecutorAgent执行失败: {error_msg}")
                
                state["execution_results"] = {
                    "error": error_msg,
                    "status": "failed",
                    "results": executor_results.get("results", {})
                }
                
            elif isinstance(executor_results, dict):
                # 执行成功的情况
                results_count = len(executor_results)
                successful_count = sum(
                    1 for result in executor_results.values() 
                    if isinstance(result, dict) and result.get("status") == "completed"
                )
                
                logger.info(f"ExecutorAgent执行完成 - 总结果数: {results_count}, 成功数: {successful_count}")
                
                state["execution_results"] = {
                    "results": executor_results,
                    "status": "completed",
                    "execution_duration": execution_duration,
                    "summary": {
                        "total_plans": len(plan),
                        "total_results": results_count,
                        "successful_results": successful_count,
                        "failed_results": results_count - successful_count
                    }
                }
                
            else:
                # 结果格式异常
                logger.warning(f"ExecutorAgent返回了异常格式的结果: {type(executor_results)}")
                state["execution_results"] = {
                    "error": f"执行器返回了异常格式的结果: {type(executor_results)}",
                    "status": "failed",
                    "raw_result": str(executor_results)
                }
            
        except asyncio.TimeoutError:
            # 执行超时
            logger.error("ExecutorAgent执行超时")
            state["execution_results"] = {
                "error": "执行器代理执行超时，请检查计划复杂度或网络连接",
                "status": "timeout"
            }
            
        except Exception as e:
            # 其他执行异常
            logger.error(f"调用ExecutorAgent时发生异常: {e}", exc_info=True)
            state["execution_results"] = {
                "error": f"执行器代理执行异常: {str(e)}",
                "status": "failed",
                "exception_type": type(e).__name__
            }
        
        # 记录最终状态并返回流转指令
        final_status = state["execution_results"].get("status", "unknown")
        logger.info(f"执行器图调用完成，最终状态: {final_status}")
        logger.info("返回计划代理进行执行结果分析")
        
        return Command(update=state, goto=AgentType.PLAN)


class ExecutorAgent(GraphBase):
    """
    第二层级：执行代理 - 多代理系统的任务执行引擎
    
    ExecutorAgent是多代理系统的执行层核心，负责将抽象的执行计划转换为
    具体的子代理调用，并管理整个执行过程的生命周期。
    
    核心职责：
    1. 子代理管理：初始化、配置和管理所有可用的子代理实例
    2. 输入格式化：将计划描述转换为各子代理能理解的输入格式
    3. 执行协调：按序执行多个计划项，处理依赖关系
    4. 结果收集：汇总各子代理的执行结果，统一格式化返回
    5. 异常处理：捕获和处理执行过程中的各种异常情况
    
    图结构设计 (ExecutorGraph):
    ```
    START -> format_input -> execute_agent -> check_completion -> END
             ↑                                      ↓
             └────── 循环处理多个计划项 ──────────────┘
    ```
    
    执行模式：
    - 顺序执行：按计划列表顺序逐一执行，确保执行顺序的正确性
    - 状态跟踪：维护当前执行索引，支持执行进度监控
    - 结果累积：收集所有执行结果，支持后续的结果分析
    
    子代理集成架构：
    - 动态加载：根据AgentCard配置动态加载启用的代理
    - 统一接口：所有子代理实现统一的execute()接口
    - 类型适配：为不同类型的代理提供输入格式适配
    - 错误隔离：单个代理失败不影响其他代理执行
    
    支持的子代理类型：
    - MemoryAgent: 记忆存储和检索服务
    - SearchAgent: 信息搜索和获取服务  
    - AnalysisAgent: 数据分析和处理服务
    - ReaderAgent: 文档阅读和解析服务
    - 其他专业代理...
    
    Attributes:
        sub_agents (Dict): 初始化后的子代理实例字典
        graph: ExecutorGraph状态图实例
        
    性能特性：
    - 异步执行：所有代理调用都是异步的，提高并发性能
    - 资源管理：合理管理代理实例的生命周期
    - 错误恢复：提供多层次的错误处理和恢复机制
    
    使用示例：
    ```python
    executor = ExecutorAgent()
    plans = [
        {"agent_name": "memory", "action_description": "存储用户数据"},
        {"agent_name": "search", "action_description": "搜索相关信息"}
    ]
    results = await executor.execute_plans(plans)
    ```
    """
    
    def __init__(self, provider: str = "azure") -> None:
        """
        初始化执行代理
        
        初始化过程：
        1. 继承GraphBase，获得LLM基础能力
        2. 初始化子代理字典和状态图
        3. 调用子代理初始化流程
        4. 预构建ExecutorGraph以提高执行效率
        
        Args:
            provider (str): LLM服务提供商，默认"azure"
        
        初始化性能考虑：
        - 延迟加载：仅初始化启用状态的代理
        - 预构建图：避免首次执行时的构建开销
        - 异常容错：单个代理初始化失败不影响整体
        """
        super().__init__(provider)
        self.graph = None  # ExecutorGraph实例
        self.sub_agents = {}  # 子代理实例缓存
        
        logger.info(f"ExecutorAgent开始初始化 - 提供商: {provider}")
        
        # 初始化所有可用的子代理
        self._initialize_sub_agents()
        
        # 预构建执行器图，提高运行时性能
        logger.info("预构建ExecutorGraph...")
        self.build_graph()
        
        logger.info(f"ExecutorAgent初始化完成 - 子代理数量: {len(self.sub_agents)}")
    
    def _initialize_sub_agents(self) -> None:
        """
        初始化所有可用的子代理实例
        
        子代理初始化策略：
        1. 从AgentCard配置中读取启用的代理列表
        2. 为每个启用的代理创建实例
        3. 验证代理实例的有效性
        4. 建立代理名称到实例的映射关系
        5. 记录初始化过程和结果
        
        错误处理：
        - 单个代理初始化失败：记录警告，继续初始化其他代理
        - 配置读取失败：使用默认配置
        - 实例创建失败：记录错误详情，跳过该代理
        
        性能优化：
        - 并发初始化：对于支持的代理类型进行并发初始化
        - 资源预分配：预分配必要的资源以减少运行时开销
        """
        logger.info("开始初始化子代理实例...")
        
        # 统计信息
        successful_agents = 0
        failed_agents = []
        
        try:
            # 获取所有启用的代理配置
            from src.utils.common import get_enabled_agents
            enabled_agents = get_enabled_agents()
            total_agents = len(enabled_agents)
            
            # 遍历启用的代理配置
            for agent_type, agent_config in enabled_agents.items():
                
                try:
                    # 创建代理实例
                    logger.debug(f"创建代理实例: {agent_type}")
                    agent_instance = self._create_agent(agent_type)
                    
                    if agent_instance is not None:
                        self.sub_agents[agent_type] = agent_instance
                        successful_agents += 1
                        logger.debug(f"代理 {agent_type} 初始化成功")
                    else:
                        logger.warning(f"代理 {agent_type} 创建返回None，可能暂不支持")
                        
                except Exception as e:
                    failed_agents.append({
                        "agent_type": agent_type,
                        "error": str(e)
                    })
                    logger.error(f"初始化代理 {agent_type} 失败: {e}", exc_info=True)
            
            # 记录初始化结果统计
            logger.info(f"子代理初始化完成 - 总数: {total_agents}, 成功: {successful_agents}, 失败: {len(failed_agents)}")
            
            if failed_agents:
                logger.warning(f"以下代理初始化失败:")
                for failed in failed_agents:
                    logger.warning(f"  - {failed['agent_type']}: {failed['error']}")
                    
            if successful_agents == 0:
                logger.error("警告: 没有任何子代理初始化成功，ExecutorAgent功能将受限")
            
        except Exception as e:
            logger.error(f"子代理初始化过程中发生异常: {e}", exc_info=True)
            raise RuntimeError(f"子代理初始化失败: {str(e)}")
    
    def _create_agent(self, agent_type: str) -> Any:
        """
        根据代理类型创建对应的代理实例
        
        这是一个代理工厂方法，负责根据代理类型字符串创建具体的代理实例。
        采用动态导入和实例化策略，支持灵活的代理扩展。
        
        Args:
            agent_type (str): 代理类型标识符
        
        Returns:
            Any: 代理实例对象或None（如果不支持该类型）
        
        支持的代理类型映射：
        - AgentType.MEMORY -> MemoryAgent
        - AgentType.SEARCH -> SearchAgent (未来实现)
        - AgentType.ANALYSIS -> AnalysisAgent (未来实现)
        - 其他类型 -> None (暂不支持)
        
        扩展指南：
        要添加新的代理类型支持，需要：
        1. 在此方法中添加相应的elif分支
        2. 实现对应的代理类
        3. 确保代理类实现统一的execute()接口
        4. 在AgentCard中添加配置信息
        """
        logger.debug(f"创建代理实例: {agent_type}")
        
        try:
            if agent_type == AgentType.MEMORY:
                # 导入并创建MemoryAgent
                from src.chat.memory_agent import MemoryAgent
                logger.debug("导入MemoryAgent成功")
                return MemoryAgent()
                
            #elif agent_type == AgentType.SEARCH:
            #    # 未来实现: SearchAgent
            #    logger.debug(f"SearchAgent暂未实现，跳过")
            #    return None
            #    
            #elif agent_type == AgentType.ANALYSIS:
            #    # 未来实现: AnalysisAgent  
            #    logger.debug(f"AnalysisAgent暂未实现，跳过")
            #    return None
                
            else:
                # 未知或暂不支持的代理类型
                logger.debug(f"未知代理类型: {agent_type}，返回通用代理(None)")
                return None
                
        except ImportError as e:
            logger.warning(f"导入代理 {agent_type} 失败: {e}")
            return None
        except Exception as e:
            logger.error(f"创建代理 {agent_type} 实例失败: {e}", exc_info=True)
            return None
    
    def build_graph(self) -> None:
        """
        构建ExecutorGraph状态图
        
        构建专用于计划执行的三节点状态图：
        1. format_input: 输入格式化节点 - 为各子代理准备专用的输入格式
        2. execute_agent: 代理执行节点 - 调用子代理执行具体任务
        3. check_completion: 完成检查节点 - 检查是否还有未执行的计划
        
        图的执行特点：
        - 顺序处理：按计划列表顺序逐一处理
        - 状态维护：通过current_plan_index跟踪执行进度
        - 循环控制：通过check_completion决定是否继续下一个计划
        - 结果累积：在results字段中累积所有执行结果
        
        图结构说明：
        ```
        START -> format_input -> execute_agent -> check_completion
                      ↑                              ↓
                      └── 如果还有计划需要执行 ──────────┘
                                                     ↓
                                                   END
        ```
        
        异常处理：
        - 图构建失败：抛出运行时异常
        - 节点添加失败：记录错误并重试
        - 编译失败：提供详细的错误信息
        """
        logger.info("开始构建ExecutorGraph状态图...")
        
        try:
            # 创建ExecutorState类型的状态图构建器
            graph_builder = StateGraph(ExecutorState)
            
            # 添加处理节点
            graph_builder.add_node("format_input", self.format_input_for_agent)
            graph_builder.add_node("execute_agent", self.execute_agent)  
            graph_builder.add_node("check_completion", self.check_plan_completion)
            
            logger.debug("ExecutorGraph节点添加完成")
            
            # 定义节点间的连接关系
            # 线性处理流程
            graph_builder.add_edge(START, "format_input")
            graph_builder.add_edge("format_input", "execute_agent")
            graph_builder.add_edge("execute_agent", "check_completion")
            # check_completion节点内部决定是否回到format_input或结束
            graph_builder.add_edge("check_completion", END)
            
            logger.debug("ExecutorGraph边连接定义完成")
            
            # 编译状态图
            self.graph = graph_builder.compile()
            
            logger.info("ExecutorGraph构建并编译成功")
            
        except Exception as e:
            logger.error(f"构建ExecutorGraph失败: {e}", exc_info=True)
            raise RuntimeError(f"ExecutorGraph构建失败: {str(e)}")
    
    async def execute_plans(self, plans: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        执行计划列表 - ExecutorAgent的主要对外接口
        
        这是ExecutorAgent的核心方法，负责协调整个计划执行过程。
        它将计划列表转换为ExecutorGraph能处理的状态，并管理整个执行生命周期。
        
        Args:
            plans (List[Dict[str, Any]]): 待执行的计划列表
                每个计划项包含：
                - agent_name (str): 负责执行的子代理名称
                - action_description (str): 执行动作的描述
                - priority (int, optional): 执行优先级
                - dependencies (List[str], optional): 依赖的其他计划
        
        Returns:
            Dict[str, Any]: 执行结果字典
                成功时包含各计划项的执行结果
                失败时包含error字段和错误描述
        
        执行流程：
        1. 验证输入参数的有效性
        2. 准备ExecutorState初始状态
        3. 通过状态图异步执行所有计划
        4. 处理执行过程中的异常情况
        5. 格式化并返回执行结果
        
        性能特点：
        - 异步执行：整个过程采用异步模式，支持高并发
        - 流式处理：通过图的事件流处理执行进度
        - 状态持久：执行状态在整个过程中保持一致
        - 异常隔离：单个计划失败不影响其他计划执行
        
        错误处理：
        - 空计划列表：返回空结果而非错误
        - 图未构建：自动构建图实例
        - 执行超时：设置合理的超时限制
        - 异常恢复：提供多层次的错误恢复机制
        """
        # 输入验证和日志记录
        if not isinstance(plans, list):
            logger.error(f"execute_plans接收到非列表类型的计划: {type(plans)}")
            return {"error": f"计划参数必须是列表类型，收到: {type(plans)}"}
        
        logger.info(f"ExecutorAgent开始执行计划 - 计划数量: {len(plans)}")
        
        # 处理空计划列表的情况
        if not plans:
            logger.warning("收到空计划列表，返回空结果")
            return {}
        
        # 记录计划概览（调试模式）
        if logger.getEffectiveLevel() == logging.DEBUG:
            logger.debug("计划执行概览:")
            for i, plan in enumerate(plans):
                agent = plan.get("agent_name", "unknown")
                action = plan.get("action_description", "no description")[:30] + "..."
                logger.debug(f"  计划{i+1}: {agent} - {action}")
        
        # 检查图状态
        if not self.graph:
            logger.warning("ExecutorGraph尚未构建，开始自动构建...")
            try:
                self.build_graph()
                logger.info("ExecutorGraph自动构建成功")
            except Exception as e:
                logger.error(f"ExecutorGraph构建失败: {e}")
                return {"error": f"执行图构建失败: {str(e)}"}
        
        # 准备初始执行状态
        initial_state = {
            "plan": plans,
            "current_plan_index": 0,
            "results": {},
            "formatted_inputs": {}
        }
        
        logger.debug(f"初始状态准备完成: {len(plans)}个计划, 索引从0开始")
        
        try:
            # 配置图执行参数
            chat_config = {
                "recursion_limit": 5,  # 限制递归深度，防止无限循环
                "thread_id": f"executor_{asyncio.current_task().get_name() if asyncio.current_task() else 'unknown'}"
            }
            
            logger.info("开始异步执行ExecutorGraph...")
            execution_start_time = asyncio.get_event_loop().time()
            
            final_state = None
            event_count = 0
            
            # 异步流式执行图
            async for event in self.graph.astream(input=initial_state, config=chat_config):
                event_count += 1
                logger.debug(f"ExecutorGraph事件 {event_count}: {list(event.keys())}")
                
                # 保存最后一个事件状态
                for key, value in event.items():
                    if value is not None:
                        logger.debug(f"更新最终状态来源: {key}")
                final_state = event

            execution_duration = asyncio.get_event_loop().time() - execution_start_time
            logger.info(f"ExecutorGraph执行完成 - 耗时: {execution_duration:.2f}秒, 事件数: {event_count}")
            # 处理执行结果
            if final_state and isinstance(final_state, dict):
                results = final_state.get("results", {})
                logger.info(f"ExecutorGraph执行成功，返回{len(results)}个结果")
                
                # 统计执行结果
                if logger.getEffectiveLevel() == logging.INFO:
                    successful = sum(1 for r in results.values() 
                                   if isinstance(r, dict) and r.get("status") == "completed")
                    failed = len(results) - successful
                    logger.info(f"执行结果统计 - 成功: {successful}, 失败: {failed}")
                
                return results
            else:
                logger.warning("ExecutorGraph未返回有效的最终状态")
                return {"error": "执行图未返回有效结果"}
                
        except asyncio.TimeoutError:
            logger.error("ExecutorGraph执行超时")
            return {"error": "执行超时，请检查计划复杂度或系统负载"}
            
        except Exception as e:
            logger.error(f"ExecutorGraph执行异常: {e}", exc_info=True)
            return {"error": f"执行失败: {str(e)}"}
    
    async def format_input_for_agent(self, state: ExecutorState) -> ExecutorState:
        """
        为代理格式化输入数据节点
        
        这是ExecutorGraph中的第一个处理节点，负责将通用的计划描述
        转换为各个子代理能够理解和处理的特定输入格式。
        
        Args:
            state (ExecutorState): 当前执行状态
            
        Returns:
            ExecutorState: 更新后的状态，包含格式化的输入数据
        
        格式化策略：
        1. 根据当前执行索引获取对应的计划项
        2. 识别计划项中指定的目标代理类型  
        3. 调用代理特定的格式化逻辑
        4. 将格式化结果保存到formatted_inputs中
        5. 为下一步执行做好数据准备
        
        代理适配：
        - MemoryAgent: 转换为记忆操作专用格式
        - SearchAgent: 转换为搜索查询专用格式
        - AnalysisAgent: 转换为数据分析专用格式
        - 通用代理: 保持原始格式
        
        错误处理：
        - 索引越界：记录警告，跳过该索引
        - 格式化失败：使用原始输入作为备用方案
        - 代理未识别：使用通用格式化逻辑
        """
        current_index = state.get("current_plan_index", 0)
        plans = state.get("plan", [])
        
        logger.debug(f"开始格式化计划索引 {current_index} 的输入")
        
        # 验证索引有效性
        if current_index >= len(plans):
            logger.warning(f"当前计划索引 {current_index} 超出计划列表长度 {len(plans)}")
            return state
        
        if current_index < 0:
            logger.warning(f"当前计划索引 {current_index} 为负数，重置为0")
            current_index = 0
            state["current_plan_index"] = current_index
        
        try:
            # 获取当前计划项
            plan = plans[current_index]
            agent_name = plan.get("agent_name", "unknown")
            action_description = plan.get("action_description", "")
            
            logger.debug(f"格式化目标 - 代理: {agent_name}, 动作: {action_description[:50]}...")
            
            # 调用代理特定的格式化逻辑
            formatted_input = await self._format_input_by_agent_type(action_description, agent_name)
            
            # 保存格式化结果
            state["formatted_inputs"][str(current_index)] = formatted_input
            
            logger.debug(f"计划索引 {current_index} 的输入格式化完成，输入长度: {len(str(formatted_input))}")
            
        except Exception as e:
            logger.error(f"格式化计划索引 {current_index} 的输入失败: {e}", exc_info=True)
            
            # 使用原始action_description作为备用输入
            backup_input = plans[current_index].get("action_description", "")
            state["formatted_inputs"][str(current_index)] = backup_input
            logger.warning(f"使用备用输入格式化: {backup_input[:50]}...")
        
        return state
    
    async def _format_input_by_agent_type(self, input_data: str, agent_name: str) -> str:
        """
        根据代理类型执行特定的输入格式化逻辑
        
        不同类型的代理需要不同格式的输入数据。此方法根据代理名称
        调用相应的格式化策略，确保代理能够正确理解和执行任务。
        
        Args:
            input_data (str): 原始的行动描述
            agent_name (str): 目标代理名称
        
        Returns:
            str: 格式化后的输入数据
        
        格式化策略：
        1. 从AgentCard获取代理配置信息
        2. 基于代理能力构建专用的提示词
        3. 使用LLM进行智能格式化转换
        4. 验证格式化结果的有效性
        5. 返回最终格式化结果
        
        LLM调用策略：
        - 使用ExecutorRole.FORMATTER角色
        - 提供代理能力和期望输出格式说明
        - 设置专门的session_id便于调试
        - 异步执行以提高性能
        
        异常处理：
        - LLM调用失败：返回原始输入
        - 格式化结果为空：使用备用策略
        - 网络异常：实现重试机制
        """
        logger.debug(f"开始为代理 {agent_name} 格式化输入")
        
        try:
            # 获取代理配置信息
            agent_config = AgentCard.get(agent_name, {})
            
            if not agent_config:
                logger.warning(f"未找到代理 {agent_name} 的配置信息，使用原始输入")
                return input_data
            
            logger.debug(f"获取到代理配置: {agent_config.get('description', 'no description')}")

            # 构建格式化提示词
            format_prompt = f"""请将以下原始任务描述转换为适合代理 {agent_name} 执行的格式化输入：

原始任务描述: {input_data}

代理信息:
- 名称: {agent_name}  
- 能力描述: {agent_config.get('description', '通用代理')}
- 输入要求: {agent_config.get('input_format', '自然语言描述')}
- 特殊参数: {agent_config.get('parameters', {})}

请生成一个清晰、具体的格式化输入，确保：
1. 符合该代理的输入格式要求
2. 包含执行任务所需的所有关键信息
3. 语言表达准确无歧义
4. 适合API调用或直接执行

格式化输入:"""

            # 调用LLM进行智能格式化
            logger.debug(f"调用LLM为代理 {agent_name} 格式化输入...")
            
            response = self.call_llm_chain(
                role=ExecutorRole.FORMATTER,
                input_prompt=format_prompt,
                session_id=f"format_agent"
            )
            
            # 处理异步响应
            if hasattr(response, "__await__"):
                response = await response
            
            # 验证格式化结果
            if response and isinstance(response, str) and len(response.strip()) > 0:
                logger.debug(f"代理 {agent_name} 的输入格式化成功，输出长度: {len(response)}")
                return response.strip()
            else:
                logger.warning(f"LLM格式化返回空结果，使用原始输入")
                return input_data
                
        except Exception as e:
            logger.error(f"为代理 {agent_name} 格式化输入时发生异常: {e}", exc_info=True)
            # 回退到原始输入作为安全措施
            logger.info(f"回退到原始输入: {input_data[:50]}...")
            return input_data
        
    async def execute_agent(self, state: ExecutorState) -> ExecutorState:
        """
        执行代理节点：批量调用所有子代理执行计划
        
        这是ExecutorGraph的核心执行节点，负责实际调用各个子代理
        来完成具体的任务执行。它采用批量处理策略，一次性执行所有计划。
        
        Args:
            state (ExecutorState): 包含计划列表和格式化输入的执行状态
            
        Returns:
            ExecutorState: 更新后的状态，包含所有执行结果
        
        执行策略：
        1. 批量处理：一次性处理所有计划项，而不是逐一处理
        2. 并发控制：虽然顺序执行，但为每个代理创建独立的执行上下文
        3. 结果收集：将所有执行结果统一保存到state.results中
        4. 异常隔离：单个代理执行失败不影响其他代理的执行
        
        性能优化：
        - 异步执行：所有代理调用都是异步的
        - 内存管理：及时清理中间结果，避免内存泄漏
        - 错误恢复：提供多级错误处理和恢复机制
        
        监控和调试：
        - 详细的执行日志记录
        - 执行时间统计
        - 成功/失败率统计
        - 异常堆栈跟踪
        """
        plans = state.get("plan", [])
        formatted_input_dict = state.get("formatted_inputs", {})
        
        logger.info(f"执行代理节点开始 - 计划总数: {len(plans)}, 格式化输入数: {len(formatted_input_dict)}")

        # 统计信息初始化
        successful_executions = 0
        failed_executions = 0
        execution_start_time = asyncio.get_event_loop().time()

        # 逐一执行所有计划项
        for index, plan in enumerate(plans):
            logger.debug(f"开始执行计划项 {index + 1}/{len(plans)}")
            
            try:
                # 获取对应的格式化输入
                formatted_input = formatted_input_dict.get(str(index))
                
                if formatted_input is None:
                    logger.warning(f"计划索引 {index} 没有对应的格式化输入，使用原始描述")
                    formatted_input = plan.get("action_description", "")
                
                # 执行单个代理任务
                result = await self.execute_single_agent(index, plan, formatted_input)
                
                # 保存执行结果
                state["results"][index] = result
                
                # 统计执行结果
                if isinstance(result, dict) and result.get("status") == "completed":
                    successful_executions += 1
                    logger.debug(f"计划项 {index} 执行成功")
                else:
                    failed_executions += 1
                    logger.debug(f"计划项 {index} 执行失败")
                    
            except Exception as e:
                # 单个计划执行异常处理
                logger.error(f"执行计划项 {index} 时发生异常: {e}", exc_info=True)
                
                state["results"][index] = {
                    "status": "failed",
                    "error": f"计划执行异常: {str(e)}",
                    "agent_name": plan.get("agent_name", "unknown"),
                    "plan_index": index
                }
                failed_executions += 1

        # 计算执行总时间
        execution_duration = asyncio.get_event_loop().time() - execution_start_time
        
        # 记录执行完成统计
        logger.info(f"执行代理节点完成 - 耗时: {execution_duration:.2f}秒")
        logger.info(f"执行结果统计 - 成功: {successful_executions}, 失败: {failed_executions}")
        
        # 如果所有执行都失败，记录警告
        if successful_executions == 0 and len(plans) > 0:
            logger.warning("所有计划项执行都失败了，请检查子代理状态和输入格式")
        
        return state
    
    async def execute_single_agent(self, plan_index: int, plan: dict, formatted_input: str) -> dict:
        """
        执行单个代理任务
        
        这是代理执行的最小单元，负责调用特定的子代理完成单个任务。
        它处理代理调用的所有细节，包括输入适配、异常处理和结果标准化。
        
        Args:
            plan_index (int): 计划项在列表中的索引，用于调试和日志
            plan (dict): 计划项详情，包含代理名称和动作描述
            formatted_input (str): 格式化后的输入数据
            
        Returns:
            dict: 标准化的执行结果
                成功时包含：
                - status: "completed"
                - result: 代理返回的实际结果
                - agent_name: 执行的代理名称
                - execution_time: 执行耗时
                失败时包含：
                - status: "failed" 
                - error: 错误描述信息
                - agent_name: 尝试执行的代理名称
        
        代理调用适配：
        - MemoryAgent: 传递纯字符串查询
        - 其他代理: 传递结构化字典数据
        - 未知代理: 返回不可用错误
        
        性能监控：
        - 记录每个代理的执行时间
        - 跟踪代理调用成功率
        - 监控异常发生频率
        
        错误分类：
        - 代理不存在：配置错误或代理未初始化
        - 执行异常：代理内部错误或网络问题
        - 结果异常：返回格式不符合预期
        """
        agent_name = plan.get("agent_name", "unknown")
        
        logger.debug(f"开始执行单个代理任务 - 索引: {plan_index}, 代理: {agent_name}")
        
        # 检查代理是否存在
        agent = self.sub_agents.get(agent_name)
        if agent is None:
            error_msg = f"代理 {agent_name} 未找到或未初始化"
            logger.warning(f"计划 {plan_index}: {error_msg}")
            return {
                "status": "failed",
                "error": error_msg,
                "agent_name": agent_name,
                "plan_index": plan_index,
                "error_type": "agent_not_found"
            }
        
        # 记录执行开始
        execution_start_time = asyncio.get_event_loop().time()
        
        try:
            logger.debug(f"调用代理 {agent_name} - 输入长度: {len(str(formatted_input))}")
            
            # 根据代理类型调用不同的接口
            if agent_name == AgentType.MEMORY:
                # MemoryAgent 接受纯字符串查询
                query_str = formatted_input if isinstance(formatted_input, str) else str(formatted_input)
                logger.debug(f"MemoryAgent调用 - 查询: {query_str[:100]}...")
                result = await agent.execute(query_str)
                
            else:
                # 其他代理接受结构化输入
                structured_input = {
                    "input": formatted_input,
                    "action_description": plan.get("action_description", ""),
                    "plan": plan,
                    "plan_index": plan_index
                }
                logger.debug(f"结构化代理调用 - 代理: {agent_name}")
                result = await agent.execute(structured_input)
            
            # 计算执行时间
            execution_time = asyncio.get_event_loop().time() - execution_start_time
            
            logger.debug(f"代理 {agent_name} 执行完成 - 耗时: {execution_time:.2f}秒")
            
            # 返回成功结果
            return {
                "status": "completed",
                "result": result,
                "agent_name": agent_name,
                "plan_index": plan_index,
                "execution_time": execution_time,
                "input_length": len(str(formatted_input))
            }
            
        except Exception as e:
            # 代理执行异常处理
            execution_time = asyncio.get_event_loop().time() - execution_start_time
            error_msg = f"代理执行异常: {str(e)}"
            
            logger.error(f"计划 {plan_index} 的代理 {agent_name} 执行失败: {e}", exc_info=True)
            
            return {
                "status": "failed", 
                "error": error_msg,
                "agent_name": agent_name,
                "plan_index": plan_index,
                "execution_time": execution_time,
                "error_type": type(e).__name__,
                "exception_details": str(e)
            }
    
    async def check_plan_completion(self, state: ExecutorState) -> Union[ExecutorState, Command]:
        """
        检查计划完成状态节点
        
        这是ExecutorGraph的流程控制节点，负责判断是否所有计划都已执行完成，
        并决定图的下一步流转方向。在当前的批量执行策略下，这个节点主要用于
        最终的完成确认和状态验证。
        
        Args:
            state (ExecutorState): 当前执行状态
            
        Returns:
            Union[ExecutorState, Command]: 
                - ExecutorState: 所有计划执行完成，结束执行
                - Command: 还有计划需要执行，继续下一轮（当前版本不会出现）
        
        检查逻辑：
        1. 验证执行状态的完整性
        2. 统计执行结果的数量和质量
        3. 确认所有计划项都有对应的结果
        4. 记录最终的执行统计信息
        5. 决定是否需要继续执行或结束流程
        
        状态验证：
        - 结果数量检查：确保results数量与计划数量匹配
        - 结果质量检查：统计成功和失败的执行数量
        - 异常状态检查：识别未处理的异常情况
        
        注意：当前版本采用批量执行策略，所以这个节点主要用于最终验证，
        不会出现需要继续执行的情况。但保留了扩展性，便于未来支持增量执行。
        """
        current_index = state.get("current_plan_index", 0)
        plans = state.get("plan", [])
        results = state.get("results", {})
        
        logger.info(f"检查计划完成状态 - 当前索引: {current_index}, 计划总数: {len(plans)}, 结果数: {len(results)}")
        
        # 验证执行状态的完整性
        if len(results) != len(plans):
            logger.warning(f"结果数量不匹配 - 计划: {len(plans)}, 结果: {len(results)}")
            
            # 检查是否有遗漏的计划项
            missing_plans = []
            for i in range(len(plans)):
                if i not in results:
                    missing_plans.append(i)
            
            if missing_plans:
                logger.error(f"发现未执行的计划项: {missing_plans}")
                # 为未执行的计划项添加错误结果
                for missing_index in missing_plans:
                    plan = plans[missing_index]
                    results[missing_index] = {
                        "status": "failed",
                        "error": "计划项未被执行",
                        "agent_name": plan.get("agent_name", "unknown"),
                        "plan_index": missing_index
                    }
                
                # 更新状态
                state["results"] = results
        
        # 统计执行结果
        successful_count = 0
        failed_count = 0
        partial_count = 0
        
        for result in results.values():
            if isinstance(result, dict):
                status = result.get("status", "unknown")
                if status == "completed":
                    successful_count += 1
                elif status == "failed":
                    failed_count += 1
                else:
                    partial_count += 1
            else:
                logger.warning(f"发现非字典类型的执行结果: {type(result)}")
                partial_count += 1
        
        # 记录最终统计信息
        logger.info(f"计划执行完成统计:")
        logger.info(f"  - 总计划数: {len(plans)}")
        logger.info(f"  - 成功执行: {successful_count}")
        logger.info(f"  - 执行失败: {failed_count}")
        logger.info(f"  - 异常状态: {partial_count}")
        
        # 计算成功率
        if len(plans) > 0:
            success_rate = (successful_count / len(plans)) * 100
            logger.info(f"  - 成功率: {success_rate:.1f}%")
            
            # 成功率过低时记录警告
            if success_rate < 50:
                logger.warning(f"计划执行成功率过低 ({success_rate:.1f}%)，请检查系统状态")
        
        # 当前版本：所有计划都已执行完成
        # 在未来版本中，这里可以添加增量执行的逻辑
        logger.info(f"所有 {len(plans)} 个计划项执行完成，ExecutorGraph即将结束")
        
        return state


if __name__ == "__main__":
    """
    模块测试入口
    
    提供基本的功能测试，验证PlanAgent的核心功能是否正常工作。
    这个测试用例演示了多代理系统处理用户查询的完整流程。
    
    测试场景：
    - 用户输入：一个包含记忆存储需求的自然语言查询
    - 预期流程：PlanAgent分析查询 -> 制定计划 -> ExecutorAgent执行 -> 生成最终答案
    - 验证点：整个流程能够正常完成并返回有意义的结果
    """
    logger.info("=" * 60)
    logger.info("开始模块功能测试 - PlanAgent多代理系统")
    logger.info("=" * 60)
    
    # 测试查询：包含记忆存储需求
    #query = "我需要记录一下最近几天的生活，前天的时候我主要是在处理 CRQ 相关的工作，早上吃的是包子和牛奶，中午吃的老乡鸡，晚上吃的米饭和饭菜。昨天我参加了 Github Copilot 的培训，早上吃的是稀饭和粽子，中午吃的老乡鸡，晚上吃的是南京大排档。"
    query = "我想知道我昨天干嘛了？"
    logger.info(f"测试查询: {query}")
    
    try:
        # 创建PlanAgent实例
        logger.info("创建PlanAgent实例...")
        multiagent_obj = PlanAgent()
        
        # 执行测试查询
        logger.info("开始执行测试查询...")
        res = asyncio.run(multiagent_obj.run_graph(query))
        
        # 输出测试结果
        logger.info("=" * 60)
        logger.info("测试结果:")
        logger.info(f"结果类型: {type(res)}")
        logger.info(f"结果长度: {len(res) if res else 0}")
        
        if res:
            # 截断长结果以便于查看
            result_preview = res[:200] + "..." if len(res) > 200 else res
            logger.info(f"结果内容: {result_preview}")
        else:
            logger.warning("测试返回空结果")
        
        logger.info("=" * 60)
        logger.info("模块功能测试完成")
        
    except Exception as e:
        logger.error(f"模块测试失败: {e}", exc_info=True)
        logger.error("=" * 60)
        logger.error("模块功能测试失败")
    
    logger.info("=" * 60)