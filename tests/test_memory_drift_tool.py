"""`tools/check_memory_drift.py` 自己的测试。

这个工具是"谁拿着哪些条目"的判据：退出码从 1 变 0 被当成了收敛完成的标志，
那它自己就不能是个大概能用的脚本。这里验的全是它会**说谎**的那几种情形：

* 只在本地/只在冻结库的条目有没有被数出来——漏数就是"明明漏了却报平安"；
* **读不到库和库是空的必须是两件事**（退出码 2 与 0 的分别）。这是本工具最
  要紧的一条：把"打不开"当"没有"，比漏几条危险得多；
* 车道之外的 namespace（上游机器级那些 `slug-<hex>`、AR 的派生名）不参与
  判定，否则决策面的行会被误报成"漏网的对话"；
* 输出能被机器读：`--json` 的形状稳定，CI 才有地方挂。

三个库都是临时造的，不碰任何真实数据根。
"""
import json
import os
import time

import pytest

from tools import check_memory_drift as drift

lancedb = pytest.importorskip("lancedb")


def _write(path, rows, dates=None):
    """rows: {namespace: [source_id, ...]} → 一个 `memories` 表。

    schema 手写而不是让 lancedb 从数据里推：空库那格也得建得出表，
    否则"有个库但里面 0 行"和"根本没建过"在这套测试里就没法分开造了。
    dates 是可选的 {source_id: "YYYY-MM-DD"}——写日期这件事应当是可测的，
    工具里"这批东西是什么时候进去的"完全靠它。
    """
    import pyarrow as pa

    data = [{"id": f"{ns}-{i}", "namespace": ns, "source_id": sid,
             "created_at": (dates or {}).get(sid, "")}
            for ns, ids in rows.items() for i, sid in enumerate(ids)]
    schema = pa.schema([pa.field("id", pa.string()),
                        pa.field("namespace", pa.string()),
                        pa.field("source_id", pa.string()),
                        pa.field("created_at", pa.string())])
    db = lancedb.connect(str(path))
    if db.list_tables().tables:
        db.drop_table("memories")
    db.create_table("memories", data=data, schema=schema)


def test_entries_that_only_live_locally_are_counted(tmp_path):
    _write(tmp_path / "up", {"AATF": ["a", "b"], "webapp-chat": ["s1"]})
    _write(tmp_path / "local", {"AATF": ["a", "b", "only-here"]})
    _write(tmp_path / "legacy", {})

    report = drift.probe(tmp_path / "up", tmp_path / "local", tmp_path / "legacy")
    lane = report["lanes"]["AATF"]
    assert lane["local_not_upstream"] == ["only-here"]
    assert lane["upstream_ids"] == 2 and lane["local_ids"] == 3
    assert report["errors"] == {}
    assert report["lanes"]["webapp-chat"]["local_not_upstream"] == []


def test_an_unreadable_store_is_not_reported_as_an_empty_one(tmp_path):
    """路径不存在 ≠ 库是空的。这条区分是整个工具最要紧的地方：把"打不开"
    当成"没有"，比漏几条危险得多。"""
    _write(tmp_path / "up", {"AATF": ["a"]})
    report = drift.probe(tmp_path / "up", tmp_path / "does-not-exist", tmp_path / "also-no")
    assert report["errors"].get("local") and report["errors"].get("legacy")
    assert report["lanes"]["AATF"]["local_ids"] == 0, "读不到不等于空"


def test_a_store_that_exists_but_has_no_table_is_empty_not_broken(tmp_path):
    """表是第一次写入才建的——fresh install 的上游就是这个样子，
    它必须是 0 行而不是退出码 2。"""
    (tmp_path / "fresh").mkdir()
    _write(tmp_path / "up", {"AATF": ["a"]})
    _write(tmp_path / "legacy", {})
    report = drift.probe(tmp_path / "up", tmp_path / "fresh", tmp_path / "legacy")
    assert report["errors"] == {}, report["errors"]
    assert report["lanes"]["AATF"]["local_ids"] == 0
    assert drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "fresh"),
                       "--legacy", str(tmp_path / "legacy")]) == 0


def test_namespaces_outside_the_lanes_do_not_move_the_verdict(tmp_path):
    _write(tmp_path / "up", {"agenticreader-250b03c14726": ["x"] * 5})
    _write(tmp_path / "local", {})
    _write(tmp_path / "legacy", {})
    report = drift.probe(tmp_path / "up", tmp_path / "local", tmp_path / "legacy")
    assert report["other_namespaces"].get("agenticreader-250b03c14726") == {"upstream": 5}
    for lane in report["lanes"].values():
        assert lane["local_not_upstream"] == []
    assert drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "local"),
                       "--legacy", str(tmp_path / "legacy")]) == 0


def test_cli_exit_codes_distinguish_stray_rows_from_unreadable_stores(tmp_path):
    _write(tmp_path / "up", {"AATF": ["a"]})
    _write(tmp_path / "local", {"AATF": ["a", "stray"]})
    _write(tmp_path / "legacy", {})
    clean = drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "up"),
                        "--legacy", str(tmp_path / "legacy"), "--json"])
    assert clean == 0, "没有只在本地的条目时必须报平安"

    stray = drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "local"),
                        "--legacy", str(tmp_path / "legacy")])
    assert stray == 1

    broken = drift.main(["--upstream", str(tmp_path / "up"),
                         "--local", str(tmp_path / "nope"), "--legacy", str(tmp_path / "nope2")])
    assert broken == 2, "读不到库必须是 2——不是 0 也不是 1"


def test_json_output_is_stable_enough_to_hang_ci_on(tmp_path, capfd):
    _write(tmp_path / "up", {"AATF": ["a"]})
    _write(tmp_path / "local", {"AATF": ["a"]})
    _write(tmp_path / "legacy", {})
    drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "local"),
                "--legacy", str(tmp_path / "legacy"), "--json"])
    payload = json.loads(capfd.readouterr().out)
    assert {"lanes", "verdict", "paths", "errors"} <= set(payload)
    assert payload["verdict"]["stray_entries"] == 0
    assert payload["lanes"]["AATF"]["upstream_ids"] == 1


def test_default_paths_point_at_the_three_stores_it_claims():
    # 路径写错，工具会在"看起来一切正常"的状态下漏掉整个库
    import os

    assert drift.DEFAULT_UPSTREAM.endswith(".llm-memory/memory")
    assert os.path.isdir(os.path.dirname(drift.DEFAULT_LOCAL)), "默认本地库路径不像样"
    assert drift.DEFAULT_LEGACY != drift.DEFAULT_LOCAL


# ------------------------------------------------------------- 日期：谁还在往错的地方写

def test_stray_rows_carry_the_window_they_were_written_in(tmp_path):
    """"只在本地 87 条"这个数说的是数量；日期说的是性质——历史包袱还是
    此刻正在发生的漏写，两者要分开报，不然一个停在三个月前的数字会被
    当成一个每天在变坏的数字。"""
    _write(tmp_path / "up", {"AATF": ["a", "b"]}, dates={"a": "2026-11-01", "b": "2026-11-10"})
    _write(tmp_path / "local", {"AATF": ["a", "b", "late-1", "late-2"]},
           dates={"a": "2026-11-01", "b": "2026-11-10",
                  "late-1": "2026-11-18", "late-2": "2026-11-22"})
    _write(tmp_path / "legacy", {})
    lanes = drift.probe(tmp_path / "up", tmp_path / "local", tmp_path / "legacy")["lanes"]
    assert lanes["AATF"]["local_only_first"] == "2026-11-18"
    assert lanes["AATF"]["local_only_last"] == "2026-11-22"


def test_the_tool_says_whether_local_is_still_getting_writes(tmp_path):
    _write(tmp_path / "up", {"AATF": ["a"]}, dates={"a": "2026-11-05"})
    _write(tmp_path / "local", {"AATF": ["z"]}, dates={"z": "2026-11-24"})
    _write(tmp_path / "legacy", {})
    report = drift.probe(tmp_path / "up", tmp_path / "local", tmp_path / "legacy")
    assert report["newest_write"]["local"] == "2026-11-24"
    assert report["newest_write"]["upstream"] == "2026-11-05"
    assert report["newest_write"]["local"] > report["newest_write"]["upstream"]

    drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "local"),
                "--legacy", str(tmp_path / "legacy")])  # 人读的那屏不许炸


def test_no_created_at_column_is_reported_as_unknown_not_as_zero(tmp_path):
    """缺日期列时不许悄悄当成"没有这类条目"，那是把未知抹平成平安。"""
    db = lancedb.connect(str(tmp_path / "nodates"))
    db.create_table("memories", data=[{"id": "a", "namespace": "AATF",
                                      "source_id": "a"}])
    db2 = lancedb.connect(str(tmp_path / "up"))
    db2.create_table("memories", data=[{"id": "a", "namespace": "AATF",
                                        "source_id": "a"}])
    report = drift.probe(tmp_path / "up", tmp_path / "nodates", tmp_path / "up")
    assert report["errors"] == {}
    assert report["newest_write"] == {"upstream": "", "local": "", "legacy": ""}
    assert report["lanes"]["AATF"]["local_only_first"] == ""


def test_a_same_day_tie_is_called_a_tie_not_all_clear(tmp_path, capsys):
    """两边同一天都在写时，"上游不比本地旧"这句会读成"没事"，其实那是一句
    还没裁决的"两边同时在长"。这个形状必须有自己的说法。"""
    _write(tmp_path / "up", {"AATF": ["a"]}, dates={"a": "2026-11-24"})
    _write(tmp_path / "local", {"AATF": ["b"]}, dates={"b": "2026-11-24"})
    _write(tmp_path / "legacy", {})
    drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "local"),
                "--legacy", str(tmp_path / "legacy")])
    out = capsys.readouterr().out
    assert "同一天" in out and "上游不比本地旧" not in out


def test_lane_level_recency_beats_the_store_level_one(tmp_path, capsys):
    """store 级的"两边都在长"会把两条不相干的车道混成一句话。这里造一个
    只在一辆车道上分叉的场景：本车道上游已经两天没动、本地还在写——
    这句必须说得出"是这条车道的事"。"""
    _write(tmp_path / "up", {"AATF": ["a"], "webapp-chat": ["s1"]},
           dates={"a": "2026-11-22", "s1": "2026-11-22"})
    _write(tmp_path / "local", {"AATF": ["a", "fresh"]}, dates={"a": "2026-11-22", "fresh": "2026-11-24"})
    _write(tmp_path / "legacy", {})
    report = drift.probe(tmp_path / "up", tmp_path / "local", tmp_path / "legacy")
    assert report["lanes"]["AATF"]["upstream_last_write"] == "2026-11-22"
    assert report["lanes"]["AATF"]["local_last_write"] == "2026-11-24"

    drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "local"),
                "--legacy", str(tmp_path / "legacy")])
    out = capsys.readouterr().out
    assert "这条车道" in out and "上游在这条车道上已经不动了" in out


def test_missing_dates_produce_no_lane_claim(tmp_path):
    """没有 created_at 就没有"谁在写"的说法——工具不许在这里发明日期。"""
    _write(tmp_path / "up", {"AATF": ["a"]}, dates={})
    _write(tmp_path / "local", {"AATF": ["a", "b"]}, dates={})
    _write(tmp_path / "legacy", {})
    report = drift.probe(tmp_path / "up", tmp_path / "local", tmp_path / "legacy")
    assert report["lanes"]["AATF"]["upstream_last_write"] == ""
    assert report["lanes"]["AATF"]["local_last_write"] == ""
    drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "local"),
                "--legacy", str(tmp_path / "legacy")])  # 不许因为缺日期就抛


# ---------------------------------------------------------------- 路由现状（解释数字的那句）

def test_unset_addressing_is_reported_as_the_real_reason(tmp_path):
    """数字后面如果不带一句"为什么不生效"，读的人就会去翻明明全绿的测试。"""
    state = drift.routing_state(env={"LLM_MEMORY_REPO": "", "MEMORY_STORE_MODE": ""},
                                ar_root=tmp_path)
    assert state["effective_repo"] == ""
    assert "没有值" in state["verdict"] and "data/memory_db" in state["verdict"]


def test_a_valid_checkout_says_the_four_paths_are_routed(tmp_path):
    checkout = tmp_path / "lm" / "src" / "llm_memoryd"
    checkout.mkdir(parents=True)
    state = drift.routing_state(env={"LLM_MEMORY_REPO": str(tmp_path / "lm"),
                                     "MEMORY_STORE_MODE": ""}, ar_root=tmp_path)
    assert state["effective_repo"] == str(tmp_path / "lm")
    assert "四条路都走上游" in state["verdict"]


def test_a_bad_path_is_called_a_bad_path(tmp_path):
    state = drift.routing_state(env={"LLM_MEMORY_REPO": str(tmp_path / "not-here"),
                                     "MEMORY_STORE_MODE": ""}, ar_root=tmp_path)
    assert "不是一个 LLM-Memory checkout" in state["verdict"]


def test_the_kill_switch_overrides_an_valid_address(tmp_path):
    checkout = tmp_path / "lm" / "src" / "llm_memoryd"
    checkout.mkdir(parents=True)
    state = drift.routing_state(env={"LLM_MEMORY_REPO": str(tmp_path / "lm"),
                                     "MEMORY_STORE_MODE": "local"}, ar_root=tmp_path)
    assert state["store_mode"] == "local"
    assert "kill switch" in state["verdict"] or "压死" in state["verdict"]


def test_dotenv_counts_because_settings_loads_it(tmp_path):
    """`settings.py` 是 `load_dotenv()`：只写在 `.env` 里的那个键也算设过。
    只读 shell 会得出"没设"的错误结论，进而把一套其实能跑的配置说成零联动。"""
    (tmp_path / ".env").write_text("LLM_MEMORY_REPO=/opt/llm-memory\n", encoding="utf-8")
    state = drift.routing_state(env={}, ar_root=tmp_path)
    assert state["dotenv_repo"] == "/opt/llm-memory"
    assert state["effective_repo"] == "/opt/llm-memory"

    # shell 有值时以 shell 为准（dotenv 默认不覆盖已有变量）
    state2 = drift.routing_state(env={"LLM_MEMORY_REPO": "/from/shell"}, ar_root=tmp_path)
    assert state2["effective_repo"] == "/from/shell"


def test_an_empty_local_table_is_flagged_as_ambiguous_not_clean(tmp_path, capsys):
    """空表是个**歧义**状态：可能是"都归上游了"，也可能是"刚被删空"。工具
    不许把它自动读成好消息——那是最省事也最贵的一种撒谎。"""
    _write(tmp_path / "up", {"AATF": ["a", "b"]}, dates={"a": "2026-11-22"})
    _write(tmp_path / "local", {})          # 表在，0 行
    _write(tmp_path / "legacy", {})
    drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "local"),
                "--legacy", str(tmp_path / "legacy")])
    out = capsys.readouterr().out
    assert "空表" in out and "刚被清空" in out
    assert "「已入库」" in out, "得把『空表不算证据』这层意思说出口"


def test_a_local_store_without_any_table_is_the_honest_empty(tmp_path, capsys):
    """连表都没有是另一种形状，说得清"这里一条都没有"，别和空表混着喊。"""
    import lancedb as _lance
    import pyarrow as _pa
    db = _lance.connect(str(tmp_path / "nohead"))
    db.create_table("memories", data=[{"id": "x", "namespace": "zz", "source_id": "x",
                                      "created_at": "2026-11-01"}],
                    schema=_pa.schema([_pa.field("id", _pa.string()),
                                       _pa.field("namespace", _pa.string()),
                                       _pa.field("source_id", _pa.string()),
                                       _pa.field("created_at", _pa.string())]))
    db.drop_table("memories")
    _write(tmp_path / "up", {"AATF": ["a"]})
    _write(tmp_path / "legacy", {})
    drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "nohead"),
                "--legacy", str(tmp_path / "legacy")])
    out = capsys.readouterr().out
    assert "连表都没有" in out


# ------------------------------------------------------------------ 向量宽度
def _write_widened(path, width, ns="AATF", ids=("a",)):
    """造一个**带向量列**的库：宽度的事只能这么测，别的列都问不出尺寸。"""
    import lancedb as _lance
    import pyarrow as _pa

    schema = _pa.schema([_pa.field("id", _pa.string()),
                         _pa.field("namespace", _pa.string()),
                         _pa.field("source_id", _pa.string()),
                         _pa.field("created_at", _pa.string()),
                         _pa.field("vector", _pa.list_(_pa.float32(), width))])
    data = [{"id": f"{ns}-{i}", "namespace": ns, "source_id": sid,
             "created_at": "2026-11-01", "vector": [0.0] * width}
            for i, sid in enumerate(ids)]
    db = _lance.connect(str(path))
    db.create_table("memories", data=data, schema=schema)


def test_every_store_gets_a_measured_vector_width(tmp_path, monkeypatch, capsys):
    _write_widened(tmp_path / "u", 512)
    _write_widened(tmp_path / "l", 1536)
    _write(tmp_path / "lg", {})
    drift.main(["--upstream", str(tmp_path / "u"), "--local", str(tmp_path / "l"),
                "--legacy", str(tmp_path / "lg"), "--json"])
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["widths"]["upstream"] == 512
    assert payload["widths"]["local"] == 1536
    assert payload["widths"]["legacy"] is None, "没有向量列就该诚实地说是 None"


def test_a_width_difference_names_the_portability_wall(tmp_path):
    _write_widened(tmp_path / "u", 512)
    _write_widened(tmp_path / "l", 1536)
    _write_widened(tmp_path / "lg", 1536)
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        drift.main(["--upstream", str(tmp_path / "u"), "--local", str(tmp_path / "l"),
                    "--legacy", str(tmp_path / "lg")])
    out = buf.getvalue()
    assert "upstream=512" in out and "local=1536" in out
    assert "互不可移植" in out, "宽度不一致必须说出它的后果，别只报三个数字"


def test_matching_widths_do_not_cry_warning(tmp_path):
    _write_widened(tmp_path / "u", 512)
    _write_widened(tmp_path / "l", 512)
    _write_widened(tmp_path / "lg", 512)
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        drift.main(["--upstream", str(tmp_path / "u"), "--local", str(tmp_path / "l"),
                    "--legacy", str(tmp_path / "lg")])
    out = buf.getvalue()
    assert "upstream=512" in out
    assert "互不可移植" not in out, "宽度一致还喊警告，就是那个总在喊错的检查"


def test_staging_activity_reports_whether_the_upstream_branch_is_been_walked(tmp_path, monkeypatch):
    """中转目录是"上游那条分支真的跑过"的唯一外部证据——工具得说得出来。"""
    import time
    staging = tmp_path / "data" / "memory_staging" / "brief"
    staging.mkdir(parents=True)
    (staging / "a.json").write_text("{}", encoding="utf-8")
    (staging / "b.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(drift, "AR", str(tmp_path))
    st = drift.staging_activity()
    assert st["files"] == 2 and st["newest"] == time.strftime("%Y-%m-%d")
    assert st["today"] == 2


def test_a_fresh_staging_dir_makes_the_tool_say_it_out_loud(tmp_path, monkeypatch, capsys):
    import time
    staging = tmp_path / "data" / "memory_staging" / "brief"
    staging.mkdir(parents=True)
    (staging / "a.json").write_text("{}", encoding="utf-8")
    os.utime(staging / "a.json", (time.time(), time.time()))
    monkeypatch.setattr(drift, "AR", str(tmp_path))
    _write(tmp_path / "up", {"AATF": ["x"]}, dates={"x": "2026-11-20"})
    _write(tmp_path / "local", {})
    _write(tmp_path / "legacy", {})
    drift.main(["--upstream", str(tmp_path / "up"), "--local", str(tmp_path / "local"),
                "--legacy", str(tmp_path / "legacy")])
    out = capsys.readouterr().out
    assert "中转目录" in out and "结果没人看" in out, "卡被递出去却没落库，这种形状必须出声"


# ------------------------------------------------------------------ 进程与代码版本
def _fake_ps(monkeypatch, text):
    """把 `ps` 的输出换成一段假文本——`run` 只要交出 .stdout 就够了。"""
    import types

    def run(*args, **kwargs):
        return types.SimpleNamespace(stdout=text)

    monkeypatch.setattr(drift.subprocess, "run", run)


def test_a_process_started_before_the_last_change_is_called_out(monkeypatch, tmp_path, capsys):
    """这轮最容易骗过判据的事：文件全对、测试全绿，进程还在跑昨天的 import 快照。"""
    _fake_ps(monkeypatch, "  PID     ELAPSED COMMAND\n95489  1-02:03:04 src/ui/run_server.py\n")
    monkeypatch.setattr(drift, "_latest_memory_source_mtime",
                        lambda: (time.time() + 3600, "src/memory/gateway.py"))
    proc = drift.running_app_versions()
    assert proc["found"] and proc["processes"][0]["pid"] == "95489"
    assert proc["processes"][0]["started"] < proc["newest_memory_mtime"], "该判它旧"


def test_a_restart_makes_the_warning_stop(monkeypatch):
    """重启之后这行就该安静——否则它会变成新的背景噪声。"""
    _fake_ps(monkeypatch, "  PID  ELAPSED COMMAND\n1  00:00:30 src/ui/run_server.py\n")
    monkeypatch.setattr(drift, "_latest_memory_source_mtime",
                        lambda: (time.time() - 86400, "src/memory/gateway.py"))
    proc = drift.running_app_versions()
    assert proc["processes"][0]["started"] > proc["newest_memory_mtime"]


def test_no_app_process_is_reported_as_stopped_not_as_error(monkeypatch):
    _fake_ps(monkeypatch, "  PID  ELAPSED COMMAND\n123  1:00:00  some/other/thing.py\n")
    proc = drift.running_app_versions()
    assert proc["found"] is False and "停" in proc["note"]


def test_an_unparseable_elapsed_time_says_unknown_rather_than_zero(monkeypatch):
    """etime 解析不了要留 -1 让调用方说"不知道"，不能当成"跑了 0 秒=刚重启"。"""
    _fake_ps(monkeypatch, "  PID  ELAPSED COMMAND\n9  ??? src/ui/run_server.py\n")
    assert drift._etime_seconds("???") == -1.0
    proc = drift.running_app_versions()
    assert proc["processes"][0]["elapsed_s"] == -1.0


# ------------------------------------------------------------------ 上游抽掉了多少
def _write_log(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    import datetime
    today = datetime.date.today().strftime("%Y-%m-%d")
    body = [f"{today} 10:00:0{ i} WARNING x.ingest: [1/1] chunk failed, will retry on next run: {why}"
            for i, why in enumerate(lines)]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def test_deterministic_failures_are_counted_instead_of_buried_in_a_log(tmp_path):
    """`will retry on next run` 这句话有两种含义，工具必须把它们分开：
    偶发的会自己补上，上下文超限的**永远不会**——而两边屏幕上都写着成功。"""
    log = _write_log(tmp_path / "store" / ".." / "app.log", [
        "Error code: 400 - ContextWindowExceededError: maximum context length is 131072",
        "Error code: 400 - some other bad request",
    ])
    got = drift.upstream_extract_failures(str(tmp_path / "store"))
    assert got["seen"] and got["today"] == 2
    assert got["context_window"] == 1 and got["other"] == 1


def test_a_missing_log_is_reported_as_unknown_not_as_zero(tmp_path):
    got = drift.upstream_extract_failures(str(tmp_path / "nowhere" / "store"))
    assert got["seen"] is False
    assert "不代表" in got["note"] or "未知" in got["note"], "拿不到日志只能报不知道"


def test_the_failure_line_shape_matches_the_real_log_format(tmp_path):
    """真实日志是 `日期 时间 LEVEL logger: [6/8] chunk failed...` 这个形状——
    正则要是只认我编的形状，真实文件里数出来永远是 0，那就白设了。"""
    app = tmp_path / "app.log"
    import datetime
    today = datetime.date.today().strftime("%Y-%m-%d")
    app.write_text(
        f"{today} 17:10:57,833 WARNING  memory_skill.llm_memoryd.ingest_mid.ingest:"
        f" [6/8] chunk failed, will retry on next run: Error code: 400 - {{'error': {{"
        "maximum context length is 131072 tokens",
        encoding="utf-8")
    got = drift.upstream_extract_failures(str(tmp_path / "memory"))
    assert got["seen"] and got["today"] == 1


def test_a_uvicorn_style_start_is_recognized_as_a_running_app(monkeypatch):
    """这栏曾经指着一句假话说"服务是停着的"：AR 也能用 `-m uvicorn
    src.ui.backend.app:app` 起，点号写法以前不在匹配范围里。
    明明在跑却报停，比什么都读不出来更坏——它会让人不去查那一侧。"""
    _fake_ps(monkeypatch,
             "  PID  ELAPSED COMMAND\n66362  00:05:00 /usr/bin/python -m uvicorn "
             "src.ui.backend.app:app --host 127.0.0.1 --port 8000\n")
    proc = drift.running_app_versions()
    assert proc["found"], "点号写法的 uvicorn 也是同一个服务，别当它不存在"
    assert proc["processes"][0]["pid"] == "66362"
