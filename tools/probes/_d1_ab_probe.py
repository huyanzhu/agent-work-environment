#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_d1_ab_probe.py — **只改来源覆盖**的对照实验（只读 · 可复跑）

阶段八 定义：
  · 保留基线 `f14bd93793cc` · 三份冻结输入 · A/B/C/D 与评分规则 **都不变**
  · **只切换语料版本**（`AIOS_D1_EXTENDED=0|1`）
  · 用**相同 as_of_seq**（冻结时点）复测 ⇒ ⛔ 不重新生成快照、⛔ 不让未来事件进来
  · 核心指标 = **已知相关对象的覆盖与召回** · **新增相关唯一对象数** · 噪声 · 重复承载 · 来源增量
    （⛔ 不用候选条目总数）
  · 新候选**必须重新盲判**（→ `--dump-review` 输出**无组别**的盲判视图）· ⛔ 不沿用旧标签

基线可复现性断言：基线圈的候选记录必须与**冻结映射**逐条一致（否则说明条件漂移）。

纪律：⛔ 只读 · ⛔ 不改评分/闸门/请求配置 · ⛔ 不落推理原文
"""
import io
import json
import os
import sys

# ── 路径解析（执行层自 `scratch/` 迁入 `tools/probes/` · 参数化）─────────
#    优先级：`AIOS_ROOT` 环境变量 ▸ 本文件位置（`<root>/tools/probes/`）▸ 工作目录。
#    ⛔ 不写死本机路径 ⇒ clone 到任意位置必须可用（`HANDOFF §四十五` 未清项之「参数化回流」）。
def _aios_root():
    env = os.environ.get("AIOS_ROOT")
    if env and env.strip():
        return os.path.abspath(env.strip())
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.dirname(os.path.dirname(here))
    if os.path.isfile(os.path.join(cand, "tools", "experience_push.py")):
        return cand
    return here


AIOS_ROOT = _aios_root()
PROBES = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(AIOS_ROOT, "tools")
# 运行期生成物（注册表缓存 / 名称索引 / 外部候选池 / 扩展语料）—— `.aios/` 不进版本库。
CACHE = os.environ.get("AIOS_STATE_DIR") or os.path.join(AIOS_ROOT, ".aios")
for _p in (TOOLS, PROBES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _ctx_snapshot_probe as csp      # noqa: E402
import _ctx_snapshot_eval as cse       # noqa: E402
import _retrieval_request_probe as rp  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

MODES = ("A", "B", "C", "D")


def _norm(p):
    return str(p).replace("\\", "/").lower()


def produced_before(payload, as_of):
    """该时点**之前已实际产出**的文件（= 独立真值"已知相关材料"）。"""
    evs = payload.get("events") or []
    return sorted({p for e in evs
                   if (e.get("seq") or 0) <= as_of and e["kind"] == "tool-call"
                   and str(e.get("tool") or "").lower() in ("edit", "write")
                   for p in (e.get("path_hints") or [])})


def one_pass(payload, as_of, extended, max_cand=12):
    os.environ["AIOS_D1_EXTENDED"] = "1" if extended else "0"
    snap = csp.build(payload, as_of)
    req0 = {"need": {"state": "unknown"}, "work": {}}
    descs, status = rp.load_sources(req0)
    pool = {_norm(d.get("local_path") or d.get("remote_path") or d.get("id")) for d in descs}
    out = {"corpus_fingerprint": rp.corpus_version(descs)["fingerprint_sha12"],
           "descriptor_count": len(descs), "pool": pool, "groups": {}, "candidates": {}}
    for mode in MODES:
        req, _refs, _ph = cse.to_request(snap, mode, max_cand)
        res = rp.run(req, max_cand)
        if not res.get("ok"):
            out["groups"][mode] = {"records": [], "objects": []}
            continue
        recs = [c["id"] for c in res["candidates"]]
        paths = [_norm(c.get("local_path") or c.get("remote_path") or "") for c in res["candidates"]]
        objs = sorted({p for p in paths if p})
        out["groups"][mode] = {"records": recs, "objects": objs, "paths": paths}
        out["candidates"][mode] = [{
            "name": c["name"], "source": c["source"]["id"], "kind": c.get("kind"),
            "role": c.get("role"),
            "path": c.get("local_path") or c.get("remote_path"),
            "evidence_only": c.get("evidence_only"),
            "preview": (c.get("preview") or "")[:180],
        } for c in res["candidates"]]
    return out, snap


def load_frozen(tag):
    p = os.path.join(PROBES, "_blind_%s.map.json" % tag)
    if not os.path.isfile(p):
        return {}
    with io.open(p, "r", encoding="utf-8-sig") as f:
        m = json.load(f)
    return {tp["as_of_seq"]: tp for tp in (m.get("timepoints") or [])}


def ab(payload, tag, review_dump=None, max_cand=12):
    frozen = load_frozen(tag)
    points = sorted(frozen.keys())
    rows, reproducibility = [], []
    for p in points:
        base, snap = one_pass(payload, p, False, max_cand)
        ext, _ = one_pass(payload, p, True, max_cand)
        known = produced_before(payload, p)
        # 基线可复现性：与冻结映射逐组比对
        fz = frozen.get(p) or {}
        for mode in MODES:
            want = sorted(((fz.get("groups") or {}).get(mode) or {}).get("records") or [])
            got = sorted(base["groups"][mode]["records"])
            reproducibility.append({"as_of_seq": p, "mode": mode,
                                    "frozen_n": len(want), "now_n": len(got),
                                    "identical": want == got})
        def cov(pool):
            return [k for k in known if _norm(k) in pool]
        def rec_(groups):
            hit = set()
            for mode in MODES:
                paths = set(groups[mode].get("paths") or [])
                for k in known:
                    if _norm(k) in paths:
                        hit.add(k)
            return sorted(hit)
        base_pool, ext_pool = base["pool"], ext["pool"]
        base_objs = set().union(*[set(base["groups"][m].get("paths") or []) for m in MODES])
        ext_objs = set().union(*[set(ext["groups"][m].get("paths") or []) for m in MODES])
        rows.append({
            "as_of_seq": p,
            "snapshot": {"future_excluded": snap["snapshot"]["future_events_excluded"],
                         "no_future_leak": True},
            "known_related_total": len(known),
            "known_in_corpus_base": len(cov(base_pool)),
            "known_in_corpus_extended": len(cov(ext_pool)),
            "known_recalled_base": len(rec_(base["groups"])),
            "known_recalled_extended": len(rec_(ext["groups"])),
            "recalled_paths_extended": rec_(ext["groups"])[:20],
            "groups_base": {m: {"records": len(base["groups"][m]["records"]),
                                "objects": len(base["groups"][m]["objects"])} for m in MODES},
            "groups_extended": {m: {"records": len(ext["groups"][m]["records"]),
                                     "objects": len(ext["groups"][m]["objects"])} for m in MODES},
            "new_objects_extended_vs_base": sorted(ext_objs - base_objs)[:40],
            "new_object_count": len(ext_objs - base_objs),
            "extended_source_candidates": sum(
                1 for m in MODES for c in ext["candidates"][m]
                if c["source"] == rp.D1_SOURCE_ID),
            "fingerprints": {"base": base["corpus_fingerprint"], "extended": ext["corpus_fingerprint"]},
            "descriptor_counts": {"base": base["descriptor_count"], "extended": ext["descriptor_count"]},
        })
    rep = {
        "ok": True, "session": payload.get("session"), "tag": tag,
        "scope_of_change": "**只改来源覆盖**（语料版本）· 评分/闸门/A-B-C-D/快照生成 一律不变",
        "baseline_frozen_fingerprint": "f14bd93793cc",
        "reproducibility": {"all_identical": all(r["identical"] for r in reproducibility),
                            "rows": reproducibility,
                            "note": "基线圈必须与冻结映射逐条一致（否则条件已漂移，读数作废）"},
        "timepoints": rows,
        "note": "🔴 新候选**必须重新盲判**（`--dump-review` 输出无组别视图）· ⛔ 不沿用旧标签",
    }
    if review_dump:
        objs, seen = [], set()
        for p in points:
            ext, _ = one_pass(payload, p, True, max_cand)
            for mode in MODES:
                for c in ext["candidates"][mode]:
                    key = _norm(c.get("path") or c["name"])
                    if key in seen:
                        continue
                    seen.add(key)
                    objs.append({"object_key": "mat:" + os.path.basename(key), "name": c["name"],
                                 "kind": c.get("kind"), "role": c.get("role"),
                                 "evidence_only": c.get("evidence_only"),
                                 "path": c.get("path"), "preview": c.get("preview")})
        with io.open(review_dump, "w", encoding="utf-8") as f:
            json.dump({"session": payload.get("session"),
                       "independent_work_evidence": {
                           "note": "🔴 原始工具证据（⛔ 不是 Runtime 派生字段）",
                           "files_produced_by_session": sorted({p for e in (payload.get("events") or [])
                                                                if e["kind"] == "tool-call"
                                                                and str(e.get("tool") or "").lower()
                                                                in ("edit", "write")
                                                                for p in (e.get("path_hints") or [])}),
                           "tool_activity_sample": [
                               {"seq": e.get("seq"), "tool": e.get("tool"), "paths": e.get("path_hints")}
                               for e in (payload.get("events") or [])
                               if e["kind"] == "tool-call" and e.get("path_hints")][:120]},
                       "candidate_objects": objs,
                       "instruction_to_reviewer": ("逐 candidate_objects 判 relevant / partial / irrelevant，"
                                                   "只依据独立工具证据与仓库真实产物；⛔ 组别/理由/评分均不提供"),
                       "discipline": "只读 · 无推理原文（D-1 扩展语料轮次）"}, f,
                      ensure_ascii=False, indent=1)
        rep["review_dump"] = review_dump
    return rep


def main():
    tag, review = None, None
    as_of = None
    for a in sys.argv[1:]:
        if a.startswith("--tag="):
            tag = a.split("=", 1)[1]
        elif a.startswith("--dump-review="):
            review = a.split("=", 1)[1]
        elif a.startswith("--as-of="):
            as_of = [int(x) for x in a.split("=", 1)[1].split(",")]
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig") or "{}")
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": "bad-input", "detail": str(exc)[:80]}) + "\n")
        return 2
    if tag is None:
        tag = str(payload.get("session") or "").replace("session-", "")[:8]
    if as_of:  # 允许显式指定时点（仍只读 payload）
        fz = load_frozen(tag)
        for k in list(fz.keys()):
            if k not in as_of:
                del fz[k]
        globals()["load_frozen"] = lambda _t, _fz=fz: _fz
    rep = ab(payload, tag, review)
    sys.stdout.write(json.dumps(rep, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
