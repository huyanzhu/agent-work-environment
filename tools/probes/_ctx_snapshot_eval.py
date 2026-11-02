#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_ctx_snapshot_eval.py — 阶段七主线：**分字段评估 + 独立对照 + 固定版本 Retrieval 对照**（只读）

依据：`RUNTIME-CONTEXT-SNAPSHOT-DESIGN.md §7` 预登记判据的 ②③④⑤：
   ② 区分 用户目标 / 当前思路 / 已放弃方向 / 实际工具活动
   ③ **分字段评估**（⛔ 不用一个总分掩盖差异）
   ④ **独立对照**（⛔ 不得用 Runtime 自己生成的字段当自己的真值）
   ⑤ 送**固定版本** Retrieval，比较候选**相关性**（⛔ 不只比数量）

🔴 本脚本的三件事（各自给读数，⛔ 不合并成一个总分）
   **A 逐步重建的可核验性**：按 seq 分位取多时点快照 ⇒ 断言
      `from_activity/from_reasoning ⊆ 该时点之前的原始事件`（**无未来泄漏**）+ 集合**单调不减**
   **B 分字段评估**：
      · `target_refs` —— 用**文件系统**作独立真值（存在性 · **多根**）
      · `work_topic` —— **两个独立对照**：① assistant 可见回复 ② **实际改动文件内容**
      · `direction_change` —— **窗口稳健性**（W=2/3/5）
      · `blockers_unresolved` —— 与独立工具失败计数核对
   **C 固定版本 Retrieval 对照**（4 组 · 同一 `corpus_version`）+ 可选 `--dump` 导出盲判输入

纪律：⛔ 只读 · ⛔ 不落推理原文 · ⛔ 不改评分/闸门/语料
"""
import io
import json
import os
import re
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
import _retrieval_request_probe as rp  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

STRONG_BASIS = ("literal-path-substring", "literal-basename-substring", "structured-key-match")
WEAK_BASIS = ("description-match", "role-map", "agent-supplied-key-match", "term-overlap")
#: 可用的对象引用档位（`exists-product-root` = 存在于**额外核实根**，如产品工作区）
USABLE_EXISTS = ("exists", "exists-suffix", "exists-product-root")


# ─────────────────────────────────────────────────────────────────────────────
# A · 逐步重建：无未来泄漏 + 单调性（**真实数据上的机械断言**）
# ─────────────────────────────────────────────────────────────────────────────
def reconstruction_check(payload, points=5):
    evs = payload.get("events") or []
    if not evs:
        return {"ok": False, "why": "no-events"}
    seqs = sorted(e.get("seq") or 0 for e in evs)
    if len(seqs) < points:
        picks = seqs
    else:
        picks = sorted({seqs[min(len(seqs) - 1, int((len(seqs) - 1) * i / (points - 1)))]
                        for i in range(points)})
    rows, prev_a, prev_r = [], set(), set()
    leak_total, monotone = 0, True
    for p in picks:
        snap = csp.build(payload, p)
        trv = snap["target_refs"]["value"] if snap["target_refs"]["state"] == "provided" else {}
        A = {x["ref"] for x in (trv.get("from_activity") or [])}
        R = {x["ref"] for x in (trv.get("from_reasoning") or [])}
        allowed_a = set(csp.clean_refs((t, c.get("seq")) for c in evs
                                       if (c.get("seq") or 0) <= p and c["kind"] == "tool-call"
                                       for t in (c.get("path_hints") or [])))
        allowed_r = set(csp.clean_refs((t, e.get("seq")) for e in evs
                                       if (e.get("seq") or 0) <= p and e["kind"] == "reasoning"
                                       for t in re.findall(csp.ws.PATH_RE, e.get("text") or "")))
        leak_a, leak_r = sorted(A - allowed_a), sorted(R - allowed_r)
        leak_total += len(leak_a) + len(leak_r)
        if not (prev_a <= A and prev_r <= R):
            monotone = False
        prev_a, prev_r = A, R
        rows.append({"as_of_seq": p, "events_used": snap["snapshot"]["events_used"],
                     "future_excluded": snap["snapshot"]["future_events_excluded"],
                     "from_activity": len(A), "from_reasoning": len(R),
                     "leak_activity": leak_a[:3], "leak_reasoning": leak_r[:3]})
    return {"ok": True, "points": len(picks), "leak_total": leak_total,
            "no_future_leak": leak_total == 0, "monotone_nondecreasing": monotone, "rows": rows}


# ─────────────────────────────────────────────────────────────────────────────
# B · 分字段评估（独立对照）
# ─────────────────────────────────────────────────────────────────────────────
def _read_multi_root(rel):
    """产物内容读取（**多根**：AI-OS 根 + 额外核实根）。"""
    r = str(rel).replace("\\", "/")
    for root in [AIOS_ROOT] + csp.extra_roots():
        fp = os.path.normpath(os.path.join(root, r))
        if os.path.isfile(fp):
            try:
                with io.open(fp, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            except OSError:
                return None
    return None


def field_eval(payload):
    snap = csp.build(payload, None)
    trv = snap["target_refs"]["value"] if snap["target_refs"]["state"] == "provided" else {}
    ar, rr = trv.get("from_activity") or [], trv.get("from_reasoning") or []

    def rate(xs):
        return round(sum(1 for x in xs if x["exists"] in USABLE_EXISTS) / float(len(xs)), 3) if xs else None

    # work_topic：**两个独立对照**
    #   ① assistant 可见回复（读数 0 命中 ⇒ 无效对照，保留以示证据）
    #   ② **该会话实际编辑/写入的文件内容**（产物 = 最独立的材料）
    atext = "\n".join(e.get("text") or "" for e in payload.get("events") or []
                      if e["kind"] == "assistant-text")
    phrases = [t["phrase"] for t in (snap["work_topic"]["value"] or [])]
    in_at = [p for p in phrases if p in atext]
    dels = sorted({p for e in payload.get("events") or []
                   if e["kind"] == "tool-call" and str(e.get("tool") or "").lower() in ("edit", "write")
                   for p in (e.get("path_hints") or [])})
    blob, read_n = [], 0
    for p in dels[:30]:
        txt = _read_multi_root(p)
        if txt is not None:
            blob.append(txt)
            read_n += 1
    blob = "\n".join(blob)
    in_prod = [p for p in phrases if p in blob]
    # direction_change：窗口稳健性
    dcs = {}
    for w in (2, 3, 5):
        d = csp.build(payload, None, window=w)["direction_change"]["value"]
        dcs["W=%d" % w] = {"change": d["change"], "at": d["at"]}
    changes = {v["change"] for v in dcs.values()}
    # blockers：与独立工具失败计数核对
    errs = sum(1 for e in payload.get("events") or []
               if e["kind"] == "tool-result" and e.get("error"))
    fails = len((snap["blockers_unresolved"]["value"] or {}).get("verified_failures") or [])
    cov = snap["evidence_coverage"]["value"] or {}
    return {
        "target_refs": {
            "from_activity_n": len(ar), "from_reasoning_n": len(rr),
            "activity_usable_rate": rate(ar), "reasoning_usable_rate": rate(rr),
            "activity_usable": sum(1 for x in ar if x["exists"] in USABLE_EXISTS),
            "agreement_n": len(trv.get("agreement") or []),
            "reasoning_only_n": len(trv.get("reasoning_only") or []),
            "activity_only_n": len(trv.get("activity_only") or []),
            "exists_breakdown": _dist([x["exists"] for x in (ar + rr)]),
            "verdict": ("✅ 可用" if rate(ar) and rate(ar) >= 0.8 else
                        ("🟡 部分" if ar else "⚪ 该会话无工具活动")),
            "independent_truth": "文件系统存在性（**多根**：AI-OS + 额外核实根）· ⛔ 不用 snapshot 自己的字段",
        },
        "work_topic": {
            "phrases_n": len(phrases),
            "cross_material_n": len(in_at),
            "cross_material_rate": round(len(in_at) / float(len(phrases)), 3) if phrases else None,
            "cross_product_n": len(in_prod),
            "cross_product_rate": round(len(in_prod) / float(len(phrases)), 3) if phrases else None,
            "products_read": read_n,
            "sample": phrases[:6],
            "prod_sample": in_prod[:6],
            "verdict": ("✅ 可用" if in_prod else ("🟡 部分" if phrases else "⚪ 无短语")),
            "independent_truth": "① assistant 可见回复（实测无效）② **实际改动文件内容**（产物 · 多根）",
        },
        "direction_change": {"by_window": dcs, "window_consistent": len(changes) == 1,
                            "verdict": ("🟡 部分（暂定 · 窗口一致）" if len(changes) == 1
                                        else "❌ 不稳定（不同窗口结论不同）")},
        "blockers_unresolved": {
            "verified_failures_n": fails, "independent_error_events": errs,
            "consistent": fails == errs,
            "reasoning_marker_n": len((snap["blockers_unresolved"]["value"] or {}).get("reasoning_markers") or []),
            "verdict": "✅ 一致" if fails == errs else "❌ 不一致",
            "independent_truth": "tool/result 的 error 标记",
        },
        "evidence_coverage": {"steps_total": cov.get("steps_total"),
                              "steps_with_reasoning": cov.get("steps_with_reasoning"),
                              "tool_only_steps": cov.get("tool_only_steps"),
                              "gaps": cov.get("gaps"), "verdict": "✅ 可核实"},
        "current_goal_focus": {
            "phrase_fragments_n": len((snap["current_goal_focus"]["value"] or {}).get("phrase_fragments") or []),
            "cross_source_n": len((snap["current_goal_focus"]["value"] or {}).get("cross_source_phrases") or []),
            "explicit_goal_sentence": "unknown",
            "verdict": "🟡 部分（只有词面片段 · ⛔ 不臆造目标句）",
        },
    }


def _dist(xs):
    d = {}
    for x in xs:
        d[x] = d.get(x, 0) + 1
    return dict(sorted(d.items()))


# ─────────────────────────────────────────────────────────────────────────────
# C · 固定版本 Retrieval 对照（4 组 · 同一 corpus_version）
# ─────────────────────────────────────────────────────────────────────────────
def to_request(snap, mode, max_cand=12):
    trv = snap["target_refs"]["value"] if snap["target_refs"]["state"] == "provided" else {}
    refs = [x["ref"] for x in (trv.get("from_activity") or []) if x["exists"] in USABLE_EXISTS]
    refs += [x["ref"] for x in (trv.get("from_reasoning") or []) if x["exists"] in USABLE_EXISTS]
    refs = sorted(set(refs))
    phrases = [t["phrase"] for t in (snap["work_topic"]["value"] or [])][:12]
    work = {}
    if mode in ("A", "B", "C", "D"):
        work["target_refs"] = {"state": "provided" if refs else "unknown", "value": refs}
    if mode in ("B", "C", "D"):
        work["work_topic"] = {"state": "provided" if phrases else "unknown", "value": " ".join(phrases)}
    if mode == "D":
        wt = (snap["work_type_hint"]["value"] or {}).get("hint")
        work["work_type"] = {"state": "provided" if wt and wt != "unknown" else "unknown", "value": wt}
        work["action"] = {"state": "unknown"}
    req = {"request_id": "ctx-%s" % mode, "need": {"state": "unknown"}, "work": work,
           "budget": {"max_candidates": max_cand, "max_per_source": 3, "per_source_quota": 1}}
    if mode == "C":
        req["search_terms"] = phrases
    return {"request": req}, refs, phrases


def strong_weak(cands):
    s = w = 0
    for c in cands:
        bas = {e.get("basis") for e in (c.get("evidence") or [])}
        if bas & set(STRONG_BASIS):
            s += 1
        elif bas & set(WEAK_BASIS):
            w += 1
    return s, w


def retrieval_compare(payload, max_cand=12, dump=None):
    snap = csp.build(payload, None)
    rows, cvs, phrase_set, detail = [], set(), set(), {}
    for mode in ("A", "B", "C", "D"):
        req, refs, phrases = to_request(snap, mode, max_cand)
        phrase_set |= {p for p in phrases if len(p) >= 3}
        out = rp.run(req, max_cand)
        if not out.get("ok"):
            rows.append({"mode": mode, "error": out.get("request_errors")})
            continue
        cands = out["candidates"]
        s, w = strong_weak(cands)
        desc_blob = " ".join((c.get("preview") or "") for c in cands)
        overlap = sorted({p for p in phrase_set if p and p in desc_blob})
        cvs.add(out["corpus_version"]["fingerprint_sha12"])
        detail[mode] = [{
            "name": c["name"], "source": c["source"]["id"], "scope": c["source"]["scope"],
            "role": c["role"], "kind": c["kind"],
            "path": c.get("local_path") or c.get("remote_path"),
            "repo": c.get("remote_repo"),
            "preview": (c.get("preview") or "")[:200],
            "hit_channels": c["hit_channels"],
            "evidence_basis": sorted({e.get("basis") for e in (c.get("evidence") or [])}),
            "evidence_matched": sorted({m for e in (c.get("evidence") or [])
                                        for m in (e.get("matched") or [])})[:8],
            "strong": bool({e.get("basis") for e in (c.get("evidence") or [])} & set(STRONG_BASIS)),
        } for c in cands]
        rows.append({
            "mode": mode, "request_fields": sorted((req["request"].get("work") or {}).keys())
            + (["search_terms"] if "search_terms" in req["request"] else []),
            "candidates": len(cands),
            "sources": out["diversity"]["sources_represented"],
            "channels": out["diversity"]["channels_used"],
            "strong_evidence": s, "weak_only": w,
            "phrase_overlap": overlap[:6],
            "weak_share": round(w / float(len(cands)), 3) if cands else None,
        })
    rep = {"rows": rows, "corpus_fingerprints": sorted(cvs),
           "same_corpus_version": len(cvs) == 1,
           "note": "🔴 `strong_evidence/weak_only` 是**证据质量**读数，⛔ **不是相关性真值**；"
                   "⛔ 不可只比候选数量"}
    if dump:
        ev = payload.get("events") or []
        acts = [{"seq": e.get("seq"), "tool": e.get("tool"), "paths": e.get("path_hints")}
                for e in ev if e["kind"] == "tool-call" and e.get("path_hints")][:80]
        dels = sorted({p for e in ev if e["kind"] == "tool-call"
                       and str(e.get("tool") or "").lower() in ("edit", "write")
                       for p in (e.get("path_hints") or [])})
        rep["dump_path"] = dump
        with io.open(dump, "w", encoding="utf-8") as f:
            json.dump({
                "session": payload.get("session"),
                "task_context": "（由调用方填写 · 不得含推理原文）",
                "independent_work_evidence": {
                    "note": "🔴 这是**原始工具证据**（⛔ 不是 Runtime 派生字段）",
                    "tool_activity_sample": acts,
                    "files_edited_or_written": dels,
                },
                "corpus_fingerprint": sorted(cvs),
                "groups": detail,
                "instruction_to_reviewer": (
                    "逐候选判 relevant / partial / irrelevant，**只依据 independent_work_evidence "
                    "与仓库真实产物**；⛔ 不得用 snapshot 派生字段当真值；"
                    "并指出是否存在『表面相关但任务层面无关』的候选"),
            }, f, ensure_ascii=False, indent=1)
    return rep


def _eval(payload, dump=None):
    return {"reconstruction": reconstruction_check(payload),
            "fields": field_eval(payload),
            "retrieval_compare": retrieval_compare(payload, dump=dump)}


def _synth():
    return csp._synth()


def selftest():
    ok = []

    def check(n, c):
        ok.append((n, bool(c)))

    p = _synth()
    rc = reconstruction_check(p, points=3)
    check("A-reconstruction-ok", rc["ok"] and rc["points"] >= 2)
    check("A-no-future-leak", rc["no_future_leak"] is True and rc["leak_total"] == 0)
    check("A-monotone", rc["monotone_nondecreasing"] is True)
    check("A-future-excluded-reported", all("future_excluded" in r for r in rc["rows"]))
    fe = field_eval(p)
    check("B-targetrefs-has-independent-truth",
          "文件系统" in fe["target_refs"]["independent_truth"]
          and fe["target_refs"]["verdict"].startswith(("✅", "🟡", "⚪")))
    check("B-split-groups-present",
          fe["target_refs"]["activity_only_n"] >= 1 or fe["target_refs"]["reasoning_only_n"] >= 1)
    check("B-direction-window-compared", set(fe["direction_change"]["by_window"]) == {"W=2", "W=3", "W=5"})
    check("B-blockers-crosschecked", fe["blockers_unresolved"]["consistent"] is True)
    check("B-goal-not-fabricated", fe["current_goal_focus"]["explicit_goal_sentence"] == "unknown")
    check("B-per-field-verdicts", all("verdict" in fe[k] for k in
                                      ("target_refs", "work_topic", "direction_change",
                                       "blockers_unresolved", "evidence_coverage")))
    snap = csp.build(p, None)
    reqB, _, _ = to_request(snap, "B")
    reqD, _, _ = to_request(snap, "D")
    check("C-mode-b-excludes-work-type", "work_type" not in (reqB["request"]["work"] or {}))
    check("C-mode-d-control-has-work-type", "work_type" in (reqD["request"]["work"] or {}))
    check("C-mode-c-has-search-terms", "search_terms" in to_request(snap, "C")[0]["request"])
    failed = [n for n, c in ok if not c]
    print(json.dumps({"selftest": {"total": len(ok), "passed": len(ok) - len(failed), "failed": failed}},
                     ensure_ascii=False))
    return 0 if not failed else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    dump = None
    for a in sys.argv[1:]:
        if a.startswith("--dump="):
            dump = a.split("=", 1)[1]
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig") or "{}")
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": "bad-input", "detail": str(exc)[:80]}) + "\n")
        return 2
    rep = {"ok": True, "session": payload.get("session"), "eval": _eval(payload, dump=dump)}
    sys.stdout.write(json.dumps(rep, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
