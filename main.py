"""
主入口文件 - 基于 AnswerAgent 的智能对话系统

功能：
1. 支持选择文档进行对话（或不选文档进行通用对话）
2. 使用 AnswerAgent 处理所有对话
3. 自动意图分析和文档检索
4. 保持多轮对话上下文
5. 友好的交互界面

运行方式：
    python main.py
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from src.agents.answer import AnswerAgent
from src.agents.indexing import DocumentRegistry
from src.core.processing.index_document import select_pdf_interactive, index_pdf_document
from src.core.processing.manage_documents import (
    list_all_documents,
    display_document_info,
    delete_document_files
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_banner():
    """打印欢迎横幅"""
    banner = """
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║                     AgenticReader - 智能文档对话助手                        ║
║                                                                            ║
║  功能：智能文档问答、多轮对话、自动检索、上下文记忆                          ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
    """
    print(banner)


async def manage_documents_interactive():
    """交互式文档管理"""
    print("\n" + "=" * 80)
    print("  文档管理")
    print("=" * 80 + "\n")

    while True:
        # 获取所有文档
        documents = list_all_documents()

        if not documents:
            logger.warning("⚠️  没有已索引的文档")
            print("\n提示: 使用索引工具来索引新文档\n")
            break

        # 显示文档列表
        print("已索引的文档:\n")
        doc_list = list(documents.keys())

        for idx, doc_name in enumerate(doc_list, 1):
            doc_data = documents[doc_name]
            total_size = doc_data['formatted_total_size']
            print(f"  [{idx}] {doc_name} ({total_size})")

        print("\n  [0] 返回主菜单\n")

        # 用户选择
        try:
            choice = input("请选择要管理的文档编号 (或输入文档名): ").strip()

            if choice == '0':
                logger.info("返回主菜单")
                break

            # 选择文档
            selected_doc = None
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(doc_list):
                    selected_doc = doc_list[idx - 1]
            elif choice in documents:
                selected_doc = choice

            if not selected_doc:
                print(f"❌ 无效选择: {choice}")
                continue

            # 显示文档详情
            doc_data = documents[selected_doc]
            display_document_info(selected_doc, doc_data)

            # 管理选项
            print("管理选项:")
            print("  [d] 删除此文档及所有相关数据")
            print("  [b] 返回文档列表\n")

            action = input("请选择操作: ").strip().lower()

            if action == 'd':
                # 删除文档
                success = delete_document_files(selected_doc, confirm=True)
                if success:
                    print(f"\n✅ 文档 {selected_doc} 已成功删除\n")
                else:
                    print(f"\n⚠️  文档 {selected_doc} 删除未完全成功\n")
            elif action == 'b':
                continue
            else:
                print(f"❌ 无效操作: {action}")

        except KeyboardInterrupt:
            print("\n\n返回主菜单")
            break
        except Exception as e:
            logger.error(f"❌ 操作失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())


def list_indexed_documents() -> dict:
    """
    列出所有已索引的文档

    Returns:
        dict: {doc_name: doc_info}
    """
    doc_registry = DocumentRegistry()
    all_docs = doc_registry.list_all()

    indexed_docs = {}
    for doc in all_docs:
        doc_name = doc.get("doc_name") or doc.get("name")  # 兼容旧字段名
        index_path = doc.get("index_path")

        # 检查向量数据库是否存在
        if index_path and Path(index_path).exists():
            indexed_docs[doc_name] = doc

    return indexed_docs


async def select_document() -> Optional[str]:
    """
    让用户选择文档

    Returns:
        Optional[str]: 文档名称，或 None（不选文档）
    """
    print("\n" + "=" * 80)
    print("  文档选择")
    print("=" * 80 + "\n")

    # 获取已索引的文档
    indexed_docs = list_indexed_documents()

    if not indexed_docs:
        logger.warning("⚠️  当前没有已索引的文档")
        logger.info("\n💡 提示：")
        logger.info("   - 输入 'i' 启动索引工具来索引新文档")
        logger.info("   - 输入 'm' 进入文档管理（如果有其他文档数据）")
        logger.info("   - 或者输入 '0' 进入通用对话模式（不涉及特定文档）\n")

        choice = input("请选择 (i=索引, m=管理, 0=通用对话): ").strip().lower()
        if choice == 'i':
            logger.info("\n启动文档索引工具...")
            try:
                # 选择 PDF 文件
                pdf_name = select_pdf_interactive()
                if pdf_name:
                    # 索引文档
                    success = await index_pdf_document(pdf_name)
                    if success:
                        logger.info("\n✅ 索引完成，刷新文档列表...")
                        return await select_document()
                    else:
                        logger.warning("\n⚠️  索引失败，返回文档选择...")
                        return await select_document()
                else:
                    logger.info("未选择文件，返回文档选择...")
                    return await select_document()
            except Exception as e:
                logger.error(f"❌ 索引过程出错: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                logger.info("返回文档选择...")
                return await select_document()
        elif choice == 'm':
            logger.info("\n进入文档管理...")
            try:
                await manage_documents_interactive()
                # 管理完成后刷新
                return await select_document()
            except Exception as e:
                logger.error(f"❌ 文档管理出错: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                logger.info("返回文档选择...")
                return await select_document()
        elif choice == '0':
            return None
        else:
            print("再见！")
            exit(0)

    # 显示已索引的文档列表
    print("已索引的文档：\n")
    doc_list = list(indexed_docs.keys())
    for idx, doc_name in enumerate(doc_list, 1):
        doc_info = indexed_docs[doc_name]
        brief_summary = doc_info.get("brief_summary", "无摘要")[:80]
        print(f"  [{idx}] {doc_name}")
        print(f"      摘要: {brief_summary}...\n")

    print(f"  [0] 不选择文档（通用对话模式）")
    print(f"  [i] 索引新文档")
    print(f"  [m] 管理文档（查看/删除）\n")

    # 用户选择
    while True:
        try:
            choice = input("请选择文档编号 (或输入文档名, i=索引, m=管理): ").strip()

            # 检查是否选择管理文档
            if choice.lower() == 'm':
                logger.info("\n进入文档管理...")
                try:
                    await manage_documents_interactive()
                    # 管理完成后刷新列表
                    logger.info("\n刷新文档列表...")
                    return await select_document()
                except Exception as e:
                    logger.error(f"❌ 文档管理出错: {e}")
                    import traceback
                    logger.debug(traceback.format_exc())
                    continue

            # 检查是否选择索引新文档
            if choice.lower() == 'i':
                logger.info("\n启动文档索引工具...")
                try:
                    # 选择 PDF 文件
                    pdf_name = select_pdf_interactive()
                    if pdf_name:
                        # 索引文档
                        success = await index_pdf_document(pdf_name)
                        if success:
                            logger.info("\n✅ 索引完成，刷新文档列表...")
                            # 递归调用 select_document 重新选择
                            return await select_document()
                        else:
                            logger.warning("\n⚠️  索引失败")
                            continue
                    else:
                        logger.info("未选择文件")
                        continue
                except Exception as e:
                    logger.error(f"❌ 索引过程出错: {e}")
                    import traceback
                    logger.debug(traceback.format_exc())
                    continue

            # 检查是否选择通用模式
            if choice == '0':
                logger.info("✅ 已进入通用对话模式（不绑定特定文档）")
                return None

            # 检查是否为数字
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(doc_list):
                    selected_doc = doc_list[idx - 1]
                    logger.info(f"✅ 已选择文档: {selected_doc}")
                    return selected_doc
                else:
                    print(f"❌ 编号无效，请输入 0-{len(doc_list)} 之间的数字")
            else:
                # 检查是否为文档名
                if choice in indexed_docs:
                    logger.info(f"✅ 已选择文档: {choice}")
                    return choice
                else:
                    print(f"❌ 文档未找到: {choice}")

        except KeyboardInterrupt:
            print("\n\n再见！")
            exit(0)
        except Exception as e:
            logger.error(f"❌ 选择失败: {e}")


async def chat_loop(answer_agent: AnswerAgent, doc_name: Optional[str]):
    """
    对话循环

    Args:
        answer_agent: AnswerAgent实例
        doc_name: 文档名称（None表示通用模式）
    """
    print("\n" + "=" * 80)
    print("  开始对话")
    print("=" * 80 + "\n")

    if doc_name:
        print(f"📄 当前文档: {doc_name}")
    else:
        print("💬 通用对话模式（未绑定特定文档）")

    print("\n💡 提示：")
    print("   - 输入问题开始对话")
    print("   - 输入 'quit', 'exit', '退出', '再见' 结束对话")
    print("   - 输入 'clear' 清空对话历史\n")

    print("=" * 80 + "\n")

    turn_count = 0

    while True:
        try:
            # 获取用户输入
            user_input = input("\n👤 You: ").strip()

            # 检查退出命令
            if user_input.lower() in ["quit", "exit", "退出", "再见", "bye"]:
                print("\n🤖 Assistant: 再见！期待下次与您对话。\n")
                break

            # 检查清空历史命令
            if user_input.lower() == "clear":
                # 重新初始化 agent（清空历史）
                logger.info("🔄 清空对话历史...")
                # 返回 True 表示需要重新初始化
                return True

            # 检查空输入
            if not user_input:
                print("⚠️  请输入问题")
                continue

            turn_count += 1
            logger.info(f"\n{'=' * 80}")
            logger.info(f"第 {turn_count} 轮对话")
            logger.info(f"{'=' * 80}\n")

            # 调用 AnswerAgent
            result = await answer_agent.graph.ainvoke({
                "user_query": user_input,
                "current_doc": doc_name,
                "needs_retrieval": False,
                "is_complete": False
            })

            # 提取回答
            final_answer = result.get("final_answer", "")
            needs_retrieval = result.get("needs_retrieval", False)
            analysis_reason = result.get("analysis_reason", "")

            # 显示意图分析（仅在 DEBUG 模式）
            if logger.level == logging.DEBUG:
                logger.debug(f"\n🤔 意图分析:")
                logger.debug(f"   - 需要检索: {'是' if needs_retrieval else '否'}")
                logger.debug(f"   - 理由: {analysis_reason}")

            # 显示回答
            print(f"\n🤖 Assistant: {final_answer}")

        except KeyboardInterrupt:
            print("\n\n🤖 Assistant: 再见！期待下次与您对话。\n")
            break
        except Exception as e:
            logger.error(f"\n❌ 对话出错: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            print(f"\n❌ 抱歉，处理您的问题时出现错误: {str(e)}\n")

    return False  # 正常退出，不需要重新初始化


async def main_async():
    """异步主函数"""
    print_banner()

    # 步骤1：选择文档
    doc_name = await select_document()

    # 步骤2：初始化 AnswerAgent
    logger.info("\n🔧 初始化 AnswerAgent...")
    answer_agent = AnswerAgent(doc_name=doc_name)
    logger.info("✅ AnswerAgent 初始化完成\n")

    # 步骤3：进入对话循环
    while True:
        should_restart = await chat_loop(answer_agent, doc_name)

        if should_restart:
            # 重新初始化 agent
            logger.info("🔧 重新初始化 AnswerAgent...")
            answer_agent = AnswerAgent(doc_name=doc_name)
            logger.info("✅ AnswerAgent 重新初始化完成\n")
        else:
            # 正常退出
            break


def main():
    """
    主入口函数
    """
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
