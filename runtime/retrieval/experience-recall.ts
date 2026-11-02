/** experience-recall.ts —— 由 `runtime/aios-activation.ts` 拆出（纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { aiosStateDir, resolveToolScript } from './../diagnostics/probe.ts'

export const EXPERIENCE_RECALL_ENTRY = resolveToolScript('experience_push.py')

export const EXPERIENCE_RECALL_TIMEOUT_MS = 2000

export const EXPERIENCE_RECALL_MAX_PER_SESSION = 3

export const EXPERIENCE_RECALL_MIN_TURN_GAP = 2

/** 注入段（Step B′）失败探针的去重键 `session|where` —— 每会话每处最多一条。
 *  教训：一个注入源异常 ⇒ 整段（event-hint / reminder / R3 维护清单 / 候选）被 catch 静默吞掉，
 *  且**探针 0 条** ⇒ 失败不可见、只能靠"对比两次失败"才看出来。⇒ catch 里落一条 `ev=delivery-error`。 */

export interface ExperienceRecallSlot { count: number; lastTurn: number; lastQuery: string }

export const EXPERIENCE_RECALL = new Map<string, ExperienceRecallSlot>()

/**  开关：**默认关** · `.aios/experience_recall.json` 的 `{"enabled":true}` 才开（改即生效）。
 *  `AIOS_EXPERIENCE_RECALL=off` 强制关（测试隔离）。裁决：注入型默认关、验收时手动开。 */

export function experienceRecallEnabled(): boolean {
  if (process.env.AIOS_EXPERIENCE_RECALL === 'off') return false
  try {
    const p = join(aiosStateDir(), 'experience_recall.json')
    if (!existsSync(p)) return false
    const j = JSON.parse(readFileSync(p, 'utf8'))
    return j !== null && j !== undefined && j.enabled === true
  } catch {
    return false
  }
}

export function emptyRecallSlot(): ExperienceRecallSlot {
  return { count: 0, lastTurn: -1, lastQuery: '' }
}

/** 取结果文本（只用于**分类与查询词**，⛔ 不回显进注入内容）。 */

export function recallAllowed(slot: ExperienceRecallSlot | undefined, turn: number, query: string): boolean {
  if (query === '') return false
  if (slot === undefined) return true
  if (slot.count >= EXPERIENCE_RECALL_MAX_PER_SESSION) return false
  if (slot.lastTurn >= 0 && turn - slot.lastTurn < EXPERIENCE_RECALL_MIN_TURN_GAP) return false
  if (query === slot.lastQuery && turn === slot.lastTurn) return false
  return true
}

/** 纯函数：把 experience_push 的 JSON 渲染成**一句注入**（≤2 条 · ⛔ 不贴全文）。 */
