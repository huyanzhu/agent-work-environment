#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_work_semantics_probe.py — **本地无模型工作语义提取器**（只读 · 实验态）

上位：技术路线 ——
  · **可以**：不通过模型得到**有限、明确**的任务语义（工作类型 / 动作 / 主题 / 对象 · 有限状态逻辑）
  · **不可以保证**：不通过模型理解**任意文本中复杂、隐含**的任务意图（第三类 · ⛔ 本原型不做）
  · 定位：**可验证的结构化解释层**，⛔ **不是**完整任务理解引擎

🔴 纪律
  · **只读** · 无模型调用 · 无网络 · 不 subprocess
  · ⛔ **不把原始推理文本写入文件**；只输出**派生字段 / 证据类型 / 规则命中 / 耗时**
  · ⛔ **不训练分类器**（那已是机器学习，不是纯规则方案）
  · ✅ **必须允许 `unknown`**：没命中规则 ≠ Agent 没在做任务；识别为 `review` ≠ 知道审查的真实目标

三组输入
  group1 仅现有机械字段（工具类别 · 目录级对象 · 计划状态）
  group2 group1 + 规则提取的**工作类型 / 动作 / 技术主题**
  group3 group2 + **相邻步骤的状态变化与可核实执行结果**

stdin : {"segments":[{"step":1,"text":"<可选·推理文本·不落盘>"}],"activity":[…],"plan":[…],"results":[…]}
stdout: {"groups": {"group1":…, "group2":…, "group3":…}, …}   # 仅派生字段
"""
import io
import json
import os
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

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
HERE_ABS = os.path.abspath(__file__)

# ── 规则表（**有限 · 可解释 · 可审**）────────────────────────────────────────────
WORK_TYPE_RULES = {
    "review":         (r"评审|审查|复核|审阅|检视|review|critique", ["评审", "审查", "复核"]),
    "implementation": (r"实现|编写|落地|新增|开发|改造|implement|refactor|write the", ["实现", "编写", "落地"]),
    "debugging":      (r"调试|排查|定位|根因|报错|失败原因|debug|troubleshoot|root cause", ["排查", "根因", "报错"]),
    "testing":        (r"测试|自检|断言|校验|验证通过|test|assert|selftest", ["测试", "自检", "断言"]),
    "research":       (r"研究|调研|探索|核实|只读核实|分析|盘点|research|investigate|explore|audit", ["研究", "核实", "调研", "盘点"]),
    "documentation":  (r"文档|交接|同步|写作|记录|说明|document|handoff|readme|write docs", ["文档", "交接", "同步"]),
}
ACTION_RULES = {
    "evaluate-design": r"评估设计|评价方案|判断是否|是否有依据|设计是否|evaluate the design",
    "investigate":     r"核实|确认|查明|看看到底|盘点|investigate|verify by reading",
    "implement":       r"实现|写|新增|落地|implement",
    "fix":             r"修|改成|收紧|修正|fix|tighten",
    "test":            r"测试|自检|跑一次|assert|selftest",
    "document":        r"写文档|同步|交接|document|handoff",
}
#: 已知技术术语（中文侧 · 有限表 · 可审）
TOPIC_TERMS = ("推理", "工作理解", "能力发现", "检索", "候选", "来源", "上下文", "任务",
               "运行时", "探针", "闸门", "保留策略", "淘汰", "交接", "对齐", "验证", "判据",
               "通道", "语义", "提取", "宿主", "负担", "投递", "递送", "授权")
PATH_RE = re.compile(r"(?<![\w/\-.\\])((?:[A-Za-z0-9_.\-]+[/\\])+[A-Za-z0-9_.\-]+\.(?:md|py|ts|mjs|json|yml|yaml|txt))")
IDENT_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_\-]{2,}")
IDENT_STOP = frozenset(("the", "and", "for", "with", "that", "this", "from", "are", "not", "but",
                        "was", "were", "has", "have", "its", "it's", "can", "will", "you", "our"))

SELFCHECK_FORBIDDEN = (
    r"\bopen\s*\([^)]*['\"][wax]",
    r"^\s*(import|from)\s+(socket|urllib|http|requests|subprocess)\b",
    r"\bsubprocess\.", r"\bshutil\.(copy|move|rmtree)\s*\(",
    r"\bos\.(remove|unlink|rename|mkdir|makedirs)\s*\(",
)


def _read(path):
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def readonly_selfcheck():
    hits = [p for p in SELFCHECK_FORBIDDEN if re.search(p, _read(HERE_ABS))]
    return {"forbidden_patterns": hits, "pass": not hits}


# ── 有限语义提取（**纯规则**）──────────────────────────────────────────────────
def extract_topics(text):
    out = []
    for t in TOPIC_TERMS:
        if t in text:
            out.append(t)
    for m in IDENT_RE.finditer(text):
        tok = m.group(0)
        if tok.lower() in IDENT_STOP:
            continue
        if tok not in out:
            out.append(tok)
    return out[:12]


def extract_targets(text):
    seen, out = set(), []
    for m in PATH_RE.finditer(text):
        p = m.group(1).replace("\\", "/")
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:8]


def classify_type(text):
    """→ (type|unknown, hits, conflict)。多类**等强**命中 ⇒ 拒绝判断（unknown）。"""
    hits = {}
    for name, (pat, _kw) in WORK_TYPE_RULES.items():
        n = len(re.findall(pat, text, flags=re.I))
        if n:
            hits[name] = n
    if not hits:
        return "unknown", {}, False
    best = max(hits.values())
    top = [k for k, v in hits.items() if v == best]
    if len(top) > 1:
        return "unknown", hits, True          # 🔴 允许拒绝判断
    return top[0], hits, False


def classify_action(text):
    for name, pat in ACTION_RULES.items():
        if re.search(pat, text, flags=re.I):
            return name
    return "unknown"


def state_from_mechanical(mech):
    """纯机械判定（group1）· ⛔ 不使用文本。"""
    act = mech.get("activity_total")
    ok = mech.get("ok_true")
    fails = mech.get("consecutive_failures")
    if act is None:
        return "unknown"
    if act == 0:
        return "unknown"                     # 无活动 ⇒ 不判"延续"
    if (fails or 0) >= 1 and (ok or 0) == 0:
        return "stalled"
    return "continuing" if (ok or 0) > 0 else "unknown"


# ── 行为证据（**独立于推理文本的机械参照**）────────────────────────────────────
# 🔴 '（**真实反例驱动** · 6/6 会话）：文本规则把 `work_type` 判成 `documentation`
#    在**全部**真实会话上出现，而工具活动构成显示主导类是 `edit`/`exec`
#    ⇒ **"谈论文档" ≠ "在做文档"** ⇒ 词面命中无法区分"在做"与"在谈论"。
#    ⇒ 对策不是再加词，而是**用机械行为证据交叉核实**，冲突时**必须降置信度**。
BEHAVIOR_ALLOW = {
    "edit": ("implementation",),
    "write": ("implementation", "documentation"),
    "exec": ("testing", "implementation", "debugging"),
    "read": ("research", "review"),
    "search": ("research",),
    "plan": ("research", "implementation"),
    "other": (),
}


def behavior_evidence(mech, work_type_effective):
    """工具活动构成 ⇒ 对文本工作类型的**交叉核实**（consistent / contradicts / inconclusive）。"""
    tc = mech.get("tool_class_counts") or {}
    if not tc:
        return {"dominant": None, "allowed_types": [], "counts": {},
                "verdict": "inconclusive", "why": "无工具活动机械量（该会话不在探针日志中或无记录）"}
    top = max(sorted(tc), key=lambda k: tc[k])
    allow = BEHAVIOR_ALLOW.get(top, ())
    if not allow or work_type_effective in (None, "unknown"):
        return {"dominant": top, "allowed_types": list(allow), "counts": tc,
                "verdict": "inconclusive", "why": "无可用对照（allowed=%s）" % list(allow)}
    verdict = "consistent" if work_type_effective in allow else "contradicts"
    return {"dominant": top, "allowed_types": list(allow), "counts": tc, "verdict": verdict,
            "why": "文本类型=%s · 主导工具类=%s（允许 %s）" % (work_type_effective, top, list(allow))}


def run_groups(payload):
    segs = payload.get("segments") or []
    mech = payload.get("mechanical") or {}
    text = " \n".join(str(s.get("text") or "") for s in segs)
    has_text = bool(text.strip())

    # ── group1：仅机械字段 ──
    g1 = {"work_state": state_from_mechanical(mech),
          "work_type": "unknown", "action": "unknown", "work_topic": [],
          "target_refs": [], "direction_change": "unknown",
          "evidence": ["tool-activity", "plan-state"], "confidence": "unknown"}

    # ── 逐步类型（**先算序列** · 供 group2/group3 共用）──
    seg_types = []
    for s in segs:
        t = str(s.get("text") or "")
        ty, _h, _c = classify_type(t) if t.strip() else ("unknown", {}, False)
        seg_types.append(ty)
    #: 按**步**众数（并列 ⇒ 拒绝判断）—— 与"按命中计数"是两个不同口径
    cnt = {}
    for t in seg_types:
        if t != "unknown":
            cnt[t] = cnt.get(t, 0) + 1
    if cnt:
        best_n = max(cnt.values())
        top_t = [k for k, v in cnt.items() if v == best_n]
        by_steps = top_t[0] if len(top_t) == 1 else "unknown"
    else:
        by_steps = "unknown"

    # ── group2：+ 文本规则（类型 / 动作 / 主题）──
    wtype, hits, conflict = classify_type(text) if has_text else ("unknown", {}, False)
    # 🔴 '（**真实反例驱动**）：`work_type` 有两个口径 ——
    #    `by_hits` = 全段合并后**按命中次数**（高频词会赢 ⇒ 读数 6/6 会话都误判成 `documentation`）
    #    `by_steps` = **按步众数**（并列即拒绝）
    #    ⇒ 两者不一致时**必须显式标出**（`merged_disagreement`），⛔ 不得静默取其一。
    disagreement = (wtype != "unknown" and by_steps != "unknown" and wtype != by_steps)
    action = classify_action(text) if has_text else "unknown"
    topics = extract_topics(text) if has_text else []
    targets = extract_targets(text) if has_text else []
    ev2 = list(g1["evidence"]) + (["reasoning-pattern-match"] if has_text else [])
    wt_eff = by_steps if by_steps != "unknown" else wtype
    beh = behavior_evidence(mech, wt_eff)
    if beh["verdict"] != "inconclusive":
        ev2.append("behavior-crosscheck(%s:%s)" % (beh["verdict"], beh["dominant"]))
    if not has_text:
        conf2 = "unknown"
    elif conflict or disagreement or beh["verdict"] == "contradicts":
        # 收紧：合并口径与逐步口径不一致 / **行为证据反驳** ⇒ 不得当作"多信号一致"
        conf2 = "provisional"
    elif wtype != "unknown" and g1["work_state"] != "unknown":
        conf2 = "multi-signal-agree"
    elif wtype != "unknown":
        conf2 = "rule-hit"
    else:
        conf2 = "unknown"
    step_share = None
    if cnt and by_steps != "unknown":
        step_share = round(cnt[by_steps] / float(len([t for t in seg_types if t != "unknown"])), 3)
    g2 = {"work_state": g1["work_state"], "work_type": wtype, "action": action,
          "work_topic": topics, "target_refs": targets, "direction_change": "unknown",
          "evidence": ev2, "confidence": conf2,
          "work_type_steps": by_steps,             # ← 建议进 Retrieval 的口径（过程众数）
          "work_type_step_share": step_share,
          "merged_disagreement": disagreement,
          "behavior_evidence": beh}

    # ── group3：+ 相邻步骤的状态变化与可核实执行结果 ──
    seq = []
    for s, ty in zip(segs, seg_types):
        tg = extract_targets(str(s.get("text") or ""))
        seq.append({"step": s.get("step"), "type": ty, "targets": tg})
    dchange = "unknown"
    for a, b in zip(seq, seq[1:]):
        if a["type"] != "unknown" and b["type"] != "unknown" and a["type"] != b["type"]:
            dchange = "changed"
            break
        if a["targets"] and b["targets"] and set(a["targets"]) != set(b["targets"]):
            dchange = "target-shift"
            break
    if not seq:
        dchange = "unknown"
    elif dchange == "unknown" and len(seq) == 1:
        dchange = "none-observed(单步 ⇒ 不足以判定)"
    res_ok = mech.get("ok_true")
    res_fail = mech.get("ok_false")
    ev3 = list(g2["evidence"])
    if res_ok is not None or res_fail is not None:
        ev3.append("verified-result(ok=%s,fail=%s)" % (res_ok, res_fail))
    if len(seq) > 1:
        ev3.append("neighbor-step")
    conf3 = conf2
    if dchange == "changed":
        # 🔴 明确：**不凭单个工具调用断定转向** ⇒ 方向变化一律标 **provisional**
        conf3 = "provisional"
    g3 = {"work_state": g1["work_state"], "work_type": wtype, "action": action,
          "work_topic": topics, "target_refs": targets, "direction_change": dchange,
          "evidence": ev3, "confidence": conf3,
          "work_type_steps": by_steps, "merged_disagreement": disagreement,
          "per_step": [{"step": s["step"], "type": s["type"], "targets": len(s["targets"])} for s in seq]}

    return {"group1": g1, "group2": g2, "group3": g3,
            "type_hits": hits, "type_conflict": conflict,
            "text_available": has_text,
            "new_info_over_g1": {"work_type_is_new": g2["work_type"] != "unknown",
                                 "topics_is_new": bool(g2["work_topic"]),
                                 "targets_is_new": bool(g2["target_refs"]),
                                 "direction_is_new": g3["direction_change"] not in ("unknown",)}}


def selftest():
    ok = []

    def check(name, cond):
        ok.append((name, bool(cond)))

    # 合成样本（**非任何真实推理** · 无隐私问题）
    S = {
        "review": "我要评审这份设计，判断字段设计是否合理、证据是否充分。",
        "implementation": "开始实现这个提取器，编写规则并落地到脚本。",
        "debugging": "排查这个报错，定位根因并解释失败原因。",
        "testing": "跑自检与断言，验证通过后再继续。",
        "research": "只读核实运行时字段，盘点信息链路的缺口。",
        "documentation": "写文档并同步交接材料。",
        "conflict": "评审并实现这个设计，同时测试它。",
        "none": "嗯，继续。",
    }
    for name in ("review", "implementation", "debugging", "testing", "research", "documentation"):
        ty, _h, _c = classify_type(S[name])
        check("type-" + name, ty == name)
    ty_c, _h, conflict = classify_type(S["conflict"])
    check("refuse-on-conflict", ty_c == "unknown" and conflict is True)
    ty_n, _h2, _c2 = classify_type(S["none"])
    check("refuse-on-no-hit", ty_n == "unknown")
    check("topics", "推理" in extract_topics("推理文本要成为语义来源"))
    check("targets", extract_targets("改 runtime/aios-activation.ts 与 scratch/_work_state_probe.py")
          == ["runtime/aios-activation.ts", "scratch/_work_state_probe.py"])
    check("group1-no-text", run_groups({"segments": [], "mechanical": {"activity_total": 5, "ok_true": 5,
                                                                     "consecutive_failures": 0}})["group1"]["work_type"] == "unknown")
    check("group2-adds-info", run_groups({"segments": [{"step": 1, "text": S["review"]}],
                                          "mechanical": {"activity_total": 5, "ok_true": 5,
                                                         "consecutive_failures": 0}})["group2"]["work_type"] == "review")
    g3 = run_groups({"segments": [{"step": 1, "text": S["review"]}, {"step": 2, "text": S["implementation"]}],
                     "mechanical": {"activity_total": 9, "ok_true": 8, "consecutive_failures": 1}})
    check("group3-direction-change", g3["group3"]["direction_change"] == "changed")
    check("group3-provisional", g3["group3"]["confidence"] == "provisional")
    check("readonly-source", readonly_selfcheck()["pass"] is True)

    failed = [n for n, c in ok if not c]
    print(json.dumps({"selftest": {"total": len(ok), "passed": len(ok) - len(failed), "failed": failed}},
                     ensure_ascii=False))
    return 0 if not failed else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig") or "{}")
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": "bad-input", "detail": str(exc)[:80]}) + "\n")
        return 2
    t0 = time.time()
    out = {"ok": True, "request_id": payload.get("request_id"), "groups": run_groups(payload),
           "readonly_selfcheck": readonly_selfcheck(), "elapsed_ms": int((time.time() - t0) * 1000),
           "note": "🔴 仅派生字段 · 无原文 · 无模型调用"}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
