"""读取 data/pipeline/summaries/{pdf,web}/*.json，生成一份独立的静态 HTML
report。

每个条目展示：标题/来源/原文链接 + 折叠展开的详细QA区块 + （如有）
"AgenticReader doc_id: xxx，可继续深度对话"提示。

改自 ai-research-pipeline 的 pipeline/render_report.py，逻辑原样保留。

用法：
    python3 -m src.pipeline.render_report [--coverage-date 2026-07-22]
"""
import argparse
import html
import json
from datetime import date

from src.pipeline.paths import OUTPUT_DIR, SUMMARIES_DIR
from src.pipeline.qa_labels import QA_LABELS


def load_summaries(subdir: str, coverage_date: str = None) -> list:
    """读摘要。coverage_date 给了就按天筛——它不再只是标题装饰：以前
    "--coverage-date X 出 X 日的报告"这句 CLI 承诺下，实际渲染的却是全部
    历史摘要拼盘，日期只写进了页面文案，静默给用户一份错报告。
    缺 coverage_date 字段的旧条目不属于任何"某天"，同样不放进按日过滤的
    结果里（全量出报请用 --all）。"""
    d = SUMMARIES_DIR / subdir
    if not d.exists():
        return []
    summaries = []
    for path in sorted(d.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                summaries.append(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[render_report] 跳过无法解析的摘要文件 {path}: {e}")
    if coverage_date is not None:
        summaries = [s for s in summaries
                     if str(s.get("coverage_date") or "")[:10] == coverage_date]
    return summaries


def render_qa_details(qa: dict) -> str:
    rows = []
    for key, answer in qa.items():
        if not answer:
            continue
        label = QA_LABELS.get(key, key)
        body = html.escape(answer).replace("\n", "<br>")
        rows.append(f'<dt>{html.escape(label)}</dt><dd>{body}</dd>')
    return "<dl>" + "".join(rows) + "</dl>"


def render_pdf_card(s: dict) -> str:
    title = html.escape(s.get("title") or s.get("doc_name", ""))
    url = s.get("url", "")
    pdf_url = s.get("pdf_url", "")
    doc_id = s.get("agenticreader_doc_id", "")
    doc_name = s.get("doc_name", "")

    links = []
    if url:
        links.append(f'<a href="{html.escape(url)}" target="_blank" rel="noopener">arXiv abstract ↗</a>')
    if pdf_url:
        links.append(f'<a href="{html.escape(pdf_url)}" target="_blank" rel="noopener">Original PDF ↗</a>')

    deep_dive_hint = ""
    if doc_id:
        deep_dive_hint = (
            f'<p class="deep-dive-hint">可通过 AgenticReader 继续深度对话'
            f'（doc_name: <code>{html.escape(doc_name)}</code>, doc_id: <code>{html.escape(doc_id)}</code>）</p>'
        )

    return f"""
    <article class="paper">
      <span class="badge">已深度解析 · PDF</span>
      <h3>{title}</h3>
      <p class="meta">覆盖日期: {html.escape(s.get('coverage_date', ''))}</p>
      <div class="links">{''.join(links)}</div>
      <details class="deep-qa">
        <summary>展开六维度深度解读</summary>
        {render_qa_details(s.get('qa', {}))}
      </details>
      {deep_dive_hint}
    </article>
    """


def render_web_card(s: dict) -> str:
    title = html.escape(s.get("title") or s.get("url", ""))
    url = s.get("url", "")
    strategy = s.get("processing_strategy", "")
    doc_name = s.get("doc_name")

    deep_dive_hint = ""
    if doc_name:
        deep_dive_hint = (
            f'<p class="deep-dive-hint">可通过 AgenticReader 继续深度对话'
            f'（doc_name: <code>{html.escape(doc_name)}</code>）</p>'
        )

    return f"""
    <article class="paper">
      <span class="badge">已深度解析 · {html.escape(strategy)}</span>
      <h3>{title}</h3>
      <p class="meta">覆盖日期: {html.escape(s.get('coverage_date', ''))}</p>
      <div class="links"><a href="{html.escape(url)}" target="_blank" rel="noopener">原文链接 ↗</a></div>
      <details class="deep-qa">
        <summary>展开五维度深度解读</summary>
        {render_qa_details(s.get('qa', {}))}
      </details>
      {deep_dive_hint}
    </article>
    """


def render_report(coverage_date: str, all_entries: bool = False) -> str:
    """渲染报告。默认只收 coverage_date 当天的条目——"出 X 日的报告"必须
    真是 X 日的内容。all_entries=True（--all）时出全部历史，日期仅作标题/
    落盘目录名，这是老行为，显式旗标才拿得到。"""
    date_filter = None if all_entries else coverage_date
    pdf_summaries = load_summaries("pdf", date_filter)
    web_summaries = load_summaries("web", date_filter)

    pdf_cards = "".join(render_pdf_card(s) for s in pdf_summaries)
    web_cards = "".join(render_web_card(s) for s in web_summaries)

    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Research Pipeline · {html.escape(coverage_date)}</title>
<style>
:root{{--bg:#08111f;--panel:#101e32;--ink:#eaf2ff;--muted:#a9b9d0;--accent:#73d6c7;--line:#263b59}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}}
main{{max-width:1000px;margin:auto;padding:34px 22px 80px}}
h1{{font-size:32px}}
h2{{font-size:22px;margin-top:40px;border-bottom:1px solid var(--line);padding-bottom:8px}}
.paper{{border:1px solid var(--line);border-radius:14px;background:var(--panel);padding:20px;margin:16px 0}}
.badge{{display:inline-block;background:var(--accent);color:#08201e;font-weight:700;font-size:12px;padding:3px 10px;border-radius:999px;margin-bottom:8px}}
h3{{margin:6px 0 10px;font-size:19px}}
.meta{{color:var(--muted);font-size:13px;margin:4px 0}}
.links a{{color:var(--accent);margin-right:14px;text-decoration:none}}
.links a:hover{{text-decoration:underline}}
details.deep-qa{{margin-top:14px;background:#0b1829;border-radius:10px;padding:12px 16px}}
summary{{cursor:pointer;font-weight:600;color:var(--accent)}}
dl{{margin:10px 0 0}}
dt{{font-weight:700;color:var(--accent);margin-top:14px}}
dd{{margin:6px 0 0;color:var(--ink)}}
.deep-dive-hint{{margin-top:12px;font-size:13px;color:var(--muted)}}
code{{background:#0b1829;padding:1px 6px;border-radius:4px}}
</style></head>
<body><main>
<h1>AI Research Pipeline</h1>
<p class="meta">覆盖日期: {html.escape(coverage_date)} · 共 {len(pdf_summaries)} 篇论文 · {len(web_summaries)} 篇文章</p>

<h2>📄 论文深度解析（{len(pdf_summaries)}）</h2>
{pdf_cards or '<p class="meta">暂无</p>'}

<h2>🌐 文章深度解析（{len(web_summaries)}）</h2>
{web_cards or '<p class="meta">暂无</p>'}

</main></body></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage-date", default=str(date.today()),
                        help="只收这一天的条目出报告；配 --all 时仅作标题/目录名")
    parser.add_argument("--all", action="store_true",
                        help="出全部历史摘要，不按 coverage-date 过滤（老行为）")
    args = parser.parse_args()

    html_content = render_report(args.coverage_date, all_entries=args.all)
    out_dir = OUTPUT_DIR / args.coverage_date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "report.html"
    out_path.write_text(html_content, encoding="utf-8")

    # 过滤后归零要出声：静默交一份"0 篇"的报告正是这工具以前最误导的行为，
    # 现在它至少还知道自己是空的——但只有页面上那行"共 0 篇"，命令行里
    # 必须同样看得见。
    counts = load_summaries("pdf", None if args.all else args.coverage_date)
    counts_w = load_summaries("web", None if args.all else args.coverage_date)
    if not counts and not counts_w and not args.all:
        print(f"⚠️  {args.coverage_date} 没有匹配到任何摘要条目——报告为空；"
              "要么这天确实没入库，要么需要 --all 出全部历史")
    print(f"报告已生成: {out_path}（pdf {len(counts)} / web {len(counts_w)}）")


if __name__ == "__main__":
    main()
