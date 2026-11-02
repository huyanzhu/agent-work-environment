# 离线复现 field_candidates 的检索段（只读 · 不改机制）
# 用途：在"三道门"之外单看 卡字段 → 对象 → 候选 的质量（评估注入准确性）
# ⚠️ ：本文件是**顶层脚本式**（import 即执行）⇒ ⛔ 不要 `import _inject_dryrun`。
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

# ── 路径解析（执行层自 `scratch/` 迁入 `tools/probes/` · 参数化）─────────
#    优先级：`AIOS_ROOT` 环境变量 ▸ 本文件位置（`<root>/tools/probes/`）▸ 工作目录。
_root_env = os.environ.get("AIOS_ROOT")
if _root_env and _root_env.strip():
    AIOS_ROOT = os.path.abspath(_root_env.strip())
else:
    _cand = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    AIOS_ROOT = _cand if os.path.isfile(os.path.join(_cand, "tools", "experience_push.py")) \
        else os.path.dirname(os.path.abspath(__file__))
PROBES = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(AIOS_ROOT, "tools")
CACHE = os.environ.get("AIOS_STATE_DIR") or os.path.join(AIOS_ROOT, ".aios")
sys.path.insert(0, TOOLS)
sys.path.insert(0, PROBES)

import _runtime_field_producer as fp          # noqa: E402
import experience_push as ep                  # noqa: E402
import wrapup_sync as ws                      # noqa: E402

idx_path = os.path.join(CACHE, "_zh_name_index.json")   # 生成物已迁至 `.aios/`
with open(idx_path, encoding="utf-8") as f:
    idx = json.load(f)

out = []
out.append("index items = %s" % idx.get("n"))

# 卡唯一性判据（项目目录口径）
proj = "task_cards/active/demo-project"
cards_in_proj = ws.cards_in_dir(os.path.join(AIOS_ROOT, proj))
out.append("cards_in_dir(%s) = %d -> %s" % (
    proj, len(cards_in_proj),
    ", ".join(os.path.basename(c) for c in cards_in_proj)))

# git 推导口径（hook 在 cwd 未映射时走这条）
cards_git, why = ws.candidates_from_git()
out.append("candidates_from_git = %d -> %s" % (len(cards_git), why))

for rel in sys.argv[1:]:
    fld = fp.produce_from_card(rel)
    out.append("")
    out.append("== %s" % rel)
    out.append("object=%s | confidence=%s | degraded=%s | source=%s"
               % (fld.get("object"), fld.get("confidence"), fld.get("degraded"), fld.get("source")))
    out.append("phrases=%s" % (fld.get("phrases"),))
    out.append("categories=%s" % (fld.get("categories"),))
    out.append("reasons=%s" % (fld.get("reasons"),))
    phrases = fld.get("phrases") or []
    if fld.get("degraded") or not phrases:
        out.append("  ⇒ 门②（字段非退化）会拦：不进入检索")
        continue
    cats = set(fld.get("categories") or [])
    best = {}
    for ph in phrases:
        pt, _ = ep.split_hits(ep.tokenize(ph))
        for it in idx.get("items") or []:
            if cats and it.get("cat") not in cats:
                continue
            n = len(pt & set(it.get("t") or []))
            if n and n > best.get(it.get("id"), (0, it))[0]:
                best[it.get("id")] = (n, it)
    rows = sorted(best.values(), key=lambda r: (-r[0], str(r[1].get("name"))))
    out.append("pool=%d (门③阈值 FIELD_POOL_MIN=50 ⇒ %s)"
               % (len(rows), "过" if len(rows) >= 50 else "拦"))
    for n, it in rows[:5]:
        toks = set(it.get("t") or [])
        hit_ph = max(phrases, key=lambda ph: len(ep.split_hits(ep.tokenize(ph))[0] & toks))
        hit = sorted(ep.split_hits(ep.tokenize(hit_ph))[0] & toks)
        out.append("  TOP %-28s [%s] hits=%d :: %s"
                   % (it.get("name"), it.get("cat"), n, "/".join(hit[:6])))

dst = os.path.join(AIOS_ROOT, "scratch", "_inject_dryrun_out.txt")
with open(dst, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("wrote " + dst)
