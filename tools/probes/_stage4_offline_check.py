#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""_stage4_offline_check.py — 阶段 4 · **重启前的离线贯通预演**（只读 · 实验态）

作用
    在 DSH 重启（`runtime/aios-activation.ts` 改动生效）**之前**，把第①＋②段
    （Runtime 构造最小请求 → Retrieval 返回候选集）在同进程里跑通，供 判读。

🔴 与正式实现的关系（**避免两套判据漂移**）
    · **正式映射**在 `runtime/aios-activation.ts` 的 `buildRetrievalRequest()` —— TS 侧。
    · 本脚本是**离线预演**：只验证"检索侧能否消费这份最小请求、返回什么"。
      ⛔ 它不是第二条生产路径；一旦 TS 侧接通并验证，本脚本只作读数资产。
    · ⛔ 不新增检索判据 —— 打分 / 闸门 / 来源枚举全部复用 Retrieval 侧既有实现。

用法
    python scratch/_stage4_offline_check.py <card-rel> [activity-path ...]
"""
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

import _runtime_field_producer as fp          # noqa: E402  （唯一字段产出）
import _retrieval_request_probe as rrp        # noqa: E402  （唯一检索入口）

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 映射规则（**与 TS 侧 `buildRetrievalRequest()` 必须一致**）──────────────────
TOPIC_PHRASES = 3
TARGET_REFS = 4
ROLE_MAP = {
    "设计": "guidance",
    "开发工具": "guidance",
    "集成": "integration",
    "测试": "verification",
    "审核": "verification",
}


def uniq(seq):
    out, seen = [], set()
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def build_request(field, activity_paths, history_coverage="partial", request_id="rr-stage4-offline"):
    """RuntimeField + 活动证据 ⇒ **最小** `retrieval-request/v1`（⛔ 不拼工作上下文 · 不传意图原文）。"""
    obj = field.get("object") or ""
    phrases = [str(p) for p in (field.get("phrases") or [])]
    topic = " ".join([obj] + phrases[:TOPIC_PHRASES]).strip()
    refs = uniq([str(p).strip() for p in activity_paths if str(p).strip()])[-TARGET_REFS:]
    roles = uniq([ROLE_MAP.get(str(c)) for c in (field.get("categories") or [])])

    work = {}
    work["work_topic"] = {"state": "provided", "value": topic} if topic else {"state": "unknown"}
    work["target_refs"] = ({"state": "provided", "value": refs} if refs else {"state": "unknown"})
    work["history_coverage"] = {
        "state": "provided",
        "value": "incomplete" if history_coverage == "partial" else "complete",
    }
    req = {
        "schema": "retrieval-request/v1",
        "request_id": request_id,
        "need": {"state": "unknown", "origin": "runtime"},
        "work": work,
        "sources": {"mode": "all-discoverable", "ids": []},
        "budget": {"max_candidates": 8, "max_per_source": 3},
    }
    if roles:
        req["roles_needed"] = roles
    return req


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    card = sys.argv[1]
    activity = sys.argv[2:]

    field = fp.produce_from_card(card)
    req = build_request(field, activity)
    out = rrp.run({"request": req}, 8)

    print("=== ① 焦点卡 → 焦点对象（已验证的产出机制 · 本轮未改）===")
    print("card      : %s" % card)
    print("object    : %s | confidence=%s | source=%s | degraded=%s"
          % (field.get("object"), field.get("confidence"), field.get("source"), field.get("degraded")))
    print("phrases   : %s" % " · ".join(field.get("phrases") or []))
    print("categories: %s" % "/".join(field.get("categories") or []))
    if field.get("reasons"):
        print("reasons   : %s" % ";".join(field.get("reasons") or []))

    print()
    print("=== ① 最小请求（Runtime 决定向 Retrieval 提供什么）===")
    print(json.dumps(req, ensure_ascii=False, indent=2))

    print()
    print("=== ② Retrieval 返回（candidate-set/v1 · 只列标识/来源/角色）===")
    cands = out.get("candidates") or []
    print("candidates: %d" % len(cands))
    print("diversity : %s" % json.dumps(out.get("diversity") or {}, ensure_ascii=False))
    print("budget    : %s" % json.dumps(out.get("budget_applied") or {}, ensure_ascii=False))
    print("gaps      : %s" % json.dumps(out.get("gaps") or [], ensure_ascii=False))
    status = {}
    for s in (out.get("source_status") or []):
        status[s.get("status")] = status.get(s.get("status"), 0) + 1
    print("source    : %s" % json.dumps(status, ensure_ascii=False))
    for i, c in enumerate(cands[:8], 1):
        src = (c.get("source") or {}).get("id")
        print("  %d. %-52s [%s/%s] channels=%s"
              % (i, str(c.get("id"))[:52], src, c.get("role"),
                 ",".join(c.get("hit_channels") or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
