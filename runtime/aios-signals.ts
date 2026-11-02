/**
 * aios-signals.ts — AI-OS v2 / · T1/T2 信号观察（**observe-only**）
 * ── 授权（「确认实施 · 按修订清单执行」）──────────────────────
 *   ① 新增本文件 + `cordis.patch.yml` **唯一**挂载项
 *   ② 只读订阅：`tools/pre-execute` · `tools/post-execute` · `agent/assistant-stream`
 *      · `agent/pre-step`（因现有观测不足以做时序关联 ⇒ 按授权「否则就加入本文件」）
 *   ③ 保留子会话 fail-closed；**不执行任何注入或发现 Action**
 *   ④ 完成后只交付四类证据（加载 / 时序 / 身份 / 透明性），**不进入阶段 4**
 * ── 本文件回答的问题（原话）──────────────────────────────────────────────────
 *   「本机 DSH 能否在**不读取隐藏思维链**的前提下，稳定识别出有价值的任务方向信号，
 *     并在**下一个适当的模型步骤之前**递送上下文？」
 *   ⇒ 为此必须同时留下两类时点：T2（`tool-call-delta` / `tools/pre-execute`）
 *     与后续模型步骤（`agent/pre-step`），并用**单调时钟**关联。
 * ── 🔴 隐私边界（硬 · 不得放宽）──────────────────────────────────────────────
 *   ✅ 可记：完整工具名 · **脱敏后**的路径/参数摘要 · 事件时序 · 身份字段 · turn/step · isError/耗时
 *   🔴 禁记：`StreamChunk.type === 'reasoning-delta'`（隐藏推理）—— **显式丢弃，不读其 text**
 *   🔴 禁记：`text-delta` 内容 · `argumentsDelta`（流式参数片段）
 *   🔴 禁记：`command` 原文（开头就可能含凭证/私有路径/用户数据）
 *            ⇒ 只记**可执行程序名 + 参数个数**，默认不记任何参数原文
 *   依据：`AUTOMATION-BOUNDARY.md §15.2` 的隐私边界 + 修订清单第 2 条
 * ── 三条实现约束（勿删）──────────────────────────────────────────────────────
 *   ⚠️ 1. 零外部包 import —— 只用 `node:` 内置模块（插件位于仓库根，
 *         裸包名解析不到 DSH 的 node_modules；依据 `vendor/loader/src/config/tree.ts:145-161`）
 *   ⚠️ 2. **waterfall 必须透明**：`next()` **恰好调用一次**，原样返回其结果；
 *         观察失败绝不改变工具行为或错误语义
 *   ⚠️ 3. `agent/assistant-stream` 是**高频**事件：只处理 `start` / `end` / `tool-call-delta`，
 *         其余帧**立即返回**；事件处理器内**不做检索 / 文件扫描 / 任何耗时任务**
 * ── 关联纪律（修订清单第 1 条）─────────────────────────────────────────
 *   只用载荷里**已有**的关联字段（session / turn / step / checkpointId）；缺失记 `unknown`。
 *   **不得**靠日志先后顺序猜出不存在的关联关系。
 */
import { appendFileSync } from 'node:fs'

export const name = 'aios-signals'

/** 无服务依赖 ⇒ 立即 ACTIVE（PENDING 是「插件没有输出」的常见原因）。 */
export const inject: string[] = []

const TAG = '[aios-signals]'
const T0 = Date.now()

/** 临时探针（短期技术记录；观察期结束随原型撤下）。双写互为 fallback。 */
const PROBE_PATHS: string[] = [
  '<repo>/scratch/_aios-signals.probe.log',
  (process.env.USERPROFILE || '<user>') + '/.dsh/_aios-signals.probe.log',
]

/** 工作区基准（仅用于把 file_path 转成相对路径；拿不到就按"工作区外"处理）。 */
const FALLBACK_CWD = '<repo>'
/** 未完成工具调用的开始时刻（仅内存 · 用于算耗时 · 不持久化）。 */
const CALL_START = new Map<string, bigint>()
const CALL_START_MAX = 512
/** 已记录过的流式工具调用（**去重**：读数一次调用会流式产生数百条 `tool-call-delta`）。 */
const SEEN_TOOLCALL = new Set<string>()
const TOOLCALL_MAX = 512

// ── 探针输出 ────────────────────────────────────────────────────────────────

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
    /* 静默 */
  }
  for (const path of PROBE_PATHS) {
    try {
      appendFileSync(path, line + '\n')
    } catch {
      /* 静默：探针不可写不得影响宿主 */
    }
  }
}

/** **单调时钟**（纳秒字符串）：跨事件间隔计算用，不受系统时间调整影响。 */
function mono(): string {
  try {
    return process.hrtime.bigint().toString()
  } catch {
    return 'unknown'
  }
}

function unknownIfMissing(v: unknown): unknown {
  return v === undefined || v === null ? 'unknown' : v
}

// ── 身份 / 关联字段（判据与阶段 1/2 **同源**）────────────────────────────────

type Identity = 'main' | 'subagent' | 'unknown'

function identityOf(agent: any): { identity: Identity; basis: string } {
  const h = agent && agent.session && agent.session.header
  if (!h) return { identity: 'unknown', basis: 'no session header' }
  if (h.origin === 'subagent') return { identity: 'subagent', basis: 'origin=subagent' }
  if (typeof h.delegationDepth === 'number' && h.delegationDepth > 0) {
    return { identity: 'subagent', basis: 'delegationDepth=' + String(h.delegationDepth) }
  }
  if (h.parentSession !== undefined) return { identity: 'subagent', basis: 'parentSession set' }
  return { identity: 'main', basis: 'depth=' + String(h.delegationDepth) + ' origin=<absent>' }
}

function sessionOf(agent: any): string {
  const h = agent && agent.session && agent.session.header
  return h && h.id !== undefined ? String(h.id) : 'unknown'
}

function cwdOf(agent: any): string {
  const h = agent && agent.session && agent.session.header
  return h && typeof h.cwd === 'string' && h.cwd ? h.cwd : FALLBACK_CWD
}

/** 公共关联字段。缺失一律 `unknown` —— **不靠日志顺序猜关联**。 */
function ctxFields(agent: any, turn: unknown, step: unknown): Record<string, unknown> {
  const id = identityOf(agent)
  return {
    mono: mono(),
    at: Date.now(),
    session: sessionOf(agent),
    identity: id.identity,
    turn: unknownIfMissing(turn),
    step: unknownIfMissing(step),
  }
}

// ── 参数脱敏（修订清单第 2 条）────────────────────────────────────────

const PATH_KEYS = ['file_path', 'filePath', 'path', 'notebook_path', 'directory']
const PATTERN_KEYS = ['pattern', 'query', 'glob', 'regex']

/** 路径 → 工作区内相对路径；工作区外只记「类别 + 扩展名」。 */
function safePath(raw: unknown, cwd: string): Record<string, unknown> {
  if (typeof raw !== 'string' || !raw) return { target: 'unknown', outside: 'unknown' }
  const norm = raw.replace(/\\/g, '/')
  const base = (cwd || '').replace(/\\/g, '/').replace(/\/+$/, '')
  if (base && (norm === base || norm.toLowerCase().startsWith(base.toLowerCase() + '/'))) {
    return { target: norm === base ? '.' : norm.slice(base.length + 1), outside: false }
  }
  const ext = (norm.match(/\.[A-Za-z0-9]{1,8}$/) || [''])[0]
  return { target: '<outside-workspace>' + ext, outside: true }
}

/**
 * 参数摘要 —— **只记安全类别，不记原文**。
 *   path 类    ⇒ 相对路径（工作区外仅类别）
 *   pattern 类 ⇒ **只记长度**，不记内容（无法确认安全）
 *   command 类 ⇒ **只记可执行程序名 + 参数个数**，默认不记任何参数原文
 *   其余       ⇒ 只记键的数量
 */
function summarizeArgs(args: unknown, cwd: string): Record<string, unknown> {
  if (!args || typeof args !== 'object') return { argKind: 'none' }
  const a = args as Record<string, unknown>

  const pathKey = PATH_KEYS.find(k => typeof a[k] === 'string')
  if (pathKey !== undefined) return { argKind: 'path', argKey: pathKey, ...safePath(a[pathKey], cwd) }

  const patKey = PATTERN_KEYS.find(k => typeof a[k] === 'string')
  if (patKey !== undefined) {
    const s = String(a[patKey])
    return { argKind: 'pattern', argKey: patKey, argLen: s.length } // 只记长度
  }

  if (typeof a.command === 'string') {
    const parts = String(a.command).trim().split(/\s+/)
    const first = parts[0] || ''
    // ⚠️ 只有**形如程序名**的首 token 才记录（≥2 字符、字母开头）；
    //    否则记 unknown —— 读数：脚本型工具的首 token 可能是 `f` 这类无意义片段，
    //    既无信息量也不该被当成"可识别程序"。**不记参数个数、不记原文**。
    const exe = /^[A-Za-z][A-Za-z0-9._-]{1,31}$/.test(first) ? first : 'unknown'
    return { argKind: 'command', exe }
  }

  return { argKind: 'other', argKeys: Object.keys(a).length }
}

// ── 插件入口 ────────────────────────────────────────────────────────────────

/**
 * @param ctx cordis Context（显式 `any`：见文件头约束 1，不用 `import type`）
 */
export function apply(ctx: any): void {
  emit({ ev: 'apply', plugin: name, t: T0, note: 'signals observer' })

  ctx.effect(() => {
    emit({ ev: 'active', plugin: name, note: 'observers attached', at: Date.now() })
    return () => {
      emit({ ev: 'dispose', plugin: name, at: Date.now() })
      CALL_START.clear()
    }
  }, 'aios-signals: lifetime')

  // ── T1/T2 关联锚点：每个模型步骤的时点（**不是** activation 的判定记录）──
  // ⚠️ waterfall ⇒ next() 恰好一次，原样返回。
  ctx.on('agent/pre-step', (payload: any, next: any) => {
    try {
      const p = payload || {}
      emit({
        ev: 'step',
        ...ctxFields(p.agent, p.turn, p.step),
        msgs: Array.isArray(p.messages) ? p.messages.length : 'unknown',
      })
    } catch {
      /* 观察失败绝不影响决策链 */
    }
    return next()
  })

  // ── T2（最强信号）：Agent 准备执行什么工具 ──
  // `exec` = { callId, name, arguments, agent, signal, … }
  ctx.on('tools/pre-execute', (exec: any, next: any) => {
    try {
      const cwd = cwdOf(exec && exec.agent)
      const callId = exec && exec.callId !== undefined ? String(exec.callId) : 'unknown'
      if (CALL_START.size >= CALL_START_MAX) CALL_START.clear()
      CALL_START.set(callId, process.hrtime.bigint())
      emit({
        ev: 'tool-intent',
        ...ctxFields(exec && exec.agent, exec && exec.turn, exec && exec.step),
        tool: exec && exec.name !== undefined ? String(exec.name) : 'unknown',
        callId,
        ...summarizeArgs(exec && exec.arguments, cwd),
      })
    } catch {
      /* 静默 */
    }
    return next() // ⚠️ 恰好一次 · 原样返回
  })

  // ── T2 结果：工具执行情况（含耗时）──
  ctx.on('tools/post-execute', (exec: any, result: any, next: any) => {
    try {
      const callId = exec && exec.callId !== undefined ? String(exec.callId) : 'unknown'
      const started = CALL_START.get(callId)
      let durMs: unknown = 'unknown'
      if (started !== undefined) {
        try {
          durMs = Number(process.hrtime.bigint() - started) / 1e6
          CALL_START.delete(callId)
        } catch {
          durMs = 'unknown'
        }
      }
      emit({
        ev: 'tool-result',
        ...ctxFields(exec && exec.agent, exec && exec.turn, exec && exec.step),
        tool: exec && exec.name !== undefined ? String(exec.name) : 'unknown',
        callId,
        isError: result && typeof result.isError === 'boolean' ? result.isError : 'unknown',
        durMs: typeof durMs === 'number' ? Math.round(durMs) : durMs,
      })
    } catch {
      /* 静默 */
    }
    return next() // ⚠️ 恰好一次 · 原样返回（不改错误语义）
  })

  // ── T2 更早的意图：流式工具调用（**高频 · 只认目标帧**）──
  // ⚠️ 只处理 start / end / tool-call-delta(name)；reasoning-delta 与 text-delta **显式丢弃且不读其内容**。
  ctx.on('agent/assistant-stream', (payload: any) => {
    try {
      const f = payload && payload.frame
      if (!f || typeof f.type !== 'string') return

      if (f.type === 'start') {
        emit({ ev: 'llm-start', ...ctxFields(payload.agent, f.turn, f.step), attemptId: f.attemptId !== undefined ? String(f.attemptId) : 'unknown' })
        return
      }
      if (f.type === 'end') {
        const outcome = f.outcome && f.outcome.kind ? String(f.outcome.kind) : 'unknown'
        emit({ ev: 'llm-end', ...ctxFields(payload.agent, 'unknown', 'unknown'), attemptId: f.attemptId !== undefined ? String(f.attemptId) : 'unknown', outcome })
        return
      }
      if (f.type !== 'chunk') return

      const c = f.chunk
      if (!c || typeof c.type !== 'string') return
      // 🔴 白名单：只认 tool-call-delta 的**工具名**；其余（含 reasoning-delta / text-delta）立即返回
      if (c.type !== 'tool-call-delta') return
      // ⚠️ **必须去重**（读数：一次工具调用会流式产生数百条 tool-call-delta —— 未去重则日志被淹没）
      //    按 (attemptId, 工具调用 id) 取**首次带名字**的那一条；name 未出现时先不记。
      if (c.name === undefined) return
      const key = String(f.attemptId !== undefined ? f.attemptId : '?') + '|' + String(c.id !== undefined ? c.id : '?')
      if (SEEN_TOOLCALL.has(key)) return
      if (SEEN_TOOLCALL.size >= TOOLCALL_MAX) SEEN_TOOLCALL.clear()
      SEEN_TOOLCALL.add(key)
      emit({
        ev: 'tool-call-delta',
        ...ctxFields(payload.agent, 'unknown', 'unknown'),
        tool: String(c.name),
        // ⚠️ 刻意不记录 c.argumentsDelta（流式参数片段）
      })
    } catch {
      /* 静默 */
    }
  })

  // ── 回合边界（已有事件 · 用于时序对照）──
  ctx.on('agent/turn-stopping', (payload: any) => {
    try {
      const p = payload || {}
      emit({ ev: 'turn-stopping', ...ctxFields(p.agent, p.turn, 'unknown') })
    } catch {
      /* 静默 */
    }
  })

  // ── 子会话边界（仅记录 · 不做任何 Action）──
  ctx.on('subagent/start', (info: any) => {
    try {
      emit({ ev: 'subagent-start', at: Date.now(), mono: mono(), id: info && info.id ? String(info.id) : 'unknown', provider: info && info.provider ? String(info.provider) : 'unknown' })
    } catch {
      /* 静默 */
    }
  })
  ctx.on('subagent/end', (info: any) => {
    try {
      emit({ ev: 'subagent-end', at: Date.now(), mono: mono(), id: info && info.id ? String(info.id) : 'unknown' })
    } catch {
      /* 静默 */
    }
  })
}
