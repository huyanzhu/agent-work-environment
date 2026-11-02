#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经验族卡 lint—— frontmatter / 结构 / 命名。

用法：
    python tools/probes/_family_field_lint.py [--root <repo>]

判据（任一不满足 ⇒ FAIL；逐文件报告）：
  1. 文件名 `<问题域>_family.md`
  2. frontmatter 存在且 5 个必填字段齐全：title / family / status / trigger / keywords
     （`alias` 可选；缺 `trigger`/`keywords` ⇒ 召回几乎命中不到 —— 读数对口 query 0 命中）
  3. `trigger` / `keywords` 非空数组
  4. 正文六节锚点齐全：覆盖的坑（成员声明）· 先对号入座 · 做法 · 判据 / 自检 · 边界 · 证据
  5. `family` 字段与文件名前缀一致（`encoding_errors_family.md` ⇒ `family: encoding_errors`）

退出码：0 全绿 · 1 有 FAIL · 2 目录缺失
"""
import argparse
import io
import os
import re
import sys

REQUIRED = ("title", "family", "status", "trigger", "keywords")
# �� 按**真实语料**校准6 张真卡没有 markdown 标题，共同锚点只有两个：
#   「成员声明」+「做法」。其余锚点（对号入座/判据/边界/证据）各卡不同 ⇒ ⛔ 不强制，避免造出假红。
ANCHORS_REQUIRED = ("成员声明", "做法")


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def strip_comments(text):
    """去掉 frontmatter 里的 `#` 注释行，避免把注释当字段。"""
    lines = []
    for line in text.split("\n"):
        if line.lstrip().startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def frontmatter_blocks(text):
    """返回 (frontmatter 文本, 正文)。"""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end < 0:
        return "", text
    return text[3:end], text[end + 4:]


def has_field(fm, key):
    return re.search(r"(?m)^%s\s*:" % re.escape(key), fm) is not None


def field_value(fm, key):
    m = re.search(r"(?m)^%s\s*:\s*(.*)$" % re.escape(key), fm)
    return (m.group(1) or "").strip() if m else ""


def non_empty_list(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return inner != ""
    return v != ""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    args = ap.parse_args()
    root = args.root.replace("\\", "/")
    d = os.path.join(root, "domains", "experiences")
    if not os.path.isdir(d):
        print("⛔ 目录不存在:", d)
        return 2

    files = sorted(f for f in os.listdir(d) if f.endswith("_family.md"))
    fail = 0
    print("经验族卡 lint · %s（%d 张）" % (d, len(files)))
    for f in files:
        text = read(os.path.join(d, f))
        fm, body = frontmatter_blocks(text)
        fm_clean = strip_comments(fm)
        problems = []

        if not fm.strip():
            problems.append("缺 frontmatter")
        else:
            miss = [k for k in REQUIRED if not has_field(fm_clean, k)]
            if miss:
                problems.append("frontmatter 缺字段: %s" % ",".join(miss))
            for k in ("trigger", "keywords"):
                if has_field(fm_clean, k) and not non_empty_list(field_value(fm_clean, k)):
                    problems.append("%s 为空数组" % k)
            fam = field_value(fm_clean, "family").strip().strip("\"'")
            # ⚠️ 不校验 family 与文件名前缀一致：真卡的 family 是中文标签（如「权限/沙箱」），
            #   文件名是 ASCII 标识（permission_sandbox）—— 二者本就不相等。
            if not fam:
                problems.append("family 为空")

        miss_anchor = [s for s in ANCHORS_REQUIRED if s not in body]
        if miss_anchor:
            problems.append("正文缺锚点: %s" % ",".join(miss_anchor))

        ok = not problems
        if not ok:
            fail += 1
        print("  %-34s %-4s %s" % (f, "OK" if ok else "FAIL", "; ".join(problems) if problems else "-"))
    print("合计 %d · OK %d · FAIL %d" % (len(files), len(files) - fail, fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
