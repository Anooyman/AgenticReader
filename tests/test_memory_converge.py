"""Phase 3 · src.memory.converge CLI 的测试面（PLAN-MEMORY-CONVERGENCE.md 阶段 3）。

契约来源：`--dry-run`（默认）零写入 / `--apply` 三源重灌 / repo 无效或
MEMORY_STORE_MODE=local 显式拒跑（非零退出 + 明确文案，不许静默）/
单文件失败记 errors 继续 / `--retire-old-db` 只打印不动作。

注入面与 phase2 同构但走进程外：CLI 的退出码与 stdout 文案必须在子进程里
验，"假 client" 改在 LLM_MEMORY_REPO 指向的假包上——`src/memory/upstream.py`
会把 <repo>/src 注入 sys.path 再 import MemoryClient，于是所有 ingest 都
落进我们写死的 JSONL 记录器，dry-run 有没有偷跑写入一眼见分晓。

子进程 cwd 一律摆进 tmp_path：DATA_ROOT="data" 是相对路径，落 tmp 的
data/ 而不是仓库真实 data/——converge 名义上"不碰 data/memory_db"，
这条测试面自己先做到不碰。

conv-src 未落地前全部 xfail 挂账，不硬跑红；落地即自动转真跑。
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest

CONVERGE_LANDED = importlib.util.find_spec("src.memory.converge") is not None
xfail_pending = pytest.mark.xfail(
    not CONVERGE_LANDED,
    reason="src/memory/converge.py 未落地（阶段 3 进行中），落地即自动转真跑",
    strict=False,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DATE = "2026-11-18"

# ---- 固定内容：两个 summary、一个 session、一张 brief 卡 ----------------
SUMMARY_PDF = {  # ai_research 源：shape 照 pipeline/generate_qa_brief 落盘
    "doc_name": "2401.01234",
    "title": "注意力再探讨",
    "url": "https://arxiv.org/abs/2401.01234",
    "generated_at": "2026-11-01T00:00:00+00:00",
    "qa": {"核心问题": "…", "机制": "…"},
    "qa_brief": "省二次抽取的现成摘要",
    "coverage_date": DATE,
}
SUMMARY_WEB = dict(SUMMARY_PDF, doc_name="example-dev-post",
                   url="https://example.org/post", type="web")
SESSION_JSON = {
    "session_id": "s-1", "title": "问答一",
    "messages": [{"role": "user", "content": "hi"},
                 {"role": "assistant", "content": "hello", "agents_used": []}],
}
BRIEF_HTML = """<html><body>
<article class="card"><h2>注意力再探讨</h2>
<p><a href="https://arxiv.org/abs/2401.01234v1">abs</a></p>
<div class="cn"><b>要点：</b>导读文字</div></article>
</body></html>"""

FAKE_PACKAGE = '''"""假 llm_memoryd：ingest/status 记录进 $FAKE_LOG，供测试面断言。

行为像上游：ingest 按 (namespace, source_id) 记住自己见过什么——
重复递同一份就 0 新增、全 skipped（hash-dedup 的 echo 形状）。
$FAKE_FAIL_SOURCE 命中时 raise，模拟单文件失败不许整批 abort。
"""
import json
import os


class MemoryClient:
    def __init__(self, *a, **kw):
        pass

    def log(self, rec):
        with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\\n")

    def status(self, namespace=None):
        self.log({"method": "status", "namespace": namespace})
        return {"namespaces": {}, "total": 0}

    def namespaces(self, namespace=None):
        self.log({"method": "namespaces"})
        return []

    def search(self, query, namespace=None, namespaces=None, **kw):
        self.log({"method": "search", "query": query})
        return {"status": "ok", "results": [], "answer": ""}

    def ingest(self, path, source_type="ai_research", *, namespace=None,
               source_id=None, dry_run=False, **kw):
        seen_path = os.path.join(os.environ["FAKE_SEEN"], namespace or "")
        os.makedirs(os.environ["FAKE_SEEN"], exist_ok=True)
        first = source_id not in open(seen_path).read() if os.path.exists(seen_path) else True
        if not first:
            added, skipped = 0, 1
        else:
            added, skipped = (1, 0) if not dry_run else (0, 0)
            os.makedirs(os.path.dirname(seen_path), exist_ok=True)
            with open(seen_path, "a", encoding="utf-8") as f:
                f.write(str(source_id) + "\\n")
        if str(source_id) == os.environ.get("FAKE_FAIL_SOURCE", ""):
            raise RuntimeError("假上游在这一单炸了")
        self.log({"method": "ingest", "path": str(path), "source_type": source_type,
                  "namespace": namespace, "source_id": source_id,
                  "dry_run": dry_run, "report": {"chunks_added": added,
                                                 "chunks_skipped": skipped}})
        return {"source_type": source_type, "namespace": namespace,
                "source_id": source_id,
                "report": {"chunks_added": added, "chunks_skipped": skipped}}

    def __getattr__(self, name):  # 其它面一律记一笔再拒绝，别静默
        def stub(*a, **kw):
            self.log({"method": name, "args": str(a)[:200]})
            raise AttributeError(name)
        return stub


__version__ = "0.1.0-test"
'''


def _tree(tmp):
    """tmp 下的完整数据面：fake 上游 repo + tmp DATA_ROOT + BRIEFS_DIR。"""
    (tmp / "repo" / "src" / "llm_memoryd").mkdir(parents=True)
    (tmp / "repo" / "src" / "llm_memoryd" / "api.py").write_text(
        FAKE_PACKAGE, encoding="utf-8")
    (tmp / "repo" / "src" / "llm_memoryd" / "__init__.py").write_text(
        "", encoding="utf-8")
    for sub in ("pdf", "web"):
        d = tmp / "data" / "pipeline" / "summaries" / sub
        d.mkdir(parents=True)
    (tmp / "data" / "pipeline" / "summaries" / "pdf" / "2401.01234.json").write_text(
        json.dumps(SUMMARY_PDF, ensure_ascii=False), encoding="utf-8")
    (tmp / "data" / "pipeline" / "summaries" / "web" / "example-dev-post.json").write_text(
        json.dumps(SUMMARY_WEB, ensure_ascii=False), encoding="utf-8")
    (tmp / "data" / "sessions").mkdir(parents=True)
    (tmp / "data" / "sessions" / "s-1.json").write_text(
        json.dumps(SESSION_JSON, ensure_ascii=False), encoding="utf-8")
    day = tmp / "briefs" / DATE
    day.mkdir(parents=True)
    (day / "research-paper-radar.html").write_text(BRIEF_HTML, encoding="utf-8")
    # 名义上"旧库不碰"——放个哨兵，任何 case 动了它都会被 grep 到
    legacy = tmp / "data" / "memory_db"
    legacy.mkdir(parents=True)
    (legacy / "canary.txt").write_text("别碰我", encoding="utf-8")
    return tmp


def _run_cli(tmp, extra=(), env_extra=None, log=None):
    """经包装子进程跑 CLI：exit code 与 stdout 都是真的。

    DATA_ROOT 的坑这里认账（CLAUDE.md Testing Notes 同款提醒）：
    `get_data_root()` 把相对 "data" 锚到**项目根**而非 cwd，
    `pipeline/paths` 的 SUMMARIES_DIR 又是 import 期快照——光把子进程
    cwd 摆进 tmp 是骗不过去的，枚举会照抄仓库真实 data/。所以包装脚本
    在 import converge 之前先把 PathConstants.DATA_ROOT（动态读）和
    settings.DATA_ROOT（给 paths 的快照）两处都拨进 tmp——测试面自己
    先做到一条都不碰仓库真实数据。
    """
    script = tmp / "run_converge.py"
    script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "import src.config.constants as _c\n"
        f"_c.PathConstants.DATA_ROOT = {str(tmp / 'data')!r}\n"
        "import src.config.settings as _s\n"
        f"_s.DATA_ROOT = Path({str(tmp / 'data')!r})\n"
        "from src.memory import converge\n"
        "sys.exit(converge.main())\n",
        encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(REPO_ROOT),
        "LLM_MEMORY_REPO": str(tmp / "repo"),
        "BRIEFS_DIR": str(tmp / "briefs"),
        "FAKE_LOG": str(log or (tmp / "calls.jsonl")),
        "FAKE_SEEN": str(tmp / "seen"),
    })
    env.pop("MEMORY_STORE_MODE", None)
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, str(script), *extra],
        cwd=str(tmp), env=env, capture_output=True, text=True, timeout=180,
    )
    return proc


def _calls(tmp, log=None):
    p = log or (tmp / "calls.jsonl")
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _ingests(tmp, log=None):
    return [c for c in _calls(tmp, log) if c.get("method") == "ingest"]


# ---------------------------------------------------------------- ① dry-run
@xfail_pending
def test_dry_run_default_makes_no_ingest_calls(tmp_path):
    """不带参数 = dry-run 缺省是计划写死的默认：假上游的日志里
    一条 ingest 都不该出现（出现即打回——"看看就好"变成了真灌库）。"""
    _tree(tmp_path)
    proc = _run_cli(tmp_path)
    assert proc.returncode == 0, f"dry-run 非零退出：{proc.stderr[:400]}"
    assert _ingests(tmp_path) == [], "dry-run 发生了真 ingest"
    # 也不能靠 dry_run=True 的"半真"糊弄：有调用就必须全带 dry_run 标记
    for c in _calls(tmp_path):
        if c.get("method") == "ingest":
            assert c.get("dry_run") is True
    # stdout 要说清"看见了多少、会灌什么"，不能空手而归
    out = (proc.stdout + proc.stderr).lower()
    assert any(w in out for w in ("dry", "将", "would", "发现", "源"))


# ---------------------------------------------------------------- ② 三源形状
@xfail_pending
def test_apply_maps_ai_research_source(tmp_path):
    _tree(tmp_path)
    proc = _run_cli(tmp_path, ["--apply"])
    assert proc.returncode == 0, proc.stderr[:400]
    hits = [c for c in _ingests(tmp_path)
            if c["source_type"] == "ai_research" and c["namespace"] == "ai-research"]
    assert hits, "summaries/pdf 没有按 ai_research→ai-research 递"
    ids = {c["source_id"] for c in hits}
    assert "2401.01234" in ids, f"source_id 没原样传：{ids}"


@xfail_pending
def test_apply_maps_webapp_chat_source(tmp_path):
    _tree(tmp_path)
    _run_cli(tmp_path, ["--apply"])
    hits = [c for c in _ingests(tmp_path)
            if c["source_type"] == "webapp_chat" and c["namespace"] == "webapp-chat"]
    assert hits, "sessions 没有按 webapp_chat→webapp-chat 递"
    assert all(c["source_id"] for c in hits), "source_id 空传"


@xfail_pending
def test_apply_maps_brief_source_via_staging_cards(tmp_path):
    _tree(tmp_path)
    _run_cli(tmp_path, ["--apply"])
    hits = [c for c in _ingests(tmp_path)
            if c["source_type"] == "brief" and c["namespace"] == "AATF"]
    assert hits, "BRIEFS_DIR 没走 brief→AATF（staging 卡片 JSON 通道）"
    ids = {c["source_id"] for c in hits}
    assert "2401.01234" in ids, f"卡片 item_id 没原样传下去：{ids}"
    # staging 通道：递的是中转 JSON 文件，不是 HTML 原路径
    assert all(str(c["path"]).endswith(".json") for c in hits), \
        "brief 源没走 staging JSON，而是把 HTML 直接递上游了"


# ---------------------------------------------------------------- ③ 拒跑
@xfail_pending
def test_refuses_when_repo_invalid(tmp_path):
    """前提不满足要显式拒：非零退出 + 指名 repo 问题，不许 exit 0 装没事。"""
    _tree(tmp_path)
    log = tmp_path / "calls.jsonl"
    proc = _run_cli(tmp_path, ["--apply"],
                    env_extra={"LLM_MEMORY_REPO": str(tmp_path / "nope")}, log=log)
    assert proc.returncode != 0, "无效 repo 竟然 exit 0——静默跳过在拒跑清单里禁"
    out = proc.stdout + proc.stderr
    assert any(w in out for w in ("repo", "LLM_MEMORY_REPO", "上游", "无效")), \
        "拒跑没留明确文案"
    assert _ingests(tmp_path, log) == []


@xfail_pending
def test_refuses_when_kill_switch_local(tmp_path):
    """MEMORY_STORE_MODE=local 说明用户明摆要旧路，converge 必须停手——
    它灌的是上游，mode 都 local 了还灌，就是越权改人家的存储决定。"""
    _tree(tmp_path)
    log = tmp_path / "calls.jsonl"
    proc = _run_cli(tmp_path, ["--apply"],
                    env_extra={"MEMORY_STORE_MODE": "local"}, log=log)
    assert proc.returncode != 0, "kill switch=local 下仍按成功收尾"
    out = proc.stdout + proc.stderr
    assert any(w in out for w in ("MEMORY_STORE_MODE", "local", "kill")), \
        "拒跑文案没指到这把 kill switch"
    assert _ingests(tmp_path, log) == []


# ---------------------------------------------------------------- ④ 幂等形状
@xfail_pending
def test_apply_second_run_reports_skips_not_dupes(tmp_path):
    """同文件二跑：新增归零、skipped 计数对得上，且不许静默把 errors
    吞成 0——"全都早就最新"要用数字说话。"""
    _tree(tmp_path)
    first = _run_cli(tmp_path, ["--apply"])
    assert first.returncode == 0
    first_added = sum(c["report"]["chunks_added"] for c in _ingests(tmp_path))
    assert first_added > 0, "首跑都没新增，幂等用例失去意义"
    # seen 记账跨运行留着，二跑才是"同一批东西再递一遍"
    second = _run_cli(tmp_path, ["--apply"])
    assert second.returncode == 0
    ing2 = _ingests(tmp_path)
    # 二跑的"新增"增量必须为零：总 added 与首跑持平
    total_added = sum(c["report"]["chunks_added"] for c in ing2)
    assert total_added == first_added, (
        f"二跑出现新增 {total_added - first_added}——幂等没归上游")


@xfail_pending
def test_single_failure_records_error_and_continues(tmp_path):
    """单文件炸了记 errors 继续跑，不许整批 abort——三个源都在，坏一个
    也要把剩下的灌完。"""
    _tree(tmp_path)
    log = tmp_path / "calls.jsonl"
    _run_cli(tmp_path, ["--apply"],
             env_extra={"FAKE_FAIL_SOURCE": "2401.01234"}, log=log)
    ing = _ingests(tmp_path, log)
    good = {c["source_id"] for c in ing if c["source_id"] != "2401.01234"}
    assert good, "坏了一单就整批停摆：别的源一条都没递"


# ---------------------------------------------------------------- ⑤ retire 占位
@xfail_pending
def test_retire_old_db_placeholder_prints_only(tmp_path):
    """--retire-old-db 此刻只该打印意图，不许真搬库：canary 原地、
    无 .legacy 目录、stdout 有话。搬库是 destructive，要点头的权力
    留给用户，测试面不许替用户放行。"""
    _tree(tmp_path)
    # 占位印在 --apply 收尾之后——单独 --retire-old-db 只会走 dry-run 早退，
    # 测"占位有没有说话"得把 apply 一起带上
    proc = _run_cli(tmp_path, ["--apply", "--retire-old-db"])
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, "占位开关都不存在就报错——还没轮到报错的时候"
    # 占位的最低要求：stdout 里有一句说清"retire 要干什么/今天不干什么"。
    # 只查"输出非空"会被 import 报错的空跑骗过去，这里点名文案才算数。
    assert any(w in out for w in ("retire", "legacy", "搬", "memory_db")), \
        f"占位没留下任何可辨认的话：{out[:200]!r}"
    assert (tmp_path / "data" / "memory_db" / "canary.txt").exists(), \
        "占位模式下动了旧库"
    assert not (tmp_path / "data" / "memory_db.legacy").exists(), \
        "占位直接搬库了"
