"""src/memory/gateway.py bridge_request 的形状回归测试。

前身是 tests/test_llmmemory_bridge_shape.py——/memory 页与其 HTTP 代理
llmmemory.py 退役后，三条逐字保证原样搬进 gateway 层（对外桥仅剩
brief_memory→gateway 一条使用路径，形状保证必须还钉得住）：
  ① transport 失败 → BridgeError(502) + "LLM-Memory webui 不可达（URL）：...
     请确认已运行: python scripts/webui/server.py --port 8765" 旧文案；
  ② HTTP >= 400 → (status, body) 原样返回，body 非 JSON 时退化
     {"detail": text[:300]}；
  ③ 2xx + 非法 body → BridgeError(502) 报错不吞，2xx 合法 body 原样过。

全程不碰真实外部服务：只替换 httpx.AsyncClient.request 成会录音的假实现，
gateway 桥代码（bridge_request 与其上的 brief_* 具名一跳）走的是真身。
"""
import asyncio

import httpx
import pytest

from src.memory import gateway

BASE = "http://127.0.0.1:8765"


@pytest.fixture(autouse=True)
def pin_url(monkeypatch):
    """钉死桥 URL 基准：gateway 的 LLM_MEMORY_URL 在 import 时读 env，测试
    进程若导出了 LLM_MEMORY_URL，下面的 URL 断言会整片红——统一 setattr 回
    BASE，让本文件对环境变量免疫。"""
    monkeypatch.setattr(gateway, "LLM_MEMORY_URL", BASE)


@pytest.fixture()
def fake_lm(monkeypatch):
    """httpx.AsyncClient.request → 录音 + 队列式假响应。

    responses 里放异常实例就 raise，放 Response 就原样返回；
    缺省回一个 200 空 json。"""
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


def _run(coro):
    return asyncio.run(coro)


def test_transport_error_raises_bridge_error_with_legacy_detail(fake_lm):
    fake_lm["responses"].append(httpx.ConnectError("Connection refused"))
    with pytest.raises(gateway.BridgeError) as exc:
        _run(gateway.brief_dates())
    assert exc.value.status_code == 502
    detail = exc.value.detail
    assert detail.startswith("LLM-Memory webui 不可达（")
    assert "请确认已运行: python scripts/webui/server.py --port 8765" in detail


def test_http_error_returns_status_and_body_verbatim(fake_lm):
    fake_lm["responses"].append(httpx.Response(404, json={"error": "unknown job"}))
    status, body = _run(gateway.brief_load_progress("abc"))
    assert status == 404
    assert body == {"error": "unknown job"}


def test_non_json_error_body_degrades_to_truncated_detail(fake_lm):
    fake_lm["responses"].append(httpx.Response(502, text="x" * 400))
    status, body = _run(gateway.brief_dates())
    assert status == 502
    assert body == {"detail": "x" * 300}


def test_2xx_non_json_raises_not_fake_success(fake_lm):
    """2xx + 非 JSON body 的刻意决策：BridgeError(502)，不喂假成功数据。"""
    fake_lm["responses"].append(httpx.Response(200, text="<html>nginx</html>"))
    with pytest.raises(gateway.BridgeError) as exc:
        _run(gateway.brief_dates())
    assert exc.value.status_code == 502
    assert "无法解析为 JSON" in exc.value.detail


def test_2xx_body_passes_through_verbatim(fake_lm):
    fake_lm["responses"].append(httpx.Response(200, json={"dates": ["2026-11-01"]}))
    status, body = _run(gateway.brief_dates())
    assert status == 200
    assert body == {"dates": ["2026-11-01"]}
    call = fake_lm["calls"][0]
    assert call["method"] == "GET"
    assert call["url"] == f"{BASE}/api/briefs/dates"


def test_papers_forwards_dates_param(fake_lm):
    fake_lm["responses"].append(httpx.Response(200, json={"papers": []}))
    _run(gateway.brief_papers("2026-11-01,2026-11-02"))
    call = fake_lm["calls"][0]
    assert call["url"] == f"{BASE}/api/briefs/papers"
    assert call["kw"].get("params") == {"dates": "2026-11-01,2026-11-02"}


def test_load_posts_dates_payload(fake_lm):
    fake_lm["responses"].append(httpx.Response(200, json={"job_id": "j1"}))
    status, body = _run(gateway.brief_load(["2026-11-01"]))
    assert status == 200 and body == {"job_id": "j1"}
    call = fake_lm["calls"][0]
    assert call["method"] == "POST"
    assert call["url"] == f"{BASE}/api/briefs/load"
    assert call["kw"].get("json") == {"dates": ["2026-11-01"]}
