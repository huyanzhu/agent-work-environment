#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_reasoning_object_retrieval_probe.py — **用推理文本的对象跑检索**（只读 · 内存态 · 不落原文）

    *"跑一下检索"* —— 把「推理文本 → 对象」接上「对象 → 检索」，看能否带回**相关能力**。

唯一变量 = **对象来源与取法**：
    R0 卡字段 `Next Action`（基线 · 上一轮读数该卡对象 = `前端` · Top-5 全对）
    R1/R2/R3 推理文本 **最近 5 / 10 / 20 块**的对象
    R4 推理文本 **全程**的对象（Top-3）
    R5 卡字段对象 ∩ 推理近窗口对象（非空则用，否则退回卡字段）
检索与判别（⛔ 不改）：中文注册表 5005 · **名称硬门槛** + 对象对齐 `category_zh`
输出：每个对象的 Top-3（相关性由 Agent 判 · ⚠️ 非独立验证）· ⛔ 不回显推理原文
"""
import io
import json
import os
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
import _zh_skill_discrimination_probe as dp
import _runtime_input_form_probe as rif
import _reasoning_focus_extract_probe as rfp

PRODUCT_CARD = rif.CARDS["G2"]


def retrieve(obj, skills, topn=3):
    keys = rif.OBJ_PHRASES.get(obj, [])
    qts = [ep.tokenize(k) for k in keys if ep.query_has_signal(ep.tokenize(k))]
    if not qts:
        return [], 0
    rows = dp.run_hard(qts, skills, cats=dp.OBJ2CAT.get(obj, []) or None)
    return [(s.get("name_zh") or s.get("name"), s.get("cat_zh")) for *_x, s in rows[:topn]], len(rows)


def show(label, objs_counts, skills, note=""):
    print("\n[%s] %s" % (label, note))
    if not objs_counts:
        print("    ⇒ **无对象 ⇒ 不检索**（显式退化 · ⛔ 不硬凑）")
        return
    for obj, n in objs_counts:
        top, pool = retrieve(obj, skills)
        print("    ▸ 对象 `%s`（%d 次）· 池 %d" % (obj, n, pool))
        for name, cat in top:
            print("        - %-26s [%s]" % (name[:26], (cat or "-")[:6]))
        if not top:
            print("        （无候选）")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cache = os.path.join(CACHE, "_zh_skill_registry.json")
    if not os.path.isfile(cache):
        print("⚠️ 缺缓存 `%s`" % cache)
        return 1
    skills = (json.load(io.open(cache, "r", encoding="utf-8", errors="replace")).get("skills") or [])
    blob = json.loads(sys.stdin.read())
    ev = blob.get("events") or []
    rs = [e for e in ev if e.get("kind") == "reasoning"]

    print("=== 用**推理文本的对象**跑检索（只读 · ⛔ 不落原文）===")
    print("会话：`%s` · reasoning 块 **%d** ｜ 池：中文注册表 **%d** 技能"
          % (blob.get("session"), len(rs), len(skills)))
    print("判别：**名称硬门槛** + 对象对齐 `category_zh`（⛔ 不改机制）")

    # ── R0 卡字段基线 ────────────────────────────────────────────────
    goal, step, nxt = rif.card_parts(PRODUCT_CARD)
    obj0, why0, deg0, _r0 = rfp.fx.focus_object(nxt)
    print("\n卡字段 `Next Action`：`%s`" % nxt[:90])
    show("R0 卡字段对象", ([(obj0, 1)] if obj0 and not deg0 else []), skills,
         "（基线 · 当前一步的对象）")

    # ── R1–R3 推理近窗口 ────────────────────────────────────────────
    for label, w in (("R1 推理·最后 5 块", 5), ("R2 推理·最后 10 块", 10), ("R3 推理·最后 20 块", 20)):
        if w > len(rs):
            continue
        c = Counter()
        for e in rs[-w:]:
            c.update(rfp.objects_in(e.get("text") or ""))
        show(label, c.most_common(3), skills, "（对象按出现次数排序 · 取 Top-3）")

    # ── R4 全程 ────────────────────────────────────────────────────
    c_all = Counter()
    for e in rs:
        c_all.update(rfp.objects_in(e.get("text") or ""))
    show("R4 推理·全程", c_all.most_common(3), skills, "（会话累积对象 · 取 Top-3）")

    # ── R5 交叉 ────────────────────────────────────────────────────
    c20 = Counter()
    for e in rs[-20:]:
        c20.update(rfp.objects_in(e.get("text") or ""))
    inter = [o for o, _n in c20.most_common() if o == obj0]
    show("R5 卡字段 ∩ 推理近窗口", ([(obj0, c20.get(obj0, 0))] if inter else []), skills,
         "（一致才用 ⇒ 用于**互证**；不一致 ⇒ 需人裁）")
    if obj0 and not inter:
        print("    ⚠️ 不一致：卡字段说 `%s`，推理近 20 块里没有它 ⇒ 按上一轮结论"
              "（推理反映累积、卡字段反映当前步），应**以卡字段为准**" % obj0)

    print("\n（只读 · 内存态 · ⛔ 推理原文未落盘 · 未改机制/闸门/语料/本体）")
    print("⚠️ Top-3 相关性由 Agent 判（非独立验证）｜ 对象/动作词表为首版启发式")
    return 0


if __name__ == "__main__":
    sys.exit(main())
