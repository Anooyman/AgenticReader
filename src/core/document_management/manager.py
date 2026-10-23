"""
文档管理工具 - 用于管理已索引的文档

功能：
1. 列出所有已索引的文档
2. 查看文档详细信息
3. 删除文档及其所有相关数据（vector_db, json, md, pdf_image 等）
   ——实际清理统一委托 delete_service.delete_document_service()（唯一权威实现）
4. 从 DocumentRegistry 中注销文档

运行方式：
    python -m src.core.processing.manage_documents
    或在代码中调用相关函数
"""
import logging
from pathlib import Path
from typing import Dict
import os

from src.core.document_management import DocumentRegistry
# 删除的唯一权威实现（REFACTOR_REPORT P2-1）：registry 注销、索引目录删除、
# brief 文件清理都只在 delete_service 里做，CLI 与 UI 共用同一路。
from src.core.document_management.delete_service import (
    PART_METADATA_DB,
    delete_document_service,
    document_paths,
)

# 获取 DATA_ROOT，如果导入失败则使用默认值
try:
    from src.config.settings import DATA_ROOT
    if DATA_ROOT is None:
        DATA_ROOT = "data"
except (ImportError, AttributeError):
    DATA_ROOT = "data"

# 确保 DATA_ROOT 是绝对路径
if not os.path.isabs(DATA_ROOT):
    # 获取项目根目录（manage_documents.py 的父目录的父目录的父目录）
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


def print_section(title: str):
    """打印分隔线和标题"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def print_subsection(title: str):
    """打印子标题"""
    print("\n" + "-" * 80)
    print(f"  {title}")
    print("-" * 80 + "\n")


def get_document_files(doc_name: str) -> Dict[str, Path]:
    """
    获取文档的所有相关文件路径

    路径拼装统一走 delete_service.document_paths()——删除与统计共用同一处，
    避免「显示出来的」和「实际被删掉的」两套路径各拼一份而漂移（D3 的教训）。

    Args:
        doc_name: 文档名称（不含扩展名）

    Returns:
        dict: 文件类型到路径的映射（键名保持历史约定，供列表展示使用）
    """
    if not doc_name:
        logger.error("文档名称为空")
        return {}

    if DATA_ROOT is None:
        logger.error("DATA_ROOT 未定义")
        return {}

    try:
        # 向量库/摘要路径统一由 constants helper 生成（历史上这里手抄过后缀，
        # 与索引落盘处必须一致）；目录穿越校验在 document_paths 内部过 safe_path
        paths = document_paths(doc_name)

        files = {
            "vector_db": paths.vector_db,
            "json_folder": paths.json_data,  # 所有 JSON 文件的文件夹
            "pdf_image": paths.images,
            "brief_summary": paths.brief,
        }

        return files
    except Exception as e:
        logger.error(f"获取文档文件路径失败: {e}")
        logger.error(f"DATA_ROOT: {DATA_ROOT}, doc_name: {doc_name}")
        return {}


def get_file_size(path: Path) -> int:
    """
    获取文件或目录的大小（字节）

    Args:
        path: 文件或目录路径

    Returns:
        int: 大小（字节）
    """
    if not path.exists():
        return 0

    if path.is_file():
        return path.stat().st_size

    # 目录：递归计算所有文件大小
    total_size = 0
    for item in path.rglob('*'):
        if item.is_file():
            total_size += item.stat().st_size

    return total_size


def format_size(size_bytes: int) -> str:
    """
    格式化文件大小

    Args:
        size_bytes: 字节数

    Returns:
        str: 格式化后的大小（如 "1.5 MB"）
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def list_all_documents() -> Dict[str, Dict]:
    """
    列出所有已索引的文档及其详细信息

    Returns:
        dict: {doc_name: {info, files, total_size}}
    """
    try:
        doc_registry = DocumentRegistry()
        all_docs = doc_registry.list_all()

        documents = {}

        for doc in all_docs:
            doc_name = doc.get("doc_name") or doc.get("name")  # 兼容旧字段名
            if not doc_name:
                logger.warning("发现没有名称的文档，跳过")
                continue

            # 获取文档的所有文件
            files = get_document_files(doc_name)
            if not files:
                logger.warning(f"无法获取文档 {doc_name} 的文件信息")
                continue

            # 计算总大小
            total_size = 0
            file_status = {}

            for file_type, file_path in files.items():
                try:
                    exists = file_path.exists()
                    size = get_file_size(file_path) if exists else 0
                    total_size += size

                    file_status[file_type] = {
                        "path": file_path,
                        "exists": exists,
                        "size": size,
                        "formatted_size": format_size(size)
                    }
                except Exception as e:
                    logger.error(f"检查文件 {file_type} 失败: {e}")
                    file_status[file_type] = {
                        "path": file_path,
                        "exists": False,
                        "size": 0,
                        "formatted_size": "0 B"
                    }

            documents[doc_name] = {
                "info": doc,
                "files": file_status,
                "total_size": total_size,
                "formatted_total_size": format_size(total_size)
            }

        return documents
    except Exception as e:
        logger.error(f"列出文档失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {}


def display_document_info(doc_name: str, doc_data: Dict):
    """
    显示文档的详细信息

    Args:
        doc_name: 文档名称
        doc_data: 文档数据（来自 list_all_documents）
    """
    print_subsection(f"文档: {doc_name}")

    # 基本信息
    info = doc_data["info"]
    print("📋 基本信息:")
    print(f"   文档ID: {info.get('doc_id', 'N/A')}")
    print(f"   创建时间: {info.get('created_at', 'N/A')}")
    print(f"   总大小: {doc_data['formatted_total_size']}")

    brief_summary = info.get("brief_summary", "")
    if brief_summary:
        print(f"\n📝 摘要:")
        print(f"   {brief_summary[:200]}...")

    # 文件详情
    print("\n📁 文件详情:")
    file_status = doc_data["files"]

    for file_type, status in file_status.items():
        status_icon = "✓" if status["exists"] else "✗"
        size_info = status["formatted_size"] if status["exists"] else "不存在"
        print(f"   [{status_icon}] {file_type}: {size_info}")

    print()


# CLI 展示用的部件名 → 历史打印文案（保持旧版清单的可读性）
_CLI_PART_LABELS = {
    "json_data": "json_folder",
    "vector_db": "vector_db",
    "images": "pdf_image",
    "summary": "输出文件(摘要)",
    "brief": "brief_summary",
    "generated": "注册表登记产物",
    "source_pdf": "源 PDF",
    PART_METADATA_DB: "元数据向量数据库",
}


def delete_document_files(doc_name: str, confirm: bool = True) -> bool:
    """
    删除文档的所有相关文件（CLI 入口）

    真正的清理逻辑在唯一权威实现
    :func:`src.core.document_management.delete_service.delete_document_service`
    （registry 注销、索引目录删除、brief 文件清理的唯一出处）；本函数只保留
    CLI 才需要的两件事：删除前列出清单与体积、可选的 ``input()`` 交互确认。

    语义与其它入口一致（parts=None 即全删，不含源 PDF）。

    Args:
        doc_name: 文档名称
        confirm: 是否需要用户确认

    Returns:
        bool: 是否成功删除（无任何失败项，且确实清掉了东西或注销了记录）
    """
    logger.info(f"\n准备删除文档: {doc_name}")

    # 非法名（空 / 目录穿越）直接拒绝，不进入交互
    try:
        document_paths(doc_name)
    except ValueError as e:
        logger.error(f"❌ 非法文档名: {e}")
        return False

    # 获取文档文件
    files = get_document_files(doc_name)

    if not files:
        logger.error("❌ 无法获取文档文件路径")
        return False

    logger.debug(f"检查到 {len(files)} 个文件类型")

    # 显示将要删除的文件
    print("\n将删除以下文件:")
    total_size = 0
    existing_files = []

    for file_type, file_path in files.items():
        logger.debug(f"检查 {file_type}: {file_path}")
        if file_path.exists():
            size = get_file_size(file_path)
            total_size += size
            existing_files.append((file_type, file_path, size))
            print(f"  ✓ {file_type}: {file_path} ({format_size(size)})")
        else:
            logger.debug(f"文件不存在: {file_type} - {file_path}")

    if not existing_files:
        logger.warning("⚠️  没有找到任何相关文件（仍会尝试注销注册表记录）")

    print(f"\n总计: {format_size(total_size)}")

    # 确认删除
    if confirm:
        print("\n⚠️  警告: 此操作不可撤销！")
        choice = input("\n确认删除？(yes/no): ").strip().lower()
        if choice != 'yes':
            logger.info("已取消删除")
            return False

    # 执行删除：交给唯一权威实现，CLI 不再自己 rmtree / 写注册表
    logger.info("\n开始删除文件...")
    print("\n正在删除:")

    result = delete_document_service(doc_name)

    for item in result.deleted:
        label = _CLI_PART_LABELS.get(item.part, item.part)
        suffix = f" ({item.size_mb:.2f} MB)" if item.size_mb else ""
        logger.info(f"  ✓ 已删除: {item.part}")
        print(f"  ✓ {label}{suffix}")

    if PART_METADATA_DB in result.deleted_parts:
        logger.info("✓ 已从 MetadataVectorDB 中删除元数据")
        print("  ✓ 元数据向量数据库已清理")

    if result.registry_removed:
        logger.info("✓ 已从 DocumentRegistry 中注销")
        print("\n📝 已从文档注册表中移除记录")

    # 总结
    print(f"\n删除完成:")
    print(f"  - 成功删除: {len(result.deleted)} 项")
    if result.failed:
        failed_parts = sorted({i.part for i in result.failed})
        print(f"  - 删除失败: {len(result.failed)} 项")
        print(f"    失败项: {', '.join(failed_parts)}")
        for item in result.failed:
            logger.error(f"  ✗ 删除失败 {item.part}: {item.error}")
        return False

    if not result.anything_done:
        # 既没有产物，注册表里也没有记录——与旧版一致地返回 False
        logger.warning("⚠️  没有找到任何相关文件")
        return False

    return True


def interactive_manage():
    """交互式文档管理"""
    print_section("文档管理工具")

    while True:
        # 获取所有文档
        documents = list_all_documents()

        if not documents:
            logger.warning("⚠️  没有已索引的文档")
            print("\n提示: 使用索引工具来索引新文档")
            break

        # 显示文档列表
        print("\n已索引的文档:\n")
        doc_list = list(documents.keys())

        for idx, doc_name in enumerate(doc_list, 1):
            doc_data = documents[doc_name]
            total_size = doc_data['formatted_total_size']
            print(f"  [{idx}] {doc_name} ({total_size})")

        print("\n  [0] 退出\n")

        # 用户选择
        try:
            choice = input("请选择要管理的文档编号 (或输入文档名): ").strip()

            if choice == '0':
                logger.info("退出文档管理")
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
                    print(f"\n✅ 文档 {selected_doc} 已成功删除")
                else:
                    print(f"\n⚠️  文档 {selected_doc} 删除未完全成功")
            elif action == 'b':
                continue
            else:
                print(f"❌ 无效操作: {action}")

        except KeyboardInterrupt:
            print("\n\n退出文档管理")
            break
        except Exception as e:
            logger.error(f"❌ 操作失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())


def main():
    """主函数"""
    try:
        interactive_manage()
    except KeyboardInterrupt:
        print("\n\n操作已取消")
    except Exception as e:
        logger.error(f"\n❌ 程序异常: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
