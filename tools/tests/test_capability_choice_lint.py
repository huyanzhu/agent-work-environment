# -*- coding: utf-8 -*-
"""test_capability_choice_lint.py — 「卡字段 ↔ `.log` 一致」校验（v3）

被测：`tools/probes/_capability_choice_lint.py: check_one()`
判据：
  · **旧三阶段卡**（有 `- 开工:` / `- 实现:` / `- 收尾:` 行）：卡上有「## 使用的能力（三阶段 ·
    可 none）」节 ⇒ 该阶段字段必须与 `.log` 的 name **一致**（不一致 ⇒ FAIL，detail 指出两边值）；
    仅当卡有该节时才校验 —— v1/v2 卡没有 ⇒ 跳过（⛔ 不判 FAIL）；既有三 stage 判据逐字不变。
  · **v4 单字段卡**（有 `- 能力:` 行、无三阶段行）：只要求一条 `.log` 行（State=`能力`，
    name 非空）；该行时间不晚于该会话首次 edit（取不到 ⇒ timing=n/a，⛔ 不判 FAIL）；该会话
    仍需 read `capabilities/` ≥ 1（name=none 除外）；`--stage` 忽略（缺 `--stage` 也不判红）。
  · 两种行都有 ⇒ **旧卡优先**（按三阶段判）；两种都没有 ⇒ 既有 SKIP / PENDING 逻辑。

纪律：全部在 `work/` 临时根里造卡；⛔ 不碰真实 `task_cards/active`、⛔ 不碰真实探针。
"""
import datetime
import importlib.util
import io
import os
import shutil
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LINT_PY = os.path.join(ROOT, "tools", "probes", "_capability_choice_lint.py")
TMP = os.path.join(ROOT, "work", "_selftest_choice_lint")


def load_lint():
    """按文件路径加载被测模块（`_` 前缀不能直接 import）。"""
    spec = importlib.util.spec_from_file_location("capability_choice_lint_under_test", LINT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LINT = load_lint()

CARD_HEAD = """# TASK_CARD — 一致性用例

## Header

```
Task ID:     TASK-20260101-901
Created:     2026-11-01 23:30
```

## Goal

卡字段 ↔ `.log` 一致性用例。

## Current Status

```
State:         Executing
```

"""

SECTION = """## 使用的能力（三阶段 · 可 none）

> 由脚本填。

- 开工: `（未记录）`
- 实现: `%s`
- 收尾: `（未记录）`

"""

LOG = ("| Time | State | Reason | Changed By |\n"
       "|------|-------|--------|:----------:|\n"
       "| 10:00 | Executing | claim 占用（session: sess-me） | Worker |\n"
       "| 10:01 | 能力-实现 | %s ｜ 理由：一致性用例 | Worker |\n")

#: `.log` 表头 + claim 留痕（会话固定 `sess-me`，与探针用例同源）
LOG_HEAD = ("| Time | State | Reason | Changed By |\n"
            "|------|-------|--------|:----------:|\n"
            "| 10:00 | Executing | claim 占用（session: sess-me） | Worker |\n")

#: v4 单字段卡的「使用的能力」节（`- 能力:` 一行；⛔ 无开工/实现/收尾行）
SECTION_V4 = """## 使用的能力（可 none）

> 由脚本填。

- 能力: `%s` ｜ 单字段用例

"""


class CapabilityChoiceLintConsistencyTest(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(TMP)
        # impl 阶段不读探针；给空索引，避免本用例碰到真实 `.aios/` 探针
        self.probe = ({}, {})

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def _card(self, name_in_card, log_name, with_section=True):
        p = os.path.join(TMP, "TASK-20260101-901.md")
        text = CARD_HEAD
        if with_section:
            text += SECTION % name_in_card
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        with io.open(p[:-3] + ".log", "w", encoding="utf-8", newline="") as f:
            f.write(LOG % log_name)
        return p

    def _check(self, p):
        return LINT.check_one(p, "impl", probe=self.probe, tpl=LINT.activation_cutoff())

    def test_matching_card_and_log_pass(self):
        r = self._check(self._card("test-driven-development", "test-driven-development"))
        self.assertEqual(r["verdict"], "PASS", r)
        self.assertEqual(r["name"], "test-driven-development")

    def test_mismatch_fails_with_both_values(self):
        r = self._check(self._card("prose_standard", "test-driven-development"))
        self.assertEqual(r["verdict"], "FAIL", r)
        self.assertEqual(r["name"], "test-driven-development", "name 仍取 `.log` 值")
        self.assertIn("不一致", r["detail"])
        self.assertIn("卡字段", r["detail"])
        self.assertIn("prose_standard", r["detail"], "detail 要指出卡上的值")
        self.assertIn("test-driven-development", r["detail"], "detail 要指出 `.log` 的值")

    def test_card_without_section_is_skipped_not_failed(self):
        """v1/v2 卡没有该节 ⇒ 跳过一致性校验（⛔ 不得因此判 FAIL）。"""
        r = self._check(self._card("ignored", "test-driven-development", with_section=False))
        self.assertEqual(r["verdict"], "PASS", "无该节 ⇒ 跳过（⛔ 不判 FAIL）：%r" % r)

    # ── 🔴 （v4）：单字段卡 —— 只要求一条 `能力` 行，stage 忽略 ─────────────
    def _probe(self, first_time=(10, 2, 30), reads=1, session="sess-me"):
        """`(first_edit, cap_reads)`：`.log` 行 10:01 vs first 10:02:30 ⇒ 早于；reads=0 ⇒ 没读。"""
        first = datetime.datetime.combine(datetime.date.today(), datetime.time(*first_time))
        return ({session: first}, {session: reads} if reads else {})

    def _card_v4(self, log_name="domain-docs", card_name=None, row_time="10:01",
                 with_single_line=True, created=None):
        """造 v4 形态卡（有 `- 能力:` 行、无三阶段行）+ `.log`（claim + 一条 `能力` 行）。"""
        p = os.path.join(TMP, "TASK-20260101-902.md")
        text = CARD_HEAD
        if created is not None:
            text = text.replace("2026-11-01 23:30", created)
        if with_single_line:
            text += SECTION_V4 % (card_name if card_name is not None else log_name)
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        rows = LOG_HEAD
        if log_name is not None:
            rows += "| %s | 能力 | %s ｜ 理由：单字段用例 | Worker |\n" % (row_time, log_name)
        with io.open(p[:-3] + ".log", "w", encoding="utf-8", newline="") as f:
            f.write(rows)
        return p

    def _check_v4(self, p, stage="impl", probe=None):
        return LINT.check_one(p, stage, probe=probe if probe is not None else self._probe(),
                              tpl=LINT.activation_cutoff())

    def test_v4_single_field_one_row_passes(self):
        """v4 卡 + 一条 `能力` 行 ⇒ PASS（name 取该行；timing 判早于首次 edit）。"""
        r = self._check_v4(self._card_v4("domain-docs"))
        self.assertEqual(r["verdict"], "PASS", r)
        self.assertEqual(r["name"], "domain-docs")
        self.assertEqual(r["timing"], "before-first-edit", r)

    def test_v4_single_field_zero_rows_fails(self):
        """v4 卡 + 零条 `能力` 行 ⇒ FAIL（detail 说清"缺 `能力` 记录"）。"""
        r = self._check_v4(self._card_v4(log_name=None))
        self.assertEqual(r["verdict"], "FAIL", r)
        self.assertIn("缺 `能力` 记录", r["detail"])
        self.assertIn("能力", r["detail"])

    def test_v4_single_field_last_row_wins(self):
        """🔴 A 案单字段卡**末条即权威** —— 改声明后按末条判，⛔ 不因首条判红。

        理由：注入侧读 `.log` 末条；校验侧若读首条 ⇒ 更新声明必"不一致" ⇒ agent 永不更新。
        """
        p = self._card_v4("domain-docs")
        with io.open(p[:-3] + ".log", "a", encoding="utf-8", newline="") as f:
            f.write("| 10:02 | 能力 | domain-backend ｜ 理由：第二段换成后端域 | Worker |\n")
        r = self._check_v4(p)
        self.assertEqual(r["verdict"], "PASS", r)
        self.assertEqual(r["name"], "domain-backend", "末条应胜出：%r" % (r,))

    def test_v4_single_field_ignores_stage(self):
        """`--stage start|impl|close` 用在 v4 卡上 ⇒ 忽略 stage，都不判红。"""
        p = self._card_v4("domain-docs")
        for st in ("start", "impl", "close"):
            with self.subTest(stage=st):
                r = self._check_v4(p, st)
                self.assertEqual(r["verdict"], "PASS", "stage=%s 必须被忽略：%r" % (st, r))

    def test_v4_missing_stage_is_accepted_by_cli(self):
        """单字段卡**省略 `--stage`** ⇒ 也能判（⛔ 不因缺 stage 报参数错 / 判红）。"""
        p = self._card_v4("domain-docs")
        old = LINT.probe_index
        LINT.probe_index = lambda: self._probe()
        buf = io.StringIO()
        try:
            from contextlib import redirect_stdout
            with redirect_stdout(buf):
                code = LINT.main(["lint", p])
        finally:
            LINT.probe_index = old
        self.assertEqual(code, 0, "缺 --stage + 单字段卡 ⇒ 应 PASS：\n" + buf.getvalue())
        self.assertIn('"stage": "once"', buf.getvalue())

    def test_v4_single_field_timing_unavailable_is_not_fail(self):
        """探针取不到该会话首次 edit ⇒ timing=n/a，⛔ 不判 FAIL（read 仍满足）。"""
        r = self._check_v4(self._card_v4("domain-docs"), probe=({}, {"sess-me": 1}))
        self.assertEqual(r["verdict"], "PASS", r)
        self.assertEqual(r["timing"], "n/a", r)

    def test_v4_single_field_late_timing_fails(self):
        """`能力` 行晚于首次 edit（10:05 > 10:02:30）⇒ FAIL，timing=after。"""
        r = self._check_v4(self._card_v4("domain-docs", row_time="10:05"))
        self.assertEqual(r["verdict"], "FAIL", r)
        self.assertEqual(r["timing"], "after", r)
        self.assertIn("晚于", r["detail"])

    def test_v4_card_created_after_first_edit_timing_na_not_fail(self):
        """卡建在该会话首次 edit **之后**（同会话里的后建卡）⇒ timing=n/a，⛔ 不判 FAIL。"""
        r = self._check_v4(self._card_v4("domain-docs", created="2099-01-01 00:00"))
        self.assertEqual(r["verdict"], "PASS", r)
        self.assertEqual(r["timing"], "n/a", r)

    def test_v4_single_field_without_capabilities_read_fails(self):
        """name ≠ none 但该会话没 read `capabilities/` ⇒ FAIL（沿用既有口径）。"""
        r = self._check_v4(self._card_v4("domain-docs"), probe=self._probe(reads=0))
        self.assertEqual(r["verdict"], "FAIL", r)
        self.assertIn("capabilities/", r["detail"])

    def test_v4_single_field_none_is_pass_without_capability_read(self):
        """`none` 是合法值：`.log` 有 `能力` 行（name=none）⇒ PASS，⛔ 不要求 read capabilities/。"""
        r = self._check_v4(self._card_v4("none"), probe=self._probe(reads=0))
        self.assertEqual(r["verdict"], "PASS", r)
        self.assertEqual(r["name"], "none")
        self.assertIn("name=none", r["detail"])

    def test_card_with_both_forms_stays_legacy(self):
        """两种行都在 ⇒ **旧卡优先**：只有单字段 `能力` 行⛔ 不能满足三阶段判据。"""
        p = os.path.join(TMP, "TASK-20260101-903.md")
        text = (CARD_HEAD + (SECTION % "test-driven-development")
                + "- 能力: `domain-docs` ｜ 额外单字段行\n")
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        with io.open(p[:-3] + ".log", "w", encoding="utf-8", newline="") as f:
            f.write(LOG_HEAD + "| 10:01 | 能力 | domain-docs ｜ 理由：单字段用例 | Worker |\n")
        r = LINT.check_one(p, "start", probe=self._probe(), tpl=LINT.activation_cutoff())
        self.assertEqual(r["verdict"], "PENDING",
                         "两种行都在 ⇒ 走旧三阶段判据（缺 `能力-开工` ⇒ PENDING，⛔ 不 PASS）：%r" % r)

    def test_prose_nengli_line_is_not_single_mode(self):
        """旧卡正文里的 `能力: …`（**无列表符**）⛔ 不得被当成 v4 卡判红（假红护栏）。"""
        p = os.path.join(TMP, "TASK-20260101-904.md")
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            f.write(CARD_HEAD + "本卡能力: 用 test-driven-development 就够\n")
        with io.open(p[:-3] + ".log", "w", encoding="utf-8", newline="") as f:
            f.write(LOG_HEAD)
        r = LINT.check_one(p, "impl", probe=self._probe(), tpl=LINT.activation_cutoff())
        self.assertEqual(r["verdict"], "PENDING",
                         "无列表符的散文行⛔ 不得触发单字段判据（应走既有 PENDING）：%r" % r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
