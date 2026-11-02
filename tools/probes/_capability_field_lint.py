#!/usr/bin/env python3
"""能力 frontmatter 字段核对（只读 · T1a 的机械检查）。

背景（`task_cards/memory/TODO.md` T1a）：
  「所有能力都有对应的词」—— 能力要能被检索到，必须先有**词**：
    · `keywords`   —— 词面通道（`search_keys_of()` 读 trigger/keywords/…）
    · `axis_domain / axis_help / axis_concern` —— 三维标签通道（`axis_hits()`）
  读数：16/16 有 axis_*，但 keywords 只 10/16 ⇒ 那份盘点靠人眼。
  本脚本把那次盘点**机械化**：新增能力 / 改动 frontmatter 后跑一次即可。

判据（缺一即 FAIL）：
  1. `name` 非空  2. `intro` 非空  3. `axis_domain/axis_help/axis_concern` 均非空
  4. `keywords` 非空（**本脚本的 T1a 新判据**）
  5. 各轴取值必须来自 `task_cards/NEEDS-VOCAB.md` 的值域（仅告警 WARN，不判 FAIL —— 词表可能演进）
  6. `phases` 存在、是 **list**（行内 `[a, b]` 或块式 `- a`）、非空、取值 ∈ `S1-决策 / S2-实现 /
     S3-受阻 / S4-收口`（**本脚本的 新判据**：17/17 已补但校验器此前不认 ⇒ 下次漏字段无人报）
  7. `parts`（片级化 · 试点 + 全量 · D-056）——**有则严格、无则只 WARN**（向后兼容）：
     · 有 `parts` ⇒ 严格校验：`class` ∈ {决策, 实现, 收尾} · `domain` ∈ 9 值
       （8 个词表领域 + `通用`）· `id` 全局唯一且形如 `<能力名>#<短名>` ·
       `one_line` ≤45 字且含"做"类动词 · `sec` 非空且**指向正文真实存在的章节片段**
       （`节号 · 标题片段`）· 片数 2–4
     · 无 `parts` ⇒ WARN（`待补片`），⛔ 不判 FAIL —— 17 个存量能力已在 全量补片；
       新增能力在补片前仍走这条 WARN

退出码：0 = 全部通过（可有 WARN）· 1 = 存在 FAIL。

用法：
  python tools/probes/_capability_field_lint.py
  python tools/probes/_capability_field_lint.py --root <repo>   # 隔离自测
"""
import argparse
import os
import re
import sys

# ⚠️ `CELLS.md` 也跳过：它不是能力文件（没有 frontmatter），而是 **格能力装配表**，
#    由本脚本下面的 `cells_of()` 单独校验 —— 若混进逐文件校验会因"缺 name/intro/..."被误判。
SKIP = {"INDEX.md", "README.md", "AXES-MAP.md", "CELLS.md"}
AXIS_FIELDS = ("axis_domain", "axis_help", "axis_concern")
REQUIRED = ("name", "intro") + AXIS_FIELDS + ("keywords",)
# `phases` 值域（与 `_capability_discovery_probe.py` / `_retrieval_request_probe.py` 的
# 阶段过滤同源 —— 那边是**前缀容错**（S1 ↔ S1-决策），这里**只认全称**：规范形态一个就够）。
PHASE_VALUES = ("S1-决策", "S2-实现", "S3-受阻", "S4-收口")

# 片级化（试点 + 全量 · D-056）：`parts:` 块 = 整包内**可独立定位/装配**的段，按 class × domain 双轴定位。
# 值域：class 是流程三分类；domain = 8 个词表领域（`task_cards/NEEDS-VOCAB.md` 同源）+ `通用`。
# 🔴 `通用`（新增）**不是词表领域，是「注入范围标记」**：做法换个领域仍成立的能力片标它，
#    任何领域任务都可选中；统计时**单列、不占 24 个领域格**（矩阵脚本 `--json` 里 `universal_parts`）。
#    ⛔ 不因为多了这个标记就放宽其它校验：class/label/one_line/sec/片数判据一条不少。
PART_CLASS_VALUES = ("决策", "实现", "收尾")
PART_DOMAIN_VALUES = ("前端", "后端", "数据", "文档", "产品", "环境·运维", "求职·职业", "AI-OS 自身", "通用")
# 🔴 格能力装配表（`capabilities/CELLS.md`）：一格 = 一个 (class, domain) 装配单，
#    按「阶段 + 领域」命中 ⇒ 渲染该格的片（不是把整包能力全丢过去）。判据（缺一即 FAIL）：
#      · cell id 形态 = `<domain>/<class>` 且与两列一致（runtime 的探针键同形）
#      · class/domain 在既有值域内；domain ⛔ 不能是 `通用`（通用片只作为**引用**出现在第 5 列）
#      · 引用的片 id **必须真实存在**（跨全部能力 frontmatter 的 `parts[].id`）
#      · 格内片总数 = 领域片 + 通用片 ≤ 3；通用片引用 ≤ 2；至少 1 片
#      · ⛔ 不跨类引用：片自己的 `class` 必须等于该格的 class（收尾片不进决策格）
#      · 领域片的 `domain` 必须等于该格 domain；通用片的 `domain` 必须是 `通用`
#      · `when`（这格什么时候用）非空 —— 没有用途说明的格 = 没筛过
CELL_UNIVERSAL_MAX = 2
CELL_PARTS_MAX = 3
UNIVERSAL_DOMAIN = "通用"

PART_MIN, PART_MAX = 2, 4               # 每个能力 2–4 片（太少 = 没拆，太多 = 该融合）
PART_MAX_ONE_LINE = 45                  # `one_line` 一句可执行的上限
# "做"类动词（启发式词表）：判据是「这句在说**照做什么**」而不是「这个能力是什么」。
# 词表不可能穷尽 ⇒ 宁可宽；FAIL 消息直接点名该改写成祈使句。
PART_ACTION_TOKENS = (
    "做", "定", "写", "跑", "看", "读", "走", "判", "按", "用", "逐", "切", "核", "对",
    "过", "取", "给", "列", "选", "改", "收", "拆", "查", "建", "立", "落", "记", "算",
    "标", "填", "勾", "调", "验", "复", "装", "配", "删", "加", "开", "清", "分", "合",
    "汇", "报", "交", "发", "提", "补", "留", "比", "排", "回", "答", "问", "试",
)


def read_text(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    return m.group(1) if m else ""


def body_text(text):
    """去掉 frontmatter 的正文 —— `sec` 存在性只能对**正文**判（否则 sec 自己就在 fm 里，永远"存在"）。"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    return text[m.end():] if m else text


def list_value(fm, key):
    """frontmatter 里的标量 / 行内 `[a, b]` / **块式** `- a` 列表 ⇒ list[str]（读不到 ⇒ []）。

    🔴 块式必须支持：现有能力的 `keywords` / `trigger` 多为
        keywords:
          - 调试
          - 报错
    （只认行内数组会把**已有的** keywords 误判成缺失 ⇒ 修）。
    """
    m = re.search(r"^" + re.escape(key) + r"[ \t]*:[ \t]*(.*)$", fm, re.M)
    if not m:
        return []
    raw = m.group(1).strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [x.strip().strip("'\"") for x in raw[1:-1].split(",") if x.strip()]
    if raw:
        return [raw.strip().strip("'\"")]
    out = []
    for line in fm[m.end():].split("\n"):
        if re.match(r"^[A-Za-z_][\w-]*\s*:", line):
            break  # 下一个 frontmatter 键 ⇒ 块结束
        ls = line.strip()
        if ls == "":
            continue
        if ls.startswith("- "):
            out.append(ls[2:].strip().strip("'\""))
        # 续行（缩进但无 `- `）⇒ 跳过（属于上一项的展开，不单独计数）
    return out


def phases_problem(fm):
    """`phases` 校验 ⇒ 问题串（供 FAIL 明细）· 合法 ⇒ None。

    四种问题各有独立串（供人一眼分辨是**哪种**漂移）：
      · `phases(缺失)`          —— frontmatter 里没有这个键
      · `phases(空)`            —— 键在但无数值（`[]` / 空块）⇒ 等于没声明
      · `phases(非list:字符串)` —— 写了标量（`S2-实现` 或裸逗号串 `S2-实现, S3-受阻`）
      · `phases(值域外:X)`      —— 取值不在 `PHASE_VALUES` 里

    形态口径：**行内数组与块式序列都算 list**（二者 YAML 语义等价，且 `_axis_list()` 两种都读得出）；
    标量不算 —— 检索侧虽容错裸逗号串，但**规范形态只认 list**（ 明确要求）。
    """
    m = re.search(r"^phases[ \t]*:[ \t]*(.*)$", fm, re.M)
    if not m:
        return "phases(缺失)"
    raw = m.group(1).strip()
    # ⚠️ 冒号后空白只许 `[ \t]*`（`\s*` 会跨行吞掉块式列表首项）
    if raw and not (raw.startswith("[") and raw.endswith("]")):
        return "phases(非list:字符串)"
    vals = list_value(fm, "phases")
    if not vals:
        return "phases(空)"
    bad = [v for v in vals if v not in PHASE_VALUES]
    if bad:
        return "phases(值域外:" + ",".join(bad) + ")"
    return None


def parts_of(fm):
    """`parts:` 块 ⇒ (list[dict], 问题串 | None)。

    无该键 ⇒ `([], None)`（调用方判「 待补片」WARN，⛔ 不判 FAIL —— 向后兼容）。
    有键但形态不对 ⇒ `(list, 问题串)` ⇒ FAIL。只认块式 list-of-map（YAML 里就是 list[dict]）：

        parts:
          - id: frontend-ui#tokens
            class: 决策

    行内 `[]` / 标量一律算形态问题：片表要能带 6 个字段，压成一个字符串必然丢字段。
    """
    m = re.search(r"^parts[ \t]*:(.*)$", fm, re.M)
    if not m:
        return [], None
    if m.group(1).strip():
        return [], "parts(非块式列表)"
    entries, cur = [], None
    for line in fm[m.end():].split("\n"):
        if re.match(r"^[A-Za-z_][\w-]*\s*:", line):
            break                                   # 下一个 frontmatter 顶层键 ⇒ 块结束
        ls = line.strip()
        if not ls:
            continue
        if ls.startswith("- "):
            cur = {}
            entries.append(cur)
            body = ls[2:].strip()
            if body:
                _kv(cur, body)
        elif cur is not None:
            _kv(cur, ls)
        # 片条目之间的自由注释行（不以 `- ` 开头）⇒ 归到当前片，键名乱就解析不出来，交给字段校验
    if not entries:
        return [], "parts(空)"
    return entries, None


def _kv(entry, line):
    """`key: value` ⇒ entry[key] = value（去掉引号；只切第一个 ASCII 冒号）。"""
    k, sep, v = line.partition(":")
    if not sep:
        return
    entry[k.strip()] = v.strip().strip("'\"")


def parts_problems(entries, fname, all_ids, text):
    """片块**严格**校验 ⇒ 问题串 list（空 = 通过）。

    `all_ids`: 跨全部能力的 id → [文件名...]（唯一性判据）；`text`: 整篇正文（`sec` 存在性判据）。
    """
    out = []
    stem = fname[:-3] if fname.endswith(".md") else fname
    # 🔴 约定一个领域一个文件（`domain-*.md`），片**不含 class**（领域是唯一分类轴）
    #   ⇒ 域能力放宽：片数 1–10 · class 可缺省（有则仍须合法）· sec 可缺省（改由 `from:` 追溯出处）
    is_dom = stem.startswith("domain-")
    if is_dom:
        if not (1 <= len(entries) <= 10):
            out.append("parts(片数:%d,应1-10)" % len(entries))
    elif not (PART_MIN <= len(entries) <= PART_MAX):
        out.append("parts(片数:%d,应2-4)" % len(entries))
    seen = set()
    for i, p in enumerate(entries, 1):
        pid = p.get("id", "").strip()
        tag = pid or ("第%d片" % i)
        # id：存在 · 形态 `<能力名>#<短名>` · 跨能力唯一 · 本能力内不重复
        if not pid:
            out.append("parts(id缺失:第%d片)" % i)
        elif len(all_ids.get(pid, [])) > 1:
            out.append("parts(id跨能力重复:%s)" % pid)      # 硬判据：全局唯一（先于形态判）
        elif pid in seen:
            out.append("parts(id重复:%s)" % pid)
        elif not re.match(r"^" + re.escape(stem) + r"#[^#\s]+$", pid):
            out.append("parts(id形态:%s)" % pid)
        seen.add(pid)
        cls = p.get("class", "").strip()
        if not cls:
            if not is_dom:
                out.append("parts(class空:%s)" % tag)
        elif cls not in PART_CLASS_VALUES:
            out.append("parts(class值域外:%s:%s)" % (tag, cls))
        dom = p.get("domain", "").strip()
        if not dom:
            out.append("parts(domain空:%s)" % tag)
        elif dom not in PART_DOMAIN_VALUES:
            out.append("parts(domain值域外:%s:%s)" % (tag, dom))
        if not p.get("label", "").strip():
            out.append("parts(label空:%s)" % tag)
        ol = p.get("one_line", "").strip()
        if not ol:
            out.append("parts(one_line空:%s)" % tag)
        else:
            if len(ol) > PART_MAX_ONE_LINE:
                out.append("parts(one_line超长:%s:%d字)" % (tag, len(ol)))
            if not any(t in ol for t in PART_ACTION_TOKENS):
                out.append("parts(one_line无动作词:%s)" % tag)
        sec = p.get("sec", "").strip()
        if not sec:
            if not is_dom:
                out.append("parts(sec空:%s)" % tag)
        else:
            frag = sec.rsplit("·", 1)[-1].strip()
            if frag and frag not in text:
                out.append("parts(sec不存在:%s:%s)" % (tag, frag))
        # 片句互不重复（同一能力内）：完全相同就算重复（近义重复由矩阵脚本的相似度负责）。
    # 只回显片 id（ASCII）不回显 one_line —— 控制台可能是 GBK，one_line 里可能有 GBK 编不出的符号。
    by_line = {}
    for p in entries:
        ol = p.get("one_line", "").strip()
        if ol:
            by_line.setdefault(ol, []).append(p.get("id", "").strip() or "?")
    for ids in by_line.values():
        if len(ids) > 1:
            out.append("parts(one_line重复:%s)" % ",".join(ids))
    return out


def _short(s, n=24):
    """截断到 n 字（只用于错误串；控制台可能 GBK，⛔ 不加 emoji）。"""
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "..."


CELL_EMPTY_TOKENS = {"-", "—", "无", "（无）", "(无)", "空", "none", "N/A", "n/a"}


def split_cell_ids(cell):
    """装配表格子里的片 id 列表 ⇒ list[str]。

    只认逗号 / 顿号 / 分号 / 空格分隔（本表由人写，⛔ 不做 YAML 解析）；
    占位符（`-` / `—` / `无` / `（无）`）⇒ 空列表。
    """
    if cell is None:
        return []
    out = []
    for x in re.split(r"[,，、;；\s]+", cell.strip()):
        s = x.strip().strip("`").strip()
        if s and s not in CELL_EMPTY_TOKENS:
            out.append(s)
    return out


def cells_of(text):
    """`capabilities/CELLS.md` 的装配表 ⇒ (list[dict], 问题串 list)。

    **只读第一个表格块**（表格行连续出现的那一段）：CELLS.md 的 §三/§四 还有别的表格
    （缺口 / 过载），不能把它们当成装配行。只认 **6 列** markdown 表格行
    （列序：cell id / class / domain / 领域片 / 通用片 / 什么时候用）；
    表头（首列以 `cell id` 开头）与 `|---|` 分隔行跳过。
    缺表头 / 0 行 / 列数不对 ⇒ 问题串（⛔ 不静默忽略：runtime 靠同一张表取片，写坏一行 = 那一格静默消失）。
    """
    rows, problems = [], []
    header_seen, started = False, False
    for line in text.split("\n"):
        s = line.strip()
        if not s.startswith("|"):
            if started:
                break                                   # 第一个表格块结束 ⇒ 后面的表不属于装配表
            continue
        started = True
        if not s.endswith("|"):
            problems.append("cells(行未闭合:%s)" % _short(s, 16))
            continue
        cols = [c.strip() for c in s.strip("|").split("|")]
        if cols and all(re.match(r"^:?-{2,}:?$", c) for c in cols):
            continue                                    # 分隔行
        if not header_seen and cols and cols[0].lower().startswith("cell id"):
            header_seen = True
            if len(cols) != 6:
                problems.append("cells(表头列数:%d,应6)" % len(cols))
            continue
        if len(cols) != 6:
            problems.append("cells(列数:%d,应6:%s)" % (len(cols), _short(cols[0], 16)))
            continue
        rows.append({
            "id": cols[0], "class": cols[1], "domain": cols[2],
            "domain_parts": split_cell_ids(cols[3]),
            "universal_parts": split_cell_ids(cols[4]),
            "when": cols[5],
        })
    if not header_seen:
        problems.append("cells(缺表头)")
    if not rows:
        problems.append("cells(0行)")
    return rows, problems


def cells_problems(rows, part_index):
    """装配表**严格**校验 ⇒ 问题串 list（空 = 通过）。

    `part_index`: 片 id → {class, domain, file}（跨全部能力的 `parts[].id`，唯一性由
    `parts_problems()` 保证 ⇒ 这里只查"存在 + 同类 + 同域"）。
    """
    out = []
    seen = set()
    for i, r in enumerate(rows, 1):
        tag = r["id"] or ("第%d行" % i)
        cid, cls, dom = r["id"], r["class"], r["domain"]
        if not cid:
            out.append("cells(cell id空:第%d行)" % i)
        elif cid in seen:
            out.append("cells(cell id重复:%s)" % cid)
        seen.add(cid)
        if cls not in PART_CLASS_VALUES:
            out.append("cells(class值域外:%s:%s)" % (tag, cls))
        if dom not in PART_DOMAIN_VALUES or dom == UNIVERSAL_DOMAIN:
            out.append("cells(domain值域外:%s:%s)" % (tag, dom))
        if cid and cls in PART_CLASS_VALUES and dom in PART_DOMAIN_VALUES and cid != dom + "/" + cls:
            out.append("cells(cell id与class/domain不符:%s)" % tag)
        if not r["when"].strip() or r["when"].strip() in CELL_EMPTY_TOKENS:
            out.append("cells(when空:%s)" % tag)
        dparts, uparts = r["domain_parts"], r["universal_parts"]
        if len(uparts) > CELL_UNIVERSAL_MAX:
            out.append("cells(通用片超%d:%s:%d)" % (CELL_UNIVERSAL_MAX, tag, len(uparts)))
        total = dparts + uparts
        if len(total) > CELL_PARTS_MAX:
            out.append("cells(片总数超%d:%s:%d)" % (CELL_PARTS_MAX, tag, len(total)))
        if not total:
            out.append("cells(0片:%s)" % tag)
        for pid in total:
            meta = part_index.get(pid)
            if meta is None:
                out.append("cells(片不存在:%s:%s)" % (tag, pid))
                continue
            if meta["class"] != cls:
                out.append("cells(跨类引用:%s:%s:%s)" % (tag, pid, meta["class"]))
            if pid in uparts:
                if meta["domain"] != UNIVERSAL_DOMAIN:
                    out.append("cells(通用片非通用域:%s:%s:%s)" % (tag, pid, meta["domain"]))
            elif meta["domain"] != dom:
                out.append("cells(领域片domain不符:%s:%s:%s)" % (tag, pid, meta["domain"]))
        both = [x for x in dparts if x in uparts]
        for pid in both:
            out.append("cells(片重复列:%s:%s)" % (tag, pid))
    return out


def vocab_values(root):
    """从 NEEDS-VOCAB.md 抓三轴值（| 值 | 示例 | 行）· 读不到 ⇒ None（跳过词表校验）。"""
    p = os.path.join(root, "task_cards", "NEEDS-VOCAB.md")
    try:
        text = read_text(p)
    except OSError:
        return None
    out = {}
    # 值行形如：| `前端` | 页面 · 样式 …… |
    vals = re.findall(r"^\|\s*`([^`]+)`\s*\|", text, re.M)
    if not vals:
        return None
    out["all"] = set(vals)
    return out


def main():
    # 🔴 （worker 读数）：控制台可能是 GBK ⇒ 末行含 ⇒ 会 UnicodeEncodeError
    #   ⇒ 读数全绿但 exit 1（照做的人会误判成红）。显式把 stdout 改 UTF-8，
    #   与 `task_card.py` / `_capability_choice_lint.py` 同口径。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    args = ap.parse_args()
    root = args.root.replace("\\", "/")
    cap_dir = os.path.join(root, "capabilities")
    vocab = vocab_values(root)
# 跳过 `_` 开头的**元文件**（模板 `_TEMPLATE-domain.md` 等）——
    #   它们是骨架不是能力；此前只靠 SKIP 白名单，新增模板会被误判成能力文件。
    files = sorted(f for f in os.listdir(cap_dir)
                   if f.endswith(".md") and f not in SKIP and not f.startswith("_"))
    # 第一遍：读全部文件 + 收集 `parts` id（唯一性是**跨能力**判据，单文件看不出重复）
    loaded, all_ids, part_index = [], {}, {}
    for f in files:
        text = read_text(os.path.join(cap_dir, f))
        fm = frontmatter(text)
        entries, block_problem = parts_of(fm)
        loaded.append((f, fm, text, entries, block_problem))
        for p in entries:
            pid = p.get("id", "").strip()
            if pid:
                all_ids.setdefault(pid, []).append(f)
                part_index.setdefault(pid, {
                    "class": p.get("class", "").strip(),
                    "domain": p.get("domain", "").strip(),
                    "file": f,
                })
    fails, warns, pending = [], [], []
    rows = []
    for f, fm, text, entries, block_problem in loaded:
        missing = [k for k in REQUIRED if len(list_value(fm, k)) == 0]
        # 域能力（`domain-*.md`）**不要求** `phases`（阶段不再是分类轴）
        is_dom = os.path.basename(f).startswith("domain-")
        ph = None if is_dom else phases_problem(fm)  # A2：`phases` 单独校验（形态 + 值域）
        problems = missing + ([ph] if ph else [])
        if block_problem:
            problems.append(block_problem)          # 有 `parts` 键但形态不对 ⇒ FAIL
        elif entries:
            problems.extend(parts_problems(entries, f, all_ids, body_text(text)))
        no_parts = (not entries) and block_problem is None   # 无 `parts` ⇒ WARN（向后兼容）
        # 词表校验（仅告警）
        bad_axis = []
        if vocab is not None:
            for k in AXIS_FIELDS:
                for v in list_value(fm, k):
                    if v not in vocab["all"]:
                        bad_axis.append(k + ":" + v)
        if no_parts:
            pending.append(f)
        status = "FAIL" if problems else ("WARN" if (bad_axis or no_parts) else "OK")
        rows.append((f, status,
                     ",".join(problems) if problems else "-",
                     ",".join(bad_axis) if bad_axis else "-",
                     str(len(entries)) if entries else "-"))
        if problems:
            fails.append((f, problems))
        if bad_axis:
            warns.append((f, bad_axis))
    w = max(len(r[0]) for r in rows) if rows else 10
    print("能力 frontmatter 字段核对（只读 · T1a + A2 + 片级化 P0/P2）· 文件数 " + str(len(rows)))
    print("-" * 98)
    for f, status, mi, ba, pc in rows:
        print("%-*s  %-4s  片: %-2s 问题: %-30s 词表外: %s" % (w, f, status, pc, mi, ba))
    print("-" * 98)
    print("合计 %d · OK %d · WARN %d · FAIL %d" % (
        len(rows),
        sum(1 for r in rows if r[1] == "OK"),
        sum(1 for r in rows if r[1] == "WARN"),
        sum(1 for r in rows if r[1] == "FAIL"),
    ))
    if fails:
        print("\n需修字段（T1a + A2 + 片级化判据）：")
        for f, missing in fails:
            print("  - " + f + " ⇒ " + " · ".join(missing))
    if warns:
        print("\n词表外取值（WARN · 可能词表已演进）：")
        for f, bad in warns:
            print("  - " + f + " ⇒ " + " · ".join(bad))
    if pending:
        # 控制台可能是 GBK（cp936）⇒ 打印串一律用可编码字符，⛔/⚠ 只留在注释与 docstring 里
        print("\n无 parts（WARN · 待补片 · 不判 FAIL）：" + str(len(pending)) + " 个")
        print("  - " + " · ".join(pending))
    # ── 格能力装配表`capabilities/CELLS.md` ──────────────────────────
    #    🔴 域合并（「一个领域一个文件 · 不要阶段」）后：
    #       CELLS.md 已归档到 `capabilities/_archive/`（一域一文件 ⇒ 「阶段×领域」格不再存在）
    #       ⇒ 本段改为**文件在才校验**；不在则打印一行说明，⛔ 不判 FAIL（保留历史兼容）。
    cell_fails = []
    cells_path = os.path.join(cap_dir, "CELLS.md")
    if os.path.exists(cells_path):
        cell_rows, cell_block = cells_of(read_text(cells_path))
        cell_problems = list(cell_block) + cells_problems(cell_rows, part_index)
        print("\nCELLS.md 装配表（A1 · 阶段 x 领域）：%d 格 · 问题 %d" % (len(cell_rows), len(cell_problems)))
        if cell_problems:
            for p in cell_problems:
                print("  - " + p)
            cell_fails = cell_problems
    else:
        print("\nCELLS.md 已归档（2026-11-02 域合并：一域一文件）-> 跳过格装配表校验")
    # ── 🔴 （审计）：`INDEX.md` 交叉校验 ──────────────────────────────────
    #   问题：新增域能力/加片后忘改 INDEX ⇒ 无任何命令报错（审计中当场复现：parts=4 vs INDEX=3，
    #         而本脚本仍报 8 OK / 0 FAIL）。⇒ 这里补两道：行数一致 + 每行片数 == 文件内 parts 数。
    idx_fails = []
    idx_path = os.path.join(cap_dir, "INDEX.md")
    if os.path.exists(idx_path):
        idx_text = read_text(idx_path)
        idx_rows = {}
        for line in idx_text.split("\n"):
            m = re.match(r"^\|\s*\d+\s*\|\s*`(domain-[a-z0-9\-]+)`\s*\|\s*[^|]*\|\s*(\d+)\s*\|", line)
            if m:
                idx_rows[m.group(1)] = int(m.group(2))
        actual = {}
        for f, _st, _mi, _ba, pc in rows:
            try:
                actual[f[:-3]] = int(str(pc).strip())
            except ValueError:
                actual[f[:-3]] = -1
        for key, pc in sorted(actual.items()):
            if key not in idx_rows:
                idx_fails.append("%s 在 INDEX 表里没有行" % key)
            elif idx_rows[key] != pc:
                idx_fails.append("%s 片数不一致：INDEX=%d vs 文件=%d" % (key, idx_rows[key], pc))
        for key in sorted(set(idx_rows) - set(actual)):
            idx_fails.append("INDEX 有行但文件不存在：%s" % key)
        print("\nINDEX.md 交叉校验：表 %d 行 · 文件 %d 个 · 问题 %d"
              % (len(idx_rows), len(actual), len(idx_fails)))
        for p in idx_fails:
            print("  - " + p)
    else:
        print("\nINDEX.md 不存在 -> 跳过交叉校验")
    sys.exit(0 if (not fails and not cell_fails and not idx_fails) else 1)


if __name__ == "__main__":
    main()
