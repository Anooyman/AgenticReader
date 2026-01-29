"""
AnswerAgent 测试文件

功能：
1. 测试 AnswerAgent 的对话能力
2. 支持单轮和多轮对话测试
3. 测试不同场景：文档查询、追问、问候、元问题等
4. 显示意图分析和回答结果

运行方式：
    python tests/test_answer_agent.py
"""
import sys
import os
import logging
import asyncio
from typing import List, Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.agents.answer import AnswerAgent
from src.core.document_management import DocumentRegistry

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_section(title: str):
    """打印分隔线和标题"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def print_subsection(title: str):
    """打印子标题"""
    print("\n" + "-" * 80)
    print(f"  {title}")
    print("-" * 80 + "\n")


def check_document_indexed(doc_registry: DocumentRegistry, doc_name: str) -> bool:
    """
    检查文档是否已被索引

    Args:
        doc_registry: DocumentRegistry实例
        doc_name: 文档名称（不含扩展名）

    Returns:
        bool: 是否已索引
    """
    doc_info = doc_registry.get_by_name(doc_name)

    if doc_info:
        logger.info(f"✅ 文档已索引: {doc_name}")
        logger.info(f"   - 文档ID: {doc_info['doc_id']}")
        logger.info(f"   - 索引路径: {doc_info.get('index_path', 'N/A')}")
        logger.info(f"   - 简要摘要: {doc_info.get('brief_summary', 'N/A')[:100]}...")

        # 检查向量数据库是否存在
        index_path = doc_info.get('index_path')
        if index_path and os.path.exists(index_path):
            logger.info(f"   - ✅ 向量数据库存在")
            return True
        else:
            logger.warning(f"   - ⚠️ 向量数据库不存在: {index_path}")
            return False
    else:
        logger.warning(f"❌ 文档未索引: {doc_name}")
        logger.warning(f"   提示: 请先使用 test_indexing_agent.py 对该文档进行索引")
        return False


async def test_single_turn(
    answer_agent: AnswerAgent,
    doc_name: str,
    query: str
) -> Dict[str, Any]:
    """
    测试单轮对话

    Args:
        answer_agent: AnswerAgent实例
        doc_name: 文档名称
        query: 用户问题

    Returns:
        dict: 对话结果
    """
    print_subsection(f"单轮测试: {query}")

    try:
        logger.info(f"📝 用户问题: {query}")
        logger.info(f"📄 目标文档: {doc_name}")

        # 调用AnswerAgent的graph
        result = await answer_agent.graph.ainvoke({
            "user_query": query,
            "current_doc": doc_name,
            "needs_retrieval": False,
            "is_complete": False
        })

        # 检查结果
        is_complete = result.get("is_complete", False)
        final_answer = result.get("final_answer", "")
        needs_retrieval = result.get("needs_retrieval", False)
        analysis_reason = result.get("analysis_reason", "")
        context = result.get("context", "")

        if is_complete:
            logger.info(f"\n✅ 对话成功")
            logger.info(f"\n🤔 意图分析:")
            logger.info(f"   - 需要检索: {'是' if needs_retrieval else '否'}")
            logger.info(f"   - 分析理由: {analysis_reason}")

            if context:
                logger.info(f"\n📚 检索上下文:")
                logger.info(f"   - 上下文长度: {len(context)} 字符")
                logger.info(f"   - 上下文预览: {context[:200]}...")

            logger.info(f"\n💬 最终回答:")
            logger.info(f"{final_answer}")

            return {
                "query": query,
                "status": "success",
                "needs_retrieval": needs_retrieval,
                "analysis_reason": analysis_reason,
                "has_context": bool(context),
                "context_length": len(context) if context else 0,
                "answer": final_answer,
                "answer_length": len(final_answer)
            }
        else:
            logger.warning(f"⚠️ 对话未完成")

            return {
                "query": query,
                "status": "incomplete"
            }

    except Exception as e:
        logger.error(f"❌ 对话失败: {query}")
        logger.error(f"   - 错误: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "query": query,
            "status": "error",
            "error": str(e)
        }


async def test_multi_turn_conversation(
    doc_name: str,
    conversation_turns: List[str]
) -> Dict[str, Any]:
    """
    测试多轮对话

    Args:
        doc_name: 文档名称
        conversation_turns: 对话轮次列表（每个元素是一个用户问题）

    Returns:
        dict: 对话统计结果
    """
    print_section(f"多轮对话测试 - 文档: {doc_name}")

    # 初始化AnswerAgent（重要：使用同一个实例以保持对话上下文）
    logger.info(f"🔧 初始化AnswerAgent...")
    answer_agent = AnswerAgent(doc_name=doc_name)

    results = []

    logger.info(f"\n🚀 开始多轮对话测试 - 共 {len(conversation_turns)} 轮\n")

    for turn_idx, query in enumerate(conversation_turns, 1):
        logger.info(f"\n{'=' * 80}")
        logger.info(f"第 {turn_idx} 轮对话")
        logger.info(f"{'=' * 80}")

        result = await test_single_turn(answer_agent, doc_name, query)
        results.append(result)

        # 短暂延迟，避免请求过快
        if turn_idx < len(conversation_turns):
            await asyncio.sleep(1)

    # 打印统计
    print_section("多轮对话完成 - 统计报告")

    success_count = sum(1 for r in results if r["status"] == "success")
    retrieval_count = sum(1 for r in results if r.get("needs_retrieval", False))

    logger.info(f"📊 总体统计:")
    logger.info(f"   - 总轮次: {len(conversation_turns)}")
    logger.info(f"   - 成功: {success_count} 轮")
    logger.info(f"   - 触发检索: {retrieval_count} 轮")
    logger.info(f"   - 成功率: {success_count/len(conversation_turns)*100:.1f}%")

    logger.info(f"\n📝 对话摘要:")
    for idx, result in enumerate(results, 1):
        if result["status"] == "success":
            retrieval_icon = "🔍" if result.get("needs_retrieval") else "💭"
            logger.info(f"\n   [{retrieval_icon}] 第 {idx} 轮:")
            logger.info(f"       问题: {result['query']}")
            logger.info(f"       意图: {result.get('analysis_reason', 'N/A')}")
            logger.info(f"       回答: {result['answer'][:100]}...")
        else:
            logger.info(f"\n   [❌] 第 {idx} 轮: {result['query']} - {result.get('error', '未完成')}")

    return {
        "total_turns": len(conversation_turns),
        "success": success_count,
        "retrieval_triggered": retrieval_count,
        "results": results
    }


async def test_different_scenarios(doc_name: str):
    """
    测试不同场景

    Args:
        doc_name: 文档名称
    """
    print_section(f"场景测试 - 文档: {doc_name}")

    # 场景1：问候语（不需要检索）
    print_subsection("场景 1: 问候语")
    agent1 = AnswerAgent(doc_name=doc_name)
    await test_single_turn(agent1, doc_name, "你好")

    await asyncio.sleep(1)

    # 场景2：文档内容查询（需要检索）
    print_subsection("场景 2: 文档内容查询")
    agent2 = AnswerAgent(doc_name=doc_name)
    await test_single_turn(agent2, doc_name, "这篇文档的主要内容是什么？")

    await asyncio.sleep(1)

    # 场景3：元问题（不需要检索）
    print_subsection("场景 3: 系统功能询问")
    agent3 = AnswerAgent(doc_name=doc_name)
    await test_single_turn(agent3, doc_name, "你能做什么？")

    await asyncio.sleep(1)

    # 场景4：多轮对话（追问）
    print_subsection("场景 4: 多轮对话（初次查询 + 追问）")
    conversation = [
        "文档的结构是怎样的？",
        "能详细说说第一部分吗？",
        "谢谢"
    ]
    await test_multi_turn_conversation(doc_name, conversation)

    logger.info("\n✅ 所有场景测试完成")


def main():
    """主测试函数"""
    print_section("AnswerAgent 测试")

    # ==================== 配置测试参数 ====================

    # 📝 文档名称（必须是已经索引过的文档）
    doc_name = "1706.03762v7"  # 改为你已经索引的文档名

    # 📝 测试模式选择
    test_mode = "multi_turn"  # 可选: "single", "multi_turn", "scenarios"

    # 📝 单轮测试查询
    single_query = "这篇论文的主要内容是什么？"

    # 📝 多轮对话测试
    multi_turn_queries = [
        "你好",
        "这篇文档讲了什么内容？",
        "能详细说说 Transformer 的架构吗？",
        "它和传统的 RNN 有什么区别？",
        "谢谢你的解释"
    ]

    # ==================== 检查文档是否已索引 ====================

    logger.info("📋 检查文档索引状态...")
    doc_registry = DocumentRegistry()

    if not check_document_indexed(doc_registry, doc_name):
        logger.error(f"❌ 文档未索引，无法进行测试")
        logger.info(f"\n💡 解决方案:")
        logger.info(f"   1. 运行: python tests/test_indexing_agent.py")
        logger.info(f"   2. 输入文档名: {doc_name}")
        logger.info(f"   3. 等待索引完成后再运行本测试")
        return

    # ==================== 执行测试 ====================

    logger.info(f"\n📋 测试配置:")
    logger.info(f"   - 文档名称: {doc_name}")
    logger.info(f"   - 测试模式: {test_mode}")

    try:
        if test_mode == "single":
            # 单轮测试
            print_section("单轮对话测试")
            answer_agent = AnswerAgent(doc_name=doc_name)
            asyncio.run(test_single_turn(answer_agent, doc_name, single_query))

        elif test_mode == "multi_turn":
            # 多轮对话测试
            asyncio.run(test_multi_turn_conversation(doc_name, multi_turn_queries))

        elif test_mode == "scenarios":
            # 场景测试
            asyncio.run(test_different_scenarios(doc_name))

        else:
            logger.error(f"❌ 未知的测试模式: {test_mode}")
            logger.info(f"   支持的模式: single, multi_turn, scenarios")
            return

        print_section("测试完成")
        logger.info("✅ 所有测试完成！")

    except KeyboardInterrupt:
        logger.warning("\n⚠️ 用户中断测试")
    except Exception as e:
        logger.error(f"\n❌ 测试过程中发生异常: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
