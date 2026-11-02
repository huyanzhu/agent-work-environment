#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_focus_object_extractor_probe.py — **V5″：焦点对象提取器（窄/宽两档）+ 全卡覆盖率**（只读 · 离线）

：*"可以"*（同意修缺陷后复测）

V5′ 的**两个实现缺陷**（修正）：
    ❌ **窗口 ±8 过窄**：`让我先读取 HANDOFF §八 和 recall 记忆` 里 `读取`→`记忆` 相隔 ~13 字符
       ⇒ 修正：新增 **`wide=True` 片段级匹配**（当前分句 ∪ 紧邻上一分句内，动作词与对象词同现即可）
    ❌ **分句把动作与对象切开**：`按 §八 顺序读：` / `1. docs/rebuild/…` 被换行拆开
       ⇒ 修正：`wide` 档把**紧邻上一分句**并入窗口 ⇒ 跨分句也能配对
    ❌ **动作表缺认知动作词**（读/读取/看/查/找/搜/扫/回顾/确认）
       ⇒ 修正：补入 `ACTIONS`（⚠️ 单独补无效，必须与 同时修 —— 上一轮已读数）

样本：12 张新模板卡 ｜ 读数：窄档 vs **宽档** 覆盖率 · 宽档逐卡对象与 Top-5 · 回退链（宽档）
判别：中文注册表 5005 · **名称硬门槛** + 对象对齐 `category_zh`（⛔ 不改机制）
"""
import io
import json
import os
import re
import sys

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

# 「已完成事实」标记（句首 12 字符内出现 ⇒ 跳过该分句）
DONE_MARKERS = ["已", "完成", "通过", "修复", "收口", "生效", "就绪", "具备", "落地",
                "记档", "核实", "验掉", "对齐旧", "均"]
# 「动作词」——对象必须与动作词同现（补入认知动作词）
ACTIONS = ["推进", "交付", "实现", "替换", "迁移", "重构", "对齐", "接入", "部署", "发布",
           "修复", "设计", "撰写", "审核", "验证", "整理", "装载", "联调", "建立",
           "补", "加", "改", "建", "写", "跑", "测", "清", "拆", "接",
           "读", "读取", "看", "查", "找", "搜", "扫", "回顾", "确认"]
SPLIT_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩]|[·；;。\n]|(?<=\S)\s*[—–]\s*")
QUOTE_RE = re.compile(r"[\"“”'‘’][^\"“”'‘’]{0,60}[\"“”'‘’]")


def clauses(text):
    return [c.strip(" ·-—:：") for c in SPLIT_RE.split(text) if c and c.strip(" ·-—:：")]


def imperative_clauses(text):
    keep, drop = [], []
    for c in clauses(text):
        (drop if any(m in c[:12] for m in DONE_MARKERS) else keep).append(c)
    return keep, drop


def match_objects(text, wide=False):
    """对象必须落在**动作词窗口**内。

    `wide=False` 窄档：对象词 ±8 字符内有动作词（原实现）。
    `wide=True`  宽档：**片段级** —— 只要该片段内同时出现动作词与对象词即可
                        （修正 窗口过窄 · 动作/对象被分句切开）。
    """
    low = text.lower()
    has_action = any(a in low for a in ACTIONS)
    out = []
    for obj, terms in dp.OBJ_TERMS.items():
        for t in terms:
            i = low.find(t.lower())
            if i < 0:
                continue
            if wide:
                if has_action:
                    out.append(obj)
                break
            win = low[max(0, i - 8): i + len(t) + 8]
            if any(a in win for a in ACTIONS):
                out.append(obj)
                break
    return out


def focus_object(next_action, wide=False):
    """→ (对象, 依据句, degraded, 原因)。取**第一个**命中的祈使分句内的第一个对象。

    宽档下窗口 = `上一分句 + 当前分句`（ 修正：动作与对象可跨分句配对）。
    """
    keep, drop = imperative_clauses(next_action)
    prev = ""
    for c in keep:
        c2 = QUOTE_RE.sub(" ", c)
        objs = match_objects((prev + " " + c2) if wide else c2, wide=wide)
        if objs:
            return objs[0], c2.strip(), False, ""
        prev = c2
    return None, "", True, "祈使分句里没有与动作词同现的受控工作对象（祈使 %d / 滤掉 %d）" % (
        len(keep), len(drop))


def focus_chain(goal, step, nxt, wide=True):
    """回退链：`Next Action` → `Current Step` → `Goal`（均用同一档）。"""
    for src, text in (("NextAction", nxt), ("CurrentStep", step), ("Goal", goal)):
        obj, why, degraded, reason = focus_object(text, wide=wide)
        if obj:
            return obj, why, src, False, ""
    return None, "", "-", True, "三字段均无可用的焦点对象"


def all_cards():
    base = os.path.join(AIOS_ROOT, "task_cards", "active")
    out = []
    for root, _d, files in os.walk(base):
        for n in sorted(files):
            if n.endswith(".md") and ts.CARD_NAME_RE.match(n) and n.startswith("TASK-"):
                out.append(os.path.relpath(os.path.join(root, n), AIOS_ROOT).replace("\\", "/"))
    return sorted(out)


def retrieve(obj, skills, topn=5):
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
    cards = all_cards()
    print("=== V5″：焦点对象提取器（窄/宽两档）· 全卡覆盖率复测 ===")
    print("样本 **%d** 张新模板卡 ｜ 池 **%d** 技能 ｜ 判别：名称硬门槛 + 对象对齐 `category_zh`"
          % (len(cards), len(skills)))

    print("\n--- ① 单字段（`Next Action`）：**窄（±8）vs 宽（片段级）** ---")
    for label, wide in (("窄档 ±8 窗口", False), ("**宽档 · 片段级 + 跨分句配对**", True)):
        n = sum(1 for rel in cards if not focus_object(rif.card_parts(rel)[2], wide=wide)[2])
        print("    %-28s ⇒ **%d/%d = %.0f%%**" % (label, n, len(cards), 100.0 * n / len(cards)))

    print("\n--- ② 宽档逐卡（对象 · 池 · Top-5）---")
    for rel in cards:
        goal, step, nxt = rif.card_parts(rel)
        obj, why, degraded, _r = focus_object(nxt, wide=True)
        tag = os.path.basename(rel).replace("TASK-", "").replace(".md", "")
        if degraded:
            print("    %-14s 🔴 退化" % tag)
            continue
        top, pool = retrieve(obj, skills)
        print("    %-14s ✅ `%-6s` 池 %-4d %s" % (tag, obj, pool,
              " / ".join(n for n, _c in top[:5]) or "（无候选）"))

    print("\n--- ③ 回退链（**宽档** · NextAction → CurrentStep → Goal）---")
    ok, bysrc = 0, {}
    for rel in cards:
        goal, step, nxt = rif.card_parts(rel)
        obj, why, src, degraded, _r = focus_chain(goal, step, nxt, wide=True)
        if not degraded:
            ok += 1
            bysrc[src] = bysrc.get(src, 0) + 1
    print("    覆盖 **%d/%d = %.0f%%** · 来源分解 %s"
          % (ok, len(cards), 100.0 * ok / len(cards), sorted(bysrc.items())))

    print("\n（只读 · 离线 · 未改机制/闸门/语料/本体 · 未安装执行外部内容）")
    print("⚠️ Top-5 相关性由 Agent 判（非独立）｜ 对象/动作/已完成标记均为首版启发式")
    return 0


if __name__ == "__main__":
    sys.exit(main())
