"""
LLM Client 基础功能测试

这个测试展示：
1. 初始化 LLM Client
2. 发送简单消息并查看LLM返回
3. 多轮对话测试
4. 查看会话信息

运行方式：
    python tests/test_llm_client.py
"""
import sys
import os
import logging

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.llm.client import LLMBase
from src.config.prompts.common_prompts import CommonRole

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def print_section(title):
    """打印分隔线和标题"""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70 + "\n")


def test_basic_llm_call():
    """测试1：基础LLM调用"""
    print_section("测试1：基础LLM调用")

    try:
        # 初始化LLM客户端（使用OpenAI provider）
        print("📌 初始化 LLM Client (provider=openai)...")
        llm_client = LLMBase(provider="openai")

        # 获取provider信息
        provider_info = llm_client.get_provider_info()
        print(f"✅ Provider信息:")
        print(f"   - Provider: {provider_info['provider']}")
        print(f"   - Chat Model: {provider_info['chat_model_type']}")
        print(f"   - Embedding Model: {provider_info['embedding_model_type']}")

        # 测试简单对话
        print("\n📌 发送测试消息...")
        session_id = "test_session_1"
        user_input = "你好，请用一句话介绍你自己。"

        print(f"👤 用户: {user_input}")

        response = llm_client.call_llm_chain(
            role=CommonRole.CHAPTER_MATCHER,
            input_prompt=user_input,
            session_id=session_id
        )

        print(f"🤖 AI回复: {response}")

        # 查看会话信息
        session_info = llm_client.get_session_info(session_id)
        print(f"\n📊 会话信息:")
        print(f"   - Session ID: {session_info['session_id']}")
        print(f"   - Message Count: {session_info['message_count']}")

        print("\n✅ 测试1通过：LLM成功响应！")
        return True

    except Exception as e:
        print(f"\n❌ 测试1失败: {e}")
        logger.exception("测试1详细错误:")
        return False


def test_multi_turn_conversation():
    """测试2：多轮对话"""
    print_section("测试2：多轮对话")

    try:
        llm_client = LLMBase(provider="openai")
        session_id = "test_session_2"

        # 对话轮次
        conversations = [
            "请记住这个数字：42",
            "我刚才告诉你的数字是多少？",
            "把这个数字乘以2是多少？"
        ]

        print("📌 开始多轮对话测试...\n")

        for i, user_input in enumerate(conversations, 1):
            print(f"--- 第{i}轮对话 ---")
            print(f"👤 用户: {user_input}")

            response = llm_client.call_llm_chain(
                role=CommonRole.CHAPTER_MATCHER,
                input_prompt=user_input,
                session_id=session_id
            )

            print(f"🤖 AI回复: {response}")

            # 显示当前消息数
            session_info = llm_client.get_session_info(session_id)
            print(f"📊 当前消息数: {session_info['message_count']}\n")

        print("✅ 测试2通过：多轮对话成功！")
        return True

    except Exception as e:
        print(f"\n❌ 测试2失败: {e}")
        logger.exception("测试2详细错误:")
        return False


def test_session_management():
    """测试3：会话管理"""
    print_section("测试3：会话管理")

    try:
        llm_client = LLMBase(provider="openai")

        # 创建多个会话
        sessions = ["session_A", "session_B", "session_C"]

        print("📌 创建多个独立会话...\n")

        for session_id in sessions:
            message = f"这是会话 {session_id} 的消息"
            print(f"向 {session_id} 发送: {message}")

            llm_client.call_llm_chain(
                role=CommonRole.CHAPTER_MATCHER,
                input_prompt=message,
                session_id=session_id
            )

        # 查看所有会话信息
        all_sessions_info = llm_client.get_session_info()
        print(f"\n📊 总会话信息:")
        print(f"   - 总会话数: {all_sessions_info['total_sessions']}")
        print(f"   - 会话列表: {all_sessions_info['sessions']}")

        # 查看单个会话详情
        print(f"\n📊 单个会话详情:")
        for session_id in sessions:
            info = llm_client.get_session_info(session_id)
            print(f"   - {session_id}: {info['message_count']} 条消息")

        print("\n✅ 测试3通过：会话管理成功！")
        return True

    except Exception as e:
        print(f"\n❌ 测试3失败: {e}")
        logger.exception("测试3详细错误:")
        return False


def main():
    """运行所有测试"""
    print("\n" + "🚀"*35)
    print("  AgenticReader - LLM Client 功能测试")
    print("🚀"*35)

    results = []

    # 运行测试
    results.append(("基础LLM调用", test_basic_llm_call()))
    results.append(("多轮对话", test_multi_turn_conversation()))
    results.append(("会话管理", test_session_management()))

    # 汇总结果
    print_section("测试汇总")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {test_name}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("\n🎉 所有测试通过！")
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败")


if __name__ == "__main__":
    main()
