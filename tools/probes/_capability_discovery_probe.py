#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_capability_discovery_probe.py — §11 **最小验证原型**（跨来源能力发现 · 只读 · 实验态）

依据：`p0/CAPABILITY-DISCOVERY-LAYER-DESIGN.md`（草案 v0.2）
  · §5.1 来源注册表（本地子集）· §5.2 适配器契约 · §6.1 CapabilityDescriptor
  · §6.3b 候选关系模型 · §7.1 迭代回路 · §9 数据模型 · §10 接口与协议

🔴 **纪律（逐条硬约束 · 自检强制）**：
  · **只读**：不写任何文件 · 不建缓存 · 不落正文原文
  · **零网络**：不 import socket/urllib/http/requests · 不 subprocess
  · **不安装 / 不连接 / 不执行**：只做发现（发现 ≠ 安装 ≠ 连接 ≠ 启用 ≠ 执行）
  · **不落原文**：输出只有标识 / 派生量 / 证据指向（**目录层 `description` 属元数据**，正文只输出长度与 hash）
  · ** 候选集合优先**：默认产出**一组**候选 + **关系**，⛔ 不以唯一最高分候选为终点
  · ⛔ 不改动 `tools/experience_push.py` 的规则 / 影子开关 / `inject` / exposure / 本体

stdin : CapabilityRequest（§4.1）—— 可含 `follow_up` 用于 §7.1 迭代验证
stdout: DiscoveryResult / CandidateSet（§9）

用法（只读）：
  echo {...} | python scratch/_capability_discovery_probe.py
  python scratch/_capability_discovery_probe.py --selftest
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

import experience_push as ep  # noqa: E402  （**只复用** tokenize / is_meaningful ⇒ 不出现第二套规则）

try:  # Windows 控制台默认 GBK ⇒ 显式 UTF-8（否则含 `⇒` 的断言会崩在最后一步）
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

HERE_ABS = os.path.abspath(__file__)
SOURCE_IDS = ("aios.capabilities", "skill.project", "skill.intake", "skill.maintenance", "skill.user")
# 🔴 读数补丁：`md_frontmatter` 适配器扫一级 `*.md` 时，`INDEX.md` / `README.md`
#    没有 frontmatter ⇒ 会被当成 name="capabilities"、keys=0 的"能力"进候选池
#    （12 个描述符里 2 个是导航文件 ⇒ 语料污染）。按通用名排除。
GENERIC_MD_NAMES = frozenset(("index.md", "readme.md"))
SELFCHECK_FORBIDDEN = (
    r"\bopen\s*\([^)]*['\"][wax]",                                    # 写模式打开
    r"^\s*(import|from)\s+(socket|urllib|http|requests|subprocess)\b",  # 网络 / 子进程
    r"\bsubprocess\.", r"\bshutil\.(copy|move|rmtree)\s*\(",
    r"\bos\.(remove|unlink|rename|mkdir|makedirs)\s*\(",
)


# ─────────────────────────────────────────────────────────────────────────────
# 来源注册表（§5.1 本地子集）· 🔴 新增来源 = **加一条注册项**，核心不改（验收）
# ─────────────────────────────────────────────────────────────────────────────
def extra_project_roots():
    raw = os.environ.get("AIOS_DISCOVERY_EXTRA_PROJECTS", "D:/deepseek-harness")
    return [p for p in raw.split(os.pathsep) if p.strip()]


def build_sources():
    """来源注册表（**配置即新增来源** ⇒ 中间层核心零改动 · 验收）。

    🔴 （要求）：每条来源必须声明 **`discoverable`** 与**依据** ——
       · `default`     ：正常进入默认发现
       · `on-demand`   ：仅当请求**显式点名**（`request.sources`）时才查询
       · `excluded`    ：按设计**不进默认发现**（协议支持；⚠️ 本机暂无实例 ⇒ 见 §7 未核实项）
    """
    home = os.path.expanduser("~")
    reg = "registry-declaration"
    src = [
        {"id": "aios.capabilities", "kind": "capability", "scope": "project",
         "root": os.path.join(AIOS_ROOT, "capabilities"), "adapter": "md_frontmatter",
         "trust": "local", "requires_consent": False, "discoverable": "default",
         # **聚合来源**标记 —— 一个来源里装着多个能力包（10+ 描述符）。
         #    检索的 `max_per_source`（默认 3）会因此把第 4 个起的能力**结构性截掉**
         #    ⇒ 读数 senior-engineer / prose_standard 在 top8 里 MISS（同来源配额满）。
         "aggregate": True,
         "discoverable_basis": reg},
        {"id": "skill.intake", "kind": "skill", "scope": "project",
         "root": os.path.join(AIOS_ROOT, "evolution", "intake"), "adapter": "skill_dir",
         "trust": "local", "requires_consent": False, "discoverable": "default",
         "discoverable_basis": reg},
        {"id": "skill.maintenance", "kind": "skill", "scope": "project",
         "root": os.path.join(AIOS_ROOT, "maintenance-skills"), "adapter": "skill_dir",
         "trust": "local", "requires_consent": False, "discoverable": "on-demand",
         "discoverable_basis": "source-self-description: maintenance-skills/health-check/SKILL.md "
                                "（自述「不是普通 Work Task 的默认上下文，不进 task_start 统一发现」）"},
        # 这两条来源的配置目录**在本机不存在**（`root-not-found`）⇒
        #    每次检索都在来源状态里白占一条"配置指向不存在"的噪音，且从未产出描述符。
        #    处置 = 按协议标 `excluded`（显式排除，⛔ 不静默当零命中）；依据写明可逆：
        #    将来真要接入用户级 / 项目级 `.agents/skills`，建好目录后把 discoverable 改回 `default`。
        {"id": "skill.project:AI-os", "kind": "skill", "scope": "project",
         "root": os.path.join(AIOS_ROOT, ".agents", "skills"), "adapter": "skill_dir",
         "trust": "local", "requires_consent": False, "discoverable": "excluded",
         "discoverable_basis": "2026-10-28 实测：`<repo>/.agents/skills` 不存在（root-not-found）⇒ "
                               "显式排除；建目录后可改回 default"},
        {"id": "skill.user", "kind": "skill", "scope": "user",
         "root": os.path.join(home, ".agents", "skills"), "adapter": "skill_dir",
         "trust": "local", "requires_consent": False, "discoverable": "excluded",
         "discoverable_basis": "2026-10-28 实测：`~/.agents/skills` 不存在（root-not-found）⇒ "
                               "显式排除；建目录后可改回 default"},
        # ── 外部来源：**只登记 · 不访问** ⇒ 状态必为 `unavailable(requires-consent)` ──
        #    🔴 用途：把"未经授权"这一**真实边界**变成**可表达状态**（R4 · 不触碰网络）
        {"id": "skill.wellknown:agent.qq.com", "kind": "skill", "scope": "external",
         "root": None, "adapter": "wellknown", "trust": "external",
         "requires_consent": True, "discoverable": "on-demand",
         "discoverable_basis": "registry-declaration: 需 Human 授权后才可**只读**访问（R4）"},
        {"id": "mcp.registry", "kind": "mcp", "scope": "external",
         "root": None, "adapter": "registry-json", "trust": "external",
         "requires_consent": True, "discoverable": "on-demand",
         "discoverable_basis": "registry-declaration: 官方 registry 元数据 REST API（preview）· 需授权（R4）"},
    ]
    # 其它项目根（**配置即新增来源** ⇒ 中间层核心零改动）
    for p in extra_project_roots():
        src.append({"id": "skill.project:" + os.path.basename(p.rstrip("/\\")),
                    "kind": "skill", "scope": "project",
                    "root": os.path.join(p, ".agents", "skills"), "adapter": "skill_dir",
                    "trust": "local-external-project", "requires_consent": False,
                    "discoverable": "default", "discoverable_basis": reg})
    return src


# ─────────────────────────────────────────────────────────────────────────────
# 适配器（§5.2 契约：list / describe —— 首版**不实现** search，也不需要）
# ─────────────────────────────────────────────────────────────────────────────
def parse_frontmatter(text):
    """极简 frontmatter 解析（顶层标量 / 列表）。解析失败 ⇒ 返回空 dict，**不猜**。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_raw, body = text[3:end], text[end + 4:]
    data, key = {}, None
    for line in fm_raw.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        m_item = re.match(r"^\s+-\s+(.*)$", line)
        if m_item and key:
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(m_item.group(1).strip().strip("\"'"))
            continue
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "":
            data[key] = []
        elif val.startswith("[") and val.endswith("]"):
            data[key] = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
        else:
            data[key] = val.strip("\"'")
    return data, body


def _read_text(path):
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _sha12(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]


def _axis_list(v):
    """frontmatter 的 `axis_*` 值 → 列表（支持 `[a, b]` 与单值）。"""
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if v is None:
        return []
    s = str(v).strip()
    return [s] if s else []


def search_keys_of(fm):
    """**结构化检索键**不同载体的规范不同 ⇒ **抽到什么算什么，并如实登记**。

    · `capabilities/*.md`（AI-OS 自有载体）：有 `trigger` / `keywords` / `title` / `condition` ⇒ 可被中文命中
    · `SKILL.md`（Agent Skills 规范）：只有 `name` + `description`（多为英文）⇒ **无结构化检索键**
    ⛔ **不做**跨语言翻译 / 模型补词（那会变成"工具替 Agent 定语义"）
    """
    keys = []
    for k in ("trigger", "keywords", "alias", "aliases", "condition", "title", "category"):
        v = fm.get(k)
        if isinstance(v, list):
            keys.extend(str(x) for x in v)
        elif v:
            keys.append(str(v))
    md = fm.get("metadata")
    if isinstance(md, str):
        keys.append(md)
    return keys


def role_of(kind, name, desc):
    """角色推断（§2.5 的四角色）· ⚠️ **启发式** ⇒ 输出里显式标 heuristic。"""
    blob = (name + " " + desc).lower()
    if re.search(r"test|verify|check|验证|校验|自检|门禁|gate", blob):
        return "verification"
    if kind in ("mcp", "tool"):
        return "operation"
    if kind in ("capability", "pattern", "experience"):
        return "evidence"
    return "guidance"


def _disp(path):
    """仓库相对路径；**跨盘符**（如 `C:\\Users\\…\\.agents\\skills`）⇒ 退回绝对路径（不谎报相对路径）。"""
    try:
        rel = os.path.relpath(path, AIOS_ROOT)
    except ValueError:
        rel = path
    return rel.replace("\\", "/")


def descriptor_of(source, path, fm, body):
    name = str(fm.get("name") or fm.get("rule_id") or os.path.basename(os.path.dirname(path)) or
               os.path.splitext(os.path.basename(path))[0])
    desc = fm.get("description") or fm.get("title") or fm.get("trigger") or ""
    if isinstance(desc, list):
        desc = " ".join(str(x) for x in desc)
    desc = re.sub(r"\s+", " ", str(desc)).strip()
    keys = search_keys_of(fm)
    rel = _disp(path)
    st = os.stat(path)
    kind = str(fm.get("type") or source["kind"])
    return {
        "id": source["id"] + ":" + name,
        "name": name,
        "description": desc[:240],
        "kind": kind if kind in ("skill", "capability", "pattern", "experience", "mcp", "tool") else source["kind"],
        "source": {"id": source["id"], "scope": source["scope"], "trust": source["trust"],
                   "requires_consent": source["requires_consent"]},
        "version": str(fm.get("version") or ""),
        "declared_source": str(fm.get("source") or ""),
        "local_path": rel,
        "compatibility": str(fm.get("compatibility") or ""),
        "allowed_tools": str(fm.get("allowed-tools") or fm.get("allowed_tools") or ""),
        "license": str(fm.get("license") or ""),
        "metadata": {k: v for k, v in fm.items() if k in ("metadata", "category", "rule_id")},
        "freshness": {"mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)),
                      "sha256_12": _sha12(body)},
        "body_chars": len(body),          # 🔴 正文**只出长度**，不出内容
        "search_keys": {"structured_count": len(keys), "has_structured_keys": bool(keys),
                        "sample": [k[:60] for k in keys[:3]]},
        # 🔴 读数补丁：`sample` 只留**前 3 个键 × 60 字符**，而匹配侧只读 `sample`
        #    ⇒ 第 4 个起的检索键（含新增的 `keywords`）**永远不参与匹配**。
        #    这里保留**全量**检索键供匹配使用（内部字段 `_keys_all` 不进候选输出）。
        "_keys_all": [str(k) for k in keys],
        # 「每一类能力都可以专门做一个关于自己的介绍；候选返回时直接返回它 + 位置」
        #    ⇒ 描述符带 `intro`（能力文件 frontmatter 的 `intro` 字段 · 人工写好的一句话），
        #    候选原样带给宿主；⛔ 不再由检索侧从 trigger/正文临时拼。
        "intro": str(fm.get("intro") or "").strip(),
        # **词表三维标签**（能力自报「属于哪些领域 / 哪类帮助 / 在意什么」）。
        #    检索侧 `axis_hits()` 用它做**确定性匹配**（请求带 axes 时）—— 不再靠词面猜。
        "axis_domain": _axis_list(fm.get("axis_domain")),
        "axis_help": _axis_list(fm.get("axis_help")),
        "axis_concern": _axis_list(fm.get("axis_concern")),
        # 🔴 （授权 · **只许 additive**）：
        #    `phases` = 「本能力可用在哪些阶段」（值域 `S1-决策 / S2-实现 / S3-受阻 / S4-收口`，可多选）。
        #    检索侧（`_retrieval_request_probe.py`）用它做**阶段过滤**；**缺字段 = 无限制**（向后兼容老文件）。
        #    ⚠️ 只增字段：既有字段名/语义/顺序一律不动（`_axis_list` 同时容错 `[a, b]` 与裸逗号串）。
        "phases": _axis_list(fm.get("phases")),
        "role": role_of(source["kind"], name, desc),
    }


def list_source(source):
    """→ (descriptors, unavailable_reason, read_failures)。

    目录不存在 ⇒ 如实返回 `root-not-found`（⛔ 不静默跳过）；读取失败计数 > 0 ⇒ 该来源记为 `error`。
    """
    root = source["root"]
    if root is None:
        return [], "no-root-declared", 0
    if not os.path.isdir(root):
        return [], "root-not-found", 0
    out, failures = [], 0
    if source["adapter"] == "md_frontmatter":
        # ① 一级 `*.md` —— 排除 `INDEX.md` / `README.md`（导航文件，无 frontmatter ⇒ 无检索键）
        for name in sorted(os.listdir(root)):
            if not name.endswith(".md") or name.lower() in GENERIC_MD_NAMES:
                continue
            path = os.path.join(root, name)
            raw = _read_text(path)
            if raw == "":
                failures += 1
                continue
            fm, body = parse_frontmatter(raw)
            if not fm:
                continue  # 无 frontmatter ⇒ 无结构化检索键，跳过（⛔ 不当成读取失败）
            out.append(descriptor_of(source, path, fm, body))
        # ② 子目录 `<name>/SKILL.md`（Agent Skills 规范形态）
        #    🔴 读数补丁：原实现只扫一级文件 ⇒ `某个归档 skill 包（未随发布）`
        #    **完全不在语料里**（该归档包因此结构性不可被发现，只能从 evolution/intake 的副本命中）。
        for name in sorted(os.listdir(root)):
            sub = os.path.join(root, name)
            if not os.path.isdir(sub):
                continue
            skill = os.path.join(sub, "SKILL.md")
            if not os.path.isfile(skill):
                continue
            # 若存在同级「入口卡」`<name>.md` ⇒ 以入口卡为**唯一发现入口**，跳过 SKILL.md
            #    （否则同一能力会以两份描述符出现：SKILL.md 只有英文 name/description、且无法承载 `intro`）
            if os.path.isfile(os.path.join(root, name + ".md")):
                continue
            raw = _read_text(skill)
            if raw == "":
                failures += 1
                continue
            fm, body = parse_frontmatter(raw)
            out.append(descriptor_of(source, skill, fm, body))
    else:  # skill_dir：`<name>/SKILL.md`
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name, "SKILL.md")
            if not os.path.isfile(path):
                continue
            raw = _read_text(path)
            if raw == "":
                failures += 1
                continue
            fm, body = parse_frontmatter(raw)
            out.append(descriptor_of(source, path, fm, body))
    return out, None, failures


# ─────────────────────────────────────────────────────────────────────────────
# 请求处理（§4.1）· 弱排序信号 + 证据（§6.3）· 候选集合与关系（§6.3b）
# ─────────────────────────────────────────────────────────────────────────────
# 🔴 **缺失三态**（限制 1 · 设计 §4.1 / 验收）
CTX_STATES = ("provided", "known-absent", "unknown")


def ctx_item(v):
    """上下文项 → 三态。裸值视为 `provided`（**向后兼容旧样本** · 并如实标注 `legacy_bare_value`）。"""
    if isinstance(v, dict) and "state" in v:
        st = str(v.get("state"))
        if st not in CTX_STATES:
            return {"state": "invalid", "value": v.get("value"), "origin": v.get("origin", "agent")}
        return {"state": st, "value": v.get("value"), "origin": v.get("origin", "agent")}
    if v is None:
        return {"state": "not-stated", "value": None, "origin": "agent"}   # ⛔ 不猜成 unknown
    return {"state": "provided", "value": v, "origin": "agent", "legacy_bare_value": True}


def ctx_value(v):
    it = ctx_item(v)
    return it["value"] if it["state"] == "provided" else None


def request_echo(req):
    """🔴 **仅标识与三态 · 不回显任何原文**（`CandidateSet` 边界 · §5.3）。"""
    wc = req.get("work_context") or {}
    items = {}
    for k in ("intent_now", "last_action", "last_result", "open_items", "corrections", "focus_paths"):
        if k in wc:
            it = ctx_item(wc[k])
            val = it["value"]
            items[k] = {"state": it["state"], "origin": it.get("origin"),
                        "chars": len(str(val)) if val is not None else 0,
                        "legacy_bare_value": bool(it.get("legacy_bare_value"))}
    return {"request_id": req.get("request_id"),
            "need_chars": len(str(req.get("need") or "")),
            "search_terms_count": len(req.get("search_terms") or []),
            "roles_needed": req.get("roles_needed") or [],
            "sources_requested": req.get("sources") or [],
            "context_items": items,
            "note": "仅标识与三态 · **不回显任何原文**"}


def validate_request(req):
    """Runtime 的**机械职责**之一：请求格式校验（限制 2 ①）—— 非法 ⇒ 明确报错，⛔ 不猜。"""
    errs = []
    if not str(req.get("need") or "").strip():
        errs.append({"code": "need-required", "detail": "need 不得为空（Agent 必须自己写出需求）"})
    wc = req.get("work_context") or {}
    for k, v in wc.items():
        it = ctx_item(v)
        if it["state"] == "not-stated":
            errs.append({"code": "ctx-item-missing-state", "field": k,
                         "detail": "协议要求三态之一（provided/known-absent/unknown）；缺失**不等于** unknown"})
        elif it["state"] == "invalid":
            errs.append({"code": "ctx-item-bad-state", "field": k,
                         "detail": "state 必须是 " + "|".join(CTX_STATES)})
    return errs


def request_tokens(req):
    parts = [str(req.get("need") or ""), str(req.get("why_now") or "")]
    # 🔴 `search_terms`：**由 Agent 自己给出**的检索键（可多语言 / 可同义）——
    #    ⛔ 不是工具猜的语义结论；缺省即不使用（工具不得替 Agent 补词）
    st = req.get("search_terms")
    if isinstance(st, list):
        parts.extend(str(x) for x in st)
    elif st:
        parts.append(str(st))
    wc = req.get("work_context") or {}
    for k in ("intent_now", "corrections", "open_items", "focus_paths", "last_action", "last_result"):
        v = ctx_value(wc.get(k))
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif isinstance(v, dict):
            parts.extend(str(x) for x in v.values())
        elif v:
            parts.append(str(v))
    return ep.tokenize(" ".join(parts))


def norm_name(n):
    n = n.lower().replace("_", "-")
    for pre in ("dsh-", "aios-"):
        if n.startswith(pre):
            n = n[len(pre):]
    return n


def desc_tokens(d):
    return ep.tokenize(d.get("description") or "")


def discover(descriptors, req, top_k):
    qt = request_tokens(req)
    scored = []
    for d in descriptors:
        if req.get("kinds") and d["kind"] not in req["kinds"] and "all" not in req["kinds"]:
            continue
        blob = d["name"] + " " + (d.get("description") or "") + " " + \
               " ".join(d["search_keys"]["sample"])
        hits = sorted(t for t in ep.tokenize(blob) if t in qt and ep.is_meaningful(t))
        ev = []
        if hits:
            ev.append({"kind": "field-match", "detail": "name/description ∩ need = " + ",".join(hits[:8]),
                       "at": int(time.time())})
        if d.get("declared_source"):
            ev.append({"kind": "source-declaration", "detail": d["declared_source"][:120],
                       "at": int(time.time())})
        ev.append({"kind": "freshness", "detail": d["freshness"]["mtime"] + " · " + d["freshness"]["sha256_12"],
                   "at": int(time.time())})
        scored.append((len(hits), d, ev, hits))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    picked = [s for s in scored if s[0] > 0][:top_k] or scored[:min(top_k, 3)]
    return qt, picked


def build_relations(picked, roles_needed=None):
    """§6.3b（收敛后）：`alternative` = 机械判据；`complementary` = **仅由 Agent 声明的角色触发**。

    🔴 **M4 收敛条件**（修正 §11.1 的 R-2"过宽 ⇒ 噪声"）：
       · 默认（请求**未**声明 `roles_needed`）⇒ **不输出任何 `complementary`**（工具不得替 Agent 猜互补）
       · 声明后 ⇒ 只在**声明角色之间**做分组配对，每组各取 weak-signal 前 2 ⇒ 关系数有界
       · `dependency` 需来源侧 `requires` 证据（`SKILL.md` 规范无此字段）· `conflict` **未实现**
    """
    rels = []
    for i in range(len(picked)):
        for j in range(i + 1, len(picked)):
            a, b = picked[i][1], picked[j][1]
            na, nb = norm_name(a["name"]), norm_name(b["name"])
            if na and na == nb:
                rels.append({"from": a["id"], "to": b["id"], "type": "alternative",
                             "basis": "normalized-name-equal(%s)" % na, "confidence": "mechanical"})
                continue
            ta, tb = desc_tokens(a), desc_tokens(b)
            if ta and tb:
                jac = len(ta & tb) / float(len(ta | tb))
                if jac >= 0.5:
                    rels.append({"from": a["id"], "to": b["id"], "type": "alternative",
                                 "basis": "description-jaccard=%.2f" % jac, "confidence": "mechanical"})
    if roles_needed:
        groups = {}
        for n, d, _ev, _h in picked:
            if d["role"] in roles_needed:
                groups.setdefault(d["role"], []).append((n, d))
        order = [r for r in roles_needed if r in groups]
        for i in range(len(order)):
            for j in range(i + 1, len(order)):
                left = sorted(groups[order[i]], key=lambda x: -x[0])[:2]
                right = sorted(groups[order[j]], key=lambda x: -x[0])[:2]
                for _na, da in left:
                    for _nb, db in right:
                        rels.append({"from": da["id"], "to": db["id"], "type": "complementary",
                                     "basis": "declared-role-pair(%s/%s)" % (order[i], order[j]),
                                     "confidence": "declared-role"})
    return rels[:24]


def candidate_set(picked, req, top_k):
    cands = []
    for n, d, ev, hits in picked:
        item = dict(d)
        item["evidence"] = ev
        item["weak_signal"] = {"hit_count": n, "hits": hits[:8]}
        cands.append(item)
    roles, srcs, groups = {}, {}, {}
    for c in cands:
        roles[c["role"]] = roles.get(c["role"], 0) + 1
        srcs[c["source"]["id"]] = srcs.get(c["source"]["id"], 0) + 1
        groups.setdefault(norm_name(c["name"]), []).append(c["id"])
    dup = {k: v for k, v in groups.items() if len(v) > 1}
    roles_needed = req.get("roles_needed") or []
    return {
        "request_id": req.get("request_id") or "req",
        "ordering": "weak-signal(hit-count) · **非权威** · 仅供排序参考（C2/P0）",
        "request_echo": request_echo(req),   # 🔴 仅标识与三态 · 无原文（U1 §5.3）
        "candidates": cands,
        "relations": build_relations(picked, roles_needed),
        "role_groups": ({r: [c["id"] for c in cands if c["role"] == r] for r in roles_needed}
                        if roles_needed else {}),
        "diversity": {"roles": roles, "sources": srcs, "duplicate_groups": dup,
                      "candidate_count": len(cands),
                      "sources_represented": len(srcs)},
        "notes": [
            "⛔ 不以唯一最高分候选为终点（P0）；候选未按单一分数截断为 1",
            "`complementary` **默认不输出** —— 仅在请求声明 `roles_needed` 时按声明角色配对（M4）",
            "conflict 判据**首版未实现**（如实标 unimplemented）",
        ],
        "unimplemented": ["conflict-relation", "dependency-relation(需来源侧 requires 证据)"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# §7.1 迭代：第二轮与第一轮的差异（证明"不被首次结果锁死"）
# ─────────────────────────────────────────────────────────────────────────────
def iterate(descriptors, first_req, follow_req, top_k):
    _, p1 = discover(descriptors, first_req, top_k)
    _, p2 = discover(descriptors, follow_req, top_k)
    s1 = {d["id"] for _, d, _, _ in p1}
    s2 = {d["id"] for _, d, _, _ in p2}
    return {"added": sorted(s2 - s1), "removed": sorted(s1 - s2), "kept": sorted(s1 & s2),
            "round1_count": len(s1), "round2_count": len(s2)}


# ─────────────────────────────────────────────────────────────────────────────
# 零副作用自检
# ─────────────────────────────────────────────────────────────────────────────
def readonly_selfcheck():
    src = _read_text(HERE_ABS)
    hits = [p for p in SELFCHECK_FORBIDDEN if re.search(p, src)]
    return {"source_forbidden_patterns": hits, "pass": not hits,
            "note": "源码级护栏（沿用回放工具做法）· 运行期不写文件 / 不联网 / 不 subprocess"}


def run(payload, top_k):
    t0 = time.time()
    req = payload.get("request") or payload
    sources = build_sources()
    requested = set(req.get("sources") or [])
    descriptors, status = [], []

    # ── 🔴 来源可达性状态机（§5.2）：每个来源**恰好一个**状态 + 依据 ──
    for s in sources:
        rec = {"id": s["id"], "kind": s["kind"], "scope": s["scope"],
               "discoverable": s.get("discoverable", "default"),
               "basis": s.get("discoverable_basis", "registry-declaration"),
               "descriptors": 0, "matched": 0}
        if s.get("requires_consent"):
            rec.update(status="unavailable", reason="requires-consent",
                       detail="需 Human 单独授权后才可只读访问（R4 边界 · 本轮**未触碰网络**）")
        elif s.get("discoverable") == "excluded":
            rec.update(status="excluded", reason="by-design",
                       detail="按来源声明不进默认发现（协议支持 · ⚠️ 本机暂无实例）")
        elif s.get("discoverable") == "on-demand" and rec["id"] not in requested:
            rec.update(status="skipped", reason="on-demand-not-requested",
                       detail="来源自述需**显式点名**（`request.sources`）；本次请求未点名")
        else:
            items, why, failures = list_source(s)
            rec["root"] = str(s["root"]).replace("\\", "/") if s["root"] else None
            if why is not None:
                rec.update(status="configured-unreachable", reason=why,
                           detail="已配置但**不可访问**（⛔ 不得读成 `queried-zero`）")
            elif failures > 0:
                rec.update(status="error", reason="read-failures", descriptors=len(items),
                           detail="%d 个文件读取失败（⛔ 与 `queried-zero` **严格分开**）" % failures)
                descriptors.extend(items)
            else:
                rec.update(status="queried-pending", descriptors=len(items))
                descriptors.extend(items)
        status.append(rec)

    _qt, picked = discover(descriptors, req, top_k)
    cs = candidate_set(picked, req, top_k)
    matched_ids = {c["id"] for c in cs["candidates"]}
    counts = {}
    for d in descriptors:
        sid = d["source"]["id"]
        if d["id"] in matched_ids:
            counts[sid] = counts.get(sid, 0) + 1
    for rec in status:
        if rec["status"] == "queried-pending":
            rec["matched"] = counts.get(rec["id"], 0)
            rec["status"] = "queried-matched" if rec["matched"] > 0 else "queried-zero"
        elif rec["status"] == "error":
            rec["matched"] = counts.get(rec["id"], 0)

    out = {
        "ok": True,
        "capability_request_echo": request_echo(req),      # 🔴 仅标识与三态 · 无原文
        "request_errors": validate_request(req),           # 🔴 Runtime 机械职责 ①：格式校验
        "candidate_set": cs,
        "source_status": status,                           # 🔴 E4：每来源恰好一个状态 + 依据
        "source_coverage": [{"id": r["id"], "status": r["status"], "descriptors": r["descriptors"],
                             "matched": r["matched"]} for r in status],
        "descriptor_total": len(descriptors),
        "readonly_selfcheck": readonly_selfcheck(),
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
    # 🔴 **目录浏览回退**（/）：Agent 显式要求时，按来源列出 catalog（Tier 1：name + role + path）
    #    理由：零命中时 Agent 需要知道"**有哪些能力存在**"，而不是只看到"没有候选"
    if req.get("browse_sources"):
        cat = {}
        for d in descriptors:
            cat.setdefault(d["source"]["id"], []).append(
                {"name": d["name"], "role": d["role"], "path": d["local_path"]})
        out["catalog"] = {k: v[:12] for k, v in cat.items()}
    if payload.get("follow_up"):
        out["iteration"] = iterate(descriptors, req, payload["follow_up"], top_k)
        # 🔴 **M3 闭环判据（修正后）**：第二轮是否让第一轮**真零命中**（`queried-zero`）的来源进入候选 ——
        #    ⛔ `excluded` / `skipped` / `unavailable` / `configured-unreachable` / `error` **不计入**零命中
        zero = [r["id"] for r in status if r["status"] == "queried-zero"]
        _n2, p2 = discover(descriptors, payload["follow_up"], top_k)
        src2 = {d["source"]["id"] for _n, d, _e, _h in p2}
        closed = sorted(s for s in zero if s in src2)
        out["fallback_loop"] = {
            "zero_sources_round1": zero,
            "not_counted_as_zero": sorted(
                r["id"] for r in status
                if r["status"] in ("excluded", "skipped", "unavailable", "configured-unreachable", "error")),
            "catalog_available": "catalog" in out,
            "round2_sources": sorted(src2),
            "closed_sources": closed,
            "closed": bool(closed),
        }
    return out


def selftest():
    ok = []

    def check(name, cond):
        ok.append((name, bool(cond)))

    fm, body = parse_frontmatter("---\nname: x-y\ndescription: a b\nversion: 1.0.0\ntrigger:\n  - one\n---\nBODY")
    check("frontmatter-scalar", fm.get("name") == "x-y" and fm.get("version") == "1.0.0")
    check("frontmatter-list", fm.get("trigger") == ["one"])
    check("frontmatter-body", body.strip() == "BODY")
    check("norm-name-merge", norm_name("dsh-prose-standard") == norm_name("prose_standard"))
    check("role-verification", role_of("skill", "dsh-pre-push-checks", "checks") == "verification")
    check("role-evidence", role_of("capability", "doc_standards", "标准") == "evidence")
    check("readonly-source", readonly_selfcheck()["pass"] is True)
    srcs = build_sources()
    check("source-registry", len(srcs) >= 5 and all("root" in s for s in srcs))
    payload = {"request": {"need": "评审并精简中文技术文档的散文与注释标准", "kinds": ["all"]},
               "follow_up": {"need": "提交前做证据门禁与自检流程", "kinds": ["all"]}}
    res = run(payload, 6)
    check("p0-candidate-set", len(res["candidate_set"]["candidates"]) > 1)
    check("relations-key", isinstance(res["candidate_set"]["relations"], list))
    check("iteration-present", "iteration" in res and res["iteration"]["round2_count"] > 0)
    check("no-body-leak", all("body_chars" in c and "body" not in c for c in res["candidate_set"]["candidates"]))
    check("m2-structured-keys",
          any(c["search_keys"]["has_structured_keys"] for c in res["candidate_set"]["candidates"]))
    check("m3-source-coverage",
          all(("matched" in s and "descriptors" in s) for s in res["source_coverage"]))
    comp = [r for r in res["candidate_set"]["relations"] if r["type"] == "complementary"]
    check("m4-default-no-complementary", comp == [])
    res2 = run({"request": {"need": "评审并精简中文技术文档的散文与注释标准", "kinds": ["all"],
                            "roles_needed": ["evidence", "verification"]}}, 6)
    comp2 = [r for r in res2["candidate_set"]["relations"] if r["type"] == "complementary"]
    check("m4-declared-complementary",
          len(comp2) > 0 and all(r["confidence"] == "declared-role" for r in comp2) and len(comp2) <= 4)
    check("m4-role-groups", "evidence" in res2["candidate_set"]["role_groups"])
    res3 = run({"request": {"need": "编写与评审一份中文技术设计文档（散文与注释标准）", "kinds": ["all"],
                            "browse_sources": True},
                "follow_up": {"need": "编写与评审一份中文技术设计文档（散文与注释标准）", "kinds": ["all"],
                              "search_terms": ["prose", "standard", "documentation", "comments",
                                               "writing", "review", "trim"]}}, 8)
    check("m3-fallback-loop-closed", res3["fallback_loop"]["closed"] is True
          and res3["fallback_loop"]["catalog_available"] is True)
    check("m3-zero-sources-reported", len(res3["fallback_loop"]["zero_sources_round1"]) > 0)

    # ── 来源可达性状态机 + 缺失三态 + 请求校验（落实后的断言）──
    # 🔴 后两个 `.agents/skills` 来源已按协议**显式 excluded**（目录不存在），
    #    ⇒ 真实环境不再有 `configured-unreachable` 实例。判据**不再依赖"本机刚好缺某个目录"**
    #    （教训：判据依赖文件布局 ⇒ 环境一变就静默失效）；改为**合成一个不可达来源**验证该分支。
    _real_build = build_sources

    def _with_unreachable():
        s = _real_build()
        s.append({"id": "selftest.unreachable", "kind": "skill", "scope": "project",
                  "root": os.path.join(AIOS_ROOT, ".aios", "__selftest_missing__"),
                  "adapter": "skill_dir", "trust": "local", "requires_consent": False,
                  "discoverable": "default", "discoverable_basis": "selftest"})
        return s

    globals()["build_sources"] = _with_unreachable
    try:
        res_u = run(payload, 6)
    finally:
        globals()["build_sources"] = _real_build
    st = {r["status"] for r in res_u["source_status"]}
    check("e4-status-machine",
          {"queried-matched", "queried-zero", "configured-unreachable", "skipped",
           "unavailable", "excluded"}.issubset(st))
    check("e4-consent-not-zero",
          all(r["status"] != "queried-zero" for r in res["source_status"]
              if r["id"].startswith(("skill.wellknown", "mcp."))))
    check("e4-on-demand-not-zero",
          "skill.maintenance" in res["fallback_loop"]["not_counted_as_zero"]
          and "skill.maintenance" not in res["fallback_loop"]["zero_sources_round1"])
    check("e4-unreachable-not-zero",
          "selftest.unreachable" in res_u["fallback_loop"]["not_counted_as_zero"])
    check("e4-excluded-source",
          all({r["id"]: r["status"] for r in res["source_status"]}.get(x) == "excluded"
              for x in ("skill.project:AI-os", "skill.user")))
    r5 = run({"request": {"need": "测试三态标注", "work_context": {
        "intent_now": {"state": "provided", "value": "x"},
        "open_items": {"state": "unknown"},
        "corrections": {"state": "known-absent", "value": []}}}}, 3)
    echo = r5["capability_request_echo"]["context_items"]
    check("ctx-three-state", echo["intent_now"]["state"] == "provided"
          and echo["open_items"]["state"] == "unknown"
          and echo["corrections"]["state"] == "known-absent")
    check("request-echo-no-原文",
          all(k in ("state", "origin", "chars", "legacy_bare_value")
              for v in echo.values() for k in v))
    r6 = run({"request": {"need": "", "work_context": {"something": None}}}, 3)
    codes = {e["code"] for e in r6["request_errors"]}
    check("request-validation", "need-required" in codes and "ctx-item-missing-state" in codes)
    failed = [n for n, c in ok if not c]
    print(json.dumps({"selftest": {"total": len(ok), "passed": len(ok) - len(failed), "failed": failed}},
                     ensure_ascii=False))
    return 0 if not failed else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    top_k = 6
    for a in sys.argv[1:]:
        if a.startswith("--top="):
            top_k = int(a.split("=", 1)[1])
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig") or "{}")
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": "bad-input", "detail": str(exc)[:80]}) + "\n")
        return 2
    sys.stdout.write(json.dumps(run(payload, top_k), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
