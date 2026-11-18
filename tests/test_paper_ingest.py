"""对话内"按需下载入库"链路的后端回归测试。

三块：
1. src/memory/search.py 的 _trim_rows 会从命中行里带出原文 url
   （AATF 卡片正文的 链接：/PDF： 行，或正文里的裸 arxiv/pdf 链接）——
   这是 /chat 回复能挂下载按钮的源头，没有它 LLM 只引 source_id；
2. memory_search 子 agent 的 _shape_hits 原样透传 url；
3. POST /api/v1/briefs/fetch-pdf 的行为契约（arxiv 名映射 / exists 幂等 /
   非 PDF 400 / HTTP 错误 502 / 非法名 400）。

全程不碰网络与真实 LanceDB：httpx 客户端与 documents 索引任务都被
monkeypatch 替换。
"""
import asyncio
import os
import re
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agents.orchestrator.sub_agents import memory_search
from src.memory import search as mem_search
from src.ui.backend.api.v1 import briefs


# ------------------------------------------------------------------ _trim_rows
def test_trim_rows_extracts_url_from_aatf_lines():
    row = {
        "id": "x1", "abstract": "标题：某论文", "source_type": "brief",
        "source_id": "2601.00001", "occurred_at": "2026-11-15T00:00:00+00:00",
        "raw_source": "标题：某论文\n链接：https://arxiv.org/abs/2601.00001\nPDF：https://arxiv.org/pdf/2601.00001\n导读：好",
        "detail": "", "semantic_score": 0.5,
    }
    [trimmed] = mem_search._trim_rows([row])
    assert trimmed["url"] == "https://arxiv.org/abs/2601.00001"  # 取"链接"行为先


def test_trim_rows_falls_back_to_loose_arxiv_url():
    row = {"id": "x2", "abstract": "", "source_type": "brief", "source_id": "y",
           "raw_source": "见 https://arxiv.org/pdf/1706.03762v7 全文", "detail": ""}
    [trimmed] = mem_search._trim_rows([row])
    assert re.match(r"^https://arxiv\.org/", trimmed["url"])


def test_trim_rows_no_url_no_key():
    row = {"id": "x3", "abstract": "无链接", "source_type": "chat",
           "source_id": "z", "raw_source": "just text", "detail": ""}
    [trimmed] = mem_search._trim_rows([row])
    assert "url" not in trimmed


# ------------------------------------------------------------------ _shape_hits
def test_shape_hits_passes_url_through():
    hits = memory_search.MemorySearchAgent._shape_hits([
        {"source_id": "2601.00001", "source_type": "brief", "abstract": "a",
         "score": 0.3, "url": "https://arxiv.org/abs/2601.00001"},
        {"source_id": "d1", "source_type": "ai_research", "abstract": "b", "score": 0.2},
    ])
    assert hits[0]["url"] == "https://arxiv.org/abs/2601.00001"
    assert "url" not in hits[1]
    assert hits[1].get("doc_name") == "d1"  # 旧 ai_research 语义不变


def test_shape_hits_extracts_url_from_detail_rows():
    """gateway.search 的真实形状：行里没有现成 url 键、只有 include_raw 带出的
    detail 全文——_shape_hits 必须现场提取，AATF 命中才有可下载的链接。"""
    hits = memory_search.MemorySearchAgent._shape_hits([
        {"source_id": "2611.04567", "source_type": "brief", "abstract": "标题：x",
         "score": 0.6,
         "detail": "标题：安全护栏并不总是稳固\n链接：https://arxiv.org/abs/2611.04567\n结论：会翻"},
    ])
    assert hits[0]["url"] == "https://arxiv.org/abs/2611.04567"


# ------------------------------------------------------------------ fetch-pdf
@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(briefs.router, prefix="/api/v1/briefs")
    monkeypatch.setattr(briefs, "PDF_DIR", tmp_path)
    # 后台索引任务真跑会起 IndexingAgent——换成记账版（provider/preset 也记，
    # fetch-pdf 不该自己写死 high）
    index_calls = []

    def fake_index(doc_name, provider, pdf_preset):
        index_calls.append({"doc_name": doc_name, "provider": provider,
                            "pdf_preset": pdf_preset})

    import src.ui.backend.api.v1.documents as documents
    monkeypatch.setattr(documents, "_index_document_task", fake_index)
    return TestClient(app), index_calls


@pytest.fixture()
def background_stub(monkeypatch):
    """直接 await 端点时绕开 Starlette 的后台任务执行：只记"排了什么"。"""
    class _StubBackgroundTasks:
        def __init__(self):
            self.registered = []

        def add_task(self, func, *args, **kwargs):
            self.registered.append({"func": getattr(func, "__name__", str(func)),
                                    "args": args, "kwargs": kwargs})

    return _StubBackgroundTasks()


def _mock_http(monkeypatch, *, status=200, chunks=(b"%PDF-1.7 hello",), exc=None, routes=None,
               yield_sleep=False):
    """替换 briefs 用到的 httpx.AsyncClient，按 URL 分派响应。

    routes: {url: {"status":…, "chunks":…, "location":…, "exc":…}}，没命中的
    URL 走上面那组默认值。真实代码关掉了自动重定向、由我们自己逐跳跟，
    所以这里也刻意不做自动跳转，形状保持一致。
    yield_sleep=True 时每块之间让出一次事件循环——并发测试要靠它把两路
    写协程真正逼到一起。
    """
    import httpx

    per_url = dict(routes or {})
    requested = []

    class _Resp:
        def __init__(self, code, body, location, err):
            self.status_code = code
            self.headers = {"location": location} if location else {}
            self._body = body
            self._err = err

        async def aiter_bytes(self, _size):
            if self._err is not None:
                raise self._err
            for c in self._body or ():
                if yield_sleep:
                    await asyncio.sleep(0)
                yield c

    class _Ctx:
        def __init__(self, resp):
            self._resp = resp

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, *a):
            return False

    class _Client:
        ctor_kwargs = {}

        def __init__(self, *a, **k):
            _Client.ctor_kwargs = k

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, **kw):
            spec = per_url.get(url, {})
            requested.append(url)
            return _Ctx(_Resp(spec.get("status", status), spec.get("chunks", chunks),
                              spec.get("location"), spec.get("exc", exc)))

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return requested


@pytest.fixture()
def dns(monkeypatch):
    """fetch-pdf 会解析主机地址来挡内网——测试不打真 DNS。

    表里没有的主机一律按公网放行（等价于 arxiv.org 解析成功）；要测拒绝
    路径就返回的表里塞 127.x/10.x，或塞 False 模拟解析失败。
    """
    table = {}

    def fake_getaddrinfo(host, *args, **kwargs):
        ip = table.get(host, "157.166.208.18")
        if not ip:
            raise OSError(f"no address for {host}")
        return [(0, 1, 6, "", (ip, 0))]

    monkeypatch.setattr(briefs.socket, "getaddrinfo", fake_getaddrinfo)
    return table


@pytest.fixture()
def registry(monkeypatch):
    """替掉 _index_status_of 函数级 import 的 DocumentRegistry——别碰真实
    data/doc_registry.json。records 就是 list_all() 的形状。"""
    import src.core.document_management.registry as reg_mod

    state = {"records": []}

    class _FakeRegistry:
        def __init__(self, *a, **kw):
            pass

        def list_all(self, *a, **kw):
            return list(state["records"])

    monkeypatch.setattr(reg_mod, "DocumentRegistry", _FakeRegistry)
    return state


def _index_dir_marker(root):
    """造一个"索引确实在"的 index_path——判据是 os.path.exists，真目录即可。"""
    d = root / "_idx"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def test_fetch_pdf_exists_idempotent(app_client, dns, monkeypatch, registry):
    client, index_calls = app_client
    (briefs.PDF_DIR / "2601.12345.pdf").write_bytes(b"%PDF-1.5 old")
    registry["records"] = [{"doc_name": "2601.12345",
                            "index_path": _index_dir_marker(briefs.PDF_DIR)}]
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://arxiv.org/abs/2601.12345"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "exists" and body["doc_name"] == "2601.12345.pdf"
    assert body["indexed"] is True and body["index_state"] == "indexed"
    assert index_calls == []  # 已索引的已存在文件，不该再排一次索引


def test_fetch_pdf_arxiv_download_starts_index(app_client, dns, monkeypatch):
    client, index_calls = app_client
    _mock_http(monkeypatch, chunks=(b"%PDF-1.7", b"more bytes"))
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://arxiv.org/pdf/1706.03762v7"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    # arxiv 名与重管线 item_id 同源约定
    assert body["doc_name"] == "1706.03762.pdf"
    assert (briefs.PDF_DIR / "1706.03762.pdf").exists()
    assert [c["doc_name"] for c in index_calls] == ["1706.03762.pdf"]  # 带 .pdf 的文档名
    assert not list(briefs.PDF_DIR.glob("*.part*")), "rename 后不留残余 tmp"


def test_fetch_pdf_rejects_non_pdf_body(app_client, dns, monkeypatch):
    client, index_calls = app_client
    _mock_http(monkeypatch, chunks=(b"<html>not a pdf</html>",))
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://arxiv.org/abs/2601.99999"})
    assert r.status_code == 400
    assert "PDF" in r.json()["detail"]
    assert index_calls == []
    # 失败后不留半截文件
    assert not list(briefs.PDF_DIR.glob("*.pdf"))
    assert not list(briefs.PDF_DIR.glob("*.part*"))


def test_fetch_pdf_http_error_maps_502(app_client, dns, monkeypatch):
    client, _ = app_client
    _mock_http(monkeypatch, status=404)
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://example.com/paper.pdf"})
    assert r.status_code == 502
    assert not list(briefs.PDF_DIR.glob("*.part*"))


def test_fetch_pdf_size_cap(app_client, dns, monkeypatch):
    client, _ = app_client
    monkeypatch.setattr(briefs, "_FETCH_PDF_MAX_BYTES", 16)
    _mock_http(monkeypatch, chunks=(b"%PDF-", b"x" * 64))
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://arxiv.org/pdf/2601.00002"})
    assert r.status_code == 413
    assert not list(briefs.PDF_DIR.glob("*.pdf"))
    assert not list(briefs.PDF_DIR.glob("*.part*"))


def test_fetch_pdf_unsafe_name_400(app_client):
    client, _ = app_client
    # 末段含非法字符（* / 等）→ 推不出安全文档名，挡在进入下载之前
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://example.com/dl/%2Ax.pdf"})
    assert r.status_code == 400
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "ftp://x/y.pdf"})
    assert r.status_code == 400


# ------------------------------------------------------------- 临时文件策略
def test_tmp_name_is_unique_per_call():
    """同进程内每次调用都要拿到独占的 tmp 名——固定名 `.name.part` 是这条
    路上唯一的静默损坏来源：失败分支的 unlink 会删掉另一路正在写的手柄，
    rename 出半截 PDF，而魔数只校验了首块，没人会发现。"""
    target = briefs.PDF_DIR / "2601.00001.pdf"
    names = [str(briefs._tmp_name(target)) for _ in range(8)]
    assert len(set(names)) == 8
    assert all(str(target) in n and ".part." in n for n in names)
    # 沿用 write_json_atomic 的 pid 约定，一眼看得出是本进程产物
    assert str(os.getpid()) in names[0]


def test_tmp_name_unique_for_async_coroutines():
    """pid+tid 单独不够用：async 端点里两路协程共用事件循环线程，tid 相同。
    （json_io 那套跑在 to_thread 里才靠 tid 分得开。）"""
    target = briefs.PDF_DIR / "2601.00002.pdf"
    seen = [str(briefs._tmp_name(target)) for _ in range(20)]  # 同线程、同 tid
    assert len(set(seen)) == 20


def test_tmp_name_unique_across_threads():
    target = briefs.PDF_DIR / "2601.00003.pdf"
    seen = []

    def worker():
        seen.append(str(briefs._tmp_name(target)))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(seen)) == 6


# ------------------------------------------------------------- SSRF 护栏
def test_fetch_pdf_rejects_internal_hosts(app_client, dns, monkeypatch):
    client, index_calls = app_client
    requested = _mock_http(monkeypatch)
    dns.update({"127.0.0.1": "127.0.0.1", "internal.example": "10.1.2.3",
                "meta.example": "169.254.169.254", "lab.example": "192.168.1.20",
                "cg.example": "100.64.0.1", "v6.example": "::1",
                "ula.example": "fd00::5", "zero.example": "0.0.0.0"})
    for host in ("127.0.0.1", "internal.example", "meta.example", "lab.example",
                 "cg.example", "v6.example", "ula.example", "zero.example"):
        r = client.post("/api/v1/briefs/fetch-pdf", json={"url": f"http://{host}/p.pdf"})
        assert r.status_code == 400, host
        detail = r.json()["detail"]
        assert "内网" in detail or "保留" in detail, (host, detail)
    # 挡在发起请求之前：一次网络都没出
    assert requested == []
    assert index_calls == []
    assert not list(briefs.PDF_DIR.iterdir())


def test_fetch_pdf_accepts_public_host_and_arxiv(app_client, dns, monkeypatch):
    """加严不该把 arxiv 挡在门外——白名单式做法最大的坑就是这个。"""
    client, _ = app_client
    _mock_http(monkeypatch, chunks=(b"%PDF-1.7", b"ok"))
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://arxiv.org/pdf/2601.00101"})
    assert r.status_code == 200
    assert (briefs.PDF_DIR / "2601.00101.pdf").exists()


def test_fetch_pdf_literal_ip_bypass_is_blocked(app_client, dns, monkeypatch):
    """有人拿字面 IP 直接绕 getaddrinfo——这条也走同一道闸。"""
    client, _ = app_client
    _mock_http(monkeypatch)
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "http://[::1]/p.pdf"})
    assert r.status_code == 400
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "http://127.0.0.2:9000/p.pdf"})
    assert r.status_code == 400


def test_fetch_pdf_rejects_unresolvable_host(app_client, dns, monkeypatch):
    client, _ = app_client
    _mock_http(monkeypatch)
    dns["nosuch.example"] = False  # 解析失败按拒绝处理，宁挡错不误放
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://nosuch.example/p.pdf"})
    assert r.status_code == 400
    assert "解析失败" in r.json()["detail"]


def test_fetch_pdf_non_http_scheme_rejected(app_client, dns, monkeypatch):
    client, _ = app_client
    _mock_http(monkeypatch)
    for bad in ("file:///etc/passwd", "gopher://arxiv.org/x.pdf"):
        r = client.post("/api/v1/briefs/fetch-pdf", json={"url": bad})
        assert r.status_code == 400, bad


def test_fetch_pdf_blocks_redirect_into_internal_target(app_client, dns, monkeypatch):
    """重定向是自己逐跳跟的：公网第一跳 302 指回 127.0.0.1 要当场挡下，
    否则"第一跳合法"就成了绕过校验的后门。"""
    client, index_calls = app_client
    dns["evil.example"] = "93.184.216.34"
    requested = _mock_http(monkeypatch, routes={
        "https://evil.example/dl.pdf": {"status": 302, "location": "http://127.0.0.1:8000/p.pdf"},
    })
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://evil.example/dl.pdf"})
    assert r.status_code == 400
    assert "内网" in r.json()["detail"]
    assert requested == ["https://evil.example/dl.pdf"]  # 内网那一跳没发出去
    assert index_calls == []
    assert not list(briefs.PDF_DIR.glob("*.pdf"))
    assert not list(briefs.PDF_DIR.glob("*.part*"))


def test_fetch_pdf_follows_public_redirect_chain(app_client, dns, monkeypatch):
    client, index_calls = app_client
    # arxiv 常见的 http→https / 源站→export 镜像两跳，公网跳要正常跟下来
    dns["export.arxiv.org"] = "143.204.230.99"
    requested = _mock_http(monkeypatch, routes={
        "http://arxiv.org/pdf/2601.00009": {"status": 301,
                                            "location": "https://export.arxiv.org/pdf/2601.00009"},
        "https://export.arxiv.org/pdf/2601.00009": {"chunks": (b"%PDF-1.7", b"body")},
    })
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "http://arxiv.org/pdf/2601.00009"})
    assert r.status_code == 200
    assert r.json()["doc_name"] == "2601.00009.pdf"
    assert requested == ["http://arxiv.org/pdf/2601.00009",
                         "https://export.arxiv.org/pdf/2601.00009"]
    assert (briefs.PDF_DIR / "2601.00009.pdf").read_bytes() == b"%PDF-1.7body"
    assert index_calls, "重定向成功后同样要排索引"


def test_fetch_pdf_relative_redirect_is_resolved_and_validated(app_client, dns, monkeypatch):
    """Location 给的是相对路径也要认下来：按当前 URL 补成绝对地址，然后
    这跳同样要过 SSRF 校验——否则"相对跳"就是校验的漏风口。"""
    client, _ = app_client
    dns["redir.example"] = "93.184.216.34"
    requested = _mock_http(monkeypatch, routes={
        "https://redir.example/a.pdf": {"status": 302, "location": "/b.pdf"},
        "https://redir.example/b.pdf": {"chunks": (b"%PDF-1.7", b"rel")},
    })
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://redir.example/a.pdf"})
    assert r.status_code == 200
    assert requested == ["https://redir.example/a.pdf", "https://redir.example/b.pdf"]
    assert (briefs.PDF_DIR / "a.pdf").read_bytes() == b"%PDF-1.7rel"


def test_fetch_pdf_redirect_loop_capped(app_client, dns, monkeypatch):
    client, _ = app_client
    _mock_http(monkeypatch, routes={
        "https://loop.example/a.pdf": {"status": 302, "location": "https://loop.example/a.pdf"},
    })
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://loop.example/a.pdf"})
    assert r.status_code == 502
    assert "重定向" in r.json()["detail"]
    assert not list(briefs.PDF_DIR.glob("*.part*"))


def test_fetch_pdf_client_has_no_auto_redirect(app_client, dns, monkeypatch):
    """构造参数必须自己关跳转——开着的话第二跳不经我们手，SSRF 校验就只剩
    第一跳是摆设。"""
    client, _ = app_client
    import httpx
    _mock_http(monkeypatch, chunks=(b"%PDF-1.7",))
    client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://arxiv.org/pdf/2601.00202"})
    assert httpx.AsyncClient.ctor_kwargs.get("follow_redirects") is False


# ------------------------------------------------------------- exists 分支
def test_fetch_pdf_exists_indexed_skips_reindex(app_client, dns, monkeypatch, registry):
    client, index_calls = app_client
    (briefs.PDF_DIR / "2601.12345.pdf").write_bytes(b"%PDF-1.5 old")
    registry["records"] = [{"doc_name": "2601.12345",
                            "index_path": _index_dir_marker(briefs.PDF_DIR)}]
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://arxiv.org/abs/2601.12345"})
    body = r.json()
    assert body["indexed"] is True and body["index_state"] == "indexed"
    assert "reindex_started" not in body and "note" not in body
    assert index_calls == []


def test_fetch_pdf_exists_with_versioned_sibling_says_elsewhere(app_client, dns, monkeypatch, registry):
    """手动上传那批的 doc_name 带版本号，对应的是磁盘上另一个文件。
    精确匹配会把它当成"本条目没索引"→ 同一篇论文再开一份索引，registry
    裂两条、LLM 白烧一遍；说它"已索引"又是虚假宣称。所以要单独一态，
    并把真名交给前端。"""
    client, index_calls = app_client
    (briefs.PDF_DIR / "2607.11185.pdf").write_bytes(b"%PDF-1.5 old")
    registry["records"] = [{"doc_name": "2607.11185v1",
                            "index_path": _index_dir_marker(briefs.PDF_DIR)}]
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://arxiv.org/abs/2607.11185"})
    body = r.json()
    assert body["indexed"] is False and body["index_state"] == "indexed_elsewhere"
    assert body["registry_doc_name"] == "2607.11185v1"
    assert "同一篇论文" in body["note"]
    assert index_calls == [], "兄弟条目已索引好，不该再排一次"


def test_fetch_pdf_versioned_sibling_index_path_gone_is_not_elsewhere(app_client, dns, monkeypatch, registry):
    """兄弟条目名字对上了但索引早被清掉——那不算 elseWhere，正常走补排。"""
    client, index_calls = app_client
    (briefs.PDF_DIR / "2607.22222.pdf").write_bytes(b"%PDF-1.5 old")
    registry["records"] = [{"doc_name": "2607.22222v3", "index_path": ""}]
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://arxiv.org/abs/2607.22222"})
    body = r.json()
    assert body["index_state"] == "unknown" and body["reindex_started"] is True
    assert index_calls


def test_fetch_pdf_exists_not_indexed_requeues_and_notes(app_client, dns, monkeypatch, registry):
    client, index_calls = app_client
    (briefs.PDF_DIR / "2601.99999.pdf").write_bytes(b"%PDF-1.5 old")
    registry["records"] = [{"doc_name": "2601.99999", "index_path": ""}]
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://arxiv.org/abs/2601.99999"})
    body = r.json()
    assert body["status"] == "exists" and body["indexed"] is False
    assert body["index_state"] == "not_indexed" and body["reindex_started"] is True
    assert "未完成" in body["note"]
    assert index_calls[0]["doc_name"] == "2601.99999.pdf"


def test_fetch_pdf_exists_untracked_says_unknown_not_failed(app_client, dns, monkeypatch, registry):
    """用户自己往 data/pdf 丢的文件：有文件、registry 没记录——算没索引，
    但不该被说成"失败过"，UI 不该为此刷红字。"""
    client, index_calls = app_client
    (briefs.PDF_DIR / "2601.88888.pdf").write_bytes(b"%PDF-1.5 old")
    registry["records"] = []
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://arxiv.org/abs/2601.88888"})
    body = r.json()
    assert body["indexed"] is False and body["index_state"] == "unknown"
    assert "排队" in body["note"] and "失败" not in body["note"]
    assert index_calls, "没索引过就该补排一次"


def test_fetch_pdf_force_bypasses_exists_and_replaces_atomically(app_client, dns, monkeypatch, registry):
    """force=true：不认"文件已存在"的捷径，重下一遍并原子盖掉——半截文件
    的重试得有实际动作，不能又走回 exists 继续干等。"""
    client, index_calls = app_client
    (briefs.PDF_DIR / "2601.66666.pdf").write_bytes(b"%PDF-1.5 truncated-old")
    registry["records"] = [{"doc_name": "2601.66666",
                            "index_path": _index_dir_marker(briefs.PDF_DIR)}]
    _mock_http(monkeypatch, chunks=(b"%PDF-1.7", b"fresh download"))
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://arxiv.org/pdf/2601.66666", "force": True})
    assert r.status_code == 200
    assert r.json()["status"] == "started"
    assert (briefs.PDF_DIR / "2601.66666.pdf").read_bytes() == b"%PDF-1.7fresh download"
    assert not list(briefs.PDF_DIR.glob("*.part*"))
    assert index_calls, "重下之后照样要排索引"


def test_fetch_pdf_without_force_still_shortcuts_on_exists(app_client, dns, monkeypatch, registry):
    """反面对照：不带 force 时不许悄悄重下（重下是要费流量的）。"""
    client, _ = app_client
    requested = _mock_http(monkeypatch)
    (briefs.PDF_DIR / "2601.66667.pdf").write_bytes(b"%PDF-1.5 old")
    registry["records"] = [{"doc_name": "2601.66667",
                            "index_path": _index_dir_marker(briefs.PDF_DIR)}]
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://arxiv.org/pdf/2601.66667"})
    assert r.json()["status"] == "exists" and r.json()["indexed"] is True
    assert requested == [], "没 force 就不该发起任何 HTTP"


def test_fetch_pdf_index_preset_follows_config(app_client, dns, monkeypatch, registry):
    """不该自己写死 "high"——/config 页选了什么就跟着什么。"""
    client, index_calls = app_client
    import src.ui.backend.api.v1.config as uiconfig
    monkeypatch.setattr(uiconfig, "get_current_pdf_preset", lambda: "fast")
    (briefs.PDF_DIR / "2601.77777.pdf").write_bytes(b"%PDF-1.5 old")
    registry["records"] = []
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "https://arxiv.org/abs/2601.77777"})
    assert r.json()["reindex_started"] is True
    assert index_calls[0]["pdf_preset"] == "fast"
    assert index_calls[0]["provider"] is None  # provider 走 resolve 链，不写死


# ------------------------------------------------------------- 并发
async def test_concurrent_fetch_of_same_doc_writes_intact_file(monkeypatch, tmp_path,
                                                               background_stub):
    """两路并发点同一篇：各拿自己的 tmp、各自原子 rename，最后落下来的是
    完整 PDF。旧写法在这里会交错出半截文件——那是唯一一种"没人报错、东西
    却坏了"的失败模式。"""
    monkeypatch.setattr(briefs, "PDF_DIR", tmp_path)
    monkeypatch.setattr(briefs.socket, "getaddrinfo",
                        lambda *a, **kw: [(0, 1, 6, "", ("157.166.208.18", 0))])
    body = (b"%PDF-1.7", b"A" * 4096, b"B" * 4096, b"%%EOF")
    _mock_http(monkeypatch, chunks=body, yield_sleep=True)

    tasks = [asyncio.ensure_future(briefs.post_fetch_pdf(
        {"url": "https://arxiv.org/pdf/2601.00555"}, background_stub)) for _ in range(6)]
    results = await asyncio.gather(*tasks)

    assert all(r["status"] in ("started", "exists") for r in results)
    assert (tmp_path / "2601.00555.pdf").read_bytes() == b"".join(body)
    assert not list(tmp_path.glob("*.part*")), "并发结束后不该留残余 tmp"
    assert len(background_stub.registered) >= 1


async def test_concurrent_one_failing_other_ok_keeps_good_file(monkeypatch, tmp_path,
                                                                background_stub):
    """一路中途断流、一路正常：失败的那路只清自己那份 tmp，不能把别人
    已经写好的目标文件干掉或半截替换上去。"""
    import httpx

    monkeypatch.setattr(briefs, "PDF_DIR", tmp_path)
    monkeypatch.setattr(briefs.socket, "getaddrinfo",
                        lambda *a, **kw: [(0, 1, 6, "", ("157.166.208.18", 0))])

    good = (b"%PDF-1.7", b"payload" * 500)
    state = {"n": 0}

    class _Resp:
        status_code = 200
        headers = {}

        def __init__(self, explode):
            self._explode = explode

        async def aiter_bytes(self, _size):
            yield b"%PDF-1.7 head"
            if self._explode:
                await asyncio.sleep(0)
                raise httpx.ReadError("connection reset")
            for c in good[1:]:
                yield c

    class _Ctx:
        def __init__(self, explode):
            self._e = explode

        async def __aenter__(self):
            return _Resp(self._e)

        async def __aexit__(self, *a):
            return False

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, **kw):
            state["n"] += 1
            return _Ctx(explode=(state["n"] == 1))  # 第一路断流，第二路正常

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    t_bad = asyncio.ensure_future(briefs.post_fetch_pdf(
        {"url": "https://arxiv.org/pdf/2601.00777"}, background_stub))
    t_good = asyncio.ensure_future(briefs.post_fetch_pdf(
        {"url": "https://arxiv.org/pdf/2601.00777"}, background_stub))
    bad, good_result = await asyncio.gather(t_bad, t_good, return_exceptions=True)

    from fastapi import HTTPException as _HTTPException
    assert isinstance(bad, _HTTPException) and bad.status_code == 502
    assert isinstance(good_result, dict) and good_result["status"] == "started"
    written = (tmp_path / "2601.00777.pdf").read_bytes()
    assert written.startswith(b"%PDF-1.7") and len(written) >= 1 + len(b"payload") * 500
    assert not list(tmp_path.glob("*.part*")), "失败的那路不该留下半截 tmp"


def test_concurrent_distinct_docs_do_not_interfere(app_client, dns, monkeypatch):
    """不同条目并发也不该互相抢名字/互相删 tmp。"""
    client, index_calls = app_client
    _mock_http(monkeypatch, chunks=(b"%PDF-1.7", b"payload"))
    urls = [f"https://arxiv.org/pdf/26{m}1.2345" for m in range(3)]
    rs = [client.post("/api/v1/briefs/fetch-pdf", json={"url": u}) for u in urls]
    assert all(r.status_code == 200 for r in rs)
    assert len(list(briefs.PDF_DIR.glob("*.pdf"))) == 3
    assert not list(briefs.PDF_DIR.glob("*.part*"))
    assert len(index_calls) == 3


def test_session_message_persists_memory_hits(tmp_path):
    """检索命中随消息落盘：刷新/翻旧账后"提及论文"条目不丢。"""
    from src.ui.backend.services.session_manager import SessionManager

    mgr = SessionManager(base_dir=str(tmp_path))
    sid = mgr.create_session("t-hits")["session_id"]
    hits = [{"source_id": "2601.00001", "source_type": "brief",
             "url": "https://arxiv.org/abs/2601.00001", "abstract": "标题：x"}]
    mgr.save_message(session_id=sid, role="assistant", content="答", memory_hits=hits)
    loaded = mgr.load_session(sid)
    assert loaded["messages"][-1]["memory_hits"] == hits
    # 空 hits 不写入空键，旧形状不变
    mgr.save_message(session_id=sid, role="assistant", content="答2")
    assert "memory_hits" not in mgr.load_session(sid)["messages"][-1]
