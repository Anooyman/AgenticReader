"""
测试 AnswerAgent 的手动选择模式

演示如何使用手动选择模式指定多个文档进行检索
"""

import asyncio
import logging
from src.agents import AnswerAgent

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def test_manual_selection_mode():
    """测试手动选择模式"""

    logger.info("=" * 80)
    logger.info("🧪 测试 AnswerAgent 手动选择模式")
    logger.info("=" * 80)

    # 1. 创建 AnswerAgent（不指定文档）
    answer_agent = AnswerAgent(doc_name=None)

    # 2. 查看所有可用文档
    available_docs = answer_agent.get_available_documents()
    logger.info(f"\n📚 可用文档列表（共 {len(available_docs)} 个）:")
    for doc in available_docs:
        logger.info(f"   - {doc['doc_name']} ({doc['doc_type']})")
        logger.info(f"     简介: {doc['brief_summary'][:100]}..." if len(doc['brief_summary']) > 100 else f"     简介: {doc['brief_summary']}")

    if len(available_docs) == 0:
        logger.warning("⚠️  没有可用文档，请先索引一些文档")
        return

    # 3. 手动选择文档（这里演示选择前2个文档）
    # 在实际应用中，这些文档名应该由用户通过UI选择
    manual_selected_docs = [doc["doc_name"] for doc in available_docs[:min(2, len(available_docs))]]

    logger.info(f"\n✅ 手动选择了 {len(manual_selected_docs)} 个文档:")
    for doc_name in manual_selected_docs:
        logger.info(f"   - {doc_name}")

    # 4. 验证选择的文档
    valid_docs, invalid_docs = answer_agent.validate_manual_selected_docs(manual_selected_docs)
    logger.info(f"\n🔍 文档验证结果:")
    logger.info(f"   - 有效文档: {len(valid_docs)} 个")
    logger.info(f"   - 无效文档: {len(invalid_docs)} 个")

    if invalid_docs:
        logger.warning(f"   - 无效文档列表: {invalid_docs}")

    if len(valid_docs) == 0:
        logger.error("❌ 没有有效的文档可以使用")
        return

    # 5. 构建状态，使用手动选择模式
    state = {
        "user_query": "这些文档的主要内容是什么？请总结它们的核心观点。",
        "current_doc": None,  # 跨文档模式
        "manual_selected_docs": valid_docs,  # 手动选择的文档列表
        "needs_retrieval": True,  # 需要检索
        "is_complete": False
    }

    logger.info(f"\n🚀 开始执行手动选择模式查询:")
    logger.info(f"   - 查询: {state['user_query']}")
    logger.info(f"   - 选择的文档: {valid_docs}")

    # 6. 执行查询
    try:
        result = await answer_agent.graph.ainvoke(state)

        logger.info("\n" + "=" * 80)
        logger.info("✅ 查询完成")
        logger.info("=" * 80)
        logger.info(f"\n📝 最终答案:\n{result['final_answer']}\n")
        logger.info(f"🔧 使用的检索模式: {result.get('retrieval_mode', 'unknown')}")
        logger.info(f"📚 实际检索的文档数: {len(result.get('multi_doc_results', {}))}")

    except Exception as e:
        logger.error(f"❌ 查询执行失败: {e}")
        import traceback
        logger.error(traceback.format_exc())


async def test_mode_comparison():
    """对比三种模式的使用方式"""

    logger.info("\n" + "=" * 80)
    logger.info("📊 三种检索模式对比")
    logger.info("=" * 80)

    answer_agent = AnswerAgent(doc_name=None)
    available_docs = answer_agent.get_available_documents()

    if len(available_docs) == 0:
        logger.warning("⚠️  没有可用文档")
        return

    query = "文档的主要内容是什么？"

    # 模式 1: 单文档模式
    logger.info("\n1️⃣  单文档模式:")
    logger.info("   初始化: AnswerAgent(doc_name='specific_doc')")
    logger.info("   State: {'user_query': query, 'current_doc': 'specific_doc'}")
    logger.info("   路由: analyze → retrieve_single → generate")

    # 模式 2: 跨文档自动选择模式
    logger.info("\n2️⃣  跨文档自动选择模式:")
    logger.info("   初始化: AnswerAgent(doc_name=None)")
    logger.info("   State: {'user_query': query, 'current_doc': None}")
    logger.info("   路由: analyze → select_docs → rewrite_queries → retrieve_multi → synthesize → generate")

    # 模式 3: 跨文档手动选择模式（新增）
    logger.info("\n3️⃣  跨文档手动选择模式（新增）:")
    logger.info("   初始化: AnswerAgent(doc_name=None)")
    logger.info("   State: {'user_query': query, 'current_doc': None, 'manual_selected_docs': ['doc1', 'doc2']}")
    logger.info("   路由: analyze → rewrite_queries → retrieve_multi → synthesize → generate")
    logger.info("   优势: 跳过自动选择步骤，用户完全控制检索范围")


def main():
    """主函数"""
    logger.info("🎯 开始测试手动选择模式\n")

    # 运行测试
    asyncio.run(test_manual_selection_mode())

    # 运行模式对比
    asyncio.run(test_mode_comparison())

    logger.info("\n✅ 测试完成")


if __name__ == "__main__":
    main()
