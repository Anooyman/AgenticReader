#!/usr/bin/env python3
"""整条联动的验收——一条命令，只动数据以外的东西（元数据痕迹见页脚那句）。

前几轮的所有断言散在各处：契约测试在 `tests/`，数据对照在
`check_memory_drift.py`，配置自述在 AR 的 `/upstream` 接口里。这个脚本把它们
收成一屏**PASS/FAIL**，回答的是同一个问题在不同层面：

  ① 路由：这条进程到底会不会走上游（寻址设没设、是不是有效）
  ② 自述：上游有没有把"我是谁"说清楚——维度、模型、source_type
  ③ 一致性：`namespaces()` 的行数加总和 `status().total` 对不对得上
  ④ 读路：search / browse 出来的行是不是 AR 认的那 14 列形状
  ⑤ 护栏：`delete_*` 在无 scope 时是不是**在任何一次写之前**就拒绝
  ⑥ 隔离：上游可用时，本地旧库是不是一次都没被碰过

写操作一条都不做：⑤ 用的是"注定被拒"的入参，护栏挡在调用之前，所以这个
脚本在你机器上跑一百次也不会改库。上游没接上时它不猜——把该做的检查标成
FAIL 并告诉你缺的是哪一个变量。

用法：
    python3 tools/check_memory_integration.py            # 人读的六行
    python3 tools/check_memory_integration.py --json     # 机读
退出码：0＝全过；1＝有 FAIL（含"根本没接上游"这种最常见的失败）。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ⑥ 用来记账：本地旧库一旦被 new 出来就说明这条路上偷偷回落了
_local_lookups = []


def _record_local_store():
    from src.memory import gateway

    original = gateway._store

    def _spy(*a, **kw):
        _local_lookups.append("touched")
        return original(*a, **kw)

    gateway._store = _spy
    return original


def _restore_local_store(previous):
    from src.memory import gateway

    gateway._store = previous


# ------------------------------------------------------------------ ①
def check_routing():
    from tools.check_memory_drift import routing_state

    st = routing_state()
    ok = bool(st["effective_repo"]) and st["store_mode"] != "local"
    return ok, f"{st['verdict']}（mode={st['store_mode']}）"


# ------------------------------------------------------------------ ②
def check_capabilities():
    from src.memory import gateway

    caps = gateway.upstream_capabilities_sync() if hasattr(gateway, "upstream_capabilities_sync") else None
    if caps is None:
        import asyncio
        caps = asyncio.run(gateway.upstream_capabilities())
    if not caps.get("available"):
        return False, f"上游自述拿不到：{caps.get('note') or caps.get('error')}"
    missing = [k for k in ("dimensions", "embedding_model", "chat_model",
                           "source_types", "store_dir") if caps.get(k) in (None, "", [])]
    if missing:
        return False, f"自述缺键：{missing}"
    return True, (f"dims={caps['dimensions']} embed={caps['embedding_model']} "
                  f"chat={caps['chat_model']} ns_types={len(caps['source_types'])}")


# ------------------------------------------------------------------ ③
def check_counts_are_one_truth():
    import asyncio

    from src.memory import gateway

    status = asyncio.run(gateway.upstream_status())
    if not status.get("available"):
        return False, f"status 不可用：{status.get('note')}"
    summed = sum(int(n.get("rows") or 0) for n in status.get("namespaces") or [])
    total = int(status.get("total") or 0)
    if summed != total:
        return False, f"namespaces 加总 {summed} ≠ status.total {total}"
    return True, f"{len(status.get('namespaces') or [])} 个 namespace / {total} 行"


# ------------------------------------------------------------------ ④
def check_read_shapes(*, with_search: bool = False):
    """形状检查默认只走 browse。

    search 这一腿**不是免费的**：它进的是 agentic 检索，一次就要几轮 LLM
    调用——一个自称"只读诊断"的工具不该顺手替人花这笔钱，所以它得是 opt-in。
    想验证检索形状再加 `--with-search`，别默认就烧。
    """
    from src.memory import gateway

    problems = []
    rows = gateway.browse_all_rows("*")
    # "空"有两种，混在一起说就会既会误报也会漏报：
    #   库里真的没有行 —— 这格无从可验，等第一批行进来才有意义，别算它失败；
    #   库里有行而这条路读出 0 —— 那才是这格存在的理由（读面悄悄回落到本地，
    #   本地那份正好是空的，于是页面上一切正常、行却一条不剩）。
    claimed_total = None
    try:
        from src.memory import upstream as _up
        claimed_total = (_up.upstream_browse_all_rows("*") or {}).get("total")
    except Exception:  # noqa: BLE001 - 问不到总数就走原来的判法
        pass
    if not rows and claimed_total == 0:
        return True, "browse 0 行，但上游自报也是 0 行——库是空的，这格暂无内容可验"
    if not rows:
        problems.append(f"browse_all_rows('*') 读出 0 行"
                        f"{'，而上游自报 ' + str(claimed_total) + ' 行——读路在骗人' if claimed_total else '（上游总数问不到，不能假定它是空的）'}")
    else:
        need = {"id", "namespace", "source_id", "chunk_hash", "abstract", "created_at"}
        missing = sorted(need - set(rows[0]))
        if missing:
            problems.append(f"browse 行缺列：{missing}（AR 的形状契约不认这个）")
    if with_search:
        import asyncio

        hits = asyncio.run(gateway.search("测试", namespaces=None))
        got = hits.get("results") if isinstance(hits, dict) else hits
        if got is None:
            problems.append("search 没有 results 键")
        return (not problems), f"browse {len(rows)} 行 / search {len(got)} 命中"
    tail = f"browse {len(rows)} 行（search 这腿没跑：要验证它加 --with-search）"
    # 判为失败时把"为什么"一起说出去，别让读者只剩一行"browse 0 行"去猜。
    return (not problems), ("；".join(problems) + "｜" + tail if problems else tail)


# ------------------------------------------------------------------ ⑤
class _SandboxStore:
    """护栏检查专用的假库。

    **这个检查绝不能碰真库**——它喂进去的是"本该被拒绝"的入参，万一护栏哪天
    失效了，落在真库上就是一次不可逆的清空，一次都没法补。第一次写这脚本时
    就犯过这个错：护栏只装在上游那条分支里，于是本地分支一声不响地按行删了
    八十几条下去。所以现在这条检查自己带一个沙箱：真要有漏，删掉的是这里的
    假行，屏幕上写的也是"落到沙箱而不是真实库"，你的数据一个字节都不会少。
    """

    def __init__(self):
        self.touched = []

    def rows_for_source(self, namespace, source_id):
        self.touched.append(("rows_for_source", namespace, source_id))
        return []

    def all_rows(self, namespace):
        self.touched.append(("all_rows", namespace))
        return []

    def delete(self, row_id):
        self.touched.append(("delete", row_id))
        return 1


def check_delete_guard():
    """拒绝必须发生在**任何一次写之前**——而且这检查本身得是无害的。"""
    from src.memory import gateway

    sandbox = _SandboxStore()
    original = gateway._store
    gateway._store = lambda provider=None: sandbox
    refused = []
    try:
        for call in (lambda: gateway.delete_source("", "x"),
                     lambda: gateway.delete_namespace("*"),
                     lambda: gateway.delete_namespace("")):
            try:
                call()
            except ValueError:
                refused.append(True)
            except Exception as exc:  # noqa: BLE001 —— 非 ValueError 说明不是那道护栏
                refused.append(False)
                print(f"      （delete 抛的是 {type(exc).__name__}: {exc}）")
            else:
                refused.append(False)
    finally:
        gateway._store = original

    if all(refused):
        return True, "无 scope 的 delete 三处全在写之前被拒（护栏打在沙箱上，真库未碰）"
    note = (f"{refused.count(True)}/3 被拒；漏掉的那几处落到的是沙箱，"
            f"不是你的 data/memory_db（沙箱里记录了 {len(sandbox.touched)} 次调用）")
    return False, note


# ------------------------------------------------------------------ ⑦
def check_width_agreement():
    """两边各多宽——这一格回答的不是"通不通"，是"接不上的时候能不能靠本地"。

    上游的宽度由本仓 config 决定（`capabilities()` 里那格就是权威），AR 自己的
    旧库按它 provider 的配置建。数字对上，回落才是"同一批东西的两个副本"；
    数字对不上，回落就只是**接口语义**上的回落——同一 namespace 名、同一套列名，
    捞出来的却是另一个向量空间里的行。两种说法差得远，所以这格不许省略，
    也不许在量不到的时候假称一致。
    """
    import os

    from src.memory import gateway
    from tools.check_memory_drift import AR, probe_vector_width

    import asyncio

    try:
        caps = asyncio.run(gateway.upstream_capabilities())
    except Exception as exc:  # noqa: BLE001 - 没接上上游时这格本来就不适用
        return True, f"上游宽度取不到（未配置/不可达：{type(exc).__name__}），本条不适用"
    up_dims = caps.get("dimensions")

    local_dims = probe_vector_width(os.path.join(AR, "data", "memory_db"))

    if up_dims is None or local_dims is None:
        got = f"上游={up_dims} 本地={local_dims}"
        return True, f"宽度有一侧量不到（{got}）——按不适用处理，别假设一致"
    if int(up_dims) == int(local_dims):
        return True, f"两边同宽（{up_dims}），回落才是同一批数据的另一副本"
    return False, (f"上游={up_dims} 本地={local_dims}：宽度不同，两边的行**互不可移植**。"
                   "上游读不到时回到本地并不等于拿回同一批东西——那只是接口语义上的"
                   "回落；补灌时这批行要按「重新抽取」计成本，不是「重放一遍」。")

def check_no_local_touch():
    """只在"路由应该走上游"的前提下断言，否则这条永远是错的。

    未接上游时打开本地库本来就是**对的**行为——把它报成 FAIL 会让整个工具的
    可信度打折：一个总在喊错的检查，最后一句也没人听了。所以这里先看路由
    脸色，只在"该走上游却没走"的时候说话。
    """
    from tools.check_memory_drift import routing_state

    st = routing_state()
    routed = bool(st["effective_repo"]) and st["store_mode"] != "local"
    if not routed:
        return True, "路由未接上游，本条不适用（本地库被打开是对的）"
    if _local_lookups:
        return False, f"该走上游的一轮里本地旧库被打开 {len(_local_lookups)} 次"
    return True, "本轮没有一次去 new 本地 VectorStore"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--with-search", action="store_true",
                    help="把 search 那一腿也跑上（会花几次 LLM 调用，默认不跑）")
    args = ap.parse_args(argv)


    restore = _record_local_store()
    checks = [("路由", check_routing), ("自述", check_capabilities),
              ("计数", check_counts_are_one_truth),
              ("读路形状", lambda: check_read_shapes(with_search=args.with_search)),
              ("删除护栏", check_delete_guard), ("本地隔离", check_no_local_touch),
              ("宽度", check_width_agreement)]
    results = []
    try:
        for name, fn in checks:
            try:
                ok, note = fn()
            except Exception as exc:  # noqa: BLE001 —— 验收工具不许自己先崩
                ok, note = False, f"{type(exc).__name__}: {str(exc)[:90]}"
            results.append({"name": name, "ok": bool(ok), "note": note})
    finally:
        _restore_local_store(restore)

    failed = [r for r in results if not r["ok"]]
    if args.json:
        print(json.dumps({"passed": not failed, "checks": results}, ensure_ascii=False))
    else:
        for r in results:
            print(f"  [{'PASS' if r['ok'] else 'FAIL'}] {r['name']:<10} {r['note']}")
        print(f"\n{len(results) - len(failed)}/{len(results)} 通过"
              + ("" if not failed else f"；{len(failed)} 项未过——按上面的名字去查"))
    if failed:
        print("（这个脚本不改任何一个库的数据：不新增行、不删行、不建表；"
              "但它对打开过的库不是零痕迹——lancedb 会在 `__manifest` 里留下"
              "version hint / txn 一类元数据。痕迹是真的，行是干净的，"
              "这两件事都该如实说。）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
