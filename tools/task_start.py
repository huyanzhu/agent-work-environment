#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
task_start.py — 开工视图 / 材料发现（大改最小实现 · D-009）

**职责收敛**（`AUTOMATION-BOUNDARY.md` §12.0.1 §12.2 §12.7① · 约定§12）：
三个时点的【输入】不同 ⇒ 职责不可合并：

    开工（无 prompt）  → **只做任务恢复**：有哪些卡可能要继续        ← 本工具**无参**时的输出
    进行时（有 prompt）→ **材料发现**：这一步有哪些经验/能力值得考虑 ← 本工具**带任务描述**时的输出（与 R4 同源判据）
    收尾               → 事实提取与持久化（`tools/wrapup_sync.py`）

依据：原「统一开工发现」把卡 + 知识 + 能力三者全送，而**开工时还不知道用户要做什么** ——
读数无 prompt 时能力 trigger **9/9 全命中**（bigram 无阈值）= 构造性噪声。
runtime 注入路径（`SessionStart`）只取 `recovery_text()`（R1）；`UserPromptSubmit`（R4）
与人工检索共用 `material_text()`（不另开第二套发现入口）。

消费语义（不变）：任务卡 = 恢复/继续；知识 = 读/采纳；能力 = 使用/装配。

知识检索复用 experience_push 的打分逻辑（同源，不重复实现）；任务卡走递归 active
扫描（补上"任务卡不入索引"缺陷）；能力来自 capabilities/INDEX.md。
**只读**，不修改任何文件。

空结果不静默（空态引导补全）：无 active 任务卡 / 知识未命中 /
能力 trigger 全未命中时，分别输出下一步引导（含可执行命令），替代静默空输出。
依据既有经验：空态必须有下一步（ui-beautification 空态门禁）、空结果即信号
、Next Action 要具体到物理动作（skill_pack_direction）。
"""
import argparse
import io
import json
import os
import re
import sys

from _root_guard import guard
guard(__file__)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import experience_push as ep

# 卡文件名的既有约定（与 `tools/wrapup_sync.py` 同源判据）：
# `TASK-<8位日期>-<3位序号>.md` 与 `T<3位序号>-<slug>.md` —— 不用 `TASK-*` 通配，
# 否则会把 `<卡>-OPERATIONS.md`（兜底日志）也算成卡（`样例账本.md` Entry #44 同型坑）。
CARD_NAME_RE = re.compile(r"^(?:TASK-\d{8}-\d{3}|T\d{3}-[^/]+)\.md$")
# 🔴 拆成「标准 v2 卡」与「v1 遗留」两个模式 —— v1 遗留（`T0xx-*.md`
#   46 张）**没有 State 字段**，把它们算进「张卡」会让开工提示系统性高估 35%（131 → 177）。
V2_CARD_NAME_RE = re.compile(r"^TASK-\d{8}-\d{3}\.md$")
V1_CARD_NAME_RE = re.compile(r"^T\d{3}-[^/]+\.md$")

# 材料发现的默认阈值（**首版值 · 无验证基线 · 待真实窗口验证**，不得当成已验证）
KNOW_MIN_SCORE = 8.0        # 经验命中阈值（knowledge() 默认 4.0 的两倍 —— 进行时预算更紧）
CAP_MIN_TRIGGER_HITS = 2    # 能力需 ≥2 个 trigger 词命中（单 bigram 命中噪声太大）
KNOW_BUDGET = 2             # 经验候选条数上限（§12.5：≤2 条经验）
CAP_BUDGET = 2              # 能力候选个数上限（§12.5：≤2 个能力）


def _full(p):
    """仓库相对路径 → **全文路径**（§12.2 R1 与 §12.5 R4 都要求"全文路径"）。

    已是绝对路径（盘符 / 根）的原样返回；否则以 ROOT 补全。统一 posix 分隔符，便于跨工具一致引用。
    """
    if not p:
        return p
    q = str(p).replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", q) or q.startswith("/"):
        return q
    return os.path.join(ROOT, q.replace("/", os.sep)).replace("\\", "/")


def _next_action(raw):
    """取卡内 `Next Action:` 字段（含其后的缩进续行）—— 收成一行的"下一步"。"""
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("Next Action:"):
            buf = [line.split(":", 1)[1].strip()]
            for cont in lines[i + 1:]:
                if cont.strip() and not cont[:1].isspace():
                    break
                buf.append(cont.strip())
            return " ".join(x for x in buf if x)
    return ""


def task_cards():
    """active/ 递归扫描任务卡（含项目卡），返回 (relpath, title, goal, next_action)。"""
    base = os.path.join(ROOT, "task_cards", "active")
    out = []
    if not os.path.isdir(base):
        return out
    for root, _dirs, files in os.walk(base):
        # 跳过 `node_modules` —— `active/` 下含完整前端仓库（读数 2.4 万+ 文件），
        #    而 `SessionStart` 的 hook 预算有限（`aios-hook.py` 的 `INJECT_TIMEOUT_S = 8s`）；
        #    任务卡不可能出现在依赖目录里。
        _dirs[:] = [d for d in _dirs if d != "node_modules"]
        for name in sorted(files):
            if not name.endswith(".md") or name.startswith("_"):
                continue
            p = os.path.join(root, name)
            try:
                raw = io.open(p, "r", encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            m = re.search(r"^#\s+(.+)$", raw, re.M)
            title = m.group(1).strip() if m else os.path.basename(p)
            gm = re.search(r"^##\s+Goal\s*\n(.*?)(?=^##\s|\Z)", raw, re.M | re.S)
            goal = re.sub(r"\s+", " ", gm.group(1)).strip()[:180] if gm else ""
            out.append((os.path.relpath(p, ROOT).replace("\\", "/"), title, goal, _next_action(raw)))
    return out


def knowledge(query_tokens, n=5, min_score=4.0):
    """复用 experience_push 的语料 / 账本打分 **与同一套相关性闸门**，
    返回 (score, kind, rel, title, effective_hits)。

    ⚠️ 阶段 3（约束：同一套规则必须共享）：判据与账本打分一律调 `ep.*`，
       本函数不再自带任何匹配 / 计分逻辑 —— 否则 `experience_push` 与 `task_start`
       会逐渐形成不一致的匹配规则。
    """
    results = []
    for kind, path in ep.collect_files():
        try:
            raw = io.open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        res = ep.score_file(query_tokens, raw)
        if res.score > 0 and ep.passes_gate(query_tokens, res):
            title = res.fm.get("title", "") or os.path.basename(path)
            results.append((res.score, kind, ep.disp_path(path), title, res.effective))
    for path, weight, header, text in ep.collect_ledger_chunks():
        res = ep.score_ledger_chunk(query_tokens, header, text)
        if res.score > 0 and ep.passes_gate(query_tokens, res):
            score = weight * res.score
            kind = "proven" if weight >= ep.PROVEN_LEDGER_WEIGHT else "ledger"
            results.append((score, kind, ep.disp_path(path), header or kind, res.effective))
    # （review 修复）：坑清单也进 task_start 的开工发现 —— 与 experience_push.search
    # 保持同一套语料；此前只接了 collect_files + ledger ⇒ 开工看不到 PITFALLS（–）。
    for path, weight, header, text in ep.collect_pitfall_chunks():
        res = ep.score_ledger_chunk(query_tokens, header, text)
        if res.score > 0 and ep.passes_gate(query_tokens, res):
            results.append((weight * res.score, "pitfall", ep.disp_path(path), header or "pitfall", res.effective))
# 注入摘要库（与 experience_push.search 同语料）
    for path, weight, header, text in ep.collect_digest_chunks():
        res = ep.score_ledger_chunk(query_tokens, header, text)
        if res.score > 0 and ep.passes_gate(query_tokens, res):
            results.append((weight * res.score, "digest", ep.disp_path(path), header or "digest", res.effective))
    results.sort(key=lambda r: -r[0])
    return [r for r in results if r[0] >= min_score][:n]


def capabilities(query_tokens):
    """解析 capabilities/INDEX.md 表格，返回 (name, hit, trigger, activation)。"""
    idx = os.path.join(ROOT, "capabilities", "INDEX.md")
    out = []
    if not os.path.isfile(idx):
        return out
    raw = io.open(idx, "r", encoding="utf-8", errors="replace").read()
    for line in raw.splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| #"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        name = cells[1] if len(cells) > 1 else cells[0]
        trig = cells[3] if len(cells) > 3 else ""
        act = cells[4] if len(cells) > 4 else ""
        eff, noi = ep.split_hits(query_tokens & ep.tokenize(trig))
        out.append((name, eff, noi, trig[:140], act[:140]))
    return out


def recovery_text():
    """R1 · **任务恢复**文本（runtime 注入 `SessionStart` 的载荷 · §12.2）。

    §12.0.1：开工时**还不知道用户要做什么** ⇒ 这里只回答「**去哪里找**当前的工作记忆」。
    经验 / 能力一律不送（那是进行时职责，见 `material_text`）。

    🔴 **形态收敛**：不再注入「最近 N 张卡的摘要」，改为
    **一句指令 + 目录 / 说明路径 + 三条动作 + 不确定就问**：
      · 理由判断能否走通的支点是「**用卡必留痕**」（`claim` / `release` /
        新建卡都会留痕）⇒ **Agent 自己找到并占用的卡**才是焦点卡的唯一真实来源；
        而「最近 3 张卡的摘要」只会把它引向**别人最近动过的卡**，且覆盖不到其余几十张。
      · 只保留一个**计数线索**（⛔ 不列任何卡内容）—— 避免「让去找、但目录里其实没卡」的空转。
      · `task_cards/README.md` 是使用方式 / 目录结构 / 纪律的唯一说明 ⇒ 这里**指向它，不复制**。
      · 「不确定 ⇒ 列出候选让用户选」= 把 `claim` 的**不猜**纪律显式交给 Agent
        （`GOAL-INPUT-CONTRACT.md` **S2**：`State` 是**占用声明** ⇒ Runtime / 脚本不自动改）。
    ⚠️ 体积：注入文本会被后续每个请求重发直到压缩（§12.2）⇒ 本形态 ≈ 原 1/3。

    ⚠️ `_mtime()` / `_clip()` **已随本次形态收敛删除**（它们只服务旧的"前 3 张卡摘要"）。
    """
    # 🔴 原来 `named` 把 v1 老命名 `T0xx-*.md` 也算卡 ⇒ 报「177 张卡」，
    #   而标准 v2 卡只有 131 张、那 46 张 v1 文件**连 State 字段都没有**。用户每次开工看到的就是这个假高数。
    #   ⇒ 分开数、都报出来（⛔ 不静默合并；也⛔ 不假装它们不存在）。
    all_cards = task_cards()
    v2_cards = [c for c in all_cards if V2_CARD_NAME_RE.match(os.path.basename(c[0]))]
    v1_leftover = [c for c in all_cards if V1_CARD_NAME_RE.match(os.path.basename(c[0]))]
    named = v2_cards
    base = os.path.join(ROOT, "task_cards", "active")
    folders = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))) if os.path.isdir(base) else []

    lines = ["【AI-OS · 工作记忆】请寻找适合本次工作的工作记忆（任务卡）。",
             "· 目录：`%s`" % _full("task_cards/active"),
             "· 说明与用法：`%s`" % _full("task_cards/README.md")]
    if named:
        extra = ("（另 %d 张 v1 老命名文件 `T0xx-*.md` 无 State 字段，不计入）" % len(v1_leftover)) if v1_leftover else ""
        lines.append("· 当前 active：**%d 张卡** · %d 个项目文件夹%s" % (len(named), len(folders), extra))
        lines.append("· 已有合适的卡 ⇒ `python tools/task_card.py claim <TASK-ID>` **声明占用**")
    else:
        lines.append("· 当前 active：**无卡**")
    lines.append("· 没有合适的 ⇒ `python tools/task_card.py create \"<标题>\"`")
    lines.append("· 不确定选哪张 ⇒ **列出候选**（标题 + Goal + Next Action）让用户选，⛔ 不替用户猜")
    lines.append("（⛔ 不占用就没有焦点卡 —— 恢复与检索都用不上；忽略本提示不影响继续工作。）")
    return "\n".join(lines)


def material_text(query_tokens, know_budget=KNOW_BUDGET, cap_budget=CAP_BUDGET,
                  min_score=KNOW_MIN_SCORE, min_trigger_hits=CAP_MIN_TRIGGER_HITS):
    """材料发现（进行时 · **R4 的同源判据**）：经验候选 + 能力候选。

    预算 ≤`know_budget` 条经验 + ≤`cap_budget` 个能力；**命中不足 ⇒ 返回空**（不硬凑候选）。
    只报候选 + 匹配原因 + 全文路径，**不写成"已采纳 / 已产生价值"** —— 判断归 Agent（§12.0.1 三方边界）。

    ⚠️ 阈值（`min_score` / `min_trigger_hits`）是**首版值**：无验证基线，**待真实窗口验证**，
    不得当成已验证（`§12.5` 只定了"阈值 + 预算"，没定具体数值）。
    """
    if not query_tokens:
        return ""
    # 阶段 3（约束 2 / 3）：低信息量查询（`继续` / `谢谢`）不触发材料发现。
    # 规则来自 `ep.query_has_signal` —— 与 CLI 入口共用，不另立一套。
    if not ep.query_has_signal(query_tokens):
        return ""
    lines = []

    hits = knowledge(query_tokens, n=know_budget, min_score=min_score)
    if hits:
        lines.append("【经验候选（读/采纳 · **非已采纳**）】")
        for score, kind, rel, title, matched in hits:
            lines.append("  - [%s] %.1f %s :: %s（有效命中 %s）"
                         % (kind, score, _full(rel), title, "/".join(sorted(matched)[:4])))

    caps = []
    qeff = len(ep.effective_query_tokens(query_tokens))
    for name, eff, _noise, trig, act in capabilities(query_tokens):
        # 阶段 3：只用【有效命中】计数 —— 噪声碎片不得触发能力候选；
        # 并加**命中密度**闸门（挡住"超长 query 匹配一切"，与经验候选同一阈值来源）
        if len(eff) < min_trigger_hits:
            continue
        if qeff > 0 and (len(eff) / float(qeff)) < ep.MIN_HIT_DENSITY:
            continue
        caps.append((len(eff), name, eff, act))
    caps.sort(key=lambda r: -r[0])
    if caps:
        lines.append("【能力候选（使用/装配 · **非已采纳**）】")
        for n_hit, name, overlap, act in caps[:cap_budget]:
            lines.append("  - %s（有效 trigger 命中 %d 个：%s）" % (name, n_hit, "/".join(sorted(overlap)[:4])))
            if act:
                lines.append("    activation: %s" % act)

    if not lines:
        return ""
    lines.append("（以上为 runtime 递送的**候选**；采纳与否由 Agent 判断 —— 未被采纳不影响本步继续。）")
    return "\n".join(lines)


# ── 开工自检（审计 /）────────────────────────────────
# 🔴 已读数（⛔ 不重新论证）：`.aios/` 被 gitignore ⇒ **新克隆默认零注入**；阶段注入块的
#   外层门还要求 `.aios/inject_probe.json` 存在**且带 `session` 字段**。v0.1.3 起发布物带
#   `.aios-sample/`（5 份开关 + README），但**忘记初始化的人不会收到任何提示** ⇒ 以为
#   "产品没用"。这里只在「发布物形态（有 `.aios-sample/`、没有 `.aios/`）」时**追加**提示：
#   · ⛔ 不递归报错（任何异常吞掉）· ⛔ 不退出非 0 · ⛔ 不改已有输出（只在末尾追加）。
SAMPLE_DIR = ".aios-sample"
AIOS_DIR = ".aios"
PROBE_FILE = "inject_probe.json"
PROBE_SESSION_KEY = "session"

_HINT_NO_AIOS = "\n".join([
    "=== 开工自检：本仓是发布物形态（有 .aios-sample/，没有 .aios/）===",
    "[!] 当前没有 .aios/  =>  能力注入不会发生（外层门要求 .aios/inject_probe.json）",
    "    初始化（一次即可，二选一）：",
    "      Windows: xcopy /E /I .aios-sample .aios",
    "      POSIX  : cp -r .aios-sample .aios",
    "    判据：初始化并重启后，会话里会出现「【AI-OS · 决策 · …能力】」",
])

_HINT_PROBE_NOT_READY = "\n".join([
    "=== 开工自检：.aios/ 在，但注入总闸未就绪（半初始化）===",
    "[!] 判据：注入发生要求 .aios/inject_probe.json 存在 **且** 带非空 session 字段",
    "    当前：.aios/inject_probe.json 缺失 / 解析失败 / session 为空 => 能力注入不会发生",
    "    修复：把 .aios-sample/inject_probe.json 复制到 .aios/，确保 \"session\" 非空后重启",
    "    判据：修复并重启后，会话里会出现「【AI-OS · 决策 · …能力】」",
])


def _probe_ready(base):
    """注入总闸是否**真的**可用：`.aios/inject_probe.json` 可解析为对象且 `session` 非空。

    只读；任何异常 ⇒ False（调用方据此提示，⛔ 不在这里报错）。
    """
    path = os.path.join(base, AIOS_DIR, PROBE_FILE)
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    session = data.get(PROBE_SESSION_KEY)
    return isinstance(session, str) and bool(session.strip())


def selfcheck_text(root=None):
    """发布物未初始化 / 半初始化 ⇒ 返回「开工自检」提示；否则返回 ""（正常仓 / 已就绪 ⇒ 零输出）。

    判据（只认**可验证的目录与文件事实**，不猜）：
      · `<root>/.aios-sample/` 不存在 ⇒ ""（不是发布物形态，⛔ 不误报）。
      · 有 `.aios-sample/`、无 `.aios/` ⇒ 未初始化（`_HINT_NO_AIOS`）。
      · 有 `.aios/`，但 `.aios/inject_probe.json` 缺失 / 非 JSON 对象 / `session` 为空
        ⇒ 半初始化（`_HINT_PROBE_NOT_READY`）：目录建了也不会注入，此前这条会被静默吞掉。
      · 有 `.aios/` 且总闸就绪 ⇒ ""（已初始化 ⇒ 零输出）。
    ⚠️ 本函数**只读**：不建目录、不写文件、不改退出码。
    """
    base = ROOT if root is None else root
    try:
        if not os.path.isdir(os.path.join(base, SAMPLE_DIR)):
            return ""
        if not os.path.exists(os.path.join(base, AIOS_DIR)):
            return _HINT_NO_AIOS
        if _probe_ready(base):
            return ""
    except OSError:  # 权限 / 怪路径 ⇒ 静默不提示（⛔ 不报错）
        return ""
    return _HINT_PROBE_NOT_READY


def _emit_selfcheck(root=None):
    """把自检提示追加到 stdout **末尾**（空提示 ⇒ 零输出）。

    ⚠️ 只是提示：包一层兜底，任何异常都**不得**影响主流程与退出码（⛔ 不"递归报错"）。
    """
    try:
        msg = selfcheck_text(root)
        if msg:
            print("\n" + msg)
    except Exception:  # noqa: BLE001 —— 提示失败必须静默（工具本来工作正常）
        return


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="AI-OS task-start view (read-only).")
    ap.add_argument("query", nargs="*", help="任务描述；给了 ⇒ 追加进行时的材料发现（经验/能力候选）")
    ap.add_argument("--auto", action="store_true",
                    help="从 git 状态 + 最近 active 任务卡意图派生查询（= 带描述的材料发现）")
    ap.add_argument("-n", type=int, default=KNOW_BUDGET, help="经验候选条数（默认 %d）" % KNOW_BUDGET)
    args = ap.parse_args()

    query = " ".join(args.query)
    if args.auto:
        auto = ep.auto_query()
        query = (query + " " + auto).strip() if query else auto
    qtokens = ep.tokenize(query)

    print("=== AI-OS 开工视图（task_start · 2026-10-09 职责收敛）===")
    print("查询: %s\n" % (query or "(空 —— 开工视图只做任务恢复；给了任务描述才做材料发现)"))

    print(recovery_text())

    if not qtokens:
        print("\n（进行时的材料发现**未触发**：本视图无任务描述。")
        print("  runtime 路径由 R4 在 `UserPromptSubmit` 上做；人工检索可加任务描述重跑，")
        print("  或 `python tools/experience_push.py \"<描述>\"`；能力入口 = 调 `auto_capability`（`what` 一句）⇒ 8 个领域词表。）")
        _emit_selfcheck()
        return 0

    print("\n--- 材料发现（进行时 · R4 同源判据 · 读/采纳）---")
    mat = material_text(qtokens, know_budget=args.n)
    if mat:
        print(mat)
    else:
        print("  （无候选命中 —— **空结果即信号**，不硬凑候选）")
        print("  下一步: 换更具体的任务描述重跑；或 `python tools/experience_push.py \"<描述>\"` 手工检索全文；")
        print("         能力入口 = `auto_capability`（what 一句 ⇒ 8 个领域词表）；真实踩坑/信念改变才沉淀 Observation，不硬写。")

    print("\n来源与消费语义：任务卡=恢复/继续；知识=读/采纳；能力=使用/装配。")
    _emit_selfcheck()
    return 0


if __name__ == "__main__":
    sys.exit(main())
