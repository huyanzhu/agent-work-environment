#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_runtime_input_form_probe.py — 验证「Runtime 有工作对象+领域职能 ⇒ 检索才能带回能力」（只读 · 离线）

假设
    *"当 Runtime 拥有工作对象以及领域职能时，它交给检索，检索才能得到能力并将其带回"*
    *"你可以先试着跑一下验证一下"*

唯一变量 = **Runtime 交给检索的输入形态**（判别规则与池一律不变）
    V0 卡 `Goal` **原文**（现状口径 · 一个查询串）
    V1 卡的**完整工作上下文**（`Goal` + `Current Step` + `Next Action` · 一个查询串）
    V2 **工作对象 + 领域职能**（受控词 → **短语化**：`前端界面实现` / `数据库迁移` / `设计令牌` …）
    V3 V2 + 卡里的**技术专名**（机械提取的 ASCII 技术词，如 `next.js` / `supabase`）
判别（沿用上一轮读数结论 · ⛔ 不改）
    · **名称硬门槛**（`name_zh`/`name`/`slug` 一个词都没命中 ⇒ 出局）
    · **工作对象过滤**（`category_zh` 与对象对齐）—— 按上一轮结论，**仅在领域职能明确时启用**
池：中文注册表 5005 技能（同一份缓存）· ⛔ 不换池、不改机制、不联网

读数：各形态的**候选池规模** + **Top-5**（relevance@5 由 Agent 判 · ⚠️ 非独立验证）
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
import _zh_skill_discrimination_probe as dp          # 复用：hits / run_hard / OBJ_TERMS / OBJ2CAT

# 🔴 **修正（夹具隔离）**：下表原直接指向**真实卡**（`task_cards/active/…`）——
#   于是真实卡一改 `State`（读数：产品卡 `Executing → Parked`、本卡 `Waiting → Executing`），
#   自测就从 **12/12 掉到 3/12**，把"卡内容漂移"误报成"字段产出回归"。
#   ⇒ 施工态样本一律指向 `tools/probes/fixtures/cards/` 下**冻结的夹具卡**：
#     自测只验证「给定卡内容 → 字段产出」这条逻辑，⛔ 不再拿真实工作卡当夹具。
#   ⚠️ G3/G4 仍是真实卡（只作"宽档样本"的 input-form 使用，不参与字段验收）。
CARDS = {
    "G1": "tools/probes/fixtures/cards/TASK-20261009-001.md",   # 施工态 · 对象=`运行时`
    "G2": "tools/probes/fixtures/cards/TASK-20261008-001.md",   # 施工态 · 对象=`前端`（HEAD 时的真实产品卡）
    "G3": "task_cards/active/demo-project/TASK-20261003-001.md",   # Reviewing（宽档样本）
    "G4": "task_cards/active/TASK-20260820-001.md",                   # Parked（宽档样本）
}
GOAL_RE = re.compile(r"^##\s+Goal\s*\n(.*?)(?=^##\s|\Z)", re.M | re.S)
STEP_RE = re.compile(r"^Current Step:\s*(.+)$", re.M)
NEXT_RE = re.compile(r"^Next Action:\s*(.+)$", re.M)

# ── 工作对象 → **领域职能短语**（透明映射 · 机械展开）───────────────────────────
# 🔴 **一次失败的方法论尝试（如实记）**：曾用 `_phrase_quality_probe.py` 按
#   「池内指标」（pool + theme_ratio = 命中候选名含对象标识词的比例）自动选优短语 ⇒
#   池从 **155 → 28**（更集中），但端到端 Top-8 的**任务可用性反而下降（5–6 → 3–4 条）**：
#   `前端样式实现` 这类高 ratio 键只捞到"暗色模式实现 / CSS 样式专家"，
#   **漏掉了对任务真正有用的"设计系统类"候选**（前端设计大师 / 交互设计模式 / 前端设计系统）。
#   ⇒ 🔴 **结论：池内指标优化的是"键的专指性"，不等于"候选对任务可用"** ——
#     后者必须以**任务侧真值**（期望候选集）为目标，池内指标**无法代理**。
#   ⇒ 故短语组**回滚为读数更优的旧值**（保留本条记录，防重犯）。
OBJ_PHRASES = {
    "前端": ["前端界面实现", "组件设计", "前端交互实现"],
    "后端": ["后端接口实现", "服务端鉴权", "API 设计"],
    "数据库": ["数据库迁移", "数据库 schema 设计", "SQL 查询优化"],
    "设计": ["设计令牌", "设计系统", "视觉设计"],
    "测试": ["单元测试", "测试驱动开发", "验收测试"],
    "部署": ["部署上线", "CI/CD 流水线", "发布管理"],
    "检索": ["检索召回", "搜索实现", "能力发现"],
    "运行时": ["运行时机制", "事件驱动", "上下文管理"],
    "技能": ["技能发现", "技能装配", "能力评估"],
    "记忆": ["长期记忆", "工作记忆", "经验沉淀"],
    "文档": ["文档撰写", "文档规范", "README 维护"],
    "审核": ["代码审查", "安全审计", "评审流程"],
    # 按规范 §3「扩展登记」新增（与 OBJ_TERMS / OBJ2CAT 同步）
    "编排": ["任务编排", "闭环流水线", "子流调度"],
    "评估": ["评估层实现", "Governor 治理", "指标与基准"],
}


def read(rel):
    return io.open(os.path.join(AIOS_ROOT, rel.replace("/", os.sep)), "r",
                   encoding="utf-8", errors="replace").read()


def card_parts(rel):
    raw = read(rel)
    g = GOAL_RE.search(raw)
    s = STEP_RE.search(raw)
    n = NEXT_RE.search(raw)
    return (re.sub(r"\s+", " ", g.group(1)).strip() if g else "",
            re.sub(r"\s+", " ", s.group(1)).strip() if s else "",
            re.sub(r"\s+", " ", n.group(1)).strip() if n else "")


def ascii_terms(text):
    return sorted(t for t in ep.tokenize(text) if ep.RE_STRONG_TERM.match(t))


def forms(goal, step, nxt, objs, objs_step):
    v2 = " ".join(p for o in objs for p in OBJ_PHRASES.get(o, []))
    v3 = (v2 + " " + " ".join(ascii_terms(goal + " " + step + " " + nxt)[:12])).strip()
    v4 = " ".join(p for o in objs_step for p in OBJ_PHRASES.get(o, []))
    return {
        "V0 Goal原文": goal,
        "V1 完整工作上下文": (goal + " " + step + " " + nxt).strip(),
        "V2 **工作对象+领域职能**": v2,
        "V3 V2+技术专名": v3,
        "V4 **焦点对象**（仅 Step/Next Action）": v4,
    }


def probe(skills, tag, label, text, cats):
    qts = [ep.tokenize(text)] if text else []
    if not qts or not ep.query_has_signal(qts[0]):
        return None, None, 0
    no_f = dp.run_hard(qts, skills)
    with_f = dp.run_hard(qts, skills, cats=cats) if cats else []
    return no_f, with_f, len(qts[0])


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cache = os.path.join(CACHE, "_zh_skill_registry.json")
    if not os.path.isfile(cache):
        print("⚠️ 缺中文注册表缓存：`%s`" % cache)
        return 1
    skills = (json.load(io.open(cache, "r", encoding="utf-8", errors="replace")).get("skills") or [])
    print("=== 验证：Runtime 有「工作对象+领域职能」时，检索能否带回能力（只读 · 离线）===")
    print("池：中文注册表 **%d** 技能 ｜ 判别：**名称硬门槛**（⛔ 不加权）+「有过滤」= 工作对象对齐 `category_zh`"
          % len(skills))
    print("形态：V0 Goal原文 · V1 完整工作上下文 · V2 **对象+职能短语** · V3 V2+技术专名")

    summary = {}
    for tag, rel in CARDS.items():
        goal, step, nxt = card_parts(rel)
        objs = dp.objects_of((goal + " " + step + " " + nxt).lower())
        objs_step = dp.objects_of((step + " " + nxt).lower())
        cats = sorted({c for o in objs for c in dp.OBJ2CAT.get(o, [])})
        cats_step = sorted({c for o in objs_step for c in dp.OBJ2CAT.get(o, [])}) or cats
        print("\n" + "=" * 82)
        print("卡 %s `%s`" % (tag, rel))
        print("  工作对象（整卡上下文 · 机械匹配）：**%s**" % (objs or "（无）"))
        print("  🔴 **焦点对象**（仅 `Current Step`/`Next Action`）：**%s**" % (objs_step or "（无）"))
        print("  V2 键：%s" % " · ".join(p for o in objs for p in OBJ_PHRASES.get(o, [])))
        print("  V4 键：%s" % (" · ".join(p for o in objs_step for p in OBJ_PHRASES.get(o, [])) or "（空 ⇒ 退化）"))
        for label, text in forms(goal, step, nxt, objs, objs_step).items():
            cc = cats_step if label.startswith("V4") else cats
            no_f, with_f, ntok = probe(skills, tag, label, text, cc)
            if no_f is None:
                print("\n  [%s] 查询信息量不足 ⇒ 不触发" % label)
                continue
            print("\n  [%s] 字符 %d · token %d ｜ 池（无过滤）**%d** ｜ 池（有过滤）**%d**"
                  % (label, len(text), ntok, len(no_f), len(with_f)))
            use = with_f if with_f else no_f
            kind = "有过滤" if with_f else "无过滤"
            for sc, nn, tt, dd, s in use[:5]:
                print("      ▸ %-26s [%s] 名%d/标%d/述%d" %
                      ((s.get("name_zh") or s.get("name"))[:26], (s.get("cat_zh") or "-")[:6], nn, tt, dd))
            summary[(tag, label)] = {"pool_no": len(no_f), "pool_f": len(with_f),
                                     "top": [(s.get("name_zh") or s.get("name"), s.get("cat_zh"))
                                             for *_x, s in use[:5]], "kind": kind}

    print("\n" + "=" * 82)
    print("--- 汇总：候选池规模（无过滤 | 有过滤）---")
    for tag in CARDS:
        row = ["%s：" % tag]
        for label in ("V0 Goal原文", "V1 完整工作上下文", "V2 **工作对象+领域职能**",
                      "V3 V2+技术专名", "V4 **焦点对象**（仅 Step/Next Action）"):
            v = summary.get((tag, label))
            row.append("%s=%s|%s" % (label.split()[0], v["pool_no"], v["pool_f"]) if v else "-")
        print("   " + "  ".join(row))
    print("\n（只读 · 离线 · 未改机制/闸门/语料 · 未安装执行外部内容）")
    print("⚠️ relevance 由 Agent 判 ｜ ⚠️ 对象过滤仅对**领域职能明确**的卡启用（上一轮实测结论）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
