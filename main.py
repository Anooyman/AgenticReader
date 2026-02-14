"""
主入口文件 - 基于 AnswerAgent 的智能对话系统

功能：
1. 单文档对话模式（选择特定文档）
2. 跨文档智能对话模式（自动选择相关文档）
3. 跨文档手动选择模式（手动指定多个文档）- 新增
4. 文档索引和管理
5. 自动意图分析和文档检索
6. 保持多轮对话上下文
7. 模式切换支持

运行方式：
    python main.py
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from src.agents.answer import AnswerAgent
from src.agents.search import SearchAgent
from src.core.document_management import DocumentRegistry
from src.core.document_management.indexer import select_pdf_interactive, index_pdf_document
from src.core.document_management.manager import (
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
║  功能：单文档对话、跨文档检索、网络搜索、URL分析、智能问答                   ║
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


def select_multiple_documents_interactive() -> Optional[list]:
    """
    交互式选择多个文档

    Returns:
        Optional[list]: 选择的文档名列表，如果取消则返回 None
    """
    print("\n" + "=" * 80)
    print("  手动选择文档")
    print("=" * 80 + "\n")

    indexed_docs = list_indexed_documents()

    if len(indexed_docs) == 0:
        logger.warning("⚠️  当前没有已索引的文档")
        return None

    # 显示文档列表
    print("📚 可用文档列表:\n")
    doc_list = list(indexed_docs.keys())
    for idx, doc_name in enumerate(doc_list, 1):
        doc_info = indexed_docs[doc_name]
        brief_summary = doc_info.get("brief_summary", "无摘要")[:60]
        print(f"  [{idx}] {doc_name}")
        print(f"      {brief_summary}...\n")

    print("\n💡 提示：")
    print("   - 输入文档编号，用逗号或空格分隔（例如: 1,3,5 或 1 3 5）")
    print("   - 输入 'all' 选择所有文档")
    print("   - 输入 'cancel' 取消选择\n")

    while True:
        try:
            user_input = input("请选择文档编号: ").strip().lower()

            # 取消选择
            if user_input == 'cancel':
                logger.info("取消文档选择")
                return None

            # 选择所有文档
            if user_input == 'all':
                logger.info(f"✅ 已选择所有 {len(doc_list)} 个文档")
                return doc_list

            # 解析输入的编号
            # 支持逗号或空格分隔
            separators = [',', ' ']
            indices_str = user_input
            for sep in separators:
                indices_str = indices_str.replace(sep, ',')

            # 去除多余的逗号
            indices_str = ','.join([s.strip() for s in indices_str.split(',') if s.strip()])

            # 提取编号
            try:
                indices = [int(s) for s in indices_str.split(',')]
            except ValueError:
                print("❌ 输入格式错误，请输入数字编号")
                continue

            # 验证编号范围
            invalid_indices = [idx for idx in indices if idx < 1 or idx > len(doc_list)]
            if invalid_indices:
                print(f"❌ 以下编号无效: {invalid_indices}，有效范围: 1-{len(doc_list)}")
                continue

            # 去重
            indices = list(set(indices))
            indices.sort()

            # 获取文档名
            selected_docs = [doc_list[idx - 1] for idx in indices]

            # 显示选择结果
            print(f"\n✅ 已选择 {len(selected_docs)} 个文档:")
            for idx, doc_name in enumerate(selected_docs, 1):
                print(f"   {idx}. {doc_name}")

            # 确认
            confirm = input("\n确认选择？(y/n): ").strip().lower()
            if confirm == 'y':
                return selected_docs
            else:
                print("重新选择...\n")
                continue

        except KeyboardInterrupt:
            print("\n\n取消选择")
            return None
        except Exception as e:
            logger.error(f"❌ 选择出错: {e}")
            print("请重新选择")
            continue


async def select_document() -> Optional[tuple]:
    """
    让用户选择对话模式和文档

    Returns:
        Optional[tuple]: (mode, data) - mode 可以是 "single", "cross", "manual", "general"
                        data: 单文档模式时是 doc_name (str)，手动选择模式时是 doc_list (list)
                        返回 None 表示退出
    """
    print("\n" + "=" * 80)
    print("  主菜单")
    print("=" * 80 + "\n")

    # 获取已索引的文档
    indexed_docs = list_indexed_documents()

    if not indexed_docs:
        logger.warning("⚠️  当前没有已索引的文档")
        logger.info("\n💡 提示：")
        logger.info("   - 输入 'i' 启动索引工具来索引新文档")
        logger.info("   - 输入 'm' 进入文档管理（如果有其他文档数据）")
        logger.info("   - 或者输入 '0' 进入通用对话模式（不涉及特定文档）\n")

        choice = input("请选择 (i=索引, m=管理, 0=通用对话, q=退出): ").strip().lower()
        if choice == 'i':
            logger.info("\n启动文档索引工具...")
            try:
                pdf_name = select_pdf_interactive()
                if pdf_name:
                    success = await index_pdf_document(pdf_name)
                    if success:
                        logger.info("\n✅ 索引完成，刷新文档列表...")
                        return await select_document()
                    else:
                        logger.warning("\n⚠️  索引失败")
                        return await select_document()
                else:
                    logger.info("未选择文件")
                    return await select_document()
            except Exception as e:
                logger.error(f"❌ 索引过程出错: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                return await select_document()
        elif choice == 'm':
            logger.info("\n进入文档管理...")
            try:
                await manage_documents_interactive()
                return await select_document()
            except Exception as e:
                logger.error(f"❌ 文档管理出错: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                return await select_document()
        elif choice == '0':
            return ("general", None)
        elif choice == 'q':
            return None
        else:
            print("❌ 无效选择")
            return await select_document()

    # 显示已索引的文档列表
    print("📚 已索引的文档：\n")
    doc_list = list(indexed_docs.keys())
    for idx, doc_name in enumerate(doc_list, 1):
        doc_info = indexed_docs[doc_name]
        brief_summary = doc_info.get("brief_summary", "无摘要")[:60]
        print(f"  [{idx}] {doc_name}")
        print(f"      {brief_summary}...\n")

    print("\n请选择操作：")
    print(f"  [1-{len(doc_list)}] 选择文档进行单文档对话")
    print(f"  [c] 跨文档智能对话（自动选择相关文档）")
    print(f"  [s] 跨文档手动选择模式（手动指定多个文档）")
    print(f"  [w] 网络搜索与URL分析（SearchAgent）")
    print(f"  [0] 通用对话模式（不绑定特定文档）")
    print(f"  [i] 索引新文档")
    print(f"  [m] 管理文档（查看/删除）")
    print(f"  [q] 退出\n")

    # 用户选择
    while True:
        try:
            choice = input("选择: ").strip().lower()

            # 检查是否退出
            if choice == 'q':
                return None

            # 检查是否选择管理文档
            if choice == 'm':
                logger.info("\n进入文档管理...")
                try:
                    await manage_documents_interactive()
                    logger.info("\n刷新文档列表...")
                    return await select_document()
                except Exception as e:
                    logger.error(f"❌ 文档管理出错: {e}")
                    import traceback
                    logger.debug(traceback.format_exc())
                    continue

            # 检查是否选择索引新文档
            if choice == 'i':
                logger.info("\n启动文档索引工具...")
                try:
                    pdf_name = select_pdf_interactive()
                    if pdf_name:
                        success = await index_pdf_document(pdf_name)
                        if success:
                            logger.info("\n✅ 索引完成，刷新文档列表...")
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

            # 检查是否选择跨文档模式
            if choice == 'c':
                logger.info("✅ 已进入跨文档智能对话模式")
                return ("cross", None)

            # 检查是否选择手动选择模式
            if choice == 's':
                logger.info("进入手动选择文档模式...")
                selected_docs = select_multiple_documents_interactive()
                if selected_docs and len(selected_docs) > 0:
                    logger.info("✅ 已进入跨文档手动选择模式")
                    return ("manual", selected_docs)
                else:
                    logger.info("未选择文档，返回主菜单")
                    continue

            # 检查是否选择通用模式
            if choice == '0':
                logger.info("✅ 已进入通用对话模式（不绑定特定文档）")
                return ("general", None)

            # 检查是否选择网络搜索模式
            if choice == 'w':
                logger.info("✅ 已进入网络搜索与URL分析模式")
                return ("search", None)

            # 检查是否为数字（选择特定文档）
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(doc_list):
                    selected_doc = doc_list[idx - 1]
                    logger.info(f"✅ 已选择文档: {selected_doc}")
                    return ("single", selected_doc)
                else:
                    print(f"❌ 编号无效，请输入 1-{len(doc_list)}")
            else:
                print(f"❌ 无效选择")

        except KeyboardInterrupt:
            print("\n\n再见！")
            return None
        except Exception as e:
            logger.error(f"❌ 选择失败: {e}")


async def chat_loop(answer_agent: AnswerAgent, mode: str, doc_name: Optional[str] = None):
    """
    对话循环

    Args:
        answer_agent: AnswerAgent实例
        mode: "single"（单文档）、"cross"（跨文档）或 "general"（通用模式）
        doc_name: 文档名称（单文档模式时使用）

    Returns:
        str: "quit"=退出, "clear"=清除历史, "switch"=切换模式, "main"=返回主菜单
    """
    print("\n" + "=" * 80)
    if mode == "single":
        print(f"  📄 单文档对话模式: {doc_name}")
    elif mode == "cross":
        print(f"  🌐 跨文档智能对话模式")
    else:
        print(f"  💬 通用对话模式")
    print("=" * 80 + "\n")

    print("💡 提示：")
    print("   - 输入问题开始对话")
    if mode == "cross":
        print("   - 系统会自动选择相关文档进行检索")
    if mode in ["single", "cross"]:
        print("   - 输入 'switch' 切换模式")
    print("   - 输入 'clear' 清除对话历史")
    print("   - 输入 'main' 返回主菜单")
    print("   - 输入 'quit' 或 'exit' 退出\n")
    print("=" * 80 + "\n")

    turn_count = 0

    while True:
        try:
            # 获取用户输入
            if mode == "single":
                mode_label = f"单文档 ({doc_name})"
            elif mode == "cross":
                mode_label = "跨文档模式"
            else:
                mode_label = "通用模式"

            user_input = input(f"\n[{mode_label}] 👤 Query: ").strip()

            # 检查命令
            if user_input.lower() in ["quit", "exit", "退出", "再见"]:
                return "quit"

            if user_input.lower() == "clear":
                print("\n🔄 清除对话历史...")
                return "clear"

            if user_input.lower() == "switch":
                return "switch"

            if user_input.lower() == "main":
                return "main"

            # 检查空输入
            if not user_input:
                print("⚠️  请输入问题")
                continue

            turn_count += 1

            # 调用 AnswerAgent
            enabled_tools = ["retrieve_documents"] if doc_name else []
            selected_docs = [doc_name] if doc_name else None
            result = await answer_agent.query(
                user_query=user_input,
                enabled_tools=enabled_tools,
                selected_docs=selected_docs
            )

            # 提取回答
            final_answer = result.get("final_answer", "")
            tool_results = result.get("tool_results", [])

            # 显示检索的文档
            for tr in tool_results:
                if tr.get("success") and isinstance(tr.get("result"), dict):
                    tr_doc_names = tr["result"].get("doc_names", [])
                    tr_mode = tr["result"].get("mode", "")
                    if tr_doc_names and tr_mode in ("auto", "multi"):
                        print(f"\n📚 检索的文档 ({len(tr_doc_names)} 个):")
                        for dn in tr_doc_names:
                            print(f"   - {dn}")

            # 显示回答
            print(f"\n🤖 Assistant: {final_answer}")

        except KeyboardInterrupt:
            print("\n\n返回主菜单")
            return "main"
        except Exception as e:
            logger.error(f"\n❌ 查询出错: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            print(f"\n❌ 抱歉，处理您的问题时出现错误: {str(e)}\n")


async def single_doc_chat_mode(doc_name: str):
    """单文档对话模式"""
    # 初始化 AnswerAgent
    logger.info(f"\n🔧 初始化 AnswerAgent（单文档模式: {doc_name}）...")
    answer_agent = AnswerAgent(doc_name=doc_name)
    logger.info("✅ AnswerAgent 初始化完成\n")

    while True:
        action = await chat_loop(answer_agent, mode="single", doc_name=doc_name)

        if action == "quit":
            print("\n再见！\n")
            break
        elif action == "clear":
            # 清除对话历史和持久化状态
            logger.info("🔧 清除对话历史和状态...")
            answer_agent.clear_all_retrieval_agents()
            answer_agent.llm.clear_all_history()
            logger.info("✅ 对话历史已清除\n")
            continue
        elif action == "switch":
            # 切换到跨文档模式
            await cross_doc_chat_mode()
            break
        elif action == "main":
            break


async def cross_doc_chat_mode():
    """跨文档智能对话模式"""
    print("\n" + "=" * 80)
    print("  跨文档智能对话模式")
    print("=" * 80 + "\n")

    # 检查文档数量
    indexed_docs = list_indexed_documents()
    if len(indexed_docs) < 2:
        print(f"⚠️  当前只有 {len(indexed_docs)} 个已索引文档")
        print("💡 建议至少索引2个文档以体验跨文档检索功能\n")

        choice = input("是否继续？(y/n): ").strip().lower()
        if choice != 'y':
            return

    # 初始化 AnswerAgent（doc_name=None 表示跨文档模式）
    logger.info("\n🔧 初始化 AnswerAgent（跨文档模式）...")
    answer_agent = AnswerAgent(doc_name=None)
    logger.info("✅ AnswerAgent 初始化完成\n")

    while True:
        action = await chat_loop(answer_agent, mode="cross", doc_name=None)

        if action == "quit":
            print("\n再见！\n")
            break
        elif action == "clear":
            # 清除对话历史和持久化状态
            logger.info("🔧 清除对话历史和状态...")
            answer_agent.clear_all_retrieval_agents()
            answer_agent.llm.clear_all_history()
            logger.info("✅ 对话历史已清除\n")
            continue
        elif action == "switch":
            # 切换到单文档模式
            indexed_docs = list_indexed_documents()
            if len(indexed_docs) == 0:
                print("\n⚠️  没有已索引的文档")
                input("\n按回车键继续...")
                continue

            print("\n已索引的文档:")
            doc_list = list(indexed_docs.keys())
            for idx, doc_name in enumerate(doc_list, 1):
                print(f"  [{idx}] {doc_name}")

            choice = input("\n请选择文档编号: ").strip()
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(doc_list):
                    selected_doc = doc_list[idx - 1]
                    await single_doc_chat_mode(selected_doc)
                    break
                else:
                    print("❌ 无效选择")
            else:
                print("❌ 无效输入")
        elif action == "main":
            break


async def manual_selection_chat_mode(selected_docs: list):
    """跨文档手动选择模式"""
    print("\n" + "=" * 80)
    print("  跨文档手动选择模式")
    print("=" * 80 + "\n")

    print(f"📚 已选择 {len(selected_docs)} 个文档作为背景知识:")
    for idx, doc_name in enumerate(selected_docs, 1):
        print(f"   {idx}. {doc_name}")

    # 初始化 AnswerAgent
    logger.info("\n🔧 初始化 AnswerAgent（手动选择模式）...")
    answer_agent = AnswerAgent(doc_name=None)

    # 验证文档
    valid_docs, invalid_docs = answer_agent.validate_manual_selected_docs(selected_docs)

    if invalid_docs:
        logger.warning(f"⚠️  以下文档未找到或未索引: {invalid_docs}")
        print(f"\n⚠️  警告: 以下文档无效，将被跳过:")
        for doc in invalid_docs:
            print(f"   - {doc}")

    if len(valid_docs) == 0:
        logger.error("❌ 没有有效的文档可以使用")
        print("\n❌ 没有有效的文档，无法继续")
        input("\n按回车键返回主菜单...")
        return

    print(f"\n✅ 有效文档数: {len(valid_docs)}")
    logger.info("✅ AnswerAgent 初始化完成\n")

    # 修改 chat_loop 以支持手动选择模式
    while True:
        try:
            # 获取用户输入
            user_input = input(f"\n[手动选择 ({len(valid_docs)} 个文档)] 👤 Query: ").strip()

            # 检查命令
            if user_input.lower() in ["quit", "exit", "退出", "再见"]:
                print("\n再见！\n")
                break

            if user_input.lower() == "clear":
                print("\n🔄 清除对话历史...")
                logger.info("🔧 重新初始化 AnswerAgent...")
                # 清除持久化状态
                answer_agent.clear_all_retrieval_agents()
                # 清除 LLM 对话历史
                answer_agent.llm.clear_all_history()
                logger.info("✅ AnswerAgent 重新初始化完成\n")
                continue

            if user_input.lower() == "main":
                break

            if user_input.lower() == "switch":
                # 允许重新选择文档
                new_selected_docs = select_multiple_documents_interactive()
                if new_selected_docs and len(new_selected_docs) > 0:
                    await manual_selection_chat_mode(new_selected_docs)
                    break
                else:
                    continue

            # 检查空输入
            if not user_input:
                print("⚠️  请输入问题")
                continue

            # 调用 AnswerAgent（手动选择模式）
            result = await answer_agent.graph.ainvoke({
                "user_query": user_input,
                "enabled_tools": ["retrieve_documents"],
                "selected_docs": valid_docs,
            })

            # 提取回答
            final_answer = result.get("final_answer", "")
            tool_results = result.get("tool_results", [])

            # 显示使用的文档
            for tr in tool_results:
                if tr.get("success") and isinstance(tr.get("result"), dict):
                    tr_doc_names = tr["result"].get("doc_names", [])
                    if tr_doc_names:
                        print(f"\n📚 检索的文档 ({len(tr_doc_names)} 个):")
                        for dn in tr_doc_names:
                            print(f"   - {dn}")

            # 显示回答
            print(f"\n🤖 Assistant: {final_answer}")

        except KeyboardInterrupt:
            print("\n\n返回主菜单")
            break
        except Exception as e:
            logger.error(f"\n❌ 查询出错: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            print(f"\n❌ 抱歉，处理您的问题时出现错误: {str(e)}\n")


async def search_chat_mode():
    """网络搜索与URL分析模式"""
    print("\n" + "=" * 80)
    print("  🌐 网络搜索与URL分析模式 (SearchAgent)")
    print("=" * 80 + "\n")

    print("💡 功能说明：")
    print("   【Use Case 1】 搜索引擎检索")
    print("   - 输入问题，系统通过搜索引擎获取最新信息")
    print("   - 示例: \"2024年AI领域有什么重大突破？\"")
    print("")
    print("   【Use Case 2】 URL内容分析")
    print("   - 输入URL或包含URL的查询，系统分析网页内容")
    print("   - 示例: \"分析这个网页：https://example.com\"")
    print("   - 内容较小时直接对话，较大时自动索引")
    print("\n" + "=" * 80 + "\n")

    print("📝 使用提示：")
    print("   - 直接输入问题或URL，系统会自动判断使用哪种模式")
    print("   - 输入 'clear' 清除对话历史")
    print("   - 输入 'main' 返回主菜单")
    print("   - 输入 'quit' 或 'exit' 退出\n")
    print("=" * 80 + "\n")

    # 初始化 SearchAgent
    logger.info("🔧 初始化 SearchAgent...")
    try:
        search_agent = SearchAgent(provider="openai")
        logger.info("✅ SearchAgent 初始化完成\n")
    except Exception as e:
        logger.error(f"❌ SearchAgent 初始化失败: {e}")
        print(f"\n❌ SearchAgent 初始化失败: {e}")
        print("请检查：")
        print("  1. MCP 服务是否正确配置（DuckDuckGo MCP、web_scraper MCP）")
        print("  2. 网络连接是否正常")
        print("  3. 环境变量是否正确设置\n")
        input("按回车键返回主菜单...")
        return

    turn_count = 0

    while True:
        try:
            # 获取用户输入
            user_input = input(f"\n[SearchAgent] 👤 输入问题或URL: ").strip()

            # 检查命令
            if user_input.lower() in ["quit", "exit", "退出", "再见"]:
                print("\n再见！\n")
                break

            if user_input.lower() == "clear":
                print("\n🔄 清除对话历史...")
                # SearchAgent 是无状态的，每次都是新的查询
                logger.info("✅ 对话历史已清除\n")
                continue

            if user_input.lower() == "main":
                print("\n返回主菜单\n")
                break

            # 检查空输入
            if not user_input:
                print("⚠️  请输入问题或URL")
                continue

            turn_count += 1

            print(f"\n🔍 正在处理您的请求...")

            # 调用 SearchAgent
            result = await search_agent.search(
                query=user_input,
                max_iterations=2  # 最多2轮检索
            )

            # 显示结果
            if result.get('success'):
                use_case = result.get('use_case', 'unknown')
                answer = result.get('answer', '')
                sources = result.get('sources', [])
                processing_strategy = result.get('processing_strategy', '')
                content_size = result.get('content_size', 0)
                scraped_count = result.get('scraped_count', 0)
                warnings = result.get('warnings', [])

                # 显示检测到的模式
                print(f"\n📊 检测模式: ", end="")
                if use_case == "search":
                    print("搜索引擎检索")
                elif use_case == "url_analysis":
                    print("URL内容分析")
                    if processing_strategy:
                        print(f"   处理策略: {processing_strategy}")
                        print(f"   内容大小: {content_size} 字符")
                else:
                    print("未知")

                # 显示爬取统计
                if scraped_count > 0:
                    print(f"   爬取页面: {scraped_count} 个")

                # 显示警告
                if warnings:
                    print(f"\n⚠️  警告信息:")
                    for warning in warnings:
                        print(f"   - {warning}")

                # 显示答案
                print(f"\n🤖 Assistant:\n{answer}")

                # 显示来源
                if sources:
                    print(f"\n📚 信息来源 ({len(sources)} 个):")
                    for idx, source in enumerate(sources, 1):
                        print(f"   {idx}. {source}")

                # 如果内容被索引，提示用户可以切换到文档对话模式
                if processing_strategy == "index_then_chat":
                    print(f"\n💡 提示: 内容已索引，您可以：")
                    print(f"   1. 继续提问相关问题")
                    print(f"   2. 返回主菜单 ('main') 切换到文档对话模式进行深度对话")

            else:
                # 失败
                error = result.get('error', '未知错误')
                print(f"\n❌ 查询失败: {error}")

        except KeyboardInterrupt:
            print("\n\n返回主菜单")
            break
        except Exception as e:
            logger.error(f"\n❌ 查询出错: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            print(f"\n❌ 抱歉，处理您的请求时出现错误: {str(e)}\n")

    # 清理资源
    try:
        await search_agent.utils.cleanup_mcp_clients()
        logger.info("✅ SearchAgent 资源已清理")
    except Exception as e:
        logger.warning(f"⚠️  清理资源时出错: {e}")


async def main_async():
    """异步主函数"""
    print_banner()

    while True:
        # 步骤1：选择模式和文档
        choice = await select_document()

        if choice is None:
            # 用户选择退出
            break

        mode, data = choice

        # 步骤2：进入对应的对话模式
        if mode == "single":
            # 单文档模式：data 是 doc_name (str)
            await single_doc_chat_mode(data)
        elif mode == "cross":
            # 跨文档自动选择模式
            await cross_doc_chat_mode()
        elif mode == "manual":
            # 跨文档手动选择模式：data 是 selected_docs (list)
            await manual_selection_chat_mode(data)
        elif mode == "search":
            # 网络搜索与URL分析模式
            await search_chat_mode()
        elif mode == "general":
            # 通用对话模式
            logger.info("\n🔧 初始化 AnswerAgent（通用模式）...")
            answer_agent = AnswerAgent(doc_name=None)
            logger.info("✅ AnswerAgent 初始化完成\n")

            while True:
                action = await chat_loop(answer_agent, mode="general", doc_name=None)

                if action == "quit":
                    print("\n再见！\n")
                    return  # 退出整个程序
                elif action == "clear":
                    # 清除对话历史和持久化状态
                    logger.info("🔧 清除对话历史和状态...")
                    answer_agent.clear_all_retrieval_agents()
                    answer_agent.llm.clear_all_history()
                    logger.info("✅ 对话历史已清除\n")
                    continue
                elif action == "main":
                    break  # 返回主菜单


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
