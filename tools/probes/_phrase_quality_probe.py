#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_phrase_quality_probe.py — 「对象 → 领域职能短语」质量测量与选优（只读 · 离线）

背景（主线：把"字段"交给检索）
    读数：`前端` 的短语 ⇒ 池 155 · Top-8 相关 5–6；`运行时` 的短语 ⇒ 池 40 · Top-8 相关 1–2。
    ⇒ 短语质量直接决定候选质量，而它**是可以机械测量的**。

测什么（对每个「对象 × 候选短语」）
    `pool`           命中候选数（**名称硬门槛 + 类别对齐**后）
    `theme`          命中候选的**名称**里含该对象"自我标识词"的数量（= 是否真命中该对象族）
    `theme_ratio`    theme / pool（越高 ⇒ 该键越"专指"，而非撞上通用词）
    `top_cat`        命中候选里占比最高的类别（类别集中度）

选优规则（机械）
    · 剔除 `theme_ratio` 低者（撞通用词）
    · 剔除 `pool` 过小者（池里没有对口族 ⇒ 该对象当前**不可检索**，应如实报告）
    · 在剩下的里按 `theme_ratio` 取前 2–3 条组成该对象的短语组

用法：python scratch/_phrase_quality_probe.py [--obj=前端]
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

ZH_CACHE = os.path.join(CACHE, "_zh_skill_registry.json")

# ── 该对象的「自我标识词」：用于判断命中候选是否真属于这个对象族 ──────────────
ALIAS = {
    "前端": ["前端", "frontend", "ui", "界面", "组件", "css", "样式"],
    "后端": ["后端", "backend", "api", "接口", "服务端", "route"],
    "数据库": ["数据库", "sql", "postgres", "sqlite", "schema", "迁移", "database"],
    "设计": ["设计", "design", "figma", "样式", "ui", "视觉"],
    "测试": ["测试", "test", "tdd", "断言", "用例"],
    "部署": ["部署", "deploy", "发布", "ci", "cd", "发布"],
    "检索": ["检索", "搜索", "search", "召回", "index"],
    "运行时": ["运行时", "runtime", "上下文", "context", "hook", "生命周期"],
    "技能": ["技能", "skill", "能力", "capability"],
    "记忆": ["记忆", "memory", "知识库", "沉淀"],
    "文档": ["文档", "doc", "readme", "撰写", "笔记"],
    "审核": ["审查", "评审", "review", "审计", "audit"],
    "编排": ["编排", "工作流", "workflow", "流水线", "调度", "pipeline"],
    "评估": ["评估", "评分", "指标", "benchmark", "eval", "基准"],
}

# ── 候选短语（每个对象多写几条：更具体的 / 更宽的，让池来判）─────────────────
CANDS = {
    "前端": ["前端界面实现", "组件设计", "前端交互实现", "前端页面实现", "UI 组件开发", "前端样式实现"],
    "后端": ["后端接口实现", "服务端鉴权", "API 设计", "REST 接口开发", "服务端路由实现", "后端服务实现"],
    "数据库": ["数据库迁移", "数据库 schema 设计", "SQL 查询优化", "数据库备份恢复", "数据建模"],
    "运行时": ["运行时机制", "事件驱动", "上下文管理", "宿主事件机制", "运行时生命周期", "上下文注入机制"],
    "文档": ["文档撰写", "文档规范", "README 维护", "技术文档编写", "文档结构设计"],
    "编排": ["任务编排", "闭环流水线", "子流调度", "工作流编排", "任务依赖调度"],
    "评估": ["评估层实现", "Governor 治理", "指标与基准", "评分与基准测试", "质量评估体系"],
    "技能": ["技能发现", "技能装配", "能力评估", "技能检索", "能力发现机制"],
    "记忆": ["长期记忆", "工作记忆", "经验沉淀", "记忆存储", "经验检索"],
    "测试": ["单元测试", "测试驱动开发", "验收测试", "集成测试", "测试用例设计"],
    "设计": ["设计令牌", "设计系统", "视觉设计", "交互设计规范", "组件视觉设计"],
    "审核": ["代码审查", "安全审计", "评审流程", "代码评审", "变更审查"],
}

POOL_MIN, POOL_MAX = 5, 400


def measure(phrase, obj, skills):
    cats = dp.OBJ2CAT.get(obj, [])
    qt = ep.tokenize(phrase)
    if not ep.query_has_signal(qt):
        return None
    rows = dp.run_hard([qt], skills, cats=cats or None)
    names = [((s.get("name_zh") or "") + " " + (s.get("name") or "")).lower() for *_x, s in rows]
    alias = ALIAS.get(obj, [obj])
    theme = sum(1 for n in names if any(a.lower() in n for a in alias))
    cats_c = Counter((s.get("cat_zh") or "-") for *_x, s in rows)
    return {"pool": len(rows), "theme": theme,
            "theme_ratio": (theme / len(rows)) if rows else 0.0,
            "top_cat": cats_c.most_common(1)[0] if cats_c else ("-", 0)}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not os.path.isfile(ZH_CACHE):
        print("⚠️ 缺缓存 `%s`" % ZH_CACHE)
        return 1
    skills = (json.load(io.open(ZH_CACHE, "r", encoding="utf-8", errors="replace")).get("skills") or [])
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--obj="):
            only = a.split("=", 1)[1]
    objs = [only] if only else list(CANDS)
    print("=== 「对象 → 领域职能短语」质量测量（池 %d · 名称硬门槛 + 类别对齐）===" % len(skills))
    print("指标：pool 命中数 ｜ theme 命中候选名含该对象标识词的数 ｜ ratio=theme/pool ｜ 选取区间 pool∈[%d,%d]"
          % (POOL_MIN, POOL_MAX))

    best = {}
    for obj in objs:
        print("\n[%s] 类别对齐集：%s" % (obj, dp.OBJ2CAT.get(obj, [])))
        rows = []
        for ph in CANDS.get(obj, []):
            m = measure(ph, obj, skills)
            if not m:
                print("    %-22s ⇒ 信息量不足" % ph)
                continue
            flag = ""
            if m["pool"] < POOL_MIN:
                flag = " ⛔ 池过小（池里无对口族）"
            elif m["pool"] > POOL_MAX:
                flag = " ⛔ 池过大（撞通用词）"
            print("    %-22s pool=%-5d theme=%-4d ratio=%.2f  top_cat=%s(%d)%s"
                  % (ph, m["pool"], m["theme"], m["theme_ratio"], m["top_cat"][0], m["top_cat"][1], flag))
            rows.append((ph, m))
        ok = [(ph, m) for ph, m in rows if POOL_MIN <= m["pool"] <= POOL_MAX]
        ok.sort(key=lambda r: -r[1]["theme_ratio"])
        pick = [ph for ph, _m in ok[:3]]
        best[obj] = pick
        print("    ⇒ **推荐短语组**：%s" % (" · ".join(pick) if pick else "（无合格候选 ⇒ 该对象当前不可检索，如实报告）"))

    print("\n--- 汇总（可回写 `OBJ_PHRASES` 的建议值）---")
    for obj, pick in best.items():
        print("    \"%s\": %s," % (obj, json.dumps(pick, ensure_ascii=False)))
    print("\n（只读 · 离线 · 未改机制/闸门/语料/本体 —— 本探针只给测量值与建议，是否回写由人/下一步决定）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
