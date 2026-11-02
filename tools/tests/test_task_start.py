# -*- coding: utf-8 -*-
"""test_task_start.py — 「开工自检」回归测试（审计 /）

被测行为（`tools/task_start.py`）：
  · 发布物形态（根有 `.aios-sample/`、**没有** `.aios/`）⇒ 输出**末尾追加**一段开工自检，
    含可复制的初始化命令（Windows + POSIX）与「注入不会发生」的结论。
  · 已初始化（`.aios/` 存在）⇒ 输出里**不含**该提示（零噪声）。
  · 半初始化（`.aios/` 存在，但 `inject_probe.json` 缺失 / 非 JSON / `session` 为空）
    ⇒ 提示「注入总闸未就绪」，并给出可验证的判据（`session` 非空）。

纪律：
  ✅ 全部在**普通临时目录**里造最小树（不碰真实 `.aios/` / `.aios-sample/`）。
  ⛔ 不用 `tempfile.mkdtemp`：它建 0o700 目录（本机沙箱下不可写 · /）
     ⇒ 用工作区内的普通目录（同 `tools/tests/test_task_card.py` 的 setUp 做法）。
"""
import io
import os
import shutil
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import task_start as T  # noqa: E402

#: 提示必须命中的关键字（只挑语义锚点，⛔ 不把整段逐字钉死 —— 文案可再打磨）
HINT_REQUIRED = ("aios-sample", "注入不会发生")
#: 提示块行数上限（任务书：中文、≤6 行）
HINT_MAX_LINES = 6


class _Stdout(io.StringIO):
    """`main()` 会读 `sys.stdout.encoding` ⇒ 给它一个 utf-8 编码，走**原有分支**。

    否则 StringIO 没有 `.encoding` ⇒ 会把"编码探测"当成被测行为的一部分（噪声）。
    """

    encoding = "utf-8"


class TaskStartSelfCheckTest(unittest.TestCase):
    def setUp(self):
        # ⚠️ 不用 tempfile.mkdtemp：它建 0o700 目录（本机沙箱下不可写 · /）⇒ 用工作区普通目录
        self.tmp = os.path.join(ROOT, "work", "_selftest_task_start")
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.makedirs(self.tmp)
        self._saved_root = T.ROOT

    def tearDown(self):
        T.ROOT = self._saved_root
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── 造场景 ───────────────────────────────────────────────────────────
    def _make_sample(self):
        """发布物形态：只有 `.aios-sample/`（5 份开关 + README 的目录骨架即可）。"""
        d = os.path.join(self.tmp, T.SAMPLE_DIR)
        os.makedirs(d)
        with io.open(os.path.join(d, "inject_probe.json"), "w", encoding="utf-8", newline="\n") as f:
            f.write('{"enabled": true, "session": "*"}\n')
        with io.open(os.path.join(d, "README.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# .aios-sample/\n")
        return d

    def _make_aios(self):
        """已初始化：`.aios/` 存在（带注入总闸，贴近真实形态）。"""
        d = os.path.join(self.tmp, T.AIOS_DIR)
        os.makedirs(d, exist_ok=True)
        with io.open(os.path.join(d, "inject_probe.json"), "w", encoding="utf-8", newline="\n") as f:
            f.write('{"enabled": true, "session": "*"}\n')
        return d

    def _run_main(self, query=None, patch_material=False):
        """在隔离根上跑 `T.main()`，返回 (exit_code, stdout 全文)。"""
        T.ROOT = self.tmp
        argv = ["task_start.py"] + (list(query) if query else [])
        buf = _Stdout()
        patches = [mock.patch.object(sys, "stdout", buf),
                   mock.patch.object(sys, "argv", argv)]
        if patch_material:  # 材料发现依赖真实语料树 ⇒ 本组用例只验"追加位置"，不重测 R4
            patches.append(mock.patch.object(T, "material_text", lambda *_a, **_kw: ""))
        for p in patches:
            p.start()
        try:
            code = T.main()
        finally:
            for p in reversed(patches):
                p.stop()
        return code, buf.getvalue()

    # ── 用例 1：发布物形态 ⇒ 必须提示 ─────────────────────────────────────
    def test_release_shape_warns_missing_aios(self):
        self._make_sample()
        self.assertFalse(os.path.exists(os.path.join(self.tmp, T.AIOS_DIR)))

        code, out = self._run_main()

        self.assertEqual(code, 0, "自检只是提示 ⇒ ⛔ 不得改退出码：\n" + out)
        for kw in HINT_REQUIRED:
            self.assertIn(kw, out, "发布物形态（有 .aios-sample/ 无 .aios/）必须提示 `%s`：\n%s"
                          % (kw, out))

        # 两条可直接复制的初始化命令（Windows + POSIX）
        self.assertIn("xcopy /E /I .aios-sample .aios", out, "缺 Windows 初始化命令：\n" + out)
        self.assertIn("cp -r .aios-sample .aios", out, "缺 POSIX 初始化命令：\n" + out)
        # 判据：初始化并重启后会出现【AI-OS · 决策 · …能力】
        self.assertIn("初始化并重启后", out, "缺「怎么判断已生效」的判据：\n" + out)
        self.assertIn("【AI-OS · 决策 · …能力】", out, "判据里要给出注入成功的可见标志：\n" + out)

        # 位置：追加在**末尾**（⛔ 不插进既有输出中间）
        hint = T.selfcheck_text(self.tmp)
        self.assertTrue(hint, "selfcheck_text() 在发布物形态下不得返回空")
        self.assertTrue(out.rstrip("\n").endswith(hint.rstrip("\n")),
                        "开工自检必须追加在 stdout **末尾**：\n" + out[-400:])
        # 体积：提示块 ≤6 行（任务书口径）
        self.assertLessEqual(len(hint.splitlines()), HINT_MAX_LINES,
                             "提示块必须 ≤%d 行：\n%s" % (HINT_MAX_LINES, hint))
        # 打印串必须 GBK 可编码（本机中文终端 / 旧控制台）
        hint.encode("gbk")

    # ── 用例 2：已初始化（`.aios/` 存在）⇒ 零提示 ────────────────────────
    def test_initialized_repo_has_no_hint(self):
        self._make_sample()
        self._make_aios()

        code, out = self._run_main()

        self.assertEqual(code, 0, out)
        for kw in HINT_REQUIRED + ("xcopy", "cp -r .aios-sample"):
            self.assertNotIn(kw, out, "`.aios/` 已存在 ⇒ ⛔ 不得再提示 `%s`：\n%s" % (kw, out))
        self.assertEqual(T.selfcheck_text(self.tmp), "", "已初始化 ⇒ selfcheck_text() 必须为空串")

    # ── 用例 3：半初始化（`.aios/` 在，但注入总闸未就绪）⇒ 必须提示 ────────
    def _make_partial(self, payload="__missing__"):
        """`.aios/` 已建，但注入总闸缺失 / 不可用（payload=None ⇒ 写非法 JSON）。"""
        d = os.path.join(self.tmp, T.AIOS_DIR)
        os.makedirs(d, exist_ok=True)
        if payload == "__missing__":
            return d
        raw = payload if isinstance(payload, str) else '{"enabled": true}\n'
        with io.open(os.path.join(d, T.PROBE_FILE), "w", encoding="utf-8", newline="\n") as f:
            f.write(raw)
        return d

    def _assert_partial_hint(self, out):
        hint = T.selfcheck_text(self.tmp)
        self.assertTrue(hint, "半初始化（.aios/ 在、总闸未就绪）必须提示")
        self.assertIn("inject_probe.json", hint, "提示必须点名注入总闸文件：\n" + hint)
        self.assertIn("session", hint, "提示必须给出可验证判据（session 非空）：\n" + hint)
        self.assertNotIn("注入不会发生（外层门", hint, "半初始化不得复用「没有 .aios/」文案：\n" + hint)
        self.assertLessEqual(len(hint.splitlines()), HINT_MAX_LINES,
                             "提示块必须 ≤%d 行：\n%s" % (HINT_MAX_LINES, hint))
        hint.encode("gbk")  # 本机中文终端
        self.assertTrue(out.rstrip("\n").endswith(hint.rstrip("\n")),
                        "半初始化自检必须追加在 stdout **末尾**：\n" + out[-400:])

    def test_partial_aios_without_probe_warns(self):
        self._make_sample()
        self._make_partial()  # `.aios/` 建了，但没放 inject_probe.json

        code, out = self._run_main()

        self.assertEqual(code, 0, "自检只是提示 ⇒ ⛔ 不得改退出码：\n" + out)
        self._assert_partial_hint(out)

    def test_partial_aios_probe_without_session_warns(self):
        self._make_sample()
        self._make_partial('{"enabled": true}\n')  # 有文件，但没有 session

        code, out = self._run_main()

        self.assertEqual(code, 0, out)
        self._assert_partial_hint(out)

    def test_partial_aios_malformed_probe_warns(self):
        self._make_sample()
        self._make_partial("{not json")  # 解析失败也当未就绪

        code, out = self._run_main()

        self.assertEqual(code, 0, out)
        self._assert_partial_hint(out)

    def test_partial_aios_empty_session_warns(self):
        self._make_sample()
        self._make_partial('{"enabled": true, "session": "   "}\n')

        code, out = self._run_main()

        self.assertEqual(code, 0, out)
        self._assert_partial_hint(out)

    # ── 用例 4：带任务描述（材料发现分支）⇒ 提示同样只在末尾 ───────────────
    def test_hint_appended_in_material_branch(self):
        self._make_sample()

        code, out = self._run_main(["改文档"], patch_material=True)

        self.assertEqual(code, 0, out)
        self.assertIn("--- 材料发现", out, "前置输出形态不得变：\n" + out)
        hint = T.selfcheck_text(self.tmp)
        self.assertTrue(out.rstrip("\n").endswith(hint.rstrip("\n")),
                        "材料发现分支的自检也必须追加在末尾：\n" + out[-400:])
        self.assertLess(out.index("来源与消费语义"), out.index("aios-sample"),
                        "自检不得插到既有输出中间（应在最后的语义行之后）")

    # ── 用例 4：既无 `.aios-sample/` 也无 `.aios/`（普通仓 / 私仓形态）⇒ 零提示 ──
    def test_plain_repo_has_no_hint(self):
        # 私仓本身就是这样：`.aios/` 在、`.aios-sample/` 不在；这里连 `.aios/` 都没有
        code, out = self._run_main()
        self.assertEqual(code, 0, out)
        self.assertNotIn("aios-sample", out, "没有 `.aios-sample/` ⇒ ⛔ 不得误报：\n" + out)


if __name__ == "__main__":
    unittest.main()
