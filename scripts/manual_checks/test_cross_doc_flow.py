"""测试跨文档检索数据流的完整性"""

# 模拟完整的数据流
def test_cross_doc_data_flow():
    print("=" * 80)
    print("测试跨文档检索数据流")
    print("=" * 80)

    # Step 1: 模拟 RetrievalAgent 的返回结果
    retrieval_state_a = {
        "query": "Transformer在NLP中的优点",
        "doc_name": "NLP论文.pdf",
        "final_summary": "Transformer在NLP任务中具有以下优点：\n1. 并行计算能力强（见第3章，第12页）\n2. 长距离依赖建模好（见第3章，第15页）",
        "formatted_data": [...],  # 简化
        "is_complete": True
    }

    retrieval_state_b = {
        "query": "Transformer模型架构优势",
        "doc_name": "架构指南.pdf",
        "final_summary": "Transformer架构的核心优势包括：\n- Self-attention机制（见第2章，第8页）\n- 多头注意力设计（见第2章，第10页）",
        "formatted_data": [...],  # 简化
        "is_complete": True
    }

    # Step 2: 模拟 ParallelCoordinator 添加元数据
    multi_doc_results = {
        "NLP论文.pdf": {
            **retrieval_state_a,
            "source_metadata": {
                "doc_name": "NLP论文.pdf",
                "similarity_score": 0.85
            },
            "used_query": "Transformer在NLP中的优点"
        },
        "架构指南.pdf": {
            **retrieval_state_b,
            "source_metadata": {
                "doc_name": "架构指南.pdf",
                "similarity_score": 0.78
            },
            "used_query": "Transformer模型架构优势"
        }
    }

    print("\n📊 Step 1: ParallelCoordinator 返回的结果")
    print(f"   - 文档数量: {len(multi_doc_results)}")
    for doc_name, result in multi_doc_results.items():
        print(f"   - {doc_name}:")
        print(f"      - 有 final_summary: {'final_summary' in result}")
        print(f"      - 有 source_metadata: {'source_metadata' in result}")
        print(f"      - 有 used_query: {'used_query' in result}")

    # Step 3: 模拟 CrossDocumentSynthesizer._format_multi_doc_results
    formatted_sections = []
    for doc_name, result in multi_doc_results.items():
        if result.get("error"):
            print(f"   ⚠️  文档 '{doc_name}' 检索失败，跳过")
            continue

        source_metadata = result.get("source_metadata", {})
        relevance_score = source_metadata.get("similarity_score", "N/A")
        final_summary = result.get("final_summary", "")

        if not final_summary or not final_summary.strip():
            print(f"   ⚠️  文档 '{doc_name}' 结果为空，跳过")
            continue

        section = f"""
========================================
文档: {doc_name} (相关性评分: {relevance_score if isinstance(relevance_score, str) else f'{relevance_score:.3f}'})
========================================
{final_summary}
"""
        formatted_sections.append(section)

    formatted_results = "\n\n".join(formatted_sections)

    print("\n📋 Step 2: CrossDocumentSynthesizer 格式化结果")
    print(formatted_results)

    # Step 4: 模拟 LLM 输入
    user_query = "Transformer的优点"
    llm_prompt = f"""用户问题：{user_query}

以下是从多个相关文档中检索到的内容：

{formatted_results}

请根据以上多个文档的内容，综合回答用户问题。要求：
1. 综合所有相关信息，提供全面的答案
2. 明确标注信息来源（例如："根据文档A..."，"文档B指出..."）
3. 如果不同文档有冲突信息，请客观呈现并说明
4. 如果所有文档都无法回答问题，请明确说明
5. 保持答案的连贯性和可读性"""

    print("\n🤖 Step 3: 发送给 LLM 的 Prompt")
    print("=" * 80)
    print(llm_prompt[:500] + "...")
    print("=" * 80)

    # 验证关键字段
    print("\n✅ 数据流验证:")
    print(f"   - 所有文档都有 final_summary: {all('final_summary' in r for r in multi_doc_results.values())}")
    print(f"   - 所有文档都有 source_metadata: {all('source_metadata' in r for r in multi_doc_results.values())}")
    print(f"   - 格式化结果不为空: {len(formatted_results) > 0}")
    print(f"   - 格式化包含文档名: {all(doc_name in formatted_results for doc_name in multi_doc_results.keys())}")

if __name__ == "__main__":
    test_cross_doc_data_flow()
