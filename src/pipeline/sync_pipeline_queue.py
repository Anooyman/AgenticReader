"""从本地 AATF-Intelligence-Briefs 解析出待处理条目，写入 pipeline_queue.json。

数据源：
- research-paper-radar.html 里的 <article class="paper"> 卡片 -> pdf_arxiv 条目
- daily-signals.html 里的外部文章链接 -> web_article 条目

HTML 解析本身在 briefs_parser.py（与 webapp 的简报浏览页共用同一实现，
两边算出的 item_id 必须一致，页面才能正确标注"这条处理过没有"）。这里只
负责把解析结果落成 queue 条目。

用法：
    python3 -m src.pipeline.sync_pipeline_queue --briefs-dir ~/Desktop/AATF-Intelligence-Briefs --coverage-date 2026-07-22
"""
import argparse
from pathlib import Path

from src.pipeline.briefs_parser import parse_paper_cards, parse_signal_cards
from src.pipeline.queue_store import load_queue, new_queue_item, save_queue


def to_queue_items(cards: list) -> list:
    return [
        new_queue_item(
            item_id=card["item_id"],
            item_type=card["type"],
            url=card["url"],
            title=card["title"],
            coverage_date=card["coverage_date"],
            pdf_url=card.get("pdf_url"),
        )
        for card in cards
    ]


def upsert(queue: dict, items: list) -> tuple:
    added, skipped = 0, 0
    for item in items:
        existing = queue.get(item["item_id"])
        if existing is not None:
            # 已存在的条目不整体覆盖（保留处理状态/artifacts），但旧解析器
            # 时代留下的空标题可以借这次解析补上。
            if not existing.get("title") and item.get("title"):
                existing["title"] = item["title"]
            skipped += 1
            continue
        queue[item["item_id"]] = item
        added += 1
    return added, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--briefs-dir", default=str(Path.home() / "Desktop" / "AATF-Intelligence-Briefs"))
    parser.add_argument("--coverage-date", required=True, help="e.g. 2026-07-22")
    args = parser.parse_args()

    briefs_dir = Path(args.briefs_dir) / args.coverage_date

    queue = load_queue()

    pdf_items = to_queue_items(
        parse_paper_cards(briefs_dir / "research-paper-radar.html", args.coverage_date))
    web_items = to_queue_items(
        parse_signal_cards(briefs_dir / "daily-signals.html", args.coverage_date))

    pdf_added, pdf_skipped = upsert(queue, pdf_items)
    web_added, web_skipped = upsert(queue, web_items)

    save_queue(queue)

    print(f"pdf_arxiv: found {len(pdf_items)}, added {pdf_added}, already existed {pdf_skipped}")
    print(f"web_article: found {len(web_items)}, added {web_added}, already existed {web_skipped}")
    print(f"queue total: {len(queue)} items")


if __name__ == "__main__":
    main()
