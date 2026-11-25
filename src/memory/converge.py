"""存量重灌 CLI（记忆收敛 Phase 3）——把三个事实源整批递给上游。

    python -m src.memory.converge --dry-run      # 默认：只枚举，零写入
    python -m src.memory.converge --apply        # 真递（需要 LLM_MEMORY_REPO 可用）
    python -m src.memory.converge --apply --retire-old-db   # 末位是占位，见下

映射与三条运行时写通道**逐字对齐**，不另立一套 id 空间：

| 事实源                                   | source_type   | namespace     | source_id       |
|----------------------------------------|---------------|---------------|-----------------|
| data/pipeline/summaries/pdf/ 、/web/     | ai_research   | ai-research   | item_id         |
| data/sessions/*.json                     | webapp_chat   | webapp-chat   | session_id      |
| BRIEFS_DIR/<date>/*.html 卡片             | brief         | AATF          | item_id（卡片）  |

三个事实源本身就是可重建的（会话文件、摘要 JSON、简报 HTML 都在本地躺着），
所以"存量不迁移、删了重灌"在这里落地的是**重灌**而不是搬家：本 CLI 不读
`data/memory_db` 的任何一行，也不从里面搬任何东西——旧库在收敛生效后是
只读兜底，退役改名是 --apply 之后**单独**的一步，做不做由用户定（见
`--retire-old-db` 那段的说明）。

契约，三条是硬的：

1. **--dry-run 一个字节都不写**。它只 open 三个源目录列文件、从 JSON 里读
   一个 id、把 BRIEFS_DIR 的 HTML 解析成卡片，然后打印"将要递什么"。上游
   一次调用都不发，brief 那条路连中转 JSON 都不写盘（写盘只发生在 --apply，
   见 `_stage` 的注释）。
2. **只写上游，不回退本地**。这是拒跑条件的全部来历：`LLM_MEMORY_REPO`
   无效、或 `MEMORY_STORE_MODE=local` 时，本 CLI **显式打印拒绝理由并退出**，
   不做任何静默降级。宁可什么都不写，也不要"半批进上游、半批进旧库"——
   那种局面下两边都说不清自己有什么，比不跑还难收场。
   顺带一个结构上的决定：这里刻意调 `upstream.upstream_ingest()` 而不是
   `gateway.ingest()`。gateway 的选路是**按调用点现探**的，跑到一半上游掉线
   时它会照着 contract 给这一条写本地——那条政策对三条常驻通道是对的，
   但和"整批只进上游"的批处理契约正相反，所以这里直接走 transport 层，
   把契约钉在"这函数根本没有本地支路"这件事上。
3. **幂等交给上游**。AR 侧不算 chunk-hash、不做去重预判；同一个文件再递一次
   由上游的 hash-dedup 回 `chunks_added == 0`，所以中途 Ctrl-C 或单文件失败
   之后**接着再跑是安全的**（README/帮助里也这么写）。别指望这里有个"断点续跑"
   的账本——没有状态文件，也没有那个必要。

上游侧的一个变化记在这儿免得下次当 bug 查：f181999 把 dir-fallback 的阀门
退役了（legacy 行走 `migrate_legacy_memory.py` 重键）。我们这层传的三个
namespace 都是显式的，不受影响；要是跑完发现 `namespaces()` 里的键变多了或
被归一化了，那是上游的正当行为，**别在 AR 侧加补丁去"纠正"它**。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config.constants import get_data_root
from src.memory import upstream
from src.memory.config import (
    MEMORY_MODE_AUTO,
    NAMESPACE_AATF,
    NAMESPACE_AI_RESEARCH,
    NAMESPACE_WEBAPP_CHAT,
    get_memory_store_mode,
)

# 三个源的键名同时是 --only 的取值，别在这儿和 CLI 选项之间造第二套名字。
SRC_SUMMARIES = "summaries"
SRC_SESSIONS = "sessions"
SRC_BRIEFS = "briefs"
ALL_SOURCES = (SRC_SUMMARIES, SRC_SESSIONS, SRC_BRIEFS)


# ---------------------------------------------------------------- 源路径

def _summaries_dir() -> Path:
    """摘要 JSON 的家。走 pipeline.paths 的常量而不是自己拼 "data/..."：
    那个常量已经处理过 PROJECT_ROOT/DATA_ROOT 的相对路径锚定，同一处事实
    第二遍定义迟早和跑批那边分家。"""
    from src.pipeline.paths import SUMMARIES_DIR  # 函数级：converge 不该拖上整条 pipeline import 链
    return Path(SUMMARIES_DIR)


def _sessions_dir() -> Path:
    # session_manager 的默认值是相对 "data/sessions"，这里统一锚到数据根，
    # 从任何 cwd 跑都指到同一处（找不到就在报告里明说是哪个路径，不猜）。
    return get_data_root() / "sessions"


def _briefs_dir() -> Path:
    from src.pipeline.paths import BRIEFS_DIR
    return Path(BRIEFS_DIR)


# ---------------------------------------------------------------- 枚举

def _task(source: str, path: Path, source_type: str, namespace: str,
          source_id: str, note: str = "") -> Dict[str, Any]:
    return {"source": source, "path": path, "source_type": source_type,
            "namespace": namespace, "source_id": source_id, "note": note}


def _id_from_json(path: Path, key: str) -> Tuple[Optional[str], str]:
    """从文件里取一个稳定 id，取不到就带上一句"为什么取不到"。

    宁可退到文件名也不要跳过这个文件：文件名在两边的命名里本来就是次级
    标识（session 的文件名 == session_id，摘要文件名带 item_id），退过去
    仍是同一个 id；而"静默少灌一条"是要到事后才发现的那种错。
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # noqa: BLE001 —— 读不动的文件归到 errors，不拖垮整批
        return None, f"读不到 JSON：{type(exc).__name__}: {exc}"
    value = data.get(key)
    if value:
        return str(value), ""
    return None, f"JSON 里没有 {key} 键，退用文件名"


def enumerate_summaries() -> Tuple[List[Dict[str, Any]], List[str]]:
    """summaries/{pdf,web}/*.json → (ai_research, ai-research, item_id)。"""
    tasks: List[Dict[str, Any]] = []
    errors: List[str] = []
    root = _summaries_dir()
    if not root.is_dir():
        return [], [f"摘要目录不存在：{root}"]
    for kind in ("pdf", "web"):
        folder = root / kind
        if not folder.is_dir():
            errors.append(f"{folder} 不存在（该 kind 跳过）")
            continue
        for path in sorted(folder.glob("*.json")):
            sid, note = _id_from_json(path, "item_id")
            if sid is None:
                errors.append(f"{path.name}：{note}")
                sid = path.stem
            tasks.append(_task(SRC_SUMMARIES, path, "ai_research",
                               NAMESPACE_AI_RESEARCH, sid, note))
    return tasks, errors


def enumerate_sessions() -> Tuple[List[Dict[str, Any]], List[str]]:
    """data/sessions/*.json → (webapp_chat, webapp-chat, session_id)。"""
    tasks: List[Dict[str, Any]] = []
    errors: List[str] = []
    root = _sessions_dir()
    if not root.is_dir():
        return [], [f"会话目录不存在：{root}"]
    for path in sorted(root.glob("*.json")):
        sid, note = _id_from_json(path, "session_id")
        if sid is None:
            errors.append(f"{path.name}：{note}")
            sid = path.stem
        tasks.append(_task(SRC_SESSIONS, path, "webapp_chat",
                           NAMESPACE_WEBAPP_CHAT, sid, note))
    return tasks, errors


def enumerate_briefs(since: Optional[str] = None,
                     until: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """BRIEFS_DIR 的日卡片 → (brief, AATF, item_id)。

    只解析 HTML，不写任何中转文件：`--apply` 时才把卡片写成摘要 JSON 递上去
    （见 `_stage_card`）。这里把日期都数出来，是因为"某天有没有 HTML"和
    "那天的卡片进没进上游"是两件事，dry-run 得让人看得见差在哪。

    `since` / `until` 是闭区间过滤，专为 `--apply` 的成本开口：一天几十张
    卡片就是几十轮 agentic 抽取，本机 69 天存量数下来是几千次调用，不能
    只剩"整批梭下去"这一个选项。日期形状写错就直接报错，不当"没有这天"
    静默滤掉——那样等于悄悄少灌一批，比报错糟得多。
    """
    from src.pipeline.briefs_parser import list_coverage_dates, parse_briefs_dir

    tasks: List[Dict[str, Any]] = []
    errors: List[str] = []
    for label, value in (("since", since), ("until", until)):
        if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return [], [f"--{label} 取值 {value!r} 不是 YYYY-MM-DD 形状"]
    root = _briefs_dir()
    if not root.is_dir():
        return [], [f"BRIEFS_DIR 不存在：{root}（env BRIEFS_DIR 可指过去）"]
    dates = list_coverage_dates(root)
    if since:
        dates = [d for d in dates if d >= since]
    if until:
        dates = [d for d in dates if d <= until]
    if not dates:
        return [], [f"{root} 下没有落在 "
                    f"{since or '最早'}..{until or '最新'} 的日期目录"]
    for date in dates:
        try:
            parsed = parse_briefs_dir(root, date)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{date} 解析失败：{type(exc).__name__}: {exc}")
            continue
        for kind in ("pdf", "web"):
            for card in parsed.get(kind) or []:
                item_id = str(card.get("item_id") or "")
                if not item_id:
                    errors.append(f"{date}/{kind} 有一张卡片缺 item_id，跳过")
                    continue
                task = _task(SRC_BRIEFS, root / date, "brief", NAMESPACE_AATF, item_id)
                task["card"] = card          # --apply 时才用，dry-run 只数不写
                tasks.append(task)
    return tasks, errors


ENUMERATORS = {
    SRC_SUMMARIES: enumerate_summaries,
    SRC_SESSIONS: enumerate_sessions,
    SRC_BRIEFS: enumerate_briefs,
}


# ---------------------------------------------------------------- 跑前的门

def preflight(probe: bool = True) -> Tuple[bool, List[str]]:
    """这条批路开不开。开了才继续，否则打印理由退出——不降级、不重试到本地。

    `probe=False` 是给 dry-run 用的"只看配置面"版本：只核 env 有没有配、
    路径指得对不对，**不构造 MemoryClient**。构造 client 看着无害，其实会
    让上游按自己的规矩把 store 目录撑开——注意**副作用的准确位置**：构造
    MemoryClient 本身什么都不留（实测指到不存在的路径后目录还不存在），是第一个
    读面调用（status / namespaces / all_rows）会 connect 过去，于是
    `~/.llm-memory/` 下多出 ingest_state 之类的空脚手架，mtime 也跟着动；表不会被
    建出来，建表是 ensure_ready 的权限。dry-run 既然写明零写入，
    就不该留下"上游被谁碰过"的痕迹；真要跑 --apply 时自然会去探一次。
    """
    reasons: List[str] = []
    mode = get_memory_store_mode()
    if mode != MEMORY_MODE_AUTO:
        reasons.append(
            f"MEMORY_STORE_MODE={mode!r}：本 CLI 只写上游，不回退本地，"
            "想跑请先 unset 这个变量（auto 是缺省）")
    if probe:
        # 真实可达性只在这儿问一次：与 gateway 选路用的是同一个同步判定，
        # 免得两处各判各的。
        reachable = upstream.upstream_available_sync()
        detail = "（路径无效，或 MemoryClient 起不来）"
    else:
        from src.config.settings import get_llm_memory_repo  # env 的唯一入口，不在这重写键名
        repo = get_llm_memory_repo()
        reachable = bool(repo) and os.path.isdir(os.path.join(repo, "src"))
        detail = "（未设置，或 <repo>/src 不存在）"
    if not reachable:
        reasons.append(
            "上游 LLM-Memory 不可达" + detail + "。converge 不往本地 data/memory_db "
            "写一行，所以这里就地拒绝——把 repo 指对再来一次比先灌一半强。")
    return (not reasons), reasons


# ---------------------------------------------------------------- 写入

def _stage_card(card: Dict[str, Any]) -> str:
    """把一张卡片写成中转摘要 JSON，返回路径（--apply 才会走到这儿）。

    走的是 brief_ingest 那同一个写盘函数，不是另起一份：轻量入库的卡片
    形状以后要改，这里跟着漂开就等于"批处理和在线路往库里塞两种东西"。
    dry-run 一条都到不了这儿，写盘的只有 --apply。
    """
    from src.memory.brief_ingest import _stage_brief_card
    return _stage_brief_card(card)


async def _deliver(task: Dict[str, Any]) -> Dict[str, Any]:
    """递一条。三种源在这里收成一个形状：都是 upstream_ingest(path, type, ns, id)。"""
    if task["source"] == SRC_BRIEFS:
        # _stage_card 是同步的写盘（brief_ingest 那边同源同实现），别 await 它。
        path = _stage_card(task["card"])
    else:
        path = str(task["path"])
    return await upstream.upstream_ingest(
        path, task["source_type"], task["namespace"], task["source_id"])


def _tally(report: Dict[str, Any]) -> Tuple[int, int]:
    """从上游 report 里 present-only 地取 (added, skipped)。

    上游将来加减计数字段时这里不该跟着崩：有就用，没有就 0——"没报上来"
    在汇总里是"未知"，不是"成功 0 条"，那种情形靠 errors 那侧的失败折叠
    去兜。summary_id/chunks_deleted 之类的键不进汇总，留给日志。
    """
    inner = report.get("report") if isinstance(report.get("report"), dict) else {}
    src = {**inner, **{k: v for k, v in report.items() if k != "report"}}
    def _num(key: str) -> int:
        try:
            return int(src.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    return _num("chunks_added"), _num("chunks_skipped")


async def run_apply(tasks: List[Dict[str, Any]]) -> Dict[str, int]:
    """逐条递，单条失败记 errors 继续跑下一批——一个坏文件不该让整批停摆。"""
    stats = {"added": 0, "skipped": 0, "failed": 0, "calls": 0}
    for index, task in enumerate(tasks, 1):
        try:
            report = await _deliver(task)
        except Exception as exc:  # noqa: BLE001 —— 兜底：折叠面之外不该有异常漏出来
            stats["failed"] += 1
            print(f"  [{index}/{len(tasks)}] ✗ {task['source_type']}/{task['namespace']} "
                  f"id={task['source_id']} → 未捕获异常 {type(exc).__name__}: {exc}")
            continue
        stats["calls"] += 1
        if not report.get("available"):
            stats["failed"] += 1
            note = report.get("note") or report.get("error") or "无 note"
            print(f"  [{index}/{len(tasks)}] ✗ {task['source_type']}/{task['namespace']} "
                  f"id={task['source_id']} → {note}")
            continue
        added, skipped = _tally(report)
        stats["added"] += added
        stats["skipped"] += skipped
        flag = "＋" if added else "＝"
        print(f"  [{index}/{len(tasks)}] {flag} {task['source_type']}/{task['namespace']} "
              f"id={task['source_id']} → +{added} 新增 / {skipped} 已存在")
    return stats


# ---------------------------------------------------------------- 打印

def _print_dry_run(groups: Dict[str, Tuple[List[Dict[str, Any]], List[str]]]) -> int:
    print("\n[dry-run] 只看不动：一条都没递，上游一次调用都没发。\n")
    total = 0
    for name in ALL_SOURCES:
        tasks, errors = groups.get(name, ([], []))
        if not tasks and not errors:
            continue
        print(f"{name}: {len(tasks)} 个来源"
              f"（source_type/namespace 见下，将调 ingest {len(tasks)} 次）")
        shapes = {}
        for task in tasks:
            shapes.setdefault((task["source_type"], task["namespace"]), 0)
            shapes[(task["source_type"], task["namespace"])] += 1
        for (stype, ns), count in sorted(shapes.items()):
            print(f"    {stype:<12} → namespace {ns:<14} ×{count}")
        # 形状例子最多列三条：够看出 id 空间，又不至于把终端刷满。
        for task in tasks[:3]:
            print(f"      e.g. {task['path']} → {task['source_type']}/{task['namespace']}"
                  f"/{task['source_id']}")
        if len(tasks) > 3:
            print(f"      …其余 {len(tasks) - 3} 条同形状")
        for line in errors[:8]:
            print(f"      ⚠ {line}")
        if len(errors) > 8:
            print(f"      ⚠ 另有 {len(errors) - 8} 条同类提示（已合并计数）")
        total += len(tasks)
        print()
    print(f"合计将调 ingest {total} 次。确认无误再 --apply。")
    return total


# ---------------------------------------------------------------- 入口

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.memory.converge",
        description="把三个事实源整批重灌进上游 LLM-Memory（收敛 Phase 3）。"
                    "幂等靠上游 hash-dedup：中途断了再跑一次是安全的。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例：\n"
               "  python -m src.memory.converge            # 只枚举（默认 dry-run）\n"
               "  python -m src.memory.converge --apply     # 真递，失败继续下一批\n"
               "  python -m src.memory.converge --only sessions --apply\n"
               "  python -m src.memory.converge --since 2026-11-01 --limit 50 --apply\n"
               "  python -m src.memory.converge --apply --retire-old-db\n"
               "                          # 末位只是占位，见该 flag 的说明\n"
               "\n可重入：中途 Ctrl-C 或单条失败之后**接着再跑就行**——幂等整个\n"
               "交给上游的 hash-dedup，重递的那条会报成「已存在」而不是重复行，\n"
               "本 CLI 自己不留任何断点状态文件。\n")
    p.add_argument("--dry-run", action="store_true",
                   help="默认行为：只枚举 + 打印将递的形状与次数，零写入")
    p.add_argument("--apply", action="store_true",
                   help="真的递：逐条 upstream_ingest，added/skipped/failed 汇总")
    p.add_argument("--only", choices=list(ALL_SOURCES), default=None,
                   help="只跑一个源（缺省三个都跑）")
    p.add_argument("--since", metavar="YYYY-MM-DD", default=None,
                   help="只取该日期（含）之后的简报卡片——只作用于 briefs 源；"
                        "上游是 agentic 抽取，一天的成本就要按几十轮 LLM 算")
    p.add_argument("--until", metavar="YYYY-MM-DD", default=None,
                   help="只取该日期（含）之前的简报卡片（闭区间，与 --since 同用）")
    p.add_argument("--limit", type=int, default=0, metavar="N",
                   help="每个源最多取前 N 条，先拿一小批试水用（0＝不限）")
    p.add_argument("--retire-old-db", action="store_true",
                   help="占位：把 data/memory_db 改名退役。这一步不在这里做，"
                        "它属于 --apply 之后用户自己拍板的独立动作")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run and args.apply:
        print("✗ --dry-run 与 --apply 互斥（前者零写入，后者写上游）")
        return 2
    do_apply = bool(args.apply)

    sources = (args.only,) if args.only else ALL_SOURCES
    groups: Dict[str, Tuple[List[Dict[str, Any]], List[str]]] = {}
    for name in sources:
        if name == SRC_BRIEFS:
            groups[name] = enumerate_briefs(since=args.since, until=args.until)
        else:
            groups[name] = ENUMERATORS[name]()
        if args.limit and len(groups[name][0]) > args.limit:
            tasks, errors = groups[name]
            kept = tasks[:args.limit]
            groups[name] = (kept, errors + [
                f"按 --limit {args.limit} 截断，本批只递前 {len(kept)} 条"
                f"（共 {len(tasks)} 条可选）"])

    if do_apply:
        # 门只挡 --apply：这条契约是"整批只进上游"，不是"不许看"。
        ok, reasons = preflight()
        if not ok:
            print("✗ 拒跑：converge 只写上游，不回退本地。")
            for line in reasons:
                print(f"  · {line}")
            print("\n上面是拒绝开跑的理由，不是警告——这一条都不会递出去。")
            return 1
        print(f"[apply] 上游就绪，开始逐条递（{sum(len(t) for t, _e in groups.values())} 条）。\n")
        return _run_apply(groups, sources, retire=args.retire_old_db)

    # dry-run 不看上游脸色：它一个字节都不写，"这批有多大"这件事在未配置
    # 环境下也想看得见，否则第一次跑的人只能靠猜。上游通不通在这儿只是
    # 一句后置提示——--apply 真要跑，上面那道门会替它拒。
    _print_dry_run(groups)
    # probe=False：dry-run 不该惊动上游（连 client 都不构造），这里只能
    # 回答"配置面看着通不通"，通 ≠ 上游已连接——措辞别替上游提前保证。
    ok, reasons = preflight(probe=False)
    if ok:
        print("\n配置面就绪（未连接上游确认——本命令一条都没递）。可以直接 --apply。")
    else:
        print("\n现在 --apply 会拒跑（本命令什么都没写，也没碰上游）：")
        for line in reasons:
            print(f"  · {line}")
    return 0


def _run_apply(groups: Dict[str, Tuple[List[Dict[str, Any]], List[str]]],
               sources: Tuple[str, ...], retire: bool) -> int:
    import time
    started = time.monotonic()
    stats = {"added": 0, "skipped": 0, "failed": 0, "calls": 0}
    interrupted = False
    for name in sources:
        tasks, errors = groups[name]
        if errors:
            print(f"{name} 的枚举提示：")
            for line in errors[:8]:
                print(f"  ⚠ {line}")
        if not tasks:
            print(f"{name}: 没有可递的文件，跳过")
            continue
        print(f"{name}: {len(tasks)} 条")
        try:
            got = asyncio.run(run_apply(tasks))
            for key in stats:
                stats[key] += got.get(key, 0)
        except KeyboardInterrupt:
            # 中断落在 group 边界上，本组剩下的不递；已递出去的靠幂等再跑一次补。
            interrupted = True
            print("\n⏹ 收到中断，这一组就停在这儿——再跑一次是安全的（上游 hash-dedup）。")
            break
        print()

    print(f"汇总：{stats['calls']} 次调用 → +{stats['added']} 新增 / "
          f"{stats['skipped']} 已存在（幂等命中）/ {stats['failed']} 失败"
          f"，用时 {time.monotonic() - started:.1f}s")
    if stats["failed"]:
        print("失败的那几条没有回落本地——这是设计，重试或 unset 才是选项。")
    if interrupted:
        print("因中断提前结束，重跑即可续上。")
    if retire:
        print("旧库退役：未执行。这是 --apply 之后单独的一步（把 data/memory_db 改名"
              "即可回退），由用户拍板，本 CLI 不代做。")
    # 退出码也是文案的一部分：中断＝130（POSIX 的 128+SIGINT 口径，脚本里
    # 一眼看得出"没跑完"而不是"跑坏了"），有失败＝1，全绿＝0。
    if interrupted:
        return 130
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
