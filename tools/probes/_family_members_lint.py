#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""族卡成员声明 lint—— 声明的坑号必须在 PITFALLS 里真实存在。

背景：发布版 `PITFALLS.md` 是**过滤版**（剔除了 5 条本机事实），
而 3 张族卡的成员声明仍写着 / / / ⇒ 读者按声明查不到 ⇒ 可核性受损。

判据：
  1. 每张族卡必须有「覆盖的坑（成员声明）」节且列出 ≥1 个 P 编号
  2. 声明的编号必须满足其一：
       a. 在 `PITFALLS.md` 的正文行里存在，或
       b. 出现在 `PITFALLS.md` 的「未随发布」名单里（发布版过滤说明）
     ⛔ 两者都不是 ⇒ FAIL（悬空声明）

用法：python tools/probes/_family_members_lint.py [--root <repo>]
退出码：0 全绿 · 1 有 FAIL · 2 缺文件
"""
import argparse
import io
import os
import re
import sys

DECL_RE = re.compile(r"覆盖的坑（成员声明）\**\s*[：:]\s*(.+)")
PIT_ROW = re.compile(r"^\|\s*\**(P\d+)\**", re.M)
DROP_RE = re.compile(r"未随发布条目[^\n]*")


def dropped_ids_of(text):
    """按行取「未随发布条目」那一行里的全部 P 编号。

    ⚠️ ：早期用 `(P\\d+(?:\\s*[·,、]\\s*P\\d+)*)` 只抓到第一个编号 ⇒ 发布版里
    // 被判悬空 = 假红。行级提取最稳。
    """
    out = set()
    for line in DROP_RE.findall(text):
        out |= set(re.findall(r"P\d+", line))
    return out


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

    pit = os.path.join(root, "task_cards", "memory", "PITFALLS.md")
    d = os.path.join(root, "domains", "experiences")
    if not os.path.isfile(pit) or not os.path.isdir(d):
        print("⛔ 缺文件:", pit if not os.path.isfile(pit) else d)
        return 2

    ptxt = read(pit)
    have = set(PIT_ROW.findall(ptxt))
    dropped = dropped_ids_of(ptxt)
    known = have | dropped

    files = sorted(f for f in os.listdir(d) if f.endswith("_family.md"))
    fail = 0
    print("族卡成员声明 lint · %s（PITFALLS 正文 %d · 未随发布 %d）" % (d, len(have), len(dropped)))
    for f in files:
        text = read(os.path.join(d, f))
        m = DECL_RE.search(text)
        if not m:
            print("  %-34s FAIL 缺「覆盖的坑（成员声明）」行" % f)
            fail += 1
            continue
        ids = re.findall(r"P\d+", m.group(1))
        if not ids:
            print("  %-34s FAIL 成员声明里没有 P 编号" % f)
            fail += 1
            continue
        missing = [p for p in ids if p not in known]
        ok = not missing
        if not ok:
            fail += 1
        print("  %-34s %-4s 声明 %d 个%s" % (
            f, "OK" if ok else "FAIL",
            len(ids), "" if ok else " · 悬空: " + ",".join(missing)))
    print("合计 %d · OK %d · FAIL %d" % (len(files), len(files) - fail, fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
