/** work-context.ts —— 由 `runtime/aios-activation.ts` 拆出（纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */





import type { SessionState } from './session-state.ts'

export interface TodoLite {
  content: string
  status: string
}

/** 从工具参数取 todo 列表（**内存处理** · 返回值**不落盘**）。 */

export type ToolClass = 'read' | 'search' | 'edit' | 'write' | 'exec' | 'plan' | 'other'

export function toolClassOf(tool: string): ToolClass {
  const t = (tool || '').toLowerCase()
  if (t === '') return 'other'
  if (/^(read|cat|notebook_read)/.test(t)) return 'read'
  if (/^(grep|glob|search|find|rg|fd|ls|list)/.test(t)) return 'search'
  if (/^(edit|multi_edit|apply_patch|sed)/.test(t)) return 'edit'
  if (/^write/.test(t)) return 'write'
  if (/^(pwsh|powershell|bash|shell|exec|run_command|node|python|git|npm|pnpm)/.test(t)) return 'exec'
  if (/^(todo_write|update_plan|plan)/.test(t)) return 'plan'
  return 'other'
}

/** 🔴 路径参数**只用于算目录类别**；其值本身**不落盘**。 */

export interface EvidenceMeta {
  src: EvidenceSrc
  /** wall clock（毫秒）。 */
  at: number
  /** 本回合序号（与判定/观察同一序号体系）。 */
  seq: number
  turn: number | null
  step: number | null
  /** 🔴 只有 `main` 会进入 WorkContext（子会话 fail-closed）。 */
  scope: 'main'
}

/** Activity 段的一条：工具名 + 类别 + 目录类别 + 结果（**不含参数原文**）。 */

export interface ActivityItem {
  tool: string
  cls: ToolClass
  pathClass: string | null
  /** 工具调用 id（用于把 `post-execute` 的 `ok` 精确回填到对应活动）。 */
  callId: string | null
  ok: boolean | null
  meta: EvidenceMeta
}

/**
 * Reasoning 段（**A 阶段结构观察**）：
 *   · 主路径（`session/event`）统计**已提交**的 `assistant/message` / `assistant/attempt`
 *   · 后备路径（`agent/assistant-stream`）只累计 `reasoning-delta` 帧
 *   🔴 只记**结构量**：块数 / 字符数 / 时长 / 形态签名 —— **推理文本本身不落盘、不留存**。
 *   🔴 `provider` / `model` 取自 `assistant/message.data.message.source`（观测项①）。
 */

export interface ReasoningObs {
  committedMessages: number
  attempts: number
  interrupted: number
  /** 已提交流中 `reasoning-chunks` 记录数（= 推理块数）。 */
  blocks: number
  /** 推理字符数（`texts` 拼接长度之和 · 只累加长度，不留内容）。 */
  chars: number
  /** 推理时长近似（Σ`dt` · 相邻 delta 时间差之和；口径见 `msBasis`）。 */
  ms: number
  /** 后备路径计数（`agent/assistant-stream` 的 reasoning 帧）。 */
  liveChunks: number
  liveChars: number
  /** 实际走通的数据来源（`none` = 两条路都没收到）。 */
  source: 'session-event' | 'assistant-stream' | 'none'
  /** 各来源观察到的记录类型签名（**读数编码形态** · 不含内容）。 */
  streamShapes: string[]
  provider: string | null
  model: string | null
  lastTurn: number | null
  lastStep: number | null
  lastAt: number | null
}

/** 进度段：**只放机械事实**（不标"调试阶段"之类语义结论 —— 明确禁止）。 */

export interface ProgressObs {
  /** 最近一次 `exec` 之后累计的 edit/write 次数。 */
  editsSinceLastExec: number
  /** 尾部连续失败次数（`ok === false`）。 */
  consecutiveFailures: number
  lastOk: boolean | null
  /** 机械派生信号（如 `has-edit` / `exec-after-edit` / `read-only-so-far`）。 */
  signals: string[]
}

// ── 阶段 2 · 推理**文本**读取（批准实施 · 设计见 `p0/STAGE2-REASONING-READ-DESIGN.md`）──
// 🔴 **授权范围（不得扩大）**：只做「读取实际推理文本 + 组织进内存 WorkContext + 归属 + 生命周期 + 结构量记录」
//    ✗ 不参与检索 / 语义 / 激活 ✗ 不递送 ✗ 不改注入开关 ✗ 不调远程 ✗ **不落原文**
// 🔴 **生命周期**：作用域 = session + Agent + turn；
//    **正式释放点 = `session/event` 的 `turn/end`**（`data.turn` 指明回合）
//    —— `agent/turn-stopping` 可被 `agent.steer()` **逆转**（"fresh steering runs another step"）
//       ⇒ **只作生命周期观测点**，🔴 **不得**据它释放（复核修正）

/** 每 turn 推理文本字符上限（**保守首版值 · 未通过读数验证** · 约定(a)）。 */

export const REASONING_TURN_CHARS_MAX = 32_000
/** 每 `(turn,step)` 的 `start` 帧队列上限（防重试风暴 · 保守值 · UNVERIFIED）。 */

export const TURNING_POINT_MAX = 64

// ── 阶段三 3.1 · **收窄参数**（裁定：**用回放选定 · 不先拍数字**）──────
//   选定依据（`p0/HANDOFF §31.8`）：12 组候选在**两组真实历史数据**上回放 ⇒ 12 组**全部收敛**
//   （收敛由**分层降级链**保证，**不依赖参数**）⇒ 再按**预先固定**的排序（端点保留率 →
//   转折点邻域保留率 → 淘汰量）比较，取 max-min 与算术平均两种规则**一致**的最优组合。
/** 弱信号升级条件 (a)：距最近强信号 ≤ 此值 ⇒ 视为"与其他变化**共同出现**"。 */

export const TP_ADJACENT_MS = 60_000
/** 弱信号升级条件 (b)：该变化后同一 `pathClass` 连续出现 ≥ 此次数 ⇒ "变化具有**持续的意义**"。 */

export type TurningPointKind =
  | 'todo-changed'
  | 'todo-new-direction'
  | 'card-mapping-change'
  | 'phase-change'
  | 'tool-error'
  | 'attempt'
  | 'tool-object-change'

/** 弱信号升级原因（可核 · 无原因 ⇒ 保持 weak）。 */

export interface TurningPoint {
  at: number
  kind: TurningPointKind
  /** 🔴 **只有 `strong` 进保护集合**；`weak` 默认不保护（收窄裁定的核心）。 */
  strength: 'strong' | 'weak'
  upgradedBy: TpUpgradedBy | null
  /** 归属回合（⚠️ 工具事件载荷无 `turn` ⇒ 取自当前回合上下文 · 如实标注为时间关联）。 */
  turn: number | null
}

/** 归属方式（**必须可区分** ⇒ 低归属率才能归因到「数据缺失 / 关联问题 / 实现缺陷」）。 */

export interface ReasoningEntry {
  /** 去重 + 归属主键：`${sessionId}#${seq}` */
  key: string
  session: string
  turn: number
  step: number
  /** 事件日志序号（日志内单调 ⇒ 排序与去重的唯一依据） */
  seq: number
  settlement: 'message'
  interrupted: boolean
  /** 🔴 推理原文 —— **仅内存** · 释放后不可达 */
  text: string
  chars: number
  blocks: number
  ms: number
  provider: string | null
  model: string | null
  attribution: Attribution
  unavailableReason: UnavailableReason | null
  attemptId: string | null
  revision: number | null
  nature: 'agent-self-explanation'
  confidence: 'assumption' | 'interrupted'
  at: number
}

/** 一条 `start` 帧 pending 记录。 */

export interface PendingStart {
  attemptId: string
  revision: number | null
  at: number
}

/** WorkContext 六段（内存）。 */

export interface WorkContext {
  /** ① 意图：当前用户消息正文 —— 🔴 **仅内存**，`intentLen` 才可落盘。 */
  intentText: string
  intentLen: number
  intentMeta: EvidenceMeta | null
  /** ② 计划：todo 完整内容（内存）· 落盘只落派生量（计数 / 状态分布 / 关键词 / 变化）。 */
  plan: {
    count: number
    status: Record<string, number>
    keywords: string[]
    changed: boolean
    newDirection: boolean
    /** 🔴 Todo **完整内容**（**内存** · 供后续发现使用）· 探针**绝不落盘**。 */
    items: TodoLite[]
  } | null
  planMeta: EvidenceMeta | null
  /** ③ 推理流（A 阶段结构观察）。 */
  reasoning: ReasoningObs
  /** ④ 环境：cwd + 末段目录名 + 唯一可关联的卡。 */
  cwd: string
  cwdTop: string
  cardKey: string | null
  /** ⑤ 活动：最近工具调用（环形上限）。 */
  activity: ActivityItem[]
  /** ⑥ 进度：机械派生。 */
  progress: ProgressObs
  /** 🔴 理解结果：本插件无 LLM ⇒ **恒为 null**（等第二层能力，不伪装）。 */
  understanding: null
  // ── 阶段 2 新增（推理**文本**读取 · **仅内存** · `turn/end` 释放）──
  /** 推理文本条目（按 step 分条 · 不拼接） */
  reasoningEntries: ReasoningEntry[]
  /** 本 turn 已累计字符数（`REASONING_TURN_CHARS_MAX` 的分母） */
  reasoningChars: number
  /** 已淘汰条目数 / 字符数（**只记数量** · 不记内容） */
  reasoningEvictedEntries: number
  reasoningEvictedChars: number
  /** `start` 帧 pending 队列：key = `${turn}:${step}` ⇒ FIFO */
  pendingAttempts: Map<string, PendingStart[]>
  /** 已处理事件 seq（去重 · 有上限 LRU） */
  seenSeq: Set<number>
  /** provisional（失败 / 重试 / 取消）attempt 的**计数**（不建 entry · 不留存文本） */
  provisionalAttempts: number
  // ── 阶段三 3.1 · 保留策略（`§28.13` · **仅内存** · 与 entry 同生命周期）──
  /** 本会话的转折点（判据来源 · 按时间关联 · `turn/end` 清理该 turn 的转折点） */
  turningPoints: TurningPoint[]
  /** 🔴 **R8**：当前内存中的推理历史**是否完整**（'partial' ⟺ 存在未释放的"曾淘汰"回合） */
  historyCoverage: 'complete' | 'partial'
  /** 生效中的策略标记（落盘 · 无原文） */
  retentionPolicy: string
  /** 累计淘汰的序号区间（合并后 · **可落盘 · 无原文**） */
  evictedSeqRanges: Array<[number, number]>
  /** 发生过淘汰的回合集合（**仅内存** ⇒ 释放该回合后 `historyCoverage` 才能如实回到 'complete'） */
  evictedTurns: Set<number>
  /** 因 `TURNING_POINT_MAX` 丢弃的**派生索引**条数（**如实计数** · 不静默；推理条目不受影响） */
  turningPointDropped: number
  /** 🔴 **物理下限**计数：内存只剩 1 条仍超预算 ⇒ 停止并**如实记**（不伪装成已收敛） */
  overBudgetFloor: number
}

/** 活动环形上限（防内存膨胀；只保留最近窗口）。 */

export function trimTurningPoints(s: SessionState): number {
  while (s.wc.turningPoints.length > TURNING_POINT_MAX) {
    s.wc.turningPoints.shift()
    s.wc.turningPointDropped += 1
    if (s.pendingWeakTpIndex !== null) s.pendingWeakTpIndex -= 1
    if (s.pendingWeakTpIndex !== null && s.pendingWeakTpIndex < 0) s.pendingWeakTpIndex = null
  }
  return s.wc.turningPoints.length - 1
}

/**
 * 弱信号升级条件 (a)：把最近 `TP_ADJACENT_MS` 内**尚未升级**的弱信号升级为强
 * （"与其他变化**共同出现**" · 强信号出现时**回溯**判定 ⇒ 双向覆盖）。
 * 🔴 **锚点只用原始强信号**（升级来的弱信号**不**再当锚点）⇒ 不做传递闭包（否则保护面会重新变宽）。
 */

export function upgradeAdjacentWeak(s: SessionState, now: number): void {
  for (let i = 0; i < s.wc.turningPoints.length; i++) {
    const tp = s.wc.turningPoints[i]
    if (tp.strength !== 'weak') continue
    if (now - tp.at > TP_ADJACENT_MS) continue
    tp.strength = 'strong'
    tp.upgradedBy = 'adjacent'
    if (s.pendingWeakTpIndex === i) s.pendingWeakTpIndex = null
  }
}

/** 记一条**原始强**转折点（Todo 变化 / 卡片映射变化 / 有结果支持的阶段转变 / 报错 / attempt）。 */

export function pushStrongTp(s: SessionState, kind: TurningPointKind, turn: number | null): void {
  const at = Date.now()
  s.wc.turningPoints.push({ at, kind, strength: 'strong', upgradedBy: null, turn })
  trimTurningPoints(s)
  s.lastStrongTpAt = at
  upgradeAdjacentWeak(s, at) // 回溯：把刚过去的弱信号一并升级（共同出现是双向的）
}

/**
 * 记一条**弱**转折点（工具对象变化 · **默认不保护**）。
 * 若距最近强信号 ≤ `TP_ADJACENT_MS` ⇒ 直接升级（条件 a）；否则登记为 weak 并作为**待定项**，
 * 等"持续出现"被证实后由 `trySustainUpgrade` 回溯升级（条件 b）。
 */

export function failStreakOf(activity: readonly ActivityItem[]): number {
  let streak = 0
  for (let i = activity.length - 1; i >= 0; i--) {
    const a = activity[i] as { ok?: boolean | null }
    if (a.ok === false) streak += 1
    else break
  }
  return streak
}

// ── 🔴 触发层调优的**纯函数**（T2 缺口分类 / T5 注入限额 / T7′ 同一问题第 2 次）
//    依据：9 份回放访谈 + 84 会话机械读数（卡 `AI-OS-Adaptation/TASK-20261023-001` 第 32–39 批）。
//    ⛔ 边界不变：全部只做**词面/结构**判定，⛔ 不读语义、⛔ 不落原文。

/** T2：**事实型失败**（重读 / 路径 typo / 参数错）—— 检索帮不上，⛔ 不该触发 gap。 */

export const FACTUAL_FAIL_RE = /not found|no such file|cannot find|ENOENT|ParserError|old_string|old string|file has not been read|file changed since it was read|no changes|拒绝访问|access denied|WinError 5|FS_STALE/i

/** 🔴 （选 B）：**权限/沙箱族**失败也触发经验召回。
 *  背景：`FACTUAL_FAIL_RE` 含 `拒绝访问 / access denied / WinError 5` ⇒ 权限类失败被判**事实型** ⇒ 永不触发；
 *  但「权限族卡」需要**自然出现**（族卡实验的口径：族出现 + Agent 知晓，族内怎么做不判）。
 *  ⛔ 不改 `failKindOf`（T2 gap 口径原样）——只在经验召回入口加**独立触发类型** `permission-error`。
 *  ⚠️ 只做词面判定（Runtime 边界不变：⛔ 不读语义）。 */

export function failKindOf(result: any): 'factual' | 'knowledge' | null {
  if (result === null || result === undefined || result.isError !== true) return null
  let text = ''
  try {
    const c = result.content
    if (Array.isArray(c)) {
      for (const x of c) text += String(x !== null && x !== undefined && x.text !== undefined ? x.text : '') + '\n'
    } else if (typeof c === 'string') {
      text = c
    } else if (typeof result.output === 'string') {
      text = result.output
    }
  } catch { /* 取不到内容 ⇒ 走保守分支 */ }
  // 拿不到内容 ⇒ 保守按「知识型」（照旧允许提示）；拿得到才按关键词分类
  if (text === '') return 'knowledge'
  return FACTUAL_FAIL_RE.test(text) ? 'factual' : 'knowledge'
}

/** T7′：词面 token 集合 —— 英文/数字词（≥3 字符）+ 中文相邻 2-gram。 */

// ── 由 `aios-activation.ts` 迁入（R2 类型接线）──

export type EvidenceSrc = 'user-message' | 'todo' | 'reasoning' | 'tool' | 'card' | 'cwd'

/** 统一证据元数据（避免把主/子会话混在一起，也避免把过期状态当当前事实）。 */

export type TpUpgradedBy = 'adjacent' | 'sustained'

/** 一条转折点（**仅内存** · 只存时间 / 类别 / 强度 / 所属 turn · **无原文**）。 */

export type Attribution = 'explicit-id' | 'fifo-unique' | 'unavailable'
/** 归属不可用的**具体原因**（明确要求可区分）。 */

export type UnavailableReason = 'no-start-seen' | 'ambiguous-queue' | 'parse-degraded' | 'scope-mismatch'

/**
 * 一条推理证据（按 step / attempt **分条** · 不拼接）。
 * 🔴 `text` **只存在于内存**；`turn/end` 到达即释放。
 * 🔴 证据性质：`nature` = Agent 对任务的**自我解释** ⇒ 可能含假设 / 错误 / 被放弃的方向，
 *    **不得**与「用户意图」「执行结果」同级当作事实。
 */
