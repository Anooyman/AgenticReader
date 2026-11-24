"""简报"轻量入库"路径的回归测试（替代原 /memory 页的 load-jobs 测试）。

页面退役后的职责边界变了，但两件事不变：
1. `POST /api/v1/briefs/light-load` 的入队行为——缺 coverage_date 挡在
   入队前，成功时登记一个 kind=load_brief_date、target=日期 的任务；
2. `job_runner._run_job()` 对 load_brief_date 的三种结局：成功 / 有警告
   （任务算完成，警告进 detail）/ 真的失败。判定只认
   {"loaded","skipped","errors"} 三键，driver 换成 local 后这条契约
   由 test_gateway_semantics.py 的 dispatch 用例在 gateway 层钉住，这里
   只管 job_runner 侧的消费形状。

全程不碰真实外部服务与 LanceDB：路由的 enqueue 与 _run_job 的
gateway.load_brief_date 都用 monkeypatch 换掉。
"""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.memory import gateway
from src.ui.backend.api.v1 import briefs
from src.ui.backend.services import job_runner


@pytest.fixture()
def client(monkeypatch):
    app = FastAPI()
    app.include_router(briefs.router, prefix="/api/v1/briefs")
    return TestClient(app)


@pytest.fixture()
def ledger(monkeypatch):
    """把 job_runner 的账本操作换成内存版：记录 enqueue 调用。"""
    calls = []

    async def fake_enqueue(kind, target, title="", item_type=None):
        calls.append({"kind": kind, "target": target, "title": title})
        return {"job_id": f"j-{target}", "kind": kind, "target": target, "status": "queued"}

    monkeypatch.setattr(job_runner, "enqueue", fake_enqueue)
    return calls


# ---------------------------------------------------------------- /light-load
def test_light_load_requires_coverage_date(client, ledger):
    r = client.post("/api/v1/briefs/light-load", json={})
    assert r.status_code == 400
    assert ledger == []  # 校验挡在入队之前


def test_light_load_rejects_bad_date_format(client, ledger):
    """格式校验与原 /load-jobs 的 _normalize_dates 同档：坏日期挡在入队前，
    不该晚一步在 job 执行时才炸出来。"""
    r = client.post("/api/v1/briefs/light-load", json={"coverage_date": "11-13-2026"})
    assert r.status_code == 400
    r = client.post("/api/v1/briefs/light-load", json={"coverage_date": "昨天"})
    assert r.status_code == 400
    assert ledger == []


def test_light_load_enqueues_load_brief_date(client, ledger):
    """单日兼容旧形状：coverage_date 仍然受理，响应从 {job} 变成统一的
    {requested, queued, dates, jobs} 四键——与 /load 的返回形状对齐。"""
    r = client.post("/api/v1/briefs/light-load", json={"coverage_date": "2026-11-13"})
    assert r.status_code == 200
    body = r.json()
    assert body["dates"] == ["2026-11-13"]
    assert body["jobs"][0]["kind"] == "load_brief_date"
    assert ledger == [{"kind": "load_brief_date", "target": "2026-11-13",
                       "title": "轻量入库 2026-11-13"}]


def test_light_load_accepts_dates_list(client, ledger):
    """多选批量 load 的主路径：dates 列表一次排 N 个 job，
    顺序按日期排序、重复项去重。"""
    r = client.post("/api/v1/briefs/light-load",
                    json={"dates": ["2026-11-12", "2026-11-10", "2026-11-12"]})
    assert r.status_code == 200
    body = r.json()
    assert body["requested"] == 2 and body["queued"] == 2
    assert body["dates"] == ["2026-11-10", "2026-11-12"]
    assert [c["target"] for c in ledger] == ["2026-11-10", "2026-11-12"]


def test_light_load_rejects_too_many_dates(client, ledger):
    """与原 /load-jobs 同一道闸门：一次超 40 个日期挡在入队前。"""
    too_many = [f"2026-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 31)]
    r = client.post("/api/v1/briefs/light-load", json={"dates": too_many[:41]})
    assert r.status_code == 400
    assert ledger == []


# ---------------------------------------------------------------- memory-status
def test_memory_status_returns_per_date_counts(client, monkeypatch):
    """/memory-status 返回按日期聚合的真实入库计数（AATF 行 + queue done），
    供 /briefs 下拉框/状态行区分"未入库 / 已入库"。计数逻辑本身
    （date_memory_counts）在 briefs_data，这里钉的是端点形状与转线程。"""
    from src.ui.backend.services import briefs_data

    monkeypatch.setattr(briefs_data, "date_memory_counts",
                        lambda: {"2026-11-12": {"aatf": 37, "heavy_done": 2},
                                 "2026-11-11": {"aatf": 0, "heavy_done": 0}})
    r = client.get("/api/v1/briefs/memory-status")
    assert r.status_code == 200
    assert r.json() == {"dates": {"2026-11-12": {"aatf": 37, "heavy_done": 2},
                                  "2026-11-11": {"aatf": 0, "heavy_done": 0}}}


def test_date_memory_counts_merges_aatf_rows_and_queue(tmp_path, monkeypatch):
    """date_memory_counts 的事实来源：AATF 行按 occurred_at 日期聚合、
    queue 里 done 条目按 coverage_date 计数；AATF 读取失败只降级不炸。"""
    from src.ui.backend.services import briefs_data
    from src.memory import gateway

    monkeypatch.setattr(gateway, "browse_all_rows", lambda ns: [
        {"occurred_at": "2026-11-12T00:00:00+00:00"},
        {"occurred_at": "2026-11-12T09:30:00+00:00"},
        {"occurred_at": "2026-11-10T08:00:00+00:00"},
    ])
    monkeypatch.setattr(briefs_data, "load_queue", lambda: {
        "a": {"pipeline_status": "done", "coverage_date": "2026-11-12"},
        "b": {"pipeline_status": "failed_permanent", "coverage_date": "2026-11-11"},
    })
    counts = briefs_data.date_memory_counts()
    assert counts["2026-11-12"] == {"aatf": 2, "heavy_done": 1}
    assert counts["2026-11-10"] == {"aatf": 1, "heavy_done": 0}
    assert "2026-11-11" not in counts  # failed 不算 done


def test_date_memory_counts_survives_db_failure(tmp_path, monkeypatch):
    from src.ui.backend.services import briefs_data
    from src.memory import gateway

    def boom(ns):
        raise RuntimeError("memory db 不可用")

    monkeypatch.setattr(gateway, "browse_all_rows", boom)
    monkeypatch.setattr(briefs_data, "load_queue", lambda: {
        "a": {"pipeline_status": "done", "coverage_date": "2026-11-12"}})
    counts = briefs_data.date_memory_counts()
    # AATF 维度按 0 计，heavy_done 照常给出——库故障不该让简报页报错
    assert counts["2026-11-12"] == {"aatf": 0, "heavy_done": 1}


# ---------------------------------------------------------------- _run_job 结局
def _run_job(monkeypatch, outcome=None, boom=False):
    async def fake_load_date(date):
        if boom:
            raise RuntimeError("轻量入库中途炸了")
        return outcome
    monkeypatch.setattr(gateway, "load_brief_date", fake_load_date)
    job = {"job_id": "j1", "kind": "load_brief_date", "target": "2026-11-13",
           "title": "", "item_type": None}
    return asyncio.run(job_runner._run_job(job))


def test_run_job_load_success(monkeypatch):
    out = _run_job(monkeypatch, {"loaded": True, "skipped": False, "errors": []})
    assert out == {"ok": True}


def test_run_job_load_skipped_only_is_ok(monkeypatch):
    """"该天早已入库 / 空日期"是正常结局——loaded False + skipped True + 无
    errors 不能折成失败，否则 /briefs 上重复点日期就刷一条误导性的错误行
    （新按钮不区分加载状态，这条路径用户天天踩）。文案里也不许再提
    "外部服务"——HTTP 桥已退役，driver 白名单只剩 local，不存在外部服务。"""
    out = _run_job(monkeypatch, {"loaded": False, "skipped": True, "errors": []})
    assert out["ok"] is True
    assert "已是最新" in out["detail"]
    assert "error" not in out


def test_run_job_load_with_warnings_keeps_detail(monkeypatch):
    out = _run_job(monkeypatch, {"loaded": True, "skipped": False,
                                 "errors": ["radar: extract failed"]})
    assert out["ok"] is True
    assert "radar" in out["detail"]


def test_run_job_load_failure_reports_error(monkeypatch):
    out = _run_job(monkeypatch, {"loaded": False, "skipped": False,
                                 "errors": ["nothing written"]})
    assert "未完成" in out["error"]
    assert "nothing written" in out["error"]


def test_run_job_load_exception_maps_to_error(monkeypatch):
    """异常透传的形状：job_runner 把 load_brief_date 抛出的任何异常折成
    "加载简报 X 失败: {e}"——异常文本原样进 error 字段，不吞栈不吞消息。
    注入什么消息都等价，这里用 local 时代的本地故障措辞（桥退役前这里
    写的是外部服务的文案，纯属历史遗留）。"""
    out = _run_job(monkeypatch, boom=True)
    assert "失败" in out["error"]
    assert "轻量入库中途炸了" in out["error"]
