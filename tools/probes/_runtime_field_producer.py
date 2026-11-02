#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_runtime_field_producer.py — **Runtime 字段产出器**（只读原型 · 机制固化）

：选择「① 把机制固化成 Runtime 字段产出器」

它做什么
    输入：**当前任务卡**（`State` / `Next Action` / `Current Step` / `Goal`）
          ＋（可选）**本会话近窗口推理文本**（内存态 · ⛔ 不落原文）
    输出：**`RuntimeField`** —— Runtime 交给检索的**唯一字段**（见 §接口）

设计决策（均由前几轮读数逼出 · ⛔ 不是偏好）
     **卡定对象，推理只做交叉验证**：推理近窗口的频率 Top-1 一定是"干得最多"的
        （读数 `测试 285` vs 当前步 `前端`）⇒ ⛔ 频率不得作排序键。
     **施工态三条件**（同时满足才算可接入）；
     **卡退化 ⇒ 默认显式退化**（⛔ 不用 `Goal` 兜底 ⇒ 避免"虚假覆盖"；
        `Goal` 兜底读数把"整卡多对象"偏差引回来）；
     **`allow_reason_only=False` 为默认**：卡退化时**不**改用推理对象
        （读数最近块首个对象 = `文档`/`测试` = 噪声）；
     **证据不含推理原文**：推理侧只留**对象计数**。

接口（RuntimeField）
    {
      "object":     str | None,          # 焦点工作对象（受控词表内）
      "phrases":    [str],               # 领域职能短语 ⇒ **交给检索的键**
      "categories": [str],               # 对齐的材料类别（来源侧过滤）
      "confidence": "high"|"medium"|"low"|None,
      "source":     "card+reason"|"card-only"|"reason-only"|None,
      "degraded":   bool,
      "reasons":    [str],               # 退化/降级原因（可解释）
      "evidence":   {"card_state","next_action_snippet","reason_object_counts"}
    }

用法
    python scratch/_runtime_field_producer.py --selftest     # 验收判据 –
    python scratch/_runtime_field_producer.py --cards        # 12 张卡的字段产出
    <emit-json> | python scratch/_runtime_field_producer.py --card=<rel>   # 含推理交叉
"""
import io
import json
import os
import re
import sys
from collections import Counter

# ── 路径解析（执行层自 `scratch/` 迁入 `tools/probes/` · 参数化）─────────
#    优先级：`AIOS_ROOT` 环境变量 ▸ 本文件位置（`<root>/tools/probes/`）▸ 工作目录。
#    ⛔ 不写死本机路径 ⇒ clone 到任意位置必须可用（`HANDOFF §四十五` 未清项之「参数化回流」）。
#    `AIOS_ROOT` 是**唯一**根来源；`TOOLS` 供 `import experience_push`（唯一一套打分 / 闸门规则）。
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
# 🔴 生成物一律落 `.aios/`：`_zh_skill_registry.json` 是**外部数据**（约 1.9 MB · 5005 条），
#    ⛔ 不随仓库发布 ⇒ 落在 `tools/probes/` 会被误提交（`.aios/` 才是它的家 · 见 `.aios/README.md`）。
CACHE = os.environ.get("AIOS_STATE_DIR") or os.path.join(AIOS_ROOT, ".aios")
for p in (TOOLS, PROBES):
    if p not in sys.path:
        sys.path.insert(0, p)

import experience_push as ep
import task_start as ts
import _zh_skill_discrimination_probe as dp
import _runtime_input_form_probe as rif
import _focus_object_extractor_probe as fx

STATE_RE = re.compile(r"^State:\s*(.+)$", re.M)
#  非施工词：出现即说明"当前没有在做的工作对象"
NON_CONSTRUCTION = ("等待", "等 ", "验收", "裁定", "观察期", "观察", "归档", "确认后", "待")
PRODUCT_CARD = rif.CARDS["G2"]
NEGATIVE_CARDS = {          # 反例（误提取 / 退化的真实样本）—— ⚠️ 指向**冻结夹具卡**
    "reviewing_wait": "tools/probes/fixtures/cards/TASK-20260923-001.md",  # State=Reviewing · 用户验收
    "reviewing_test": "tools/probes/fixtures/cards/TASK-20261002-001.md",  # Reviewing · 宽档曾误提 `测试`
    "unit_g1": "tools/probes/fixtures/cards/TASK-20261009-001.waiting.md",  # Waiting · 观察期（退化正例）
}


def read(rel):
    return io.open(os.path.join(AIOS_ROOT, rel.replace("/", os.sep)), "r",
                   encoding="utf-8", errors="replace").read()


def card_state(rel):
    m = STATE_RE.search(read(rel))
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def produce(state, next_action, current_step, goal, reason_texts=None,
            reason_window=20, allow_reason_only=False):
    """→ RuntimeField（见 §接口）。"""
    reasons = []
    executing = state.strip().lower().startswith("executing")
    if not executing:
        reasons.append("state-not-executing")
    obj_card, why, no_obj, _r = fx.focus_object(next_action, wide=True)
    if no_obj:
        reasons.append("next-action-has-no-action-object")
    wait_hits = [w for w in NON_CONSTRUCTION if w in next_action[:40]]
    # N2（修正）：**⛔ 不得只表达"等待/验收/归档"** ——
    #   只要「动作+对象」能从**任意一段**（含"到位后"那段）提取到，等待成分**不构成拒因**
    #   （原措辞"不以非施工词开头"与 N4 自相矛盾 ⇒ 已废止）
    if wait_hits and no_obj:
        reasons.append("non-construction-only:" + ",".join(wait_hits))
    construction = not reasons                      # D-2 三条件

    # 推理侧：只取近窗口的**对象计数**（/）
    counts = {}
    if reason_texts:
        c = Counter()
        for t in reason_texts[-reason_window:]:
            c.update(fx.match_objects(fx.QUOTE_RE.sub(" ", t), wide=True))
        counts = dict(c)

    evidence = {"card_state": state[:40], "next_action_snippet": next_action[:60],
                "reason_object_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])[:6])}

    # 卡不可接入 ⇒ 默认显式退化；仅当显式允许时才退到推理对象
    if not construction:
        if allow_reason_only and counts:
            top = max(counts.items(), key=lambda kv: kv[1])[0]
            return _field(top, "low", "reason-only", False,
                          reasons + ["fallback-reason-only(EXPLICIT)"], evidence)
        return _field(None, None, None, True, reasons, evidence)

    # 交叉裁决（收紧）：⛔「出现过一次」不足以判 high ——
    #   要求 **近窗口前 3** 且 **计数 ≥2**；否则只算 medium（并标 weak，可追溯）
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    topk = {o for o, _n in ranked[:3]}
    n_obj = counts.get(obj_card, 0)
    if n_obj >= 2 and obj_card in topk:
        conf, src = "high", "card+reason"
    elif n_obj:
        conf, src = "medium", "card+reason(weak-presence)"
    else:
        conf, src = "medium", "card-only"
    return _field(obj_card, conf, src, False, reasons, evidence)


def _field(obj, conf, src, degraded, reasons, evidence):
    return {"object": obj,
            "phrases": list(rif.OBJ_PHRASES.get(obj, [])) if obj else [],
            "categories": list(dp.OBJ2CAT.get(obj, [])) if obj else [],
            "confidence": conf, "source": src, "degraded": degraded,
            "reasons": reasons, "evidence": evidence}


def produce_from_card(rel, reason_texts=None, allow_reason_only=False):
    raw = read(rel)
    goal, step, _nxt = rif.card_parts(rel)
    # ⚠️ **Next Action 必须按 `task_start._next_action()` 的口径取**（首行 + **缩进续行**）——
    #    这才是 Runtime 真实能拿到的那一份；用纯首行会与规范/lint 口径不一致（读数已修）
    return produce(card_state(rel), ts._next_action(raw), step, goal, reason_texts,
                   allow_reason_only=allow_reason_only)


def retrieve(field, skills, topn=5):
    """字段 → 检索（复用名称硬门槛 + 对象过滤；⛔ 不加新规则）。"""
    if field["degraded"] or not field["object"]:
        return [], 0
    qts = [ep.tokenize(k) for k in field["phrases"] if ep.query_has_signal(ep.tokenize(k))]
    if not qts:
        return [], 0
    rows = dp.run_hard(qts, skills, cats=field["categories"] or None)
    return [(s.get("name_zh") or s.get("name"), s.get("cat_zh")) for *_x, s in rows[:topn]], len(rows)


def all_cards():
    base = os.path.join(AIOS_ROOT, "task_cards", "active")
    out = []
    for root, _d, files in os.walk(base):
        for n in sorted(files):
            if n.endswith(".md") and ts.CARD_NAME_RE.match(n) and n.startswith("TASK-"):
                out.append(os.path.relpath(os.path.join(root, n), AIOS_ROOT).replace("\\", "/"))
    return sorted(out)


def _load_skills():
    cache = os.path.join(CACHE, "_zh_skill_registry.json")
    if not os.path.isfile(cache):
        return []
    return (json.load(io.open(cache, "r", encoding="utf-8", errors="replace")).get("skills") or [])


def selftest():
    ok, fail = [], []

    def check(name, cond, detail=""):
        (ok if cond else fail).append("%s%s" % (name, (" — " + detail) if detail else ""))

    #  施工态正例：产品卡 ⇒ 对象=前端 · 可接入 · 置信 medium（无推理输入时）
    f = produce_from_card(PRODUCT_CARD)
    check("A1 正例：产品卡 ⇒ 对象 `前端` · 不退化 · 置信 medium",
          f["object"] == "前端" and not f["degraded"] and f["confidence"] == "medium",
          "got %s/%s/%s" % (f["object"], f["degraded"], f["confidence"]))
    check("A1b 正例：短语与类别齐备（交给检索的键）",
          bool(f["phrases"]) and bool(f["categories"]), str(f["phrases"])[:60])

    #  反例：Reviewing + 用户验收 ⇒ 必须退化（不得输出对象）
    g = produce_from_card(NEGATIVE_CARDS["reviewing_wait"])
    check("A2 反例：`20260923-001`（Reviewing·用户验收）⇒ **degraded**",
          g["degraded"] is True and g["object"] is None, str(g["reasons"]))

    #  反例：宽档曾误提 `测试` 的卡 ⇒ 也必须退化（状态把关）
    h = produce_from_card(NEGATIVE_CARDS["reviewing_test"])
    check("A3 反例：`20261002-001`（Reviewing · 曾误提 `测试`）⇒ **degraded**",
          h["degraded"] is True and h["object"] != "测试", str(h["reasons"]))

    #  反例：本卡（Waiting）⇒ 退化，且原因**指明状态**
    #   ⚠️ 该卡 Next Action 已按规范改写 ⇒ 不再依赖"非施工词"这一条（判据随卡更新，⛔ 不是放宽）
    u = produce_from_card(NEGATIVE_CARDS["unit_g1"])
    check("A4 反例：本卡（Waiting）⇒ **degraded** 且原因含 `state-not-executing`",
          u["degraded"] is True and "state-not-executing" in u["reasons"], str(u["reasons"]))

# 卡退化时**默认不得**改用推理对象
    u2 = produce_from_card(NEGATIVE_CARDS["unit_g1"], reason_texts=["顺便推进一下前端界面"],
                           allow_reason_only=False)
    check("A5 D-4：卡退化 + 默认 allow_reason_only=False ⇒ 仍 degraded（⛔ 不用推理兜底）",
          u2["degraded"] is True and u2["object"] is None, str(u2["object"]))
    u3 = produce_from_card(NEGATIVE_CARDS["unit_g1"], reason_texts=["顺便推进一下前端界面"],
                           allow_reason_only=True)
    check("A5b D-4：显式允许时 ⇒ reason-only · 置信 low（可追溯为**显式**选择）",
          (not u3["degraded"]) and u3["source"] == "reason-only" and u3["confidence"] == "low",
          str((u3["object"], u3["source"], u3["confidence"])))

    #  交叉：推理近窗口**前 3 且 ≥2 块**含 `前端` ⇒ 置信升为 high（收紧后）
    #   ⚠️ 计数的语义 = **出现的推理块数**（同块内重复提及只计 1）⇒ 用例须用**多块**
    f2 = produce_from_card(PRODUCT_CARD,
                           reason_texts=["推进前端界面", "前端组件设计", "前端交互实现"])
    check("A6 交叉：推理近窗口前 3 且 ≥2 次含 `前端` ⇒ 置信 **high** · source `card+reason`",
          f2["confidence"] == "high" and f2["source"] == "card+reason",
          str((f2["confidence"], f2["source"], f2["evidence"]["reason_object_counts"])))
    f2b = produce_from_card(PRODUCT_CARD, reason_texts=["顺便一提，前端那边也许要看看"])
    check("A6c 收紧：只出现 **1 次** ⇒ 降为 `medium` · `weak-presence`（不再误判互证）",
          f2b["confidence"] == "medium" and "weak" in (f2b["source"] or ""),
          str((f2b["confidence"], f2b["source"])))
    check("A6b 交叉不影响对象（仍是卡定的 `前端`）", f2["object"] == "前端")

    #  证据不含推理原文
    blob = json.dumps(f2, ensure_ascii=False)
    check("A7 证据不含推理原文（只留对象计数）",
          "前端界面与组件设计" not in blob and "继续推进" not in blob,
          blob[:120])

    #  退化时不得返回短语/类别（防止下游误用）
    check("A8 退化时 phrases/categories 为空",
          u["phrases"] == [] and u["categories"] == [])

    print("=== 验收判据（A1–A8）===")
    for line in ok:
        print("  [ok]   %s" % line)
    for line in fail:
        print("  [FAIL] %s" % line)
    print("结果：**%d/%d**" % (len(ok), len(ok) + len(fail)))
    return 0 if not fail else 1


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    skills = _load_skills()
    if "--selftest" in sys.argv:
        return selftest()
    if "--cards" in sys.argv:
        print("=== 字段产出器 · 12 张卡 ===")
        good = 0
        for rel in all_cards():
            f = produce_from_card(rel)
            tag = os.path.basename(rel).replace("TASK-", "").replace(".md", "")
            if f["degraded"]:
                print("  ⛔ [%s] degraded · reasons=%s" % (tag, f["reasons"]))
                continue
            good += 1
            top, pool = retrieve(f, skills)
            print("  ✅ [%s] object=`%s` conf=%s src=%s 池=%d" % (tag, f["object"], f["confidence"],
                                                                f["source"], pool))
            print("        phrases=%s" % " · ".join(f["phrases"]))
            print("        Top-5=%s" % " / ".join(n for n, _c in top))
        print("\n  可接入 **%d/%d** · ⛔ 其余显式退化（不用 Goal 兜底）"
              % (good, len(all_cards())))
        return 0

    card = PRODUCT_CARD
    for a in sys.argv[1:]:
        if a.startswith("--card="):
            card = a.split("=", 1)[1]
    blob = json.loads(sys.stdin.read())
    rs = [e.get("text") or "" for e in (blob.get("events") or []) if e.get("kind") == "reasoning"]
    f = produce_from_card(card, reason_texts=rs)
    print("=== 字段产出器 · 卡 + 推理交叉 ===")
    print("卡：`%s` ｜ 会话 `%s` · reasoning 块 %d" % (card, blob.get("session"), len(rs)))
    print(json.dumps(f, ensure_ascii=False, indent=2))
    top, pool = retrieve(f, skills)
    print("检索：池 %d · Top-5：%s" % (pool, " / ".join("%s[%s]" % (n, (c or "-")[:6]) for n, c in top)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
