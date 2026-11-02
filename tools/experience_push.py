# -*- coding: utf-8 -*-
"""
experience_push.py — AI-OS minimal experience push (load-bearing candidate v0.2)

WHAT IT IS
  A read-only retrieval CLI: given the Agent's current task (typed, OR derived
  automatically from live git state via --auto), it surfaces the most relevant
  past experience NEXT TO the Agent, which then decides whether to use it.
  Sources, in trust order:
    1. the PROVEN ledger (样例账本.md) - highest trust: append-only
       record of REAL observed outcomes (success AND honest failure), each
       reality-tested against an actual Agent session. By AI-OS L1
       ("verifiable assistance"), reality-tested > curated declarations.
    2. the pain ledger (curated memory) - every entry exists because a cost
       recurred; a solved problem must never be paid twice
    3. declarative patterns / experiences / task cards

--auto is the "keep doing it" mode: the query is derived from recent repo
state (last 3 commit subjects + changed files + CURRENT_GOAL intent), so
experience arrives without being hand-typed. CAVEAT: the query is seeded by
the Agent's OWN recent commits + goal, so --auto ECHOES recent focus rather
than independently reconstructing state - a rear-view mirror, not an impartial
recovery. (It does not avoid carrier self-certification; it only indirects it.)

WHAT IT IS NOT (discipline locks)
  - NOT a Runtime daemon: no background process, no watching, no state.
  - NOT a knowledge injector: it prints candidates; it never modifies context,
    files, or Agent behavior.
  - NOT a new state owner: writes nothing. Zero mutation. (v1F-safe)

USAGE
  python tools/experience_push.py "描述当前任务, 如: git bash 杀不掉 node 进程 端口占用"
  python tools/experience_push.py -n 3 "orphan branch 隔离历史"
  python tools/experience_push.py --auto            # query derived from git state
  python tools/experience_push.py --auto "额外线索"  # git state + extra hint

VALIDATION (why this exists)
  This is the Q1-Q5 Existence Validation candidate. Each real use should end
  with an honest Review answer: did it actually help? (see AGENTS.md rule 5)
"""
import argparse
import collections
import io
import json
import math
import os
import re
import subprocess
import sys

from _root_guard import guard
guard(__file__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCES = [
    ("pattern", os.path.join(ROOT, "domains"), ("patterns",)),
    ("experience", os.path.join(ROOT, "domains"), ("experiences",)),
    ("experience", os.path.join(ROOT, "domains", "experiences"), None),
    ("pattern", os.path.join(ROOT, "domains", "patterns"), None),
    ("task_card", os.path.join(ROOT, "task_cards"), None),
]

# frontmatter field weights
FIELD_WEIGHTS = {
    "trigger": 3.0,
    "keywords": 3.0,
    "alias": 3.0,
    "title": 2.0,
    "rule_id": 2.0,
    "condition": 2.0,
}
BODY_WEIGHT = 1.0
# The pain ledger (curated memory) is the highest-trust source: every entry
# exists BECAUSE a cost recurred. A solved problem must never be paid twice.
LEDGER_WEIGHT = 4.0
# The PROVEN ledger = 样例账本.md: append-only record of REAL observed
# outcomes (success AND honest failure). By AI-OS L1 ("verifiable assistance"),
# reality-tested > curated declarations, so it outranks the declarative ledger.
PROVEN_LEDGER_WEIGHT = 5.0
#: 坑清单（人工维护的 task_cards/memory/PITFALLS.md）：与 curated memory 同级信任。
# 验证：PITFALLS 在 task_cards/memory/ 下，而 collect_files() 只扫顶层 ⇒
# PITFALLS 从未进入召回语料（10 个真实坑场景：3 零命中、4 只命中账本/泛化 pattern）。
PITFALLS_PATH = os.path.join(ROOT, "task_cards", "memory", "PITFALLS.md")
# 首版 4.0 → **4.8**（首版值 · 待回归）： 的 `R1/R2/R3` 稀有 ID 命中被账本条目
# （10.5）压到第 4 位 ⇒ top3 漏召。4.8 仍低于 PROVEN 账本 5.0，不压过"真实观测"。
PITFALLS_WEIGHT = 4.8
CJK = re.compile(u"[\u4e00-\u9fff]")

# ─────────────────────────────────────────────────────────────────────────────
# 阶段 3 · 检索质量修复（批准 · 七条约束）
#   目标：碎片不能单独触发；无关候选被过滤；正反向固定样本见
#         `scratch/_retrieval_regression.py`（约束 6：阈值变化必须重跑全部样本）
#   ⚠️ 以下全部阈值为【首版值 · 待回归验证】—— 不得写成已验证。
#   ⚠️ 规则只在这里定义一次，`task_start.py` 一律调用本模块 —— 不许出现第二套匹配规则。
# ─────────────────────────────────────────────────────────────────────────────

# 单 token 形态：纯数字 / 列表编号 / 单字母编号 ⇒ 不作有效命中（约束 1）
RE_PURE_NUMBER = re.compile(r"^\d+$")
RE_NUM_ORDINAL = re.compile(r"^\d+[.)]$")
RE_ALPHA_ORDINAL = re.compile(r"^[a-z][.)]$")

# 长度 ≥3 的 ASCII 技术词（rls / permissionerror / auth.uid）——
# 单个即可构成查询信号（约束 2：不把门槛写死成"必须 ≥2 个 token"）
RE_STRONG_TERM = re.compile(r"^[a-z][a-z0-9_.\-]{2,}$")

# 读数噪声 bigram。来源：`HANDOFF-hook-mount.md` 条目 24–26 的实际注入故障
#   + 阶段 3 基线 A/B/C（`scratch/_retrieval_before.json`）
# ⚠️ **软降权、不删除**（约束 3）：全局中文停用词会连真实技术词一起打掉
#    —— 例：`不可变` 的 bigram 是 `不可`/`可变`，两者都含否定字。
# ⚠️ 噪声命中：×NOISE_FACTOR 参与评分，但**绝不**计入有效命中、**绝不**帮助候选过闸门。
NOISE_BIGRAMS = frozenset((
    "务的", "真实", "要真", "需要", "之前", "代码", "变更", "可能", "历史", "处理", "已发",
    "一句", "什么", "即可", "句话",
))
NOISE_FACTOR = 0.2          # 噪声命中在评分里的系数
MIN_EFFECTIVE_HITS = 3      # 独立【有效】命中数下限（首版值）
# 密度下限 = 有效命中数 / 有效查询词数。**阶段 3 首版值 0.25**（读数分离区间）：
#   正向 / 的**应命中**候选密度 0.33–0.38；负向 C（`--auto` 的 633 词大 query）
#   的**宽泛词面重叠**只有 0.12–0.17 ⇒ 0.25 把两侧分开。
#   机制含义：**query 越长，要求命中的绝对数越多** —— 长 query 不能靠常见词重叠蒙分。
MIN_HIT_DENSITY = 0.25
MIN_EFFECTIVE_QUERY = 1     # 有效查询词下限
EFFECTIVE_QUERY_FLOOR = 2   # 达到即视为信息量足够

# 🔴 （误召回修复 · 第一批）：**泛词停用表** —— 只过滤"任何失败都可能出现"的词，
#   不过滤技术词（`PermissionError` / `ENOTFOUND` / `credential` 等复合或具体词照常计分）。
#   依据： 真机 + N=10 质量读数（`AI-OS-Adaptation/EXPERIENCE-QUALITY-.md`）
#      DNS 失败只靠 `error`/`failed`/`fetch` 三个泛词就越过阈值，召回到无关的 （git push）。
#   ⚠️ 软降权思路的替代：这里是**不计入有效命中**（与 NOISE 同类），而不是删词。
GENERIC_STOPWORDS = frozenset((
    "error", "errors", "failed", "fail", "failure", "fatal", "fetch",
    "exception", "traceback", "warning", "message", "stdin", "stdout",
    "unknown", "none", "true", "false",
))


def tokenize(text):
    """ASCII words + CJK bigrams, lowercased.

    ⚠️ 阶段 3 起：本函数**保持返回全部 token**（含噪声）—— 向后兼容所有调用方；
       有效性分类交给 `split_hits()` / `is_meaningful()`，
       从而 `experience_push` 与 `task_start` 共用同一套规则（约束：不许两套）。
    """
    text = text.lower()
    tokens = set(re.findall(r"[a-z0-9_\-\.]{2,}", text))
    cjk_runs = re.findall(u"[\u4e00-\u9fff]{2,}", text)
    for run in cjk_runs:
        for i in range(len(run) - 1):
            tokens.add(run[i:i + 2])
    return tokens


def is_meaningful(token):
    """【有效命中】判据（约束 1 / 3）。

    纯数字与列表编号不作有效命中 ⇒ **Entry 编号（`#32` 里的 `32`）不能单独构成
    经验相关性的证据**。读数噪声 bigram 同样不计为有效命中。

    ⚠️ 有意保留字母数字混合的技术标识符（`x86` / `s2-2` / `auth.uid` / `PermissionError`）：
       这里只排除**纯**数字与**纯**编号形态，不按字母个数机械删除。
    """
    if not token:
        return False
    if RE_PURE_NUMBER.match(token) or RE_NUM_ORDINAL.match(token) or RE_ALPHA_ORDINAL.match(token):
        return False
    if token in GENERIC_STOPWORDS:
        return False
    return token not in NOISE_BIGRAMS


def split_hits(tokens):
    """→ (effective, noise)。全仓库唯一的命中分类入口。"""
    eff = {t for t in tokens if is_meaningful(t)}
    return eff, set(tokens) - eff


def effective_query_tokens(query_tokens):
    """去重后的有效查询词（约束 2：门槛按有效信息量算，不按原始 token 数）。"""
    return {t for t in query_tokens if is_meaningful(t)}


def query_has_signal(query_tokens):
    """查询信息量门槛（约束 2）。

    · ≥2 个有效查询词 ⇒ 有信号
    · 仅 1 个 ⇒ 只有当它是长度 ≥3 的 ASCII 技术词时才够（`rls` / `PermissionError`）
    · `继续` / `谢谢` 这类单个 CJK bigram ⇒ 不够 ⇒ 不做材料发现
    """
    eff = effective_query_tokens(query_tokens)
    if len(eff) >= EFFECTIVE_QUERY_FLOOR:
        return True
    if len(eff) == MIN_EFFECTIVE_QUERY:
        return bool(RE_STRONG_TERM.match(next(iter(eff))))
    return False


def passes_gate(query_tokens, res):
    """相关性闸门（约束 3 / 4）—— 三条同时满足才放行。

    ① 查询信息量足够（`query_has_signal`）
    ② 独立**有效**命中数 ≥ `MIN_EFFECTIVE_HITS`
    ③ 命中密度 ≥ `MIN_HIT_DENSITY`（挡住"超长 query 匹配一切"）
    ④ 至少一个有效命中来自**高权重字段**（frontmatter 字段 / 账本正文）

    ⚠️ **噪声命中永远不能帮助候选过闸门** —— 它们只在评分里 ×NOISE_FACTOR。
    """
    if not query_has_signal(query_tokens):
        return False
    if len(res.effective) < MIN_EFFECTIVE_HITS:
        return False
    qeff = len(effective_query_tokens(query_tokens))
    if qeff > 0 and (len(res.effective) / float(qeff)) < MIN_HIT_DENSITY:
        return False
    if not res.high_field_effective:
        return False
    return True


def parse_frontmatter(raw):
    """Very small YAML-ish frontmatter reader: returns {field: text}."""
    fm = {}
    if not raw.startswith("---"):
        return fm, raw
    end = raw.find("\n---", 3)
    if end < 0:
        return fm, raw
    block = raw[3:end]
    body = raw[end + 4:]
    current = None
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            current = m.group(1).strip().lower()
            fm[current] = m.group(2).strip()
        elif current and line.strip().startswith("-"):
            fm[current] = fm.get(current, "") + " " + line.strip().lstrip("- ").strip()
        elif current and line.startswith("  "):
            fm[current] = fm.get(current, "") + " " + line.strip()
    return fm, body


def collect_files():
    files = []
    for kind, base, subdirs in SOURCES:
        if not os.path.isdir(base):
            continue
        if subdirs is None:
            for name in sorted(os.listdir(base)):
                if name.endswith(".md"):
                    files.append((kind, os.path.join(base, name)))
        else:
            for domain in sorted(os.listdir(base)):
                for sub in subdirs:
                    d = os.path.join(base, domain, sub)
                    if os.path.isdir(d):
                        for name in sorted(os.listdir(d)):
                            if name.endswith(".md"):
                                files.append((kind, os.path.join(d, name)))
    return files


def ledger_files():
    """Return [(abs_path, weight)] for the experience ledger, trust-ordered.

    Trust tiers:
      5.0 PROVEN   - 样例账本.md (observed reality; each entry is a
                     real Agent-session outcome, tagged [MECHANISM]/[PRODUCT-Q1])
      4.0 DECLARED - curated memory (project .workbuddy/memory/MEMORY.md, inside
                     the current environment) - curated declarations
      4.0 EXTERNAL - any AIOS_EXTERNAL_MEMORY env paths (opt-in; NOT read by
                     default, so a fresh clone never depends on host user memory)
    Missing files are skipped. See 样例账本.md for provenance rules.

    Local-first, external-memory opt-in: the environment is self-sufficient by
    default; external memory is an explicitly configured provider.
    """
    declared = [
        os.path.join(ROOT, ".workbuddy", "memory", "MEMORY.md"),
    ]
    proven = [os.path.join(ROOT, "样例账本.md")]
    entries = [(p, PROVEN_LEDGER_WEIGHT) for p in proven]
    entries += [(p, LEDGER_WEIGHT) for p in declared]
    external = os.environ.get("AIOS_EXTERNAL_MEMORY")
    if external is not None:
        ext_paths = [p for p in external.split(os.pathsep) if p]
        if not ext_paths:
            ext_paths = [os.path.expanduser(os.path.join("~", ".workbuddy", "MEMORY.md"))]
        for p in ext_paths:
            ap = os.path.abspath(os.path.expanduser(p))
            print(f"[experience_push] external memory enabled: {ap}")
            entries.append((ap, LEDGER_WEIGHT))
    seen, out = set(), []
    for p, w in entries:
        ap = os.path.abspath(p)
        if ap not in seen and os.path.isfile(ap):
            seen.add(ap)
            out.append((ap, w))
    return out


def collect_ledger_chunks():
    """Split curated memory into per-bullet chunks, each tagged with its section
    header, so retrieval surfaces the specific lesson, not the whole file.
    Returns (path, weight, header, text)."""
    chunks = []
    for path, weight in ledger_files():
        try:
            with io.open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        header = ""
        buf = []
        for line in lines:
            stripped = line.strip()
            if line.startswith("#"):
                if buf:
                    chunks.append((path, weight, header, " ".join(buf)))
                    buf = []
                header = line.lstrip("# ").strip()
            elif re.match(r"^-\s", line):
                if buf:
                    chunks.append((path, weight, header, " ".join(buf)))
                buf = [stripped.lstrip("- ").strip()]
            elif stripped and buf:
                buf.append(stripped.lstrip("- ").strip())
        if buf:
            chunks.append((path, weight, header, " ".join(buf)))
    return chunks


def collect_pitfall_chunks():
    """把 PITFALLS.md 的表格行切成**逐条**经验（现象 / 触发 / 处置 / 来源）。

    为什么需要（验证）：PITFALLS 在 `task_cards/memory/` 下，而
    `collect_files()` 只扫 `task_cards` 顶层 ⇒ PITFALLS 从未进入召回语料；
    10 个真实坑场景读数：3 条零命中、4 条只命中账本或泛化 pattern。
    返回 (path, weight, header, text)，与 ledger chunk 同构。
    """
    chunks = []
    if not os.path.isfile(PITFALLS_PATH):
        return chunks
    try:
        with io.open(PITFALLS_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return chunks
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        # 单元格内的 `\|` 转义要先换占位，否则会被误切成两列
        cells = [c.strip().replace("\x00", "|")
                 for c in s.replace("\\|", "\x00").strip("|").split("|")]
        if len(cells) < 3:
            continue
        m = re.match(r"^\*{0,2}(P\d+)\*{0,2}", cells[0])
        if not m:
            continue
        body = [c for c in cells[1:] if c]
        if not body:
            continue
        chunks.append((PITFALLS_PATH, PITFALLS_WEIGHT, "PITFALLS " + m.group(1), " ".join(body[:4])))
    return chunks


# 注入摘要库长 pattern / 能力只给指针；这里每条 ≤1 句「照做就行」⇒ inject。
DIGEST_PATH = os.path.join(ROOT, "domains", "experiences", "inject_digests.md")
DIGEST_WEIGHT = 4.8
DIGEST_ROW = re.compile(r"^-\s+\*\*(.+?)\*\*：(.*)$")


def collect_digest_chunks():
    """把 `domains/experiences/inject_digests.md` 的每行切成**逐条**摘要（主题 / 处置）。
    返回 (path, weight, header="DIGEST 主题", text=处置 → 指针)，与 ledger chunk 同构。"""
    chunks = []
    if not os.path.isfile(DIGEST_PATH):
        return chunks
    try:
        with io.open(DIGEST_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return chunks
    for line in lines:
        m = DIGEST_ROW.match(line.strip())
        if not m:
            continue
        chunks.append((DIGEST_PATH, DIGEST_WEIGHT, "DIGEST " + m.group(1).strip(), m.group(2).strip()))
    return chunks


def disp_path(path):
    try:
        rp = os.path.relpath(path, ROOT)
    except ValueError:
        return path
    if rp.startswith(".."):
        home = os.path.expanduser("~")
        if path.startswith(home):
            return "~" + path[len(home):].replace("\\", "/")
        return path
    return rp


#: 打分结果（阶段 3 起）：调用方据此过闸门并显示**命中依据**。
#:   score / matched        总分 · 全部命中（有效 + 噪声）
#:   effective              有效命中（唯一可用于闸门与展示的证据）
#:   noise                  噪声命中（只降权参与评分）
#:   high_field_effective   是否至少一个有效命中来自高权重字段
#:   fm                     frontmatter（调用方取 title 等）
ScoreResult = collections.namedtuple(
    "ScoreResult", "score matched effective noise high_field_effective fm")


def score_file(query_tokens, raw):
    """frontmatter 字段权重 + 正文打分（**阶段 3 重写**）。

    改动（约束 4）：**饱和计分** `w * (1 + ln n)`，其中 n 是该字段内**有效且去重**的
    命中数；无有效命中 ⇒ 该字段不贡献分数。噪声命中单独 ×`NOISE_FACTOR`。
    ⚠️ 因此**新分数与旧分数（435 / 375 / 365）不可直接比较** ——
       验收看"候选是否正确、无关项是否消失、相关项排名是否保留"，不看绝对分。
    """
    fm, body = parse_frontmatter(raw)
    score = 0.0
    matched, effective, noise = set(), set(), set()
    high_field_effective = False

    for field, weight in FIELD_WEIGHTS.items():
        if field not in fm:
            continue
        eff, noi = split_hits(query_tokens & tokenize(fm[field]))
        if eff:
            score += weight * (1.0 + math.log(len(eff)))
            matched |= eff
            effective |= eff
            high_field_effective = True       # frontmatter 字段 = 高权重字段
        if noi:
            score += weight * NOISE_FACTOR * len(noi)
            matched |= noi
            noise |= noi

    eff, noi = split_hits(query_tokens & tokenize(body[:4000]))
    if eff:
        score += BODY_WEIGHT * (1.0 + math.log(len(eff)))
        matched |= eff
        effective |= eff
    if noi:
        score += BODY_WEIGHT * NOISE_FACTOR * len(noi)
        matched |= noi
        noise |= noi

    return ScoreResult(score, matched, effective, noise, high_field_effective, fm)


def score_ledger_chunk(query_tokens, header, text):
    """账本 chunk 打分 —— **共享实现**。

    ⚠️ 阶段 3 之前，`experience_push.main()` 与 `task_start.knowledge()` **各写了一份**
       等价逻辑，那正是"两套规则会逐渐不一致"的来源（约束：同一套规则必须共享）。
    ⚠️ 账本正文即本体 ⇒ 有效命中即视为"高信息量字段命中"。
    """
    eff, noi = split_hits(query_tokens & tokenize(header + " " + text))
    score = 0.0
    if eff:
        score += 1.0 + math.log(len(eff))
    if noi:
        score += NOISE_FACTOR * len(noi)
    return ScoreResult(score, set(eff) | set(noi), eff, noi, bool(eff), {})


def extract_action(raw):
    """Pull the action.do lines from frontmatter if present, else first heading."""
    m = re.search(r"action:\s*\n\s*do:\s*\n((?:\s*-\s.*\n)+)", raw)
    if m:
        lines = [l.strip().lstrip("- ").strip() for l in m.group(1).splitlines() if l.strip()]
        return " / ".join(lines[:3])
    m = re.search(r"^#+\s*(.+)$", raw, re.M)
    return m.group(1).strip() if m else ""


def preview_text(path, action, limit=260):
    """Return candidate content (action lines preferred, else body) so the
    experience lands IN the Agent's attention space — not just a filename it
    would have to open (: Consumption 缺口修复 #1)."""
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        return action or ""
    m = re.search(r"action:\s*\n\s*do:\s*\n((?:\s*-\s.*\n)+)", raw)
    if m:
        lines = [l.strip().lstrip("- ").strip() for l in m.group(1).splitlines() if l.strip()]
        text = " / ".join(lines)
    else:
        fm, body = parse_frontmatter(raw)
        text = body.strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit] + ("…" if len(text) > limit else "")


def _git(args):
    try:
        out = subprocess.check_output(
            ["git"] + args, cwd=ROOT, stderr=subprocess.DEVNULL)
        return out.decode("utf-8", "replace")
    except Exception:
        return ""


def _goal_intent():
    """Read active task cards' Goal sections as INTENT for --auto.
    R1：替换已死的 CURRENT_GOAL.md 钩子——意图源 = task_cards/active 各卡 ## Goal。
    """
    out = []
    base = os.path.join(ROOT, "task_cards", "active")
    if not os.path.isdir(base):
        return ""
    for root, _dirs, files in os.walk(base):
        for name in sorted(files):
            if not name.endswith(".md") or name.startswith("_"):
                continue
            p = os.path.join(root, name)
            try:
                raw = io.open(p, "r", encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            m = re.search(r"^##\s+Goal\s*\n(.*?)(?=^##\s|\Z)", raw, re.M | re.S)
            if m:
                out.append(re.sub(r"\s+", " ", m.group(1)).strip()[:200])
    return " ".join(out)


def auto_query():
    """Build a query from the live repo state instead of a hand-typed one.

    This is the point of --auto: the query is derived from live repo state
    (changed files + recent commit subjects + persisted goal intent) rather
    than hand-typed by the Agent. A hand-typed query risks the Agent steering
    retrieval toward what it already believes; --auto instead anchors to recent
    activity. CAVEAT: the anchor IS the Agent's own recent commits + goal, so
    --auto reinforces recent focus (echo) - it does not independently recover
    state or suggest next steps. Goal intent (CURRENT_GOAL.md) aligns retrieval
    with WHAT the Agent is trying to do, not just WHAT files changed.
    """
    parts = []
    changed = _git(["diff", "--name-only", "HEAD"]) + "\n" + \
        _git(["diff", "--name-only", "--cached"])
    for line in changed.splitlines():
        line = line.strip()
        if not line:
            continue
        base = os.path.splitext(os.path.basename(line))[0]
        parts.append(base.replace("_", " ").replace("-", " "))
    subjects = _git(["log", "-3", "--format=%s"])
    parts.append(subjects)
    intent = _goal_intent()
    if intent:
        parts.append(intent)
    return " ".join(parts).strip()


def _context_query(context_path):
    """Build a query from the REAL working context (1.2 signal fix).

    --auto uses repo-wide git state at ROOT, which echoes AI-OS's own commits
    (rear-view mirror) — useless when the Agent is working inside a sub-project
    like projects/demo-project. --context instead derives the query from files
    recently touched in the given project dir (mtime-based), so retrieval tracks
    what the Agent is ACTUALLY working on, not what AI-OS committed last.
    """
    parts = []
    try:
        entries = []
        for root, dirs, files in os.walk(context_path):
            dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "data", "searxng", "dist", "build")]
            for name in files:
                if name.endswith((".js", ".py", ".html", ".md", ".json")):
                    p = os.path.join(root, name)
                    try:
                        entries.append((os.path.getmtime(p), p))
                    except OSError:
                        pass
        entries.sort(reverse=True)
        for _, p in entries[:15]:
            base = os.path.splitext(os.path.basename(p))[0]
            parts.append(base.replace("_", " ").replace("-", " "))
        parts.append(os.path.basename(os.path.abspath(context_path)))
        readme = os.path.join(context_path, "README.md")
        if os.path.isfile(readme):
            with io.open(readme, "r", encoding="utf-8", errors="replace") as f:
                head = f.read(500)
            m = re.search(r"^#\s+(.+)$", head, re.M)
            if m:
                parts.append(m.group(1))
    except OSError:
        return ""
    return " ".join(parts).strip()


def search(query, n=5, min_score=4.0):
    """检索核心（文本输出与 `--stdin-json` 共用 · ⛔ 不写第二套规则）。

    返回 (top, None) 或 (None, reason)。reason: `empty-query` / `no-signal:<词>`。
    """
    qtokens = tokenize(query)
    if not qtokens:
        return None, "empty-query"
    eff_q = effective_query_tokens(qtokens)
    if not query_has_signal(qtokens):
        return None, "no-signal:" + "/".join(sorted(eff_q)[:6])

    results = []
    for kind, path in collect_files():
        try:
            with io.open(path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except OSError:
            continue
        res = score_file(qtokens, raw)
        if res.score > 0 and passes_gate(qtokens, res):
            title = res.fm.get("title", "") or os.path.basename(path)
            results.append((res.score, kind, path, title, res.effective, extract_action(raw)))

    for path, weight, header, text in collect_ledger_chunks():
        res = score_ledger_chunk(qtokens, header, text)
        if res.score > 0 and passes_gate(qtokens, res):
            score = weight * res.score
            kind = "proven" if weight >= PROVEN_LEDGER_WEIGHT else "ledger"
            title = header if header else kind
            results.append((score, kind, path, title, res.effective, text[:160]))

# 坑清单逐条进语料（此前 PITFALLS 从未被召回）
    for path, weight, header, text in collect_pitfall_chunks():
        res = score_ledger_chunk(qtokens, header, text)
        if res.score > 0 and passes_gate(qtokens, res):
            results.append((weight * res.score, "pitfall", path, header, res.effective, text[:240]))

# 注入摘要库（长 pattern 的「一句照做」⇒ inject 通道）
    for path, weight, header, text in collect_digest_chunks():
        res = score_ledger_chunk(qtokens, header, text)
        if res.score > 0 and passes_gate(qtokens, res):
            results.append((weight * res.score, "digest", path, header, res.effective, text[:240]))

    # R2：按 (path, title) 去重保留最高分（修复 ledger 同 Entry 多 bullet 重复候选）
    seen = {}
    for r in results:
        key = (disp_path(r[2]), r[3])
        if key not in seen or r[0] > seen[key][0]:
            seen[key] = r
    results = list(seen.values())
    # 🔴 （误召回修复 · 第二批）：**标题相关性只作同分 tie-break**（⛔ 不压过分差）。
    #   教训（N=30 对照读数）：把「标题重合」当第一优先级会**系统性伤害** `PITFALLS ` /
    #   `Entry #N` 这类标题无语义的条目（标题 token 恒 0 ⇒ 相关条目被不相关条目挤下 top1）。
    #   ⇒ 主序仍是分数；标题只在同分时起作用。
    def _title_overlap(r):
        toks = {t for t in tokenize(str(r[3])) if is_meaningful(t)}
        return len(toks & eff_q) if len(toks) >= 2 else 0
    results.sort(key=lambda r: (-r[0], -_title_overlap(r)))
    return [r for r in results if r[0] >= min_score][:n], None


# 约定按**成本**分层，不按类型 ——
#: 短条目（PITFALLS / 账本 chunk · 一句能照做）⇒ inject（直接注入）；
#: 文件类（pattern / knowledge / experience 整篇）⇒ pointer（只给指针，正文不注入，与能力同口径）。
#: ⚠️ 文件类即使 action 摘要很短，正文仍是长文 ⇒ 一律 pointer；要"能注入"就先拆成 chunk。
INJECT_MAX_CHARS = 160


def form_of(kind, action_text):
    """→ 'inject' | 'pointer'（按成本分层：chunk / 摘要短 ⇒ inject；整篇文件 ⇒ pointer）。"""
    return "inject" if kind in ("pitfall", "ledger", "proven", "digest") else "pointer"


def run_stdin_json():
    """Runtime 集成入口（经验召回）：stdin `{query,n,min}` → stdout JSON hits。"""
    try:
        # 🔴 （读数 · /R2）：Runtime 以 UTF-8 写 stdin，但 Windows 下文本 stdin
        #   默认按 cp936/GBK 解码 ⇒ 中文 query 变 mojibake（hits 恒 0）。⇒ 按字节读、显式 UTF-8 解码。
        #   （Runtime 侧也固定了子进程编码，双保险；⛔ 不改检索规则/阈值/条数。）
        raw = sys.stdin.buffer.read()
        payload = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        payload = {}
    q = str(payload.get("query", "") or "")
    n = int(payload.get("n", 3) or 3)
    mn = float(payload.get("min", 6.0) or 6.0)
    top, reason = search(q, n, mn)
    if top is None:
        print(json.dumps({"ok": False, "reason": reason}, ensure_ascii=False))
        return 0
    hits = []
    for (s, k, p, t, m, a) in top:
        f = form_of(k, a)
        hits.append({
            "score": round(s, 1), "kind": k, "title": t, "file": disp_path(p),
            "content": a[:240] if f == "inject" else "",
            "matched": sorted(m)[:8], "form": f,
        })
    print(json.dumps({"ok": True, "hits": hits}, ensure_ascii=False))
    return 0


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Surface relevant past experience near the Agent (read-only).")
    ap.add_argument("query", nargs="*", help="describe the current task / problem")
    ap.add_argument("-n", type=int, default=5, help="max results (default 5)")
    ap.add_argument("--min", type=float, default=4.0, help="minimum relevance score (default 4.0)")
    ap.add_argument("--auto", action="store_true",
                    help="derive the query from live git state (changed files + recent commits)")
    ap.add_argument("--context", type=str, default=None,
                    help="real working context dir (e.g. projects/demo-project): derive query from recently touched files there (1.2 signal fix, beats --auto rear-view)")
    ap.add_argument("--stdin-json", action="store_true",
                    help="read {query,n,min} from stdin and print JSON hits (Runtime experience-recall integration)")
    args = ap.parse_args()
    if args.stdin_json:
        return run_stdin_json()
    query = " ".join(args.query)
    if args.context:
        ctx = _context_query(args.context)
        query = (query + " " + ctx).strip() if query else ctx
        if not query:
            print("[experience_push] --context: empty (no recent files in %s)" % args.context)
            return 0
    elif args.auto:
        auto = auto_query()
        query = (query + " " + auto).strip() if query else auto
        if not query:
            print("[experience_push] --auto: no git signal (clean tree, no recent commits)")
            return 0
    top, reason = search(query, args.n, args.min)
    if top is None:
        if reason == "empty-query":
            print("[experience_push] empty query after tokenization")
            return 1
        print("[experience_push] 查询信息量不足 ⇒ 不做材料发现（%s）" % (reason or ""))
        return 0
    if not top:
        print("[experience_push] no relevant past experience found for: %s" % query)
        print("[experience_push] 无相关经验值得记录（空结果即信号：本身是 Observation 候选；"
              "有真实踩坑/信念改变才沉淀，不硬写）")
        return 0

    print("[experience_push] 命中 %d 条相关经验（请采纳）：" % len(top))
    print("    以下经验与当前任务相关，内容摘要已列在下方——请在实现前阅读并采纳；")
    print("    需要全文时打开 file 路径（read-only，不注入上下文）。\n")
    for score, kind, path, title, matched, action in top:
        rel = disp_path(path)
        form = form_of(kind, action)
        print("- [%.1f][%s] %s" % (score, kind, title))
        print("    file : %s" % rel)
        print("    form : %s" % form)
        if form == "pointer":
            print("    内容 : （一长串 ⇒ 只给指针）需要时打开 file")
        elif kind in ("proven", "ledger", "pitfall"):
            # R2：账本/坑候选的"内容" = chunk 文本本身（不再是文件头样板）
            if action:
                print("    内容 : %s" % action)
        else:
            if action:
                print("    do   : %s" % action)
            preview = preview_text(path, action)
            if preview:
                print("    内容 : %s" % preview)
        print("    hit  : %s" % ", ".join(sorted(matched)[:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
