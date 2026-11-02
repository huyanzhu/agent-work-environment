# -*- coding: utf-8 -*-
"""_scene_probe.py — 场景探针 v0（**族级**：出现 / 漏召回 / 误报）

只回答三个问题（对齐 口径）：
  1) 该场景期望的**经验族**出现了吗（top1 / top3）
  2) 漏了吗（top3 里都没有该族）
  3) 误报吗（top1 有返回但不是该族）
⛔ **不测**「族内选了哪条行/哪条经验」—— 那是 Agent 消费层，机械读不到、自述不可信（//）。

对比两个检索器（同一批场景）：
  · lexical = `experience_push.search(q, 3, 6.0)`（当前运行时词面通道）
  · hybrid  = `semantic_search.retrieve(...)`（离线语义层 · core 经验库 · joint 配置）

用法（⚠️ 需要 fastembed ⇒ 用 venv python；repo python 会在建 Embedder 时 ModuleNotFoundError）：
  & $VENV tools/probes/_scene_probe.py            # 跑并打印；快照写 <repo>/scratch/_scene_probe_snapshot.json
  & $VENV tools/probes/_scene_probe.py --check    # 与上次快照对比，读数变化则提示（回归用）

PATH NOTE（转正）
  本文件已从 `scratch/` 转正到 `tools/probes/`；`scratch/_scene_probe.py` 留 runpy 薄壳（旧命令等价）。
  路径一律**按本文件所在仓库位置解析**，⛔ 不写死盘符、⛔ 不看 CWD、⛔ 不写死 `scratch/`：
  · 导入：`tools/`（experience_push）+ 本目录（semantic_search —— 已同批转正）
  · 快照 = `AIOS_SCENE_PROBE_SNAPSHOT` 或 `<repo>/scratch/_scene_probe_snapshot.json`（产物不进 git）
"""
import io
import json
import os
import sys

#: 仓库根：本文件在 `<repo>/tools/probes/` ⇒ 上三级 = 仓库根
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (os.path.join(ROOT, "tools"), HERE):   # HERE 优先：semantic_search 在本目录
    if _p not in sys.path:
        sys.path.insert(0, _p)

import experience_push as E  # noqa: E402
import semantic_search as S  # noqa: E402

#: 快照（回归对比用）默认落 `scratch/`（产物不进 git）；可用 AIOS_SCENE_PROBE_SNAPSHOT 覆盖。
SNAPSHOT = (os.environ.get("AIOS_SCENE_PROBE_SNAPSHOT")
            or os.path.join(ROOT, "scratch", "_scene_probe_snapshot.json"))

# ── 经验族定义（v0：只做权限族；族 = 一组「同一问题域」的经验条目，等族卡落地后换成单元 id）──
FAMILIES = {
    "权限族": {
        "note": "沙箱/权限拒绝（语料里现有 2 类做法：提权 / 换位置）；2026-11-01 族卡转正后并入族卡单元",
        "entries": {
            ("pitfall", "PITFALLS P12"),
            ("pitfall", "PITFALLS P40"),
            ("pitfall", "PITFALLS P57"),
            ("pattern", "权限/Sandbox 相关错误时请求提权而非绕过"),
            ("digest", "DIGEST 权限/沙箱错误"),
            # 02:3x pilot 族卡 + digest 一行已进语料（转正）：
            # 同族 = 同一问题域的一组条目，族卡单元与旧条目都算「族出现」
            ("digest", "DIGEST 权限/沙箱错误族"),
            ("experience", "权限/沙箱错误族（先对号入座，再照做）"),
        },
    },
    "编码族": {
        "note": "中文乱码/编码错误（写坏 / 读错 / 传丢 三类做法）；2026-11-01 04:5x **转正（加卡+digest，保留旧条目）**，族卡 = domains/experiences/encoding_errors_family.md",
        "entries": {
            ("pitfall", "PITFALLS P13"),
            ("pitfall", "PITFALLS P54"),
            ("pitfall", "PITFALLS P56"),
            ("pitfall", "PITFALLS P68"),
            ("digest", "DIGEST Windows 上写中文文件"),
            ("experience", "中文文件不乱码的四条硬规则"),
            # 04:5x 转正后的族卡单元
            ("digest", "DIGEST 中文乱码/编码错误族"),
            ("experience", "遇到中文乱码/编码错误（改文件、读输出、重定向都算）"),
            ("pitfall", "PITFALLS P91"),
            ("pitfall", "PITFALLS P94"),
        },
    },
    "推送族": {
        "note": "推送/发布（git·gh·PR）；2026-11-01 04:4x 转正（加卡+digest，保留旧条目）· 05:5x 族收敛（拆出「对外文案/账本」D 段 ⇒ 卡题去掉「对外交付都算」）· 06:2x 收尾：D 段的三条坑（P39/P44/P47）与三个 D 类场景同步移出（P85 同代纪律）",
        "entries": {
            ("pitfall", "PITFALLS P14"),
            ("pitfall", "PITFALLS P37"),
            ("pitfall", "PITFALLS P41"),
            ("pitfall", "PITFALLS P42"),
            ("pitfall", "PITFALLS P43"),
            ("pitfall", "PITFALLS P71"),
            ("pitfall", "PITFALLS P88"),
            # 04:4x 转正后的族卡单元（05:5x 族收敛后卡题去掉「对外交付都算」⇒ 同步更新， 纪律）
            ("digest", "DIGEST 推送/发布族"),
            ("experience", "遇到推送/发布问题（git · gh · PR 都算）"),
        },
    },
    "任务卡族": {
        "note": "🟢 2026-11-01 05:1x **已撤族卡**（接 Human 判断：机制修好后这些坑不再发生 ⇒ 族卡冗余）——本族仅作**监测基线**保留（只看旧条目，不再期望族卡单元出现）",
        "entries": {
            ("pitfall", "PITFALLS P1"),
            ("pitfall", "PITFALLS P2"),
            ("pitfall", "PITFALLS P18"),
            ("pitfall", "PITFALLS P51"),
            ("pitfall", "PITFALLS P52"),
            ("pitfall", "PITFALLS P61"),
            # 同族但 A/B 未纳入的（Runtime 看卡/焦点卡类 · 探针按"同问题域"计入族）
            ("pitfall", "PITFALLS P19"),
            ("pitfall", "PITFALLS P23"),
            ("pitfall", "PITFALLS P24"),
            ("pitfall", "PITFALLS P26"),
            ("pitfall", "PITFALLS P27"),
        },
    },
    "工具族": {
        "note": "工具使用/参数误用；2026-11-01 05:1x 转正（**加卡但无 digest** —— digest 会让 N=30 误报 +1）",
        "entries": {
            ("pitfall", "PITFALLS P20"),
            ("pitfall", "PITFALLS P22"),
            ("pitfall", "PITFALLS P37"),
            ("pitfall", "PITFALLS P46"),
            ("pitfall", "PITFALLS P65"),
            ("pitfall", "PITFALLS P66"),
            ("experience", "遇到工具调用/参数用错（编辑·写文件·命令参数都算）"),
            ("pitfall", "PITFALLS P92"),
            ("pitfall", "PITFALLS P95"),
        },
    },
    "Runtime 族": {
        "note": "Runtime 改造；2026-11-01 05:1x 转正（**加卡无 digest**）；节点触发 = 编辑 runtime/*.ts（v49q 已验证加载）；06:0x 补 P83/P84 期望条目（P85 纪律：语料新增须与期望集同代）",
        "entries": {
            ("pitfall", "PITFALLS P6"),
            ("pitfall", "PITFALLS P17"),
            ("pitfall", "PITFALLS P35"),
            ("pitfall", "PITFALLS P49"),
            ("pitfall", "PITFALLS P67"),
            ("pitfall", "PITFALLS P69"),
            ("pitfall", "PITFALLS P70"),
            ("pitfall", "PITFALLS P72"),
            ("pitfall", "PITFALLS P83"),
            ("pitfall", "PITFALLS P84"),
            ("experience", "改 Runtime/注入管道时（改本体 · 加触发点 · 写注入段都算）"),
        },
    },
    "自检与判据": {
        "note": "判读读数/判据/统计口径；2026-11-01 06:1x **转正**（离线 A/B 7/7 PASS：B2 x 编码 14/14·漏0·误报0；只上族卡、无 digest）· 覆盖真实任务里 7/9 的失败形态（原 5 族只覆盖 2/9）",
        "entries": {
            ("pitfall", "PITFALLS P5"),
            ("pitfall", "PITFALLS P7"),
            ("pitfall", "PITFALLS P8"),
            ("pitfall", "PITFALLS P19"),
            ("pitfall", "PITFALLS P58"),
            ("pitfall", "PITFALLS P63"),
            ("pitfall", "PITFALLS P73"),
            ("pitfall", "PITFALLS P74"),
            ("pitfall", "PITFALLS P75"),
            ("pitfall", "PITFALLS P85"),
            ("pitfall", "PITFALLS P86"),
            ("digest", "DIGEST 交接写「待重启」前先读最后一条 `ev=apply`"),
            ("experience", "判读读数与判据时（自检 · 期望集 · 统计口径都算）"),
            ("pitfall", "PITFALLS P93"),
            ("pitfall", "PITFALLS P96"),
            ("pitfall", "PITFALLS P97"),
            ("pitfall", "PITFALLS P98"),
        },
    },
}

# ── 场景样本（原词 / 换词 / 语义 三档 · 纪律）────────────────────────────
SCENES = [
    # pytest 临时目录
    ("权限族", "原词", "在 DSH 工作区跑 pytest 报 PermissionError WinError 5 临时目录 rmtree"),
    ("权限族", "换词", "跑测试时临时文件夹删不掉 提示拒绝访问"),
    ("权限族", "语义", "测试报错说没有权限 好像是系统临时文件的问题"),
    # Chrome 无头导出
    ("权限族", "原词", "Chrome 无头 print-to-pdf 报 crashpad_client_win 拒绝访问"),
    ("权限族", "换词", "无头浏览器导出 PDF 静默失败 沙箱"),
    ("权限族", "语义", "想把网页导成 PDF 但浏览器一启动就崩"),
    # tempfile / 系统临时区
    ("权限族", "原词", "tempfile.mkdtemp PermissionError 系统临时区"),
    ("权限族", "换词", "程序写临时文件被拒绝 说没有权限"),
    ("权限族", "语义", "要建临时目录 但工具说没权限"),
    # 通用 sandbox 拒绝
    ("权限族", "原词", "PermissionError [WinError 5] 拒绝访问 sandbox"),
    ("权限族", "换词", "沙箱拒绝写工作区外 文件动不了"),
    ("权限族", "语义", "工具说我权限不够 不让我改文件"),
    # 提权后仍失败（族内兜底行）
    ("权限族", "原词", "提权后仍然 PermissionError danger-full-access 还是失败"),
    ("权限族", "语义", "已经放开了权限 怎么还是说拒绝访问"),

    # ── 编码族（场景取自 scratch/_ab_families.py · 原词/换词/语义三档 · 纪律）──
    ("编码族", "原词", "PowerShell Get-Content 读中文 md 出现乱码 默认编码"),
    ("编码族", "原词", "PowerShell 5.1 重定向 > 写 UTF-16 编码错误 中文"),
    ("编码族", "原词", "PowerShell 整文读写 UTF-8 源文件 中文 mojibake BOM 行尾"),
    ("编码族", "原词", "中文文件 mojibake UTF-8 可解码 内容损坏 不可还原"),
    ("编码族", "换词", "命令行写文件后中文变成乱码 引号也消失"),
    ("编码族", "换词", "用 PowerShell 改中文文件 编码被搞坏 读回全是怪字"),
    ("编码族", "换词", "命令输出存成 JSON 之后读不了 编码不对 中文乱码"),
    ("编码族", "换词", "文档中文全坏了 还能恢复原始内容吗"),
    ("编码族", "语义", "写进去的中文变成了奇怪符号"),
    ("编码族", "语义", "改了中文文档之后打开全是乱码"),
    ("编码族", "语义", "命令行里传中文内容被吃掉 怎么都写不对"),
    ("编码族", "语义", "文件编码错了 现在想救回原来的中文"),
    ("编码族", "语义", "整个文件的中文都不对了 想确认是不是编码问题"),
    ("编码族", "语义", "读回来的中文是问号和方块 原来是好好的"),

    # ── 推送族（场景取自 scratch/_ab_families.py「推送/发布」· 三档 · 纪律）──
    ("推送族", "原词", "gh api 带 -f 查询被当 POST accepts 1 arg(s) received 3"),
    ("推送族", "原词", "gh api endpoint 分支名带斜杠 404 ref"),
    ("推送族", "原词", "git push fatal error couldn't create signal pipe Win32 error 5 credential helper"),
    ("推送族", "原词", "删 JSON 字段留 trailing comma verify 报不是合法 JSON"),
    ("推送族", "换词", "推送代码时一直让我输用户名 沙箱里不弹凭据"),
    ("推送族", "换词", "用 gh 查分支里的文件 明明传上去了却 404"),
    ("推送族", "换词", "本地这份源码和上游不一样 提交前要核对是不是夹带别人的改动"),
    ("推送族", "语义", "提交到远程仓库失败 说读不到账号"),
    ("推送族", "语义", "问 GitHub 接口拿数据 结果报参数数量不对"),
    ("推送族", "语义", "发布前想确认我这次改动里没有别人的东西"),
    ("推送族", "语义", "命令行里那段 jq 查询被 shell 吞了"),

    # ── 任务卡族（场景取自 scratch/_ab_families.py「任务卡占用与状态」· 三档 · 纪律）──
    ("任务卡族", "原词", "task_card.py claim 报 ID 在多个项目下重名"),
    ("任务卡族", "原词", "task_card.py create 后直接 claim 被拒 State=Created"),
    ("任务卡族", "原词", "claim release 后同一回合 edit 同一张卡 file changed since it was read"),
    ("任务卡族", "原词", "DSH 重启后任务卡仍显示 Executing 孤儿占用"),
    ("任务卡族", "换词", "新建的任务卡不能直接认领 状态不对"),
    ("任务卡族", "换词", "认领任务卡提示重名 该用哪个标识"),
    ("任务卡族", "换词", "刚占用的卡改不了 工具让我重读"),
    ("任务卡族", "换词", "重启后卡一直显示进行中 没人释放"),
    ("任务卡族", "语义", "刚建的卡说要先改状态才能接手"),
    ("任务卡族", "语义", "两个项目里有同名任务卡 占卡时分不清"),
    ("任务卡族", "语义", "改卡时提示文件在我读完之后被改过"),
    ("任务卡族", "语义", "上次会话异常退出 卡还占着 怎么回收"),
    ("任务卡族", "语义", "占卡时探针里没有 card-cmd 事件 是不是没占上"),
    ("任务卡族", "语义", "焦点卡接口停在旧会话 还能信吗"),

    # ── 工具族（场景取自 scratch/_ab_families.py「工具使用/参数误用」· 三档）──
    ("工具族", "原词", "write 对已删除的同路径文件报 file no longer exists re-read the file then retry"),
    ("工具族", "原词", "大块 edit 把相邻注释块开头一起吞掉 语法断裂"),
    ("工具族", "原词", "pwsh Select-Object -First 20 提前关管道 进程非零退出"),
    ("工具族", "原词", "PowerShell echo; 空调用报 missing mandatory parameters"),
    ("工具族", "换词", "删了临时脚本想用同名重建 写入被拒 还让我先读"),
    ("工具族", "换词", "改完一个函数 注释尾巴悬空了 编译不过"),
    ("工具族", "换词", "命令明明成功 但退出码是 1 输出被截断"),
    ("工具族", "换词", "gh api 的 jq 参数被 shell 吃掉 报解析 json 失败"),
    ("工具族", "语义", "工具说文件不存在 可我明明刚删了想重建"),
    ("工具族", "语义", "改完代码跑不起来 像是括号或注释断了"),
    ("工具族", "语义", "输出只看到一半 是不是命令被提前掐断了"),
    ("工具族", "语义", "命令行里带引号的查询参数总是传不进去"),
    ("工具族", "语义", "给工具传了错的参数 它没报错 跑到深处才炸"),
    ("工具族", "语义", "想复用同一个文件名 但工具不让写"),

    # ── Runtime 族（场景取自 scratch/_ab_families.py「Runtime 改造」· 三档）──
    ("Runtime 族", "原词", "块作用域变量跨 try 引用 ReferenceError 被 catch 吞掉 注入静默失效"),
    ("Runtime 族", "原词", "post-execute 注入段 spawn python 未隔离 异步测试级联失败"),
    ("Runtime 族", "原词", "frontmatter 解析 跨行吞掉下一行 块式列表读成 1 条"),
    ("Runtime 族", "原词", "水平状态做节流 状态抖动 同一句注入 18 次"),
    ("Runtime 族", "换词", "加了新触发点 探针一条都没有 也不报错"),
    ("Runtime 族", "换词", "改完后 ev=apply 和上次一模一样 不知道加载没"),
    ("Runtime 族", "换词", "子 agent 的 knownCardKeys 是空的 新触发点被整块跳过"),
    ("Runtime 族", "换词", "cardKeyOfId 返回的 key 带 .md 拼 .log 路径失败"),
    ("Runtime 族", "语义", "注入没出现 也没有任何报错 像是被吞了"),
    ("Runtime 族", "语义", "只加了命令识别 但工具实际接受另一种写法 所以没触发"),
    ("Runtime 族", "语义", "改完本体忘了升版本串 重启后也判不出新旧"),
    ("Runtime 族", "语义", "测试全绿 但真实注入一次都没到"),
    ("Runtime 族", "语义", "解析配置时少读了一整条 数目对不上"),
    ("Runtime 族", "语义", "提醒每隔几步就重复一次"),

    # ── 自检与判据族（06:1x 转正 · 场景取自 scratch/_ab_families.py 同名族 · 三档 4/4/6）──
    ("自检与判据", "原词", "hybrid 只回传 kind/title ⇒ _rel 三段判定失效 读数 8/7/7 掉成 8/5/5"),
    ("自检与判据", "原词", "族卡替换后场景探针 FAMILIES 期望集没同步 词面 top1 11 掉到 2 假回归"),
    ("自检与判据", "原词", "交接写 v48 待重启 实际最后一条 ev=apply policy 已含 +v48-return-tune"),
    ("自检与判据", "原词", "CARD_CMD_RE.exec 只取首个匹配 一次 pwsh 多条 claim 只记第一条"),
    ("自检与判据", "换词", ".aios/focus-card.json 停在旧会话 读到的 session 和 cardKey 都是老的"),
    ("自检与判据", "换词", "探针读的是 profile 那份 log 混进别的 root 读数 和真实不一致"),
    ("自检与判据", "换词", "只用 turnHadSuccess 判有改动 只读卡跑只读命令也算 判据不对"),
    ("自检与判据", "换词", "给语料加了一条 单条 query 的纯向量相似度被顶过阈值 只超 0.0043 就多一条误报"),
    ("自检与判据", "语义", "图表上全绿 可真实情况正好相反 结论是反的"),
    ("自检与判据", "语义", "我改了语料的条目 结果探针读数一下掉很多 但检索其实没变差"),
    ("自检与判据", "语义", "交接文档说还要重启 核了一下发现新版本早就跑起来了"),
    ("自检与判据", "语义", "那个状态文件里写的还是上次会话的卡 能不能信它"),
    ("自检与判据", "语义", "统计只按第一条算 后面几条都没算进去"),
    ("自检与判据", "语义", "想给族卡补覆盖 写在同义现象里 结果语义通道那条根本没读到"),
]


def _fams_of(kind, title):
    """返回该条目**所属的全部族**（多标签）。

    修正（tool-fp 读数）： 同时被推送族与工具族认领，
    旧的 `_fam_of` 只取 FAMILIES 遍历顺序里第一个命中的族 ⇒ 另一族把它判成「误报 + 错族 + 漏」，
    两族都会被系统性扣分。改为多标签后：top1 只要「本族在 top1 条目的族集合里」就算命中。
    """
    return [fam for fam, spec in FAMILIES.items() if (kind, title) in spec["entries"]]


def _lexical_hits(q, n=3):
    top, _reason = E.search(q, n, 6.0)
    return [{"kind": k, "title": t} for _s, k, _p, t, _m, _a in (top or [])]


def _hybrid_hits(q, corpus, index, emb, n=3):
    hits, _reason = S.retrieve(q, corpus, index, emb, cfg=S.DEFAULT_CFG, n=n)
    return [{"kind": h["kind"], "title": h["title"]} for h in hits]


def _agg(rows):
    agg = {"top1": 0, "top3": 0, "miss": 0, "fp": 0, "wrong_family": 0}
    for r in rows:
        agg["top1"] += int(r["top1_hit"])
        agg["top3"] += int(r["top3_hit"])
        agg["miss"] += int(r["miss"])
        agg["fp"] += int(r["fp"])
        agg["wrong_family"] += int(r["wrong_family"])
    return agg


def _eval(hits_by_query):
    rows = []
    for fam, tier, q in SCENES:
        hits = hits_by_query(q)
        fams = [_fams_of(h["kind"], h["title"]) for h in hits]     # 每条的族集合（多标签）
        top1 = bool(fams) and fam in fams[0]
        top3 = any(fam in f for f in fams[:3])
        miss = not top3
        fp = bool(hits) and fam not in (fams[0] if fams else [])
        wrong_family = bool(fams) and bool(fams[0]) and fam not in fams[0]
        rows.append({
            "family": fam, "tier": tier, "query": q,
            "top1_hit": top1, "top3_hit": top3, "miss": miss, "fp": fp,
            "wrong_family": wrong_family,
            "hits": hits,
            "top1_family": "/".join(fams[0]) if fams and fams[0] else None,
        })
    return rows, _agg(rows)


def _print_result(label, rows, agg):
    n = len(rows)
    print("\n【%s】族级读数（N=%d 场景）" % (label, n))
    print("  top1 族出现 %d/%d · top3 族出现 %d/%d · 漏召回 %d · 误报(top1) %d（其中错族 %d）"
          % (agg["top1"], n, agg["top3"], n,
             agg["miss"], agg["fp"], agg["wrong_family"]))
    print("  %-4s %-3s %-42s %-6s %-6s %-4s %s" % ("族", "档", "场景", "top1", "top3", "漏", "top1 实际"))
    for r in rows:
        mark1 = "HIT" if r["top1_hit"] else ("FP" if r["fp"] else "-")
        mark3 = "HIT" if r["top3_hit"] else ("MISS" if r["miss"] else "-")
        top = r["hits"][0]["title"] if r["hits"] else "(无召回)"
        print("  %-4s %-3s %-42s %-6s %-6s %-4s %s"
              % (r["family"], r["tier"], r["query"][:42], mark1, mark3,
                 "Y" if r["miss"] else "-", top[:34]))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    corpus = S.build_corpus()
    # 🔴 （clone 可用性）：缺 fastembed / 索引缺失时**给可读指引**，⛔ 不吐 traceback。
    #   本脚本已转正进版本控制 ⇒ 新用户会直接跑它；repo python 没有 fastembed 是常态，
    #   给一段"怎么办"比 30 行栈有用（退出码 2 = 环境未就绪，不是读数失败）。
    #   ⚠️ `S.Embedder()` 是**懒加载**（真正 import 发生在其 `_ensure()`），所以必须显式预检。
    try:
        import fastembed  # noqa: F401
    except ModuleNotFoundError:
        print("[scene-probe] 跳过：未安装 fastembed（语义/混合通道需要它；词面通道不需要）。")
        print("  · 只跑词面通道：python tools/experience_push.py \"<查询>\"")
        print("  · 要跑完整回归门：用装了 fastembed 的解释器")
        print("      <venv>/python tools/probes/semantic_search.py build")
        print("      <venv>/python tools/probes/_scene_probe.py")
        print("  · 说明见 QUICKSTART.md §1（fastembed 属可选依赖）")
        return 2
    try:
        index = S.load_index(S.DEFAULT_INDEX_BASE, corpus=corpus)
        emb = S.Embedder()
    except ModuleNotFoundError as e:
        print("[scene-probe] 跳过：缺依赖 `%s`（语义/混合通道需要 fastembed）。" % e.name)
        print("  · 只跑词面通道：python tools/experience_push.py \"<查询>\"（不需要 fastembed）")
        print("  · 要跑完整回归门：用装了 fastembed 的解释器，例：")
        print("      <venv>/python tools/probes/semantic_search.py build")
        print("      <venv>/python tools/probes/_scene_probe.py")
        print("  · 说明见 QUICKSTART.md §1（fastembed 属可选依赖）")
        return 2
    except ValueError as e:
        if "index stale" in str(e):
            print("[scene-probe] 跳过：索引与语料不同代 ⇒ 先重建：")
            print("  <venv>/python tools/probes/semantic_search.py build")
            print("  （详见 maintenance-skills/experience-family-pipeline.md 的「同代读数」）")
            return 2
        raise

    # 前置自检：期望族的条目必须在语料里存在（否则探针本身失真）
    known = {(e["kind"], e["title"]) for e in corpus}
    missing = []
    for fam, spec in FAMILIES.items():
        for kt in spec["entries"]:
            if kt not in known:
                missing.append((fam, kt))
    if missing:
        print("❌ 探针数据失真：期望族条目不在语料中：%s" % missing)
        return 2
    print("语料 %d 条 · 族 %d 个（%s）· 场景 %d 个"
          % (len(corpus), len(FAMILIES),
             " / ".join("%s 期望 %d 条" % (f, len(s["entries"])) for f, s in FAMILIES.items()),
             len(SCENES)))

    lex_rows, lex_agg = _eval(_lexical_hits)
    hyb_rows, hyb_agg = _eval(lambda q: _hybrid_hits(q, corpus, index, emb))

    for fam in FAMILIES:
        _print_result("词面 lexical · %s" % fam, [r for r in lex_rows if r["family"] == fam],
                      _agg([r for r in lex_rows if r["family"] == fam]))
    for fam in FAMILIES:
        _print_result("混合 hybrid · %s" % fam, [r for r in hyb_rows if r["family"] == fam],
                      _agg([r for r in hyb_rows if r["family"] == fam]))
    print("\n【合计 N=%d】词面 %s ｜ 混合 %s"
          % (len(SCENES), json.dumps(lex_agg, ensure_ascii=False), json.dumps(hyb_agg, ensure_ascii=False)))

    print("\n【对比】逐场景 top1 族命中差异：")
    for a, b in zip(lex_rows, hyb_rows):
        if a["top1_hit"] != b["top1_hit"] or a["fp"] != b["fp"]:
            print("  %-42s 词面:%-6s 混合:%-6s | 混合 top1=%s"
                  % (a["query"][:42], "HIT" if a["top1_hit"] else ("FP" if a["fp"] else "-"),
                     "HIT" if b["top1_hit"] else ("FP" if b["fp"] else "-"),
                     (b["hits"][0]["title"] if b["hits"] else "-")[:34]))

    snapshot = {
        "scenes": len(SCENES),
        "lexical": lex_agg,
        "hybrid": hyb_agg,
        "by_family": {
            fam: {
                "lexical": _agg([r for r in lex_rows if r["family"] == fam]),
                "hybrid": _agg([r for r in hyb_rows if r["family"] == fam]),
            } for fam in FAMILIES
        },
        "rows": [{"family": r["family"], "tier": r["tier"], "query": r["query"],
                  "top1_hit": r["top1_hit"],
                  "top3_hit": r["top3_hit"], "miss": r["miss"], "fp": r["fp"],
                  "top1": r["hits"][0]["title"] if r["hits"] else None} for r in hyb_rows],
    }
    if "--check" in sys.argv and os.path.isfile(SNAPSHOT):
        old = json.load(io.open(SNAPSHOT, encoding="utf-8"))
        print("\n【回归】与上次快照对比：")
        for key in ("lexical", "hybrid"):
            if old.get(key) != snapshot[key]:
                print("  ⚠️ %s 变化：%s → %s" % (key, old.get(key), snapshot[key]))
            else:
                print("  ✅ %s 读数不变 %s" % (key, snapshot[key]))
    with io.open(SNAPSHOT, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print("\n快照已写 %s" % os.path.relpath(SNAPSHOT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
