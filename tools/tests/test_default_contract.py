# -*- coding: utf-8 -*-
"""默认契约测试：`.aios-sample` 的值只有一处事实源，且样本文件与 README 一致。

背景：代码缺省 / 样本 / 发布文档曾给出相反答案（recall、domainInject、claimHint），
导致「实验里开了、产品里关着」「文档写关、样本开」⇒ 走通了看不出。

⛔ 本测试只依赖**随发布**的文件（`tools/aios_switches.py` + `.aios-sample/`），
   不 import 作者侧 `release_assemble.py`（否则干净克隆里必红）。
"""
import importlib.util
import io
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MOD = os.path.join(ROOT, "tools", "aios_switches.py")
SAMPLE = os.path.join(ROOT, ".aios-sample")


def load_source():
    spec = importlib.util.spec_from_file_location("aios_switches_under_test", MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DefaultContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = load_source()

    def test_single_source_exists(self):
        self.assertTrue(hasattr(self.src, "SWITCH_SAMPLE"), "必须有单一事实源 SWITCH_SAMPLE")
        self.assertEqual(sorted(self.src.SWITCH_SAMPLE),
                         sorted(["phase_inject.json", "inject_probe.json", "cap-cells.json",
                                 "experience_recall.json", "r3-wake.json"]),
                         "样本文件集合固定为 5 份")

    def test_recommended_values(self):
        s = self.src.SWITCH_SAMPLE
        self.assertIs(s["phase_inject.json"]["enabled"], True)
        self.assertIs(s["inject_probe.json"]["enabled"], True)
        self.assertEqual(s["inject_probe.json"]["session"], "*", "缺 session 会让注入整块静默失效")
        self.assertIs(s["inject_probe.json"]["allowSubagent"], True, "子会话也要收投递")
        self.assertEqual(s["cap-cells.json"]["claimHint"], "generic")
        self.assertEqual(s["cap-cells.json"]["domainInject"], "on", "声明驱动，⛔ 不猜域")
        self.assertIs(s["cap-cells.json"]["enabled"], False, "格能力已废弃 ⇒ 保持关")
        self.assertIs(s["experience_recall.json"]["enabled"], True)
        self.assertIs(s["r3-wake.json"]["enabled"], False, "空闲唤醒要人确认后手动开")

    def test_readme_matches_source(self):
        rd = self.src.SAMPLE_README
        for k in self.src.SWITCH_SAMPLE:
            self.assertIn(k, rd, "样本 README 必须列出 " + k)
        for needle in ('"allowSubagent":true', '"claimHint":"generic"', '"domainInject":"on"',
                       '{"enabled":false}'):
            self.assertIn(needle, rd, "README 表格值应与 SWITCH_SAMPLE 一致：缺 " + needle)
        self.assertIn("零注入", rd, "README 必须说明：`.aios/` 缺失 = 零注入")

    def test_shipped_sample_files_match_source(self):
        """发布物里的 `.aios-sample/*.json` 必须与事实源逐值一致（防手工改漂）。"""
        if not os.path.isdir(SAMPLE):
            self.skipTest("当前不是发布物（无 .aios-sample/）")
        for name, cfg in self.src.SWITCH_SAMPLE.items():
            p = os.path.join(SAMPLE, name)
            self.assertTrue(os.path.isfile(p), "样本缺文件：" + name)
            got = json.load(io.open(p, encoding="utf-8"))
            self.assertEqual(got, cfg, "样本值与事实源不一致：" + name)


if __name__ == "__main__":
    unittest.main()
