#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_d1_diag_and_aggregate.py — 的**根因诊断**与**盲判汇总**（只读）

两个模式（互不依赖）：
  `--mode=diag`  词面重合诊断：把扩展语料材料的**检索面词集合**与
                 该时点 Runtime 字段（`work_topic` 短语 + `target_refs`）的**词集合**求交，
                 机械量化"**两侧是否在同一个词面空间**"。
                 ⇒ 用来验证 §2.1 的根因判断（跨语言/跨形态），⛔ 不修改任何匹配规则
  `--mode=agg`   盲判汇总：读 `--verdicts=<json>`（`{object_key|basename: verdict}`），
                 与 `_d1_ab_*.json` 的 `new_objects_extended_vs_base` 交叉 ⇒
                 **新增对象中相关的数量** · 全候选的相关分布（的核心指标）

纪律：⛔ 只读 · ⛔ 不改评分/闸门/匹配规则 · ⛔ 不落推理原文
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
import _retrieval_request_probe as rp  # noqa: E402
import _ctx_snapshot_eval as cse       # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass


def _toks(text):
    return {t for t in rp.ep.tokenize(str(text)) if rp.ep.is_meaningful(t)}


def runtime_tokens(payload, as_of):
    """该时点 Runtime 侧的**词集合**（来自 `work_topic` 短语 + `target_refs` + `need`）。"""
    snap = csp.build(payload, as_of)
    parts = []
    for t in (snap["work_topic"]["value"] or []):
        parts.append(t["phrase"])
    trv = snap["target_refs"]["value"] if snap["target_refs"]["state"] == "provided" else {}
    parts += [x["ref"] for x in (trv.get("from_activity") or [])]
    parts += [x["ref"] for x in (trv.get("from_reasoning") or [])]
    if snap["current_goal_focus"]["value"]:
        parts += (snap["current_goal_focus"]["value"].get("phrase_fragments") or [])
    out = set()
    for s in parts:
        out |= _toks(s)
    return out, {"phrases": len(snap["work_topic"]["value"] or []),
                 "target_refs": len(parts) - len(snap["work_topic"]["value"] or [])}


def diag(payload, as_of):
    os.environ["AIOS_D1_EXTENDED"] = "1"
    rt, meta = runtime_tokens(payload, as_of)
    descs, _st = rp.load_sources({"need": {"state": "unknown"}, "work": {}})
    rows = []
    for d in descs:
        if d["source"]["id"] != rp.D1_SOURCE_ID:
            continue
        blob = " ".join([str(d.get("name") or ""), str(d.get("description") or ""),
                         " ".join(d.get("search_keys", {}).get("sample") or [])])
        mt = _toks(blob)
        inter = mt & rt
        rows.append({"path": str(d.get("local_path") or ""),
                     "root": str(d.get("declared_source") or ""),
                     "material_tokens": len(mt), "overlap": len(inter),
                     "common": sorted(inter)[:8]})
    by_root = {}
    for r in rows:
        b = by_root.setdefault(r["root"], {"materials": 0, "with_overlap": 0, "overlap_sum": 0})
        b["materials"] += 1
        if r["overlap"] > 0:
            b["with_overlap"] += 1
        b["overlap_sum"] += r["overlap"]
    for b in by_root.values():
        b["overlap_rate"] = round(b["with_overlap"] / float(b["materials"]), 3) if b["materials"] else None
        b["avg_overlap"] = round(b["overlap_sum"] / float(b["materials"]), 2) if b["materials"] else None
    top = sorted(rows, key=lambda r: (-r["overlap"], r["path"]))[:10]
    return {"as_of_seq": as_of, "runtime_tokens": len(rt), "runtime_meta": meta,
            "runtime_token_sample": sorted(rt)[:20],
            "materials": len(rows), "by_root": by_root, "top_overlap": top,
            "note": "🔴 overlap=0 ⇔ 材料与 Runtime 字段**没有共同词** ⇒ 无论用什么字段都召不回它"}


def agg(ab_path, verdicts):
    with io.open(ab_path, "r", encoding="utf-8-sig") as f:
        ab = json.load(f)
    norm = {}
    for k, v in verdicts.items():
        key = str(k).split(":")[-1].lower()
        norm[key] = v
    out = {"session": ab.get("session"), "timepoints": []}
    for t in ab.get("timepoints") or []:
        newp = [str(x).split("/")[-1].lower() for x in (t.get("new_objects_extended_vs_base") or [])]
        vd = [norm.get(b, "unjudged") for b in newp]
        out["timepoints"].append({
            "as_of_seq": t["as_of_seq"],
            "known_related_total": t["known_related_total"],
            "coverage": {"base": t["known_in_corpus_base"], "extended": t["known_in_corpus_extended"]},
            "recall": {"base": t["known_recalled_base"], "extended": t["known_recalled_extended"]},
            "new_objects": len(newp),
            "new_relevant": sum(1 for v in vd if v == "relevant"),
            "new_partial": sum(1 for v in vd if v == "partial"),
            "new_irrelevant": sum(1 for v in vd if v == "irrelevant"),
            "new_unjudged": sum(1 for v in vd if v == "unjudged"),
            "new_object_verdicts": [{"file": b, "verdict": v} for b, v in zip(newp, vd)],
        })
    allv = list(norm.values())
    out["verdict_totals"] = {k: sum(1 for v in allv if v == k)
                             for k in ("relevant", "partial", "irrelevant", "unjudged")}
    return out


def main():
    mode = "diag"
    verdicts, ab_path = None, None
    for a in sys.argv[1:]:
        if a.startswith("--mode="):
            mode = a.split("=", 1)[1]
        elif a.startswith("--verdicts="):
            verdicts = a.split("=", 1)[1]
        elif a.startswith("--ab="):
            ab_path = a.split("=", 1)[1]
    if mode == "agg":
        if not verdicts or not ab_path:
            sys.stdout.write(json.dumps({"ok": False, "error": "need --verdicts and --ab"}) + "\n")
            return 2
        with io.open(verdicts, "r", encoding="utf-8-sig") as f:
            v = json.load(f)
        sys.stdout.write(json.dumps(agg(ab_path, v), ensure_ascii=False) + "\n")
        return 0
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig") or "{}")
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": "bad-input", "detail": str(exc)[:80]}) + "\n")
        return 2
    as_of = None
    for a in sys.argv[1:]:
        if a.startswith("--as-of="):
            as_of = int(a.split("=", 1)[1])
    sys.stdout.write(json.dumps({"ok": True, "session": payload.get("session"),
                                 "diag": diag(payload, as_of)}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
