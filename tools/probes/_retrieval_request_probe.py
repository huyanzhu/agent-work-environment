#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_retrieval_request_probe.py — 阶段六 ① **Retrieval 请求接口原型**（只读 · 实验态）

依据：`p0/HANDOFF.md §四十一`（阶段六四阶段）· `p0/RUNTIME-WORK-UNDERSTANDING-DESIGN.md §0`（主线锚定）
      · `p0/PASSIVE-DISCOVERY-VERIFICATION.md`（卡点 1 根因 a 语料覆盖 / 根因 b 候选 id 粒度）

🔴 **本原型要回答的问题（阶段①）**：*高质量的检索需要什么样的**请求接口**？*
   ⇒ 做法 = **从"高质量检索"的实际需求反推字段与通道**，⛔ **不照搬**现有 Python 工具
     （`tools/experience_push.py`）的输入形态（单一 `query: str`）。

🔴 **与现有工具输入的关键区别（本原型的立身之本）**
   · 现有形态：所有材料**拼成一个字符串** ⇒ 一个 token 集合 ⇒ 一套匹配 ⇒ 无法回答
     "**是哪个字段把它召回的**"。`scratch/_capability_discovery_probe.py:request_tokens()`
     正是这种形态（第 331–349 行：need + why_now + search_terms + work_context 六项全拼）。
   · 本原型：**字段 → 通道** 显式路由（`FIELD_CHANNELS`），每个候选必须携带**字段级证据**；
     `context` 类字段**不单独构成命中**（防止长文本发散）；
     `identifier` 类字段**不分词**（精确标识符检索）。
   · 每个输入字段在 `field_usage` 里都要**交代去处**（用了/未用/为何未用）—— 这是"不同字段不同作用"的机械证据。

🔴 **纪律（逐条硬约束 · 自检强制）**
   · **只读**：不写文件 · 不建缓存 · ⛔ 不落推理原文（本原型只处理文件材料与派生字段）
   · **零网络**：不 import socket/urllib/http/requests · 不 subprocess（外部来源适配器是**独立进程**，见阶段③）
   · **规则唯一**：一律复用 `tools/experience_push.py` 的 `tokenize` / `is_meaningful`（⛔ 不出现第二套）
   · **来源适配复用**：本地来源枚举复用 `scratch/_capability_discovery_probe.py`（⛔ 不写第二套枚举）
   · ⛔ 不改评分 / 闸门 / 本体 / 注入 / 语料范围（本原型**不参与正式检索**）

stdin : RetrievalRequest v1（见 §接口）
stdout: CandidateSet v1（候选 + 来源状态 + 字段去向 + 缺口）
用法：
  python scratch/_retrieval_request_probe.py --selftest
  python scratch/_retrieval_request_probe.py --in scratch/_rr_req1.json
  python scratch/_retrieval_request_probe.py --in ... --compare    # 加打印"融合式"对照读数
"""
import hashlib
import io
import json
import os
import re
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
sys.path.insert(0, TOOLS)
sys.path.insert(0, PROBES)

import experience_push as ep            # noqa: E402  （唯一一套匹配规则）
import _capability_discovery_probe as cd  # noqa: E402  （唯一一套来源枚举）

try:  # Windows 控制台默认 GBK ⇒ 显式 UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

HERE_ABS = os.path.abspath(__file__)
SCHEMA_REQUEST = "retrieval-request/v1"
SCHEMA_RESULT = "candidate-set/v1"

SELFCHECK_FORBIDDEN = (
    r"\bopen\s*\([^)]*['\"][wax]",
    r"^\s*(import|from)\s+(socket|urllib|http|requests|subprocess)\b",
    r"\bsubprocess\.", r"\bshutil\.(copy|move|rmtree)\s*\(",
    r"\bos\.(remove|unlink|rename|mkdir|makedirs)\s*\(",
)

# ─────────────────────────────────────────────────────────────────────────────
# §接口 v1 · 字段 → 通道（**反推结果** · 每一步都在设计文档里给出理由）
# ─────────────────────────────────────────────────────────────────────────────
# 通道语义（**不是同一套匹配**）：
#   identifier : 字面标识符 · **不分词**（路径 / 文件名 / 名字）⇒ 精确来源检索
#   topic      : 主题词面 · 优先来源侧**结构化检索键**（trigger/keywords），否则 description
#   role       : 用途与角色 · 由 work_type / action 映射到角色需求（verification/guidance/…）
#   intent     : 语义需求主通道 · 词面（provided 时才存在）
#   context    : 上下文补充 · 词面但 **⛔ 不单独构成命中**（`recent_action_result` / `unresolved`）
#   meta       : **不检索** · 只驱动缺口提示与回退（`history_coverage` + 来源状态）
FIELD_CHANNELS = (
    ("target_refs", "identifier"),
    ("work_topic", "topic"),
    ("work_type", "role"),
    ("action", "role"),
    ("need", "intent"),
    # 🔴 跨来源反推出来的字段：**Agent 自写的检索键**（可多语言 / 可同义）。
    #    依据 = `CAPABILITY-DISCOVERY-LAYER-DESIGN §11`（/M2）：**第一障碍是描述语言/检索键不一致**，
    #    而 `SKILL.md` 规范**没有结构化检索键** ⇒ 必须由 Agent 提供，⛔ 不允许工具猜词。
    ("search_terms", "keys"),
    ("recent_action_result", "context"),
    ("unresolved", "context"),
    ("history_coverage", "meta"),
)
CHANNEL_WEIGHT = {"identifier": 3.0, "axis": 4.0, "topic": 2.0, "role": 1.5, "keys": 1.5, "intent": 1.0, "context": 0.5}
# `axis` = **词表三维标签的确定性匹配**（请求带 `axes` 时才有）——权重最高：
#    标签相等比词面相似可信（「先做词表 → 按词表整理能力」）。
PRIMARY_CHANNELS = ("identifier", "axis", "topic", "role", "keys", "intent")
AXIS_FIELDS = (("domain", "axis_domain"), ("help", "axis_help"), ("concern", "axis_concern"))
# 🔴 （读数驱动）：**聚合来源**（一个来源装多个能力包，如 `aios.capabilities`）
#    的每来源配额。`max_per_source`（默认 3）会让第 4 个起的能力**结构性不可见** ——
#    读数 `senior-engineer` / `prose_standard` 在 top8 里 MISS（同来源前 3 名是别的能力）。
#    首版值 6：够让同来源 6 个能力同时可见，仍给其它来源留名额。⚠️ 无验证基线，⛔ 非"已验证"。
AGGREGATE_PER_SOURCE_CAP = 8

# ── 🔴 （阶段过滤 · 请求新增可选 `phase`）────────────────────────
#   设计稿：`task_cards/active/AI-OS-Adaptation/PHASE-INJECTION-DESIGN-.md §4.2/§4.3/§4.4`
#   口径：**以能力自报的 `phases` 为准，⛔ 不叠设计稿 §4.2 的类别门**
#     （类别门是二手推断；`phases` 是逐能力判定的更准版本 —— AND 起来会有 6 个 (能力,阶段) 对永远不可达）。
#   行为：
#     · 请求带 `phase`（`S1|S2|S3|S4`）⇒ 只保留 `phases` 含该阶段的候选；
#     · **缺 `phases` 字段 = 无限制**（向后兼容：字段正在分批补；⛔ 不得把老文件滤没）；
#     · 前缀匹配（`S1` ↔ `S1-决策`）；
#     · ⛔ 不改既有输出 schema 的既有字段（只**增加** `phase_filter`）；⛔ 不改排序主键（`rank_key`）。
PHASE_FIELD = "phases"
PHASE_VALUES = ("S1", "S2", "S3", "S4")
PHASE_VALUE_SPLIT_RE = re.compile(r"[,，;；\s]+")


def phase_list(v):
    """`phases` 值 → 标签列表（**两种形态都容错**：行内数组 `[A, B]` 已是 list；裸逗号串再切一次）。"""
    raw = []
    if isinstance(v, (list, tuple)):
        raw = [str(x) for x in v]
    elif v is None:
        return []
    else:
        raw = [str(v)]
    out = []
    for x in raw:
        s = x.strip().strip("[]").strip().strip("\"'").strip()
        for piece in PHASE_VALUE_SPLIT_RE.split(s):
            p = piece.strip()
            if p and p not in out:
                out.append(p)
    return out


def phases_of(d):
    """描述符的阶段标签。**缺字段 / 空 ⇒ `[]` = 无限制**（向后兼容）。"""
    return phase_list(d.get(PHASE_FIELD))


def phase_allows(phases, want):
    """`phases` 是否含阶段 `want`（**前缀匹配**：`S1` ↔ `S1-决策`）。空列表 ⇒ 无限制。"""
    if not phases:
        return True
    w = str(want).strip().upper()
    for p in phases:
        v = str(p).strip()
        if v == w or v.upper().startswith(w + "-"):
            return True
    return False


# work_type / action → 角色需求（**显式映射表** · 未命中即拒绝判断，⛔ 不猜）
ROLE_ALIAS = (
    ("review", ("verification",)), ("审查", ("verification",)), ("verify", ("verification",)),
    ("test", ("verification",)), ("测试", ("verification",)), ("验证", ("verification",)),
    ("debug", ("verification", "operation")), ("调试", ("verification", "operation")),
    ("implement", ("guidance",)), ("实现", ("guidance",)),
    ("research", ("guidance", "evidence")), ("研究", ("guidance", "evidence")),
    ("document", ("guidance",)), ("文档", ("guidance",)),
    ("evaluat", ("verification", "evidence")), ("评估", ("verification", "evidence")),
)
WORK_FIELDS = ("work_state", "work_type", "work_topic", "action", "target_refs",
               "recent_action_result", "unresolved", "direction_change", "history_coverage",
               "evidence")
CTX_STATES = ("provided", "known-absent", "unknown")


def _sha12(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]


def _read(path):
    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def tristate(v, origin="runtime"):
    """上下文/工作字段 → 三态。**缺失 ≠ unknown**（沿用 三态纪律）。"""
    if isinstance(v, dict) and "state" in v:
        st = str(v.get("state"))
        if st not in CTX_STATES:
            return {"state": "invalid", "value": None, "origin": origin}
        return {"state": st, "value": v.get("value"), "origin": v.get("origin", origin),
                "confidence": v.get("confidence", "unknown"),
                "evidence": v.get("evidence", [])}
    if v is None:
        return {"state": "not-stated", "value": None, "origin": origin, "confidence": "unknown",
                "evidence": []}
    return {"state": "provided", "value": v, "origin": origin, "confidence": "unknown",
            "evidence": [], "legacy_bare_value": True}


def tv(req, field):
    """取字段值（仅 provided 才返回值）。`work` / 顶层 `need` / 顶层 `search_terms` 都支持。"""
    if field == "need":
        return tristate(req.get("need"))
    if field == "search_terms":
        return tristate(req.get("search_terms"))
    return tristate((req.get("work") or {}).get(field))


def as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [x for x in v if x is not None and str(x).strip()]
    if isinstance(v, dict):
        return [x for x in v.values() if x is not None and str(x).strip()]
    return [v]


# 🔴 读数补丁：**虚词/疑问结构零区分度**，但会被当成命中词 ⇒ 噪声。
#    实证：查询「这段代码有点多余，**能不能**删点东西」把 `不能 / 能不 / 有点` 当命中词，
#    结果 noise 候选（甚至 frontend-ui）排到了真正的 simplification_audit 前面（已读数 rank 4 vs 9）。
#    ⚠️ 只过滤**明确的**口语虚词/疑问结构；⛔ 不过滤实义词（"删除/多余/简化"保留）。
STOP_TOKENS = frozenset((
    "不能", "能不", "能不能", "有点", "一下", "看看", "帮我", "东西",
    "是否", "是不是", "有没有", "会不会", "能不能删", "这段", "这个", "那个",
    # 🔴 （②）：「数据」= **宽领域词，零区分度** —— 它既在 data-change-safety
    #    的 trigger（"数据库…"）里、也在 `domains/` 大量条目里，导致「数据分析」这类请求
    #    确定性命中"数据变更安全"（读数 rank 1）。`下数` 是「一下 + 数据」的跨词垃圾 bigram。
    #    ⚠️ 只滤这两个**零区分度**的词；真正的实义词（备份 / 迁移 / 索引 / 回填 / 还原）不受影响。
    "数据", "下数",
))


def toks(text):
    """唯一分词入口（复用 ep）· 只保留**有效**词 · 再滤口语虚词（见 `STOP_TOKENS`）。"""
    return {t for t in ep.tokenize(str(text)) if ep.is_meaningful(t) and t not in STOP_TOKENS}


def validate(req):
    """请求校验（Runtime 的机械职责）· 非法 ⇒ 明确报错，⛔ 不猜。"""
    errs = []
    need = tristate(req.get("need"))
    need_ok = need["state"] == "provided" and bool(str(need["value"] or "").strip())
    work = req.get("work") or {}
    provided = [k for k in work if tristate(work.get(k))["state"] == "provided"]
    if not need_ok and not provided:
        errs.append({"code": "no-retrieval-signal",
                     "detail": "need 与 work 全部非 provided ⇒ 无检索信号（⛔ 不得凭空检索）"})
    for k, v in list(work.items()):
        it = tristate(v)
        if it["state"] == "not-stated":
            errs.append({"code": "work-field-missing-state", "field": k,
                         "detail": "工作字段必须三态之一（provided/known-absent/unknown）；缺失 ≠ unknown"})
        elif it["state"] == "invalid":
            errs.append({"code": "work-field-bad-state", "field": k,
                         "detail": "state 必须是 " + "|".join(CTX_STATES)})
    if need["state"] == "invalid":
        errs.append({"code": "need-bad-state"})
    if need["state"] == "provided" and not need_ok:
        errs.append({"code": "need-empty", "detail": "provided 但为空 ⇒ 与未提供同效（⛔ 不当作需求）"})
    # `phase` 是**新增可选字段**；带了就必须是 S1–S4 之一（⛔ 不静默当"无过滤"，
    #   否则拼错阶段名会看起来"过滤了但没生效"，与 静默失效）。
    if "phase" in req and req.get("phase") not in (None, ""):
        ph = str(req.get("phase")).strip().upper()
        if ph not in PHASE_VALUES:
            errs.append({"code": "phase-bad-value", "field": "phase",
                         "detail": "phase 只能是 %s 之一（收到 %r）" % ("|".join(PHASE_VALUES), req.get("phase"))})
    b = req.get("budget") or {}
    for k in ("max_candidates", "max_per_source", "max_queries"):
        if k in b and not isinstance(b[k], int):
            errs.append({"code": "budget-not-int", "field": k})
    if req.get("roles_needed") is not None and not isinstance(req["roles_needed"], list):
        errs.append({"code": "roles-needed-not-list"})
    return errs


# ─────────────────────────────────────────────────────────────────────────────
# 匹配：每类通道**各写一处**（通道隔离 ⇒ 可归因）
# ─────────────────────────────────────────────────────────────────────────────
GENERIC_BASENAMES = frozenset(("skill.md", "index.md", "readme.md", "__init__.py", "main.py",
                               "package.json", "notes.md"))


def identifier_hits(refs, d):
    """`target_refs` 通道 —— **字面包含**匹配（不分词）。

    ⚠️ 读数修正：`SKILL.md` 这种**通用文件名**单独出现在 hay 里**不构成证据**
    （否则任意一个 `*/SKILL.md` 引用会命中全部来源的 SKILL.md ⇒ 精确检索退化为全命中）。
    """
    hay = " ".join([str(d.get("local_path") or ""), str(d.get("name") or ""),
                    str(d.get("id") or ""), str(d.get("declared_source") or "")]).lower().replace("\\", "/")
    out = []
    for r in refs:
        s = str(r).strip().lower().replace("\\", "/")
        if not s:
            continue
        base = s.rsplit("/", 1)[-1]
        if s in hay:
            out.append({"field": "target_refs", "channel": "identifier",
                        "basis": "literal-path-substring", "matched": [s], "strength": "strong"})
        elif len(base) >= 3 and base not in GENERIC_BASENAMES and base in hay:
            out.append({"field": "target_refs", "channel": "identifier",
                        "basis": "literal-basename-substring", "matched": [base], "strength": "strong"})
    return out


def _keys_of(d):
    """描述符的**全量检索键**（内部字段 `_keys_all` 优先；回退 `search_keys.sample`）。
    🔴 读数：只读 `sample`（前 3 键 × 60 字符）会让第 4 个起的检索键
    （尤其新增的 `keywords`）**永远不参与匹配** ⇒ 加词不生效。"""
    a = d.get("_keys_all")
    if isinstance(a, list) and a:
        return " ".join(str(x) for x in a)
    return " ".join(d.get("search_keys", {}).get("sample") or [])


def topic_hits(ftokens, d):
    """`work_topic` 通道 —— **来源侧结构化检索键优先**（不同来源不同方式）。"""
    key_t = toks(_keys_of(d))
    desc_t = toks(str(d.get("name") or "") + " " + str(d.get("description") or ""))
    ev = []
    sk = ftokens & key_t
    sd = ftokens & desc_t
    if sk:
        ev.append({"field": "work_topic", "channel": "topic", "basis": "structured-key-match",
                   "matched": sorted(sk)[:8], "strength": "strong"})
    if sd:
        ev.append({"field": "work_topic", "channel": "topic", "basis": "description-match",
                   "matched": sorted(sd)[:8], "strength": "medium"})
    return ev


def role_hits(vals, d):
    """`work_type` / `action` 通道 —— 显式角色映射；**无映射即拒绝判断**。"""
    want, keys = set(), []
    for v in vals:
        low = str(v).lower()
        for key, roles in ROLE_ALIAS:
            if key in low:
                want |= set(roles)
                keys.append(key)
    if not want or str(d.get("role")) not in want:
        return []
    return [{"field": "work_type|action", "channel": "role", "basis": "role-map(%s)" % ",".join(sorted(set(keys))),
             "matched": [str(d.get("role"))], "strength": "medium"}]


def intent_hits(ftokens, d):
    """`need` 通道 —— 词面（需 ≥1 有效命中；不设 3 词闸门：单字段短需求是合法输入）。"""
    ht = ftokens & (toks(str(d.get("name") or "")) | toks(str(d.get("description") or "")) |
                    toks(_keys_of(d)))
    if not ht:
        return []
    return [{"field": "need", "channel": "intent", "basis": "term-overlap",
             "matched": sorted(ht)[:8], "strength": "medium"}]


def keys_hits(ftokens, d):
    """`search_terms` 通道 —— **Agent 自供检索键**（跨语言/跨来源的关键；⛔ 工具不补词）。"""
    pool = toks(str(d.get("name") or "")) | toks(str(d.get("description") or "")) | \
        toks(_keys_of(d))
    ht = ftokens & pool
    if not ht:
        return []
    return [{"field": "search_terms", "channel": "keys", "basis": "agent-supplied-key-match",
             "matched": sorted(ht)[:8], "strength": "medium"}]


def context_hits(ftokens, d):
    """`recent_action_result` / `unresolved` 通道 —— **只产出加分证据，⛔ 不单独构成命中**。"""
    ht = ftokens & (toks(str(d.get("name") or "")) | toks(str(d.get("description") or "")))
    if not ht:
        return []
    return [{"field": "recent_action_result|unresolved", "channel": "context", "basis": "term-overlap",
             "matched": sorted(ht)[:8], "strength": "weak"}]


def axis_hits(req, d):
    """`axes` 通道 —— **词表三维标签的确定性匹配**（「先做词表 → 按词表整理能力」）。

    请求侧：`axes = {"domain": [...], "help": [...], "concern": [...]}`（值必须来自 `NEEDS-VOCAB`）；
    描述符侧：读 frontmatter 的 `axis_domain / axis_help / axis_concern`。
    命中 = **同轴取值交集** ⇒ `strength: strong`（标签相等，不是词面相似）。
    ⚠️ 只在请求**带了 axes** 时产生证据；没带 ⇒ 不参与（旧请求行为完全不变）。

    🔴 （② 第二种修法「**help 轴也必须命中**」）：
    单凭 `domain` 命中**不构成**轴通道 —— 宽领域标签零区分度（如「数据」只有 1 个能力，
    任何数据请求都会被"确定性地"塞回 data-change-safety，哪怕它只覆盖变更/迁移）。
    规则：**请求必须带 help 轴、且本描述符的 axis_help 与之有交集**，轴通道才成立；
    domain / concern 的交集仍作为证据列出（可归因），但不单独构成命中。
    ⇒ 请求只写 domain（无 help）时回退词面通道，不再"确定性"命中。
    """
    want = req.get("axes")
    if not isinstance(want, dict):
        return []
    want_help = [str(x).strip() for x in (want.get("help") or []) if str(x).strip()]
    if not want_help:
        return []
    have_help = [str(x) for x in (d.get("axis_help") or [])]
    if not [x for x in want_help if x in have_help]:
        return []
    ev = []
    for k, dk in AXIS_FIELDS:
        w = [str(x).strip() for x in (want.get(k) or []) if str(x).strip()]
        have = [str(x) for x in (d.get(dk) or [])]
        hit = [x for x in w if x in have]
        if hit:
            ev.append({"field": "axes." + k, "channel": "axis", "basis": "axis-label-match",
                       "matched": hit, "strength": "strong"})
    return ev


def match_descriptor(req, d):
    """→ (evidence[], hit_channels, primary_hit: bool)。字段隔离 + 可归因。"""
    ev = []
    refs = [v["value"] for v in [tv(req, "target_refs")] if v["state"] == "provided"]
    if refs:
        ev += identifier_hits(as_list(refs[0]), d)
    wt = tv(req, "work_topic")
    if wt["state"] == "provided":
        ev += topic_hits(toks(wt["value"]), d)
    role_vals = []
    for f in ("work_type", "action"):
        it = tv(req, f)
        if it["state"] == "provided":
            role_vals += [str(x) for x in as_list(it["value"])]
    if role_vals:
        ev += role_hits(role_vals, d)
    nd = tv(req, "need")
    if nd["state"] == "provided":
        ev += intent_hits(toks(nd["value"]), d)
    st = tv(req, "search_terms")
    if st["state"] == "provided":
        ev += keys_hits(toks(" ".join(str(x) for x in as_list(st["value"]))), d)
    ax = axis_hits(req, d)
    if ax:
        ev += ax
    ctxv = []
    for f in ("recent_action_result", "unresolved"):
        it = tv(req, f)
        if it["state"] == "provided":
            ctxv += [str(x) for x in as_list(it["value"])]
    if ctxv:
        ev += context_hits(toks(" ".join(ctxv)), d)
    chans = []
    for e in ev:
        if e["channel"] not in chans:
            chans.append(e["channel"])
    return ev, chans, any(c in PRIMARY_CHANNELS for c in chans)


def rank_key(item):
    """排序 = 通道多样性优先，其次通道权重和（**非权威** · 弱信号）。

    🔴 **capability 类结构性补位**。
    能力包描述符的 `role` 几乎只能是 `evidence`（`role_of()` 对 capability/pattern/experience
    一律给 evidence）⇒ 只有 work_type/action 映射到 research/evaluat 时才拿得到 `role` 通道，
    其余场景**天生比语料少一条通道**（能力 2 条 vs 语料常 3 条）。而排序**先比通道条数**，
    于是"全场匹配最强"的能力可能被压在 rank 6。
    ⇒ 当「kind=capability + 没有任何 role 通道 + 已有 ≥2 条真实通道」时，补一条**虚拟 role**
    （权重 = `CHANNEL_WEIGHT["role"]` = 1.5，语义 = 补上结构上拿不到的那条通道，⛔ 不是无差别提权）。
    ⚠️ 只在 2 条以上真实通道时才补 —— 1 条弱匹配的能力不该仅凭"是能力"前插（读数过反例：
    1 条通道的弱能力集体前插，top8 里 7–8 个都是能力，把真语料挤出去）。
    """
    ev, chans = item["evidence"], item["hit_channels"]
    virtual = 0.0
    if item.get("kind") == "capability" and "role" not in chans and len(chans) >= 2:
        virtual = CHANNEL_WEIGHT["role"]
    return (-(len(chans) + (1 if virtual else 0)),
            -(sum(CHANNEL_WEIGHT.get(c, 0.0) for c in chans) + virtual),
            item["id"])


# ─────────────────────────────────────────────────────────────────────────────
# 语料装载（本地 · 只读）· 来源状态机（八态 · 每来源恰好一个状态 + 依据）
# ─────────────────────────────────────────────────────────────────────────────
def ledger_descriptors():
    """账本 → **chunk 级**候选（卡点 1 根因 b：文件级 id 会让去重/追溯/多来源一致失真）。"""
    out = []
    path = os.path.join(AIOS_ROOT, "样例账本.md")
    try:
        lines = _read(path).splitlines()
    except OSError:
        return out
    header, buf, idx = "", [], 0
    chunks = []
    seen = {}
    for line in lines:
        stripped = line.strip()
        if line.startswith("#"):
            if buf:
                chunks.append((header, " ".join(buf)))
                buf = []
            header = line.lstrip("# ").strip()
        elif re.match(r"^-\s", line):
            if buf:
                chunks.append((header, " ".join(buf)))
            buf = [stripped.lstrip("- ").strip()]
        elif stripped and buf:
            buf.append(stripped.lstrip("- ").strip())
    if buf:
        chunks.append((header, " ".join(buf)))
    for i, (hd, text) in enumerate(chunks):
        if not text.strip():
            continue
        h = _sha12(text)
        occ = seen.get(h, 0)
        seen[h] = occ + 1
        out.append({
            "id": "ledger.proven:样例账本.md#" + h + ("#%d" % occ if occ else ""),
            "name": (hd or "chunk")[:80],
            "description": text[:200],
            "preview": text[:160],
            "kind": "ledger-chunk",
            "role": "evidence",
            "local_path": "样例账本.md",
            "version": "",
            "declared_source": "",
            "search_keys": {"structured_count": 0, "has_structured_keys": False, "sample": []},
            "freshness": {"mtime": "", "sha256_12": h},
            "body_chars": len(text),
            "chunk": {"index": idx, "chars": len(text), "content_sha12": h,
                      "occurrence": occ, "duplicate_content": occ > 0},
            "source": {"id": "ledger.proven", "scope": "project", "trust": "proven",
                       "requires_consent": False},
        })
        idx += 1
    return out


def corpus_descriptors():
    """现有正式语料（`domains/` + `task_cards/` 顶层）—— 作为独立来源登记（只读对照用）。"""
    out = []
    for kind, path in ep.collect_files():
        try:
            raw = _read(path)
        except OSError:
            continue
        fm, body = cd.parse_frontmatter(raw)
        d = cd.descriptor_of({"id": "aios.legacy-corpus", "kind": kind, "scope": "project",
                              "trust": "local", "requires_consent": False}, path, fm, body)
        d["id"] = "aios.legacy-corpus:" + cd._disp(path)
        d["preview"] = re.sub(r"\s+", " ", body.strip())[:160]
        d["source"] = {"id": "aios.legacy-corpus", "scope": "project", "trust": "local",
                       "requires_consent": False}
        out.append(d)
    return out


# ── 外部来源（R-1/R-2/R-3 批准）───────────────────────────────────────────────
# 🔴 **三机制分离的落实**：适配器（联网 · 独立进程 `scratch/_ext_gh_adapter.ps1`）与
#    **Retrieval 核心**（本文件 · **零网络**）**不在同一个进程里**。
#    本函数只**读适配器产出的本地缓存 JSON** ⇒ 检索侧可复跑、可无网络副作用。
EXTERNAL_CACHE = os.path.join(CACHE, "_ext_gh_candidates.json")
EXTERNAL_TTL_NOTE = "缓存读数（非实时）· 由独立适配器产出 · 检索侧零网络"


def external_descriptors():
    """→ (items, rec)。缓存缺失/异常 ⇒ **明确状态**，⛔ 不静默当成零命中。"""
    rec = {"id": "external.gh", "kind": "skill", "scope": "external", "discoverable": "default",
           "basis": "R-1/R-2/R-3（Human 批准 · 只读公开元数据）· " + EXTERNAL_TTL_NOTE,
           "descriptors": 0, "matched": 0}
    if not os.path.isfile(EXTERNAL_CACHE):
        rec.update(status="unavailable", reason="no-cache",
                   detail="适配器缓存不存在（⛔ 与 `queried-zero` 严格分开）")
        return [], rec
    try:
        with io.open(EXTERNAL_CACHE, "r", encoding="utf-8-sig", errors="replace") as f:
            blob = json.load(f)
    except Exception as exc:
        rec.update(status="error", reason="cache-unreadable", detail=str(exc)[:80])
        return [], rec
    st = str(blob.get("status") or "unknown")
    rec["adapter"] = {"shape": blob.get("shape"), "query": blob.get("query"),
                      "fetched_at": blob.get("fetched_at"), "adapter_status": st,
                      "duration_ms": blob.get("duration_ms"), "repos": len(blob.get("repos") or [])}
    if st != "matched":
        rec.update(status="unavailable", reason="adapter-status:" + st,
                   detail="适配器未返回 `matched`（`zero`/`error`/`unavailable` 各自可分）")
        return [], rec
    items = []
    for c in (blob.get("candidates") or []):
        desc = re.sub(r"\s+", " ", str(c.get("description") or "")).strip()
        sid = str(c.get("stable_id") or c.get("url") or c.get("name"))
        lang = "zh" if re.search(u"[\u4e00-\u9fff]", desc) else "en"
        items.append({
            "id": "external.gh:" + sid,
            "name": str(c.get("name") or sid),
            "description": desc[:240],
            "preview": desc[:160],
            "kind": "skill",
            "role": cd.role_of("skill", str(c.get("name") or ""), desc),
            "local_path": None,
            "remote_path": str(c.get("path") or ""),
            "remote_repo": str(c.get("source") or ""),
            "url": str(c.get("url") or ""),
            "install_url": str(c.get("install_url") or ""),
            "version": str(c.get("version") or ""),
            "audit": str(c.get("audit") or "not-available(from this source)"),
            "declared_source": str(c.get("source") or ""),
            "desc_lang": lang,
            "search_keys": {"structured_count": 0, "has_structured_keys": False, "sample": []},
            "freshness": {"mtime": str(blob.get("fetched_at") or ""), "sha256_12": ""},
            "body_chars": 0,
            "source": {"id": "external.gh", "scope": "external", "trust": "external",
                       "requires_consent": True},
        })
    rec.update(status="queried-pending", descriptors=len(items))
    return items, rec


# ── 受控扩展语料（阶段八）────────────────────────────────
# 🔴 **只改来源覆盖**：用一个环境开关切换语料版本，⛔ 不动评分 / 闸门 / 匹配规则 / 请求配置。
#    材料 = 六个时点**已机械识别**的相关材料（`known_relevant_materials`）· ⛔ 不递归索引
#    工作产物 `evidence_only: true` ⇒ 可作**证据**被发现，⛔ 不当可执行能力
D1_CORPUS = os.path.join(CACHE, "_d1_extended_corpus_v1.json")
D1_SOURCE_ID = "aios.extended.v1"


def d1_enabled():
    return os.environ.get("AIOS_D1_EXTENDED") == "1"


def extended_corpus_descriptors():
    """→ (items, rec)。语料未构建 ⇒ **明确状态**（⛔ 不静默当零命中）。"""
    rec = {"id": D1_SOURCE_ID, "kind": "mixed", "scope": "expanded", "discoverable": "default",
           "basis": "D-1 受控来源扩展（Human 2026-10-11）· 材料 = 六个时点已机械识别的相关材料 · "
                    "⛔ 不递归索引 · 工作产物 evidence_only · 维护类/未授权来源约束不变",
           "descriptors": 0, "matched": 0}
    if not os.path.isfile(D1_CORPUS):
        rec.update(status="unavailable", reason="corpus-not-built")
        return [], rec
    try:
        with io.open(D1_CORPUS, "r", encoding="utf-8-sig", errors="replace") as f:
            blob = json.load(f)
    except Exception as exc:
        rec.update(status="error", reason="corpus-unreadable", detail=str(exc)[:80])
        return [], rec
    items = []
    for m in (blob.get("materials") or []):
        if not m.get("readable"):
            continue
        abs_p = m.get("abs") or m.get("path_rel")
        fm, keys = {}, []
        if str(abs_p).lower().endswith(".md") and os.path.isfile(abs_p):
            try:
                fm, _body = cd.parse_frontmatter(_read(abs_p))
                keys = cd.search_keys_of(fm)
            except OSError:
                pass
        base = os.path.splitext(os.path.basename(m["path_rel"]))[0]
        # 路径词（把 `/ _ - .` 归一为空格）—— 让 `20261008000002_rls_policies.sql` 这类名字**可分词**
        pathwords = re.sub(r"\s+", " ", re.sub(r"[/_\-.]+", " ", m["path_rel"])).strip()
        desc = re.sub(r"\s+", " ", " ".join([pathwords, m.get("title") or "",
                                             m.get("desc") or ""])).strip()[:240]
        items.append({
            "id": D1_SOURCE_ID + ":" + str(m.get("root")) + "/" + m["path_rel"],
            "name": base,
            "description": desc,
            "preview": (m.get("title") or m.get("desc") or pathwords)[:160],
            "kind": m.get("kind") or "material",
            "role": "evidence" if m.get("evidence_only") else cd.role_of("tool", base, desc),
            "local_path": abs_p if m.get("root") == "product" else m["path_rel"],
            "version": m.get("sha12") or "",
            "declared_source": "root:" + str(m.get("root")),
            "path_words": pathwords[:160],
            "evidence_only": bool(m.get("evidence_only")),
            "executable": False,
            "search_keys": {"structured_count": len(keys), "has_structured_keys": bool(keys),
                            "sample": [k[:60] for k in keys[:3]]},
            "freshness": {"mtime": "", "sha256_12": m.get("sha12") or ""},
            "body_chars": m.get("bytes") or 0,
            "source": {"id": D1_SOURCE_ID, "scope": "expanded",
                       "trust": m.get("trust") or "local", "requires_consent": False},
        })
    rec.update(status="queried-pending", descriptors=len(items))
    return items, rec


def load_sources(req, corpus=None):
    """→ (descriptors, source_status[])。`corpus` 注入时用于自检（确定性合成语料）。"""
    if corpus is not None:
        descs = list(corpus["descriptors"])
        status = []
        for s in corpus["sources"]:
            n = len([d for d in descs if d["source"]["id"] == s["id"]])
            status.append({"id": s["id"], "kind": s.get("kind", "synth"), "scope": s.get("scope", "synth"),
                           "discoverable": s.get("discoverable", "default"),
                           "basis": s.get("discoverable_basis", "synth"), "descriptors": n, "matched": 0,
                           "status": "queried-zero" if n == 0 else "queried-pending"})
        return descs, status

    requested = set((req.get("sources") or {}).get("ids") or []) if isinstance(req.get("sources"), dict) \
        else set(req.get("sources") or [])
    descs, status = [], []
    for s in cd.build_sources():
        rec = {"id": s["id"], "kind": s["kind"], "scope": s["scope"],
               "discoverable": s.get("discoverable", "default"),
               "basis": s.get("discoverable_basis", "registry-declaration"),
               "descriptors": 0, "matched": 0}
        # **聚合来源**（一个来源里装多个能力包，如 `aios.capabilities`）
        #    ⇒ 下游配额按放宽值处理（否则第 4 个起的能力被结构性截掉）
        if s.get("aggregate") is True:
            rec["aggregate"] = True
        if s.get("requires_consent"):
            rec.update(status="unavailable", reason="requires-consent",
                       detail="需 Human 单独授权后才可只读访问（本轮⛔ 不触碰网络）")
        elif s.get("discoverable") == "excluded":
            rec.update(status="excluded", reason="by-design", detail="按来源声明不进默认发现")
        elif s.get("discoverable") == "on-demand" and rec["id"] not in requested:
            rec.update(status="skipped", reason="on-demand-not-requested",
                       detail="来源自述需**显式点名**（`sources.ids`）")
        else:
            items, why, failures = cd.list_source(s)
            rec["root"] = str(s.get("root") or "").replace("\\", "/") or None
            if why is not None:
                rec.update(status="configured-unreachable", reason=why)
            elif failures > 0:
                rec.update(status="error", reason="read-failures", descriptors=len(items))
                descs.extend(items)
            else:
                rec.update(status="queried-pending", descriptors=len(items))
                descs.extend(items)
        status.append(rec)

    # 账本（chunk 级）与既有语料（文件级）作为两个显式来源
    for sid, kind, loader, basis in (
        ("ledger.proven", "ledger-chunk", ledger_descriptors, "compiled-in: proven ledger chunks"),
        ("aios.legacy-corpus", "corpus", corpus_descriptors, "compiled-in: experience_push.SOURCES"),
    ):
        items = loader()
        status.append({"id": sid, "kind": kind, "scope": "project", "discoverable": "default",
                       "basis": basis, "descriptors": len(items), "matched": 0,
                       "status": "queried-pending" if items else "queried-zero"})
        descs.extend(items)
    # 外部来源（独立适配器缓存 · 检索侧仍零网络）
    ext_items, ext_rec = external_descriptors()
    status.append(ext_rec)
    descs.extend(ext_items)
    #  受控扩展语料（**只由开关切换语料版本** ⇒ 其余条件一律不变）
    if d1_enabled():
        d1_items, d1_rec = extended_corpus_descriptors()
        status.append(d1_rec)
        descs.extend(d1_items)
    return descs, status


# ─────────────────────────────────────────────────────────────────────────────
# 融合式对照（**现有形态**：所有材料拼成一个字符串 ⇒ 一个 token 集合 ⇒ 一套打分/闸门）
# ─────────────────────────────────────────────────────────────────────────────
def fused_query(req):
    parts = []
    nd = tv(req, "need")
    if nd["state"] == "provided":
        parts.append(str(nd["value"]))
    for f, _c in FIELD_CHANNELS:
        it = tv(req, f)
        if it["state"] == "provided":
            parts.extend(str(x) for x in as_list(it["value"]))
    st = req.get("search_terms")
    if isinstance(st, list):
        parts.extend(str(x) for x in st)
    elif st:
        parts.append(str(st))
    return " ".join(parts)


def fused_baseline(req, descriptors, top_k):
    """等价于现有形态：拼一个 query → 一套匹配 + `ep.passes_gate` 三条判据。"""
    q = fused_query(req)
    qt = ep.tokenize(q)
    qeff = len(ep.effective_query_tokens(qt))
    rows = []
    for d in descriptors:
        blob = str(d.get("name") or "") + " " + str(d.get("description") or "") + " " + \
            " ".join(d.get("search_keys", {}).get("sample") or [])
        shared = qt & ep.tokenize(blob)
        eff, _noi = ep.split_hits(shared)
        hi = bool(eff & toks(" ".join(d.get("search_keys", {}).get("sample") or [])))
        density = (len(eff) / float(qeff)) if qeff else 0.0
        rows.append({"id": d["id"], "effective_hits": len(eff), "density": round(density, 4),
                     "high_field": hi})
    passed = [r for r in rows if r["effective_hits"] >= ep.MIN_EFFECTIVE_HITS
              and r["density"] >= ep.MIN_HIT_DENSITY and r["high_field"]]
    passed.sort(key=lambda r: (-r["effective_hits"], r["id"]))
    return {"query_chars": len(q), "query_tokens": len(qt), "effective_query_tokens": qeff,
            "gate": {"min_effective_hits": ep.MIN_EFFECTIVE_HITS, "min_hit_density": ep.MIN_HIT_DENSITY,
                     "require_high_field": True},
            "candidates_passed_gate": len(passed), "top": passed[:top_k],
            "note": "**融合式** = 现有工具形态（单 query）· ⛔ 无法回答『哪个字段召回的』"}


# ─────────────────────────────────────────────────────────────────────────────
# CandidateSet（返回契约）
# ─────────────────────────────────────────────────────────────────────────────
def corpus_version(descriptors):
    """语料版本指纹（**只读** · 目标 ⑤"固定版本"对照所需）。

    ⛔ 本函数**不改语料范围**（那是，须裁定）；它只把"这次检索看到的是哪一版候选池"
    变成**可复算的指纹**，从而让 A/B 对照能够按 `corpus_version` 切分
    （与 `SOURCE-COVERAGE-AND-ID-DECISION.md` 的建议一致）。
    """
    items = []
    per_source = {}
    for d in descriptors:
        sid = d["source"]["id"]
        per_source[sid] = per_source.get(sid, 0) + 1
        loc = d.get("local_path") or d.get("remote_path") or d["id"]
        ver = (d.get("freshness") or {}).get("sha256_12") or d.get("version") or ""
        items.append((sid, str(loc), str(ver)))
    items.sort()
    blob = "\n".join("|".join(x) for x in items)
    return {"descriptor_count": len(items),
            "by_source": dict(sorted(per_source.items())),
            "fingerprint_sha12": hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()[:12]}


def key_discrimination(req, descriptors):
    """🔴 **诊断（⛔ 不改打分）**：Agent 自供检索键在**当前候选池**里的命中率。

    读数反例（rr3）：`skill` 这类通用键几乎命中整个 `SKILL.md` 族 ⇒ 它把
    **任意** skill 都召回来（外部 36 候选里 `canvas-design` / `docx` 就是这样进来的）。
    ⇒ 一个键若在候选池里命中率 ≥50%，它的召回**没有判别力**（噪声级）⇒ 必须能看见。
    同时记录一个**词袋的机械局限**：`tokenize` 丢弃短语结构 ⇒
    `"context assembly"` 与 `"assembly context"` 产生**相同** token 集合（可断言）。
    """
    st = tv(req, "search_terms")
    if st["state"] != "provided":
        return {"state": st["state"], "note": "未提供检索键 ⇒ 该通道不参与"}
    dtoks = [toks(str(d.get("name") or "") + " " + str(d.get("description") or "") + " " +
                  " ".join(d.get("search_keys", {}).get("sample") or [])) for d in descriptors]
    pool_n = max(1, len(dtoks))
    groups = {}
    for d, t in zip(descriptors, dtoks):
        groups.setdefault(d["source"]["id"], []).append(t)
    rows = {}
    for k in as_list(st["value"]):
        kt = toks(str(k))
        if not kt:
            continue
        hit = sum(1 for t in dtoks if kt & t)
        ratio = round(hit / float(pool_n), 3)
        # 🔴 **来源内**命中率才是关键：一个键在全池里看着"稀有"，在**新来源内部**可能命中全部
        #    （读数：外部 36 个 skill 的描述几乎都写 "skill" ⇒ 该键在 external.gh 内 ratio≈1 ⇒ 噪声级）
        per = {}
        for sid, ts in groups.items():
            if len(ts) < 5:
                continue
            per[sid] = round(sum(1 for t in ts if kt & t) / float(len(ts)), 3)
        worst = max(per.items(), key=lambda kv: kv[1]) if per else None
        rows[str(k)] = {"pool_hit_ratio": ratio, "pool_hits": hit, "pool_size": len(dtoks),
                        "max_source_ratio": ({"source": worst[0], "ratio": worst[1]} if worst else None),
                        "verdict": ("low-discrimination" if ratio >= 0.5 else
                                    ("weak" if ratio >= 0.2 else "discriminative"))}
    return {"state": "provided", "pool_size": len(dtoks), "keys": rows,
            "phrase_blind": {"why": "tokenize 丢弃短语结构",
                             "demo": "'context assembly' 与 'assembly context' 的 token 集合相同",
                             "same": toks("context assembly") == toks("assembly context")},
            "note": "⛔ 诊断字段 · 不参与打分/闸门/排序"}


def request_echo(req):
    """🔴 **仅标识与三态 · 不回显任何原文**。"""
    items = {}
    for f, ch in FIELD_CHANNELS:
        it = tv(req, f)
        val = it["value"]
        items[f] = {"state": it["state"], "origin": it.get("origin"),
                    "confidence": it.get("confidence"),
                    "chars": len(str(val)) if val is not None else 0}
    out = {"schema": req.get("schema") or SCHEMA_REQUEST,
           "request_id": req.get("request_id"),
           "field_channels": {f: ch for f, ch in FIELD_CHANNELS},
           "fields": items,
           "sources": req.get("sources"),
           "budget": req.get("budget") or {},
           "note": "仅标识 / 三态 / 字符数 · **不回显任何原文**"}
    # 阶段过滤的**请求侧回显**（只增加字段 · 不带 `phase` 的旧请求输出逐字不变）
    if req.get("phase") not in (None, ""):
        out["phase"] = str(req.get("phase")).strip().upper()
    return out


def run(payload, top_k=8, corpus=None, want_fused=False):
    t0 = time.time()
    req = payload.get("request") or payload
    errs = validate(req)
    if errs:
        return {"ok": False, "schema": SCHEMA_RESULT, "request_errors": errs}
    budget = req.get("budget") or {}
    max_cand = int(budget.get("max_candidates") or top_k or 8)
    max_per_source = int(budget.get("max_per_source") or 3)

    descriptors, status = load_sources(req, corpus)

    # **阶段过滤**（在匹配/排序**之前**；⛔ 不动 `rank_key`）——
    #   只缩候选池，不改任何既有字段。`phase_filter` 只做**派生读数**（多少条被阶段滤掉）。
    want_phase = str(req.get("phase") or "").strip().upper()
    phase_filter = None
    if want_phase:
        kept = []
        dropped_limited = 0
        phase_field_present = 0
        for d in descriptors:
            phases = phases_of(d)               # 缺字段 ⇒ [] ⇒ 无限制（向后兼容）
            if phases:
                phase_field_present += 1
            if phase_allows(phases, want_phase):
                kept.append(d)
            else:
                dropped_limited += 1
        phase_filter = {"phase": want_phase,
                        "descriptors_before": len(descriptors),
                        "descriptors_after": len(kept),
                        "dropped_by_phase": dropped_limited,
                        "with_phase_field": phase_field_present,
                        "rule": "phases 含该阶段（前缀匹配 S1↔S1-决策）；缺字段=无限制；⛔ 不叠类别门"}
        descriptors = kept

    items, field_usage = [], {}
    for f, ch in FIELD_CHANNELS:
        it = tv(req, f)
        field_usage[f] = {"state": it["state"], "channel": ch,
                          "confidence": it.get("confidence"),
                          "used_for_matching": ch not in ("meta",) and it["state"] == "provided",
                          "hits": 0}
        if it["state"] != "provided":
            field_usage[f]["why_unused"] = ("非 provided（%s）⇒ 不参与匹配" % it["state"]) if ch != "meta" \
                else "meta 通道不检索（只驱动缺口提示）"
        elif ch == "meta":
            field_usage[f]["why_unused"] = "meta 通道不检索（只驱动缺口提示 · 见 gaps）"

    for d in descriptors:
        ev, chans, primary = match_descriptor(req, d)
        if not primary:
            continue
        for e in ev:
            for f in str(e["field"]).split("|"):
                if f in field_usage:
                    field_usage[f]["hits"] += len(e.get("matched") or [])
        item = {
            "id": d["id"],
            "name": d["name"],
            "kind": d["kind"],
            "role": d["role"],
            "source": d["source"],
            "local_path": d.get("local_path"),
            "version": d.get("version") or "",
            "preview": (d.get("preview") or d.get("description") or "")[:160],
            # 🔴 能力自带的一句话介绍（frontmatter `intro`）· 无则空串（语料/账本没有）
            "intro": str(d.get("intro") or ""),
            "hit_channels": chans,
            "evidence": ev,
            "access": {"state": "read-only", "installed": False, "executed": False,
                       "basis": "discovery ≠ install ≠ execute"},
        }
        # 🔴 修正：`evidence_only` / `executable` / `path_words` 必须**传到候选**，
        #    否则下游（Agent / 盲判者 / 任何消费者）看不到"这只是工作产物"的约束
        #    —— 读数缺陷：只加在 descriptor 上，候选输出里全是 `null`
        #    ⇒ 盲判者据此指出"工作产物被当成能力呈现"。用 `is not None`（False 也要传）。
        for k in ("remote_path", "remote_repo", "url", "install_url", "audit", "desc_lang",
                  "evidence_only", "executable", "path_words", "kind"):
            if d.get(k) is not None:
                item[k] = d[k]
        if d.get("chunk"):
            item["chunk"] = d["chunk"]
        items.append(item)

    items.sort(key=rank_key)
    per_source, picked, chosen = {}, [], set()
    # 🔴 读数补丁：**聚合来源放宽每来源配额**。
    #    反例（本机读数）：`aios.capabilities` 一个来源装 10 个能力包，`max_per_source=3`
    #    ⇒ 第 4 个起的能力**结构性不可见**（senior-engineer / prose_standard 在 top8 里 MISS，
    #      而同来源前 3 名都是别的能力）。⇒ 聚合来源单独给更宽的首版值（模块级常量，可单测/可调）。
    per_source_cap = {}
    for rec in status:
        per_source_cap[rec["id"]] = AGGREGATE_PER_SOURCE_CAP if rec.get("aggregate") is True else max_per_source
    # 🔴 实证驱动的公平性修正：**每来源保底配额**。
    #    反例（rr3 读数）：外部来源 36 个候选**只进来 1 个**，而本地账本 4 个 Entry 全进 ——
    #    因为账本是长正文 × 通用词面（规模效应），弱信号计数天然更高。
    #    ⇒ 只按全局弱信号排序时，**新来源永远被既有的规模效应挤掉**（与卡点 1 同源）。
    quota = int(budget.get("per_source_quota") or 0)
    if quota > 0:
        by_src = {}
        for it in items:
            by_src.setdefault(it["source"]["id"], []).append(it)
        for sid in sorted(by_src, key=lambda s: rank_key(by_src[s][0])):
            for it in by_src[sid][:quota]:
                if len(picked) >= max_cand:
                    break
                picked.append(it)
                chosen.add(it["id"])
                per_source[sid] = per_source.get(sid, 0) + 1
    for it in items:
        if len(picked) >= max_cand:
            break
        if it["id"] in chosen:
            continue
        sid = it["source"]["id"]
        if per_source.get(sid, 0) >= per_source_cap.get(sid, max_per_source):
            continue
        picked.append(it)
        chosen.add(it["id"])
        per_source[sid] = per_source.get(sid, 0) + 1
    picked.sort(key=rank_key)

    for it in picked:
        for rec in status:
            if rec["id"] == it["source"]["id"]:
                rec["matched"] += 1
    for rec in status:
        if rec["status"] == "queried-pending":
            rec["status"] = "queried-matched" if rec["matched"] > 0 else "queried-zero"

    gaps = []
    for f, u in field_usage.items():
        if u["state"] != "provided":
            gaps.append({"kind": "field-not-provided", "field": f,
                         "detail": "缺失 ⇒ 相关通道不可用（⛔ 不得读成『没有相关能力』）"})
    zero = [r["id"] for r in status if r["status"] == "queried-zero"]
    if zero:
        gaps.append({"kind": "sources-zero", "detail": "已查询但零命中的来源：%s" % ", ".join(zero),
                     "note": "零命中 ≠ 该来源没有能力（可能语料不含此材料）"})
    unav = [r["id"] for r in status if r["status"] in ("unavailable", "configured-unreachable", "skipped", "error")]
    if unav:
        gaps.append({"kind": "sources-not-queried", "detail": ", ".join(unav),
                     "note": "**未接入/未授权** ⇒ 候选池天然不完整（卡点 1 根因 a）"})
    hc = tv(req, "history_coverage")
    if hc["state"] == "provided" and hc["value"] not in (None, "complete", True):
        gaps.append({"kind": "history-incomplete", "detail": str(hc["value"])[:80],
                     "note": "历史不完整 ⇒ 检索输入不完整 ⇒ 结论应降置信度（⛔ 不追问）"})

    out = {
        "ok": True,
        "schema": SCHEMA_RESULT,
        "request_echo": request_echo(req),
        "field_usage": field_usage,
        "corpus_version": corpus_version(descriptors),
        "key_discrimination": key_discrimination(req, descriptors),
        "candidates": picked,
        "source_status": status,
        "gaps": gaps,
        "diversity": {"candidate_count": len(picked),
                      "sources_represented": len({c["source"]["id"] for c in picked}),
                      # ⚠️ 读数修正：集合推导必须 `sorted` —— 否则跨进程 PYTHONHASHSEED 随机化
                      #    会让等价请求的输出**逐字不同** ⇒ 违反"可复算"（ST-7）
                      "roles": {r: len([c for c in picked if c["role"] == r])
                                for r in sorted({c["role"] for c in picked})},
                      "sources": sorted({c["source"]["id"] for c in picked}),
                      "channels_used": sorted({c for it in picked for c in it["hit_channels"]})},
        "ordering": "通道多样性 → 通道权重 → id（**弱信号 · 非权威** · ⛔ 不用分数替代适用性判断）",
        "budget_applied": {"max_candidates": max_cand, "max_per_source": max_per_source,
                           "per_source_quota": int(budget.get("per_source_quota") or 0),
                           "truncated": len(items) > len(picked), "matched_before_budget": len(items)},
        "unimplemented": ["conflict-relation", "external-source-adapters（阶段③）"],
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
    # **只增加**字段（请求未带 `phase` 时输出与旧版逐字一致 ⇒ 零回退）。
    if phase_filter is not None:
        out["phase_filter"] = phase_filter
    if want_fused:
        out["fused_baseline"] = fused_baseline(req, descriptors, max_cand)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 自检（确定性 · 合成语料 ⇒ 字段隔离必须可机械断言）
# ─────────────────────────────────────────────────────────────────────────────
def _synth():
    srcs = [{"id": "synth.A", "kind": "skill", "scope": "project", "discoverable_basis": "synth"},
            {"id": "synth.B", "kind": "skill", "scope": "project", "discoverable_basis": "synth"}]
    descs = [
        {"id": "synth.A:alpha-review", "name": "alpha-review", "kind": "skill",
         "description": "code review checklist and verification guidance",
         "preview": "code review checklist", "local_path": ".agents/skills/alpha-review/SKILL.md",
         "version": "", "declared_source": "", "role": "verification", "body_chars": 10,
         "search_keys": {"structured_count": 2, "has_structured_keys": True,
                         "sample": ["review", "verification"]},
         "freshness": {"mtime": "", "sha256_12": "0" * 12},
         "source": {"id": "synth.A", "scope": "project", "trust": "local", "requires_consent": False}},
        {"id": "synth.B:beta-runtime", "name": "beta-runtime", "kind": "skill",
         "description": "runtime work understanding and context assembly",
         "preview": "runtime work understanding", "local_path": ".agents/skills/beta-runtime/SKILL.md",
         "version": "", "declared_source": "", "role": "guidance", "body_chars": 10,
         "search_keys": {"structured_count": 0, "has_structured_keys": False, "sample": []},
         "freshness": {"mtime": "", "sha256_12": "0" * 12},
         "source": {"id": "synth.B", "scope": "project", "trust": "local", "requires_consent": False}},
    ]
    return {"sources": srcs, "descriptors": descs}


def selftest():
    ok = []

    def check(name, cond):
        ok.append((name, bool(cond)))

    # S1–S2 校验
    r = run({"request": {"need": "", "work": {}}}, 5, corpus=_synth())
    check("S1 no-signal-rejected", r["ok"] is False and
          any(e["code"] == "no-retrieval-signal" for e in r["request_errors"]))
    r = run({"request": {"need": {"state": "unknown"}, "work": {"work_topic": None}}}, 5, corpus=_synth())
    check("S2 missing-state-is-not-unknown", r["ok"] is False and
          any(e["code"] == "work-field-missing-state" for e in r["request_errors"]))
    r = run({"request": {"need": {"state": "bogus"}}}, 5, corpus=_synth())
    check("S2b bad-state-rejected", any(e["code"] == "need-bad-state" for e in r["request_errors"]))

    # S3 字段隔离（同一个语料 · 不同字段 ⇒ 不同候选 + 不同通道）
    r = run({"request": {"request_id": "t-id", "need": {"state": "known-absent"},
                         "work": {"target_refs": {"state": "provided", "value": ["alpha-review/SKILL.md"]}}}},
            5, corpus=_synth())
    ids = [c["id"] for c in r["candidates"]]
    check("S3a identifier-only-field", ids == ["synth.A:alpha-review"]
          and r["candidates"][0]["hit_channels"] == ["identifier"])
    r = run({"request": {"request_id": "t-topic", "need": {"state": "known-absent"},
                         "work": {"work_topic": {"state": "provided",
                                                 "value": "runtime work understanding"}}}},
            5, corpus=_synth())
    ids = [c["id"] for c in r["candidates"]]
    check("S3b topic-only-field", ids == ["synth.B:beta-runtime"]
          and r["candidates"][0]["hit_channels"] == ["topic"])
    r = run({"request": {"request_id": "t-role", "need": {"state": "known-absent"},
                         "work": {"work_type": {"state": "provided", "value": "review"}}}},
            5, corpus=_synth())
    check("S3c role-channel", [c["id"] for c in r["candidates"]] == ["synth.A:alpha-review"]
          and r["candidates"][0]["hit_channels"] == ["role"])
    # 🔴 context 字段**单独不构成命中**（防长文本发散）
    r = run({"request": {"request_id": "t-ctx", "need": {"state": "known-absent"},
                         "work": {"recent_action_result": {"state": "provided",
                                                           "value": "runtime work understanding alpha review " * 6}}}},
            5, corpus=_synth())
    check("S3d context-alone-never-hits", r["candidates"] == []
          and r["field_usage"]["recent_action_result"]["hits"] == 0)
    # context 作为**加分证据**在已有主通道命中时出现
    r = run({"request": {"request_id": "t-ctx2", "need": {"state": "known-absent"},
                         "work": {"work_topic": {"state": "provided", "value": "runtime work understanding"},
                                  "recent_action_result": {"state": "provided",
                                                            "value": "we were reading runtime work understanding docs"}}}},
            5, corpus=_synth())
    check("S3e context-as-supporting-evidence",
          len(r["candidates"]) == 1 and "context" in r["candidates"][0]["hit_channels"])

    # S4 字段去向（每个字段都交代）
    check("S4 field-usage-complete",
          set(r["field_usage"]) == {f for f, _ in FIELD_CHANNELS}
          and r["field_usage"]["history_coverage"]["why_unused"].startswith("meta"))

    # S5 请求回显不含原文
    echo = r["request_echo"]
    check("S5 echo-no-raw-text",
          all(k in ("state", "origin", "confidence", "chars") for v in echo["fields"].values() for k in v)
          and "runtime work understanding" not in json.dumps(echo, ensure_ascii=False))

    # S6 来源状态：每来源恰好一个状态
    check("S6 one-status-per-source", len({s["id"] for s in r["source_status"]}) == len(r["source_status"])
          and all(s.get("status") for s in r["source_status"]))

    # S7 真实语料：chunk 级身份（卡点 1 根因 b）
    led = ledger_descriptors()
    check("S7a ledger-chunks-nonempty", len(led) > 1)
    check("S7b ledger-chunk-ids-unique", len({d["id"] for d in led}) == len(led))
    check("S7c ledger-id-is-content-level",
          all(d["chunk"]["content_sha12"] in d["id"] and d["chunk"]["content_sha12"] != "0" * 12
              for d in led))
    # 同一文件内多个 chunk ⇒ 多个**不同**候选 id（旧形态：739 chunk 共享一个文件级 id）
    check("S7d no-file-level-collapse", len(led) == len({d["id"] for d in led}) and len(led) > 10)
    # 🔴 读数新发现：账本内**存在内容完全相同的 chunk** ⇒ 纯内容 hash **会撞 id** ⇒
    #    必须以 `occurrence` 区分，并把"同内容"作为**显式可读的去重信息**（⛔ 不静默丢）
    dups = [d for d in led if d["chunk"]["duplicate_content"]]
    grp = {}
    for d in led:
        grp.setdefault(d["chunk"]["content_sha12"], []).append(d["id"])
    check("S7e duplicate-chunks-are-labelled",
          len(dups) == sum(len(v) - 1 for v in grp.values() if len(v) > 1))

    # S8 预算有界
    big = {"sources": _synth()["sources"],
           "descriptors": [dict(_synth()["descriptors"][i % 2], id="synth.X:item%d" % i,
                                name="item%d" % i,
                                local_path=".agents/skills/item%d/SKILL.md" % i) for i in range(20)]}
    r = run({"request": {"need": {"state": "known-absent"},
                         "work": {"work_topic": {"state": "provided", "value": "runtime work understanding"}},
                         "budget": {"max_candidates": 3, "max_per_source": 2}}}, 8, corpus=big)
    check("S8 budget-enforced", len(r["candidates"]) <= 3
          and all(v <= 2 for v in [len([c for c in r["candidates"] if c["source"]["id"] == s]) for s in
                                   ("synth.A", "synth.B")]))

    # S9 融合式对照：长字段拼接 ⇒ 密度闸门失效（客观读数）
    real = run({"request": {"request_id": "t-fused", "need": {"state": "provided", "value":
                 "我们需要让 Runtime 通过 Agent 暴露的信息更可靠地了解当前正在发生什么并在正确时机提供适用能力"},
                 "search_terms": ["runtime", "retrieval", "candidate", "source", "field", "evidence"],
                 "work": {"work_topic": {"state": "provided", "value": "Runtime 工作感知与 Retrieval 请求接口"},
                          "recent_action_result": {"state": "provided",
                                                   "value": "读完了 HANDOFF 四十一 与 设计文档 并开始写原型" * 4}}}},
         5, corpus=_synth(), want_fused=True)
    fb = real["fused_baseline"]
    check("S9 fused-baseline-reported", fb["query_tokens"] > 30 and "candidates_passed_gate" in fb)
    check("S9b separated-still-attributes",
          all(c["evidence"] for c in real["candidates"]) and real["diversity"]["channels_used"])

    # S12 外部来源（R-1/R-2/R-3）：缓存存在 ⇒ 可参与混合候选；缺失 ⇒ **明确 unavailable**
    ext_items, ext_rec = external_descriptors()
    if os.path.isfile(EXTERNAL_CACHE):
        check("S12a external-cache-loaded",
              ext_rec["status"] in ("queried-pending", "unavailable")
              and (ext_rec["status"] != "queried-pending" or len(ext_items) > 0))
        if ext_items:
            check("S12b external-descriptor-shape",
                  all(i["source"]["id"] == "external.gh" and i["version"].startswith("commit:")
                      and i["remote_repo"] and i["url"] for i in ext_items))
            check("S12c external-not-installed",
                  all(i["source"]["requires_consent"] is True for i in ext_items))
    else:
        check("S12a external-missing-is-explicit", ext_rec["status"] == "unavailable"
              and ext_rec["reason"] == "no-cache")

    # S13 每来源保底配额（rr3 实证驱动：外部 36 候选只进 1 个 ⇒ 新来源被规模效应挤掉）
    s0 = _synth()
    s3 = dict(s0["descriptors"][1], id="synth.C:gamma", name="gamma",
              description="code review verification guidance",
              local_path=".agents/skills/gamma/SKILL.md",
              source={"id": "synth.C", "scope": "project", "trust": "local", "requires_consent": False})
    corp3 = {"sources": s0["sources"] + [{"id": "synth.C", "kind": "skill", "scope": "project",
                                          "discoverable_basis": "synth"}],
             "descriptors": s0["descriptors"] + [s3]}
    r = run({"request": {"need": {"state": "known-absent"},
                         "work": {"work_topic": {"state": "provided",
                                                 "value": "runtime work understanding code review verification"}},
                         "budget": {"max_candidates": 2, "max_per_source": 2, "per_source_quota": 1}}},
            8, corpus=corp3)
    check("S13 per-source-quota", len({c["source"]["id"] for c in r["candidates"]}) >= 2
          and r["budget_applied"]["per_source_quota"] == 1)

    # S14 检索键判别力诊断（rr3 实证驱动：`skill` 这类通用键召回不具判别力）
    r = run({"request": {"need": {"state": "known-absent"},
                         "work": {"work_topic": {"state": "provided", "value": "runtime work understanding"}},
                         "search_terms": ["runtime", "code review"]}}, 8, corpus=_synth())
    kd = r["key_discrimination"]
    check("S14a key-discrimination-reported",
          kd["state"] == "provided" and set(kd["keys"]) == {"runtime", "code review"}
          and all("pool_hit_ratio" in v for v in kd["keys"].values()))
    check("S14b key-discrimination-layer",
          kd["keys"]["runtime"]["verdict"] in ("low-discrimination", "weak", "discriminative")
          and kd["keys"]["code review"]["pool_hits"] >= 1)
    check("S14c phrase-blind-demo", kd["phrase_blind"]["same"] is True)

    # S15 阶段过滤：给 `phase` ⇒ 只留该阶段能力；
    #     **缺 `phases` 字段 = 无限制**（向后兼容）；`phase_filter` 只做派生读数。
    s0 = _synth()
    phased_descs = [
        dict(s0["descriptors"][0], id="synth.A:alpha-s1", name="alpha-s1",
             phases=["S1-决策"], local_path=".agents/skills/alpha-s1/SKILL.md"),
        # 裸逗号串形态（容错：上游若写成标量也要能读）
        dict(s0["descriptors"][1], id="synth.B:beta-s23", name="beta-s23",
             phases="S2-实现, S3-受阻", local_path=".agents/skills/beta-s23/SKILL.md"),
        # 缺字段 ⇒ 无限制（向后兼容：字段分批补时老文件不得被滤没）
        dict(s0["descriptors"][0], id="synth.A:gamma-nophase", name="gamma-nophase",
             local_path=".agents/skills/gamma-nophase/SKILL.md"),
    ]
    corp_phase = {"sources": s0["sources"], "descriptors": phased_descs}
    r = run({"request": {"phase": "S1", "need": {"state": "known-absent"},
                         "work": {"work_topic": {"state": "provided",
                                                 "value": "code review verification runtime work understanding"}}}},
            8, corpus=corp_phase)
    ids = [c["id"] for c in r["candidates"]]
    check("S15a phase-filter-keeps-matching", "synth.A:alpha-s1" in ids)
    check("S15b phase-filter-drops-other-phase", "synth.B:beta-s23" not in ids)
    check("S15c phase-missing-field-unlimited", "synth.A:gamma-nophase" in ids)
    check("S15d phase-filter-reported",
          r.get("phase_filter", {}).get("phase") == "S1"
          and r["phase_filter"]["descriptors_before"] == 3
          and r["phase_filter"]["descriptors_after"] == 2
          and r["phase_filter"]["dropped_by_phase"] == 1
          and r["phase_filter"]["with_phase_field"] == 2)
    # 不带 phase ⇒ 输出里没有 phase_filter（零回退）
    r0 = run({"request": {"need": {"state": "known-absent"},
                          "work": {"work_topic": {"state": "provided", "value": "code review"}}}},
             8, corpus=corp_phase)
    check("S15e no-phase-no-filter-field", "phase_filter" not in r0 and "phase" not in r0["request_echo"])
    # 向后兼容用法：裸逗号串被切成两个阶段标签 ⇒ S3 也能命中 β
    r = run({"request": {"phase": "S3", "need": {"state": "known-absent"},
                         "work": {"work_topic": {"state": "provided",
                                                 "value": "code review verification runtime work understanding"}}}},
            8, corpus=corp_phase)
    check("S15f scalar-comma-tolerated",
          "synth.B:beta-s23" in [c["id"] for c in r["candidates"]])

    # S16 非法 `phase` ⇒ 明确报错（⛔ 不静默当"无过滤"）
    r = run({"request": {"phase": "S9", "need": {"state": "known-absent"},
                         "work": {"work_topic": {"state": "provided", "value": "x"}}}}, 5, corpus=_synth())
    check("S16 bad-phase-rejected",
          r.get("ok") is False and any(e["code"] == "phase-bad-value" for e in r.get("request_errors", [])))

    # S10 只读护栏
    src = _read(HERE_ABS)
    hits = [p for p in SELFCHECK_FORBIDDEN if re.search(p, src, re.M)]
    check("S10 readonly-guard", not hits)

    # S11 可复算：所有由集合推导出的输出键必须**有序**（否则跨进程 PYTHONHASHSEED 会让
    #     等价请求逐字不同 —— 本原型实际踩到过：`diversity.roles` 曾是 set 推导）
    r = run({"request": {"need": {"state": "known-absent"},
                         "work": {"work_type": {"state": "provided", "value": "review"},
                                  "work_topic": {"state": "provided", "value": "code review"}}}},
            5, corpus=_synth())
    dv = r["diversity"]
    check("S11 output-key-order-stable",
          list(dv["roles"]) == sorted(dv["roles"]) and dv["sources"] == sorted(dv["sources"])
          and dv["channels_used"] == sorted(dv["channels_used"]))

    failed = [n for n, c in ok if not c]
    print(json.dumps({"selftest": {"total": len(ok), "passed": len(ok) - len(failed), "failed": failed}},
                     ensure_ascii=False))
    return 0 if not failed else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    top_k, want_fused, inp = 8, "--compare" in sys.argv, None
    for a in sys.argv[1:]:
        if a.startswith("--top="):
            top_k = int(a.split("=", 1)[1])
        elif a.startswith("--in="):
            inp = a.split("=", 1)[1]
    raw = _read(inp).encode("utf-8") if inp else sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig") or "{}")
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": "bad-input", "detail": str(exc)[:80]}) + "\n")
        return 2
    sys.stdout.write(json.dumps(run(payload, top_k, want_fused=want_fused), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
