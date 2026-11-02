/** phase-policy.ts —— 由 `runtime/aios-activation.ts` 拆出（纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */
import { existsSync, readFileSync } from 'node:fs'

import { spawn } from 'node:child_process'

import { join } from 'node:path'
import { AIOS_ROOT, CARDS_DIR, aiosStateDir } from './../diagnostics/probe.ts'
import type { Occupancy, TaskCursor } from './../session/session-state.ts'

export type AiPhase = 'S1' | 'S2' | 'S3' | 'S4'

/** 阶段名（只用于注入文案；⛔ 不改既有探针字段语义）。 */

export interface PhaseSignals {
  /** 本会话**占用**的卡数（`myOccupiedCards().length` · 卡上真相）。 */
  ownedCards: number
  /** 本会话**已 release** 的次数（post-execute 从**成功**的 `task_card.py release` 命令字面量记账 · 内存）。 */
  releasedCards: number
  /** 本拍刚观察到一次 release（升沿 · 由 post-execute 观测段置位 ⇒ 收口那一步就能注，不等下一次 pre-step 刷新卡快照）。 */
  releasedThisStep: boolean
  /** 当前拍 `has-edit`（⚠️ 滚动窗口 `PROGRESS_WINDOW=6` ⇒ **会回落**）。 */
  hasEdit: boolean
  /** 本会话**曾**出现 `has-edit`（**锁存** —— ⛔ 滚动窗口回落不得把 S2 判回 S1； 同源风险）。 */
  everEdited: boolean
  /** 尾部连续失败数（与现有 `stuck` 判据同口径）。 */
  failStreak: number
}

/**
 * **阶段判定（纯函数 · 供单测 S145）** —— 由现有内存态推出 `S1|S2|S3|S4|null`。
 * 优先级 `S4 > S3 > S2 > S1` 与依据（逐条对齐设计稿 §4.1）：
 *   · `S4 收口`   = 本拍刚 release，或 本会话已 release 且**当前不再占用**卡（release = 收工锚）。
 *   · `S3 受阻`   = 尾部连续失败 ≥ 2（现有 `stuck` 判据 · 与 `detectEvents` 同口径）。
 *   · `S2 实现中` = 本会话**出现过实质改动**（`has-edit` **锁存** —— 只看滚动窗口会在连续 6 步无 edit 后回落）。
 *   · `S1 已决策` = 本会话**恰好占用 1 张卡**且**其后未发生实质改动**。
 *   · 其它 ⇒ `null`（⛔ 不猜：0 张卡 / 多张卡 / 无任何信号）。
 * ⚠️ 如实标注（报告里同样写明）：`releasedCards` 是**内存记账**（成功 release 的命令字面量），
 *    不像占用那样读卡上留痕 ⇒ 宿主用**非** `task_card.py` 的方式释放时 S4 不触发（⛔ 不猜）。
 *    这条只是"选收口类能力"，**不是**焦点卡判据 —— 占用真相仍在卡上。
 */

export function phaseOf(sig: PhaseSignals): AiPhase | null {
  if (sig.releasedThisStep || (sig.releasedCards > 0 && sig.ownedCards === 0)) return 'S4'
  if (sig.failStreak >= 2) return 'S3'
  if (sig.everEdited || sig.hasEdit) return 'S2'
  if (sig.ownedCards === 1) return 'S1'
  return null
}

/** 阶段注入**渲染/注入**条数（🔴 · 单变量实验：**5 → 1** —— 只注打分最高的那条；
 *  背景：能力注入 11 次、0 次进入 worker 推理 ⇒ 隔离「一次给 5 条」的认知成本。
 *  ⛔ 不动时机 / 文案 / 打分公式；请求 `budget` 用**另一个常量** `PHASE_BUDGET_CANDIDATES`（保持 5）。
 *  ⚠️ 旧口径（硬 ≤3 → 前 5）已由本值取代；与 inline 检索的
 *  `WORK_REPORT_RETRIEVAL_MAX_CANDIDATES=3` 仍是**两个通道**（本值只管**阶段注入**）。 */

export const PHASE_MAX_CANDIDATES = 1
/** 阶段检索请求的 `budget`（🔴 · 单变量实验：**保持 5**，与注入条数**拆成两个常量**）。
 *  为什么不同步改成 1：变量是"一次给几条"，不是"池子多大"；budget 若也变 1，
 *  就等于"池子里只有 1 条" ⇒ 测不出"从 5 个里挑 1 个"的认知成本，实验被污染。 */

export const PHASE_BUDGET_CANDIDATES = 5

// ── 🔴 （A/B 前置 · 约定）：开关与条数改为**文件配置** ────────────────────
//   要解决的两个缺陷（上一位 worker 自曝，已核实）：
//     ① 条数上限写死 `PHASE_MAX_CANDIDATES = 1` ⇒ 格装配（最多 3 片）**只渲染首片**，通用片几乎
//        永不出现 ⇒ A/B 实际比的是「格首片 vs 检索 top1」，**不是**「格装配 vs 整包」；
//     ② 开关是**环境变量** `AIOS_CAP_CELLS` ⇒ 同一宿主进程内无法切换 ⇒ A/B 要**重启两次**。
//   做法：新增 `.aios/cap-cells.json` = `{"enabled":false,"max":1,"form":"intro"}`；`enabled` 替代 env
//     开关（**env 保留作 override**：env 存在时以 env 为准，便于临时强制），`max` = **两条渲染路径共用**
//     的候选条数上限（格路径与检索路径都用它 —— A/B 公平性要求）。
//   🔴 （定的 C 组）：schema 再加 `form` = 格路径的**注入形态**
//     （`"intro"` = 只给介绍 + 位置 / `"action"` = 的现有能力块）。三组切换全靠这一个 JSON：
//       `enabled:false` ⇒ A 组（检索整包） · `enabled:true + form:"action"` ⇒ B 组 · `+ form:"intro"` ⇒ C 组。
//   ⛔ 缺省（文件不存在 / 解析失败 / enabled·max 字段缺失或类型错）⇒ `{enabled:false, max:1, form:"intro"}`
//     ⇒ 与改前**逐字一致**（既有用例的断言语义一条都不改；S170 直接盯住这条）。

export type CapCellsForm = 'intro' | 'action'
/** 格路径的缺省形态 = **保守档**（定：不预设"该动作"，只告诉 Agent 这格是干什么的）。 */

export const CELL_FORM_DEFAULT: CapCellsForm = 'intro'

export interface CapCellsConfig { enabled: boolean; max: number; form: CapCellsForm }

/**
 * `.aios/cap-cells.json` ⇒ 生效配置（**读法照既有开关文件**）。
 * 读法口径（与 `.aios/r3-wake.json` / `.aios/experience_recall.json` 一致）：
 *   · **懒读**：调用方每次现取（本函数就是唯一读取点）；
 *   · **缓存失效**：既有两个开关文件**都不缓存**（每次调用重读）⇒ 本函数同样不缓存
 *     ⇒ 改文件**下一拍即生效**，无需重启（这正是 A/B 的关键；`aiosStateDir()` 那条注释
 *     记的就是"模块加载时求值一次 ⇒ 开关改了没反应"的坑，⛔ 不重犯）；
 *   · **fail-safe**：读不到 / 解析失败 / 字段缺失或类型不对 ⇒ 回落缺省（⛔ 不抛错、⛔ 不影响宿主）；
 *   · 先剥 **UTF-8 BOM**（沿用 `r3WakeEnabled()` 的读数坑：中文 Windows 手写 JSON 常带 BOM，
 *     不剥 ⇒ `JSON.parse` 抛 ⇒ "看起来开了实际是关"且无任何报错）。
 * 字段语义（**enabled / max 整份生效或整份缺省** —— ⛔ 不做"部分字段生效"）：
 *   · `enabled` —— 必须是**布尔**；`true` 才算开（`"yes"` / `1` 这类 ⇒ 整份回落缺省，fail-closed）；
 *   · `max`     —— 必须是**正整数**；否则整份回落缺省。
 *   · 为什么要求两个字段都在：缺省口径必须能被 S170/S172 一句话盯死（"任何偏离 ⇒ 恰好
 *     `{enabled:false, max:1, form:"intro"}`"）；半份配置（如 `{"max":3}`）会制造"看起来配了其实没生效"的坑。
 *   · `form`    —— `"intro"` / `"action"`；**缺省 / 非法值一律回落 `"intro"`**（⛔ 不抛错）。
 *     ⚠️ 它与上面两项的口径**故意不同**：`form` 有**自己的缺省**，写错一个形态值不该把已经配好的
 *     开关 / 条数一起打回缺省（`enabled` / `max` 错 = 整份不可信 ⇒ 整份回落；`form` 错 = 只这一项不可信）。
 */

export function capCellsConfig(): CapCellsConfig {
  const fallback: CapCellsConfig = { enabled: false, max: PHASE_MAX_CANDIDATES, form: CELL_FORM_DEFAULT }
  try {
    const p = join(aiosStateDir(), 'cap-cells.json')
    if (!existsSync(p)) return fallback
    const j = JSON.parse(readFileSync(p, 'utf8').replace(/^\uFEFF/, ''))
    if (j === null || typeof j !== 'object' || Array.isArray(j)) return fallback
    const o = j as Record<string, unknown>
    if (typeof o.enabled !== 'boolean') return fallback
    const m = o.max
    if (typeof m !== 'number' || !Number.isSafeInteger(m) || m <= 0) return fallback
    return { enabled: o.enabled, max: m, form: cellFormOf(o.form) }
  } catch {
    return fallback
  }
}

/** **纯函数**：`form` 取值 ⇒ 生效形态（`"action"` 原样；缺省 / 其它任何值 ⇒ `"intro"`）。
 *  约束：⛔ 不抛错（非法值不是异常，是"用保守档"）；⛔ 不因它拖累 `enabled` / `max` 的判定。 */

export function cellFormOf(v: unknown): CapCellsForm {
  return v === 'action' ? 'action' : CELL_FORM_DEFAULT
}

/** 本次生效的候选条数上限 = `capCellsConfig().max ?? PHASE_MAX_CANDIDATES`（缺省 1）。
 *  格能力渲染路径（`renderCellCandidates`）已删除 ⇒ 现在**只剩**
 *     `renderPhaseCandidates` 消费本上限；`max` 仍从 `.aios/cap-cells.json` 现读（⛔ 勿连坐删）。 */

export type CapNudgeState = 'off' | 'on'

/** **纯函数**：`nudge` 取值 ⇒ 生效开关（**只认 `"on"`**；缺省 / 任何其它值 ⇒ `"off"`）。 */

export function capNudgeOf(v: unknown): CapNudgeState {
  return v === 'on' ? 'on' : 'off'
}

/**
 * `.aios/cap-cells.json` ⇒ 本开关是否开（**缺省 off**）。
 * ⚠️ 为什么**另起函数**而不是改 `capCellsConfig()`：`nudge` 不参与格路径判定，混进去会改变既有
 *   字段的语义 —— 本卡硬约束：`enabled` / `max` / `form` / `claimHint` **一律不受影响**。
 *   「整份校验」落在本开关上：`enabled` / `max` / `nudge` 任一不可信 ⇒ **本开关回落缺省（off）**；
 *   `form` / `claimHint` 各有自己的语义（前者有自身缺省、后者不属本开关）⇒ ⛔ 不拿来判本开关。
 */

export function capNudgeEnabled(): boolean {
  try {
    const p = join(aiosStateDir(), 'cap-cells.json')
    if (!existsSync(p)) return false
    const j = JSON.parse(readFileSync(p, 'utf8').replace(/^\uFEFF/, ''))
    if (j === null || typeof j !== 'object' || Array.isArray(j)) return false
    const o = j as Record<string, unknown>
    if (typeof o.enabled !== 'boolean') return false
    const m = o.max
    if (typeof m !== 'number' || !Number.isSafeInteger(m) || m <= 0) return false
    return capNudgeOf(o.nudge) === 'on'
  } catch {
    return false
  }
}

// ── 🔴 （已授权「1可以」）：**域能力注入**（替代检索打分的阶段注入）──────
//   背景（**已定的结构，⛔ 不要重新设计**）：能力库已**域合并** —— `capabilities/` 下 8 个
//     `domain-*.md`（前端/后端/数据/文档/产品/环境·运维/求职·职业/AI-OS 自身），一域一文件、
//     片不含 `class`（`CELLS.md` 已归档）。
//   ⇒ **不需要检索打分**：域对了就只有一个文件。
//     🔴 **更正**：域**不再靠判定**（`domainCapabilityOf()` 猜域读数不可靠，
//       精确率 topic 57% / 检索 47–59% / 路径 83%）⇒ 域改由 **agent 在卡上声明**、Runtime 读声明。
//       本节的开关 / 读法 / 探针 `ev` 全部沿用；`inferDomainOf()` / `domainCapabilityOf()` 保留为
//       纯函数（单测仍在用），⛔ 但注入路径不再调用。
//   旧检索路径（`buildPhaseRetrievalRequest` + `renderPhaseCandidates`）**保持不动**，
//     ⚠️ 但 `domainInject:"on"` 时**不再作为回退**（回退 = 继续用机器猜域；由 `!domainOn` 挡住）。
//   开关：`.aios/cap-cells.json` 的 `domainInject`（`"on"` / 缺省 `"off"`）。
//   读法：与 `capCellsConfig()` **同一文件、同一读法**（剥 BOM · 懒读 · 无缓存 · 整份校验 · ⛔ 不抛错）；
//     缺省 / 文件缺 / 字段非法 ⇒ **off**。
//   ⛔ **不影响** `enabled` / `max` / `form` / `claimHint` 的既有语义（各字段各读各的）。

export type DomainInjectState = 'off' | 'on'

/** **纯函数**：`domainInject` 取值 ⇒ 生效开关（**只认 `"on"`**；缺省 / 任何其它值 ⇒ `"off"`）。 */

export function domainInjectOf(v: unknown): DomainInjectState {
  return v === 'on' ? 'on' : 'off'
}

/**
 * `.aios/cap-cells.json` ⇒ 域能力注入是否开（**缺省 off**）。
 * 「整份校验」口径照 `capNudgeEnabled()`：`enabled` / `max` 缺或类型不对 ⇒ 整份不可信 ⇒ **off**
 *   （⛔ 不抛错）；`form` / `claimHint` 各有自身语义 ⇒ ⛔ 不拿来判本开关。
 * ⚠️ 为什么**另起函数**而不往 `capCellsConfig()` 的返回形状里加字段：那个形状被 S170 / S172
 *   （`{enabled,max,form}` 逐字快照）盯死 —— 加字段就等于改既有字段的语义，本卡硬约束 ⛔ 不允许。
 */

export function domainInjectEnabled(): boolean {
  try {
    const p = join(aiosStateDir(), 'cap-cells.json')
    if (!existsSync(p)) return false
    const j = JSON.parse(readFileSync(p, 'utf8').replace(/^\uFEFF/, ''))
    if (j === null || typeof j !== 'object' || Array.isArray(j)) return false
    const o = j as Record<string, unknown>
    if (typeof o.enabled !== 'boolean') return false
    const m = o.max
    if (typeof m !== 'number' || !Number.isSafeInteger(m) || m <= 0) return false
    return domainInjectOf(o.domainInject) === 'on'
  } catch {
    return false
  }
}

/** 三处能力记录的 **State 列字面量**（来源：`tools/task_card.py: CAPABILITY_STAGES`）。 */

export const CAP_RECORD_MARKS = { start: '能力-开工', impl: '能力-实现', close: '能力-收尾' } as const

export type CapRecordStage = keyof typeof CAP_RECORD_MARKS
/** 阶段 ⇒ **必填**的能力记录（S2 开工 · S4 收尾）。 */

export const CAP_NUDGE_NEED: Partial<Record<AiPhase, CapRecordStage>> = { S2: 'start', S4: 'close' }

/**
 * **纯函数**：`.log` 原文 ⇒ 缺哪几处能力记录（按 `start` / `impl` / `close` 顺序）。
 * 判据逐字对齐 `tools/task_card.py capability` 写的表格行：
 *   `| HH:mm | 能力-开工 | <name> ｜ 理由：… | Worker |`
 * ⇒ **只认 State 列**（⛔ 不在理由里匹配：理由里写到"能力-开工"不算已记录）。
 * 读不到 / 空 ⇒ 三处全缺（⛔ 不猜"已记录"）。
 */

export function missingCapRecordsOf(raw: string): CapRecordStage[] {
  const text = String(raw || '')
  const out: CapRecordStage[] = []
  for (const stage of ['start', 'impl', 'close'] as CapRecordStage[]) {
    const re = new RegExp('\\|\\s*' + CAP_RECORD_MARKS[stage] + '\\s*\\|')
    if (!re.test(text)) out.push(stage)
  }
  return out
}

/** 卡 ⇒ 缺哪几处能力记录（**唯一读取点**：卡的同级同名 `.log`；读失败 ⇒ 三处全缺）。 */

export function missingCapRecordsOnCard(card: TaskCursor): CapRecordStage[] {
  let raw = ''
  try {
    raw = readFileSync(cardLogPathOf(card.key), 'utf8')
  } catch {
    raw = ''
  }
  return missingCapRecordsOf(raw)
}

/** 合规提醒正文（**逐字固定** · ⛔ 不点名任何能力 · ⛔ 不带候选/建议/打分）。 */

export const CAP_NUDGE_TEXT = [
  '【AI-OS · 缺失记录】本阶段还没有记录「用了哪个能力」。',
  '  → 看一眼 capabilities/INDEX.md，然后用一条命令记录（收口前必须补）：',
  '    python tools/task_card.py capability <TASK-ID> --stage <start|impl|close> --name <能力名|none> --why "<一句>"',
].join('\n')

/** 阶段注入的检索等待上限（与内联检索 1500ms 同量级；超时只记 `spawn-failed`）。 */

export interface PhaseInjectSlot {
  /** 已注入（或已**尝试**）的阶段 —— **去重的真相**：每阶段每会话最多一次。 */
  sent: Set<AiPhase>
  /** 已报过 `state:"dup"` 的阶段 —— 防每拍一条 dup 探针把日志刷满（读数只需一条）。 */
  dupReported: Set<AiPhase>
  /** 已报过 `state:"no-anchor"` 的阶段（无卡静默不注 · 读数每阶段一条，⛔ 也不进 `sent`）。 */
  noAnchorReported: Set<AiPhase>
  /**
   * 本会话**首拍**是否已判过（**独立标记** —— ⛔ 不复用 `sent`：`sent` 是"每阶段一条"的
   *   阶段去重真相，首拍若写进 `sent` 会把 S1 记账掉 ⇒ 常规 S1 永不再注（S167 拦回归））。
   *   置位后**永不回退**（首拍只判一次 · 不补拍）。
   */
  firstStepDone: boolean
  /** 首拍 `state:"dup"` 是否已报（每会话最多一条，防每拍一条把探针刷满）。 */
  firstStepDupReported: boolean
  /** `has-edit` 锁存（见 `PhaseSignals.everEdited`）。 */
  everEdited: boolean
  /**
   * 本会话已**检查过**能力记录的阶段（S2/S4）。
   *   用途：`.log` 只在每阶段**首次进入**读一次 ⇒ 不按每拍读盘（大 `.log` 的成本可控）。
   */
  nudgeChecked: Set<AiPhase>
  /**
   * 已发过合规提醒的阶段 —— **独立 Set**（⛔ 不复用 `sent`：`sent` 是阶段注入的去重真相，
   *   提醒与"注没注能力块"是两件事）。
   */
  nudgeSent: Set<AiPhase>
  /** 已报过 `state:"dup"` 的阶段（每阶段最多一条 dup 探针，⛔ 不每拍刷）。 */
  nudgeDupReported: Set<AiPhase>
  /**
   * 该阶段**最后一次**注入所用的域能力名（**声明通道的去重真相**）。
   *   `undefined` ⇒ 该阶段还没注过；`=== 当前声明` ⇒ 不重复（落一条 `dup` 读数）；
   *   `!== 当前声明` ⇒ 声明变了 ⇒ **再注入一次**（`state:"re-injected"` + `prev`）。
   *   ⛔ 不复用 `sent`：`sent` 是"每阶段一条"的旧口径，与"声明变了要再注"直接冲突。
   */
  injectedCap: Map<AiPhase, string>
  /** 已报过 `state:"dup"` 的阶段（声明通道 · 每阶段一条，⛔ 不每拍刷）。 */
  declaredDupReported: Set<AiPhase>
}

export const PHASE_INJECT = new Map<string, PhaseInjectSlot>()

export function emptyPhaseInjectSlot(): PhaseInjectSlot {
  return {
    sent: new Set(), dupReported: new Set(), noAnchorReported: new Set(),
    firstStepDone: false, firstStepDupReported: false, everEdited: false,
    nudgeChecked: new Set(), nudgeSent: new Set(), nudgeDupReported: new Set(),
    injectedCap: new Map(), declaredDupReported: new Set(),
  }
}

export function phaseInjectSlotOf(session: string): PhaseInjectSlot {
  let slot = PHASE_INJECT.get(session)
  if (slot === undefined) {
    slot = emptyPhaseInjectSlot()
    PHASE_INJECT.set(session, slot)
  }
  return slot
}

/**
 * 阶段注入开关：
 *   · `AIOS_PHASE_INJECT=off` ⇒ 强制关（**测试隔离** · 与 同纪律）；
 *   · `.aios/phase_inject.json` 若存在且 `enabled:false` ⇒ 关（改即生效，无需重启）；
 *   · 缺省**开** —— 外层还有 `inject_probe.json` 探针门（`injectOn`），两把门都开才注入。
 */

export function phaseInjectEnabled(): boolean {
  if (process.env.AIOS_PHASE_INJECT === 'off') return false
  try {
    const p = join(aiosStateDir(), 'phase_inject.json')
    if (!existsSync(p)) return true
    const j = JSON.parse(readFileSync(p, 'utf8'))
    return !(j !== null && j !== undefined && (j as Record<string, unknown>).enabled === false)
  } catch {
    return true
  }
}

/** 本会话**已被检索返回过**的能力 id（`auto_capability` 内联检索 + 阶段注入共用）——
 *  设计稿 §4.4：「同一能力已被 `auto_capability` 返回过 ⇒ 不再注」。 */

export function cardLogPathOf(key: string): string {
  const md = key.toLowerCase().endsWith('.md') ? join(CARDS_DIR, key) : join(CARDS_DIR, key + '.md')
  return md.toLowerCase().endsWith('.md') ? md.slice(0, -3) + '.log' : md + '.log'
}

/** `taskId`（命令字面量里的 `项目/TASK-ID` 或裸 ID）⇒ `.log` 路径。
 *  ⛔ 不依赖 `knownCardKeys`（子 agent 接手时可能为空）—— 直接从命令给出的 ID 定位。 */
