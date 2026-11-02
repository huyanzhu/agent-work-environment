#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_ctx_snapshot_probe.py — 阶段七 **主线**：Context Snapshot 构建（只读 · 可复跑）

阶段七主线问题（原文）：
    *"Runtime 能否**仅依靠宿主已提供的上下文**，逐步形成足以指导能力发现的、
      可追溯且与实际工作一致的工作表示？"*

🔴 **三条核心原则（明确 · 本文件逐条落实）**
   ① **区分"Agent 正在谈论什么"与"宿主实际正在做什么"** ——
      `target_refs` **分两列**：`from_reasoning`（提到）vs `from_activity`（真的动了），
      ⛔ **不合并**；不一致时**并列呈现**。
   ② **reasoning 的假设 / 试探 / 已放弃方向不能直接当事实** ——
      每条声明带 `strength`：`attested`(用户原话) / `verified`(工具活动) /
      `provisional`(reasoning 陈述) / `superseded`(被后续修正推翻)。
   ③ **不强制压成一个工作类型** —— `work_type_hint` 是**非强制辅助**（`advisory: true`，
      `not_for_filtering: true`），⛔ 不作硬过滤、⛔ 不决定检索通道。

🔴 **逐步重建（明确：避免未来泄漏）**：`--as-of-seq N` 只用 `seq <= N` 的事件，
   并显式报告被排除的未来事件数。⛔ 不用未来结果去解释早期判断。

🔴 **`work_topic` 保留多词短语与语义关系**（明确）—— ⛔ 不拆成无法区分次序的词袋。

纪律：⛔ 不落推理原文（只出短语 / 路径 / 计数 / 时点）· ⛔ 不改本体 / 评分 / 闸门 / 语料
规则复用：`scratch/_work_semantics_probe.py`（唯一一套词面规则与行为交叉核实）
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

import _work_semantics_probe as ws  # noqa: E402  （复用 PATH_RE / TOPIC_TERMS / 行为交叉核实）

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

CJK = re.compile(u"[\u4e00-\u9fff]")
ASCIIW = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}")
# 代码/正则特征 —— 读数：推理文本里的**代码片段与正则**会被 PATH_RE 当成"对象引用"
#    （反例：`^def |^class |^[A-Z_]+ = ` · `add_argument|def main` · `task_cards/.../X.md`）
#    ⇒ 提取后**必须清洗**，否则"谈论过什么"这一列会被垃圾淹没。
CODEISH = re.compile(r"[|^$*()\[\]{}<>#]|\.\.\.|^\s|\s$")
#: 强修正标记（**可解释的方向变化证据**）
REVISION_MARKERS_STRONG = (u"改为", u"不再", u"放弃", u"撤回", u"转向", u"换成", u"instead",
                           u"rather than", u"revised to")
# 弱标记（**只计数 · 不驱动判定** —— 读数"其实"在真实推理里出现 59 次，噪声极大）
REVISION_MARKERS_WEAK = (u"其实", u"重新", u"更正", u"修正方向", u"revert")
#: 未决 / 阻塞标记
UNRESOLVED_MARKERS = (u"待", u"尚未", u"未验证", u"未核实", u"需要确认", u"不确定", u"未知",
                      u"TODO", u"UNKNOWN", u"blocked", u"待裁", u"悬而未决")


def clean_refs(pairs):
    """(ref, seq) 序列 → {ref: seq}（**去代码特征 · 统一分隔符 · 去重**）。"""
    out = {}
    for r, seq in pairs:
        s = str(r).replace("\\", "/").strip()
        if not s or len(s) > 160:
            continue
        if "//" in s or CODEISH.search(s):
            continue
        if "/" not in s and "." not in s:
            continue
        out.setdefault(s, seq)
    return out

STRENGTH_BY_SOURCE = {"user": "attested", "tool": "verified", "reasoning": "provisional",
                      "lifecycle": "verified"}


def _field(state, value, claims, confidence, note=None):
    return {"state": state, "value": value, "claims": claims, "confidence": confidence, "note": note}


def _claim(ref, source_kind, seq=None, turn=None, step=None, basis=None, strength=None):
    return {"ref": str(ref)[:160], "source_kind": source_kind,
            "strength": strength or STRENGTH_BY_SOURCE.get(source_kind, "provisional"),
            "at": {"seq": seq, "turn": turn, "step": step}, "basis": basis}


# ─────────────────────────────────────────────────────────────────────────────
# 短语提取（**多词 · 保序 · 带邻接**）—— ⛔ 不返回词袋
# ─────────────────────────────────────────────────────────────────────────────
LEFT_ASCII = re.compile(r"([A-Za-z][A-Za-z0-9_\-]{1,})\s*$")
RIGHT_ASCII = re.compile(r"\s*([A-Za-z][A-Za-z0-9_\-]{1,})")


def extract_phrases(text, terms, topk=18, win=6):
    """对已知术语，取其**左右邻接**构成多词短语（保留语序与邻接关系）。

    ⛔ 与 `tokenize` 的差别：`tokenize` 丢弃次序（`'context assembly'` == `'assembly context'`），
       本函数**保留邻接**，因此可以用作 Retrieval 的短语匹配输入。

    ⚠️ 性能（读数修正）：**不得**用 `text[:i]` / `text[j:]` 切片 —— 每个命中都复制整个前缀，
       在 300KB 级推理文本上退化为 O(n²)（本机读数直接把评估跑到超时）。
       改为**固定 40 字符窗口**切片。
    """
    counts, first_at = {}, {}
    for t in terms:
        if t not in text:
            continue
        start = 0
        while True:
            i = text.find(t, start)
            if i < 0:
                break
            start = i + len(t)
            j = i + len(t)
            left = ""
            k = i
            while k > 0 and len(left) < 4 and CJK.match(text[k - 1]):
                left = text[k - 1] + left
                k -= 1
            if not left:
                mm = LEFT_ASCII.search(text[max(0, i - 40):i])
                if mm:
                    left = mm.group(1) + " "
            right = ""
            k = j
            while k < len(text) and len(right) < win and CJK.match(text[k]):
                right += text[k]
                k += 1
            if not right:
                mm = RIGHT_ASCII.match(text[j:j + 40])
                if mm:
                    right = " " + mm.group(1)
            phrase = re.sub(r"\s+", " ", (left + t + right).strip())
            if len(phrase) < 2 or len(phrase) > 24:
                continue
            counts[phrase] = counts.get(phrase, 0) + 1
            if phrase not in first_at:
                first_at[phrase] = i
    rows = [{"phrase": p, "count": c} for p, c in counts.items() if c >= 2]
    if not rows:                     # 短输入（合成样本 / 单条消息）⇒ 退回低支持度，但仍**保序**
        rows = [{"phrase": p, "count": c} for p, c in counts.items()]
    rows.sort(key=lambda r: (-r["count"], -len(r["phrase"]), r["phrase"]))
    return rows[:topk]


_PATHS = None
_EXTRA_ROOTS = None


def extra_roots():
    """额外核实根（**环境变量 `AIOS_EXTRA_ROOTS`** · pathsep 分隔 · 只读）。

    ⚠️ 读数修正：真实工作的对象常常**不在 AI-OS 仓库**里
    （产品会话的工作区是 `D:\\AI\\projects\\demo-project-v2`）⇒
    只查 `AIOS_ROOT` 会把**真实存在的引用**系统性判成 `not-found`
    （读数两个产品会话的 reasoning 可用率被低估到 0.017 / 0.069）。
    """
    global _EXTRA_ROOTS
    if _EXTRA_ROOTS is None:
        raw = os.environ.get("AIOS_EXTRA_ROOTS", "")
        _EXTRA_ROOTS = [os.path.abspath(p) for p in raw.split(os.pathsep)
                        if p.strip() and os.path.isdir(p)]
    return _EXTRA_ROOTS


_SKIP_DIRS = (".git", "node_modules", "__pycache__", ".next", "dist", "build")


def repo_paths():
    """全部核实根下的相对路径（小写 · 带根标记 `R0|` / `RX|`）—— 供**后缀唯一匹配**用。"""
    global _PATHS
    if _PATHS is None:
        s = set()
        for i, root in enumerate([AIOS_ROOT] + extra_roots()):
            tag = "R0|" if i == 0 else "RX|"
            for base, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                for f in files:
                    rel = os.path.relpath(os.path.join(base, f), root).replace("\\", "/").lower()
                    s.add(tag + rel)
        _PATHS = s
    return _PATHS


def exists_class(ref):
    """对象引用存在性核实：`exists` | `exists-product-root` | `exists-suffix` | `ambiguous-suffix` | `not-found`。"""
    raw = str(ref).strip().replace("\\", "/")
    norm = raw[2:] if raw.startswith("./") else raw
    for i, root in enumerate([AIOS_ROOT] + extra_roots()):
        if os.path.exists(os.path.normpath(os.path.join(root, norm))):
            return "exists" if i == 0 else "exists-product-root"
    suf = norm.lower()
    hits = sum(1 for p in repo_paths() if p.endswith("|" + suf) or p.endswith("/" + suf))
    if hits == 1:
        return "exists-suffix"
    if hits > 1:
        return "ambiguous-suffix"
    return "not-found"


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot 构建
# ─────────────────────────────────────────────────────────────────────────────
def build(payload, as_of_seq=None, window=3):
    evs = payload.get("events") or []
    probe = payload.get("probe") or {}
    seqs = [e.get("seq") or 0 for e in evs]
    if as_of_seq is None:
        as_of_seq = max(seqs) if seqs else 0
    used = [e for e in evs if (e.get("seq") or 0) <= as_of_seq]
    excluded = len(evs) - len(used)

    users = [e for e in used if e["kind"] == "user"]
    reas = [e for e in used if e["kind"] == "reasoning"]
    calls = [e for e in used if e["kind"] == "tool-call"]
    results = [e for e in used if e["kind"] == "tool-result"]
    rtext = "\n".join(e.get("text") or "" for e in reas)
    utext = "\n".join(e.get("text") or "" for e in users)

    snap = {
        "snapshot": {"session": payload.get("session"),
                     "as_of": {"seq": as_of_seq,
                               "turn": (reas[-1].get("turn") if reas else None),
                               "step": (reas[-1].get("step") if reas else None),
                               "at": (used[-1].get("at") if used else None)},
                     "events_used": len(used), "future_events_excluded": excluded,
                     "no_future_leak": True,
                     "rule": "⛔ 只用 seq<=as_of 的事件（避免把未来结果泄漏给早期判断）"},
        "principles": {
            "talk_vs_do": "target_refs 分 from_reasoning / from_activity 两列，⛔ 不合并",
            "strength": "attested(用户原话) / verified(工具活动) / provisional(reasoning) / superseded",
            "no_forced_type": "work_type_hint 仅 advisory · 不作硬过滤 · 不决定检索通道",
            "phrases": "work_topic 是多词短语（保序），⛔ 不是词袋",
            "no_raw_text": "只出短语/路径/计数/时点，⛔ 不出推理原文",
        },
    }

    # ── ① current_goal_focus（用户意图 + 近期上下文的短语 · 不确定即 unknown）──
    u_ph = {p["phrase"] for e in users[-2:] for p in extract_phrases(e.get("text") or "",
                                                                    ws.TOPIC_TERMS, topk=8)}
    r_ph = {p["phrase"] for p in extract_phrases(rtext, ws.TOPIC_TERMS, topk=17)}
    gc = []
    for e in users[-2:]:
        for p in extract_phrases(e.get("text") or "", ws.TOPIC_TERMS, topk=8):
            gc.append(_claim(p["phrase"], "user", seq=e.get("seq"),
                             basis="user-phrase(count=%d)" % p["count"]))
    cross = sorted(u_ph & r_ph)
    if not gc and reas:
        for p in extract_phrases(rtext, ws.TOPIC_TERMS, topk=8):
            gc.append(_claim(p["phrase"], "reasoning", seq=reas[-1].get("seq"),
                             basis="reasoning-phrase(count=%d)" % p["count"]))
    snap["current_goal_focus"] = (
        _field("provided",
               {"phrase_fragments": sorted(u_ph)[:10] if u_ph else sorted(r_ph)[:10],
                "cross_source_phrases": cross[:10],
                "explicit_goal_sentence": "unknown",
                "why_no_sentence": "⛔ Runtime **不臆造目标句** —— 词面片段 ≠ 完整目标；"
                                   "跨来源共同短语（用户 ∩ 推理）是当前最强的可用信号"},
               gc, "attested" if u_ph else "provisional",
               "来自用户消息短语（无用户消息时退回 reasoning 短语并降级）")
        if gc else _field("unknown", None, [], "unknown", "该时点没有用户消息与可用推理短语"))

    # ── ② activity_evidence（**verified** · 实际做了什么）──
    ac = []
    for c in calls[-12:]:
        ac.append(_claim("%s(%s)" % (c.get("tool"), ",".join(c.get("path_hints") or []) or "-"),
                         "tool", seq=c.get("seq"), turn=c.get("turn"), step=c.get("step"),
                         basis="tool-call"))
    ok_n = sum(1 for r in results if r.get("ok"))
    bad_n = sum(1 for r in results if r.get("error"))
    classes = {}
    for c in calls:
        classes[c.get("tool")] = classes.get(c.get("tool"), 0) + 1
    val = {"tool_calls": len(calls), "results_ok": ok_n, "results_error": bad_n,
           "by_tool": dict(sorted(classes.items()))} if calls else None
    snap["activity_evidence"] = (
        _field("provided", val, ac, "verified",
               "工具调用与结果 = **宿主实际做了什么**（⛔ 不解释为什么）")
        if calls else _field("known-absent", None, [], "unknown", "该时点没有任何工具调用"))

    # ── ③ target_refs（**双来源分离** —— 本文件的核心）──
    from_reasoning = clean_refs((t, e.get("seq")) for e in reas
                                for t in re.findall(ws.PATH_RE, e.get("text") or ""))
    from_activity = clean_refs((t, c.get("seq")) for c in calls
                               for t in (c.get("path_hints") or []))
    r_refs = [{"ref": k, "at_seq": v, "exists": exists_class(k), "source_kind": "reasoning",
               "strength": "provisional"} for k, v in sorted(from_reasoning.items())]
    a_refs = [{"ref": k, "at_seq": v, "exists": exists_class(k), "source_kind": "tool",
               "strength": "verified"} for k, v in sorted(from_activity.items())]
    rset = {x["ref"] for x in r_refs}
    aset = {x["ref"] for x in a_refs}
    both = rset & aset
    # 🔴 "第一种修正之后未再出现" **只作提示** —— 读数该启发式会过度标记（18/… 条），
    #    ⛔ 因此**不据此改 strength**、⛔ 不称其为"已放弃"
    not_rementioned = []
    strong_seq = None
    for e in reas:
        if any(m in (e.get("text") or "") for m in REVISION_MARKERS_STRONG):
            strong_seq = e.get("seq")
            break
    if strong_seq is not None:
        after = "\n".join((e.get("text") or "") for e in reas if (e.get("seq") or 0) > strong_seq)
        not_rementioned = sorted(x["ref"] for x in (a_refs + r_refs) if x["ref"] not in after)[:12]
    snap["target_refs"] = _field(
        "provided" if (r_refs or a_refs) else "unknown",
        {"from_reasoning": r_refs, "from_activity": a_refs,
         "agreement": sorted(both), "reasoning_only": sorted(rset - aset),
         "activity_only": sorted(aset - rset),
         "cleaning": "已去代码/正则特征 · 统一分隔符 · 去重（⛔ 未清洗前 81 条里有大量代码片段）",
         "interpretation": "⛔ 两列不合并：`reasoning_only` = **谈论过但该时点没动**；"
                           "`activity_only` = **实际动了但没在推理里提到**"},
        [_claim(x["ref"], x["source_kind"], seq=x["at_seq"],
                basis="path-in-%s(exists=%s)" % (x["source_kind"], x["exists"]))
         for x in (a_refs + r_refs)[:16]],
        "verified" if a_refs else ("provisional" if r_refs else "unknown"),
        "双来源分离 · 存在性已机械核实")
    snap["target_refs"]["not_rementioned_after_revision_marker"] = not_rementioned

    # ── ④ work_topic（**多词短语 · 保序**）──
    ph_r = extract_phrases(rtext, ws.TOPIC_TERMS)
    ph_u = extract_phrases(utext, ws.TOPIC_TERMS)
    merged = {}
    for p in ph_r:
        merged.setdefault(p["phrase"], {"phrase": p["phrase"], "count": 0, "sources": []})
        merged[p["phrase"]]["count"] += p["count"]
        merged[p["phrase"]]["sources"].append("reasoning")
    for p in ph_u:
        merged.setdefault(p["phrase"], {"phrase": p["phrase"], "count": 0, "sources": []})
        merged[p["phrase"]]["count"] += p["count"]
        merged[p["phrase"]]["sources"].append("user")
    topics = sorted(merged.values(), key=lambda r: (-r["count"], -len(r["phrase"])))[:16]
    snap["work_topic"] = _field(
        "provided" if topics else "unknown", topics,
        [_claim(t["phrase"], "user" if "user" in t["sources"] else "reasoning",
                basis="multiword-phrase(count=%d)" % t["count"]) for t in topics[:10]],
        "provisional" if topics else "unknown",
        "**多词短语**（保序 · 带邻接）· ⛔ 不是词袋；短语判别力高于单词（见阶段③ key_discrimination）")

    # ── ⑤ direction_change（步骤级 · 含修正标记）──
    per_step = {}
    for e in reas:
        key = (e.get("turn"), e.get("step"))
        per_step.setdefault(key, []).append(e)
    seq_steps = [{"turn": k[0], "step": k[1],
                  "phrases": {p["phrase"] for p in extract_phrases(
                      "\n".join(x.get("text") or "" for x in v), ws.TOPIC_TERMS, topk=10)},
                  "targets": set(re.findall(ws.PATH_RE, "\n".join(x.get("text") or "" for x in v)))}
                 for k, v in sorted(per_step.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1] or 0))]
    # 🔴 窗口比较（读数修正）：单步比较在**探索期**会误判（step2 就判 target-shift）
    #    ⇒ 用 W 步窗口的**累计集合**比较，且要求两侧都非空
    W = window
    dchange, at_step, detail = "unknown", None, []
    if len(seq_steps) >= 2 * W:
        for i in range(W, len(seq_steps) - W + 1):
            prev, nxt = seq_steps[i - W:i], seq_steps[i:i + W]
            pt = set().union(*[s["targets"] for s in prev])
            nt = set().union(*[s["targets"] for s in nxt])
            pp = set().union(*[s["phrases"] for s in prev])
            np_ = set().union(*[s["phrases"] for s in nxt])
            if pt and nt and not (pt & nt):
                dchange, at_step = "target-shift", {"turn": nxt[0]["turn"], "step": nxt[0]["step"]}
                detail.append("window-target-disjoint(W=%d)" % W)
                break
            if pp and np_ and not (pp & np_):
                dchange, at_step = "changed", {"turn": nxt[0]["turn"], "step": nxt[0]["step"]}
                detail.append("window-phrase-disjoint(W=%d)" % W)
                break
        if dchange == "unknown":
            dchange = "none-observed"
    elif len(seq_steps) > 1:
        dchange = "none-observed(样本不足 <2W)"
    strong_m = [{"seq": e.get("seq"), "marker": m, "turn": e.get("turn"), "step": e.get("step")}
                for e in reas for m in REVISION_MARKERS_STRONG if m in (e.get("text") or "")]
    weak_n = sum(1 for e in reas for m in REVISION_MARKERS_WEAK if m in (e.get("text") or ""))
    snap["direction_change"] = _field(
        "provided" if seq_steps else "unknown",
        {"change": dchange, "at": at_step, "basis": detail, "window": W,
         "revision_markers_strong": strong_m[:6], "revision_markers_strong_count": len(strong_m),
         "revision_markers_weak_count": weak_n,
         "not_rementioned_after_revision": not_rementioned,
         "prior_direction_still_valid": (None if not strong_m else "unknown(需 Agent 判断)")},
        [_claim("step@%s" % json.dumps(at_step, ensure_ascii=False), "reasoning",
                basis="step-level-%s" % dchange)] if at_step else [],
        "provisional", "方向变化**一律 provisional** —— ⛔ 不凭单个工具调用断定转向")

    # ── ⑥ blockers_unresolved（**两个来源分开**）──
    bl = []
    for r in results:
        if r.get("error"):
            bl.append(_claim("tool-error@turn%s/step%s" % (r.get("turn"), r.get("step")), "tool",
                             seq=r.get("seq"), turn=r.get("turn"), step=r.get("step"),
                             basis="tool-result.error"))
    um = []
    for e in reas:
        for m in UNRESOLVED_MARKERS:
            if m in (e.get("text") or ""):
                um.append({"marker": m, "turn": e.get("turn"), "step": e.get("step"), "seq": e.get("seq")})
                break
    snap["blockers_unresolved"] = _field(
        "provided" if (bl or um) else "unknown",
        {"verified_failures": [c["ref"] for c in bl],
         "reasoning_markers": [{"marker": x["marker"], "at": {"turn": x["turn"], "step": x["step"]}}
                               for x in um[:8]],
         "note": "失败=实测；未决标记=**仅表示该字面出现**，⛔ 不表示已确认阻塞"},
        bl, "verified" if bl else ("provisional" if um else "unknown"),
        "两个来源分开呈现（工具失败 vs 推理里的未决标记）")

    # ── ⑦ evidence_coverage（可追溯 + 累计口径的缺失标记）──
    steps_with_reasoning = len({(e.get("turn"), e.get("step")) for e in reas})
    steps_with_tools = len({(e.get("turn"), e.get("step")) for e in calls})
    all_steps = len({(e.get("turn"), e.get("step")) for e in used
                     if e.get("turn") is not None})
    cov = {
        "as_of_seq": as_of_seq, "future_events_excluded": excluded,
        "events_used": len(used), "event_kinds": _dist([e["kind"] for e in used]),
        "steps_total": all_steps, "steps_with_reasoning": steps_with_reasoning,
        "steps_with_tools": steps_with_tools,
        "tool_only_steps": max(0, steps_with_tools - steps_with_reasoning),
        "probe": probe,
        "missing_marking_rule": "缺失用**累计口径**（evicted_*）· ⛔ 不用 turn 级 historyCoverage",
    }
    gaps = []
    if excluded:
        gaps.append("future-events-excluded(%d)" % excluded)
    if all_steps and steps_with_reasoning < all_steps:
        gaps.append("pure-tool-steps(%d)" % (all_steps - steps_with_reasoning))
    if probe.get("evicted_entries_cumulative"):
        gaps.append("history-evicted-cumulative(%s entries)" % probe["evicted_entries_cumulative"])
    cov["gaps"] = gaps
    snap["evidence_coverage"] = _field("provided" if used else "unknown", cov, [],
                                       "verified" if used else "unknown",
                                       "覆盖情况本身是可核实的事实")

    # ── ⑧ work_type_hint（**非强制辅助** · 沿用唯一一套规则 + 行为交叉核实）──
    wt, hits, conflict = ws.classify_type(rtext) if rtext.strip() else ("unknown", {}, False)
    mech = {"tool_class_counts": {}}
    for c in calls:  # 用**实际工具名**做行为交叉核实（⛔ 不替代 Agent 判断）
        cls = {"edit": "edit", "write": "write", "read": "read", "glob": "search", "grep": "search",
               "pwsh": "exec", "powershell": "exec", "bash": "exec", "task": "other"}
        k = cls.get(str(c.get("tool") or "").lower(), "other")
        mech["tool_class_counts"][k] = mech["tool_class_counts"].get(k, 0) + 1
    beh = ws.behavior_evidence(mech, wt)
    snap["work_type_hint"] = _field(
        "provided" if wt != "unknown" else "unknown",
        {"hint": wt, "advisory": True, "not_for_filtering": True, "type_hits": hits,
         "behavior_evidence": beh},
        [_claim("type-rule:%s" % wt, "reasoning", basis="rule-hit-count")] if wt != "unknown" else [],
        "provisional", "🔴 **非强制辅助**：⛔ 不作硬过滤 · ⛔ 不决定检索通道（阶段②已证伪其可靠性）")
    return snap


def _dist(xs):
    d = {}
    for x in xs:
        d[x] = d.get(x, 0) + 1
    return dict(sorted(d.items()))


# ─────────────────────────────────────────────────────────────────────────────
def _synth():
    """合成事件流（自检用 · 含"谈论了 A 但实际动了 B"的反例）"""
    return {"session": "synth", "probe": {"evicted_entries_cumulative": 110},
            "events": [
                {"seq": 1, "kind": "user", "text": "请实现 Runtime 工作上下文的检索字段并验证"},
                {"seq": 2, "kind": "reasoning", "turn": 1, "step": 1,
                 "text": "先读 tools/experience_push.py 理解现有检索规则，可能还要看 scratch/x.py；"
                         "参考 `^def |^class |^[A-Z_]+ = ` 与 task_cards/.../X.md 这类写法"},
                {"seq": 3, "kind": "tool-call", "turn": 1, "step": 2, "tool": "read",
                 "path_hints": ["tools/experience_push.py"]},
                {"seq": 4, "kind": "tool-result", "turn": 1, "step": 2, "ok": True, "error": False},
                {"seq": 5, "kind": "reasoning", "turn": 1, "step": 3,
                 "text": "其实不该继续改旧规则，改为新增 snapshot 构建器；工作上下文短语要保留"},
                {"seq": 6, "kind": "tool-call", "turn": 1, "step": 4, "tool": "edit",
                 "path_hints": ["scratch/_ctx_snapshot_probe.py"]},
                {"seq": 7, "kind": "tool-result", "turn": 1, "step": 4, "ok": False, "error": True},
                {"seq": 8, "kind": "reasoning", "turn": 1, "step": 5,
                 "text": "自检失败，尚未确定原因，需要确认路径正则"},
            ]}


def selftest():
    ok = []

    def check(n, c):
        ok.append((n, bool(c)))

    full = build(_synth(), None)
    check("S1 as_of_default_uses_all", full["snapshot"]["future_events_excluded"] == 0
          and full["snapshot"]["events_used"] == 8)
    early = build(_synth(), 2)
    check("S2 no_future_leak", early["snapshot"]["as_of"]["seq"] == 2
          and early["snapshot"]["future_events_excluded"] == 6
          and early["snapshot"]["no_future_leak"] is True)
    # 早期时点：还不知道 edit / 失败
    check("S3 early_snapshot_has_no_later_activity",
          early["activity_evidence"]["value"] is None
          and early["target_refs"]["value"]["from_activity"] == [])
    # 双来源分离：谈论 x.py 但实际动的是别的
    tr = full["target_refs"]["value"]
    check("S4 dual-source-not-merged",
          "scratch/x.py" in tr["reasoning_only"]
          and "scratch/_ctx_snapshot_probe.py" in tr["activity_only"]
          and tr["agreement"] == ["tools/experience_push.py"])
    claim_kinds = {c["source_kind"] for c in full["target_refs"]["claims"]}
    check("S5 strengths_by_source", claim_kinds <= {"reasoning", "tool"}
          and all(c["strength"] in ("provisional", "verified", "superseded")
                  for c in full["target_refs"]["claims"]))
    # work_topic 是多词短语（不是单词 token）
    ph = [t["phrase"] for t in full["work_topic"]["value"]]
    check("S6 topic_is_multiword_phrase", bool(ph) and all((" " in p or len(p) >= 4) for p in ph))
    check("S7 topic_has_sources", all(t["sources"] for t in full["work_topic"]["value"]))
    # 方向变化 + 修正标记
    dc = full["direction_change"]["value"]
    check("S8 direction_change_provisional",
          full["direction_change"]["confidence"] == "provisional"
          and dc["revision_markers_strong_count"] >= 1
          and (dc["change"] in ("changed", "target-shift") or dc["change"].startswith("none-observed")))
    check("S9 not_remarked_is_advisory_only",
          isinstance(full["target_refs"].get("not_rementioned_after_revision_marker"), list)
          and all(c["strength"] != "superseded" for c in full["target_refs"]["claims"]))
    # 🔴 代码/正则片段不得被当成对象引用（真实反例：`^def |^class |` · `task_cards/.../X.md`）
    refs = [x["ref"] for x in (full["target_refs"]["value"]["from_reasoning"]
                               + full["target_refs"]["value"]["from_activity"])]
    check("S9b codeish_refs_filtered",
          not any(("|" in r or "^" in r or "..." in r) for r in refs)
          and "tools/experience_push.py" in refs)
    # 阻塞：两个来源分开
    bl = full["blockers_unresolved"]["value"]
    check("S10 blockers_two_sources", bl is not None and bl["verified_failures"]
          and isinstance(bl["reasoning_markers"], list))
    # 覆盖：累计口径 + 缺口
    cov = full["evidence_coverage"]["value"]
    check("S11 coverage_cumulative_eviction",
          cov["probe"]["evicted_entries_cumulative"] == 110
          and any("history-evicted-cumulative" in g for g in cov["gaps"]))
    # work_type 非强制
    wth = full["work_type_hint"]["value"]
    check("S12 type_hint_advisory", wth["advisory"] is True and wth["not_for_filtering"] is True)
    # 空输入 ⇒ unknown（允许未知）
    empty = build({"session": "e", "events": [], "probe": {}}, None)
    check("S13 all_unknown_when_empty",
          empty["current_goal_focus"]["state"] == "unknown"
          and empty["work_topic"]["state"] == "unknown"
          and empty["target_refs"]["state"] == "unknown")
    # 不落原文：所有 ref 都是短语/路径（无长段落）
    longest = max([len(c["ref"]) for c in full["target_refs"]["claims"]] +
                  [len(t["phrase"]) for t in full["work_topic"]["value"]] + [0])
    check("S14 no_raw_text_in_output", longest <= 160)
    check("S15 principles_declared", full["principles"]["no_forced_type"].startswith("work_type_hint"))

    failed = [n for n, c in ok if not c]
    print(json.dumps({"selftest": {"total": len(ok), "passed": len(ok) - len(failed), "failed": failed}},
                     ensure_ascii=False))
    return 0 if not failed else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    as_of = None
    for a in sys.argv[1:]:
        if a.startswith("--as-of-seq="):
            as_of = int(a.split("=", 1)[1])
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig") or "{}")
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": "bad-input", "detail": str(exc)[:80]}) + "\n")
        return 2
    snap = build(payload, as_of)
    sys.stdout.write(json.dumps({"ok": True, "request_id": payload.get("session"),
                                 "context_snapshot": snap}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
