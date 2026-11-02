#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""_field_emit.py — 阶段 4 · **焦点对象字段的 JSON 出口**（只读 · 薄包装）

为什么存在
    `_runtime_field_producer.py` 的 CLI 输出是**人类可读文本 + JSON 混排**（给 判读用）
    ⇒ 不适合作**进程接口**。DSH 原生 Runtime（`runtime/aios-activation.ts`）需要机器可读的字段。

它做什么
    **只做一件事**：把已验证的 `produce_from_card()` 结果**原样**输出为一行 JSON。

🔴 纪律（逐条硬约束）
    · ⛔ **不新增任何判据** —— 对象 / 短语 / 类别 / 退化判定一律来自 `_runtime_field_producer`
    · **只读**：不写文件 · 不建缓存 · 不联网
    · **不落推理原文**：`reasoning` 只经 stdin 进**内存**做**交叉裁决**（卡定对象 · 推理只做
      验证），⛔ 不落盘 · 不回显 · 不进探针；`allow_reason_only=False`（默认）⇒ 推理**永不取代卡对象**
    · 输入非法 ⇒ 明确失败（`{"error": ...}` + 非零），⛔ **不猜**
    · 🔴 **输出必须走 `stdout.buffer` + UTF-8**：Windows 默认 stdout 编码是 GBK，
      `sys.stdout.write(中文)` 会写出 GBK 字节 ⇒ 调用方（Node `String(chunk)` 按 utf8 解码）
      拿到的是**乱码**，而乱码仍是**合法 JSON 字符串** ⇒ 不报错、只静默失败（实际踩到）。

stdin : {"card": "<repo-relative card path>", "reasoning": ["..."]?}
stdout: RuntimeField JSON（`_runtime_field_producer.py` §接口）＋ `_emit` 元信息
"""
import json
import os
import sys

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
for _p in (TOOLS, PROBES):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _runtime_field_producer as fp  # noqa: E402  （**唯一**字段产出实现）


def _out(payload):
    """一行 JSON ⇒ **UTF-8 字节**（不依赖 stdout 的 locale 编码）。"""
    sys.stdout.buffer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _fail(msg, detail=None, code=2):
    payload = {"error": msg}
    if detail is not None:
        payload["detail"] = str(detail)[:80]
    _out(payload)
    return code


def main():
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig") or "{}")
    except Exception as exc:
        return _fail("bad-input", exc)
    if not isinstance(payload, dict):
        return _fail("bad-input", "not-an-object")

    card = payload.get("card") or ""
    if not isinstance(card, str) or card.strip() == "":
        return _fail("no-card")

    rs = payload.get("reasoning") or []
    reason_texts = [str(t) for t in rs] if isinstance(rs, list) else []

    try:
        field = fp.produce_from_card(card, reason_texts=reason_texts or None)
    except Exception as exc:  # noqa: BLE001  —— 失败**如实分类**，不猜
        return _fail("produce-failed", type(exc).__name__, 1)

    field["_emit"] = {
        "schema": "runtime-field/v1",
        "card": card,
        "withReasoning": bool(reason_texts),
    }
    _out(field)
    return 0


if __name__ == "__main__":
    sys.exit(main())
