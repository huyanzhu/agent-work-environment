# -*- coding: utf-8 -*-
"""semantic_search.py — AI-OS 经验检索的「语义层」离线实现（hybrid = 词面 + 向量）

WHY
  纯词面 recall 对「同场景不同说法」覆盖不足。读数（paraphrase 8 条经验 × 3 档）：
  原词 8/8 · 换词 4/8 · **语义 2/8** ⇒ 词面已到天花板。
  bge-small-zh-v1.5（512 维 · fastembed 0.9.0）原型把语义档提到 5/8，但：
    · 每次 spawn 独立进程 ⇒ 模型加载 0.85~1.2s，贴着 的 2s timeout；
    · 单用向量会引入误召回（N=30 质量表）⇒ 必须词面 + 向量混合。
  本模块 = 离线层：预计算语料向量存盘 + 纯函数融合，**可回归验证**。
  ⛔ 不改 Runtime（接入需 约定+ 重启）。

WHAT
  · build_corpus()     —— 与 tools/experience_push.py 完全同源（PITFALLS / digest / 账本 / 文件类）
  · Embedder           —— 懒加载 bge；passage / query 两种编码
  · build/save/load    —— 预计算索引（向量 + 元数据 + 指纹），语料变了能检出
  · lexical_map()      —— **复用** experience_push 的打分与闸门（⛔ 不写第二套规则）
  · score_query()      —— 一次查询 → 每条候选的（词面分, 余弦相似度, 命中词）
  · select_hits()      —— **纯函数**：融合 / 去重 / 接受判据 / 排序
  · retrieve()         —— 组合（查询侧）

USAGE（需要 fastembed + onnxruntime 的 venv；已核实：demo-project venv）
  $env:PYTHONIOENCODING='utf-8'
  # 建索引（语料变更后重跑；一次性）
  & <venv-python> tools/probes/semantic_search.py build
  # 单条查询（JSON，形状对齐 experience_push --stdin-json）
  & <venv-python> tools/probes/semantic_search.py query "跑测试时权限被拒绝 临时文件夹删不掉" -n 3
  # 纯函数自测（不加载模型，repo python 即可）
  python tools/probes/semantic_search.py selftest

PATH NOTE（转正）
  本文件已从 `scratch/` 转正到 `tools/probes/`；`scratch/semantic_search.py` 留 runpy 薄壳，
  旧命令仍可用。路径**按本文件所在仓库位置解析**，⛔ 不依赖 CWD、⛔ 不写死 `scratch/`：
  · 索引基址 = `AIOS_SEMANTIC_INDEX`（不带扩展名）或 `<repo>/scratch/semantic-index/experience-corpus-v1`
  · 模型缓存 = `SEMANTIC_CACHE_DIR` 或 `<repo>/scratch/fastembed_cache`
  （索引/缓存是产物，留 `scratch/` 不进 git；**入口脚本**已在版本控制里 ⇒ 换机/克隆后命令仍在。）

ENV NOTE
  fastembed 的 cache_dir 默认取 TEMP/fastembed_cache，**不吃 HF_HOME**；
  本机 DSH 沙箱下 TEMP 不可写 ⇒ 必须显式 cache_dir。模型已缓存在
  `scratch/fastembed_cache`（0.85s 加载）。可用 SEMANTIC_CACHE_DIR 覆盖。
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time

#: 仓库根：本文件在 `<repo>/tools/probes/` ⇒ 上三级 = 仓库根（⛔ 不写死盘符、⛔ 不看 CWD）
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(ROOT, "tools")
for _p in (TOOLS, HERE):          # HERE 优先：同名兄弟模块都在本目录
    if _p not in sys.path:
        sys.path.insert(0, _p)

import experience_push as E  # noqa: E402  （复用词面打分/闸门/tokenize —— 唯一实现）

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
INDEX_VERSION = 1
DEFAULT_CACHE_DIR = os.environ.get("SEMANTIC_CACHE_DIR") or os.path.join(ROOT, "scratch", "fastembed_cache")
#: 索引默认落仓库根的 `scratch/`（产物不进 git）；换机 / 自定义位置用 `AIOS_SEMANTIC_INDEX` 覆盖（不带扩展名）。
DEFAULT_INDEX_BASE = (os.environ.get("AIOS_SEMANTIC_INDEX")
                      or os.path.join(ROOT, "scratch", "semantic-index", "experience-corpus-v1"))

#: bge v1.5 检索式 query instruction（**只在 query 侧加**，passage 侧不加）。
# 读数（scratch/_probe_embed_variants.py）：core 语料 top1 语义档 5/8 → 6/8，top3-any 7/8 → 8/8。
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

#: 语义通道默认只覆盖「可注入的经验条目」（PITFALLS + digest）——
# 949 条 proven 账本 chunk 在向量空间里互相高度相似，会把精选经验挤掉（读数 语义档 top1=Entry #59）。
#: ⚠️ 推荐配置的**候选空间**同样是 core（见下）；若要「词面全语料 + 向量 core」的混合形态，
# 传 `sources=None`（读数 N=30 误报 12→14，不满足判据）。
DEFAULT_SEMANTIC_SOURCES = ("pitfall", "digest")

#: 推荐配置的**候选空间**（两通道都只看 core 经验库）—— 任务定义的「经验库」范围。
#: ⚠️ 若保留全语料词面候选（sources=None），同一 joint 配置在 N=30 上误报 12→14（+2），
# **不满足**「N=30 误报不升」判据 —— 见 `SEMANTIC-RETRIEVAL-OFFLINE-.md §三`。
DEFAULT_CANDIDATE_SOURCES = DEFAULT_SEMANTIC_SOURCES

#: 融合/接受配置（字段含义见 fuse_score / accept_score）。
#: ⚠️ 默认值 = `scratch/_calib_semantic.py` 标定结果（见读数文档 §融合标定）；⛔ 未标定前不得当已验证。
DEFAULT_CFG = {
    "mode": "joint",      # lexical | vector | gated | joint | sum | max | product
    "w_lex": 0.6,         # 词面通道权重（sum/max 用；gated/joint 仅影响排序）
    "w_vec": 0.4,         # 向量通道权重（同上）
    "lex_scale": 8.0,     # 词面分归一化尺度（= 典型相关分 ~8）
    "sim_floor": 0.45,    # 向量相似度下限（低于它向量通道 = 0）
    "sim_gate": 0.55,     # joint/gated/vector：向量通道单独放行门槛（instruction 尺度）
    "sim_low": 0.35,      # joint：词面候选还要求的最低向量 sim（挡「词面误报」的低相关候选）
    "lex_min": 6.0,       # joint/gated/lexical：词面通道放行门槛（与运行时 min=6.0 同参）
    "min_fused": 0.30,    # sum/max/product：融合分放行门槛
}

#: 短条目（chunk / 摘要）= 一句能照做 ⇒ inject；整篇文件 ⇒ pointer（与 experience_push.form_of 同口径）
INJECT_KINDS = frozenset(("pitfall", "digest", "ledger", "proven"))


def form_of(kind):
    return "inject" if kind in INJECT_KINDS else "pointer"


def _rel(path):
    try:
        return os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:
        return path


def _read(path):
    try:
        return io.open(path, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# 语料（与 experience_push 同源；确定性顺序 ⇒ 索引可对齐）
# ─────────────────────────────────────────────────────────────────────────────

def _chunk_entry(kind, path, weight, title, body, seq):
    return {
        "id": "%s|%s|%s#%d" % (kind, _rel(path), title, seq),
        "kind": kind,
        "source": _rel(path),
        "weight": float(weight),
        "title": title,
        "body": body,
        "raw": "",
        "embed_text": (title + " " + body)[:1600],
    }


def _file_entry(file_kind, path):
    raw = _read(path)
    fm, body = E.parse_frontmatter(raw)
    title = fm.get("title", "").strip() or os.path.basename(path)
    # 向量文本 = 标题 + 高权重 frontmatter 字段 + 正文开头（与词面打分的字段口径一致）
    head = " ".join(x for x in (
        title,
        fm.get("trigger", ""),
        fm.get("keywords", ""),
        fm.get("condition", ""),
        fm.get("alias", ""),
    ) if x)
    return {
        "id": "file|%s" % _rel(path),
        "kind": file_kind,          # pattern / experience / task_card
        "source": _rel(path),
        "weight": 1.0,
        "title": title,
        "body": "",
        "raw": raw,
        "embed_text": (head + " " + body[:1400])[:2000],
    }


def build_corpus():
    """→ list[dict]（顺序确定）。chunk 的 id 含源文件+标题；文件类 id 含路径。

    ⚠️ ledger 同一 header 会有多 chunk（与运行时一致；排序时按 (source,title) 去重取最高分）。
    """
    corpus = []
    # 同一 header 下会有多条 chunk（账本 Entry 多 bullet）⇒ id 必须带序号，否则会被去重误吞
    seq = {}

    def add_chunk(kind, path, weight, title, text):
        key = (kind, _rel(path), title)
        n = seq.get(key, 0)
        seq[key] = n + 1
        corpus.append(_chunk_entry(kind, path, weight, title, text, n))

    for path, weight, header, text in E.collect_pitfall_chunks():
        add_chunk("pitfall", path, weight, header, text)
    for path, weight, header, text in E.collect_digest_chunks():
        add_chunk("digest", path, weight, header, text)
    for path, weight, header, text in E.collect_ledger_chunks():
        kind = "proven" if weight >= E.PROVEN_LEDGER_WEIGHT else "ledger"
        add_chunk(kind, path, weight, header or kind, text)
    for file_kind, path in E.collect_files():
        corpus.append(_file_entry(file_kind, path))
    # 去重 id（理论唯一；防御性保留首次）
    seen, out = set(), []
    for e in corpus:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        out.append(e)
    return out


def corpus_fingerprint(corpus):
    """语料指纹：id + embed_text 的 sha1（语料变更 ⇒ 索引失效可检出）。"""
    h = hashlib.sha1()
    for e in corpus:
        h.update(("%s\t%s\n" % (e["id"], e["embed_text"])).encode("utf-8"))
    return h.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# 嵌入（懒加载）
# ─────────────────────────────────────────────────────────────────────────────

class Embedder:
    """bge-small-zh-v1.5 的懒加载封装（fastembed 默认已归一化；这里再归一化一次防版本差异）。"""

    def __init__(self, model_name=MODEL_NAME, cache_dir=DEFAULT_CACHE_DIR):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model = None

    def _ensure(self):
        if self._model is None:
            from fastembed import TextEmbedding  # 仅查询/建索引时才需要
            self._model = TextEmbedding(self.model_name, cache_dir=self.cache_dir)
        return self._model

    @property
    def dim(self):
        return 512

    def embed_passages(self, texts, batch_size=64):
        import numpy as np
        model = self._ensure()
        out = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            out.extend(model.embed(batch))
        v = np.asarray(out, dtype="float32")
        norms = np.linalg.norm(v, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return v / norms

    def embed_query(self, text, prefix=""):
        import numpy as np
        payload = (prefix + text) if prefix else text
        v = np.asarray(list(self._ensure().embed([payload])), dtype="float32")
        n = np.linalg.norm(v, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return (v / n)[0]


# ─────────────────────────────────────────────────────────────────────────────
# 索引（预计算向量存盘）
# ─────────────────────────────────────────────────────────────────────────────

def build_index(corpus, embedder, log=print):
    t0 = time.time()
    texts = [e["embed_text"] for e in corpus]
    if log:
        log("[index] embedding %d passages ..." % len(texts))
    vectors = embedder.embed_passages(texts)
    meta = {
        "version": INDEX_VERSION,
        "model": embedder.model_name,
        "dim": int(vectors.shape[1]),
        "count": len(corpus),
        "fingerprint": corpus_fingerprint(corpus),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": round(time.time() - t0, 2),
    }
    entries = [{"id": e["id"], "kind": e["kind"], "source": e["source"],
                "title": e["title"], "weight": e["weight"]} for e in corpus]
    return {"meta": meta, "entries": entries, "vectors": vectors}


def save_index(index, base=DEFAULT_INDEX_BASE):
    import numpy as np
    os.makedirs(os.path.dirname(os.path.abspath(base)), exist_ok=True)
    np.save(base + ".npy", index["vectors"])
    payload = {"meta": index["meta"], "entries": index["entries"]}
    with io.open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return base + ".npy", base + ".json"


def load_index(base=DEFAULT_INDEX_BASE, corpus=None):
    """加载索引；给 corpus 时校验指纹（语料变了 ⇒ 抛错，⛔ 不静默用陈旧向量）。"""
    import numpy as np
    npy, meta_path = base + ".npy", base + ".json"
    if not (os.path.isfile(npy) and os.path.isfile(meta_path)):
        raise FileNotFoundError("index missing: %s (.npy/.json)。先跑 build。" % base)
    vectors = np.load(npy)
    with io.open(meta_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    meta, entries = payload["meta"], payload["entries"]
    if meta.get("version") != INDEX_VERSION:
        raise ValueError("index version %r != %r" % (meta.get("version"), INDEX_VERSION))
    if vectors.shape[0] != len(entries) != meta.get("count"):
        raise ValueError("index count mismatch: vectors=%d entries=%d meta=%r"
                         % (vectors.shape[0], len(entries), meta.get("count")))
    if corpus is not None:
        fp = corpus_fingerprint(corpus)
        if fp != meta.get("fingerprint"):
            raise ValueError("index stale: 语料指纹 %s != 索引 %s ⇒ 重跑 build" % (fp, meta.get("fingerprint")))
    return {
        "meta": meta,
        "entries": entries,
        "vectors": vectors,
        "id_to_row": {e["id"]: i for i, e in enumerate(entries)},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 词面通道（复用 experience_push —— 唯一规则实现）
# ─────────────────────────────────────────────────────────────────────────────

def lexical_map(query_tokens, corpus):
    """→ {entry_id: (词面分, 有效命中 set)}，只保留「过闸门」的候选（与运行时 search() 同口径）。

    · chunk 类：weight × score_ledger_chunk（PITFALLS 4.8 / digest 4.8 / 账本 4.0~5.0）
    · 文件类：score_file（frontmatter 字段权重 + 正文；不乘 weight）
    """
    out = {}
    for e in corpus:
        if e["kind"] in ("pattern", "experience", "task_card"):
            res = E.score_file(query_tokens, e["raw"])
            if res.score > 0 and E.passes_gate(query_tokens, res):
                out[e["id"]] = (res.score, res.effective)
        else:
            res = E.score_ledger_chunk(query_tokens, e["title"], e["body"])
            if res.score > 0 and E.passes_gate(query_tokens, res):
                out[e["id"]] = (e["weight"] * res.score, res.effective)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 查询侧：一次打分，多种配置复用（标定脚本靠这个；避免反复跑模型）
# ─────────────────────────────────────────────────────────────────────────────

def score_query(query, corpus, index, embedder, sources=None, query_prefix=QUERY_PREFIX):
    """→ (scored list, reason)。每条 scored: id/kind/source/title/body/lex/matched/sim。

    query_prefix: bge v1.5 检索 instruction（默认加；传 "" 可关，用于对照）。
    reason: None | 'empty-query' | 'no-signal:<tokens>'（与 experience_push 一致：无信号不做检索）。
    """
    qtokens = E.tokenize(query)
    if not qtokens:
        return [], "empty-query"
    if not E.query_has_signal(qtokens):
        eff_q = sorted(E.effective_query_tokens(qtokens))[:6]
        return [], "no-signal:" + "/".join(eff_q)

    lex_map = lexical_map(qtokens, corpus)
    qv = embedder.embed_query(query, prefix=query_prefix)
    sims = index["vectors"] @ qv
    id2row = index["id_to_row"]

    scored = []
    for e in corpus:
        if sources and e["kind"] not in sources:
            continue
        lex, matched = lex_map.get(e["id"], (0.0, frozenset()))
        row = id2row.get(e["id"])
        sim = float(sims[row]) if row is not None else 0.0
        scored.append({
            "id": e["id"], "kind": e["kind"], "source": e["source"], "title": e["title"],
            "body": e["body"], "lex": float(lex), "matched": set(matched), "sim": sim,
        })
    return scored, None


# ─────────────────────────────────────────────────────────────────────────────
# 融合 / 接受 / 排序（纯函数 · 可单测）
# ─────────────────────────────────────────────────────────────────────────────

def _norm_lex(score, scale):
    if scale <= 0:
        return 0.0
    return min(1.0, max(0.0, float(score) / float(scale)))


def _norm_vec(sim, floor):
    if floor >= 1.0:
        return 0.0
    return max(0.0, (float(sim) - float(floor)) / (1.0 - float(floor)))


def fuse_score(lex, sim, cfg=None):
    """融合分。mode:
    · sum     = w_lex·L̂ + w_vec·V̂        （线性加权）
    · max     = max(w_lex·L̂, w_vec·V̂)     （任一通道强即可）
    · product = L̂·V̂                        （字面「词面分 × 向量 sim」，会杀纯语义候选）
    · gated   = 同 sum（gated 的放行由 accept_score 单独判）
    · joint   = 同 sum（joint 的放行见 accept_score：词面候选需最低 sim）
    · lexical = L̂                           （纯词面基线）
    · vector  = V̂                           （纯向量基线）
    L̂ = min(1, lex/lex_scale) · V̂ = max(0, (sim-sim_floor)/(1-sim_floor))
    """
    c = _cfg(cfg)
    ln = _norm_lex(lex, c["lex_scale"])
    vn = _norm_vec(sim, c["sim_floor"])
    mode = c["mode"]
    if mode == "lexical":
        return ln
    if mode == "vector":
        return vn
    if mode == "product":
        return ln * vn
    if mode == "max":
        return max(c["w_lex"] * ln, c["w_vec"] * vn)
    return c["w_lex"] * ln + c["w_vec"] * vn


def accept_score(lex, sim, fused, cfg=None, vector_ok=True):
    """接受判据（是否返回该候选）。

    gated = 词面过阈值 **或** 向量过高门槛；
    joint = （词面过阈值 **且** 真实 sim ≥ sim_low）**或**（向量过高门槛）。
    vector_ok: 该条目是否允许走**向量通道**（由 vector_sources 过滤）；为 False 时向量分支不生效。
      ⚠️ 词面分支用的是**真实 sim**（sim_low 是「词面候选的最低语义相关度」），
         与向量分支的「候选池」是两件事 —— 非 core 条目仍可凭词面通道进入。
    """
    c = _cfg(cfg)
    mode = c["mode"]
    if mode == "lexical":
        return lex >= c["lex_min"]
    if mode == "vector":
        return bool(vector_ok) and sim >= c["sim_gate"]
    if mode == "gated":
        return lex >= c["lex_min"] or (bool(vector_ok) and sim >= c["sim_gate"])
    if mode == "joint":
        # 词面候选要求具备最低语义相关度（挡纯词面误报）；或向量通道单独高门槛放行
        return (lex >= c["lex_min"] and sim >= c["sim_low"]) or (bool(vector_ok) and sim >= c["sim_gate"])
    return fused >= c["min_fused"]


def _cfg(cfg):
    c = dict(DEFAULT_CFG)
    if cfg:
        c.update(cfg)
    return c


def select_hits(scored, cfg=None, n=3, dedup=True, vector_sources=None):
    """纯函数：融合 → 去重（(source,title) 取最高融合分，与运行时 R2 同口径）→ 排序 → top n。

    vector_sources: 语义通道只在这些 kind 上生效（None = 全部）。
      非向量池的条目 sim 在**融合排序**里按 0 计（不靠向量分占位），但**词面通道照常生效**；
      joint 模式下词面候选另需真实 sim ≥ sim_low（见 accept_score）。
    返回 list[dict]：scored 字段 + fused + sim_used；按 (-fused, -lex, -sim) 排序。
    """
    c = _cfg(cfg)
    rows = []
    for s in scored:
        vec_ok = (vector_sources is None or s["kind"] in vector_sources)
        sim_used = s["sim"] if vec_ok else 0.0
        fused = fuse_score(s["lex"], sim_used, c)
        if accept_score(s["lex"], s["sim"], fused, c, vector_ok=vec_ok):
            r = dict(s)
            r["fused"] = fused
            r["sim_used"] = sim_used
            rows.append(r)
    if dedup:
        best = {}
        for r in rows:
            key = (r["source"], r["title"])
            # 同分时用原始词面分兜底（归一化会把 8 和 10 都截到 1.0；运行时是按原始分去重的）
            if key not in best or (r["fused"], r["lex"]) > (best[key]["fused"], best[key]["lex"]):
                best[key] = r
        rows = list(best.values())
    rows.sort(key=lambda r: (-r["fused"], -r["lex"], -r["sim"]))
    return rows[:n]


def hit_payload(row):
    """→ 与 experience_push --stdin-json 对齐的 hit 形状（多带 lexical_score/sim/sim_used 便于读数）。"""
    k = row["kind"]
    form = form_of(k)                       # "inject" | "pointer"
    return {
        "score": round(row["fused"], 4),
        "lexical_score": round(row["lex"], 2),
        "sim": round(row["sim"], 4),
        "sim_used": round(row.get("sim_used", row["sim"]), 4),
        "kind": k,
        "title": row["title"],
        "file": row["source"],
        # ⚠️ pointer = 只给指针（正文不注入）；form 是字符串，必须显式比较，⛔ 不能写 if form
        "content": row["body"][:240] if form == "inject" else "",
        "matched": sorted(row["matched"])[:8],
        "form": form,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 查询入口
# ─────────────────────────────────────────────────────────────────────────────

def retrieve(query, corpus, index, embedder, cfg=None, n=3, sources=DEFAULT_CANDIDATE_SOURCES,
             query_prefix=QUERY_PREFIX, vector_sources=DEFAULT_SEMANTIC_SOURCES):
    """→ (hits, reason)。hits 已是展示形状（hit_payload）。

    sources=None ⇒ 全语料候选（词面全量 + 向量 core）；默认 = core 经验库（推荐配置的候选空间）。
    """
    scored, reason = score_query(query, corpus, index, embedder, sources=sources,
                                 query_prefix=query_prefix)
    if reason:
        return [], reason
    rows = select_hits(scored, cfg, n=n, vector_sources=vector_sources)
    return [hit_payload(r) for r in rows], None


# ─────────────────────────────────────────────────────────────────────────────
# 自测（纯函数；不加载模型 / 不需要索引）
# ─────────────────────────────────────────────────────────────────────────────

def selftest(verbose=True):
    ok = 0

    def check(name, cond):
        nonlocal ok
        if not cond:
            raise AssertionError("FAIL: " + name)
        ok += 1
        if verbose:
            print("  ok  " + name)

    # 归一化
    check("norm_lex cap", _norm_lex(16, 8) == 1.0)
    check("norm_lex half", abs(_norm_lex(4, 8) - 0.5) < 1e-9)
    check("norm_vec floor", _norm_vec(0.4, 0.5) == 0.0)
    check("norm_vec top", abs(_norm_vec(0.6, 0.5) - 0.2) < 1e-9)

    # 融合形状
    cfg_sum = {"mode": "sum", "w_lex": 0.6, "w_vec": 0.4, "lex_scale": 8.0, "sim_floor": 0.4}
    l_hi = fuse_score(8.0, 0.4, cfg_sum)     # 词面满分，向量无贡献
    l_lo = fuse_score(0.0, 0.9, cfg_sum)     # 纯向量
    check("sum: lexical vs vector independent", l_hi > 0.59 and l_lo > 0.32)
    check("product kills pure vector", fuse_score(0.0, 0.99, {"mode": "product"}) == 0.0)
    check("max takes strongest channel", abs(fuse_score(0.0, 1.0, {"mode": "max", "sim_floor": 0.0}) - 0.4) < 1e-9)

    # 接受判据
    gated = {"mode": "gated", "lex_min": 6.0, "sim_gate": 0.6}
    check("gated: lexical channel", accept_score(6.5, 0.1, 0.0, gated) is True)
    check("gated: vector channel", accept_score(0.0, 0.61, 0.0, gated) is True)
    check("gated: both weak reject", accept_score(5.9, 0.59, 0.0, gated) is False)

    # 去重 + 排序（纯函数，不依赖语料）
    def cand(i, source, title, lex, sim):
        return {"id": i, "kind": "pitfall", "source": source, "title": title,
                "body": "b", "lex": lex, "matched": set(), "sim": sim}
    scored = [
        cand("a", "f.md", "T1", 8.0, 0.30),
        cand("b", "f.md", "T1", 10.0, 0.30),   # 同 (source,title) 但分更高 ⇒ 保留 b
        cand("c", "f.md", "T2", 0.0, 0.80),    # 纯向量候选（gated 放行）
        cand("d", "f.md", "T3", 0.0, 0.10),    # 两通道都弱 ⇒ 丢弃
    ]
    rows = select_hits(scored, {"mode": "gated", "lex_min": 6.0, "sim_gate": 0.6}, n=3)
    ids = [r["id"] for r in rows]
    check("dedup keeps best", "b" in ids and "a" not in ids)
    check("vector-only allowed in gated", "c" in ids)
    check("weak dropped", "d" not in ids)
    check("n respected", len(rows) == 2)

    # vector_sources 只限制「向量通道」，不限制「词面通道」（独立复核 OBS-1 的回归）
    joint = {"mode": "joint", "lex_min": 6.0, "sim_low": 0.35, "sim_gate": 0.55,
             "lex_scale": 8.0, "sim_floor": 0.45, "w_lex": 0.6, "w_vec": 0.4}

    def row(i, kind, lex, sim):
        return {"id": i, "kind": kind, "source": "s", "title": i, "body": "b",
                "lex": lex, "matched": set(), "sim": sim}

    mixed = [
        row("core-lex", "pitfall", 8.0, 0.20),   # core：词面过闸但 sim < sim_low ⇒ 拒
        row("core-vec", "pitfall", 0.0, 0.60),   # core：向量通道 ⇒ 收
        row("file-lex", "pattern", 8.0, 0.50),   # 非 core：**词面通道仍生效**（真实 sim 过 sim_low）
        row("file-vec", "pattern", 0.0, 0.90),   # 非 core：向量通道关闭 ⇒ 拒（哪怕 sim 很高）
    ]
    rows = select_hits(mixed, joint, n=5, vector_sources=("pitfall", "digest"))
    ids = {r["id"] for r in rows}
    check("joint: non-core reachable via lexical", "file-lex" in ids)
    check("joint: non-core blocked from vector", "file-vec" not in ids)
    check("joint: lexical needs sim_low", "core-lex" not in ids)
    check("joint: core vector works", "core-vec" in ids)

    # hit_payload：pointer 正文恒空（独立复核 OBS-4 的回归）
    payload = hit_payload({"kind": "pattern", "title": "t", "source": "f.md", "body": "正文",
                           "fused": 0.5, "lex": 6.0, "sim": 0.2, "matched": set()})
    check("pointer content empty", payload["content"] == "" and payload["form"] == "pointer")

    # 语料确定性 + id 唯一（真实语料，只读）
    c1, c2 = build_corpus(), build_corpus()
    check("corpus deterministic", [e["id"] for e in c1] == [e["id"] for e in c2])
    check("corpus id unique", len({e["id"] for e in c1}) == len(c1))
    check("corpus non-empty", len(c1) > 100)
    check("fingerprint stable", corpus_fingerprint(c1) == corpus_fingerprint(c2))

    print("\nselftest: %d checks OK · corpus=%d entries" % (ok, len(c1)))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def cmd_build(args):
    corpus = build_corpus()
    kinds = {}
    for e in corpus:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print("[corpus] %d entries · %s" % (len(corpus), ", ".join("%s=%d" % kv for kv in sorted(kinds.items()))))
    emb = Embedder()
    index = build_index(corpus, emb)
    npy, meta = save_index(index, args.index_base)
    print("[index] saved %s (%.2fs) + %s" % (npy, index["meta"]["elapsed_s"], meta))
    print("[index] meta: %s" % json.dumps(index["meta"], ensure_ascii=False))
    return 0


def cmd_query(args):
    corpus = build_corpus()
    index = load_index(args.index_base, corpus=corpus)
    emb = Embedder()
    if args.sources.strip().lower() == "all":
        sources = None
    else:
        sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    hits, reason = retrieve(args.query, corpus, index, emb, cfg=DEFAULT_CFG, n=args.n, sources=sources)
    out = {"ok": True, "reason": reason, "hits": hits, "n": len(hits), "sources": list(sources) if sources else "all"}
    print(json.dumps(out, ensure_ascii=False))
    return 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="AI-OS 语义检索离线层（hybrid 词面+向量 · 只读）")
    ap.add_argument("--index-base", default=DEFAULT_INDEX_BASE)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("build", help="预计算语料向量并存盘")
    q = sub.add_parser("query", help="单条查询（JSON 输出）")
    q.add_argument("query")
    q.add_argument("-n", type=int, default=3)
    q.add_argument("--sources", default="pitfall,digest",
                   help="候选空间（kind 逗号分隔；all=全语料。⚠️ 实测 all 形态 N=30 误报 12→14）")
    sub.add_parser("selftest", help="纯函数自测（不加载模型）")

    args = ap.parse_args(argv)
    if args.cmd == "build":
        return cmd_build(args)
    if args.cmd == "query":
        return cmd_query(args)
    return selftest()


if __name__ == "__main__":
    sys.exit(main())
