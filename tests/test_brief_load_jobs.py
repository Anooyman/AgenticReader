"""内存页「批量 + 异步 load」的回归测试。

覆盖三件事：

1. `POST /api/v1/llmmemory/load-jobs` 的输入校验与去重——日期格式、单个字符
   串、超量请求都该被挡在入队之前，而不是让外部服务去猜。
2. `GET /api/v1/llmmemory/load-jobs` 只回加载类任务，不把 /api/v1/jobs 里
   的 process_item 之类一起倒给页面。
3. `job_runner._run_job()` 对 `load_brief_date` 的三种结局：成功 / 有警告 /
   真的失败（外部服务明确没写进任何东西）。

全程不碰真实外部服务、也不写 webapp_jobs.json：路由用 monkeypatch 替掉
job_runner 的账本操作，_run_job 用 monkeypatch 替掉 brief_memory.load_date。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ui.backend.api.v1 import llmmemory
from src.ui.backend.services import brief_memory, job_runner

PREFIX = "/api/v1/llmmemory"


@pytest.fixture()
def client(monkeypatch):
    app = FastAPI()
    app.include_router(llmmemory.router, prefix=PREFIX)
    return TestClient(app)


@pytest.fixture()
def ledger(monkeypatch):
    """把 job 账本换成内存版：记录 enqueue 调用，list_jobs 返回固定视图。"""
    calls = []

    async def fake_enqueue(kind, target, title="", item_type=None):
        calls.append({"kind": kind, "target": target, "title": title})
        return {"job_id": f"j-{target}", "kind": kind, "target": target, "status": "queued"}

    def fake_list_jobs():
        return [
            {"job_id": "a", "kind": "load_brief_date", "target": "2026-10-13",
             "status": "done", "created_at": "2"},
            {"job_id": "b", "kind": "process_item", "target": "2610.18861",
             "status": "running", "created_at": "1"},
            {"job_id": "c", "kind": "load_brief_date", "target": "2026-10-14",
             "status": "failed", "detail": "2026-10-14/radar: extract failed",
             "created_at": "0"},
        ]

    monkeypatch.setattr(job_runner, "enqueue", fake_enqueue)
    monkeypatch.setattr(job_runner, "list_jobs", fake_list_jobs)
    return calls


def test_load_jobs_dedupes_and_sorts(client, ledger):
    r = client.post(f"{PREFIX}/load-jobs",
                    json={"dates": ["2026-10-14", "2026-10-13", "2026-10-13"]})
    assert r.status_code == 200
    body = r.json()
    assert body["dates"] == ["2026-10-13", "2026-10-14"]
    assert body["queued"] == 2, "同一日期重复提交不该排两条"
    assert [c["target"] for c in ledger] == ["2026-10-13", "2026-10-14"]
    assert ledger[0]["kind"] == job_kind()


def test_load_jobs_accepts_single_date_string(client, ledger):
    r = client.post(f"{PREFIX}/load-jobs", json={"dates": "2026-10-15"})
    assert r.status_code == 200
    assert ledger == [{"kind": job_kind(), "target": "2026-10-15",
                      "title": "加载简报 2026-10-15"}]


@pytest.mark.parametrize("body", [
    {"dates": ["not-a-date"]},
    {"dates": []},
    {"dates": 12},
    {},
    {"dates": [f"2026-11-{i:02d}" for i in range(1, 42)]},
])
def test_load_jobs_rejects_bad_input(client, ledger, body):
    assert client.post(f"{PREFIX}/load-jobs", json=body).status_code == 400
    assert ledger == [], "校验失败时一个任务都不该入队"


def test_load_jobs_view_only_shows_load_kind(client, ledger):
    r = client.get(f"{PREFIX}/load-jobs")
    assert r.status_code == 200
    assert [j["job_id"] for j in r.json()["jobs"]] == ["a", "c"]


# ---- job_runner 分支 -------------------------------------------------------

def job_kind() -> str:
    return llmmemory._LOAD_KIND


async def _run_load_job(monkeypatch, outcome):
    async def fake_load_date(date):
        return outcome
    monkeypatch.setattr(brief_memory, "load_date", fake_load_date)
    return await job_runner._run_job({"kind": job_kind(), "target": "2026-10-13"})


@pytest.mark.parametrize("outcome,expect_ok,expect_detail", [
    ({"loaded": True, "skipped": False, "errors": []}, True, None),
    # 日期处理了、但里面某个 kind 抽取/入库失败：任务算完成，警告留在 detail
    ({"loaded": True, "skipped": False, "errors": ["2026-10-13/radar: boom"]},
     True, "2026-10-13/radar: boom"),
    # 外部服务一口没吃：失败，好让 UI 给出"重试"
    ({"loaded": False, "skipped": False, "errors": []}, False, None),
])
async def test_run_job_outcomes(monkeypatch, outcome, expect_ok, expect_detail):
    result = await _run_load_job(monkeypatch, outcome)
    assert ("error" in result) is (not expect_ok)
    assert result.get("detail") == expect_detail


async def test_run_job_reports_load_failure_reason(monkeypatch):
    result = await _run_load_job(
        monkeypatch, {"loaded": False, "skipped": False,
                      "errors": ["2026-10-13: nothing processed"]})
    assert "nothing processed" in result["error"]


async def test_unknown_kind_still_rejected():
    result = await job_runner._run_job({"kind": "nope", "target": "x"})
    assert "未知任务类型" in result["error"]
