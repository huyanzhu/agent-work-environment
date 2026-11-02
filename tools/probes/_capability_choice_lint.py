# -*- coding: utf-8 -*-
"""_capability_choice_lint.py —— 「能力使用点」的机械校验（改读 `.log`）

🔴 重写（已确认口径）：**⛔ 不再解析卡正文**。
  卡是自由文本，正则只能猜格式（读数已出现假红）⇒ 能力选择改由
  `python tools/task_card.py capability …` 写进**同级 `.log`** 的结构化表格行，
  本探针只读 `.log`、只对时/对证据。

判据（三个固定点）：
  | stage | 判据 |
  |---|---|
  | `start` | `.log` 有 `能力-开工` 行 **且** 该行时间早于探针里该会话第一次 `edit` 的 `at` |
  | `impl`  | `.log` 有 `能力-实现` 行（同一能力贯穿可写「复用」） |
  | `close` | `.log` 有 `能力-收尾` 行；若 `name ≠ none` ⇒ 探针里该会话有 `read` 且 `pathClass` 含 `capabilities/` |

· 会话（session）从卡 `.log` 的 **claim 留痕**里取（最后一条 claim = 当前占用者）。
· 探针 = `.aios/_aios-activation.probe.log`，只看 `ev=tool-sig`（`pathClass` 不限）。
· **旧卡处理**（已定：只对新卡生效）：卡 `Created` 早于
  `task_cards/_TASK_CARD_template.md` 的 mtime ⇒ `SKIP`（⚪ 不算 FAIL，单独计数）。

🔴 （v3 · 新增一档）：卡上有「## 使用的能力（三阶段 · 可 none）」节 ⇒
  该阶段**卡字段**必须与 `.log` 的 `name` **一致**（不一致 ⇒ FAIL，detail 指出两边值）；
  v1/v2 卡**没有**该节 ⇒ 跳过这一档（⛔ 不判 FAIL —— 保护已有 A/B 数据）。
  三个 stage 的既有判据（上表）逐字不变。

🔴 （v4 · **单字段**）：按**卡形态**双模式判定（⛔ 不看模板版本号；判据单一来源 =
  `tools/task_card.py: card_capability_mode()`）：
  · 卡上有 `- 开工:` / `- 实现:` / `- 收尾:` 行（v1/v2/v3 旧卡）⇒ 上表**三阶段判据逐字不变**
    （两种行都在 ⇒ 旧卡优先，仍走三阶段）；
  · 卡上有 `- 能力:` 行（v4 新卡）⇒ **只要求一条** `.log` 行（State 列 = `能力`，name 不为空）：
    该行时间**不晚于**该会话首次 edit（探针取不到 ⇒ `timing: n/a`，⛔ 不判 FAIL）；**卡创建时间
    晚于该会话首次 edit ⇒ 首次 edit 不可能是本卡的改动 ⇒ 同样记 `timing: n/a`（⛔ 不判 FAIL，
    否则"同一会话里后建的第二张卡"会必红）**；该会话仍需 `read capabilities/` ≥ 1 次
    （name=none 除外，沿用既有口径）；`--stage` 在该卡上**忽略**（缺 `--stage` 也可判）；
  · 两种行都没有 ⇒ 走既有 SKIP / PENDING 逻辑（⛔ 不因"没这两行"判 FAIL）。

用法：
  python tools/probes/_capability_choice_lint.py <卡路径或 TASK-ID> [--stage start|impl|close]
  python tools/probes/_capability_choice_lint.py --all [--stage start|impl|close]
  （单字段卡可省略 `--stage`；旧三阶段卡仍必须给）

输出（单卡）：
  {"card": ..., "stage": ..., "verdict": "PASS|FAIL|SKIP", "detail": ...,
   "name": ..., "timing": "before-first-edit|after|n/a"}
输出（`--all`）：每 stage 的 PASS / FAIL / SKIP 计数 + 总数（JSON）。
退出码：PASS / SKIP ⇒ 0；FAIL ⇒ 1；参数错误 ⇒ 2。
"""
import datetime
import glob
import gzip
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAPS = os.path.join(ROOT, "capabilities")
PROBE = os.path.join(ROOT, ".aios", "_aios-activation.probe.log")
TEMPLATE = os.path.join(ROOT, "task_cards", "_TASK_CARD_template.md")
ACTIVE = os.path.join(ROOT, "task_cards", "active")

# 🔴 机制生效时点（固定常量 · ⛔ 不随模板/本文件 mtime 移动）
#     = `capability` 子命令首次落地时刻。此前的卡一律 SKIP（只对新卡生效）。
ACTIVATION_CUTOFF = datetime.datetime(2026, 11, 1, 19, 10, 0)

# 复用既有卡解析（裸 ID / `项目/ID` / 路径后缀）—— ⛔ 不在这里另写一套
sys.path.insert(0, os.path.join(ROOT, "tools"))
try:
    import task_card as CARD  # noqa: E402
except Exception:  # pragma: no cover
    CARD = None

#: stage ⇒ `.log` 的 State 列取值（与 `tools/task_card.py` 同源口径）
STAGE_LABEL = {"start": "能力-开工", "impl": "能力-实现", "close": "能力-收尾"}
STAGES = ("start", "impl", "close")

# （v4）：单字段卡的 `.log` State 列取值（`--stage` 在该形态上被忽略）
SINGLE_LABEL = "能力"
#: 卡形态（`task_card.card_capability_mode()` 的两个返回值）
MODE_LEGACY = "legacy"
MODE_SINGLE = "single"

# `--all` 扫卡时跳过的依赖/构建目录（否则会把 node_modules 当卡扫 · 读数 1399 条噪点）
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "coverage",
             "tests", "assets", "__pycache__"}

#: 卡 Header 的创建时间（`Created: YYYY-MM-DD HH:mm`；缺时间部分时按 00:00）
CREATED_RE = re.compile(
    r"^\s*Created:\s*(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", re.M)
#: `.log` 能力行的 Reason 列：`<name> ｜ 理由：<why>`（全角竖线）
REASON_RE = re.compile(r"^(?P<name>[^｜]+?)\s*｜\s*理由[:：]\s*(?P<why>.*)$")
#: claim 留痕（取会话 id；与 `tools/task_card.py` 写出的行同源）
CLAIM_RE = re.compile(r"claim\s*占用（session:\s*([^）]*)）")


# ── 读 / 路径 ────────────────────────────────────────────────────────────────

def _read(path):
    return io.open(path, encoding="utf-8", errors="replace").read()


def _rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def _log_path(card_path):
    """卡路径 ⇒ 同级同名 `.log`（`X.md` → `X.log`）。"""
    if card_path.lower().endswith(".md"):
        return card_path[:-3] + ".log"
    return card_path + ".log"


def resolve_card(arg):
    """`<卡路径或 TASK-ID>` ⇒ `(卡路径, 错误)`；路径存在 ⇒ 直接用，否则复用 `task_card._find_card`。"""
    if arg.lower().endswith(".md") and os.path.isfile(arg):
        return os.path.abspath(arg), None
    if CARD is None:
        return None, "无法解析 TASK-ID（tools/task_card.py 不可用）"
    return CARD._find_card(arg)


def card_files():
    """`task_cards/active/**/TASK-*.md`（跳过依赖/构建目录）。"""
    out = []
    if not os.path.isdir(ACTIVE):
        return out
    for root, dirs, names in os.walk(ACTIVE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            # ⚠️ 修：`-OPERATIONS.md` 是派生件（不是真卡），不参与计数
            if n.startswith("TASK-") and n.endswith(".md") and not n.endswith("-OPERATIONS.md"):
                out.append(os.path.join(root, n))
    return sorted(out)


# ── `.log` 表格读取 ──────────────────────────────────────────────────────────

def log_rows(card_path):
    """→ `[{time, state, reason, worker}]`（去表头/分隔线；跳过空行与非表格行）。"""
    log = _log_path(card_path)
    if not os.path.isfile(log):
        return []
    rows = []
    for line in _read(log).split("\n"):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[0] == "Time" or cells[1] == "State" or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append({"time": cells[0], "state": cells[1], "reason": cells[2],
                     "worker": cells[3] if len(cells) > 3 else ""})
    return rows


def stage_row(rows, stage):
    """该 stage 的第一条能力行（追加日志 ⇒ 首次声明即权威；后补是更正，仍按首条判）。"""
    label = STAGE_LABEL[stage]
    for r in rows:
        if r["state"] == label:
            return r
    return None


def card_mode(card_path):
    """卡路径 ⇒ `"legacy"` | `"single"` | `None`（判据**单一来源**：`task_card.card_capability_mode`）。

    `task_card` 不可用时 ⇒ `None`（退回既有三阶段 / SKIP 逻辑，⛔ 不另写一套正则）。
    """
    if CARD is None:
        return None
    try:
        return CARD.card_capability_mode(_read(card_path))
    except Exception:  # pragma: no cover - 卡读不到等异常 ⇒ 当"判不出形态"
        return None


def single_row(rows):
    """单字段卡的**最后一条** `能力` 行（⛔ 不混入 `能力-开工|实现|收尾`）。

    🔴 （定 A 案）：单字段卡改「**末条即权威**」（last-wins）——
    理由是注入侧（runtime `declaredDomainCapabilityOf`）读的就是 `.log` **末条**；
    校验侧若读首条，会造成「更新声明 ⇒ 两边不一致」⇒ agent 理性选择"永不更新"
    ⇒ 跨域任务的声明校正（`re-injected`）永远触发不了。
    ⚠️ 旧三阶段卡**不受影响**（那条仍按首条，见 `stage_row`）。
    """
    hit = None
    for r in rows:
        if r["state"] == SINGLE_LABEL:
            hit = r
    return hit


def parse_reason(reason):
    """Reason 列 ⇒ `(name, why)`；格式不符 ⇒ `(None, None)`。"""
    m = REASON_RE.match((reason or "").strip())
    if not m:
        return None, None
    return m.group("name").strip().strip("`").strip(), m.group("why").strip()


def claim_sessions(rows):
    """从 `.log` 的 claim 留痕按出现顺序取会话 id（已归一化：去 `session-` 前缀）。"""
    out = []
    for r in rows:
        m = CLAIM_RE.search(r["reason"])
        if not m:
            continue
        sid = norm_session(m.group(1))
        if sid and sid != "-":
            out.append(sid)
    return out


def norm_session(s):
    """探针与 `.log` 两种写法归一：`session-<id>` / `<id>` ⇒ `<id>`。"""
    s = (s or "").strip()
    if s.startswith("session-"):
        s = s[len("session-"):]
    return s


# ── 时间 / 阈值 ──────────────────────────────────────────────────────────────

def card_state(card_path):
    """卡当前 State（Header/Current Status 里的 `State:` 行）；读不到 ⇒ None。"""
    m = re.search(r"^\s*State:\s*([A-Za-z_]+)", _read(card_path), re.M)
    return m.group(1) if m else None


def card_created_at(card_path):
    """卡创建时间 ⇒ `(datetime|None, 来源)`。

    优先 Header 的 `Created:`（**卡自身声明的创建时间**）；缺失/不可解析 ⇒ 退回文件 mtime。
    """
    head = _read(card_path)[:8000]
    m = CREATED_RE.search(head)
    if m:
        try:
            return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                     int(m.group(4) or 0), int(m.group(5) or 0)), "Created"
        except ValueError:
            pass
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(card_path)), "mtime"
    except OSError:
        return None, "none"


def template_mtime():
    """旧卡阈值。

    🔴 修：原实现用**模板 mtime** —— 每次改模板都会把此前**所有**卡判成旧卡 SKIP
    ⇒ 账本永远攒不出历史（改一次模板，全部历史读数作废）。改为**固定截止时刻常量**：
    机制生效时点 = （首次落地 `capability` 子命令的时刻）。
    此后新建的卡才会被检查；⛔ 改模板/改本文件都不再移动这条边界。
    """
    return ACTIVATION_CUTOFF


def activation_cutoff():
    """机制生效时点（固定常量 · 不随文件 mtime 移动）。"""
    return ACTIVATION_CUTOFF


def row_datetime(card_path, hhmm):
    """`.log` 行的 `HH:MM` ⇒ datetime（日期取 `.log` 的 mtime 日期）。

    行的粒度只有分钟 ⇒ 秒按 `:00` 计；这样"同一分钟内的 edit"仍算**晚于**开工记录
    （否则同一分钟必假红）。跨天时若日志 mtime 已是当天，旧行按旧日期比较也无害。
    """
    m = re.match(r"^(\d{1,2}):(\d{2})$", (hhmm or "").strip())
    if not m:
        return None
    log = _log_path(card_path)
    try:
        base = datetime.datetime.fromtimestamp(os.path.getmtime(log))
    except OSError:
        try:
            base = datetime.datetime.fromtimestamp(os.path.getmtime(card_path))
        except OSError:
            base = datetime.datetime.now()
    return datetime.datetime(base.year, base.month, base.day,
                             int(m.group(1)), int(m.group(2)))


# ── 探针索引 ────────────────────────────────────────────────────────────────

def _probe_files():
    """现役探针日志 + **所有轮转归档**（`.aios/*.probe.log*.gz`）。

    🔴 （复核读数）：只读现役日志会在**轮转**后丢失历史证据 ——
       实际：`TASK-20261102-019` 的 `capabilities/` 读取落在归档里 ⇒ 现役日志 0 次 ⇒ 误判 FAIL，
       含归档后同一会话读 1 次。⇒ 判据的证据源必须跨轮转连续。
    """
    paths = [PROBE] if os.path.isfile(PROBE) else []
    paths += sorted(glob.glob(PROBE + "*.gz"))
    return paths


def probe_index():
    """→ `(first_edit, cap_reads)`：{session: 第一次 edit 的 datetime} / {session: read capabilities/ 次数}。

    只读 `ev=tool-sig`；`pathClass` **不限**（开工判据按规格不看路径）。
    """
    first_edit, cap_reads = {}, {}
    paths = _probe_files()
    if not paths:
        return first_edit, cap_reads
    for path in paths:
        opener = gzip.open if path.endswith(".gz") else io.open
        with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"tool-sig"' not in line:
                    continue
                try:
                    d = json.loads(line.split("] ", 1)[1])
                except Exception:
                    continue
                sid = norm_session(d.get("session"))
                if not sid:
                    continue
                tool = d.get("tool")
                if tool == "edit":
                    try:
                        dt = datetime.datetime.fromtimestamp(float(d.get("at")) / 1000.0)
                    except (TypeError, ValueError, OSError):
                        continue
                    if sid not in first_edit or dt < first_edit[sid]:
                        first_edit[sid] = dt
                elif tool == "read" and "capabilities/" in str(d.get("pathClass") or ""):
                    cap_reads[sid] = cap_reads.get(sid, 0) + 1
    return first_edit, cap_reads


# ── 判据 ────────────────────────────────────────────────────────────────────

def _skip_result(card_path, stage, created, src, tpl):
    return {
        "card": _rel(card_path),
        "stage": stage,
        "verdict": "SKIP",
        "detail": ("旧卡：创建时间 %s（来源 %s）早于机制生效时点 %s ⇒ 只对新卡生效（⚪ 不算 FAIL）"
                   % (created.strftime("%Y-%m-%d %H:%M"), src,
                      tpl.strftime("%Y-%m-%d %H:%M:%S"))),
        "name": None,
        "timing": "n/a",
    }


def _check_single_field(card_path, rows, probe, stage, base):
    """v4 单字段卡：只要求一条 `能力` 行（`stage` 一律忽略；判据见模块 docstring）。

    - 缺 `能力` 行 ⇒ FAIL（单字段卡的能力记录是**必填**，不是三阶段里的某一段）
    - 该行时间不晚于该会话首次 edit；探针取不到 ⇒ `timing: n/a`（⛔ 不判 FAIL）
    - name ≠ none ⇒ 该会话必须 read `capabilities/` ≥ 1（沿用既有口径）
    """
    row = single_row(rows)
    if row is None:
        base["verdict"] = "FAIL"
        base["detail"] = ("缺 `能力` 记录：`.log` 里没有 State=`能力` 的行（已检查 %d 行）"
                          " -> 先跑 `capability <ID> --name <域能力|none> --why \"...\"`"
                          % len(rows))
        return base

    name, _why = parse_reason(row["reason"])
    if name is None:
        base["verdict"] = "FAIL"
        base["detail"] = ("`能力` 行格式不符（应为 `<name> ｜ 理由：<why>`）：`%s`"
                          % row["reason"])
        return base
    base["name"] = name

    sessions = claim_sessions(rows)
    if not sessions:
        base["verdict"] = "FAIL"
        base["detail"] = "`.log` 无 claim 留痕 -> 取不到会话，无法核对探针"
        return base
    sid = sessions[-1]

    first = probe[0].get(sid)
    row_dt = row_datetime(card_path, row["time"])
    card_dt, _src = card_created_at(card_path)
    note = ""
    if first is not None and card_dt is not None and card_dt > first:
        # 卡建在该会话首次 edit **之后** ⇒ 那次 edit 不可能是本卡的改动（同一会话里的第 N 张卡）
        # ⇒ 计时无从判起：记 n/a，⛔ 不判 FAIL（否则"后建卡"必红 = 假红）。
        base["timing"] = "n/a"
        note = "；计时 n/a（卡创建时间晚于该会话首次 edit，首次 edit 不属于本卡）"
    elif first is None or row_dt is None:
        # 探针取不到 / 行时间不可解析 ⇒ 记 n/a，⛔ 不判 FAIL
        base["timing"] = "n/a"
        note = ("；计时 n/a（%s）"
                % ("探针里该会话无 `edit` 记录" if first is None
                   else "`能力` 行时间不可解析：%s" % row["time"]))
    elif row_dt <= first:
        base["timing"] = "before-first-edit"
    else:
        base["timing"] = "after"
        base["verdict"] = "FAIL"
        base["detail"] = ("`能力` %s **晚于**该会话首次 edit %s -> 能力记录落在实质改动之后"
                          % (row_dt.strftime("%Y-%m-%d %H:%M"),
                             first.strftime("%Y-%m-%d %H:%M:%S")))
        return base

    if name == "none":
        base["verdict"] = "PASS"
        base["detail"] = "`.log` 有 `能力` 行且 name=none（单字段卡）" + note
        return base
    n = probe[1].get(sid, 0)
    if n > 0:
        base["verdict"] = "PASS"
        base["detail"] = ("`.log` 有 `能力` 行（name=%s）· 该会话 read `capabilities/` %d 次%s"
                          % (name, n, note))
    else:
        base["verdict"] = "FAIL"
        base["detail"] = ("`.log` 有 `能力` 行（name=%s），但探针里该会话**没有** "
                          "`capabilities/` read（声称用了但没打开）" % name)
    return base


def check_one(card_path, stage, probe=None, tpl=None):
    """单卡单 stage ⇒ 结果 dict（判据见模块 docstring；单字段卡上 `stage` 被忽略）。"""
    probe = probe if probe is not None else probe_index()
    tpl = tpl if tpl is not None else template_mtime()
    created, src = card_created_at(card_path)

    # 旧卡：Created 早于机制生效时点 ⇒ SKIP（⛔ 不算 FAIL）
    if created is not None and tpl is not None and created < tpl:
        return _skip_result(card_path, stage, created, src, tpl)

    rows = log_rows(card_path)
    base = {"card": _rel(card_path), "stage": stage, "name": None, "timing": "n/a"}

    # 🔴 （v4）：卡形态双模式 —— 单字段卡只查一条 `能力` 行，`stage` 忽略。
    mode = card_mode(card_path)
    if mode == MODE_SINGLE:
        return _check_single_field(card_path, rows, probe, stage, base)

    row = stage_row(rows, stage)
    if row is None:
        # 🔴 修：**进行中的卡**（State=Planning/Executing）没有该行是正常的
        # ⇒ 判 PENDING（⛔ 不算 FAIL）；否则 `--all` 会把正在跑的 worker 全报成失败。
        st = card_state(card_path)
        if st in ("Planning", "Executing"):
            base["verdict"] = "PENDING"
            base["detail"] = ("卡状态 %s（进行中）· `.log` 暂无 `%s` 行（已检查 %d 行）"
                              % (st, STAGE_LABEL[stage], len(rows)))
            return base
        base["verdict"] = "FAIL"
        base["detail"] = ("`.log` 里没有 `%s` 行（已检查 %d 行 · 卡状态 %s）⇒ 该阶段未记录"
                          % (STAGE_LABEL[stage], len(rows), st or "?"))
        return base

    name, why = parse_reason(row["reason"])
    if name is None:
        base["verdict"] = "FAIL"
        base["detail"] = ("`%s` 行格式不符（应为 `<name> ｜ 理由：<why>`）：`%s`"
                          % (STAGE_LABEL[stage], row["reason"]))
        return base
    base["name"] = name

    # 🔴 v3卡上有「使用的能力」节 ⇒ 卡字段必须与 `.log` 的 name 一致。
    #   仅当卡有该节时才校验（v1/v2 卡没有 ⇒ 跳过，⛔ 不判 FAIL）。
    if CARD is not None:
        card_text = _read(card_path)
        if CARD.has_capability_section(card_text):
            card_name, _card_line = CARD.capability_card_value(card_text, stage)
            if card_name != name:
                base["verdict"] = "FAIL"
                base["detail"] = (
                    "卡字段与 `.log` 不一致：卡上 `%s` = `%s` · `.log` `%s` 行 = `%s`"
                    % (STAGE_LABEL[stage], card_name if card_name is not None
                       else "(缺失/格式不符)", STAGE_LABEL[stage], name))
                return base

    if stage == "impl":
        base["verdict"] = "PASS"
        base["detail"] = ("`.log` 有 `能力-实现` 行（name=%s%s）"
                          % (name, " · 理由写「复用」" if "复用" in why else ""))
        return base

    sessions = claim_sessions(rows)
    if not sessions:
        base["verdict"] = "FAIL"
        base["detail"] = "`.log` 无 claim 留痕 ⇒ 取不到会话，无法核对探针"
        return base
    sid = sessions[-1]

    if stage == "start":
        first = probe[0].get(sid)
        if first is None:
            # 🔴 修：开工行已记但**还没有任何 edit**（worker 正在进行中）
            # ⇒ 判 PENDING（⛔ 不算 FAIL）；卡已收口却仍无 edit ⇒ 才判 FAIL。
            st = card_state(card_path)
            if st in ("Planning", "Executing"):
                base["verdict"] = "PENDING"
                base["detail"] = ("卡状态 %s（进行中）· 该会话（%s…）尚无 `edit` ⇒ 暂无法判定先后"
                                  % (st, sid[:8]))
                return base
            base["verdict"] = "FAIL"
            base["detail"] = ("探针里该会话（%s…）**没有 `edit` 记录** ⇒ 无法证明开工记录先于首次改动（卡状态 %s）"
                              % (sid[:8], st or "?"))
            return base
        row_dt = row_datetime(card_path, row["time"])
        if row_dt is None:
            base["verdict"] = "FAIL"
            base["detail"] = "`.log` 行时间不可解析：`%s`" % row["time"]
            return base
        base["timing"] = "before-first-edit" if row_dt < first else "after"
        if row_dt < first:
            base["verdict"] = "PASS"
            base["detail"] = ("`能力-开工` %s 早于该会话首次 edit %s（session %s…）"
                              % (row_dt.strftime("%H:%M"),
                                 first.strftime("%Y-%m-%d %H:%M:%S"), sid[:8]))
        else:
            base["verdict"] = "FAIL"
            base["detail"] = ("`能力-开工` %s **不早于**该会话首次 edit %s ⇒ 开工记录落在实质改动之后"
                              % (row_dt.strftime("%Y-%m-%d %H:%M"),
                                 first.strftime("%Y-%m-%d %H:%M:%S")))
        return base

    # close：name ≠ none ⇒ 探针里该会话必须有 read capabilities/
    if name == "none":
        base["verdict"] = "PASS"
        base["detail"] = "`.log` 有 `能力-收尾` 行且 name=none（⛔ 不要求 capabilities/ read）"
        return base
    n = probe[1].get(sid, 0)
    if n > 0:
        base["verdict"] = "PASS"
        base["detail"] = ("`.log` 有 `能力-收尾` 行（name=%s）· 该会话 read `capabilities/` %d 次"
                          % (name, n))
    else:
        base["verdict"] = "FAIL"
        base["detail"] = ("`.log` 有 `能力-收尾` 行（name=%s），但探针里该会话**没有** "
                          "`capabilities/` read（声称用了但没打开）" % name)
    return base


def run_all(stage=None):
    """`--all`：每 stage 的 PASS / FAIL / SKIP 计数 + 总数（JSON）。"""
    stages = [stage] if stage else list(STAGES)
    files = card_files()
    probe = probe_index()
    tpl = template_mtime()
    out = {"total": len(files), "stages": {}}
    for st in stages:
        counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
        failures = []
        for f in files:
            r = check_one(f, st, probe=probe, tpl=tpl)
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
            if r["verdict"] == "FAIL":
                failures.append({"card": r["card"], "detail": r["detail"]})
        out["stages"][st] = {"PASS": counts["PASS"], "FAIL": counts["FAIL"],
                             "SKIP": counts["SKIP"], "total": len(files)}
        if failures:
            out["stages"][st]["failures"] = failures[:10]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv):
    # Windows 控制台默认 GBK ⇒ 显式 UTF-8（detail 里的箭头/符号否则会让 `--all` 打印时崩掉）
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover
        pass
    args = list(argv[1:])
    stage = None
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--stage":
            if i + 1 >= len(args):
                print("⛔ `--stage` 后面没有值（start / impl / close）")
                return 2
            stage = args[i + 1]
            i += 2
            continue
        if a.startswith("--stage="):
            stage = a.split("=", 1)[1]
            i += 1
            continue
        rest.append(a)
        i += 1
    if stage is not None and stage not in STAGE_LABEL:
        print("⛔ `--stage` 必须是 %s（收到 `%s`）" % (" / ".join(STAGES), stage))
        return 2

    if "--all" in rest:
        rest = [a for a in rest if a != "--all"]
        if rest:
            print("⛔ `--all` 不接受位置参数：%s" % " ".join(rest))
            return 2
        return run_all(stage)

    if not rest:
        print(__doc__)
        return 2
    if len(rest) > 1:
        print("⛔ 只能给一个卡路径或 TASK-ID（收到：%s）" % " ".join(rest))
        return 2
    path, err = resolve_card(rest[0])
    if path is None:
        print("⛔ 卡未找到：%s" % err)
        return 2
    if stage is None:
        # 🔴 （v4）：单字段卡不看 stage ⇒ 缺省它也能判（旧三阶段卡仍需显式给）
        if card_mode(path) == MODE_SINGLE:
            stage = "once"
        else:
            print("⛔ 需要 `--stage start|impl|close`（单字段卡可省略；或用 `--all` 看全量）")
            return 2
    r = check_one(path, stage)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["verdict"] in ("PASS", "SKIP") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
