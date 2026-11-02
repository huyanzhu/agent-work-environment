# -*- coding: utf-8 -*-
"""R3：注释「张冠李戴」只读检查器（搬运遗留）。

判据：一个**连续注释块**里若出现反引号包着的符号名（如 `` `readHead` `` / `` `OBS` ``），
      而该符号在本文件既没定义也没 import ⇒ 该注释很可能属于**别的文件**（搬运时被拖错）。

为什么是 WARN 而不是 FAIL：注释是文档，误报率高（`§14.8`/`` 这类不是符号）。
它给出的价值是：B 阶段继续提炼时，能提前看到"这段注释到底在说谁"。

用法：python tools/probes/_comment_home_lint.py [--root <repo>] [--strict]
      `--strict` ⇒ 有告警就 exit 1（默认只提示）。
"""
import argparse
import io
import os
import re
import sys

SUBDIRS = ("diagnostics", "session", "retrieval", "activation", "delivery", "maintenance")
SYMBOL = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{2,})(?:\(\))?`")

# 🔇 通用名（形参/局部变量/JSON 字段）—— 不许当「符号」报，否则 65 条噪音掩盖真问题
GENERIC = {
    "path", "session", "value", "tmp", "start", "end", "chunk", "card", "cards", "name",
    "enabled", "index", "key", "node", "text", "data", "cmd", "args", "opts", "e", "i",
    "allowSubagent", "sessionId", "state", "kind", "why", "note", "at", "id", "ev", "obs",
    "json", "true", "false", "null", "undefined", "pathToFileURL",
}


def files(root):
    base = os.path.join(root, "runtime")
    out = [os.path.join(base, "aios-activation.ts")]
    for sd in SUBDIRS:
        d = os.path.join(base, sd)
        if os.path.isdir(d):
            out += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".ts")]
    return [p for p in out if os.path.isfile(p)]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    root = args.root
    all_defined = set()
    exported_home = {}      # 符号 → 定义并 export 它的文件
    texts = {}
    for p in files(root):
        t = io.open(p, encoding="utf-8").read()
        texts[p] = t
        all_defined |= set(re.findall(r"(?:export )?(?:async )?(?:function|const|let|type|interface|class) ([A-Za-z0-9_]+)", t))
        for m in re.finditer(r"(?m)^export (?:async )?(?:function|const|let|type|interface|class) ([A-Za-z0-9_]+)", t):
            exported_home.setdefault(m.group(1), os.path.relpath(p, root))

    warns = []
    for p, t in texts.items():
        defined = set(re.findall(r"(?:export )?(?:async )?(?:function|const|let|type|interface|class) ([A-Za-z0-9_]+)", t))
        imported = set()
        for m in re.finditer(r"import (?:type )?\{([^}]*)\}", t):
            imported |= {x.strip() for x in m.group(1).split(",") if x.strip()}
        lines = t.split("\n")
        block = []

        def flush(block, start_line):
            if not block:
                return
            text = "\n".join(block)
            for sym in set(SYMBOL.findall(text)):
                if sym in GENERIC:
                    continue
                if sym in defined or sym in imported:
                    continue
                # 只报「被别的文件 export 的真 API」——参数名/局部变量（max/sent/step）不算符号
                if sym not in exported_home or exported_home.get(sym) == os.path.relpath(p, root):
                    continue
                warn = "注释提到 `%s`，但本文件没定义也没 import（真身在别处）" % sym
                warns.append((os.path.relpath(p, root), start_line, warn))
                return

        start = 0
        for i, l in enumerate(lines):
            s = l.strip()
            if s.startswith(("//", "/*", "*")):
                if not block:
                    start = i + 1
                block.append(s)
            else:
                if block:
                    flush(block, start)
                block = []
        if block:
            flush(block, start)

    for f, ln, w in warns:
        print("  ⚠️ %-42s L%-5d %s" % (f, ln, w))
    print("注释归属检查：%d 个文件 · 告警 %d 处%s" % (len(texts), len(warns), "（strict ⇒ 失败）" if args.strict else ""))
    return 1 if (args.strict and warns) else 0


if __name__ == "__main__":
    raise SystemExit(main())
