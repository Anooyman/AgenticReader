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
import re

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
    # 后台索引任务真跑会起 IndexingAgent——换成记账版
    index_calls = []

    def fake_index(doc_name, provider, pdf_preset):
        index_calls.append(doc_name)

    import src.ui.backend.api.v1.documents as documents
    monkeypatch.setattr(documents, "_index_document_task", fake_index)
    return TestClient(app), index_calls


def _mock_http(monkeypatch, *, status=200, chunks=(b"%PDF-1.7 hello",), exc=None):
    """替换 briefs 用到的 httpx.AsyncClient：GET stream 返回给定状态/分块。"""
    import httpx

    class _Resp:
        status_code = status

        async def aiter_bytes(self, _size):
            if exc:
                raise exc
            for c in chunks:
                yield c

    class _Ctx:
        async def __aenter__(self):
            return _Resp()

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
            return _Ctx()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def test_fetch_pdf_exists_idempotent(app_client, monkeypatch):
    client, index_calls = app_client
    (briefs.PDF_DIR / "2601.12345.pdf").write_bytes(b"%PDF-1.5 old")
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://arxiv.org/abs/2601.12345"})
    assert r.status_code == 200
    assert r.json() == {"status": "exists", "doc_name": "2601.12345.pdf"}
    assert index_calls == []  # exists 直接返回，不重复触发索引


def test_fetch_pdf_arxiv_download_starts_index(app_client, monkeypatch):
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
    assert "1706.03762.pdf" in index_calls  # 后台索引已登记（带 .pdf 的文档名）


def test_fetch_pdf_rejects_non_pdf_body(app_client, monkeypatch):
    client, index_calls = app_client
    _mock_http(monkeypatch, chunks=(b"<html>not a pdf</html>",))
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://arxiv.org/abs/2601.99999"})
    assert r.status_code == 400
    assert "PDF" in r.json()["detail"]
    assert index_calls == []
    # 失败后不留半截文件
    assert not list(briefs.PDF_DIR.glob("*.pdf"))


def test_fetch_pdf_http_error_maps_502(app_client, monkeypatch):
    client, _ = app_client
    _mock_http(monkeypatch, status=404)
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://example.com/paper.pdf"})
    assert r.status_code == 502


def test_fetch_pdf_size_cap(app_client, monkeypatch):
    client, _ = app_client
    monkeypatch.setattr(briefs, "_FETCH_PDF_MAX_BYTES", 16)
    _mock_http(monkeypatch, chunks=(b"%PDF-", b"x" * 64))
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://arxiv.org/pdf/2601.00002"})
    assert r.status_code == 413
    assert not list(briefs.PDF_DIR.glob("*.pdf"))


def test_fetch_pdf_unsafe_name_400(app_client):
    client, _ = app_client
    # 末段含非法字符（* / 等）→ 推不出安全文档名，挡在进入下载之前
    r = client.post("/api/v1/briefs/fetch-pdf",
                    json={"url": "https://example.com/dl/%2Ax.pdf"})
    assert r.status_code == 400
    r = client.post("/api/v1/briefs/fetch-pdf", json={"url": "ftp://x/y.pdf"})
    assert r.status_code == 400


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
