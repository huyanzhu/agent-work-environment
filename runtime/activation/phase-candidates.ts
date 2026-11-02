/** phase-candidates.ts — 从 `runtime/delivery/phase-injection.ts` 拆出的
 *  「阶段打分 / 候选渲染」闭包（22 个顶层声明逐字搬入，只加 `export`）。
 *  🔴 行为零变化：声明正文与原文件逐字一致；⛔ 本文件只做「搬家」，改逻辑请回原模块并跑 202 项自测。
 *  ⚠️ import 面按「去注释/字符串后的真实引用」重算 —— 搬运器按原文（含注释）接线会引入
 *      `phase-injection` 的循环 import（注释里提到的 `firstStepInjectOnce` 等），已剔除。
 */
import { PHASE_TITLE } from './declared-domain.ts'
import type { AiPhase } from './phase-policy.ts'
import { PHASE_BUDGET_CANDIDATES, capCellsConfig } from './phase-policy.ts'
import type { WorkReportRecord } from '../diagnostics/probe.ts'
import { WORK_REPORTS, clip } from '../diagnostics/probe.ts'
import { WR_CONCERN_VALUES, WR_DOMAIN_VALUES, WR_HELP_TYPES, isCapabilityCandidatePath, retrievalCandidatesOf } from '../retrieval/request-builder.ts'
import type { TaskCursor } from '../session/session-state.ts'
import type { WorkContext } from '../session/work-context.ts'

export function tokensOf(items: string[]): Set<string> {
  const out = new Set<string>()
  for (const raw of items) {
    const s = String(raw || '').toLowerCase()
    for (const w of s.match(/[a-z0-9_]{2,}/g) || []) out.add(w)
    const cjk = s.replace(/[^\u4e00-\u9fff]+/g, ' ')
    for (const seg of cjk.split(/\s+/)) {
      for (let i = 0; i + 2 <= seg.length; i++) out.add(seg.slice(i, i + 2))
    }
  }
  return out
}

// ── Step B′ · 最小递送验证（**批准的边界** · 一次性静态标记）──────
// 🔴 **授权边界（不得扩大）**：
//   · **只**在受控的**主 Agent 测试会话**里，经 `tools/post-execute` 附加一段**固定标记文本**
//   · **不读取 / 不递送推理原文** · **不连接 Python 检索** · **不调远程 LLM**
//   · **不修改**现有注入开关（`.claude/aios-exposure.json`）的语义
//   · **不改变工具原始执行结果**（`{...downstream}` 保留 `content` / `value`）
//   · **不建立新的持久化事实状态** —— 下面是**启停开关**（只存控制 · 不存事实 · 同 R0 定位）
//   · **不等待**：固定标记直接附加，**不做任何异步准备**
//     （"动态就绪 / 未就绪就不附加"的分支留到后续**单独**实施与测试）
// 🔴 开关 = **本地文件 · 每次调用重新读取**（同 R0 纪律）；文件缺失 / 非法 / 未启用 ⇒ **完全透明**
//    （`return next()` ⇒ 与旧版行为**逐字一致**）

export function latestWorkReport(session: string): WorkReportRecord | null {
  const list = WORK_REPORTS.get(session)
  if (list === undefined || list.length === 0) return null
  return list[list.length - 1]
}

// ── 🔴 **从命令行识别「占用 / 释放」动作**（补 `claim` / `release` 的观测缺口）────
// 缺口：`claim` / `release` 由 `tools/task_card.py` 执行，走的是**命令行**（`pwsh` 工具），
//   ⛔ 不是 `edit` / `write` ⇒ 只观测这两个工具的 `cardEdits` **看不见占用动作**，
//   于是"宿主的占用"对 Runtime 不可见，焦点卡只能靠 `wc.cardKey`（唯一 `Executing`）兜底，
//   而那个值只在 `agent/pre-step` 重算 ⇒ 同一 turn 内 claim 完看不到焦点。
// 做法：从 `pwsh` 的**命令参数**里**机械识别** `task_card.py (claim|release) <TASK-ID>` ——
//   ⛔ 不是猜意图：命令是宿主**显式写下**的字面量，与"读卡路径"同一条证据纪律。
// 边界（如实）：① 手工用 `edit` 改 `State` ⇒ 走 `cardEdits` ✓；② 手工用 `Set-Content` 等**别的**
//   写法改 `State` ⇒ **仍看不见**（那时由 `wc.cardKey` 唯一 `Executing` 兜底）；
//   ③ 只在命令**成功**时记账（`claim` 被拒时卡的 `State` 没变，记账会给出**虚假焦点**）。

export function phaseMaxCandidates(): number {
  return capCellsConfig().max
}

// ── **能力合规提醒（nudge）** ────────────────────────────────
//   背景（今天读数，别改前提）：能力**注入**（推送推荐）4 轮真实任务 / 15 次注入 / **0 次**成为决策输入，
//   且结构上晚于决策；而「必须填」的三点账本 24+ 卡 × 3 stage 全 PASS ⇒ 把 runtime 的角色从
//   「递送推荐」改成「**合规提醒**」：只提醒"你还缺记录"，⛔ **不点名任何能力**。
//   开关：`.aios/cap-cells.json` 的 `nudge`（`"off"` 缺省 / `"on"`）—— **缺省 off ⇒ 本段一行都不执行**。
//   读法：与 `capCellsConfig()` 同一文件、同一 fail-safe 口径（剥 BOM · 懒读 · 无缓存 · ⛔ 不抛错）。

export const PHASE_RETRIEVAL_TIMEOUT_MS = 1500

/** `work_topic` 长度上限（沿用原来的 400）与**分层分隔符**。 */

export const PHASE_TOPIC_MAX = 400

export const PHASE_TOPIC_SEP = ' ｜ '

/** 阶段注入的会话级状态（**内存** · 与 `SESSIONS` 同一生命周期 —— `dropSession()` 同步释放）。 */

export function phaseTopicOf(card: TaskCursor | null): string {
  if (card === null) return ''
  const next = card.next.replace(/\s+/g, ' ').trim()
  const goal = card.goal.replace(/\s+/g, ' ').trim()
  if (next === '' && goal === '') return ''
  if (next === '') return goal.slice(0, PHASE_TOPIC_MAX)
  if (goal === '') return next.slice(0, PHASE_TOPIC_MAX)
  const head = next.slice(0, PHASE_TOPIC_MAX)
  const room = PHASE_TOPIC_MAX - head.length - PHASE_TOPIC_SEP.length
  if (room <= 0) return head // next 已占满 ⇒ goal 让位（⛔ 不截 next 去塞 goal）
  return head + PHASE_TOPIC_SEP + goal.slice(0, room)
}

/**
 * 🔴 （A/B 读数驱动）：阶段 ⇒ **兜底 `help`**（只在会话**没有任何**
 *   `auto_capability` 上报时使用）。
 *   为什么（读数，不是猜）：python 侧 `axis` 通道是**权重最高的确定性匹配**，但它**只在请求带 `axes`
 *   时产生证据**（`_retrieval_request_probe.py:axis_hits`）—— 同一 work_topic 下，不带 axes 只有 3 条
 *   候选、`senior-engineer` 轴证据 0；带 axes 出 5 条、senior 得 2 条（`domain=AI-OS 自身` + `help=评审`）。
 *   而 `axis_hits` 有**help 闸门**（请求必须带 help 轴、且与描述符 `axis_help` 有交集，轴通道才成立）
 *   ⇒ 只有 help 轴能单独构成证据；`domain` / `concern` 拿不到就**留空**，⛔ 不编。
 *   值全部取自 `task_cards/NEEDS-VOCAB.md`（与 `WR_*_VALUES` 手工同步）。
 */

export const PHASE_DEFAULT_HELP: Record<AiPhase, readonly string[]> = {
  S1: ['评审', '设计'],
  S2: ['实现', '验证'],
  S3: ['调试'],
  S4: ['验证', '审计·清理'],
}

/** 只收**恰好等于词表值**的项（去重 · 保序）——⛔ 不猜同义词 / ⛔ 不自造值。 */

export function vocabPicked(list: readonly string[], allow: readonly string[]): string[] {
  const out: string[] = []
  for (const x of list) {
    const s = String(x).trim()
    if (s !== '' && allow.includes(s) && !out.includes(s)) out.push(s)
  }
  return out
}

/**
 * **纯函数**：阶段请求的 `axes`（词表三维）—— 两级来源：
 *   ① `latestWorkReport(session)`：本会话最近一条 `auto_capability` —— 显式 `axes`（两步式）
 *      **按轴优先**，否则从 `need` / `concern` 抽**恰好是词表值**的项；
 *   ② 该会话**没有任何上报** ⇒ 按阶段兜底 `help`（`PHASE_DEFAULT_HELP`），domain/concern 留空。
 * 结果为空 ⇒ `null`（调用方**不加 `axes` 字段** ⇒ 请求形状与旧版**逐字段一致**，向后兼容）。
 * ⚠️ 对"有上报但全是非法值"**不**回落到阶段默认 —— 默认是"没表达过需求"时的兜底；已有上报（哪怕全是
 *    自由文本）说明 Agent 表达过，不拿默认去**覆盖**它（与 「显式 > 推断 > 默认」同纪律）。
 */

export function phaseAxesOf(phase: AiPhase, session: string): Record<string, string[]> | null {
  const rep = session === '' ? null : latestWorkReport(session)
  if (rep !== null) {
    // 每轴：显式 axes优先；该轴没选 ⇒ 从 need/concern 抽词表值；仍空 ⇒ 该轴不出现。
    const pick = (explicit: readonly string[], derived: readonly string[], allow: readonly string[]): string[] => {
      const ex = vocabPicked(explicit, allow)
      return ex.length > 0 ? ex : vocabPicked(derived, allow)
    }
    const domain = pick(rep.axes.domain, rep.need, WR_DOMAIN_VALUES)
    const help = pick(rep.axes.help, rep.need, WR_HELP_TYPES)
    const concern = pick(rep.axes.concern, rep.need.concat(rep.concern), WR_CONCERN_VALUES)
    const out: Record<string, string[]> = {}
    if (domain.length > 0) out.domain = domain
    if (help.length > 0) out.help = help
    if (concern.length > 0) out.concern = concern
    return Object.keys(out).length > 0 ? out : null
  }
  const help = PHASE_DEFAULT_HELP[phase]
  if (help === undefined || help.length === 0) return null
  return { help: help.slice() }
}

/**
 * **纯函数**：阶段 ⇒ `retrieval-request/v1`（供单测；⛔ 无 I/O）。
 * **卡是唯一排序输入** —— 请求的 `work_topic` 只由卡的
 *   `Goal`（要达成什么）+ `Next Action`（现在对什么做什么）拼成；**无卡 / 拼不出 topic ⇒ 返回 `null`**
 *   （调用方**不 spawn、不记账**，只落 `state:"no-anchor"`）。
 *   ⛔ **删掉旧版的 `wc.intentText` 兜底**：读数（重启后第一个 S2 样本，本会话还没占卡）
 *      用"正在讨论的元话语"当 topic ⇒ 注入 3/3 全无关候选（误报），一条都没被打开。
 * 🔴 （同上定稿）：`work_topic` 由平铺改成**分层 `<Next Action> ｜ <Goal>`**（见 `phaseTopicOf`）；
 *   仍是**单个字符串**（⛔ 不改 schema / 不新增字段）。
 * 其余输入仍取设计稿 §4.3「都已在卡里，不需新字段」；`phase` 是**新增可选字段**
 *   （Python 侧只用来过滤 `capabilities/*.md` 的 `phases:`；缺字段 = 无限制）。
 * 🔴 （同上）：额外带**词表三维 `axes`**（`phaseAxesOf`）—— 它只影响检索侧的 `axis` 通道证据，
 *   ⛔ 不动 `work` / `need` / 条数 / 渲染；无可用轴值 ⇒ **不加该字段**（旧请求逐字不变）。
 *   ⚠️ `session` 可选：缺省 = "本会话无上报" ⇒ 走阶段默认 help（旧 4 参调用/旧用例仍成立；接线处必传）。
 */

export function buildPhaseRetrievalRequest(phase: AiPhase, card: TaskCursor | null, wc: WorkContext, now: number,
                                   session?: string): Record<string, unknown> | null {
  if (card === null) return null
  const topic = phaseTopicOf(card)
  // 拼不出 topic（卡上没有 Goal / Next Action）⇒ **不发请求**（⛔ 不拿别的东西兜底凑一个"看起来像工作"的 topic）
  if (topic === '') return null
  return phaseRequestOf(phase, topic, wc, now, session === undefined ? '' : session, 'phase')
}

/**
 * **纯函数**：`retrieval-request/v1` 组装 —— 常规阶段（`buildPhaseRetrievalRequest`）与**首拍**
 *   （`buildFirstStepRetrievalRequest`）**共用同一形状**：只有 `work_topic` 的来源与 `request_id`
 *   前缀不同（⛔ 不复制第二份请求体，否则两处迟早漂移）。
 *   ⛔ 字段语义与 // 逐字一致（`budget` 用池子常量 5；`axes` 有值才加）。
 */

export function phaseRequestOf(phase: AiPhase, topic: string, wc: WorkContext, now: number, session: string,
                        idPrefix: string): Record<string, unknown> {
  const work: Record<string, unknown> = {
    target_refs: { state: 'unknown' },
    work_topic: { state: 'provided', value: topic },
    history_coverage: { state: 'provided', value: wc.historyCoverage === 'partial' ? 'incomplete' : 'complete' },
  }
  const req: Record<string, unknown> = {
    schema: 'retrieval-request/v1',
    request_id: idPrefix + '-' + phase + '-' + String(now),
    phase,
    need: { state: 'unknown', origin: 'runtime' },
    work,
    sources: { mode: 'all-discoverable', ids: [] },
    // `budget` 用**池子常量**（保持 5），与注入 slice（`phaseMaxCandidates()`，缺省 1）**解耦**
    budget: { max_candidates: PHASE_BUDGET_CANDIDATES, max_per_source: PHASE_BUDGET_CANDIDATES },
  }
  // 有可用轴值才加字段（⛔ 不加 `axes:{}` / `axes:null` —— 那是"看似带了、实则零证据"）
  const axes = phaseAxesOf(phase, session)
  if (axes !== null) req.axes = axes
  return req
}

/**
 * **纯函数（实验 B）**：**会话首拍**的检索请求 —— `phase:"S1"` + `work_topic = 用户首条消息`。
 * 🔴 为什么 topic 不是卡：首拍**必然还没 claim**（读数 r4：claim 在第 35 个工具调用之后）⇒ 卡的
 *    `Goal` / `Next Action` 此刻不存在。这是 「无卡 ⇒ 静默」的**唯一例外**，例外**只**存在于本函数
 *    的唯一调用点（`firstStepInjectOnce`），S1/S2/S3/S4 的既有路径与 `no-anchor` 静默**逐字不变**。
 * ⛔ 截断沿用 400（`PHASE_TOPIC_MAX`）；空白归一；空 topic ⇒ `null`（⛔ 不拿空串去检索）。
 * ⛔ 不用卡的描述、也不在此时读 `wc.intentText`（它每回合都会被改写 —— 调用方传的是**锁存值**）。
 */

export const PHASE_SCORE_W = { channelKind: 0.30, matchedCoverage: 0.30, evidenceLevel: 0.20, axisCoverage: 0.10, channelDiversity: 0.10 }

/** 通道**种类**权重确定性标识 > 主题词面 > 角色/自供键 > 上下文弱证据。
 *  ⚠️ 与 python `CHANNEL_WEIGHT` **同序但不同值**（这里只是 0–1 归一用；⛔ 不回写检索器）。 */

export const PHASE_CHANNEL_W: Record<string, number> = {
  axis: 1.0, identifier: 0.9, topic: 0.8, role: 0.6, keys: 0.5, intent: 0.5, context: 0.2,
}

/** `matchedCoverage` 的满分覆盖比例（命中 topic 的 25% 词即视为满分）。 */

export const PHASE_COVERAGE_FULL = 0.25

/** 候选是否带**可用于打分**的信号（`hit_channels` / `evidence` 任一非空）。纯函数 · 供单测。 */

export function hasCapScoreSignals(c: any): boolean {
  if (c === null || c === undefined || typeof c !== 'object') return false
  const ch = Array.isArray(c.hit_channels) ? c.hit_channels.length : 0
  const ev = Array.isArray(c.evidence) ? c.evidence.length : 0
  return ch > 0 || ev > 0
}

/**
 * **纯函数**：单个能力候选 ⇒ `0–1` 分数（公式见上方注释原文 · ⛔ 不读正文 / ⛔ 不调远程）。
 * 输入是 `candidate-set/v1` 的**原始候选 item**（不是工具返回的归一结构）。
 * @param c 原始候选 item（`hit_channels` / `evidence`）
 * @param topicText 卡的 `work_topic`（**可选**）：给了才算 `matchedCoverage`；⛔ 缺省不影响其它项
 */

export function phaseCapScoreOf(c: any, topicText: string = ''): number {
  if (c === null || c === undefined || typeof c !== 'object') return 0
  const channels = Array.isArray(c.hit_channels) ? c.hit_channels.map((x: any) => String(x)) : []
  const evidence = Array.isArray(c.evidence) ? c.evidence : []
  if (channels.length === 0 && evidence.length === 0) return 0
  let kindSum = 0
  for (const ch of channels) kindSum += PHASE_CHANNEL_W[ch] !== undefined ? PHASE_CHANNEL_W[ch] : 0.3
  const channelKind = Math.min(1, kindSum / 2)
  const channelDiversity = Math.min(1, channels.length / 3)
  let strong = 0
  let medium = 0
  let weak = 0
  const terms = new Set<string>()
  const axisTerms = new Set<string>()
  for (const e of evidence) {
    if (e === null || e === undefined || typeof e !== 'object') continue
    const st = String(e.strength !== undefined ? e.strength : '')
    if (st === 'strong') strong += 1
    else if (st === 'medium') medium += 1
    else if (st === 'weak') weak += 1
    const m = Array.isArray(e.matched) ? e.matched : []
    for (const t of m) {
      terms.add(String(t))
      if (String(e.channel !== undefined ? e.channel : '') === 'axis') axisTerms.add(String(t))
    }
  }
  const evidenceLevel = Math.min(1, (2 * strong + 1 * medium + 0.5 * weak) / 4)
  const axisCoverage = Math.min(1, axisTerms.size / 3)
  // **具体匹配** —— 命中词覆盖了 topic 的多少（topic 词用同一套 tokenizer，⛔ 不引语料特征）。
  let matchedCoverage = 0
  if (topicText !== '') {
    const topicTokens = tokensOf([topicText])
    if (topicTokens.size > 0) {
      let inter = 0
      for (const t of terms) if (topicTokens.has(t)) inter += 1
      matchedCoverage = Math.min(1, (inter / topicTokens.size) / PHASE_COVERAGE_FULL)
    }
  }
  const raw = PHASE_SCORE_W.channelKind * channelKind
    + PHASE_SCORE_W.matchedCoverage * matchedCoverage
    + PHASE_SCORE_W.evidenceLevel * evidenceLevel
    + PHASE_SCORE_W.axisCoverage * axisCoverage
    + PHASE_SCORE_W.channelDiversity * channelDiversity
  return Math.round(raw * 1000) / 1000 // 3 位小数：探针可读 + 稳定可复算
}

/**
 * **纯函数**：候选集 ⇒ 阶段注入文本（**1 条 · top1** · 按 `phaseCapScoreOf` 分数降序 · 同分保持 python 顺序 ·
 * 照 三行格式 · ⛔ 不注整包正文 · ⛔ 不把分数写进文本）。
 *   · 只取 `capabilities/` 下的**能力包**（账本 / 语料 chunk 不是"能力描述"，不注）；
 *   · 已被返回过（`already`，含 `auto_capability` 与前一阶段注过的）⇒ 跳过；
 *   · 无可用候选 ⇒ `text:''`（调用方记 `no-candidate`）。
 * @param topicText 卡的 `work_topic`（**可选**）：只用于打分里的 `matchedCoverage`，⛔ 不写进文本
 * @returns `ids`/`scores` **等长**（探针原始数据）；`scoreMode:'none'` = 无分数信号、按 python 顺序。
 */

export function renderPhaseCandidates(set: any, phase: AiPhase, already: ReadonlySet<string>, topicText: string = ''):
  { text: string; ids: string[]; scores: number[]; pool: number; matched: number; scoreMode: 'capability-signals' | 'none' } {
  // 原始候选按 id 建索引（分数原料只在原始 item 上；⛔ 不从工具返回白名单拿分）
  const rawById = new Map<string, any>()
  const rawList = set !== null && set !== undefined && Array.isArray(set.candidates) ? set.candidates : []
  for (const r of rawList) {
    if (r !== null && r !== undefined && typeof r === 'object') rawById.set(String(r.id !== undefined ? r.id : ''), r)
  }
  const cands = retrievalCandidatesOf(set).filter(c => isCapabilityCandidatePath(c.path))
  const budget = set !== null && set !== undefined && set.budget_applied !== null && set.budget_applied !== undefined
    ? set.budget_applied as Record<string, any> : {}
  const matched = typeof budget.matched_before_budget === 'number' ? budget.matched_before_budget : cands.length
  const freshBase = cands.filter(c => !already.has(c.id))
  // 打分 + **稳定**降序（同分保持 python 返回顺序 —— ⛔ 不让打分把等价候选颠来颠去）
  // 把卡的 topic 一并喂给打分（**具体匹配**才算分；⛔ topic 不进渲染文本）
  let scoreMode: 'capability-signals' | 'none' = 'capability-signals'
  if (!freshBase.some(c => hasCapScoreSignals(rawById.get(c.id)))) scoreMode = 'none'
  const scored = freshBase.map((c, i) => ({ c, i, s: scoreMode === 'none' ? 0 : phaseCapScoreOf(rawById.get(c.id), topicText) }))
  if (scoreMode !== 'none') scored.sort((a, b) => (b.s - a.s) || (a.i - b.i))
  const fresh = scored.slice(0, phaseMaxCandidates())
  if (fresh.length === 0) return { text: '', ids: [], scores: [], pool: cands.length, matched, scoreMode }
  const lines = ['【AI-OS · ' + PHASE_TITLE[phase] + '阶段 · 能力候选】']
  for (const x of fresh) {
    const c = x.c
    const base = c.path.split('/').pop() || c.path
    const name = base.replace(/\.md$/i, '')
    lines.push('  · ' + name + (c.summary !== '' ? ' — ' + c.summary : ''))
    lines.push('    → ' + c.path)
  }
  return { text: lines.join('\n'), ids: fresh.map(x => x.c.id), scores: fresh.map(x => x.s), pool: cands.length, matched, scoreMode }
}

// ── **格能力（阶段 × 领域）代码已删除** ──────────────────────
//   删除原因（已核实 · ⛔ 不复论证）：该路径依赖 `capabilities/CELLS.md` 的「阶段 × 领域」装配表，
//     该表已归档到 `capabilities/_archive/` ⇒ `loadCells()` 恒返回 `[]` ⇒ 路径**永远不命中**
//     （探针 `basis:"cell"` 0 条 · `.aios/cap-cells.json` 的 `enabled:false` · 对应单测曾显式 SKIP）。
//   已删：`capCellsEnabled()` / `parseCellsTable()` / `cellRowsOf()` / `cellPartMetaOf()` /
//     `collectCellParts()` / `cellOf()` / `cellCriterionPidOf()` / `CellRenderOut` / `renderCellIntro()` /
//     `renderCellCandidates()` / `cellInjectOf()`、`CELL_CLASS_OF_PHASE` / `CELL_SKIP_FILES` /
//     `CELL_EMPTY_TOKENS` / `splitCellIds` / `CellRow` / `CellPartMeta`，以及接线处 `basis:"cell"` 整块。
//   **保留**：`capCellsConfig()` + `phaseMaxCandidates()` —— `.aios/cap-cells.json` 的 `max`
//     仍是**检索路径**的候选条数上限（与格能力无关，删它 = 连坐改检索行为）；
//   **保留**：下方 `CELL_DOMAIN_WORDS` / `CELL_DOMAIN_DIRS` / `CELL_DOMAIN_EXTS` + `cellWordAt()` /
//     `cellDomainOfPathClass()` / `inferCellDomain()` —— 只服务 `inferDomainOf()`（纯函数，
//     单测 S187/S189/S190 仍断言其判域结果）；格注入已删除 ⇒ 它们不再被任何注入路径调用。

/**
 * 🔴 **：首拍注入默认关闭。**
 * 依据（已核实 · ⛔ 勿重新论证）：实验 B真机触发后，首拍注入的 topic = **用户首条消息**
 *   （读数 `topic_chars:141`，含大量【AI-OS · …】引导文本）⇒ top1 = `simplification_audit`（0.588），
 *   **与当时工作无关**；同会话 claim 后的常规 S1（topic = 卡的 `Goal ｜ Next Action`）⇒ top1 = `senior-engineer`，
 *   **相关**。⇒ 首拍 topic 质量低于 claim 后的 topic，每会话开场多一条不相关候选 = 噪音。
 * 做法：**常量门控接线点**（`FIRST_STEP_INJECT_ENABLED`）—— 关时 `firstStepInjectOnce` **不被调用**
 *   ⇒ **零注入 + 零探针**（⛔ 不落 `state:"skipped"` / 任何占位读数：那会污染日志）。
 * ⛔ **实现全部保留**（`buildFirstStepRetrievalRequest` / `firstStepInjectOnce` / `firstUserText` /
 *   `postExecuteCount` / `PhaseInjectSlot.firstStep*`）：复活 = 把本常量改 `true`，无需改其它代码；
 *   请求构造纯函数仍由 S165 直接单测（⛔ 不删用例）。
 * 边界：关闭态下 `firstStepInjectOnce` 函数体在运行时**不可达**（仅保留 + 单测可调）—— 本仓库无 tsc/lint
 *   静态检查，故不产生"未使用"告警；`FIRST_STEP_INJECT_ENABLED` 在 `? :` 里显式引用它，保持可发现性。
 */

export const INJECT_MAX_WITHOUT_RETRIEVAL = 2

/** T5 判据（纯函数）。 */

export function injectAllowedByBudget(injectsSinceRetrieval: number): boolean {
  return injectsSinceRetrieval < INJECT_MAX_WITHOUT_RETRIEVAL
}

// ── 🔴 **经验召回**（事件触发 · 与「能力检索」分开）──────────────
//   依据：检索本是为经验设计的（`experience_push.py` 自我描述 = "Surface relevant past
//   experience near the Agent"）；能力走 skill 目录 + 按需加载，经验走「召回一句 + 直接注入」。
//   ⛔ 不改检索算法 / 不调候选条数 / ⛔ 不注入候选列表 —— 只注入 top1–2 **一句经验**。

export const EXPERIENCE_RECALL_MIN_SCORE = 6.0

export function renderExperienceRecall(parsed: any): string {
  const hits = parsed !== null && parsed !== undefined && Array.isArray(parsed.hits) ? parsed.hits : []
  const lines: string[] = []
  for (const h of hits.slice(0, 2)) {
    const title = String(h && h.title !== undefined ? h.title : '').trim()
    const content = String(h && h.content !== undefined ? h.content : '').replace(/\s+/g, ' ').trim()
    const file = String(h && h.file !== undefined ? h.file : '').trim()
    if (title === '' && content === '') continue
    lines.push('· ' + title + ' —— ' + clip(content, 120) + (file !== '' ? '（' + file + '）' : ''))
  }
  if (lines.length === 0) return ''
  return '【AI-OS · 经验召回】同类问题的现成处置（照着做可能省一次试错）：\n' + lines.join('\n')
}

/**
 * 检测本拍**上升沿事件**（纯函数 · 供单测）。⛔ 不判阶段、不做语义。
 * 输入 = 可核实信号；输出 = 本拍**新出现**的事件（上一拍没有、这一拍才有）。
 * 🔴 三处改动：
 *   · T1 砍掉 `first-edit` / `anchor-claimed`（读数：无上下文触发 17/36 调用、候选消费 **0**）；
 *   · T2 `gap` 只在**非事实型**失败触发（路径 typo / 重读 / 参数错 ⇒ 检索帮不上）；
 *   · T7′ 新增 `repeat-question`（与上一条用户消息词面高度重合且期间未推进）。
 */
