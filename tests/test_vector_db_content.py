"""
Vector DB 内容查看测试

功能：
1. 加载指定文档的 Vector DB
2. 遍历显示所有文档内容
3. 按类型分组展示（context, title, structure）
4. 显示每个文档的 metadata 和 content

运行方式：
    python tests/test_vector_db_content.py
"""

import sys
import os
import logging
from pathlib import Path
from typing import Dict, List, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.vector_db.vector_db_client import VectorDBClient
from src.core.llm.client import LLMBase
from src.config.settings import DATA_ROOT

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


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


def load_vector_db(doc_name: str) -> VectorDBClient:
    """
    加载指定文档的 Vector DB

    Args:
        doc_name: 文档名称（不含扩展名）

    Returns:
        VectorDBClient 实例
    """
    # 构建 vector db 路径
    # vector_db_path = Path(DATA_ROOT) / "vector_db" / f"{doc_name}_data_index"
    vector_db_path = Path(DATA_ROOT) / "vector_db" / "_metadata"

    logger.info(f"📂 Vector DB 路径: {vector_db_path}")

    # 检查路径是否存在
    if not vector_db_path.exists():
        raise FileNotFoundError(f"❌ Vector DB 不存在: {vector_db_path}")

    logger.info(f"✅ Vector DB 路径存在")

    # 初始化 LLM（需要 embedding_model）
    llm = LLMBase(provider="openai")

    # 创建 VectorDBClient
    vector_db_client = VectorDBClient(
        db_path=str(vector_db_path),
        embedding_model=llm.embedding_model
    )

    if not vector_db_client.vector_db:
        raise ValueError(f"❌ Vector DB 加载失败")

    logger.info(f"✅ Vector DB 加载成功")

    return vector_db_client


def analyze_vector_db_content(vector_db_client: VectorDBClient) -> Dict[str, List[Dict[str, Any]]]:
    """
    分析 Vector DB 中的所有文档

    Args:
        vector_db_client: VectorDBClient 实例

    Returns:
        按类型分组的文档字典
    """
    # 按类型分组
    docs_by_type = {
        "context": [],
        "title": [],
        "structure": [],
        "other": []
    }

    # 遍历 docstore 中的所有文档
    if not vector_db_client.vector_db or not vector_db_client.vector_db.docstore:
        logger.warning("⚠️  Docstore 为空")
        return docs_by_type

    total_docs = len(vector_db_client.vector_db.docstore._dict)
    logger.info(f"📊 文档总数: {total_docs}")

    for doc_id, doc in vector_db_client.vector_db.docstore._dict.items():
        metadata = doc.metadata
        doc_type = metadata.get("type", "other")

        doc_info = {
            "doc_id": doc_id,
            "type": doc_type,
            "content": doc.page_content,
            "metadata": metadata
        }

        # 按类型分类
        if doc_type in docs_by_type:
            docs_by_type[doc_type].append(doc_info)
        else:
            docs_by_type["other"].append(doc_info)

    return docs_by_type


def display_statistics(docs_by_type: Dict[str, List[Dict[str, Any]]]):
    """
    显示统计信息

    Args:
        docs_by_type: 按类型分组的文档字典
    """
    print_section("统计信息")

    total = sum(len(docs) for docs in docs_by_type.values())
    print(f"📊 文档总数: {total}\n")

    for doc_type, docs in docs_by_type.items():
        if docs:
            print(f"  - {doc_type}: {len(docs)} 个")

    print()


def display_context_documents(docs: List[Dict[str, Any]]):
    """
    显示 context 类型的文档（章节摘要）

    Args:
        docs: context 类型的文档列表
    """
    print_section(f"Context 文档 (章节摘要) - 共 {len(docs)} 个")

    for idx, doc in enumerate(docs, 1):
        metadata = doc["metadata"]
        title = metadata.get("title", "未知标题")
        pages = metadata.get("pages", [])
        content = doc["content"]

        print_subsection(f"章节 {idx}: {title}")
        print(f"📄 页码: {pages}")
        print(f"📝 摘要长度: {len(content)} 字符")
        print(f"\n摘要内容:\n{content[:500]}...")

        # 显示 refactor 信息
        refactor = metadata.get("refactor", "")
        if refactor:
            print(f"\n🔄 重构内容长度: {len(refactor)} 字符")
            print(f"重构内容预览:\n{refactor[:300]}...")

        # 显示 raw_data 信息
        raw_data = metadata.get("raw_data", {})
        if raw_data:
            print(f"\n📑 原始数据: {len(raw_data)} 页")


def display_title_documents(docs: List[Dict[str, Any]]):
    """
    显示 title 类型的文档（章节标题）

    Args:
        docs: title 类型的文档列表
    """
    print_section(f"Title 文档 (章节标题) - 共 {len(docs)} 个")

    for idx, doc in enumerate(docs, 1):
        metadata = doc["metadata"]
        title_content = doc["content"]
        pages = metadata.get("pages", [])
        summary = metadata.get("summary", "")

        print(f"{idx}. 标题: {title_content}")
        print(f"   📄 页码: {pages}")
        print(f"   📝 摘要长度: {len(summary)} 字符")
        if summary:
            print(f"   摘要预览: {summary[:200]}...")
        print()


def display_structure_documents(docs: List[Dict[str, Any]]):
    """
    显示 structure 类型的文档（文档结构）

    Args:
        docs: structure 类型的文档列表
    """
    print_section(f"Structure 文档 (文档结构) - 共 {len(docs)} 个")

    for idx, doc in enumerate(docs, 1):
        metadata = doc["metadata"]
        content = doc["content"]

        print_subsection(f"结构文档 {idx}")
        print(f"📋 内容:\n{content}")
        print(f"\n📊 Metadata: {metadata}")


def display_other_documents(docs: List[Dict[str, Any]]):
    """
    显示其他类型的文档

    Args:
        docs: 其他类型的文档列表
    """
    if not docs:
        return

    print_section(f"其他文档 - 共 {len(docs)} 个")

    for idx, doc in enumerate(docs, 1):
        doc_type = doc["type"]
        content = doc["content"]
        metadata = doc["metadata"]

        print_subsection(f"文档 {idx} (类型: {doc_type})")
        print(f"📝 内容长度: {len(content)} 字符")
        print(f"内容预览:\n{content[:300]}...")
        print(f"\n📊 Metadata: {metadata}")


def export_to_json(docs_by_type: Dict[str, List[Dict[str, Any]]], doc_name: str):
    """
    将 Vector DB 内容导出为 JSON 文件

    Args:
        docs_by_type: 按类型分组的文档字典
        doc_name: 文档名称
    """
    import json
    from datetime import datetime

    output_dir = Path(DATA_ROOT) / "output"
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"{doc_name}_vector_db_export_{timestamp}.json"

    # 准备导出数据
    export_data = {
        "doc_name": doc_name,
        "export_time": datetime.now().isoformat(),
        "statistics": {
            doc_type: len(docs) for doc_type, docs in docs_by_type.items()
        },
        "documents": docs_by_type
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    logger.info(f"✅ 导出完成: {output_file}")
    print(f"\n💾 已导出到: {output_file}")


def main():
    """主测试函数"""
    print_section("Vector DB 内容查看器")

    # ==================== 配置测试参数 ====================

    # 📝 在这里配置要查看的PDF名称（不含.pdf扩展名）
    doc_name = "1706.03762v7"

    # 是否导出为JSON文件
    export_json = True

    # ==================== 执行测试 ====================

    logger.info(f"📋 测试配置:")
    logger.info(f"   - 文档名称: {doc_name}")
    logger.info(f"   - 导出JSON: {export_json}")

    try:
        # 1. 加载 Vector DB
        print_section("加载 Vector DB")
        vector_db_client = load_vector_db(doc_name)

        # 2. 分析内容
        print_section("分析 Vector DB 内容")
        docs_by_type = analyze_vector_db_content(vector_db_client)

        # 3. 显示统计信息
        display_statistics(docs_by_type)

        # 4. 显示各类型文档
        if docs_by_type["context"]:
            display_context_documents(docs_by_type["context"])

        if docs_by_type["title"]:
            display_title_documents(docs_by_type["title"])

        if docs_by_type["structure"]:
            display_structure_documents(docs_by_type["structure"])

        if docs_by_type["other"]:
            display_other_documents(docs_by_type["other"])

        # 5. 导出为JSON（可选）
        if export_json:
            print_section("导出数据")
            export_to_json(docs_by_type, doc_name)

        print_section("测试完成")
        logger.info("✅ Vector DB 内容查看完成！")

    except FileNotFoundError as e:
        logger.error(f"❌ 文件未找到: {e}")
        logger.info("\n💡 提示: 请先运行 test_indexing_agent.py 对文档进行索引")

    except Exception as e:
        logger.error(f"❌ 测试过程中发生异常: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
