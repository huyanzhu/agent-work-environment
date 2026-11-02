#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""AI-OS 验证器 —— 接入是否真的可用（重启 DSH 之后运行）。

（自 `另一仓库` 移植进 AI-OS 本体。三处差异：支持 `--repo`；
 `tools/probes/` 缺失时降级为「知悉项」而非失败；自测**不含 Stop**（Stop 会真实写回，
 属有副作用调用，按 AI-OS 纪律⛔ 不用它试探）。）

（修 · 约定探针自测判据由「在 stdout 找硬编码期望串」
  （`retrieval_request` 写死 `"26"`）改为「解析 `selftest` JSON 判 `failed == []`」——
  探针用例 26 → 28 后原判据产生**假 ❌**（判据漂移，非接入失败）。见 `selftest_verdict()`。）

用法：

    python tools/verify.py            # 全量验证
    python tools/verify.py --quick    # 跳过探针自测（只查配置/依赖/活性）

验四件事（每项都给出可复核判据，⛔ 不猜）
    1. 配置：`cordis.patch.yml` 补丁块在不在、是否指向本仓库、hooks.json 写法对不对
    2. 依赖：python / node / 工具入口 / 机制探针 / 夹具 /（可选）名称索引
    3. 工具自测：task_start · aios-hook 两个事件（⛔ 不含 Stop）· 三个探针 `--selftest`
    4. 插件活性：探针日志是否有**近期写入**（判据与不确定性都如实说明）

退出码：0 = 全通过；1 = 有失败项。
"""
import argparse
import datetime
import io
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEGIN = "# >>> focusroute:begin"
END = "# <<< focusroute:end"


def slashes(p):
    return p.replace("\\", "/")


def read_text(p):
    try:
        with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def dsh_home():
    env = os.environ.get("DSH_HOME")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    cand = os.path.join(os.path.expanduser("~"), ".dsh")
    return cand if os.path.isdir(cand) else None


def run(args, timeout=180):
    try:
        r = subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except Exception as e:
        return 99, "", "%s: %s" % (type(e).__name__, e)


def selftest_verdict(want, rc, out, err):
    """把探针 `--selftest` 的输出判成 `(ok, detail)`。

    ⚠️ **修——原判据是「在 stdout 里找硬编码的期望串」**
    （`retrieval_request` 写死 `"26"`）。探针用例扩到 28 后，读数输出
    `{"selftest": {"total": 28, "passed": 28, "failed": []}}` · rc=0，验证器却报 ❌
    —— 属**判据漂移（stale expectation）**，不是接入失败。
    ⇒ 现改为：优先**解析 JSON 的 `selftest` 结构**判 `failed == []`（与用例数解耦）；
    输出里没有该结构（如 `_runtime_field_producer.py` 打印的是人读文本）才回退到
    **期望串子串判据**（`want` 传空串 ⇒ 该探针必须给出 selftest 结构，否则判失败）。
    ⛔ 回退路径在 detail 里明写「回退判据」，不静默降级。
    """
    lines = (out or "").strip().splitlines()
    tail = lines[-1] if lines else ""

    payload = None
    for line in reversed(lines):                     # 从尾部找最后一行可解析的 JSON
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("selftest"), dict):
            payload = obj["selftest"]
            break

    if payload is not None:
        total = payload.get("total")
        passed = payload.get("passed")
        failed = payload.get("failed")
        ok = (rc == 0
              and isinstance(total, int) and isinstance(passed, int)
              and isinstance(failed, list) and not failed
              and total > 0 and total == passed)
        if isinstance(failed, list):
            fail_note = ("0" if not failed
                         else "%d（%s）" % (len(failed), ", ".join(str(x) for x in failed[:3])))
        else:
            fail_note = "?"
        detail = "selftest %s/%s · failed=%s" % (passed, total, fail_note)
        return ok, detail

    if want:
        detail = tail[:70] or (err or "").strip()[:70]
        return (rc == 0 and want in (out or "")), "%s（回退判据：期望串 %s）" % (detail, want)
    return False, (tail[:70] or (err or "").strip()[:70]
                   or "既无 `selftest` JSON 结构，也未给出期望串 ⇒ 判失败（不猜）")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="AI-OS 接入验证")
    ap.add_argument("--quick", action="store_true", help="跳过探针自测")
    ap.add_argument("--repo", default=None, help="要验证的仓库根（默认 = 本脚本所在仓库）")
    args = ap.parse_args()

    global REPO
    if args.repo:
        REPO = os.path.abspath(args.repo)

    fails = []
    warns = []

    def sec(t):
        print("\n── %s ──" % t)

    def item(name, ok, detail="", warn_only=False):
        tag = "✅" if ok else ("⚠️ " if warn_only else "❌")
        print("  %s %-26s %s" % (tag, name, detail))
        if not ok:
            (warns if warn_only else fails).append(name)

    print("AI-OS 验证器")
    print("  仓库: %s" % slashes(REPO))

    # ── 1. 配置 ──────────────────────────────────────────────────────────
    sec("1. 配置")
    home = dsh_home()
    item("DSH home", bool(home), home or "未找到 ~/.dsh")
    patch_found, patch_ok, pointed = None, False, False
    if home:
        base = os.path.join(home, "profiles")
        hits = []
        if os.path.isdir(base):
            for n in sorted(os.listdir(base)):
                p = os.path.join(base, n, "cordis.patch.yml")
                if os.path.isfile(p) and BEGIN in read_text(p):
                    hits.append((n, p))
        if hits:
            patch_found = ", ".join(n for n, _ in hits)
            patch_ok = True
            for _n, p in hits:
                t = read_text(p)
                if (slashes(REPO) + "/.claude/hooks.json" in t
                        and "file:///" + slashes(REPO) + "/runtime/aios-activation.ts" in t
                        and END in t):
                    pointed = True
        item("补丁块", patch_ok, "profile: %s" % patch_found if patch_ok else "未找到 focusroute 补丁块 ⇒ 先跑 tools/install.py --apply")
        if patch_ok:      # 无块时不再重复报"路径不符"（那与"无块"是同一件事）
            item("路径指向本仓库", pointed,
                 "configPath / file:/// 均指向本仓库" if pointed
                 else "补丁块里的路径与当前仓库**不一致**（仓库被移动过？重跑 install.py --apply）")
    hj = os.path.join(REPO, ".claude", "hooks.json")
    htxt = read_text(hj)
    # ⚠️ JSON 里 Windows 路径是 `<repo>\\…`（双反斜杠）⇒ 先归一化再比对，
    #    否则「写对了但被 JSON 转义」会被误判成失败（实际踩到）。
    hnorm = htxt.replace("\\\\", "/").replace("\\", "/")
    h_ok = bool(htxt) and ("${CLAUDE_PROJECT_DIR}" in htxt
                           or slashes(REPO) + "/tools/aios-hook.py" in hnorm)
    item("hooks.json", h_ok,
         "含 ${CLAUDE_PROJECT_DIR} 或本仓库绝对路径（两种都合法）" if h_ok
         else "既没有 ${CLAUDE_PROJECT_DIR}，也不指向本仓库 tools/aios-hook.py")
    # 🔴 （审计）：`${CLAUDE_PROJECT_DIR}` 的展开者是 hooks 插件在**配置解析期**做字符串替换，
    #   前提是插件配置里写了 `projectDir`。只写 configPath 时 Windows(PowerShell) 把 `${VAR}` 当未定义变量
    #   ⇒ 命令里的路径变空 ⇒ `python /tools/aios-hook.py …` ⇒ hook **静默失败**（只 logger.warn）。
    #   证据：dsh-hooks-claude-code `lib/index.js:143-146`（只有 projectDir !== undefined 才传给解析器）
    #        与 `:35`（`out.split("${CLAUDE_PROJECT_DIR}").join(vars.projectDir)`）。
    if patch_found:
        for _n, p in hits:
            t = read_text(p)
            i = t.find("hooks-claude-code")
            if i < 0:
                continue
            window = t[i:i + 900]
            ok_pd = "projectDir:" in window
            item("hooks 桥 projectDir", ok_pd,
                 "补丁块含 projectDir ⇒ ${CLAUDE_PROJECT_DIR} 会被展开" if ok_pd
                 else "补丁块**缺 projectDir** ⇒ Windows 上该变量变空 ⇒ hook 静默失败（重跑 tools/install.py --apply）")
            break

    # ── 2. 依赖 ──────────────────────────────────────────────────────────
    sec("2. 依赖")
    item("python", sys.version_info >= (3, 8), "%d.%d.%d" % sys.version_info[:3])
    rc, out, _e = run(["node", "--version"], timeout=30)
    item("node", rc == 0, (out or "").strip() or "未找到（DSH 自身依赖）")
    item("工具入口", os.path.isfile(os.path.join(REPO, "tools", "aios-hook.py")), "tools/aios-hook.py")
    has_probes = os.path.isdir(os.path.join(REPO, "tools", "probes"))
    item("机制探针", os.path.isfile(os.path.join(REPO, "tools", "probes", "_field_emit.py")),
         "tools/probes/" if has_probes else "本仓库未包含 tools/probes/（非接入必需 · 降级为知悉项）",
         warn_only=True)
    item("自测夹具", os.path.isfile(os.path.join(REPO, "tools", "probes", "fixtures",
                                                "zh_skill_registry.fixture.json")),
         "tools/probes/fixtures/" if has_probes else "同上（跳过）", warn_only=True)
    idx = os.path.join(REPO, ".aios", "_zh_name_index.json")
    item("名称索引", os.path.isfile(idx),
         "已生成" if os.path.isfile(idx) else "未生成（需 .aios/_zh_skill_registry.json；缺失时 field_candidates fail-open）",
         warn_only=True)

    # ── 3. 工具自测 ──────────────────────────────────────────────────────
    sec("3. 工具自测")
    rc, out, err = run([sys.executable, os.path.join(REPO, "tools", "task_start.py")])
    first = (out.strip().splitlines() or [""])[0]
    item("task_start（无参）", rc == 0, first[:70] or (err.strip()[:70]))
    # ⛔ 不含 Stop：Stop 会触发 wrapup_writeback（真实写回），属有副作用调用 —— 不拿它做自测。
    for ev in ("SessionStart", "UserPromptSubmit"):
        rc, out, err = run([sys.executable, os.path.join(REPO, "tools", "aios-hook.py"), ev])
        item("aios-hook %s" % ev, rc == 0, "rc=0（无 stdout = 开关全关，属正常）" if rc == 0 else err.strip()[:70])
    if not args.quick and os.path.isdir(os.path.join(REPO, "tools", "probes")):
        # `want` = **回退判据**（输出里没有 `selftest` JSON 结构时才用）；`field_producer`
        # 打印的是人读文本 ⇒ 保留期望串；另两个探针输出 selftest JSON ⇒ 留空串，
        # 强制走结构判据（拿不到结构就判失败，不靠猜）—— 修判据漂移。
        for name, script, want in (("field_producer", "_runtime_field_producer.py", "12/12"),
                                   ("retrieval_request", "_retrieval_request_probe.py", ""),
                                   ("capability_discovery", "_capability_discovery_probe.py", "")):
            p = os.path.join(REPO, "tools", "probes", script)
            rc, out, err = run([sys.executable, p, "--selftest"])
            ok, detail = selftest_verdict(want, rc, out, err)
            item("probe %s" % name, ok, detail)

    # ── 4. 插件活性（ℹ️ 参考信息 · ⛔ 不参与通过判定）──────────────────────
    sec("4. 插件活性（ℹ️ 仅供参考 · 不参与通过判定）")
    cands = [os.path.join(REPO, ".aios", "_aios-activation.probe.log")]
    if home:
        cands.append(os.path.join(home, "_aios-activation.probe.log"))
    now = datetime.datetime.now()
    live = []
    for c in cands:
        if os.path.isfile(c):
            age = (now - datetime.datetime.fromtimestamp(os.path.getmtime(c))).total_seconds() / 60.0
            live.append((c, age))
    if live:
        print("  📄 探针日志最近写入 %.1f 分钟前（%d 处）" % (min(a for _c, a in live), len(live)))
        for c, age in live:
            print("      %-56s %.1f 分钟前" % (slashes(c), age))
    else:
        print("  📄 两处探针日志都不存在")
    print("""
  ⚠️ 判据局限（如实标注）：探针日志**不含副本标识** —— 它只能说明「有 aios-activation 在写日志」，
     ⛔ **不能**证明是本仓库这一份。故本项不计入通过 / 失败。
     要确认真实生效：重启 DSH → 在会话里发一条消息 → 看下面两条是否成立：
       · 探针日志出现新的写入时间
       · 打开某项能力（改 `.claude/aios-exposure.json`）后，会话里能看到对应内容""")

    # ── 5. 结论 ──────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    if not fails:
        print("✅ 验证通过 —— 接入可用。")
        if warns:
            print("   ⚠️ 需你知悉的 %d 项（非阻断）：%s" % (len(warns), " · ".join(warns)))
        print("   提示：能力默认全关；要启用改 `.claude/aios-exposure.json`（一行即生效）。")
        return 0
    print("❌ 有 %d 项未通过：%s" % (len(fails), " · ".join(fails)))
    print("""
   常见处理：
     · 补丁块缺失/路径不符 ⇒  python tools/install.py --apply  然后**重启 DSH**
     · 探针自测失败        ⇒  多半是 `.aios/` 或 fixtures 缺失；重跑 install 或检查文件是否完整
     · 名称索引未生成      ⇒  提供 .aios/_zh_skill_registry.json 后跑
                              python tools/probes/_zh_name_index_build.py
     · 插件活性未知        ⇒  重启 DSH，随便发一条消息，再跑本命令""")
    return 1


if __name__ == "__main__":
    sys.exit(main())
