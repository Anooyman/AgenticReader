"""
多PDF智能问答系统 - 自动化测试套件

功能：
1. 测试元数据提取和向量数据库
2. 测试文档选择器
3. 测试跨文档检索完整流程
4. 测试单文档模式向后兼容性

注意：
- 日常使用请运行 main.py
- 此文件仅用于自动化测试和验证

运行方式：
    python test_multi_pdf.py
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import List, Dict, Any

import pytest

from src.agents.answer import AnswerAgent
from src.core.document_management import DocumentRegistry
from src.core.vector_db.metadata_db import MetadataVectorDB

# 配置日志 - 使用 INFO 级别
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_banner():
    """打印测试横幅"""
    banner = """
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║              AgenticReader - 多PDF系统自动化测试套件                        ║
║                                                                            ║
║  用途：测试和验证多PDF检索系统的各项功能                                    ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
    """
    print(banner)


def print_section(title: str):
    """打印章节标题"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def list_indexed_documents() -> Dict[str, Any]:
    """
    列出所有已索引的文档

    Returns:
        Dict[str, Any]: {doc_name: doc_info}
    """
    doc_registry = DocumentRegistry()
    all_docs = doc_registry.list_all()

    indexed_docs = {}
    for doc in all_docs:
        doc_name = doc.get("doc_name") or doc.get("name")
        index_path = doc.get("index_path")
        if index_path and Path(index_path).exists():
            indexed_docs[doc_name] = doc

    return indexed_docs


async def test_metadata_extraction():
    """
    测试1: 元数据提取和存储

    检查已索引文档的元数据是否已正确提取并存储到向量数据库
    """
    print_section("测试1: 元数据提取和向量数据库")

    try:
        # 获取所有已索引文档
        doc_registry = DocumentRegistry()
        all_docs = doc_registry.list_all()

        print(f"📊 文档注册表统计:")
        print(f"   - 总文档数: {len(all_docs)}")

        # 检查元数据增强字段
        has_metadata = 0
        for doc in all_docs:
            doc_name = doc.get("doc_name")
            metadata_enhanced = doc.get("metadata_enhanced")

            if metadata_enhanced:
                has_metadata += 1
                print(f"\n✅ 文档: {doc_name}")
                print(f"   - 标题: {metadata_enhanced.get('title', 'N/A')}")
                print(f"   - 关键词: {len(metadata_enhanced.get('keywords', []))} 个")
                print(f"   - 主题: {len(metadata_enhanced.get('topics', []))} 个")
                print(f"   - 关键词: {', '.join(metadata_enhanced.get('keywords', [])[:5])}...")
            else:
                print(f"\n⚠️  文档: {doc_name}")
                print(f"   - 缺少 metadata_enhanced 字段（可能是旧索引）")

        if len(all_docs) > 0:
            print(f"\n📊 元数据提取覆盖率: {has_metadata}/{len(all_docs)} ({has_metadata/len(all_docs)*100:.1f}%)")

        # 检查元数据向量数据库
        print(f"\n🔍 检查元数据向量数据库...")
        metadata_db = MetadataVectorDB()
        stats = metadata_db.get_stats()

        print(f"📊 向量数据库统计:")
        print(f"   - 索引路径: {stats['index_path']}")
        print(f"   - 索引存在: {stats['index_exists']}")
        print(f"   - 文档数量: {stats['total_documents']}")

        if stats['index_exists'] and stats['total_documents'] > 0:
            print(f"\n✅ 元数据向量数据库正常")
        else:
            print(f"\n⚠️  元数据向量数据库可能未正确初始化")

        return True

    except Exception as e:
        logger.error(f"❌ 测试1失败: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return False


async def test_document_selector():
    """
    测试2: 文档选择器

    测试 DocumentSelector 能否正确选择相关文档
    """
    print_section("测试2: 文档选择器")

    try:
        from src.agents.answer.components import DocumentSelector

        # 初始化
        doc_registry = DocumentRegistry()
        metadata_db = MetadataVectorDB()

        # 检查是否有足够的文档用于测试
        all_docs = doc_registry.list_all()
        if len(all_docs) < 2:
            print(f"⚠️  文档数量不足（当前: {len(all_docs)} 个），建议至少索引2个文档进行测试")
            print(f"💡 您可以先索引更多文档，然后再运行此测试")
            return False

        print(f"📊 当前已索引 {len(all_docs)} 个文档")

        # 测试查询列表
        test_queries = [
            "transformer 模型架构",
            "深度学习 优化算法",
            "自然语言处理 应用",
        ]

        print(f"\n🔍 测试文档选择（{len(test_queries)} 个查询）...\n")

        # 创建 AnswerAgent 获取 LLM 实例
        answer_agent = AnswerAgent()
        selector = DocumentSelector(answer_agent.llm, doc_registry)

        for idx, query in enumerate(test_queries, 1):
            print(f"\n{'─' * 80}")
            print(f"查询 {idx}: {query}")
            print(f"{'─' * 80}")

            # 测试选择
            selected = await selector.select_relevant_documents(
                query=query,
                max_docs=3
            )

            if selected:
                print(f"\n✅ 选择了 {len(selected)} 个文档:")
                for doc in selected:
                    print(f"   - {doc['doc_name']} (相似度: {doc['similarity_score']:.3f})")
            else:
                print(f"\n⚠️  未找到相关文档")

        print(f"\n✅ 文档选择器测试完成")
        return True

    except Exception as e:
        logger.error(f"❌ 测试2失败: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return False


async def test_cross_doc_retrieval(test_query: str = None):
    """
    测试3: 跨文档检索

    测试完整的跨文档问答流程

    Args:
        test_query: 测试查询（如果为None，使用默认查询）
    """
    print_section("测试3: 跨文档检索完整流程")

    try:
        # 检查文档数量
        indexed_docs = list_indexed_documents()
        if len(indexed_docs) < 2:
            print(f"⚠️  文档数量不足（当前: {len(indexed_docs)} 个）")
            print(f"💡 建议至少索引2个文档以测试跨文档检索功能")
            return False

        print(f"📊 当前已索引 {len(indexed_docs)} 个文档:")
        for idx, (doc_name, doc) in enumerate(indexed_docs.items(), 1):
            brief = doc.get("brief_summary", "")[:60]
            print(f"   {idx}. {doc_name}")
            print(f"      {brief}...")

        # 获取测试查询
        if test_query is None:
            test_query = "这些文档的主要内容是什么？"

        print(f"\n🔍 测试查询: {test_query}")

        # 初始化 AnswerAgent（不指定 doc_name，启用跨文档模式）
        logger.info("\n🔧 初始化 AnswerAgent（跨文档模式）...")
        answer_agent = AnswerAgent(doc_name=None)
        logger.info("✅ AnswerAgent 初始化完成")

        # 执行查询
        logger.info(f"\n🚀 开始跨文档检索...")
        result = await answer_agent.graph.ainvoke({
            "user_query": test_query,
            "current_doc": None,  # 触发跨文档模式
            "needs_retrieval": False,
            "is_complete": False
        })

        # 提取结果
        final_answer = result.get("final_answer", "")
        retrieval_mode = result.get("retrieval_mode", "")
        selected_documents = result.get("selected_documents", [])
        multi_doc_results = result.get("multi_doc_results", {})

        # 显示结果
        print(f"\n" + "=" * 80)
        print(f"  检索结果")
        print(f"=" * 80)

        print(f"\n📊 检索模式: {retrieval_mode}")

        if selected_documents:
            print(f"\n📚 选择的文档 ({len(selected_documents)} 个):")
            for doc in selected_documents:
                print(f"   - {doc['doc_name']} (相似度: {doc.get('similarity_score', 'N/A')})")

        if multi_doc_results:
            print(f"\n🔍 检索结果统计:")
            success_count = sum(1 for r in multi_doc_results.values() if r.get("is_complete", False))
            print(f"   - 成功: {success_count}/{len(multi_doc_results)}")

        print(f"\n🤖 最终答案:")
        print(f"{'─' * 80}")
        print(final_answer)
        print(f"{'─' * 80}")

        print(f"\n✅ 跨文档检索测试完成")
        return True

    except Exception as e:
        logger.error(f"❌ 测试3失败: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return False


async def test_single_doc_compatibility():
    """
    测试4: 向后兼容性

    测试单文档模式是否仍然正常工作
    """
    print_section("测试4: 向后兼容性（单文档模式）")

    try:
        # 获取第一个文档
        indexed_docs = list_indexed_documents()
        if len(indexed_docs) == 0:
            print(f"⚠️  没有已索引的文档")
            return False

        # 获取第一个文档名
        test_doc = next(iter(indexed_docs.keys()))
        print(f"📄 测试文档: {test_doc}")

        # 初始化 AnswerAgent（指定 doc_name，单文档模式）
        logger.info(f"\n🔧 初始化 AnswerAgent（单文档模式）...")
        answer_agent = AnswerAgent(doc_name=test_doc)
        logger.info("✅ AnswerAgent 初始化完成")

        # 测试查询
        test_query = "这个文档的主要内容是什么？"
        print(f"\n🔍 测试查询: {test_query}")

        # 执行查询
        logger.info(f"\n🚀 开始单文档检索...")
        result = await answer_agent.graph.ainvoke({
            "user_query": test_query,
            "current_doc": test_doc,
            "needs_retrieval": False,
            "is_complete": False
        })

        # 提取结果
        final_answer = result.get("final_answer", "")
        retrieval_mode = result.get("retrieval_mode", "")

        # 显示结果
        print(f"\n" + "=" * 80)
        print(f"  检索结果")
        print(f"=" * 80)

        print(f"\n📊 检索模式: {retrieval_mode}")
        print(f"\n🤖 最终答案:")
        print(f"{'─' * 80}")
        print(final_answer)
        print(f"{'─' * 80}")

        print(f"\n✅ 向后兼容性测试完成（单文档模式正常工作）")
        return True

    except Exception as e:
        logger.error(f"❌ 测试4失败: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return False


async def run_all_tests():
    """运行所有自动化测试"""
    print_section("运行所有自动化测试")

    results = {}

    # 测试1: 元数据提取
    results["metadata_extraction"] = await test_metadata_extraction()

    # 测试2: 文档选择器
    results["document_selector"] = await test_document_selector()

    # 测试3: 跨文档检索
    results["cross_doc_retrieval"] = await test_cross_doc_retrieval(
        test_query="这些文档的主要内容和核心概念是什么？"
    )

    # 测试4: 向后兼容性
    results["single_doc_compatibility"] = await test_single_doc_compatibility()

    # 显示测试总结
    print_section("测试总结")

    print(f"测试结果:")
    for test_name, success in results.items():
        status = "✅ 通过" if success else "❌ 失败"
        print(f"   - {test_name}: {status}")

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n总计: {passed}/{total} 通过 ({passed/total*100:.1f}%)")


@pytest.mark.skipif(
    os.environ.get("RUN_INTERACTIVE_TESTS") != "1",
    reason="交互式菜单需要 stdin 输入，只在 RUN_INTERACTIVE_TESTS=1 时手工运行",
)
async def test_menu():
    """测试菜单（交互式，依赖 input()，默认跳过）"""
    while True:
        print("\n" + "=" * 80)
        print("  测试菜单")
        print("=" * 80 + "\n")

        print("请选择测试模式:\n")
        print("  [1] 运行所有自动化测试")
        print("  [2] 测试元数据提取")
        print("  [3] 测试文档选择器")
        print("  [4] 测试跨文档检索")
        print("  [5] 测试单文档兼容性")
        print("  [0] 退出\n")

        try:
            choice = input("请选择 [0-5]: ").strip()

            if choice == "0":
                print("\n再见！")
                break
            elif choice == "1":
                await run_all_tests()
                input("\n按回车键继续...")
            elif choice == "2":
                await test_metadata_extraction()
                input("\n按回车键继续...")
            elif choice == "3":
                await test_document_selector()
                input("\n按回车键继续...")
            elif choice == "4":
                await test_cross_doc_retrieval()
                input("\n按回车键继续...")
            elif choice == "5":
                await test_single_doc_compatibility()
                input("\n按回车键继续...")
            else:
                print("❌ 无效选择")

        except KeyboardInterrupt:
            print("\n\n再见！")
            break
        except Exception as e:
            logger.error(f"❌ 测试出错: {e}")
            import traceback
            logger.error(traceback.format_exc())
            input("\n按回车键继续...")


async def main_async():
    """异步主函数"""
    print_banner()
    print("\n💡 提示：日常使用请运行 main.py，此文件仅用于自动化测试\n")
    await test_menu()


def main():
    """主入口函数"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n\n再见！")
    except Exception as e:
        logger.error(f"\n❌ 程序异常: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
