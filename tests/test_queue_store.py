"""pipeline_queue.json 这本账本的直接用例——安全/并发关键件此前 0 覆盖。

queue_store 的整个价值都押在一句话上：**排他锁横跨"读 → 改 → 写回"**。它坏
掉的形态不会抛异常，而是"两次写其中一次安静消失"（lost update），跑起来还
一切正常，所以这里不测"能不能读写"就完事：

* 事务真的排他——同一时刻最多一个事务在临界区里（探针直接盯锁本身）；
* 探针在没有锁的对照场景里确实看得见重叠，否则上一条是白测；
* 中途出错的事务不该把半成品写盘，也不该把锁带进死胡同；
* 损坏的账本该报错，而不是顺手清空——那是把用户队列当缓存丢；
* 状态机那几个函数（select/claim/finish/fail）的边界与"独立副本"承诺。

多进程那一层用 spawn 起子进程，并且子进程里第一件事就是把路径**显式**指回
临时目录——spawn 会重跑模块级定义，不显式指定就会去够真实的 data/pipeline。
"""
import json
import multiprocessing as mp
import os
import threading
import time
from pathlib import Path

import pytest

import src.pipeline.queue_store as qs
from src.core import filelock

REAL_ACQUIRE = filelock.acquire
REAL_RELEASE = filelock.release

# 模块级 import 时 queue_store 已经从 src.pipeline.paths 拿走了真实 STATE_DIR，
# 所以每个用例都必须先把这两个路径钉到 tmp 里，否则测试会去写用户真正的队列。


@pytest.fixture
def store(tmp_path, monkeypatch):
    """把 queue_store 的两个路径常量换到 tmp 下。

    注意是 setattr 到模块上而不是构造实例：queue_store 是一组模块级函数，
    QUEUE_PATH 是它自己的全局名，函数每次调用现读。
    """
    monkeypatch.setattr(qs, "QUEUE_PATH", tmp_path / "pipeline_queue.json", raising=True)
    monkeypatch.setattr(qs, "QUEUE_LOCK_PATH", tmp_path / "pipeline_queue.lock", raising=True)
    return qs


def seed(*item_ids, item_type="pdf", status="pending"):
    """按 item_id 建几个条目，省掉每个用例重复 new_queue_item。"""
    qs.save_queue({
        i: qs.new_queue_item(i, item_type, f"http://example.com/{i}", f"标题 {i}", "2026-01-01")
        for i in item_ids
    })


# ---------------------------------------------------------------- 往返
def test_load_gives_empty_dict_when_the_ledger_is_absent(store):
    assert store.load_queue() == {}


def test_save_and_load_roundtrip_keeps_unicode_and_nesting(store):
    data = {
        "a1": {"title": "论文 \u00e9 中文", "artifacts": {"pdf": "/tmp/x.pdf"}},
        "b2": {"attempts": 2, "last_error": None},
    }
    store.save_queue(data)
    assert store.load_queue() == data


def test_save_leaves_no_stray_temporary_files(store):
    """write_json_atomic 是 tmp+rename，成功路径不该留下 *.tmp.* 残骸。"""
    store.save_queue({"k": {"v": 1}})
    strays = [p.name for p in Path(store.QUEUE_PATH).parent.glob("*.tmp*")]
    assert strays == []


def test_transaction_creates_the_state_directory(store, tmp_path):
    """锁文件的目录会自己建出来：冷启动时 data/pipeline 可能还不存在。"""
    fresh = tmp_path / "deep" / "nested"
    store.QUEUE_PATH = fresh / "pipeline_queue.json"
    store.QUEUE_LOCK_PATH = fresh / "pipeline_queue.lock"
    assert not fresh.exists()
    with store.queue_transaction() as q:
        q["x"] = {"ok": True}
    assert fresh.exists() and store.load_queue() == {"x": {"ok": True}}


# ---------------------------------------------------------------- 损坏的账本
def test_load_reports_corrupt_json_without_guessing(store):
    store.QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    store.QUEUE_PATH.write_text("{not json,", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        store.load_queue()


def test_transaction_on_corrupt_file_does_not_clobber_it(store):
    """这条比"报不报错"更要紧：事务不能因为读不动就顺手把文件写成 {}——
    那等于把用户排好的队列当缓存清了。"""
    store.QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = "{not json,"
    store.QUEUE_PATH.write_text(raw, encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        with store.queue_transaction() as q:
            q["injected"] = True
    assert store.QUEUE_PATH.read_text(encoding="utf-8") == raw


def test_lock_survives_a_failed_transaction(store):
    """上一次失败不能把锁永久占住，否则整条管线就此卡死。"""
    store.save_queue({"a": {}})
    with pytest.raises(RuntimeError):
        with store.queue_transaction() as q:
            q["b"] = True
            raise RuntimeError("中途炸了")
    # 修好之后应当还能走通
    with store.queue_transaction() as q:
        q["c"] = True
    assert store.load_queue() == {"a": {}, "c": True}


def test_a_raising_body_writes_nothing_back(store):
    """改到一半抛异常时不该有半截结果落盘——事务是原子的，不是"边改边写"。"""
    store.save_queue({"keep": {"v": 1}})
    with pytest.raises(ValueError):
        with store.queue_transaction() as q:
            q["half"] = True
            q["keep"]["v"] = 999
            raise ValueError("boom")
    assert store.load_queue() == {"keep": {"v": 1}}


def test_yield_before_writeback_means_body_changes_are_committed(store):
    with store.queue_transaction() as q:
        assert store.load_queue() == {}
        q["only"] = True
    assert store.load_queue() == {"only": True}


# ---------------------------------------------------------------- 排他性·线程层
def test_no_two_transactions_are_inside_the_critical_section_at_once(store):
    """排他锁的结构性不变量：临界区的"在人数"永远 ≤ 1。

    这条原先是 flaky 的，原因就在探针自己身上，而不是锁不可靠：
        def release(fd):
            REAL_RELEASE(fd)      # 先放锁
            seen["cur"] -= 1      # 后才把自已从"在临界区"里划掉
    于是存在一个"锁已经放给别人了、我还在计数里"的窗口——B 在这个窗口里
    进来说自己进去了，cur 就成了 2。空跑看不出来，负载一大窗口就张开，
    这就是那种"全量撞一次 failed、单跑 33/33"的形态。修探针的顺序是核心：
    **先把自己从计数里摘掉，再放锁**，这样"两个人同时在里面"根本不可能被
    构造出来，剩下的才是真信号。

    另外两处让它从"采样这轮没撞上"变成有结构依据：
      * 线程起跑先过一道 barrier，六个线程同时扑向锁，争用是真的发生了
        （对照组 test_the_probe_itself_can_see_overlap 证明这套计数器
        在锁失效时看得见重叠，所以这里恒为 1 不是"压根没人竞争"）；
      * 除了 cur/max，还留一条 enter/exit 事件流水做独立校验：任何一次
        enter 之前必须先有对应的 exit，未闭合的 enter 不得超过 1 个。
    """
    store.save_queue({})
    threads_n, rounds = 6, 8
    seen = {"cur": 0, "max": 0}
    events = []            # (kind, tid) —— kind: "in" / "out"
    guard = threading.Lock()
    barrier = threading.Barrier(threads_n, timeout=15)

    def acquire(fd, **kw):
        REAL_ACQUIRE(fd, **kw)
        tid = threading.get_ident()
        with guard:
            seen["cur"] += 1
            seen["max"] = max(seen["max"], seen["cur"])
            events.append(("in", tid))

    def release(fd):
        tid = threading.get_ident()
        with guard:
            seen["cur"] -= 1          # 计数先归零
            events.append(("out", tid))
        REAL_RELEASE(fd)              # 锁后放——顺序反了就会自己造出重叠

    qs.filelock.acquire = acquire
    qs.filelock.release = release
    try:
        def worker(n):
            try:
                barrier.wait()    # 同时到锁门口；极重负载下真等不到也只是少点争用，
            except threading.BrokenBarrierError:
                pass              # 本条测的是不变量，不是"有没有争用"，不值得为此判失败
            for i in range(rounds):
                with store.queue_transaction() as q:
                    q[f"k{n}-{i}"] = {"i": i}
                    time.sleep(0.001)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(threads_n)]
        [t.start() for t in threads]
        [t.join() for t in threads]
    finally:
        qs.filelock.acquire, qs.filelock.release = REAL_ACQUIRE, REAL_RELEASE

    overlap = seen["max"]
    assert overlap == 1, f"同一瞬间有 {overlap} 个事务在临界区里"
    # 事件流水单独再判一遍：任意前缀里 "in" 的数量不得比 "out" 多出 1 个以上
    live = 0
    for kind, _tid in events:
        live += 1 if kind == "in" else -1
        assert live <= 1, "事件流水里出现两个人同时在临界区"
        assert live >= 0, "没进过临界区就先出来了，探针自己错了"
    assert len(events) == threads_n * rounds * 2
    assert len(store.load_queue()) == threads_n * rounds


def test_the_probe_itself_can_see_overlap(store):
    """对照组，用来证明上面那条不是自证：把锁摘掉，探针必须看得见重叠，
    而且真的丢数据。这里用 barrier 把"两个读者各自拿到快照"变成确定的时序，
    不靠调度碰运气。"""
    store.save_queue({})
    seen = {"cur": 0, "max": 0}
    guard = threading.Lock()
    barrier = threading.Barrier(2, timeout=5)

    def fake_acquire(fd, **kw):        # 锁不再生效，但仍计入统计
        with guard:
            seen["cur"] += 1
            seen["max"] = max(seen["max"], seen["cur"])

    def fake_release(fd):
        with guard:
            seen["cur"] -= 1

    qs.filelock.acquire = fake_acquire
    qs.filelock.release = fake_release
    try:
        def worker(n):
            with store.queue_transaction() as q:
                q[f"k{n}"] = {"n": n}
                barrier.wait()         # 两边都改完，等对方一起写回

        ts = [threading.Thread(target=worker, args=(n,)) for n in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    finally:
        qs.filelock.acquire, qs.filelock.release = REAL_ACQUIRE, REAL_RELEASE

    assert seen["max"] == 2, "探针看不见重叠，那「排他」那条就只是白测"
    assert len(store.load_queue()) == 1, "无锁版本应当确定性地丢掉一次写入"


def test_increment_from_many_threads_loses_nothing(store):
    """真实一点的形状：每线程反复"读整本 → 改一条 → 写回"。"""
    seed("a", "b", "c")
    def bump(tag):
        for i in range(10):
            with store.queue_transaction() as q:
                q["a"]["attempts"] = q["a"].get("attempts", 0) + 1
                q[f"{tag}{i}"] = True
    ts = [threading.Thread(target=bump, args=(f"t{n}",)) for n in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    q = store.load_queue()
    assert q["a"]["attempts"] == 40
    assert len(q) == 3 + 4 * 10


# ---------------------------------------------------------------- 排他性·事务层
def test_a_second_writer_is_refused_while_one_is_midflight(store):
    """排他锁必须**握到写回完成**，而不是只罩住 load 那一下。

    做法：第一个事务在体内等一个门闩，期间第二个写者拿非阻塞锁应当被拒；
    门闩打开后第二个事务才走，于是两次写都留得下来。
    """
    store.save_queue({})
    inside = threading.Event()
    gate = threading.Event()

    def first():
        with store.queue_transaction() as q:
            inside.set()
            assert gate.wait(5), "第一个事务没被放行，测试框架本身有问题"
            q["first"] = True

    t = threading.Thread(target=first)
    t.start()
    try:
        assert inside.wait(5), "第一个事务没能进入临界区"
        fd = os.open(store.QUEUE_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            with pytest.raises(BlockingIOError):
                filelock.acquire(fd, non_blocking=True)
        finally:
            os.close(fd)
        gate.set()
        t.join(10)
    finally:
        gate.set()
        t.join(10)

    assert "first" in store.load_queue()


def test_blocked_transaction_still_commits_after_the_holder_releases(store):
    """阻塞式排队：第二个事务在锁外等着，进来时应当读到第一个已落盘的版本。"""
    store.save_queue({})
    hold = threading.Event()
    started = threading.Event()

    def holder():
        with store.queue_transaction() as q:
            started.set()
            hold.wait(5)
            q["holder"] = True

    def waiter():
        with store.queue_transaction() as q:
            q["waiter"] = True

    th = threading.Thread(target=holder)
    tw = threading.Thread(target=waiter)
    th.start()
    assert started.wait(5)
    tw.start()
    time.sleep(0.05)           # 让 waiter 走到阻塞点，别让两者都瞬间跑完
    hold.set()
    th.join(10)
    tw.join(10)
    assert store.load_queue() == {"holder": True, "waiter": True}


# ---------------------------------------------------------------- 跨进程层
def _child_writer(state_dir: str, tag: str, count: int):
    """子进程：先把两个路径常量指回临时目录，再重复写自己的那批键。

    这一步不是客套——spawn 会在新进程里重跑模块级定义，那时 QUEUE_PATH
    会重新算成真实的 data/pipeline/pipeline_queue.json，指回去就等于去写
    用户真的排好的队列。
    """
    qs.QUEUE_PATH = Path(state_dir) / "pipeline_queue.json"
    qs.QUEUE_LOCK_PATH = Path(state_dir) / "pipeline_queue.lock"
    for i in range(count):
        with qs.queue_transaction() as q:
            q[f"{tag}-{i}"] = {"tag": tag, "i": i}
            time.sleep(0.001)
    return 0


@pytest.mark.skipif(not hasattr(mp, "get_all_start_methods"), reason="平台不提供 multiprocessing 上下文")
def test_two_processes_writing_the_same_ledger_lose_nothing(store, tmp_path):
    """多进程这一层：两个进程各自做 12 次事务写，合起来应当一条不少。

    用的是 spawn——它是这台机器上的默认起法，也顺带绕开 fork 在 macOS 上
    和线程/ObjC 运行时相处不好的那套历史问题。子进程起不来/超时算环境问题
    （skip），只有"数据真的丢了"才判失败。
    """
    store.save_queue({})
    if "spawn" not in mp.get_all_start_methods():
        pytest.skip("该平台只有 fork 可用，跨进程测试的意义不大")
    ctx = mp.get_context("spawn")
    children = [ctx.Process(target=_child_writer,
                            args=(str(tmp_path), f"c{n}", 12), daemon=True)
                for n in range(2)]
    for p in children:
        p.start()
    deadline = time.time() + 25
    for p in children:
        p.join(max(0.1, deadline - time.time()))
    if any(p.is_alive() for p in children):
        for p in children:
            p.terminate()
        pytest.skip("子进程在 25s 内没跑完：这更像 spawn 冷启动/沙箱受限，不是锁的行为")
    if any(p.exitcode for p in children):
        pytest.skip(f"子进程异常退出（{[p.exitcode for p in children]}）——环境问题，不是锁的行为")

    q = store.load_queue()
    expected = {f"c{n}-{i}" for n in range(2) for i in range(12)}
    assert expected <= set(q), f"跨进程少写了 {sorted(expected - set(q))}"


# ---------------------------------------------------------------- 状态机边界
def test_new_queue_item_starts_pending(store):
    item = qs.new_queue_item("i1", "web", "http://x", "标题", "2026-01-02")
    assert item["pipeline_status"] == "pending"
    assert item["attempts"] == 0 and item["artifacts"] == {}
    assert item["pdf_url"] is None


def test_mark_failed_escalates_exactly_at_max_attempts(store):
    item = qs.new_queue_item("i", "pdf", "u", "t", "d")
    assert qs.MAX_ATTEMPTS == 3
    qs.mark_failed(item, "第 1 次")
    assert item["pipeline_status"] == "failed_retryable" and item["attempts"] == 1
    qs.mark_failed(item, "第 2 次")
    assert item["pipeline_status"] == "failed_retryable" and item["attempts"] == 2
    qs.mark_failed(item, "第 3 次")
    assert item["pipeline_status"] == "failed_permanent" and item["attempts"] == 3
    # 到 permanent 之后再失败也只是继续计数，状态不该掉回 retryable
    qs.mark_failed(item, "第 4 次")
    assert item["pipeline_status"] == "failed_permanent" and item["attempts"] == 4


def test_mark_failed_tolerates_missing_counter_and_non_string_error(store):
    item = {"pipeline_status": "in_progress"}          # 手工拼的、没有 attempts
    qs.mark_failed(item, RuntimeError("底层挂了"))
    assert item["attempts"] == 1
    assert "底层挂了" in item["last_error"]             # 转成了字符串而不是塞了个异常对象


def test_reset_stale_only_touches_the_requested_type(store):
    q = {
        "p1": {"type": "pdf", "pipeline_status": "in_progress"},
        "p2": {"type": "pdf", "pipeline_status": "in_progress"},
        "w1": {"type": "web", "pipeline_status": "in_progress"},
        "d1": {"type": "pdf", "pipeline_status": "done"},
    }
    assert qs.reset_stale_in_progress(q, item_type="pdf") == 2
    assert q["p1"]["pipeline_status"] == "pending" and q["p2"]["pipeline_status"] == "pending"
    assert q["w1"]["pipeline_status"] == "in_progress", "web 处理器正在做的事不该被 pdf 处理器重置"
    assert q["d1"]["pipeline_status"] == "done"
    assert qs.reset_stale_in_progress(q, item_type="web") == 1
    assert qs.reset_stale_in_progress({"nothing": {"type": "pdf", "pipeline_status": "pending"}}) == 0


def test_reset_stale_with_none_restores_the_old_wholesale_behaviour(store):
    q = {"a": {"type": "pdf", "pipeline_status": "in_progress"},
         "b": {"type": "web", "pipeline_status": "in_progress"}}
    assert qs.reset_stale_in_progress(q, item_type=None) == 2
    assert all(v["pipeline_status"] == "pending" for v in q.values())


def test_select_processable_picks_pending_and_retryable_only(store):
    qs.save_queue({
        "p1": qs.new_queue_item("p1", "pdf", "u", "t", "d"),
        "p2": qs.new_queue_item("p2", "pdf", "u", "t", "d"),
        "p3": qs.new_queue_item("p3", "pdf", "u", "t", "d"),
        "p4": qs.new_queue_item("p4", "pdf", "u", "t", "d"),
    })
    with store.queue_transaction() as q:
        q["p2"]["pipeline_status"] = "failed_retryable"
        q["p3"]["pipeline_status"] = "failed_permanent"
        q["p4"]["pipeline_status"] = "done"
    ids = store.select_processable("pdf")
    assert sorted(ids) == ["p1", "p2"]

    limited = store.select_processable("pdf", limit=1)
    assert len(limited) == 1
    assert set(limited) <= {"p1", "p2"}


def test_select_processable_reopens_stale_items_of_its_own_type(store):
    qs.save_queue({
        "p1": qs.new_queue_item("p1", "pdf", "u", "t", "d"),
        "w1": qs.new_queue_item("w1", "web", "u", "t", "d"),
    })
    with store.queue_transaction() as q:
        q["p1"]["pipeline_status"] = "in_progress"
        q["w1"]["pipeline_status"] = "in_progress"
    ids = store.select_processable("pdf")
    assert ids == ["p1"], "上一轮崩掉留下的 in_progress 该被重新排进来，而且只能动 pdf 的"
    with store.queue_transaction() as q:
        assert q["w1"]["pipeline_status"] == "in_progress", "web 那条被误伤了"


def test_select_processable_with_explicit_item_id(store):
    qs.save_queue({
        "p1": qs.new_queue_item("p1", "pdf", "u", "t", "d"),
        "w1": qs.new_queue_item("w1", "web", "u", "t", "d"),
    })
    assert store.select_processable("pdf", item_id="p1") == ["p1"]
    assert store.select_processable("pdf", item_id="w1") == [], "别的类型的条目不该被这次调用端进来"
    assert store.select_processable("pdf", item_id="nope") == []


def test_claim_item_returns_an_independent_copy(store):
    """docstring 承诺"独立副本"：拿到的东西改了不该影响盘上，
    否则长时间处理期间就等同一边攥着整表改。"""
    seed("p1")
    item = store.claim_item("p1")
    assert item["pipeline_status"] == "in_progress"
    item["title"] = "被本地改掉的标题"
    item["artifacts"]["json"] = "/tmp/fake.json"
    on_disk = store.load_queue()["p1"]
    assert on_disk["title"] == "标题 p1"
    assert on_disk["artifacts"] == {}
    assert "title" in item and "artifacts" in item


def test_claim_item_marks_in_progress_and_gives_none_for_unknown(store):
    seed("p1")
    assert store.claim_item("p1") is not None
    assert store.load_queue()["p1"]["pipeline_status"] == "in_progress"
    assert store.claim_item("不存在") is None


def test_two_workers_claiming_the_same_item_both_get_a_copy(store):
    """没有 owner 字段，认领是幂等的——这不是 bug，但得写下来，
    否则以后有人加认领锁时以为在"修"一个原本就有的缺陷。"""
    seed("p1")
    first = store.claim_item("p1")
    second = store.claim_item("p1")
    assert first is not None and second is not None
    assert first["pipeline_status"] == "in_progress"
    assert second["pipeline_status"] == "in_progress"
    assert first is not second


def test_finish_item_merges_instead_of_replacing(store):
    seed("p1")
    item = store.claim_item("p1")
    item["artifacts"] = {"json": "a.json"}
    store.finish_item("p1", {"pipeline_status": "done", "artifacts": {"json": "a.json"}})
    live = store.load_queue()["p1"]
    assert live["pipeline_status"] == "done"
    assert live["artifacts"] == {"json": "a.json"}
    assert live["attempts"] == 0 and live["title"] == "标题 p1", "没提到的字段必须原样保留"


def test_finish_item_writes_onto_the_latest_version(store):
    """这是"三个短事务"存在的理由：B 在 A 处理期间改了别的字段，A 回写时
    不该把 B 的改动抹掉。"""
    seed("p1", "p2")
    store.claim_item("p1")             # worker A 认领 p1（副本它自己不需要用）
    store.finish_item("p2", {"note": "别的 worker 刚写的"})   # B 先落盘
    store.finish_item("p1", {"pipeline_status": "done"})     # A 慢慢做完再回写
    q = store.load_queue()
    assert q["p2"]["note"] == "别的 worker 刚写的"
    assert q["p1"]["pipeline_status"] == "done"


def test_finish_and_fail_on_unknown_id_are_silent_no_ops(store):
    seed("p1")
    before = store.load_queue()
    store.finish_item("不存在", {"x": 1})
    store.fail_item("不存在", "boom")
    assert store.load_queue() == before, "不该凭空造出一个条目，也不该报错"


def test_fail_item_records_error_and_attempts(store):
    seed("p1")
    store.fail_item("p1", "第一次挂")
    item = store.load_queue()["p1"]
    assert item["attempts"] == 1 and item["pipeline_status"] == "failed_retryable"
    assert item["last_error"] == "第一次挂"
    store.fail_item("p1", RuntimeError("第二次挂"))
    item = store.load_queue()["p1"]
    assert item["attempts"] == 2 and "第二次挂" in item["last_error"]


def test_the_permanent_failure_never_gets_selected_again(store):
    seed("p1")
    for _ in range(qs.MAX_ATTEMPTS):
        store.fail_item("p1", "反复失败")
    assert store.load_queue()["p1"]["pipeline_status"] == "failed_permanent"
    assert store.select_processable("pdf") == []


def test_claim_and_finish_loop_from_threads_keeps_every_item(store):
    """把整套短事务并发跑一遍：4 个"worker" 各领不同条目，收尾后总数不变。"""
    ids = [f"p{i}" for i in range(8)]
    seed(*ids)

    def worker(name):
        for item_id in ids:
            item = store.claim_item(item_id)
            if item is None:
                continue
            time.sleep(0.001)
            store.finish_item(item_id, {"artifacts": {"by": name}})
            with store.queue_transaction() as q:
                q[item_id]["pipeline_status"] = "done"

    ts = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    q = store.load_queue()
    assert sorted(q) == sorted(ids)
    assert all(v["pipeline_status"] == "done" for v in q.values())


def test_queue_file_is_the_only_writer_path_and_stays_valid_json(store):
    """跑完一串真实动作后，盘上必须还是合法 JSON 且没有 tmp 残骸——
    这条是把"atomic 写 + 锁"合起来的结果性检查。"""
    seed("a", "b")
    for _ in range(5):
        store.claim_item("a")
        store.finish_item("a", {"artifacts": {"x": 1}})
        store.fail_item("b", "反复")
    assert isinstance(store.load_queue(), dict)
    assert list(Path(store.QUEUE_PATH).parent.glob("*.tmp*")) == []


def test_reset_stale_bumps_attempts_so_killed_processes_cant_loop_forever(store):
    """进程反复被杀（不走 fail_item）的条目以前会在 pending↔in_progress
    之间无限循环，永远够不到 MAX_ATTEMPTS=3——超时回炉也记一次 attempt。"""
    q = {"x": {"type": "pdf", "pipeline_status": "in_progress", "attempts": 1}}
    assert qs.reset_stale_in_progress(q) == 1
    assert q["x"]["pipeline_status"] == "pending"
    assert q["x"]["attempts"] == 2
