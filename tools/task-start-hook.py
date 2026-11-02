#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""task-start-hook.py — R1（任务恢复）的**可独立执行薄壳**（收敛后）

角色：把「任务恢复」包成 Claude Code 方言的**一行 JSON**，供**单事件直连**或自测使用。
      runtime 的正常路径已改走稳定入口 `tools/aios-hook.py`（R0 dispatcher · `§12.1`）——
      `.claude/hooks.json` 三个事件现在都指向 dispatcher，本文件因此**降级为薄壳**：
      与 dispatcher 的 `task_recovery` action **同源调用** `task_start.recovery_text()`，
      **不复制任何发现逻辑**（守「AI-OS 不新建 Runtime、不能有自己的账本」）。

为什么保留：① `§11.5 ⑤`「保留已验证件」；② 需要**绕过开关**做单点验证时的直连入口。

收敛（`§12.0.1` §12.2）：**只送任务恢复**（卡 / Goal / 下一步 / 路径）。
      原实现把"卡 + 知识 + 能力"三者全送 —— 而开工时还不知道用户要做什么，
      读数无 prompt 时能力 trigger **9/9 全命中**（bigram 无阈值）= 构造性噪声。
      经验 / 能力发现归**进行时**（`UserPromptSubmit` · R4 · `§12.5`）。

为什么注入摘要而不是全量：`task_start.py` 全量输出 ≈9.2 KB / ≈2.6k tokens，
而 hook 文本会被后续**每个请求**重发直到压缩（`hooks-claude-code` README「Model Experience」）
⇒ 只送【判断要用的材料】+ 一条取全量的指针。

纪律（不变）：
  · stdout **只打一行 JSON** —— claude-code 方言只认 JSON，多余文本会破坏解析；
  · 任何异常都不得阻塞：失败 = 不注入，Agent 照常开始（一律 exit 0，诊断走 stderr）。
"""
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def main():
    try:
        import task_start as ts          # 同源：发现逻辑不复制
        text = ts.recovery_text()
    except BaseException:                # noqa: BLE001 —— 失败 = 不注入，绝不阻塞
        import traceback
        traceback.print_exc(file=sys.stderr)   # 诊断走 stderr（DSH 记进 hook/result）
        return 0
    sys.stdout.write(json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}},
        ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
