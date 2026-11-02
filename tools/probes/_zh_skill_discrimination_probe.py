#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_zh_skill_discrimination_probe.py — 「**名称优先 + 工作对象优先**」判别力对照（只读 · 离线）

指令
    *"我认为你说的判别力，应该优先是**名称优先 + 工作对象优先**，类似前后端 审核之类。"*

背景（为什么需要它）
    `_e2e_runtime_retrieval_pipeline.py` 已跑通六段链路，但中文源命中 **2228/5005 = 44%**（G1）·
    **1692/5005 = 34%**（G2）⇒ **"命中"本身几乎不含信息**（同一失败模式：阶段九 G-1 的
    "标记词过宽 ⇒ 候选爆炸"换到了外部池）。本探针只改**"键的用法与排序"**，⛔ **不改机制 / 不换池**。

两条规则的机械落实
    ① **名称优先**：命中落在 `name_zh` ⇒ ×3 · `tags`/`category_zh` ⇒ ×2 · `description_zh` ⇒ ×1
    ② **工作对象优先**：用**受控工作对象词表**（前后端/审核/检索/设计/迁移…）从卡的
       `Goal + Current Step + Next Action` **机械匹配**出该卡的工作对象 ⇒
       与注册表 `category_zh` **对齐过滤**（无关类别直接出局，如"教育"）

四档对照（同一份缓存 · 同一批技能 · 唯一变量 = 键的用法与排序）
     **现状基线**：Agent 短语键 × 命中词数排序 × 不过滤
     名称优先：同上 + 名称加权排序
     **名称优先 + 工作对象过滤**（= 给的规则）
     工作对象**作主键** + 名称优先 + 过滤（更极端形态）
读数：命中池规模 · **Top-10** · **precision@10**（对照**预登记**的"期望关键词" · 透明可核）

只读 · 离线（读 `_zh_skill_registry.json` 缓存 · 无网络）
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
# 运行期生成物（注册表缓存 / 名称索引）—— `.aios/` 不进版本库（外部数据 + 体积）。
CACHE = os.environ.get("AIOS_STATE_DIR") or os.path.join(AIOS_ROOT, ".aios")
# TOOLS 由头部统一提供（AIOS_ROOT/tools）
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import experience_push as ep

ZH_CACHE = os.path.join(CACHE, "_zh_skill_registry.json")
CARDS = {
    "G1": "task_cards/active/AI-OS-Adaptation/TASK-20261009-001.md",
    "G2": "task_cards/active/demo-project/TASK-20261008-001.md",
}
GOAL_RE = re.compile(r"^##\s+Goal\s*\n(.*?)(?=^##\s|\Z)", re.M | re.S)
STEP_RE = re.compile(r"^(?:Current Step|Next Action):\s*(.+)$", re.M)

# ── 受控**工作对象**词表（*"类似前后端 审核之类"*）—— 中英对照 ──────────────
#    用法：从卡的工作上下文**机械匹配**出对象词 ⇒ 既作过滤依据，也可作主键
OBJ_TERMS = {
    "前端": ["前端", "界面", "组件", "frontend", "ui", "next.js", "tailwind", "react"],
    "后端": ["后端", "接口", "服务端", "backend", "api", "route handler"],
    "数据库": ["数据库", "迁移", "schema", "sql", "supabase", "postgres", "sqlite", "drizzle", "orm"],
    "设计": ["设计", "视觉", "令牌", "design", "figma", "样式", "css"],
    "测试": ["测试", "验收", "test", "tdd", "断言"],
    "部署": ["部署", "上线", "发布", "deploy", "vercel", "ci"],
    "检索": ["检索", "搜索", "召回", "retrieval", "search", "find"],
    "运行时": ["运行时", "runtime", "hook", "事件", "上下文", "context", "机制"],
    "技能": ["技能", "能力", "skill", "capability", "装配", "发现"],
    "记忆": ["记忆", "账本", "memory", "ledger"],
    "文档": ["文档", "规范", "doc", "readme", "报告"],
    "审核": ["审核", "评审", "审查", "review", "审计", "audit"],
    # ↓ 按规范 §3「扩展登记」新增（读数：`评估层`/`Governor`/`端到端闭环` 原不在词表
    #   ⇒ 那类卡永远无法提取对象）
    "编排": ["编排", "子流", "task graph", "control plane", "闭环", "流水线", "pipeline", "orchestrat"],
    "评估": ["评估", "governor", "指标", "benchmark", "评分", "evaluation"],
}
# 工作对象 → 注册表 `category_zh` 的**对齐映射**（只用于过滤 · 透明可核）
OBJ2CAT = {
    "前端": ["设计", "开发工具", "集成"],
    "后端": ["开发工具", "集成", "数据工具"],
    "数据库": ["数据工具", "开发工具"],
    "设计": ["设计", "集成"],
    "测试": ["开发工具", "测试工具", "效率工具"],
    "部署": ["开发工具", "集成", "效率工具"],
    "检索": ["效率工具", "开发工具"],
    "运行时": ["开发工具", "效率工具"],
    "技能": ["效率工具", "开发工具"],
    "记忆": ["开发工具", "效率工具"],
    "文档": ["效率工具", "办公工具"],
    "审核": ["开发工具", "效率工具"],
    "编排": ["开发工具", "效率工具", "集成"],
    "评估": ["开发工具", "效率工具", "测试工具"],
}
# ── Agent 短语键（与上一轮链路原型同源 · 作为"次级键"对照）──────────────────────
KEYS_AGENT = {
    "G1": ["能力发现", "技能发现", "技能检索", "工作上下文", "运行时上下文", "自动触发检索"],
    "G2": ["前端界面", "前端实现", "组件设计", "视觉层次", "设计令牌", "数据库迁移"],
}
# ── 预登记"期望关键词"（⚠️ 作者判断 · 透明列出 · 用于算 precision@10）──────────────
EXPECT = {
    "G1": ["技能", "skill", "能力", "发现", "记忆", "上下文", "检索", "安装", "registry", "评估"],
    "G2": ["迁移", "数据库", "drizzle", "前端", "设计", "figma", "组件", "界面", "tailwind", "部署"],
}


def read(rel):
    return io.open(os.path.join(AIOS_ROOT, rel.replace("/", os.sep)), "r",
                   encoding="utf-8", errors="replace").read()


def card_context(rel):
    raw = read(rel)
    g = GOAL_RE.search(raw)
    steps = " ".join(m.group(1) for m in STEP_RE.finditer(raw))
    return ((re.sub(r"\s+", " ", g.group(1)) if g else "") + " " + steps).lower()


def objects_of(ctx):
    """机械匹配**工作对象**（受控词表）—— ⛔ 不做语义判断。"""
    return [obj for obj, terms in OBJ_TERMS.items() if any(t.lower() in ctx for t in terms)]


def skill_text(s, which):
    if which == "name":
        return " ".join([s.get("name_zh") or "", s.get("name") or "", s.get("slug") or ""])
    if which == "tags":
        return " ".join([s.get("cat_zh") or "", " ".join(s.get("tags") or [])])
    return " ".join([s.get("desc_zh") or "", s.get("desc_en") or ""])


def hits(qts, s):
    """→ (name_hits, tag_hits, desc_hits)（去重后的有效命中词数）。"""
    out = []
    for which in ("name", "tags", "desc"):
        got = set()
        for qt in qts:
            eff, _n = ep.split_hits(qt & ep.tokenize(skill_text(s, which)))
            got |= eff
        out.append(len(got))
    return tuple(out)


def run(keys, keys_qts, skills, cats=None, rank_by_name=False):
    rows = []
    for s in skills:
        if cats is not None and (s.get("cat_zh") or "") not in cats:
            continue
        n, t, d = hits(keys_qts, s)
        if n + t + d == 0:
            continue
        score = (3 * n + 2 * t + 1 * d) if rank_by_name else (n + t + d)
        rows.append((score, n, t, d, s))
    rows.sort(key=lambda r: (-r[0], -r[1], str(r[4].get("name_zh"))))
    return rows


def run_hard(keys_qts, skills, cats=None):
    """**名称硬门槛**：`name_zh`/`name` 一个词都没命中 ⇒ **直接出局**（名称优先的强形态）。"""
    rows = []
    for s in skills:
        if cats is not None and (s.get("cat_zh") or "") not in cats:
            continue
        n, t, d = hits(keys_qts, s)
        if n == 0:
            continue
        rows.append((3 * n + 2 * t + 1 * d, n, t, d, s))
    rows.sort(key=lambda r: (-r[0], -r[1], str(r[4].get("name_zh"))))
    return rows


def p_at_10(rows, expect):
    top = " ".join(((r[4].get("name_zh") or "") + " " + (r[4].get("name") or "") + " "
                    + (r[4].get("desc_zh") or "") + " " + " ".join(r[4].get("tags") or [])).lower()
                   for r in rows[:10])
    return sum(1 for e in expect if e.lower() in top), len(rows)


def run_card(tag, skills):
    ctx = card_context(CARDS[tag])
    objs = objects_of(ctx)
    cats = sorted({c for o in objs for c in OBJ2CAT.get(o, [])})
    key_obj = objs
    kq = lambda ks: [ep.tokenize(k) for k in ks if ep.query_has_signal(ep.tokenize(k))]

    print("\n" + "=" * 80)
    print("卡 %s — 工作对象（机械匹配受控词表）：**%s**" % (tag, objs or "（无）"))
    print("  ⇒ 对齐 `category_zh` 过滤集：%s" % (cats or "（无）"))
    print("  键：Agent 短语 %d 个 · 工作对象 %d 个 · 期望关键词（预登记）%s"
          % (len(KEYS_AGENT[tag]), len(key_obj), EXPECT[tag]))

    variants = [
        ("B0 现状基线（短语键 · 命中数排序 · 不过滤）",
         run(KEYS_AGENT[tag], kq(KEYS_AGENT[tag]), skills)),
        ("B1 名称优先（短语键 · 名称加权 · 不过滤）",
         run(KEYS_AGENT[tag], kq(KEYS_AGENT[tag]), skills, rank_by_name=True)),
        ("B2 **名称优先 + 工作对象过滤**（Human 的规则）",
         run(KEYS_AGENT[tag], kq(KEYS_AGENT[tag]), skills, cats=cats, rank_by_name=True)),
        ("B3 工作对象**作主键** + 名称优先 + 过滤",
         run(key_obj, kq(key_obj), skills, cats=cats, rank_by_name=True)),
        ("B4 **名称硬门槛**（名称未命中 ⇒ 出局）· 不过滤",
         run_hard(kq(KEYS_AGENT[tag]), skills)),
        ("B5 **名称硬门槛 + 工作对象过滤**（最强形态）",
         run_hard(kq(KEYS_AGENT[tag]), skills, cats=cats)),
    ]
    for label, rows in variants:
        p, n = p_at_10(rows, EXPECT[tag])
        pool = 100.0 * n / len(skills) if skills else 0
        print("\n  [%s]" % label)
        print("    命中池 **%d/%d（%.0f%%）** · **precision@10 = %d/10**" % (n, len(skills), pool, p))
        for sc, nn, tt, dd, s in rows[:10]:
            print("      ▸ %-26s [%s] score=%d (名%d/标%d/述%d)"
                  % ((s.get("name_zh") or s.get("name"))[:26], (s.get("cat_zh") or "-")[:6], sc, nn, tt, dd))
    return variants


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not os.path.isfile(ZH_CACHE):
        print("⚠️ 中文注册表缓存不存在：`%s`（请先跑 `_e2e_runtime_retrieval_pipeline.py`）" % ZH_CACHE)
        return 1
    blob = json.load(io.open(ZH_CACHE, "r", encoding="utf-8", errors="replace"))
    skills = blob.get("skills") or []
    print("=== 「名称优先 + 工作对象优先」判别力对照（只读 · 离线）===")
    print("池：中文注册表 **%d** 技能 · %s" % (len(skills), blob.get("version")))
    print("排序权重：名称 ×3 · 标签/分类 ×2 · 描述 ×1 ｜ 过滤：`category_zh` 与工作对象对齐")
    print("⚠️ precision@10 对照的是**预登记期望关键词**（作者判断 · 透明可核 · 非独立验证）")
    for tag in CARDS:
        run_card(tag, skills)
    print("\n（只读：未改机制 / 未换池 / 未联网 / 未安装执行外部内容）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
