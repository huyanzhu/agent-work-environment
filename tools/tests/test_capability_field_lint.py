#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""能力字段校验器 · `phases` 判据的隔离自测（先红后绿）。

被测：`tools/probes/_capability_field_lint.py`（只读 lint · 退出码 0 = 全过 / 1 = 有 FAIL）
契约：`workspaces/ai-os-public/NEXT.md` —— 「17/17 已补但校验器不认」
      + `task_cards/active/AI-OS-Adaptation/NEXT-SESSION-TODO-.md` §4.2

判据（`phases` 值域 = `S1-决策 / S2-实现 / S3-受阻 / S4-收口`）：
  T1 合法行内数组 `[S1-决策, S2-实现]`  ⇒ OK（退出码 0）
  T2 值域外取值 `[S1]`                  ⇒ FAIL 且报出文件名
  T3 缺 `phases` 字段                   ⇒ FAIL 且报出文件名
  T4 写成字符串（非 list）              ⇒ FAIL 且报出文件名
  T5 块式列表 `- S1-决策`（合法 list 形态）⇒ OK（与行内数组等价）
  T6 空列表 `[]`                        ⇒ FAIL（字段在但无数值 ⇒ 等于没声明）

片级化判据（试点 · D-056 · `parts:` 块 —— **有则严格、无则只 WARN**）：
   合法片块（2 片 · id/class/domain/label/one_line/sec 齐） ⇒ OK（退出码 0）
   `class` 值域外（如 `实战`）        ⇒ FAIL（class ∈ 决策/实现/收尾）
   `domain` 值域外（如 `美工`）       ⇒ FAIL（domain = 8 个词表领域 + `通用`）
   同一 id 出现在两个能力文件里       ⇒ FAIL（id 跨能力唯一）
   `one_line` 超 45 字                ⇒ FAIL
   `one_line` 无"做"类动词（写成说明句）⇒ FAIL
   `sec` 为空                         ⇒ FAIL
   `sec` 指向正文不存在的章节          ⇒ FAIL（sec 必须能核对）
   片数 1（少于 2）                   ⇒ FAIL（每能力 2–4 片）
   无 `parts`                        ⇒ 只 WARN（` 待补片`），⛔ 不 FAIL —— 向后兼容尚未补片的存量能力
   行内 `parts: [a, b]`              ⇒ FAIL（片表要能带 6 个字段）
   `domain: 通用`（注入范围标记） ⇒ OK（9 值域；矩阵单列、不占 24 格）

纪律：全部在 `scratch/_selftest_cap_lint` 隔离根内跑（⛔ 不碰真实 `capabilities/`）；
      不写 `task_cards/NEEDS-VOCAB.md` ⇒ 词表校验自动跳过，本用例只锁 `phases` 行为。
退出码：0 = 全通过；1 = 有失败（unittest 口径）。
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # tools/tests → 仓库根
LINT_PY = os.path.join(ROOT, "tools", "probes", "_capability_field_lint.py")

# ⚠️ 不用系统临时区（本机沙箱判其不可写 · 见 test_focus_card_probe.py 注）⇒ 落在工作区内并清理。
TMP = os.path.join(ROOT, "scratch", "_selftest_cap_lint")


def load_lint():
    """按文件路径加载被测模块（`_` 前缀不能直接 import）。"""
    spec = importlib.util.spec_from_file_location("capability_field_lint_under_test", LINT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LINT = load_lint()

# 其余四个必需字段一律齐备 ⇒ 任何 FAIL 都只能由 `phases` 引起（断言才隔离得住）。
FM = """---
name: alpha
intro: 测试用能力
axis_domain: [后端]
axis_help: [实现]
axis_concern: [正确性]
keywords:
  - 测试
{phases}---
正文
"""


def run_lint(root):
    """→ (退出码, stdout)。argv 与 stdout 都改写/重定向，跑完还原。"""
    argv = sys.argv
    sys.argv = ["_capability_field_lint.py", "--root", root.replace("\\", "/")]
    buf = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf):
            try:
                LINT.main()
            except SystemExit as exc:
                if isinstance(exc.code, int):
                    code = exc.code
                elif exc.code is not None:
                    code = 1
    finally:
        sys.argv = argv
    return code, buf.getvalue()


def lint_one(fname, phases_line):
    """建隔离根 + 单个能力文件 ⇒ 跑 lint ⇒ (退出码, stdout)。"""
    shutil.rmtree(TMP, ignore_errors=True)
    cap = os.path.join(TMP, "capabilities")
    os.makedirs(cap)
    with io.open(os.path.join(cap, fname), "w", encoding="utf-8") as fh:
        fh.write(FM.format(phases=phases_line))
    return run_lint(TMP)


class PhasesLintTest(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_t1_legal_inline_list_passes(self):
        """T1 合法行内数组 ⇒ 通过（退出码 0 · 该文件只 WARN —— 无 parts 是 待补片，不是 FAIL）。"""
        code, out = lint_one("good.md", "phases: [S1-决策, S2-实现]\n")
        self.assertEqual(code, 0, "合法 phases ⇒ 退出码必须 0，实际 %r\n%s" % (code, out))
        self.assertIn("WARN 1", out, "合法 phases 但无 parts ⇒ 只 WARN（P2 待补片）\n" + out)
        self.assertNotIn("FAIL 1", out, "合法 phases 不得判 FAIL\n" + out)

    def test_t2_out_of_domain_value_fails_with_filename(self):
        """T2 值域外 `[S1]` ⇒ FAIL + 文件名 + 指出是 phases 的问题。"""
        code, out = lint_one("bad-value.md", "phases: [S1]\n")
        self.assertEqual(code, 1, "值域外 phases ⇒ 退出码必须非 0，实际 %r\n%s" % (code, out))
        self.assertIn("bad-value.md", out, "FAIL 必须指出文件名\n" + out)
        self.assertIn("phases(值域外:S1)", out, "必须报出具体值域外取值\n" + out)
        self.assertIn("- bad-value.md", out, "文件名必须出现在 FAIL 明细里（不只是表格行）\n" + out)

    def test_t3_missing_phases_fails_with_filename(self):
        """T3 缺 `phases` ⇒ FAIL + 文件名。"""
        code, out = lint_one("missing.md", "")
        self.assertEqual(code, 1, "缺 phases ⇒ 退出码必须非 0，实际 %r\n%s" % (code, out))
        self.assertIn("missing.md", out, "FAIL 必须指出文件名\n" + out)
        self.assertIn("phases(缺失)", out, "必须报出 phases 缺失\n" + out)
        self.assertIn("- missing.md", out, "文件名必须出现在 FAIL 明细里\n" + out)

    def test_t4_string_instead_of_list_fails(self):
        """T4 `phases: S2-实现`（字符串而非 list）⇒ FAIL，且与"缺失"可区分。"""
        code, out = lint_one("string-form.md", "phases: S2-实现\n")
        self.assertEqual(code, 1, "字符串形态 ⇒ 退出码必须非 0，实际 %r\n%s" % (code, out))
        self.assertIn("string-form.md", out, "FAIL 必须指出文件名\n" + out)
        self.assertIn("phases(非list:字符串)", out, "必须指出是形态问题（非 list）\n" + out)
        self.assertNotIn("phases(缺失)", out, "形态问题不得被误报成缺失\n" + out)

    def test_t5_block_list_passes(self):
        """T5 块式 `- S1-决策`（合法 YAML list 形态）⇒ 通过（无 parts ⇒ 只 WARN，不 FAIL）。"""
        code, out = lint_one("block.md", "phases:\n  - S1-决策\n  - S4-收口\n")
        self.assertEqual(code, 0, "块式 list ⇒ 退出码必须 0，实际 %r\n%s" % (code, out))
        self.assertIn("WARN 1", out, "块式 list ⇒ 只 WARN（P2 待补片）\n" + out)
        self.assertNotIn("FAIL 1", out, "块式 list 不得判 FAIL\n" + out)

    def test_t6_empty_list_fails(self):
        """T6 `phases: []`（字段在但无数值 ⇒ 等于没声明）⇒ FAIL。"""
        code, out = lint_one("empty.md", "phases: []\n")
        self.assertEqual(code, 1, "空列表 ⇒ 退出码必须非 0，实际 %r\n%s" % (code, out))
        self.assertIn("empty.md", out, "FAIL 必须指出文件名\n" + out)
        self.assertIn("phases(空)", out, "必须报出列表为空\n" + out)


# 片级化用例的 frontmatter（`{parts}` 占位）· 其余字段齐备 ⇒ 任何 FAIL 只可能来自 parts
FM_PARTS = """---
name: alpha
intro: 测试用能力
axis_domain: [后端]
axis_help: [实现]
axis_concern: [正确性]
keywords:
  - 测试
phases: [S2-实现]
{parts}---
正文

### 1）基元：设计从 Token 开始
"""


def part(pid, cls="决策", dom="后端", label="测试片", ol="先定令牌再写样式",
         sec="三-1 · 基元：设计从 Token 开始"):
    """一片的六个字段（默认全部合法 ⇒ 改一个字段就能隔离出那条判据）。"""
    return {"id": pid, "class": cls, "domain": dom, "label": label,
            "one_line": ol, "sec": sec}


def parts_block(items):
    """list[dict] ⇒ `parts:` 块式 YAML（与真实能力文件同形态）。"""
    lines = ["parts:"]
    for it in items:
        lines.append("  - id: " + it["id"])
        lines.append("    class: " + it["class"])
        lines.append("    domain: " + it["domain"])
        lines.append("    label: " + it["label"])
        lines.append("    one_line: " + it["one_line"])
        lines.append("    sec: " + it["sec"])
    return "\n".join(lines) + "\n"


def two_parts(prefix="alpha"):
    """两片（合法下限）· id 前缀 = 文件名（`<能力名>#<短名>` 形态）。"""
    return [part(prefix + "#a"),
            part(prefix + "#b", cls="收尾", ol="逐条勾完检查清单再收口")]


class PartsLintTest(unittest.TestCase):
    """片级化（D-056）：有 parts ⇒ 严格校验；无 parts ⇒ 只 WARN（不判 FAIL）。"""

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def _run(self, files):
        """{文件名: 文件内容} ⇒ 隔离根内落盘 ⇒ (退出码, stdout)。"""
        shutil.rmtree(TMP, ignore_errors=True)
        cap = os.path.join(TMP, "capabilities")
        os.makedirs(cap)
        for fname, content in files.items():
            with io.open(os.path.join(cap, fname), "w", encoding="utf-8") as fh:
                fh.write(content)
        return run_lint(TMP)

    def _one(self, parts, fname="alpha.md"):
        return self._run({fname: FM_PARTS.format(parts=parts_block(parts))})

    def test_p1_valid_parts_pass(self):
        """ 合法片块 ⇒ 退出码 0 · 该文件 OK（有 parts 时严格校验也全过）。"""
        code, out = self._one(two_parts())
        self.assertEqual(code, 0, "合法片块 ⇒ 退出码必须 0，实际 %r\n%s" % (code, out))
        self.assertIn("OK 1", out, "合法片块 ⇒ 该文件必须判 OK\n" + out)
        self.assertIn("片: 2", out, "输出必须显示片数\n" + out)

    def test_p2_class_out_of_domain_fails(self):
        """ `class: 实战`（不在 决策/实现/收尾）⇒ FAIL。"""
        parts = two_parts()
        parts[0]["class"] = "实战"
        code, out = self._one(parts)
        self.assertEqual(code, 1, "class 值域外 ⇒ 退出码必须非 0，实际 %r\n%s" % (code, out))
        self.assertIn("parts(class值域外:alpha#a:实战)", out, "必须报出片 id + 非法 class\n" + out)

    def test_p3_domain_out_of_domain_fails(self):
        """ `domain: 美工`（不在 9 值：8 词表领域 + 通用）⇒ FAIL。"""
        parts = two_parts()
        parts[1]["domain"] = "美工"
        code, out = self._one(parts)
        self.assertEqual(code, 1, "domain 值域外 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("parts(domain值域外:alpha#b:美工)", out, "必须报出片 id + 非法 domain\n" + out)

    def test_p4_id_duplicated_across_capabilities_fails(self):
        """ 同一 id 出现在两个能力文件 ⇒ FAIL（id 跨能力唯一）。"""
        a = FM_PARTS.format(parts=parts_block(two_parts("alpha")))
        b = FM_PARTS.format(parts=parts_block([part("alpha#a"), part("beta#b")]))
        code, out = self._run({"alpha.md": a, "beta.md": b})
        self.assertEqual(code, 1, "id 跨能力重复 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("parts(id跨能力重复:alpha#a)", out, "必须指出重复的 id\n" + out)

    def test_p5_one_line_too_long_fails(self):
        """ `one_line` 超 45 字 ⇒ FAIL。"""
        parts = two_parts()
        parts[0]["one_line"] = "先" + "定" * 60
        code, out = self._one(parts)
        self.assertEqual(code, 1, "one_line 超长 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("parts(one_line超长:alpha#a:", out, "必须报出超长片 id\n" + out)

    def test_p6_one_line_without_action_verb_fails(self):
        """ `one_line` 写成说明句（无"做"类动词）⇒ FAIL。"""
        parts = two_parts()
        parts[0]["one_line"] = "这个能力是关于设计令牌的说明"
        code, out = self._one(parts)
        self.assertEqual(code, 1, "无动作词 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("parts(one_line无动作词:alpha#a)", out, "必须指出该写成祈使句\n" + out)

    def test_p7_empty_sec_fails(self):
        """ `sec` 为空 ⇒ FAIL。"""
        parts = two_parts()
        parts[1]["sec"] = ""
        code, out = self._one(parts)
        self.assertEqual(code, 1, "sec 空 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("parts(sec空:alpha#b)", out, "必须报出缺 sec 的片 id\n" + out)

    def test_p8_sec_not_in_body_fails(self):
        """ `sec` 指向正文不存在的章节 ⇒ FAIL（sec 必须能核对）。"""
        parts = two_parts()
        parts[0]["sec"] = "三-9 · 不存在的章节"
        code, out = self._one(parts)
        self.assertEqual(code, 1, "sec 不存在 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("parts(sec不存在:alpha#a:不存在的章节)", out, "必须报出核对失败的片段\n" + out)

    def test_p9_part_count_out_of_range_fails(self):
        """ 片数 1（少于 2）⇒ FAIL（每能力 2–4 片）。"""
        code, out = self._one([part("alpha#a")])
        self.assertEqual(code, 1, "片数 1 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("parts(片数:1,应2-4)", out, "必须报出片数与应有区间\n" + out)

    def test_p10_no_parts_warns_not_fails(self):
        """ 无 parts ⇒ 只 WARN（待补片），退出码 0（向后兼容存量能力）。"""
        code, out = self._run({"noparts.md": FM.format(phases="phases: [S1-决策]\n")})
        self.assertEqual(code, 0, "无 parts ⇒ 不得判 FAIL，实际 %r\n%s" % (code, out))
        self.assertIn("WARN 1", out, "无 parts ⇒ 该文件判 WARN\n" + out)
        self.assertIn("待补片", out, "WARN 必须说明原因\n" + out)
        self.assertNotIn("FAIL 1", out, "无 parts 不得判 FAIL\n" + out)


    def test_p11_inline_parts_form_fails(self):
        """ `parts` 写成行内 `[a, b]`（不是块式 list-of-map）⇒ FAIL（片表要能带 6 个字段）。"""
        content = FM.format(phases="phases: [S1-决策]\nparts: [a, b]\n")
        code, out = self._run({"inline.md": content})
        self.assertEqual(code, 1, "行内形态 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("parts(非块式列表)", out, "必须指出形态问题\n" + out)

    def test_p12_universal_domain_passes(self):
        """ `domain: 通用`（注入范围标记）⇒ 通过（9 值域；统计单列不占领域格）。"""
        parts = two_parts()
        parts[0]["domain"] = "通用"
        parts[1]["domain"] = "通用"
        code, out = self._one(parts)
        self.assertEqual(code, 0, "通用域 ⇒ 退出码必须 0，实际 %r\n%s" % (code, out))
        self.assertIn("OK 1", out, "通用域片块必须判 OK\n" + out)
        self.assertIn("片: 2", out, "输出必须显示片数\n" + out)


# ── 格能力装配表（`capabilities/CELLS.md`）──────────────────────────────
#   判据：引用片必须存在 · 片总数 ≤3 · 通用片 ≤2 · 不跨类引用 · 领域片同域 · cell id = <domain>/<class>。
#   隔离根内既放能力文件（片索引来源）也放 CELLS.md；⛔ 不碰真实 capabilities/。
def cells_md(rows):
    """装配表 + 第二个表格块（缺口表）—— 后者**不得**被当成装配行（只读第一个表块）。"""
    head = [
        "# 格能力装配表",
        "",
        "| cell id | class | domain | 领域片（id 列表） | 引用的通用片（≤2，id 列表） | 这格什么时候用（一句） |",
        "|---|---|---|---|---|---|",
    ]
    body = ["| %s | %s | %s | %s | %s | %s |" % r for r in rows]
    tail = ["", "## 缺口", "", "| 缺口格 | 为什么 |", "|---|---|", "| 后端/决策 | 没片 |", ""]
    return "\n".join(head + body + tail)


class CellsLintTest(unittest.TestCase):
    """装配表校验：机械判据全过 ⇒ OK；任一违例 ⇒ FAIL（退出码 1）。"""

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def _run(self, rows, beta_parts=None):
        shutil.rmtree(TMP, ignore_errors=True)
        cap = os.path.join(TMP, "capabilities")
        os.makedirs(cap)
        alpha = FM_PARTS.format(parts=parts_block(two_parts("alpha")))
        if beta_parts is None:
            beta_parts = [part("beta#u", dom="通用"),
                          part("beta#v", cls="收尾", dom="通用", ol="逐条勾完检查清单再收口")]
        beta = FM_PARTS.format(parts=parts_block(beta_parts))
        with io.open(os.path.join(cap, "alpha.md"), "w", encoding="utf-8") as fh:
            fh.write(alpha)
        with io.open(os.path.join(cap, "beta.md"), "w", encoding="utf-8") as fh:
            fh.write(beta)
        with io.open(os.path.join(cap, "CELLS.md"), "w", encoding="utf-8") as fh:
            fh.write(cells_md(rows))
        return run_lint(TMP)

    def test_c1_valid_cells_pass(self):
        """ 合法装配表 ⇒ 退出码 0 · 2 格 0 问题 · 缺口表不被当成装配行 · CELLS.md 不进逐文件校验。"""
        code, out = self._run([
            ("后端/决策", "决策", "后端", "alpha#a", "beta#u", "改后端接口前先定判据"),
            ("后端/收尾", "收尾", "后端", "alpha#b", "beta#v", "后端收口时"),
        ])
        self.assertEqual(code, 0, "合法装配表 ⇒ 退出码必须 0，实际 %r\n%s" % (code, out))
        self.assertIn("文件数 2", out, "CELLS.md 不是能力文件（⛔ 不进逐文件校验）\n" + out)
        self.assertIn("CELLS.md 装配表（A1 · 阶段 x 领域）：2 格 · 问题 0", out, "缺口表不得被当成装配行\n" + out)

    def test_c2_unknown_part_id_fails(self):
        """ 引用了不存在的片 id ⇒ FAIL。"""
        code, out = self._run([
            ("后端/决策", "决策", "后端", "alpha#a", "alpha#nope", "x"),
        ])
        self.assertEqual(code, 1, "不存在的片 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("cells(片不存在:后端/决策:alpha#nope)", out, "必须报出缺失的片 id\n" + out)

    def test_c3_part_total_over_three_fails(self):
        """ 格内片总数 > 3 ⇒ FAIL（领域片 + 通用片一起算）。"""
        code, out = self._run([
            ("后端/决策", "决策", "后端", "alpha#a, alpha#b", "beta#u, beta#v", "x"),
        ])
        self.assertEqual(code, 1, "片总数超 3 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("cells(片总数超3:后端/决策:4)", out, "必须报出格与片数\n" + out)

    def test_c4_universal_over_two_fails(self):
        """ 通用片 > 2 ⇒ FAIL（不能把 13 个决策通用片全塞进一格）。"""
        beta = [part("beta#u", dom="通用"), part("beta#v", dom="通用"), part("beta#w", dom="通用")]
        code, out = self._run([
            ("后端/决策", "决策", "后端", "alpha#a", "beta#u, beta#v, beta#w", "x"),
        ], beta_parts=beta)
        self.assertEqual(code, 1, "通用片超 2 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("cells(通用片超2:后端/决策:3)", out, "必须报出通用片超限\n" + out)

    def test_c5_cross_class_reference_fails(self):
        """ 跨类引用（收尾片塞进决策格）⇒ FAIL。"""
        code, out = self._run([
            ("后端/决策", "决策", "后端", "alpha#b", "-", "x"),
        ])
        self.assertEqual(code, 1, "跨类引用 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("cells(跨类引用:后端/决策:alpha#b:收尾)", out, "必须指出片的 class 与格不符\n" + out)

    def test_c6_domain_part_domain_mismatch_fails(self):
        """ 领域片的 domain 与格的 domain 不符 ⇒ FAIL。"""
        code, out = self._run([
            ("前端/决策", "决策", "前端", "alpha#a", "-", "x"),
        ])
        self.assertEqual(code, 1, "领域片不同域 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("cells(领域片domain不符:前端/决策:alpha#a:后端)", out, "必须报出片所属域\n" + out)

    def test_c7_cell_id_must_match_class_and_domain(self):
        """ cell id ≠ `<domain>/<class>` ⇒ FAIL（runtime 的探针键同形）。"""
        code, out = self._run([
            ("后端/实现", "决策", "后端", "alpha#a", "-", "x"),
        ])
        self.assertEqual(code, 1, "cell id 与两列不一致 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("cells(cell id与class/domain不符:后端/实现)", out, "必须报出 id 形态问题\n" + out)

    def test_c8_duplicate_cell_id_fails(self):
        """ 同一 cell id 出现两次 ⇒ FAIL。"""
        code, out = self._run([
            ("后端/决策", "决策", "后端", "alpha#a", "-", "x"),
            ("后端/决策", "决策", "后端", "alpha#a", "-", "y"),
        ])
        self.assertEqual(code, 1, "cell id 重复 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("cells(cell id重复:后端/决策)", out, "必须报出重复的 cell id\n" + out)

    def test_c9_missing_header_fails(self):
        """ 没有 6 列表头 ⇒ FAIL（runtime 靠同一张表取片，写坏 = 那格静默消失）。"""
        shutil.rmtree(TMP, ignore_errors=True)
        cap = os.path.join(TMP, "capabilities")
        os.makedirs(cap)
        with io.open(os.path.join(cap, "alpha.md"), "w", encoding="utf-8") as fh:
            fh.write(FM_PARTS.format(parts=parts_block(two_parts("alpha"))))
        with io.open(os.path.join(cap, "CELLS.md"), "w", encoding="utf-8") as fh:
            fh.write("# 空壳\n\n没有表格\n")
        code, out = run_lint(TMP)
        self.assertEqual(code, 1, "缺表头 ⇒ 退出码必须非 0\n" + out)
        self.assertIn("cells(缺表头)", out, "必须报出缺表头\n" + out)
        self.assertIn("cells(0行)", out, "必须报出 0 行\n" + out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
