"""llmmemory.py 桥形状回归测试。

httpx 一跳收编进 src/memory/gateway.py 的 bridge_request / brief_* 之后，
原来 _lm 的三条逐字保证必须原样成立（0.x 收敛阶段不许有形状漂移）：
  ① transport 失败 → 502 + "LLM-Memory webui 不可达（URL）：...请确认已
     运行: python scripts/webui/server.py --port 8765" 旧文案；
  ② HTTP >= 400 → 原状态码 + 解析后的 body 透传，body 不是 JSON 时退化为
     {"detail": text[:300]}；
  ③ 2xx → 返回外部 json body 原样；2xx 但 body 解析不出 JSON → 不喂假
     成功数据，BridgeError(502) 报错不吞（bridge_request docstring 有记录）。
外加本轮新增的 POST /chat/stop/{job_id} 纯透传的两路（200 / 404）。

全程不碰真实外部服务：只替换 httpx.AsyncClient.request 成会录音的假实现，
gateway 桥代码（bridge_request、BriefError→HTTPException 映射）走的是真身。
"""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.memory import gateway
from src.ui.backend.api.v1 import llmmemory

PREFIX = "/api/v1/llmmemory"
BASE = "http://127.0.0.1:8765"


@pytest.fixture()
def client(monkeypatch):
    # 钉死桥 URL 基准：gateway 的 LLM_MEMORY_URL 在 import 时读 env，测试
    # 进程若导出了 LLM_MEMORY_URL，下面的 URL 断言会整片红——这里统一
    # setattr 回 BASE，让本文件对环境变量免疫。
    monkeypatch.setattr(gateway, "LLM_MEMORY_URL", BASE)
    app = FastAPI()
    app.include_router(llmmemory.router, prefix=PREFIX)
    return TestClient(app)


@pytest.fixture()
def fake_lm(monkeypatch):
    """httpx.AsyncClient.request → 录音 + 队列式假响应。

    responses 里放异常实例就 raise，放 Response 就原样返回；
    缺省回一个 200 空 json。TestClient 自己走同步 transport，
    替换这个类方法只影响 gateway 桥那一条路。"""
    calls = []
    responses = []

    async def fake_request(self, method, url, **kw):
        calls.append({"method": method, "url": str(url), "kw": kw})
        nxt = responses.pop(0) if responses else httpx.Response(200, json={})
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    return {"calls": calls, "responses": responses}


def test_transport_error_maps_to_502_with_legacy_detail(client, fake_lm):
    fake_lm["responses"].append(httpx.ConnectError("Connection refused"))
    r = client.get(f"{PREFIX}/dates")
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail.startswith("LLM-Memory webui 不可达（")
    assert "请确认已运行: python scripts/webui/server.py --port 8765" in detail


def test_http_error_maps_status_and_body_verbatim(client, fake_lm):
    fake_lm["responses"].append(httpx.Response(404, json={"error": "unknown job"}))
    r = client.get(f"{PREFIX}/load/progress/abc")
    assert r.status_code == 404
    assert r.json()["detail"] == {"error": "unknown job"}


def test_non_json_error_body_degrades_to_truncated_detail(client, fake_lm):
    fake_lm["responses"].append(httpx.Response(502, text="x" * 400))
    r = client.get(f"{PREFIX}/dates")
    assert r.status_code == 502
    assert r.json()["detail"] == {"detail": "x" * 300}


def test_2xx_non_json_maps_to_502_not_fake_success(client, fake_lm):
    """2xx + 非 JSON body 的刻意决策：不把它当成功数据喂给前端，
    BridgeError→502（旧 _lm 在这里是 JSONDecodeError→500，"报错不吞"
    语义相同，映射码 502 属收敛后的形状决策，由本测试钉死）。"""
    fake_lm["responses"].append(httpx.Response(200, text="<html>nginx</html>"))
    r = client.get(f"{PREFIX}/dates")
    assert r.status_code == 502
    assert "无法解析为 JSON" in r.json()["detail"]


def test_2xx_body_passes_through_verbatim(client, fake_lm):
    fake_lm["responses"].append(httpx.Response(200, json={"dates": ["2026-11-01"]}))
    r = client.get(f"{PREFIX}/dates")
    assert r.status_code == 200
    assert r.json() == {"dates": ["2026-11-01"]}
    call = fake_lm["calls"][0]
    assert call["method"] == "GET"
    assert call["url"] == f"{BASE}/api/briefs/dates"


def test_papers_forwards_dates_param(client, fake_lm):
    fake_lm["responses"].append(httpx.Response(200, json={"papers": []}))
    r = client.get(f"{PREFIX}/papers?dates=2026-11-01,2026-11-02")
    assert r.status_code == 200
    call = fake_lm["calls"][0]
    assert call["url"] == f"{BASE}/api/briefs/papers"
    assert call["kw"].get("params") == {"dates": "2026-11-01,2026-11-02"}


def test_chat_posts_payload_with_aatf_default(client, fake_lm):
    fake_lm["responses"].append(httpx.Response(200, json={"job_id": "j1"}))
    r = client.post(f"{PREFIX}/chat", json={"message": "hi", "history": []})
    assert r.status_code == 200
    assert r.json() == {"job_id": "j1"}
    call = fake_lm["calls"][0]
    assert call["method"] == "POST"
    assert call["url"] == f"{BASE}/api/chat"
    assert call["kw"]["json"] == {"message": "hi", "history": [], "namespace": ["AATF"]}


def test_chat_rejects_blank_message_before_hop(client, fake_lm):
    r = client.post(f"{PREFIX}/chat", json={"message": "   "})
    assert r.status_code == 400
    assert fake_lm["calls"] == []


def test_chat_stop_passes_through(client, fake_lm):
    fake_lm["responses"].append(httpx.Response(200, json={"ok": True}))
    r = client.post(f"{PREFIX}/chat/stop/job-123")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    call = fake_lm["calls"][0]
    assert call["method"] == "POST"
    assert call["url"] == f"{BASE}/api/chat/stop/job-123"


def test_chat_stop_unknown_job_maps_external_404(client, fake_lm):
    fake_lm["responses"].append(httpx.Response(404, json={"error": "unknown chat job: x"}))
    r = client.post(f"{PREFIX}/chat/stop/x")
    assert r.status_code == 404
    assert r.json()["detail"] == {"error": "unknown chat job: x"}


def test_download_forwards_url(client, fake_lm):
    fake_lm["responses"].append(httpx.Response(200, json={"id": "f", "path": "/p/f.pdf"}))
    r = client.post(f"{PREFIX}/download", json={"url": "https://arxiv.org/pdf/2401.00001.pdf"})
    assert r.status_code == 200
    call = fake_lm["calls"][0]
    assert call["url"] == f"{BASE}/api/deepread/download"
    assert call["kw"]["json"] == {"url": "https://arxiv.org/pdf/2401.00001.pdf"}
