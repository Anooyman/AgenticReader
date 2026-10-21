"""LLM-Memory 桥接 API——把外部 LLM-Memory webui（默认 http://127.0.0.1:8765）
的 brief 管线能力转发给本 UI 的记忆页面。

为什么用 HTTP 桥接而不是同进程 import：两边是各自独立演进的仓库/venv，
LLM-Memory 侧自己就有完整的 brief 抽取、增量状态、检索与对话链路；这里
只做透明代理，不做第二套语义——路由路径、参数、返回形状都尽量原样透传，
出问题时排查只看一层代码。

对话作用域约定：前端勾选的日期会拼进 query 前缀（"关于 2026-10-19 这期：
……"），namespace 固定为 AATF——LM 的 agentic 检索本来就擅长带日期的
自然语言问题，不需要额外的结构化 scope 字段。
"""
import os

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()

LLM_MEMORY_URL = os.environ.get("LLM_MEMORY_URL", "http://127.0.0.1:8765").rstrip("/")
_TIMEOUT = httpx.Timeout(15.0, read=180.0)


async def _lm(method: str, path: str, **kw):
    """One hop to LLM-Memory webui; connection refused etc. become a clean
    502 naming both services instead of a raw traceback."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.request(method, f"{LLM_MEMORY_URL}{path}", **kw)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM-Memory webui 不可达（{LLM_MEMORY_URL}）：{exc}. "
                   f"请确认已运行: python scripts/webui/server.py --port 8765")
    if r.status_code >= 400:
        try:
            body = r.json()
        except ValueError:
            body = {"detail": r.text[:300]}
        raise HTTPException(status_code=r.status_code, detail=body)
    return r.json()


@router.get("/dates")
async def brief_dates():
    return await _lm("GET", "/api/briefs/dates")


@router.get("/papers")
async def brief_papers(request: Request):
    return await _lm("GET", "/api/briefs/papers",
                     params={"dates": request.query_params.get("dates", "")})


@router.post("/load")
async def brief_load(body: dict):
    return await _lm("POST", "/api/briefs/load",
                     json={"dates": (body or {}).get("dates") or []})


@router.get("/load/progress/{job_id}")
async def brief_load_progress(job_id: str):
    return await _lm("GET", f"/api/briefs/load/progress/{job_id}")


@router.post("/chat")
async def chat(body: dict):
    """Proxy of LM /api/chat (job-based). body: {message, history, namespace}.
    Namespace defaults to AATF because this page's whole premise is the
    brief pipeline."""
    payload = {
        "message": (body or {}).get("message") or "",
        "history": (body or {}).get("history") or [],
        "namespace": (body or {}).get("namespace") or ["AATF"],
    }
    if not payload["message"].strip():
        raise HTTPException(status_code=400, detail="message is required")
    return await _lm("POST", "/api/chat", json=payload)


@router.get("/chat/progress/{job_id}")
async def chat_progress(job_id: str):
    return await _lm("GET", f"/api/chat/progress/{job_id}")


@router.post("/download")
async def download(body: dict):
    """PDF → AgenticReader's data/pdf (the write happens on the LM side,
    whose deepread endpoint is configured to drop files right there)."""
    url = ((body or {}).get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    return await _lm("POST", "/api/deepread/download", json={"url": url})
