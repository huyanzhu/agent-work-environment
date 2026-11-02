#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aios-hook.py — AI-OS Runtime 稳定入口（R0 dispatcher · AUTOMATION-BOUNDARY §12.1）

角色：DSH 的 hook 命令**唯一稳定入口**。`.claude/hooks.json` 每个事件都指向它：

    SessionStart / UserPromptSubmit / Stop  →  python tools/aios-hook.py <Event>

为什么存在（§12.1 · §11.4）：DSH 的 hook 命令**在插件加载时读一次**
（`hooks-claude-code/src/index.ts:100-108` · 注释 "Parse once at load"）。
若把开关写在 `hooks.json`，每次"逐个打开"都要重启（中断会话 + 必须 执行），
而注入型纪律恰恰要求**逐个打开**。⇒ 本入口把开关移到**运行期读的文件**：

    .claude/aios-exposure.json

⇒ **一次重启之后，开/关一个暴露 = 改一行、不重启。**

三条边界（§12.1 —— 本文件只做路由，不做发现算法）：
  · **不是状态源** —— 只读开关 + 转发；不记录任何事实 / 不做幂等依据 / 不存会话状态
  · **不做判断** —— 不决定"该不该注入"，只执行开关已授权的 action
  · **不阻塞** —— 任何路径 exit 0

兜底（§12.0 五条）：
  ① exit 0 恒成立  ② stdout 只一行 JSON（其余一律 stderr）
  ③ 对 Agent fail-open、对注入 fail-closed（注入失败 = 不注入，绝不注入半截）
  ④ 不新增事实状态源（本文件不写任何事实文件）
  ⑤ 逐个 action 独立 try + 独立超时（一个坏了不拖垮另一个；开关坏 = 全关 + stderr 留痕）

开关纪律：
  默认全关 · **每次调用重新读取** · 损坏 ⇒ 全关 + stderr · **不得靠旧运行记录恢复开关**
  ⇒ 本文件不缓存开关、不落盘、不做任何"上次是开的"式恢复。
"""
import io
import json
import os
import sys
import tempfile
import threading
import time

# 同族修复（见 wrapup_sync.py 缺陷 ①）：hook stdout/stderr 随 locale（Windows 默认 GBK）
# ⇒ 输出里的 '⇒'（U+21D2）会抛 UnicodeEncodeError。显式改 UTF-8（errors=replace 保证任何字符都不炸）。
# ⚠️ **stdin 同样要设**：DSH 写进的 payload 是 UTF-8 JSON，而 Windows 上 `sys.stdin` 默认走 locale
# 编码（GBK）⇒ 中文 `prompt` 会被解成乱码、甚至让 `json.loads` 直接失败 = **R4 静默失效**。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

EXPOSURE_PATH = os.path.join(ROOT, ".claude", "aios-exposure.json")

# 协议输出流：**保住原始 stdout**。action 执行期间 `sys.stdout` 会被**永久**换成 StringIO
# （见 `_run_isolated` 的理由）⇒ 协议的那一行 JSON **只能**走这里，不能走 `sys.stdout`。
_PROTOCOL_OUT = sys.stdout

# 内部超时（§12.0 ⑤ §12.1 兜底 · §12.5 预算）：
#   · `SessionStart` = **detached**（不阻塞会话）⇒ 用 §12.1 的默认值 **8s**
#   · `UserPromptSubmit` = **awaited**（超时直接给用户加延迟）⇒ 按 §12.5 收紧到 **5s**（本机读数 55 ms，余量充足）
#   · 写回型要覆盖 `wrapup_sync` 的 IO 退避重试窗口（8 次 × 120ms 递增 ≈ 4.3s）⇒ **30s**
INJECT_TIMEOUT_S = 8.0
PROMPT_TIMEOUT_S = 5.0
WRITEBACK_TIMEOUT_S = 30.0

# action 注册表：**代码侧**登记"某个 action 属于哪个事件、是注入型还是写回型"。
# 开关（.claude/aios-exposure.json）只能在这个白名单里选启停 —— 未登记的 action 一律不跑。
ACTIONS = {
    "task_recovery": {"event": "SessionStart", "kind": "inject"},
    "material_discovery": {"event": "UserPromptSubmit", "kind": "inject"},
    # R4′（打开注入）：**卡字段驱动**的能力候选
    #   链路：卡（State + Next Action）→ 焦点对象 → 领域职能短语 → 名称硬门槛检索 → Top-3
    "field_candidates": {"event": "UserPromptSubmit", "kind": "inject"},
    # 🔴 **hook 版 R3** —— 用户消息时检查「曾占用、现在不占」⇒ 注入维护清单
    #   补 Runtime R3 的缺口：R3 只在 `post-execute`（工具调用后）检查，而"只收到消息、没调工具"时不会提示。
    "ownership_lost": {"event": "UserPromptSubmit", "kind": "inject"},
    # 🔴 **R3 关闭态告知** —— 只在 `.aios/r3-wake.json` 为关（默认）时工作。
    #   ① SessionStart：会话开始就告知「R3 空闲唤醒 = 关」（每会话一次）
    #   ② UserPromptSubmit：本会话的卡被**别的会话占用**（takeover）时再告知一次（每卡一次）
    #   ⚠️ 与 `ownership_lost` 分工：那条给「维护清单（做什么）」；本 action 只给
    #      「模式边界（为什么可能没人自动维护）」，⛔ 不重复清单内容。
    "r3_notice_start": {"event": "SessionStart", "kind": "inject"},
    "r3_notice_lost": {"event": "UserPromptSubmit", "kind": "inject"},
    "wrapup_writeback": {"event": "Stop", "kind": "writeback"},
}


# ── 宿主运行模式（B 的条件）──────────────────────────
#   为什么需要：`aios-exposure.json` 的 `enabled` 只表达"这个 action 开不开"，**不表达"在哪个宿主下开"**；
#   而 DSH 原生主路线与纯 Claude Code 兼容路线的注入源必须**二选一**
#   （唯一注入源纪律 · `p0/RESPONSIBILITY-BOUNDARIES.md §1.1`）。
#   判据（⛔ 不猜）：DSH 托管进程会向子进程导出 `DSH_*`（读数 `DSH_HOME` / `DSH_SESSION_ID` / `DSH_SHELL`）；
#   纯 CC 环境没有这些（读数无 `CLAUDE_*`）⇒ 无 `DSH_*` 即判为 `cc`。
def host_mode():
    """`dsh` = DSH 原生宿主 · `cc` = 纯 Claude Code 宿主。"""
    for k in os.environ:
        if k.startswith("DSH_"):
            return "dsh"
    return "cc"


def _diag(msg):
    """诊断一律走 stderr（DSH 记进 hook/result 的 stderrSummary）。stdout 留给那一行 JSON。"""
    try:
        sys.stderr.write("[aios-hook] %s\n" % msg)
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


# ── 🔴 （本会话修）：幂等状态的**可写位置探测** ────────────────────
#   现象：hook 子进程写 `.aios/maint-notified|r3-notice/<session>.json` 失败（mtime 冻结），
#         同一命令手工跑却能写 ⇒ 同一提醒**每轮重复注入**；旧 `ownership_lost` 还
#         `except: pass` 把失败吞了。
#   根因（本会话读数 + 配置核对）：hook 是 **session-free** 调用 ⇒ 沙箱写根 =
#         `sandbox-policy.workspaceRoot`，而 `cordis.patch.yml` 把它绑成 `process.cwd()`
#         （DSH 启动目录，≠ `<repo>`）⇒ 写 `ROOT/.aios` 被拒。数据侧证据：
#         `.aios/r3-notice/` 只有最后一次"能写"的 20:06 那份，本会话 SessionStart 没留下文件；
#         SessionStart 是 detached 生命周期点 ⇒ **不记 hook/result**，所以失败诊断也看不到。
#   处置（不改宿主、Pytho 侧即时生效）：状态**先试 `ROOT/.aios/<kind>`，不可写则降级到
#         `AIOS_HOOK_STATE_DIR` 或 `%TEMP%/aios-hook-state/<kind>`**；
#         读侧**两处都读并合并**（降级后旧状态不丢）；降级/失败一律 `_diag`，⛔ 不静默。
#   ⚠️ 根治要改宿主的 `sandbox-policy.workspaceRoot`（`cordis.patch.yml`）⇒ 需 重启授权。
HOOK_STATE_ENV = "AIOS_HOOK_STATE_DIR"


def _state_roots():
    """→ 状态根候选（**按优先级**，去重保序）。

    首选 `<ROOT>/.aios`（正常实例）。不可写时的兜底链（读数调整）：
      ① `AIOS_HOOK_STATE_DIR`（测试 / 部署覆盖）
      ② `%LOCALAPPDATA%/Temp/aios-hook-state` —— **显式**系统 TEMP；⛔ 不用
         `tempfile.gettempdir()` 作首选：DSH 沙箱会把进程 TEMP 重定向到
         `<tmp>`，读数该目录在受限执行下**不可写**（PermissionError）。
      ③ `tempfile.gettempdir()/aios-hook-state`（非 DSH 宿主 / 普通环境）
      ④ `<ROOT>/scratch/hook-state`（最后尝试：若 .aios 仅个别目录受限，这里可能可写）
    """
    cands = [os.path.join(ROOT, ".aios")]
    override = os.environ.get(HOOK_STATE_ENV, "").strip()
    if override:
        cands.append(override)
    # hook 的沙箱写根 = `sandbox-policy.workspaceRoot`（= DSH 启动目录）。
    #   把 DSH 自己的目录加进来：若写根落在 `%DSH_HOME%` 下，这是**唯一一定可写**的位置
    #   （读数 `.aios` 与系统 TEMP 都被拒，见）。⛔ 不放密钥 / 不放事实，只放幂等标记。
    dsh_home = os.environ.get("DSH_HOME", "").strip()
    if dsh_home:
        cands.append(os.path.join(dsh_home, "aios-hook-state"))
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        cands.append(os.path.join(local, "Temp", "aios-hook-state"))
    # 🔴 删掉 `tempfile.gettempdir()` 候选（A 组子代理 review · 真实缺陷）：
    #   它在 DSH 沙箱下被重定向成**每进程一个新的** `<旧脑根>\<文件>\tmp\dsh-<随机>` ⇒
    #   "探针能写"但**下一个 hook 进程读不到** ⇒ 幂等形同虚设，还多一行"降级"把问题掩盖成正常。
    #   ⇒ 只保留**跨进程稳定**的根。
    cands.append(os.path.join(ROOT, "scratch", "hook-state"))
    seen, out = set(), []
    for c in cands:
        k = os.path.normcase(os.path.abspath(c))
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def _read_state_file(path):
    """读一份状态 JSON；缺失 / 读失败 / 非对象 ⇒ None（⛔ 不抛）。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _merge_state(base, extra):
    """合并两份状态：列表字段取**并集**（保序去重），其余字段先到先得（首选目录优先）。"""
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, list):
            cur = out.get(k)
            cur = [str(x) for x in cur] if isinstance(cur, list) else []
            out[k] = list(dict.fromkeys(cur + [str(x) for x in v]))
        elif k not in out:
            out[k] = v
    return out


def _load_state(kind, session):
    """读状态：**主根权威** —— 主根有该文件就以它为准；主根缺失才回落兜底根。

    🔴 （A 组子代理 review · 真实缺陷）：旧实现是「所有根取并集」，而写侧只写
    第一个可写根 ⇒ 某次降级把 `{"start": true}` 写进兜底后，主根恢复可写仍会被并集的
    陈旧副本**永久钉死**（单调状态：SessionStart 告知不再出现 / 该卡永远算"已提示"）。
    ⇒ 单调状态不合并：主根存在即权威。
    """
    fname = session.replace("/", "_") + ".json"
    roots = _state_roots()
    primary = _read_state_file(os.path.join(roots[0], kind, fname))
    if primary is not None:
        return primary
    return _read_state_file(os.path.join(roots[-1], kind, fname)) or {}


_STATE_DIR_CACHE = {}


def _probe_state_dir():
    """探测**第一个可写**状态根（写一个 `._write-probe` 再删）；进程内缓存。

    只在「需要读写状态」时惰性调用（不增加正常轮次噪音）；一旦**降级**就 `_diag` 一行，
    使「幂等为什么失效」在下一次 `hook/result.stderrSummary` 里可见（修法②）。
    → 可写根路径｜None（全部不可写）。
    """
    if "dir" in _STATE_DIR_CACHE:
        return _STATE_DIR_CACHE["dir"]
    errors = []
    for root in _state_roots():
        try:
            os.makedirs(root, exist_ok=True)
            probe = os.path.join(root, "._write-probe")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            if errors:
                _diag("幂等状态**降级**到 `%s`（cwd=%s · TEMP=%s ｜ 首选失败：%s）"
                      % (root, os.getcwd(), os.environ.get("TEMP", ""), " | ".join(errors)))
            _STATE_DIR_CACHE["dir"] = root
            return root
        except (OSError, ValueError) as e:
            errors.append("%s: %s" % (type(e).__name__, e))
    _diag("幂等状态**无可写根**（cwd=%s · TEMP=%s · 全部失败：%s）⇒ 提醒去重会失效"
          % (os.getcwd(), os.environ.get("TEMP", ""), " | ".join(errors)))
    _STATE_DIR_CACHE["dir"] = None
    return None


def _save_state(kind, session, state):
    """写到**探测到的可写状态根**；不可写 ⇒ 诊断可见。→ (ok, used_path)。"""
    root = _probe_state_dir()
    if root is None:
        _diag("%s 状态写不进去（无可用状态根）⇒ 幂等失效、下轮可能重复提醒" % kind)
        return False, None
    path = os.path.join(root, kind, session.replace("/", "_") + ".json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # 🔴 （A 组 review）：tmp 名带 pid —— 固定 `.tmp` 在并发（SessionStart 是
        #   detached，会与首条 UserPromptSubmit 同时读改写）下互相踩掉 / `os.replace` 撞 FileNotFoundError。
        tmp = path + ".tmp-%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True, path
    except (OSError, ValueError) as e:
        _diag("%s 状态写入失败（%s: %s）⇒ 幂等失效、下轮可能重复提醒"
              % (kind, type(e).__name__, e))
        return False, None


# --------------------------------------------------------------------------
# 运行期开关
# --------------------------------------------------------------------------

def load_exposure():
    """读运行期开关；返回 (enabled, note)。

    **fail-closed**：文件缺失 / 读失败 / JSON 非法 / 结构不对 ⇒ 返回空 dict（全关）+ 一行说明。
    只认**严格布尔 True**（`"true"` 这类字符串不算开），避免手改文件时的静默误判。
    """
    try:
        with open(EXPOSURE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}, "开关文件不存在（%s）⇒ 全关（默认）" % os.path.relpath(EXPOSURE_PATH, ROOT).replace("\\", "/")
    except (OSError, ValueError) as e:
        return {}, "开关读取失败（%s: %s）⇒ 全关（fail-closed）" % (type(e).__name__, e)
    if not isinstance(raw, dict):
        return {}, "开关结构非法（顶层不是对象）⇒ 全关（fail-closed）"
    actions = raw.get("actions")
    if not isinstance(actions, dict):
        return {}, "开关缺 `actions` 对象 ⇒ 全关（fail-closed）"

    host = host_mode()
    enabled = {}
    unknown = []
    off_host = []
    for name, spec in actions.items():
        if name not in ACTIONS:
            unknown.append(name)
            continue
        if not (isinstance(spec, dict) and spec.get("enabled") is True):
            continue
        # 可选键 `hosts`：限定该 action 的生效宿主；缺省 / 空列表 ⇒ 全宿主（向后兼容）
        hosts = spec.get("hosts")
        if isinstance(hosts, list) and len(hosts) > 0:
            allowed = [str(h) for h in hosts]
            if host not in allowed:
                off_host.append("%s（声明 hosts=%s · 当前宿主=%s）"
                                % (name, "/".join(allowed), host))
                continue
        enabled[name] = spec
    notes = []
    if unknown:
        notes.append("开关声明了未登记的 action（%s）⇒ 忽略（只有代码侧白名单里的 action 会跑）"
                     % ", ".join(sorted(unknown)))
    if off_host:
        notes.append("开关声明**不在本宿主运行** ⇒ 跳过（唯一注入源纪律 · "
                     "`p0/RESPONSIBILITY-BOUNDARIES.md §1.1`）：%s" % "、".join(off_host))
    return enabled, " · ".join(notes)


# --------------------------------------------------------------------------
# 隔离执行：独立 try + 独立超时 + stdout 抑制
# --------------------------------------------------------------------------

def _run_isolated(fn, payload, timeout_s, name):
    """执行一个 action，**任何异常都不得逃出**；超时 = 放弃（注入型即"不注入"）。

    超时用 daemon 线程实现（Windows 无 SIGALRM）：线程到点仍活着 ⇒ 主线程不再等它，
    进程退出时 daemon 线程随之消失。对注入型安全（放弃结果 = 不注入）；
    对写回型，写入本身有 IO 重试 + 原子写（tmp + os.replace），半截写不会落盘。

    ⚠️ **stdout 永久隔离**（**不用** `with redirect_stdout`）：超时后 action 线程**仍可能在跑**，
    若那时把 stdout 恢复成真流，它后续的 `print` 就会写进协议输出 ⇒ 破坏"stdout 只一行 JSON"。
    ⇒ 这里直接 `sys.stdout = StringIO()` 且**永不恢复**；协议输出只走 `_PROTOCOL_OUT`。
    """
    box = {}
    buf = io.StringIO()
    sys.stdout = buf

    def target():
        try:
            box["value"] = fn(payload)
        except BaseException as e:  # noqa: BLE001 —— 含 SystemExit/KeyboardInterrupt：action 里没有"该退出"的语义
            box["error"] = e

    t = threading.Thread(target=target, name="aios-action-%s" % name, daemon=True)
    t.start()
    t.join(timeout_s)
    alive = t.is_alive()
    captured = buf.getvalue()
    if captured and captured.strip():
        # action 自己的 print 是诊断，不是协议输出 —— 转 stderr，绝不污染协议流
        _diag("action %s 的 stdout（转诊断）：\n%s" % (name, captured.rstrip()))
    if alive:
        raise TimeoutError("action 超时（>%.0fs）⇒ 放弃（注入型 = 不注入；迟到输出已被隔离）" % timeout_s)
    if "error" in box:
        raise box["error"]
    return box.get("value")


# --------------------------------------------------------------------------
# Actions（**同源调用**既有实现，不复制发现算法）
# --------------------------------------------------------------------------

def action_task_recovery(payload):
    """R1 · 任务恢复（`SessionStart`）：只送可恢复的卡 + Goal / 下一步 / 路径。

    §12.0.1：开工时**还不知道用户要做什么** ⇒ 此处**不做**经验 / 能力发现
    （读数无 prompt 时能力 trigger 9/9 全命中 = bigram 噪声）。材料发现属进行时（R4）。
    """
    import task_start as ts
    return ts.recovery_text()


def action_material_discovery(payload):
    """R4 · 进行时材料发现（`UserPromptSubmit`）：真实 prompt → 经验 + 能力**候选**。

    **判据同源** `task_start.material_text()`（预算 ≤2 条经验 + ≤2 个能力 · 命中不足 ⇒ 不注入）——
    本 action 只负责"取 prompt → 交给同源检索 → 拿回可注入文本"，**不复制发现算法**。
    """
    import experience_push as ep
    import os
    import re
    import task_start as ts
    import wrapup_sync as ws

    prompt = payload.get("prompt")
    prompt = prompt if isinstance(prompt, str) else ""
    tokens = ep.tokenize(prompt)
    if not tokens:
        return ""

    # §12.5：「读 prompt（+ **可确定的**当前卡 Goal）」—— "可确定"沿用 R2 的选卡判据
    # （**唯一**才算可确定；不唯一 ⇒ 不并入，不猜）。⚠️ 只调**只读**判据，不写任何文件。
    card_note = ""
    try:
        card_path, _why = ws.resolve_target_card()
    except BaseException:  # noqa: BLE001 —— 判据失败不得影响注入（对 Agent fail-open）
        card_path = None
    if card_path:
        try:
            with open(card_path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except OSError:
            raw = ""
        m = re.search(r"^##\s+Goal\s*\n(.*?)(?=^##\s|\Z)", raw, re.M | re.S)
        goal = " ".join(m.group(1).split()) if m else ""
        if goal:
            tokens = tokens | ep.tokenize(goal)
            card_note = ("（本轮候选由 prompt + **唯一确定卡** `%s` 的 Goal 共同检索）"
                         % os.path.basename(card_path).removesuffix(".md"))

    text = ts.material_text(tokens)
    if text and card_note:
        return text + "\n" + card_note
    return text          # 无候选 ⇒ 空（不硬凑）；有候选但无可确定卡 ⇒ 只送候选


# ── 🔴 焦点卡跨语言接口 · **读取侧（只诊断 · 不切换）** ──────────────────────────────
#   （步 2 · 授权）
#   契约：`task_cards/active/demo-project/p0/FOCUS-CARD-INTERFACE-DESIGN.md`
#   🔴 **本段的边界（步 2 的全部内容）**：只**读**接口件 + **落只读诊断**：
#      ⛔ 不改变写回目标选择 · ⛔ 不删旧 Git 回退 · ⛔ 不清零 V-2 · ⛔ 不注入
#   ⇒ 目的：先回答"接口到底**命中多少**"，为"是否切换"提供**读数依据**（设计 §八 步 2）。
#   判据与写入侧**逐字同源**（设计 §四 §五）：schema / session 强关联 / TTL / `card` 非空；
#   `cwd` 差异**只记录、不拒绝**（决策 3）。
#   ⚠️ `session-mismatch` 是**预期内正常分支**（多会话并行必然出现）⇒ ⛔ 不得计入故障率。

FOCUS_CARD_SCHEMA = "focus-card/v1"
FOCUS_CARD_PROBE = os.path.join(ROOT, ".aios", "_focus-card-probe.jsonl")


def _focus_card_path():
    """接口件路径（三级兜底与本体 `resolveStateFile()` 同构）。"""
    env = os.environ.get("AIOS_FOCUS_CARD")
    if env and env.strip():
        return env.strip()
    state = os.path.join(ROOT, ".aios")
    if not os.path.isdir(state):
        state = os.path.join(ROOT, "scratch")
    scratch = os.path.join(ROOT, "scratch")
    preferred = os.path.join(state, "focus-card.json")
    for cand in (preferred,
                 os.path.join(state, "_focus-card.json"),
                 os.path.join(scratch, "_focus-card.json")):
        if os.path.exists(cand):
            return cand
    return preferred


def _focus_probe_append(rec):
    """append-only 只读诊断（⛔ 任何失败一律静默 —— 诊断绝不影响宿主）。"""
    try:
        with io.open(FOCUS_CARD_PROBE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except (OSError, ValueError, TypeError):
        pass


def focus_card_probe(payload):
    """读接口件并按契约校验，落**只读诊断**；返回 `(hit, reason)`。

    🔴 **返回值仅供诊断** —— 调用方⛔ **不得**据它改变写回行为（步 2 边界）。

    🔴 **改（A：去掉占用件的 TTL 失效判据）**：
      「本对话正占用卡 X」是**持续状态**，不是一次性判定 ⇒ **时间流逝不改变它**。
      陈旧隔离**已由 `session` 逐字相等承担**（别的会话读到 ⇒ `session-mismatch` ⇒ 不会误用）。
      ⇒ ⛔ **不再**因 `now > expiresAt` 拒绝；`expiresAt` / `writtenAt` 降为**诊断信息**：
        · 未过期命中 ⇒ `reason:"hit"`
        · 已过期仍命中 ⇒ `reason:"hit-stale"`（附 `ageMs`，供观测"陈旧率"）—— **仍是命中**
      失效只由**状态变化**驱动：文件缺失 / 损坏 / schema 不符 / **会话不符** / `card` 为空。
      契约同步：`FOCUS-CARD-INTERFACE-DESIGN.md`（§四校验链 · §五对照表 · §六）。
    """
    payload = payload if isinstance(payload, dict) else {}
    path = _focus_card_path()
    now = int(time.time() * 1000)
    rec = {"at": now, "path": path, "session": str(payload.get("session_id") or "")}

    def _miss(reason, **extra):
        rec["ev"] = "focus-card-miss"
        rec["reason"] = reason
        rec.update(extra)
        _focus_probe_append(rec)
        return False, reason

    try:
        with io.open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return _miss("missing")
    try:
        obj = json.loads(raw)
    except ValueError:
        return _miss("corrupt")
    if not isinstance(obj, dict):
        return _miss("corrupt")
    if obj.get("schema") != FOCUS_CARD_SCHEMA:
        return _miss("schema-mismatch", gotSchema=str(obj.get("schema")))
    if str(obj.get("session") or "") != str(payload.get("session_id") or ""):
        # ⚠️ 正常分支（别的会话的判定）—— 不是故障；它同时也是**陈旧隔离的实际承担者**
        return _miss("session-mismatch")
    card = obj.get("card")
    if not isinstance(card, str) or card == "":
        return _miss("bad-card")
    # ✅ 命中 —— ⛔ TTL **不参与**判定；只把它记成诊断
    try:
        exp = int(obj.get("expiresAt"))
    except (TypeError, ValueError):
        exp = None          # ⛔ 字段缺失/非法**不再**判 `bad-card`（TTL 已非失效判据）

    def _norm(p):
        return str(p or "").replace("\\", "/").rstrip("/")
    stale = exp is not None and now > exp
    rec["ev"] = "focus-card-hit"
    rec["reason"] = "hit-stale" if stale else "hit"
    rec["card"] = card
    rec["basis"] = str(obj.get("basis") or "")
    rec["writtenAt"] = obj.get("writtenAt")
    rec["cwdDiff"] = _norm(obj.get("cwd")) != _norm(payload.get("cwd"))
    if stale:
        rec["ageMs"] = now - exp      # 陈旧读数（供观测"过期但仍在用"的比例）
    _focus_probe_append(rec)
    return True, rec["reason"]


def action_wrapup_writeback(payload):
    """R2 + R3 · 收尾写回（`Stop`）：任务卡 Event Log（**不猜卡**）+ 账本追加机械事实。

    §12.3 / §12.4：两个写回目标**各自独立 try**（在 wrapup_sync 内保证）；
    机制**只写"发生了什么"**，`Outcome` / `footprint` / `influence` 留占位标"待补"。
    """
    # ── 🔴 步 2 · 焦点卡接口 **只诊断** ──────────────────────────────────────────
    #    ⛔ 命中与否**都不影响**下面 `ws.main([])` 的行为（仍走旧 Git 事实判据）。
    #    诊断自身异常也一律吞掉 —— 绝不得让"观察"改变"写回"。
    try:
        _hit, _reason = focus_card_probe(payload)
        _diag("focus-card 接口：%s（%s）" % ("hit" if _hit else "miss", _reason))
    except Exception as _exc:  # noqa: BLE001
        _diag("focus-card 诊断自身异常（已忽略，不影响写回）：%s" % _exc)
    import wrapup_sync as ws
    # 🔴 修补：wrapup 选卡要用「本会话自己的卡」判据 ⇒ 需要本会话 id。
    #    hook 与 ws 同进程 ⇒ 显式透传（DSH_SESSION_ID 优先，payload 兜底）；拿不到则不设（ws 回退 git 判据）。
    #    读数背景：Stop 自动写回一直 `skip`，显式 `wrapup_sync <TASK-ID>` 却能写 ⇒ 先补会话 id 透传。
    _sid = str(os.environ.get("DSH_SESSION_ID") or payload.get("session_id") or "").strip()
    if _sid and _sid != "-":
        os.environ["AIOS_SESSION_ID"] = _sid
    _diag("wrapup：session=%s ⇒ 选卡判据 = 本会话自己的卡（无则回退 git）" % (_sid or "-"))
    code = ws.main([])   # 不传 TASK-ID ⇒ 走"不猜卡"判据（见 wrapup_sync.resolve_target_card）
    if code != 0:
        raise RuntimeError("wrapup_sync 返回非零（%s）—— 详见其 stderr 诊断" % code)
    return None


# 卡字段驱动的注入门限（透明可调）
#   · 命中池 < FIELD_POOL_MIN ⇒ 判定"池内无对口族 / 过窄" ⇒ **不注入**（宁缺毋滥，
#     读数：`运行时`/`文档` 两个对象在中文池里池 ≤7 ⇒ 属 no-family，递了也是噪声）
# 曾临时改为 1（面试叙事演示用），**已回滚为 50**。
FIELD_POOL_MIN = 50
FIELD_TOPN = 3

# **工作区 → AI-OS 卡所在的项目目录**（新增）
#   为什么需要：`resolve_target_card()` 无参时走 **git 事实推导**，而 hook 的 git 根是 `<root>`
#   ⇒ 在**别的工作区**（如产品仓库）里开会话时它根本看不到那里的改动 ⇒ 判"不唯一" ⇒ 永不注入。
#   本表把"当前工作目录"映射到 `task_cards/active/` 下的**项目目录**，
#   再交给既有判据 **`resolve_target_card(project=…)`**（目录内**唯一卡**才算可确定）
#   ⇒ ✅ 符合"不猜卡"纪律（cwd 是显式事实，唯一性由既有判据裁定），⛔ 不含标题/mtime 相似度。
WORKSPACE_PROJECTS = {
    "d:\\ai\\projects\\demo-project-v2": "task_cards/active/demo-project",
}


def _project_of_cwd(cwd):
    if not isinstance(cwd, str) or not cwd:
        return None, None
    key = os.path.normcase(os.path.normpath(cwd)).rstrip("\\")
    for prefix, proj in WORKSPACE_PROJECTS.items():
        if key == prefix or key.startswith(prefix + "\\"):
            return proj, prefix
    return None, None


def action_field_candidates(payload):
    """R4′ · **卡字段驱动**的能力候选（`UserPromptSubmit`）。

    链路：卡（`State` + `Next Action`）→ 焦点对象 → 领域职能短语 → **名称硬门槛**检索 → Top-3。

    边界（严格）
      · ⛔ **不含推理原文** —— `UserPromptSubmit` 发生在 pre-step，推理尚未产生，此路本就拿不到
      · ⛔ **不写任何文件**（只读卡 + 读索引缓存）
      · ⛔ **卡不唯一确定 / 字段退化 / 命中池 < `FIELD_POOL_MIN`** ⇒ **不注入**
      · 依赖**已迁到正式路径**的字段产出器：`tools/probes/`（起；旧位 `scratch/` 仅作只读回退）
        ⇒ 缺失或异常 **fail-open**（stderr 留痕，不注入、不阻塞）
    """
    import json
    import os as _os
    import sys as _sys

    import wrapup_sync as ws

    # 执行层自 `scratch/` 迁入 `tools/probes/`（`HANDOFF §四十六`）。
    #    仍保留 `scratch/` 作**只读回退**（迁移期兼容 · 两侧都在时 `tools/probes/` 优先）。
    for _d in (_os.path.join(ROOT, "tools", "probes"), _os.path.join(ROOT, "scratch")):
        if _os.path.isdir(_d) and _d not in _sys.path:
            _sys.path.insert(0, _d)

    # 卡关联：① 先按 **当前工作目录** 映射到项目目录（跨工作区可用）；② 退回 git 推导。
    #   两条都走既有的"唯一才算可确定"判据 ⇒ ⛔ 不猜。
    project, prefix = _project_of_cwd(payload.get("cwd"))
    try:
        if project:
            card_path, why_card = ws.resolve_target_card(project=project)
        else:
            card_path, why_card = ws.resolve_target_card()
    except BaseException:  # noqa: BLE001
        card_path, why_card = None, "选卡判据异常"
    if not card_path:
        _diag("field_candidates：卡不唯一确定（%s）⇒ 不猜、不注入" % why_card)
        return ""

    # 名称索引：**生成物** ⇒ 优先 `.aios/`（起），再回退 `tools/probes/` / `scratch/`
    idx_path = ""
    for _d in (_os.path.join(ROOT, ".aios"), _os.path.join(ROOT, "tools", "probes"),
               _os.path.join(ROOT, "scratch")):
        _cand = _os.path.join(_d, "_zh_name_index.json")
        if _os.path.isfile(_cand):
            idx_path = _cand
            break
    if not idx_path:
        _diag("field_candidates：缺名称索引（先跑 python tools/probes/_zh_name_index_build.py）⇒ 不注入")
        return ""

    try:
        import _runtime_field_producer as fp
        rel = _os.path.relpath(card_path, ROOT).replace("\\", "/")
        field = fp.produce_from_card(rel)
    except BaseException as e:  # noqa: BLE001
        _diag("field_candidates：字段产出失败（%s）⇒ 不注入" % type(e).__name__)
        return ""
    if field.get("degraded") or not field.get("phrases"):
        _diag("field_candidates：字段退化（%s）⇒ 不注入" % ";".join(field.get("reasons") or []))
        return ""

    try:
        import experience_push as ep
        with open(idx_path, "r", encoding="utf-8") as f:
            idx = json.load(f)
        cats = set(field.get("categories") or [])
        best = {}
        for ph in field["phrases"]:
            pt, _noi = ep.split_hits(ep.tokenize(ph))
            for it in idx.get("items") or []:
                if cats and it.get("cat") not in cats:
                    continue
                n = len(pt & set(it.get("t") or []))
                if n and n > best.get(it.get("id"), (0, it))[0]:
                    best[it.get("id")] = (n, it)
    except BaseException as e:  # noqa: BLE001
        _diag("field_candidates：检索失败（%s）⇒ 不注入" % type(e).__name__)
        return ""

    rows = sorted(best.values(), key=lambda r: (-r[0], str(r[1].get("name"))))
    if len(rows) < FIELD_POOL_MIN:
        _diag("field_candidates：命中池 %d < %d ⇒ 判定池内无对口族/过窄 ⇒ 不注入"
              % (len(rows), FIELD_POOL_MIN))
        return ""

    card = _os.path.basename(card_path).removesuffix(".md")
    lines = ["【AI-OS 能力候选（卡字段驱动 · R4′）】",
             "对象 `%s`（置信 %s · 卡 `%s` · 池 %d）"
             % (field.get("object"), field.get("confidence"), card, len(rows))]
    phrases = list(field["phrases"])
    for n, it in rows[:FIELD_TOPN]:
        it_toks = set(it.get("t") or [])
        # 给出**命中词**（可核证据）—— 便于 Agent 自判，而非只给分数
        hit_ph = max(phrases, key=lambda ph: len(ep.split_hits(ep.tokenize(ph))[0] & it_toks))
        hit_toks = sorted(ep.split_hits(ep.tokenize(hit_ph))[0] & it_toks)
        lines.append("  · %s [%s]（命中 %d：%s）"
                     % (it.get("name"), it.get("cat") or "-", n, "/".join(hit_toks[:4])))
    lines.append("来源：外部中文技能注册表（%s 条）· 判据：**名称粗筛** + 类别对齐" % idx.get("n"))
    lines.append("⚠️ 名称粗筛（中文 bigram 存在**跨词假命中**，如「件设」）—— 请按命中词自行判断适用性；"
                 "不采纳不影响本步继续。")
    return "\n".join(lines)


def action_ownership_lost(payload):
    """🔴 **hook 版 R3** —— 用户消息进来时检查「我曾占用、现在不占」。

    为什么放 hook（不只靠 Runtime 的 post-execute）：
      Runtime 的 R3 只在**工具调用之后**检查 ⇒ 若本对话只收到一条消息、没调工具，就永远不提示。
      `UserPromptSubmit` 是**每条用户消息都会跑**的 ⇒ 补上这个缺口（「hook 等同用户消息」）。
    判据（⛔ 不猜）：
      · 本会话（`DSH_SESSION_ID`）在某张卡的 `.log` 里**有过 claim**
      · 而该卡**当前占用者不是本会话**（被 release / 被别的会话 takeover）
      ⇒ 注入维护清单（与 Runtime R3 同一套六项）
    幂等：`.aios/maint-notified/<session>.json` 记已提示过的卡（⛔ 不在每条消息上重复打扰）。
    """
    import json as _json
    import re as _re
    me = str(os.environ.get("DSH_SESSION_ID") or payload.get("session_id") or "").strip()
    if not me or me == "-":
        return ""  # 判不出会话 ⇒ 不注入（fail-closed）
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import task_card as tc
        paths = tc._iter_cards()
    except BaseException:  # noqa: BLE001
        _diag("ownership_lost：无法 import task_card / 扫卡 ⇒ 跳过")
        return ""
    lost = []
    for p in paths:
        try:
            rows = []
            logp = tc._event_log_path(p)
            if os.path.isfile(logp):
                rows = tc._read(logp).split("\n")
            elif os.path.isfile(p):
                m = tc.EVENT_LOG_RE.search(tc._read(p))
                rows = m.group(2).split("\n") if m else []
            claimed_by_me = any(
                mm and mm.group(1).strip() == me
                for mm in (_re.search(r"claim 占用（session:\s*([^）]*)）", ln) for ln in rows))
            if not claimed_by_me:
                continue
            if tc._current_occupant(p) != me:
                lost.append(os.path.basename(p)[:-3])
        except BaseException:  # noqa: BLE001
            continue
    if not lost:
        return ""
    # 幂等（可写位置探测 + 降级；⛔ 不再 `except: pass` 吞掉写失败）
    notified = [str(x) for x in (_load_state("maint-notified", me).get("notified") or [])]
    todo = [c for c in lost if c not in notified]
    if not todo:
        return ""
    _save_state("maint-notified", me,
                {"notified": notified + todo, "at": time.strftime("%Y-%m-%d %H:%M")})
    text = ("【AI-OS · 收工维护（R3 · hook 检查）】卡 `" + " · ".join(todo)
            + "` 已**不在本会话占用**（被释放 / 被别的会话接管）。\n"
            "请逐条过一遍（Runtime 只提醒，⛔ 不自动改任何东西）：\n"
            "1. INVENTORY：本次造出\"别的对话会用到\"的东西了吗？没登记就补一行（只给指针）。\n"
            "2. ENV：机器 / 账号能力面有变化吗？（模型 / API / 工具版本 / 权限）\n"
            "3. PITFALLS：这次踩到会再咬人的坑了吗？（现象 · 触发条件 · 处置）\n"
            "4. 卡：State / Next Action 是否是**当前**实况？\n"
            "5. 探针体积：`.aios/_aios-activation.probe.log`（阈值待定）。\n"
            "6. tests：`node runtime/tests/activation.test.mjs` 是否绿（已知红 1 = S37）。\n"
            "维护完再开新工作；⛔ 不存密钥值 · ⛔ 不把一次性产物登记进 INVENTORY。")
    # 🔴 R3 唤醒=关时，把「模式边界」并进**同一条**提醒，
    #   而不是让 r3_notice_lost 在同一轮再出一条（否则一次收两条、内容重复）。
    if not r3_wake_enabled():
        text += ("\n· R3 空闲唤醒 = **关**（`.aios/r3-wake.json`）⇒ 不会有空闲会话被自动拉起做维护；"
                 "⛔ 开关变更前**先与用户确认**，不要自行切换；用户同意后再写入 {\"enabled\": true}（改即生效，无需重启）。")
    return text


# ── 🔴 · **R3 关闭态告知** ──────────────────────────────
#   档 2「真唤醒」（runtime 监听卡 → followup 唤醒）的开关 = `.aios/r3-wake.json`，**默认关**。
#   关着时最容易被误解：本会话的卡被别的会话 takeover 后，**不会有会话被自动拉起**做维护；
#   维护提示只会在本会话下次活动时出现。⇒ 本 action 只在「R3 唤醒 = 关」时出声：
#     ① SessionStart：开局告知（每会话一次）
#     ② UserPromptSubmit：本会话的卡被别的会话占用（takeover）时告知（每卡一次）
#   ⚠️ 与 `ownership_lost` 分工：那条给「维护清单（做什么）」；本 action 只给「模式边界
#      （为什么可能没人自动维护）」，⛔ 不重复清单内容。两处的幂等状态互不影响。
#   开关纪律同 exposure：每次调用重读，缺失/非法 ⇒ 按**关**处理（fail-closed）。
R3_WAKE_PATH = os.path.join(ROOT, ".aios", "r3-wake.json")
R3_NOTICE_DIR = os.path.join(ROOT, ".aios", "r3-notice")


def r3_wake_enabled():
    """`.aios/r3-wake.json` 的 `enabled` 是否**严格 true**；缺失/非法/非 true ⇒ 关。

    🔴 读侧容忍 **UTF-8 BOM**（中文 Windows 手写 / `Set-Content` 常见）——否则 JSON 解析失败
    ⇒ 开关"看起来开了实际是关"且无报错（读数：BOM 让真唤醒周期整段不跑）。
    """
    try:
        with open(R3_WAKE_PATH, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return False
    return isinstance(raw, dict) and raw.get("enabled") is True


def _r3_notice_state(session):
    """→ (state, path)。🔴 后走**统一层**：读主 + 兜底并合并（path 仅兼容，恒 None）。"""
    return _load_state("r3-notice", session), None


def _r3_notice_save(session, state):
    """保存 r3-notice 状态（统一层自动选可写根）。→ bool。"""
    ok, _path = _save_state("r3-notice", session, state)
    return ok


def _r3_session(payload):
    return str(os.environ.get("DSH_SESSION_ID") or payload.get("session_id") or "").strip()


def _r3_taken_over_cards(tc, me):
    """→ [(card_id, occupant)]：本会话曾 claim、**当前被别的会话占用**（takeover）的卡。

    判据（与 `task_card._current_occupant` 同源）：最后一条留痕是 claim 的 session；
    `occupant == ""` ⇒ 无人占用（= 自己 release，⛔ 不算 takeover）；`occupant != me` ⇒ 被接管。
    """
    import re as _re
    out = []
    for p in tc._iter_cards():
        try:
            rows = []
            logp = tc._event_log_path(p)
            if os.path.isfile(logp):
                rows = tc._read(logp).split("\n")
            elif os.path.isfile(p):
                m = tc.EVENT_LOG_RE.search(tc._read(p))
                rows = m.group(2).split("\n") if m else []
            claimed_by_me = any(
                mm and mm.group(1).strip() == me
                for mm in (_re.search(r"claim 占用（session:\s*([^）]*)）", ln) for ln in rows))
            if not claimed_by_me:
                continue
            occ = tc._current_occupant(p)
            if occ and occ != me:
                out.append((os.path.basename(p)[:-3], occ))
        except BaseException:  # noqa: BLE001 —— 单卡失败不影响其余
            continue
    return out


def action_r3_notice_start(payload):
    """SessionStart：会话开始告知一次 R3 状态（开/关都给，含开关纪律）。

    🔴 「R3 状态提示**只需要会话开始**」——本 action 是**唯一**出口；
    卡释放清单 / takeover 提示不再带 R3 状态句（避免同一信息多处重复）。
    """
    me = _r3_session(payload)
    if not me or me == "-":
        return ""
    state = _load_state("r3-notice", me)
    if state.get("start") is True:
        return ""
    state["start"] = True
    _save_state("r3-notice", me, state)
    if r3_wake_enabled():
        head = (
            "【AI-OS · R3 状态提醒】R3 空闲唤醒 = **开**（`.aios/r3-wake.json`）。\n"
            "⇒ 你的卡若被**别的会话 takeover**，Runtime 会在 15s 周期内唤醒你并注入维护清单。\n"
        )
    else:
        head = (
            "【AI-OS · R3 状态提醒】R3 空闲唤醒 = **关**（`.aios/r3-wake.json`，默认关）。\n"
            "⇒ 你的卡若被**别的会话 takeover**，不会有会话被自动拉起做维护；"
            "维护提示只会在你下次活动（消息 / 工具调用）时出现。\n"
        )
    return head + (
        "· ⛔ 开关变更前**先与用户确认**（不要自行切换）；用户同意后再写入 "
        "{\"enabled\": true} / {\"enabled\": false}（改即生效，无需重启）。\n"
        "· 维护清单（六项）：`task_cards/memory/README.md §四`。"
    )


def action_r3_notice_lost(payload):
    """UserPromptSubmit：卡被别的会话占用（takeover）+ R3 唤醒=关 ⇒ 告知一次（每卡一次）。"""
    if r3_wake_enabled():
        return ""
    me = _r3_session(payload)
    if not me or me == "-":
        return ""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import task_card as tc
        lost = _r3_taken_over_cards(tc, me)
    except BaseException as e:  # noqa: BLE001
        _diag("r3_notice_lost：无法 import task_card / 扫卡 ⇒ 跳过（%s）" % type(e).__name__)
        return ""
    if not lost:
        return ""
    state = _load_state("r3-notice", me)
    done = [str(x) for x in (state.get("cards") or [])]
    todo = [(cid, occ) for cid, occ in lost if cid not in done]
    if not todo:
        return ""
    state["cards"] = done + [cid for cid, _occ in todo]
    _save_state("r3-notice", me, state)
    # 🔴 同一张卡若已由 `ownership_lost` 出过（它现在会把「R3=关」的
    #   模式边界并进同一条提醒），本 action 不再单独出第二条；仍写状态，免得下轮重算。
    seen = set(str(x) for x in (_load_state("maint-notified", me).get("notified") or []))
    if all(cid in seen for cid, _occ in todo):
        return ""
    names = " · ".join(cid for cid, _occ in todo)
    return (
        "【AI-OS · R3 状态提醒】卡 `" + names + "` 已被**别的会话占用**（takeover）；"
        "R3 空闲唤醒 = **关** ⇒ 不会自动拉起维护。\n"
        "· 维护请按清单自行过一遍（六项见 `task_cards/memory/README.md §四`）。\n"
        "· ⛔ 开关变更前**先与用户确认**（不要自行切换）；用户同意后再把 `.aios/r3-wake.json` 写成 {\"enabled\": true}（改即生效，无需重启）。")


ACTION_FUNCS = {
    "task_recovery": action_task_recovery,
    "material_discovery": action_material_discovery,
    "field_candidates": action_field_candidates,
    "wrapup_writeback": action_wrapup_writeback,
    "ownership_lost": action_ownership_lost,
    "r3_notice_start": action_r3_notice_start,
    "r3_notice_lost": action_r3_notice_lost,
}


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def _read_payload():
    """读 DSH 写进 stdin 的事件 payload（claude-code 方言）。非 JSON / 空 ⇒ 空 dict（不阻塞）。

    ⚠️ 走 `sys.stdin.buffer` 显式按 **`utf-8-sig`** 解码 —— 不依赖 locale：Windows 默认 GBK 会把中文
    `prompt` 解坏，而 `prompt` 正是 R4 的输入（读数：解码坏 ⇒ `json.loads` 失败 ⇒ 静默不注入）。
    `-sig` 而非 `utf-8`：带 BOM 的输入（自测用 `Set-Content -Encoding utf8` 读数会写 `EF BB BF`）
    在 `utf-8` 下会让 `json.loads` 失败 ⇒ **整轮静默空 payload、所有 action 跳过**（假阴性）；
    `utf-8-sig` 对**无 BOM 输入完全等价**，只多剥一个 BOM。同目录 `scratch/_shadow_discovery.py`
    已按同一理由使用 `utf-8-sig`。
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        buf = getattr(sys.stdin, "buffer", None)
        if buf is not None:
            raw = buf.read().decode("utf-8-sig", errors="replace")
        else:
            raw = sys.stdin.read()
    except (OSError, ValueError, AttributeError):
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        _diag("stdin 不是合法 JSON ⇒ 视为空 payload")
        return {}
    return data if isinstance(data, dict) else {}


def main():
    event = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    payload = _read_payload()

    if not event:
        _diag("未给出事件名（用法：python tools/aios-hook.py <SessionStart|UserPromptSubmit|Stop>）⇒ 不执行任何 action")
        return 0

    declared = payload.get("hook_event_name")
    if isinstance(declared, str) and declared and declared != event:
        _diag("payload 的 hook_event_name=%s 与命令行事件 %s 不一致 ⇒ 以命令行事件为准（hooks.json 是权威）"
              % (declared, event))

    enabled, note = load_exposure()
    if note:
        _diag(note)

    # 🔴 诊断：真实 hook 子进程**是否看得到 `DSH_*`** 决定 `host_mode()` 判 dsh/cc，
    #   进而决定 `hosts` 门能不能拦住注入（B 方案依赖它）。一行，短。
    try:
        _dsh = sorted(k for k in os.environ if k.startswith("DSH_"))
        _diag("host=%s · DSH_*键=%d%s" % (host_mode(), len(_dsh), (" [" + ",".join(_dsh[:3]) + "]") if _dsh else ""))
    except BaseException:  # noqa: BLE001
        pass

    # 状态根探测**前置**（否则诊断会被 `field_candidates` 的长 stderr 挤到 2000 字符外、
    #   在 `hook/result.stderrSummary` 里被截掉 —— 那正是 一直"看不到原因"的一半原因）。
    _probe_state_dir()

    texts = []
    for name, spec in ACTIONS.items():
        if spec["event"] != event:
            continue
        if name not in enabled:
            _diag("action %s：**关闭**（开关未开启 / 默认全关）⇒ 跳过" % name)
            continue
        kind = spec["kind"]
        if kind == "writeback":
            timeout_s = WRITEBACK_TIMEOUT_S
        elif event == "UserPromptSubmit":
            timeout_s = PROMPT_TIMEOUT_S      # awaited ⇒ 收紧（§12.5）
        else:
            timeout_s = INJECT_TIMEOUT_S      # SessionStart 是 detached（§12.1）
        started = time.perf_counter()
        try:
            value = _run_isolated(ACTION_FUNCS[name], payload, timeout_s, name)
        except BaseException as e:  # noqa: BLE001 —— 一个 action 坏了不拖垮其余，也绝不阻塞 agent
            _diag("action %s 失败（%s: %s）⇒ 跳过（不阻塞）" % (name, type(e).__name__, e))
            continue
        _diag("action %s：完成（%.0f ms，%s）" % (name, (time.perf_counter() - started) * 1000.0, kind))
        if kind == "inject" and value:
            texts.append(str(value))

    # 注入型：有材料才输出那一行 JSON；无材料 ⇒ 什么都不输出（fail-closed，不注入半截）
    if event in ("SessionStart", "UserPromptSubmit") and texts:
        # ⚠️ **只走 `_PROTOCOL_OUT`**：`sys.stdout` 已被 action 隔离替换（见 `_run_isolated`）
        _PROTOCOL_OUT.write(json.dumps(
            {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "\n\n".join(texts)}},
            ensure_ascii=False))
        _PROTOCOL_OUT.write("\n")
        _PROTOCOL_OUT.flush()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 —— §12.0 ①：exit 0 恒成立
        _diag("dispatcher 顶层异常（%s: %s）⇒ exit 0（不阻塞 agent）" % (type(e).__name__, e))
        sys.exit(0)
