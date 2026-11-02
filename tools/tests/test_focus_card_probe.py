#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""焦点卡跨语言接口 · **读取侧（只诊断 · 不切换）** 的隔离自测 · 步 2

契约：`task_cards/active/demo-project/p0/FOCUS-CARD-INTERFACE-DESIGN.md`

测什么（全部为**判据层** · ⛔ 不触真实运行数据）：
  T1  hit            —— 合法且会话相符 ⇒ 命中
  T2  missing        —— 文件不存在
  T3  corrupt        —— JSON 非法 / 顶层非对象
  T4  schema-mismatch—— 版本不符（⛔ 不尝试解析旧版）
  T5  session-mismatch —— **预期内正常分支**（别的会话的判定 · 也是**陈旧隔离的实际承担者**）
  T6 🔴 hit-stale —— **已过期仍命中**（选项 A：TTL 不再是失效判据，只记 `ageMs`）
  T7  bad-card       —— `card` 缺失 / 空（⛔ `expiresAt` 非法**不再**算 bad-card）
  T8  cwdDiff        —— `cwd` 不一致 ⇒ **仍判命中**（只记录、不拒绝）
  T9  🔴 **诊断不改变写回行为** —— `ws.main` 必被调用且参数/返回值不受 hit/miss 影响
   诊断是 append-only 且隔离（⛔ 不写真实 `.aios/`）

纪律：所有用例在临时目录内 · 先保存后还原被测模块的全局量 · ⛔ 不碰真实 `.aios/`。

运行：`python tools/tests/test_focus_card_probe.py`（**独立脚本** · ⛔ 不是 unittest 模块）
      —— 用例只在 `if __name__ == "__main__"` 下执行 ⇒ 导入期零副作用，
      `unittest discover` 把它当 0 用例模块（不再是 import ERROR）。
退出码：0 = 全通过；1 = 有失败。
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
HOOK_PY = os.path.join(TOOLS, "aios-hook.py")

RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append("PASS  " + name)
    except AssertionError as exc:
        RESULTS.append("FAIL  " + name + " :: " + str(exc))
    except Exception as exc:  # noqa: BLE001
        RESULTS.append("FAIL  " + name + " :: 异常 " + type(exc).__name__ + ": " + str(exc))


def load_hook():
    """按文件路径加载 `aios-hook.py`（文件名带连字符 ⇒ 不能直接 import）。"""
    spec = importlib.util.spec_from_file_location("aios_hook_under_test", HOOK_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SESSION = "session-selftest-fc"
CWD = "<repo>"


def write_card(**over):
    o = {
        "schema": "focus-card/v1",
        "session": SESSION,
        "cwd": CWD,
        "card": "projA/TASK-20260101-001.md",
        "basis": "session-claim",
        "windowSeq": 7,
        "writtenAt": int(time.time() * 1000),
        "expiresAt": int(time.time() * 1000) + 600_000,
        "writer": "aios-activation",
        "writerPolicy": "v13-test",
    }
    o.update(over)
    with io.open(CARD_FILE, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(o, ensure_ascii=False, indent=2) + "\n")


def clear_card():
    try:
        os.remove(CARD_FILE)
    except OSError:
        pass


def probe_records():
    try:
        with io.open(PROBE_FILE, "r", encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except OSError:
        return []


def clear_probe():
    try:
        os.remove(PROBE_FILE)
    except OSError:
        pass


PAYLOAD = {"session_id": SESSION, "cwd": CWD, "hook_event_name": "Stop"}


# ── T1 ────────────────────────────────────────────────────────────────────
def t1():
    clear_card()
    clear_probe()
    write_card()
    hit, reason = hook.focus_card_probe(PAYLOAD)
    assert hit is True, "合法且会话相符 ⇒ 必须命中，实际 reason=" + reason
    assert reason == "hit", "reason 应为 hit"
    rec = probe_records()[-1]
    assert rec["ev"] == "focus-card-hit", "诊断事件名必须是 focus-card-hit"
    assert rec["card"] == "projA/TASK-20260101-001.md", "命中的卡必须被记录"
    assert rec["cwdDiff"] is False, "cwd 一致 ⇒ cwdDiff 必须 False"


# ── T2 ────────────────────────────────────────────────────────────────────
def t2():
    clear_card()
    clear_probe()
    hit, reason = hook.focus_card_probe(PAYLOAD)
    assert hit is False and reason == "missing", "缺文件 ⇒ missing，实际 " + reason
    assert probe_records()[-1]["ev"] == "focus-card-miss", "miss 必须落诊断"


# ── T3 ────────────────────────────────────────────────────────────────────
def t3():
    clear_probe()
    with io.open(CARD_FILE, "w", encoding="utf-8") as fh:
        fh.write("{ not json")
    assert hook.focus_card_probe(PAYLOAD) == (False, "corrupt"), "非法 JSON ⇒ corrupt"
    with io.open(CARD_FILE, "w", encoding="utf-8") as fh:
        fh.write("[1,2,3]")
    assert hook.focus_card_probe(PAYLOAD) == (False, "corrupt"), "顶层非对象 ⇒ corrupt"


# ── T4 ────────────────────────────────────────────────────────────────────
def t4():
    clear_probe()
    write_card(schema="focus-card/v0")
    hit, reason = hook.focus_card_probe(PAYLOAD)
    assert (hit, reason) == (False, "schema-mismatch"), "版本不符 ⇒ schema-mismatch，实际 " + reason
    assert probe_records()[-1]["gotSchema"] == "focus-card/v0", "必须如实记录读到的版本"


# ── T5 ────────────────────────────────────────────────────────────────────
def t5():
    clear_probe()
    write_card(session="session-someone-else")
    hit, reason = hook.focus_card_probe(PAYLOAD)
    assert (hit, reason) == (False, "session-mismatch"), "会话不符 ⇒ session-mismatch，实际 " + reason
    # ⚠️ 语义纪律：这是**正常分支**，不得被当作故障统计（此处只锁分类名）
    assert probe_records()[-1]["reason"] == "session-mismatch", "分类名必须稳定（供按类计数）"


# ── T6 ────────────────────────────────────────────────────────────────────
def t6():
    """🔴 （选项 A）：**过期不再是失效判据** —— 仍须命中，标 `hit-stale`。"""
    clear_probe()
    now = int(time.time() * 1000)
    write_card(writtenAt=now - 700_000, expiresAt=now - 100_000)
    hit, reason = hook.focus_card_probe(PAYLOAD)
    assert hit is True, "🔴 已过期 ⇒ **仍须命中**（TTL 已非失效判据），实际 " + reason
    assert reason == "hit-stale", "过期命中应标 hit-stale，实际 " + reason
    rec = probe_records()[-1]
    assert rec["ev"] == "focus-card-hit", "hit-stale 仍属**命中**事件"
    assert rec["ageMs"] > 0, "过期命中必须附 ageMs（供观测陈旧率）"
    assert rec["card"], "命中必须带 card"
    # 另一侧：未过期 ⇒ 普通 hit
    write_card(writtenAt=now, expiresAt=now + 60_000)
    hit2, reason2 = hook.focus_card_probe(PAYLOAD)
    assert (hit2, reason2) == (True, "hit"), "未过期 ⇒ hit，实际 " + reason2
    # ⛔ `expired` **已不再是** miss 分类（值域已变）
    assert all(r["reason"] != "expired" for r in probe_records()), "⛔ 不应再产生 expired 分类"


# ── T7 ────────────────────────────────────────────────────────────────────
def t7():
    clear_probe()
    write_card(card="")
    assert hook.focus_card_probe(PAYLOAD) == (False, "bad-card"), "card 为空 ⇒ bad-card"
    write_card(card=None)
    assert hook.focus_card_probe(PAYLOAD) == (False, "bad-card"), "card 缺失 ⇒ bad-card"
    # `expiresAt` 已非失效判据 ⇒ 非法值**不再**算 bad-card（只失去陈旧诊断）
    write_card(expiresAt="not-a-number")
    hit, reason = hook.focus_card_probe(PAYLOAD)
    assert (hit, reason) == (True, "hit"), "expiresAt 非法 ⇒ 仍命中（只丢诊断），实际 " + reason
    assert "ageMs" not in probe_records()[-1], "exp 非法 ⇒ 不得编造 ageMs"


# ── T8 ────────────────────────────────────────────────────────────────────
def t8():
    clear_probe()
    write_card(cwd="D:\\OTHER\\path")
    hit, reason = hook.focus_card_probe(PAYLOAD)
    assert hit is True, "🔴 cwd 不一致 ⇒ **仍须命中**（只记录、不拒绝 —— 设计 §四 决策 3）"
    assert probe_records()[-1]["cwdDiff"] is True, "cwd 差异必须被记录"
    # 分隔符差异不应被误判为不同
    write_card(cwd="<repo>/")
    assert hook.focus_card_probe(PAYLOAD)[0] is True, "尾斜杠/分隔符差异不得影响判定"


# ── T9 ────────────────────────────────────────────────────────────────────
def t9():
    """🔴 步 2 的**核心边界**：诊断不得改变写回行为。"""
    class FakeWS(object):
        def __init__(self):
            self.calls = []

        def main(self, argv=None):
            self.calls.append(argv)
            return 0

    saved = sys.modules.get("wrapup_sync")
    fake = FakeWS()
    sys.modules["wrapup_sync"] = fake
    try:
        # ① 接口件**命中**
        clear_card()
        clear_probe()
        write_card()
        assert hook.action_wrapup_writeback(PAYLOAD) is None, "写回成功应返回 None"
        assert fake.calls == [[]], "🔴 命中时仍必须以 `[]` 调用旧写回（⛔ 不切换）"
        # ② 接口件**缺失**
        fake.calls = []
        clear_card()
        assert hook.action_wrapup_writeback(PAYLOAD) is None, "写回成功应返回 None"
        assert fake.calls == [[]], "🔴 缺失时同样以 `[]` 调用旧写回（回退不中断）"
        # ③ 诊断自身抛异常 ⇒ 写回**照常**
        fake.calls = []
        orig = hook.focus_card_probe
        hook.focus_card_probe = lambda _p: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            assert hook.action_wrapup_writeback(PAYLOAD) is None, "诊断异常必须被吞掉"
        finally:
            hook.focus_card_probe = orig
        assert fake.calls == [[]], "🔴 诊断异常时写回**仍须照常**（观察不得影响行为）"
    finally:
        if saved is None:
            sys.modules.pop("wrapup_sync", None)
        else:
            sys.modules["wrapup_sync"] = saved


# ── T10 ───────────────────────────────────────────────────────────────────
def t10():
    clear_probe()
    clear_card()
    for _ in range(3):
        hook.focus_card_probe(PAYLOAD)
    recs = probe_records()
    assert len(recs) == 3, "诊断必须 append-only（3 次调用 ⇒ 3 条），实际 %d" % len(recs)
    assert all(r["reason"] == "missing" for r in recs), "每条都必须带 reason"
    assert PROBE_FILE.startswith(TMP), "诊断件必须落在隔离目录内"
    real = os.path.join(TOOLS, "..", ".aios", "_focus-card-probe.jsonl")
    assert os.path.abspath(PROBE_FILE) != os.path.abspath(real), "🔴 隔离件不得等于真实件"


# ── 运行入口：只有**直接执行**本文件才跑用例（⛔ 导入期零副作用）────────────────
#   `unittest discover` 会导入本目录所有 `test_*.py`；若导入期执行用例并以 `sys.exit()`
#   收尾，discover 会把 SystemExit 记为 import ERROR（此前全量唯一 error 的来源）。
#   兄弟脚本 `test_aios_hook_state.py` 同法保护（它是脚本、不是 unittest 模块）。
def main():
    global hook, TMP, CARD_FILE, PROBE_FILE

    hook = load_hook()

    # ── 隔离：接口件 + 诊断件都指向**工作区内**的临时目录（⛔ 绝不碰真实 .aios/）──────
    #   ⚠️ 不用 `tempfile.mkdtemp()`：本机沙箱把系统临时区（`<旧脑根>\<文件>\tmp\dsh-*`）判为
    #      **不可写**（读数 `PermissionError: [Errno 13]`）⇒ 必须落在工作区内（与 TS 侧同法）。
    TMP = os.path.join(os.path.dirname(TOOLS), "scratch", "_selftest_fc_probe")
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    CARD_FILE = os.path.join(TMP, "focus-card.json")
    PROBE_FILE = os.path.join(TMP, "_focus-card-probe.jsonl")
    prev_env = os.environ.get("AIOS_FOCUS_CARD")
    prev_probe = hook.FOCUS_CARD_PROBE
    os.environ["AIOS_FOCUS_CARD"] = CARD_FILE
    hook.FOCUS_CARD_PROBE = PROBE_FILE

    check("T1 hit：合法且会话相符 ⇒ 命中 + 落 focus-card-hit", t1)
    check("T2 missing：文件不存在", t2)
    check("T3 corrupt：JSON 非法 / 顶层非对象", t3)
    check("T4 schema-mismatch：版本不符（⛔ 不尝试解析旧版）", t4)
    check("T5 session-mismatch：预期内正常分支（别的会话）", t5)
    check("T6 🔴 hit-stale：已过期**仍命中**（TTL 不再是失效判据）", t6)
    check("T7 bad-card：card 缺失/空（expiresAt 非法 ⇒ 仍命中）", t7)
    check("T8 cwdDiff：cwd 不一致 ⇒ 仍命中（只记录不拒绝）", t8)
    check("T9 🔴 诊断不改变写回行为（命中/缺失/诊断异常三种情形）", t9)
    check("T10 诊断 append-only 且路径隔离", t10)

    # ── 收尾：还原全局量 + 清理 ─────────────────────────────────────────────
    if prev_env is None:
        os.environ.pop("AIOS_FOCUS_CARD", None)
    else:
        os.environ["AIOS_FOCUS_CARD"] = prev_env
    hook.FOCUS_CARD_PROBE = prev_probe
    shutil.rmtree(TMP, ignore_errors=True)

    print("\n=== 焦点卡接口 · 读取侧（步 2 · 只诊断）隔离自测 ===")
    for line in RESULTS:
        print(line)
    failed = [r for r in RESULTS if r.startswith("FAIL")]
    print("\n合计 %d 项 · 通过 %d · 失败 %d"
          % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
