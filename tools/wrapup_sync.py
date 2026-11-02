#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI-OS 收尾自动写回脚本（无感最小集第 2 项）
============================================
设计来源：AI-OS_无感使用设计_.md §3.4（E-6：状态写回自动化，不靠 Agent 手动填状态字段）
reshape：V2 已删除 CURRENT_GOAL.md（被 task_cards 替代）——写回对象改为**任务卡 Event Log**。
修正：git 事实取自**任务卡 Goal 中定位的项目目录**（有独立 git 用其提交；untracked/无 git 用项目内最近修改文件），不再取根仓库旧提交（off-topic 噪音）。
 reshape：收尾写回后检查 SUCCESS_LOG 是否已为本任务追加 Entry，无则提示（把账本触发放进收尾路径；Phase 1 实证：Agent 收尾无 SUCCESS_LOG 概念）。
Learning Closure reshape：收尾时把"是否值得沉淀经验"放进决策空间（只加判断入口，不强制产生 Knowledge；Phase 1-4 实证：沉淀概念从未进入 Agent 收尾 reasoning）。
Gap 修复（A/B/C）+ 幂等（Step 1–2，依据 research/baseline/AUTOMATION-BOUNDARY.md §6.2 §6.3）：
  · Gap A：find_target_card 改为**递归** active/（含项目文件夹）——原实现只扫平层，AI-OS-Adaptation/
    这类项目文件夹内的卡**结构性找不到**（两次可复现："未找到任务卡——跳过"）。
  · Gap B：find_project_dir **优先取"卡自身所在目录"**（卡在项目文件夹内 ⇒ 该文件夹即项目），
    正则抓盘符路径降为回退 —— 原实现会从 Goal 文本抓到无关路径。
  · Bug C：未找到卡时的提示不再无条件拼 "TASK-" 前缀（原会输出 TASK-TASK-…）。
  · 幂等：同一次提交重复调用只写一行（判据 = commit hash 是否已在卡的 Event Log 里）。
    ⚠️ **不新增状态文件** —— 幂等依据是【已有文件】。AI-OS 可以有自己的 loop，但**不能有自己的账本**。

R2 选卡修复 + R3 账本写回（来源：`AUTOMATION-BOUNDARY.md` §12.3 §12.4 §12.4.1 ·
批准 §12 → Phase 1 写码）：
  · **R2 选卡：目标卡不猜** —— 原实现取"全库最新 mtime" ⇒ 编辑一张卡，Stop 的落点就跟着跳卡
    （读数 11:09 → 11:48）。新判据（**禁止仅凭 mtime**）= 显式 TASK-ID ▸ 显式 `--project` ▸
    git 改动事实（改动**直指卡文件** ▸ 改动落在**项目文件夹**）；
    **无法唯一确定 ⇒ 跳过写回 + 留诊断**（不静默）。
    ⚠️ 代价（如实记）：自动路径会比过去**更多地跳过** —— 宁漏不错，因为写错卡 = 污染别的卡的历史。
  · **R3 账本：Stop 多写一个目标**（§10 已裁 (b) · 第 ⑤ 步落地）—— 追加 `样例账本.md` 的
    **机械事实** Entry；与卡写回**各自独立 try**（一个失败不影响另一个）。
    🔴 机制**不写** `Outcome` / `footprint` / `influence`（一律留占位标「待补」）——
    否则 AI-OS 会**自己给自己打分**，与 Sovereignty 冲突。
    ⚠️ 仍**不新增状态源**：写的是**已有**账本，幂等键 = **(卡, commit)**（不能只用 commit ——
    一次 commit 可能对应多张卡，那会吞掉另一张卡的记录）。

做什么：
  任务收尾运行时，从 git 提取本次实际改动，把收尾事件追加到指定任务卡（TASK-*.md）的
  Event Log——Agent 不需要记得手动登记收尾，事实由 git 生成。

为什么这样设计（对第一纪元死因）：
  - resume.py 死于"无自动触发点"——本脚本被设计为收尾链的一环，挂在 git 提交/收尾流程上，
    不依赖 Agent 记得跑。
  - K-027 实证：状态字段是最容易遗漏的（Agent 写内容字段忠实、状态字段漏改）——自动写回消灭遗漏。

用法：
  python tools/wrapup_sync.py [TASK-ID] [--dry-run] [--force]
  TASK-ID 例如 TASK-20260821-008（不传则扫描 active 找最近更新的卡）。
  --force  跳过幂等自检（同一次提交也强制再写一行）。

输出：
  dry-run: 只打印将更新的内容，不写文件。
  正式:    在任务卡 Event Log 追加一条收尾事件（最近提交 + 改动文件 + 未提交提醒），返回改动行数。
"""
import subprocess
import sys
import os
import datetime
import json
import re
import time

# 修复（缺陷 ①）：挂在 Stop hook 上时 stdout 由宿主捕获，
# 解释器编码随 locale（Windows 默认 GBK）⇒ print 提示语里的 '⇒'（U+21D2）
# 抛 UnicodeEncodeError ⇒ **每轮 turn 结束都以非零码退出**（被 hooks.json 的
# `|| exit 0` 掩盖、且 stderr 空导致 hook/result 无 stderrSummary ⇒ 表面"干净"）。
# 修法：把两个流显式改成 UTF-8（errors=replace 保证任何字符都不会再炸）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

from _root_guard import guard
guard(__file__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS_DIR = os.path.join(ROOT, "task_cards")
ACTIVE_DIR = os.path.join(CARDS_DIR, "active")

# Event Log 容量（卡内上限不变，满了把"即将被归档的"迁入兜底日志）
EVENT_LOG_MAX_ROWS = 20   # 卡模板「Event Log (max 20 entries)」的数据行上限
EVENT_LOG_KEEP_ROWS = 10  # 触顶后卡内保留的最近条数（必须 < MAX，否则迁完还是满的）

# 写盘重试（缺陷 ⑤：Stop hook 读数被 `PermissionError: [Errno 13]` 打死一次）
# 实际：hook 在 turn 结束（21:12:12）写卡时被拒，而同一文件 21:11:44 刚被 Agent 的编辑器写过
# ⇒ Windows 上"另一个进程仍持有句柄 / 杀毒或索引器正在扫"造成的**瞬时占用**。
# 这类错误重试即可；不重试则"一次瞬时占用 = 整轮写回丢失"，正是本机制要消灭的失败模式。
IO_RETRY_LIMIT = 8
IO_RETRY_DELAY_MS = 120   # 退避窗口 ≈ 4.3s：覆盖 Agent 编辑器/索引器/杀毒的典型占用时长
# 诊断开关（临时）：设 WRAPUP_IO_DEBUG=1 时打印每次重试的失败详情
_IO_DEBUG = bool(os.environ.get("WRAPUP_IO_DEBUG"))
# 决策留痕开关：设 WRAPUP_DECIDE_LOG=1 时，把每次运行的判据写入 scratch/_wrapup-decisions.log
_DECIDE_LOG = bool(os.environ.get("WRAPUP_DECIDE_LOG"))


def retry_io(fn, what):
    """执行一个可能因**瞬时占用**失败的 IO 动作，按 IO_RETRY_* 退避重试。

    缺陷 ⑤：Stop hook 读数被 `PermissionError: [Errno 13]` 打死一次
    （Agent 的编辑器/工具刚写过同一文件，Windows 上句柄尚未释放）。
    端到端读数（`experiments/`）暴露两个要点：
      · 只有**写入**重试不够 —— `open(...,'r')` / `f.read()` 同样会被占用拒绝（异常先出现在读取处）；
      · `os.replace(tmp, target)` 在 target 被占用时也会被拒 ⇒ 必须整体重试。
    """
    last = None
    for attempt in range(IO_RETRY_LIMIT):
        try:
            return fn()
        except OSError as e:
            last = e
            retryable = getattr(e, "errno", None) in (13, 1, 16) or getattr(e, "winerror", None) in (5, 32, 33)
            if _IO_DEBUG:
                try:
                    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_wrapup_io_debug.log"),
                              "a", encoding="utf-8") as f:
                        f.write(f"{what} attempt {attempt + 1}/{IO_RETRY_LIMIT} retryable={retryable} "
                                f"{type(e).__name__} errno={e.errno} winerror={getattr(e, 'winerror', None)}\n")
                except OSError:
                    pass
            if not retryable:
                raise
            time.sleep(IO_RETRY_DELAY_MS / 1000.0 * (attempt + 1))
    raise last


def read_text_retry(path):
    """读文件（重试瞬时占用）；文件不存在时抛 OSError 由调用方处理。"""
    def _do():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return retry_io(_do, f"read({os.path.basename(path)})")


def write_with_retry(path, text):
    """原子写：重试瞬时占用（EACCES/EPERM/EBUSY）；失败时抛出最后一个异常。"""
    def _do():
        tmp = f"{path}.wrapup-tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)   # 同目录 rename 才是原子的；避免"写一半被杀"
    retry_io(_do, f"write({os.path.basename(path)})")


def append_with_retry(path, text):
    """追加写：重试瞬时占用；失败时抛出最后一个异常。"""
    def _do():
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    retry_io(_do, f"append({os.path.basename(path)})")


def git(cmd, cwd):
    # Windows 默认 GBK 解码会炸中文提交信息——git 输出按 UTF-8 解
    r = subprocess.run(["git"] + cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip(), r.returncode


def find_project_dir(card_path):
    """定位该卡所属的项目目录。

    优先级（修正 Gap B —— 原实现只靠正则抓盘符路径，会抓偏）：
      ① 卡在【项目文件夹】内（active/<PROJECT>/TASK-*.md）⇒ 取该文件夹
         —— 这是最可靠的事实：卡自己就在那儿
      ② 回退：卡内文本里的盘符路径（原逻辑，仅用于平铺卡指向外部项目的情况）
    """
    parent = os.path.dirname(os.path.abspath(card_path))
    if os.path.normcase(parent) != os.path.normcase(os.path.abspath(ACTIVE_DIR)):
        return parent

    with open(card_path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"## Goal\s*\n(.*?)(?=\n## |\Z)", text, re.S)
    goal = m.group(1) if m else text
    candidates = re.findall(r"[A-Za-z]:[\\/][^\s`\"'<>|]+", goal) + \
                 re.findall(r"[A-Za-z]:[\\/][^\s`\"'<>|]+", text)
    seen = set()
    for p in candidates:
        norm = p.replace("/", "\\").rstrip("\\.,;:)]}") if p else p
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.isdir(norm):
            return norm
    return None


def nearest_git_root(path):
    """从 path 向上找最近的含 .git 的目录。"""
    cur = os.path.abspath(path)
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def recent_project_files(project_dir, limit=5):
    """项目内最近修改的代码/文档文件（mtime 事实，供 untracked 项目使用）。"""
    entries = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules", "data", "demo")]
        for name in files:
            if name.endswith((".py", ".md", ".json", ".html")):
                p = os.path.join(root, name)
                try:
                    entries.append((os.path.getmtime(p), p))
                except OSError:
                    pass
    entries.sort(reverse=True)
    rels = []
    for _, p in entries[:limit]:
        try:
            rels.append(os.path.relpath(p, project_dir).replace("\\", "/"))
        except ValueError:
            rels.append(p)
    return rels


def git_facts(project_dir):
    """返回 (last_msg, files_desc, dirty_desc)。git 事实优先取项目目录的提交；无 git 才用 mtime。

    修正：原实现在项目内有**未跟踪文件**（`git status` 的 `??` 行）时整条链降级，
    连 `last_msg` 也退化成「（项目未纳入独立 git / untracked）」——
    后果一：描述与事实不符（历史上有 Flaky 记录）；
    后果二（踩到，更严重）：`stop_idem` 依赖 `last_msg` 的首段 hash，
      兜底日志文件一出现（它就是未跟踪文件）⇒ `last_msg` 变成占位文本 ⇒ **幂等彻底失效**，
      每轮重复写回（隔离自测第 [3] 步可复现）。
    修法：**有 git 就必须用 git 事实**（提交 + 改动文件）；未跟踪项只如实计入 `dirty_desc`。
    mtime 分支只留给"项目根本不在任何 git 仓库内"这一种情况。
    """
    git_root = nearest_git_root(project_dir)
    if git_root:
        rel = os.path.relpath(project_dir, git_root).replace("\\", "/")
        last_msg, _ = git(["log", "-1", "--pretty=format:%h %s"], git_root)
        files, _ = git(["-c", "core.quotepath=false", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD", "--", rel], git_root)
        file_list = [f for f in files.splitlines() if f.strip() and f.startswith(rel)]
        names = ", ".join(f.replace(rel + "/", "", 1) for f in file_list[:3])
        files_desc = f"{names} 等 {len(file_list)} 个文件" if len(file_list) > 3 else (names or "（无）")
        dirty, _ = git(["status", "--porcelain", "--", rel], git_root)
        dirty_lines = [l for l in dirty.splitlines() if l.strip()]
        untracked_n = len([l for l in dirty_lines if l.startswith("??")])
        dirty_desc = f"未提交 {len(dirty_lines)} 项"
        if untracked_n:
            dirty_desc += f"（其中未跟踪 {untracked_n} 项）"
        return last_msg or "（无提交）", files_desc, dirty_desc
    # 不在 git 仓库内：用项目内最近修改文件（mtime 事实）
    rels = recent_project_files(project_dir)
    names = ", ".join(rels)
    files_desc = f"{names} 等 {len(rels)} 个文件" if len(rels) > 3 else (names or "（无）")
    return "（项目未纳入独立 git / untracked）", files_desc, "项目未 commit（任务纪律）"


# 卡文件名的两种既有约定（与 tools/task-start-hook.py 同源判据）：
#   `TASK-<8位日期>-<3位序号>.md` 与 `T<3位序号>-<slug>.md`。
# **不用** `TASK-*.md` 通配 —— 那会把 `<卡>-OPERATIONS.md`（兜底日志）与 `-event-log-archive.md`
# 也当成卡（`样例账本.md` Entry #44 已记录同型坑）。
CARD_NAME_RE = re.compile(r"^(?:TASK-\d{8}-\d{3}|T\d{3}-[^/]+)\.md$")


def find_cards_by_id(task_id):
    """显式 TASK-ID → 卡路径**列表**（0 / 1 / 多张）。

    多张 = 重复 ID（全库既有缺陷：`TASK-20261003-001` 在 `AI-OS-Adaptation/` 与
    `demo-project/` 各一张）⇒ 调用方必须**拒绝写回**：此时连"显式给 ID"都有歧义（§12.4.1 ③）。
    """
    hits = []
    flat = os.path.join(ACTIVE_DIR, f"{task_id}.md")
    if os.path.isfile(flat):
        hits.append(os.path.abspath(flat))
    if os.path.isdir(ACTIVE_DIR):
        for root, _dirs, files in os.walk(ACTIVE_DIR):
            if f"{task_id}.md" in files:
                p = os.path.abspath(os.path.join(root, f"{task_id}.md"))
                if p not in hits:
                    hits.append(p)
    return hits


def cards_in_dir(directory):
    """目录（递归）内的**卡**文件（判据 = CARD_NAME_RE）。"""
    out = []
    for root, _dirs, files in os.walk(directory):
        for name in files:
            if CARD_NAME_RE.match(name):
                out.append(os.path.abspath(os.path.join(root, name)))
    return sorted(out)


def changed_paths():
    """ git 事实：**优先工作区未提交改动**；未提交为空时才回退"最近一次提交的改动文件"。

    为什么优先未提交：Stop hook 在 turn 结束时跑，此时工作**通常还没提交**
    ⇒ 未提交面才代表""；最近一次提交属于上一轮（混进来会产生陈旧候选）。
    ⚠️ **只读 git 事实，不读 mtime** —— R2 选卡修复的硬约束：「禁止仅凭 mtime 猜卡」（§12.4.1 ①）。
    """
    out = set()
    root = nearest_git_root(ROOT)
    if not root:
        return out
    status, _ = git(["-c", "core.quotepath=false", "status", "--porcelain"], root)
    for line in status.splitlines():
        line = line.rstrip()
        if not line:
            continue
        # porcelain v1 = `XY PATH`。⚠️ `git()` 返回的是 `.strip()` 过的整体输出 ⇒
        # **第一行会丢掉行首空格**（读数：` M task_cards/…` 被 strip 成 `M task_cards/…`）
        # ⇒ 不能盲目用 `line[3:]`（那会吃掉路径首字符 't' → `ask_cards/…`，候选被静默丢弃）。
        # 用"前 1–2 个状态字符 + 空白"的**非贪婪**匹配：对 strip 免疫。
        path = re.sub(r"^.{1,2}?\s", "", line, count=1).strip()
        if not path:
            continue
        if " -> " in path:                      # rename：取新路径
            path = path.split(" -> ")[-1].strip()
        path = path.strip('"')
        if path:
            out.add(path.replace("\\", "/"))
    if out:
        return out
    files, _ = git(["-c", "core.quotepath=false", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"], root)
    for line in files.splitlines():
        if line.strip():
            out.add(line.strip().replace("\\", "/"))
    return out


# 机制写回行的固定标记（与 main() 的 entry_line 措辞同源）。
# 用途：**排除"机制自己写的收尾行"作为选卡证据** —— 否则 Stop hook 每写一张卡，
# 下一次运行的候选里就多一张 ⇒ **歧义自增强**（读数：上个会话 hook 写的未提交卡改动会一直挂在候选里）。
MECH_WRITEBACK_MARK = "收尾写回（wrapup_sync"


def diff_is_only_mechanism(rel_path):
    """该文件的改动是否**只**由机制写回行组成（是 ⇒ 不作为选卡证据，返回 True）。

    ⚠️ 判据读的是**改动内容**（`git diff HEAD -- <path>` 的新增行是否全部含机制标记），
    不是文件名、也不是 mtime。文件里还有**任何**其他新增行 ⇒ False（那是真实编辑，保留为候选）。
    """
    diff, rc = git(["-c", "core.quotepath=false", "diff", "--unified=0", "HEAD", "--", rel_path], ROOT)
    if rc != 0 or not diff:
        return False
    added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    if not added:
        return False
    return all(MECH_WRITEBACK_MARK in l for l in added)


def candidates_from_git():
    """从 git 事实推导候选卡 —— 返回 (候选绝对路径 set, 人类可读的推导说明)。

    判据（**全部可机械判定 · 无 mtime**）：
      ① **强信号**：改动文件**本身就是卡** ⇒ 直接进候选（唯一即定案）；
         但**只含机制收尾行**的卡改动不算（见 `diff_is_only_mechanism`，防歧义自增强）
      ② 回退：改动落在 `task_cards/active/<项目>/` 或 `workspaces/<项目>/` ⇒ 该项目文件夹内的卡
    """
    paths = changed_paths()
    if not paths:
        return set(), "无 git 改动事实（既无提交改动也无未提交改动）"

    direct = set()
    for p in paths:
        if CARD_NAME_RE.match(os.path.basename(p)):
            full = os.path.abspath(os.path.join(ROOT, p.replace("/", os.sep)))
            if os.path.isfile(full):
                if diff_is_only_mechanism(p):
                    continue                # 只含机制收尾行 ⇒ 不是"本次会话在工作的卡"
                direct.add(full)
    if len(direct) == 1:
        only = next(iter(direct))
        return direct, "改动文件直接指向唯一卡：%s" % os.path.relpath(only, ROOT).replace("\\", "/")
    if len(direct) > 1:
        return direct, "改动文件指向 %d 张卡" % len(direct)

    projects = set()
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 3 and parts[0] == "task_cards" and parts[1] == "active":
            projects.add(os.path.join(ACTIVE_DIR, parts[2]))
        elif len(parts) >= 2 and parts[0] == "workspaces":
            cand = os.path.join(ACTIVE_DIR, parts[1])
            if os.path.isdir(cand):
                projects.add(cand)
    if not projects:
        return set(), "改动未落在任何项目文件夹（无项目信号）"

    cards = set()
    for d in projects:
        if os.path.isdir(d):
            cards.update(cards_in_dir(d))
    return cards, "改动落在 %d 个项目文件夹（%s）⇒ 其内卡 %d 张" % (
        len(projects), ", ".join(sorted(os.path.basename(d) for d in projects)), len(cards))


# ── 🔴 修法辅助（"现在可同时出现多张焦点卡"）──────────
#   `.aios/focus-card.json` 是单文件单例（已记：多会话会覆盖）⇒ 不能作为写回判据；
#   这里直接读卡 `.log` 的**最后一条 claim/release**，判"本会话现在是否仍占着它"。
_SESSION_OP_RE = re.compile(r"\|\s*(claim 占用|release 释放)（session:\s*([^）]*)）")
_LOG_ROW_TIME_RE = re.compile(r"^\|\s*(\d{1,2}):(\d{2})\s*\|")


def _my_session_id():
    """本会话 id（Stop hook 环境有 `DSH_SESSION_ID`；hook 侧另透传 `AIOS_SESSION_ID`）；取不到 ⇒ 空串（⛔ 不猜）。"""
    for k in ("DSH_SESSION_ID", "CLAUDE_SESSION_ID", "AIOS_SESSION_ID"):
        v = os.environ.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _last_log_owner(card_path):
    """→ `(op, session, minute_of_day, row_index)` | None。读 `.log` 数据行，倒序取首条 claim/release。"""
    rows = read_card_log_rows(card_path)
    for i in range(len(rows) - 1, -1, -1):
        ln = rows[i]
        m = _SESSION_OP_RE.search(ln)
        if not m:
            continue
        tm = _LOG_ROW_TIME_RE.match(ln)
        minute = (int(tm.group(1)) * 60 + int(tm.group(2))) if tm else -1
        return ("claim" if m.group(1).startswith("claim") else "release", m.group(2).strip(), minute, i)
    return None


def session_owned_cards():
    """本会话**当前仍占用**的卡 → `[(path, minute, row_index)]`，按"最近 claim"排序。

    判据：`.log` 最后一条 claim/release 是 **claim** 且 session == 本会话
    （最后一条是 release ⇒ 已释放，⛔ 不是我的卡；被别人 claim ⇒ 已被 takeover）。
    排序：与当前时刻的分钟差（跨午夜取模）最小者优先；同差取 `.log` 中更晚出现者。
    """
    me = _my_session_id()
    if not me:
        return []
    now = time.localtime()
    now_min = now.tm_hour * 60 + now.tm_min
    out = []
    for p in cards_in_dir(ACTIVE_DIR):
        owner = _last_log_owner(p)
        if owner is None:
            continue
        op, sess, minute, idx = owner
        if op != "claim" or sess != me:
            continue
        out.append((p, minute, idx))
    out.sort(key=lambda x: (((now_min - x[1]) % (24 * 60)) if x[1] >= 0 else 10 ** 6, -x[2]))
    return out


def resolve_target_card(task_id=None, project=None):
    """解析写回目标卡 —— 返回 (卡路径 or None, 说明)。

    🔴 **目标卡不猜**（§12.4.1 ①）：无法唯一确定 ⇒ 返回 None，由调用方**跳过写回**并留诊断（不静默）。
    **禁止仅凭 mtime** —— 原实现取全库最新 mtime ⇒ "编辑一张卡，Stop 的落点就跟着跳卡"（读数 11:09 → 11:48）。

    优先级：① 显式 TASK-ID ② 显式项目目录 ③ **本会话自己的卡**（修法）④ git 事实推导
    """
    if task_id:
        hits = find_cards_by_id(task_id)
        if len(hits) == 1:
            return hits[0], "显式 TASK-ID 唯一命中"
        if not hits:
            return None, "显式 TASK-ID `%s` 在 active 下未找到" % task_id
        return None, "显式 TASK-ID `%s` 命中 %d 张卡（重复 ID ⇒ 歧义，拒绝写回）：%s" % (
            task_id, len(hits), ", ".join(os.path.relpath(h, ROOT).replace("\\", "/") for h in hits))

    if project:
        d = project if os.path.isabs(project) else os.path.join(ROOT, project)
        if not os.path.isdir(d):
            return None, "显式项目目录不存在：%s" % project
        cards = cards_in_dir(d)
        if len(cards) == 1:
            return cards[0], "显式项目目录内唯一卡"
        return None, "显式项目目录 `%s` 内有 %d 张卡（不唯一）" % (project, len(cards))

    # 🔴 修法（"现在可同时出现多张焦点卡"）：
    #    原修法假设"焦点卡唯一"；但占用自 起**按卡互斥、不按全局** ⇒ 同一会话可
    #    同时占多张卡（不同项目并行），`.aios/focus-card.json` 又是单文件单例⇒ 不可靠。
    #    ⇒ 判据 = 「**本会话自己的卡**」：卡 `.log` **最后一条** claim/release 是 claim 且
    #      session == 本会话；多张 ⇒ 按**最近一次 claim 的时分**（跨午夜取时间差最小）选并标注；
    #      ⛔ 无自己的卡 ⇒ 回退 git 推导（兼容"没有占用时也写回"的旧场景）。
    mine = session_owned_cards()
    if len(mine) == 1:
        return mine[0][0], "本会话唯一占用卡（%s）" % os.path.relpath(mine[0][0], ROOT).replace("\\", "/")
    if len(mine) > 1:
        pick = mine[0][0]
        return pick, "本会话占用 %d 张卡 ⇒ 按最近 claim 选 `%s`（多卡并行 · 要写回指定卡请显式给 TASK-ID）" % (
            len(mine), os.path.relpath(pick, ROOT).replace("\\", "/"))

    cards, why = candidates_from_git()
    if len(cards) == 1:
        return next(iter(cards)), why
    if not cards:
        return None, "无法唯一确定：%s" % why
    return None, "无法唯一确定：%s ⇒ 候选 %d 张（%s）" % (
        why, len(cards), ", ".join(os.path.relpath(c, ROOT).replace("\\", "/") for c in sorted(cards)))


def find_target_card(task_id):
    """兼容壳（起语义已变）：显式 ID → 卡路径；**无 ID ⇒ 返回 None（不再猜卡）**。

    保留旧名只为不打断 `scratch/` 里的只读诊断脚本；**新代码请用 `resolve_target_card`**。
    """
    if task_id:
        hits = find_cards_by_id(task_id)
        return hits[0] if len(hits) == 1 else None
    return None


# --------------------------------------------------------------------------
# R3 · 账本写回（§10 已裁 (b) · §12.4）—— 机制只写"发生了什么"
# --------------------------------------------------------------------------

def ledger_path():
    return os.path.join(ROOT, "样例账本.md")


def ledger_next_entry_no(text):
    """下一个 Entry 号 = 现有 `## Entry #N` 最大值 + 1（不新增编号状态源）。"""
    nums = [int(n) for n in re.findall(r"^##\s+Entry\s+#(\d+)\s*$", text, re.M)]
    return (max(nums) + 1) if nums else 1


def ledger_already_written(card_path, commit_hash):
    """账本幂等判据 = **(卡, commit)**（§12.4.1 ②）。

    不能只用 commit 去重 —— 一次 commit 可能对应多张卡，那样会吞掉另一张卡的记录。
    判据读的是**已有文件**（账本文本），不新增状态源（§12.0 ④）。
    """
    if not commit_hash:
        return False
    try:
        text = read_text_retry(ledger_path())
    except OSError:
        return False
    task_id = os.path.basename(card_path).removesuffix(".md")
    for chunk in text.split("\n## Entry ")[1:]:
        if commit_hash in chunk and task_id in chunk:
            return True
    return False


def ledger_entry_text(no, card_path, project_dir, last_msg, files_desc, dirty_desc):
    """一条账本 Entry 的文本：**只含机械事实**。

    🔴 §12.4 边界：`Outcome` / `footprint` / `influence` 一律**留占位并标"待补"** ——
    判断归 Agent / ；机制写这些 = AI-OS 开始**自己给自己打分**（与 Sovereignty 冲突）。
    §12.4 要求的机械事实项：日期 · 卡/项目 · commit · 改动文件 · **机制调用是否出现** · 未提交面。
    ⚠️「机制调用是否出现」的数据源**方案未细化** ⇒ 首版口径 = 只写本机制**自己这一次**的出现
    （`Stop → wrapup_writeback`），并明说注入型（R1/R4）的调用情况**不由账本承担**（属 L1/L2 验收，需读轨迹）。
    """
    today = datetime.date.today().isoformat()
    task_id = os.path.basename(card_path).removesuffix(".md")
    proj = os.path.basename(project_dir) if project_dir else "?"
    return (
        f"\n## Entry #{no}\n\n"
        f"- {today} · 项目 `{proj}` · 卡 `{task_id}` · **机制写回**（`tools/wrapup_sync.py` · R3）\n"
        f"- 事实（机械提取）：提交 `{last_msg}`；改动 {files_desc}；{dirty_desc}\n"
        f"- 机制调用：本 Entry 由 **`Stop` → `wrapup_writeback`** 写入（R0 dispatcher · `§12.1`）；"
        f"注入型（R1 / R4）是否被调用**本机制不自采**（属 L1/L2 验收，需读轨迹 —— 不由账本承担）\n"
        f"- Outcome: **待补** —— 机制不写判断（归 Agent / Human）\n"
        f"- footprint: **待补** —— 机制不写判断（归 Agent / Human）\n"
        f"- influence: **待补** —— 机制不写判断（归 Agent / Human）\n"
        f"- ⚠️ 本 Entry 由机制自动写入，**只含可机械提取的事实**；上面三项占位**不是结论**。\n"
    )


def append_ledger(card_path, project_dir, last_msg, files_desc, dirty_desc):
    """追加一条机械事实 Entry；同 **(卡, commit)** 已存在则跳过。返回 (status, 说明)。"""
    path = ledger_path()
    if not os.path.isfile(path):
        return "missing", "账本不存在（%s）" % os.path.relpath(path, ROOT).replace("\\", "/")
    commit_hash = (last_msg or "").split()[0] if last_msg else ""
    if ledger_already_written(card_path, commit_hash):
        return "skip", "同 (卡, commit) 已有 Entry ⇒ 幂等跳过"
    text = read_text_retry(path)
    no = ledger_next_entry_no(text)
    append_with_retry(path, ledger_entry_text(no, card_path, project_dir, last_msg, files_desc, dirty_desc))
    return "written", "Entry #%d" % no


def event_log_bounds(lines):
    """返回卡内 `## Event Log` 小节的 (首行下标, 结束下标)，未找到则 None。

    统一供 `already_written` / `append_event_log` / `count_event_rows` / `migrate_event_log` 使用，
    避免各处各自扫一遍导致行为分叉（缺陷 ② 的教训：**判据范围必须精确**）。
    """
    start = end = None
    for i, line in enumerate(lines):
        if start is None:
            if line.strip().startswith("## Event Log"):
                start = i
            continue
        if line.strip().startswith("## "):
            end = i
            break
    if start is None:
        return None
    return (start, end if end is not None else len(lines))


def is_table_row(line):
    """表格**数据**行（排除表头 `| Time | …` 与分隔行 `|---|`）。

    隔离自测抓到的第三个 bug：原判据 `not set(s) <= set("|-: ")` **漏掉了表头**
    （表头字母不在 `|-: ` 里）⇒ 表头被算成数据行 ⇒ 计数多 1、且表头被当作数据参与幂等匹配。
    判据改为：排除以 `|---` 开头的行，并排除列名恰为表头的行。
    """
    s = line.strip()
    if not s.startswith("|"):
        return False
    if s.startswith("|---") or s.startswith("| ---"):
        return False
    head = [c.strip() for c in s.strip("|").split("|")]
    if head[:2] == ["Time", "State"]:
        return False
    return True


def iter_card_rows(lines):
    """卡内 Event Log 的数据行下标列表（按出现顺序）。"""
    b = event_log_bounds(lines)
    if not b:
        return []
    start, end = b
    return [i for i in range(start + 1, end) if is_table_row(lines[i])]


def oplog_path(card_path):
    """兜底日志路径 = 卡同目录、同 TASK-ID、后缀 -OPERATIONS.md。

    约定「卡的 20 条满了 ⇒ 即将被归档的移入兜底日志」。
    与卡**同目录同名**：卡归档时两文件一起走；枚举目录时一眼能配对。
    """
    stem = os.path.basename(card_path)[:-3] if card_path.lower().endswith(".md") else os.path.basename(card_path)
    return os.path.join(os.path.dirname(os.path.abspath(card_path)), f"{stem}-OPERATIONS.md")


OPLOG_HEADER = [
    "> **本文件的角色**：本卡 Event Log 的**兜底日志**（不满 20 条时不会出现）。",
    "> 卡内 Event Log 达上限后，**最早的条目逐字迁入这里**（append-only，不删除、不改写）。",
    "> 迁入判据与格式 = 与卡内 Event Log 完全一致；机制输出（收尾写回）优先落卡，满了才落这里。",
]

MIGRATION_MARK = "<!-- 历史归档（wrapup_sync 自动迁入） -->"


def ensure_oplog(log_path, task_id, create=True):
    """确保兜底日志存在（含表头）；`create=False` 时**只探测不创建**（dry-run 用）。"""
    if os.path.isfile(log_path):
        return True
    if not create:
        return False
    write_with_retry(
        log_path,
        f"# OPERATIONS — {task_id} 兜底日志\n\n"
        + "\n".join(OPLOG_HEADER) + "\n\n"
        + "| Time | State | Reason | Changed By |\n"
        + "|------|-------|--------|:----------:|\n",
    )
    return True

def append_oplog_rows(log_path, rows, mark_first=False):
    """把若干行逐字追加到兜底日志（必要时写入迁移小标题）。"""
    body = ("\n" + MIGRATION_MARK + "\n" if mark_first else "") + "".join(row + "\n" for row in rows)
    append_with_retry(log_path, body)


# ── 🔴 **Event Log 外置**（与 `tools/task_card.py` 同步 · 约定）──────────
#   卡 = 快照（Goal/Status/Next）· 日志 = 流水（同级同名 `.log`）。收尾写回**也写 .log**，
#   ⛔ 不再往卡内追加（否则卡又变长 ⇒ 该问题复发）。
LOG_HEADER = "| Time | State | Reason | Changed By |\n|------|-------|--------|:----------:|\n"


def card_log_path(card_path):
    """卡 ⇒ **同级同名**日志路径（`X.md` → `X.log`）。"""
    return card_path[:-3] + ".log" if card_path.lower().endswith(".md") else card_path + ".log"


def read_card_log_rows(card_path):
    """读外置日志的**数据行**（去表头/分隔线）；不存在 ⇒ `[]`。"""
    p = card_log_path(card_path)
    if not os.path.isfile(p):
        return []
    try:
        return [ln.rstrip() for ln in read_text_retry(p).splitlines()
                if ln.strip().startswith("|") and not ln.strip().startswith("|------")
                and "Changed By" not in ln]
    except OSError:
        return []


def write_card_log_rows(card_path, rows):
    """原子写外置日志（表头 + 数据行）。"""
    write_with_retry(card_log_path(card_path), LOG_HEADER + "\n".join(rows) + "\n")


def migrate_event_log(card_path):
    """把**外置日志**里最早（即将被归档）的若干条迁入兜底日志（`-OPERATIONS.md`）。

    触发：数据行数 > `EVENT_LOG_MAX_ROWS`。迁移后保留最近 `EVENT_LOG_KEEP_ROWS` 条。
    对象从"卡内 Event Log"改为"**外置 `.log`**"（卡已不再承载日志）。
    返回迁出条数（0 = 未触发）。
    """
    rows = read_card_log_rows(card_path)
    if len(rows) <= EVENT_LOG_MAX_ROWS:
        return 0
    drop_n = len(rows) - EVENT_LOG_KEEP_ROWS
    moved, keep = rows[:drop_n], rows[drop_n:]
    task_id = os.path.basename(card_path).removesuffix(".md")
    log_path = oplog_path(card_path)
    ensure_oplog(log_path, task_id)
    append_oplog_rows(log_path, moved, mark_first=True)
    write_card_log_rows(card_path, keep)
    print(f"[wrapup] 外置日志达上限（>{EVENT_LOG_MAX_ROWS} 条）⇒ 最早 {drop_n} 条迁入 "
          f"{os.path.basename(log_path)}（日志保留最近 {EVENT_LOG_KEEP_ROWS} 条）")
    return drop_n


def already_written(card_path, marker):
    """幂等判据（Step 2；两处修正：缺陷 ② + 兜底日志）。

    ⚠️ **不新增状态文件** —— 判据读的是**已有文件**（卡的 Event Log / 兜底日志文本）。
    依据：AUTOMATION-BOUNDARY §6.3「状态在【已有文件】里，不新增状态文件」。

    缺陷 ②：原判据是 `marker in 卡全文`。卡的**正文/说明文字**里常会提到
    某个 commit hash（例如解释"这次挂载是 031da72"），于是脚本误判"该 commit 已写回"
    ⇒ **漏写**（读数：该 hash 在卡内只出现 1 次，且位置是说明文字，Event Log 里从没有过）。
    修法：只认 `## Event Log` 小节内的数据行（修正；count/migrate 共用同一判据）。

    兜底日志：迁出的条目落在同目录 `<TASK-ID>-OPERATIONS.md` ⇒ 判据也要覆盖它，
    否则"迁出后同一 commit 会被重复写回"（判据必须跟着写回目标走）。
    """
    if not marker:
        return False
    # **外置日志优先**（判据必须跟着写回目标走 —— 否则外置后重复写回）
    for line in read_card_log_rows(card_path):
        if marker in line:
            return True
    try:
        lines = read_text_retry(card_path).splitlines()
    except OSError:
        return False
    for i in iter_card_rows(lines):
        if marker in lines[i]:
            return True
    log_path = oplog_path(card_path)
    if os.path.isfile(log_path):
        try:
            return any(marker in line for line in read_text_retry(log_path).splitlines() if is_table_row(line))
        except OSError:
            return False
    return False


def append_event_log(card_path, entry_line):
    """把收尾留痕写进**外置日志**（同级同名 `.log`）。

    🔴 **外置**（与 `task_card.py` 同步）：⛔ 不再写卡内（否则卡又变长 ⇒ 该问题复发）。
    超出上限时把最旧的迁入兜底日志（`-OPERATIONS.md`，沿用既有语义）。
    """
    rows = read_card_log_rows(card_path)
    rows.append(entry_line)
    if len(rows) > EVENT_LOG_MAX_ROWS:
        drop_n = len(rows) - EVENT_LOG_KEEP_ROWS
        moved, rows = rows[:drop_n], rows[drop_n:]
        task_id = os.path.basename(card_path).removesuffix(".md")
        op = oplog_path(card_path)
        ensure_oplog(op, task_id)
        append_oplog_rows(op, moved, mark_first=True)
    write_card_log_rows(card_path, rows)
    return 1


def check_success_log(card_path):
    """（语义更新）：R3 已让机制自动落账 ⇒ 本检查改为「**判断项仍需人补**」的提示。

    边界（§12.4）：机制只写"发生了什么"；`Outcome` / `footprint` / `influence` 归 Agent / 。
    """
    log_path = os.path.join(ROOT, "样例账本.md")
    if not os.path.isfile(log_path):
        print("[wrapup] 提示：样例账本.md 不存在——收尾时应创建并追加 Entry")
        return
    text = read_text_retry(log_path)
    task_id = os.path.basename(card_path).removesuffix(".md")
    if task_id not in text:
        print(f"[wrapup] 提示：本任务 {task_id} 尚未在 样例账本.md 追加 Entry。")
        print("        有消费语境但没消费 → 请显式追加 footprint = NONE 的 Entry（宁留缺口不事后造数据）。")
        print("        无消费语境 → 请追加 Entry 并标注 NOT_APPLICABLE。")
    else:
        print(f"[wrapup] SUCCESS_LOG 已有 {task_id} 的 Entry（R3 机制写的只含机械事实）——"
              "Outcome / footprint / influence 属**判断项**，需 Agent / Human 补，机制不写。")


def check_learning_closure(card_path):
    """Learning Closure（// 最小 reshape）：把'是否值得沉淀'放进收尾决策空间。

    只增加判断入口，不强制生成 Knowledge：
      - 无 → 显式确认"无值得沉淀"（有效输出，不是失败）
      - 有 → 走 结构化判定 → 审查 → 才进入 domains
    """
    print("[wrapup] 沉淀检查（Learning Closure）：本任务是否有值得沉淀的经验/规则/教训？")
    print("        无 → 在 SUCCESS_LOG 显式确认'无值得沉淀'即可（'无'也是有效输出）。")
    print("        有 → 走 A05 结构化判定（原因/条件/行为/结果/可复用性）→ A04 审查 → 才进入 domains。")


def main(argv=None):
    """收尾写回入口。`argv=None` ⇒ 用 `sys.argv[1:]`（CLI）；dispatcher 传 `[]`（hook 路径）。

    返回 0 = 无失败（**含"跳过"** —— 跳过不是失败）；1 = 至少一个写回目标失败
    （DSH 会把 stderr 摘要记进 `hook/result`，所以失败必须显式可见）。
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    # 位置参数（TASK-ID）与 --project 的值要分开：`--project` 后面跟的是**路径**，不是 ID
    project = None
    positional = []
    skip_next = False
    for i, a in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if a == "--project":
            skip_next = True
            if i + 1 < len(argv):
                project = argv[i + 1]
            continue
        if a.startswith("--project="):
            project = a.split("=", 1)[1]
            continue
        if a.startswith("--"):
            continue
        positional.append(a)
    task_id = positional[0] if positional else None
    dry = "--dry-run" in argv
    force = "--force" in argv

    # 🔴 选卡：**不猜**（§12.4.1 ①）。无法唯一确定 ⇒ 跳过写回，但**留诊断**（不静默）。
    card_path, why = resolve_target_card(task_id, project)
    if not card_path:
        print(f"[wrapup] ⏭ 未写回（无法唯一确定目标卡）：{why}")
        print("[wrapup]    可显式消歧：python tools/wrapup_sync.py <TASK-ID>"
              "  或  --project task_cards/active/<项目>")
        return 0
    rel_card = os.path.relpath(card_path, ROOT).replace("\\", "/")
    print(f"[wrapup] 目标卡：{rel_card} —— {why}")

    # git 事实：优先取任务卡定位的项目目录（有独立 git 用其提交；untracked/无 git 用项目内最近修改文件）
    project_dir = find_project_dir(card_path) or ROOT
    last_msg, files_desc, dirty_desc = git_facts(project_dir)

    now = datetime.datetime.now().strftime("%H:%M")
    today = datetime.date.today().isoformat()
    entry_line = (
        f"| {now} | Executing | 收尾写回（wrapup_sync {today}，项目 {os.path.basename(project_dir)}）："
        f"提交 `{last_msg}`；改动 {files_desc}；{dirty_desc} | Worker |"
    )

    # 幂等自检（Step 2）：判据 = 该 commit hash 是否已在卡内 Event Log /
    # 兜底日志里。动机：挂在 Stop hook 上时**每 turn 结束都会触发**（单会话可达 20+ 次）⇒ 必须幂等。
    # ⚠️ 不新增状态文件；依据是【已有文件】（git 事实 + 卡 / 兜底日志文本）。
    commit_hash = (last_msg or "").split()[0] if last_msg else ""
    skip_idem = bool(commit_hash) and len(commit_hash) >= 7 and not force and already_written(card_path, commit_hash)

    # 容量判定卡内满了 ⇒ 先迁移"最早 / 即将被归档的"，再落到卡内。
    # 迁移后卡内仍有空间 ⇒ 新行照常进卡（保持卡内可见性；只有历史被外移）。
    # ⚠️ 读取也要重试：端到端读数中，占用首先打死的是这里的 f.read()（缺陷 ⑤）。
    rows_now = len(iter_card_rows(read_text_retry(card_path).splitlines()))
    overflow = rows_now > EVENT_LOG_MAX_ROWS

    # 决策留痕（诊断）：hook 自己算出的判据要能事后回放 —— 否则只有
    # exitCode=0 而没有卡片改动时，无法区分"幂等跳过 / 读到别的 commit / 迁移异常"。
    # 增记 `why`（选卡判据）：选卡不再靠 mtime ⇒ 必须能回放"为什么是这张卡"。
    if _DECIDE_LOG:
        try:
            with open(os.path.join(ROOT, "scratch", "_wrapup-decisions.log"), "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "at": datetime.datetime.now().isoformat(timespec="seconds"),
                    "card": os.path.basename(card_path),
                    "why": why,
                    "commit": commit_hash,
                    "last_msg": last_msg,
                    "dirty": dirty_desc,
                    "rows_before": rows_now,
                    "overflow": overflow,
                    "skip_idem": skip_idem,
                }, ensure_ascii=False) + "\n")
        except OSError:
            pass

    log_path = oplog_path(card_path)
    target = (
        f"{os.path.basename(log_path)}（兜底日志 · 卡内已满且未触发迁移）"
        if (overflow and dry)
        else "Event Log"
    )

    if dry:
        print(f"[wrapup] DRY-RUN——将追加到 {os.path.basename(card_path)} {target}：")
        if overflow:
            print(f"[wrapup] DRY-RUN 已满：卡内 {rows_now} 条 > 上限 {EVENT_LOG_MAX_ROWS} ⇒ "
                  f"正式运行会先把最早 {rows_now - EVENT_LOG_KEEP_ROWS} 条迁入 {os.path.basename(log_path)}，再追加本行")
        print(entry_line)
        print(f"[wrapup] DRY-RUN——将追加账本 Entry（R3 · 只写机械事实）：")
        print(ledger_entry_text(ledger_next_entry_no(read_text_retry(ledger_path())) if os.path.isfile(ledger_path()) else 1,
                                card_path, project_dir, last_msg, files_desc, dirty_desc).rstrip()
              if os.path.isfile(ledger_path()) else "（账本文件不存在）")
        if skip_idem:
            print(f"[wrapup] DRY-RUN 幂等命中：提交 {commit_hash} 已在卡内/兜底日志中 ⇒ 正式运行将**跳过**（--force 可强制）")
        print("[wrapup] 收尾检查（E6）：若本次没有值得沉淀的经验，请确认“无相关经验值得记录”——"
              "空结果本身是信号，不硬写，但要过一遍。")
        return 0

    if skip_idem:
        print(f"[wrapup] 幂等跳过：提交 {commit_hash} 已写回 {os.path.basename(card_path)}（--force 可强制）")
        return 0

    # --- 目标 ① 任务卡 Event Log（R2 · 已闭环） ---
    card_err = None
    try:
        migrate_event_log(card_path)
        append_event_log(card_path, entry_line)
        print(f"[wrapup] ✅ 卡写回 {rel_card} Event Log（+1 行）")
    except OSError as e:
        # 失败必须**显式可见**（返回 1 ⇒ DSH 在会话里记 hook/result 的 stderrSummary），
        # 且不能吞掉收尾检查 —— 缺 ① 的教训就是"崩溃被 `|| exit 0` 掩盖成干净"。
        card_err = e
        print(f"[wrapup] ❌ 卡写回失败（{type(e).__name__}: {e}）—— 本行未写入 {rel_card}")

    # --- 目标 ② 账本（R3 · §10 已裁 (b) · 第 ⑤ 步落地）---
    # 与卡写回**各自独立 try**（§12.4 兜底）：一个失败不影响另一个。
    ledger_err = None
    try:
        status, note = append_ledger(card_path, project_dir, last_msg, files_desc, dirty_desc)
        if status == "written":
            print(f"[wrapup] ✅ 账本写回 样例账本.md（{note} · 只写机械事实；"
                  "Outcome / footprint 留占位标「待补」）")
        elif status == "skip":
            print(f"[wrapup] ⏭ 账本跳过：{note}")
        else:
            print(f"[wrapup] ⚠️ 账本未写：{note}")
    except OSError as e:
        ledger_err = e
        print(f"[wrapup] ❌ 账本写回失败（{type(e).__name__}: {e}）")

    print("[wrapup] 收尾检查（E6）：若本次没有值得沉淀的经验，请确认“无相关经验值得记录”——"
          "空结果本身是信号，不硬写，但要过一遍。")
    check_success_log(card_path)
    check_learning_closure(card_path)
    return 1 if (card_err or ledger_err) else 0


if __name__ == "__main__":
    sys.exit(main())
