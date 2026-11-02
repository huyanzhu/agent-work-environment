#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_e2e_field_driven_pipeline.py — 端到端链路 **v2：字段产出器驱动**（只读 · 内存态）

主线（HANDOFF §四十三 漂移判据）
    *"Runtime 通过 Agent 暴露的信息，更可靠地了解当前正在发生什么，并在正确时机提供适用能力"*

与 v1（`_e2e_runtime_retrieval_pipeline.py`）的差别
    v1：`[2] 查询构造` 用**手写的 Agent 派生键**（KEYS 常量）
    v2：`[2] 查询构造` 改用 **`_runtime_field_producer`**（卡 + 推理交叉 ⇒ `RuntimeField`）
        ⇒ 这才是"卡辅助推理文本"真正接进链路；退化时 **⛔ 不交检索**

链路
    [1] Runtime 输入   卡 `State` / `Next Action` / `Current Step` / `Goal`
    [2] 字段产出       **卡定对象（精度）+ 推理近窗口交叉（验证）**
    [3] 检索           字段可用时：本地能力 + 本地知识 + **外部·中文 5005** + 外部·英文 47
    [4] 候选集         按来源分组 · 带命中证据
    [5] 交回宿主       打印（本会话内宿主 = Agent 本人）
    [6] 宿主判定       由 Agent 判（⚠️ 非独立验证）

用法：<emit-json> | python scratch/_e2e_field_driven_pipeline.py --card=<rel> [--allow-reason-only]
"""
import io
import json
import os
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

import _runtime_field_producer as fp
import _e2e_runtime_retrieval_pipeline as e2e
import _zh_skill_discrimination_probe as dp
import _runtime_input_form_probe as rif
import experience_push as ep


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    card = rif.CARDS["G2"]
    allow_reason_only = "--allow-reason-only" in sys.argv
    for a in sys.argv[1:]:
        if a.startswith("--card="):
            card = a.split("=", 1)[1]

    blob = json.loads(sys.stdin.read())
    ev = blob.get("events") or []
    rs = [e.get("text") or "" for e in ev if e.get("kind") == "reasoning"]
    first_user = next((e.get("text") or "" for e in ev if e.get("kind") == "user"), "")
    zh_skills = (e2e.fetch_zh_registry()[0] or {}).get("skills") or []
    ext_cands = e2e.load_ext_pool()

    print("=== 端到端链路 v2（**字段产出器驱动**）===")
    print("会话 `%s` · reasoning **%d** 块 · 首条用户消息：`%s`"
          % (blob.get("session"), len(rs), first_user[:70].replace("\n", " ")))
    print("卡：`%s` ｜ 池：中文 **%d** + 英文 **%d**" % (card, len(zh_skills), len(ext_cands)))

    # [1]+[2]
    field = fp.produce_from_card(card, reason_texts=rs, allow_reason_only=allow_reason_only)
    print("\n[1] Runtime 输入：State=`%s`" % field["evidence"]["card_state"][:34])
    print("    Next Action：`%s`" % field["evidence"]["next_action_snippet"])
    print("[2] 字段产出：object=%s · confidence=%s · source=%s · degraded=%s"
          % (field["object"], field["confidence"], field["source"], field["degraded"]))
    print("    推理近窗口对象计数：%s" % field["evidence"]["reason_object_counts"])

    if field["degraded"]:
        print("\n[3] ⛔ **不交检索**（reasons=%s）" % field["reasons"])
        print("    ⇒ 按设计：⛔ 不用 `Goal` 兜底、⛔ 不按频率取推理对象（避免虚假覆盖）")
        print("\n（只读 · 内存态 · ⛔ 未落推理原文 · 未改机制/闸门/语料/本体）")
        return 0

    # [3] ⚠️ 必须复用**已验证的判别规则**（名称硬门槛 + 类别对齐）——
    #     v2 首版误用了原始 `match_text` ⇒ 外部中文命中 **2571/5005（51%）**，被 `tanstack *` 霸榜
    keys = {"field": field["phrases"]}
    caps = e2e.search_local_caps(keys)
    know = e2e.search_local_knowledge(keys)
    qts = [ep.tokenize(k) for k in field["phrases"] if ep.query_has_signal(ep.tokenize(k))]
    zh_hard = dp.run_hard(qts, zh_skills, cats=field["categories"] or None)
    zh_raw = e2e.search_zh_registry(keys, zh_skills)
    ext = e2e.search_ext_pool(keys, ext_cands)
    print("\n[3] 检索：本地能力 **%d** · 本地知识 **%d** · 外部中文 **%d**（名称硬门槛）/ %d（原始匹配）· 外部英文 **%d**"
          % (len(caps), len(know), len(zh_hard), len(zh_raw), len(ext)))

    # [4]/[5]
    print("[4]/[5] 候选集 → 交回宿主（phrases=%s ｜ categories=%s）"
          % (" · ".join(field["phrases"]), "/".join(field["categories"])))
    print("  ── 外部·中文（**名称硬门槛 + 类别对齐**）Top-8 ──")
    for sc, n, t, d, s in zh_hard[:8]:
        print("    ▸ %-26s [%s] 名%d/标%d/述%d"
              % ((s.get("name_zh") or s.get("name"))[:26], (s.get("cat_zh") or "-")[:6], n, t, d))
    if not zh_hard:
        print("    （无命中）")
    print("  ── 外部·英文 Top-5 ──")
    for strength, total, sid, v in e2e.rank(ext)[:5]:
        c = v["c"]
        best = max(v["hits"], key=lambda h: h[1])
        print("    ▸ %-26s [%s] 强度 %d（键 `%s` · 命中 %s）"
              % (c.get("name"), (c.get("source") or "")[:16], strength, best[0], "/".join(best[2])))
    if not ext:
        print("    （无命中）")
    print("  ── 本地能力 ──")
    for name, recs in sorted(caps.items(), key=lambda kv: -max(r[1] for r in kv[1]))[:5]:
        best = max(recs, key=lambda r: r[1])
        print("    ▸ %-26s 强度 %d（键 `%s` 命中 %s）" % (name[:26], best[1], best[0], "/".join(best[3])))
    if not caps:
        print("    （无命中）")

    print("\n[6] 宿主判定 ⇒ 见对话（⚠️ 由 Agent 判 · 非独立验证）")
    print("（只读 · 内存态 · ⛔ 未落推理原文 · 未改机制/闸门/语料/本体）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
