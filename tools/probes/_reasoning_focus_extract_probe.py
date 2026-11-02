#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_reasoning_focus_extract_probe.py — 从**推理文本**提取焦点对象（只读 · 内存态 · ⛔ 不落原文）

    *"你看看推理文本呢，看看能不能提取到"*
    （背景：卡字段 `Next Action` 单字段只覆盖 3/12，回退链到 67% 但质量下降 ⇒ 试推理文本）

输入：`node scratch/_ctx_snapshot_evidence.mjs <archive> --emit` 的 **stdin JSON**
      （逐帧解压 · ASCII-escaped ⇒ 管道安全 · 解压文本**不落盘**）
机制：与卡字段**同一套**提取器（分句 → 跳过'已完成事实' → 去引号 → **动作词窗口**内匹配对象）
读数：① 覆盖率（多少推理块能提取到对象）② **对象分布**（Top 对象）③ 与卡字段对照
纪律：⛔ 只输出**对象名 / 命中计数 / 块序号** —— ⛔ 不回显推理原文（仅极短依据片段，≤40 字符）
"""
import io
import json
import os
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
import _zh_skill_discrimination_probe as dp
import _runtime_input_form_probe as rif
import _focus_object_extractor_probe as fx

BRIEF = 40          # 依据片段最大字符（⛔ 不回显原文）
# 「元话语对象」：既是受控对象词、又常被当作**动作/元操作**使用
#   （"设计一个探针" / "写文档" / "跑测试" / "审核一下"）
#   ⇒ 在推理文本里会**霸榜**（读数：设计 128 / 文档 90 / 测试 64，压过真实对象）
META_OBJECTS = ("设计", "文档", "测试", "审核")


def objects_in(text, wide=True):
    """→ [对象]（该块内**所有**与动作词同现的对象 · 不取"第一个"）。

    `wide=True` 用**片段级**匹配（修正窗口 ±8 过窄 / 动作与对象被分句切开两处缺陷）。
    """
    out = []
    keep, _drop = fx.imperative_clauses(text)
    prev = ""
    for cl in keep:
        c2 = fx.QUOTE_RE.sub(" ", cl)
        out.extend(fx.match_objects((prev + " " + c2) if wide else c2, wide=wide))
        prev = c2
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raw = sys.stdin.read()
    try:
        blob = json.loads(raw)
    except Exception as exc:
        print("⚠️ 无法解析 stdin JSON：%s" % exc)
        return 1
    ev = blob.get("events") or []
    rs = [e for e in ev if e.get("kind") == "reasoning"]
    print("=== 从**推理文本**提取焦点对象（只读 · ⛔ 不落原文）===")
    print("会话：`%s` · 事件 %d · **reasoning 块 %d** · 总字符 %d"
          % (blob.get("session"), len(ev), len(rs),
             sum(len(e.get("text") or "") for e in rs)))
    if not rs:
        print("⚠️ 该会话存档里没有 reasoning 块（⛔ 不静默当零命中）")
        return 1

    # ① 单块覆盖率（"第一个对象"口径）与 ② 全块对象分布
    ok = 0
    hist_all, hist_last, first_objs = Counter(), Counter(), Counter()
    for i, e in enumerate(rs):
        objs = objects_in(e.get("text") or "")
        if objs:
            ok += 1
            hist_all.update(objs)
        obj1, _why, degraded, _r = fx.focus_object(e.get("text") or "", wide=True)
        if not degraded:
            first_objs.update([obj1])
    ok_narrow = sum(1 for e in rs if objects_in(e.get("text") or "", wide=False))
    for e in rs[-20:]:
        hist_last.update(objects_in(e.get("text") or ""))

    print("\n① **覆盖率**（能提取到至少一个工作对象的推理块）")
    print("   窄档（±8 窗口）：**%d/%d = %.0f%%**" % (ok_narrow, len(rs), 100.0 * ok_narrow / len(rs)))
    print("   **宽档（片段级 + 跨分句）**：**%d/%d = %.0f%%**" % (ok, len(rs), 100.0 * ok / len(rs)))
    print("   （对照：卡字段 `Next Action` = 3/12 窄 · 25% ｜ 三字段回退链 = 67%）")

    print("\n② **对象分布**（全部 %d 块 · 出现计数）" % len(rs))
    for o, n in hist_all.most_common(15):
        print("   %-8s %d" % (o, n))

    print("\n③ **窗口对比**（越近的窗口越接近「此刻在做什么」· 卡字段只给「当前一步」）")
    for w in (1, 3, 5, 10, 20, 50):
        if w > len(rs):
            continue
        h = Counter()
        for e in rs[-w:]:
            h.update(objects_in(e.get("text") or ""))
        print("   最后 %-3d 块：%s" % (w, " · ".join("%s×%d" % kv for kv in h.most_common(5))))
    print("   全 %-3d 块：%s" % (len(rs), " · ".join("%s×%d" % kv for kv in hist_all.most_common(5))))
    print("   ⚠️ 不做固定的元话语排除：实测同一词在两会话里性质不同"
          "（研究会话的 `设计` = 元话语；施工会话的 `测试` = **真实对象**）")

    print("\n（只读 · 内存态 · ⛔ 推理原文未落盘 · 未改机制/闸门/语料/本体）")
    print("⚠️ 对象分布由 Agent 判读（非独立验证）｜ 对象/动作词表为首版启发式")
    return 0


if __name__ == "__main__":
    sys.exit(main())
