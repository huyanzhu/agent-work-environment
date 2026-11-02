#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_card_assisted_reasoning_field_probe.py — **卡辅助推理文本 → Runtime 交给检索的字段**（只读）

    *"现在的方向我认为是：通过任务卡来辅助推理文本，使 runtime 得到能够交给检索的字段"*
    *"可以"*（同意先按判据把 12 张卡逐条判"施工态 / 非施工态"并给出可接入子集）

机制（分工 · 两条来源各司其职）
    | 来源 | 作用 | 特性 |
    |---|---|---|
    | **任务卡**（`State` + `Next Action`） | 定**焦点对象**（当前这一步） | 精度高 · 覆盖低 |
    | **推理文本**（近窗口） | **交叉验证 / 补充** | 覆盖高 · 频率不可作排序键 |
    输出 = **Runtime 可交给检索的字段**：`{对象, 领域职能短语, 对齐类别, 置信, 依据}`

两档模式
    `--cards`          判 **12 张新模板卡**：施工态判据 → 可接入子集 + 各自 Top-5
    `--card=<rel>`     读 stdin 的会话 JSON（`_ctx_snapshot_evidence.mjs --emit`）
                       ⇒ 卡字段 × 推理近窗口 **交叉** ⇒ 产出字段 ⇒ 检索 Top-5

施工态判据（机械 · ⛔ 不含语义判断）
    ① `State` 以 `Executing` 开头  ② `Next Action` 宽档能提到「动作 + 对象」
    ③ `Next Action` **不含"等待/验收/裁定/观察期/归档/确认后"** 等非施工词
    ⇒ 三条同时满足才算**可接入**；否则**显式退化**（⛔ 不用 Goal 兜底 ⇒ 避免"虚假覆盖"）
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

import experience_push as ep
import task_start as ts
import _zh_skill_discrimination_probe as dp
import _runtime_input_form_probe as rif
import _focus_object_extractor_probe as fx

STATE_RE = re.compile(r"^State:\s*(.+)$", re.M)
NON_CONSTRUCTION = ("等待", "等 ", "验收", "裁定", "观察期", "观察", "归档", "确认后", "待")


def read(rel):
    return io.open(os.path.join(AIOS_ROOT, rel.replace("/", os.sep)), "r",
                   encoding="utf-8", errors="replace").read()


def card_state(rel):
    m = STATE_RE.search(read(rel))
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def construction(rel):
    """→ (可接入?, 对象, 依据, 原因列表)"""
    st = card_state(rel)
    _g, _s, nxt = rif.card_parts(rel)
    obj, why, degraded, reason = fx.focus_object(nxt, wide=True)
    why_not = []
    if not st.lower().startswith("executing"):
        why_not.append("状态非 Executing（`%s`）" % st[:24])
    if degraded:
        why_not.append("Next Action 提不到「动作+对象」")
    hit_wait = [w for w in NON_CONSTRUCTION if w in nxt[:40]]
    if hit_wait:
        why_not.append("含非施工词 %s" % hit_wait)
    return (not why_not), obj, why, why_not


def retrieve(obj, skills, topn=5):
    keys = rif.OBJ_PHRASES.get(obj, [])
    qts = [ep.tokenize(k) for k in keys if ep.query_has_signal(ep.tokenize(k))]
    if not qts:
        return [], 0
    rows = dp.run_hard(qts, skills, cats=dp.OBJ2CAT.get(obj, []) or None)
    return [(s.get("name_zh") or s.get("name"), s.get("cat_zh")) for *_x, s in rows[:topn]], len(rows)


def all_cards():
    base = os.path.join(AIOS_ROOT, "task_cards", "active")
    out = []
    for root, _d, files in os.walk(base):
        for n in sorted(files):
            if n.endswith(".md") and ts.CARD_NAME_RE.match(n) and n.startswith("TASK-"):
                out.append(os.path.relpath(os.path.join(root, n), AIOS_ROOT).replace("\\", "/"))
    return sorted(out)


def mode_cards(skills):
    print("=== 模式 A：12 张卡 · 施工态判定 → **可接入子集** ===")
    ok, rows = 0, []
    for rel in all_cards():
        good, obj, why, why_not = construction(rel)
        tag = os.path.basename(rel).replace("TASK-", "").replace(".md", "")
        st = card_state(rel)[:16]
        if good:
            ok += 1
            top, pool = retrieve(obj, skills)
            print("\n  ✅ [%s] State=`%s` · 对象 **`%s`** · 池 %d" % (tag, st, obj, pool))
            print("       依据：`%s`" % why[:70])
            print("       Top-5：%s" % " / ".join("%s[%s]" % (n, (c or "-")[:6]) for n, c in top) or "（无候选）")
            rows.append((tag, obj, top))
        else:
            print("  ⛔ [%s] State=`%s` ⇒ %s" % (tag, st, "；".join(why_not)))
    print("\n--- 汇总：可接入 **%d/%d = %.0f%%**（其余显式退化 · ⛔ 不用 Goal 兜底）---"
          % (ok, len(all_cards()), 100.0 * ok / len(all_cards()) if all_cards() else 0))
    print("  精度（我判）：%s" % " · ".join("%s=%s" % (t, o) for t, o, _t2 in rows))
    return 0


def mode_cross(card_rel, skills):
    blob = json.loads(sys.stdin.read())
    rs = [e for e in (blob.get("events") or []) if e.get("kind") == "reasoning"]
    print("=== 模式 B：**卡辅助推理文本** → 交给检索的字段 ===")
    print("卡：`%s`" % card_rel)
    print("会话：`%s` · reasoning 块 **%d**" % (blob.get("session"), len(rs)))

    good, obj_card, why_card, why_not = construction(card_rel)
    print("\n[卡侧] State=`%s` · 可接入=%s · 对象=`%s`" % (card_state(card_rel)[:22], good,
                                                        obj_card or "（退化）"))
    if why_not:
        print("       ⛔ 未通过：%s" % "；".join(why_not))

    # 推理近窗口：**取最近块里出现的对象**（⛔ 不按频率取 Top-1）
    win = 20
    seq_objs = []
    for e in rs[-win:]:
        seq_objs.extend(fx_objects(e.get("text") or ""))
    recent_first = []
    for e in rs[-win:]:
        o = fx_objects(e.get("text") or "")
        if o:
            recent_first.append(o[0])
    cnt = Counter(seq_objs)
    print("\n[推理侧] 近 %d 块：对象计数 %s" % (win, cnt.most_common(6)))
    print("          **最近块首个对象**序列（末 6）：%s" % recent_first[-6:])

    # 交叉裁决
    if not good and not seq_objs:
        print("\n⇒ **显式退化**：卡侧与推理侧都无对象 ⇒ ⛔ 不交检索")
        return 0
    if good and obj_card in cnt:
        conf, obj, src = "**高**（卡 + 推理互证）", obj_card, "card∩reason"
    elif good:
        conf, obj, src = "中（卡为准 · 推理近窗口未出现 ⇒ 卡可能过时）", obj_card, "card-only"
    else:
        obj, conf, src = (recent_first[-1] if recent_first else cnt.most_common(1)[0][0]), \
                         "低（卡退化 ⇒ 用推理最近块首个对象）", "reason-only"
    print("\n⇒ **交给检索的字段**：对象 `%s` · 置信 %s · 来源 %s" % (obj, conf, src))
    print("   短语（领域职能）：%s" % " · ".join(rif.OBJ_PHRASES.get(obj, [])))
    print("   对齐类别：%s" % dp.OBJ2CAT.get(obj, []))
    top, pool = retrieve(obj, skills)
    print("   检索：池 **%d** · Top-5：%s" % (pool, " / ".join("%s[%s]" % (n, (c or "-")[:6]) for n, c in top)))
    print("\n（只读 · 内存态 · ⛔ 推理原文未落盘 · 未改机制/闸门/语料/本体）")
    return 0


def fx_objects(text):
    return fx.match_objects(fx.QUOTE_RE.sub(" ", text), wide=True)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cache = os.path.join(CACHE, "_zh_skill_registry.json")
    skills = ((json.load(io.open(cache, "r", encoding="utf-8", errors="replace")).get("skills") or [])
              if os.path.isfile(cache) else [])
    if "--cards" in sys.argv:
        return mode_cards(skills)
    card = rif.CARDS["G2"]
    for a in sys.argv[1:]:
        if a.startswith("--card="):
            card = a.split("=", 1)[1]
    return mode_cross(card, skills)


if __name__ == "__main__":
    sys.exit(main())
