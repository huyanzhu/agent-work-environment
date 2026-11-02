/**
 * aios-observe.ts — AI-OS v2 / · 阶段 1「最小 observe-only 原生插件原型」
 * ── 授权（逐字）────────────────────────────────────────────
 *   批准仅实施阶段 1 Observe-only 原型，采用落点 A。
 *   · 新增 `仓库根\runtime\aios-observe.ts`
 *   · 修改 `~/.dsh/profiles/web/cordis.patch.yml`，仅增加此原型所需的挂载配置
 *   · 优先验证 Profile Patch 热加载；若需要重启，不得自行重启，先报告
 *   · 不检索、不注入、不创建状态机、不写任务卡或账本、不修改现有 Hook 与 Python 工具
 *   ⇒ **本授权不等于批准完整 §14.9**，也不批准任何新增持久化状态或真实注入行为。
 * ── 本原型要回答的三个问题 ───────────────────────────────────────────────────
 *   ① 插件加载/卸载 —— `apply` 与 dispose 生命周期；改 Profile 配置后是否真实加载（热加载？）
 *   ② `agent/pre-step` 时机 —— 事件何时到达，是否在模型处理当前输入之前
 *   ③ 会话与回合边界 —— 主/子会话的事件序列有何区别，哪些字段可可靠识别其身份
 * ── 三个刻意为之的实现约束（勿删）────────────────────────────────────────────
 *   ⚠️ 1. **零外部包 import**：本文件位于仓库根（AI-OS 仓库）。插件自身的裸包名
 *         import 会从该位置向上找 node_modules（`仓库根\node_modules` → `D:\node_modules` → ✗），
 *         解析不到 DSH 的 `@deepseek-ai/*` 包。⇒ 一律用显式类型注解，**不用 `import type`**。
 *         唯一例外是 Node **内置**模块（`node:fs`）—— 内置不走 node_modules 解析。
 *         依据：`vendor/loader/src/config/tree.ts:145-161`（本机走 `loader.internal.import`）。
 *   ⚠️ 2. **`agent/pre-step` 必须透明调用 `next()`**：该点是 **waterfall**
 *         （`api-catalog.ts:3094-3099`）。不调 `next()` 会**短路后续监听器** ——
 *         即直接掐断 `hooks-claude-code` 的 UserPromptSubmit 链路。本插件只观察，不改动决策。
 *   ⚠️ 3. **身份判据不推断**：字段缺失一律报 `unknown`，**不得**反推为「主会话」；
 *         `delegationDepth` 缺失同样报 `unknown`，**不得**当成 `0`。（授权明文要求）
 * ── 隐私与事实边界 ───────────────────────────────────────────────────────────
 *   只记元数据（事件名 / 时间 / 身份字段 / 计数 / 关联 id）。
 *   **不记** prompt 正文、消息内容、文件内容、凭证、完整上下文。
 *   不写任务卡 Event Log、不写账本。探针文件只是**短期技术记录**（观察期结束即撤），
 *   **不是事实状态源**，其输出也**不得**被解释为 L3 价值证据。
 */
import { appendFileSync } from 'node:fs' // node 内置 ⇒ 不涉及 node_modules 解析

export const name = 'aios-observe'

/** 无服务依赖：不声明 `inject` ⇒ 立即 ACTIVE（PENDING 是「插件没有输出」的常见原因）。 */
export const inject: string[] = []

const TAG = '[aios-observe]'
const T0 = Date.now()

/**
 * 临时探针通道（**双写互为 fallback**）。运行中实例的 stdout 落在其启动终端里
 * （本机 `~/.dsh` 下无日志文件），为了让观察结果可被读取，额外落盘两份：
 *   ① AI-OS 工作区 scratch —— 便于 AI-OS 侧读取
 *   ② `$DSH_HOME`           —— 不依赖工作区写权限（历史教训：受限 token 写工作区会被拒）
 * 两份都是**短期技术记录**，观察期结束后连同原型一并撤下。
 */
const PROBE_PATHS: string[] = [
  '<repo>/scratch/_aios-observe.probe.log',
  (process.env.USERPROFILE || '<user>') + '/.dsh/_aios-observe.probe.log',
]

/** 只读字段白名单：`subagent/*` 的 info 可能很大，绝不整包 dump。 */
const RUN_INFO_KEYS = ['id', 'runId', 'provider', 'mode', 'kind', 'status', 'outcome', 'agentType']

/**
 * 一行结构化日志（stdout + 临时探针文件）。任何失败都不得抛出：
 * 观察型探针绝不影响宿主。
 */
function emit(fields: Record<string, unknown>): void {
  let line: string
  try {
    line = TAG + ' ' + JSON.stringify(fields)
  } catch {
    return
  }
  try {
    console.log(line)
  } catch {
    /* 静默：日志失败不是宿主的故障 */
  }
  for (const path of PROBE_PATHS) {
    try {
      appendFileSync(path, line + '\n')
    } catch {
      /* 静默：探针不可写不得影响宿主 */
    }
  }
}

/** 会话 id（拿不到就报 unknown，不猜）。 */
function sessionIdOf(agent: any): string {
  const header = agent && agent.session && agent.session.header
  return header && header.id !== undefined ? String(header.id) : 'unknown'
}

/**
 * 主 / 子会话身份三态判据（**正向命中才算，缺失一律 unknown**）。
 *   subagent —— `origin === 'subagent'`，或 `delegationDepth > 0`，或 `parentSession` 存在
 *   main     —— 字段存在且形态为非子会话（**附 basis；尚待本机读数证实**，故同时给出原始字段）
 *   unknown  —— 三个字段全缺（或载荷无 session header）⇒ 明确报未知，**不归类**
 * 依据：`SessionHeader` 定义 `packages/core/session/src/types.ts:93-130`
 *      （`origin?: 'subagent'` :116 · `parentSession?` :106 · `delegationDepth?` :122）；
 *      live agent 暴露 `session`（`packages/core/agent-loop/src/agent.ts:100`）。
 */
function identify(agent: any): Record<string, unknown> {
  const header = agent && agent.session && agent.session.header
  if (!header) return { identity: 'unknown', basis: 'no session header on payload' }

  const origin = header.origin
  const depth = header.delegationDepth
  const parent = header.parentSession

  if (origin === 'subagent') {
    return { identity: 'subagent', basis: 'origin=subagent', origin, depth: depthOf(depth), parent: bool(parent) }
  }
  if (depth !== undefined && depth > 0) {
    return { identity: 'subagent', basis: 'delegationDepth=' + String(depth), origin: originOf(origin), depth, parent: bool(parent) }
  }
  if (parent !== undefined) {
    return { identity: 'subagent', basis: 'parentSession set', origin: originOf(origin), depth: depthOf(depth), parent: true }
  }
  if (origin === undefined && depth === undefined && parent === undefined) {
    return { identity: 'unknown', basis: 'origin/delegationDepth/parentSession all absent' }
  }
  return {
    identity: 'main',
    basis: 'depth=' + String(depth) + ' origin=' + (origin === undefined ? '<absent>' : String(origin)),
    origin: originOf(origin),
    depth: depthOf(depth),
    parent: false,
  }
}

/** 缺失 ⇒ 'unknown'（**不得**写成 0）。 */
function depthOf(v: any): any {
  return v === undefined || v === null ? 'unknown' : v
}
function originOf(v: any): any {
  return v === undefined || v === null ? 'unknown' : v
}
function bool(v: any): boolean {
  return v !== undefined && v !== null
}

function summarizeRunInfo(info: any): Record<string, unknown> | null {
  if (!info || typeof info !== 'object') return null
  const out: Record<string, unknown> = {}
  for (const key of RUN_INFO_KEYS) {
    if (info[key] !== undefined && info[key] !== null) out[key] = String(info[key])
  }
  return out
}

/**
 * 插件入口。只订阅回答三个问题所必需的事件 —— **不订阅**其余扩展点，
 * 尤其不碰 `agent/assistant-stream`（授权明文：过多事件会让日志失去重点）。
 * @param ctx cordis Context（显式 `any`：见文件头约束 1，不用 `import type`）
 */
export function apply(ctx: any): void {
  emit({ ev: 'apply', plugin: name, t: T0 })

  // 加载/卸载的可观测痕迹：effect 主体在加载期运行，返回的 disposer 在卸载期运行。
  ctx.effect(() => {
    emit({ ev: 'active', plugin: name, note: 'loaded; observers attached', at: Date.now() })
    return () => emit({ ev: 'dispose', plugin: name, note: 'unloaded; observers removed', at: Date.now() })
  }, 'aios-observe: lifetime')

  // 问题③ · 会话起点（emit，无 next）。生命周期开始，每个会话一次。
  ctx.on('agent/session-start', (payload: any) => {
    const p = payload || {}
    emit({ ev: 'session-start', session: sessionIdOf(p.agent), source: p.source, ...identify(p.agent), at: Date.now() })
  })

  // 问题② · 模型步骤入口（**waterfall** —— 必须透明传递 next()，见文件头约束 2）。
  ctx.on('agent/pre-step', (payload: any, next: any) => {
    try {
      const p = payload || {}
      emit({
        ev: 'pre-step',
        session: sessionIdOf(p.agent),
        turn: p.turn,
        step: p.step,
        msgs: Array.isArray(p.messages) ? p.messages.length : 'unknown', // 只记条数，不记内容
        ...identify(p.agent),
        at: Date.now(),
      })
    } catch {
      /* 观察失败绝不影响决策链 */
    }
    return next()
  })

  // 问题③ · 回合收尾（serial，无 next；返回 undefined ⇒ 不阻塞、不 steer）。
  ctx.on('agent/turn-stopping', (payload: any) => {
    const p = payload || {}
    emit({ ev: 'turn-stopping', session: sessionIdOf(p.agent), turn: p.turn, ...identify(p.agent), at: Date.now() })
  })

  // 问题③ · 子会话边界（emit）。用于对照主会话的事件序列差异。
  ctx.on('subagent/start', (info: any) => {
    emit({ ev: 'subagent-start', info: summarizeRunInfo(info), at: Date.now() })
  })
  ctx.on('subagent/end', (info: any) => {
    emit({ ev: 'subagent-end', info: summarizeRunInfo(info), at: Date.now() })
  })
}
