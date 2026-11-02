# -*- coding: utf-8 -*-
"""内容一致性 lint 的回归测试（///）—— RED 夹具必须 FAIL，真件必须 PASS。

设计原则（踩过的坑）：**规则要按真实语料校准**，⛔ 不能拿自己编的模板当判据（否则造出假红）。
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_lint(script, root, extra=None):
    cmd = [sys.executable, os.path.join(ROOT, "tools", "probes", script), "--root", root]
    if extra:
        cmd.extend(extra)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def mkroot(base):
    """造一个最小合法仓：PITFALLS + 一张族卡 + 能力/INDEX。"""
    os.makedirs(os.path.join(base, "task_cards", "memory"), exist_ok=True)
    os.makedirs(os.path.join(base, "domains", "experiences"), exist_ok=True)
    os.makedirs(os.path.join(base, "capabilities"), exist_ok=True)
    write(base, "task_cards/memory/PITFALLS.md", (
        "# PITFALLS\n\n| # | 现象 | 触发条件 | 处置 | 来源 |\n|---|---|---|---|---|\n"
        "| **P1** | 现象一 | 条件一 | 处置一 | 来源一 |\n"
        "| **P2** | 现象二 | 条件二 | 处置二 | 来源二 |\n"))
    write(base, "domains/experiences/demo_family.md", (
        "---\ntitle: 演示族\nfamily: 演示\nstatus: active\n"
        "trigger: [现象一]\nkeywords: [演示]\n---\n\n"
        "# 演示族\n\n**覆盖的坑（成员声明）**：P1 · P2（共 2 条）\n\n## 做法\n1. 照做\n"))
    write(base, "capabilities/domain-demo.md", (
        "---\nname: domain-demo\nintro: 当演示时 ⇒ 照做。\n"
        "axis_domain: [演示]\naxis_help: [实现]\naxis_concern: [正确性]\n"
        "keywords: [演示]\ndomain: 演示\nparts:\n"
        "  - id: domain-demo#one\n    domain: 演示\n    label: 一片\n"
        "    one_line: 照做就行\n    origin: 本库真事\n---\n\n# 演示 能力\n\n## 做法\n1. 照做\n"))
    write(base, "capabilities/INDEX.md", (
        "# capabilities/INDEX\n\n| # | 域能力 | 领域 | 片数 | 什么时候用 |\n|---|---|---|---|---|\n"
        "| 1 | `domain-demo` | 演示 | 1 | 演示用。 |\n"))


def write(base, rel, text):
    p = os.path.join(base, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, "w", encoding="utf-8", newline="\n").write(text)


class ContentLintTest(unittest.TestCase):
    def setUp(self):
        # ⚠️ 不用 tempfile.mkdtemp（0700 DACL · 沙箱不可写）⇒ 用工作区内普通目录
        self.tmp = os.path.join(ROOT, "work", "_selftest_content_lints")
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.makedirs(self.tmp)
        mkroot(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── PITFALLS 编号 ──────────────────────────────────────────
    def test_pitfalls_clean_passes(self):
        code, out = run_lint("_pitfalls_id_lint.py", self.tmp)
        self.assertEqual(code, 0, out)

    def test_pitfalls_duplicate_fails(self):
        p = os.path.join(self.tmp, "task_cards", "memory", "PITFALLS.md")
        s = io.open(p, encoding="utf-8").read()
        s += "| **P2** | 重复号 | c | d | e |\n"
        io.open(p, "w", encoding="utf-8", newline="\n").write(s)
        code, out = run_lint("_pitfalls_id_lint.py", self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("重复", out)

    def test_pitfalls_gap_fails(self):
        p = os.path.join(self.tmp, "task_cards", "memory", "PITFALLS.md")
        s = io.open(p, encoding="utf-8").read()
        s += "| **P9** | 跳号 | c | d | e |\n"
        io.open(p, "w", encoding="utf-8", newline="\n").write(s)
        code, out = run_lint("_pitfalls_id_lint.py", self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("缺", out)

    # ── 族卡结构 ───────────────────────────────────────────────
    def test_family_clean_passes(self):
        code, out = run_lint("_family_field_lint.py", self.tmp)
        self.assertEqual(code, 0, out)

    def test_family_missing_trigger_fails(self):
        p = os.path.join(self.tmp, "domains", "experiences", "demo_family.md")
        s = io.open(p, encoding="utf-8").read().replace("trigger: [现象一]\n", "")
        io.open(p, "w", encoding="utf-8", newline="\n").write(s)
        code, out = run_lint("_family_field_lint.py", self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("trigger", out)

    # ── 成员声明 ───────────────────────────────────────────────
    def test_family_members_clean_passes(self):
        code, out = run_lint("_family_members_lint.py", self.tmp)
        self.assertEqual(code, 0, out)

    def test_family_members_dangling_fails(self):
        p = os.path.join(self.tmp, "domains", "experiences", "demo_family.md")
        s = io.open(p, encoding="utf-8").read().replace("P1 · P2（共 2 条）", "P1 · P999（共 2 条）")
        io.open(p, "w", encoding="utf-8", newline="\n").write(s)
        code, out = run_lint("_family_members_lint.py", self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("P999", out)

    def test_family_members_accepts_dropped_list(self):
        """发布版把某些编号剔除后，只要 PITFALLS 里写了「未随发布」名单，声明就不算悬空。"""
        p = os.path.join(self.tmp, "task_cards", "memory", "PITFALLS.md")
        s = io.open(p, encoding="utf-8").read()
        s += "\n## 未随发布\n\n未随发布条目：P999（本机事实）\n"
        io.open(p, "w", encoding="utf-8", newline="\n").write(s)
        p2 = os.path.join(self.tmp, "domains", "experiences", "demo_family.md")
        s2 = io.open(p2, encoding="utf-8").read().replace("P1 · P2（共 2 条）", "P1 · P999（共 2 条）")
        io.open(p2, "w", encoding="utf-8", newline="\n").write(s2)
        code, out = run_lint("_family_members_lint.py", self.tmp)
        self.assertEqual(code, 0, out)

    # ── INDEX 交叉校验（并入能力 lint）────────────────────────
    def test_capability_index_mismatch_fails(self):
        p = os.path.join(self.tmp, "capabilities", "INDEX.md")
        s = io.open(p, encoding="utf-8").read().replace("| 1 |", "| 2 |")
        s = s.replace("| 演示 | 1 |", "| 演示 | 3 |")   # 片数写错
        io.open(p, "w", encoding="utf-8", newline="\n").write(s)
        code, out = run_lint("_capability_field_lint.py", self.tmp)
        self.assertEqual(code, 1, out)


    # ── 未绑定引用（审计 R1：probe.ts 调了没 import 的 noteCatchFail）──
    def test_unbound_refs_clean_passes(self):
        """GREEN：引用的名字有 import / 本文件定义 ⇒ 0 条。"""
        write(self.tmp, "runtime/defs.ts",
              "export const LIMIT = 3\n"
              "export type Rec = { id: string }\n"
              "export function helper(n: number): number { return n + LIMIT }\n")
        write(self.tmp, "runtime/main.ts",
              "import { helper, LIMIT } from './defs.ts'\n"
              "import type { Rec } from './defs.ts'\n"
              "export function run(r: Rec): number { return helper(r.id.length) + LIMIT }\n")
        code, out = run_lint("_unbound_refs_lint.py", self.tmp)
        self.assertEqual(code, 0, out)

    def test_unbound_refs_missing_import_fails(self):
        """RED：调了别处顶层定义、本文件没 import ⇒ 必须 FAIL（R1 原案）。"""
        write(self.tmp, "runtime/defs.ts",
              "export function noteCatchFail(where: string): void { void where }\n")
        write(self.tmp, "runtime/caller.ts",
              "export function go(): void { noteCatchFail('shadow:S1') }\n")
        code, out = run_lint("_unbound_refs_lint.py", self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("noteCatchFail", out)

    def test_unbound_refs_type_only_missing_import_fails(self):
        """RED：`import type` 名漏 import 同样算未绑定（probe.ts 的 WorkReportRecord 形态）。"""
        write(self.tmp, "runtime/defs.ts",
              "export interface WorkReportRecord { session: string }\n")
        write(self.tmp, "runtime/store.ts",
              "export const REPORTS = new Map<string, WorkReportRecord[]>()\n")
        code, out = run_lint("_unbound_refs_lint.py", self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("WorkReportRecord", out)

    def test_unbound_refs_ignores_comments_strings_properties(self):
        """噪音豁免：注释/字符串/模板字面量/正则/对象键/属性访问里的同名都不算引用。"""
        write(self.tmp, "runtime/defs.ts",
              "export function noteCatchFail(where: string): void { void where }\n")
        write(self.tmp, "runtime/noise.ts",
              "// noteCatchFail in a line comment\n"
              "/* noteCatchFail in a block comment */\n"
              "export const s = 'noteCatchFail in string'\n"
              "export const t = `noteCatchFail in template`\n"
              "export const re = /noteCatchFail/g\n"
              "export const obj = { noteCatchFail: 1 }\n"
              "export interface Shape { noteCatchFail?: number }\n"
              "export function g(o: Shape): number { return o.noteCatchFail ?? obj.noteCatchFail }\n")
        code, out = run_lint("_unbound_refs_lint.py", self.tmp)
        self.assertEqual(code, 0, out)

    def test_unbound_refs_allow_whitelist(self):
        """--allow 白名单：默认空（上面 RED 已证）；显式放行后 PASS。"""
        write(self.tmp, "runtime/defs.ts",
              "export function noteCatchFail(where: string): void { void where }\n")
        write(self.tmp, "runtime/caller.ts",
              "export function go(): void { noteCatchFail('x') }\n")
        code, out = run_lint("_unbound_refs_lint.py", self.tmp, ["--allow", "noteCatchFail"])
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
