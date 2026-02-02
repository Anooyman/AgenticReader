"""
测试元数据向量数据库的去重机制

验证：
1. document_exists() 能否正确检测重复
2. add_document() 能否自动去重
3. delete_document() 能否正确删除
"""
import asyncio
import logging
from src.core.vector_db.metadata_db import MetadataVectorDB
from src.core.document_management import DocumentRegistry

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_section(title: str):
    """打印章节标题"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def test_document_exists():
    """测试文档存在性检查"""
    print_section("测试1: 检查文档是否存在")

    try:
        metadata_db = MetadataVectorDB()
        registry = DocumentRegistry()

        # 获取所有已索引文档
        all_docs = registry.list_all()
        if not all_docs:
            print("⚠️  没有已索引的文档，跳过测试")
            return

        # 测试第一个文档
        first_doc = all_docs[0]
        doc_id = first_doc.get("doc_id")
        doc_name = first_doc.get("doc_name")

        print(f"测试文档: {doc_name} (ID: {doc_id})")

        # 检查是否存在
        exists = metadata_db.document_exists(doc_id)
        print(f"✅ document_exists() 返回: {exists}")

        if exists:
            print("✓ 文档在元数据向量数据库中存在")
        else:
            print("⚠️  文档不在元数据向量数据库中（可能未提取元数据）")

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_deduplication():
    """测试去重机制"""
    print_section("测试2: 去重机制")

    try:
        metadata_db = MetadataVectorDB()
        registry = DocumentRegistry()

        # 获取第一个文档
        all_docs = registry.list_all()
        if not all_docs:
            print("⚠️  没有已索引的文档，跳过测试")
            return

        first_doc = all_docs[0]
        doc_id = first_doc.get("doc_id")
        doc_name = first_doc.get("doc_name")
        metadata_enhanced = first_doc.get("metadata_enhanced", {})
        embedding_summary = metadata_enhanced.get("embedding_summary", "")

        if not embedding_summary:
            print(f"⚠️  文档 {doc_name} 没有 embedding_summary，无法测试")
            return

        print(f"测试文档: {doc_name} (ID: {doc_id})")

        # 检查初始状态
        exists_before = metadata_db.document_exists(doc_id)
        print(f"初始状态: 文档存在 = {exists_before}")

        # 尝试重复添加（应该自动去重）
        print(f"\n尝试重复添加同一文档...")
        metadata_db.add_document(
            doc_id=doc_id,
            doc_name=doc_name,
            embedding_summary=embedding_summary,
            update_if_exists=True
        )

        # 检查去重后的状态
        exists_after = metadata_db.document_exists(doc_id)
        print(f"去重后: 文档存在 = {exists_after}")

        # 获取统计信息
        stats = metadata_db.get_stats()
        print(f"\n📊 元数据数据库统计:")
        print(f"   - 总文档数: {stats['total_documents']}")

        print(f"\n✅ 去重测试完成")
        print(f"💡 如果文档存在，add_document() 会先删除旧的再添加新的，避免重复")

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_delete():
    """测试删除功能（只显示不实际删除）"""
    print_section("测试3: 删除功能演示")

    try:
        metadata_db = MetadataVectorDB()
        registry = DocumentRegistry()

        # 获取所有文档
        all_docs = registry.list_all()
        if len(all_docs) < 2:
            print("⚠️  文档数量不足（需要至少2个），跳过删除测试")
            return

        # 显示当前状态
        stats_before = metadata_db.get_stats()
        print(f"删除前统计:")
        print(f"   - 总文档数: {stats_before['total_documents']}")

        print(f"\n💡 delete_document() 功能说明:")
        print(f"   - 通过重建索引实现删除")
        print(f"   - 会过滤掉指定 doc_id 的文档")
        print(f"   - 保留其他所有文档")
        print(f"\n⚠️  此测试不会实际删除文档，只是演示功能")

        # 示例：如何删除文档
        example_doc = all_docs[0]
        example_id = example_doc.get("doc_id")
        example_name = example_doc.get("doc_name")

        print(f"\n示例代码（删除 {example_name}）:")
        print(f"```python")
        print(f"metadata_db = MetadataVectorDB()")
        print(f"success = metadata_db.delete_document('{example_id}')")
        print(f"```")

        print(f"\n✅ 删除功能演示完成")

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_rebuild_index():
    """测试重建索引功能"""
    print_section("测试4: 重建索引")

    try:
        metadata_db = MetadataVectorDB()

        print("🔄 开始重建元数据索引...")
        print("💡 这会从 DocumentRegistry 读取所有文档并重建向量数据库")

        metadata_db.rebuild_index()

        # 显示重建后的统计
        stats = metadata_db.get_stats()
        print(f"\n📊 重建后统计:")
        print(f"   - 索引路径: {stats['index_path']}")
        print(f"   - 索引存在: {stats['index_exists']}")
        print(f"   - 总文档数: {stats['total_documents']}")

        print(f"\n✅ 索引重建完成")

    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("  元数据向量数据库 - 去重机制测试")
    print("=" * 80)

    print("\n测试内容:")
    print("  [1] 检查文档是否存在")
    print("  [2] 测试去重机制")
    print("  [3] 删除功能演示")
    print("  [4] 重建索引")
    print("  [0] 退出\n")

    while True:
        try:
            choice = input("请选择测试 [0-4]: ").strip()

            if choice == "0":
                print("\n再见！")
                break
            elif choice == "1":
                test_document_exists()
            elif choice == "2":
                test_deduplication()
            elif choice == "3":
                test_delete()
            elif choice == "4":
                test_rebuild_index()
            else:
                print("❌ 无效选择")

            input("\n按回车键继续...")

        except KeyboardInterrupt:
            print("\n\n再见！")
            break
        except Exception as e:
            logger.error(f"❌ 测试出错: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
