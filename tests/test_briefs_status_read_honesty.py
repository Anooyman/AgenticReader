"""`/api/v1/briefs/memory-status` 不许把"读不出来"报成"都没入库"。

这一层的取舍本来就和其他地方不一样：日期格只有一半信息，`heavy_done` 那半边
还要靠这个函数活着返回——所以让它直接抛错是不合适的。但**继续一声不响**同样
不合适：那正好是最省事也最贵的一种撒谎：一次故障之后，页面会显示"65 天全都
还没入库"。

折中就是这一组用例守的东西：接口照旧 200 返回它拿得到的部分，同时把
"我哪里读失败了"如实挂在 body 上；读成功之后这个记号必须撤掉，否则一次历史
故障会永久挂成 degraded。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.memory.gateway as gateway
from src.ui.backend.api.v1 import briefs
from src.ui.backend.services import briefs_data


def _client():
    app = FastAPI()
    app.include_router(briefs.router, prefix="/api/v1/briefs")
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_markers():
    briefs_data.clear_read_errors()
    yield
    briefs_data.clear_read_errors()


def test_a_failed_aatf_read_is_marked_not_flattened_to_zero(monkeypatch):
    def boom(namespace="*", columns=None):
        raise OSError("LanceDB 打不开这个表")

    monkeypatch.setattr(gateway, "browse_all_rows", boom)
    monkeypatch.setattr(briefs_data, "load_queue", lambda: {})

    body = _client().get("/api/v1/briefs/memory-status").json()
    assert body["degraded"] is True
    assert "date_memory_counts" in body["read_errors"]
    assert "OSError" in body["read_errors"]["date_memory_counts"]
    assert isinstance(body["dates"], dict), "另一半（heavy_done）还得照常给出来"


def test_a_healthy_read_says_nothing_about_degradation(monkeypatch):
    monkeypatch.setattr(gateway, "browse_all_rows", lambda namespace="*", columns=None: [
        {"source_id": "2611.27924", "occurred_at": "2026-11-23T00:00:00+00:00"}])
    monkeypatch.setattr(briefs_data, "load_queue", lambda: {})
    body = _client().get("/api/v1/briefs/memory-status").json()
    assert "degraded" not in body and "read_errors" not in body
    assert body["dates"]["2026-11-23"]["aatf"] == 1


def test_a_previous_failure_does_not_hang_around_as_degraded(monkeypatch):
    """成功一次就要把记号撤掉——否则这条接口会永远在喊故障。"""
    def boom(namespace="*", columns=None):
        raise OSError("上游和本地都没成")

    monkeypatch.setattr(gateway, "browse_all_rows", boom)
    monkeypatch.setattr(briefs_data, "load_queue", lambda: {})
    first = _client().get("/api/v1/briefs/memory-status").json()
    assert first.get("degraded") is True

    monkeypatch.setattr(gateway, "browse_all_rows", lambda namespace="*", columns=None: [])
    second = _client().get("/api/v1/briefs/memory-status").json()
    assert "degraded" not in second, "故障早就好了，接口还在说 degraded"


def test_the_source_id_helper_reports_its_own_failure_too(monkeypatch):
    def boom(namespace="*", columns=None):
        raise RuntimeError("浏览面挂了")

    monkeypatch.setattr(gateway, "browse_all_rows", boom)
    assert briefs_data._local_memory_source_ids("AATF") == set()
    assert "local_memory_source_ids:AATF" in briefs_data.read_errors()

    monkeypatch.setattr(gateway, "browse_all_rows", lambda namespace="*", columns=None: [
        {"source_id": "x"}])
    assert briefs_data._local_memory_source_ids("AATF") == {"x"}
    assert "local_memory_source_ids:AATF" not in briefs_data.read_errors()


def test_meta_shape_keeps_working_alongside_the_marker(monkeypatch):
    monkeypatch.setattr(gateway, "browse_all_rows", lambda namespace="*", columns=None: [])
    monkeypatch.setattr(briefs_data, "load_queue", lambda: {})
    r = _client().get("/api/v1/briefs/memory-status?include_meta=true")
    assert r.status_code == 200
    body = r.json()
    assert "meta" in body
    assert "degraded" not in body
