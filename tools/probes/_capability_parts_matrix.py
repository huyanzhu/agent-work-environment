#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""能力片级矩阵 · **领域视角**（域合并后重写 · 只读）

旧版 = 3 class × 8 domain 的 24 格（D-056 片级化）。
裁定：**领域是唯一分类轴**（17 能力 → 8 域能力，片不含 class）⇒
本脚本改为「域 → 片」的两级视图，给出：
  · 每域片数 / 抽象自哪些旧能力（`merge_of`）
  · 域内融合候选（同域内 one_line 词面相似 ≥ 阈值）
  · 覆盖缺口（8 域里哪些没有域能力文件）

⚠️ 只读：不写盘、不改 capabilities。
用法：
  python tools/probes/_capability_parts_matrix.py
  python tools/probes/_capability_parts_matrix.py --json
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
from itertools import combinations

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FUSION_THRESHOLD = 0.30
DOMAINS_8 = ["前端", "后端", "数据", "文档", "产品", "环境·运维", "求职·职业", "AI-OS 自身"]


def _frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""


def _parts(fm):
    """块式 list-of-map ⇒ [dict]（与 `_capability_field_lint.parts_of` 同形态，简化版）。"""
    m = re.search(r"^parts[ \t]*:(.*)$", fm, re.M)
    if not m:
        return []
    out, cur = [], None
    for line in fm[m.end():].split("\n"):
        if re.match(r"^[A-Za-z_][\w-]*\s*:", line):
            break
        s = line.strip()
        if s.startswith("- "):
            cur = {}
            out.append(cur)
            s = s[2:].strip()
        if cur is not None and ":" in s:
            k, _, v = s.partition(":")
            cur[k.strip()] = v.strip().strip("'\"")
    return out


def _bigrams(t):
    t = re.sub(r"[^\w\u4e00-\u9fff]", "", t or "")
    return {t[i:i + 2] for i in range(len(t) - 1)} or ({t} if t else set())


def _sim(a, b):
    ga, gb = _bigrams(a), _bigrams(b)
    return len(ga & gb) / max(1, len(ga | gb))


def collect(root):
    caps = []
    for p in sorted(glob.glob(os.path.join(root, "capabilities", "domain-*.md"))):
        text = io.open(p, encoding="utf-8").read()
        fm = _frontmatter(text)
        name = os.path.basename(p)[:-3]
        dom = ""
        merge_of = []
        in_merge = False
        for line in fm.split("\n"):
            if line.startswith("domain:"):
                dom = line.split(":", 1)[1].strip()
            if line.startswith("merge_of:"):
                in_merge = True
                continue
            if in_merge:
                if line.startswith("  - "):
                    merge_of.append(line.strip()[2:].strip())
                elif line.strip():
                    in_merge = False
        caps.append({"capability": name, "domain": dom, "merge_of": merge_of,
                     "parts": _parts(fm)})
    return caps


def main(argv):
    as_json = "--json" in argv
    root = ROOT
    for i, a in enumerate(argv):
        if a == "--root" and i + 1 < len(argv):
            root = argv[i + 1]
    caps = collect(root)
    by_dom = {}
    for c in caps:
        by_dom.setdefault(c["domain"], []).append(c)

    rows = []
    for dom in DOMAINS_8:
        cs = by_dom.get(dom, [])
        parts = [pp for c in cs for pp in c["parts"]]
        rows.append({
            "domain": dom,
            "capabilities": [c["capability"] for c in cs],
            "merge_of": sorted({m for c in cs for m in c["merge_of"]}),
            "part_count": len(parts),
            "parts": [{"id": pp.get("id", ""), "label": pp.get("label", ""),
                       "one_line": pp.get("one_line", "")} for pp in parts],
        })

    fusion = []
    for r in rows:
        ps = r["parts"]
        for a, b in combinations(ps, 2):
            s = _sim(a["one_line"], b["one_line"])
            if s >= FUSION_THRESHOLD:
                fusion.append({"domain": r["domain"], "a": a["id"], "b": b["id"],
                               "sim": round(s, 3)})
    empty = [d for d in DOMAINS_8 if d not in by_dom]
    total = sum(r["part_count"] for r in rows)

    if as_json:
        print(json.dumps({
            "probe": "_capability_parts_matrix",
            "read_only": True,
            "view": "domain",
            "domains": DOMAINS_8,
            "files": len(caps),
            "parts_total": total,
            "rows": rows,
            "empty_domains": empty,
            "fusion_threshold": FUSION_THRESHOLD,
            "fusion_candidates": fusion,
        }, ensure_ascii=False, indent=2))
        return 0

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    print("能力片级矩阵 · 领域视角（只读 · 2026-11-02 域合并后）· %d 个域能力 · %d 个片"
          % (len(caps), total))
    print()
    print("%-12s %-22s %4s  %s" % ("领域", "域能力", "片数", "抽象自（旧能力）"))
    for r in rows:
        print("%-12s %-22s %4d  %s" % (r["domain"], "、".join(r["capabilities"]) or "❌ 缺",
                                       r["part_count"], "、".join(r["merge_of"]) or "-"))
    print()
    print("一、覆盖：%d/%d 个域有域能力%s"
          % (len(DOMAINS_8) - len(empty), len(DOMAINS_8),
             "（缺：" + "、".join(empty) + "）" if empty else ""))
    print("二、域内融合候选（one_line 词面相似 ≥%.2f）：%d 对" % (FUSION_THRESHOLD, len(fusion)))
    for f in fusion[:10]:
        print("   [%s] %.2f  %s ↔ %s" % (f["domain"], f["sim"], f["a"], f["b"]))
    if not fusion:
        print("   无（域内片之间没有明显重复 ⇒ 融合发生在**域之间**，不在域内）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
