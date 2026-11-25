#!/usr/bin/env python3
"""memory 到底在哪儿——一条能反复跑的对照命令。

背景：收敛之后，同一条记忆可能落在三处地方——
  · 上游 `~/.llm-memory/memory`（这才是"记忆的家"）
  · AR 的 `data/memory_db`（auto 路由没接上/上游不可达时的本地旧路）
  · AR 的 `data/memory_db.legacy`（收敛前冻结的那份）

三个库都能被读到，于是"这条记忆入库了吗"就有了三个答案，而人只会看屏幕上
那一个。这个脚本不修任何东西：**它只把"谁拿着哪些 source_id"摊开**——
尤其盯"只在本地有、上游没有"的那一批，因为那正是目标终态里不该存在的：
非 PDF 的对话/摘要记忆应该落在上游那份库里。

用法：
    python3 tools/check_memory_drift.py            # 人读的一屏
    python3 tools/check_memory_drift.py --json     # 给 CI / 脚本
    python3 tools/check_memory_drift.py --max-only-local 0

退出码：
    0  没有"只在本地"的条目（或调用方明确放宽了阈值）
    1  有只在本地/只在 legacy 的条目——需要补灌或说明
    2  至少一个库的路径不存在/打不开。注意这跟"空库"是两格：表是首次写入
       时才建的，fresh install 的上游本来就是"目录在、表没有"，那是 0 行
       而不是错误；**目录都没有**才报 2，因为那意味着看错了地方。
"""
import argparse
import json
import os
import subprocess
import time
import sys

AR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 上游的库根由上游自己算（它才有 MEMORY_DATA_DIR 的话语权）；这里只是
# 读，不参与选址，所以宁可让 --upstream 显式覆盖，也别拿一个猜出来的路径吓人。
DEFAULT_UPSTREAM = os.path.join(os.path.expanduser("~"), ".llm-memory", "memory")
DEFAULT_LOCAL = os.path.join(AR, "data", "memory_db")
DEFAULT_LEGACY = os.path.join(AR, "data", "memory_db.legacy")

# 收敛口径里"归上游"的那三条车道（AR 的 config.py 里那三个常量的值）
LANES = ("AATF", "ai-research", "webapp-chat")


def probe_vector_width(path):
    """这个库的向量宽多少——量不到就返回 None，绝不猜。

    为什么值得单列一行：两个库合并不了，第一道墙不是列名，是**宽度**。上游的库
    是 512，AR 自己那个旧库按它 provider 的配置建，历史上是 1536——宽度不同的
    两张表，行互不可移植。于是"上游读不到就回落本地"在这种局面下只是**语义**
    上的回落（同一个 namespace 名、同一套列名，捞出来的却是另一个空间的向量），
    不是能拿本地补上游数据的那种回落。这行数字摆在这儿，比文档里解释十遍都直接。
    """
    import lancedb

    if not os.path.isdir(path):
        return None
    db = lancedb.connect(path)
    names = db.list_tables()
    names = names.tables if hasattr(names, "tables") else names
    for name in names:
        try:
            schema = db.open_table(name if isinstance(name, str) else name[0]).schema
        except Exception:  # noqa: BLE001 - 表开不了就是量不到，不是 0
            continue
        for field in schema:
            ftype = field.type
            if hasattr(ftype, "list_size"):
                return int(ftype.list_size)
    return None


def _tables(path):
    """一个 LanceDB 目录里的 {namespace: (source_id 集合, 行数)}。

    读不到时抛异常，不返回空——"打不开"和"空的"必须是两句话，
    这是这套跨库对照唯一不能撒谎的地方。
    """
    import lancedb

    # 先分清"这里有个库"和"这条路根本不在"。空库是一个合法状态——表是第一次
    # 写入时才建的，fresh install 的上游就是"目录在、表没有"；而目录不存在的
    # 意思是压根没在看这个库，拿它当"库里 0 行"报出来，比漏几条危险得多。
    if not os.path.isdir(path):
        raise FileNotFoundError(f"库路径不存在：{path}（不是空库，是没在看的那个库）")
    db = lancedb.connect(path)
    names = db.list_tables()
    names = names.tables if hasattr(names, "tables") else names
    names = [n if isinstance(n, str) else n[0] for n in names]
    out = {}
    for name in names:
        tbl = db.open_table(name)
        frame = tbl.to_pandas()
        if "namespace" not in frame or "source_id" not in frame:
            raise RuntimeError(f"{path}/{name} 不是记忆表（缺 namespace/source_id 列）")
        # created_at 是可选列：有就能回答"这些只在本地的行是什么时候进去的"，
        # 也就是"还在那儿往上涨吗"；没有就留空，别编一个日期出来。
        has_time = "created_at" in frame
        for ns, sub in frame.groupby("namespace"):
            ids = set(str(s) for s in sub["source_id"])
            stamped = ({str(s): str(t)[:10] for s, t in zip(sub["source_id"], sub["created_at"])}
                       if has_time else {})
            out[str(ns)] = {"ids": ids, "rows": int(len(sub)), "dates": stamped}
    return out


def routing_state(env=None, ar_root=AR):
    """AR 现在**到底会不会**走上游——这是解释上面所有数字的那一句。

    差口为什么一直在那儿，通常不是路由写错了，而是运行环境里那个寻址旋钮
    压根没有值：机制全在、测试全绿，实际跑起来一条记忆都不出仓。所以这里
    把"设没设、设得对不对、有没有被 kill switch 压住"分开报，别让人对着
    一张明明全绿的测试套件找 bug。

    读法上按 AR 自己的规矩来：`settings.py` 走 `load_dotenv()`，所以
    `.env` 里的键和 shell 里的键都算数（`.env` 只在 shell 没设时补位）。
    """
    env = os.environ if env is None else env
    repo = (env.get("LLM_MEMORY_REPO") or "").strip()
    mode = (env.get("MEMORY_STORE_MODE") or "").strip().lower()
    dot = os.path.join(ar_root, ".env")
    in_dotenv = ""
    if os.path.isfile(dot):
        try:
            with open(dot, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip().startswith("LLM_MEMORY_REPO="):
                        in_dotenv = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except OSError:
            in_dotenv = ""  # 读不动 .env：说"未知"，别当作没设

    effective = repo or in_dotenv
    if mode == "local":
        verdict = ("MEMORY_STORE_MODE=local 把路由压死了——无论 LLM_MEMORY_REPO "
                   "是什么，记忆都留在本地旧库")
    elif not effective:
        verdict = ("LLM_MEMORY_REPO 没有值（shell 与 .env 都没有）→ 记忆一律走"
                   "AR 自己的 data/memory_db；机制都在，实际一条都不出仓。"
                   "想让这件事不能悄悄发生，另设 MEMORY_STORE_MODE=upstream："
                   "上游不在了就抛错，不给自己留'先写本地'那一步")
    elif not os.path.isdir(os.path.join(effective, "src", "llm_memoryd")):
        verdict = f"设了 LLM_MEMORY_REPO={effective!r}，但那不是一个 LLM-Memory checkout → 会先 warning 再走本地"
    else:
        verdict = f"寻址有效（{effective}）→ search/ingest/delete/browse 四条路都走上游"
    return {"env_repo": repo, "dotenv_repo": in_dotenv, "effective_repo": effective,
            "store_mode": mode or "auto", "verdict": verdict}


def probe(upstream, local, legacy):
    stores = {}
    errors = {}
    for label, path in (("upstream", upstream), ("local", local), ("legacy", legacy)):
        try:
            stores[label] = _tables(path)
        except Exception as exc:  # noqa: BLE001 —— 读不到要如实报，别当空库
            stores[label] = {}
            errors[label] = f"{type(exc).__name__}: {str(exc)[:120]}"
    lanes = {}
    for lane in LANES:
        up = stores.get("upstream", {}).get(lane) or {"ids": set(), "rows": 0, "dates": {}}
        lo = stores.get("local", {}).get(lane) or {"ids": set(), "rows": 0, "dates": {}}
        lg = stores.get("legacy", {}).get(lane) or {"ids": set(), "rows": 0, "dates": {}}
        stray_ids = lo["ids"] - up["ids"]
        # 只在本地的那批是什么时候写进去的——这决定的是"要不要急"，不是
        # "要不要做"：日期一直停在几周前说明那是历史包袱，今天还在长才说明
        # 每天都在把记忆写到错的地方去。
        stray_dates = sorted(d for s, d in lo["dates"].items() if s in stray_ids and d)
        # 车道级的"最近写入"比 store 级的诚实：store 级会算上别的 namespace
        # 今天的动静，于是"AATF 还在往本地长"和"上游今天在长别的东西"会被
        # 混成一句含糊的"两边都在长"。
        all_up = sorted(d for d in up["dates"].values() if d)
        all_lo = sorted(d for d in lo["dates"].values() if d)
        lanes[lane] = {
            "upstream_ids": len(up["ids"]), "upstream_rows": up["rows"],
            "local_ids": len(lo["ids"]), "legacy_ids": len(lg["ids"]),
            "local_not_upstream": sorted(stray_ids),
            "local_only_first": stray_dates[0] if stray_dates else "",
            "local_only_last": stray_dates[-1] if stray_dates else "",
            "upstream_last_write": all_up[-1] if all_up else "",
            "local_last_write": all_lo[-1] if all_lo else "",
            "legacy_not_upstream": len(lg["ids"] - up["ids"]),
        }
    # 别的 namespace（上游机器级那些 slug-<hex> 的，还有 AR 派生名）只报行数，
    # 不参与"车道"判定，免得把决策面的行当成漏网的对话。
    other = {}
    for label in ("upstream", "local", "legacy"):
        for ns, entry in stores.get(label, {}).items():
            if ns not in lanes:
                other.setdefault(ns, {})[label] = entry["rows"]
    # 每个库最近一次写入是什么时候——这格回答的是"还在不在发生"。本地比上游
    # 新就意味着此刻仍有记忆落到错的地方，而不只是历史遗留。
    newest = {}
    for label, per_ns in stores.items():
        stamps = [d for entry in per_ns.values() for d in entry["dates"].values() if d]
        newest[label] = max(stamps) if stamps else ""
    return {"lanes": lanes, "other_namespaces": other, "errors": errors,
            "newest_write": newest,
            "paths": {"upstream": upstream, "local": local, "legacy": legacy}}


def staging_activity() -> dict:
    """`data/memory_staging/brief` 最近有没有在动——**这条是运行时在骗不骗人的探头**。

    为什么值得单独看一眼：这个目录只有 `load_brief_date_upstream` 会写（每张卡
    先落成中转 JSON，再把路径递给 `ingest`）。所以"这里有今天的新文件"意味着
    上游那条分支**真的被走过了**。而两边库都没有今天的行——这两件事同时成立，
    中间必然有一段是"递上去了、但没人知道结果"，这正是我最不该让它继续隐身的那种
    形状：不是崩，不是错，是**什么都不发生**。

    没有这个探头时，工具只会说"没有差口"，看起来像收敛完成了。
    """
    import glob
    import time

    path = os.path.join(AR, "data", "memory_staging", "brief")
    files = glob.glob(os.path.join(path, "*.json"))
    if not files:
        return {"files": 0, "newest": None, "today": 0}
    stamps = [os.path.getmtime(f) for f in files]
    newest = max(stamps)
    return {"files": len(files),
            "newest": time.strftime("%Y-%m-%d", time.localtime(newest)),
            "today": sum(1 for s in stamps
                         if time.strftime("%Y-%m-%d", time.localtime(s)) ==
                         time.strftime("%Y-%m-%d"))}


def _etime_seconds(etime: str) -> float:
    """`ps` 的 etime（[[D-]H:]M:S）换成秒——解析不了就返回 -1，让调用方去说"不知道"。"""
    try:
        days = 0
        if "-" in etime:
            days, etime = etime.split("-", 1)
            days = int(days)
        parts = [int(x) for x in etime.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return float(days * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2])
    except Exception:  # noqa: BLE001
        return -1.0


def _latest_memory_source_mtime() -> tuple:
    """记忆里最后被动过的文件与时间——用来和进程启动时间比新旧。"""
    newest, newest_path = 0.0, ""
    for root in ("src/memory", "src/ui/backend/services", "src/pipeline"):
        d = os.path.join(AR, root)
        if not os.path.isdir(d):
            continue
        for dirpath, _dirs, files in os.walk(d):
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(dirpath, f)
                m = os.path.getmtime(p)
                if m > newest:
                    newest, newest_path = m, os.path.relpath(p, AR)
    return newest, newest_path


def upstream_extract_failures(store_dir: str) -> dict:
    """上游今天**抽掉了多少 chunk**——从它自己的日志里数，不是猜。

    起因是两条互相矛盾的观察凑在一起：AR 说"这批卡加载成功了，errors=0"，
    上游的库里却少了行。答案在上游的日志里：抽取失败的每一条都写成
    `chunk failed, will retry on next run`——**跳过这一条、下轮再试**，
    调用方拿到的整体结果依然是成功。

    如果失败是偶发的（超时、端点抖），下一轮确实会补上。可日志里最常见的那类是
    `ContextWindowExceededError` / 400 invalid request：**确定性失败**，
    再试十轮还是同一个结果。这种形状下"retry on next run"听上去像自愈，
    实际上是永久跳过，而且两边屏幕上都不会有失败。
    """
    import re
    import time

    log = os.path.join(os.path.dirname(os.path.abspath(store_dir)), "app.log")
    if not os.path.isfile(log):
        return {"seen": False, "note": "上游日志不在预期位置（不代表没有失败）"}
    today = time.strftime("%Y-%m-%d")
    pat = re.compile(r"^(\d{4}-\d{2}-\d{2}) [\d:,]+\s+\w+.*chunk failed", re.M)
    counts = {"total": 0, "today": 0, "context_window": 0, "other": 0}
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = pat.match(line)
                if not m:
                    continue
                counts["total"] += 1
                if m.group(1) == today:
                    counts["today"] += 1
                    low = line.lower()
                    if "contextwindow" in low or "maximum context length" in low:
                        counts["context_window"] += 1
                    else:
                        counts["other"] += 1
    except OSError as exc:  # noqa: BLE001 - 日志读不动也要继续出别的数
        return {"seen": False, "note": f"上游日志读不动：{type(exc).__name__}"}
    counts["seen"] = True
    counts["log"] = log
    return counts


def running_app_versions() -> dict:
    """跑着的 AR 进程有没有在执行当前这棵树——**这条比任何测试都直接**。

    起因是一次真实的误判：我以为"今天的中转卡片没落库是因为上游那条链断了"，
    实测之后真相是——那个进程是**昨天下午启动的**，它内存里还是旧代码；我把同一
    批卡在当前树上递了一遍，全数落地、0 错误。也就是说：**代码是对的，跑的
    不是它**。

    一台机器上最容易骗过判据的事就是这个：文件都已经改好、测试全绿，但运行的
    进程还带着旧 import 快照，屏幕上却什么都看不出来。这里把它变成一栏数字：
    进程启动时间 vs `src/` 里最后一个被改过的记忆文件时间。
    """
    try:
        # 用 etime 而不是 lstart 来推启动时间：etime 形如 [[D-]H:]M:S，
        # 换成秒再拿 now 一减就是 epoch，不用碰任何依赖 locale 的日期解析。
        out = subprocess.run(["ps", "-eo", "pid,etime,command"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception as exc:  # noqa: BLE001 - 拿不到进程表就明说
        return {"found": False, "note": f"进程表读不到：{type(exc).__name__}"}

    procs = []
    for line in out.splitlines()[1:]:
        # 两种起法都得认出来：直接 `python src/ui/run_server.py`，
        # 以及 `python -m uvicorn src.ui.backend.app:app`——点号写法以前会漏，
        # 于是明明服务在跑，这栏却说"AR 是停的"，那是个会反着误导人的假安静。
        if ("run_server.py" not in line and "src/ui/backend" not in line
                and "src.ui.backend" not in line):
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, et, cmd = parts[0], parts[1], parts[2]
        procs.append({"pid": pid, "elapsed_s": _etime_seconds(et),
                      "started": time.strftime("%Y-%m-%d %H:%M",
                                               time.localtime(time.time() - _etime_seconds(et))),
                      "cmd": cmd.strip()[:90]})
    newest, newest_path = _latest_memory_source_mtime()
    if not procs:
        return {"found": False, "note": "没有跑着的应用进程（这台机器上 AR 是停的）",
                "newest_memory_file": newest_path,
                "newest_memory_mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(newest))}
    return {"found": True, "processes": procs,
            "newest_memory_file": newest_path,
            "newest_memory_mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(newest))}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    ap.add_argument("--local", default=DEFAULT_LOCAL)
    ap.add_argument("--legacy", default=DEFAULT_LEGACY)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-only-local", type=int, default=0,
                    help="允许多少条只在本地/只在 legacy 的条目（默认 0，一条都不许有）")
    args = ap.parse_args(argv)

    report = probe(args.upstream, args.local, args.legacy)
    report["routing"] = routing_state()
    # 每个库的向量宽度——不合库的第一道墙在这格，不在列名那一列。
    report["widths"] = {}
    for label, path in (("upstream", args.upstream), ("local", args.local),
                        ("legacy", args.legacy)):
        try:
            report["widths"][label] = probe_vector_width(path)
        except Exception as exc:  # noqa: BLE001 - 宽度量不到就明说，别当作 0
            report["errors"][f"width:{label}"] = f"{type(exc).__name__}: {str(exc)[:110]}"
            report["widths"][label] = None
    report["staging"] = staging_activity()
    report["process"] = running_app_versions()
    report["extract_failures"] = upstream_extract_failures(args.upstream)
    stray = sum(len(v["local_not_upstream"]) for v in report["lanes"].values())
    stray += sum(v["legacy_not_upstream"] for v in report["lanes"].values())

    if args.json:
        report["verdict"] = {"stray_entries": stray, "read_errors": bool(report["errors"])}
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"上游 {report['paths']['upstream']}")
        print(f"本地 {report['paths']['local']}")
        print(f"冻结 {report['paths']['legacy']}")
        print(f"路由 {report['routing']['verdict']}\n")
        st = report["staging"]
        if st["files"]:
            quiet = [lab for lab, d in (report.get("newest_write") or {}).items()
                     if d == st["newest"]]
            print(f"中转目录：{st['files']} 张卡｜最近改动 {st['newest']}"
                  + (f"（今天 {st['today']} 张）" if st["today"] else ""))
            if st["today"]:
                print("      ↑ 这个目录只有「走上游那条分支」才会写。它在动而两边库都没今天的行，"
                      "说明有一段是「递上去就完事、结果没人看」——那比报错更该查，因为屏幕上不会出现失败。")
        ef = report.get("extract_failures") or {}
        if not ef.get("seen"):
            print(f"上游抽取失败：{ef.get('note', '未知')}")
        else:
            print(f"上游抽取失败：累计 {ef.get('total', 0)} 条"
                  f"｜今天 {ef.get('today', 0)} 条"
                  f"（其中上下文窗口 {ef.get('context_window', 0)}，其它 {ef.get('other', 0)}）")
            if ef.get("context_window"):
                print("      ↑ 这类是**确定性失败**：日志写的是 will retry on next run，"
                      "可上下文超限再试一轮还是超限。上游把它记成跳过、AR 把它记成成功——"
                      "行少了却是全绿，这是这里最难发现的一种静默。")
        proc = report.get("process") or {}
        if proc.get("found"):
            print(f"运行中的进程：{len(proc['processes'])} 个"
                  f"｜最近一次改动记忆代码：{proc['newest_memory_mtime']}"
                  f"（{proc['newest_memory_file']}）")
            for pr in proc["processes"]:
                stale = pr["elapsed_s"] >= 0 and pr["started"] < proc["newest_memory_mtime"]
                print(f"      pid {pr['pid']} 启动于 {pr['started']} · {pr['cmd']}"
                      + ("  ← 启动早于最后一次代码改动：**它跑的不是这棵树**" if stale else ""))
            if any(p["elapsed_s"] >= 0 and p["started"] < proc["newest_memory_mtime"]
                   for p in proc["processes"]):
                print("      ↑ 这一条能解释一堆「机制都对、数据不涨」的现象：测试跑的是磁盘上的"
                      "新代码，服务跑的是内存里的旧快照。重启之前，别急着判断是哪一侧的错。")
        else:
            print(f"运行中的进程：{proc.get('note', '未知')}")
        w = report["widths"]
        got = {k: v for k, v in w.items() if v}
        print("向量宽度：" + "  ".join(f"{k}={w[k] if w[k] else '量不到'}" for k in w))
        if len(set(got.values())) > 1:
            print("  → 宽度不一致：这些库的**行互不可移植**。此时「回落到本地」只是语义上的"
                  "回落（同一个 namespace 名、同一套列名，捞出来的是另一个空间的向量），"
                  "别把它当成能用本地补上游数据的兜底。")
        print(f"{'车道':<14}{'上游':>8}{'上游id':>8}{'本地id':>8}{'冻结id':>9}   只在本地")
        for lane, v in report["lanes"].items():
            print(f"{lane:<14}{v['upstream_rows']:>8}{v['upstream_ids']:>8}"
                  f"{v['local_ids']:>8}{v['legacy_ids']:>9}   "
                  f"{len(v['local_not_upstream'])}+{v['legacy_not_upstream']}")
        # 只在本地不等于"一直在本地"：日期说的是这批东西是哪阵子写进去的。
        print("\n只在本地的那批是什么时候写的：")
        for lane, v in report["lanes"].items():
            if v["local_not_upstream"]:
                span = (f"{v['local_only_first']} → {v['local_only_last']}"
                        if v["local_only_first"] else "（库里没有 created_at 列，日期未知）")
                lane_note = ""
                if v["upstream_last_write"] and v["local_last_write"]:
                    if v["local_last_write"] > v["upstream_last_write"]:
                        lane_note = (f"  ← 这条车道自己：本地上次写入 {v['local_last_write']}"
                                     f" 比上游 {v['upstream_last_write']} 新，"
                                     f"上游在这条车道上已经不动了")
                    elif v["local_last_write"] == v["upstream_last_write"]:
                        lane_note = f"  ← 这条车道两边同日（{v['local_last_write']}）"
                    else:
                        lane_note = "  ← 这条车道上游反而更新"
                print(f"  {lane:<14} {len(v['local_not_upstream']):>4} 条   {span}{lane_note}")
        newest = report.get("newest_write") or {}
        newest = report.get("newest_write") or {}
        if newest.get("local") and newest.get("upstream"):
            if newest["local"] > newest["upstream"]:
                verdict_now = "本地比上游新——此刻还在往本地写记忆，不只是历史包袱"
            elif newest["local"] == newest["upstream"]:
                verdict_now = ("两边同一天都在写——不是静止的历史包袱，是两边同时在长；"
                               "这批差口的性质得看日期窗口，别看这个大小比较")
            else:
                verdict_now = "上游不比本地旧——这批是历史遗留，不每天变差"
            print(f"最近写入：本地 {newest['local']} / 上游 {newest['upstream']} → {verdict_now}")

        # 空本地库是个**歧义**状态，不是好消息：它可能是"记忆都归上游了"，
        # 也可能是"刚被人删空"（本仓真出过这么一次，drift 于是很好看但什么也
        # 没说明）。凡是三条车道都归零，就去看表还在不在——在，就得说清楚。
        if all(not v["local_not_upstream"] for v in report["lanes"].values()) and \
                all(v["local_ids"] == 0 for v in report["lanes"].values()):
            table_dir = os.path.join(str(report["paths"]["local"]), "memories.lance")
            if os.path.isdir(table_dir):
                print("注意：本地库现在是**空表**（表在、0 行）。这有两种可能，"
                      "本工具分不出来：记忆确实都归上游了，或者这张表刚被清空过。\n"
                      "      如果最近没人做过迁移或清理，把它当成事故来查，别当成收敛完成——"
                      "空表不产生任何「已入库」的证据。")
            else:
                print("注意：本地库连表都没有（不是空表，是从没建过）——那才是"
                      "「记忆一条都没在这里」的诚实形状。")
        if report["other_namespaces"]:
            print("\n其它 namespace（不参与车道判定）：")
            for ns, per in sorted(report["other_namespaces"].items()):
                print(f"  {ns:<34}", per)
        for label, err in report["errors"].items():
            print(f"  读不到 {label}：{err}")
        print(f"\n结论：应当已落在上游库里、现在却只在 AR 本地/冻结库里的条目 = "
              f"{stray} 条"
              + ("。" if stray == 0 else " —— 补灌到上游，或明确记下为什么留着。"))

    if report["errors"]:
        return 2
    return 0 if stray <= args.max_only_local else 1


if __name__ == "__main__":
    sys.exit(main())
