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


def load_summaries(subdir: str) -> list:
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


def render_report(coverage_date: str) -> str:
    pdf_summaries = load_summaries("pdf")
    web_summaries = load_summaries("web")

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
    parser.add_argument("--coverage-date", default=str(date.today()))
    args = parser.parse_args()

    html_content = render_report(args.coverage_date)

    out_dir = OUTPUT_DIR / args.coverage_date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "report.html"
    out_path.write_text(html_content, encoding="utf-8")

    print(f"报告已生成: {out_path}")


if __name__ == "__main__":
    main()
