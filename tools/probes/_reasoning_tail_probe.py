#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_reasoning_tail_probe.py — 诊断**最后 1–3 个推理块**能得到什么（只读 · 内存态）

：*"看看推理文本的 1-3 批能得到什么，还是产品对话"*

每一步都报：
    · 块标识（`seq`）· 字符数 · **分句统计**（祈使 N / 被"已完成事实"滤掉 M）
    · **全部命中对象**（动作窗口内）
    · **焦点对象**（取第一个）⇒ 有则跑检索 Top-3
    · ⛔ 片段仅**诊断用 ≤60 字符**，不落盘
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

SEG = 60


def retrieve(obj, skills, topn=3):
    keys = rif.OBJ_PHRASES.get(obj, [])
    qts = [ep.tokenize(k) for k in keys if ep.query_has_signal(ep.tokenize(k))]
    if not qts:
        return [], 0
    rows = dp.run_hard(qts, skills, cats=dp.OBJ2CAT.get(obj, []) or None)
    return [(s.get("name_zh") or s.get("name"), s.get("cat_zh")) for *_x, s in rows[:topn]], len(rows)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cache = os.path.join(CACHE, "_zh_skill_registry.json")
    skills = ((json.load(io.open(cache, "r", encoding="utf-8", errors="replace")).get("skills") or [])
              if os.path.isfile(cache) else [])
    blob = json.loads(sys.stdin.read())
    rs = [e for e in (blob.get("events") or []) if e.get("kind") == "reasoning"]

    print("=== 诊断：**最初 1–3 个推理块**能得到什么（只读 · ⛔ 不落原文）===")
    print("会话：`%s` · reasoning 块 **%d**" % (blob.get("session"), len(rs)))

    for k in (1, 2, 3):
        if k > len(rs):
            continue
        b = rs[k - 1]
        t = b.get("text") or ""
        keep, drop = rfp.fx.imperative_clauses(t)
        objs = rfp.objects_in(t)
        obj, why, deg, reason = rfp.fx.focus_object(t)
        print("\n--- 最初 %d 块（`seq=%s`）· **%d 字符** · 分句：祈使 **%d** / 滤掉 **%d**"
              % (k, b.get("seq"), len(t), len(keep), len(drop)))
        print("    命中对象（动作窗口内）：%s"
              % (" · ".join("%s×%d" % kv for kv in Counter(objs).most_common()) or "**（无）**"))
        if deg:
            print("    ⇒ 焦点对象：**无**（%s）" % reason)
        else:
            print("    ⇒ 焦点对象：**`%s`** ← 依据 `%s`" % (obj, why[:SEG]))
            top, pool = retrieve(obj, skills)
            print("       检索：池 **%d** · Top-3：%s"
                  % (pool, " / ".join("%s[%s]" % (n, (c or "-")[:6]) for n, c in top) or "（无候选）"))
        print("    片段（≤%d · 诊断用）：`%s`" % (SEG, t[:SEG].replace("\n", " ")))
        if keep:
            print("    首个祈使分句（≤%d）：`%s`" % (SEG, keep[0][:SEG]))

    # ── 对照：**窗口放宽到整句** + 补「认知动作词」────────────────────
    # 上一版只补动作词 ⇒ **无变化** ⇒ 定位到真正缺陷：窗口 `±8` 太窄
    #   （"让我先读取 HANDOFF §八 和 recall 记忆"里 `读取`→`记忆` 相距 ~13 字符）
    print("\n--- 对照：**窗口放宽到整句** + 补认知动作词（读·读取·看·查·找·搜·扫·回顾·确认）---")
    orig = list(rfp.fx.ACTIONS)
    rfp.fx.ACTIONS = orig + ["读", "读取", "看", "查", "找", "搜", "扫", "回顾", "确认"]

    def wide(text):
        low = text.lower()
        if not any(a in low for a in rfp.fx.ACTIONS):
            return []
        return [o for o, terms in dp.OBJ_TERMS.items() if any(t.lower() in low for t in terms)]

    for k in (1, 2, 3):
        if k > len(rs):
            continue
        b = rs[k - 1]
        t = b.get("text") or ""
        keep, _d = rfp.fx.imperative_clauses(t)
        objs = []
        for cl in keep:
            objs.extend(wide(rfp.fx.QUOTE_RE.sub(" ", cl)))
        obj = objs[0] if objs else None
        print("    最初 %d 块：命中对象 %s ⇒ 焦点 **%s**"
              % (k, " · ".join("%s×%d" % kv for kv in Counter(objs).most_common()) or "（无）",
                 obj or "无"))
        if obj:
            top, pool = retrieve(obj, skills)
            print("        检索：池 **%d** · Top-3：%s"
                  % (pool, " / ".join("%s[%s]" % (n, (c or "-")[:6]) for n, c in top) or "（无候选）"))
    rfp.fx.ACTIONS = orig

    print("\n（只读 · 内存态 · ⛔ 推理原文未落盘 · 未改机制/闸门/语料/本体）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
