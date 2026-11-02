# -*- coding: utf-8 -*-
"""/ 回归闸门：静默 catch 的**可观测化**不许回退（模块化后扫全部 runtime 模块）。

判据（任一不满足 ⇒ FAIL）：
  1. `noteCatchFail` 必须存在（任一模块）且总调用数 ≥ 10
  2. 「真空 catch」（体内只有注释/空）**全 runtime 合计** ≤ 基线 5
  3. 探针事件名 `catch-fail` 必须存在（否则加了调用但没落探针 = 假绿）

背景： 三批把 18 处静默 catch 接上 `catch-fail` 探针； 模块化把这些声明搬进了
`diagnostics/ session/ …` 子模块 ⇒ 判据必须扫全量，⛔ 只看主文件会假红/假绿。
"""
import argparse
import io
import os
import re
import sys

BASELINE_EMPTY = 5
MIN_CALLS = 10

EMPTY_CATCH = re.compile(r"^\s*\} catch \{\s*(?:/\*.*\*/)?\s*$")
CALL = re.compile(r"noteCatchFail\(")


SUBDIRS = ("diagnostics", "session", "retrieval", "activation", "delivery", "maintenance")


def runtime_files(root):
    """只扫**本体主文件 + 拆出的模块子目录**。

    ⛔ 不扫 `runtime/` 根下的 `aios-observe.ts` / `aios-signals.ts`（旧插件，不属 范围；
    纳入会把它们的 12 处空 catch 也算进来 ⇒ 判据假红）。
    """
    base = os.path.join(root, "runtime")
    out = []
    main = os.path.join(base, "aios-activation.ts")
    if os.path.isfile(main):
        out.append(main)
    for sd in SUBDIRS:
        d = os.path.join(base, sd)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".ts"):
                out.append(os.path.join(d, f))
    return out


def count_empty(text):
    n = 0
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not EMPTY_CATCH.match(line):
            continue
        j = i + 1
        while j < len(lines) and (lines[j].strip() == "" or lines[j].strip().startswith(("/*", "//", "*"))):
            j += 1
        if j < len(lines) and lines[j].strip().startswith("}"):
            n += 1
    return n


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    args = ap.parse_args()
    root = args.root.replace("\\", "/")
    files = runtime_files(root)
    if not files:
        print("无法定位 runtime 模块:", root)
        return 2

    has_helper = False
    calls = 0
    has_event = False
    empty = 0
    unbound = []
    for p in files:
        text = io.open(p, encoding="utf-8").read()
        defines = "function noteCatchFail" in text
        imports = re.search(r"(?m)^import (?:type )?\{[^}]*\bnoteCatchFail\b[^}]*\}", text) is not None
        if defines:
            has_helper = True
        n_calls = len(CALL.findall(text))
        calls += n_calls
        # 🔴 关键：**调用必须被绑定**（本文件定义 或 import 进来）
        #    —— 期间真实踩坑：probe.ts 调 `noteCatchFail` 却没绑定，
        #    只数调用次数会判「全绿」，而它在 `finally` 里一触发就是 ReferenceError。
        if n_calls > 0 and not defines and not imports:
            unbound.append(os.path.relpath(p, root))
        if "catch-fail" in text:
            has_event = True
        empty += count_empty(text)

    rows = [
        ("noteCatchFail 存在", has_helper, "定义存在" if has_helper else "缺 helper"),
        ("接线数 >= %d" % MIN_CALLS, calls >= MIN_CALLS, "实际 %d 处" % calls),
        ("调用均已绑定", not unbound, "全部已绑定" if not unbound else "未绑定: " + ", ".join(unbound)),
        ("探针事件名", has_event, "catch-fail 存在" if has_event else "无 catch-fail（假绿）"),
        ("真空 catch <= 基线 %d" % BASELINE_EMPTY, empty <= BASELINE_EMPTY, "实际 %d 处" % empty),
    ]
    fails = sum(0 if ok else 1 for _, ok, _ in rows)
    print("静默 catch 可观测化 lint · runtime/*.ts（%d 个文件）" % len(files))
    for name, ok, detail in rows:
        print("  %-22s %-4s %s" % (name, "OK" if ok else "FAIL", detail))
    print("合计 %d · OK %d · FAIL %d" % (len(rows), len(rows) - fails, fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
