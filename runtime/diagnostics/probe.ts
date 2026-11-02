/** probe.ts —— 由 `runtime/aios-activation.ts` 拆出（纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */
import { appendFileSync, closeSync, existsSync, openSync, readFileSync, readSync, statSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

export const AIOS_ROOT: string = (() => {
  const env = process.env.AIOS_ROOT
  if (env && env.trim()) return env.trim().replace(/[/\\]+$/, '')
  // 🔴 本文件已搬到 `runtime/diagnostics/` 下 —— ⛔ 不能再写死「上两层」。
  //   改为**按 marker 向上找根**：同时存在 `runtime/` 与 `task_cards/` 的目录即根。
  //   （读数：写死层数会让 ROOT 偏一层 ⇒ AIOS_ROOT 错 ⇒ 22 项自测 FAIL + capabilities ENOENT）
  try {
    let d = dirname(fileURLToPath(import.meta.url))
    for (let i = 0; i < 6; i++) {
      if (existsSync(join(d, 'runtime')) && existsSync(join(d, 'task_cards'))) return d
      const up = dirname(d)
      if (up === d) break
      d = up
    }
  } catch { /* 落到 cwd 兜底 */ }
  return process.cwd().replace(/[/\\]+$/, '')
})()
/**
 * 运行期实例目录（默认 `<root>/.aios` · 缺失则回退 `<root>/scratch` 的兼容位）。
 * 🔴 修：此前是**模块加载时求值一次**的常量 ⇒ 若插件启动时 `.aios/` 尚不存在
 *    （之后才创建 / 才迁移），本进程会**一直**去 `scratch/` 找开关与探针
 *    ⇒ 与「开关改文件即生效 · **不需要重启**」的承诺直接冲突
 *    （实际表现：把开关放进 `.aios/` 却毫无反应，且**无任何报错**）。
 *    ⇒ 改为**每次调用重算**（`existsSync` 开销可忽略；读取端本就是「每次重读文件」的纪律）。
 * ⚠️ 语义不变：仍是「存在即优先 `.aios/`，否则回退 `scratch/`」—— ⛔ **只读探测，不写不搬**
 *    （迁移由 /Agent 显式执行 · 见 `resolveStateFile()` 注释）。
 */

export function aiosStateDir(): string {
  const env = process.env.AIOS_STATE_DIR
  if (env && env.trim()) return env.trim().replace(/[/\\]+$/, '')
  const preferred = join(AIOS_ROOT, '.aios')
  try {
    return existsSync(preferred) ? preferred : join(AIOS_ROOT, 'scratch')
  } catch {
    return join(AIOS_ROOT, 'scratch')
  }
}
/** 机制探针目录。 */

export const AIOS_PROBES_DIR: string = (() => {
  const env = process.env.AIOS_PROBES_DIR
  if (env && env.trim()) return env.trim().replace(/[/\\]+$/, '')
  return join(AIOS_ROOT, 'tools', 'probes')
})()

export const TAG = '[aios-activation]'

export const HEAD_BYTES = 8192
/**
 * 读卡**尾部**的字节数（用于解析 `Event Log` 的最近留痕 —— 卡头由 `HEAD_BYTES` 负责）。
 * 🔴 修（**读数驱动 · 决定性根因**）：原值 `8192`，但卡会**越来越长**
 *   （Notes 累积）。读数 `TASK-20261023-001`：文件 50,541 B · `## Event Log` 在 offset 14,114 ·
 *   最后一条 claim 在 16,193 ⇒ **8KB 尾窗从 42,349 起，完全覆盖不到 Event Log（差 26KB）**。
 *   ⇒ `lastOccupancyOf()` 恒 `null` ⇒ `myOccupiedCards()` 恒空 ⇒ **连锁失效**：
 *     ① 焦点卡判不出（`focusCardOf` = null）⇒ 接口件恒 'no-card'（** 的真正原因**，不是写失败）
 *     ② stage4 恒 `no-focus-card`（检索永不派发）
 *     ③ R3 维护清单永不触发（的基线恒空）
 *     ④ `multi-claim` 提醒失效
 *   修法：尾部窗口放大到 **128 KB**（只对 `State=Executing` 的卡读 tail ⇒ 通常 1–2 张 × 128KB）。
 *   ⚠️ 若单卡超过 128 KB 会再失效 ⇒ 长期正解是**把 `Event Log` 保持在文件末尾**（改 `task_card.py` 的格式，
 *      需单独裁），或让 `scanCards()` 对 Executing 卡读全文。
 */

export const TAIL_BYTES = 131072
/** 内存状态卫生：会话数上限（原型期足够；不需要持久化）。 */

export const OBS = 'v7-turnend-fill'
/**
 * **本体版本标记** —— `ev=apply` 的 `policy` 与 `focus-card` 接口文件的 `writerPolicy`
 * **共用同一个来源**（契约 §0「每项能力只有一个 owner」· ⛔ 不建第二份）。
 */
// 🔴 升版（纪律①「改本体必升 policy」）——
//    本版把**焦点卡判据**从「本会话卡改动 ▸ 退回环境唯一 `Executing`」改为
//    「**本会话的占用声明**」（`claim` / `release` 命令字面量）：
//      · 新增会话级 `claimed`⇒ ** 已删除**：占用判据改为**读卡真相**
//        （`State=Executing` + `Event Log` 最后占用行的 `session`）—— `claimed` 是"按命令猜"，
//        与工具写在卡上的真相会不一致（读数：被拒的 `claim` 也被记账）。
//      · ⛔ 删除 `env-unique-executing` 兜底（拿"卡级全局状态"冒充"会话级占用" ⇒ 跨会话串味）
//      · ⛔ `--dry-run` 不再记占用（预览不是占用）
//    裁定：**焦点卡 = 「在这个对话中占用的卡」**。

export const POLICY = 'activation+deferred-discovery(judge-only)v18-card-truth-occupancy+v19-work-report+v20-corpus-input+v21-report-reminder+v22-r3-maintenance+v23-inject-hint+v24-fix-tail-window+v25-phase-hint+v26-log-external+v27-stage4-fresh-cards+v28-maintenance-repeat+v30-inline-retrieval+v31-candidate-path-summary+v32-r3-wake-takeover+v33-two-step-vocab+v34-r3-single-injector+v35-retrieval-nudge+v36-event-hint+v37-nudge-frames+v38-tool-rename+v39-inject-copy+v40-inject-subagent+v41-nudge-revert+v42-project-prefixed-claim+v43-subagent-observation+v44-r3-fire-once+v45-inject-copy-please-use+v46-gap-after-fail+v47-trigger-tune+v48-return-tune+v49-experience-recall+v49a-recall-scope-fix+v49b-recall-subagent+v49c-permission-recall+v49d-exec-permission+v49e-exec-exitcode+v49f-query-permline+v49g-recall-transport-source-query+v49h-exec-error-context+v49i-perm-query-no-cmd+v49j-strip-abs-path+v50-r3-claim-handoff+v50b-r3-disarm-notice+v49k-encoding-recall+v49m-push-release-node+v49l-recall-quota+v49n-access-is-denied+v49o-hint-copy+v49p-startup-recover-project-prefix+v49q-runtime-edit-node+v51-phase-inject+v51a-phase-no-anchor+v51b-topic-order+v51c-node-inject+v51d-cap-top5-score+v51e-card-snapshot-refresh+v51f-card-id-resolve+v51g-cap-score-discrim+v51h-phase-axes+v51i-top1+v51j-first-step-inject+v51k-first-step-off+v51l-cap-cells+v51m-cap-cells-config+v51n-cell-block+v51o-cell-form+v51p-cap-nudge+v51q-domain-inject+v51r-declared-domain+v51s-encoding-query-fallback+v51t-cell-code-removed+v51u-spawn-output-cap+v51w-switch-cache+v51y-modular-a+v52-recall-query-norm-subagent-default+v53-domain-vocab-default+v54-confirmed-optional'
/** 每回合签名序列上限（防日志膨胀；超出只计数不追加）。 */

export function mono(): string {
  try {
    return process.hrtime.bigint().toString()
  } catch {
    return 'unknown'
  }
}

// ── 🔴 开关文件的**会话绑定**（需求）──────────────────────────
// 原话（逐字）：
//   「**不能只是通过绑定某一段对话 / 不然太麻烦 / 最好是可以直接用 哪怕是新开一个对话**」
// ⇒ 四个开关文件（delivery / shadow / stage4 / reminder）的 `session` 字段支持**通配**：
//     ① 完整字面 id   `"session-42c77fda-…"`  ⇒ **恰好相等**（旧行为 · 不变）
//     ② 通配 `"*"`                            ⇒ **任意会话**（免人工改绑）
//     ③ 尾通配 `"session-42c77fda*"`          ⇒ **前缀匹配**（够用且可核对：不引入 glob 语义）
//     ④ 字符串数组                            ⇒ 任一项命中即算（①–③ 各项规则不变）
//   ⛔ **不含**内嵌通配（`"a*b"`）—— 一个会话 id 里出现 `*` 不合法 ⇒ 当字面量处理，不猜。
//   ⛔ **空串 / 缺失 / 非法类型仍 = 不允许**（沿用旧实现）：
//      开关文件的默认语义必须是「**不匹配任何会话**」——「写了但写错」不得变成「对全世界开放」。
//   🔴 通配**只决定"插件是否在该会话工作"**，不放宽任何其它边界：
//      仍然不递送（`delivery` 字段）、仍然只落探针、仍然不落推理原文。改开关文件**不需重启**。
/** 探针里的会话绑定原文（逐字保留 `"*"` 与 `a*` —— 探针读数是取证材料）。 */

export function resolveStateFile(newName: string, oldName: string): string {
  const preferred = join(aiosStateDir(), newName)
  try {
    if (existsSync(preferred)) return preferred
    const legacySame = join(aiosStateDir(), oldName)
    if (existsSync(legacySame)) return legacySame
    const legacyScratch = join(AIOS_ROOT, 'scratch', oldName)
    if (existsSync(legacyScratch)) return legacyScratch
    return preferred
  } catch {
    return preferred
  }
}

/** 机制**探针脚本**解析：`AIOS_PROBES_DIR/<名>` ▸ 兼容位 `AIOS_STATE_DIR/<旧名>` ▸ `scratch/<旧名>` ▸ 首选名。 */

export function resolveScript(name: string, legacyName: string): string {
  const preferred = join(AIOS_PROBES_DIR, name)
  try {
    if (existsSync(preferred)) return preferred
    const legacySame = join(aiosStateDir(), legacyName)
    if (existsSync(legacySame)) return legacySame
    const legacyScratch = join(AIOS_ROOT, 'scratch', legacyName)
    if (existsSync(legacyScratch)) return legacyScratch
    return preferred
  } catch {
    return preferred
  }
}

/**
 * 🔴 **`<root>/tools/` 的**工具**脚本解析 —— 与机制探针目录（`tools/probes/`）分开。
 * 为什么必须单独一个函数（第二处缺陷）：
 *    经验召回调的是 **工具** `tools/experience_push.py`；初版复用 `resolveScript()`（语义 = 机制探针）
 *   ⇒ 解析到 `tools/probes/experience_push.py`（**不存在**）⇒ `spawn` 到不存在的文件 ⇒ 恒 `spawn-error`
 *   ⇒ 即使 `s` 修好了，召回也拿不到任何结果。
 *   ⛔ **不扩大 `resolveScript()` 的语义**（它服务 `tools/probes/` 的机制探针，混进去会让「探针」与「工具」再分不清）。
 */

export function resolveToolScript(name: string): string {
  const preferred = join(AIOS_ROOT, 'tools', name)
  try {
    if (existsSync(preferred)) return preferred
  } catch { /* 取不到 ⇒ 返回候选路径（spawn 失败会如实记 state） */ }
  return preferred
}

/**
 * 临时探针通道（双写互为 fallback；观察期结束后随原型一并撤下）。
 * ⚠️ **读数教训（自测暴露）**：隔离自测（mock ctx）会**写进真实探针通道**
 * ⇒ 真实窗口的统计里混入自测行 ⇒ `_activation_stats.mjs` 的交叉核对直接判 `mismatch`。
 * ⇒ 故给出 `AIOS_PROBE_PATH` 覆盖（**只**替换工作区那一路），与 `AIOS_CARDS_DIR` 同属
 *   「**隔离自测通道**」—— 不是新结构、不是新状态源。**自测必须设它。**
 */

export function probePaths(): string[] {
  if (process.env.AIOS_PROBE_PATH) return [process.env.AIOS_PROBE_PATH]
  return [
    join(aiosStateDir(), '_aios-activation.probe.log'),
    (process.env.USERPROFILE || process.env.HOME || '.') + '/.dsh/_aios-activation.probe.log',
  ]
}

export function emit(fields: Record<string, unknown>): void {
  let line: string
  try {
    line = TAG + ' ' + JSON.stringify(fields)
  } catch {
    return
  }
  try {
    console.log(line)
  } catch {
    /* ⛔ 不落探针（批3 判定）：**探针通道自身**写失败（磁盘满/权限）—— 在这里再 emit 就是递归自激；这类失败由调用方返回码/上层现象体现 */
  }
  for (const path of probePaths()) {
    try {
      appendFileSync(path, line + '\n')
    } catch {
      /* ⛔ 不落探针（批3 判定）：**探针通道自身**写失败（磁盘满/权限）—— 在这里再 emit 就是递归自激；这类失败由调用方返回码/上层现象体现 */
    }
  }
}

export function clip(s: unknown, n: number): string {
  const t = s === undefined || s === null ? '' : String(s).replace(/\s+/g, ' ').trim()
  return t.length <= n ? t : t.slice(0, n - 1) + '…'
}

/** 只读文件头部（不整读，保持"每轮极轻量检查"）。 */

export function readHead(path: string): string {
  let fd: number | undefined
  try {
    fd = openSync(path, 'r')
    const buf = Buffer.alloc(HEAD_BYTES)
    const n = readSync(fd, buf, 0, HEAD_BYTES, 0)
    return buf.subarray(0, n).toString('utf8')
  } catch {
    return ''
  } finally {
    if (fd !== undefined) {
      try {
        closeSync(fd)
      } catch (err) {
        noteCatchFail('state:readhead', err)
        /* 静默 */
      }
    }
  }
}

/** 只读文件**尾部**（`TAIL_BYTES`）—— 用于解析 `Event Log` 的最近留痕。 */

export function readTail(path: string): string {
  let fd: number | undefined
  try {
    fd = openSync(path, 'r')
    const size = statSync(path).size
    const start = Math.max(0, size - TAIL_BYTES)
    const len = size - start
    if (len <= 0) return ''
    const buf = Buffer.alloc(len)
    const n = readSync(fd, buf, 0, len, start)
    return buf.subarray(0, n).toString('utf8')
  } catch {
    return ''
  } finally {
    if (fd !== undefined) {
      try {
        closeSync(fd)
      } catch (err) {
        noteCatchFail('state:readtail', err)
        /* 静默 */
      }
    }
  }
}

/**
 * 从卡正文解析**最后一条**占用 / 释放留痕 ⇒ `Occupancy | null`（**纯函数 · 供单测**）。
 * 判据与 `tools/task_card.py` 的**写入侧逐字同源**：
 *   `| HH:mm | <State> | claim 占用（session: X） | Worker |`
 *   `| HH:mm | <State> | release 释放（session: X）[ · reason] | Worker |`
 * ⛔ 只认这两种行；其它 `Event Log` 行（收尾写回等）一律忽略（继续往前找）。
 * ⛔ 找不到 ⇒ `null`（"没有占用者"）⇒ 谁都不把它当焦点卡。
 */
/** ── 从 maintenance/r3-wake.ts 上收的共享声明 ── */
export const name = 'aios-activation'

/** 无服务依赖：不声明 `inject` ⇒ 立即 ACTIVE（PENDING 是「插件没有输出」的常见原因）。 */

export const SWITCH_CACHE = new Map<string, { mtimeMs: number; size: number; value: unknown }>()

/** 纯函数（导出供自测）：缓存是否失效（mtime 或 size 变了 ⇒ 需要重读）。 */

export function switchNeedsReload(
  cachedMtimeMs: number, cachedSize: number, mtimeMs: number, size: number,
): boolean {
  return cachedMtimeMs !== mtimeMs || cachedSize !== size
}

/** 读开关文件并按 mtime+size 缓存**已解析**的值；读/解析失败 ⇒ 返回 fallback。 */

export function readSwitchCached<T>(path: string, parse: (raw: string) => T, fallback: T): T {
  try {
    const st = statSync(path)
    const hit = SWITCH_CACHE.get(path)
    if (hit !== undefined && !switchNeedsReload(hit.mtimeMs, hit.size, st.mtimeMs, st.size)) {
      return hit.value as T
    }
    const raw = readFileSync(path, 'utf8')
    const value = parse(raw)
    SWITCH_CACHE.set(path, { mtimeMs: st.mtimeMs, size: st.size, value })
    return value
  } catch {
    return fallback
  }
}

export function userMessageOf(text: string, summary = 'aios delivery probe (static marker)'): Record<string, unknown> {
  return Object.freeze({
    id: randomUUID(),
    role: 'user',
    content: Object.freeze([{ type: 'text', text }]),
    source: Object.freeze({
      kind: `plugin:${name}`,
      form: 'notice',
      summary,
    }),
  })
}
/** ── 从 maintenance/r3-wake.ts 上收的共享声明 ── */
export const CATCH_FAIL_SEEN = new Set<string>()

export function noteCatchFail(where: string, err: unknown): void {
  try {
    if (CATCH_FAIL_SEEN.has(where)) return
    CATCH_FAIL_SEEN.add(where)
    emit({ ev: 'catch-fail', obs: OBS, where, detail: clip(String(err), 120), at: Date.now(), mono: mono() })
  } catch {
    /* 探针通道自身失败必须静默（⛔ 递归 emit）：已由 批3 复核确认保留 */
  }
}
/** ── 从 maintenance/r3-wake.ts 上收的共享声明 ── */
export const CARD_NAME_RE = /^(?:TASK-\d{8}-\d{3}|T\d{3}-[^.]+)\.md$/
/**
 * 卡目录。可用 `AIOS_CARDS_DIR` 覆盖 —— 用于**隔离自测**（临时副本树，不碰真实卡，
 * 与仓库既有 `scratch/_selftest_oplog.py` 同法）。
 */

export const WORK_REPORTS = new Map<string, WorkReportRecord[]>()

/**
 * 🔴 **归属**：**子会话也能调**，但语料**归父会话**。
 *   理由：检索只在**主会话**的 stage4 跑 ⇒ 子会话自述若不归并，主会话检索永远看不到，
 *         "子会话能调"就成空话。判据 = `identityOf(agent)` 判 subagent 且 `header.parentSession` 存在。
 *   ⛔ 拿不到父会话 ⇒ 归自己并在 ack 里注明（⛔ 不猜父会话是谁 —— 与"不推断"同一纪律）。
 *   纯函数（只读 agent 的 header）· 供单测。
 */
/** ── 从 maintenance/r3-wake.ts 上收的共享声明 ── */
export const CARDS_DIR = process.env.AIOS_CARDS_DIR || join(AIOS_ROOT, 'task_cards', 'active')
/** 只读文件头部即可覆盖 `State:` / `Current Step:`（它们都在 Header / Current Status 区块）。 */

// ── 由 `aios-activation.ts` 迁入（R2 类型接线）──

export const EXEC_TOOL_RE = /^(pwsh|powershell|bash|sh|zsh|cmd|cmd\.exe|exec|shell|run|terminal|pwsh\.exe|powershell\.exe)$/i

export function isExecToolName(name: string): boolean | null {
  const t = String(name === null || name === undefined ? '' : name).trim()
  if (t === '') return null
  return EXEC_TOOL_RE.test(t)
}

// ── 🔴 （经验侧 · 定稿 (a)）：**三个新节点** N1/N2/N3 ─────────────
//   背景：能力侧走阶段注入（//）；**经验侧走节点触发** —— 在高风险动作发生的**当下**，
//   给「自检与判据族」一个指针（⛔ 不注正文、⛔ 不到失败才提示、⛔ 不硬造能力包）。
//   🔴 照 （发布/推送节点）/ （改本体节点）的**已验证范式**写：纯词面判据 + 每节点每会话一次 Set
//      + 独立早退门 + `ev=node-inject` 探针（必须带 `session`）。
//   ⛔ N4 改本体 = `` 已有 · N5 发布推送 = `` 已有 ⇒ **本段不收编它们**（留待以后）。
//   ⛔ 不新建开关：门控沿用 `experienceRecallEnabled()`（与 / 一致）。

export function stripRepoPaths(text: string): string {
  const s = String(text === null || text === undefined ? '' : text)
  // 兼容两种形态：单反斜杠（真实输出）与双反斜杠（Python repr / 日志转义）。
  return s.replace(/[A-Za-z]:[\\/]{1,2}(?:[^\\/\s'"]+[\\/]{1,2})+/g, '<path>/')
}


/** T2：从工具结果判定失败类型（纯函数 · ⛔ 不记正文，只回分类）。 */

export function tokenSetOf(text: string): Set<string> {
  const out = new Set<string>()
  const s = String(text === null || text === undefined ? '' : text).toLowerCase()
  for (const m of s.matchAll(/[a-z0-9_]{3,}/g)) out.add(m[0])
  for (const seg of s.matchAll(/[\u4e00-\u9fa5]{2,}/g)) {
    const t = seg[0]
    for (let i = 0; i + 2 <= t.length; i++) out.add(t.slice(i, i + 2))
  }
  return out
}

/** T7′ 阈值：重合 token ≥3，且两条都 ≥5 个 token（太短一律不算重复）。 */
/** ── 从 maintenance/r3-wake.ts 上收的共享声明 ── */
export interface WorkReportRecord {
  id: string
  session: string
  at: number
  chars: number
  needCount: number
  concernCount: number
  confirmed: string
  hasFix: boolean
  hasCard: boolean
  /** ↓ 语料正文（内存 only · 检索读取 · ⛔ 不落盘） */
  what: string
  need: string[]
  concern: string[]
  fix: string
  note: string
  card: string
  /** 两步式第二步显式选的词表值（空数组 = 未选）· ⛔ 非词表值已在写入前被过滤 */
  axes: { domain: string[]; help: string[]; concern: string[] }
}

/** 每会话**语料环形**（内存 · ⛔ 不落盘 · 插件卸载即消失）。 */
