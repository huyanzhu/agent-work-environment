#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PITFALLS 编号 lint（1）—— 编号唯一 / 连续 / 表格列数一致。

用法：
    python tools/probes/_pitfalls_id_lint.py
    python tools/probes/_pitfalls_id_lint.py --root <clone 目录>

判据（任一不满足 ⇒ FAIL）：
  1. 同一编号出现两次 ⇒ FAIL（引用会指错）
  2. 编号从 起**连续**（允许在末尾追加更大的号；中间跳号 ⇒ FAIL，并报缺失号）
  3. 每个条目行的**列数一致**（5 列：编号 / 现象 / 触发条件 / 处置 / 来源）
  4. 允许存在「未随发布」名单（发布版过滤用）：名单里的编号不要求有正文行

退出码：0 全绿 · 1 有 FAIL · 2 文件缺失
"""
import argparse
import io
import os
import re
import sys

# ⚠️ 校准（第一版写错，造成假红）：
#   ① 原正则要求 ID 后**紧跟** `|` ⇒ 漏掉带严重度标记的行（`|  🔴 |`）—— 只数到 50/98 条。
#   ② 原列数统计**不剥内联代码** ⇒ 处置列里含 `|` 字面（如 `<>:"|?*`）被误判成多列。
ROW_RE = re.compile(r"^\|\s*\**(P\d+)\**")
CODE_SPAN_RE = re.compile(r"`[^`]*`")
# ⚠️ 校准（第三版）：**按行**取「未随发布条目」那一行里的全部 P 编号。
#   前两版用 `(P\d+[^\n]*?)+` / `(P\d+(?:…)*)` ⇒ 只抓到一个编号（懒匹配/分隔符没吞），
#   导致发布版 93 条被判「缺 ///」= 假红。
DROP_LINE_RE = re.compile(r"未随发布条目[^\n]*")


def dropped_ids_of(text):
    out = set()
    for line in DROP_LINE_RE.findall(text):
        out |= set(re.findall(r"P\d+", line))
    return out


def cells_of(line):
    """剥掉内联代码后再按 `|` 切列（行首行尾的竖线不算列）。"""
    s = CODE_SPAN_RE.sub("CODE", line.strip())
    parts = s.split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return parts


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    args = ap.parse_args()
    root = args.root.replace("\\", "/")
    path = os.path.join(root, "task_cards", "memory", "PITFALLS.md")
    if not os.path.isfile(path):
        print("⛔ 找不到:", path)
        return 2

    text = read(path)
    ids, dup, col_bad = [], [], []
    for line in text.split("\n"):
        m = ROW_RE.match(line)
        if not m:
            continue
        pid = m.group(1)
        ids.append(pid)
        if not line.strip().startswith(("| #", "|---")):
            ncells = len(cells_of(line))
            if ncells != 5:
                col_bad.append((pid, ncells))

    seen, dups = set(), []
    for pid in ids:
        if pid in seen and pid not in dups:
            dups.append(pid)
        seen.add(pid)

    # 「未随发布」名单要先算：发布版有意剔除的编号不算缺号
    dropped = dropped_ids_of(text)

    nums = sorted(int(p[1:]) for p in set(ids))
    missing = []
    if nums:
        for n in range(1, max(nums) + 1):
            pid = "P%d" % n
            if n not in nums and pid not in dropped:
                missing.append(pid)

    rows = [
        ("编号唯一", not dups, "重复: %s" % ",".join(dups) if dups else "无重复"),
        ("编号连续", not missing,
         ("缺: %s（若属「未随发布」请写进该名单）" % ",".join(missing[:12])) if missing else "连续"),
        ("表格列数=5", not col_bad,
         ("列数不符: %s" % ", ".join("%s(%d列)" % c for c in col_bad[:6])) if col_bad else "全部 5 列"),
    ]
    fails = sum(0 if ok else 1 for _, ok, _ in rows)
    print("PITFALLS 编号 lint · %s" % path)
    for name, ok, detail in rows:
        print("  %-12s %-4s %s" % (name, "OK" if ok else "FAIL", detail))
    print("  条目 %d · 唯一编号 %d · 未随发布名单 %d" % (len(ids), len(set(ids)), len(dropped)))
    print("合计 %d · OK %d · FAIL %d" % (len(rows), len(rows) - fails, fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
