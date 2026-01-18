#!/usr/bin/env python3
"""
重构验证脚本

快速验证 Agent 模块重构后的导入和基本功能
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_imports():
    """测试所有 Agent 的导入"""
    print("=" * 60)
    print("📦 测试1: 验证模块导入")
    print("=" * 60)

    try:
        from src.agents.indexing import IndexingAgent, IndexingState, DocumentRegistry
        print("✅ IndexingAgent 导入成功")

        from src.agents.retrieval import RetrievalAgent, RetrievalState
        print("✅ RetrievalAgent 导入成功")

        from src.agents.answer import AnswerAgent, AnswerState
        print("✅ AnswerAgent 导入成功")

        print("\n🎉 所有模块导入成功！\n")
        return True

    except Exception as e:
        print(f"\n❌ 导入失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_indexing_agent_init():
    """测试 IndexingAgent 初始化"""
    print("=" * 60)
    print("🔧 测试2: IndexingAgent 初始化")
    print("=" * 60)

    try:
        from src.agents.indexing import IndexingAgent

        # 测试初始化
        agent = IndexingAgent(provider="openai")
        print("✅ IndexingAgent 实例化成功")

        # 检查模块是否正确初始化
        assert hasattr(agent, 'utils'), "缺少 utils 模块"
        assert hasattr(agent, 'tools'), "缺少 tools 模块"
        assert hasattr(agent, 'nodes'), "缺少 nodes 模块"
        assert hasattr(agent, 'graph'), "缺少 graph"
        print("✅ 所有子模块已正确加载")

        # 检查 doc_registry
        assert hasattr(agent, 'doc_registry'), "缺少 doc_registry"
        print("✅ DocumentRegistry 已初始化")

        # 检查对外接口
        assert hasattr(agent, 'list_documents'), "缺少 list_documents 方法"
        assert hasattr(agent, 'get_document_info'), "缺少 get_document_info 方法"
        assert hasattr(agent, 'delete_document'), "缺少 delete_document 方法"
        print("✅ 对外接口方法存在")

        print("\n🎉 IndexingAgent 初始化测试通过！\n")
        return True

    except Exception as e:
        print(f"\n❌ IndexingAgent 初始化失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_retrieval_agent_init():
    """测试 RetrievalAgent 初始化"""
    print("=" * 60)
    print("🔍 测试3: RetrievalAgent 初始化")
    print("=" * 60)

    try:
        from src.agents.retrieval import RetrievalAgent

        # 测试初始化
        agent = RetrievalAgent()
        print("✅ RetrievalAgent 实例化成功")

        # 检查模块是否正确初始化
        assert hasattr(agent, 'utils'), "缺少 utils 模块"
        assert hasattr(agent, 'tools'), "缺少 tools 模块"
        assert hasattr(agent, 'nodes'), "缺少 nodes 模块"
        assert hasattr(agent, 'graph'), "缺少 graph"
        print("✅ 所有子模块已正确加载")

        # 检查检索缓存
        assert hasattr(agent, 'retrieval_data_dict'), "缺少 retrieval_data_dict"
        assert isinstance(agent.retrieval_data_dict, dict), "retrieval_data_dict 应该是字典"
        print("✅ 检索缓存已初始化")

        print("\n🎉 RetrievalAgent 初始化测试通过！\n")
        return True

    except Exception as e:
        print(f"\n❌ RetrievalAgent 初始化失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_answer_agent_init():
    """测试 AnswerAgent 初始化"""
    print("=" * 60)
    print("💬 测试4: AnswerAgent 初始化")
    print("=" * 60)

    try:
        from src.agents.answer import AnswerAgent

        # 测试初始化
        agent = AnswerAgent()
        print("✅ AnswerAgent 实例化成功")

        # 检查 graph
        assert hasattr(agent, 'graph'), "缺少 graph"
        print("✅ Graph 已构建")

        print("\n🎉 AnswerAgent 初始化测试通过！\n")
        return True

    except Exception as e:
        print(f"\n❌ AnswerAgent 初始化失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def test_graph_structure():
    """测试 Graph 结构是否正确"""
    print("=" * 60)
    print("🕸️ 测试5: Graph 结构验证")
    print("=" * 60)

    try:
        from src.agents.indexing import IndexingAgent
        from src.agents.retrieval import RetrievalAgent
        from src.agents.answer import AnswerAgent

        # 测试 IndexingAgent Graph
        indexing = IndexingAgent()
        assert indexing.graph is not None, "IndexingAgent graph 为空"
        print("✅ IndexingAgent graph 结构正常")

        # 测试 RetrievalAgent Graph
        retrieval = RetrievalAgent()
        assert retrieval.graph is not None, "RetrievalAgent graph 为空"
        print("✅ RetrievalAgent graph 结构正常")

        # 测试 AnswerAgent Graph
        answer = AnswerAgent()
        assert answer.graph is not None, "AnswerAgent graph 为空"
        print("✅ AnswerAgent graph 结构正常")

        print("\n🎉 所有 Graph 结构验证通过！\n")
        return True

    except Exception as e:
        print(f"\n❌ Graph 结构验证失败: {e}\n")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有验证测试"""
    print("\n" + "=" * 60)
    print("🚀 开始验证 Agent 模块重构")
    print("=" * 60 + "\n")

    results = []

    # 运行所有测试
    results.append(("导入测试", test_imports()))
    results.append(("IndexingAgent 初始化", test_indexing_agent_init()))
    results.append(("RetrievalAgent 初始化", test_retrieval_agent_init()))
    results.append(("AnswerAgent 初始化", test_answer_agent_init()))
    results.append(("Graph 结构验证", test_graph_structure()))

    # 汇总结果
    print("=" * 60)
    print("📊 验证结果汇总")
    print("=" * 60)

    for test_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{test_name}: {status}")

    all_passed = all(result[1] for result in results)

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉🎉🎉 所有验证测试通过！重构成功！")
        print("=" * 60 + "\n")
        print("✅ 可以安全使用重构后的代码")
        print("✅ 建议运行完整测试套件: pytest tests/")
        return 0
    else:
        print("❌ 部分验证测试失败，请检查错误信息")
        print("=" * 60 + "\n")
        print("⚠️  建议：")
        print("   1. 检查上述错误信息")
        print("   2. 恢复备份文件: mv agent.py.backup agent.py")
        print("   3. 重新执行重构")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
