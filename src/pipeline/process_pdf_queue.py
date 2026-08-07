"""批量处理 pipeline_queue.json 里 type=pdf_arxiv 的条目：
下载 -> (判重) IndexingAgent 索引 -> 六维度详细问答 -> 生成简明摘要 ->
写入 src.memory -> 落盘摘要 JSON。

改自 ai-research-pipeline 的 pipeline/process_pdf_queue.py。原实现要先
os.chdir(AGENTICREADER_ROOT) + sys.path.insert 才能 import IndexingAgent/
AnswerAgent（跨仓库 venv 隔离），合并进 AgenticReader 后两者在同一项目根、
同一套 sys.path 下运行，直接绝对 import 即可，不再需要那套 hack。

单条目失败不阻塞整批：每个 item 独立 try/except + continue，超过
MAX_ATTEMPTS 次转 failed_permanent。每步处理后立即 checkpoint 落盘 queue。

用法：
    python3 -m src.pipeline.process_pdf_queue [--limit N] [--provider openai]
"""
import argparse
import asyncio
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from src.agents.answer import AnswerAgent
from src.agents.indexing import IndexingAgent
from src.config.settings import DATA_ROOT
from src.memory.config import NAMESPACE_AI_RESEARCH
from src.memory.ingest import ingest_source
from src.pipeline.generate_qa_brief import generate_brief_for_summary
from src.pipeline.paths import SUMMARIES_DIR, write_json_atomic
from src.pipeline.queue_store import claim_item, fail_item, finish_item, select_processable

PDF_DIR = Path(DATA_ROOT) / "pdf"

QUESTIONS_PDF = [
    # 这些问题的定位是"大致知道论文在做什么"，不是"替代读论文"——详细程度
    # 控制在几段话以内，而不是要求"不要省略细节/尽可能全面"。这样做有两个
    # 直接好处：(1) report UI 上更好展示；(2) 写入 memory 时，这段文本本身
    # 还会被 ingest 管线再浓缩一次成 abstract/keywords，源头信息量越大对
    # 这道工序越是浪费，并不会让最终检索到的摘要更详细。真正需要深挖细节
    # 时，chat 里的 deep_dive_document 会直接查询 AgenticReader 的原始索引。
    ("full_content", "用几句话概括这篇论文讲了什么问题、用什么方法、得到什么结论，简明扼要即可。"),
    ("innovation", "这篇论文最核心的创新点是什么？一两句话说清楚新在哪里即可，不需要展开。"),
    ("experiments", "论文的实验大致验证了什么、主要结论是什么？给出关键结果即可，不需要列全部数据。"),
    ("algorithm_detail", "论文核心方法的关键设计思路是什么？简要说明，不需要展开公式推导。"),
    ("advantages", "这篇论文相对同类工作的主要优势和主要局限各是什么？各一两句话即可。"),
    ("key_takeaways", "这篇论文最值得记住的1-3条结论是什么？简短列出即可。"),
]


def load_doc_registry() -> dict:
    registry_path = Path(DATA_ROOT) / "doc_registry.json"
    if not registry_path.exists():
        return {}
    with open(registry_path, encoding="utf-8") as f:
        return json.load(f)


def find_registered_doc(registry: dict, doc_name: str):
    for doc_id, entry in registry.items():
        if entry.get("doc_name") == doc_name:
            return entry
    return None


def download_pdf(pdf_url: str, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest_path, "wb") as out:
        out.write(resp.read())


async def index_document(doc_name: str, pdf_path: Path, provider: str):
    agent = IndexingAgent(provider=provider, pdf_preset="high")
    result = await agent.graph.ainvoke({
        "doc_name": doc_name,
        "doc_path": str(pdf_path),
        "doc_type": "pdf",
        "is_complete": False,
    })
    if result.get("error") or result.get("status") == "error":
        raise RuntimeError(result.get("error") or "IndexingAgent 索引失败，未返回具体错误")
    return result


async def run_qa(doc_name: str, provider: str) -> dict:
    qa = {}
    for key, question in QUESTIONS_PDF:
        agent = AnswerAgent(doc_name=doc_name, provider=provider)
        result = await agent.query(
            user_query=question,
            enabled_tools=["retrieve_documents"],
            selected_docs=[doc_name],
        )
        qa[key] = result.get("final_answer", "")
        agent.reset_history()
    return qa


async def process_item(item: dict, provider: str, registry: dict) -> None:
    doc_name = item["item_id"]
    pdf_path = PDF_DIR / f"{doc_name}.pdf"

    existing = find_registered_doc(registry, doc_name)
    already_indexed = existing is not None and existing.get("status") == "completed"

    if already_indexed:
        print(f"  [{doc_name}] 已在 AgenticReader doc_registry 中完成索引，跳过下载/索引")
        item["artifacts"]["agenticreader_doc_id"] = existing.get("doc_id")
        item["pipeline_stage"] = "indexed"
    else:
        if item.get("pipeline_stage") is None:
            print(f"  [{doc_name}] 下载 PDF: {item['pdf_url']}")
            download_pdf(item["pdf_url"], pdf_path)
            item["pipeline_stage"] = "downloaded"

        print(f"  [{doc_name}] 调用 IndexingAgent 索引...")
        result = await index_document(doc_name, pdf_path, provider)
        item["artifacts"]["agenticreader_doc_id"] = result.get("doc_id")
        item["artifacts"]["index_path"] = result.get("index_path")
        item["pipeline_stage"] = "indexed"

    print(f"  [{doc_name}] 跑六维度详细问答...")
    qa = await run_qa(doc_name, provider)
    item["pipeline_stage"] = "qa_done"

    summary = {
        "item_id": item["item_id"],
        "type": "pdf_arxiv",
        "doc_name": doc_name,
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "pdf_url": item.get("pdf_url", ""),
        "coverage_date": item.get("coverage_date", ""),
        "agenticreader_doc_id": item["artifacts"].get("agenticreader_doc_id", ""),
        "index_path": item["artifacts"].get("index_path", ""),
        "qa": qa,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }

    print(f"  [{doc_name}] 生成简明摘要...")
    summary["qa_brief"] = await generate_brief_for_summary(summary, provider)

    summary_path = SUMMARIES_DIR / "pdf" / f"{doc_name}.json"
    write_json_atomic(summary_path, summary)
    item["artifacts"]["summary_path"] = str(summary_path)

    print(f"  [{doc_name}] 写入 memory...")
    try:
        memory_report = await ingest_source(
            str(summary_path), source_type="ai_research",
            namespace=NAMESPACE_AI_RESEARCH, provider=provider, source_id=doc_name,
        )
        item["artifacts"]["memory_ingested"] = True
        item["artifacts"]["memory_chunks_added"] = memory_report.get("chunks_added", 0)
    except Exception as e:
        # memory 写入失败不阻断整条流程——摘要已经落盘，report 页面照常可用，
        # 只是暂时搜不到。留空 memory_ingested，下次跑批处理时会被
        # sync_memory_ingest 的补灌逻辑捡起来重试。
        print(f"  [{doc_name}] ⚠️  memory 写入失败（不影响本条完成）: {e}")
        item["artifacts"]["memory_ingested"] = False

    item["pipeline_status"] = "done"
    print(f"  [{doc_name}] ✅ 完成，摘要已落盘: {summary_path}")


async def main_async(limit: int, provider: str, item_id: str = None):
    registry = load_doc_registry()

    # failed_retryable 也纳入选取——mark_failed 会在 attempts 达到
    # MAX_ATTEMPTS 时转 failed_permanent，所以这里天然有重试上限。
    item_ids = select_processable("pdf_arxiv", limit=limit, item_id=item_id)
    print(f"待处理 pdf_arxiv 条目数: {len(item_ids)}")

    done_count, failed_count = 0, 0
    for iid in item_ids:
        # 认领 / 处理 / 回写三段分开：中间那段动辄几十分钟，期间不持有
        # queue，也就不会用旧快照覆盖别人的改动。
        item = claim_item(iid)
        if item is None:
            print(f"\n=== 跳过 {iid}：条目已不存在 ===")
            continue
        print(f"\n=== 处理 {iid}: {item.get('title', '')} ===")
        try:
            await process_item(item, provider, registry)
            finish_item(iid, item)
            done_count += 1
        except Exception as e:
            print(f"  [{iid}] ❌ 失败: {e}")
            fail_item(iid, e)
            failed_count += 1

    print(f"\n汇总: 成功 {done_count} / 失败 {failed_count} / 共处理 {len(item_ids)} 条")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="限制处理条数（0=不限制）")
    parser.add_argument("--item-id", default=None,
                        help="只处理这一个条目（webapp 按需触发单篇时用）")
    parser.add_argument("--provider", default="openai", help="LLM provider")
    args = parser.parse_args()
    asyncio.run(main_async(args.limit, args.provider, args.item_id))


if __name__ == "__main__":
    main()
