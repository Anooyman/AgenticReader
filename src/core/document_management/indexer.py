"""
文档索引工具 - 用于索引 PDF 文档

功能：
1. 索引 PDF 文档并生成向量数据库
2. 注册到 DocumentRegistry
3. 提供命令行和函数调用两种方式

运行方式：
    python index_document.py
    或在代码中调用: await index_pdf_document(pdf_path)
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional
import os

# 注意：IndexingAgent 依赖 src.agents（会连带拉起 langgraph），为避免
# core -> agents 的模块级循环 import 边，这里不做模块级 import：
# 需要时由 _create_indexing_agent() 在函数体内延迟 import，
# 也可由调用方通过 agent_factory 参数注入自定义工厂。
from src.core.document_management import DocumentRegistry

# 获取 DATA_ROOT，如果导入失败则使用默认值
try:
    from src.config.settings import DATA_ROOT
    if DATA_ROOT is None:
        DATA_ROOT = "data"
except (ImportError, AttributeError):
    DATA_ROOT = "data"

# 确保 DATA_ROOT 是绝对路径
if not os.path.isabs(DATA_ROOT):
    # 获取项目根目录（index_document.py 的父目录的父目录的父目录）
    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent.parent
    DATA_ROOT = str(project_root / DATA_ROOT)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 调试信息
logger.debug(f"DATA_ROOT 路径: {DATA_ROOT}")


def _default_indexing_agent_factory(provider: str, pdf_preset: str):
    """
    默认的 IndexingAgent 工厂：延迟 import，保证模块级不依赖 src.agents。

    Args:
        provider: LLM 提供商
        pdf_preset: PDF 转图片质量预设

    Returns:
        IndexingAgent 实例
    """
    from src.agents.indexing import IndexingAgent  # 延迟 import：断开 core -> agents 模块级边
    return IndexingAgent(provider=provider, pdf_preset=pdf_preset)


def print_section(title: str):
    """打印分隔线和标题"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def list_available_pdfs() -> list:
    """
    列出可用的 PDF 文件

    Returns:
        list: PDF 文件名列表
    """
    if DATA_ROOT is None:
        logger.error("❌ DATA_ROOT 未定义")
        return []

    try:
        pdf_dir = Path(DATA_ROOT) / "pdf"
        if not pdf_dir.exists():
            logger.warning(f"⚠️  PDF 目录不存在: {pdf_dir}")
            logger.info(f"💡 提示: 请创建目录并将 PDF 文件放入其中")
            return []

        pdf_files = list(pdf_dir.glob("*.pdf"))
        return [f.name for f in pdf_files]
    except Exception as e:
        logger.error(f"❌ 列出 PDF 文件失败: {e}")
        logger.error(f"DATA_ROOT: {DATA_ROOT}")
        return []


def check_already_indexed(doc_name: str) -> bool:
    """
    检查文档是否已被索引

    Args:
        doc_name: 文档名称（不含扩展名）

    Returns:
        bool: 是否已索引
    """
    doc_registry = DocumentRegistry()
    doc_info = doc_registry.get_by_name(doc_name)

    if doc_info:
        index_path = doc_info.get("index_path")
        if index_path and Path(index_path).exists():
            logger.info(f"✅ 文档已索引: {doc_name}")
            logger.info(f"   - 索引路径: {index_path}")
            logger.info(f"   - 摘要: {doc_info.get('brief_summary', 'N/A')[:100]}...")
            return True

    return False


async def index_pdf_document(
    pdf_name: str,
    force_reindex: bool = False,
    provider: str = 'openai',
    pdf_preset: str = 'high',
    agent_factory=None
) -> bool:
    """
    索引 PDF 文档

    Args:
        pdf_name: PDF 文件名（包含 .pdf 扩展名）
        force_reindex: 是否强制重新索引
        provider: LLM 提供商 ('azure', 'openai', 'ollama', 'gemini')
        pdf_preset: PDF 转图片质量预设 ('fast', 'balanced', 'high', 'ultra')
        agent_factory: 可选的 agent 工厂，形如 factory(provider=..., pdf_preset=...)
            -> agent 实例。为 None 时在函数体内延迟 import 默认的 IndexingAgent，
            保持既有调用方（无需传参）的行为不变

    Returns:
        bool: 是否成功
    """
    if DATA_ROOT is None:
        logger.error("❌ DATA_ROOT 未定义")
        return False

    # 提取文档名（不含扩展名）
    doc_name = pdf_name.replace(".pdf", "")

    # 检查是否已索引
    if not force_reindex and check_already_indexed(doc_name):
        choice = input("\n文档已索引，是否重新索引？(y/n): ").strip().lower()
        if choice != 'y':
            logger.info("跳过索引")
            return True

    # 检查 PDF 文件是否存在
    try:
        pdf_path = Path(DATA_ROOT) / "pdf" / pdf_name
        if not pdf_path.exists():
            logger.error(f"❌ PDF 文件不存在: {pdf_path}")
            return False
    except Exception as e:
        logger.error(f"❌ 构建 PDF 路径失败: {e}")
        logger.error(f"DATA_ROOT: {DATA_ROOT}, pdf_name: {pdf_name}")
        return False

    logger.info(f"\n📄 开始索引文档: {pdf_name}")
    logger.info(f"   文档路径: {pdf_path}")

    try:
        # 初始化 IndexingAgent
        logger.info("\n🔧 初始化 IndexingAgent...")
        logger.info(f"   Provider: {provider}")
        logger.info(f"   PDF Preset: {pdf_preset}")
        factory = agent_factory or _default_indexing_agent_factory
        indexing_agent = factory(provider=provider, pdf_preset=pdf_preset)
        logger.info("✅ IndexingAgent 初始化完成")

        # 调用统一入口进行索引（初始 state 由 IndexingAgent.index_document 构造，
        # 含 doc_type；core 层不直接碰 agent 内部图）
        logger.info(f"\n🚀 开始索引流程...\n")
        result = await indexing_agent.index_document(
            doc_name=doc_name,
            doc_path=str(pdf_path),  # 注意：使用 doc_path 而不是 pdf_path
            doc_type="pdf",
        )

        # 检查结果
        is_complete = result.get("is_complete", False)

        if is_complete:
            logger.info(f"\n✅ 索引完成！")

            # 显示结果信息
            brief_summary = result.get("brief_summary", "")
            if brief_summary:
                logger.info(f"\n📝 文档摘要:")
                logger.info(f"{brief_summary[:300]}...")

            agenda_dict = result.get("agenda_dict", {})
            if agenda_dict:
                logger.info(f"\n📚 文档章节: {len(agenda_dict)} 个")

            logger.info(f"\n💾 文档已注册到 DocumentRegistry")
            logger.info(f"   文档名: {doc_name}")

            return True
        else:
            error_msg = result.get("error")
            logger.warning(f"⚠️  索引未完成" + (f": {error_msg}" if error_msg else ""))
            return False

    except Exception as e:
        logger.error(f"\n❌ 索引失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def select_pdf_interactive() -> Optional[str]:
    """
    交互式选择 PDF 文件

    Returns:
        Optional[str]: PDF 文件名，或 None
    """
    print_section("PDF 文件选择")

    # 获取可用的 PDF 文件
    pdf_files = list_available_pdfs()

    if not pdf_files:
        logger.warning("⚠️  data/pdf 目录下没有 PDF 文件")
        logger.info("\n💡 提示:")
        logger.info(f"   - 请将 PDF 文件放到: {Path(DATA_ROOT) / 'pdf'}")
        logger.info(f"   - 然后重新运行此程序\n")
        return None

    # 显示 PDF 文件列表
    print("可用的 PDF 文件：\n")
    for idx, pdf_file in enumerate(pdf_files, 1):
        # 检查是否已索引
        doc_name = pdf_file.replace(".pdf", "")
        indexed_status = "✓ 已索引" if check_already_indexed(doc_name) else "  未索引"
        print(f"  [{idx}] {pdf_file} {indexed_status}")

    print()

    # 用户选择
    while True:
        try:
            choice = input("请选择 PDF 文件编号 (或输入文件名): ").strip()

            # 检查是否为数字
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(pdf_files):
                    selected_pdf = pdf_files[idx - 1]
                    logger.info(f"✅ 已选择: {selected_pdf}")
                    return selected_pdf
                else:
                    print(f"❌ 编号无效，请输入 1-{len(pdf_files)} 之间的数字")
            else:
                # 检查是否为文件名
                if choice in pdf_files:
                    logger.info(f"✅ 已选择: {choice}")
                    return choice
                elif f"{choice}.pdf" in pdf_files:
                    selected_pdf = f"{choice}.pdf"
                    logger.info(f"✅ 已选择: {selected_pdf}")
                    return selected_pdf
                else:
                    print(f"❌ 文件未找到: {choice}")

        except KeyboardInterrupt:
            print("\n\n取消操作")
            return None
        except Exception as e:
            logger.error(f"❌ 选择失败: {e}")


async def main_async():
    """异步主函数"""
    print_section("PDF 文档索引工具")

    # 选择 PDF 文件
    pdf_name = select_pdf_interactive()

    if not pdf_name:
        logger.info("未选择文件，退出")
        return

    # 索引文档
    success = await index_pdf_document(pdf_name)

    if success:
        print_section("索引完成")
        logger.info("✅ 文档已成功索引并注册")
        logger.info(f"\n💡 下一步:")
        logger.info(f"   - 运行 'python main.py' 开始对话")
        logger.info(f"   - 在文档选择界面选择该文档即可\n")
    else:
        print_section("索引失败")
        logger.error("❌ 文档索引失败，请查看错误信息\n")


def main():
    """主函数"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n\n操作已取消")
    except Exception as e:
        logger.error(f"\n❌ 程序异常: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
