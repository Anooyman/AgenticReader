"""对话入库的水位线：什么时候才**配**往前推一格。

这条规则决定了"对话记忆会不会静默消失"，比路由对不对更容易出事：
`ingest` 失败时如果水位线照样走，这条会话就再也不会被重试——不是报错，
是**什么都不发生**，而屏幕上没有任何一处会说"少了一条"。

所以这里钉的是三条：

1. 失败不推水位线（只记 `last_error`），下一轮 sweep 还得把它捞回来；
2. 成功时推的是会话的 `updated_at`，**不是当前时间**——否则 ingest 期间
   新到的消息会被误判成已同步，永远漏掉那一截；
3. 只要会话内容又动了（`updated_at` 变大），它重新变成待同步。

`due_sessions()` 用 naive datetime 那一段是踩过的坑（`chat_ingest.py` 里有
注释），这里也照同一个形式来测，别把它测成只有带时区才过。
"""
import asyncio
import json
from datetime import datetime, timedelta

import pytest

from src.ui.backend.services import chat_ingest


def _session(root, session_id="s-1", updated_at="2026-11-20T09:00:00", messages=2):
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{session_id}.json"
    path.write_text(json.dumps({
        "session_id": session_id,
        "updated_at": updated_at,
        "messages": [{"role": "user", "content": "问题"} for _ in range(messages // 2)] +
                    [{"role": "assistant", "content": "回答"} for _ in range(messages - messages // 2)],
    }, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    monkeypatch.setattr(chat_ingest, "SESSIONS_DIR", root)
    monkeypatch.setattr(chat_ingest, "STATE_PATH", tmp_path / "state.json")
    return root, monkeypatch


def _fake_ingest(monkeypatch, *, ok=True, calls=None):
    async def fake(path, *a, **kw):
        if calls is not None:
            calls.append(str(path))
        if not ok:
            raise RuntimeError("上游 ingest 没成")
        return {"chunks_added": 2, "chunks_skipped": 0, "chunks_deleted": 0}

    monkeypatch.setattr(chat_ingest.gateway, "ingest", fake)


# ------------------------------------------------------------------ 失败
def test_a_failed_ingest_does_not_advance_the_watermark(sandbox):
    root, monkeypatch = sandbox
    path = _session(root)
    _fake_ingest(monkeypatch, ok=False)

    out = asyncio.run(chat_ingest.ingest_session("s-1", path, "2026-11-20T09:00:00"))
    assert "error" in out

    state = chat_ingest._load_state()
    entry = state["sessions"]["s-1"]
    assert entry.get("last_ingested_at") is None, "失败了还推水位线 = 这条会话以后没人管了"
    assert entry.get("last_error"), "总得留一个字面说法"

    # 下一轮 sweep 必须还能看见它
    _fake_ingest(monkeypatch, ok=True)
    due = chat_ingest.due_sessions(now=datetime.now() + timedelta(seconds=400))
    assert any(sid == "s-1" for sid, _p, _u in due), "失败之后这条会话掉出了待同步名单"


def test_a_timeouts_failure_is_a_failure_like_any_other(sandbox):
    root, monkeypatch = sandbox
    path = _session(root)

    async def slow(path, *a, **kw):
        await asyncio.sleep(5)
        return {"chunks_added": 1}

    monkeypatch.setattr(chat_ingest.gateway, "ingest", slow)
    monkeypatch.setattr(chat_ingest, "INGEST_TIMEOUT", 0.05)

    out = asyncio.run(chat_ingest.ingest_session("s-1", path, "2026-11-20T09:00:00"))
    assert "error" in out
    assert chat_ingest._load_state()["sessions"]["s-1"].get("last_ingested_at") is None


# ------------------------------------------------------------------ 成功
def test_success_records_the_sessions_updated_at_not_the_clock(sandbox):
    root, monkeypatch = sandbox
    path = _session(root, updated_at="2026-11-20T09:00:00")
    _fake_ingest(monkeypatch, ok=True)

    asyncio.run(chat_ingest.ingest_session("s-1", path, "2026-11-20T09:00:00"))
    entry = chat_ingest._load_state()["sessions"]["s-1"]
    assert entry["last_ingested_at"] == "2026-11-20T09:00:00"
    assert entry["last_error"] is None
    assert entry["last_attempt_at"]  # 尝试时间另有其位，不拿来充当水位线


def test_a_session_that_changed_mid_ingest_is_due_again(sandbox):
    root, monkeypatch = sandbox
    _session(root, updated_at="2026-11-20T09:00:00")
    _fake_ingest(monkeypatch, ok=True)

    asyncio.run(chat_ingest.ingest_session("s-1", root / "s-1.json", "2026-11-20T09:00:00"))
    _session(root, updated_at="2026-11-20T09:30:00")   # ingest 期间又写了新消息

    due = chat_ingest.due_sessions(now=datetime.now() + timedelta(seconds=400))
    assert any(u == "2026-11-20T09:30:00" for _s, _p, u in due)


def test_a_quiet_fresh_session_is_left_alone_until_it_stops_active(sandbox):
    root, monkeypatch = sandbox
    just_now = datetime.now().isoformat(timespec="seconds")
    _session(root, updated_at=just_now)
    _fake_ingest(monkeypatch, ok=True)
    due = chat_ingest.due_sessions(now=datetime.now())
    assert due == [], "还在聊的会话不该每个 tick 都去重算尾块"


def test_forget_session_clears_the_watermark_but_nothing_else(sandbox):
    root, monkeypatch = sandbox
    path = _session(root)
    _fake_ingest(monkeypatch, ok=True)
    asyncio.run(chat_ingest.ingest_session("s-1", path, "2026-11-20T09:00:00"))

    assert chat_ingest.forget_session("s-1") is True
    assert chat_ingest._load_state()["sessions"] == {}
    assert chat_ingest.forget_session("s-1") is False, "重复清理不该报成功"
