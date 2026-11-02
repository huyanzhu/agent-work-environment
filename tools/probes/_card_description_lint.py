#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_card_description_lint.py — 任务卡**描述规范**的机械检查器（只读）

：*"可以；同时需要改写任务卡的描述，比如 goal 以及 next action 的写作规范"*

它检查什么（⛔ 全部机械 · 无语义判断）
    【Goal】
      G1 **含受控工作对象词**（唯一能对齐材料 `category_zh` 的维度 —— 前几轮读数：对象提供粗筛维度）
      G2 **不含元信息**（`施工依据/恢复入口/基线/新仓库` 等标签 + 盘符路径）
         —— 读数：这些属**字段职责混淆**（应归 `Knowledge Used`/`Resume Point`）
      G3 **长度 ≤ 180 字符**（`task_start.py` 现行只读前 180 ⇒ 超长必被截断 · 本卡曾丢 82%）
      G4 结果 vs 动作 —— ⚠️ **需人判**（机械不可判 · 只报长度与对象供人看）
    【Next Action】
      N1 **含「动作词 + 受控工作对象」**（⇒ 字段产出器能提取焦点对象）
      N2 **不以非施工词开头**（等待/等/验收/裁定/观察/归档/确认后/待）
      N3 **长度 ≤ 120 字符**（供检索用的键应短）
      N4 **等待型必须自带"到位后做什么"**（含等待词 ⇒ 必须同时含 `到位后/之后/后再 + 动作+对象`）
         —— 否则 Runtime 无法从这条提取对象（读数：等待型卡全部退化）

用法：python scratch/_card_description_lint.py [--all]
"""
import io
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

import task_start as ts
import _runtime_input_form_probe as rif
import _focus_object_extractor_probe as fx
import _zh_skill_discrimination_probe as dp

GOAL_RE = re.compile(r"^##\s+Goal\s*\n(.*?)(?=^##\s|\Z)", re.M | re.S)
STATE_RE = re.compile(r"^State:\s*(.+)$", re.M)
NEXT_RE = re.compile(r"^Next Action:\s*(.+)$", re.M)

META_LABELS = ("施工依据", "恢复入口", "旧实现基线", "新仓库", "Resume Point", "基线")
PATH_RE = re.compile(r"[A-Za-z]:\\")
LEADING_NON = ("等待", "等 ", "验收", "裁定", "观察期", "观察", "归档", "确认后", "待")
WAIT_WORDS = ("等待", "等 ", "验收", "裁定", "确认后", "待")
AFTER_RE = re.compile(r"(到位后|之后|后再|后，|後)")
# N6（新增）：⛔ 不得把「历史 / 已完成项」写进 `Next Action`
#   读数（产品母卡 `TASK-20261008-001`）：`推进 S9（S8 前端四页已全部落地并收口）`
#   ⇒ 抽取器取走**词表里命中的** `前端`（历史），而当前对象 `S9` 不在词表 ⇒ 焦点对象错、类别跟着偏。
HISTORY_RE = re.compile(r"(已落地|已收口|已完成|已通过|已提交|已归档|全部落地)")

GOAL_MAX = 180
NA_MAX = 120


def read(rel):
    return io.open(os.path.join(AIOS_ROOT, rel.replace("/", os.sep)), "r",
                   encoding="utf-8", errors="replace").read()


def parts(rel):
    raw = read(rel)
    g = GOAL_RE.search(raw)
    s = STATE_RE.search(raw)
    # ⚠️ Next Action 必须按 **`task_start._next_action()` 的口径**取（**首行 + 缩进续行**），
    #    否则 lint 会漏掉"首行很短、续行很长"的情况（读数口径不一致 ⇒ 已修）
    return (re.sub(r"\s+", " ", g.group(1)).strip() if g else "",
            re.sub(r"\s+", " ", s.group(1)).strip() if s else "",
            re.sub(r"\s+", " ", ts._next_action(raw)).strip())


# ── 字段**唯一性**（新增）─────────────────────────────────────────────
# 机制只读**第一条** ⇒ 多行 = **静默失效**（既不生效、也不报错）。
#   · `Next Action` ⇒ 规范 `GOAL-INPUT-CONTRACT.md` **N5**（`task_start._next_action()` 只取第一条）
#   · `Current Step` / `State` ⇒ 同一条道理（`aios-activation` 与字段产出器都按 `re.M` 取首个匹配）
# 读数`AI-OS-Adaptation/TASK-20261009-001.md` 有**两个** `Current Step:` 行，
#   而第一个已经过时 ⇒ 机制读到的是**过时值**，且没有任何提示。
UNIQUE_FIELDS = (
    ("N5", "Next Action", re.compile(r"^Next Action:", re.M)),
    ("S3", "Current Step", re.compile(r"^Current Step:", re.M)),
    ("S3b", "State", re.compile(r"^State:", re.M)),
)


def lint_unique(rel):
    """字段唯一性：多行 ⇒ **静默失效**（⛔ 不是"取最后一条"，是"只认第一条"）。"""
    raw = read(rel)
    bad = []
    for tag, name, rx in UNIQUE_FIELDS:
        n = len(rx.findall(raw))
        if n > 1:
            bad.append("%s 多个 `%s:` 行（%d 行）⇒ 机制只读第一条，其余**静默失效**"
                       % (tag, name, n))
    return bad


def lint_goal(goal):
    bad = []
    objs = [o for o, terms in dp.OBJ_TERMS.items() if any(t.lower() in goal.lower() for t in terms)]
    if not objs:
        bad.append("G1 无受控工作对象词")
    meta = [m for m in META_LABELS if m in goal] + (["盘符路径"] if PATH_RE.search(goal) else [])
    if meta:
        bad.append("G2 含元信息 %s" % meta)
    if len(goal) > GOAL_MAX:
        bad.append("G3 超长 %d>%d（会被 `task_start` 截断）" % (len(goal), GOAL_MAX))
    return objs, bad


def lint_next(nxt):
    bad = []
    obj, _why, degraded, _r = fx.focus_object(nxt, wide=True)
    if degraded:
        bad.append("N1 提不到「动作+对象」")
    # N2（修正）：**⛔ 不得只表达"等待/验收/归档"** —— 只要「动作+对象」能从任意一段
    #   （含"到位后"那段）提取到，等待成分不构成不合规（原"不以非施工词开头"与 N4 冲突 ⇒ 废止）
    wait_w = [w for w in WAIT_WORDS if w in nxt[:40]]
    if wait_w and degraded:
        bad.append("N2 只表达等待/验收/归档（%s）且无「动作+对象」" % wait_w)
    if len(nxt) > NA_MAX:
        bad.append("N3 超长 %d>%d" % (len(nxt), NA_MAX))
    if wait_w and not (AFTER_RE.search(nxt) and obj):
        bad.append("N4 等待型且未声明「到位后 动作+对象」")
    # N6：历史 / 已完成陈述 ⇒ 会把当前对象顶掉（`HISTORY_RE` 见文件头）
    hist = sorted(set(HISTORY_RE.findall(nxt)))
    if hist:
        bad.append("N6 含历史/已完成陈述（%s）⇒ 会被当成当前对象" % "/".join(hist))
    return obj, bad


def all_cards():
    base = os.path.join(AIOS_ROOT, "task_cards", "active")
    out = []
    for root, _d, files in os.walk(base):
        for n in sorted(files):
            if n.endswith(".md") and ts.CARD_NAME_RE.match(n) and n.startswith("TASK-"):
                out.append(os.path.relpath(os.path.join(root, n), AIOS_ROOT).replace("\\", "/"))
    return sorted(out)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cards = all_cards()
    print("=== 任务卡描述规范 · 机械检查（%d 张新模板卡）===" % len(cards))
    print("Goal：G1 含工作对象 · G2 无元信息 · G3 ≤%d 字符 ｜ "
          "Next Action：N1 动作+对象 · N2 非施工开头 · N3 ≤%d · N4 等待型须声明「到位后」"
          % (GOAL_MAX, NA_MAX))
    g_ok = n_ok = both = 0
    for rel in cards:
        goal, state, nxt = parts(rel)
        objs, gbad = lint_goal(goal)
        nobj, nbad = lint_next(nxt)
        ubad = lint_unique(rel)
        tag = os.path.basename(rel).replace("TASK-", "").replace(".md", "")
        if not gbad:
            g_ok += 1
        if not nbad and not ubad:
            n_ok += 1
        if not gbad and not nbad and not ubad:
            both += 1
        print("\n  [%s] State=`%s`" % (tag, state[:26]))
        print("     Goal(%d 字符 · 对象 %s)：%s"
              % (len(goal), objs or "无", "✅" if not gbad else "⛔ " + "；".join(gbad)))
        print("     NextAction(%d 字符)：%s"
              % (len(nxt), "✅ 对象=`%s`" % nobj if not nbad else "⛔ " + "；".join(nbad)))
        if ubad:
            print("     唯一性：⛔ " + "；".join(ubad))
    print("\n--- 合规率 ---")
    print("  Goal 合规 **%d/%d** · Next Action 合规 **%d/%d** · **两者同时合规 %d/%d**"
          % (g_ok, len(cards), n_ok, len(cards), both, len(cards)))
    print("\n（只读：未改任何卡 · 未改机制/闸门/语料/本体）")
    print("⚠️ G4（结果 vs 动作）机械不可判 ⇒ 需人复核；本检查器只覆盖可机械化的部分")
    return 0


if __name__ == "__main__":
    sys.exit(main())
