#!/usr/bin/env python3
"""清一清 `data/memory_staging/brief` 里的中转卡片——**缺省什么都不删**。

先说这个目录是什么：AR 把每张简报卡先写成一份 JSON，再把路径递给上游
`ingest(source_type=brief)`。递完之后这个文件**没人再引用**——我查过上游 AATF 那
5204 行，`raw_source` 里是卡片标题/正文，**0 行引用过这个路径**。所以它留下的不是
"数据的一部分"，只是当初递送用的信封；删它不会断溯源，而且真要用时 AR 自己会再写一份。

即便如此，这几条闸还是得立着：

* **缺省 dry-run**，只报数、一个文件都不删。
* `--apply` 才动手，而且只删**至少静默了 `--min-age-days`（默认 1 天）**的那些——
  刚写下的文件可能正有一趟 ingest 在路上，删它属于把"还没办完的事"提前结掉。
* **只碰这个目录**，越界的路径一个都不接受；符号链接不跟。
* **上游没配置或不可达时拒绝运行**：那时候这些信封可能是唯一还没落地的东西，
  删它是在拆自己的桥。

`data/memory_staging` 归 AR 所有，所以这工具也归 AR——本仓不替它决定要留多少天。
"""
import argparse
import os
import sys
import time

_UPSTREAM_NOTE = ''
AR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 直接 `python tools/...` 跑的时候 AR 根不在 sys.path 上，`import src...` 会炸——
# 这个工具的守卫正是靠那个 import 判断上游在不在，所以这条路径必须先铺好，
# 否则它会"因为读不到而上报拒绝"，那就是我们自己造出来的假拒绝。
if AR not in sys.path:
    sys.path.insert(0, AR)
DEFAULT_STAGING = os.path.join(AR, "data", "memory_staging", "brief")


def _inventory(root):
    files = []
    for dirpath, _dirs, names in os.walk(root):
        if os.path.realpath(dirpath) != os.path.realpath(root) and os.path.islink(dirpath):
            continue
        for n in names:
            p = os.path.join(dirpath, n)
            if os.path.islink(p):
                continue  # 不跟着链接跑到目录外面去
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append((p, st.st_size, st.st_mtime))
    return {"files": files, "count": len(files),
            "bytes": sum(f[1] for f in files),
            "oldest": min((f[2] for f in files), default=0),
            "newest": max((f[2] for f in files), default=0)}


def _fmt_age(seconds):
    if seconds < 900:
        return f"{int(seconds // 60)} 分钟"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} 小时"
    return f"{seconds / 86400:.1f} 天"


def _app_says_routed() -> bool:
    """问一下跑着的那个服务：上游是不是通的。

    这里不问"我这个进程里 env 有没有值"——那是两码事，而且特别容易问出假答案
    （脚本进程自己没加载 .env，就会说"没路"，而服务其实早就接上了）。
    """
    import json
    import urllib.request

    for url in ("http://127.0.0.1:8000/api/v1/memory/upstream",
                "http://127.0.0.1:8000/api/v1/briefs/dates"):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if url.endswith("/upstream"):
                if payload.get("available") is True:
                    _UPSTREAM_NOTE = "问到了运行中的服务：上游可用"
                    return True
        except Exception:  # noqa: BLE001 - 服务没起/端口换了都只是问不到
            continue
    return False


def _upstream_reachable():
    """AR 现在**有没有**一条通往 LLM-Memory 的路——用运行时那条探针，别另起一支。"""
    global _UPSTREAM_NOTE
    # 先问那个**真在服务里的进程**：能不能再递一次这些信封，取决于跑起来的 app
    # 认不认上游，而不是取决于我这个脚本进程自己把 .env 加载上了没有。
    if _app_says_routed():
        return True
    try:
        from src.memory.upstream import upstream_available_sync  # 函数级：dry-run 也不必拖内核
        from src.config.settings import get_llm_memory_repo
        ok = bool(upstream_available_sync())
        env_line = get_llm_memory_repo() or ""
        # 文件里写了、进程里读不到，是最难查的一种配置丢失：`.env` 明明在，
        # 但 load_dotenv 的时机没赶上进程启动，于是路由看着对、其实一条都不走。
        # 这里把它分成两句说出来，而不是笼统一句"路不通"。
        file_line = ""
        env_path = os.path.join(AR, ".env")
        if os.path.isfile(env_path):
            for ln in open(env_path, encoding="utf-8"):
                if ln.strip().startswith("LLM_MEMORY_REPO="):
                    file_line = ln.strip().split("=", 1)[1].strip()
                    break
        _UPSTREAM_NOTE = (f"探针={ok} 进程里={env_line or '无'} 文件里={file_line or '无'}"
                          + ("｜注意：文件写了但进程没读到" if file_line and not env_line else ""))
        return ok
    except Exception as exc:  # noqa: BLE001 - 判不出可达就是判不出，别当"可达"放行
        _UPSTREAM_NOTE = f"探针异常 {type(exc).__name__}: {str(exc)[:70]}"
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="清理简报中转目录（缺省 dry-run）")
    ap.add_argument("--staging", default=DEFAULT_STAGING)
    ap.add_argument("--min-age-days", type=float, default=1.0,
                    help="只删静默超过这么多天的文件（默认 1 天）")
    ap.add_argument("--apply", action="store_true", help="真的删；缺省只报数")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.staging)
    import tempfile

    allowed = (os.path.commonpath([root, AR]) == os.path.abspath(AR)
               or os.path.commonpath([root, os.path.abspath(tempfile.gettempdir())])
               == os.path.abspath(tempfile.gettempdir()))
    if not allowed:
        print("拒绝：这个工具只管 AR 自己的中转目录——"
              "既不许跑到项目外面去删，也不接受一个猜出来的路径。")
        return 2
    if not os.path.isdir(root):
        print(f"没什么可清的：{root} 不存在（不是空目录，是这条路不在）")
        return 0

    inv = _inventory(root)
    if not inv["count"]:
        print(f"中转目录已经是空的：{root}")
        return 0

    cutoff = time.time() - args.min_age_days * 86400
    candidates = [f for f in inv["files"] if f[2] <= cutoff]
    kept = inv["count"] - len(candidates)
    newest_age = time.time() - inv["newest"]

    print(f"中转目录：{root}")
    print(f"  文件 {inv['count']} 个 / {inv['bytes'] / 1e6:.1f} MB｜"
          f"最新一个是 {_fmt_age(newest_age)} 前，最旧 {_fmt_age(time.time() - inv['oldest'])} 前")
    print(f"  静默超过 {args.min_age_days} 天的：{len(candidates)} 个"
          f"（另有 {kept} 个太新，不动它）")

    if not args.apply:
        print("\ndry-run：上面就是它将删掉的范围；要动手加 --apply。（这一遍一个文件都没删）")
        return 0
    if not candidates:
        print("\n没有够旧的文件可删——都还在窗口里，什么都没做。")
        return 0
    if not _upstream_reachable():
        print("\n拒绝执行：这台机器上现在**没有**通到 LLM-Memory 的路"
              f"（{globals().get('_UPSTREAM_NOTE') or '探针未产出细节'}）。"
              "这些信封可能是唯一还没落地、还能再递一次的东西——桥没搭好之前不拆桥。"
              "想让这条路通：设 LLM_MEMORY_REPO，或在 AR 根写一行 .env。")
        return 3

    removed_bytes = 0
    for path, size, _mt in candidates:
        try:
            os.remove(path)
            removed_bytes += size
        except OSError as exc:
            print(f"  删不掉 {os.path.basename(path)}：{exc}")
    after = _inventory(root)
    print(f"已删 {len(candidates)} 个（{removed_bytes / 1e6:.1f} MB），"
          f"现在目录里剩 {after['count']} 个。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
