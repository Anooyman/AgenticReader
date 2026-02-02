"""
测试元数据提取修复

验证 metadata_extractor 能否正确处理各种 structure 格式
"""
import asyncio
from src.agents.indexing.components import MetadataExtractor


def test_fallback_metadata():
    """测试降级元数据生成"""
    # 创建一个模拟的 MetadataExtractor（不需要真实的LLM）
    class MockLLM:
        pass

    extractor = MetadataExtractor(MockLLM())

    # 测试1: 正常的 agenda_dict
    print("测试1: 正常的 agenda_dict")
    structure1 = {
        "第一章 引言": [1, 2, 3],
        "第二章 方法": [4, 5, 6],
        "第三章 实验": [7, 8, 9]
    }
    result1 = extractor._create_fallback_metadata(
        doc_name="测试文档.pdf",
        brief_summary="这是一个测试文档",
        structure=structure1
    )
    print(f"✅ 结果1: {result1['title']}")
    print(f"   关键词: {result1['keywords']}")
    print(f"   主题: {result1['topics']}")
    print()

    # 测试2: 空的 structure
    print("测试2: 空的 structure")
    structure2 = {}
    result2 = extractor._create_fallback_metadata(
        doc_name="空结构文档.pdf",
        brief_summary="这是一个没有章节结构的文档",
        structure=structure2
    )
    print(f"✅ 结果2: {result2['title']}")
    print(f"   关键词: {result2['keywords']}")
    print(f"   主题: {result2['topics']}")
    print()

    # 测试3: None
    print("测试3: None structure")
    result3 = extractor._create_fallback_metadata(
        doc_name="2505.09388v1_data_index.pdf",
        brief_summary="科研论文",
        structure=None
    )
    print(f"✅ 结果3: {result3['title']}")
    print(f"   关键词: {result3['keywords']}")
    print(f"   主题: {result3['topics']}")
    print()

    print("✅ 所有测试通过！")


if __name__ == "__main__":
    test_fallback_metadata()
