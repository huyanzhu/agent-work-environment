# -*- coding: utf-8 -*-
"""部署闸门：宿主实际装载的 POLICY vs 源码 POLICY（runtime 改动必须重启才生效）。

用法：python tools/probes/_live_policy_check.py [--root <clone>]
退出码：0 = 一致 / 无可查（SKIP）；1 = 不一致（提示重启）。
"""
import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    return ap.parse_args()


def source_policy(root):
    p = os.path.join(root, "runtime", "diagnostics", "probe.ts")
    if not os.path.isfile(p):
        return None
    m = re.search(r"export const POLICY = '([^']*)'", io.open(p, encoding="utf-8", errors="replace").read())
    return m.group(1) if m else None


def live_policy(root):
    p = os.path.join(root, ".aios", "_aios-activation.probe.log")
    if not os.path.isfile(p):
        return None
    last = None
    for line in io.open(p, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line.split("] ", 1)[1])
        except Exception:
            continue
        if r.get("ev") == "apply" and r.get("policy"):
            last = r["policy"]
    return last


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    args = parse_args()
    src, live = source_policy(args.root), live_policy(args.root)
    print("源码 POLICY:", src or "(未找到)")
    print("宿主 POLICY:", live or "(无 apply 记录)")
    if not src or not live:
        print("SKIP：缺源码 POLICY 或宿主 apply 记录")
        return 0
    if src == live:
        print("OK：宿主装载与源码一致")
        return 0
    print("❌ 不一致：源码尾=%s · 宿主尾=%s" % (src.rsplit("+", 1)[-1], live.rsplit("+", 1)[-1]))
    print("   ⇒ 改过 runtime 但宿主未重载：重启宿主后重跑本检查。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
