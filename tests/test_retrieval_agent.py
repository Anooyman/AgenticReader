"""
RetrievalAgent 测试文件

功能：
1. 检查文档是否已经被索引（通过DocumentRegistry）
2. 如果已索引，使用RetrievalAgent进行检索测试
3. 支持单个或批量查询测试
4. 显示检索结果和统计信息

运行方式：
    python tests/test_retrieval_agent.py
"""
import sys
import os
import logging
import asyncio
from typing import List, Dict, Any

import pytest

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.agents.retrieval import RetrievalAgent
from src.core.document_management import DocumentRegistry
from src.config.settings import VECTOR_DB_PATH

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_section(title):
    """打印分隔线和标题"""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")


def print_subsection(title):
    """打印子标题"""
    print("\n" + "-"*80)
    print(f"  {title}")
    print("-"*80 + "\n")


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
        logger.info(f"   - 创建时间: {doc_info.get('created_at', 'N/A')}")
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


# ==================== pytest fixtures ====================
# test_single_query 既被 pytest 当作用例收集，也被 batch_test_queries() 当普通
# 协程函数直接调用。为消除 pytest 收集后的 fixture 缺失 ERROR，这里补上 module 级
# fixture（构造方式与 batch_test_queries() 中 RetrievalAgent(doc_name=...) 一致）。
# max_iterations 带默认值，pytest 不会把它当 fixture。

DEFAULT_DOC_NAME = "1706.03762v7"  # 需事先用 test_indexing_agent.py 索引过
DEFAULT_QUERY = "这篇论文的主要内容是什么？"


@pytest.fixture(scope="module")
def doc_name() -> str:
    """被测文档名；文档尚未索引时整模块跳过（与脚本模式的前置检查一致）"""
    doc_registry = DocumentRegistry()
    if not check_document_indexed(doc_registry, DEFAULT_DOC_NAME):
        pytest.skip(f"文档 {DEFAULT_DOC_NAME} 尚未索引，跳过 RetrievalAgent 用例")
    return DEFAULT_DOC_NAME


@pytest.fixture(scope="module")
def query() -> str:
    """检索测试用的问题"""
    return DEFAULT_QUERY


@pytest.fixture(scope="module")
def retrieval_agent(doc_name: str) -> RetrievalAgent:
    """与脚本模式一致的构造方式：RetrievalAgent(doc_name=...)"""
    return RetrievalAgent(doc_name=doc_name)


async def test_single_query(
    retrieval_agent: RetrievalAgent,
    doc_name: str,
    query: str,
    max_iterations: int = 3  # 测试用较小值，生产环境使用 ProcessingLimits.MAX_RETRIEVAL_ITERATIONS
) -> Dict[str, Any]:
    """
    测试单个查询

    Args:
        retrieval_agent: RetrievalAgent实例
        doc_name: 文档名称
        query: 查询问题
        max_iterations: 最大迭代次数

    Returns:
        dict: 检索结果
    """
    print_subsection(f"检索测试: {query}")

    try:
        logger.info(f"📝 查询内容: {query}")
        logger.info(f"📄 目标文档: {doc_name}")
        logger.info(f"🔄 最大迭代: {max_iterations}")

        # 调用RetrievalAgent的graph
        result = await retrieval_agent.graph.ainvoke({
            "query": query,
            "doc_name": doc_name,
            "max_iterations": max_iterations,
            "current_iteration": 0,
            "is_complete": False,
            "thoughts": [],
            "actions": [],
            "observations": [],
            "retrieved_content": []
        })

        # 检查结果
        is_complete = result.get("is_complete", False)
        final_summary = result.get("final_summary", "")
        selected_pages = result.get("selected_pages", [])
        retrieved_content = result.get("retrieved_content", [])

        if is_complete:
            logger.info(f"\n✅ 检索成功")
            logger.info(f"\n📄 最终摘要:")
            logger.info(f"{final_summary}")
            logger.info(f"\n📑 相关页码: {selected_pages}")
            logger.info(f"\n📊 检索统计:")
            logger.info(f"   - 检索到的内容块: {len(retrieved_content)}")
            logger.info(f"   - 迭代次数: {result.get('current_iteration', 0)}")

            # 显示部分检索内容
            if retrieved_content:
                logger.info(f"\n📚 检索内容预览:")
                for idx, content in enumerate(retrieved_content[:3], 1):
                    title = content.get("title", "Unknown")
                    pages = content.get("pages", [])
                    text = content.get("content", "")[:150]
                    logger.info(f"\n   [{idx}] {title} (Pages: {pages})")
                    logger.info(f"       {text}...")

            return {
                "query": query,
                "status": "success",
                "final_summary": final_summary,
                "selected_pages": selected_pages,
                "retrieved_count": len(retrieved_content),
                "iterations": result.get('current_iteration', 0)
            }
        else:
            logger.warning(f"⚠️ 检索未完成")
            logger.warning(f"   - 原因: {result.get('reason', '未知')}")

            return {
                "query": query,
                "status": "incomplete",
                "reason": result.get('reason', '未知'),
                "iterations": result.get('current_iteration', 0)
            }

    except Exception as e:
        logger.error(f"❌ 检索失败: {query}")
        logger.error(f"   - 错误: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "query": query,
            "status": "error",
            "error": str(e)
        }


async def batch_test_queries(
    doc_name: str,
    query_list: List[str],
    provider: str = "openai",
    max_iterations: int = 3
):
    """
    批量测试查询列表

    Args:
        doc_name: 文档名称
        query_list: 查询列表
        provider: LLM提供商
        max_iterations: 最大迭代次数
    """
    print_section(f"批量检索测试 - 文档: {doc_name}")

    # 检查文档是否已索引
    logger.info(f"📋 初始化DocumentRegistry...")
    doc_registry = DocumentRegistry()

    if not check_document_indexed(doc_registry, doc_name):
        logger.error(f"❌ 文档未索引，无法进行检索测试")
        logger.info(f"\n💡 解决方案:")
        logger.info(f"   1. 运行: python tests/test_indexing_agent.py")
        logger.info(f"   2. 输入文档名: {doc_name}")
        logger.info(f"   3. 等待索引完成后再运行本测试")
        return

    # 初始化RetrievalAgent
    logger.info(f"\n🔧 初始化RetrievalAgent (provider={provider})...")
    retrieval_agent = RetrievalAgent(doc_name=doc_name)

    # 处理结果统计
    results = {
        "success": [],
        "incomplete": [],
        "error": []
    }

    # 逐个处理查询
    logger.info(f"\n🚀 开始批量检索测试 - 共 {len(query_list)} 个查询\n")

    for idx, query in enumerate(query_list, 1):
        logger.info(f"\n{'='*80}")
        logger.info(f"进度: {idx}/{len(query_list)}")
        logger.info(f"{'='*80}")

        result = await test_single_query(
            retrieval_agent,
            doc_name,
            query,
            max_iterations
        )

        # 统计结果
        status = result["status"]
        if status == "success":
            results["success"].append(result)
        elif status == "incomplete":
            results["incomplete"].append(result)
        else:
            results["error"].append(result)

    # 打印最终统计
    print_section("测试完成 - 统计报告")

    logger.info(f"✅ 检索成功: {len(results['success'])} 个")
    for r in results['success']:
        logger.info(f"\n   查询: {r['query']}")
        logger.info(f"   摘要: {r['final_summary'][:100]}...")
        logger.info(f"   页码: {r['selected_pages']}")
        logger.info(f"   迭代: {r['iterations']} 次")

    logger.info(f"\n⚠️ 未完成: {len(results['incomplete'])} 个")
    for r in results['incomplete']:
        logger.info(f"   - {r['query']}: {r['reason']}")

    logger.info(f"\n❌ 失败: {len(results['error'])} 个")
    for r in results['error']:
        logger.info(f"   - {r['query']}: {r['error']}")

    logger.info(f"\n📊 总体统计:")
    logger.info(f"   - 总查询数: {len(query_list)}")
    logger.info(f"   - 成功率: {len(results['success'])/len(query_list)*100:.1f}%")

    return results


def get_query_list_from_user() -> List[str]:
    """
    从用户输入获取查询列表

    Returns:
        List[str]: 查询列表
    """
    print("\n" + "="*80)
    print("  请输入查询问题")
    print("="*80)
    print("\n使用说明:")
    print("  - 输入查询问题")
    print("  - 多个问题用分号(;)分隔")
    print("  - 例如: 文档的主要内容是什么?; 作者是谁?")
    print("  - 输入 'q' 或 'quit' 退出\n")

    try:
        user_input = input("请输入查询: ").strip()

        # 检查退出命令
        if user_input.lower() in ['q', 'quit', 'exit', '退出']:
            logger.info("用户取消操作")
            return []

        # 检查空输入
        if not user_input:
            logger.warning("输入为空，请重新运行并输入查询")
            return []

        # 解析分号分隔的查询
        queries = [q.strip() for q in user_input.split(';')]
        # 过滤掉空字符串
        queries = [q for q in queries if q]

        if not queries:
            logger.warning("未识别到有效的查询")
            return []

        logger.info(f"✅ 已识别 {len(queries)} 个查询:")
        for query in queries:
            logger.info(f"   - {query}")

        return queries

    except EOFError:
        logger.warning("\n检测到EOF，使用空列表")
        return []
    except KeyboardInterrupt:
        logger.warning("\n用户中断输入")
        return []


def main():
    """主测试函数"""
    print_section("RetrievalAgent 测试")

    # ==================== 配置测试参数 ====================

    # 📝 文档名称（必须是已经索引过的文档）
    doc_name = "1706.03762v7"  # 改为你已经索引的文档名

    # 📝 查询列表（支持多个查询）
    query_list = [
        "这篇论文的主要主要内容是什么？",
        "第三章的详细内容是什么？",
        "本文的结构是怎样的？",
        # "Transformer模型的架构是怎样的？",
        # "作者提出了哪些创新点？",
    ]

    # 如果查询列表为空，提示用户输入
    if not query_list:
        logger.info("💬 查询列表未预设，启动交互式输入...")
        query_list = get_query_list_from_user()

        if not query_list:
            logger.warning("⚠️ 未获取到查询列表，退出测试")
            logger.info("\n提示：你也可以直接在代码中配置query_list:")
            logger.info('    query_list = ["问题1", "问题2"]')
            return

    # LLM提供商配置
    provider = "openai"  # 可选: "openai", "azure", "ollama"

    # 最大迭代次数
    max_iterations = 3

    # ==================== 执行测试 ====================

    logger.info("📋 测试配置:")
    logger.info(f"   - 文档名称: {doc_name}")
    logger.info(f"   - 查询数量: {len(query_list)}")
    logger.info(f"   - LLM Provider: {provider}")
    logger.info(f"   - 最大迭代次数: {max_iterations}")
    logger.info(f"   - 向量数据库路径: {VECTOR_DB_PATH}")

    # 运行异步批处理
    try:
        results = asyncio.run(batch_test_queries(
            doc_name=doc_name,
            query_list=query_list,
            provider=provider,
            max_iterations=max_iterations
        ))

        if results:
            print_section("测试完成")
            logger.info("✅ 所有测试完成！")
            logger.info(f"📊 处理结果: 成功 {len(results['success'])} | 未完成 {len(results['incomplete'])} | 失败 {len(results['error'])}")

    except KeyboardInterrupt:
        logger.warning("\n⚠️ 用户中断测试")
    except Exception as e:
        logger.error(f"\n❌ 测试过程中发生异常: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
