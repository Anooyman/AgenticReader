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

# 显式「跳过」标记：脚本式测试没有 pytest.skip，用一个哨兵值区分「通过 / 跳过 / 失败」，
# 避免把「因缺配置没跑成」误记成通过。
SKIP = "SKIPPED"


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


def provider_skip_reason(provider: str):
    """
    检查某个 provider 的凭据是否齐备。

    返回 None 表示配置齐全、可以真实测试；返回字符串表示应当「显式跳过」的原因。
    这样缺配置时是明确的 SKIP，而不是把异常吞掉后照常打印「测试通过」（假绿）。
    """
    from src.config.settings import LLM_CONFIG, LLM_EMBEDDING_CONFIG

    if provider == "openai":
        if not (LLM_CONFIG.get("openai_api_key") or os.getenv("OPENAI_API_KEY")):
            return "OPENAI_API_KEY 未配置"
        return None

    if provider == "azure":
        # chat 侧读 LLM_CONFIG（CHAT_*），embedding 侧读 LLM_EMBEDDING_CONFIG；
        # update_provider_config 会同时构造两者，所以四项都要有值。
        missing = [name for name, value in (
            ("CHAT_API_KEY", LLM_CONFIG.get("api_key")),
            ("CHAT_AZURE_ENDPOINT", LLM_CONFIG.get("azure_endpoint")),
            ("CHAT_DEPLOYMENT_NAME", LLM_CONFIG.get("deployment_name")),
            ("EMBEDDING_API_KEY", LLM_EMBEDDING_CONFIG.get("api_key")),
        ) if not value]
        if missing:
            return "缺少 " + ", ".join(missing)
        return None

    # 其它 provider 不做凭据预判，按「配置齐全」处理，交给实际调用去验证
    return None


def test_provider_switching():
    """测试2：Provider 动态切换（真实断言，不吞异常）"""
    print_section("测试2：Provider 动态切换")

    try:
        # 起始 provider：openai。凭据缺失时显式跳过，而不是硬跑一次算「通过」
        reason = provider_skip_reason("openai")
        if reason:
            print(f"⏭️ SKIP: openai provider 未配置（{reason}），跳过动态切换测试")
            return SKIP

        print("📌 初始化为 OpenAI Provider...")
        llm_client = LLMBase(provider="openai")

        initial_info = llm_client.get_provider_info()
        print(f"✅ 初始 Provider: {initial_info['provider']}")
        print(f"   - Chat Model: {initial_info['chat_model_type']}")

        assert initial_info["provider"] == "openai", \
            f"切换前 provider 应为 openai，实际为 {initial_info['provider']}"
        # provider 实例缓存应当只含 openai，没有别的 provider 混进来
        assert set(llm_client._provider_instances) == {"openai"}, \
            f"provider 实例缓存异常: {set(llm_client._provider_instances)}"

        # 切换目标 provider 的凭据要先确认；没有就显式 SKIP（见 provider_skip_reason）
        reason = provider_skip_reason("azure")
        if reason:
            print(f"\n⏭️ SKIP: Azure 未配置（{reason}），跳过切换验证——未验证不代表通过")
            return SKIP

        print("\n📌 尝试切换到 Azure Provider...")
        llm_client.update_provider_config(provider="azure")
        updated_info = llm_client.get_provider_info()

        print(f"✅ 切换成功！")
        print(f"   - 新 Provider: {updated_info['provider']}")
        print(f"   - 新 Chat Model: {updated_info['chat_model_type']}")
        print(f"   - 新 Embedding Model: {updated_info['embedding_model_type']}")

        # 真实断言：不只是 provider 字段变了，底层模型实例也要真的换成 azure
        assert updated_info["provider"] == "azure", \
            f"切换后 provider 应为 azure，实际为 {updated_info['provider']}"
        assert "azure" in updated_info["chat_model_type"].lower(), \
            f"chat model 未随 provider 切换: {updated_info['chat_model_type']}"
        assert "azure" in updated_info["embedding_model_type"].lower(), \
            f"embedding model 未随 provider 切换: {updated_info['embedding_model_type']}"
        # 旧 provider 的实例缓存必须被清掉，否则「切换」只是字符串上的
        assert "openai" not in llm_client._provider_instances, \
            f"旧 provider 实例缓存未清理: {set(llm_client._provider_instances)}"
        assert type(llm_client._chat_model).__name__ == updated_info["chat_model_type"], \
            "懒加载缓存 _chat_model 与 provider_info 报告的类型不一致"

        print("\n✅ 测试2通过：Provider 切换功能正常（provider 字段 + 模型实例均已生效）！")
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

    passed = sum(1 for _, result in results if result is True)
    skipped = sum(1 for _, result in results if result is SKIP)
    total = len(results)

    for test_name, result in results:
        if result is True:
            status = "✅ 通过"
        elif result is SKIP:
            status = "⏭️ 跳过"
        else:
            status = "❌ 失败"
        print(f"{status} - {test_name}")

    failed = total - passed - skipped
    print(f"\n总计: {passed}/{total} 通过（跳过 {skipped}，失败 {failed}）")

    if failed:
        print("\n❌ 存在失败的测试，请查看上面的错误信息")
        return 1
    if skipped:
        print("\n⚠️  有测试因缺少 provider 配置被跳过，补上环境变量后重跑以覆盖")
        return 0
    print("\n🎉 所有测试通过！")
    return 0


if __name__ == "__main__":
    # 脚本语义：有失败时非零退出，方便 CI / 其它脚本判断（跳过的测试不算失败）
    sys.exit(main())
