/** lifecycle.ts —— 由 `runtime/aios-activation.ts` 拆出（纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */
import { readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from 'node:fs'

import { spawn } from 'node:child_process'

import { join } from 'node:path'
import type { Occupancy, TaskCursor } from './session-state.ts'
import { CARDS_DIR } from './../diagnostics/probe.ts'
import { AIOS_ROOT, OBS, POLICY, emit, mono, readHead, readTail, resolveStateFile, CARD_NAME_RE, WORK_REPORTS } from './../diagnostics/probe.ts'

import { noteCatchFail } from './../diagnostics/probe.ts'
import type { SessionState } from './session-state.ts'
import { name } from './../diagnostics/probe.ts'

export const FOCUS_CARD_SCHEMA = 'focus-card/v1'
/**
 * 有效期（**首版值 · 无验证基线** · 裁定 10 分钟）。
 * ⚠️ 自**成功写入时刻**（`writtenAt`）起算；达到边界即视为过期。
 * 该值是否合适，由"双轨期的实际回退比例"回答 —— ⛔ 不得先验声称已验证。
 */

export const FOCUS_CARD_TTL_MS = 600_000

/** 接口文件路径（三级兜底与 `resolveStateFile()` 同构 · env 覆盖**仅供隔离自测**）。 */

export function focusCardFile(): string {
  return process.env.AIOS_FOCUS_CARD || resolveStateFile('focus-card.json', '_focus-card.json')
}

/** 写入计数（内存 · 只读诊断 · ⛔ 不是事实源）。 */

export const FOCUS_CARD_STATS = { written: 0, unchanged: 0, noCard: 0, failed: 0 }

/**
 * **语义芯** —— 只有这四个字段相同才算"内容未变"。
 * 🔴 `windowSeq` / `writtenAt` / `expiresAt` **刻意不计入**：它们是时间性字段；
 *    若计入就变成"每次触发都写" ⇒ 等于把"刷新时间戳"当成写盘理由（明确禁止）。
 */

export function focusCardCore(o: any): string {
  return JSON.stringify([o?.session ?? null, o?.cwd ?? null, o?.card ?? null, o?.basis ?? null])
}

/**
 * 把 `focusCardOf()` 的判定结果交给跨语言接口（**幂等 · 原子 · 失败透明**）。
 * @returns `'written' | 'unchanged' | 'no-card' | 'failed'`（同时累加 `FOCUS_CARD_STATS`）
 */

export function writeFocusCard(s: SessionState, session: string, cwd: string): string {
  try {
    const focus = focusCardOf(s)
    if (focus.key === null || focus.key === '') {
      FOCUS_CARD_STATS.noCard += 1
      return 'no-card'
    }
    const file = focusCardFile()
    const now = Date.now()
    const next = {
      schema: FOCUS_CARD_SCHEMA,
      session,
      cwd,
      card: focus.key,
      basis: focus.basis,
      windowSeq: s.windowSeq,
      writtenAt: now,
      expiresAt: now + FOCUS_CARD_TTL_MS,
      writer: name,
      writerPolicy: POLICY,
    }
    // 🔴 **不变不写**（含"已过期也不刷新"）：先读现有件、只比**语义芯**
    try {
      const cur = JSON.parse(readFileSync(file, 'utf8')) as Record<string, unknown>
      if (cur !== null && typeof cur === 'object' && cur.schema === FOCUS_CARD_SCHEMA
          && focusCardCore(cur) === focusCardCore(next)) {
        FOCUS_CARD_STATS.unchanged += 1
        return 'unchanged'
      }
    } catch (err) {
      noteCatchFail('state:focus', err)
      /* 不存在 / 损坏 / 版本不符 ⇒ 一律按"需要写"处理（⛔ 不尝试解析旧版） */
    }
    // ── 原子写：同目录临时件 ⇒ `renameSync` 替换 ──
    const tmp = file + '.tmp-' + process.pid + '-' + Math.random().toString(36).slice(2, 8)
    try {
      writeFileSync(tmp, JSON.stringify(next, null, 2) + '\n', 'utf8')
      renameSync(tmp, file)
    } catch (err) {
      // 写失败 ⇒ 清掉可能残留的临时件（⛔ 绝不触碰旧文件）
      try { rmSync(tmp, { force: true }) } catch { /* 静默 */ }
      throw err
    }
    FOCUS_CARD_STATS.written += 1
    return 'written'
  } catch {
    FOCUS_CARD_STATS.failed += 1
    return 'failed'
  }
}

// ── 🔴 **提醒型递送**（批准「提醒型先行」· 候选型仍等质量验证）────────────
// 为什么挂在 `post-execute`：DSH 的扩展点里**只有 `tools/post-execute` 能「向下游决策添加上下文」**
//   （`agent/pre-step` / `tools/pre-execute` 只能 deny/allow）⇒ 提醒的实际时机 = **某个工具刚执行完**
//   = 工作已经开始（与 `discovery-opportunity` 同一判据：「首个实质工作意图」）。
// 🔴 边界（逐条硬约束）
//   · **默认完全透明**：开关文件缺失 / 非法 / 未启用 ⇒ 不读判据、不附加（零开销）
//   · **每会话每类最多一次** —— ⛔ 每步都提醒就是噪声（`AUTOMATION-BOUNDARY §12.0.1` 的教训）
//   · **只提醒，不代替宿主动作**：⛔ 不自动 `claim` · ⛔ 不自动改 `State` · ⛔ 不自动 `release`
//   · 判据**全机械**（Runtime 无 LLM）· 失败**原样透传**下游 decision

export function cardLogPathOfTaskId(taskId: string): string {
  const md = join(CARDS_DIR, taskId + '.md')
  return md.toLowerCase().endsWith('.md') ? md.slice(0, -3) + '.log' : md + '.log'
}

/** 🔴 **接手检查正文**（claim 后向前一不同会话注入 · 与维护清单同口径）。 */

export function lastOccupancyOf(raw: string): Occupancy | null {
  if (!raw) return null
  const lines = raw.split('\n')
  for (let i = lines.length - 1; i >= 0; i--) {
    const m = /\|\s*(claim 占用|release 释放)（session:\s*([^）]*)）/.exec(lines[i])
    if (m !== null) {
      return { op: m[1] === 'claim 占用' ? 'claim' : 'release', session: String(m[2] || '').trim() }
    }
  }
  return null
}

/**
 * 卡 ⇒ **占用判据**（Event Log **外置**后必须优先读外置日志）。
 * 顺序：① **同级同名 `.log`**（的新格式 · 小文件 · 语义明确）
 *       ② 卡内 `readTail`（**兼容**尚未迁移的旧卡）
 * 为什么必须改：外置后卡内只剩**指针** ⇒ 继续只读卡内 = 占用永远 null ⇒
 *   焦点卡 / stage4 / R3 / 多占用提醒**再次静默失效**（的同类问题，第三次咬）。
 * ⛔ 不写文件；读失败一律回退。
 */

export function occupancyOfCard(p: string): Occupancy | null {
  try {
    const logPath = p.toLowerCase().endsWith('.md') ? p.slice(0, -3) + '.log' : p + '.log'
    const o = lastOccupancyOf(readFileSync(logPath, 'utf8'))
    if (o !== null) return o
  } catch (err) {
    noteCatchFail('state:occupancy', err)
    /* 无外置日志 ⇒ 走兼容路径 */
  }
  return lastOccupancyOf(readTail(p))
}

/** 递归列出卡文件（只读目录，不建索引）。 */

export function field(head: string, re: RegExp): string {
  const m = re.exec(head)
  return m && m[1] !== undefined ? m[1].trim() : ''
}

/**
 * **只读**扫描 active 卡的任务事实（`State:` / `Current Step:`）。
 * ⚠️ 这不是"发现算法"—— 检索 / 评分 / 能力注册仍全部在 Python（`§14.9.1`）。
 *    这里只读 §14.8 信号表第一行所指的「**任务卡状态变化**」。
 */

export function scanCards(): TaskCursor[] {
  const out: TaskCursor[] = []
  for (const p of listCardFiles(CARDS_DIR)) {
    const head = readHead(p)
    if (!head) continue
    const rawState = field(head, /^\s*State:\s*(.+)$/m)
    const state = (rawState.split(/\s+/)[0] || '').replace(/[^\w-]/g, '')
    out.push({
      key: p.slice(CARDS_DIR.length + 1),
      state,
      step: field(head, /^\s*Current Step:\s*(.+)$/m),
      // S2增读 `Goal` / `Next Action` —— 属"已有事实"，不新增结构
      goal: field(head, /^\s*Goal:\s*(.+)$/m),
      next: field(head, /^\s*Next Action:\s*(.+)$/m),
      // 🔴 步骤 2占用的**真相**来自卡内 `Event Log` ——
      //    只对 `State=Executing` 的卡读尾部（省 I/O：非占用卡不可能有"当前占用者"）。
      occupancy: state.toLowerCase() === 'executing' ? occupancyOfCard(p) : null,
    })
  }
  return out
}

// ── 🔴 **启动回收：作废上一个进程的遗留占用**（**破例**授权）────────────
//   问题：`State` 写在卡文件里（**持久**），而"谁占用"活在进程内存里
//     ⇒ 重启后卡仍是 `Executing`、内存已空 ⇒ **孤儿占用**：
//       ① 任何新对话都 `claim` 不进任何卡（`task_card.py` 的**全局互斥**挡住）
//       ② 占用判据若只看卡级状态，就会把**上个进程**的卡当成"当前占用"
//   裁定：⛔ **破例**允许 Runtime 在启动时把遗留的 `Executing` 改回 `Parked`
//     （原纪律 `GOAL-INPUT-CONTRACT.md §2.6 S2 ①`「Runtime / 脚本**绝不自动改** `State`」——
//      明确破例；理由 = `Executing` 只应在**进程生命周期内**有效。）
//   判据（全机械 · ⛔ 无猜测）：**新进程的会话表必为空** ⇒ 卡池里所有 `Executing` 都是遗留。
//   ⛔ 每进程**只做一次** · ⛔ **不阻塞**（`setTimeout(0)` + `stdio:'ignore'`）· 失败静默只计数。
//   ⛔ 写入口仍是**工具**（`task_card.py release --state=Parked --reason=startup-recover`）——
//      单一 owner；Runtime ⛔ **不直接改卡文件**。

/** 启动回收判据（**纯函数 · 供隔离自测**）：返回需要回收的卡 key（`State=Executing`）。 */

export function legacyExecutingCards(cards: TaskCursor[]): string[] {
  return cards.filter(c => String(c.state || '').toLowerCase() === 'executing').map(c => c.key)
}

/** 🔴 （真修复）：回收时传给 `task_card.py release` 的卡 ID —— **⛔ 不剥项目前缀**。
 *  旧实现 `key.split('/').pop()` 把 `active/<项目>/TASK-x.md` 剥成裸 `TASK-x` ⇒ 跨项目重名时
 *  `task_card.py` 按 拒收裸 ID ⇒ 回收**静默失败**（探针只有 `phase:"done", ok:false`）、孤儿占用留着。
 *  `active/<项目>/TASK-x.md` ⇒ `<项目>/TASK-x`；`active/TASK-x.md` ⇒ `TASK-x`。 */

export function startupRecoverIdOf(key: string): string {
  return String(key === null || key === undefined ? '' : key)
    .replace(/^active[\\/]/, '')
    .replace(/\.md$/, '')
}

/** 启动回收计数（内存 · 只读诊断 · ⛔ 不是事实源）。 */

export const STARTUP_RECOVER_STATS = { scanned: 0, spawned: 0, ok: 0, failed: 0 }

export let STARTUP_RECOVER_RAN = false

/** 启动回收（**每进程一次** · 异步 · 失败静默）。 */

export function startupRecover(): void {
  if (STARTUP_RECOVER_RAN) return
  STARTUP_RECOVER_RAN = true
  try {
    const legacy = legacyExecutingCards(scanCards())
    STARTUP_RECOVER_STATS.scanned = legacy.length
    emit({
      ev: 'startup-recover', obs: OBS, phase: 'scan', legacy: legacy.length, cards: legacy,
      at: Date.now(), mono: mono(),
      note: '新进程 ⇒ 卡池里所有 Executing 均为**上一个进程的遗留** ⇒ 逐个 release --state=Parked（Human 2026-10-16 破例授权）',
    })
    for (const key of legacy) {
      const id = startupRecoverIdOf(key)
      if (!id) continue
      STARTUP_RECOVER_STATS.spawned += 1
      const child = spawn('python',
        [join(AIOS_ROOT, 'tools', 'task_card.py'), 'release', id,
         '--state=Parked', '--reason=startup-recover'],
        { cwd: AIOS_ROOT, stdio: 'ignore' })
      child.on('error', () => {
        STARTUP_RECOVER_STATS.failed += 1
        emit({ ev: 'startup-recover', obs: OBS, phase: 'error', card: key, at: Date.now(), mono: mono() })
      })
      child.on('exit', (code: number | null) => {
        if (code === 0) STARTUP_RECOVER_STATS.ok += 1
        else STARTUP_RECOVER_STATS.failed += 1
        emit({
          ev: 'startup-recover', obs: OBS, phase: 'done', card: key, code, ok: code === 0,
          at: Date.now(), mono: mono(),
        })
      })
    }
  } catch (err) {
    noteCatchFail('state:startup', err)
    /* 回收失败绝不影响宿主（与既有纪律一致） */
  }
}

/** 主 / 子会话身份（阶段 1 读数判据；**缺失一律 unknown**，不推断）。 */
/** ── 从 maintenance/r3-wake.ts 上收的共享声明 ── */
export function myOccupiedCards(s: SessionState): TaskCursor[] {
  const mine = String(s.me || '')
  if (mine === '') return []
  return (s.cards || []).filter(c =>
    String(c.state || '').toLowerCase() === 'executing'
    && c.occupancy !== null
    && c.occupancy.op === 'claim'
    && c.occupancy.session === mine)
}

/**
 * 🔴 **焦点卡判定**（唯一入口 —— Runtime 与 Hook 都必须消费它，⛔ 不得各自再推一套）：
 *   裁定：**焦点卡 = 「在这个对话中占用的卡」** ⇒ 判据 = `myOccupiedCards()`：
 *     ① **恰好 1 张** ⇒ 就是它（`basis: 'card-claim'`）
 *     ② **> 1 张** ⇒ **不猜** —— 属**异常状态**（「一个对话同时只能占用一张卡」）；
 *        由 `reminderFor()` 的 `multi-claim` 提醒让 Agent **自己收敛**
 *        （⛔ Runtime 不自动释放/替换 —— `GOAL-INPUT-CONTRACT.md §2.6 S2 ①`）
 *     ③ **0 张** ⇒ `null`（`basis:'none'`）—— ⛔ **不退回**"环境唯一 `Executing`"
 *   ⛔ **为什么删掉 `env-unique-executing` 兜底**：它拿**卡级全局状态**（哪张卡是 `Executing`）
 *      去冒充**会话级占用**（哪个对话在用它）⇒ 没有占用关系的对话会被套上别人的卡
 *      （读数：产品会话 `demo-project-v2` 被判成 `AI-OS-Adaptation/TASK-20261016-001.md`）。
 *      读数口径：删兜底前 `focusBasis` 分布 = `env-unique-executing` **32** / `session-card-edit` **6**
 *      （⇒ **84% 的焦点卡是兜底套上去的**）。
 *   ⚠️ `cardEdits` / `cardReads` **退为提醒触发与审计证据**（`GOAL-INPUT-CONTRACT.md §2.6 S2`），
 *      ⛔ 不再参与焦点卡判定 —— 因此**"编辑卡"不等于"占用卡"**。
 */

export function focusCardOf(s: SessionState): { key: string | null; basis: string } {
  const mine = myOccupiedCards(s)
  if (mine.length === 1) return { key: mine[0].key, basis: 'card-claim' }
  if (mine.length > 1) return { key: null, basis: 'card-claims-multiple:' + mine.length }
  return { key: null, basis: 'none' }
}

// ── 🔴 **焦点卡跨语言接口**（`focus-card/v1` · **步 1 = 只写侧**）──────────────────────────
//  契约与判据的唯一来源：`task_cards/active/demo-project/p0/FOCUS-CARD-INTERFACE-DESIGN.md`
//  🔴 修的是 **V-2**（选卡判据漂移）：Runtime 已用 `focusCardOf()`，而 Hook 的 R2 写回**仍用
//     git 事实** ⇒ 同一工作区可能得出两个答案（`RESPONSIBILITY-BOUNDARIES.md §5 越界 #1` 读数过）。
//     本文件 = "由 Runtime 把判定结果交给 Hook" 的**唯一传递面**。
//  🔴 边界（逐条落地 · ⛔ 不得放宽）
//    · **唯一写入方 = Runtime**；⛔ 本文件**不是任务事实源**（删掉它不损失任何任务事实）
//    · **只写标识符级字段** —— ⛔ 不含推理原文 / 卡正文 / 工具参数
//    · **原子写**：同目录 `<target>.tmp-<pid>-<rand>` ▸ `renameSync` 替换
//      （同卷 rename 原子 ⇒ 读者**永不见半截 JSON**；写失败**不破坏**旧文件）
//    · **不变不写**：语义芯（`session` / `cwd` / `card` / `basis`）未变 ⇒ **不写**
//      🔴 **即使文件已过期也不刷新** —— ⛔ 不得用"重写一遍"把旧判定**伪装成新鲜证据**
//      （明确）。过期就该让读者走旧 Git 回退、并计入回退统计。
//    · **失败透明**：任何异常 ⇒ 静默 + 只计数（⛔ 绝不阻塞宿主、绝不改宿主 decision）

export function reminderFor(s: SessionState): { kind: string; text: string } | null {
  // ⓪ 🔴 **一个对话同时只能占用一张卡**（补丁）——
  //    判据 = **卡上**读出的"本会话占用" > 1（`myOccupiedCards()` · 与焦点卡**同源**）。
  //    检测到 ⇒ **注入提醒**让 Agent 自己收敛；⛔ 不静默替换、⛔ 不自动 release。
  const myClaims = myOccupiedCards(s)
  if (myClaims.length > 1 && !s.reminderC) {
    s.reminderC = true
    const names = myClaims.map(c => String(c.key).split('/').pop()).join(' · ')
    return {
      kind: 'multi-claim',
      text: '【AI-OS · 任务卡】本对话同时占用了 **' + myClaims.length + '** 张卡：' + names + '\n'
        + '· 🔴 **一个对话同时只能占用一张**（多占用会让焦点卡判不出来）⇒ 请保留当前在用的那张，\n'
        + '  ⚠️ 且**只能占用「未被占用」的卡** —— 被别的对话占用的卡对你 = 不可用（占用是排他的）\n'
        + '  其余释放：`python tools/task_card.py release <TASK-ID> --state=Parked`\n'
        + '· 释放的含义 = **退出占用**，该卡状态回到「**进行中**」\n'
        + '  （`Parked` = 未完成 · 可恢复 · 随时能再 `claim`；⛔ 不是"已完成"，也⛔ 不是"放弃"）\n'
        + '⛔ Runtime **不会**替你释放或替换（只提醒）。忽略本提醒不影响继续工作。',
    }
  }
  // ⓪·五 🔴 · 可知性 **C**：首次需要时**提醒一次**「该用 `auto_capability`」
  //   判据：本会话**已有实质改动**（`has-edit`）但**从未上报** ⇒ 说明"这次要干什么"没告诉工作模块
  //   ⇒ 提醒一次（⛔ 不常驻、不重复、不阻塞）；与 `dispatchStage4` 的 `ev=work-report-missed` 配对成为**可数读数**。
  //   ⚠️ 仍**只是提醒**：⛔ 不代替宿主动作、⛔ 不注入候选、⛔ 不阻断（忘了报 ⇒ 检索自动回退旧通道）。
  if (!s.reminderD && s.wc.progress.signals.includes('has-edit')
      && (WORK_REPORTS.get(String(s.me || '')) ?? []).length === 0) {
    s.reminderD = true
    return {
      kind: 'work-report',
      text: '【AI-OS · 能力提示】这次工作已经有实质改动了，但还没向 AI-OS 说过「你在做什么 / 需要什么能力」。\n'
        + '· 当你想用某种能力、或**要做某件事**时，调用 `auto_capability`：说清在做什么 + 想要哪类能力（need 取词表三维），\n'
        + '  它会按字段去查 AI-OS 现有的能力 / 知识，把可能用得上的东西（skill / 经验 / 候选）找回来。\n'
        + '· 例：做前端页面 → `{"what":"做作品集首页","need":["前端","实现"],"confirmed":"user"}`\n'
        + '· ⛔ 不必每步都报；有变化才说。⛔ 没跟对方确认过的判断用 `confirmed:"agent-inferred"`（只当假设存）。\n'
        + '忽略本提醒不影响继续工作（检索会自动回退到旧的事件推导通道）。',
    }
  }
  const anchored = s.cardEdits.size > 0 || s.cardReads.size > 0
  if (!anchored && !s.reminderA) {
    s.reminderA = true
    return {
      kind: 'no-anchor',
      text: '【AI-OS · 任务卡】本会话还没有工作锚点（未读、未改任何任务卡）。\n'
        + '· 已有任务 ⇒ 到 `task_cards/active/` 找到对应的卡并**占用**它：'
        + '`python tools/task_card.py claim <TASK-ID>`\n'
        + '· 🔴 **只能占用「未被占用」的卡** —— 被别的对话占用的卡，对你 = **不可用**\n'
        + '  （占用是**排他**的：它只属于占用者，⛔ 不是"谁都能用"）\n'
        + '· 新工作 ⇒ `python tools/task_card.py create "<标题>"`\n'
        + '⛔ 不占用就没有焦点卡（检索与恢复都用不上）。忽略本提醒不影响继续工作。',
    }
  }
  // 原 `reminderB`（maintain / 收尾提醒）**已移除** —— 按 约定`CONCLUSIONS #32`
  //    「收尾提醒与维护清单**全部移交 R3**」。R3 的注入点在 `tools/post-execute` 的
  //    `maintenanceChecklist()`（卡**释放后**注入维护清单）；⛔ 不再由本函数发收尾提醒，
  //    否则同一时刻会出现两条收尾提醒（重复打扰）。
  //    `reminderB` 字段保留但**不再使用**（防结构漂移；待 R3 拆成独立插件时一并删）。
  return null
}

// ── 🔴 · **R3 收工维护**（授权「D 三个时段 runtime 实现」· R1 暂不做）──
//   裁定来源：`CONCLUSIONS #31/#32/#37` ——「卡被 release」是**唯一收工锚**；
//     R3 = 检测 release ⇒ **注入"维护清单"**，由 Agent 执行（⛔ Runtime 不自动改知识 / 卡）。
//   落地形态（过渡）：先驻在 R2 插件内 —— 因为 **独立插件要改宿主 profile**（沙箱外），
//     需 手动安装；待打包成 profile bundle 时再拆（`§7.5 阶段 5`）。⛔ 不改本插件的 `inject`。
/** 每会话**维护提示上限**（⛔ 不能无限：占用抖动时不该反复打扰；3 次足够覆盖重占/被抢）。 */

export function listCardFiles(dir: string): string[] {
  const out: string[] = []
  let entries
  try {
    entries = readdirSync(dir, { withFileTypes: true })
  } catch {
    return out
  }
  for (const e of entries) {
    const p = dir + '/' + e.name
    if (e.isDirectory()) out.push(...listCardFiles(p))
    else if (e.isFile() && CARD_NAME_RE.test(e.name)) out.push(p)
  }
  return out
}
