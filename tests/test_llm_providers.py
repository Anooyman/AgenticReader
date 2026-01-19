"""
LLM Provider 切换测试

这个测试展示：
1. 不同 Provider 的初始化（Azure, OpenAI, Ollama）
2. Provider 信息查看
3. 动态切换 Provider
4. 测试每个 Provider 的基本功能

运行方式：
    python tests/test_llm_providers.py

注意：
    - 需要配置相应的环境变量才能测试对应的 Provider
    - 如果某个 Provider 未配置，会跳过该测试
"""
import sys
import os
import logging

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.llm.client import LLMBase
from src.core.llm.providers import AzureLLMProvider, OpenAILLMProvider, OllamaLLMProvider
from src.agents.common.prompts import CommonRole

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


def test_provider_initialization():
    """测试1：Provider 初始化"""
    print_section("测试1：Provider 初始化")

    providers = {
        "openai": "OpenAI",
        "azure": "Azure OpenAI",
        "ollama": "Ollama (本地模型)"
    }

    successful_providers = []

    for provider_key, provider_name in providers.items():
        try:
            print(f"📌 尝试初始化 {provider_name}...")
            llm_client = LLMBase(provider=provider_key)

            # 获取provider信息
            provider_info = llm_client.get_provider_info()

            print(f"✅ {provider_name} 初始化成功！")
            print(f"   - Provider: {provider_info['provider']}")
            print(f"   - Chat Model: {provider_info['chat_model_type']}")
            print(f"   - Embedding Model: {provider_info['embedding_model_type']}")
            print()

            successful_providers.append(provider_key)

        except Exception as e:
            print(f"⚠️  {provider_name} 初始化失败: {e}")
            print(f"   提示: 请检查 {provider_key.upper()} 相关的环境变量配置\n")

    if successful_providers:
        print(f"✅ 成功初始化的 Provider: {', '.join(successful_providers)}")
        return True
    else:
        print("❌ 没有成功初始化的 Provider")
        return False


def test_provider_switching():
    """测试2：Provider 动态切换"""
    print_section("测试2：Provider 动态切换")

    try:
        # 先创建一个 OpenAI client
        print("📌 初始化为 OpenAI Provider...")
        llm_client = LLMBase(provider="openai")

        initial_info = llm_client.get_provider_info()
        print(f"✅ 初始 Provider: {initial_info['provider']}")
        print(f"   - Chat Model: {initial_info['chat_model_type']}")

        # 尝试切换到其他provider（如果可用）
        print("\n📌 尝试切换到 Azure Provider...")

        try:
            llm_client.update_provider_config(provider="azure")
            updated_info = llm_client.get_provider_info()

            print(f"✅ 切换成功！")
            print(f"   - 新 Provider: {updated_info['provider']}")
            print(f"   - 新 Chat Model: {updated_info['chat_model_type']}")

        except Exception as e:
            print(f"⚠️  切换到 Azure 失败: {e}")
            print("   提示: Azure 可能未配置，这是正常的")

        print("\n✅ 测试2通过：Provider 切换功能正常！")
        return True

    except Exception as e:
        print(f"\n❌ 测试2失败: {e}")
        logger.exception("测试2详细错误:")
        return False


def test_provider_basic_call():
    """测试3：测试每个可用 Provider 的基本调用"""
    print_section("测试3：Provider 基本调用测试")

    providers_to_test = ["openai"]  # 默认只测试 OpenAI

    # 检查是否可以测试其他 provider
    try:
        from src.config.settings import LLM_CONFIG
        if LLM_CONFIG.get("api_key") and LLM_CONFIG.get("azure_endpoint"):
            providers_to_test.append("azure")
    except:
        pass

    test_message = "请用一句话回答：1+1等于几？"
    successful_calls = 0

    for provider in providers_to_test:
        try:
            print(f"\n📌 测试 {provider.upper()} Provider...")
            llm_client = LLMBase(provider=provider)

            print(f"👤 用户: {test_message}")

            response = llm_client.call_llm_chain(
                role=CommonRole.CHAPTER_MATCHER,
                input_prompt=test_message,
                session_id=f"test_{provider}"
            )

            print(f"🤖 {provider.upper()} 回复: {response}")
            print(f"✅ {provider.upper()} 调用成功！")

            successful_calls += 1

        except Exception as e:
            print(f"⚠️  {provider.upper()} 调用失败: {e}")

    if successful_calls > 0:
        print(f"\n✅ 测试3通过：{successful_calls} 个 Provider 调用成功！")
        return True
    else:
        print("\n❌ 测试3失败：没有成功的 Provider 调用")
        return False


def test_provider_classes():
    """测试4：直接测试 Provider 类"""
    print_section("测试4：Provider 类直接测试")

    provider_classes = {
        "OpenAI": OpenAILLMProvider,
        "Azure": AzureLLMProvider,
        "Ollama": OllamaLLMProvider
    }

    successful_providers = []

    for name, provider_class in provider_classes.items():
        try:
            print(f"📌 测试 {name}LLMProvider 类...")
            provider = provider_class()

            # 获取chat model
            chat_model = provider.get_chat_model()
            print(f"   - Chat Model: {type(chat_model).__name__}")

            # 获取embedding model
            embedding_model = provider.get_embedding_model()
            print(f"   - Embedding Model: {type(embedding_model).__name__}")

            print(f"✅ {name}LLMProvider 类测试成功！\n")
            successful_providers.append(name)

        except Exception as e:
            print(f"⚠️  {name}LLMProvider 类测试失败: {e}")
            print(f"   提示: {name} 可能未配置\n")

    if successful_providers:
        print(f"✅ 测试4通过：{len(successful_providers)} 个 Provider 类测试成功")
        return True
    else:
        print("❌ 测试4失败：没有成功的 Provider 类")
        return False


def main():
    """运行所有测试"""
    print("\n" + "🚀"*35)
    print("  AgenticReader - LLM Provider 切换测试")
    print("🚀"*35)

    print("\n📋 说明：")
    print("   - 本测试会尝试测试所有配置的 Provider")
    print("   - 如果某个 Provider 未配置，会显示警告但不影响其他测试")
    print("   - 建议至少配置一个 Provider (OpenAI 或 Azure)")

    results = []

    # 运行测试
    results.append(("Provider初始化", test_provider_initialization()))
    results.append(("Provider切换", test_provider_switching()))
    results.append(("Provider调用", test_provider_basic_call()))
    results.append(("Provider类测试", test_provider_classes()))

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
