/** session-state.ts —— 由 `runtime/aios-activation.ts` 拆出（纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */





import type { WorkContext } from './work-context.ts'

export const MAX_SESSIONS = 64
/**
 * ⚠️ 首版阈值（UNKNOWN · 无验证基线）：归一化后 ≤ 该长度 ⇒ 视为"延续 / 短应答"。
 * 依据 `§14.8 C 类`（"继续" / "这个函数也改一下"）—— 阈值只用于**保守地不立即发现**，
 * **不用来断定"这是新任务"**（后者本版不判，见文件头 UNKNOWN B）。
 */

export interface SessionState {
  identity: Identity
  basis: string
  phase: Phase
  /** 同一 turn 只评估一次（去重）。 */
  lastEvalTurn: number | null
  /** 上次看到的任务事实（**去重的核心**：同卡同 step ⇒ C 类保持安静）。 */
  cursor: Snapshot | null
  counts: Record<TriggerKind, number>
  discoCounts: Record<Discovery, number>
  /** 输入性质（不含正文）。 */
  promptClass: PromptClass
  /** 延迟发现等待窗口是否打开（§15.4 阶段②）。窗口 = **本回合**。 */
  waiting: boolean
  /**
   * 回合序号（每次被评估的 `pre-step` +1）。
   * 🔴 **刻意不依赖载荷里的 `turn`** —— 真实窗口读数：`tools/pre-execute` 的载荷**没有 `turn`**
   *    （`packages/core/tools/src/index.ts:307-331` `ToolExecutionInput = {callId, rootCallId?, name,
   *    arguments, agent?, parent?, signal}`）。早期版本用 `e.turn` 去重 ⇒ 真实场景恒为
   *    `null !== null` ⇒ **工具意图永不记录**（缺陷见 `p0/HANDOFF §12.10`，隔离自测因 mock 塞了
   *    `turn: 1` 而漏判）。
   */
  windowSeq: number
  /** 已观察过意图的回合序号（同一回合只观察首个实质意图）。 */
  observedSeq: number
  /** 本窗口是否已命中意图（命中即关窗 ⇒ 天然防重复，不需第二个去重键）。 */
  intentSeenInWindow: boolean
  /** ② 本回合的工作方向签名（`工具类别:目录类别`，按出现顺序；回合开始时清空）。 */
  turnSig: string[]
  /** 本回合是否已产生 deferred 机会（供 `step` 记录"本回合是否已 deferred"）。 */
  deferredSeen: boolean
  /** 本回合卡事实分类（供 `step` 记录关联激活类别）。 */
  lastTriggerKind: TriggerKind | null
  /** 本回合已判定的机会（供 `step` 记录）。 */
  lastDiscovery: Discovery | null
  /** 本回合激活依据标签（`prompt-*` / `card-fact-*`）—— **只作标签，不是判据**。 */
  activationBasis: string | null
  /**
   * ① **观察去重键**（`turn:step`，缺字段时退化为 `t<turn>`）。
   * 🔴 与"判定去重"（`lastEvalTurn`）**是两套** —— 观察要记录**每个** `pre-step`（含 `msgs=0`），
   *    若按 turn 去重会把同回合的延续步骤误吞，从而看不到"deferred 之后还有没有模型步骤"。
   */
  lastStepKey: string | null
  /**
   * ③ **S1 瞬时解析层**（**内存 · 不落盘**）：上一份 todo 计划的 token 集合 ——
   * 仅用于与本次快照做一致性比较（`todo_write` 是**整体替换**，必须比较新旧）。
   * ⚠️ 它**不是**事实状态源 · **不落盘** · **不持久化**（会话内存，重启即丢）。
   */
  todoSig: Set<string> | null
  /**
   * **本回合**是否已出现 todo 计划（**回合级** · 用于 `signals.semantic`）。
   * ⚠️ 与 `todoSig`（**跨回合**留存的上一份签名）语义不同 —— 前者答"这一轮有没有计划"，
   *    后者答"与上次方向是否一致"。二者不可混用。
   */
  todoSeenThisTurn: boolean
  /** **S4** 上次观察到的 cwd（仅用于"是否换了工作目录"）。 */
  lastCwd: string
  /** **S2** 上次焦点卡 `Goal` 的内容哈希（**内存 · 只落"是否变化"布尔**）。 */
  lastGoalHash: string
  /**
   * **阶段三 3.1** 当前回合号（**内存**）。
   * 🔴 用途：工具事件载荷**无 `turn`/`step`**（`§12.10`）⇒ 转折点只能按时间归属，
   *    需要一个"当前回合"的会话级游标（取自最近一次 `pre-step` 或提交事件）。
   */
  currentTurn: number | null
  /** **阶段三 3.1** 上一回合的工作方向签名（用于 第 ④ 类「回合签名变化」）。 */
  lastTurnSig: string[]
  // ── 阶段三 3.1（收窄）： 强弱分级所需的内存游标 ──
  /** 上次焦点卡 key（**任务 / 项目映射变化** = 强信号的机械依据）。 */
  lastFocusKey: string | null
  /** 本回合是否出现过**成功结果**（`ok:true` 且 `exec`/`edit`/`write`）—— 阶段转变必须有它支持。 */
  turnHadSuccess: boolean
  /** 最近一条**强**转折点的时间（弱信号"共同出现"判定的锚点）。 */
  lastStrongTpAt: number | null
  /** 当前 `pathClass` 连续出现次数 + 上一次的类别（弱信号"持续意义"判定的依据）。 */
  pathClassRun: number
  /** 🔴 **本会话的 id**（步骤 2：占用判据要拿它与卡上的留痕比对）。 */
  me: string
  /**
   * 🔴 **最近一次扫到的卡列表**（`scanCards()` 的产物）—— **焦点卡判据的真相来源**（步骤 2）。
   *   ⛔ 从**卡**读（`State=Executing` + `Event Log` 最后占用行的 `session`）；
   *   ⛔ **不再**从 `claim` 命令字面量推断（读数：被拒的 `claim` 也会被记账 ⇒ 与卡上真相不一致）。
   */
  cards: TaskCursor[]
  /**
   * **本会话的卡改动**（卡 key → 次数）。
   *   来源：本会话自己的 `edit` / `write` 命中 `task_cards/active/<项目>/TASK-*.md`（**只记路径**）。
   *   **退回为"提醒触发 + 审计证据"**（`GOAL-INPUT-CONTRACT.md §2.6 S2`），
   *   ⛔ **不再是焦点卡判据**（那由**卡上的占用留痕**决定 —— "编辑卡" ≠ "占用卡"）。
   *   用途：`reminderFor()` 的 `anchored` / `maintain` 判据。
   */
  cardEdits: Map<string, number>
  /**
   * 🔴 **本会话读过哪些卡**（卡 key → 次数）。
   *   与 `cardEdits` 的区别：**读 ≠ 改**（来看一眼不等于占用）。它只用于**提醒判据**（"已关联"）
   *   与**冲突审计**，⛔ **不再与 `State` 并列作为焦点卡判据** ——
   *   裁定：`State` 决定占用；读写事件退为**提醒触发 + 审计证据**。
   */
  cardReads: Map<string, number>
  /**
   * 本会话**已 release** 卡的**次数**（内存 · 只在 `task_card.py release` 命令**成功**时 +1）。
   *   用途：阶段判定 `S4 收口`（见 `phaseOf`）。⛔ 不是事实源（重启即丢）；占用/释放的**卡上真相**不变。
   */
  cardReleaseCount: number
  /** 本拍刚观察到 release 的**升沿**（post-execute 观测段置位 · 阶段段消费后清回 false）。 */
  releaseJustObserved: boolean
  /**
   * 本会话**第一条用户消息**（首次 `pre-step` 且 `msgs>0` 时**锁存**）。
   *   用途：会话首拍注入的 `work_topic` —— 首拍必然还没 claim ⇒ 卡的 `Goal`/`Next Action` 不可用。
   *   ⛔ 只锁存**一次**：后续回合的 `wc.intentText` 会被改写，用它就会变成"任意时刻的意图"（S165 拦回归）。
   *   ⚠️ 只进**内存**（与 `wc` 同生命周期 · 重启即丢）· ⛔ 不落盘 · 只用于构造检索请求。
   */
  firstUserText: string
  /**
   * 本会话**第几次** `tools/post-execute`（main / subagent · 每次进入即 +1 · 只进内存）。
   *   用途：**首拍判定**的机械依据 —— `=== 1` 即"本会话第一个工具调用刚收尾"。
   *   ⚠️ 为什么不用 `wc.activity.length`：同一 step 的**并行工具调用**会一次塞进多条活动 ⇒ 首拍时
   *      `activity.length` 可能 > 1，用活动条数会把这类会话误判成"已经开工"（首拍注入静默不触发）。
   */
  postExecuteCount: number
  /**
   * **最近一次扫到的卡 key 列表**（`TaskCursor.key`）。
   *   用途：把命令行里的 `TASK-ID` 还原成**卡 key**（`claim` / `release` 走命令行 ⇒
   *   `cardEdits` 看不见，需要从命令字面量识别后再映射回卡）。⚠️ 只缓存 key，不含正文。
   */
  knownCardKeys: string[]
  /**
   * **待递送的候选项**（第③段）。
   *   检索是**异步**的 ⇒ 派发时（`tools/pre-execute`）拿不到结果，只能把渲染好的文本暂存，
   *   由**下一次** `tools/post-execute` 带出去（那是 DSH 唯一能「向下游添加上下文」的扩展点）。
   *   由 `string` 改为 `PendingDelivery`（带回合序号 / 焦点卡 / 时间戳）
   *      ⇒ 递送前可核对时效，过期即**丢弃并留派生读数**（见 `pendingStaleReason()`）。
   */
  pendingDelivery: PendingDelivery | null
  /** 已递送次数（候选型 · 上限 = 探针的 `maxPerSession` · 防刷屏）。 */
  deliveredCount: number
  /** 提醒①是否已发（**每会话一次** · 防打扰 —— `AUTOMATION-BOUNDARY §12.0.1` 的噪声教训）。 */
  reminderA: boolean
  /** 提醒②是否已发（同上）。 */
  reminderB: boolean
  /** 提醒③「**一个对话同时只能占一张卡**」是否已发（同上 · 补丁）。 */
  reminderC: boolean
  /**
   * 提醒④「**该用 `auto_capability` 而没用**」是否已发（每会话一次 · 授权）。
   * 🔴 这是"可知性 A+C"里的 **C**：A = 工具描述常驻；C = 首次需要时提醒一次（⛔ 不常驻、不重复）。
   */
  reminderD: boolean
  lastPathClass: string | null
  /** 待升级的弱转折点在 `turningPoints` 中的下标（"持续"被证实后**回溯升级**）。 */
  pendingWeakTpIndex: number | null
  // ── 🔴 触发层调优 · 四个新字段（**全部仅内存** · ⛔ 不落盘）──
  /** T7′：上一条**用户**消息（已剥宿主注入块）—— 供「同一问题第 2 次」词面重合判定。 */
  lastUserTextClean: string
  /** T7′：本次用户消息是否与上一条高度重合（且期间未推进）—— 由 `UserPromptSubmit` 写入。 */
  repeatQuestion: boolean
  /** T2：最近一次工具失败的**类型**（`factual` = 路径 / 重读 / 参数类 ⇒ 不触发 gap）。 */
  lastFailKind: 'factual' | 'knowledge' | null
  /** T5：自上次成功调用检索以来已注入几条 —— 达到 2 后本会话停发（`dacf` 22 次提示 → 2 调用 → 0 打开）。 */
  injectsSinceRetrieval: number
  /**
   * **Step A′** WorkContext 六段（内存快照）。
   * 🔴 重启即丢 · **不是**事实状态源 · 可重建 ⇒ 不得据它声称任何任务事实。
   */
  wc: WorkContext
}

// ── Step A′：WorkContext 六段（**内存快照** · Observe-only · 裁定）──
// 🔴 性质：**不是**新账本 · **不是**新的事实状态源 —— 由现有事件**临时组装**、使用后释放、
//    重启即丢；**可重建**，不依赖任何必须永久保存的 `ACTIVE` 状态。
// 🔴 前五段 = 已有信息的「**汇集**」；末段 `understanding` = 对工作的「**解释**」——
//    本插件无 LLM ⇒ **诚实标 `null`**，**不得**用机械关键词冒充语义理解（`§24.2` / `§24.3`）。
// 🔴 四类事实不可混同：用户意图 / Agent 计划 / 实际行为 / 执行结果（`§24.1`）。

/** 证据来源（表：来源 · 时间 · 会话 · Agent 作用域 · 新鲜度）。 */

export const SESSIONS = new Map<string, SessionState>()

/** 一行结构化日志（stdout + 探针双通道）；任何失败都不得影响宿主。 */

export function identityOf(agent: any): { identity: Identity; basis: string } {
  const h = agent && agent.session && agent.session.header
  if (!h) return { identity: 'unknown', basis: 'no session header' }
  if (h.origin === 'subagent') return { identity: 'subagent', basis: 'origin=subagent' }
  if (typeof h.delegationDepth === 'number' && h.delegationDepth > 0) {
    return { identity: 'subagent', basis: 'delegationDepth=' + String(h.delegationDepth) }
  }
  if (h.parentSession !== undefined) return { identity: 'subagent', basis: 'parentSession set' }
  return { identity: 'main', basis: 'depth=' + String(h.delegationDepth) + ' origin=<absent>' }
}

// ── T0：输入性质（§15.1 T0 · 只记归类与长度，绝不记正文）────────────────────

/** 从消息内容里抽纯文本（多形态兼容 —— 真实结构未验证，见文件头 UNKNOWN C）。 */

export function sessionIdOf(agent: any): string {
  const h = agent && agent.session && agent.session.header
  return h && h.id !== undefined ? String(h.id) : 'unknown'
}

/**
 * 丢弃一个会话的**全部内存态**。
 * 🔴 修：此前只有 `SESSIONS` 受 `MAX_SESSIONS`（64）约束，
 *    而 `STAGE4_DONE` / `STAGE4_INFLIGHT` / `SHADOW_DONE` / `SHADOW_DIAG` 四个**会话级**集合
 *    **只增不减** —— 它们同样是"按 session 建条目"，却没有任何上限或清理
 *    ⇒ 长驻进程（DSH 插件可常驻数天）会随"曾出现过的会话数"**无界增长**。
 *    ⇒ 会话级状态必须**同一生命周期**：一起建、一起丢（本函数即唯一丢弃点）。
 * ⛔ 只清内存态；⛔ 不碰任何文件 / 探针 / 开关（它们本来就不是事实源）。
 */

// ── 由 `aios-activation.ts` 迁入（R2 类型接线）──

export type Identity = 'main' | 'subagent' | 'unknown'

export type Phase = 'IDLE' | 'CANDIDATE' | 'ACTIVE'

export type TriggerKind = 'A' | 'B' | 'C' | 'D'
/** T0 输入性质（**不含正文** · 机械分类 · `unknown` 表示读不到输入 ⇒ fail-closed）。 */

export type PromptClass = 'continuation' | 'unclassified' | 'unknown'
/** T1/T2 意图类别（`plan` = 组织计划 · `work` = 实际工作工具）。 */

export type Discovery = 'task_fact' | 'waiting' | 'deferred' | 'quiet' | 'none' | 'missed'

/**
 * 卡的占用留痕（**步骤 2**）—— 从卡内 `Event Log` 的**最后一条**占用/释放行解析。
 * 🔴 这是「**谁占用**」的**唯一真相**（由工具 `task_card.py` 写入）；⛔ 不再从命令字面量推断。
 */

export interface Snapshot {
  /** 上次所有 `Executing` 卡的 key —— **检测"新进入任务"的唯一依据**。 */
  execKeys: string[]
  /** 焦点卡（仅当唯一 `Executing` 时确定；多张时为 null ⇒ 保守）。 */
  focus: TaskCursor | null
  /** 焦点卡上次的 `Current Step`（用于 B 类判定）。 */
  focusStep: string
}

/** prompt 抽取结果：`text` 只在内存中用于算长度，**不落盘**。 */

export interface PendingDelivery {
  /** 渲染好的候选文本（给模型看的那段）。 */
  text: string
  /** 产出时的**回合序号**（`SessionState.windowSeq`）—— 递送时不等 ⇒ 语境已变。 */
  windowSeq: number
  /** 产出时的**焦点卡 key** —— 递送时与本会话当前焦点卡不符 ⇒ 对象已变。 */
  cardKey: string
  /** 产出时的 wall clock（毫秒）—— 兜底硬超时。 */
  at: number
}

/** 唯一的临时控制状态：会话级、内存、重启即丢、**不是事实源**。 */
/** ── 从 maintenance/r3-wake.ts 上收的共享声明 ── */
export interface Occupancy {
  op: 'claim' | 'release'
  /** 该行记录的会话 id（`-` = 非特定会话发起，如启动回收）。 */
  session: string
}

/** 任务事实快照条目：**只读**卡的字段（S2 增读 `Goal` / `Next Action`；步骤 2 增读 `occupancy`）。 */

export interface TaskCursor {
  /** 卡的相对键（判断"卡是否换了"）。 */
  key: string
  /** `State:` 的首个 token（如 `Executing` / `Waiting`）。 */
  state: string
  /** `Current Step:` 原文（判断"阶段是否变了"）。 */
  step: string
  /** **S2** `Goal:` 首行（**只在焦点唯一时使用**；原文**不落盘**，只落长度与"是否变化"）。 */
  goal: string
  /** **S2** `Next Action:` 首行（同上）。 */
  next: string
  /** 🔴 **占用留痕**（步骤 2）：仅对 `State=Executing` 的卡读取（省 I/O）；其它为 `null`。 */
  occupancy: Occupancy | null
}

/** 去重游标：上次观测到的 Executing 集合 + 焦点卡。 */
