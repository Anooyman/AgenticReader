"""为已有摘要 JSON（data/pipeline/summaries/{pdf,web}/*.json）补一份"简明
摘要"（qa_brief 字段），供 report 页面默认展示——原有的 qa 字段（六/五维度
详细问答，单条经常几千字）适合"需要深挖细节时展开阅读"，但作为列表默认
展示太长。

qa_brief 结构与 qa 完全对应（同样的 key），每个 value 是对该维度详细回答
的一句话精简结论（不是简单截断——真正调一次 LLM 做提炼）。

改自 ai-research-pipeline 的 pipeline/generate_qa_brief.py。原实现里那段
"先 import src.agents.answer 确保 settings.py 走完整"的 workaround，在
合并进同一个项目后不再需要——process_pdf_queue.py/process_web_queue.py
早已在同一个 Python 进程里正常 import 过 AnswerAgent，不存在"跨仓库首次
import 顺序敏感"的问题。

幂等：已经有 qa_brief 且其 key 集合与当前 qa 一致的摘要会被跳过，不重复
调用 LLM。

用法：
    python3 -m src.pipeline.generate_qa_brief [--limit N] [--provider openai]
"""
import argparse
import asyncio
import json
from pathlib import Path

from src.core.llm import LLMBase
from src.pipeline.paths import SUMMARIES_DIR, write_json_atomic
from src.pipeline.qa_labels import QA_LABELS

BRIEF_PROMPT_TEMPLATE = (
    "以下是针对一篇论文/文章「{label}」这个维度的详细回答：\n\n{answer}\n\n"
    "请把以上内容提炼成一句话结论（不超过60个字，直接给出结论本身，"
    "不要加\"这段内容讲的是\"之类的引导语，不要换行）。"
)


def needs_brief(summary: dict) -> bool:
    qa = summary.get("qa") or {}
    brief = summary.get("qa_brief") or {}
    qa_keys_with_content = {k for k, v in qa.items() if v}
    return not qa_keys_with_content.issubset(set(brief.keys()))


async def generate_brief_for_summary(summary: dict, provider: str) -> dict:
    llm = LLMBase(provider=provider)
    qa = summary.get("qa") or {}
    brief = dict(summary.get("qa_brief") or {})

    for key, answer in qa.items():
        if not answer:
            continue
        if key in brief:
            continue
        label = QA_LABELS.get(key, key)
        prompt = BRIEF_PROMPT_TEMPLATE.format(label=label, answer=answer)
        session_id = f"qa_brief_{summary['item_id']}_{key}"
        result = await llm.async_call_llm_chain(role="", input_prompt=prompt, session_id=session_id)
        llm.message_histories.pop(session_id, None)
        brief[key] = result.strip()

    return brief


async def process_one(path: Path, provider: str) -> None:
    with open(path, encoding="utf-8") as f:
        summary = json.load(f)

    if not needs_brief(summary):
        print(f"  [{summary['item_id']}] 已有完整 qa_brief，跳过")
        return

    print(f"  [{summary['item_id']}] 生成简明摘要...")
    generated = await generate_brief_for_summary(summary, provider)

    # 写回不是快照覆写，而是"对当前盘上内容合并 qa_brief 字段"：
    # 摘要文件的权威写者是 job_runner 的 process_*（内联生成走同一 key 空间），
    # 本 CLI 的 LLM 生成耗时以十秒计，从旧快照整文件回写会把期间内联更新的
    # 其它字段连灰抹掉。锁跨不了生成（那等于持锁做 LLM），所以关键操作
    # 收窄到写前一瞬：拿锁重读、只把盘上还没有的键补进去、原子落盘。
    from src.core import filelock
    lock_path = Path(str(path) + ".lock")
    with open(lock_path, "w") as lock_file:
        try:
            filelock.acquire(lock_file.fileno())
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                current = summary  # 文件读不回就用我们的生成源打底，别丢内容
            qa = dict(current.get("qa_brief") or {})
            for key, value in generated.items():
                qa.setdefault(key, value)
            current["qa_brief"] = qa
            write_json_atomic(path, current)
        finally:
            filelock.release(lock_file.fileno())
    print(f"  [{summary['item_id']}] ✅ 完成")


async def main_async(limit: int, provider: str):
    paths = []
    for subdir in ("pdf", "web"):
        d = SUMMARIES_DIR / subdir
        if d.exists():
            paths.extend(sorted(d.glob("*.json")))
    if limit:
        paths = paths[:limit]

    print(f"待处理摘要数: {len(paths)}")
    for path in paths:
        try:
            await process_one(path, provider)
        except Exception as e:
            print(f"  [{path.stem}] ❌ 失败: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--provider", default="openai")
    args = parser.parse_args()
    asyncio.run(main_async(args.limit, args.provider))


if __name__ == "__main__":
    main()
