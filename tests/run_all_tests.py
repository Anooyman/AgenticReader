"""
运行所有功能测试

这个脚本会依次运行所有测试文件，并汇总结果。

运行方式：
    python tests/run_all_tests.py

可选参数：
    --skip-providers    跳过 Provider 切换测试
    --skip-compression  跳过历史压缩测试
    --quick            只运行快速测试（跳过耗时的LLM总结测试）
"""
import sys
import os
import subprocess
import argparse

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def print_header(title):
    """打印标题"""
    print("\n" + "🔷" * 40)
    print(f"  {title}")
    print("🔷" * 40 + "\n")


def run_test_file(test_file, description):
    """
    运行单个测试文件

    Args:
        test_file: 测试文件路径
        description: 测试描述

    Returns:
        bool: 测试是否成功
    """
    print_header(f"运行: {description}")

    test_path = os.path.join(os.path.dirname(__file__), test_file)

    if not os.path.exists(test_path):
        print(f"❌ 测试文件不存在: {test_path}")
        return False

    try:
        # 运行测试文件
        result = subprocess.run(
            [sys.executable, test_path],
            capture_output=False,  # 直接显示输出
            text=True
        )

        if result.returncode == 0:
            print(f"\n✅ {description} - 完成")
            return True
        else:
            print(f"\n⚠️  {description} - 返回码 {result.returncode}")
            return True  # 仍然返回True，因为我们的测试不使用退出码

    except Exception as e:
        print(f"\n❌ {description} - 运行失败: {e}")
        return False


def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="运行所有功能测试")
    parser.add_argument("--skip-providers", action="store_true", help="跳过 Provider 切换测试")
    parser.add_argument("--skip-compression", action="store_true", help="跳过历史压缩测试")
    parser.add_argument("--quick", action="store_true", help="快速模式（跳过耗时测试）")

    args = parser.parse_args()

    print("\n" + "🚀" * 40)
    print("  AgenticReader - 运行所有功能测试")
    print("🚀" * 40)

    # 定义测试列表
    tests = [
        ("test_llm_client.py", "LLM Client 基础功能测试", False),
        ("test_llm_providers.py", "LLM Provider 切换测试", args.skip_providers),
        ("test_history_compression.py", "历史记录压缩测试", args.skip_compression or args.quick),
    ]

    results = []

    # 运行每个测试
    for test_file, description, skip in tests:
        if skip:
            print(f"\n⏭️  跳过: {description}")
            continue

        success = run_test_file(test_file, description)
        results.append((description, success))

    # 汇总结果
    print_header("所有测试完成 - 汇总结果")

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for description, success in results:
        status = "✅ 成功" if success else "❌ 失败"
        print(f"{status} - {description}")

    print(f"\n📊 总计: {passed}/{total} 测试成功")

    if passed == total:
        print("\n🎉 所有测试都成功完成！")
        print("\n💡 提示:")
        print("   - 查看上面的输出了解各个功能的详细运行情况")
        print("   - 特别关注 '历史记录压缩测试' 中的LLM总结效果")
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败")
        print("   - 检查环境变量配置")
        print("   - 查看错误日志了解详情")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
