# -*- coding: utf-8 -*-
"""PITFALLS 编号 lint 的回归用例（缺号名单 / 列数 / 内联竖线 / 重复编号）。

被测脚本：tools/probes/_pitfalls_id_lint.py
跑法：python -m unittest tools.tests.test_pitfalls_id_lint
"""
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LINT = os.path.join(ROOT, "tools", "probes", "_pitfalls_id_lint.py")

HEAD = (
    "# PITFALLS — 踩过的坑（发布版）\n\n"
    "> 过滤版。\n"
)


def card_text(rows, drop_line=""):
    text = HEAD
    if drop_line:
        text += drop_line + "\n"
    text += "\n| # | 现象 | 触发条件 | 处置 | 来源 |\n|---|---|---|---|---|\n"
    return text + rows + "\n"


class PitfallsIdLintTest(unittest.TestCase):
    def setUp(self):
        # 隔离目录落工作区内（P12）。⚠️ 本机 `tempfile.mkdtemp(dir=...)` 建出的目录
        # 无法再建子目录（WinError 5，2026-11-02 实测）⇒ 显式 os.makedirs 到唯一名。
        base = os.path.join(ROOT, "_pitfalls_lint_%d" % os.getpid())
        n = 0
        while os.path.exists(base):
            n += 1
            base = os.path.join(ROOT, "_pitfalls_lint_%d_%d" % (os.getpid(), n))
        self.tmp = base
        self.mem = os.path.join(self.tmp, "task_cards", "memory")
        os.makedirs(self.mem)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_lint(self, root):
        p = subprocess.run(
            [sys.executable, LINT, "--root", root],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    def write(self, text):
        with open(os.path.join(self.mem, "PITFALLS.md"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_live_repo_is_green(self):
        """发布版 PITFALLS 必须全绿（本次修复的验收位）。"""
        rc, out = self.run_lint(ROOT)
        self.assertEqual(rc, 0, out)
        self.assertIn("FAIL 0", out)

    def test_missing_id_without_drop_list_fails(self):
        """P1/P3 缺 P2 且无「未随发布条目」⇒ 必须报缺号。"""
        self.write(card_text(
            "| P1 | a | b | c | d |\n| P3 | a | b | c | d |"))
        rc, out = self.run_lint(self.tmp)
        self.assertEqual(rc, 1, out)
        self.assertIn("缺: P2", out)

    def test_missing_id_in_drop_list_passes(self):
        """缺号写进「未随发布条目」⇒ 不再算缺号。"""
        self.write(card_text(
            "| P1 | a | b | c | d |\n| P3 | a | b | c | d |",
            drop_line="> 未随发布条目：P2（本机环境）"))
        rc, out = self.run_lint(self.tmp)
        self.assertEqual(rc, 0, out)
        self.assertIn("未随发布名单 1", out)

    def test_wrong_column_count_fails(self):
        """4 列行 ⇒ 列数 FAIL，并点名该行。"""
        self.write(card_text(
            "| P1 | a | b | c | d |\n| P2 | a | b | c |"))
        rc, out = self.run_lint(self.tmp)
        self.assertEqual(rc, 1, out)
        self.assertIn("列数不符", out)
        self.assertIn("P2(4列)", out)

    def test_pipe_inside_code_span_keeps_five_columns(self):
        """内联代码里的 `|` 不算列分隔符（校准位，防假红）。"""
        self.write(card_text(
            "| P1 | a | b | `x|y` | d |\n| P2 | a | b | `p|q` | d |"))
        rc, out = self.run_lint(self.tmp)
        self.assertEqual(rc, 0, out)

    def test_duplicate_id_fails(self):
        """同号出现两次 ⇒ 编号唯一 FAIL。"""
        self.write(card_text(
            "| P1 | a | b | c | d |\n| P1 | a | b | c | d |"))
        rc, out = self.run_lint(self.tmp)
        self.assertEqual(rc, 1, out)
        self.assertIn("重复: P1", out)


if __name__ == "__main__":
    unittest.main()
