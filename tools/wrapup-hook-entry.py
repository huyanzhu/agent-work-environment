#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hook 诊断入口—— 把 hook 进程的实况尽可能打到 stdout/stderr。

为什么需要它：.cmd 启动器 + 留痕文件的方案在 hook 环境里始终"什么都没留下"，
无法区分"没被执行 / 执行了但写不进去 / 在导入阶段就被拒"。
本入口不依赖任何文件写入成功：所有关键信息直接 print 到 stdout 与 stderr，
而 DSH 会把它们记进会话的 hook/result（stdout 决定 decision，stderr 进 stderrSummary）。
"""
import os
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 仓库根（本文件在 <root>/tools/ 下）—— ⛔ 不写死本机路径，换目录也能跑
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def note(msg):
    print(f"[hook-diag] {msg}")
    print(f"[hook-diag] {msg}", file=sys.stderr)


def main():
    # 最先、无条件地把"我活着"打到 stderr —— 这行不依赖任何写权限，
    # 只要 hook 进程真的执行到这个入口，DSH 的 hook/result 里就一定看得到。
    note("ALIVE — hook entry executed")
    note(f"python={sys.executable}")
    note(f"cwd={os.getcwd()}")
    note(f"argv={sys.argv[1:]}")
    note(f"TEMP={os.environ.get('TEMP')}")
    note(f"DSH_HOME={os.environ.get('DSH_HOME')}")
    note(f"CLAUDE_PROJECT_DIR={os.environ.get('CLAUDE_PROJECT_DIR')}")

    # 写权限探测：工作区内 / 系统 TEMP
    for target in (
        os.path.join(ROOT, "scratch", "_hookdiag-workspace.txt"),
        os.path.join(os.environ.get("TEMP", os.path.join(ROOT, "scratch", "tmp")), "_hookdiag-temp.txt"),
    ):
        try:
            with open(target, "a", encoding="utf-8") as f:
                f.write("probe\n")
            note(f"write OK   {target}")
        except OSError as e:
            note(f"write FAIL {target} -> {type(e).__name__}: {e}")

    # 转发到真实脚本（不隐藏它的输出，但把异常也打出来）
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import importlib.util

        spec = importlib.util.spec_from_file_location("wrapup_sync", os.path.join(ROOT, "tools", "wrapup_sync.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["wrapup_sync"] = mod
        spec.loader.exec_module(mod)      # 这一步若被拒（如 _root_guard），异常会打出来
        note("import wrapup_sync OK")
        rc = mod.main()
        note(f"wrapup_sync.main() rc={rc}")
        return rc or 0
    except BaseException:
        note("EXCEPTION while running wrapup_sync:")
        for line in traceback.format_exc().splitlines():
            note(line)
        return 0   # 诊断入口自身永远不阻塞 agent


if __name__ == "__main__":
    sys.exit(main())
