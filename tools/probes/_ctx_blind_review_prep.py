#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_ctx_blind_review_prep.py — 三会话·产品优先的候选相关性盲判：**准备器**（只读）

指令（唯一新增验证任务）：
  · **两个产品对话**分别作为核心样本，⛔ 不合并平均；第三个真实会话作对照
  · 沿用 **A/B/C/D** 四组，同一 `corpus_version`，⛔ 不改语料 / 匹配规则 / 评分阈值
  · **逐时点评估**：在预先选定的工作时点用对应 `as-of-seq` 快照，⛔ 禁止未来信息泄漏
  · 盲判者**看不到组别 / 召回理由 / 评分 / 预期**，但必须拿到足够的独立工作证据
  · 读数必须区分：**候选记录数** vs **去重后实际对象数** vs **相关的唯一对象数** vs
    **重复承载数** vs **已知相关但未召回的材料** vs **新增字段的增量效果**

🔴 本文件的两个关键设计（回应 的两条要求）
  ① **候选记录 ID 与底层材料对象身份分开**：保留全部原始记录，同时用
     `object_key` 归并底层对象（依据：来源侧 `declared_source` 显式登记 → 归一化名称 → 内容 hash），
     ⛔ 不因合并而丢掉载体差异（每个对象的 `carriers[]` 保留来源/路径/版本）
  ② **"已知相关但未召回"可机械分离**：把该时点**之前已实际产出**的文件路径作为"已知相关材料"，
     分别判定 `not_in_corpus`（材料根本不在池 ⇒ 根因 a）与 `in_corpus_not_recalled`（在池但没召回 ⇒ 匹配问题）
     ⇒ 这把"Runtime 的理解问题"与"Retrieval 的覆盖问题"**分开**

纪律：⛔ 只读 · ⛔ 不落推理原文（输出只有候选元数据 / 路径 / 计数）· ⛔ 不改检索规则
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
import _ctx_snapshot_eval as cse       # noqa: E402
import _retrieval_request_probe as rp  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

MODES = ("A", "B", "C", "D")
EDIT_TOOLS = ("edit", "write")


def norm_name(n):
    """归一化名称（**机械可解释**）：去扩展名 / 去尾部编号 / 去项目前缀 / 统一分隔符。"""
    s = str(n or "").lower().strip()
    s = re.sub(r"\.(md|py|ts|mjs|json|ps1)$", "", s)
    s = re.sub(r"[-_]\d{1,3}$", "", s)
    s = re.sub(r"^(aios|dsh|ai-os)[-_]", "", s)
    return s.replace("_", "-")


def object_key(c):
    """底层对象身份（⛔ 与候选记录 id 分离）。优先级：显式登记 > 归一化名 > 内容 hash。"""
    ds = str(c.get("declared_source") or "").strip()
    if ds:
        return "declared:" + norm_name(ds)
    nn = norm_name(c.get("name"))
    if nn:
        return "name:" + nn
    return "rec:" + str(c.get("id"))


def carrier_of(c):
    return {"record_id": c.get("id"), "name": c.get("name"), "source": c["source"]["id"],
            "path": c.get("local_path") or c.get("remote_path"),
            "version": c.get("version") or (c.get("freshness") or {}).get("sha256_12") or "",
            "kind": c.get("kind"), "role": c.get("role"),
            "preview": (c.get("preview") or "")[:180],
            "hit_channels": c.get("hit_channels"),
            "evidence_basis": sorted({e.get("basis") for e in (c.get("evidence") or [])}),
            "strong": bool({e.get("basis") for e in (c.get("evidence") or [])} & set(cse.STRONG_BASIS)),
            "declared_source": c.get("declared_source") or ""}


def timepoints(payload, quantiles):
    seqs = sorted(e.get("seq") or 0 for e in payload.get("events") or [])
    if not seqs:
        return []
    return sorted({seqs[min(len(seqs) - 1, int((len(seqs) - 1) * q))] for q in quantiles})


def prep(payload, quantiles=(0.30, 0.80), max_cand=12):
    evs = payload.get("events") or []
    # 候选池路径集合（用于"已知相关但未召回"的机械分离）
    descs, _status = rp.load_sources({"need": {"state": "unknown"}, "work": {}})
    pool = set()
    for d in descs:
        for k in ("local_path", "remote_path"):
            v = d.get(k)
            if v:
                pool.add(str(v).replace("\\", "/").lower())

    tp_rows, objects = [], {}
    for p in timepoints(payload, quantiles):
        snap = csp.build(payload, p)
        groups, rec2obj = {}, {}
        for mode in MODES:
            req, refs, _ph = cse.to_request(snap, mode, max_cand)
            out = rp.run(req, max_cand)
            if not out.get("ok"):
                groups[mode] = []
                continue
            objs, recs = [], []
            for c in out["candidates"]:
                k = object_key(c)
                recs.append(c["id"])
                rec2obj[c["id"]] = k
                objs.append(k)
                cur = objects.setdefault(k, {"object_key": k, "name": c.get("name"),
                                             "carriers": [], "groups": set(), "timepoints": set()})
                if not any(x["record_id"] == c["id"] for x in cur["carriers"]):
                    cur["carriers"].append(carrier_of(c))
                cur["groups"].add(mode)
                cur["timepoints"].add(p)
            groups[mode] = {"records": recs, "unique_objects": sorted(set(objs)),
                            "record_count": len(recs), "object_count": len(set(objs)),
                            "repeated_carriers": len(recs) - len(set(objs)),
                            "corpus_fingerprint": out["corpus_version"]["fingerprint_sha12"]}
        # 已知相关材料：该时点**之前已实际 edit/write** 的文件
        produced = sorted({str(x).replace("\\", "/") for e in evs
                           if (e.get("seq") or 0) <= p and e["kind"] == "tool-call"
                           and str(e.get("tool") or "").lower() in EDIT_TOOLS
                           for x in (e.get("path_hints") or [])})
        known = []
        for w in produced:
            wl = w.lower()
            recalled = sorted({m for m in MODES if wl in
                               [str(r).lower() for r in groups[m]["records"]]})
            known.append({"path": w, "in_corpus": wl in pool,
                          "recalled_by": recalled,
                          "missing_kind": ("recalled" if recalled else
                                           ("in_corpus_not_recalled" if wl in pool else "not_in_corpus"))})
        tp_rows.append({
            "as_of_seq": p,
            "snapshot": {"as_of": snap["snapshot"]["as_of"],
                         "future_events_excluded": snap["snapshot"]["future_events_excluded"],
                         "no_future_leak": True},
            "groups": groups,
            "known_relevant_materials": known,
            "known_summary": {
                "produced_total": len(known),
                "recalled_by_any_group": sum(1 for k in known if k["recalled_by"]),
                "in_corpus_not_recalled": sum(1 for k in known if k["missing_kind"] == "in_corpus_not_recalled"),
                "not_in_corpus": sum(1 for k in known if k["missing_kind"] == "not_in_corpus"),
            },
        })

    cand_objects = []
    for k, v in objects.items():
        v["groups"] = sorted(v["groups"])
        v["timepoints"] = sorted(v["timepoints"])
        cand_objects.append(v)
    cand_objects.sort(key=lambda o: (o["object_key"]))

    acts = [{"seq": e.get("seq"), "tool": e.get("tool"), "paths": e.get("path_hints")}
            for e in evs if e["kind"] == "tool-call" and e.get("path_hints")][:120]
    produced_all = sorted({str(x).replace("\\", "/") for e in evs
                           if e["kind"] == "tool-call"
                           and str(e.get("tool") or "").lower() in EDIT_TOOLS
                           for x in (e.get("path_hints") or [])})
    fps = sorted({t["groups"][m]["corpus_fingerprint"] for t in tp_rows for m in MODES
                  if t["groups"].get(m)})
    return split_views(payload, tp_rows, cand_objects, acts, produced_all, fps)


def split_views(payload, tp_rows, cand_objects, acts, produced_all, fps):
    """🔴 两个视图必须分开：盲判视图（⛔ 无组别/召回理由） vs 本地归因映射。"""
    REVIEW_CARRIER_KEYS = ("name", "source", "path", "kind", "role", "preview", "version",
                           "declared_source")
    review_objects = [{
        "object_key": o["object_key"], "name": o["name"], "carrier_count": len(o["carriers"]),
        "carriers": [{k: c.get(k) for k in REVIEW_CARRIER_KEYS} for c in o["carriers"]],
    } for o in cand_objects]
    local_map = {o["object_key"]: {"groups": o["groups"], "timepoints": o["timepoints"],
                                   "record_ids": [c["record_id"] for c in o["carriers"]],
                                   "sources": sorted({c["source"] for c in o["carriers"]}),
                                   "any_strong": any(c["strong"] for c in o["carriers"])}
                 for o in cand_objects}
    review = {
        "session": payload.get("session"), "corpus_fingerprints": fps,
        "timepoint_count": len(tp_rows), "candidate_objects": review_objects,
        "independent_work_evidence": {
            "note": "🔴 原始工具证据（⛔ 不是 Runtime 派生字段）",
            "tool_activity_sample": acts, "files_produced_by_session": produced_all},
        "instruction_to_reviewer": (
            "逐 **candidate_objects** 判 relevant / partial / irrelevant，"
            "只依据 independent_work_evidence 与仓库真实产物；⛔ 组别、召回理由、评分与实验预期"
            "**均不提供**，也不得推测。请指出哪些候选只是『表面相关但任务层面无关』，"
            "并对同一对象的多个 carrier 说明它们是不是同一份材料。"),
        "discipline": "只读 · 无推理原文 · 不改语料/匹配规则/评分",
    }
    local = {"session": payload.get("session"), "corpus_fingerprints": fps,
             "timepoints": tp_rows, "object_map": local_map,
             "note": "🔴 本地归因映射（组别 / 时点 / 记录 id）· ⛔ 绝不传给盲判者"}
    return review, local


def _summary(local):
    """本地读数摘要（组级归因读数 · 该摘要**不进盲判视图**）。"""
    return {
        "ok": True, "session": local["session"], "dump": None,
        "corpus_fingerprints": local["corpus_fingerprints"],
        "timepoints": [{"as_of_seq": t["as_of_seq"], "known_summary": t["known_summary"],
                        "groups": {m: {"records": t["groups"][m]["record_count"],
                                       "objects": t["groups"][m]["object_count"],
                                       "repeated": t["groups"][m]["repeated_carriers"]}
                                   for m in MODES if t["groups"].get(m)}} for t in local["timepoints"]],
        "candidate_objects": len(local["object_map"]),
    }


def main():
    dump, qs = None, (0.30, 0.80)
    for a in sys.argv[1:]:
        if a.startswith("--dump="):
            dump = a.split("=", 1)[1]
        elif a.startswith("--quantiles="):
            qs = tuple(float(x) for x in a.split("=", 1)[1].split(","))
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig") or "{}")
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": "bad-input", "detail": str(exc)[:80]}) + "\n")
        return 2
    review, local = prep(payload, qs)
    if dump:
        with io.open(dump, "w", encoding="utf-8") as f:
            json.dump(review, f, ensure_ascii=False, indent=1)
        with io.open(dump.replace(".json", ".map.json"), "w", encoding="utf-8") as f:
            json.dump(local, f, ensure_ascii=False, indent=1)
    s = _summary(local)
    s["dump"] = dump
    s["objects_with_multiple_carriers"] = sum(1 for o in review["candidate_objects"]
                                             if o["carrier_count"] > 1)
    sys.stdout.write(json.dumps(s, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
