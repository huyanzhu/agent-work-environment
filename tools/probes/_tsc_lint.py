# -*- coding: utf-8 -*-
"""类型闸门（tsc --noEmit）—— R2 遗留，。

设计要点：
  · `runtime/` 下没有 `node_modules` ⇒ 直接 `tsc -p runtime/tsconfig.json` 会报
    `TS2688 Cannot find type definition file for 'node'`。本脚本在**可写的 scratch/** 下生成一份
    临时 tsconfig（`include`/`typeRoots` 用绝对路径指向本仓 runtime 与已装的 @types），再跑 tsc。
  · **找不到 tsc / @types/node 时 exit 2（SKIP）** —— 不假装绿、也不因缺依赖而红。
  · 全量 strict 零基线（审计读数：88 条里 79 条是 `types: []` 假错）。

用法：
    python tools/probes/_tsc_lint.py                 # 本仓 runtime
    python tools/probes/_tsc_lint.py --root <repo>   # 指定仓库
退出码：0 无错误 · 1 有错误 · 2 SKIP（缺 tsc 或 @types/node）
"""
import argparse
import io
import json
import os
import subprocess
import sys


def find_tsc(root):
    """按优先级找 tsc：scratch/tscheck → 仓根 node_modules → npx。"""
    cands = [
        os.path.join(root, "scratch", "tscheck", "node_modules", ".bin", "tsc"),
        os.path.join(root, "node_modules", ".bin", "tsc"),
    ]
    for c in cands:
        for exe in (c + ".cmd", c):
            if os.path.isfile(exe):
                return exe
    return None


def find_type_roots(root):
    cands = [
        os.path.join(root, "scratch", "tscheck", "node_modules", "@types"),
        os.path.join(root, "node_modules", "@types"),
    ]
    for c in cands:
        if os.path.isdir(os.path.join(c, "node")):
            return c
    return None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    tsc = find_tsc(root)
    type_roots = find_type_roots(root)
    if tsc is None or type_roots is None:
        missing = "tsc" if tsc is None else "@types/node"
        print("类型闸门：SKIP（缺少 %s）" % missing)
        print("  装法（一次性，产物在 scratch/ 不入仓）：")
        print("  npm i typescript@5 @types/node --prefix scratch/tscheck --cache scratch/npm-cache")
        return 2

    out_dir = os.path.join(root, "scratch", "_tsc_runtime")
    os.makedirs(out_dir, exist_ok=True)
    cfg_path = os.path.join(out_dir, "tsconfig.json")
    cfg = {
        "compilerOptions": {
            "target": "ES2022",
            "module": "nodenext",
            "moduleResolution": "nodenext",
            "strict": True,
            "noEmit": True,
            "skipLibCheck": True,
            "allowImportingTsExtensions": True,
            "verbatimModuleSyntax": True,
            "types": ["node"],
            "typeRoots": [type_roots.replace("\\", "/")],
            "lib": ["ES2022"],
        },
        "include": [os.path.join(root, "runtime", "**", "*.ts").replace("\\", "/")],
        "exclude": [os.path.join(root, "runtime", "tests").replace("\\", "/")],
    }
    io.open(cfg_path, "w", encoding="utf-8", newline="\n").write(json.dumps(cfg, ensure_ascii=False, indent=2))

    r = subprocess.run([tsc, "-p", cfg_path, "--noEmit"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=root)
    out = (r.stdout or "") + (r.stderr or "")
    errs = [l for l in out.splitlines() if l.startswith("error TS") or ("error TS" in l)]
    print("类型闸门 tsc --noEmit · strict 零基线")
    if errs:
        for l in errs[:20]:
            print("  " + l.strip())
        if len(errs) > 20:
            print("  … 共 %d 条" % len(errs))
    print("合计 %d 条错误" % len(errs))
    return 0 if r.returncode == 0 and not errs else 1


if __name__ == "__main__":
    raise SystemExit(main())
