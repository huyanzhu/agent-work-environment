# -*- coding: utf-8 -*-
"""test_task_card.py — 任务卡机制的**回归测试**（对应 /// 的「修机制」）

跑法：python -m unittest discover -s tools/tests -p "test_task_card.py" -v
纪律：✅ 全部在**临时目录**里造卡（不碰真实 task_cards/active）。
"""
import datetime
import io
import os
import re
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import task_card as T  # noqa: E402

# 🔴 `claimHint` 缺省（= off）时 claim 的**改前快照** —— 改动前用同一张临时卡
#: （`demo-project/TASK-20260101-900` · session 固定 `sess-me`）实跑捕获，逐字钉死 A 组对照。
#: ⚠️ 只替换 `<TASK-ID>` 用于其它 id 的同类用例；其它字符⛔ 一个都不许改。
CLAIM_STDOUT_OFF_SNAPSHOT = (
    "[task_card] claimed: demo-project/TASK-20260101-900  State: Planning -> Executing  "
    "(task_cards/active/demo-project/TASK-20260101-900.md)\n"
    "\n"
    "  \U0001F4CC Event Log 已追加留痕（**外置**：同级同名 `.log` · 含 session id ⇒ 占用可追溯）\n"
    "  \u2139\ufe0f 该卡刚被改写 ⇒ 本轮若要继续编辑它，请**先重读**（否则工具会报 "
    "`file changed since it was read`）\n"
)


class TaskCardMechanismTest(unittest.TestCase):
    def setUp(self):
        # ⚠️ 不用 tempfile.mkdtemp：它建 0o700 目录（本机沙箱下不可写 · /）⇒ 用工作区内普通目录
        self.tmp = os.path.join(ROOT, "work", "_selftest_task_card_tmp")
        shutil.rmtree(self.tmp, ignore_errors=True)
        cards = os.path.join(self.tmp, "task_cards")
        self.active = os.path.join(cards, "active")
        os.makedirs(self.active)
        tpl = os.path.join(cards, "_TASK_CARD_template.md")
        shutil.copyfile(os.path.join(ROOT, "task_cards", "_TASK_CARD_template.md"), tpl)
        tpl2 = os.path.join(cards, "_TASK_CARD_template.v2.md")
        src2 = os.path.join(ROOT, "task_cards", "_TASK_CARD_template.v2.md")
        if os.path.isfile(src2):  # v2 模板尚未落地时（RED 阶段）保持缺失 ⇒ 用例按"模板缺失"报红
            shutil.copyfile(src2, tpl2)
        tpl3 = os.path.join(cards, "_TASK_CARD_template.v3.md")
        src3 = os.path.join(ROOT, "task_cards", "_TASK_CARD_template.v3.md")
        if os.path.isfile(src3):  # v3 尚未落地时同样保持缺失 ⇒ 用例按"模板缺失"报红
            shutil.copyfile(src3, tpl3)
        # v4（单字段）已是**缺省**模板 ⇒ 必须像 v1 一样复制进临时根
        tpl4 = os.path.join(cards, "_TASK_CARD_template.v4.md")
        src4 = os.path.join(ROOT, "task_cards", "_TASK_CARD_template.v4.md")
        if os.path.isfile(src4):  # v4 缺失 ⇒ 缺省建卡用例按"模板缺失"报红
            shutil.copyfile(src4, tpl4)
        self._saved = (T.ROOT, T.CARDS_DIR, T.ACTIVE_DIR, T.ARCHIVE_DIR, T.TEMPLATE, T._session_id)
        self._saved_v2 = getattr(T, "TEMPLATE_V2", None)
        self._saved_v3 = getattr(T, "TEMPLATE_V3", None)
        self._saved_v4 = getattr(T, "TEMPLATE_V4", None)
        self._saved_probe = getattr(T, "PROBE_LOG", None)
        self._env_saved = os.environ.pop("AIOS_CARD_TEMPLATE", None)
        T.ROOT, T.CARDS_DIR = self.tmp, cards
        T.ACTIVE_DIR = self.active
        T.ARCHIVE_DIR = os.path.join(cards, "archive")
        os.makedirs(T.ARCHIVE_DIR, exist_ok=True)
        T.TEMPLATE = tpl
        T.TEMPLATE_V2 = tpl2
        T.TEMPLATE_V3 = tpl3
        T.TEMPLATE_V4 = tpl4
        T.PROBE_LOG = os.path.join(self.tmp, ".aios", "_aios-activation.probe.log")
        T._session_id = lambda: "sess-me"

    def tearDown(self):
        (T.ROOT, T.CARDS_DIR, T.ACTIVE_DIR, T.ARCHIVE_DIR, T.TEMPLATE, T._session_id) = self._saved
        if self._saved_v2 is None:
            if hasattr(T, "TEMPLATE_V2"):
                del T.TEMPLATE_V2
        else:
            T.TEMPLATE_V2 = self._saved_v2
        if self._saved_v3 is None:
            if hasattr(T, "TEMPLATE_V3"):
                del T.TEMPLATE_V3
        else:
            T.TEMPLATE_V3 = self._saved_v3
        if self._saved_v4 is None:
            if hasattr(T, "TEMPLATE_V4"):
                del T.TEMPLATE_V4
        else:
            T.TEMPLATE_V4 = self._saved_v4
        if self._saved_probe is None:
            if hasattr(T, "PROBE_LOG"):
                del T.PROBE_LOG
        else:
            T.PROBE_LOG = self._saved_probe
        if self._env_saved is None:
            os.environ.pop("AIOS_CARD_TEMPLATE", None)
        else:
            os.environ["AIOS_CARD_TEMPLATE"] = self._env_saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, fn, *a, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = fn(*a, **kw)
        return code, buf.getvalue()

    def _card(self, project, task_id, state, title=None, goal=None):
        d = os.path.join(self.active, project) if project else self.active
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, task_id + ".md")
        body = "# TASK_CARD" + (" — " + title if title else "") + "\n\n"
        if goal:
            body += "## Goal\n\n" + goal + "\n\n"
        body += ("## Current Status\n\n```\nState:         %s\n"
                 "Current Step:  x\nNext Action:   y\n```\n" % state)
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(body)
        return p

    def _write_cfg(self, text, bom=False):
        """写临时 `.aios/cap-cells.json`（`bom=True` ⇒ 带 BOM，复现中文 Windows 手写配置）。"""
        d = os.path.join(self.tmp, ".aios")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "cap-cells.json")
        with io.open(p, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
            f.write(text)
        return p

    def _cells_fixture(self):
        """🔴 域合并后**不再需要 CELLS 表**（一域一文件，提示按域能力）。

        保留本方法为空壳：调用点还在（历史 A/B 用例的结构），但 claim 提示已不看 CELLS。
        真实 `capabilities/CELLS.md` 已归档到 `capabilities/_archive/`。
        """
        os.makedirs(os.path.join(self.tmp, "capabilities"), exist_ok=True)

    # ── ：create 出来的卡必须能直接 claim ──────────────────────────────
    def test_create_then_claim_works(self):
        code, out = self._run(T.cmd_create, "机制测试卡", "demo-project")
        self.assertEqual(code, 0, out)
        task_id = out.split("created:")[1].split()[0]
        path = os.path.join(self.active, "demo-project", task_id + ".md")
        with io.open(path, encoding="utf-8") as f:
            raw = T._state_value(T._state_raw(f.read()))
        self.assertEqual(raw, "Planning", "P61：create 后 State 必须是 Planning（不再停在 Created）")
        code, out = self._run(T.cmd_claim, "demo-project/" + task_id)
        self.assertEqual(code, 0, "P61：新建卡必须能直接 claim（原缺陷：State=Created 被拒）\n" + out)

    # ── 兼容：老卡停在 Created 也能 claim ─────────────────────────────
    def test_claim_accepts_legacy_created(self):
        self._card("demo-project", "TASK-20260101-001", "Created")
        code, out = self._run(T.cmd_claim, "demo-project/TASK-20260101-001")
        self.assertEqual(code, 0, "P61：老卡 State=Created 应可 claim（向后兼容）\n" + out)

    # ── ：重名报错要能直接照抄命令 ─────────────────────────────────────
    def test_duplicate_id_error_gives_command(self):
        self._card("demo-project", "TASK-20260101-002", "Planning")
        self._card("AI-OS-Adaptation", "TASK-20260101-002", "Planning")
        code, out = self._run(T.cmd_claim, "TASK-20260101-002")
        self.assertEqual(code, 1)
        self.assertIn("重名", out)
        self.assertIn("claim ", out, "P1：错误里要带可复制的 claim 命令\n" + out)
        self.assertTrue("AI-OS-Adaptation/TASK-20260101-002" in out or "demo-project/TASK-20260101-002" in out)

    # ── 缓解：claim 输出必须提醒「先重读」 ───────────────────────────
    def test_claim_hints_reread(self):
        self._card("demo-project", "TASK-20260101-003", "Planning")
        code, out = self._run(T.cmd_claim, "demo-project/TASK-20260101-003")
        self.assertEqual(code, 0)
        self.assertIn("先重读", out, "P52：claim 后同回合 edit 会报 stale ⇒ 输出里必须提醒先重读\n" + out)

    # ── 回归：非占用者不能 release（应已被拒绝） ─────────────────────
    def test_release_by_other_session_refused(self):
        p = self._card("demo-project", "TASK-20260101-004", "Executing")
        log = p[:-3] + ".log"
        with io.open(log, "w", encoding="utf-8") as f:
            f.write("| 01:00 | Executing | claim 占用（session: sess-other） | Worker |\n")
        code, out = self._run(T.cmd_release, "demo-project/TASK-20260101-004", state="Parked")
        self.assertEqual(code, 1, "P27：非占用者 release 必须被拒\n" + out)
        self.assertIn("takeover", out, "拒绝时要给出显式接管命令")


    # ── 新增：`--project=X`（等号）与 `--project X`（空格）等价 ──────
    #    故障：旧解析只按整 token 找 `--project` ⇒ 等号写法把参数并进标题、卡落 active/ 顶层。
    def test_main_create_equals_project(self):
        code, out = self._run(T.main, ["task_card.py", "create", "等号形式建卡",
                                       "--project=demo-project"])
        self.assertEqual(code, 0, out)
        task_id = out.split("created:")[1].split()[0]
        path = os.path.join(self.active, "demo-project", task_id + ".md")
        self.assertTrue(os.path.isfile(path), "`--project=X` 必须落到项目文件夹：\n" + out)
        self.assertEqual([n for n in os.listdir(self.active) if n.endswith(".md")], [],
                         "⛔ 不得在 active/ 顶层留下垃圾卡")
        with io.open(path, encoding="utf-8") as f:
            head = f.readline()
        self.assertIn("等号形式建卡", head)
        self.assertNotIn("--project", head, "⛔ 参数不得并进标题：\n" + head)

    def test_main_create_space_project_unchanged(self):
        code, out = self._run(T.main, ["task_card.py", "create", "空格形式建卡",
                                       "--project", "demo-project"])
        self.assertEqual(code, 0, out)
        task_id = out.split("created:")[1].split()[0]
        path = os.path.join(self.active, "demo-project", task_id + ".md")
        self.assertTrue(os.path.isfile(path), "既有空格写法行为不得变：\n" + out)
        with io.open(path, encoding="utf-8") as f:
            head = f.readline()
        self.assertIn("空格形式建卡", head)
        self.assertNotIn("--project", head, "⛔ 参数不得并进标题：\n" + head)

    # ── `--project` 路径越界 ─────────────────────────
    #    已确认过两种形态都能写到 active/ 之外：
    #      `--project=../../x`  ⇒ 上跳；`--project=D:/evil` ⇒ 绝对路径直接替换基目录
    #    ⇒ 现在 `--project` 只按「单段安全目录名」接受；下面把它锁死。
    def test_main_create_rejects_project_path_traversal(self):
        parent = os.path.dirname(self.active)
        before = sorted(os.listdir(parent))
        bad = ["../../escape", "..", "D:/evil", "D:\\evil", "a/b", "a\\b",
               " evil", "evil.", "a*b", "CON:", "a:b"]
        for name in bad:
            code, out = self._run(T.main, ["task_card.py", "create", "越界试探",
                                           "--project=" + name])
            self.assertNotEqual(code, 0, "⛔ 应拒绝 `--project=%s`：\n%s" % (name, out))
            self.assertIn("参数错误", out, out)
        # 关键：active/ 之外不得出现新目录
        self.assertEqual(sorted(os.listdir(parent)), before,
                         "⛔ 越界拒绝后⛔ 不得在 active/ 之外留下目录")

    def test_main_create_accepts_safe_project_name(self):
        for name in ["回归测试", "demo-project", "a_b-c.d"]:
            code, out = self._run(T.main, ["task_card.py", "create", "安全项目名",
                                           "--project=" + name])
            self.assertEqual(code, 0, "合法项目名应通过（%s）：\n%s" % (name, out))
            self.assertTrue(os.path.isdir(os.path.join(self.active, name)), out)

    # ── 🔴 路径形态必须**按父目录精确匹配** ────────────────
    #    故障：`验证/` 与 `设备名验证/` 各有同 ID 卡时，旧实现用后缀匹配 ⇒ 路径写法必然歧义。
    def test_find_card_path_form_exact_parent(self):
        self._card("验证", "TASK-20260101-001", "Planning")
        self._card("设备名验证", "TASK-20260101-001", "Planning")
        path, err = T._find_card("验证/TASK-20260101-001")
        self.assertIsNone(err, err)
        self.assertEqual(os.path.basename(path), "TASK-20260101-001.md")
        self.assertEqual(os.path.basename(os.path.dirname(path)), "验证",
                         "⛔ 路径形态必须命中精确父目录，不能后缀匹配到 `设备名验证/`")
        # 反向也要对
        path2, err2 = T._find_card("设备名验证/TASK-20260101-001")
        self.assertIsNone(err2, err2)
        self.assertEqual(os.path.basename(os.path.dirname(path2)), "设备名验证")
        # 裸 ID 仍应拒绝（跨项目重名）
        p3, err3 = T._find_card("TASK-20260101-001")
        self.assertIsNone(p3)
        self.assertIn("重名", err3)

    # ── 🔴 ID 抢占冲突时必须**换号**，⛔ 不覆盖已有卡 ──────────────────
    def test_create_does_not_overwrite_existing_id(self):
        proj = os.path.join(self.active, "并发")
        os.makedirs(proj, exist_ok=True)
        nxt = T._next_id(project="并发")
        sentinel = os.path.join(proj, nxt + ".md")
        with io.open(sentinel, "w", encoding="utf-8") as f:
            f.write("SENTINEL-不要覆盖")
        code, out = self._run(T.main, ["task_card.py", "create", "并发建卡", "--project=并发"])
        self.assertEqual(code, 0, out)
        with io.open(sentinel, encoding="utf-8") as f:
            self.assertEqual(f.read(), "SENTINEL-不要覆盖",
                             "⛔ 已存在的卡被覆盖了（原子创建失效）")
        new_id = out.split("created:")[1].split()[0]
        self.assertNotEqual(new_id, nxt, "⛔ 冲突时应换号")
        self.assertTrue(os.path.isfile(os.path.join(proj, new_id + ".md")), out)

    def test_main_create_project_without_value_refused(self):
        code, out = self._run(T.main, ["task_card.py", "create", "缺值卡", "--project"])
        self.assertEqual(code, 1, "`--project` 无值必须报错（⛔ 不静默并进标题）：\n" + out)
        self.assertIn("参数错误", out)
        self.assertIn("没有项目名", out)
        self.assertEqual(os.listdir(self.active), [], "⛔ 报错时不得留下任何卡/目录")

    def test_main_create_project_only_keeps_default_title(self):
        # 兼容：历史上 `create --project <名>`（不写标题）也建卡 ⇒ 行为不得变
        code, out = self._run(T.main, ["task_card.py", "create", "--project", "demo-project"])
        self.assertEqual(code, 0, out)
        task_id = out.split("created:")[1].split()[0]
        path = os.path.join(self.active, "demo-project", task_id + ".md")
        self.assertTrue(os.path.isfile(path), out)
        with io.open(path, encoding="utf-8") as f:
            self.assertEqual(f.readline().rstrip("\n"), "# TASK_CARD")

    def test_main_create_unknown_flag_refused(self):
        code, out = self._run(T.main, ["task_card.py", "create", "标题", "--foo", "bar"])
        self.assertEqual(code, 1, "未知参数必须报错（⛔ 不并进标题）：\n" + out)
        self.assertIn("未知参数", out)
        self.assertIn("--foo", out)
        self.assertEqual(os.listdir(self.active), [], "⛔ 报错时不得落卡")

    def test_main_create_rejects_project_residue_title(self):
        code, out = self._run(T.main, ["task_card.py", "create",
                                       "公开仓 PROBLEM.md 起草（T4 第二件） --project=demo-project"])
        self.assertEqual(code, 1, "标题残留 `--project=` 必须拒绝：\n" + out)
        self.assertIn("拒绝建卡", out)
        self.assertIn("--project", out)
        self.assertEqual(os.listdir(self.active), [], "⛔ 拒绝时不得落卡")

    def test_main_create_rejects_mojibake_title(self):
        code, out = self._run(T.main, ["task_card.py", "create", "TASK_CARD 鈥?Coze 鏅鸿兘浣?"])
        self.assertEqual(code, 1, "疑似 mojibake 标题必须拒绝：\n" + out)
        self.assertIn("拒绝建卡", out)
        self.assertIn("mojibake", out)
        self.assertEqual(os.listdir(self.active), [], "⛔ 拒绝时不得落卡")


    # ── --help：总览 / 单命令 / 未知命令提示（新增）────────────
    def test_help_overview(self):
        code, out = self._run(T.main, ["task_card.py", "--help"])
        self.assertEqual(code, 0, out)
        for name in T.USAGE:
            self.assertIn(name, out, "总览必须列出命令：%s\n%s" % (name, out))
        self.assertIn("项目/TASK-ID", out, "必须说明跨项目重名的写法")
        self.assertIn("先重读", out, "必须提醒 claim/release 后先重读（P52）")

    def test_help_subcommand(self):
        code, out = self._run(T.main, ["task_card.py", "claim", "--help"])
        self.assertEqual(code, 0, out)
        self.assertIn("usage: task_card.py claim", out)
        # 只打印帮助，⛔ 不动任何卡
        self.assertEqual(os.listdir(self.active), [], "`claim --help` 不得改动 active/")

    def test_unknown_command_suggests(self):
        code, out = self._run(T.main, ["task_card.py", "cliam"])
        self.assertEqual(code, 1)
        self.assertIn("unknown command", out)
        self.assertIn("claim", out, "拼错时应给出相近命令建议：\n" + out)
        self.assertIn("--help", out)


    # ── 🔴 （C'/B' 实验）：`claim` 尾部能力提示 · `claimHint` 三档 ──────────────
    #   前提（读数 · ⛔ 不重新论证）：阶段注入**永远晚于**它想影响的决策
    #   ⇒ 提示必须出现在 **claim 的 stdout**（开工之前、工具返回而不是 notice）。
    def test_claim_hint_off_is_byte_identical(self):
        """缺省（= off）⇒ claim 输出**逐字等于**改前快照（A 组对照，⛔ 多一行都不行）。"""
        self._card("demo-project", "TASK-20260101-900", "Planning")
        code, out = self._run(T.cmd_claim, "demo-project/TASK-20260101-900")
        self.assertEqual(code, 0, out)
        self.assertEqual(out, CLAIM_STDOUT_OFF_SNAPSHOT,
                         "claimHint 缺省时 claim 输出必须与改前**逐字一致**（对照组被污染）")

    def test_claim_hint_generic_names_no_capability(self):
        """generic ⇒ 三行通用提示，且**不含任何具体能力名**（只说"有可用的"）。"""
        self._write_cfg('{"claimHint": "generic"}')
        self._card("demo-project", "TASK-20260101-901", "Planning", title="机制测试卡")
        code, out = self._run(T.cmd_claim, "demo-project/TASK-20260101-901")
        self.assertEqual(code, 0, out)
        self.assertIn("[AI-OS] 本阶段可用能力：见 capabilities/INDEX.md\n", out)
        self.assertIn("        开工前先定用哪个，然后记录：\n", out)
        self.assertIn("        python tools/task_card.py capability "
                      "demo-project/TASK-20260101-901 "
                      "--name <能力|none> --why \"<一句>\"\n", out)
        names = T._capability_names()
        self.assertGreaterEqual(len(names), 17, "能力名列表应覆盖能力库（同源）")
        hit = sorted(n for n in names if n in out)
        self.assertEqual(hit, [], "generic 档⛔ 不点名任何具体能力（命中：%s）" % hit)

    def test_claim_hint_cell_with_domain(self):
        """cell + 判得出域 ⇒ `<domain>·<class>` + CELLS.md 该格「这格什么时候用」原文 + `#<cell>`。"""
        self._cells_fixture()
        self._write_cfg('{"claimHint": "cell"}')
        self._card("demo-project", "TASK-20260101-902", "Planning",
                   title="前端 页面 评审补充")
        code, out = self._run(T.cmd_claim, "demo-project/TASK-20260101-902")
        self.assertEqual(code, 0, out)
        self.assertIn("[AI-OS] 本阶段可用能力（前端 · 一域一文件）：\n", out)
        self.assertIn("当做页面、觉得丑、或要过可访问性/性能验收时", out,
                      "必须是该域能力 frontmatter `intro` 的**原文**")
        self.assertIn("→ capabilities/domain-frontend.md\n", out)
        self.assertIn("记录：python tools/task_card.py capability "
                      "demo-project/TASK-20260101-902 "
                      "--name <域能力|none> --why \"...\"", out)
        self.assertNotIn("见 capabilities/INDEX.md", out, "cell 档不应再给通用文案")

    def test_claim_hint_cell_undetermined_domain_falls_back_generic(self):
        """cell + 判不出域 ⇒ **回退 generic 文案**（⛔ 静默不提示 · ⛔ 猜域）。"""
        self._cells_fixture()
        self._write_cfg('{"claimHint": "cell"}')
        self._card("demo-project", "TASK-20260101-903", "Planning", title="机制测试卡")
        code, out = self._run(T.cmd_claim, "demo-project/TASK-20260101-903")
        self.assertEqual(code, 0, out)
        self.assertIn("[AI-OS] 本阶段可用能力：见 capabilities/INDEX.md\n", out)
        self.assertNotIn("CELLS.md#", out, "判不出域时⛔ 不得硬套格（应回退 generic）")

    def test_claim_hint_cell_former_gap_domain_now_has_capability(self):
        """cell + 域判得出 ⇒ 提示该域的**域能力**。

        旧「缺口格 ⇒ 回退 generic」已失效 —— 域合并后每个域都有域能力
        （如「AI-OS 自身」曾有 0 片，现在有 `domain-aios-itself`）⇒ 应正常提示，⛔ 不再回退。
        """
        self._cells_fixture()
        self._write_cfg('{"claimHint": "cell"}')
        self._card("demo-project", "TASK-20260101-905", "Planning",
                   title="运行时 注入 探针")
        code, out = self._run(T.cmd_claim, "demo-project/TASK-20260101-905")
        self.assertEqual(code, 0, out)
        self.assertIn("（AI-OS 自身 · 一域一文件）：", out)
        self.assertIn("→ capabilities/domain-aios-itself.md", out)
        self.assertNotIn("见 capabilities/INDEX.md", out, "域解析成功时⛔ 不给通用文案")

    def test_claim_hint_real_site_config_stays_off(self):
        """真实实际配置（`enabled/max/form` 有、**无** `claimHint`）⇒ 仍是 off（A 组逐字不变）。"""
        self._write_cfg('{"enabled": true, "max": 1, "form": "intro"}')
        self._card("demo-project", "TASK-20260101-906", "Planning")
        code, out = self._run(T.cmd_claim, "demo-project/TASK-20260101-906")
        self.assertEqual(code, 0, out)
        self.assertEqual(out, CLAIM_STDOUT_OFF_SNAPSHOT.replace(
            "TASK-20260101-900", "TASK-20260101-906"))

    def test_claim_hint_broken_config_falls_back_off(self):
        """配置写坏 / 值非法 ⇒ 回落 `"off"`：claim 输出仍逐字等于快照，⛔ 不抛错。"""
        for i, bad in enumerate(('{not json', '[1, 2, 3]', '{"claimHint": "sometimes"}',
                                 '{"claimHint": true}')):
            tid = "TASK-20260101-9%02d" % i
            self._write_cfg(bad)
            p = self._card("demo-project", tid, "Planning")
            code, out = self._run(T.cmd_claim, "demo-project/" + tid)
            self.assertEqual(code, 0, "配置写坏⛔ 不得抛错：%r\n%s" % (bad, out))
            self.assertEqual(out, CLAIM_STDOUT_OFF_SNAPSHOT.replace(
                "TASK-20260101-900", tid),
                "配置写坏 / 值非法必须回落 off（⛔ 静默开启）：%r" % bad)
            # 复位：下一轮不该再看到「另有 Executing 卡」的提示行（它只影响提示，不影响被测行为）
            T._atomic_write(p, T._set_state_text(T._read(p), "Planning")[0])

    def test_claim_hint_bom_broken_config_falls_back_off(self):
        """**带 BOM + 坏 JSON** ⇒ 回落 off、⛔ 不抛错（中文 Windows 手写配置的读数坑）。"""
        self._write_cfg('{"claimHint": "generic"', bom=True)
        self._card("demo-project", "TASK-20260101-920", "Planning")
        code, out = self._run(T.cmd_claim, "demo-project/TASK-20260101-920")
        self.assertEqual(code, 0, "BOM + 坏配置⛔ 不得抛错：\n" + out)
        self.assertEqual(out, CLAIM_STDOUT_OFF_SNAPSHOT.replace(
            "TASK-20260101-900", "TASK-20260101-920"))

    def test_claim_hint_bom_valid_config_is_honored(self):
        """**带 BOM 的合法配置照样生效**（`utf-8-sig` 剥 BOM）。

        理由：若"带 BOM ⇒ 静默回落 off"，中文 Windows 手写的配置会"看起来开了实际是关"
        ⇒ A/B 的 B 组静默退化成 A 组（实验直接失效，且零报错）。
        """
        self._write_cfg('{"claimHint": "generic"}', bom=True)
        self._card("demo-project", "TASK-20260101-921", "Planning")
        code, out = self._run(T.cmd_claim, "demo-project/TASK-20260101-921")
        self.assertEqual(code, 0, out)
        self.assertIn("[AI-OS] 本阶段可用能力：见 capabilities/INDEX.md\n", out)

    def test_capability_hint_matches_claim_text(self):
        """`capability-hint` 与 claim **同一份文案逻辑**，且 ⛔ 不落盘、⛔ 不记账。"""
        self._write_cfg('{"claimHint": "generic"}')
        self._card("demo-project", "TASK-20260101-930", "Planning")
        code, out = self._run(T.main, ["task_card.py", "capability-hint",
                                       "demo-project/TASK-20260101-930",
                                       "--stage", "impl"])
        self.assertEqual(code, 0, out)
        self.assertEqual(out,
                         "[AI-OS] 本阶段可用能力：见 capabilities/INDEX.md\n"
                         "        开工前先定用哪个，然后记录：\n"
                         "        python tools/task_card.py capability "
                         "demo-project/TASK-20260101-930 "
                         "--name <能力|none> --why \"<一句>\"\n")
        log = os.path.join(self.active, "demo-project", "TASK-20260101-930.log")
        self.assertFalse(os.path.isfile(log), "capability-hint ⛔ 不落盘、不记账")

    def test_capability_hint_cell_domain_ignores_stage(self):
        """域合并后**阶段不再映射 class**：省略 `--stage` / `impl` / `close` 都提示同一个域能力。

        🔴 修：`--stage` 从「必填」改为「可省略」；给了也⛔ 不改变文案（按域出）。
        """
        self._cells_fixture()
        self._write_cfg('{"claimHint": "cell"}')
        self._card("demo-project", "TASK-20260101-931", "Planning", title="前端 组件 行为")
        outs = []
        for extra in ([], ["--stage=impl"], ["--stage", "close"]):
            code, out = self._run(T.main, ["task_card.py", "capability-hint",
                                           "demo-project/TASK-20260101-931"] + extra)
            self.assertEqual(code, 0, out)
            outs.append(out)
        self.assertEqual(len(set(outs)), 1, "阶段⛔ 不得改变提示文案（域合并后按域出）")
        self.assertIn("（前端 · 一域一文件）：", outs[0])
        self.assertIn("→ capabilities/domain-frontend.md\n", outs[0])

    def test_capability_hint_stage_is_optional(self):
        """省略 `--stage` ⇒ 单字段卡口径（与 `--stage start` 逐字相同 · 与 claim 同一文案）。"""
        self._write_cfg('{"claimHint": "generic"}')
        self._card("demo-project", "TASK-20260101-933", "Planning")
        code, no_stage = self._run(T.main, ["task_card.py", "capability-hint",
                                            "demo-project/TASK-20260101-933"])
        self.assertEqual(code, 0, no_stage)
        code, with_stage = self._run(T.main, ["task_card.py", "capability-hint",
                                              "demo-project/TASK-20260101-933",
                                              "--stage", "start"])
        self.assertEqual(code, 0, with_stage)
        self.assertEqual(no_stage, with_stage,
                         "省略 --stage 必须等价于显式 start（单字段口径）")
        self.assertIn("[AI-OS] 本阶段可用能力：见 capabilities/INDEX.md\n", no_stage)
        log = os.path.join(self.active, "demo-project", "TASK-20260101-933.log")
        self.assertFalse(os.path.isfile(log), "capability-hint ⛔ 不落盘、不记账")

    def test_capability_hint_rejects_unknown_stage(self):
        """显式给非法阶段 ⇒ 明确拒绝（含「可省略」提示）；`once` 是内部哨兵，⛔ 不接受显式传。"""
        self._write_cfg('{"claimHint": "generic"}')
        self._card("demo-project", "TASK-20260101-934", "Planning")
        for bad in ("foo", "once", "S1"):
            code, out = self._run(T.main, ["task_card.py", "capability-hint",
                                           "demo-project/TASK-20260101-934",
                                           "--stage", bad])
            self.assertEqual(code, 1, "非法 stage 必须拒绝（%r）：\n%s" % (bad, out))
            self.assertIn("capability-hint 被拒绝", out)
            self.assertIn("可省略", out, "拒绝文案要说清 `--stage` 可省略：\n" + out)

    def test_capability_hint_usage_marks_stage_optional(self):
        """`--help` 的用法必须写 `[--stage …]`（可省略），⛔ 不再写成必填。"""
        code, out = self._run(T.main, ["task_card.py", "capability-hint", "--help"])
        self.assertEqual(code, 0, out)
        self.assertIn("capability-hint <TASK-ID 或 项目/ID> [--stage start|impl|close]", out)
        self.assertIn("可省略", out)

    def test_capability_hint_off_prints_nothing(self):
        """`claimHint` 缺省 ⇒ `capability-hint` 什么都不打印（与 claim 逐字不变；省略/给 stage 都一样）。"""
        self._card("demo-project", "TASK-20260101-932", "Planning")
        for extra in ([], ["--stage", "start"]):
            code, out = self._run(T.main, ["task_card.py", "capability-hint",
                                           "demo-project/TASK-20260101-932"] + extra)
            self.assertEqual(code, 0, out)
            self.assertEqual(out, "", "off 档⛔ 必须零输出（省略 stage 亦然）")
        log = os.path.join(self.active, "demo-project", "TASK-20260101-932.log")
        self.assertFalse(os.path.isfile(log), "capability-hint ⛔ 不落盘、不记账")

    # ── ② 模板选择：`--template v1|v2|v3|v4`（缺省 **v4** · `AIOS_CARD_TEMPLATE` 优先）──
    #   判据：v2 ⇒ 能力节在 `## Current Status` 之后、`## Outcome` 之前；
    #   缺省（起 = v4）⇒ 与**当前 v4 模板**逐字一致（单字段「使用的能力」）；
    #   显式 v1 ⇒ 保旧行为（三阶段勾选框仍在 Close Checklist、⛔ 无「使用的能力」节）。

    def _card_text(self, path):
        with io.open(path, encoding="utf-8-sig", newline="") as f:
            return f.read().replace("\r\n", "\n")

    def _created_path(self, out):
        tid = out.split("created:")[1].split()[0]
        return tid, os.path.join(self.active, tid + ".md")

    def test_create_v2_puts_capability_section_between_status_and_outcome(self):
        code, out = self._run(T.main, ["task_card.py", "create", "v2 卡", "--template", "v2"])
        self.assertEqual(code, 0, out)
        _, path = self._created_path(out)
        text = self._card_text(path)
        head = "## 能力（三处必填 · 从 capabilities/ 选）"
        self.assertIn(head, text, "v2 必须含能力节：\n" + text[:400])
        i_status = text.index("## Current Status")
        i_cap = text.index(head)
        i_outcome = text.index("## Outcome")
        self.assertLess(i_status, i_cap, "能力节必须在 `## Current Status` 之后")
        self.assertLess(i_cap, i_outcome, "能力节必须在 `## Outcome` 之前")
        between = text[text.index("\n", i_status):i_cap]
        self.assertNotIn("\n## ", between, "Current Status 与能力节之间不得夹其它节：\n" + between)
        section = text[i_cap:i_outcome]
        # 🔴 域合并：v2 能力节的指引从 CELLS.md 改为 INDEX.md（8 个域能力）
        for frag in ("- [ ] **开工**", "- [ ] **实现**", "- [ ] **收尾**",
                     "--stage start", "--stage impl", "--stage close",
                     "_capability_choice_lint.py", "capabilities/INDEX.md"):
            self.assertIn(frag, section, "能力节缺 `%s`：\n%s" % (frag, section))

    def test_create_v2_close_checklist_keeps_five_and_pointer(self):
        code, out = self._run(T.main, ["task_card.py", "create", "v2 收口", "--template=v2"])
        self.assertEqual(code, 0, out)
        _, path = self._created_path(out)
        text = self._card_text(path)
        close = text[text.index("## Close Checklist"):]
        for keep in ("Deliverables completed", "Pattern extracted", "Telemetry written",
                     "Task Card cleaned", "Task Card archived"):
            self.assertIn("- [ ] " + keep, close, "原 5 项不得丢：%s" % keep)
        for gone in ("**能力-开工**", "**能力-实现**", "**能力选择（收口）**"):
            self.assertNotIn(gone, close, "v2 收口清单不得重复能力三项：%s" % gone)
        self.assertIn("能力三点见上方『能力』节", close, "v2 收口清单要有指向能力节的一行指针")
        self.assertEqual(close.count("- [ ]"), 6, "v2 收口清单 = 原 5 项 + 1 行指针：\n" + close)

    def test_v1_template_structure_untouched(self):
        """v1 只加一行 A/B 指针：能力三项仍在 Close Checklist，⛔ 没有能力节。"""
        text = self._card_text(os.path.join(ROOT, "task_cards", "_TASK_CARD_template.md"))
        self.assertNotIn("## 能力（三处必填", text, "⛔ v1 不得结构改动（能力节只属于 v2）")
        close = text[text.index("## Close Checklist"):]
        for frag in ("**能力-开工**", "**能力-实现**", "**能力选择（收口）**"):
            self.assertIn(frag, close, "v1 能力三项不得被挪走：%s" % frag)
        self.assertIn("_TASK_CARD_template.v2.md", close, "v1 要有一行指向 v2 的 A/B 指针")

    def test_default_create_is_current_v4_template_verbatim(self):
        """缺省（= v4）⇒ 卡内容 == 当前 v4 模板逐字 + create 的四处替换 ⇒ 无模板外改写。"""
        code, out = self._run(T.main, ["task_card.py", "create", "默认卡"])
        self.assertEqual(code, 0, out)
        tid, path = self._created_path(out)
        got = self._card_text(path)
        tpl = self._card_text(os.path.join(ROOT, "task_cards", "_TASK_CARD_template.v4.md"))
        m = re.search(r"^Created:\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})$", got, re.M)
        self.assertIsNotNone(m, "卡 Header 里应有 Created 时间：\n" + got[:400])
        expected = tpl.replace("TASK-YYYYMMDD-001", tid)
        expected = expected.replace("YYYY-MM-DD HH:mm", m.group(1))
        expected = T.STATE_LINE_RE.sub(lambda mm: mm.group(1) + "Planning", expected, count=1)
        expected = expected.replace("# TASK_CARD", "# TASK_CARD — 默认卡")
        self.assertEqual(got, expected, "缺省 create 必须逐字复制当前 v4 模板（单字段版）")
        self.assertNotIn("## 能力（三处必填", got, "缺省 create 不得用 v2")

    def test_default_create_has_single_field_capability_section(self):
        """缺省 v4 ⇒ 有 `## 使用的能力（可 none）` + `- 能力: `（未记录）``，且⛔ 没有 `- 开工:`。"""
        code, out = self._run(T.main, ["task_card.py", "create", "单字段缺省"])
        self.assertEqual(code, 0, out)
        _, path = self._created_path(out)
        text = self._card_text(path)
        self.assertIn("## 使用的能力（可 none）", text, "缺省卡必须有单字段能力节：\n" + text[:600])
        self.assertIn("- 能力: `（未记录）`", text, "缺省卡必须有单字段占位行")
        self.assertNotIn("- 开工:", text, "v4 卡⛔ 不得有三阶段字段行")
        i_status = text.index("## Current Status")
        i_cap = text.index("## 使用的能力（可 none）")
        i_outcome = text.index("## Outcome")
        self.assertLess(i_status, i_cap)
        self.assertLess(i_cap, i_outcome)

    def test_explicit_v1_template_still_builds_v1_card(self):
        """`--template v1` 仍建 v1 卡（保旧行为）：⛔ 无「使用的能力」节、能力三项仍在 Close Checklist。"""
        code, out = self._run(T.main, ["task_card.py", "create", "显式 v1", "--template", "v1"])
        self.assertEqual(code, 0, out)
        _, path = self._created_path(out)
        text = self._card_text(path)
        self.assertNotIn("## 使用的能力", text, "显式 v1 不得出现能力字段节")
        self.assertNotIn("- 能力:", text)
        close = text[text.index("## Close Checklist"):]
        for frag in ("**能力-开工**", "**能力-实现**", "**能力选择（收口）**"):
            self.assertIn(frag, close, "v1 能力三项不得被挪走：%s" % frag)

    def test_template_env_wins_over_cli(self):
        """环境变量优先于 `--template`（任务书明确：env 优先）—— 两个方向都要生效。"""
        with mock.patch.dict(os.environ, {"AIOS_CARD_TEMPLATE": "v2"}):
            code, out = self._run(T.main, ["task_card.py", "create", "env v2",
                                           "--template", "v1"])
        self.assertEqual(code, 0, out)
        _, path = self._created_path(out)
        self.assertIn("## 能力（三处必填", self._card_text(path),
                      "env=v2 必须压过 CLI --template v1")
        with mock.patch.dict(os.environ, {"AIOS_CARD_TEMPLATE": "v1"}):
            code, out = self._run(T.main, ["task_card.py", "create", "env v1",
                                           "--template", "v2"])
        self.assertEqual(code, 0, out)
        _, path = self._created_path(out)
        self.assertNotIn("## 能力（三处必填", self._card_text(path),
                         "env=v1 必须压过 CLI --template v2")

    def test_template_v2_missing_is_explicit_error(self):
        """模板缺失 ⇒ 明确报错 · ⛔ 不静默回落 v1。"""
        os.remove(os.path.join(self.tmp, "task_cards", "_TASK_CARD_template.v2.md"))
        code, out = self._run(T.main, ["task_card.py", "create", "缺模板", "--template", "v2"])
        self.assertEqual(code, 1, "v2 模板缺失必须失败：\n" + out)
        self.assertIn("模板缺失", out)
        self.assertIn("v2", out)
        self.assertEqual(os.listdir(self.active), [], "⛔ 报错时不得落卡（更不得回落 v1）")

    # ── ④ （v3）：卡上「使用的能力」字段 + `capability` 双写 ─────────────
    #   判据（任务书）：卡上**可见**、`.log` **可核**，由同一子命令同时写；
    #   v1/v2 卡无该节 ⇒ 只写 `.log`、⛔ 不报错、⛔ 不自动加节（保护已有 A/B 数据）。
    CAP_HEAD_V3 = "## 使用的能力（三阶段 · 可 none）"

    def _create_v3(self, title="v3 卡"):
        code, out = self._run(T.main, ["task_card.py", "create", title, "--template", "v3"])
        self.assertEqual(code, 0, out)
        return self._created_path(out)

    def _create_v4(self, title="v4 卡"):
        """v4 是**缺省**模板 ⇒ 不传 `--template`。"""
        code, out = self._run(T.main, ["task_card.py", "create", title])
        self.assertEqual(code, 0, out)
        return self._created_path(out)

    def test_capability_without_stage_writes_single_field(self):
        """v4 卡 + 省略 `--stage` ⇒ `.log` 一条 `能力` 行 · 卡上一行 `- 能力:`（⛔ 多出阶段行）。"""
        task_id, path = self._create_v4("单字段写入")
        code, out = self._run(T.main, ["task_card.py", "capability", task_id,
                                       "--name", "domain-docs",
                                       "--why", "本次改文档与校验器，按文档域能力执行"])
        self.assertEqual(code, 0, out)
        text = self._card_text(path)
        self.assertIn("- 能力: `domain-docs` ｜ 本次改文档与校验器，按文档域能力执行", text)
        self.assertEqual(text.count("- 能力:"), 1, "单字段卡只应有这一行能力记录")
        self.assertNotIn("- 开工:", text, "v4 卡⛔ 不得冒出三阶段字段行")
        with io.open(path[:-3] + ".log", encoding="utf-8") as f:
            log_text = f.read()
        self.assertIn("| 能力 | domain-docs ｜ 理由：本次改文档与校验器，按文档域能力执行 |",
                      log_text)

    def test_capability_without_stage_none_writes_single_field(self):
        """v4 卡 + 省略 `--stage` + `--name none` ⇒ 卡上 `- 能力: `none``，`.log` 一条 `能力` 行。"""
        task_id, path = self._create_v4("单字段 none")
        code, out = self._run(T.main, ["task_card.py", "capability", task_id,
                                       "--name", "none",
                                       "--why", "该卡只验 none 语义：本次无对应域能力可装配"])
        self.assertEqual(code, 0, out)
        text = self._card_text(path)
        self.assertIn("- 能力: `none` ｜ 该卡只验 none 语义：本次无对应域能力可装配", text)
        self.assertEqual(text.count("- 能力:"), 1)
        self.assertNotIn("- 开工:", text, "v4 卡⛔ 不得冒出三阶段字段行")
        with io.open(path[:-3] + ".log", encoding="utf-8") as f:
            log_text = f.read()
        self.assertIn("| 能力 | none ｜ 理由：该卡只验 none 语义：本次无对应域能力可装配 |",
                      log_text)

    def test_capability_rejects_stage_on_v4_single_field_card(self):
        """v4 单字段卡 + 显式 `--stage` ⇒ 拒绝且**无副作用**（否则会插入阶段行、卡形态翻 legacy）。"""
        task_id, path = self._create_v4("拒绝阶段行")
        before = self._card_text(path)
        code, out = self._run(T.main, ["task_card.py", "capability", task_id,
                                       "--stage", "start", "--name", "none",
                                       "--why", "单字段卡给阶段参数会写坏卡形态，必须拒绝"])
        self.assertEqual(code, 1, "v4 单字段卡给 --stage 必须拒绝：\n" + out)
        self.assertIn("单字段卡", out)
        self.assertIn("--stage", out)
        self.assertEqual(self._card_text(path), before, "拒绝时卡必须一字不动")
        self.assertFalse(os.path.isfile(path[:-3] + ".log"), "拒绝时不得先写 `.log`")

    def test_create_v3_has_capability_field_block(self):
        _, path = self._create_v3()
        text = self._card_text(path)
        self.assertIn(self.CAP_HEAD_V3, text)
        i_status = text.index("## Current Status")
        i_cap = text.index(self.CAP_HEAD_V3)
        i_outcome = text.index("## Outcome")
        self.assertLess(i_status, i_cap, "字段节必须在 `## Current Status` 之后")
        self.assertLess(i_cap, i_outcome, "字段节必须在 `## Outcome` 之前")
        between = text[text.index("\n", i_status):i_cap]
        self.assertNotIn("\n## ", between, "Current Status 与字段节之间不得夹其它节：\n" + between)
        section = text[i_cap:i_outcome]
        for frag in ("- 开工: `（未记录）`", "- 实现: `（未记录）`", "- 收尾: `（未记录）`"):
            self.assertIn(frag, section, "v3 字段块缺 `%s`：\n%s" % (frag, section))
        self.assertNotIn("## 能力（三处必填", text, "v3 不得再保留 v2 的勾选框节")

    def test_create_v3_close_checklist_pointer(self):
        _, path = self._create_v3("v3 收口")
        text = self._card_text(path)
        close = text[text.index("## Close Checklist"):]
        self.assertIn("能力三点见上方『使用的能力』节，校验用 `_capability_choice_lint.py`", close)
        self.assertNotIn("**能力-开工**", close, "v3 收口清单不得重复能力三项")
        self.assertEqual(close.count("- [ ]"), 6, "v3 收口清单 = 原 5 项 + 1 行指针：\n" + close)

    def test_capability_writes_card_field_and_log_idempotently(self):
        task_id, path = self._create_v3("字段联动")
        code, out = self._run(T.main, ["task_card.py", "capability", task_id,
                                       "--stage", "start", "--name", "test-driven-development",
                                       "--why", "第一次开工理由够长"])
        self.assertEqual(code, 0, out)
        text = self._card_text(path)
        self.assertIn("- 开工: `test-driven-development` ｜ 第一次开工理由够长", text)
        log = path[:-3] + ".log"
        self.assertTrue(os.path.isfile(log), "`.log` 必须同时有记录")
        with io.open(log, encoding="utf-8") as f:
            log_text = f.read()
        self.assertIn("| 能力-开工 | test-driven-development ｜ 理由：第一次开工理由够长 |",
                      log_text)
        # 幂等：同一 stage 再跑 ⇒ 覆盖该行，⛔ 不追加
        code, out = self._run(T.main, ["task_card.py", "capability", task_id,
                                       "--stage", "start", "--name", "test-driven-development",
                                       "--why", "第二次开工理由覆盖"])
        self.assertEqual(code, 0, out)
        text = self._card_text(path)
        self.assertEqual(text.count("- 开工:"), 1, "同一 stage 必须覆盖、⛔ 不追加：\n" + text)
        self.assertIn("- 开工: `test-driven-development` ｜ 第二次开工理由覆盖", text)
        self.assertNotIn("第一次开工理由够长", text, "旧值必须被覆盖")

    def test_capability_stage_labels_map_to_card_lines(self):
        """三阶段 ⇒ 卡上 开工 / 实现 / 收尾 三行；`none` 也照写（不特殊跳过）。"""
        task_id, path = self._create_v3("三阶段映射")
        for stage, label, name, why in (
                ("impl", "实现", "test-driven-development", "实现阶段记录理由"),
                ("close", "收尾", "none", "收尾阶段无合适能力")):
            code, out = self._run(T.main, ["task_card.py", "capability", task_id,
                                           "--stage", stage, "--name", name, "--why", why])
            self.assertEqual(code, 0, out)
            self.assertIn("- %s: `%s` ｜ %s" % (label, name, why),
                          self._card_text(path), "阶段 %s 必须写卡上的 `%s` 行" % (stage, label))

    def test_capability_overwrites_manually_broken_line(self):
        """节存在但阶段行被手改坏 ⇒ 覆盖成规范行（⛔ 留着坏行、⛔ 追加重复行）。"""
        task_id, path = self._create_v3("手改坏")
        text = self._card_text(path).replace("- 实现: `（未记录）`", "- 实现已手改坏")
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        code, out = self._run(T.main, ["task_card.py", "capability", task_id,
                                       "--stage", "impl", "--name", "none",
                                       "--why", "手改坏也要覆盖成规范行"])
        self.assertEqual(code, 0, out)
        text = self._card_text(path)
        self.assertIn("- 实现: `none` ｜ 手改坏也要覆盖成规范行", text)
        self.assertNotIn("实现已手改坏", text, "坏行必须被规范行替换")
        self.assertEqual(text.count("- 实现:"), 1, "⛔ 不得追加重复行：\n" + text)

    def test_capability_v2_card_without_field_section_only_writes_log(self):
        """v1/v2 卡没有「使用的能力」节 ⇒ 只写 `.log`、命令成功、卡**一字不动**（向后兼容）。"""
        for tpl in ("v1", "v2"):
            with self.subTest(template=tpl):
                code, out = self._run(T.main, ["task_card.py", "create", "兼容 " + tpl,
                                               "--template", tpl])
                self.assertEqual(code, 0, out)
                task_id, path = self._created_path(out)
                with io.open(path, "rb") as f:
                    before = f.read()
                code, out = self._run(T.main, ["task_card.py", "capability", task_id,
                                               "--stage", "impl", "--name", "none",
                                               "--why", "该阶段无合适能力故记 none"])
                self.assertEqual(code, 0, "v1/v2 卡无该节也必须成功（⛔ 不报错）：\n" + out)
                with io.open(path, "rb") as f:
                    after = f.read()
                self.assertEqual(after, before, "无该节 ⇒ 卡必须一字不动（⛔ 自动加节）")
                log = path[:-3] + ".log"
                self.assertTrue(os.path.isfile(log))
                with io.open(log, encoding="utf-8") as f:
                    self.assertIn("| 能力-实现 | none ｜ 理由：该阶段无合适能力故记 none |",
                                  f.read())

    def test_template_invalid_value_is_error(self):
        for argv in (["--template", "v9"], ["--template="], ["--template"]):
            code, out = self._run(T.main, ["task_card.py", "create", "坏模板值"] + argv)
            self.assertEqual(code, 1, "非法模板参数必须报错：%r\n%s" % (argv, out))
            self.assertIn("--template", out)
            self.assertEqual(os.listdir(self.active), [], "⛔ 报错时不得落卡")

    def test_template_env_invalid_is_error(self):
        with mock.patch.dict(os.environ, {"AIOS_CARD_TEMPLATE": "v9"}):
            code, out = self._run(T.main, ["task_card.py", "create", "坏 env"])
        self.assertEqual(code, 1, "非法环境变量必须报错：\n" + out)
        self.assertIn("AIOS_CARD_TEMPLATE", out)
        self.assertEqual(os.listdir(self.active), [], "⛔ 报错时不得落卡")

    # ── ③ 只读自检：`capability-timing <TASK-ID>` ──────────────────────
    #   一次给出 A/B 的第 2、3 条判据：开工是否早于首次 edit / 三处是同一能力还是阶段切换。

    def _write_log(self, path, rows):
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.write("| Time | State | Reason | Changed By |\n"
                    "|------|-------|--------|:----------:|\n")
            for r in rows:
                f.write(r + "\n")

    def _write_probe(self, session, at_dt, tool="edit"):
        p = T.PROBE_LOG
        os.makedirs(os.path.dirname(p), exist_ok=True)
        line = ('[aios-activation] {"ev":"tool-sig","obs":"test","session":"%s",'
                '"windowSeq":0,"callId":"c1","tool":"%s","toolClass":"%s",'
                '"pathClass":"tools/x.py","deferred":false,"at":%d}\n'
                % (session, tool, tool, int(at_dt.timestamp() * 1000)))
        with io.open(p, "a", encoding="utf-8", newline="") as f:
            f.write(line)

    def _timing_fixture(self, names, first_edit_hhmmss=(10, 2, 30), start="10:01"):
        p = self._card("demo-project", "TASK-20260101-950", "Executing")
        log = p[:-3] + ".log"
        rows = ["| %s | Executing | claim 占用（session: sess-me） | Worker |" % "10:00"]
        times = {"start": start, "impl": "10:02", "close": "10:03"}
        for stage, name in zip(("start", "impl", "close"), names):
            if name is None:
                continue
            rows.append("| %s | %s | %s ｜ 理由：本次改动按该能力执行并留痕 | Worker |"
                        % (times[stage], T.CAPABILITY_STAGES[stage], name))
        self._write_log(log, rows)
        today = datetime.date.today()
        first = datetime.datetime.combine(today, datetime.time(*first_edit_hhmmss))
        self._write_probe("sess-me", first)
        return p, log

    def test_capability_timing_reports_before_edit_and_stage_switch(self):
        p, _ = self._timing_fixture(["test-driven-development", "self-verification", "prose_standard"])
        code, out = self._run(T.main, ["task_card.py", "capability-timing",
                                       "demo-project/TASK-20260101-950"])
        self.assertEqual(code, 0, out)
        for frag in ("开工: 10:01", "实现: 10:02", "收尾: 10:03",
                     "首次 edit:", "10:02:30",
                     "开工早于首次 edit: YES", "阶段切换"):
            self.assertIn(frag, out, "capability-timing 缺 `%s`：\n%s" % (frag, out))
        out.encode("gbk")  # GBK 控制台：新打印串必须可编码

    def test_capability_timing_reports_reuse(self):
        _, _ = self._timing_fixture(["self-verification"] * 3)
        code, out = self._run(T.main, ["task_card.py", "capability-timing",
                                       "demo-project/TASK-20260101-950"])
        self.assertEqual(code, 0, out)
        self.assertIn("复用", out, "三处同一能力应判「复用」：\n" + out)
        self.assertNotIn("阶段切换", out)

    def test_capability_timing_single_field_output_sample(self):
        """v4 单字段卡 ⇒ `能力: …` / `首次 edit: …` / `早于首次 edit: YES`（⛔ 不打三处明细）。"""
        task_id, path = self._create_v4("单字段 timing")
        # 🔴 修时间依赖：本用例把探针首次 edit 固定在**今天 10:02:30**，
        #    而卡 Created 取"现在" ⇒ 只要当前挂钟晚于 10:02，就会判成"后建卡"⇒ 期望 YES 变 N/A。
        #    （读数：09:0x 跑绿、12:5x 跑红 —— 发布产物克隆闸门抓到）
        #    ⇒ 把 Created 固定成，让"卡早于首次 edit"成为**恒真**前提。
        text = self._card_text(path)
        text = re.sub(r"^Created:\s+.*$", "Created:     2000-01-01 00:00", text,
                      count=1, flags=re.M)
        with io.open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        self._write_log(path[:-3] + ".log", [
            "| 10:00 | Executing | claim 占用（session: sess-me） | Worker |",
            "| 10:01 | 能力 | domain-docs ｜ 理由：单字段记录 | Worker |",
        ])
        today = datetime.date.today()
        self._write_probe("sess-me", datetime.datetime.combine(today, datetime.time(10, 2, 30)))
        code, out = self._run(T.main, ["task_card.py", "capability-timing", task_id])
        self.assertEqual(code, 0, out)
        self.assertIn("能力: domain-docs（10:01）", out)
        self.assertIn("首次 edit:", out)
        self.assertIn("早于首次 edit: YES", out)
        self.assertNotIn("三处能力", out, "单字段卡⛔ 不打三处明细")
        out.encode("gbk")  # GBK 控制台：新打印串必须可编码

    def test_capability_timing_single_field_card_built_after_first_edit(self):
        """卡建于该会话首次 edit 之后（同会话后建卡）⇒ `早于首次 edit: N/A`（⛔ 误判 NO）。"""
        task_id, path = self._create_v4("后建卡 timing")
        text = self._card_text(path)
        text = re.sub(r"^Created:\s+.*$", "Created:     2099-01-01 00:00", text,
                      count=1, flags=re.M)
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        self._write_log(path[:-3] + ".log", [
            "| 10:00 | Executing | claim 占用（session: sess-me） | Worker |",
            "| 10:01 | 能力 | domain-docs ｜ 理由：单字段记录 | Worker |",
        ])
        today = datetime.date.today()
        self._write_probe("sess-me", datetime.datetime.combine(today, datetime.time(10, 2, 30)))
        code, out = self._run(T.main, ["task_card.py", "capability-timing", task_id])
        self.assertEqual(code, 0, out)
        self.assertIn("早于首次 edit: N/A", out, "后建卡⛔ 不得因会话首次 edit 误判 NO：\n" + out)
        out.encode("gbk")

    def test_capability_timing_is_read_only(self):
        p, log = self._timing_fixture(["self-verification", "self-verification", "self-verification"])
        with io.open(p, encoding="utf-8") as f:
            card_before = f.read()
        with io.open(log, encoding="utf-8") as f:
            log_before = f.read()
        before = (os.path.getmtime(p), os.path.getmtime(log), card_before, log_before)
        code, out = self._run(T.main, ["task_card.py", "capability-timing",
                                       "demo-project/TASK-20260101-950"])
        self.assertEqual(code, 0, out)
        with io.open(p, encoding="utf-8") as f:
            card_after = f.read()
        with io.open(log, encoding="utf-8") as f:
            log_after = f.read()
        after = (os.path.getmtime(p), os.path.getmtime(log), card_after, log_after)
        self.assertEqual(before, after, "capability-timing 必须只读（卡 / .log 一字不动）")

    def test_capability_timing_missing_card_is_error(self):
        code, out = self._run(T.main, ["task_card.py", "capability-timing", "TASK-19990101-001"])
        self.assertEqual(code, 1)
        self.assertIn("未找到", out)


class CreateArgParseAndGuardTest(unittest.TestCase):
    """纯函数测试：`create` 的 argv 解析 + 标题守卫 —— **不建任何卡 · ⛔ 不碰文件系统**。"""

    def test_space_form(self):
        self.assertEqual(T.parse_create_args(["标题", "--project", "demo-project"]),
                         ("标题", "demo-project", None))
        self.assertEqual(T.parse_create_args(["--project", "demo-project", "标题"]),
                         ("标题", "demo-project", None))

    def test_equals_form(self):
        self.assertEqual(T.parse_create_args(["标题", "--project=demo-project"]),
                         ("标题", "demo-project", None))
        self.assertEqual(T.parse_create_args(["--project=demo-project", "标题"]),
                         ("标题", "demo-project", None))

    def test_title_join_unchanged(self):
        # 旧行为：`" ".join(args)` ⇒ 多 token 标题用空格拼回（逐字一致）
        self.assertEqual(T.parse_create_args(["多", "词", "标题"]), ("多 词 标题", None, None))
        self.assertEqual(T.parse_create_args([]), ("", None, None))

    # ── ② 模板选择的纯解析：`--template X`（空格）与 `--template=X`（等号）等价 ──────
    def test_template_flag_parsed(self):
        self.assertEqual(T.parse_create_args_full(["标题", "--template", "v2"]),
                         ("标题", None, "v2", None))
        self.assertEqual(T.parse_create_args_full(["标题", "--template=v2", "--project=X"]),
                         ("标题", "X", "v2", None))
        self.assertEqual(T.parse_create_args_full(["标题"]), ("标题", None, None, None))

    def test_template_flag_keeps_three_tuple_compat(self):
        # 旧公开签名（3 元组）不得变：既有调用方/用例依赖它
        self.assertEqual(T.parse_create_args(["标题", "--template=v2"]), ("标题", None, None))

    def test_template_flag_errors(self):
        for argv in (["标题", "--template"], ["标题", "--template="],
                     ["标题", "--template", "v9"], ["标题", "--template=v1", "--template=v2"]):
            title, project, template, err = T.parse_create_args_full(argv)
            self.assertIsNone(title, argv)
            self.assertIsNone(project, argv)
            self.assertIsNone(template, argv)
            self.assertIn("--template", err or "", argv)

    def test_missing_value_is_error(self):
        for argv in (["标题", "--project"], ["--project"]):
            title, project, err = T.parse_create_args(argv)
            self.assertIsNone(title, argv)
            self.assertIsNone(project, argv)
            self.assertIn("没有项目名", err or "", argv)

    def test_empty_equals_value_is_error(self):
        _, _, err = T.parse_create_args(["标题", "--project="])
        self.assertIn("没有项目名", err or "")

    def test_next_token_looks_like_flag_is_error(self):
        _, _, err = T.parse_create_args(["标题", "--project", "--state=Parked"])
        self.assertIn("没有项目名", err or "")

    def test_duplicate_project_is_error(self):
        _, _, err = T.parse_create_args(["标题", "--project=A", "--project=B"])
        self.assertIn("重复", err or "")

    def test_unknown_flag_is_error(self):
        title, project, err = T.parse_create_args(["标题", "--foo", "x"])
        self.assertIsNone(title)
        self.assertIsNone(project)
        self.assertIn("未知参数", err or "")
        self.assertIn("--foo", err or "")

    def test_title_project_residue_rejected(self):
        ok, why = T.check_create_title("公开仓 PROBLEM.md 起草（T4 第二件） --project=AI-OS-Adaptation")
        self.assertFalse(ok)
        self.assertIn("--project", why)

    def test_title_other_flag_residue_rejected(self):
        ok, why = T.check_create_title("标题 --state=Parked")
        self.assertFalse(ok)
        self.assertIn("--state=", why)

    def test_title_mojibake_rejected(self):
        for bad in ("TASK_CARD 鈥?Coze 鏅鸿兘浣?", "锛", "銆", "bad \ufffd text"):
            ok, why = T.check_create_title("前缀 %s 后缀" % bad)
            self.assertFalse(ok, "应拒绝：%r" % bad)
            self.assertIn("mojibake", why)

    def test_empty_title_allowed_for_compat(self):
        # 兼容：历史用法 `create --project <名>`（标题后补）⇒ ⛔ 不因空标题改行为
        ok, why = T.check_create_title("   ")
        self.assertTrue(ok, why)

    def test_normal_title_passes(self):
        for good in ("公开仓 PROBLEM.md 起草（T4 第二件）",
                     "修 task_card.py 的等号参数解析",
                     "测试：中文标题 · 含标点（括号）"):
            ok, why = T.check_create_title(good)
            self.assertTrue(ok, "不应拒绝正常标题 %r：%s" % (good, why))


class CardCapabilityModeTest(unittest.TestCase):
    """卡形态判定（`task_card.card_capability_mode`）—— lint 的**单一来源**（⛔ 不另写一套）。"""

    def test_legacy_and_single(self):
        self.assertEqual(T.card_capability_mode("- 开工: `x` ｜ y\n"), "legacy")
        self.assertEqual(T.card_capability_mode("- 实现: `x` ｜ y\n"), "legacy")
        self.assertEqual(T.card_capability_mode("- 收尾: `x` ｜ y\n"), "legacy")
        self.assertEqual(T.card_capability_mode("- 能力: `x` ｜ y\n"), "single")

    def test_both_forms_legacy_wins(self):
        self.assertEqual(T.card_capability_mode("- 开工: `x` ｜ y\n- 能力: `z` ｜ w\n"),
                         "legacy", "两种行都在 ⇒ 旧卡优先（三阶段判据逐字不变）")

    def test_neither_form_is_none(self):
        self.assertIsNone(T.card_capability_mode("# TASK_CARD\n\n## Goal\n\nx\n"))
        self.assertIsNone(T.card_capability_mode(""), "空文本 ⇒ None")
        # 散文里的 `能力: …`（无列表符）⛔ 不算 v4 行（否则旧卡会被误判成单字段而假红）
        self.assertIsNone(T.card_capability_mode("本卡能力: 用 x 就够\n"))


class ClaimHintWordTableParityTest(unittest.TestCase):
    """Python 侧词表 vs `runtime/aios-activation.ts` 的 `CELL_DOMAIN_WORDS` —— **漂移即红**。

    为什么值得一条用例：两份词表一旦不同步，**同一个任务**会被 claim 判成 A 域、被阶段注入判成 B 域
    ⇒ 格提示与注入互相打脸，而**两边都不会报错**（只做 Python 侧，runtime 下一轮才统一）。
    """

    def test_claim_hint_words_align_with_runtime(self):
        p = os.path.join(ROOT, "runtime", "aios-activation.ts")
        if not os.path.isfile(p):
            self.skipTest("runtime/aios-activation.ts 不在本环境")
        with io.open(p, encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"const CELL_DOMAIN_WORDS\b[^=]*=\s*\[(.*?)\n\]", text, re.S)
        self.assertIsNotNone(m, "找不到 `CELL_DOMAIN_WORDS`（TS 结构变了 ⇒ 请同步本用例）")
        rows = re.findall(r"\{\s*domain:\s*'([^']+)',\s*words:\s*\[([^\]]*)\]\s*\}",
                          m.group(1))
        ts = [(d, tuple(w.strip().strip("'") for w in ws.split(",") if w.strip()))
              for d, ws in rows]
        self.assertEqual(ts, list(T.CELL_DOMAIN_WORDS),
                         "Python 与 TS 的领域词表已漂移 ⇒ 同一任务会被判成不同的域（两边一起改）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
