# -*- coding: utf-8 -*-
"""
task_card.py — task_cards 最小工具（V2 第一形态）

动作（create / list / archive / claim / release / takeover / states / capability / capability-timing）：
  create  <title> [--project=<项目名>] [--template=v1|v2|v3|v4]
                           -> 复制模板到 active/，命名 TASK-YYYYMMDD-NNN
                              （缺省 v4（单字段「使用的能力」）· 环境变量 AIOS_CARD_TEMPLATE 优先于 --template）
  list                     -> 列出 active/ 卡片
  archive <TASK-ID> [--confirm] -> 从 active/ 移到 archive/（仅当任务已完成且已获用户确认）
  claim <TASK-ID>        -> **显式占用**：Planning / Parked ⇒ Executing
  release <TASK-ID> --state=Parked|Completed -> **显式释放**：Executing ⇒ 指定状态（必填）
  takeover <TASK-ID> [--reason=…] -> **显式接管**：释放别人的占用 + 自己占用（一步留痕）
  states [--off-vocab]     -> **只读**列出各卡 State（含**缺失**与**值域外**写法 —— 状态校验）
  capability <TASK-ID> [--stage start|impl|close] --name <能力名|none> --why "<一句>"
                           -> **记录能力使用点** ⇒ 追加到同级 `.log`，并**覆盖**卡上
                              「## 使用的能力」节对应行；省略 `--stage` ⇒ 单字段 `能力` 行（v4 卡）
                              （v4 单字段卡给 `--stage` ⇒ 拒绝；旧三阶段卡才用 `--stage`）
  capability-timing <TASK-ID>
                           -> **只读**打印能力记录时间 / 该卡会话首次 edit 时间 /
                              「是否早于首次 edit」；三阶段卡另打三处明细与复用/阶段切换
                              （单字段卡打 `能力: <name>（<时间>）`；⛔ 不落盘）
  capability-hint <TASK-ID> [--stage start|impl|close]   [临时 · 实验辅助]
                           -> **只读**打印当前配置下该给 worker 看的能力提示（⛔ 不落盘、⛔ 不记账）
                              省略 `--stage` ⇒ 单字段卡口径（与 claim 一致）；显式给 stage 仍接受
                              （域合并后提示按**域**出，阶段不再改变文案）

🔴 占用语义（裁定 · `p0/RESPONSIBILITY-BOUNDARIES.md`）
  `State` **不是描述，而是显式占用声明**：想用一张卡就必须声明占用（`claim`）；结束就显式释放
  （`release`）。于是「焦点卡 = 被占用的那张」不再需要从 git 脏文件 / 最近修改时间 / 全局
  `Executing` 张数去猜。
  ⛔ 脚本**绝不自动推断**完成状态 —— 不依据测试结果、不依据 Turn 停止、不自动归档。
  `Completed` 只表示「已完成」，**归档仍是独立动作**（`archive --confirm`）。

安全条件（逐条硬约束）
  · `claim` 检查**全局是否已有别的卡处于 `Executing`** ⇒ 有则**拒绝并报告冲突**，
    ⛔ **不自动替其他卡释放**（同一 Worker 同时只能有一张 `Executing`，除非另有协调授权）。
  · 写入**原子化**（同目录 tmp + `os.replace`），且用 `newline=""` **原样保留换行** ——
    卡的其它内容**一字不动**。
  · 只替换 `State:` 行的**值**；原值若带附加说明（如 `Executing —— 真实工作窗口（…）`），
    会在输出里**明确报告已被移除**（请移入 `Notes` / `Current Step`）—— 不静默丢内容。
  · `--dry-run` 可无副作用预览。

不做：自动推断字段 / 自动改状态 / 自动生命周期 / 自动分析内容 / telemetry / 与 CURRENT_GOAL 同步。
原则：最小工具降低使用摩擦，内容和行为保持真实。

安全条件（逐条硬约束）
  · **占用互斥按卡、不按全局**：`claim` ⛔ 不因"别处已有 `Executing`"而拒绝（只打印提示）；
    同一张卡被重复占用仍由 `cur == "Executing"` 拦住。不同对话可并行推进不同任务。
  · **ID 唯一性按项目、不按全局**：`_next_id(project=...)` 只在该项目目录内递增
    （`active/<proj>/` + `archive/<proj>/`）；跨项目重名时 `claim` / `release` / `archive`
    支持 `<项目>/TASK-ID` 定位；裸 ID 遇重名 ⇒ **报错并列出候选路径**（⛔ 仍不猜）。
  · **占用留痕持久化**：`claim` / `release` 成功后向**同级 `.log`** 追加一行（含**会话 id**，
    取 `DSH_SESSION_ID`）；**只追加、⛔ 改卡**。理由：占用只活在 Runtime **内存**里 ⇒
    换会话 / 重启即丢（**孤儿占用**不可追溯，还会挡住后续 `claim`）。
    ⛔ **不新增字段**（守 Freeze）· ⛔ 裁剪逻辑不在这里 —— 容量上限与溢出兜底
    `<TASK-ID>-OPERATIONS.md` 仍由 `tools/wrapup_sync.py`（`EVENT_LOG_MAX_ROWS`）统一处理。
  · **只有占用者能 `release`**（排他性是硬约束，⛔ 不靠自觉）；`takeover` = 一步完成
    「释放别人的占用 + 自己占用」，必须留痕。
  · **归档门槛**：仅当任务已完成**且**已获用户确认（`archive --confirm`）；⛔ 自动推断完成。

`claim` 尾部的能力提示
  由 `.aios/cap-cells.json` 的 `claimHint`（`off` 缺省 / `generic` / `cell`）控制；
  `off` ⇒ 输出**逐字不变**。理由：阶段注入**永远晚于**它想影响的决策 ——
  `claim → 选能力 → turn 结束 → post-execute 才注入` ⇒ 注入到达时本阶段记录已写完
  ⇒ 把提示放到 **`claim` 的 stdout**（开工之前、且是**工具返回**而不是 notice）。

卡形态（两种并存）
  · **单字段卡（缺省模板）**：卡上写 `- 能力: <name> ｜ why`；`capability` 省略 `--stage`
    ⇒ `.log` 写一条 `能力` 行。单字段卡给 `--stage` ⇒ 拒绝。
  · **三阶段卡**：`## 使用的能力（三阶段 · 可 none）` 节，`capability` 子命令仍写 `.log`
    （格式逐字不变），并**覆盖**卡上对应阶段行（⛔ 不追加）。卡上没有该节 ⇒ 只写 `.log`、
    ⛔ 不报错、⛔ 不自动加节。旧模板仍可显式 `--template v1|v2|v3` 建卡（保旧行为）。
"""

import json
import os
import re
import shutil
import sys
from datetime import date, datetime

from _root_guard import guard
guard(__file__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS_DIR = os.path.join(ROOT, "task_cards")
ACTIVE_DIR = os.path.join(CARDS_DIR, "active")

def _project_problem(project):
    """`--project` 的合法性判据 → (规范化后的目录名 | None, 错误文案 | None)。

    🔴 `--project` 原来是**裸拼** `os.path.join(ACTIVE_DIR, project)`：
      · `--project=../../x` ⇒ 建到 active/ 之外；
      · `--project=D:/evil` ⇒ 绝对路径**直接替换**基目录 ⇒ 写到仓外（读数成立）。
    ⇒ 现在按「名字」而不是「路径」对待：只允许单段安全目录名。
    """
    if project is None:
        return None, None
    name = str(project)
    if not name.strip():
        return None, "项目名不能为空"
    if os.path.isabs(name) or (len(name) > 1 and name[1] == ":"):
        return None, "项目名不能是绝对路径（含盘符 / UNC）：%r" % name
    if name in (".", "..") or ".." in name.replace("\\", "/").split("/"):
        return None, "项目名不能含 `..` 路径段：%r" % name
    if "/" in name or "\\" in name:
        return None, "项目名不能含路径分隔符：%r" % name
    if any(ch in name for ch in '<>:"|?*') or any(ord(ch) < 32 for ch in name):
        return None, "项目名含非法字符（<>:\"|?* 或控制字符）：%r" % name
    if name != name.strip() or name.rstrip(".") != name:
        return None, "项目名不能有前导/尾随空格或尾随点：%r" % name
    # ④ 兜底：规范化后必须仍在 ACTIVE_DIR 之下
    try:
        final = os.path.normpath(os.path.join(ACTIVE_DIR, name))
        common = os.path.commonpath([os.path.abspath(final), os.path.abspath(ACTIVE_DIR)])
    except ValueError:
        return None, "项目名无法规范化：%r" % name
    if os.path.abspath(common) != os.path.abspath(ACTIVE_DIR):
        return None, "项目名会越出 task_cards/active：%r" % name
    return name, None


ARCHIVE_DIR = os.path.join(CARDS_DIR, "archive")
TEMPLATE = os.path.join(CARDS_DIR, "_TASK_CARD_template.md")
# （A/B）：能力区前置版模板 —— `create --template v2` 用它；**缺省已改为 v4**。
TEMPLATE_V2 = os.path.join(CARDS_DIR, "_TASK_CARD_template.v2.md")
# （v3）：卡上带「使用的能力」字段块 —— 由 `capability` 子命令同步填值。
TEMPLATE_V3 = os.path.join(CARDS_DIR, "_TASK_CARD_template.v3.md")
# （v4）：**单字段**「使用的能力」（不需要阶段）—— `--stage` 可省略。
TEMPLATE_V4 = os.path.join(CARDS_DIR, "_TASK_CARD_template.v4.md")
#: 模板选择器：环境变量优先于命令行（任务书明确「env 优先」）⇒ 见 `resolve_template_version()`。
TEMPLATE_VERSIONS = ("v1", "v2", "v3", "v4")
TEMPLATE_ENV = "AIOS_CARD_TEMPLATE"
#: Runtime 的 tool-signature 探针（只读）：`capability-timing` 用它取该会话**首次 edit** 时间。
#: 与 `tools/probes/_capability_choice_lint.py: PROBE` 同一文件、同一行格式（⛔ 不另立一套）。
PROBE_LOG = os.path.join(ROOT, ".aios", "_aios-activation.probe.log")
CAPS_DIR = os.path.join(ROOT, "capabilities")

# ── 能力使用点（已确认口径）：写**结构化 .log 行**，⛔ 不写卡正文 ──────
#   理由：卡正文是自由文本，正则只能猜格式（读数已出现假红）⇒ 由**脚本**写表格行，
#   格式永远正确、时间戳自动；只对**新卡**生效（旧卡不补记）。
#: stage ⇒ `.log` 的 State 列取值（与既有 4 列表格同构：Time | State | Reason | Changed By）
CAPABILITY_STAGES = {"start": "能力-开工", "impl": "能力-实现", "close": "能力-收尾",
                     # 卡改为**单字段**「使用的能力」（不需要阶段）
                     #   `--stage` 可省略 ⇒ 记一条 `能力` 行，卡上只有一行 `- 能力: `X` ｜ why`
                     "once": "能力"}
# `capability-hint` **可显式指定**的阶段（🔴 v4：省略 `--stage` 合法 ⇒ 单字段口径）。
#: 与 `CAPABILITY_STAGES` 分开：`once` 是内部单字段哨兵，⛔ 不接受用户在命令行显式传 `--stage once`。
CAPABILITY_HINT_STAGES = ("start", "impl", "close")
#: 明确不算理由的写法（空泛 ⇒ ⛔ 不写；`none` 也要写清为什么不需要能力）
VAGUE_WHY = {"不需要", "无需", "暂无", "不适用", "没有", "无", "na", "n/a",
             "none", "不需要能力", "没有能力"}

# ── State 值域（与 `_TASK_CARD_template.md` 同步 · 状态校验的唯一来源）────────────────
#   `Parked`（新增）= **暂停但未完成、可以恢复** ——
#   与 `Planning`（尚在规划、尚未开始）/ `Waiting_`（等待人的动作）**不是同一件事**。
STATES = ("Created", "Planning", "Executing", "Parked", "Blocked",
          "Waiting_Human", "Reviewing", "Completed", "Archived")
#: `claim` 允许的**起始**状态（可显式开始 / 恢复）
#  🔴 （真修复）：`Created` 也接受 —— 老卡（模板旧行为）停在 Created 时不再"必须手工改卡再 claim"；
#  同时 `cmd_create` 改为直接写 `Planning`（新卡开箱可 claim）。
CLAIMABLE = ("Created", "Planning", "Parked")
#: `release` 允许的**目标**状态（必须由调用者显式指定；⛔ 无默认值）
RELEASABLE_TO = ("Parked", "Completed")

CARD_NAME_RE = re.compile(r"^TASK-\d{8}-\d{3}\.md$")
STATE_LINE_RE = re.compile(r"^(State:[ \t]*)(.*)$", re.M)


def _next_id(prefix="TASK", project=None, skip=()):
    """生成 `TASK-YYYYMMDD-NNN`（**可跳过已被占用的号** —— 供原子创建重试）。

    约定ID 唯一性**按项目**保证（⛔ 不按全局）——
    指定 `project` 时只在该项目目录内递增（`active/<project>/` + `archive/<project>/`），
    因此不同项目可以各自有同日 `001`；跨项目重名时用 `_find_card` 的「项目/ID」形式定位。

    🔴 （审计）：只扫目录算 max+1 是**非原子**的 —— 并发 create 会撞号并静默覆盖。
       ⇒ 本函数支持 `skip`，由 `cmd_create` 用 `open(..., "x")` 抢占并在冲突时重试。
    """
    today = date.today().strftime("%Y%m%d")
    pattern = re.compile(rf"^{prefix}-{today}-(\d{{3}})\.md$")
    dirs = ((os.path.join(ACTIVE_DIR, project), os.path.join(ARCHIVE_DIR, project))
            if project else (ACTIVE_DIR, ARCHIVE_DIR))
    max_n = 0
    for d in dirs:
        if os.path.isdir(d):
            for f in os.listdir(d):
                m = pattern.match(f)
                if m:
                    max_n = max(max_n, int(m.group(1)))
    n = max_n + 1
    while f"{prefix}-{today}-{n:03d}" in set(skip):
        n += 1
    return f"{prefix}-{today}-{n:03d}"


# ── 卡的读 / 定位 / 写（占用与状态校验共用）──────────────────────────────────────

def _read(path):
    """读卡文本 —— `newline=""` **原样保留换行**（卡里多为 CRLF，⛔ 不得因一次状态改写而换掉）。"""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _atomic_write(path, text):
    """同目录 tmp + `os.replace` ⇒ 原子替换，且保留原换行风格。"""
    tmp = os.path.join(os.path.dirname(path), "." + os.path.basename(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


#: 卡 Header 的创建时间（缺时间部分 ⇒ 按 00:00；与 lint 的 `card_created_at` 同口径）
_CARD_CREATED_RE = re.compile(
    r"^\s*Created:\s*(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", re.M)


def card_created_at(card_path):
    """卡 Header 的 `Created:` ⇒ `datetime`（不可解析 / 缺失 ⇒ `None`；⛔ 不猜）。

    只给 `capability-timing` 判"首次 edit 是否可能属于本卡"用（v4 单字段）。
    """
    m = _CARD_CREATED_RE.search(_read(card_path)[:8000])
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        int(m.group(4) or 0), int(m.group(5) or 0))
    except ValueError:
        return None


def _iter_cards():
    """active/ 下**递归**的全部卡（判据 = `CARD_NAME_RE` ⇒ `-OPERATIONS.md` 这类派生件不算卡）。"""
    out = []
    for root, _dirs, files in os.walk(ACTIVE_DIR):
        for n in sorted(files):
            if CARD_NAME_RE.match(n):
                out.append(os.path.join(root, n))
    return sorted(out)


def _rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _find_card(task_id):
    """TASK-ID ⇒ (卡路径, 错误)。支持两种写法：

    · `TASK-YYYYMMDD-NNN`        —— **全局唯一**才可确定；跨项目重名 ⇒ 拒绝并提示用路径形式
    · `<项目>/TASK-YYYYMMDD-NNN` —— 跨项目重名时**唯一定位**
    """
    task_id = (task_id or "").removesuffix(".md")
    if "/" in task_id or "\\" in task_id:
        # 🔴 （审计）：原实现用**后缀匹配**（`_rel(p).endswith(rel)`）⇒
        #   两个项目名互为后缀时（如 `验证/` 与 `设备名验证/` 各有同 ID 卡）路径写法**必然歧义**，
        #   连报错里"请写更完整"也救不了自己。⇒ 改为**按父目录逐段精确比较**。
        rel = task_id.replace("\\", "/").lstrip("/")
        if not rel.endswith(".md"):
            rel += ".md"
        want_dir, want_name = (rel.rsplit("/", 1) if "/" in rel else ("", rel))
        hits = []
        for p in _iter_cards():
            if os.path.basename(p) != want_name:
                continue
            r = _rel(p)
            r_dir = r.rsplit("/", 1)[0] if "/" in r else ""
            # 允许 `项目/ID` 或 `active/项目/ID` 两种写法：按**末尾段**精确比较
            if r_dir == want_dir or r_dir.endswith("/" + want_dir):
                hits.append(p)
        if len(hits) == 0:
            return None, "按路径未找到：%s" % task_id
        if len(hits) > 1:
            return None, "路径命中多张卡 ⇒ 请写更完整：%s" % ", ".join(_rel(p) for p in hits)
        return hits[0], None
    if not CARD_NAME_RE.match(task_id + ".md"):
        return None, "ID 格式不是 TASK-YYYYMMDD-NNN：%s" % task_id
    hits = [p for p in _iter_cards() if os.path.basename(p) == task_id + ".md"]
    if len(hits) == 0:
        return None, "active/ 下未找到：%s" % task_id
    if len(hits) > 1:
        # 🔴 （体验修复）：不只说"重名"，直接给**可复制的候选命令**。
        cands = ", ".join(_rel(p) for p in hits)
        cp = [os.path.relpath(p, ACTIVE_DIR).replace("\\", "/").removesuffix(".md") for p in hits]
        return None, ("ID 在多个项目下重名 ⇒ 用「项目/ID」定位。\n"
                      "  候选：%s\n"
                      "  例：python tools/task_card.py claim %s"
                      % (cands, cp[0]))
    return hits[0], None


def _state_raw(text):
    """`State:` 行的**原值**（未取 token）；无该行 ⇒ None。"""
    m = STATE_LINE_RE.search(text)
    return m.group(2) if m else None


def _state_value(raw):
    """`State` 的**首个 token**（值域是单 token）—— 兼容 `Executing —— 说明` 这类历史写法。"""
    s = (raw or "").strip()
    return s.split()[0] if s else ""


def _set_state_text(text, new_state):
    """只替换 `State:` 行的值 ⇒ (新文本, 原值 or None)。⛔ 卡的其他内容一字不动。"""
    m = STATE_LINE_RE.search(text)
    if not m:
        return None, None
    old_raw = m.group(2)
    new_text = text[:m.start(2)] + new_state + text[m.end(2):]
    return new_text, old_raw


def _note_removed(old_raw, new_state):
    """原值里**值的首个 token 之后**的附加说明 ⇒ 如实报告（⛔ 不静默丢内容）。

    ⚠️ 切片必须按**原值**的首 token 长度算，⛔ **不是** `new_state` 的长度 ——
    后者会把 `Executing`（9 字符）按 `Parked`（6 字符）切出残片 `ing`（实际踩到）。
    """
    s = (old_raw or "").strip()
    if not s:
        return ""
    old_val = s.split()[0]
    extra = s[len(old_val):].strip()
    if not extra:
        return ""
    return ("\n  ⚠️ 原 State 行含附加说明，**已移除**：%s\n"
            "     ⇒ 原文已留档于 `scratch/_state_release_20261012.json`；"
            "如需保留请把它移入 `Notes` / `Current Step`（`State` 只写值本身）" % extra)


def _executing_elsewhere(keep_path):
    """全局**其他**处于 `Executing` 的卡 —— **只读提示**，不再作为阻断判据。

    约定占用互斥应**按卡**、不按全局 —— 同一张卡不能被重复占用
    （由 `cmd_claim` 的 `cur == "Executing"` 拦住），但不同对话可以各占不同的卡
    （读数场景：求职准备卡与产品开发卡并行推进）。
    """
    out = []
    for p in _iter_cards():
        if os.path.abspath(p) == os.path.abspath(keep_path):
            continue
        if _state_value(_state_raw(_read(p))).lower() == "executing":
            out.append(p)
    return out


# ── 占用留痕把「谁在占用」写进卡内已有的 Event Log ──────────
#   需求：`State=Executing` 是**全局**事实（任何会话都能看到），而"**本对话**占用了它"是
#   **会话级**事实。后者此前只存在 Runtime 内存 ⇒ 换会话 / 重启即丢 ⇒ 孤儿占用不可追溯。
#   ⛔ 不新增字段（Freeze）；⛔ 不在这里裁行数（那是 `wrapup_sync.py` 的唯一职责）。

EVENT_LOG_RE = re.compile(r"^(##[ \t]+Event Log[^\n]*\n)(.*?)(?=^##[ \t]|\Z)", re.M | re.S)

# ── 🔴 **日志外置**「给它整到卡外面 · 跟卡片同级 · 名字就跟卡一样」──
#   理由（PITFALLS 读数）：日志留在卡里 ⇒ ① 卡越来越长，Runtime 的"读尾部"判据被挤出窗口
#     （占用 / 焦点卡 / stage4 / R3 **全部静默失效 · 零报错**）② 快照与流水混在一起。
#   ⇒ **卡 = 快照**（Goal / Status / Next Action · 永远短）· **日志 = 流水**（同目录同 stem · `.log`）。
#   兼容：旧卡**首次被写时自动迁移**（卡内表格行 → `.log`，卡内段变**指针**）；未迁移的旧卡，
#     Runtime 仍回退读卡内段（双读）。
EVENT_LOG_MAX_LINES = 200


def _session_id():
    """当前会话 id（供 Event Log 记录**谁占用**）。取不到 ⇒ `-`（fail-open，⛔ 不阻塞占用）。"""
    for k in ("DSH_SESSION_ID", "CLAUDE_SESSION_ID"):
        v = os.environ.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return "-"


def _event_log_path(card_path):
    """卡路径 ⇒ **同级同名**日志路径（`X.md` → `X.log`）。"""
    if card_path.lower().endswith(".md"):
        return card_path[:-3] + ".log"
    return card_path + ".log"


def _current_occupant(card_path):
    """当前占用者 session（读**外置日志**最后一条 claim/release · 回退卡内段）。

    返回空串 = **无人占用**（最后一条是 release，或没有任何留痕）。
    判据与 Runtime 的 `lastOccupancyOf()` **同源**（同一行格式），⛔ 不另立一套。
    """
    rows = []
    lp = _event_log_path(card_path)
    if os.path.isfile(lp):
        try:
            rows = _read(lp).split("\n")
        except OSError:
            rows = []
    if not rows:
        m = EVENT_LOG_RE.search(_read(card_path))
        rows = m.group(2).split("\n") if m else []
    for ln in reversed(rows):
        mm = re.search(r"(claim 占用|release 释放)（session:\s*([^）]*)）", ln)
        if mm:
            return mm.group(2).strip() if mm.group(1).startswith("claim") else ""
    return ""


def _event_log_header():
    return "| Time | State | Reason | Changed By |\n|------|-------|--------|:----------:|\n"


def _event_log_rows(raw):
    """从日志/卡段文本里取**数据行**（去掉表头与分隔线）。"""
    out = []
    for ln in str(raw or "").split("\n"):
        s = ln.strip()
        if not s.startswith("|"):
            continue
        if s.startswith("|------") or "Changed By" in s:
            continue
        out.append(ln.rstrip())
    return out


def append_event_log_line(card_path, state, reason):
    """向**外置日志**追加一行（建表头 · 裁剪最旧 · 原子写）。⛔ 不碰卡文件。"""
    log_path = _event_log_path(card_path)
    existing = []
    if os.path.isfile(log_path):
        try:
            existing = _event_log_rows(_read(log_path))
        except OSError:
            existing = []
    row = "| %s | %s | %s | Worker |" % (datetime.now().strftime("%H:%M"), state, reason)
    rows = existing + [row]
    if len(rows) > EVENT_LOG_MAX_LINES:
        rows = rows[-EVENT_LOG_MAX_LINES:]
    _atomic_write(log_path, _event_log_header() + "\n".join(rows) + "\n")


def _migrate_event_log_to_file(text, card_path):
    """把卡内 `## Event Log` 的**表格行**迁到外置日志，并把卡内该段替换为**指针**。

    幂等：没有该段 / 已是指针 ⇒ 结构仍收敛到同一指针（不重复迁行）。
    ⛔ 不丢行：卡内行 + 既有日志行**合并去重**（保持顺序）。
    """
    m = EVENT_LOG_RE.search(text)
    if m is None:
        return text
    card_rows = _event_log_rows(m.group(2))
    log_path = _event_log_path(card_path)
    existing = []
    if os.path.isfile(log_path):
        try:
            existing = _event_log_rows(_read(log_path))
        except OSError:
            existing = []
    rows = existing + [r for r in card_rows if r not in existing]
    if len(rows) > EVENT_LOG_MAX_LINES:
        rows = rows[-EVENT_LOG_MAX_LINES:]
    _atomic_write(log_path, _event_log_header() + "\n".join(rows) + "\n")
    name = os.path.basename(log_path)
    pointer = (
        "## Event Log — 已外置\n\n"
        "> 本卡的占用 / 收尾留痕已移到**同级同名文件** `" + name + "`（快照与流水分离 · 2026-10-28）。\n"
        "> ⛔ 本段不再追加；要查占用 / 收尾看那个 `.log`。\n\n"
    )
    return text[:m.start()] + pointer + text[m.end():]


def _append_event_log(text, state, reason, card_path):
    """把一条留痕写进**外置日志**，并把卡内 `## Event Log` 迁成指针 ⇒ `(新文本, 是否成功)`。

    从"写卡内表格"改为"写同级 `.log`"（根治）。
    """
    try:
        new_text = _migrate_event_log_to_file(text, card_path)
        append_event_log_line(card_path, state, reason)
        return new_text, True
    except OSError:
        return text, False


def _report_event_log(logged):
    if logged:
        print("  📌 Event Log 已追加留痕（**外置**：同级同名 `.log` · 含 session id ⇒ 占用可追溯）")
    else:
        print("  ⚠️ 外置日志写入失败 ⇒ **未追加留痕**（占用本身已生效，但**不可追溯**）")


# ── 既有动作 ──────────────────────────────────────────────────────────────────

# ── 模板选择（A/B → v3 · 缺省改 v4）：`--template v1|v2|v3|v4` + env 优先 ──
#   判据：缺省 v4（单字段「使用的能力」）；显式 v1 ⇒ 旧行为逐字不变；v2 ⇒ 能力节在 Current Status 之后、Outcome 之前；
#   模板缺失 ⇒ 明确报错，⛔ 不静默回落（否则 A/B 的 B 组会悄悄退化成 A 组且零报错）。

def template_path(version):
    """`v1|v2|v3|v4` ⇒ 模板绝对路径（调用方先经 `resolve_template_version()` 校验）。"""
    if version == "v1":
        return TEMPLATE
    if version == "v2":
        return TEMPLATE_V2
    if version == "v4":
        return TEMPLATE_V4
    return TEMPLATE_V3


def resolve_template_version(cli_value=None):
    """⇒ `(version, error)`。优先序：**`AIOS_CARD_TEMPLATE`（env）> `--template` > 缺省 v4**。

    🔴 缺省从 v1 改为 **v4**（单字段「使用的能力」）；
    显式 `--template v1|v2|v3` 仍可用（保旧行为）。

    空串 / 纯空白 ⇒ 视为未设置（shell 里 `AIOS_CARD_TEMPLATE=` 不该把建卡弄坏）；
    非法值 ⇒ 明确报错（⛔ 不回落：静默回落会让选了模板的人静默用错模板）。
    """
    env_raw = os.environ.get(TEMPLATE_ENV)
    env_set = env_raw is not None and bool(env_raw.strip())
    source = TEMPLATE_ENV if env_set else "--template"
    raw = env_raw if env_set else cli_value
    if raw is None or not str(raw).strip():
        return "v4", ""
    version = str(raw).strip().lower()
    if version not in TEMPLATE_VERSIONS:
        return None, ("`%s` 只能是 %s（收到：`%s`；优先序：%s > --template > 缺省 v4）"
                      % (source, " / ".join(TEMPLATE_VERSIONS), raw, TEMPLATE_ENV))
    return version, ""


def cmd_create(title, project=None, template=None):
    version, err = resolve_template_version(template)
    if err:
        print("[task_card] ⛔ 参数错误：%s" % err)
        return 1
    tpl_path = template_path(version)
    if not os.path.isfile(tpl_path):
        print("[task_card] ⛔ 模板缺失（--template=%s）：%s" % (version, tpl_path))
        print("  ⇒ 未落卡（⛔ 不静默回落其它模板；请先补齐该模板）")
        return 1
    project, perr = _project_problem(project)
    if perr:
        print("[task_card] ⛔ 参数错误：%s" % perr)
        print("  ⇒ 未落卡（项目名只允许单段安全目录名；⛔ 不接受路径）")
        return 1
    skip_ids = set()
    task_id = _next_id(project=project, skip=skip_ids)
    target_dir = os.path.join(ACTIVE_DIR, project) if project else ACTIVE_DIR
    if project:
        os.makedirs(target_dir, exist_ok=True)
    # **原子创建** —— 用 "x" 模式抢占文件名；冲突即重算 ID（最多 5 次），
    #   ⛔ 绝不覆盖已有卡（旧实现 open(...,"w") 并发时会静默覆盖，卡直接消失）。
    for _attempt in range(5):
        target = os.path.join(target_dir, f"{task_id}.md")
        try:
            _fd = open(target, "x", encoding="utf-8")
        except FileExistsError:
            task_id = _next_id(project=project, skip=skip_ids | {task_id})
            skip_ids.add(task_id)
            continue
        else:
            _fd.close()
            break
    else:
        print("[task_card] ⛔ 建卡失败：连续 5 次 ID 冲突（并发过多？）⇒ 未落卡")
        return 1
    with open(tpl_path, "r", encoding="utf-8") as src:
        content = src.read()
    # 仅替换最表面的 Task ID 示例，不推断任何其他字段
    content = content.replace("TASK-YYYYMMDD-001", task_id)
    content = content.replace("YYYY-MM-DD HH:mm", datetime.now().strftime("%Y-%m-%d %H:%M"))
    # 🔴 （真修复）：模板的 `State:` 行是**值域菜单**（`Created | Planning | ...`），
    #   `_state_value` 会取首个 token = `Created` ⇒ 新卡无法 claim（旧行为：必须手工改成 Planning）。
    #   ⇒ create 直接落 `Planning`（新卡开箱可 claim；`claim` 同时兼容老卡 `Created`）。
    content = STATE_LINE_RE.sub(lambda m: m.group(1) + "Planning", content, count=1)
    if title:
        content = content.replace("# TASK_CARD", f"# TASK_CARD — {title}")
    with open(target, "w", encoding="utf-8") as dst:
        dst.write(content)
    print(f"[task_card] created: {task_id}  ({target})")
    # 🔴 （归因读数）：`--project` 是**可选**参数，缺省落 `active/` **顶层**。
    #   后果：11 月 83 张平铺卡（当时全量的 6 成）⇒ 按项目归档/检索全被噪音拖垮；
    #   而任务书普遍只写 `create "<标题>"`（不带 `--project`）⇒ 无声落顶层。
    #   ⇒ 不强制拒绝（会破坏历史脚本/测试），但**必须醒目提示**，让人当场改。
    if not project:
        print("[task_card] \u26a0\ufe0f  未给 --project ⇒ 本卡落在 active/ 顶层（无法按项目归档 / 检索）")
        print("            建议：python tools/task_card.py create \"<标题>\" --project=<项目名>")
        print("            现有项目：%s" % " · ".join(sorted(
            e for e in os.listdir(ACTIVE_DIR) if os.path.isdir(os.path.join(ACTIVE_DIR, e)))))
    # 缺省 v4 ⇒ 多一行（一眼看出用了哪套模板）；显式 v1 ⇒ 输出逐字不变（A 组对照）。
    if version != "v1":
        print(f"[task_card] template: {version}  ({_rel(tpl_path)})")
    return 0


def cmd_list():
    """列出 active：项目文件夹（目录名天然可关联）+ 卡片（TASK-ID + 标题/Goal 摘要）。"""
    entries = sorted(e for e in os.listdir(ACTIVE_DIR) if not e.startswith("."))
    dirs = [e for e in entries if os.path.isdir(os.path.join(ACTIVE_DIR, e))]
    files = [e for e in entries if os.path.isfile(os.path.join(ACTIVE_DIR, e))]
    if not entries:
        print("[task_card] active: (none)")
        return 0
    print("[task_card] active:")
    for d in dirs:
        print(f"  {d}/  —  [项目文件夹]")
    for f in files:
        print(f"  {f}  —  {_card_summary(f.removesuffix('.md'))}")
    return 0


def _card_summary(task_id):
    """读卡文件，返回标题（# TASK_CARD — xxx）；无标题则取 Goal 首行；均无则标注。"""
    path = os.path.join(ACTIVE_DIR, f"{task_id}.md")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            fallback = None
            in_goal = False
            for line in fh:
                s = line.strip()
                if s.startswith("# TASK_CARD"):
                    rest = s.replace("# TASK_CARD", "", 1).strip(" —-\t")
                    if rest:
                        return rest
                    fallback = "(untitled)"
                    continue
                if s == "## Goal":
                    in_goal = True
                    continue
                if in_goal:
                    if s.startswith("## ") or s.startswith("```"):
                        if s.startswith("## "):
                            break
                        continue
                    if s:
                        return s[:90]
            return fallback or "(untitled)"
    except OSError:
        return "(unreadable)"


def cmd_archive(task_id, confirm=False):
    task_id = task_id.removesuffix(".md")
    src = os.path.join(ACTIVE_DIR, f"{task_id}.md")
    if not os.path.isfile(src):
        print(f"[task_card] not found in active: {task_id}")
        return 1
    if not confirm:
        print(
            "[task_card] 归档被拒绝：归档 = 任务已完成且已获用户确认。\n"
            "  - 若任务/项目尚未完成（例如阶段一完成、后续还有阶段），请保持 active，不要归档。\n"
            "  - 确认已完成并已获用户确认后，重新运行：\n"
            "      python tools/task_card.py archive <TASK-ID> --confirm"
        )
        return 1
    dst = os.path.join(ARCHIVE_DIR, f"{task_id}.md")
    if os.path.isfile(dst):
        print(f"[task_card] 归档目标已存在，拒绝覆盖：{dst}（请先处理冲突）")
        return 1
    shutil.move(src, dst)
    print(f"[task_card] archived: {task_id}（已确认：任务完成 + 用户确认）")
    return 0


# ── 占用：claim / release───────────────────────────────

def cmd_claim(task_id, dry_run=False):
    """**显式占用**：`Planning` / `Parked` ⇒ `Executing`。"""
    path, err = _find_card(task_id)
    if err:
        print(f"[task_card] claim 被拒绝：{err}")
        return 1
    text = _read(path)
    raw = _state_raw(text)
    if raw is None:
        print(f"[task_card] claim 被拒绝：{_rel(path)} **没有 `State:` 行** —— 请先补上（值域见模板）")
        return 1
    cur = _state_value(raw)
    if cur not in STATES:
        print(f"[task_card] claim 被拒绝：State 值 `{cur}` **不在值域**（{'|'.join(STATES)}）"
              f" —— 请先改正（值域外写法会同时让分类与字段产出失效）")
        return 1
    if cur == "Executing":
        print(f"[task_card] claim 被拒绝：{task_id} **已经在执行中**（不重复 claim）")
        return 1
    if cur not in CLAIMABLE:
        print(f"[task_card] claim 被拒绝：State=`{cur}` 不可占用（可占用的起始状态："
              f"{' | '.join(CLAIMABLE)}）\n"
              f"  - `Completed` / `Archived` ⇒ 已完成/已归档，⛔ 不可重开\n"
              f"  - `Blocked` ⇒ 先解除阻塞；`Waiting_Human` ⇒ 等的是人，不是会话")
        return 1
    # 约定互斥**按卡**、不按全局 —— 不再因"别处已有 Executing"而拒绝；
    # 真正的重复占用由上面的 `cur == "Executing"` 拦住（同一张卡，无论谁占的）。
    # 这里只做**信息性提示**，让"当前还有哪些卡在执行"可见，但不阻断。
    others = _executing_elsewhere(path)
    if others:
        print(f"[task_card] 提示：另有 {len(others)} 张卡处于 Executing"
              f"（按卡互斥 ⇒ 不阻断本卡占用）")
        for p in others:
            print(f"    - {_rel(p)}")
    new_text, old_raw = _set_state_text(text, "Executing")
    if dry_run:
        print(f"[task_card] claim --dry-run：{_rel(path)}\n  State: {cur} -> Executing")
        print(_note_removed(old_raw, "Executing"))
        return 0
    new_text, logged = _append_event_log(
        new_text, "Executing", "claim 占用（session: %s）" % _session_id(), path)
    _atomic_write(path, new_text)
    print(f"[task_card] claimed: {task_id}  State: {cur} -> Executing  ({_rel(path)})")
    print(_note_removed(old_raw, "Executing"))
    _report_event_log(logged)
    # 🔴 （缓解）：claim 会重写 `State:` 行 ⇒ 之前读过的版本已过期。
    #   把这条**当场说清**，避免"claim 后同回合 edit 报 file changed since it was read"。
    print("  ℹ️ 该卡刚被改写 ⇒ 本轮若要继续编辑它，请**先重读**（否则工具会报 "
          "`file changed since it was read`）")
    # 🔴 （C'/B' 实验）：**最后**再追加能力提示（既有输出行一字不改，只追加）。
    #   只在**成功**路径上追加：`--dry-run` 在更早就 return 了（预览 ⇒ 不提示）。
    hint = claim_hint_for_card(path, task_id)
    if hint:
        print(hint)
    return 0


def cmd_release(task_id, state=None, dry_run=False, reason=None, takeover=False):
    """**显式释放**：`Executing` ⇒ 调用者指定的状态（必填）。⛔ 不推断完成与否。

    `reason`（可选）= 追加到留痕里的**来源标注**（如 `startup-recover`）。
    🔴 增加**占用者校验** —— 只有占用者能 release；
       别人要拿这张卡必须走**显式接管**：`takeover <ID> --reason=…`（或 `release --takeover` 应急）。
       理由：此前"任何会话都能 release 别人的卡"，等于**排他性可被静默绕过**（PITFALLS 读数）。
    """
    path, err = _find_card(task_id)
    if err:
        print(f"[task_card] release 被拒绝：{err}")
        return 1
    if not state:
        print("[task_card] release 被拒绝：**必须显式指定**最终状态（⛔ 无默认值）\n"
              "  - 暂停但未完成 ⇒ --state=Parked\n"
              "  - 确实完成（等待归档）⇒ --state=Completed\n"
              "  ⛔ 归档是独立动作：release --state=Completed 之后仍需 "
              "`archive <TASK-ID> --confirm`")
        return 1
    if state not in RELEASABLE_TO:
        print(f"[task_card] release 被拒绝：`--state={state}` 不在允许的目标状态（"
              f"{' | '.join(RELEASABLE_TO)}）")
        return 1
    text = _read(path)
    raw = _state_raw(text)
    if raw is None:
        print(f"[task_card] release 被拒绝：{_rel(path)} 没有 `State:` 行")
        return 1
    cur = _state_value(raw)
    if cur != "Executing":
        print(f"[task_card] release 被拒绝：{task_id} 当前 State=`{cur}`，**不是 `Executing`** —— "
              f"只有被占用的卡才需要释放（⛔ 不替其他状态做转换）")
        return 1
    # **占用者校验** —— 只有占用者能 release（排他性是硬约束，不再靠自觉）
    if not takeover:
        me = _session_id()
        occ = _current_occupant(path)
        if occ not in ("", "-") and me not in ("", "-") and occ != me:
            print(f"[task_card] release 被拒绝：{task_id} 由**另一个会话**占用（session: {occ}）。\n"
                  "  · 占用是**排他**的（Human 2026-10-12 裁定）⇒ 只有占用者能释放它\n"
                  "  · 确实需要把这卡拿过来 ⇒ 走**显式接管**（一步完成 + 全程留痕）：\n"
                  f"      python tools/task_card.py takeover {task_id} --reason=<为什么>")
            return 1
    new_text, old_raw = _set_state_text(text, state)
    if dry_run:
        print(f"[task_card] release --dry-run：{_rel(path)}\n  State: Executing -> {state}")
        print(_note_removed(old_raw, state))
        return 0
    _why = "release 释放（session: %s）" % _session_id()
    if reason:
        _why += " · %s" % reason
    new_text, logged = _append_event_log(new_text, state, _why, path)
    _atomic_write(path, new_text)
    print(f"[task_card] released: {task_id}  State: Executing -> {state}  ({_rel(path)})")
    print(_note_removed(old_raw, state))
    _report_event_log(logged)
    # 🔴 （缓解）：release 同样重写 `State:` 行 ⇒ 后续编辑前必须先重读。
    print("  ℹ️ 该卡刚被改写 ⇒ 本轮若要继续编辑它，请**先重读**（否则工具会报 "
          "`file changed since it was read`）")
    if state == "Completed":
        print("  ℹ️ `Completed` 只表示任务完成；**归档**仍是独立动作，需 Human 确认后：\n"
              "      python tools/task_card.py archive %s --confirm" % task_id)
    return 0


def cmd_takeover(task_id, reason=None, dry_run=False):
    """🔴 **显式接管** —— 一步完成「释放别人的占用 + 自己占用」。

    用途：另一个对话确实要把卡拿过去（的读数场景）。
    与"偷偷 release + claim"的区别：
      · **一个命令**完成（不会停在"已释放、未占用"的中间态）
      · `.log` 两条留痕都带 `takeover from <原占用者>` + `reason` ⇒ **可追溯、可审计**
      · 若卡当前没被占用 ⇒ 等价于普通 `claim`（⛔ 不写多余的接管痕迹）
    """
    path, err = _find_card(task_id)
    if err:
        print(f"[task_card] takeover 被拒绝：{err}")
        return 1
    text = _read(path)
    raw = _state_raw(text)
    cur = _state_value(raw) if raw is not None else ""
    if cur != "Executing":
        print(f"[task_card] takeover：{task_id} 当前 State=`{cur}`（未被占用）⇒ 按**普通占用**处理")
        return cmd_claim(task_id, dry_run=dry_run)
    prev = _current_occupant(path)
    me = _session_id()
    if prev == me:
        print(f"[task_card] takeover：{task_id} **本来就是你占用的**（session: {me}）⇒ 无需接管")
        return 0
    why = "takeover from %s" % (prev if prev not in ("", "-") else "unknown")
    if reason:
        why += " · %s" % reason
    print(f"[task_card] takeover：{task_id} 原占用者 `{prev or 'unknown'}` ⇒ 接管者 `{me}`（{why}）")
    rc = cmd_release(task_id, state="Parked", dry_run=dry_run, reason=why, takeover=True)
    if rc != 0:
        return rc
    return cmd_claim(task_id, dry_run=dry_run)


def _capability_names():
    """`capabilities/` 下的能力名集合（与能力库**同源** ⇒ ⛔ 不另立清单）。

    排除 `INDEX` / `README` / `AXES-MAP` / `CELLS` 与 `_` 开头的派生件；`.md` 文件名即能力名。
    再并入 `_aliases.json` 的**旧能力名**（域合并前的 17 个）——
    历史账本与在途记录仍可写旧名，⛔ 不因合并而拒收历史。
    """
    out = set()
    if not os.path.isdir(CAPS_DIR):
        return out
    for n in sorted(os.listdir(CAPS_DIR)):
        if not n.endswith(".md") or n.startswith("_"):
            continue
        if n in ("INDEX.md", "README.md", "AXES-MAP.md", "CELLS.md"):
            continue
        out.add(n[:-3])
    try:
        with open(os.path.join(CAPS_DIR, "_aliases.json"), encoding="utf-8") as fh:
            al = json.load(fh)
        if isinstance(al, dict):
            out.update(str(k) for k in al.keys())
    except (OSError, ValueError):
        pass
    return out


def domain_capability_of(domain):
    """域 ⇒ 域能力名（`capabilities/domain-*.md` 的 `domain:` 字段反查）。判不出 ⇒ `""`。"""
    if not domain or not os.path.isdir(CAPS_DIR):
        return ""
    for n in sorted(os.listdir(CAPS_DIR)):
        if not (n.startswith("domain-") and n.endswith(".md")):
            continue
        try:
            with open(os.path.join(CAPS_DIR, n), encoding="utf-8") as fh:
                s = fh.read()
        except OSError:
            continue
        for line in s.split("\n")[:14]:
            if line.startswith("domain:"):
                if line.split(":", 1)[1].strip() == domain:
                    return n[:-3]
                break
    return ""


# ── 🔴 （C'/B' 实验 · 约定）：`claim` 输出尾部的**能力提示** ────────────────
#   读数前提（⛔ 不重新论证）：阶段注入**永远晚于**它想影响的决策 ——
#     claim → `capability --stage start`（选择已定）→ turn 结束 → post-execute 才发注入
#     ⇒ 注入到达时，本阶段的记录已经写完了。
#   ⇒ 把提示放到 **`claim` 的 stdout**：开工之前、且是**工具返回**（不是 notice）。
#   配置 = `.aios/cap-cells.json`（与 runtime **同一文件**）的新字段 `claimHint`：
#     · `"off"`（缺省 / 写坏 / 字段缺失）⇒ claim 输出**逐字不变**（A 组对照 · 快照用例钉死）；
#     · `"generic"` ⇒ 一段**不点名任何具体能力**的通用提示（只让它知道"有可用的、需要填"）；
#     · `"cell"`    ⇒ 格定位版（`<domain>·<class>` + CELLS.md 该格「这格什么时候用」原文）；
#       ⚠️ 判不出域 / 该格不存在（CELLS.md 的 7 个缺口格）⇒ **回退 `"generic"` 文案**
#       （⛔ 不静默不提示、⛔ 不猜域）。
#   ⛔ 本字段**不读**同文件的 `enabled` / `max` / `form`：claim 提示与格注入是**两个变量**
#     （A/B 单变量要求；改 `claimHint` 不影响 runtime 的注入，反之亦然）。
#   ⚠️ 只读 + fail-safe：文件读不到 / JSON 坏 / 字段值非法 ⇒ 一律 `"off"`，⛔ 不抛错、⛔ 不阻塞占用。
CAP_CLAIM_HINT_MODES = ("off", "generic", "cell")

#: 阶段 ⇒ 格 class（**与 runtime 的 `CELL_CLASS_OF_PHASE` 同口径**：S1→决策 · S2/S3→实现 · S4→收尾）。
# ⚠️ 这是 Python 侧的**第二份**实现（不动 `runtime/`，下一轮才统一）；改口径时**两边一起改**。
CELL_CLASS_OF_STAGE = {"start": "决策", "impl": "实现", "close": "收尾"}

#: 领域词表（只用来**选格**：⛔ 不参与检索、⛔ 不回写卡）。
#: ⚠️ **逐词对齐 `runtime/aios-activation.ts` 的 `CELL_DOMAIN_WORDS`**（`CELL_CLASS_OF_PHASE` 之后那段）。
#: 两份词表将来不同步 = 同一个任务在 claim 与阶段注入里被判成**不同的域** ⇒ 格提示与注入互相打脸。
#: 单测 `test_claim_hint_words_align_with_runtime` 直接对拍 TS 源码（漂移 ⇒ 红），⛔ 不靠人眼。
#: 顺序 = 平票时的优先级（与 TS 一致）。
CELL_DOMAIN_WORDS = (
    ("前端", ("前端", "页面", "界面", "组件", "样式", "布局", "视觉", "美化", "配色", "响应式", "ui", "css")),
    ("后端", ("后端", "服务端", "接口", "api", "鉴权", "并发", "事务", "网关")),
    ("数据", ("数据", "数据库", "迁移", "备份", "索引", "报表", "查询", "sql", "sqlite", "mysql", "字段")),
    ("文档", ("文档", "说明书", "手册", "注释", "措辞", "散文", "readme", "文档站")),
    ("产品", ("产品", "需求", "用户故事", "立项", "范围", "方案", "想法")),
    ("环境·运维", ("部署", "运维", "环境", "服务器", "进程", "沙箱", "docker", "powershell", "windows", "路径")),
    ("求职·职业", ("求职", "简历", "面试", "作品集", "岗位", "招聘", "jd", "自我介绍")),
    ("AI-OS 自身", ("ai-os", "aios", "runtime", "运行时", "探针", "任务卡", "注入", "检索", "装配", "能力片")),
)

#: ASCII 词（`ui` / `api` / `jd`）要加**词界**，否则 `ui` 会命中 `build`（TS `cellWordAt()` 同口径）。
_ASCII_WORD_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
#: 表格分隔行（`|---|:--:|---|`）—— 不是数据行。
_CELL_SEP_ROW_RE = re.compile(r"^:?-{2,}:?$")


def _cell_word_at(text, word):
    """`word` 在文本里的**首次**出现位置（`-1` = 没出现）—— 与 TS `cellWordAt()` 同口径。"""
    if _ASCII_WORD_RE.match(word):
        pat = r"(?<![A-Za-z0-9_-])%s(?![A-Za-z0-9_-])" % re.escape(word)
        m = re.search(pat, text, re.IGNORECASE)
        return m.start() if m else -1
    return text.find(word)


def infer_cell_domain(topic):
    """**纯函数**：文本面 ⇒ 格领域（8 值之一 / `None` = 判不出）。

    判定 = **最早出现者**（同位置取更长的词，再平票按 `CELL_DOMAIN_WORDS` 顺序）——
    与 runtime `inferCellDomain()` 的**词面那一半**同口径。
    ⚠️ runtime 还有「目录 / 扩展名兜底」，Python 侧**没有**（claim 不掌握活动路径）
    ⇒ 这里判不出就是 `None`，由调用方回退 `"generic"`（⛔ 不猜域）。
    """
    best = None  # (at, domain, len)
    for domain, words in CELL_DOMAIN_WORDS:
        for w in words:
            at = _cell_word_at(topic, w)
            if at < 0:
                continue
            if best is None or at < best[0] or (at == best[0] and len(w) > best[2]):
                best = (at, domain, len(w))
    return None if best is None else best[1]


def cell_rows():
    """读 + 解析 `capabilities/CELLS.md` 的**第一个表格块**（6 列 = 格装配表）。

    best-effort：文件缺失 / 结构不符 ⇒ `[]`（调用方回退 generic，⛔ 不抛错）。
    契约与 runtime `parseCellsTable()` / `_capability_field_lint.py: cells_of()` 同形。
    """
    path = os.path.join(ROOT, "capabilities", "CELLS.md")
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError:
        return []
    rows, started, header_seen = [], False, False
    for raw in text.split("\n"):
        s = raw.strip()
        if not s.startswith("|"):
            if started:
                break  # 第一个表格块结束（§三 缺口表 / §四 过载表不属于装配表）
            continue
        started = True
        if not s.endswith("|"):
            continue
        cols = [c.strip() for c in s[1:-1].split("|")]
        if cols and all(_CELL_SEP_ROW_RE.match(c) for c in cols):
            continue
        if not header_seen and cols and cols[0].lower().startswith("cell id"):
            header_seen = True
            continue
        if len(cols) != 6:
            continue
        rows.append({"id": cols[0], "cls": cols[1], "domain": cols[2], "when": cols[5]})
    return rows


def cell_of(stage, topic):
    """(阶段, 文本面) ⇒ 命中的格（`{id, cls, domain, when}` / `None`）。

    精确匹配 `(domain, class)` —— ⛔ 不做域别名、⛔ 不跨 class 借格（与 runtime `cellOf()` 同口径）。
    """
    cls = CELL_CLASS_OF_STAGE.get(stage)
    domain = infer_cell_domain(topic)
    if cls is None or domain is None:
        return None
    for row in cell_rows():
        if row["domain"] == domain and row["cls"] == cls:
            return row
    return None


def card_topic(path):
    """卡 ⇒ 判域用的**文本面**（标题 + `Goal` 段 + `Current Step` / `Next Action` 行）。

    只取"这张卡要做什么"的显式文本：⛔ 不读 `.log`、⛔ 不读 Event Log（流水里的词会把域带偏）。
    """
    try:
        text = _read(path)
    except OSError:
        return ""
    keep = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("# TASK_CARD"):
            rest = s.replace("# TASK_CARD", "", 1).strip(" —-\t")
            if rest:
                keep.append(rest)
            break
    m = re.search(r"^##[ \t]+Goal[^\n]*\n(.*?)(?=^##[ \t]|\Z)", text, re.M | re.S)
    if m:
        keep.append(m.group(1).strip())
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("Current Step:") or s.startswith("Next Action:"):
            keep.append(s)
    return "\n".join(k for k in keep if k)


def claim_hint_mode():
    """`.aios/cap-cells.json` 的 `claimHint` ⇒ `"off" | "generic" | "cell"`（fail-safe ⇒ `"off"`）。

    读法（与 runtime `capCellsConfig()` 同口径）：**懒读**（每次现取 · 改文件下一拍生效）·
    先剥 **UTF-8 BOM**（`utf-8-sig` —— 中文 Windows 手写 JSON 常带 BOM）·
    读不到 / 解析失败 / 字段值非法 ⇒ `"off"`。
    ⚠️ 与 runtime 的差别（故意）：**不要求** `enabled` / `max` 存在 —— `claimHint` 是独立开关，
    否则"只想开 claim 提示"也得把格注入的整份配置抄一遍。
    """
    try:
        with open(os.path.join(ROOT, ".aios", "cap-cells.json"), "r",
                  encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return "off"
    if not isinstance(data, dict):
        return "off"
    v = data.get("claimHint")
    return v if v in CAP_CLAIM_HINT_MODES else "off"


def _domain_intro(cap_name):
    """域能力名 ⇒ 该文件 frontmatter 的 `intro`（读不到 ⇒ `""`）。"""
    try:
        with open(os.path.join(CAPS_DIR, cap_name + ".md"), encoding="utf-8") as fh:
            s = fh.read()
    except OSError:
        return ""
    for line in s.split("\n")[:10]:
        if line.startswith("intro:"):
            return line.split(":", 1)[1].strip()
    return ""


def claim_hint_text(task_id, stage, mode, topic=""):
    """**纯函数**（只读 `capabilities/`）：⇒ 该给 worker 看的提示（`""` = 不打印）。

    · `off` ⇒ `""`（claim 输出**逐字不变** · 对照组）
    · `generic` ⇒ 三行通用提示（⛔ 不点名任何具体能力）
    · `cell` ⇒ 格定位版；判不出域 / 无该格 ⇒ **回退 generic 文案**
    ⚠️ `stage` 参数保留给**调用方逐轮核对**（claim 恒传 `start`；`capability-hint --stage impl`
    就原样传 `impl`）；🔴 域合并后提示只由 `topic` 判出的**域**决定 ⇒
    读数 start / impl / close 的输出**逐字相同**，阶段不再改变文案。
    """
    if mode == "cell":
        # 🔴 域合并：**不再查 CELLS 格**（一域一文件 ⇒ 阶段不再是定位维度）
        dom = infer_cell_domain(topic)
        dc = domain_capability_of(dom) if dom else ""
        if dc:
            return ("[AI-OS] 本阶段可用能力：用检索工具 `auto_capability` → 它会给出 8 个领域词表，选一个\n"
                    "        机器推测域：%s（仅参考 · 以检索/自选为准）\n"
                    "        记录：python tools/task_card.py capability %s "
                    "--name <域能力|none> --why \"...\""
                    % (dom, task_id))
        mode = "generic"  # ⛔ 不静默、⛔ 不猜域：判不出就退回通用文案
    if mode != "generic":
        return ""
    # 用户 2026-11-02 口径：提示换成**检索工具**；能力词表只有 8 个域能力
    return ("[AI-OS] 本阶段可用能力：用检索工具 `auto_capability` → 它会给出 8 个领域词表，选一个\n"
            "        记录：python tools/task_card.py capability %s "
            "--name <域能力|none> --why \"<一句>\""
            % task_id)


def claim_hint_for_card(path, task_id, stage="start"):
    """卡路径 ⇒ claim 尾部要追加的提示（`""` = 一条都不打印 · 既有输出行一字不动）。"""
    mode = claim_hint_mode()
    if mode == "off":
        return ""
    return claim_hint_text(task_id, stage, mode, card_topic(path))


def parse_capability_args(args):
    """纯函数：`capability` 的 argv ⇒ `(task_id, stage, name, why, error)`。

    · `--stage start`（空格）与 `--stage=start`（等号）**等价** —— 用法原文就是空格形式
    · 位置参数只允许**一个** TASK-ID（裸 ID 或 `项目/ID`）；缺值 / 重复 / 未知参数 ⇒ error
      （⛔ 不静默、不猜）
    """
    flags = {"--stage": "stage", "--name": "name", "--why": "why"}
    opts = {}
    tid = None
    i = 0
    while i < len(args):
        a = args[i]
        key = None
        if "=" in a and a.split("=", 1)[0] in flags:
            key = flags[a.split("=", 1)[0]]
            value = a.split("=", 1)[1]
            i += 1
        elif a in flags:
            key = flags[a]
            if i + 1 >= len(args):
                return None, None, None, None, "`%s` 后面没有值" % a
            value = args[i + 1]
            i += 2
        elif a.startswith("--"):
            return None, None, None, None, (
                "未知参数 `%s`（capability 只支持 --stage / --name / --why）" % a)
        else:
            if tid is not None:
                return None, None, None, None, "只能指定一个 TASK-ID（多给了：`%s`）" % a
            tid = a
            i += 1
            continue
        if key in opts:
            return None, None, None, None, "`--%s` 重复指定" % key
        opts[key] = value
    return tid, opts.get("stage"), opts.get("name"), opts.get("why"), None


def check_capability_args(stage, name, why):
    """纯函数 ⇒ `(ok, error)`：stage / name / why 三项校验（不合法 ⇒ 明确报错、不写）。"""
    stage = (stage or "").strip().lower()
    if not stage:
        stage = "once"          # 🔴 省略 `--stage` ⇒ 单字段模式（卡上一行「能力」）
    if stage not in CAPABILITY_STAGES:
        return False, ("`--stage` 可省略（单字段）或取 start / impl / close（收到：`%s`）"
                       % stage)
    name = (name or "").strip().strip("`").strip()
    if not name:
        return False, "缺 `--name`（填 `capabilities/` 下的能力名，或 `none`）"
    names = _capability_names()
    if name != "none" and name not in names:
        return False, ("未知能力 `%s` ⇒ 可选 `none` 或以下 %d 个之一：%s"
                       % (name, len(names), " / ".join(sorted(names))))
    why = (why or "").strip()
    if not why:
        return False, "缺 `--why`（写一句本次改动**为什么**用/不用这个能力，≥8 个字符）"
    if "\n" in why or "\r" in why:
        return False, "理由不能换行（`.log` 一行一条）"
    if "|" in why:
        return False, "理由里不能含 `|`（会破坏 `.log` 表格行；要分隔请用「｜」）"
    if len(why) < 8:
        return False, ("理由太短（≥8 个字符；写清本次改动**为什么**用/不用这个能力）：`%s`"
                       % why)
    norm = re.sub(r"[\s，。；、,.!！?？…·:：\-—_/（）()\[\]【】\"'“”‘’]+", "", why)
    if norm in VAGUE_WHY:
        return False, ("理由空泛（`%s` 不算理由；请写本次改动为什么用/不用这个能力）"
                       % why)
    return True, ""


# ── 🔴 （v3 · 约定）：能力字段**同步写卡** ─────────────────────────────
#   卡上新增「## 使用的能力（三阶段 · 可 none）」节（v3 模板）⇒ `capability` 同时写卡与 `.log`：
#     · `.log` = **流水**（格式逐字不变 · lint 与历史数据的唯一来源）
#     · 卡     = **快照**（该阶段一行：`- 开工: `<name>` ｜ <why>`）
#   ⛔ 不追加（重复跑同 stage ⇒ 覆盖该行）· ⛔ 卡上没有该节（v1/v2）⇒ 只写 `.log`
#   （不报错、不自动加节 —— 向后兼容，保护已有 A/B 数据的卡）。
#   卡仍是自由文本 ⇒ 只认**固定行格式**；行被手改坏 ⇒ 按"覆盖成规范行"处理。
CAP_STAGE_LABELS = {"start": "开工", "impl": "实现", "close": "收尾", "once": "能力"}
CAP_STAGE_ORDER = ("start", "impl", "close", "once")

# ── 🔴 （v4 · 约定）：卡形态**双模式**判定 ─────────────────────────────
#   按**卡上有没有那几行**判，⛔ 不看模板版本号（卡可被手改 / 从别处搬来）。
#     · `legacy` = v1/v2/v3 卡的 `- 开工:` / `- 实现:` / `- 收尾:` 行 ⇒ 三阶段判据（逐字不变）
#     · `single` = v4 卡的 `- 能力:` 行 ⇒ 只要求一条 `能力` 记录
#     · 两种行都在 ⇒ **旧卡优先**（legacy）；两种都没有 ⇒ `None`（走既有 SKIP / PENDING 逻辑）
#   ⚠️ 同一份判据被 `tools/probes/_capability_choice_lint.py` 复用（单一来源，⛔ 不另写一套）。
_CAP_LEGACY_FIELD_RE = re.compile(
    r"^[ \t]*(?:[-*][ \t]*)?(?:开工|实现|收尾)[ \t]*[:：]", re.M)
#: ⚠️ 单字段行**必须带列表符**（`- 能力:`）—— 放宽会把手写散文里的 `能力: …` 误判成 v4 卡，
#: 进而让旧卡（无 `能力` 行）被判 FAIL（假红）。
_CAP_SINGLE_FIELD_RE = re.compile(
    r"^[ \t]*[-*][ \t]*能力[ \t]*[:：]", re.M)


def card_capability_mode(text):
    """卡文本 ⇒ `"legacy"` | `"single"` | `None`（判据见上方注释；两种都有 ⇒ `"legacy"`）。"""
    if _CAP_LEGACY_FIELD_RE.search(text or ""):
        return "legacy"
    if _CAP_SINGLE_FIELD_RE.search(text or ""):
        return "single"
    return None


_CAP_SECTION_RE = re.compile(r"^##[ \t]+使用的能力[^\n]*\r?\n", re.M)
_CAP_H2_RE = re.compile(r"^##[ \t]", re.M)


def _cap_section_span(text):
    """卡文本 ⇒ 「使用的能力」节正文的 `(start, end)`；没有该节 ⇒ `None`。"""
    m = _CAP_SECTION_RE.search(text)
    if m is None:
        return None
    start = m.end()
    m2 = _CAP_H2_RE.search(text, start)
    return start, (m2.start() if m2 else len(text))


def _cap_stage_line_re(stage):
    """该阶段行的**前缀**正则（容忍手改：列表符 / 全角冒号 / 缺冒号但仍是列表行都在内）。"""
    label = re.escape(CAP_STAGE_LABELS[stage])
    return re.compile(r"^[ \t]*(?:[-*][ \t]*%s|%s(?=[ \t:：`]|$))" % (label, label))


def has_capability_section(text):
    """卡文本是否有「## 使用的能力」节（v3 卡才校验卡字段 ↔ `.log` 一致）。"""
    return _cap_section_span(text) is not None


def capability_card_value(text, stage):
    """卡文本 ⇒ `(该阶段字段值|None, 原行|None)`（无节 / 无该行 ⇒ `(None, None)`）。"""
    span = _cap_section_span(text)
    if span is None:
        return None, None
    label_re = _cap_stage_line_re(stage)
    for line in text[span[0]:span[1]].splitlines():
        if not label_re.match(line):
            continue
        m = re.search(r"`([^`]*)`", line)
        return (m.group(1).strip() if m else None), line
    return None, None


def _cap_card_line(stage, name, why):
    """卡上该阶段的**规范行**（与 v3 模板 / lint 同一格式）。"""
    return "- %s: `%s` ｜ %s" % (CAP_STAGE_LABELS[stage], name, why)


def sync_capability_to_card(card_path, stage, name, why):
    """把该阶段的值写进卡上的「使用的能力」节 ⇒ `bool`（写了卡 = True；无该节 = False）。

    覆盖该阶段行（⛔ 不追加）；行被手改坏 / 缺行 ⇒ 用规范行替换或按阶段顺序插入。
    """
    text = _read(card_path)
    span = _cap_section_span(text)
    if span is None:
        return False
    start, end = span
    body = text[start:end]
    lines = body.splitlines(keepends=True)
    eol = "\r\n" if "\r\n" in body else "\n"
    target_re = _cap_stage_line_re(stage)
    target = next((i for i, ln in enumerate(lines) if target_re.match(ln)), None)
    canonical = _cap_card_line(stage, name, why)
    if target is not None:
        old = lines[target]
        lines[target] = canonical + old[len(old.rstrip("\r\n")):]
    else:
        pos = None
        idx = CAP_STAGE_ORDER.index(stage)
        for prev in reversed(CAP_STAGE_ORDER[:idx]):
            prev_re = _cap_stage_line_re(prev)
            hits = [i for i, ln in enumerate(lines) if prev_re.match(ln)]
            if hits:
                pos = hits[-1] + 1
                break
        if pos is None:
            for nxt in CAP_STAGE_ORDER[idx + 1:]:
                nxt_re = _cap_stage_line_re(nxt)
                hits = [i for i, ln in enumerate(lines) if nxt_re.match(ln)]
                if hits:
                    pos = hits[0]
                    break
        if pos is None:
            pos = len(lines)
            while pos > 0 and not lines[pos - 1].strip():
                pos -= 1
            if pos > 0 and not lines[pos - 1].endswith(("\n", "\r")):
                lines[pos - 1] += eol
        lines.insert(pos, canonical + eol)
    _atomic_write(card_path, text[:start] + "".join(lines) + text[end:])
    return True


def cmd_capability(task_id, stage, name, why):
    """**记录一个能力使用点** ⇒ 追加同级 `.log` **并同步卡上字段**。

    🔴 （已确认口径）：能力选择**写卡正文不行** —— 卡是自由文本，正则只能猜
      格式（读数已出现假红）。⇒ `.log` 仍由**脚本**写（格式永远正确、时间戳自动）。
      v1/v2/v3 卡的三点固定：**开工 / 实现 / 收尾**；只对**新卡**生效（旧卡不补记）。
    🔴 （v3）：卡上新增「使用的能力」字段节 ⇒ **同一子命令**再把该阶段值写回卡
      （`- 开工: `<name>` ｜ <why>`，覆盖不追加）；v1/v2 卡没有该节 ⇒ 只写 `.log`。
    🔴 （v4）：卡改**单字段** ⇒ 省略 `--stage` 时写一条 `能力` 行 + 卡上一行
      `- 能力: `<name>` ｜ <why>`；显式给 `--stage` 仍按三阶段写（旧卡照旧）。
      单字段卡（有 `- 能力:` 行）给 `--stage` ⇒ **拒绝**（阶段行会把卡形态翻成 legacy）。
    """
    if not task_id:
        print(usage_for("capability"))
        return 1
    ok, err = check_capability_args(stage, name, why)
    if not ok:
        print("[task_card] capability 被拒绝：%s" % err)
        return 1
    path, err = _find_card(task_id)
    if err:
        print("[task_card] capability 被拒绝：%s" % err)
        return 1
    # 🔴 （v4 单字段）：显式 `--stage` 只属于旧三阶段卡。
    #   在 v4 卡上写阶段行会把 `- 开工:` 插进单字段节 ⇒ `card_capability_mode()` 翻成 legacy
    #   ⇒ 卡上出现不该有的阶段行、lint 也不再按单字段判。⛔ 不静默改写，直接拒绝（无副作用）。
    if stage and card_capability_mode(_read(path)) == "single":
        print("[task_card] capability 被拒绝：%s 是 v4 单字段卡（有 `- 能力:` 行）⇒ "
              "省略 --stage（写一条 `能力` 记录）；旧三阶段卡才用 --stage start|impl|close"
              % _rel(path))
        return 1
    stage = (stage or "").strip().lower() or "once"   # 🔴 省略 ⇒ 单字段
    name = (name or "").strip().strip("`").strip()
    why = (why or "").strip()
    try:
        append_event_log_line(path, CAPABILITY_STAGES[stage],
                              "%s ｜ 理由：%s" % (name, why))
    except OSError as exc:
        print("[task_card] capability 被拒绝：写日志失败（%s）" % exc)
        return 1
    # 🔴 v3：`.log` 是权威记录（先写）；卡是快照（后写）。卡写失败 ⇒ 明确告警，⛔ 不静默。
    try:
        synced = sync_capability_to_card(path, stage, name, why)
        sync_err = None
    except OSError as exc:
        synced, sync_err = False, exc
    print("[task_card] capability recorded: %s %s %s" % (_rel(path), stage, name))
    if sync_err is not None:
        print("  ⚠️ `.log` 已记录，但**卡上字段未同步**（%s）⇒ 请重跑本命令" % sync_err)
        return 1
    if synced:
        print("  ⇒ 已同步写卡：『使用的能力』· %s" % CAP_STAGE_LABELS[stage])
    return 0


# ── ③ （A/B 判据）：`capability-timing` —— **只读**自检 ─────────────────────
#   一次拿全：三处记录时间 / 该卡会话**首次 edit** / 「开工早于首次 edit」/「复用 or 阶段切换」。
#   会话 ⇒ 取 `.log` 最后一条 claim 留痕；首次 edit ⇒ 读 Runtime 的 `tool-sig` 探针
#   （与 `tools/probes/_capability_choice_lint.py` **同一文件、同一口径**：只认 `tool=edit`）。
#   ⛔ 只读：卡与 `.log` 一字不动、⛔ 不写探针、⛔ 不改 State。

#: `.log` 能力行的 Reason 列：`<name> ｜ 理由：<why>`（全角竖线 · 与探针同口径）
CAP_REASON_RE = re.compile(r"^(?P<name>[^｜]+?)\s*｜\s*理由[:：]\s*(?P<why>.*)$")
#: claim 留痕（取会话 id；与 `_current_occupant()` 的正则同源）
CLAIM_SESSION_RE = re.compile(r"claim\s*占用（session:\s*([^）]*)）")


def _read_text_utf8_sig(path):
    """只读文本：**剥 BOM**（中文 Windows 手写文件常带 BOM）+ 容错解码。"""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        return fh.read()


def log_table_rows(card_path):
    """读**外置 `.log`** 的表格数据行 ⇒ `[{time, state, reason}]`（⛔ 不读卡正文、⛔ 不写）。"""
    log_path = _event_log_path(card_path)
    if not os.path.isfile(log_path):
        return []
    rows = []
    for line in _read_text_utf8_sig(log_path).split("\n"):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[0] == "Time" or cells[1] == "State" or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append({"time": cells[0], "state": cells[1], "reason": cells[2]})
    return rows


def _capability_record(rows, stage):
    """该 stage 的**首条**能力行（追加日志 ⇒ 首次声明即权威，后补视为更正）。"""
    label = CAPABILITY_STAGES[stage]
    for r in rows:
        if r["state"] == label:
            return r
    return None


def _capability_name(reason):
    """Reason 列 ⇒ 能力名（格式不符 ⇒ None）。"""
    m = CAP_REASON_RE.match((reason or "").strip())
    return m.group("name").strip().strip("`").strip() if m else None


def _norm_session(s):
    """探针与 `.log` 两种写法归一：`session-<id>` / `<id>` ⇒ `<id>`。"""
    s = (s or "").strip()
    return s[len("session-"):] if s.startswith("session-") else s


def _last_claim_session(rows):
    """`.log` 里**最后一条** claim 留痕的会话（= 当前占用者；无 ⇒ `""`）。"""
    for r in reversed(rows):
        m = CLAIM_SESSION_RE.search(r["reason"])
        if m:
            return _norm_session(m.group(1))
    return ""


def probe_first_edit(session):
    """该会话在 Runtime 探针里的**首次 `edit`** 时间（`datetime|None`）。

    只读扫 `.aios/_aios-activation.probe.log` 的 `ev=tool-sig` 行；`at` = epoch 毫秒。
    探针不存在 / 读不到 / 无该会话 ⇒ `None`（调用方打印 N/A，⛔ 不猜）。
    """
    if not session or not os.path.isfile(PROBE_LOG):
        return None
    best = None
    try:
        fh = open(PROBE_LOG, "r", encoding="utf-8", errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            if '"tool-sig"' not in line or '"edit"' not in line:
                continue
            try:
                d = json.loads(line.split("] ", 1)[1])
            except (ValueError, IndexError):
                continue
            if d.get("ev") != "tool-sig" or d.get("tool") != "edit":
                continue
            if _norm_session(d.get("session")) != session:
                continue
            try:
                dt = datetime.fromtimestamp(float(d.get("at")) / 1000.0)
            except (TypeError, ValueError, OSError, OverflowError):
                continue
            if best is None or dt < best:
                best = dt
    return best


def _row_datetime(card_path, hhmm):
    """`.log` 行的 `HH:MM` ⇒ datetime（日期取 `.log` mtime 的日期；秒按 `:00`，同 probe 口径）。"""
    m = re.match(r"^(\d{1,2}):(\d{2})$", (hhmm or "").strip())
    if not m:
        return None
    try:
        base = datetime.fromtimestamp(os.path.getmtime(_event_log_path(card_path)))
    except OSError:
        try:
            base = datetime.fromtimestamp(os.path.getmtime(card_path))
        except OSError:
            base = datetime.now()
    return datetime(base.year, base.month, base.day, int(m.group(1)), int(m.group(2)))


def cmd_capability_timing(task_id):
    """**只读**：能力记录时间 + 首次 edit + 先后判据（⛔ 不落盘、⛔ 不改卡）。

    输出为**人读文本**（非 JSON）：
      · 单字段卡（v4）⇒ `能力: <name>（<时间>）` / `首次 edit: …` / `早于首次 edit: YES|NO|N/A`
      · 三阶段卡（v1/v2/v3）⇒ 维持既有输出（三处明细 + 复用/阶段切换）
    """
    if not task_id:
        print(usage_for("capability-timing"))
        return 1
    path, err = _find_card(task_id)
    if err:
        print("[task_card] capability-timing 被拒绝：%s" % err)
        return 1
    rows = log_table_rows(path)
    session = _last_claim_session(rows)
    print("[task_card] capability-timing: %s" % _rel(path))
    print("  会话: %s" % (session or "(无 claim 留痕)"))

    # 🔴 （v4）：单字段卡 —— 只打一条 `能力` 记录 + 首次 edit 先后，⛔ 不打三处明细。
    if card_capability_mode(_read(path)) == "single":
        # 🔴 A 案（定）：单字段卡**末条即权威**，与注入侧读法一致。
        row = None
        for r in rows:
            if r["state"] == CAPABILITY_STAGES["once"]:
                row = r
        name = _capability_name(row["reason"]) if row else None
        print("  能力: %s（%s）" % (name or "(未记录)", row["time"] if row else "-"))
        first = probe_first_edit(session)
        if first is None:
            print("  首次 edit: (探针无记录)")
            print("  早于首次 edit: N/A")
            return 0
        print("  首次 edit: %s" % first.strftime("%Y-%m-%d %H:%M:%S"))
        row_dt = _row_datetime(path, row["time"]) if row else None
        created = card_created_at(path)
        if row is None:
            print("  早于首次 edit: N/A（缺能力记录）")
        elif created is not None and created > first:
            # 卡建在该会话首次 edit 之后 ⇒ 那次 edit 不可能是本卡的改动 ⇒ 记 N/A（⛔ 不误判 NO）
            print("  早于首次 edit: N/A")
        elif row_dt is None:
            print("  早于首次 edit: N/A（能力时间不可解析：%s）" % row["time"])
        else:
            print("  早于首次 edit: %s" % ("YES" if row_dt <= first else "NO"))
        return 0

    records = {}
    for stage in ("start", "impl", "close"):
        row = _capability_record(rows, stage)
        name = _capability_name(row["reason"]) if row else None
        records[stage] = (row, name)
        label = CAPABILITY_STAGES[stage].replace("能力-", "")
        if row is None:
            print("  %s: (未记录)" % label)
        else:
            print("  %s: %s  name=%s" % (label, row["time"], name or "(格式不符)"))

    first = probe_first_edit(session)
    if first is None:
        print("  首次 edit: (探针无记录)")
        print("  开工早于首次 edit: N/A")
    else:
        print("  首次 edit: %s" % first.strftime("%Y-%m-%d %H:%M:%S"))
        start_row = records["start"][0]
        start_dt = _row_datetime(path, start_row["time"]) if start_row else None
        if start_row is None:
            print("  开工早于首次 edit: N/A（缺开工记录）")
        elif start_dt is None:
            print("  开工早于首次 edit: N/A（开工时间不可解析：%s）" % start_row["time"])
        else:
            print("  开工早于首次 edit: %s" % ("YES" if start_dt < first else "NO"))

    names = [name for _row, name in records.values() if name]
    if len(names) < 3:
        print("  三处能力: 待补（已记 %d/3）" % len(names))
    elif len(set(names)) == 1:
        print("  三处能力: 复用（%s）" % names[0])
    else:
        seq = []
        for n in names:  # 连续同名折叠 ⇒ `A -> A -> B` 读成 `A -> B`（逐处明细仍在上面三行）
            if not seq or seq[-1] != n:
                seq.append(n)
        print("  三处能力: 阶段切换（%s）" % " -> ".join(seq))
    return 0


def parse_stage_only_args(args):
    """纯函数：`capability-hint` 的 argv ⇒ `(task_id, stage, error)`（`--stage x` / `--stage=x` 等价）。"""
    stage, tid, i = None, None, 0
    while i < len(args):
        a = args[i]
        if a == "--stage":
            if i + 1 >= len(args):
                return None, None, "`--stage` 后面没有值"
            value, i = args[i + 1], i + 2
        elif a.startswith("--stage="):
            value, i = a.split("=", 1)[1], i + 1
        elif a.startswith("--"):
            return None, None, "未知参数 `%s`（capability-hint 只支持 `--stage`，且可省略）" % a
        else:
            if tid is not None:
                return None, None, "只能指定一个 TASK-ID（多给了：`%s`）" % a
            tid = a
            i += 1
            continue
        if stage is not None:
            return None, None, "`--stage` 重复指定"
        stage = value
    return tid, stage, None


def cmd_capability_hint(task_id, stage):
    """**临时实验辅助**：按当前配置打印「该给 worker 看的那段提示」（与 claim **同一份**文案逻辑）。

    用途：A/B 执行时核对"这一轮应该显示什么"，也让 worker 在 turn 中途可重取。
    ⛔ 不落盘、⛔ 不记账（`.log` 一行都不写）；`claimHint:"off"` / 判不出域时的回退都**同 claim**。

    🔴 （v4 单字段）：`--stage` **可省略** —— 省略 ⇒ 按单字段卡口径（`once`）出提示，
    与 claim 一致；显式给 start / impl / close 仍接受（向后兼容既有调用方）。
    域合并后提示只由**卡文本判出的域**决定 ⇒ 阶段**不再改变文案**（读数三档逐字相同）。
    """
    if not task_id:
        print(usage_for("capability-hint"))
        return 1
    stage = (stage or "").strip().lower()
    if stage and stage not in CAPABILITY_HINT_STAGES:
        print("[task_card] capability-hint 被拒绝：`--stage` 可省略（单字段）"
              "或取 start / impl / close（收到：`%s`）" % stage)
        print(usage_for("capability-hint"))
        return 1
    path, err = _find_card(task_id)
    if err:
        print("[task_card] capability-hint 被拒绝：%s" % err)
        return 1
    text = claim_hint_text(task_id, stage or "once", claim_hint_mode(), card_topic(path))
    if text:
        print(text)
    return 0


def cmd_states(off_vocab_only=False):
    """**只读**状态校验：列出各卡 State（含**缺失**与**值域外**写法）。"""
    cards = _iter_cards()
    missing, off_vocab, ok_rows = [], [], []
    for p in cards:
        raw = _state_raw(_read(p))
        if raw is None:
            missing.append(_rel(p))
            continue
        v = _state_value(raw)
        if v not in STATES:
            off_vocab.append((_rel(p), v))
            continue
        ok_rows.append((v, _rel(p)))
    if not off_vocab_only:
        print("[task_card] State 校验（active 下 %d 张卡）" % len(cards))
        for v, rel in sorted(ok_rows):
            print("  %-14s %s" % (v, rel))
    if missing:
        print("\n  ⛔ **缺 `State:` 行**（%d 张）⇒ 分类与字段产出都无法接入：" % len(missing))
        for rel in missing:
            print("    - %s" % rel)
    if off_vocab:
        print("\n  ⛔ **值域外写法**（%d 张）⇒ 应写成值域内的词（注释归 `Current Step` / `Notes`）：" % len(off_vocab))
        for rel, v in off_vocab:
            print("    - %-40s State=`%s`" % (rel, v))
    if not missing and not off_vocab:
        print("\n  ✅ 全部卡的 State 均在值域内（missing=0 · off-vocab=0）")
    print("\n（只读：本命令不改任何卡）")
    return 0


# ── 帮助（「卡片命令的 --help」）──────────────────────────────
#   用法**单一来源**：`--help` / 子命令 `--help` / 缺参数报错 共用同一份，⛔ 不再两头各写一遍。
USAGE = {
    "create": ('create "<标题>" [--project=<项目名> | --project <项目名>] [--template=v1|v2|v3|v4]',
               "新建卡（State 直接落 Planning · 建完即可 claim）；缺省模板 v4（单字段「使用的能力」），"
               "环境变量 AIOS_CARD_TEMPLATE 优先于 --template"),
    "list": ("list", "列出 active 下的项目文件夹与卡（TASK-ID + 标题摘要）"),
    "claim": ("claim <TASK-ID 或 项目/ID> [--dry-run]",
              "显式占用：Planning / Parked / Created ⇒ Executing"),
    "capability": ('capability <TASK-ID 或 项目/ID> [--stage start|impl|close] --name <能力名|none> --why "<一句理由>"',
                   "记录能力使用点 ⇒ 追加到同级 .log；省略 --stage ⇒ 单字段 `能力` 行（v4），"
                   "卡上有「使用的能力」节 ⇒ 同时覆盖该行；v4 单字段卡给 --stage ⇒ 拒绝"),
    "capability-timing": ("capability-timing <TASK-ID 或 项目/ID>",
                          "只读：能力记录时间 + 该会话首次 edit + 是否早于它（三阶段卡另打三处明细）"),
    "capability-hint": ("capability-hint <TASK-ID 或 项目/ID> [--stage start|impl|close]",
                        "（临时 · 实验辅助）只读打印：当前配置下该给 worker 看的能力提示"
                        "（与 claim 同一文案逻辑）；省略 --stage ⇒ 单字段卡口径（v4），"
                        "显式给 stage 仍接受（域合并后阶段不改变文案）"),
    "release": ("release <TASK-ID 或 项目/ID> --state=Parked|Completed [--reason=<文本>] [--takeover] [--dry-run]",
                "显式释放：Executing ⇒ 指定状态（必填、无默认值；只有占用者能释放）"),
    "takeover": ("takeover <TASK-ID 或 项目/ID> [--reason=<为什么>] [--dry-run]",
                 "显式接管：一步完成「释放别人的占用 + 自己占用」，两步都留痕"),
    "archive": ("archive <TASK-ID 或 项目/ID> [--confirm]",
                "归档（移入 archive/）；⛔ 仅当已完成且已获用户确认"),
    "states": ("states [--off-vocab]",
               "只读状态校验：列出各卡 State（含缺失 / 值域外写法）"),
}

COMMON_NOTES = """\
说明：
  · <TASK-ID> = `TASK-YYYYMMDD-NNN`；**跨项目重名时必须写「项目/TASK-ID」**
  · State 值域：Created | Planning | Executing | Parked | Blocked | Waiting_Human | Reviewing | Completed | Archived
  · `claim` / `release` 会重写卡里的 `State:` 行 ⇒ 同一回合要接着改这张卡，请**先重读**
    （否则工具会报 `file changed since it was read`）
  · `State` 是**占用声明**：想用卡就 claim，本轮结束就 release（停止 ≠ 任务结束）
  · `capability` 写**同级 `.log`**（省略 `--stage` ⇒ 一条 `能力` 行；给 `--stage` ⇒
    `能力-开工|实现|收尾` 三行，格式不变）；卡上有「使用的能力」节 ⇒ 同时**覆盖**对应行
    （v1/v2 无该节 ⇒ 只写 `.log`、⛔ 不加节）
  · v4 **单字段卡**（有 `- 能力:` 行）给 `--stage` ⇒ **拒绝**（会往单字段节插阶段行、
    把卡形态翻成 legacy）；旧三阶段卡才需要 `--stage start|impl|close`
  · `create --template v1|v2|v3|v4`：缺省 **v4**（单字段「使用的能力」）；`AIOS_CARD_TEMPLATE`
    **优先于** `--template`；模板缺失 / 非法值 ⇒ 报错且不落卡（⛔ 不静默回落）
  · `capability-timing` 只读（卡与 `.log` 一字不动）：能力记录时间 + 首次 edit + 先后判据
  · `capability-hint` 只读（⛔ 不落盘、⛔ 不记账）：`--stage` **可省略** ⇒ 按单字段卡口径出提示
    （与 claim 一致）；显式给 start / impl / close 仍接受（域合并后提示按域出，阶段不改变文案）
  · `--project` 两种写法**等价**：`--project=<名>` / `--project <名>`；标题请用引号包住
    （标题里若残留 `--xxx=` 或 mojibake 特征 ⇒ 拒绝建卡，⛔ 不落垃圾卡）
  · ⛔ 本工具**不自动改状态**、不推断完成与否；归档需 `--confirm` + Human 确认
"""


def usage_for(cmd):
    """→ 该命令的一行用法（无此命令 ⇒ None）。"""
    spec = USAGE.get(cmd)
    return ('usage: task_card.py %s\n  %s' % (spec[0], spec[1])) if spec else None


def help_text(cmd=None):
    """→ 帮助文本。给了已知命令 ⇒ 该命令用法；否则总览（含常见坑说明）。"""
    if cmd and cmd in USAGE:
        return usage_for(cmd) + "\n\n" + COMMON_NOTES
    lines = ["task_card.py —— AI-OS 任务卡（工作记忆锚点）", "",
             "用法：python tools/task_card.py <命令> [参数]", "",
             "命令："]
    for name, (sig, desc) in USAGE.items():
        lines.append("  %-9s %s" % (name, sig))
        lines.append("            %s" % desc)
    lines += ["", COMMON_NOTES, "示例：",
              "  python tools/task_card.py claim AI-OS-Adaptation/TASK-20261023-001",
              "  python tools/task_card.py release AI-OS-Adaptation/TASK-20261023-001 --state=Parked",
              "  python tools/task_card.py takeover AI-OS-Adaptation/TASK-20261023-001 --reason=\"另一会话已离线\"",
              "  python tools/task_card.py capability AI-OS-Adaptation/TASK-20261023-001 --stage start --name <能力名|none> --why \"一句理由\"",
              "  python tools/task_card.py claim --help        # 单命令用法", ""]
    return "\n".join(lines)


# ── create 的 argv 解析 + 标题守卫（**纯函数 · ⛔ 不碰文件系统**）─────────
#   故障（2 个 worker 受害）：`create "<标题>" --project=X` 里旧代码只按**整 token** 找项目名
#   （`"--project" in args`，见 git 历史 712-719 行）⇒ 等号写法：① 项目名没被识别，卡落到
#   `active/` 顶层 ② 整段 `--project=X` 被 `" ".join(args)` 并进卡标题。
#   ⇒ 解析抽成纯函数（可单测、不建真卡）：`--project X` 与 `--project=X` 都认；
#     缺值 / 空值 / 重复 ⇒ **明确报错**（⛔ 不静默并进标题）。
#   ⛔ 守卫只**拒绝**，不做任何"编码修复"（修复会引入第二个变量）。

#: `--project` 残留（含 = 形式；`--project-x` 这类不拦）
_PROJECT_RESIDUE_RE = re.compile(r"--project(?![\w-])")
#: 其它 `--xxx=` 残留（参数被写进标题的典型形态）
_ARG_FLAG_RESIDUE_RE = re.compile(r"--[A-Za-z][\w-]*=")
#: 疑似 mojibake（PowerShell 传中文 argv 给 python 的典型产物；只列举，⛔ 不反向解码）
MOJIBAKE_MARKERS = ("鈥", "鏅", "锛", "銆", "\ufffd")


def _parse_create_args(args):
    """`create` 的 argv[2:] ⇒ `(title, project, template, error)`（内部实现 · 4 元组）。

    · `--project <名>` / `--project=<名>` 等价（修）
    · `--template <v1|v2|v3|v4>` / `--template=<v1|v2|v3|v4>` 等价（A/B 新增 · v3 同日新增；
      新增 v4 并将其设为缺省）
    · 缺值 / 空值 / 重复 / 未知 `--xxx` / 非法模板值 ⇒ `error`（四项均为 None；⛔ 不静默并进标题）
    · 其余 token 按原顺序用空格拼回标题（与旧 `" ".join(args)` 逐字一致）
    """
    project = None
    template = None
    title_parts = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--project" or a.startswith("--project="):
            if a == "--project":
                value = args[i + 1] if i + 1 < len(args) else None
                if value is None or value.startswith("--") or not value.strip():
                    return None, None, None, ("`--project` 后面没有项目名"
                                              "（写法：`--project <名>` 或 `--project=<名>`）")
                i += 2
            else:
                value = a.split("=", 1)[1]
                if not value.strip():
                    return None, None, None, "`--project=` 后面没有项目名（写法：`--project=<名>`）"
                i += 1
            if project is not None:
                return None, None, None, "`--project` 重复指定（只允许一次）"
            project = value
            continue
        if a == "--template" or a.startswith("--template="):
            if a == "--template":
                value = args[i + 1] if i + 1 < len(args) else None
                if value is None or value.startswith("--") or not value.strip():
                    return None, None, None, ("`--template` 后面没有值"
                                              "（写法：`--template v1|v2|v3|v4` 或 `--template=v1|v2|v3|v4`）")
                i += 2
            else:
                value = a.split("=", 1)[1]
                if not value.strip():
                    return None, None, None, "`--template=` 后面没有值（只能是 v1 / v2 / v3 / v4）"
                i += 1
            if template is not None:
                return None, None, None, "`--template` 重复指定（只允许一次）"
            template = value.strip().lower()
            if template not in TEMPLATE_VERSIONS:
                return None, None, None, ("`--template` 只能是 %s（收到：`%s`；"
                                          "环境变量 %s 优先于命令行）"
                                          % (" / ".join(TEMPLATE_VERSIONS), value, TEMPLATE_ENV))
            continue
        if a.startswith("--"):
            return None, None, None, ("未知参数 `%s`（create 只支持 `--project` / `--template`；"
                                      "标题请用引号包住，⛔ 别把参数写进标题）" % a)
        title_parts.append(a)
        i += 1
    return " ".join(title_parts), project, template, None


def parse_create_args(args):
    """**向后兼容**的 3 元组版本：`(title, project, error)`（既有调用方 / 用例依赖此签名）。"""
    title, project, _template, err = _parse_create_args(args)
    return title, project, err


def parse_create_args_full(args):
    """4 元组版本：`(title, project, template|None, error)`（`main` 用；template=None = 未指定）。"""
    return _parse_create_args(args)


def check_create_title(title):
    """纯函数：⇒ `(ok, reason)` —— 只拦「明显异常」的标题（⛔ 不修复 / 不转码 / 不落卡）。

    拦截两类故障形态：
      ① 参数残留：标题含 `--project` 或其它 `--xxx=`（说明参数被并进了标题）
      ② 疑似 mojibake：`鈥` / `鏅` / `锛` / `銆` / U+FFFD（PowerShell argv 编码产物）
    """
    if not title.strip():
        # 兼容：历史上有人 `create --project <名>` 不写标题（卡先建、标题后补）⇒ ⛔ 不因空标题改行为
        return True, ""
    m = _PROJECT_RESIDUE_RE.search(title)
    if m:
        return False, ("标题里残留了 `%s`（项目名没被识别 ⇒ 卡会落到 active/ 顶层）。"
                       "项目名请写在标题引号**外面**：`--project <名>` 或 `--project=<名>`"
                       % m.group(0))
    m = _ARG_FLAG_RESIDUE_RE.search(title)
    if m:
        return False, ("标题里残留了命令行参数 `%s`（参数别写进标题的引号里；"
                       "项目名用 `--project <名>` / `--project=<名>` 传）" % m.group(0))
    hit = [c for c in MOJIBAKE_MARKERS if c in title]
    if hit:
        return False, ("标题含疑似 mojibake 字符 `%s`（PowerShell 传中文 argv 的典型产物）"
                       "⇒ 拒绝建卡。⛔ 本工具不尝试修复编码，请用 UTF-8 安全方式重传标题"
                       % "".join(hit))
    return True, ""


def main(argv):
    # Windows 控制台默认 GBK ⇒ 显式 UTF-8（否则状态校验里的 ⛔/✅ 会 UnicodeEncodeError 崩掉）
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover
        pass
    if len(argv) < 2:
        print(help_text())
        return 1
    cmd = argv[1]
    args = argv[2:]
    # `--help` / `-h` / `help` —— 总览；`<命令> --help` —— 单命令用法（⛔ 不改任何卡）
    if cmd in ("--help", "-h", "help"):
        print(help_text())
        return 0
    if "--help" in args or "-h" in args:
        print(help_text(cmd if cmd in USAGE else None))
        return 0
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    if cmd == "create":
# 解析抽成纯函数 ⇒ `--project X` / `--project=X` 等价；
        # 缺值/空值/重复 ⇒ 明确报错（旧代码会把 `--project=X` 整段并进标题、卡落 active/ 顶层）。
        title, project, template, err = parse_create_args_full(args)
        if err:
            print("[task_card] ⛔ 参数错误：%s" % err)
            print(usage_for("create"))
            return 1
        ok, why = check_create_title(title)
        if not ok:
            print("[task_card] ⛔ 拒绝建卡：%s" % why)
            print("  ⛔ 未落卡（标题：%s）" % title)
            print(usage_for("create"))
            return 1
        return cmd_create(title, project, template=template)
    if cmd == "list":
        return cmd_list()
    if cmd == "archive":
        confirm = "--confirm" in args
        ids = [a for a in args if not a.startswith("--")]
        if len(ids) < 1:
            print(usage_for("archive"))
            return 1
        return cmd_archive(ids[0], confirm=confirm)
    if cmd == "claim":
        ids = [a for a in args if not a.startswith("--")]
        if len(ids) < 1:
            print(usage_for("claim"))
            return 1
        return cmd_claim(ids[0], dry_run=dry)
    if cmd == "capability":
        task_id, stage, name, why, err = parse_capability_args(args)
        if err:
            print("[task_card] ⛔ 参数错误：%s" % err)
            print(usage_for("capability"))
            return 1
        return cmd_capability(task_id, stage, name, why)
    if cmd == "capability-timing":
        ids = [a for a in args if not a.startswith("--")]
        if len(ids) < 1:
            print(usage_for("capability-timing"))
            return 1
        return cmd_capability_timing(ids[0])
    if cmd == "capability-hint":
        task_id, stage, err = parse_stage_only_args(args)
        if err:
            print("[task_card] ⛔ 参数错误：%s" % err)
            print(usage_for("capability-hint"))
            return 1
        return cmd_capability_hint(task_id, stage)
    if cmd == "release":
        state = None
        reason = None
        takeover = "--takeover" in args
        for a in args:
            if a.startswith("--state="):
                state = a.split("=", 1)[1].strip()
            elif a.startswith("--reason="):
                reason = a.split("=", 1)[1].strip()
        ids = [a for a in args if not a.startswith("--")]
        if len(ids) < 1:
            print(usage_for("release") + "\n  --takeover = 明知不是自己占用的、也要强制释放"
                  "（应急；推荐改用 `takeover`：一步接管 + 留痕）")
            return 1
        return cmd_release(ids[0], state=state, dry_run=dry, reason=reason, takeover=takeover)
    if cmd == "takeover":
        reason = None
        for a in args:
            if a.startswith("--reason="):
                reason = a.split("=", 1)[1].strip()
        ids = [a for a in args if not a.startswith("--")]
        if len(ids) < 1:
            print(usage_for("takeover"))
            return 1
        return cmd_takeover(ids[0], reason=reason, dry_run=dry)
    if cmd == "states":
        return cmd_states(off_vocab_only="--off-vocab" in args)
    # 未知命令 ⇒ 明确提示去哪看用法（原来只有一行 "unknown command"）
    try:
        import difflib
        near = difflib.get_close_matches(cmd, list(USAGE), n=2, cutoff=0.5)
    except Exception:  # pragma: no cover
        near = []
    print("unknown command: %s" % cmd)
    if near:
        print("  是不是想用：%s" % " / ".join(near))
    print("  看全部命令：python tools/task_card.py --help")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
