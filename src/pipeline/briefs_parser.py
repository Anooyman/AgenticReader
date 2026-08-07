"""AATF-Intelligence-Briefs 的 HTML 解析——批处理与 webapp 共用的唯一实现。

改自 ai-research-pipeline 的 pipeline/briefs_parser.py，逻辑原样保留。
`sync_pipeline_queue.py`（批处理，登记进 queue）和简报浏览页（只读预览，
不落盘）必须算出完全一致的 item_id，否则页面无法正确比对"这条是不是已经
处理过了"。

item_id 的推导（arxiv_id_no_version / url_hash）也收在这里作为唯一来源。

## 解析出来的东西比原来多

原先只取 title/url/id，卡片里现成的中文导读、English brief 等全部被丢弃。
简报浏览页要让人"先看简介再决定要不要花 20 分钟处理这篇"，靠的就是这些
字段——它们本来就在 HTML 里，不需要额外调 LLM 生成。

两个文件的 `<div class="cn">` 内部结构不同（论文卡用 `<br>` 分隔，signals
卡用 `<p>` 包裹），且小标题措辞也不同（"值得关注" vs "为何值得看"），所以
`_parse_cn_block` 统一按"`<b>标签：</b>` 的位置切分 + 去标签"来处理，不对
具体标签名做硬编码。
"""
import hashlib
import html as html_module
import re
from pathlib import Path

# ---- 论文卡（research-paper-radar.html）----
# 源工具的模板改过版：旧版是 <article class="paper">...<h3>标题</h3>...，
# 新版（2026-08-06 起观察到）简化成了 <article class="card">...<h2>标题</h2>...，
# 且不再有 score/themes/authors/English brief/why 这些字段，只剩标题+
# arXiv 链接+中文摘要+中文导读。两种都要认，不能假设格式永远不变。
ARTICLE_RE = re.compile(r'<article class="(?:paper|card)">(.*?)</article>', re.DOTALL)
TITLE_RE = re.compile(r'<h([23])[^>]*>(.*?)</h\1>', re.DOTALL)
ARXIV_ABS_RE = re.compile(r'href="(https?://arxiv\.org/abs/[0-9.]+v?[0-9]*)"')
ARXIV_PDF_RE = re.compile(r'href="(https?://arxiv\.org/pdf/[0-9.]+v?[0-9]*)"')
SCORE_RE = re.compile(r'<div class="score">(.*?)</div>', re.DOTALL)
META_RE = re.compile(r'<p class="meta">(.*?)</p>', re.DOTALL)
THEMES_RE = re.compile(r'<p class="meta">\s*AATF themes:\s*(.*?)</p>', re.DOTALL)
ENGLISH_BRIEF_RE = re.compile(r'<b>\s*English brief:\s*</b>(.*?)</p>', re.DOTALL)
WHY_RE = re.compile(r'<p class="why">\s*<b>.*?</b>(.*?)</p>', re.DOTALL)

# daily-signals.html 的文章卡片：<article class="card ...">，真实文章的标题
# 是 <h3><a href="原文URL">标题</a></h3>——标题和链接在这里是准确配对的。
# 推文摘要卡的 h3 是纯文本、twitter 链接全在卡内 source-list 里，按
# "只取 h3 里的链接"这一条规则就天然被排除。
SIGNAL_CARD_RE = re.compile(r'<article class="card[^"]*">(.*?)</article>', re.DOTALL)
SIGNAL_H3_LINK_RE = re.compile(r'<h3[^>]*>\s*<a\s+href="(https?://[^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
TOPIC_TAG_RE = re.compile(r'<span class="topic-tag">(.*?)</span>', re.DOTALL)
DETAILS_RE = re.compile(r'<details>(.*?)</details>', re.DOTALL)
FOLLOWUP_RE = re.compile(r'<b>\s*后续可追问[：:]\s*</b>(.*?)</p>', re.DOTALL)
EXCLUDED_DOMAINS = ("news.aatf.ai", "arxiv.org", "twitter.com", "x.com")

# 两个文件共用。class 属性用词边界匹配而不是精确字符串——"未启用 --llm"
# 时源 HTML 会把这块标成 class="cn muted"（多一个 muted 类表示占位提示），
# 精确匹配 class="cn" 会直接漏掉整个块，导致页面上完全看不到这条提示，
# 反而显得比"卡片本身没有中文导读"更费解。
CN_DIV_RE = re.compile(r'<div class="cn(?:\s[^"]*)?">(.*?)</div>', re.DOTALL)
CN_LABEL_RE = re.compile(r'<b>\s*([^<：:]+?)\s*[：:]\s*</b>', re.DOTALL)

# 源工具没开 --llm 时塞进 cn 块里的固定提示句——不是真的导读内容。
_NO_LLM_PLACEHOLDER_RE = re.compile(r'本次未启用\s*LLM')

# 另一种占位套话：某些批次的 daily-signals 卡片里，"中文导读"字段不是真的
# 针对这篇文章的分析，而是原样套用 "这条AI新闻内容聚焦于'{标题}'。建议先看
# 原文摘要和方法/证据，再判断其影响范围；本页摘要严格限于已捕获来源内容。"
# 这句模板——每张卡片文字完全相同（只有引号里的标题不同），本质上和
# "本次未启用 LLM" 是同一类问题：没有真正生成内容，用占位句顶替。按这句
# 模板末尾的固定措辞识别，不当真导读展示。
_GENERIC_TEMPLATE_RE = re.compile(r'本页摘要严格限于已捕获来源内容')

# 有些格式把英文原文摘要也塞进了 cn 块里当成一个 label（比如"来源摘要"），
# 而不是像旧格式那样放在 cn 块外的独立字段（English brief/excerpt）。
# 用户明确要求不看英文摘要，这里按 label 名直接排除，与旧格式的
# english_brief/excerpt 排除逻辑保持一致。
_EXCLUDED_CN_LABELS = {"来源摘要"}

TAG_RE = re.compile(r'<[^>]+>')


# ---- id 推导（唯一来源）----

def arxiv_id_no_version(raw_id: str) -> str:
    """去掉版本号后缀，如 2607.18264v1 -> 2607.18264。"""
    if "v" in raw_id:
        base, _, ver = raw_id.rpartition("v")
        if ver.isdigit():
            return base
    return raw_id


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


# ---- 文本清理 ----

def _text(raw: str) -> str:
    """去标签 + 反转义 + 折叠空白。<br> 之类的换行标记退化成空格，因为这些
    字段在 UI 上是整段展示的，不需要保留原有换行。"""
    if not raw:
        return ""
    return re.sub(r'\s+', ' ', html_module.unescape(TAG_RE.sub(' ', raw))).strip()


def _parse_cn_block(card: str) -> dict:
    """把 <div class="cn"> 里的"小标题 + 正文"拆成 dict。

    按 `<b>标签：</b>` 出现的位置切分、再各自去标签，因此对两种嵌套形式
    （<br> 分隔 / <p> 包裹）通吃，也不依赖具体的标签名——论文卡是
    导读/值得关注/阅读提示，signals 卡是 导读/为何值得看/核验提示。

    源工具没开 `--llm` 时，这个块里塞的不是真的中文导读，而是一句提示
    "本次未启用 LLM。运行工具时加入 --llm ..."——原样按 label 解析出来会
    让页面上一大片卡片都显示同一句话，看起来像是"这些论文的导读都长
    一样"，比直接留空更容易误导人，所以在这一步就识别并丢弃，交回空
    dict（页面上按现有的"没有中文导读"分支处理，不新增专门的占位态）。

    按 label 级别排除，而不是整块清空——同一个 cn 块里可能有的 label
    是垃圾（英文原文摘要、占位套话），有的是真实内容，只丢弃有问题的
    那一条，保留其余。"""
    m = CN_DIV_RE.search(card)
    if not m:
        return {}
    inner = m.group(1)
    if _NO_LLM_PLACEHOLDER_RE.search(inner):
        return {}
    labels = list(CN_LABEL_RE.finditer(inner))
    result = {}
    for i, match in enumerate(labels):
        label = match.group(1).strip()
        if label in _EXCLUDED_CN_LABELS:
            continue
        end = labels[i + 1].start() if i + 1 < len(labels) else len(inner)
        body = _text(inner[match.end():end])
        if not body or _GENERIC_TEMPLATE_RE.search(body):
            continue
        result[label] = body
    return result


# ---- 论文卡 ----

def parse_paper_cards(html_path: Path, coverage_date: str) -> list:
    """解析 research-paper-radar.html。缺少标题或 arXiv abstract 链接的卡
    直接跳过（拿不到 item_id 就没法进管线）。"""
    if not Path(html_path).exists():
        return []
    text = Path(html_path).read_text(encoding="utf-8")

    items = []
    for card in ARTICLE_RE.findall(text):
        title_match = TITLE_RE.search(card)
        abs_match = ARXIV_ABS_RE.search(card)
        if not (title_match and abs_match):
            continue

        abs_url = abs_match.group(1)
        raw_id = abs_url.rstrip("/").rsplit("/", 1)[-1]
        pdf_match = ARXIV_PDF_RE.search(card)

        # 新版模板（<article class="card">）的 meta 行只有
        # "arXiv：2608.05000 ↗" 这一条，本身就是 arXiv 编号的重复展示，
        # 不是作者信息——按是否含 "arXiv" 关键字排除，避免把这行错当成
        # "author" 塞进"更多信息"。旧版模板没有这个问题（authors 和
        # "AATF themes:" 是两条独立的 meta）。
        metas = [_text(m) for m in META_RE.findall(card)]
        authors = next(
            (m for m in metas if not m.startswith("AATF themes:") and "arXiv" not in m),
            "",
        )

        themes_match = THEMES_RE.search(card)
        themes = []
        if themes_match:
            themes = [t.strip() for t in _text(themes_match.group(1)).split(",") if t.strip()]

        score_match = SCORE_RE.search(card)
        english_match = ENGLISH_BRIEF_RE.search(card)
        why_match = WHY_RE.search(card)

        items.append({
            "item_id": arxiv_id_no_version(raw_id),
            "type": "pdf_arxiv",
            "title": _text(title_match.group(2)),
            "url": abs_url,
            "pdf_url": pdf_match.group(1) if pdf_match else f"https://arxiv.org/pdf/{raw_id}",
            "coverage_date": coverage_date,
            "score": _text(score_match.group(1)) if score_match else "",
            "authors": authors,
            "themes": themes,
            "english_brief": _text(english_match.group(1)) if english_match else "",
            "cn": _parse_cn_block(card),
            "why": _text(why_match.group(1)) if why_match else "",
        })
    return items


# ---- signals 卡 ----

def parse_signal_cards(html_path: Path, coverage_date: str) -> list:
    """解析 daily-signals.html。只取 h3 里带链接的卡（推文摘要卡的 h3 是
    纯文本，天然被排除），并按 URL 去重、排除站内与 arXiv/推特域名。"""
    if not Path(html_path).exists():
        return []
    text = Path(html_path).read_text(encoding="utf-8")

    items = []
    seen_urls = set()
    for card in SIGNAL_CARD_RE.findall(text):
        link_match = SIGNAL_H3_LINK_RE.search(card)
        if not link_match:
            continue
        url = link_match.group(1)
        if any(domain in url for domain in EXCLUDED_DOMAINS):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        topic_match = TOPIC_TAG_RE.search(card)
        details_match = DETAILS_RE.search(card)
        excerpt, followup = "", ""
        if details_match:
            details_inner = details_match.group(1)
            followup_match = FOLLOWUP_RE.search(details_inner)
            if followup_match:
                followup = _text(followup_match.group(1))
            body = re.sub(r'<summary>.*?</summary>', '', details_inner, flags=re.DOTALL)
            if followup_match:
                body = body.replace(followup_match.group(0), '')
            excerpt = _text(body)

        items.append({
            "item_id": url_hash(url),
            "type": "web_article",
            "title": _text(link_match.group(2)),
            "url": url,
            "coverage_date": coverage_date,
            "topic_tag": _text(topic_match.group(1)) if topic_match else "",
            "cn": _parse_cn_block(card),
            "excerpt": excerpt,
            "followup": followup,
        })
    return items


# ---- 目录扫描 ----

def list_coverage_dates(briefs_dir: Path) -> list:
    """briefs 目录下形如 YYYY-MM-DD 的子目录，倒序（新的在前）。"""
    briefs_dir = Path(briefs_dir)
    if not briefs_dir.is_dir():
        return []
    dates = [
        p.name for p in briefs_dir.iterdir()
        if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)
    ]
    return sorted(dates, reverse=True)


def parse_briefs_dir(briefs_dir: Path, coverage_date: str) -> dict:
    """一次解析某一天的两个 HTML，返回 {"pdf": [...], "web": [...]}。"""
    day_dir = Path(briefs_dir) / coverage_date
    return {
        "pdf": parse_paper_cards(day_dir / "research-paper-radar.html", coverage_date),
        "web": parse_signal_cards(day_dir / "daily-signals.html", coverage_date),
    }
