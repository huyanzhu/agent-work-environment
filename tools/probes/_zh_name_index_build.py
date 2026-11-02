#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_zh_name_index_build.py — 生成**中文技能「名称索引」**（供 hook 注入用 · 只读 + 写 1 个缓存）

为什么需要
    `UserPromptSubmit` 是 **awaited** 事件（`tools/aios-hook.py` 的 `PROMPT_TIMEOUT_S = 5s`，
    超时直接给用户加延迟）⇒ 注入侧**不能**每次实际 tokenize 5005 条技能。
    本脚本把「名称 token」预先算成索引 ⇒ 注入时只需加载 + 求交（<1s）。

索引内容（⛔ 只含公开元数据）
    `{id, name, cat, t:[名称有效 token]}` —— **只索引 `name` 字段**（这正是"名称硬门槛"用的那一段）

用法：python scratch/_zh_name_index_build.py
"""
import io
import json
import os
import sys
import time

# ── 路径解析（执行层自 `scratch/` 迁入 `tools/probes/` · 参数化）─────────
#    优先级：`AIOS_ROOT` 环境变量 ▸ 本文件位置（`<root>/tools/probes/`）▸ 工作目录。
#    ⛔ 不写死本机路径 ⇒ clone 到任意位置必须可用（`HANDOFF §四十五` 未清项之「参数化回流」）。
#    `AIOS_ROOT` 是**唯一**根来源；`TOOLS` 供 `import experience_push`（唯一一套打分 / 闸门规则）。
def _aios_root():
    env = os.environ.get("AIOS_ROOT")
    if env and env.strip():
        return os.path.abspath(env.strip())
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.dirname(os.path.dirname(here))
    if os.path.isfile(os.path.join(cand, "tools", "experience_push.py")):
        return cand
    return here


AIOS_ROOT = _aios_root()
PROBES = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(AIOS_ROOT, "tools")
# 运行期生成物（注册表缓存 / 名称索引 / 外部候选池 / 扩展语料）—— `.aios/` 不进版本库。
# 🔴 生成物一律落 `.aios/`：`_zh_skill_registry.json` 是**外部数据**（约 1.9 MB · 5005 条），
#    ⛔ 不随仓库发布 ⇒ 落在 `tools/probes/` 会被误提交（`.aios/` 才是它的家 · 见 `.aios/README.md`）。
CACHE = os.environ.get("AIOS_STATE_DIR") or os.path.join(AIOS_ROOT, ".aios")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
if PROBES not in sys.path:
    sys.path.insert(0, PROBES)

import experience_push as ep

SRC = os.path.join(CACHE, "_zh_skill_registry.json")
OUT = os.path.join(CACHE, "_zh_name_index.json")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not os.path.isfile(SRC):
        print("⚠️ 缺注册表缓存 `%s`" % SRC)
        return 1
    blob = json.load(io.open(SRC, "r", encoding="utf-8", errors="replace"))
    items = []
    for s in blob.get("skills") or []:
        name = ((s.get("name_zh") or "") + " " + (s.get("name") or "")).strip()
        eff, _noi = ep.split_hits(ep.tokenize(name))
        toks = sorted(eff)
        if not toks:
            continue
        items.append({"id": s.get("id"), "name": name, "cat": s.get("cat_zh") or "", "t": toks})
    out = {"source": "zh-name-index", "of": blob.get("version"),
           "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "n": len(items), "items": items}
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False)
    print("索引：**%d** 条 ⇒ `%s`（%.1f MB）"
          % (len(items), os.path.relpath(OUT, AIOS_ROOT), os.path.getsize(OUT) / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
