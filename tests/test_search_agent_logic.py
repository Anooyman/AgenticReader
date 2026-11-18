"""SearchAgent 纯逻辑层用例——不联网、不启 MCP、不调 LLM。

Lead 划的范围很清楚：只测逻辑层（use_case 判定、strategy 阈值切档、
sources/warnings 组装、错误路径的返回形状）。凡是会真发 MCP/HTTP 的地方
一律 monkeypatch 掉 tools / llm，桩替身只做两件事：按预设返回数据、
记下被调用了几次。

覆盖两块：
1. `SearchUtils` 的纯函数——URL 判定、抽取、内容量估算、should_index_content
   的三条策略、搜索结果归一化、爬取内容合并、use_case 自动检测；
2. `SearchNodes` 里不依赖外部的节点——analyze_query / route_by_use_case /
   should_continue / evaluate_content_size / extract_and_merge /
   format_answer / select_urls / scrape_content 的分支与错误形状。

节点用的是依赖注入（`self.agent.xxx`），所以拿一个轻量 stub agent 就够，
不需要构造真的 SearchAgent（那会拖上 LLMBase 与 MCP 配置）。
"""
import json

import pytest

from src.agents.search.nodes import SearchNodes
from src.agents.search.utils import SearchUtils


# ==================== 桩替身 ====================

class StubLLM:
    """async_call_llm_chain 的替身：按调用顺序返回预设响应，或按要求抛错。"""

    def __init__(self, responses=None, raises=None):
        self.responses = list(responses or [])
        self.raises = raises
        self.calls = []

    async def async_call_llm_chain(self, role="", input_prompt="", session_id=""):
        self.calls.append({"role": role, "prompt": input_prompt, "session": session_id})
        if self.raises:
            raise self.raises
        if self.responses:
            return self.responses.pop(0)
        return "桩答案"


class StubTools:
    """MCP 工具的替身：只记调用，不做任何 IO。"""

    def __init__(self, web_search=None, scrape_single=None, scrape_batch=None):
        self._web_search = web_search or {"success": True, "results": []}
        self._scrape_single = scrape_single or {"success": False, "error": "not configured"}
        self._scrape_batch = scrape_batch or {"success": False, "error": "not configured"}
        self.calls = []

    async def web_search(self, query, max_results=10):
        self.calls.append(("web_search", query, max_results))
        return self._web_search

    async def scrape_single_url(self, url, content_types=None, timeout=30000):
        self.calls.append(("scrape_single_url", url))
        return self._scrape_single

    async def scrape_batch_urls(self, urls, content_types=None, concurrent_limit=3, delay_between=0):
        self.calls.append(("scrape_batch_urls", tuple(urls)))
        return self._scrape_batch


def make_nodes(llm=None, tools=None):
    """造一个只带 utils/llm/tools 的假 agent——节点只用到这三样。"""
    agent = type("StubAgent", (), {})()
    agent.llm = llm or StubLLM()
    agent.tools = tools or StubTools()
    agent.utils = SearchUtils(agent)
    return SearchNodes(agent)


@pytest.fixture(autouse=True)
def _no_cache_writes(tmp_path, monkeypatch):
    """节点里的 save_search_cache / save_web_content 会真落盘——统一钉到 tmp，
    免得测试往仓库 data/ 或 scraped_data/ 里丢文件。"""
    from src.config import constants as const
    monkeypatch.setattr(const.PathConstants, "DATA_ROOT", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)


# ==================== SearchUtils：URL 判定与抽取 ====================

@pytest.mark.parametrize("url,expected", [
    ("https://arxiv.org/abs/2601.00001", True),
    ("http://example.com", True),
    ("  https://with-ws.com/x  ", True),
    ("ftp://example.com/x", False),            # 协议不在白名单
    ("//example.com/x", False),                # 没 scheme
    ("https:///no-host.com", False),           # 没 netloc
    ("just words", False),
    ("", False),
    (None, False),
    (123, False),                              # 非字符串
])
def test_is_valid_url(url, expected):
    assert SearchUtils.is_valid_url(url) is expected


def test_extract_urls_from_text_dedups_and_drops_junk():
    text = "看 https://a.com/p 和 https://a.com/p，还有 http://b.com/q，坏的不算 javascript:alert(1)"
    urls = SearchUtils.extract_urls_from_text(text)
    assert urls == ["https://a.com/p", "http://b.com/q"], "路径要留住、去重、非 http(s) 不进列表"
    assert not any("javascript" in u for u in urls)


def test_extract_urls_keeps_path_query_and_fragment():
    """Bug 1 的回归：正则现在带 path/query/fragment 段，论文页不再被抽成主机名。"""
    assert SearchUtils.extract_urls_from_text("看 https://arxiv.org/abs/1706.03762 这篇") == [
        "https://arxiv.org/abs/1706.03762"]
    assert SearchUtils.extract_urls_from_text("https://arxiv.org/pdf/1706.03762v7") == [
        "https://arxiv.org/pdf/1706.03762v7"]
    got = SearchUtils.extract_urls_from_text("a https://x.com/p?q=1&z=2 b https://y.com/p#frag c")
    assert got == ["https://x.com/p?q=1&z=2", "https://y.com/p#frag"]


def test_extract_urls_drops_trailing_punctuation():
    """紧跟标点的写法不该把逗号/句号吸进 URL（中文标点走正则终止集，
    西文句末点走函数里的 rstrip）。"""
    assert SearchUtils.extract_urls_from_text("http://b.com/q，还有") == ["http://b.com/q"]
    assert SearchUtils.extract_urls_from_text("visit https://example.com/page.") == [
        "https://example.com/page"]


def test_extract_urls_paren_is_a_known_stop_char():
    """已知取舍：圆括号也进了终止集，所以 `.../wiki/A_(B)` 会停在 `A_`。
    这比旧版"整条路都丢掉"好得多，但要留个记录——真要支持就得做括号配平，
    不在本轮范围内。"""
    assert SearchUtils.extract_urls_from_text(
        "https://en.m.wikipedia.org/wiki/A_(B) 尾括号") == ["https://en.m.wikipedia.org/wiki/A_"]


def test_extract_urls_empty_and_plain():
    assert SearchUtils.extract_urls_from_text("") == []
    assert SearchUtils.extract_urls_from_text("完全没有链接的一段中文") == []
    assert SearchUtils.extract_urls_from_text("%2Ax.pdf 单看不是 URL") == []


# ==================== SearchUtils：内容量估算 ====================

def test_calculate_content_size_empty():
    assert SearchUtils.calculate_content_size("") == {"chars": 0, "words": 0, "estimated_tokens": 0}
    assert SearchUtils.calculate_content_size(None) == {"chars": 0, "words": 0, "estimated_tokens": 0}


def test_calculate_content_size_cjk_counts_per_char():
    m = SearchUtils.calculate_content_size("你好世界")
    assert m["chars"] == 4
    assert m["words"] == 4, "中文按字计词"
    assert m["estimated_tokens"] == 4


def test_calculate_content_size_english_and_mixed():
    en = SearchUtils.calculate_content_size("one two three four")
    assert en["words"] == 4
    assert en["estimated_tokens"] == int(4 * 1.3)
    mixed = SearchUtils.calculate_content_size("中文 one two")
    assert mixed["words"] == 4  # 2 字 + 2 词
    assert mixed["chars"] >= 3


# ==================== SearchUtils：should_index_content 阈值 ====================

def test_should_index_at_threshold_boundary():
    # 恰好在阈值上 → 索引
    yes, why = SearchUtils.should_index_content(5000, threshold=5000, num_sources=1)
    assert yes is True and "内容量大" in why
    # 刚好差一个字符 → 还没到 80%，走直接对话
    no, why2 = SearchUtils.should_index_content(3999, threshold=5000, num_sources=1)
    assert no is False and "内容量小" in why2


def test_should_index_uses_80_percent_rule():
    assert SearchUtils.should_index_content(4000, threshold=5000, num_sources=1)[0] is True
    assert "接近阈值" in SearchUtils.should_index_content(4000, threshold=5000, num_sources=1)[1]
    assert SearchUtils.should_index_content(3999, threshold=5000, num_sources=1)[0] is False


def test_should_index_multi_source_rule_beats_small_content():
    yes, why = SearchUtils.should_index_content(10, threshold=5000, num_sources=4)
    assert yes is True and "多源" in why
    # 3 个来源不算"多源"（>3 才算）
    assert SearchUtils.should_index_content(10, threshold=5000, num_sources=3)[0] is False


def test_should_index_default_small_single_source_is_direct_chat():
    assert SearchUtils.should_index_content(100, threshold=5000, num_sources=1) == (
        False, "内容量小 (100 字符 < 5000)")


# ==================== SearchUtils：结果归一化 / 合并 ====================

def test_format_search_results_canonical_and_aliases():
    raw = [{"title": "T1", "url": "https://a.com", "snippet": "S1"},
           {"name": "T2", "link": "https://b.com", "description": "D2"},
           {"title": "T3", "url": "https://c.com", "content": "C3"}]
    out = SearchUtils.format_search_results(raw)
    assert [(o["title"], o["url"], o["snippet"]) for o in out] == [
        ("T1", "https://a.com", "S1"), ("T2", "https://b.com", "D2"), ("T3", "https://c.com", "C3")]


def test_format_search_results_drops_items_without_valid_url():
    out = SearchUtils.format_search_results([
        {"title": "没链接", "url": "not-a-url", "snippet": "x"},
        {"title": "空链接", "snippet": "y"},
        {"title": "好", "url": "https://ok.com", "snippet": "z"},
    ])
    assert [o["title"] for o in out] == ["好"], "URL 不合法整条被丢，静默丢弃是既定行为"


def test_format_search_results_fills_missing_title():
    out = SearchUtils.format_search_results([{"url": "https://a.com"}])
    assert out[0]["title"] == "无标题" and out[0]["snippet"] == ""


def test_merge_scraped_content_skips_failures_and_blanks():
    results = [
        {"success": True, "url": "https://a.com", "content": {"text": "第一页"}},
        {"success": False, "url": "https://b.com", "content": {"text": "不该出现"}},
        {"success": True, "url": "https://c.com", "content": {"text": "   "}},
        {"success": True, "url": "https://d.com", "content": {}},
    ]
    merged = SearchUtils.merge_scraped_content(results)
    assert "第一页" in merged and "=== 来源 1: https://a.com ===" in merged
    assert "不该出现" not in merged and "https://c.com" not in merged


def test_merge_scraped_content_empty_list():
    assert SearchUtils.merge_scraped_content([]) == ""


def test_merge_scraped_content_keeps_original_numbering():
    # 已知小毛病：编号是"在列表里的位置"而不是"成功来源的序号"，失败项会让
    # 来源标号跳号——不影响正确性，但下游按标号引用时会误导。
    merged = SearchUtils.merge_scraped_content([
        {"success": False, "url": "https://fail", "content": {"text": "x"}},
        {"success": True, "url": "https://ok", "content": {"text": "y"}},
    ])
    assert "来源 2: https://ok" in merged


# ==================== SearchUtils：use_case 检测 ====================

def test_auto_detect_explicit_target_urls_win():
    assert SearchUtils.auto_detect_use_case("随便问点什么", ["https://x.com"])[0] == "url_analysis"


def test_auto_detect_url_inside_query():
    case, reason = SearchUtils.auto_detect_use_case("解读 https://arxiv.org/abs/2601.00001")
    assert case == "url_analysis" and "1 个URL" in reason


@pytest.mark.parametrize("kw", ["这个网页", "这篇文章", "该页面", "此链接", "分析网页", "网页内容"])
def test_auto_detect_indicator_words(kw):
    assert SearchUtils.auto_detect_use_case(f"帮我看看{kw}讲了什么")[0] == "url_analysis"


def test_auto_detect_defaults_to_search():
    case, reason = SearchUtils.auto_detect_use_case("2026 年多模态模型的最新进展")
    assert case == "search" and "默认使用搜索引擎检索" in reason


def test_generate_doc_name_shape_and_determinism():
    a = SearchUtils.generate_doc_name_from_url("https://arxiv.org/abs/2601.00001")
    assert a.startswith("web_arxiv_org_") and len(a.split("_")[-1]) == 8
    assert a == SearchUtils.generate_doc_name_from_url("https://arxiv.org/abs/2601.00001")
    assert a != SearchUtils.generate_doc_name_from_url("https://arxiv.org/abs/2601.00002")


def test_generate_query_hash_only_normalizes_case_and_edge_space():
    # strip + lower：中间空格保留，所以 "hello world" != "helloworld"
    assert SearchUtils.generate_query_hash("  Hello World ") == SearchUtils.generate_query_hash("hello world")
    assert SearchUtils.generate_query_hash("A") == SearchUtils.generate_query_hash("a")
    assert SearchUtils.generate_query_hash("hello world") != SearchUtils.generate_query_hash("helloworld")


def test_validate_state_requires_query():
    node = make_nodes()
    with pytest.raises(ValueError):
        node.agent.utils.validate_state({"no_query": 1})
    node.agent.utils.validate_state({"query": "有就行"})


# ==================== 节点：analyze_query / 路由 ====================

async def test_analyze_query_explicit_use_case_without_urls_falls_back_to_search():
    """显式要 url_analysis 但一个 URL 都没给 → 退回 search。

    同步后的期望：state['use_case'] 这个键本身还是保留着用户给的
    "url_analysis"（本轮不做 use_case 语义/生命周期重构，没人负责清它），
    但它对缓存判定已经是惰性的了——两处缓存分支改读
    `_cache_use_case()`（detected_use_case 优先），所以这条状态上不会
    出现"场景已经变了、缓存按老场景写"的错账。
    """
    nodes = make_nodes()
    out = await nodes.analyze_query({"query": "x", "use_case": "url_analysis"})
    assert out["detected_use_case"] == "search"
    assert "URL分析模式但未找到URL" in out["use_case_reason"]

    # 口径统一后，用这个 state 走一遍 extract_and_merge：按 search 处理，缓存该写就写
    saved = []
    nodes2 = make_nodes()
    nodes2.agent.utils.save_search_cache = lambda **kw: saved.append(kw)
    state = {"query": "x", "use_case": "url_analysis", "detected_use_case": "search",
             "scraped_results": [{"success": True, "url": "https://a", "content": {"text": "正文"}}]}
    await nodes2.extract_and_merge(state)
    assert saved, "场景已退回 search，缓存判定要跟着 detected_use_case 走"


async def test_analyze_query_explicit_search_use_case_wins():
    nodes = make_nodes()
    out = await nodes.analyze_query({"query": "随便问 https://a.com", "use_case": "search"})
    assert out["detected_use_case"] == "search" and out["use_case_reason"] == "用户手动指定"


async def test_analyze_query_extracts_urls_from_query():
    """Bug 1 的下游回归：target_urls 现在拿到的是完整论文页，不再是首页。"""
    nodes = make_nodes()
    out = await nodes.analyze_query({"query": "看看 https://arxiv.org/abs/1706.03762 这篇"})
    assert out["detected_use_case"] == "url_analysis"
    assert out["target_urls"] == ["https://arxiv.org/abs/1706.03762"]


async def test_analyze_query_keyword_without_url_falls_back_to_search():
    nodes = make_nodes()
    out = await nodes.analyze_query({"query": "这个网页里讲了什么（无链接）"})
    assert out["detected_use_case"] == "search"
    assert "URL分析模式但未找到URL" in out["use_case_reason"]


async def test_analyze_query_error_path_defaults_to_search():
    """缺 query 时 analyze_query 自己吞掉异常并回落到 search——错误形状要钉住
    （不能把 KeyError 抛到图外面）。"""
    nodes = make_nodes()
    out = await nodes.analyze_query({})          # state['query'] KeyError
    assert out["detected_use_case"] == "search"
    assert "分析失败" in out["use_case_reason"]


def test_route_by_use_case_branches():
    nodes = make_nodes()
    assert nodes.route_by_use_case({"detected_use_case": "search"}) == "search"
    assert nodes.route_by_use_case({"detected_use_case": "url_analysis"}) == "url_analysis"
    assert nodes.route_by_use_case({}) == "search", "缺键默认走搜索分支"


def test_should_continue_branches():
    nodes = make_nodes()
    assert nodes.should_continue({"is_complete": True}) == "format"
    assert nodes.should_continue({"is_complete": False}) == "continue"
    assert nodes.should_continue({}) == "continue"


# ==================== 节点：evaluate_content_size 阈值切档 ====================

async def test_evaluate_size_small_content_is_direct_chat():
    nodes = make_nodes()
    state = {"scraped_results": [{"success": True, "url": "https://a", "content": {"text": "短"}}]}
    out = await nodes.evaluate_content_size(state)
    assert out["processing_strategy"] == "direct_chat"
    assert out["should_call_indexing"] is False
    assert "内容量小" in out["strategy_reason"]


async def test_evaluate_size_large_content_is_index_then_chat():
    nodes = make_nodes()
    big = "很长" * 4000   # 8000 字符 > 5000 阈值
    state = {"scraped_results": [{"success": True, "url": "https://a", "content": {"text": big}}]}
    out = await nodes.evaluate_content_size(state)
    assert out["processing_strategy"] == "index_then_chat"
    assert out["should_call_indexing"] is True
    assert "内容量大" in out["strategy_reason"]


async def test_evaluate_size_many_sources_even_when_small():
    nodes = make_nodes()
    state = {"scraped_results": [{"success": True, "url": f"https://s{i}", "content": {"text": "短"}}
                                 for i in range(5)]}
    out = await nodes.evaluate_content_size(state)
    assert out["processing_strategy"] == "index_then_chat"
    assert "多源" in out["strategy_reason"]


async def test_evaluate_size_all_failed_is_direct_chat():
    nodes = make_nodes()
    state = {"scraped_results": [{"success": False, "url": "https://x", "error": "超时"}]}
    out = await nodes.evaluate_content_size(state)
    assert out["processing_strategy"] == "direct_chat"
    assert out["content_size"] == 0


async def test_evaluate_size_internal_error_degrades_to_direct_chat(monkeypatch):
    nodes = make_nodes()

    def boom(*a, **kw):
        raise RuntimeError("合并炸了")

    monkeypatch.setattr(nodes.agent.utils, "merge_scraped_content", staticmethod(boom))
    out = await nodes.evaluate_content_size({"scraped_results": []})
    assert out["processing_strategy"] == "direct_chat"
    assert out["should_call_indexing"] is False
    assert "评估失败" in out["strategy_reason"], "失败路径要在 reason 里自证"


async def test_evaluate_size_url_analysis_writes_doc_name(monkeypatch):
    """url_analysis + 需要索引时，要生成 IndexingAgent 用的 doc_name 与
    web_content_json——这两个键是索引分支的前置条件。"""
    nodes = make_nodes()
    monkeypatch.setattr(nodes.agent.utils, "save_web_content",
                        lambda url, content, metadata=None: "/tmp/web.json")
    big = "x" * 6000
    state = {"scraped_results": [{"success": True, "url": "https://a.com/p", "content": {"text": big}}],
             "use_case": "url_analysis", "detected_use_case": "url_analysis"}
    out = await nodes.evaluate_content_size(state)
    assert out["processing_strategy"] == "index_then_chat"
    assert out["web_content_json"] == "/tmp/web.json"
    assert out["generated_doc_name"].startswith("web_a_com_")


# ==================== 节点：extract_and_merge / sources ====================

async def test_extract_and_merge_assembles_sources_only_from_success():
    nodes = make_nodes()
    state = {"scraped_results": [
        {"success": True, "url": "https://good", "content": {"text": "正文", "html": "<p>", "json": {}}},
        {"success": False, "url": "https://bad", "content": {"text": "不该进 sources"}},
        {"success": True, "url": "https://blank", "content": {"text": "   "}},
    ]}
    out = await nodes.extract_and_merge(state)
    assert out["sources"] == ["https://good"]
    assert [c["url"] for c in out["extracted_content"]] == ["https://good"]


async def test_extract_and_merge_with_no_results_is_empty_not_error():
    nodes = make_nodes()
    out = await nodes.extract_and_merge({"scraped_results": []})
    assert out["extracted_content"] == [] and out["sources"] == []


async def test_extract_and_merge_preserves_content_fields():
    nodes = make_nodes()
    out = await nodes.extract_and_merge({"scraped_results": [
        {"success": True, "url": "https://a", "content": {"text": "t", "html": "h", "json": {"k": 1}}}]})
    item = out["extracted_content"][0]
    assert item["text"] == "t" and item["html"] == "h" and item["json"] == {"k": 1}


# ==================== 节点：format_answer / warnings ====================

async def test_format_answer_appends_sources_section():
    nodes = make_nodes(llm=StubLLM(responses=["正文内容"]))
    state = {"query": "q", "sources": ["https://a.com", "https://b.com"],
             "extracted_content": [{"url": "https://a.com", "text": "AAA"}]}
    out = await nodes.format_answer(state)
    assert "## 信息来源" in out["final_answer"]
    assert "1. https://a.com" in out["final_answer"] and "2. https://b.com" in out["final_answer"]


async def test_format_answer_without_content_returns_fixed_wording():
    nodes = make_nodes()
    out = await nodes.format_answer({"query": "q", "extracted_content": []})
    assert "抱歉，未能获取到相关内容" in out["final_answer"]
    assert nodes.agent.llm.calls == [], "没内容时不该白叫一次 LLM"


async def test_format_answer_truncates_overlong_merged_content():
    long = "x" * 150000   # 超过 100k 总上限
    nodes = make_nodes(llm=StubLLM(responses=["答"]))
    out = await nodes.format_answer({"query": "q", "extracted_content": [
        {"url": "https://a", "text": long}, {"url": "https://b", "text": "tail"}]})
    prompt = nodes.agent.llm.calls[0]["prompt"]
    assert "[内容过长，已截断...]" in prompt
    assert len(prompt) < len(long) + 10000
    # 第一个来源就把总预算吃满，后面的来源直接不进去
    assert "=== 来源: https://b ===" not in prompt
    assert isinstance(out["final_answer"], str) and out["final_answer"] == "答"


async def test_format_answer_llm_exception_shape():
    nodes = make_nodes(llm=StubLLM(raises=RuntimeError("LLM 挂了")))
    out = await nodes.format_answer({"query": "q", "extracted_content": [
        {"url": "https://a", "text": "有内容"}], "sources": []})
    assert "生成答案时出错" in out["final_answer"]


# ==================== 节点：select_urls / scrape_content 错误形状 ====================

async def test_select_urls_falls_back_to_first_five_on_parse_failure():
    nodes = make_nodes(llm=StubLLM(responses=["这不是 JSON"] * 3))
    state = {"query": "q", "search_engine_results": [
        {"title": f"t{i}", "url": f"https://s{i}", "snippet": "s"} for i in range(9)]}
    out = await nodes.select_urls(state)
    assert len(out["selected_urls"]) == 5, "解析失败时的兜底是前 5 个"
    assert "解析失败" in out["selection_reason"]


async def test_select_urls_honours_parsed_selection():
    payload = json.dumps({"selected_urls": [{"url": "https://picked", "reason": "相关"}],
                          "overall_reason": "人工筛选"})
    nodes = make_nodes(llm=StubLLM(responses=[payload]))
    out = await nodes.select_urls({"query": "q", "search_engine_results": [
        {"title": "t", "url": "https://other", "snippet": "s"}]})
    assert out["selected_urls"] == ["https://picked"]
    assert out["selection_reason"] == "人工筛选"


async def test_select_urls_empty_results_short_circuits():
    nodes = make_nodes()
    out = await nodes.select_urls({"query": "q", "search_engine_results": []})
    assert out["selected_urls"] == []
    assert nodes.agent.llm.calls == [], "没结果就不该去问 LLM"


async def test_select_urls_outer_exception_falls_back_to_first_three():
    nodes = make_nodes(llm=StubLLM(raises=RuntimeError("boom")))
    state = {"query": "q", "search_engine_results": [
        {"title": f"t{i}", "url": f"https://s{i}", "snippet": "s"} for i in range(9)]}
    out = await nodes.select_urls(state)
    assert len(out["selected_urls"]) == 3
    assert "筛选失败" in out["selection_reason"]


async def test_scrape_content_no_urls_makes_empty_list():
    nodes = make_nodes()
    out = await nodes.scrape_content({"detected_use_case": "search", "selected_urls": []})
    assert out["scraped_results"] == []
    assert nodes.agent.tools.calls == []


async def test_scrape_content_batch_failure_records_warning():
    tools = StubTools(scrape_batch={"success": False, "error": "全部超时"})
    nodes = make_nodes(tools=tools)
    out = await nodes.scrape_content({"detected_use_case": "search",
                                      "selected_urls": ["https://a", "https://b"]})
    assert out["scraped_results"] == []
    assert any("批量爬取失败" in w for w in out["warnings"])


async def test_scrape_content_tool_exception_records_warning():
    class BoomTools(StubTools):
        async def scrape_single_url(self, url, content_types=None, timeout=30000):
            raise RuntimeError("MCP 没起来")

    nodes = make_nodes(tools=BoomTools())
    out = await nodes.scrape_content({"detected_use_case": "url_analysis",
                                      "target_urls": ["https://a"]})
    assert out["scraped_results"] == []
    assert any("爬取异常" in w for w in out["warnings"])
    assert "MCP 没起来" in " ".join(out["warnings"])


async def test_scrape_content_single_url_success_counts_observation():
    tools = StubTools(scrape_single={"success": True, "url": "https://a",
                                    "content": {"text": "正文", "html": "", "json": {}}})
    nodes = make_nodes(tools=tools)
    out = await nodes.scrape_content({"detected_use_case": "url_analysis",
                                      "target_urls": ["https://a"]})
    assert out["scraped_results"][0]["success"] is True
    assert any("成功 1" in o for o in out["observations"])


async def test_web_search_failure_and_exception_record_warnings():
    nodes = make_nodes(tools=StubTools(web_search={"success": False, "error": "配额用尽"}))
    out = await nodes.web_search({"query": "q"})
    assert out["search_engine_results"] == []
    assert any("搜索失败: 配额用尽" in w for w in out["warnings"])

    class Boom(StubTools):
        async def web_search(self, query, max_results=10):
            raise RuntimeError("MCP 进程没了")

    nodes2 = make_nodes(tools=Boom())
    out2 = await nodes2.web_search({"query": "q"})
    assert out2["search_engine_results"] == []
    assert any("搜索异常" in w for w in out2["warnings"])


async def test_initialize_fills_defaults_and_flags_bad_state():
    nodes = make_nodes()
    out = await nodes.initialize({"query": "q"})
    assert out["max_iterations"] == 10
    assert out["warnings"] == [] and out["sources"] == []
    assert out["thoughts"] == [] and out["actions"] == [] and out["observations"] == []

    bad = await nodes.initialize({"not_query": 1})
    assert bad["is_complete"] is True and "缺少必需字段" in bad["error"]


# ==================== Bug 2 回归：缓存场景口径统一 ====================

async def test_auto_detected_search_still_saves_cache_in_extract_and_merge():
    """没显式传 use_case、只靠自动检测判成 search 的检索，缓存现在照写。

    修之前 `extract_and_merge` / `format_answer` 的缓存分支只读
    state['use_case']，而自动检测只写 detected_use_case，于是这条路子
    一条缓存都不落。现在两处都走 `_cache_use_case()` 的统一口径。
    """
    nodes = make_nodes()
    saved = []
    nodes.agent.utils.save_search_cache = lambda **kw: saved.append(kw)
    await nodes.extract_and_merge({
        "query": "2026 最新进展",
        "detected_use_case": "search",
        "scraped_results": [{"success": True, "url": "https://a", "content": {"text": "正文"}}],
    })
    assert saved, "自动检测的 search 场景也要触发 save_search_cache"
    assert saved[0]["query"] == "2026 最新进展"


async def test_auto_detected_search_updates_cache_in_format_answer():
    """同一个口径在 format_answer 那处也要成立：答案要能补进缓存。"""
    nodes = make_nodes(llm=StubLLM(responses=["成文的答案"]))
    saved = []
    nodes.agent.utils.save_search_cache = lambda **kw: saved.append(kw)
    await nodes.format_answer({
        "query": "2026 最新进展",
        "detected_use_case": "search",
        "extracted_content": [{"url": "https://a", "text": "正文"}],
        "sources": ["https://a"],
    })
    assert saved, "format_answer 的缓存更新同样要认 detected_use_case"
    # 缓存里存的是拼好"## 信息来源"之后的完整答案，不是裸 LLM 输出
    assert saved[0]["answer"].startswith("成文的答案") and "## 信息来源" in saved[0]["answer"]


async def test_url_analysis_still_does_not_write_search_cache():
    """反面对照：口径统一不等于把 search 的缓存逻辑扩到 url_analysis 上，
    url_analysis 场景依旧不该往搜索缓存里写东西。"""
    nodes = make_nodes()
    saved = []
    nodes.agent.utils.save_search_cache = lambda **kw: saved.append(kw)
    await nodes.extract_and_merge({
        "query": "看 https://a.com/p",
        "detected_use_case": "url_analysis",
        "scraped_results": [{"success": True, "url": "https://a.com/p", "content": {"text": "正文"}}],
    })
    assert saved == []


async def test_evaluate_size_autodetected_url_analysis_sets_web_content_keys():
    """Bug 2 同一刀的第三个站点：自动检测出的 url_analysis（调用方没传
    use_case，只有 detected_use_case）也要产出 web_content_json 与
    generated_doc_name——修之前这段整体会跳过，call_indexing_agent 拿不到输入。"""
    nodes = make_nodes()
    written = []
    nodes.agent.utils.save_web_content = lambda url, content, metadata=None: (
        written.append((url, metadata)) or "/tmp/web_content.json")
    out = await nodes.evaluate_content_size({
        "query": "看看 https://arxiv.org/abs/1706.03762 这篇",
        "detected_use_case": "url_analysis",   # 只有自动检测写出来的那一个键
        "scraped_results": [{"success": True, "url": "https://arxiv.org/abs/1706.03762",
                             "content": {"text": "正文", "html": "", "json": {}}}],
    })
    assert written, "自动检测的 url_analysis 场景也要走这段内容落盘"
    assert out["web_content_json"] == "/tmp/web_content.json"
    assert out["generated_doc_name"].startswith("web_arxiv_org_")
    assert out["processing_strategy"] in ("direct_chat", "index_then_chat")
