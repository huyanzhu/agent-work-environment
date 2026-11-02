/** probe-state.ts —— 由 `runtime/aios-activation.ts` 拆出（纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { PHASE_RETRIEVAL_TIMEOUT_MS, phaseMaxCandidates, phaseRequestOf, renderPhaseCandidates, PHASE_TOPIC_MAX } from './../activation/phase-candidates.ts'
import type { PhaseInjectSlot } from './../activation/phase-policy.ts'
import { PHASE_INJECT } from './../activation/phase-policy.ts'
import { OBS, POLICY, clip, emit, mono } from './../diagnostics/probe.ts'
import { spawnJsonAsync } from './../retrieval/python-bridge.ts'
import { RETURNED_CAPABILITY_IDS, STAGE4_RETRIEVAL_ENTRY } from './../retrieval/request-builder.ts'
import { focusCardOf, myOccupiedCards } from './../session/lifecycle.ts'
import type { PendingDelivery, SessionState } from './../session/session-state.ts'
import type { ActivityItem, WorkContext } from './../session/work-context.ts'
import { failStreakOf } from './../session/work-context.ts'

export const DELIVERY_SENT = new Map<string, number>()

export type InjectEvent = 'anchor-claimed' | 'first-edit' | 'stuck' | 'user-named' | 'gap' | 'repeat-question'

/** 会话级事件状态（**内存** · `dropSession` 同步释放 —— ⛔ 只增不减会无界增长）。 */

export interface EventSlot {
  /** 已发事件 —— **去重的真相**：每个事件每会话最多一次（Set，⛔ 不是「上一拍 key」）。 */
  sent: Set<InjectEvent>
  /** 已发条数（每会话上限用）。 */
  count: number
  /** 上一拍的 `has-edit`（**升沿**检测 · 与 `detectEvents` 配对推进）。 */
  lastHasEdit: boolean
  /** 上一拍的连续失败数（**升沿**检测）。 */
  lastFailStreak: number
  /** `user-named` 上次触发的轮次（同轮去重）。 */
  lastNamedTurn: number | null
}

export const INJECT_EVENTS = new Map<string, EventSlot>()

export function emptyEventSlot(): EventSlot {
  return { sent: new Set(), count: 0, lastHasEdit: false, lastFailStreak: 0, lastNamedTurn: null }
}

// ── 🔴 约定「需重启生效」· ⛔ 不重启 ──────────────────
//   设计稿：`task_cards/active/AI-OS-Adaptation/PHASE-INJECTION-DESIGN-.md §4.1–§4.4`
//   一句话：**阶段决定"哪一类能力"，卡描述决定"具体哪个能力"，注入"能力描述 + 指针"（不是整包）**。
//   **无工作卡 ⇒ 静默不注** —— 卡 `Goal` + `Next Action` 是**唯一排序输入**；
//      ⛔ 不再用 `intentText` 兜底（读数误报：无卡时拿"正在讨论的元话语"当 topic ⇒ 注入 3/3 全无关）；
//      无卡只落 `state:"no-anchor"` 且**不记账**（等占了卡该阶段仍能正常注入）。
//   🔴 （同上 · 排序分层）：`work_topic` 由「goal next 平铺」改为 **`<Next Action> ｜ <Goal>`**
//      （顺序即权重；next 超长时 **goal 让位**，⛔ 不让 goal 挤掉 next）。
//   🔴 （同上 · 定稿）：注入条数 **≤3 → 前 5**（请求 `budget` 同步到 5）+ 候选**打分排序**
//      （分数只进探针 · 不写进注入文本）。
//   🔴 （A/B 读数）：阶段请求**带词表三维 `axes`** —— 优先取本会话最近一条
//      `auto_capability`（只收词表值），会话没有上报 ⇒ 按阶段兜底 `help`；两级都空 ⇒ **不带该字段**。
//      依据：`axis` 是 python 侧权重最高的确定性匹配，但只在请求带 axes 时产生证据。
//   🔴 （单变量实验）：注入条数 **5 → 1**（只注打分最高的那条），请求 `budget`
//      **保持 5**（池子够大才轮得到打分选 top1 —— 否则「top1」只是「池子只有 1 条」）。
//      ⛔ 不动注入时机 / 文案 / 打分公式（只改条数这一个变量）。
//   🔴 （实验 B「注入窗口前移」· **单变量 = 时机**）：**会话首拍**也注一次能力。
//      背景（读数，已核实）：现状注入挂在 claim 成功后（S1）/ 首次实质改动后（S2）/ release 后（S4），
//        而 r4 真实任务里 **claim 发生在第 35 个工具调用之后** ⇒ S1 到达时工作已过半。
//      做法：`tools/post-execute` 的注入段里，**本会话第一个** post-execute（`firstStepDone` 未置位，
//        且 `postExecuteCount === 1` = 第一个工具调用刚收尾、此前没有完成过任何工具调用）时，
//        用 `phase:"S1"` + **topic = 用户首条消息**（`firstUserText` · 锁存，⛔ 不是"最近一条意图"）注 **1 条**。
//      ⛔ 为什么必须挂在 post-execute（如实边界）：DSH 的扩展点里**只有** `tools/post-execute` 能追加
//        `additionalContexts`（`agent/pre-step` / `tools/pre-execute` 只能 deny/allow）⇒ 物理上最早的可注时机
//        就是「第一个工具调用收尾、第二个还没发出」这一拍。**它晚于同一次调用的 `tool-sig`**（`pre-execute`
//        先发），早于后续任何工具调用。
//      🔴 **「无卡 ⇒ 静默」的唯一例外**：会话首拍必然还没 claim（这正是要修的病），若沿用
//        该注入永远不可能发生 ⇒ 例外**只**给这一条路径，且**额外要求此刻 `myOccupiedCards === 0`**
//        （有卡时常规 S1 当拍就会注，无需例外；同时避免同拍双注）。
//        ⛔ 例外不放宽：S1/S2/S3/S4 的既有判定、`no-anchor` 静默、`sent` 去重**逐字不变**（S166 拦回归）。
//      ⛔ 独立去重标记 `firstStepDone`（⛔ 不复用 `sent` Set，否则首拍会把 S1 记账掉、常规 S1 永不再注）；
//         ⛔ 不把首拍注过的能力记进 `RETURNED_CAPABILITY_IDS`（那是 S1/S2/S4 与 `auto_capability` 的既有去重口径，
//         复用会改变常规 S1 选哪条 —— 本实验只改时机这一个变量）。
//      ⛔ 不动打分公式 / 条数 / 渲染文本 / axes 口径（请求形状与 S1 逐字段一致，只有 `request_id` 前缀不同）。
//      探针：`ev=phase-inject{phase:"S1", basis:"first-step", state:"injected"|"dup"|"no-candidate"|"spawn-failed"}`。
//      🔴 **：默认关闭** —— 真机读数：首拍 topic（= 用户首条消息，含引导文本）
//      的 top1 与当时工作无关，而 claim 后常规 S1 的 topic（卡的 `Goal ｜ Next Action`）top1 相关
//      ⇒ 首拍注入 = 每会话开场多一条不相关候选（噪音）。⇒ 常量 `FIRST_STEP_INJECT_ENABLED=false`
//      门控接线点：关时**不调用** `firstStepInjectOnce`、**零注入零探针**；实现全部保留（改常量即复活）。
//   🔴 为什么 说"⛔ 不推断阶段"， 又加阶段？（口径区别，别重复踩）
//       的教训是**用阶段做节流**（rolling-window 阶段在 edit/read 交替下每步来回跳 ⇒ 单会话刷 18 次）；
//      本段**不用阶段做节流** —— 节流一律由「**升沿 + 已发 Set**」承担（`PHASE_INJECT.sent`），
//      阶段只用来**选能力类别**（`phase` 作为检索请求的可选过滤字段）。
//   ⛔ 边界（逐条落地）：
//      · 不改既有注入源（事件提示 / 经验召回 / R3 / 候选递送）任何行为；
//      · ⛔ 不复活 砍掉的 `first-edit` 事件（未授权）—— 这里只做**判定**，不新增事件；
//      · ⛔ 不改检索器权重 / 阈值 / 语料；`phase` 只是请求里的一个**新增可选字段**；
//      · 失败静默（⛔ 不影响工具结果），但**必落探针**（⛔ 不允许"零报错零探针"）。
//      · ⛔ 不叠设计稿 §4.2 的类别门（裁定：以能力自报的 `phases` 为准）。

/** 阶段判定输入（**全部来自现有内存态** · 纯函数 · ⛔ 无 I/O）。 */

export const FIRST_STEP_INJECT_ENABLED: boolean = false

// ── 🔴 （实验 B · **单变量 = 注入时机**）：**会话首拍**注入一次能力 ────────────
//   精确判据（三条同时成立，且本拍还没发过事件提示）：
//     ① `slot.firstStepDone === false` —— 本会话**第一次**进入本段（独立标记 · ⛔ 不复用阶段 `sent` Set）；
//     ② `ist.postExecuteCount === 1` —— 这是本会话**第一个** `tools/post-execute`（= 第一个工具调用刚收尾
//        ⇒ 此前**没有完成过任何工具调用**）。⚠️ 不用 `wc.activity.length`：同 step 的**并行**工具调用会一次
//        塞多条活动 ⇒ 首拍被误判成"已开工"；
//     ③ `myOccupiedCards(ist).length === 0` —— 还没 claim（例外的前提；有卡时常规 S1 当拍就会注，
//        不需要例外，也不允许同拍双注）。
//   ⛔ 置位后**永不回退**：晚到的"首拍"已经是第二拍（工作已经开始），⛔ 不补拍。
//   ⛔ 不改打分公式 / 条数 / 渲染文本 / axes 口径：请求与 S1 同形（`phaseRequestOf`），渲染走同一个
//      `renderPhaseCandidates`，条数走同一生效上限 `phaseMaxCandidates()`（缺省 1 · 与改前逐字一致）。
//   @returns 要注入的文本（`''` = 本拍不注；四态读数已落探针）

export async function firstStepInjectOnce(session: string, ist: SessionState, slot: PhaseInjectSlot): Promise<string> {
  // ① 已判过 ⇒ 只报一条 `dup`（每会话一次），⛔ 不再注
  if (slot.firstStepDone) {
    if (!slot.firstStepDupReported && ist.postExecuteCount > 1) {
      slot.firstStepDupReported = true
      emit({
        ev: 'phase-inject', obs: OBS, session, phase: 'S1', basis: 'first-step', state: 'dup',
        n: 0, chars: 0,
        note: 'first-step injected at most once per session (independent latch · ⛔ 不复用阶段 sent Set)',
        at: Date.now(), mono: mono(),
      })
    }
    return ''
  }
  // ② 只在**第一拍**成立（本会话已有更早的 post-execute ⇒ 已经开工，⛔ 不冒充首拍）
  if (ist.postExecuteCount !== 1) return ''
  // ③ 例外的前提：**没有已占用的卡**（有卡 ⇒ 走常规 S1，⛔ 不在这里注）
  if (myOccupiedCards(ist).length !== 0) return ''
  // 判过即占位（无论成败）：⛔ 不补拍 —— 失败/无候选的代价由探针四态如实可见
  slot.firstStepDone = true
  const req = buildFirstStepRetrievalRequest(ist.firstUserText, ist.wc, Date.now(), session)
  if (req === null) {
    emit({
      ev: 'phase-inject', obs: OBS, session, phase: 'S1', basis: 'first-step', state: 'no-candidate',
      why: 'no-topic', n: 0, chars: 0,
      note: '首条用户消息为空 ⇒ 不构造请求（⛔ 不拿空 topic 去检索）',
      at: Date.now(), mono: mono(),
    })
    return ''
  }
  const topicText = String((req.work as Record<string, any>).work_topic.value)
  const got = await spawnJsonAsync(STAGE4_RETRIEVAL_ENTRY, { request: req }, PHASE_RETRIEVAL_TIMEOUT_MS)
  if (got.outcome !== 'ok' || got.value === null || got.value === undefined) {
    emit({
      ev: 'phase-inject', obs: OBS, session, phase: 'S1', basis: 'first-step', state: 'spawn-failed',
      outcome: got.outcome, n: 0, chars: 0, topic_chars: topicText.length,
      detail: clip(got.detail !== undefined ? got.detail : '', 100),
      at: Date.now(), mono: mono(),
    })
    return ''
  }
  if (got.value.ok === false) {
    const errs = Array.isArray(got.value.request_errors) ? got.value.request_errors : []
    emit({
      ev: 'phase-inject', obs: OBS, session, phase: 'S1', basis: 'first-step', state: 'no-candidate',
      why: 'request-invalid', errors: errs.slice(0, 3), n: 0, chars: 0, topic_chars: topicText.length,
      at: Date.now(), mono: mono(),
    })
    return ''
  }
  const rendered = renderPhaseCandidates(got.value, 'S1', capabilityIdsOf(session), topicText)
  if (rendered.text === '') {
    emit({
      ev: 'phase-inject', obs: OBS, session, phase: 'S1', basis: 'first-step', state: 'no-candidate',
      n: 0, chars: 0, pool: rendered.pool, matched: rendered.matched, score_mode: rendered.scoreMode,
      topic_chars: topicText.length,
      at: Date.now(), mono: mono(),
    })
    return ''
  }
  emit({
    ev: 'phase-inject', obs: OBS, session, phase: 'S1', basis: 'first-step', state: 'injected',
    n: rendered.ids.length, chars: rendered.text.length,
    pool: rendered.pool, matched: rendered.matched,
    // `rendered.*` 已按生效上限切片 ⇒ 直接照录；`cap_max` 记录本次生效的 max（A/B 事后核对用）
    candidates: rendered.ids,
    scores: rendered.scores,
    cap_max: phaseMaxCandidates(),
    score_mode: rendered.scoreMode, topic_chars: topicText.length,
    note: 'first-step (before any work) → capability DESCRIPTION + pointer (top·cap_max · ⛔ 不注整包正文)',
    at: Date.now(), mono: mono(),
  })
  return rendered.text
}

/** 活动序列尾部的连续失败数（与 同口径 · **只读**）。 */

export interface NodeInjectSlot {
  sent: Set<NodeId>
  dupReported: Set<NodeId>
}

export function nodeTargetPathOf(args: unknown): string {
  if (args === null || args === undefined || typeof args !== 'object') return ''
  const a = args as Record<string, unknown>
  for (const k of ['file_path', 'path', 'new_path']) {
    if (typeof a[k] === 'string' && a[k] !== '') return String(a[k])
  }
  return ''
}

/** N1 判据函数（纯函数 · 供单测）：编辑目标是语料 ⇒ `true`。⛔ `read` 等读取类工具在调用方就被挡住。 */

export const DELIVERY_ERR_SEEN = new Set<string>()

export function detectEvents(
  s: {
    hasEdit: boolean
    activity: readonly ActivityItem[]
    cardEdits: number
    intentText: string
    turn: number | null
    /**  T2：最近一次失败类型（`factual` 不触发 gap）。缺省 = 未知（按知识型处理）。 */
    lastFailKind?: 'factual' | 'knowledge' | null
    /**  T7′：本次用户消息是否与上一条高度重合（由 `UserPromptSubmit` 预判）。 */
    repeatQuestion?: boolean
  },
  prev: {
    sent: ReadonlySet<InjectEvent>
    lastHasEdit: boolean
    lastFailStreak: number
    lastNamedTurn: number | null
  },
): InjectEvent[] {
  const out: InjectEvent[] = []
  const streak = failStreakOf(s.activity)
  // 🔴 T1**砍掉** first-edit / anchor-claimed。
  //   证据：84 会话归因 —— 无缺口上下文的触发占 17/36 次调用，候选消费 **0**（卡第 32/33 批）。
  // 缺口触发 —— 尾部**单次**失败即提示（不等连败 2 次）； 起加 T2 分类闸。
  if (!prev.sent.has('gap') && streak >= 1 && s.lastFailKind !== 'factual') out.push('gap')
  if (!prev.sent.has('stuck') && streak >= 2 && prev.lastFailStreak < 2) out.push('stuck')
  // 🔴 T7′：同一问题第 2 次（纯词面 · 无语义）—— 替代「用户否定语」关键词触发（会误命中）。
  if (!prev.sent.has('repeat-question') && s.repeatQuestion === true) out.push('repeat-question')
  if (detectRetrievalRequest(s.intentText).hit && s.turn !== prev.lastNamedTurn) out.push('user-named')
  return out
}

/**
 * 是否发布（纯函数 · 供单测）：**每事件一次** + 每会话上限。
 * ⚠️ 与 `shouldPublishHint` 的根因差异：这里判「事件是否已发过」（Set），
 *    ⛔ 不是「上一拍是什么 key」⇒ **不存在「key 交替 ⇒ 重发」的抖动通道**。
 */

export function shouldPublishEvent(slot: EventSlot, ev: InjectEvent, maxPerSession: number): boolean {
  if (slot.sent.has(ev)) return false
  if (slot.count >= maxPerSession) return false
  slot.sent.add(ev)
  slot.count += 1
  return true
}

/** 事件 → 文案（**能力通道出现** · 事实 + 动作 · ⛔ 不写「阶段」）。 */

export function eventHintText(ev: InjectEvent, streak = 2): string {
  switch (ev) {
    case 'anchor-claimed':
      return '【AI-OS · 能力通道】任务已开始。把「在做什么 + 需要哪类能力」告诉 `auto_capability`，'
        + '**请使用它**，以便更好的完成任务 —— 相关工具 / 经验会**自动找给你**（不调也能继续）。'
        + '⏭️ **等会你第一次改文件时，我还会再出现一次。**'
    case 'first-edit':
      return '【AI-OS · 能力通道】第一条实质改动已出现 —— **再**告诉 `auto_capability` 一次，'
        + '**请使用它**，以便更好的完成任务 —— 它会把与当前任务同形的做法 / 坑找来（不调不影响继续）。'
    case 'stuck':
      return '【AI-OS · 能力通道】最近连续 ' + String(streak) + ' 步工具失败。把「卡在哪」告诉 `auto_capability`'
        + '（`need` 含「调试」），它会去找排查经验。'
    case 'gap':
      return '【AI-OS · 能力通道】刚才有一步工具失败了 —— 把「卡在哪 / 报错原文」告诉 `auto_capability`'
        + '（`need` 含「调试」），**请使用它**，它会去找同类问题的排查做法与坑。'
    case 'repeat-question':
      return '【AI-OS · 能力通道】这次的问题和上一条高度重合 —— 先对齐：把「上次哪里没做对」告诉 `auto_capability`'
        + '（`need` 含「调试」），**请使用它**，它会去找同类问题的排查做法；⛔ 别在没对齐前重复动手。'
    case 'user-named':
      return '【AI-OS · 能力通道】你要求做一次检索。调 `auto_capability`：`what` 写当前在做什么，'
        + '`need` 可填（前端 / 后端 / 文档 / 调试 / 检索 / 评审…）。'
  }
}

/** 用户**点名**要检索的说法（给的叫法：「做个检索」「找找能力」）。 */

export let R3_DISARM_PENDING: { session: string; card: string } | null = null

/** 写入口（ESM 导入绑定只读；主文件 L5111 改写为一次调用）。 */

export function setR3DisarmPending(v: { session: string; card: string } | null): void {
  R3_DISARM_PENDING = v
}

/** 候选递送的**兜底硬超时**（主闸是回合序号 —— 见 `pendingStaleReason()`）。 */

export const PENDING_DELIVERY_MAX_AGE_MS = 600_000

/**
 * 判定一条待递送候选**是否已过期**（返回 `null` = 仍然有效，否则返回原因串）。
 * 🔴 为什么需要它：检索是**异步**的，候选在**产出**与**递送**之间至少隔着一次工具调用。
 *    若这期间回合已前进、或焦点卡已切换，候选描述的就是**上一个语境**
 *    ⇒ 递给 Agent 不是帮助而是噪声（`RETURN-AND-DELIVERY-VERIFICATION.md` 的时效要求）。
 * 判据（**全部只读内存态** · ⛔ 不新增事实源 · ⛔ 不写文件）：
 *   ① `window-advanced` —— 产出时的回合序号 ≠ 当前回合序号（**主闸**：语境变化的代理量）
 *   ② `expired`         —— 超过兜底硬超时（同回合内极端拖延的兜底）
 *   ③ `focus-changed`   —— 当前焦点卡 ≠ 产出时焦点卡（**复用同一判据 `focusCardOf()`** ·
 *      ⛔ 不另立第二套选卡判据 —— `RESPONSIBILITY-BOUNDARIES.md §0/§2` / V-2）
 *      ⚠️ 焦点卡**判不出**（`null` / 空串）时**不**据此丢弃：那是"不确定"，不是"已变化"（宁少丢不误丢）。
 */

export function pendingStaleReason(ds: SessionState, pd: PendingDelivery, now: number): string | null {
  if (ds.windowSeq !== pd.windowSeq) return 'window-advanced'
  if (now - pd.at > PENDING_DELIVERY_MAX_AGE_MS) return 'expired'
  const cur = focusCardOf(ds).key
  if (cur !== null && cur !== '' && cur !== pd.cardKey) return 'focus-changed'
  return null
}

/**
 * 🔴 **Step B′ · 递送**（原 `apply()` 内逐字搬入）。
 * 顺序（与原代码同序、同短路）：
 *   ① 读开关（读不到即透明）⇒ ② 判「有没有活要干」（6 个来源独立参与早退门）⇒ ③ `await next()` **恰好一次**
 *   ⇒ ④ `try {` 各注入源按原顺序 push `extras`；任何失败 ⇒ 原样透传下游 decision。
 * @returns 下游 decision：无注入时原样返回；有注入时 `{ ...downstream, additionalContexts: [...prior, ...extras] }`。
 * ⚠️ 副作用与原来完全一致（模块级 Set/Map、`R3_DISARM_PENDING`、`ist`/`pslot` 等对象按引用改）。
 * ⚠️ `exec`/`result` 来自 `tools/post-execute` 载荷；`next` = 宿主 waterfall 的续行（保持原 await 点）。
 */
/** ── 从 maintenance/r3-wake.ts 上收的共享声明 ── */
export type NodeId = 'N1' | 'N2' | 'N3'

/** N1 判据：编辑目标是**语料** —— `domains/**`（含 `domains/experiences/...`）或 `task_cards/memory/PITFALLS.md`。
 *  ⚠️ `domains/experiences/inject_digests.md` 已被 `domains/**` 覆盖，下面单独写一项只为**显式对齐任务清单**。 */

// ── 由 `aios-activation.ts` 迁入（R2 类型接线）──

export function capabilityIdsOf(session: string): ReadonlySet<string> {
  return RETURNED_CAPABILITY_IDS.get(session) ?? new Set<string>()
}

export function buildFirstStepRetrievalRequest(firstUserText: string, wc: WorkContext, now: number,
                                        session: string): Record<string, unknown> | null {
  const topic = String(firstUserText === undefined || firstUserText === null ? '' : firstUserText)
    .replace(/\s+/g, ' ').trim().slice(0, PHASE_TOPIC_MAX)
  if (topic === '') return null
  return phaseRequestOf('S1', topic, wc, now, session, 'first-step')
}

// ── 阶段注入候选**打分**（0–1） + 按分排序后取 top1（； 曾取前 5） ─────
//   为什么（读数诊断）：`pool:3` 的真相是请求 `budget.max_candidates=3` 截断；放宽后出 7 条能力、
//   `host-runtime-traps` 排 #4 被截掉 ⇒ ① **上限 3→5**（含请求 budget，否则池子还是 3）② 给候选**打分**，
//   分数只进探针（⛔ 不写进注入文本，保持「能力名 — 一句话 + → 路径」形态）。
//   ⛔ 边界：**只用候选 payload 现有信号**，不新造语料特征、⛔ 不改 python 检索内核（`tools/probes/` 不在写域）。
//   🔴 可用字段（`candidate-set/v1` 的**原始**候选 item —— 注意不是 `retrievalCandidatesOf` 的工具返回
//      白名单：S109 明确「⛔ 不给正文 / 分数」⇒ 工具返回里没有分数原料，但阶段注入拿的是**原始 set**）：
//        · `hit_channels: string[]` —— 命中通道（identifier / axis / topic / role / keys / intent / context）
//        · `evidence: [{ channel, strength: 'strong'|'medium'|'weak', matched: string[] }]` —— 字段级证据
//      其余字段（`name` / `local_path` / `intro`）只用于渲染，不参与打分。
//   🔴 **打分公式（首版 · 未标定 UNVERIFIED）** —— 四项各自归一到 0–1，再按权重合成：
//        channelDiversity = min(1, 命中通道数 / 3)                       // 3 条不同通道即满分（多通道佐证更可信）
//        axisHit          = 命中通道含 `axis` ? 1 : 0                    // 词表三维**确定性情标签**（python 侧权重最高 4.0）
//        evidenceLevel    = min(1, (2*strong + 1*medium + 0.5*weak) / 3) // 3 条强证据即满分
//        matchedLevel     = min(1, 去重命中词数 / 6)                     // 6 个不同命中词即满分
//        score = 0.35*channelDiversity + 0.30*axisHit + 0.25*evidenceLevel + 0.10*matchedLevel
//      ⇒ 分数 ∈ [0,1]；**词面命中多 / 轴命中 / 强证据多 ⇒ 分高**（单调）。
//      ⚠️ 权重是首版拍定值，**不声称已验证**；的"新成员 + 真实任务"验证轮用探针 `scores` 判相关/不相关。
//   ⛔ 无任何可用信号（候选没有 `hit_channels` 也没有 `evidence`）⇒ 调用方回落 `score_mode:"none"`，
//      按 python 返回顺序取首条（注入只取 1 条），⛔ 不编分。
//   🔴 （真实同分样本驱动）：**旧公式对"同通道同日"的候选恒同分** ——
//      实证 `candidates:[frontend-ui, senior-engineer] · scores:[0.383, 0.383]`（人为判：senior 相关、
//      frontend 不相关）。根因不是"信号少"，而是旧公式把信号压成三个**会饱和**的标量
//      （`n/3` / `x/3` / `n/6`）⇒ **具体匹配被抹平**；同通道同轴的两条候选只能在两个饱和项上相等。
//      ⇒ 换成五项，其中三项直接取自**具体匹配**（⛔ 不读正文 / ⛔ 不调远程 / ⛔ 不改 python 检索内核）：
//        channelKind      = min(1, Σ命中通道权重 / 2)                    // 通道**种类**：axis > identifier > topic > role > keys/intent > context
//        matchedCoverage  = min(1, (命中词 ∩ topic 词) / topic 词数 / 0.25) // 命中词**覆盖 topic 的比例**（25% 即满分）
//        evidenceLevel    = min(1, (2*strong + 1*medium + 0.5*weak) / 4) // 分母 3→4：消"3 分即封顶"
//        axisCoverage     = min(1, 轴值命中数 / 3)                       // 轴是**几维**命中（旧版只看"含不含 axis"）
//        channelDiversity = min(1, 命中通道数 / 3)
//        score = 0.30*channelKind + 0.30*matchedCoverage + 0.20*evidenceLevel
//              + 0.10*axisCoverage + 0.10*channelDiversity
//      ⚠️ 权重仍是拍定值（UNVERIFIED）；`score_mode` 语义 / 条数 / 渲染文本**不变**，分数**只进探针**。
//      ⚠️ 边界：**不新造语料特征** —— topic 词来自请求已有的 `work_topic`；候选侧只用 payload 的
//         `hit_channels` / `evidence`（⛔ 不用 name/intro 打分；它们是渲染字段）。

export const RETRIEVAL_WORDS: readonly string[] = [
  '做个检索', '做检索', '检索一下', '找找能力', '找一下能力', '有什么能力', '哪些能力',
  '有没有相关', '有没有类似', '查一下有没有', '找个经验', '找经验', '搜一下',
]

/** 是否**用户点名**要检索（纯函数 · 供单测）。 */

export function detectRetrievalRequest(text: string): { hit: boolean; matched: string } {
  const t = String(text || '')
  for (const w of RETRIEVAL_WORDS) if (t.includes(w)) return { hit: true, matched: w }
  return { hit: false, matched: '' }
}

/** 卡 key（`项目/TASK-ID` 或 `TASK-ID.md`）⇒ 同级同名 `.log` 路径（与 `scanTakeovers` 同口径）。 */
