/** pending-delivery.ts —— 由 `runtime/aios-activation.ts` 拆出（纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */
import { readFileSync } from 'node:fs'




import { OBS, emit, mono, resolveStateFile } from './../diagnostics/probe.ts'
import { readSwitchCached, userMessageOf } from './../diagnostics/probe.ts'

export type ProbeSessionSpec = string | string[]
/** 命中结果：`exact` = 字面相等 · `pattern` = 通配命中（判读时必须能分辨这两者）。 */

export type SessionMatch = { hit: boolean; mode: 'exact' | 'pattern' | 'none' }

export function parseProbeSessions(v: unknown): string[] | null {
  if (typeof v === 'string') return v === '' ? null : [v]
  if (!Array.isArray(v) || v.length === 0) return null
  const out: string[] = []
  for (const x of v) {
    if (typeof x !== 'string' || x === '') return null   // 数组里混进非法项 ⇒ 整体不匹配（fail-closed）
    out.push(x)
  }
  return out
}

/** 单条模式：`*` ⇒ 任何会话；尾 `*` ⇒ 前缀；其余 ⇒ 字面相等。 */

export function probePatternHit(pattern: string, session: string): { hit: boolean; mode: 'exact' | 'pattern' } {
  if (pattern === '*') return { hit: true, mode: 'pattern' }
  if (pattern.length > 1 && pattern.endsWith('*')) {
    return { hit: session.startsWith(pattern.slice(0, -1)), mode: 'pattern' }
  }
  return { hit: session === pattern, mode: 'exact' }
}

export function sessionAllowsProbe(spec: ProbeSessionSpec, session: string): SessionMatch {
  const pats = parseProbeSessions(spec)
  if (pats === null || session === '') return { hit: false, mode: 'none' }
  let best: 'none' | 'pattern' = 'none'
  for (const p of pats) {
    const r = probePatternHit(p, session)
    if (r.hit && r.mode === 'exact') return r
    if (r.hit) best = 'pattern'
  }
  return { hit: best !== 'none', mode: best }
}

/**
 * `probe-session`（**只读授权行** · 每个 (会话, 开关, 模式集) 只落一次）：
 * 让"插件此刻对**谁**开机"在探针里**可查**。没有它，通配绑定会变成新的不可见状态
 * （`HANDOFF §四十五` 的教训：不落判据 ⇒ 事后只能靠历史样本猜机制）。
 * ⚠️ `granted:false` 行**不是错误**，是"开关读了、但本会话不在绑定里"的事实记录 ——
 *    与"开关文件缺失/非法 ⇒ 完全透明且无任何记录"必须能分开（否则 fail-closed 无从取证）。
 */

export const PROBE_AUTH_SEEN = new Set<string>()

export function noteProbeAuth(key: string, session: string, spec: ProbeSessionSpec, sessionKey: string | null, m: SessionMatch): void {
  const specRaw = JSON.stringify(spec)
  const k = key + '|' + sessionKey + '|' + specRaw
  if (PROBE_AUTH_SEEN.has(k)) return
  PROBE_AUTH_SEEN.add(k)
  emit({
    ev: 'probe-session', obs: OBS, session,
    probe: key, spec: specRaw,
    sessionBound: sessionKey, granted: m.hit, match: m.mode,
    note: m.hit
      ? (m.mode === 'pattern' ? '通配绑定命中（`*` = 任意会话 · `a*` = 前缀）' : '字面 id 绑定命中')
      : '开关已读但**本会话不在绑定内** ⇒ 不工作（不是故障）',
    at: Date.now(), mono: mono(),
  })
}

/**
 * 运行期**开关文件**解析（**只读探测存在性，不写不搬** —— 迁移由 /Agent 显式执行，⛔ 不由插件偷偷做）。
 *   三级：① `AIOS_STATE_DIR/<新名>` ▸ ② `AIOS_STATE_DIR/<旧名>` ▸ ③ **`<root>/scratch/<旧名>`**
 *   🔴 第三级是**必须的**（读数故障）：迁移把"权威状态目录"改成了 `.aios/`，
 *      但四个开关文件当时**还留在 `scratch/`** ⇒ 只做前两级 ⇒ 开关**一个都读不到**
 *      ⇒ `post-execute` 第一行就 `return next()` ⇒ 影子与递送**整段静默失效**（探针零记录、无任何报错）。
 *      ⚠️ 教训：**"改默认目录"这种改动必须带上"旧位置兜底"**，否则失效是静默的。
 *   · 都没有 ⇒ 返回首选名（⇒ 读不到 ⇒ fail-closed，与"开关缺失"语义一致）。
 */

export const PROGRESS_WINDOW = 6

export function deliveryProbeFile(): string {
  return process.env.AIOS_DELIVERY_PROBE || resolveStateFile('delivery_probe.json', '_delivery_probe.json')
}

export interface DeliveryProbe {
  /** ⚠️ 逐字保留开关原文（`"*"` / `a*` / 数组）—— 会话命中判据见 `sessionAllowsProbe()`。 */
  session: ProbeSessionSpec
  marker: string
  maxPerSession: number
}

/** 读启停开关（**每次调用**）。任何异常 ⇒ `null` ⇒ 完全透明（fail-closed 到"不附加"）。 */

export function readDeliveryProbe(): DeliveryProbe | null {
  let raw: string
  try {
    raw = readFileSync(deliveryProbeFile(), 'utf8')
  } catch {
    return null
  }
  try {
    const o = JSON.parse(raw) as Record<string, unknown>
    if (!o || o.enabled !== true) return null
    if (parseProbeSessions(o.session) === null) return null
    if (typeof o.marker !== 'string' || o.marker === '') return null
    return {
      session: o.session as ProbeSessionSpec,
      marker: o.marker,
      maxPerSession: typeof o.maxPerSession === 'number' && o.maxPerSession > 0 ? o.maxPerSession : 1,
    }
  } catch {
    return null
  }
}

/**
 * 本插件**自己**发起的附加次数（内存 · 重启即丢 · 仅用于"一次性"限制）。
 * 🔴 按 **marker** 计数（而非全局计数）⇒ 不同标记互不干扰，语义 = "这段标记最多发 N 次"。
 */

export function shadowProbeFile(): string {
  return process.env.AIOS_SHADOW_PROBE || resolveStateFile('shadow_probe.json', '_shadow_probe.json')
}

export interface ShadowProbe {
  enabled: boolean
  /** ⚠️ 逐字保留开关原文（支持 `"*"` / `a*` / 数组）—— 判据见 `sessionAllowsProbe()`。 */
  session: ProbeSessionSpec
  maxPerSession: number
  timeoutMs: number
  topN: number
}

/** 读影子开关（**每次调用** · 缺失/非法/未启用 ⇒ `null` ⇒ 完全透明）。 */

export function readShadowProbe(): ShadowProbe | null {
  let raw: string
  try {
    raw = readFileSync(shadowProbeFile(), 'utf8')
  } catch {
    return null
  }
  try {
    const o = JSON.parse(raw) as Record<string, unknown>
    if (o.enabled !== true) return null
    if (parseProbeSessions(o.session) === null) return null
    return {
      enabled: true,
      session: o.session as ProbeSessionSpec,
      maxPerSession: typeof o.maxPerSession === 'number' ? o.maxPerSession : 4,
      timeoutMs: typeof o.timeoutMs === 'number' ? o.timeoutMs : 4_000,
      topN: typeof o.topN === 'number' ? o.topN : 3,
    }
  } catch {
    return null
  }
}

/** **A 组查询**：只用现有工作上下文（意图 / 计划 / 环境 / 最近活动）—— 🔴 不含任务卡正文。 */

export function stage4ProbeFile(): string {
  return process.env.AIOS_STAGE4_PROBE || resolveStateFile('stage4_probe.json', '_stage4_probe.json')
}

export interface Stage4Probe {
  enabled: boolean
  /** ⚠️ 逐字保留开关原文（支持 `"*"` / `a*` / 数组）—— 判据见 `sessionAllowsProbe()`。 */
  session: ProbeSessionSpec
  maxPerSession: number
  timeoutMs: number
  maxCandidates: number
  maxPerSource: number
  /** `delivery: "deliver"` ⇒ 候选渲染后**交给宿主**（第③段）；否则只落探针。 */
  deliver: boolean
}

/** 读阶段 4 开关（**每次调用** · 缺失 / 非法 / 未启用 ⇒ `null` ⇒ 完全透明）。 */

export function readStage4Probe(): Stage4Probe | null {
  let raw: string
  try {
    raw = readFileSync(stage4ProbeFile(), 'utf8')
  } catch {
    return null
  }
  try {
    const o = JSON.parse(raw) as Record<string, unknown>
    if (o.enabled !== true) return null
    if (parseProbeSessions(o.session) === null) return null
    return {
      enabled: true,
      session: o.session as ProbeSessionSpec,
      maxPerSession: typeof o.maxPerSession === 'number' ? o.maxPerSession : 3,
      timeoutMs: typeof o.timeoutMs === 'number' ? o.timeoutMs : 8_000,
      maxCandidates: typeof o.maxCandidates === 'number' ? o.maxCandidates : 8,
      maxPerSource: typeof o.maxPerSource === 'number' ? o.maxPerSource : 3,
      deliver: o.delivery === 'deliver',
    }
  } catch {
    return null
  }
}

/**
 * 领域类别 → 能力角色（**显式映射** · 无映射 ⇒ **不提供**该字段 · ⛔ 不做"猜语义"）。
 * 依据 `RETRIEVAL-INTERFACE-DESIGN.md §2.1`（`work_type` / `action` ⇒ `role` 通道）。
 */

export function reminderProbeFile(): string {
  return process.env.AIOS_REMINDER_PROBE || resolveStateFile('reminder_probe.json', '_reminder_probe.json')
}

export interface ReminderProbe {
  enabled: boolean
  /** ⚠️ 逐字保留开关原文（支持 `"*"` / `a*` / 数组）—— 判据见 `sessionAllowsProbe()`。 */
  session: ProbeSessionSpec
}

/** 读提醒开关（**每次调用** · 缺失 / 非法 / 未启用 ⇒ `null` ⇒ 完全透明）。 */

export function readReminderProbe(): ReminderProbe | null {
  let raw: string
  try {
    raw = readFileSync(reminderProbeFile(), 'utf8')
  } catch {
    return null
  }
  try {
    const o = JSON.parse(raw) as Record<string, unknown>
    if (o.enabled !== true) return null
    if (parseProbeSessions(o.session) === null) return null
    return { enabled: true, session: o.session as ProbeSessionSpec }
  } catch {
    return null
  }
}

// ── 🔴 **实验**：「每轮都出现的用户消息」能否压住注意力（提出并授权试）──
//   假设「之前漏报 = 工具 schema 常驻被**用户消息**压住」⇒ 那让 Runtime 也发**用户消息**、
//     而且**每轮都出现**，看能不能把使用率拉起来。
//   ⚠️ 事实校正（本文件已核实）：提醒原本就是 `role:'user'`（`userMessageOf()`）⇒ 本实验唯一变量 = **频次**。
//   成本（估算）：一条约 200 字/轮 · 10 轮 ≈ 2k 字；对比每步注入 ≈ 20–30k 字 ⇒ 默认 `per:"turn"`。
//   🔴 判据（**可证伪**）：注入后到下一次 `auto_capability` 的间隔 —— 若"每轮注入 + 仍长期不报"
//     ⇒ 假设不成立（不是"被压住"，是"不需要/不划算"）⇒ 应转 ** 代报**（Runtime 用卡 Goal 兜底）。
//   ⛔ 边界：只注入文本 · ⛔ 不代替宿主动作 · ⛔ 不改卡 · ⛔ 不注入候选 · 改开关文件即生效（**不需重启**）。

export interface InjectProbe {
  enabled: boolean
  session: ProbeSessionSpec
  /** `turn` = 每轮最多一条（默认 · 成本可控）· `step` = 每次工具调用后一条（"一直出现"最强形态） */
  per: 'turn' | 'step'
  maxPerSession: number
  /** 是否也向**子 agent**（`identity==='subagent'`）注入事件提示（缺省 false ⇒ 只发主会话）。 */
  allowSubagent: boolean
}

export function injectProbeFile(): string {
  return process.env.AIOS_INJECT_PROBE || resolveStateFile('inject_probe.json', '_inject_probe.json')
}

/** 🔴 （审计）：开关文件**解析结果缓存**（按 mtime+size 失效）。
 *   背景：`readInjectProbe()` 在**每一步** `pre-execute` 被调用 ⇒ 每步一次读盘 + JSON.parse；
 *   长会话 / 高频工具调用下有可感知 IO 抖动。开关「改即生效」语义必须保 ⇒ 每次仍 `stat`，
 *   只省掉「没变时的读盘 + 解析」。 */

export function readInjectProbe(): InjectProbe | null {
  return readSwitchCached<InjectProbe | null>(injectProbeFile(), (raw) => {
    try {
      const o = JSON.parse(raw) as Record<string, unknown>
      if (o.enabled !== true) return null
      if (parseProbeSessions(o.session) === null) return null
      const per: 'turn' | 'step' = o.per === 'step' ? 'step' : 'turn'
      const max = typeof o.maxPerSession === 'number' && Number.isFinite(o.maxPerSession) && o.maxPerSession > 0
        ? Math.floor(o.maxPerSession) : 20
      // 子会话默认**也**投递（`allowSubagent` 缺省 = 开）：子 agent 承担真实工作时，
      // 关掉会让最重的工作落在注入盲区（读数 14 个子会话 13 个零注入）。
      // 想只给主会话投递 ⇒ 显式写 `"allowSubagent": false`。
      const allowSubagent = o.allowSubagent !== false
      return { enabled: true, session: o.session as ProbeSessionSpec, per, maxPerSession: max, allowSubagent }
    } catch {
      return null
    }
  }, null)
}

// ── 🔴 注入改「事件驱动」—— 删 频次闸 + 阶段状态机 ─────────────
//   为什么换（读数依据 · 单会话）： 用「伪阶段」当状态 —— 输入只是**最后一条用户消息**
//     的词面（`wc.intentText`），叠加 `has-edit`（**最近 6 步**滚动窗口 · `PROGRESS_WINDOW`）。
//     `starting` 判据含「`cardEdits>0 && !has-edit`」、`implementing` = `has-edit`
//     ⇒ 卡操作与文件编辑交替时，两态**每步来回跳**；catalog 式节流只挡「同 key 连发」，
//     挡不住「key 交替」⇒ 同一句话反复注入（读数 18 次 / 会话）。
//   ⇒ 新口径：**只发离散事实事件**（**边沿触发** · 每会话每事件最多一次），⛔ 不再推断阶段。
//     依据：Runtime = 机械控制面⇒ 只出可核实事实，不做语义。
//   可证伪判据：交替 20 步（edit → read×7 → edit …）⇒ 注入 ≤ 2 次（旧实现 18 次）。

export function deliverySourcesActive(probe: DeliveryProbe | null, remind: ReminderProbe | null,
                               hasQueued: boolean): boolean {
  return probe !== null || remind !== null || hasQueued
}

/**
 * 阶段 4 第①＋②段：**焦点卡 → 焦点对象 → 最小请求 → Retrieval → 回收候选**。
 * 第③段（递送）：候选渲染后存入 `pendingDelivery`，由**下一次** `post-execute` 带出；
 * `delivery` 开关关闭时只落探针（宿主上下文零变化）。
 */
/**
 * 🔴 · **stage4 开关**（裁定「关掉」）。
 *    起真正出结果的路 = `auto_capability` 内联检索；stage4 自 10-19 起 9 天 0 次成功。
 *   ⇒ 停派发，但**保留代码可回退**（把常量改 true 即可）。
 */
