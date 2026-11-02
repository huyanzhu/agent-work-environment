#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""未绑定引用 lint（静态闸门 · 审计 R1 /）。

背景（R1 的教训）：`runtime/diagnostics/probe.ts` 调用了**没 import** 的
`noteCatchFail`，而当时只有「数调用次数」的 lint 判绿 ⇒ 实际一触发就
`ReferenceError`。本 lint 不看调用次数，只看**名字有没有绑定**。

判据（对 `runtime/**/*.ts`，排除 `tests/ scratch/`）：
  1. 收集每个文件的**本文件绑定**：import 名（含 `import type` / 默认 / namespace /
     别名）、任意作用域的 `const/let/var`（含解构）、`function/class/interface/
     type/enum/namespace` 名、函数/方法/箭头的参数名、`catch` 参数。
  2. 收集 `ALL`：所有被扫描文件的**顶层定义** + 所有被扫描文件 import 过的名字。
     （后者是对判据的刻意加强：删掉一个 `node:fs` 的 import 时，别处仍 import 同名，
       就能报出来；只被单一文件 import 的内置名删掉则仍看不到 —— 见文末「不覆盖」。）
  3. 把源码里的注释、字符串、模板字面量的**字面部分**、正则字面量剥成空格
     （保留换行 ⇒ 行号不变；模板 `${...}` 里的代码保留），再找 `\\bNAME\\b`。
  4. 若 `NAME ∈ ALL` 且 `NAME ∉ 本文件绑定` ⇒ 报告 `文件:行  未绑定 NAME`。

噪音豁免（校准过，避免 `_comment_home_lint` 那样 65 条噪音）：
  · 对象属性访问 `.NAME`（含 `?.NAME`）；但展开 `...NAME` 仍算引用；
  · 对象字面量/类型成员/标签的键 `NAME:`、`NAME?:`；
  · 对象/类/接口的方法名 `NAME(...) {` / `NAME(...): Type`；
  · `break LABEL` / `continue LABEL` 里的标签；
  · `export { ... } from '...'` 里的名字（不是本地引用）；
  · 注释、字符串、模板字面量、正则里的内容。

用法：
    python tools/probes/_unbound_refs_lint.py
    python tools/probes/_unbound_refs_lint.py --root <repo>/work/_clone/agent-work-environment
    python tools/probes/_unbound_refs_lint.py --allow noteCatchFail --allow Foo,Bar

退出码：0 零条 · 1 有未绑定 · 2 根目录/runtime 缺失

⛔ 不覆盖（诚实边界）：
  · 动态属性/动态调用：`obj[name]`、`globalThis[name]`、`eval('...')`；
  · 运行时才拼出来的名字、`typeof NAME` 之外的字符串化（`String(NAME)` 里 NAME 会被当引用）；
  · 只被**单个**文件 import、在仓库别处没有定义/import 的内置或 npm 名（如只删
    probe.ts 的 `closeSync` import）—— ALL 里没有它，本判据看不到；
  · 作用域精度：参数/局部变量按「文件名下有绑定」处理，不做逐作用域分析 ⇒
    内层同名变量会掩盖外层的真未绑定（假阴性方向，宁漏不误报）；
  · 类型位置的引用（`typeof`、泛型实参、类型注解）按普通标识符看，不做类型检查；
  · 重导出 `export { x } from ...` 不视为本地绑定（TS 语义），但也不报告；
  · 只扫 `runtime/**/*.ts`；`.mjs`、`tools/**`、仓库根其它 TS 不在范围内。
"""
import argparse
import io
import os
import re
import sys

DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCAN_DIR = "runtime"
EXCLUDE_DIRS = {"tests", "scratch"}

ID_RE = re.compile(r"[A-Za-z_$][\w$]*")
IMPORT_RE = re.compile(r"(?m)^[ \t]*import\b(?!\s*[.(])")
EXPORT_FROM_RE = re.compile(r"(?m)^[ \t]*export\s+(?:type\s+)?\{[^}]*\}\s*from\b")
TOP_DEF_RE = re.compile(
    r"(?m)^(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?(?:abstract\s+)?"
    r"(function|class|const|let|var|type|interface|enum|namespace)\s+"
)
DECL_RE = re.compile(r"\b(?:const|let|var)\s+")
TYPE_DECL_RE = re.compile(r"\b(?:function|class|interface|type|enum|namespace)\s+([A-Za-z_$][\w$]*)")

CONTROL_WORDS = {
    "if", "for", "while", "switch", "catch", "with", "function", "return",
    "typeof", "void", "delete", "new", "throw", "do", "else", "case", "in", "of",
}


# ──────────────────────────────────────────────────────────────────────────────
# 1) 剥注释 / 字符串 / 模板字面量 / 正则（等长替换，保留换行 ⇒ 行号稳定）
# ──────────────────────────────────────────────────────────────────────────────
def mask_source(src):
    out = list(src)
    n = len(src)

    def blank(a, b):
        for k in range(max(0, a), min(b, n)):
            if src[k] not in "\r\n":
                out[k] = " "

    def prev_sig(pos):
        k = pos - 1
        while k >= 0 and out[k] in " \t\r\n":
            k -= 1
        return k

    def regex_allowed(pos):
        """`/` 是正则开始还是除号：看前一个有意义字符/关键字。"""
        k = prev_sig(pos)
        if k < 0:
            return True
        ch = out[k]
        if ch in "([{,;:=!&|?+-*%^~<>":
            return True
        s = k
        while s >= 0 and (out[s].isalnum() or out[s] in "_$"):
            s -= 1
        word = "".join(out[s + 1:k + 1])
        return word in {
            "return", "typeof", "instanceof", "case", "delete", "void", "throw",
            "new", "else", "do", "yield", "await", "default", "in", "of",
        }

    def scan_code(i, stop_brace=False):
        depth = 0
        while i < n:
            c = src[i]
            if stop_brace:
                if c == "}" and depth == 0:
                    return i
                if c == "{":
                    depth += 1
                    i += 1
                    continue
                if c == "}":
                    depth -= 1
                    i += 1
                    continue
            if c == "/" and i + 1 < n and src[i + 1] == "/":
                j = src.find("\n", i)
                blank(i, n if j < 0 else j)
                i = n if j < 0 else j
            elif c == "/" and i + 1 < n and src[i + 1] == "*":
                j = src.find("*/", i + 2)
                j = n if j < 0 else j + 2
                blank(i, j)
                i = j
            elif c in "'\"":
                j = i + 1
                while j < n:
                    if src[j] == "\\":
                        j += 2
                        continue
                    if src[j] == c:
                        j += 1
                        break
                    if src[j] in "\r\n":
                        break
                    j += 1
                blank(i, j)
                i = j
            elif c == "`":
                seg_start = i
                j = i + 1
                while j < n:
                    if src[j] == "\\":
                        j += 2
                        continue
                    if src[j] == "`":
                        j += 1
                        break
                    if src[j] == "$" and j + 1 < n and src[j + 1] == "{":
                        blank(seg_start, j + 2)          # 字面部分 + `${`
                        k = scan_code(j + 2, stop_brace=True)  # 插值里的代码保留
                        j = k + 1 if k < n else n
                        seg_start = j
                        continue
                    j += 1
                blank(seg_start, j)
                i = j
            elif c == "/" and regex_allowed(i):
                j = i + 1
                in_class = False
                while j < n:
                    if src[j] == "\\":
                        j += 2
                        continue
                    if src[j] == "[":
                        in_class = True
                    elif src[j] == "]":
                        in_class = False
                    elif src[j] == "/" and not in_class:
                        j += 1
                        while j < n and (src[j].isalpha()):
                            j += 1
                        break
                    elif src[j] in "\r\n":
                        break
                    j += 1
                blank(i, j)
                i = j
            else:
                i += 1
        return i

    scan_code(0)
    return "".join(out)


def mask_export_from(code):
    """把 `export { ... } from '...'` 整段抹成空格（不是本地引用）。"""
    out = list(code)
    for m in EXPORT_FROM_RE.finditer(code):
        for k in range(m.start(), m.end()):
            if out[k] not in "\r\n":
                out[k] = " "
    return "".join(out)


# ──────────────────────────────────────────────────────────────────────────────
# 2) 解析 import / 顶层定义 / 本地绑定
# ──────────────────────────────────────────────────────────────────────────────
def split_top(text, sep=","):
    """按顶层分隔符切（忽略 (), [], {} 里的分隔符）。"""
    parts, depth, start = [], 0, 0
    for i, c in enumerate(text):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif c == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def top_prefix(text, targets):
    """取顶层目标符号之前的部分（用于参数 `name: Type` 里的绑定名）。"""
    depth = 0
    for i, c in enumerate(text):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and c in targets:
            return text[:i]
    return text


def match_bracket(code, pos):
    """pos 指向 `(`/`{`/`[`，返回到匹配闭括号的下标（找不到 ⇒ -1）。"""
    pairs = {"(": ")", "{": "}", "[": "]"}
    if pos >= len(code) or code[pos] not in pairs:
        return -1
    opener, closer = code[pos], pairs[code[pos]]
    depth = 0
    i = pos
    while i < len(code):
        c = code[i]
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def pattern_names(pattern):
    """从一个绑定模式里取绑定的标识符：`{a, b: c, ...d}` / `[a, b]` / `a`。"""
    names = set()
    p = pattern.strip()
    if not p:
        return names
    if p.startswith("..."):
        p = p[3:].strip()
    if p.startswith("{"):
        end = match_bracket(p, 0)
        inner = p[1:end] if end > 0 else p[1:]
        for item in split_top(inner):
            item = item.strip()
            if not item:
                continue
            if item.startswith("..."):
                ident = ID_RE.match(item[3:].strip())
                if ident:
                    names.add(ident.group(0))
                continue
            # `key: binding` / `key = default` / `key`
            head = top_prefix(item, ":=")
            colon = ":" in item[:len(head) + 1] if len(head) < len(item) else False
            if colon:
                rest = item[len(head) + 1:].strip()
                rest = top_prefix(rest, "=").strip()
                names |= pattern_names(rest)
            else:
                ident = ID_RE.match(head.strip())
                if ident:
                    names.add(ident.group(0))
        return names
    if p.startswith("["):
        end = match_bracket(p, 0)
        inner = p[1:end] if end > 0 else p[1:]
        for item in split_top(inner):
            names |= pattern_names(item)
        return names
    ident = ID_RE.match(p)
    if ident:
        names.add(ident.group(0))
    return names


def parse_params(text):
    """参数列表 → 绑定名（只取绑定目标，不把类型注解当绑定）。"""
    names = set()
    for seg in split_top(text):
        seg = seg.strip()
        if not seg:
            continue
        seg = re.sub(r"^(?:(?:public|private|protected|readonly|override|declare)\s+)+", "", seg)
        seg = seg.strip()
        if seg.startswith("@"):  # 装饰器（本项目不用；保守跳过前缀）
            seg = re.sub(r"^@[A-Za-z_$][\w$.]*\s*", "", seg).strip()
        if not seg:
            continue
        head = top_prefix(seg, "=").strip() if "=" in seg else seg
        # 只取冒号前的绑定部分（`: Type` 里的类型不是绑定）
        head = top_prefix(head, ":").strip()
        if head.startswith("..."):
            head = head[3:].strip()
        if head.startswith("{") or head.startswith("["):
            names |= pattern_names(head)
        else:
            ident = ID_RE.match(head)
            if ident and ident.group(0) not in CONTROL_WORDS:
                names.add(ident.group(0))
    return names


def collect_imports(code):
    """返回 import 绑定名集合。code 是剥噪音后的文本。"""
    names = set()
    for m in IMPORT_RE.finditer(code):
        fm = re.search(r"\bfrom\b", code[m.end():])
        if not fm:
            # `import './side-effect'` 或 `import x = require(...)`
            continue
        from_pos = m.end() + fm.start()
        between = code[m.end():from_pos]
        # 副作用 import 没有 from；防止把**下一条** import 的 from 认成自己的
        if ";" in between or re.search(r"\b(?:import|export)\b", between):
            continue
        clause = re.sub(r"\s+", " ", between).strip()
        if clause.startswith("type "):
            clause = clause[5:].strip()
        # 默认导入：`Foo, { ... }` / `Foo from`
        dm = re.match(r"([A-Za-z_$][\w$]*)\s*(?:,|$)", clause)
        if dm and dm.group(1) not in ("type",):
            names.add(dm.group(1))
            clause = clause[dm.end():].strip()
        # namespace：`* as ns`
        nm = re.search(r"\*\s*as\s+([A-Za-z_$][\w$]*)", clause)
        if nm:
            names.add(nm.group(1))
        # 具名：`{ A, B as C, type D }`
        bm = re.search(r"\{([^}]*)\}", clause)
        if bm:
            for item in split_top(bm.group(1)):
                item = item.strip()
                if not item:
                    continue
                if item.startswith("type "):
                    item = item[5:].strip()
                am = re.search(r"\bas\s+([A-Za-z_$][\w$]*)\s*$", item)
                if am:
                    names.add(am.group(1))
                    continue
                im = re.match(r"([A-Za-z_$][\w$]*)", item)
                if im and im.group(1) not in ("type",):
                    names.add(im.group(1))
    return names


def collect_bindings(code):
    """文件内任意作用域的绑定名（宁多勿少：多绑 = 假阴性，少绑 = 假阳性）。"""
    names = set()
    # const / let / var（含解构、for 头）
    for m in DECL_RE.finditer(code):
        p = m.end()
        while p < len(code) and code[p] in " \t\r\n":
            p += 1
        if p >= len(code):
            continue
        if code[p] in "{[":
            end = match_bracket(code, p)
            if end > p:
                names |= pattern_names(code[p:end + 1])
        else:
            im = ID_RE.match(code, p)
            if im:
                names.add(im.group(0))
    # function / class / interface / type / enum / namespace 名（任意作用域）
    for m in TYPE_DECL_RE.finditer(code):
        names.add(m.group(1))
    # 函数参数
    for m in re.finditer(r"\bfunction\b\s*\*?\s*(?:[A-Za-z_$][\w$]*)?\s*\(", code):
        op = m.end() - 1
        cl = match_bracket(code, op)
        if cl > op:
            names |= parse_params(code[op + 1:cl])
    # 方法 / 箭头 / catch：遍历所有 `(`，看闭括号后面是什么
    for m in re.finditer(r"\(", code):
        op = m.start()
        cl = match_bracket(code, op)
        if cl <= op:
            continue
        after = code[cl + 1:]
        inner = code[op + 1:cl]
        # 箭头函数：`(...) =>` 或 `(...): Type =>`
        if re.match(r"\s*=>", after) or re.match(r"\s*:\s*[^=;{]*?=>", after):
            names |= parse_params(inner)
            continue
        # 方法定义：`name(...) {` / `name(...): Type {`
        meth = re.search(r"([A-Za-z_$][\w$]*)\s*$", code[:op])
        if meth and meth.group(1) not in CONTROL_WORDS:
            if re.match(r"\s*(?::[^;{]*)?\{", after):
                names |= parse_params(inner)
        # catch (e)：参数也是绑定
        if meth and meth.group(1) == "catch":
            names |= parse_params(inner)
    return names


def top_level_defs(code):
    """只收集列 0 的顶层定义（ALL 的来源）。"""
    names = set()
    for m in TOP_DEF_RE.finditer(code):
        kw = m.group(1)
        rest = code[m.end():]
        if kw == "function":
            rest = rest.lstrip()
            if rest.startswith("*"):
                rest = rest[1:].lstrip()
        if kw in ("const", "let", "var"):
            p = 0
            while p < len(rest) and rest[p] in " \t":
                p += 1
            if p < len(rest) and rest[p] in "{[":
                end = match_bracket(rest, p)
                if end > p:
                    names |= pattern_names(rest[p:end + 1])
                continue
        im = ID_RE.match(rest, 0)
        if im:
            names.add(im.group(0))
    return names


# ──────────────────────────────────────────────────────────────────────────────
# 3) 找引用（masked code 上的标识符 + 噪音豁免）
# ──────────────────────────────────────────────────────────────────────────────
def prev_sig(code, pos):
    k = pos - 1
    while k >= 0 and code[k] in " \t\r\n":
        k -= 1
    return k


def next_sig(code, pos):
    k = pos
    while k < len(code) and code[k] in " \t\r\n":
        k += 1
    return k


def is_method_name(code, pos, end):
    """`name(...) {` / `name(...): Type` 形态（对象/类/接口类型成员）⇒ 名字不是引用。"""
    k = next_sig(code, end)
    if k >= len(code) or code[k] != "(":
        return False
    cl = match_bracket(code, k)
    if cl < 0:
        return False
    after = code[cl + 1:]
    # 方法定义：`name(...) {` / `name(...): Type {`
    if re.match(r"\s*(?::[^;{]*)?\{", after):
        p = prev_sig(code, pos)
        if p < 0 or code[p] in "{,;}":
            return True
        line_start = code.rfind("\n", 0, pos) + 1
        return code[line_start:pos].strip() == ""
    # 类型成员签名：`name(...): Type;` / `name(...): Type }`（interface / type 字面量里；
    # 调用式后面跟 `: Type` 只可能是三元/对象值上下文，用「前一个有意义字符」再卡一道）
    if re.match(r"\s*:\s*[^;{}\n]+[;}\n]", after):
        p = prev_sig(code, pos)
        if p < 0 or code[p] in "{,;}":
            return True
        line_start = code.rfind("\n", 0, pos) + 1
        return code[line_start:pos].strip() == ""
    return False


def find_unbound(text, all_names, allow):
    code = mask_export_from(mask_source(text))
    bound = collect_imports(code) | collect_bindings(code)
    found = []
    for m in ID_RE.finditer(code):
        name = m.group(0)
        if name not in all_names or name in bound or name in allow:
            continue
        start, end = m.start(), m.end()
        # 属性访问 `.NAME`（但 `...NAME` 展开仍算引用）
        p = prev_sig(code, start)
        if p >= 0 and code[p] == ".":
            pp = prev_sig(code, p)
            if not (pp >= 0 and code[pp] == "."):
                continue
        # 标签引用 `break LABEL` / `continue LABEL`：不是变量/函数引用
        if p >= 0:
            ws = p
            while ws >= 0 and (code[ws].isalnum() or code[ws] in "_$"):
                ws -= 1
            if code[ws + 1:p + 1] in ("break", "continue"):
                continue
        # 键 / 标签：`NAME:` 或 `NAME?:`
        n = next_sig(code, end)
        is_key = False
        if n < len(code) and code[n] == ":":
            is_key = True
        elif n + 1 < len(code) and code[n] == "?" and next_sig(code, n + 1) < len(code) \
                and code[next_sig(code, n + 1)] == ":":
            is_key = True
        if is_key:
            pp = prev_sig(code, start)
            line_start = code.rfind("\n", 0, start) + 1
            at_line_start = code[line_start:start].strip() == ""
            if pp < 0 or code[pp] in "{,;}" or at_line_start:
                continue
        # 方法名 `name(...) {` / 类型成员签名 `name(...): Type`
        if is_method_name(code, start, end):
            continue
        found.append((text.count("\n", 0, start) + 1, name))
    return found


# ──────────────────────────────────────────────────────────────────────────────
# 4) 主流程
# ──────────────────────────────────────────────────────────────────────────────
def iter_ts(root):
    base = os.path.join(root, SCAN_DIR)
    if not os.path.isdir(base):
        return None
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        rel = os.path.relpath(dirpath, base).replace("\\", "/")
        parts = [] if rel == "." else rel.split("/")
        if any(p in EXCLUDE_DIRS for p in parts):
            dirnames[:] = []
            continue
        for fn in sorted(filenames):
            if fn.endswith(".ts"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="runtime/**/*.ts 未绑定引用静态闸门")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="仓库根（含 runtime/）")
    ap.add_argument("--allow", action="append", default=[],
                    help="白名单名字；可重复，也可逗号分隔（默认空）")
    args = ap.parse_args()
    root = os.path.abspath(args.root.replace("\\", "/")).replace("\\", "/")
    allow = set()
    for item in args.allow:
        allow |= {s.strip() for s in item.split(",") if s.strip()}

    files = iter_ts(root)
    if files is None:
        print("⛔ 找不到 runtime/:", os.path.join(root, SCAN_DIR))
        return 2
    if not files:
        print("⛔ runtime/ 下没有 .ts:", os.path.join(root, SCAN_DIR))
        return 2

    texts, defs, imports_by_file = {}, {}, {}
    for path in files:
        with io.open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        rel = os.path.relpath(path, root).replace("\\", "/")
        texts[rel] = text
        code = mask_source(text)
        defs[rel] = top_level_defs(code)
        imports_by_file[rel] = collect_imports(code)
    all_names = set()
    for rel in texts:
        all_names |= defs[rel] | imports_by_file[rel]

    rows = []
    for rel in sorted(texts):
        for line, name in find_unbound(texts[rel], all_names, allow):
            rows.append((rel, line, name))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))

    print("未绑定引用 lint · %s" % os.path.join(root, SCAN_DIR).replace("\\", "/"))
    print("  扫描 %d 个 .ts · 已知名字(定义∪import) %d · 白名单 %d"
          % (len(files), len(all_names), len(allow)))
    for rel, line, name in rows:
        print("%s:%d  未绑定 %s" % (rel, line, name))
    print("合计 未绑定 %d 处" % len(rows))
    return 0 if not rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
