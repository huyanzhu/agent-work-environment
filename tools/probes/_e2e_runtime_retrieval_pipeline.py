#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_e2e_runtime_retrieval_pipeline.py — **完整链路原型**：Runtime → 检索 → Runtime → 宿主

指令
    *"现在可以暂时抛掉纪律 —— 只做：怎么样能够达成 Runtime 检索 Runtime 宿主的完整链路。"*

🔴 **抛掉的纪律（如实列举 · 供 复核）**
    · 允许 Agent 派生检索键（此前标为"含 Agent 参与 · 非纯机械" ⇒ 作为链路正常组成）
    · 允许联网只读外部来源（含**中文 skill 站**）· 允许落 1 个 scratch 缓存
    · ⛔ **仍然不做（安全底线，未被指令覆盖）**：不安装 / 不执行外部技能内容 · 不提交 ·
      不注入宿主（需 重启）· 不改 AI-OS 本体 / 评分 / 闸门 / 语料

链路六段
    [1] Runtime 输入     读当前卡：Goal / Current Step / Next Action / 登记对象键
    [2] 查询构造         Query representation：中文键 + 英文键（⛔ 不把整段 Goal 当查询串）
    [3] 检索（4 源）     S1 本地能力(9) · S2 本地知识(domains+账本) ·
                         S3 **外部·中文** skill-hub 注册表(5005 技能 · 中英双语) ·
                         S4 **外部·英文** GitHub(47 候选 · 已采池)
    [4] 候选集           CandidateSet：统一身份/来源/版本/命中证据
    [5] 交回宿主         输出宿主可消费清单（**本会话里宿主 = Agent 本人** ⇒ 会话内即成立）
    [6] 宿主消费判定     由 Agent（= 宿主）判断适用性（⚠️ 非独立验证）

产物：`scratch/_zh_skill_registry.json`（**精简缓存**：仅 id/名称/中文描述/分类/标签 ·
      ⛔ 不落任何 SKILL.md 正文）· 读数打到 stdout
"""
import io
import json
import os
import re
import sys
import time
import urllib.request

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
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import experience_push as ep
import task_start as ts

ZH_CACHE = os.path.join(CACHE, "_zh_skill_registry.json")
EXT_POOL = os.path.join(PROBES, "_ext_full_pool.json")
ZH_REGISTRY_URL = ("https://raw.githubusercontent.com/kevinaimonster/skill-hub/"
                   "main/registry/recommendations.json")
ZH_REGISTRY_VER = "1.0.0 / updated 2026-03-19 / total_count 5005（来源仓库自述）"

GOAL_RE = re.compile(r"^##\s+Goal\s*\n(.*?)(?=^##\s|\Z)", re.M | re.S)
STEP_RE = re.compile(r"^Current Step:\s*(.+)$", re.M)
NEXT_RE = re.compile(r"^Next Action:\s*(.+)$", re.M)

CARDS = {
    "G1": "task_cards/active/AI-OS-Adaptation/TASK-20261009-001.md",
    "G2": "task_cards/active/demo-project/TASK-20261008-001.md",
}

# [2] 查询构造：Agent 派生键（本方 = 链路组成 · 非"纯机械"）
KEYS = {
    "G1": {
        "zh": ["能力发现", "技能发现", "技能检索", "工作上下文", "运行时上下文",
               "自动触发检索", "技能评估", "宿主事件"],
        "en": ["agent skill discovery", "skill invocation", "capability discovery",
               "work context understanding", "runtime context", "skill evaluation"],
    },
    "G2": {
        "zh": ["前端界面", "前端实现", "组件设计", "视觉层次", "交互体验",
               "设计令牌", "打包部署", "数据库迁移"],
        "en": ["frontend ui implementation", "webapp testing", "component design",
               "visual design", "design tokens", "database migration"],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# [1] Runtime 输入
# ─────────────────────────────────────────────────────────────────────────────

def read(rel):
    return io.open(os.path.join(AIOS_ROOT, rel.replace("/", os.sep)), "r",
                   encoding="utf-8", errors="replace").read()


def runtime_context(rel):
    raw = read(rel)
    g = GOAL_RE.search(raw)
    s = STEP_RE.search(raw)
    n = NEXT_RE.search(raw)
    return {
        "goal": re.sub(r"\s+", " ", g.group(1)).strip() if g else "",
        "current_step": re.sub(r"\s+", " ", s.group(1)).strip() if s else "",
        "next_action": re.sub(r"\s+", " ", n.group(1)).strip()[:200] if n else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# [3] 检索源
# ─────────────────────────────────────────────────────────────────────────────

def fetch_zh_registry():
    """中文技能注册表（5005 技能 · 中英双语）→ 精简缓存（⛔ 不落正文）。"""
    if os.path.isfile(ZH_CACHE):
        blob = json.load(io.open(ZH_CACHE, "r", encoding="utf-8", errors="replace"))
        return blob, "cache"
    raw = urllib.request.urlopen(ZH_REGISTRY_URL, timeout=120).read().decode("utf-8", "replace")
    src = json.loads(raw)
    skills = []
    for s in src.get("skills") or []:
        skills.append({
            "id": s.get("id"), "name": s.get("name"), "name_zh": s.get("name_zh"),
            "slug": s.get("slug"), "desc_zh": s.get("description_zh"),
            "desc_en": s.get("description"), "cat_zh": s.get("category_zh"),
            "tags": s.get("tags") or [],
        })
    blob = {"source": "external.zh.registry", "origin": ZH_REGISTRY_URL,
            "version": ZH_REGISTRY_VER, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_count": src.get("total_count"), "skills": skills}
    with io.open(ZH_CACHE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(blob, f, ensure_ascii=False)
    return blob, "fetched"


def load_ext_pool():
    if not os.path.isfile(EXT_POOL):
        return []
    return (json.load(io.open(EXT_POOL, "r", encoding="utf-8", errors="replace"))
            .get("candidates") or [])


def match_text(qt, text):
    eff, _noi = ep.split_hits(qt & ep.tokenize(text))
    return eff


def search_local_caps(keys):
    out = {}
    for lang, ks in keys.items():
        for k in ks:
            qt = ep.tokenize(k)
            if not ep.query_has_signal(qt):
                continue
            qeff = len(ep.effective_query_tokens(qt))
            for name, eff, _noi, _trig, _act in ts.capabilities(qt):
                if not eff:
                    continue
                dens = len(eff) / float(qeff) if qeff else 0
                out.setdefault(name.split("（")[0], []).append((k, len(eff), dens, sorted(eff)))
    return out


def search_local_knowledge(keys):
    out = {}
    for lang, ks in keys.items():
        for k in ks:
            for _s, _kind, rel, title, m in ts.knowledge(ep.tokenize(k), n=3, min_score=0.0):
                out.setdefault(os.path.basename(rel), []).append((k, sorted(m)[:5]))
    return out


def search_zh_registry(keys, skills):
    """中文注册表匹配：**中文键打中文描述**（语言墙在中文源上不存在）。"""
    out = {}
    for lang, ks in keys.items():
        for k in ks:
            qt = ep.tokenize(k)
            if not ep.query_has_signal(qt):
                continue
            for s in skills:
                text = " ".join([s.get("name_zh") or "", s.get("desc_zh") or "",
                                 s.get("cat_zh") or "", " ".join(s.get("tags") or []),
                                 s.get("name") or "", s.get("desc_en") or ""])
                eff = match_text(qt, text)
                if eff:
                    out.setdefault(s.get("id"), {"s": s, "hits": []})["hits"].append(
                        (k, len(eff), sorted(eff)[:6]))
    return out


def search_ext_pool(keys, cands):
    out = {}
    for lang, ks in keys.items():
        for k in ks:
            qt = ep.tokenize(k)
            if not ep.query_has_signal(qt):
                continue
            for c in cands:
                eff = match_text(qt, "%s %s" % (c.get("name") or "", c.get("description") or ""))
                if eff:
                    out.setdefault(c.get("stable_id") or c.get("name"),
                                   {"c": c, "hits": []})["hits"].append((k, len(eff), sorted(eff)[:6]))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# [4]-[5] 候选集 + 交回宿主
# ─────────────────────────────────────────────────────────────────────────────

def rank(hits_map, key="hits"):
    rows = [(max(h[1] for h in v[key]), sum(h[1] for h in v[key]), k, v) for k, v in hits_map.items()]
    rows.sort(key=lambda r: (-r[0], -r[1], str(r[2])))
    return rows


def run_card(tag, zh_skills, ext_cands):
    ctx = runtime_context(CARDS[tag])
    keys = KEYS[tag]
    print("\n" + "=" * 80)
    print("[1] Runtime 输入 · 卡 %s = `%s`" % (tag, CARDS[tag]))
    print("    Goal（%d 字符）：%s" % (len(ctx["goal"]), ctx["goal"][:110] + "…"))
    print("    Current Step：%s" % ctx["current_step"][:100])
    print("    Next Action ：%s" % ctx["next_action"][:100])

    print("\n[2] 查询构造 · 中文键 %d · 英文键 %d（Agent 派生 · 本轮允许）"
          % (len(keys["zh"]), len(keys["en"])))

    caps = search_local_caps(keys)
    know = search_local_knowledge(keys)
    zh = search_zh_registry(keys, zh_skills)
    ext = search_ext_pool(keys, ext_cands)

    print("\n[3] 检索（4 源）")
    print("    S1 本地能力（9 个整包）命中 **%d**" % len(caps))
    print("    S2 本地知识（domains+账本）命中 **%d**" % len(know))
    print("    S3 **外部·中文** skill-hub 注册表（%d 技能）命中 **%d**" % (len(zh_skills), len(zh)))
    print("    S4 **外部·英文** GitHub 池（%d 候选）命中 **%d**" % (len(ext_cands), len(ext)))

    print("\n[4]/[5] 候选集 → 交回宿主（按命中强度排序 · 宿主可直接消费）")
    print("  ── S3 外部·中文（**本链路的主力来源**）──")
    for strength, total, sid, v in rank(zh)[:12]:
        s = v["s"]
        best = max(v["hits"], key=lambda h: h[1])
        print("    ▸ %-28s [%s] 强度 %d（键 `%s` · 命中 %s）"
              % ((s.get("name_zh") or s.get("name"))[:28], s.get("cat_zh") or "-",
                 strength, best[0], "/".join(best[2])))
    print("  ── S4 外部·英文 ──")
    for strength, total, sid, v in rank(ext)[:8]:
        c = v["c"]
        best = max(v["hits"], key=lambda h: h[1])
        print("    ▸ %-28s [%s] 强度 %d（键 `%s` · 命中 %s）"
              % (c.get("name"), (c.get("source") or "")[:18], strength, best[0], "/".join(best[2])))
    print("  ── S1 本地能力 ──")
    for name, recs in sorted(caps.items(), key=lambda kv: -max(r[1] for r in kv[1]))[:6]:
        best = max(recs, key=lambda r: r[1])
        print("    ▸ %-28s 强度 %d（键 `%s` · 命中 %s）" % (name[:28], best[1], best[0], "/".join(best[3])))
    print("  ── S2 本地知识 ──")
    for name, recs in sorted(know.items(), key=lambda kv: -len(kv[1]))[:6]:
        best = max(recs, key=lambda r: len(r[1]))
        print("    ▸ %-28s 键 `%s` · 命中 %s" % (name[:28], best[0], "/".join(best[1])))

    return {"tag": tag, "caps": caps, "know": know, "zh": zh, "ext": ext}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=== 完整链路原型：Runtime → 检索 → Runtime → 宿主 ===")
    blob, how = fetch_zh_registry()
    zh_skills = blob.get("skills") or []
    ext_cands = load_ext_pool()
    print("S3 中文注册表：%s · **%d** 技能 · total_count=%s"
          % (how, len(zh_skills), blob.get("total_count")))
    print("S4 英文池：**%d** 候选" % len(ext_cands))
    print("🔴 链路性质：阶段 [1]–[5] 真跑；**[5] 递送在本会话内成立**（宿主 = Agent 本人）——"
          "⛔ 但**不是** hook 自动注入（那需要 Human 重启）")

    res = {}
    for tag in CARDS:
        res[tag] = run_card(tag, zh_skills, ext_cands)

    print("\n" + "=" * 80)
    print("[6] 宿主消费判定（Agent 判断 · ⚠️ 非独立验证）")
    for tag, r in res.items():
        top = [v["s"].get("name_zh") or v["s"].get("name")
               for _s, _t, _i, v in rank(r["zh"])[:5]]
        print("    %s：中文源 Top5 = %s" % (tag, top))
    print("\n⚠️ 本链路**未**验证：递送**时机** · Agent**采纳率** · 候选**最终适用性**（需真实任务闭环）")
    print("（安全底线仍守：未安装 / 未执行外部内容 / 未提交 / 未注入 / 未改本体·评分·闸门·语料）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
