"""
IndexingAgent 测试文件

功能：
1. 检查PDF文档是否已经注册到DocumentRegistry
2. 如果未注册，调用IndexingAgent进行解析和索引
3. 支持批量处理PDF列表

运行方式：
    python tests/test_indexing_agent.py
"""
import sys
import os
import logging
import asyncio
from typing import List

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.agents.indexing import IndexingAgent, DocumentRegistry
from src.config.settings import PDF_PATH

# 配置日志
logging.basicConfig(
    level=logging.INFO,  # Changed to DEBUG to see detailed stage_status tracking
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


def check_pdf_exists(pdf_name: str) -> bool:
    """
    检查PDF文件是否存在于data/pdf/目录

    Args:
        pdf_name: PDF文件名（不含.pdf扩展名）

    Returns:
        bool: 文件是否存在
    """
    pdf_path = os.path.join(PDF_PATH, f"{pdf_name}.pdf")
    exists = os.path.exists(pdf_path)

    if exists:
        # 获取文件大小
        size_bytes = os.path.getsize(pdf_path)
        size_mb = size_bytes / (1024 * 1024)
        logger.info(f"✅ PDF文件存在: {pdf_name}.pdf ({size_mb:.2f} MB)")
    else:
        logger.warning(f"❌ PDF文件不存在: {pdf_path}")

    return exists


def is_document_registered(doc_registry: DocumentRegistry, pdf_name: str) -> bool:
    """
    检查文档是否已经注册

    Args:
        doc_registry: DocumentRegistry实例
        pdf_name: PDF文件名（不含扩展名）

    Returns:
        bool: 是否已注册
    """
    doc_info = doc_registry.get_by_name(pdf_name)

    if doc_info:
        logger.info(f"📋 文档已注册: {pdf_name}")
        logger.info(f"   - 文档ID: {doc_info['doc_id']}")
        logger.info(f"   - 索引路径: {doc_info.get('index_path', 'N/A')}")
        logger.info(f"   - 创建时间: {doc_info.get('created_at', 'N/A')}")
        logger.info(f"   - 简要摘要: {doc_info.get('brief_summary', 'N/A')[:100]}...")

        # 显示处理阶段状态
        if "processing_stages" in doc_info:
            stages = doc_info["processing_stages"]
            logger.info(f"   - 处理阶段:")
            for stage_name, stage_info in stages.items():
                status_emoji = "✅" if stage_info.get("status") == "completed" else "❌"
                output_count = len(stage_info.get("output_files", []))
                logger.info(f"     {status_emoji} {stage_name}: {stage_info.get('status')} ({output_count} 个文件)")

        return True
    else:
        logger.info(f"🆕 文档未注册: {pdf_name}")
        return False


async def process_single_pdf(
    indexing_agent: IndexingAgent,
    doc_registry: DocumentRegistry,
    pdf_name: str,
    force_reindex: bool = False
) -> dict:
    """
    处理单个PDF文档

    Args:
        indexing_agent: IndexingAgent实例
        doc_registry: DocumentRegistry实例
        pdf_name: PDF文件名（不含扩展名）
        force_reindex: 是否强制重新索引（即使已注册）

    Returns:
        dict: 处理结果
    """
    print_subsection(f"处理文档: {pdf_name}")

    # 1. 检查PDF文件是否存在
    if not check_pdf_exists(pdf_name):
        return {
            "pdf_name": pdf_name,
            "status": "error",
            "message": "PDF文件不存在"
        }

    # 2. 检查文档是否已注册
    is_registered = is_document_registered(doc_registry, pdf_name)

    if is_registered and not force_reindex:
        logger.info(f"⏭️  跳过已注册的文档: {pdf_name}")
        return {
            "pdf_name": pdf_name,
            "status": "skipped",
            "message": "文档已注册"
        }

    # 3. 调用IndexingAgent进行索引
    if is_registered and force_reindex:
        logger.warning(f"🔄 强制重新索引: {pdf_name}")
    else:
        logger.info(f"🚀 开始索引新文档: {pdf_name}")

    try:
        # 构建PDF完整路径
        pdf_path = os.path.join(PDF_PATH, f"{pdf_name}.pdf")

        # 调用IndexingAgent的graph
        logger.info(f"📑 调用IndexingAgent处理文档...")
        result = await indexing_agent.graph.ainvoke({
            "doc_name": pdf_name,
            "doc_path": pdf_path,
            "doc_type": "pdf",
            "status": "pending"
        })

        # 检查处理结果
        final_status = result.get("status")

        if final_status == "completed":
            logger.info(f"✅ 文档索引成功: {pdf_name}")
            logger.info(f"   - 文档ID: {result.get('doc_id')}")
            logger.info(f"   - 索引路径: {result.get('index_path')}")
            logger.info(f"   - 简要摘要: {result.get('brief_summary', '')[:150]}...")

            # 显示生成的文件
            generated_files = result.get("generated_files", {})
            logger.info(f"   - 生成的文件:")
            logger.info(f"     * 图片: {len(generated_files.get('images', []))} 个")
            logger.info(f"     * JSON: {generated_files.get('json_data', 'N/A')}")
            logger.info(f"     * 向量DB: {generated_files.get('vector_db', 'N/A')}")
            logger.info(f"     * 摘要: {len(generated_files.get('summaries', []))} 个")

            # 显示处理阶段状态
            doc_info = doc_registry.get_by_name(pdf_name)
            if doc_info and "processing_stages" in doc_info:
                stages = doc_info["processing_stages"]
                logger.info(f"   - 处理阶段:")
                for stage_name, stage_info in stages.items():
                    status_emoji = "✅" if stage_info.get("status") == "completed" else "❌"
                    logger.info(f"     {status_emoji} {stage_name}: {stage_info.get('status')}")

            return {
                "pdf_name": pdf_name,
                "status": "success",
                "doc_id": result.get("doc_id"),
                "index_path": result.get("index_path"),
                "message": "索引完成"
            }
        else:
            error_msg = result.get("error", "未知错误")
            logger.error(f"❌ 文档索引失败: {pdf_name}")
            logger.error(f"   - 错误: {error_msg}")

            return {
                "pdf_name": pdf_name,
                "status": "error",
                "message": error_msg
            }

    except Exception as e:
        logger.error(f"❌ 处理文档时发生异常: {pdf_name}")
        logger.error(f"   - 异常: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

        return {
            "pdf_name": pdf_name,
            "status": "error",
            "message": str(e)
        }


async def batch_process_pdfs(
    pdf_name_list: List[str],
    provider: str = "openai",
    pdf_preset: str = "high",
    force_reindex: bool = False
):
    """
    批量处理PDF文档列表

    Args:
        pdf_name_list: PDF文件名列表（不含扩展名）
        provider: LLM提供商 ('openai', 'azure', 'ollama')
        pdf_preset: PDF转图片质量预设 ('fast', 'balanced', 'high', 'ultra')
        force_reindex: 是否强制重新索引已注册的文档
    """
    print_section(f"批量处理PDF文档 - 共 {len(pdf_name_list)} 个")

    # 初始化IndexingAgent
    logger.info(f"🔧 初始化IndexingAgent (provider={provider}, pdf_preset={pdf_preset})...")
    indexing_agent = IndexingAgent(provider=provider, pdf_preset=pdf_preset)

    # 初始化DocumentRegistry
    logger.info(f"📋 初始化DocumentRegistry...")
    doc_registry = indexing_agent.doc_registry

    # 显示当前注册表统计
    stats = doc_registry.get_statistics()
    logger.info(f"📊 当前注册表统计:")
    logger.info(f"   - 总文档数: {stats['total_documents']}")
    logger.info(f"   - 按类型分布: {stats['by_type']}")

    # 处理结果统计
    results = {
        "success": [],
        "skipped": [],
        "error": []
    }

    # 逐个处理PDF
    for idx, pdf_name in enumerate(pdf_name_list, 1):
        logger.info(f"\n{'='*80}")
        logger.info(f"进度: {idx}/{len(pdf_name_list)}")
        logger.info(f"{'='*80}")

        result = await process_single_pdf(
            indexing_agent,
            doc_registry,
            pdf_name,
            force_reindex
        )

        # 统计结果
        status = result["status"]
        if status == "success":
            results["success"].append(result)
        elif status == "skipped":
            results["skipped"].append(result)
        else:
            results["error"].append(result)

    # 打印最终统计
    print_section("处理完成 - 统计报告")

    logger.info(f"✅ 成功索引: {len(results['success'])} 个")
    for r in results['success']:
        logger.info(f"   - {r['pdf_name']}")

    logger.info(f"\n⏭️  跳过（已注册）: {len(results['skipped'])} 个")
    for r in results['skipped']:
        logger.info(f"   - {r['pdf_name']}")

    logger.info(f"\n❌ 失败: {len(results['error'])} 个")
    for r in results['error']:
        logger.info(f"   - {r['pdf_name']}: {r['message']}")

    # 最终注册表统计
    final_stats = doc_registry.get_statistics()
    logger.info(f"\n📊 最终注册表统计:")
    logger.info(f"   - 总文档数: {final_stats['total_documents']}")
    logger.info(f"   - 按类型分布: {final_stats['by_type']}")

    return results


def get_pdf_list_from_user() -> List[str]:
    """
    从用户输入获取PDF列表

    Returns:
        List[str]: PDF名称列表（不含.pdf扩展名）
    """
    print("\n" + "="*80)
    print("  请输入要处理的PDF文件名")
    print("="*80)
    print(f"\nPDF文件应存放在: {PDF_PATH}")
    print("\n使用说明:")
    print("  - 输入PDF文件名（不含.pdf扩展名）")
    print("  - 多个文件用逗号分隔")
    print("  - 例如: document1, document2, research_paper")
    print("  - 输入 'q' 或 'quit' 退出\n")

    try:
        user_input = input("请输入PDF名称: ").strip()

        # 检查退出命令
        if user_input.lower() in ['q', 'quit', 'exit', '退出']:
            logger.info("用户取消操作")
            return []

        # 检查空输入
        if not user_input:
            logger.warning("输入为空，请重新运行并输入PDF名称")
            return []

        # 解析逗号分隔的PDF名称
        pdf_names = [name.strip() for name in user_input.split(',')]
        # 过滤掉空字符串
        pdf_names = [name for name in pdf_names if name]

        if not pdf_names:
            logger.warning("未识别到有效的PDF名称")
            return []

        logger.info(f"✅ 已识别 {len(pdf_names)} 个PDF:")
        for name in pdf_names:
            logger.info(f"   - {name}")

        return pdf_names

    except EOFError:
        logger.warning("\n检测到EOF，使用空列表")
        return []
    except KeyboardInterrupt:
        logger.warning("\n用户中断输入")
        return []


def main():
    """主测试函数"""
    print_section("IndexingAgent 测试")

    # ==================== 配置测试参数 ====================

    # 📝 在这里配置要测试的PDF列表（不含.pdf扩展名）
    pdf_name_list = [
        "1706.03762v7"
        # "example_document_1",
        # "example_document_2",
        # "research_paper",
    ]

    # 如果列表为空，提示用户输入
    if not pdf_name_list:
        logger.info("💬 PDF列表未预设，启动交互式输入...")
        pdf_name_list = get_pdf_list_from_user()

        if not pdf_name_list:
            logger.warning("⚠️  未获取到PDF列表，退出测试")
            logger.info("\n提示：你也可以直接在代码中配置pdf_name_list:")
            logger.info('    pdf_name_list = ["document1", "document2"]')
            return

    # LLM提供商配置
    provider = "openai"  # 可选: "openai", "azure", "ollama"

    # PDF转图片质量预设
    pdf_preset = "high"  # 可选: "fast", "balanced", "high", "ultra"

    # 是否强制重新索引已注册的文档
    force_reindex = False

    # ==================== 执行测试 ====================

    logger.info("📋 测试配置:")
    logger.info(f"   - PDF列表: {pdf_name_list}")
    logger.info(f"   - LLM Provider: {provider}")
    logger.info(f"   - PDF质量预设: {pdf_preset}")
    logger.info(f"   - 强制重新索引: {force_reindex}")
    logger.info(f"   - PDF目录: {PDF_PATH}")

    # 运行异步批处理
    try:
        results = asyncio.run(batch_process_pdfs(
            pdf_name_list=pdf_name_list,
            provider=provider,
            pdf_preset=pdf_preset,
            force_reindex=force_reindex
        ))

        print_section("测试完成")
        logger.info("✅ 所有测试完成！")
        logger.info(f"📊 处理结果: 成功 {len(results['success'])} | 跳过 {len(results['skipped'])} | 失败 {len(results['error'])}")

    except KeyboardInterrupt:
        logger.warning("\n⚠️  用户中断测试")
    except Exception as e:
        logger.error(f"\n❌ 测试过程中发生异常: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
