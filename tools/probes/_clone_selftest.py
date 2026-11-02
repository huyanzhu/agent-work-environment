# -*- coding: utf-8 -*-
"""克隆可用性闸门：从 HEAD 建干净 worktree，跑 4 条自检，报告是否可用。

用法：
    python tools/probes/_clone_selftest.py            # 建临时 worktree 跑完再删
    python tools/probes/_clone_selftest.py --keep     # 保留 worktree 便于排查

判据（任一不满足 ⇒ 退出码 1）：
  ① `task_card.py states` 退出 0
  ② `_capability_field_lint.py` 全 OK / 0 FAIL
  ③ `unittest discover tools/tests` 全绿
  ④ `node runtime/tests/activation.test.mjs` 失败项 ≤ 1（唯一允许 S37 已知红）
"""
import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KNOWN_RED = ("S37",)


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    # 🔴 本目录**不是独立 git 仓**时，`git worktree` 会向上找到父仓
    #   ⇒ 这道闸门会「验的是私有仓 HEAD」，却打印「✅ 克隆可用」= **假绿**（比失败更危险）。
    #   ⇒ fail-closed：toplevel 必须等于本脚本所在根，否则明确拒绝。
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    top = (r.stdout or "").strip().replace("\\", "/")
    here = ROOT.replace("\\", "/")
    if r.returncode != 0 or top.lower() != here.lower():
        print("⛔ 克隆闸门跳过：本目录不是独立的 git 仓（fail-closed）")
        print("   本目录 : %s" % here)
        print("   git 顶层: %s" % (top or "(不是 git 仓)"))
        print("   ⇒ 若这是发布产物：先在本目录 `git init && git add -A && git commit` 再跑本闸门。")
        print("   ⛔ 不会回落到父仓验证（那会给出假绿）。")
        return 2

    wt = os.path.join(tempfile.gettempdir(), "aios-clone-selftest")
    if os.path.isdir(wt):
        subprocess.run(["git", "worktree", "remove", wt, "--force"], cwd=ROOT,
                       capture_output=True)
        shutil.rmtree(wt, ignore_errors=True)
    code, out = run(["git", "worktree", "add", wt, "HEAD", "--detach"], ROOT)
    if code != 0:
        print("⛔ 建 worktree 失败:", out[-300:])
        return 1
    print("干净克隆:", wt)

    results = []

    code, out = run([sys.executable, os.path.join("tools", "task_card.py"), "states"], wt)
    results.append(("① 卡系统 states", code == 0, out.strip().split("\n")[-3:]))

    code, out = run([sys.executable, os.path.join("tools", "probes", "_capability_field_lint.py")], wt)
    m = re.search(r"合计 (\d+) · OK (\d+) · WARN (\d+) · FAIL (\d+)", out)
    ok = bool(m) and int(m.group(4)) == 0
    results.append(("② 能力字段校验", ok, m.group(0) if m else out[-200:]))

    code, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tools/tests", "-p", "test_*.py"], wt)
    m = re.search(r"Ran (\d+) tests", out)
    results.append(("③ tools 测试", code == 0 and bool(m), (m.group(0) if m else out[-200:])))

    code, out = run(["node", os.path.join("runtime", "tests", "activation.test.mjs")], wt)
    m = re.search(r"合计 (\d+) 项 · 通过 (\d+) · 失败 (\d+)", out)
    fails = re.findall(r"^FAIL\s+(\S+)", out, re.M)
    unexpected = [f for f in fails if not any(k in f for k in KNOWN_RED)]
    ok = bool(m) and len(unexpected) == 0
    results.append(("④ runtime 自测", ok, (m.group(0) if m else "无汇总行") +
                    (" | 非预期红: " + ",".join(unexpected) if unexpected else " | 仅已知红")))

    print()
    allok = True
    for name, ok, detail in results:
        print("%s %-16s %s" % ("✅" if ok else "⛔", name, detail))
        allok = allok and ok

    if not args.keep:
        subprocess.run(["git", "worktree", "remove", wt, "--force"], cwd=ROOT, capture_output=True)
        print("\n(已清理 worktree)")
    else:
        print("\n(保留:", wt, ")")
    print("\n判定:", "✅ 克隆可用" if allok else "⛔ 克隆不可用")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
