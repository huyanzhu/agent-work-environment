#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""" + 回归自测（主线收尾批次）。

为什么存在：`tools/aios-hook.py` 的幂等状态此前"写不进去但不报错"——
hook 子进程的沙箱写根 = `sandbox-policy.workspaceRoot`（DSH 启动目录），不是 `ROOT`。
本测试锁住修复后的行为，防止再退化成"静默重复提醒"。

覆盖：
  F. 候选链：首选 = `<ROOT>/.aios`，含 DSH_HOME/TEMP/scratch 兜底且无重复
  A. 首选可写 ⇒ 写首选、读回一致
  B. 首选不可写 ⇒ 探测**降级**到下一候选 + stderr 有「降级」诊断（⛔ 不静默）
  . 全部候选不可写 ⇒ 明确失败 + 诊断
  C. 读侧合并：主 + 兜底两份状态取**并集**（降级后旧状态不丢）
  D. `r3_notice_start` 幂等：第二次返回空
  E. 去重：同卡未被 `ownership_lost` 记过 ⇒ 出边界提醒；已记过 ⇒ 不再单独出

运行：`python tools/tests/test_aios_hook_state.py`
"""
import importlib.util
import json
import os
import shutil
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(ROOT, "tools", "aios-hook.py")

spec = importlib.util.spec_from_file_location("aios_hook", HOOK)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)  # `__main__` 保护 ⇒ 不跑 main()

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  → " + detail if detail else ""))
        FAILED.append(name)


class capture_stderr:
    def __enter__(self):
        self.buf = []
        self._old = sys.stderr
        sys.stderr = self
        return self.buf

    def write(self, s):
        self.buf.append(str(s))

    def flush(self):
        pass

    def __exit__(self, *a):
        sys.stderr = self._old
        return False


def main():
    tmp = os.path.join(ROOT, "scratch", "_p33_test_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    primary = os.path.join(tmp, ".aios")
    fallback = os.path.join(tmp, "fallback")

    def roots(lst):
        """设候选链 + 清探测缓存（否则进程内缓存会让后续用例串味）。"""
        h._state_roots = (lambda: lst)
        h._STATE_DIR_CACHE.clear()

    # F. 默认候选链
    default_roots = h._state_roots()
    check("F 首选 = ROOT/.aios", default_roots[0] == os.path.join(ROOT, ".aios"), str(default_roots[:2]))
    check("F 候选 ≥3 且无重复",
          len(default_roots) >= 3 and len(set(default_roots)) == len(default_roots), str(default_roots))

    # A. 首选可写
    roots([primary, fallback])
    ok, p = h._save_state("t", "s1", {"n": ["a"]})
    check("A 写首选", ok and p is not None and os.path.isfile(p) and p.startswith(primary), str(p))
    check("A 读回", h._load_state("t", "s1").get("n") == ["a"])

    # B. 首选不可写（用同名**文件**挡住目录创建）⇒ 降级 + 诊断
    blocked = os.path.join(tmp, "blocked")
    with open(blocked, "w", encoding="utf-8") as f:
        f.write("x")
    roots([blocked, fallback])
    with capture_stderr() as err:
        ok2, p2 = h._save_state("t", "s2", {"n": ["b"]})
    check("B 降级成功", ok2 and p2 is not None and p2.startswith(fallback), str(p2))
    check("B 降级有诊断", any("降级" in s for s in err), "".join(err)[:300])

    # . 全部候选不可写 ⇒ 明确失败
    roots([blocked, os.path.join(blocked, "x")])
    with capture_stderr() as err3:
        ok3, p3 = h._save_state("t", "s3", {"n": ["c"]})
    check("B2 全失败返回 False", ok3 is False and p3 is None)
    check("B2 全失败有诊断", any("无可写根" in s or "无可用状态根" in s for s in err3), "".join(err3)[:300])

    # C. 合并（主 + 兜底）
    roots([primary, fallback])
    # C. 单调状态：**主根权威**（不合并陈旧兜底副本 —— A 组 review 后的口径）
    roots([primary, fallback])
    h._save_state("cards", "s4", {"cards": ["A"]})
    os.makedirs(os.path.join(fallback, "cards"), exist_ok=True)
    with open(os.path.join(fallback, "cards", "s4.json"), "w", encoding="utf-8") as f:
        json.dump({"cards": ["B"]}, f)
    check("C 主根权威（陈旧副本不得钉死状态）", h._load_state("cards", "s4").get("cards") == ["A"],
          str(h._load_state("cards", "s4")))
    # . 主根缺失 ⇒ 回落兜底
    os.remove(os.path.join(primary, "cards", "s4.json"))
    check("C2 主根缺失回落兜底", h._load_state("cards", "s4").get("cards") == ["B"])

    # D. r3_notice_start 幂等
    roots([os.path.join(tmp, "r3a"), os.path.join(tmp, "r3b")])
    h.r3_wake_enabled = lambda: False
    h._r3_session = lambda payload: "session-me"
    first = h.action_r3_notice_start({"session_id": "session-me"})
    second = h.action_r3_notice_start({"session_id": "session-me"})
    check("D 首次出提醒", "R3 状态提醒" in first, first[:120])
    check("D 第二次幂等空", second == "", second[:120])

    # E. 去重
    roots([os.path.join(tmp, "c2a"), os.path.join(tmp, "c2b")])
    h._r3_taken_over_cards = lambda tc, me: [("TASK-R3X", "session-other")]
    h.r3_wake_enabled = lambda: False
    h._r3_session = lambda payload: "session-me"

    out1 = h.action_r3_notice_lost({"session_id": "session-me"})
    check("E1 未覆盖时出边界提醒", "TASK-R3X" in out1 and "别的会话占用" in out1, out1[:160])

    h._save_state("maint-notified", "session-me", {"notified": ["TASK-R3X"]})
    out2 = h.action_r3_notice_lost({"session_id": "session-me"})
    check("E2 已覆盖时去重为空", out2 == "", out2[:160])

    print("\n合计：%d 项失败" % len(FAILED))
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    try:
        rc = main()
    except BaseException:
        traceback.print_exc()
        rc = 2
    sys.exit(rc)
