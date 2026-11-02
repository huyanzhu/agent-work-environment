#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""hook_trace.py —— DSH 会话轨迹取证（**只读**）：三个 Hook 事件到底有没有真触达？

为什么需要它（不是推测）：

1. **`SessionStart` 的 `hook/invoked` / `hook/result` 结构性不写轨迹。**
   `packages/hooks/hooks-claude-code/src/index.ts` 只在 `opts.turn !== undefined`
   时才 `appendHookInvoked` / `appendHookResult`（L156 / L180），而 SessionStart 的
   调用点在 `ctx.on('agent/session-start')`（L205）——**不传 turn**。
   ⇒ 它唯一的 L1 证据是**注入消息**（`source.kind === 'plugin'`，见 L86 / L194）。
   本工具专门检出它，避免把「轨迹里没有」误读成「没触发」。

2. **会话文件 `session.v3.jsonl.zstd` 是多帧 zstd（逐段追加写）。**
   Node 的 `zstdDecompressSync` 一次只出第一帧，其余帧报
   `ZSTD_error_prefix_unknown: Unknown frame descriptor`。
   ⇒ 必须按魔数 `28 b5 2f fd` 切帧、逐帧解压（本机读数：单会话 294 帧 / 零失败）。
   错误做法（一次性整文件解压）会**静默只得到 2 行**，足以让人得出错误结论。

用法：

    python tools/hook_trace.py                 # 汇总：每个会话的事件计数 + 注入条数
    python tools/hook_trace.py --inject        # 额外打印注入消息正文（前 300 字）
    python tools/hook_trace.py --json          # 机器可读输出
    python tools/hook_trace.py --sessions-dir <路径>

退出码：0 = 至少有一个会话可读；1 = 找不到会话目录 / node 不可用。只读，不改任何文件。
"""
import argparse
import json
import os
import subprocess
import sys

# 与 packages/.../install.py 的 check_yaml 同模式：把重活交给 node，Python 只做编排。
NODE_JS = r"""
const fs = require("fs"), path = require("path"), zlib = require("zlib");
const base = process.argv[1];
const M = [0x28, 0xb5, 0x2f, 0xfd];
function walk(dir, d) {
  d = d || 0; let out = [];
  if (d > 4) return out;
  let es = [];
  try { es = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return out; }
  for (const e of es) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out = out.concat(walk(p, d + 1));
    else if (p.endsWith(".zstd")) out.push(p);
  }
  return out;
}
function decode(p) {
  const buf = fs.readFileSync(p);
  const offs = [];
  for (let i = 0; i + 3 < buf.length; i++) {
    if (buf[i] === M[0] && buf[i+1] === M[1] && buf[i+2] === M[2] && buf[i+3] === M[3]) offs.push(i);
  }
  let t = "", bad = 0;
  for (let k = 0; k < offs.length; k++) {
    const s = offs[k], e = k + 1 < offs.length ? offs[k+1] : buf.length;
    try { t += zlib.zstdDecompressSync(buf.subarray(s, e)).toString("utf8"); } catch (err) { bad++; }
  }
  return { text: t, frames: offs.length, bad };
}
const res = [];
for (const f of walk(base)) {
  const st = fs.statSync(f);
  const d = decode(f);
  const lines = d.text.split(/\r?\n/).filter(Boolean);
  const events = {}, inject = [];
  for (const l of lines) {
    if (l.indexOf('"hook/') >= 0) {
      try {
        const o = JSON.parse(l);
        if (o.type === "hook/invoked" || o.type === "hook/result") {
          const key = o.type.replace("hook/", "") + ":" + ((o.data && o.data.point) || "?");
          events[key] = (events[key] || 0) + 1;
        }
      } catch (e) {}
    }
    if (l.indexOf('"plugin":"hooks-claude-code"') >= 0) inject.push(l.slice(0, 4000));
  }
  res.push({ file: f, mtime: st.mtimeMs, frames: d.frames, badFrames: d.bad, lines: lines.length, events, inject });
}
process.stdout.write(JSON.stringify(res));
"""


def sessions_dir(explicit):
    if explicit:
        return os.path.abspath(explicit)
    home = os.environ.get("DSH_HOME")
    if not home or not os.path.isdir(home):
        home = os.path.join(os.path.expanduser("~"), ".dsh")
    return os.path.join(home, "sessions")


def short(path, base):
    rel = os.path.relpath(path, base)
    parts = rel.split(os.sep)
    if len(parts) >= 2:
        return "%s  (%s)" % (parts[-2][:28], parts[0])
    return rel


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="DSH 会话轨迹取证（只读）")
    ap.add_argument("--sessions-dir", default=None)
    ap.add_argument("--inject", action="store_true", help="打印注入消息正文前 300 字")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    base = sessions_dir(args.sessions_dir)
    if not os.path.isdir(base):
        print("⛔ 找不到会话目录：%s" % base)
        return 1
    try:
        r = subprocess.run(["node", "-e", NODE_JS, base], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
    except Exception as exc:
        print("⛔ 调用 node 失败：%s" % exc)
        return 1
    if r.returncode != 0 or not (r.stdout or "").strip():
        print("⛔ node 取证失败（rc=%s）：%s" % (r.returncode, (r.stderr or "")[:400]))
        return 1
    data = json.loads(r.stdout)
    data.sort(key=lambda d: -d["mtime"])

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print("DSH 会话轨迹取证（只读）· %s" % base)
    agg = {"SessionStart": 0, "UserPromptSubmit": 0, "Stop": 0}
    for d in data:
        ev = d["events"]
        ups = ev.get("invoked:UserPromptSubmit", 0)
        stp = ev.get("invoked:Stop", 0)
        inj = len(d["inject"])
        if ups:
            agg["UserPromptSubmit"] += 1
        if stp:
            agg["Stop"] += 1
        if inj:
            agg["SessionStart"] += 1
        print("── %s" % short(d["file"], base))
        print("   帧 %d（失败 %d）· 行 %d · UserPromptSubmit %d/%d · Stop %d/%d · 注入 %d%s"
              % (d["frames"], d["badFrames"], d["lines"],
                 ev.get("invoked:UserPromptSubmit", 0), ev.get("result:UserPromptSubmit", 0),
                 ev.get("invoked:Stop", 0), ev.get("result:Stop", 0),
                 inj, "   ← SessionStart 证据" if inj else ""))
        if args.inject and inj:
            for l in d["inject"][:1]:
                try:
                    o = json.loads(l)
                    dd = o.get("data", {})
                    blocks = list(dd.get("content") or [])
                    for ins in dd.get("inserted") or []:
                        blocks.extend(ins.get("content") or [])
                    text = " ".join(b.get("text", "") for b in blocks if isinstance(b, dict))
                except Exception:
                    text = l
                print("   注入> %s" % text[:300].replace("\n", " "))
    print("\n汇总（有证据的会话数）：SessionStart(注入) %d · UserPromptSubmit %d · Stop %d"
          % (agg["SessionStart"], agg["UserPromptSubmit"], agg["Stop"]))
    print("说明：SessionStart 只有「注入」这一种证据（它结构性不写 hook/result）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
