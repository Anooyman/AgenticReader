"""批量处理 pipeline_queue.json 里 type=web_article 的条目：
探测 processing_strategy -> direct_chat(纯文本QA) 或 index_then_chat(索引后
AnswerAgent QA) -> 生成简明摘要 -> 写入 src.memory -> 落盘摘要 JSON。

改自 ai-research-pipeline 的 pipeline/process_web_queue.py，去掉了跨仓库
chdir/subprocess hack，直接 import src.agents.search。

用法：
    python3 -m src.pipeline.process_web_queue [--limit N]
"""
import argparse
import asyncio
from datetime import datetime, timezone

from src.agents.answer import AnswerAgent
from src.agents.search import SearchAgent
from src.agents.search.utils import SearchUtils
from src.core.llm import LLMBase
from src.memory.config import NAMESPACE_AI_RESEARCH
from src.memory.ingest import ingest_source
from src.pipeline.generate_qa_brief import generate_brief_for_summary
from src.pipeline.paths import SUMMARIES_DIR, write_json_atomic
from src.pipeline.queue_store import claim_item, fail_item, finish_item, select_processable

QUESTIONS_WEB = [
    # 同 process_pdf_queue.py 的 QUESTIONS_PDF：定位是"大致知道文章在说什么"，
    # 不追求跟原文一样详细。
    ("overview", "用几句话概括这篇文章/帖子的核心内容，简明扼要即可。"),
    ("key_claims", "文章提出了哪些主要观点？简短列出1-3条即可，不需要展开说明。"),
    ("evidence_quality", "文章的论据/数据支撑是否充分、来源是否可核实？一两句话给出判断即可。"),
    ("relevance", "这篇内容对AI/安全从业者有什么参考价值？一两句话即可。"),
    ("caveats", "这篇内容有哪些需要谨慎对待的地方？简短指出即可，不需要展开。"),
]


async def probe_and_process(url: str) -> dict:
    """调用一次 SearchAgent.search() 探测/爬取，同时（若判定需要）触发索引。
    返回 {"strategy", "overview_answer", "success", "error"}。"""
    agent = SearchAgent(provider="openai")
    try:
        result = await agent.search(
            query="总结这篇文章的主要内容",
            target_urls=[url],
            use_case="url_analysis",
            max_iterations=1,
        )
        return {
            "strategy": result.get("processing_strategy", ""),
            "overview_answer": result.get("answer", ""),
            "success": result.get("success", False),
            "error": result.get("error"),
        }
    finally:
        await agent.utils.cleanup_mcp_clients()


async def direct_chat_qa(overview_answer: str) -> dict:
    """direct_chat 场景：探测阶段已经生成了 overview_answer（基于爬取的
    merged_text）。剩余问题对同样的上下文做纯文本 LLM QA，不重新爬取。"""
    llm = LLMBase(provider="openai")
    qa = {"overview": overview_answer}

    for key, question in QUESTIONS_WEB:
        if key == "overview":
            continue
        prompt = (
            f"以下是一篇文章的摘要性描述（已由前序步骤基于原文生成）：\n\n{overview_answer}\n\n"
            f"请基于以上内容回答问题（若信息不足以完整回答，请如实说明哪些部分无法从已知内容判断）：\n{question}"
        )
        session_id = f"web_qa_direct_{key}"
        answer = await llm.async_call_llm_chain(role="", input_prompt=prompt, session_id=session_id)
        llm.message_histories.pop(session_id, None)
        qa[key] = answer
    return qa


async def generate_title_from_qa(qa: dict, item_id: str) -> str:
    """标题兜底：正常情况下 sync 阶段已经从简报卡片的 h3 链接带上准确标题；
    但旧解析器时代的存量条目标题为空，用已生成的 overview 请 LLM 起一个短
    标题。"""
    llm = LLMBase(provider="openai")
    overview = (qa.get("overview") or "").strip()
    if not overview:
        return ""
    prompt = (
        f"以下是一篇文章的概述：\n\n{overview[:2000]}\n\n"
        "请为这篇文章起一个不超过30个字的中文标题，直接输出标题本身，"
        "不要引号，不要句号，不要任何解释。"
    )
    session_id = f"web_title_{item_id}"
    answer = await llm.async_call_llm_chain(role="", input_prompt=prompt, session_id=session_id)
    llm.message_histories.pop(session_id, None)
    return answer.strip().strip('"“”「」《》').strip()


async def index_then_chat_qa(doc_name: str) -> dict:
    qa = {}
    for key, question in QUESTIONS_WEB:
        agent = AnswerAgent(doc_name=doc_name, provider="openai")
        result = await agent.query(
            user_query=question,
            enabled_tools=["retrieve_documents"],
            selected_docs=[doc_name],
        )
        qa[key] = result.get("final_answer", "")
        agent.reset_history()
    return qa


async def process_item(item: dict) -> None:
    url = item["url"]
    print(f"  [{item['item_id']}] 探测处理策略: {url}")
    probe = await probe_and_process(url)

    if not probe["success"]:
        raise RuntimeError(probe.get("error") or "SearchAgent 探测失败，未返回具体错误")

    strategy = probe["strategy"]
    item["artifacts"]["processing_strategy"] = strategy
    print(f"  [{item['item_id']}] 策略: {strategy}")

    # 抓取失败时 SearchAgent 会返回固定的失败提示文案而不是报错——把这种
    # 情况当作真正的处理失败对待，而不是产出一份内容全是"无法判断"的空洞
    # 摘要并标记 done。
    if not (probe.get("overview_answer") or "").strip() or "未能获取到相关内容" in probe.get("overview_answer", ""):
        raise RuntimeError("SearchAgent 未能抓取到任何真实内容，跳过此条目而非生成空摘要")

    if strategy == "index_then_chat":
        doc_name = SearchUtils.generate_doc_name_from_url(url)
        item["artifacts"]["doc_name"] = doc_name
        print(f"  [{item['item_id']}] 已索引为 {doc_name}，跑五维度详细问答...")
        qa = await index_then_chat_qa(doc_name)
    else:
        print(f"  [{item['item_id']}] direct_chat：对已抓取内容做纯文本问答...")
        qa = await direct_chat_qa(probe["overview_answer"])
        doc_name = None

    if not item.get("title"):
        print(f"  [{item['item_id']}] 标题为空，用 overview 生成短标题...")
        item["title"] = await generate_title_from_qa(qa, item["item_id"])

    summary = {
        "item_id": item["item_id"],
        "type": "web_article",
        "doc_name": doc_name,
        "title": item.get("title", ""),
        "url": url,
        "coverage_date": item.get("coverage_date", ""),
        "processing_strategy": strategy,
        "agenticreader_doc_id": None,
        "qa": qa,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }

    print(f"  [{item['item_id']}] 生成简明摘要...")
    summary["qa_brief"] = await generate_brief_for_summary(summary, provider="openai")

    summary_path = SUMMARIES_DIR / "web" / f"{item['item_id']}.json"
    write_json_atomic(summary_path, summary)
    item["artifacts"]["summary_path"] = str(summary_path)

    print(f"  [{item['item_id']}] 写入 memory...")
    try:
        memory_report = await ingest_source(
            str(summary_path), source_type="ai_research",
            namespace=NAMESPACE_AI_RESEARCH, provider="openai", source_id=item["item_id"],
        )
        item["artifacts"]["memory_ingested"] = True
        item["artifacts"]["memory_chunks_added"] = memory_report.get("chunks_added", 0)
    except Exception as e:
        print(f"  [{item['item_id']}] ⚠️  memory 写入失败（不影响本条完成）: {e}")
        item["artifacts"]["memory_ingested"] = False

    item["pipeline_status"] = "done"
    item["pipeline_stage"] = "qa_done"
    print(f"  [{item['item_id']}] ✅ 完成，摘要已落盘: {summary_path}")


async def main_async(limit: int, item_id: str = None):
    item_ids = select_processable("web_article", limit=limit, item_id=item_id)
    print(f"待处理 web_article 条目数: {len(item_ids)}")

    done_count, failed_count = 0, 0
    for iid in item_ids:
        item = claim_item(iid)
        if item is None:
            print(f"\n=== 跳过 {iid}：条目已不存在 ===")
            continue
        print(f"\n=== 处理 {iid}: {item.get('url', '')} ===")
        try:
            await process_item(item)
            finish_item(iid, item)
            done_count += 1
        except Exception as e:
            print(f"  [{iid}] ❌ 失败: {e}")
            fail_item(iid, e)
            failed_count += 1

    print(f"\n汇总: 成功 {done_count} / 失败 {failed_count} / 共处理 {len(item_ids)} 条")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--item-id", default=None,
                        help="只处理这一个条目（webapp 按需触发单篇时用）")
    args = parser.parse_args()
    asyncio.run(main_async(args.limit, args.item_id))


if __name__ == "__main__":
    main()
