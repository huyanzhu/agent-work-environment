#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_shadow_discovery.py — 阶段三 3.2 **A/B 影子发现通道**（只读 · 实验态）

用途（设计见 `p0/STAGE3-DISCOVERY-AB-DESIGN.md` §4/§5）：
  给定**同一次工作上下文**组装出的两组查询 —— A 组（现有工作上下文）与
  B 组（**完全相同** + **推理文本**）—— **一次进程内**分别跑发现，输出**候选标识与分数**。

🔴 **纪律（逐条硬约束）**：
  · **只读**：不写任何文件 · 不写日志 · 不建缓存
  · **不回显输入原文**：输出只有候选 ID / 分数 / 命中数 / 排名（**无原文、无标题**）
  · **不调远程**：零网络
  · **只复用** `tools/experience_push.py` 的 tokenize / 打分 / 闸门（**不许出现第二套规则**）
  · **A/B 只差推理文本**：本脚本**不组装**查询（组装在调用方），只保证**同一套语料与规则**

stdin : {"queries": {"A": "<文本>", "B": "<文本>"}, "topN": 4, "minScore": 0.0}
stdout: {"A": {"candidates": [...], "elapsedMs": N, "gate": "..."}, "B": {...},
         "shared": {"corpusFiles": N, "loadMs": N, "topN": N}}

⚠️ 实验态：位于 `scratch/`（与其他实验工具一致 · 不入库）；**验证通过后再固化到 `tools/`**。
"""
import io
import json
import os
import sys
import time

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
sys.path.insert(0, TOOLS)
sys.path.insert(0, PROBES)

import experience_push as ep  # noqa: E402  （唯一一套打分 / 闸门规则）

#: 与 `tools/task_start.py` 同源的阈值（**不得另立一套**）
KNOW_MIN_SCORE = 8.0
KNOW_BUDGET = 2


def _gate_reason(query_tokens, res):
    """闸门未过的**具体原因**（🔴 必须可区分 —— 否则无法判断"无候选"是数据问题还是密度问题）。"""
    if not ep.query_has_signal(query_tokens):
        return "no-signal"
    if len(res.effective) < ep.MIN_EFFECTIVE_HITS:
        return "min-hits"
    qeff = len(ep.effective_query_tokens(query_tokens))
    if qeff > 0 and (len(res.effective) / float(qeff)) < ep.MIN_HIT_DENSITY:
        return "density"
    if not res.high_field_effective:
        return "no-high-field"
    return "passed"


def _discover(corpus, ledger, query_tokens, top_n, min_score):
    """在**已加载**的语料上跑一次发现 ⇒ 候选（**只含标识与派生量**）。"""
    results = []
    rejects = []
    for disp, raw in corpus:
        res = ep.score_file(query_tokens, raw)
        if res.score <= 0:
            continue
        if ep.passes_gate(query_tokens, res):
            results.append({
                "id": disp,
                "score": round(res.score, 3),
                "kind": "file",
                "hits": len(res.effective),
            })
        else:
            rejects.append((res.score, disp, _gate_reason(query_tokens, res), len(res.effective)))
    for disp, header, weight, text in ledger:
        res = ep.score_ledger_chunk(query_tokens, header, text)
        if res.score <= 0:
            continue
        if ep.passes_gate(query_tokens, res):
            results.append({
                "id": disp,
                "score": round(weight * res.score, 3),
                "kind": "proven" if weight >= ep.PROVEN_LEDGER_WEIGHT else "ledger",
                "hits": len(res.effective),
            })
        else:
            rejects.append((weight * res.score, disp, _gate_reason(query_tokens, res), len(res.effective)))
    results.sort(key=lambda r: -r["score"])
    kept = [r for r in results if r["score"] >= min_score][:top_n]
    for i, r in enumerate(kept):
        r["rank"] = i + 1
    # 🔴 被闸门挡住的**最高分**候选及其**原因**（诊断用 · 只落标识与派生量 · 无原文）
    rejects.sort(key=lambda x: -x[0])
    rej = [{"id": d, "score": round(s, 3), "reason": r, "hits": h} for s, d, r, h in rejects[:2]]
    return kept, len(results), rej


def main():
    started = time.time()
    # 🔴 输入编解码必须**显式**处理：调用方可能带 UTF-8 BOM（读数：PowerShell 管道会加 BOM），
    #    也可能在 Windows 上用 GBK 传参 ⇒ 因此**只走 stdin**（不经命令行参数）+ `utf-8-sig` 解码。
    raw_in = sys.stdin.buffer.read()
    try:
        text_in = raw_in.decode("utf-8-sig")
    except UnicodeDecodeError:
        text_in = raw_in.decode("utf-8", "replace")
    try:
        payload = json.loads(text_in or "{}")
    except Exception as exc:  # 输入非法 ⇒ 明确失败，**不猜**
        sys.stdout.write(json.dumps({"error": "bad-input", "detail": str(exc)[:80]}) + "\n")
        return 2

    queries = payload.get("queries") or {}
    if not isinstance(queries, dict) or len(queries) == 0:
        sys.stdout.write(json.dumps({"error": "no-queries"}) + "\n")
        return 2
    top_n = int(payload.get("topN", KNOW_BUDGET))
    min_score = float(payload.get("minScore", KNOW_MIN_SCORE))

    # ── 语料**只加载一次**（A/B 共享 ⇒ 消除"语料差异"这一混杂因素）──
    load_t0 = time.time()
    corpus = []
    for kind, path in ep.collect_files():
        try:
            with io.open(path, "r", encoding="utf-8", errors="replace") as f:
                corpus.append((ep.disp_path(path), f.read()))
        except OSError:
            continue
    ledger = []
    for path, weight, header, text in ep.collect_ledger_chunks():
        ledger.append((ep.disp_path(path), header, weight, text))
    load_ms = int((time.time() - load_t0) * 1000)

    out = {}
    for arm in ("A", "B"):
        text = queries.get(arm)
        if not isinstance(text, str):
            out[arm] = {"gate": "no-query", "candidates": []}
            continue
        t0 = time.time()
        tokens = ep.tokenize(text)
        if not ep.query_has_signal(tokens):
            out[arm] = {"gate": "no-signal", "candidates": [], "elapsedMs": int((time.time() - t0) * 1000)}
            continue
        kept, total, rej = _discover(corpus, ledger, tokens, top_n, min_score)
        out[arm] = {
            "gate": "passed" if kept else "filtered-all",
            "candidates": kept,
            "rawHits": total,
            "queryTokens": len(tokens),
            "queryEffective": len(ep.effective_query_tokens(tokens)),
            "topRejects": rej,
            "elapsedMs": int((time.time() - t0) * 1000),
        }

    out["shared"] = {
        "corpusFiles": len(corpus),
        "ledgerChunks": len(ledger),
        "loadMs": load_ms,
        "topN": top_n,
        "minScore": min_score,
        "totalMs": int((time.time() - started) * 1000),
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
