# -*- coding: utf-8 -*-
"""能力来源探针：卡上**必填字段「能力」** vs 它到底从哪来（自己读 / 检索工具 / 注入到达）。

用户 2026-11-02 定：只需要卡上一个明确要求填的字段（能力），然后看它是**自己去找**还是**用检索工具**。
本探针把"来源"分成四类，避免把"注入给了它"误读成"它自己找的"：

  | 来源 | 判据（该会话的 probe 事件） |
  |---|---|
  | **自己读** | `tool-sig.pathClass` = `capabilities/<能力名>.md`（读的就是卡上记的那个） |
  | **检索后选** | 有 `retrieval-corpus` 事件（`auto_capability` 同步检索）且记录值命中其候选/兜底 |
  | **注入到达** | 该会话有 `phase-inject/node-inject{state:"injected", capability:<卡上那个>}`，但**没有读它** |
  | **无** | 以上都没有 |

用法：
    python tools/probes/_capability_source_probe.py                    # 当前仓库
    python tools/probes/_capability_source_probe.py --root <clone>
    python tools/probes/_capability_source_probe.py --root <clone> --json
"""
import argparse
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CARD_CAP = re.compile(r"^-\s*能力[:：]\s*`?([^`\s｜|]+)`?", re.M)
CARD_ADOPT = re.compile(r"^-\s*投递采用[:：]\s*`?([^`\n]*)", re.M)
CARD_CLAIM = re.compile(r"claim 占用（session:\s*([0-9a-zA-Z\-]+)）")
READ_CAP = re.compile(r"capabilities/([A-Za-z0-9_\-]+)\.md")


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--json", action="store_true")
    return ap.parse_args()


def load_probe(root):
    p = os.path.join(root, ".aios", "_aios-activation.probe.log")
    rows = []
    if not os.path.isfile(p):
        return rows
    for line in io.open(p, encoding="utf-8", errors="replace"):
        try:
            rows.append(json.loads(line.split("] ", 1)[1]))
        except Exception:
            continue
    return rows


def ts(r):
    v = r.get("t") or (float(r["at"]) / 1000.0 if r.get("at") else 0.0)
    return float(v)


def cards_of(root):
    out = []
    base = os.path.join(root, "task_cards", "active")
    for dirpath, _dn, files in os.walk(base):
        for f in files:
            if not f.endswith(".md"):
                continue
            p = os.path.join(dirpath, f)
            t = io.open(p, encoding="utf-8", errors="replace").read()
            m = CARD_CAP.search(t)
            if not m:
                continue
            cap = m.group(1).strip()
            if cap in ("（未记录）", ""):
                cap = ""
            adopt = CARD_ADOPT.search(t)
            log = p[:-3] + ".log"
            session, cap_min = None, None
            if os.path.isfile(log):
                lt = io.open(log, encoding="utf-8", errors="replace").read()
                claims = CARD_CLAIM.findall(lt)
                session = claims[-1] if claims else None
                for line in lt.split("\n"):
                    if "| 能力 |" in line:
                        mm = re.match(r"\|\s*(\d{1,2}):(\d{2})\s*\|", line)
                        if mm:
                            cap_min = int(mm.group(1)) * 60 + int(mm.group(2))
            out.append({
                "card": os.path.relpath(p, root).replace("\\", "/"),
                "capability": cap,
                "adopted": (adopt.group(1).strip() if adopt else ""),
                "session": session,
                "cap_min": cap_min,
            })
    return out


def classify(card, rows):
    sess = card["session"]
    evs = [r for r in rows if r.get("session") == sess] if sess else []
    read_caps = set()
    for r in evs:
        if r.get("ev") != "tool-sig":
            continue
        m = READ_CAP.search(str(r.get("pathClass", "")))
        if m and "_archive" not in str(r.get("pathClass", "")):
            read_caps.add(m.group(1))
    inj_caps = set()
    for r in evs:
        if r.get("ev") in ("phase-inject", "node-inject") and r.get("state") == "injected":
            if r.get("capability"):
                inj_caps.add(r["capability"])
    n_retr = sum(1 for r in evs if r.get("ev") == "retrieval-corpus")
    # 读证据是否可判：子会话在别的工作区根下时，probe 只记父目录前缀（如 `<clone 前缀>/`，文件名丢失）
    read_tools = [r for r in evs if r.get("ev") == "tool-sig"
                  and r.get("tool") in ("read", "grep")
                  and r.get("pathClass") not in (None, "")]
    unresolved = [r for r in read_tools if "capabilities" not in str(r.get("pathClass", ""))]
    cap = card["capability"]
    if cap and cap in read_caps:
        src = "自己读"
    elif n_retr:
        src = "检索后选"
    elif cap and cap in inj_caps:
        src = "注入到达（读证据不可判）" if unresolved else "注入到达（未读）"
    elif unresolved:
        src = "读证据不可判"
    elif cap:
        src = "无（填了但无证据）"
    else:
        src = "未记录"
    return {
        "source": src,
        "read_caps": sorted(read_caps),
        "injected_caps": sorted(inj_caps),
        "retrieval_n": n_retr,
        "read_file": (cap in read_caps),
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    args = parse_args()
    rows = load_probe(args.root)
    cards = cards_of(args.root)
    out = []
    for c in cards:
        r = dict(c)
        r.update(classify(c, rows))
        out.append(r)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print("能力来源探针 —— 卡上必填「能力」字段 vs 来源")
    print("root:", os.path.abspath(args.root), "| 有提交记录卡:", len(out))
    print()
    print("%-42s %-20s %-16s %-10s %s" % ("卡", "能力（必填）", "来源", "检索次数", "投递采用"))
    for r in out:
        print("%-42s %-20s %-16s %-10s %s" % (
            r["card"][-42:], (r["capability"] or "(空)")[:20], r["source"],
            r["retrieval_n"], (r["adopted"] or "(未填)")[:26]))
    print()
    from collections import Counter
    cnt = Counter(r["source"] for r in out)
    for k, v in cnt.most_common():
        print("  %-18s %d" % (k, v))
    print("\n判读：`自己读` = 卡上那个能力文件真被打开过；`注入到达（未读）` = 靠注入文案用上、没读全文；"
          "`检索后选` = 调用过检索工具；`无（填了但无证据）` = 字段填了但既没读也没检索也没注入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
