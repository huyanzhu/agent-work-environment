#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_release_manifest.py — 对一棵**已组装好的发布树**生成 / 校验 MANIFEST.sha256。

为什么不在公开仓发布 `tools/release_assemble.py`：
    组装修剪脚本含白名单、脱敏规则与作者侧路径语义；公开它既可能泄露内部资料，
    也让「发布物是否可复现」依赖作者环境。⇒ 公开侧只给**文件清单 + 校验**：
    拿到发布树的人可以逐字节确认「这棵树没有被改过」。

用法：

    # 1) 生成（默认写到 <root>/MANIFEST.sha256）
    python tools/probes/_release_manifest.py --root release/knowhow

    # 2) 校验（任意 cwd；清单路径相对 cwd，或以 --root 为基准）
    python tools/probes/_release_manifest.py --root . --verify MANIFEST.sha256

    # 3) 校验时允许清单之外多出文件（默认严格：多文件也算失败）
    python tools/probes/_release_manifest.py --root . --verify MANIFEST.sha256 --allow-extra

清单格式（UTF-8、LF、无 BOM，可 diff / 可脚本解析）：

    # AI-OS release manifest v1
    # files: 273
    <64 位小写 sha256>  <相对路径，统一用 />

约定：
    · 只覆盖**普通文件**；路径相对 `--root`，统一正斜杠（跨平台可比）。
    · 排除 VCS 与缓存目录（`.git/`、`__pycache__/`、`.pytest_cache/` 等）——
      它们不是发布内容，且会因本机运行而变。
    · `MANIFEST.sha256` 自身不列入清单（否则自指、永远无法稳定复现）。
    · 生成是确定性的：同样的树 ⇒ 同样的清单（无时间戳、无主机名、按路径排序）。
    · 校验默认**严格**：哈希不符 / 文件缺失 / 多出文件 / 文件数不符 ⇒ exit 1。
      只读、不修改发布树。

退出码：0 = 成功（生成或校验通过）；1 = 校验失败或输入不可读；2 = 参数/用法错误。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import sys
from typing import List, Optional, Tuple

MANIFEST_NAME = "MANIFEST.sha256"
MANIFEST_HEADER = "# AI-OS release manifest v1"
COUNT_PREFIX = "# files: "

# 这些目录不是发布内容：VCS 元数据、Python/工具缓存。
EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
# 同上，按文件名排除。
EXCLUDE_FILE_SUFFIXES = (".pyc", ".pyo")

_CHUNK = 1024 * 1024
_LINE_RE = re.compile(r"^([0-9a-f]{64})  (.+)$")


def _out(msg: str = "") -> None:
    try:
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()
    except (OSError, ValueError):
        pass


def _err(msg: str) -> None:
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _is_excluded_dir(name: str) -> bool:
    return name in EXCLUDE_DIRS


def _is_excluded_file(path: str) -> bool:
    return path.lower().endswith(EXCLUDE_FILE_SUFFIXES)


def collect_files(root: str, manifest_path: str) -> List[str]:
    """→ 相对路径（`/` 分隔、已排序）。

    跳过 VCS/缓存目录、缓存文件与清单自身；不跟随目录符号链接（os.walk 缺省）。
    """
    root_abs = os.path.abspath(root)
    manifest_abs = os.path.normcase(os.path.abspath(manifest_path))
    out = []  # type: List[str]
    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = sorted(d for d in dirnames if not _is_excluded_dir(d))
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.normcase(os.path.abspath(full)) == manifest_abs:
                continue
            if _is_excluded_file(name):
                continue
            rel = os.path.relpath(full, root_abs).replace(os.sep, "/")
            out.append(rel)
    out.sort()
    return out


def write_manifest(root: str, out_path: str) -> int:
    if not os.path.isdir(root):
        _err("FAIL: --root 不是目录：%s" % root)
        return 1
    files = collect_files(root, out_path)
    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    tmp = out_path + ".tmp-%d" % os.getpid()
    total_bytes = 0
    try:
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(MANIFEST_HEADER + "\n")
            f.write(COUNT_PREFIX + str(len(files)) + "\n")
            for rel in files:
                full = os.path.join(root, rel.replace("/", os.sep))
                digest = _sha256_file(full)
                total_bytes += os.path.getsize(full)
                f.write("%s  %s\n" % (digest, rel))
        os.replace(tmp, out_path)
    except OSError as exc:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        _err("FAIL: 写清单失败（%s: %s）" % (type(exc).__name__, exc))
        return 1

    rel_manifest = os.path.relpath(out_path, os.getcwd()).replace(os.sep, "/")
    _out("OK: wrote %s" % rel_manifest)
    _out("files=%d bytes=%d" % (len(files), total_bytes))
    return 0


def parse_manifest(path: str) -> Tuple[int, List[Tuple[str, str]]]:
    """→ (声明的文件数, [(sha256, 相对路径)])；格式非法抛 ValueError。"""
    count = None
    rows = []  # type: List[Tuple[str, str]]
    seen = set()  # type: set
    with io.open(path, "r", encoding="utf-8-sig") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\r\n")
            if line == "":
                continue
            if line.startswith("#"):
                if line.startswith(COUNT_PREFIX):
                    try:
                        count = int(line[len(COUNT_PREFIX):].strip())
                    except ValueError:
                        raise ValueError("第 %d 行文件数不是整数" % lineno)
                continue
            m = _LINE_RE.match(line)
            if not m:
                raise ValueError("第 %d 行格式非法（期望 `<sha256>  <相对路径>`）" % lineno)
            digest, rel = m.group(1), m.group(2)
            if rel in seen:
                raise ValueError("第 %d 行路径重复：%s" % (lineno, rel))
            if rel.startswith("/") or rel.startswith("../") or "/../" in rel or rel == "..":
                raise ValueError("第 %d 行路径越界：%s" % (lineno, rel))
            seen.add(rel)
            rows.append((digest, rel))
    if count is None:
        raise ValueError("清单缺少 `# files: <N>` 头")
    return count, rows


def verify_manifest(root: str, manifest_path: str, allow_extra: bool = False) -> int:
    if not os.path.isdir(root):
        _err("FAIL: --root 不是目录：%s" % root)
        return 1
    if not os.path.isfile(manifest_path):
        _err("FAIL: 清单不存在：%s" % manifest_path)
        return 1
    try:
        declared_count, rows = parse_manifest(manifest_path)
    except (OSError, ValueError) as exc:
        _err("FAIL: 清单不可读 / 格式非法（%s）" % exc)
        return 1

    failures = []  # type: List[str]
    if declared_count != len(rows):
        failures.append("清单自相矛盾：声明 files=%d，实际列出 %d 行"
                        % (declared_count, len(rows)))

    expected = {rel: digest for digest, rel in rows}
    actual_files = collect_files(root, manifest_path)
    actual_set = set(actual_files)

    missing = sorted(set(expected) - actual_set)
    extra = sorted(actual_set - set(expected))

    for rel in sorted(expected):
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue  # 已计入 missing
        try:
            digest = _sha256_file(full)
        except OSError as exc:
            failures.append("读取失败：%s（%s）" % (rel, exc))
            continue
        if digest != expected[rel]:
            failures.append("哈希不符：%s（期望 %s…，实际 %s…）"
                            % (rel, expected[rel][:12], digest[:12]))

    if missing:
        failures.append("缺失 %d 个文件：%s" % (len(missing), "、".join(missing[:10])))
    if extra and not allow_extra:
        failures.append("多出 %d 个清单外文件：%s（如确属发布内容，请重新生成清单；"
                        "否则加 --allow-extra）" % (len(extra), "、".join(extra[:10])))
    if not allow_extra and declared_count != len(actual_files):
        failures.append("文件数不符：清单 %d，实际 %d" % (declared_count, len(actual_files)))

    if failures:
        _err("FAIL: %d 项问题（root=%s）" % (len(failures), root))
        for item in failures[:50]:
            _err("  - " + item)
        if len(failures) > 50:
            _err("  … 还有 %d 项未列出" % (len(failures) - 50))
        return 1

    suffix = "（允许清单外文件 %d 个）" % len(extra) if extra else ""
    _out("OK: %d files verified%s" % (len(actual_files), suffix))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(
        description="生成 / 校验发布树的 MANIFEST.sha256（相对路径 + sha256 + 文件数）")
    ap.add_argument("--root", default=".", help="发布树根目录（默认当前目录）")
    ap.add_argument("--out", default=None,
                    help="生成时写到哪个文件（默认 <root>/%s）" % MANIFEST_NAME)
    ap.add_argument("--verify", default=None, metavar="MANIFEST",
                    help="校验模式：清单路径（相对 cwd；不存在时尝试相对 --root）")
    ap.add_argument("--allow-extra", action="store_true",
                    help="校验时允许清单之外多出文件（默认严格）")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    if args.verify:
        manifest = args.verify
        if not os.path.isabs(manifest) and not os.path.isfile(manifest):
            candidate = os.path.join(root, manifest)
            if os.path.isfile(candidate):
                manifest = candidate
        return verify_manifest(root, os.path.abspath(manifest), args.allow_extra)

    out = args.out or os.path.join(root, MANIFEST_NAME)
    return write_manifest(root, os.path.abspath(out))


if __name__ == "__main__":
    raise SystemExit(main())
