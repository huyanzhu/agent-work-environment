/** r3-wake.ts —— 由 `runtime/aios-activation.ts` 拆出（纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */
import { readFileSync, renameSync, rmSync, statSync, watch, writeFileSync } from 'node:fs'



import { join } from 'node:path'
import type { TaskCursor } from './../session/session-state.ts'
import { CARDS_DIR } from './../diagnostics/probe.ts'
import type { WorkReportRecord } from './../diagnostics/probe.ts'
import { CARD_NAME_RE, CATCH_FAIL_SEEN, OBS, SWITCH_CACHE, WORK_REPORTS, aiosStateDir, clip, emit, mono, name, noteCatchFail, readSwitchCached, readTail, switchNeedsReload, userMessageOf } from './../diagnostics/probe.ts'
import type { SessionState } from './../session/session-state.ts'
import { identityOf } from './../session/session-state.ts'
import { myOccupiedCards, focusCardOf, listCardFiles, reminderFor } from './../session/lifecycle.ts'

export const MAINT_MAX_PER_SESSION = 3

export const MAINT_STATE = new Map<string, { owned: Set<string>; count: number }>()

/** 探针文件体积（MB · 派生量，只用于维护清单里的一句提示）。 */

export function probeSizeMb(): number {
  try {
    const p = join(aiosStateDir(), '_aios-activation.probe.log')
    return Math.round((statSync(p).size / (1024 * 1024)) * 10) / 10
  } catch {
    return 0
  }
}

/**
 * **R3 维护清单**（卡释放后注入一次 · 每会话一次）。
 * 判据：本会话**曾占用**某卡、现在 `myOccupiedCards` 为空 ⇒ 视为已释放。
 * 🔴 修（**读数驱动** · 上一版恒不触发）：**不能用 `s.cards`**。
 *    `s.cards` 只在 `agent/pre-step` 且 **`msgs>0`**（新用户回合第一步）时重扫 ——
 *    同回合的后续 step 直接 `return next()`（`pre-step` 早退）。
 *    ⇒ **同一回合内的 claim → release 对 R3 完全不可见**：基线永远空、`released` 永远空
 *      （读数：release 后 `ev=maintenance` 恒为 0）。
 *    ⇒ 改为**现扫卡**（只读）。成本 = 一次全卡扫描（~27 张 × head 8KB），
 *      且 `remind` 开关开启时每工具调用一次；只在维护判断需要时发生，可接受。
 *    ⚠️ 同一根因也影响**焦点卡**（`focusCardOf` 读 `s.cards`）⇒ 同回合 claim 后 stage4 会 `no-focus-card`。
 *      那属于另一处设计约束（每步重扫的成本权衡），**不修**，只登记。
 * @param cardsOverride 仅供**隔离自测**注入卡列表（⛔ 生产不传：传了就绕过现扫）
 * ⛔ 只生成文本；⛔ 不写文件 / 不改卡 / 不碰家底本（执行者永远是 Agent）。
 */

export const R3_WAKE_DEBOUNCE_MS = 2000

export const R3_WAKE_WINDOW_MS = 30 * 60 * 1000

export const R3_WAKE_POLL_MS = 15000

export const R3_MAX_PER_SESSION = 1

export function r3WakePath(): string { return join(aiosStateDir(), 'r3-wake.json') }

export function r3WakeStatePath(): string { return join(aiosStateDir(), 'r3-wake-state.json') }

/** 开关：`enabled` 必须**严格 true**；缺失/非法 ⇒ 关（fail-closed）。
 *  🔴 读数坑：中文 Windows 手写 / `Set-Content` 写的 JSON 常带 **UTF-8 BOM**
 *    ⇒ `JSON.parse` 直接抛 ⇒ 开关"看起来开了实际是关"，且**无任何报错**。⇒ 读侧先剥 BOM。 */

export function r3WakeEnabled(): boolean {
  return readSwitchCached<boolean>(r3WakePath(), (raw) => {
    try {
      const o = JSON.parse(raw.replace(/^\uFEFF/, ''))
      return o !== null && typeof o === 'object' && (o as Record<string, unknown>).enabled === true
    } catch {
      return false
    }
  }, false)
}

/** 每会话唤醒计数（持久 · 跨重启不重复唤醒）。 */

export function loadR3WakeState(): Record<string, number> {
  try {
    const raw = JSON.parse(readFileSync(r3WakeStatePath(), 'utf8'))
    return raw !== null && typeof raw === 'object' ? raw as Record<string, number> : {}
  } catch {
    return {}
  }
}

export function saveR3WakeState(state: Record<string, number>): void {
  try {
    writeFileSync(r3WakeStatePath(), JSON.stringify(state), 'utf8')
  } catch (err) {
    noteCatchFail('state:r3state', err)
    /* 状态写失败 ⇒ 下次可能重复唤醒（探针可见）；⛔ 不影响宿主 */
  }
}

export interface R3Takeover { card: string; victim: string; occupant: string }

/** `.log` 尾部 → 最近一次 takeover（纯函数 · 供自测）。 */

export function takeoverFromLog(raw: string): R3Takeover | null {
  if (!raw) return null
  const rows: { op: string; session: string; rest: string }[] = []
  const re = /\|\s*(claim 占用|release 释放)（session:\s*([^）]*)）([^\n]*)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(raw)) !== null) {
    rows.push({ op: m[1].startsWith('claim') ? 'claim' : 'release', session: String(m[2] || '').trim(), rest: m[3] || '' })
  }
  if (rows.length < 2) return null
  const last = rows[rows.length - 1]
  const prev = rows[rows.length - 2]
  if (last.op !== 'claim' || prev.op !== 'release') return null
  const tm = /takeover from\s+([^\s·|]+)/.exec(prev.rest)
  if (tm === null) return null
  const victim = String(tm[1] || '').trim()
  if (victim === '' || last.session === '' || victim === last.session) return null
  return { card: '', victim, occupant: last.session }
}

/** 扫卡目录 → 最近窗口（mtime）内的 takeover 事件（file truth）。 */

export function scanTakeovers(nowMs: number): R3Takeover[] {
  const out: R3Takeover[] = []
  for (const p of listCardFiles(CARDS_DIR)) {
    try {
      const logPath = p.toLowerCase().endsWith('.md') ? p.slice(0, -3) + '.log' : p + '.log'
      if (nowMs - statSync(logPath).mtimeMs > R3_WAKE_WINDOW_MS) continue
      const t = takeoverFromLog(readTail(logPath))
      if (t === null) continue
      out.push({ card: p.slice(CARDS_DIR.length + 1).replace(/\.md$/, ''), victim: t.victim, occupant: t.occupant })
    } catch (err) {
      noteCatchFail('state:scan', err)
      /* 无 .log / 读失败 ⇒ 跳过 */
    }
  }
  return out
}

/** R3 唤醒正文（六项维护清单 · 与 hook / checklist 同一套口径）。 */

export function r3WakeText(card: string): string {
  return '【AI-OS · R3 收工维护（卡被 takeover）】卡 `' + card + '` 已被**别的会话占用**。'
    + '请逐条过一遍（Runtime 只提醒，⛔ 不自动改任何东西）：\n'
    + '1. INVENTORY：本次造出"别的对话会用到"的东西了吗？没登记就补一行（只给指针）。\n'
    + '2. ENV：机器 / 账号能力面有变化吗？（模型 / API / 工具版本 / 权限）\n'
    + '3. PITFALLS：这次踩到会再咬人的坑了吗？（现象 · 触发条件 · 处置）\n'
    + '4. 卡：State / Event Log / Next Action 是否是**当前**实况？\n'
    + '5. 探针体积：`.aios` 探针约 ' + String(probeSizeMb()) + ' MB（阈值待定）。\n'
    + '6. tests：`node runtime/tests/activation.test.mjs` 是否绿（已知红 1 = S37）。\n'
    + '维护完再开新工作（本提示来自 `.aios/r3-wake.json` 已开启的 R3 真唤醒）。'
}

/** 🔴 `.log` → **前一个「不同会话」的占用者**（纯函数 · 供自测）。
 *  用途：claim 成功后向前手注入「接手检查」。⛔ **同一会话重占**（A claim → … → A claim）不注入 ——
 *  所以取法 = 从尾部往前找**最后一条 claim 且 session ≠ 当前会话**；找不到 ⇒ null。
 *  与 `takeoverFromLog` 的判据同源（`| HH:mm | <State> | claim 占用（session: X） |`），但更宽松：
 *  不要求中间有 release/takeover（正常「前手 release → 本会话 claim」也注入）。 */

export function r3HandoffText(card: string): string {
  return '【AI-OS · R3 接手检查（卡被新会话占用）】你上一手占用的卡 `' + card + '` 已被**另一个会话** claim 接手。'
    + '请核对并维护（Runtime 只提醒，⛔ 不自动改任何东西）：\n'
    + '· 卡：State / Event Log 尾部 / Current Step / Next Action 是否是**当前**实况？\n'
    + '· 未写回产出：本次做的东西是否已写回（产物路径 / 结论 / 指针）？\n'
    + '· 维护清单：① INVENTORY 新东西登记了吗 ② ENV 有变化吗 ③ PITFALLS 有新坑吗 ④ 卡状态 ⑤ 探针体积 ⑥ tests 绿吗。\n'
    + '维护完再开新工作（本提示来自 `.aios/r3-wake.json` 已开启的 R3 接手检查）。'
}

/** 🔴 **fire-once 关闭告知**的待注入标记 ——
 *   成功向前手注入一次后自动 disarm（与 同语义），等本次 post-execute 的 Step B′ 段
 *  向**触发会话**（接手方 b）投一条「已关闭，请询问用户是否开启」。 */

export function disarmR3Wake(): boolean {
  const file = r3WakePath()
  try {
    let cur: Record<string, unknown> = {}
    try {
      const parsed = JSON.parse(readFileSync(file, 'utf8').replace(/^\uFEFF/, '')) as unknown
      if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
        cur = parsed as Record<string, unknown>
      }
    } catch { cur = {} }
    const next = { ...cur, enabled: false }
    const tmp = file + '.tmp-' + process.pid + '-' + Math.random().toString(36).slice(2, 8)
    try {
      writeFileSync(tmp, JSON.stringify(next) + '\n', 'utf8')
      renameSync(tmp, file)
    } catch (err) {
      try { rmSync(tmp, { force: true }) } catch { /* 静默 */ }
      throw err
    }
    emit({
      ev: 'r3-wake', obs: OBS, state: 'disarmed',
      note: 'fire-once: 成功唤醒一个会话 ⇒ 开关写回默认关（enabled:false），⛔ 需再次使用时请与用户确认后手动打开',
      at: Date.now(), mono: mono(),
    })
    return true
  } catch (err) {
    emit({ ev: 'r3-wake', obs: OBS, state: 'disarm-failed', detail: clip(String(err), 120), at: Date.now(), mono: mono() })
    return false
  }
}

/** 一次唤醒周期：只对被 takeover 且未唤醒过的会话 followup。 */

export function r3WakeCycle(ctx: any): void {
  let enabled = false
  try { enabled = r3WakeEnabled() } catch { enabled = false }
  if (!enabled) return
  let takeovers: R3Takeover[] = []
  try { takeovers = scanTakeovers(Date.now()) } catch { return }
  if (takeovers.length === 0) return
  const state = loadR3WakeState()
  let agents: any
  try { agents = ctx.get('agents') } catch { agents = undefined }
  for (const t of takeovers) {
    if ((state[t.victim] || 0) >= R3_MAX_PER_SESSION) continue
    const agent = agents !== undefined && agents !== null && typeof agents.get === 'function' ? agents.get(t.victim) : undefined
    if (agent === undefined || agent === null || typeof agent.followup !== 'function') {
      // 🔴 记一次状态：否则 15s 轮询会**每轮重复**记 `no-agent`（读数 30 分钟窗口会产生上百条）。
      //    victim 之后若变 live，由 hook 版 R3（UserPromptSubmit / SessionStart）兜底提醒。
      state[t.victim] = 1
      emit({ ev: 'r3-wake', obs: OBS, state: 'no-agent', card: t.card, victimSession: t.victim, at: Date.now(), mono: mono() })
      continue
    }
    try {
      agent.followup(userMessageOf(r3WakeText(t.card), 'aios R3 wake (takeover)'))
      state[t.victim] = 1
      // 🔴 （B 方案）：唤醒即视为「该会话已收到这张卡的清单」⇒ 同步 Runtime 幂等基线，
      //   否则该会话下一次 post-execute 的 清单会对**同一张卡**再出一次（跨源重复的另一半）。
      try {
        const prev = MAINT_STATE.get(t.victim)
        if (prev === undefined) {
          MAINT_STATE.set(t.victim, { owned: new Set<string>(), count: 1 })
        } else {
          prev.owned.delete(t.card)
          prev.count = Math.min(prev.count + 1, MAINT_MAX_PER_SESSION)
        }
      } catch { /* 静默：幂等基线同步失败不影响唤醒本身 */ }
      emit({ ev: 'r3-wake', obs: OBS, state: 'ok', card: t.card, victimSession: t.victim, at: Date.now(), mono: mono() })
      // fire-once —— 成功注入一次即把开关写回默认关（见 `disarmR3Wake()` 注释），
      //   然后 `break`：不再唤醒其它受害会话（一次性触发器语义）。
      disarmR3Wake()
      break
    } catch (err) {
      emit({ ev: 'r3-wake', obs: OBS, state: 'failed', card: t.card, victimSession: t.victim, detail: clip(String(err), 120), at: Date.now(), mono: mono() })
    }
  }
  saveR3WakeState(state)
}

/**
 * 安装卡目录监听（watcher 一直在；**是否唤醒由开关决定** ⇒ 开关可运行期改，改即生效）。
 * 防抖 2s（一次 takeover 会写卡 + `.log` 两处）· 启动 5s 后补扫 · dispose 时清理。
 */

export function installR3Wake(ctx: any): void {
  // ⛔ 隔离/自测模式（`AIOS_CARDS_DIR` 指向临时卡树）**不装 watcher**：
  //    防止测试进程被 `fs.watch` 挂住（事件循环不退出），且测试纪律要求不监听真实卡目录。
  if (process.env.AIOS_CARDS_DIR) return
  let timer: any = null
  ctx.effect(() => {
    let watcher: any = null
    try {
      watcher = watch(CARDS_DIR, { recursive: true }, (eventType: string, filename: any) => {
        // 轻量事件探针（量小）：用来区分「watcher 没装上」与「装上了但事件没来」。
        emit({ ev: 'r3-wake', obs: OBS, state: 'watch-event', event: String(eventType || ''), file: String(filename || ''), at: Date.now(), mono: mono() })
        if (timer !== null) return
        timer = setTimeout(() => {
          timer = null
          try { r3WakeCycle(ctx) } catch { /* 静默：⛔ 不影响宿主 */ }
        }, R3_WAKE_DEBOUNCE_MS)
      })
      emit({ ev: 'r3-wake', obs: OBS, state: 'installed', cardsDir: CARDS_DIR, at: Date.now(), mono: mono() })
    } catch (err) {
      emit({ ev: 'r3-wake', obs: OBS, state: 'watch-failed', detail: clip(String(err), 160), at: Date.now(), mono: mono() })
    }
    // 🔴 兜底轮询（15s）：`fs.watch` 在部分宿主/沙箱下可能**建得成功但事件不来**
    //    （实机：watch 无报错、`installed` 需要探针才能确认，文件改动没触发回调）。
    //    ⇒ 真唤醒不能只押在 watch 上；轮询保证"最迟 15s 内出现"。
    //    未开开关时 `r3WakeCycle` 只读一个小 JSON 就早退（成本可忽略）。
    const poll = setInterval(() => { try { r3WakeCycle(ctx) } catch { /* 静默 */ } }, R3_WAKE_POLL_MS)
    const boot = setTimeout(() => { try { r3WakeCycle(ctx) } catch { /* 静默 */ } }, 5000)
    return () => {
      if (watcher !== null) { try { watcher.close() } catch { /* 静默 */ } }
      clearInterval(poll)
      clearTimeout(boot)
      if (timer !== null) { clearTimeout(timer); timer = null }
    }
  }, 'aios-activation: r3-wake')
}

/**
 * 候选 ⇒ **模型可见文本**（第③段递送内容）。
 * 🔴 纪律（与 Hook 侧 `field_candidates` 同源要求）：
 *   · **含身份与来源**（候选 id 是仓库相对路径）· ⛔ **不含推理原文** · ⛔ **不裁决适用性**
 *   · 只取 Top-N · 显式声明"是候选不是建议" · 长度有界（§四十四 J3：≤400 字符量级）
 */

// ── 由 `aios-activation.ts` 迁入（R2 类型接线）──
