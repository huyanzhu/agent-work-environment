/**
 * declared-domain.ts — 从 `runtime/aios-activation.ts` 的 `apply()` 提炼。
 * 内容 = 「**注入跟随卡上声明的域能力**」的完整依赖闭包：
 *   · 声明读取（同级 `.log` 末条 / 卡正文「## 使用的能力」）· 旧名 ⇒ 域能力映射（`_aliases.json`）
 *   · `intro` 原文读取 · 三行注入文本渲染 · 域标签
 *   · `applyDeclaredDomainInjection()` —— 原 `apply()` 内 注入段，**语句原样搬移**。
 * 🔴 行为零变化：只做两处允许的改写 —— ① 局部变量改成参数；② `injectedEventThisStep = true`
 *    改成 `return true`（调用方据此置位）。门条件 / 探针字段 / 去重口径 / try 边界逐字保留。
 * ⛔ 改逻辑请改回主模块并跑 184 项自测（唯一红 = S37）。
 */
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { AIOS_ROOT, OBS, clip, emit, mono, userMessageOf } from '../diagnostics/probe.ts'
import { cardLogPathOf, phaseInjectSlotOf } from './phase-policy.ts'
import { CARDS_DIR } from './../diagnostics/probe.ts'
import type { AiPhase } from './phase-policy.ts'
import { myOccupiedCards } from '../session/lifecycle.ts'
import type { SessionState, TaskCursor } from '../session/session-state.ts'

export const PHASE_TITLE: Record<AiPhase, string> = { S1: '决策', S2: '实现', S3: '受阻', S4: '收口' }

/** 域能力目录（**每次现读**）。`AIOS_ROOT` 在**调用时**再取一次（模块加载那份是常量）
 *  —— 只为让单测（S186 形态）能指向**隔离根**（"域文件不存在 ⇒ ⛔ 不抛错"）。
 *  ⛔ 不缓存 / ⛔ 不写盘；env 缺省时与常量同值（生产行为不变）。 */
export function domainCapDir(): string {
  const env = process.env.AIOS_ROOT
  const root = env !== undefined && env.trim() !== '' ? env.trim().replace(/[/\\]+$/, '') : AIOS_ROOT
  return join(root, 'capabilities')
}

/** 读一个能力文件 frontmatter 的 `domain` / `intro`（**每次现读**；读不到 / 无 frontmatter ⇒ `null`）。 */
export function domainFrontmatterOf(file: string): { domain: string; intro: string } | null {
  try {
    const text = readFileSync(file, 'utf8').replace(/^\uFEFF/, '')
    const fmMatch = /^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n/.exec(text)
    if (fmMatch === null) return null
    const fm = fmMatch[1]
    const pick = (key: string): string => {
      const m = new RegExp('^' + key + '[ \\t]*:[ \\t]*(.+)$', 'm').exec(fm)
      return m === null ? '' : m[1].trim().replace(/^['"]|['"]$/g, '')
    }
    return { domain: pick('domain'), intro: pick('intro') }
  } catch {
    return null
  }
}

/** **纯函数**：域能力名 ⇒ 该文件 frontmatter 的 `intro` **原文**（读不到 / 为空 ⇒ `null`）。
 *  ⚠️ 返回**原文**（⛔ 不改写 / ⛔ 不加句号 / ⛔ 不拼接）：注入文本里的那一行必须能逐字回源到 frontmatter。 */
export function domainIntroOf(capName: string): string | null {
  const name = String(capName === undefined || capName === null ? '' : capName).trim()
  if (name === '' || /[/\\]/.test(name)) return null
  const fm = domainFrontmatterOf(join(domainCapDir(), name + '.md'))
  if (fm === null || fm.intro === '') return null
  return fm.intro
}

/**
 * **纯函数**：域能力 ⇒ 注入文本（**逐字 3 行** · ⛔ 无"能力候选" / ⛔ 无打分 / ⛔ 无条数）。
 *   形状（本卡硬约束，改一个字 = 改实验变量）：
 *     ```
 *     【AI-OS · <阶段中文> · <域>能力】
 *       <intro>            ← 该域能力 frontmatter 的 `intro` **原文**（⛔ 不改写）
 *       → capabilities/<capName>.md
 *     ```
 *   `<阶段中文>` 取既有 `PHASE_TITLE`（⛔ 不另立映射）。
 */
export function renderDomainInjection(phase: AiPhase, domain: string, capName: string, intro: string): string {
  return [
    '【AI-OS · ' + PHASE_TITLE[phase] + ' · ' + domain + '能力】',
    '  ' + intro,
    '  → capabilities/' + capName + '.md',
  ].join('\n')
}

// ── **注入跟随卡上声明的域能力**（替代机器猜域）──────────
//   方向已定，⛔ 不再论证。依据：机器猜域**全不可靠** —— topic 词表精确率 57% ·
//     检索工具 47–59% · 路径 83%（都不如 agent 自己填）⇒ **域由 agent 在卡上声明**；
//     Runtime 只**读**声明，⛔ 不再 `inferDomainOf()` 猜、⛔ 不再用检索判域。
//   声明的两个落点（v4 卡 · `tools/task_card.py capability` 同时写两处，`.log` 先写 = 权威）：
//     ① 同级同名 `.log` 的 `能力` 行（脚本写 ⇒ 格式永远正确）；
//     ② 卡正文「## 使用的能力」节的 `- 能力: `<name>``（人可读的快照）。
//   语义（**三值** · ⛔ 不要合并）：
//     · 能力名 ⇒ 注入该域能力（**声明变了 ⇒ 同阶段再注入一次** —— 明确要求）；
//     · `none`  ⇒ 已声明"不用能力" ⇒ **不注入**（⛔ 不回退成猜域）；
//     · `null`  ⇒ 未声明（没写 / 读失败）⇒ **不注入**（⛔ 不猜、⛔ 不回退检索判域）。

/** 卡 key（`项目/TASK-ID.md` / `TASK-ID.md`）⇒ 卡正文路径（与 `cardLogPathOf` 同口径）。 */
export function cardMdPathOf(key: string): string {
  return key.toLowerCase().endsWith('.md') ? join(CARDS_DIR, key) : join(CARDS_DIR, key + '.md')
}

/** 卡正文 ⇒ 「## 使用的能力」节正文（无该节 ⇒ `null`）；判据与 `tools/task_card.py: _cap_section_span` 同形。 */
function capSectionBodyOf(raw: string): string | null {
  const text = String(raw === undefined || raw === null ? '' : raw)
  const head = /^##[ \t]+使用的能力[^\n]*$/m.exec(text)
  if (head === null) return null
  const rest = text.slice(head.index + head[0].length)
  const next = /^##[ \t]/m.exec(rest)
  return next === null ? rest : rest.slice(0, next.index)
}

/**
 * **纯函数**：卡正文 ⇒ 「## 使用的能力」节里 `- 能力: `<name>`` 的名字（未声明 ⇒ `null`）。
 *   判据与 `tools/task_card.py: _cap_stage_line_re("once")` 同形（容忍 `* 能力:` / 全角冒号）；
 *   只认**反引号内**的值 —— 模板占位 `- 能力: （未记录）`（无反引号）⇒ `null`（= 未声明，⛔ 不当能力名）。
 */
export function declaredCapOfCardBody(raw: string): string | null {
  const body = capSectionBodyOf(raw)
  if (body === null) return null
  const lineRe = /^[ \t]*(?:[-*][ \t]*能力|能力(?=[ \t:：`]|$))/
  for (const line of body.split(/\r?\n/)) {
    if (!lineRe.test(line)) continue
    const m = /`([^`]*)`/.exec(line)
    return m === null ? null : m[1].trim()
  }
  return null
}

/**
 * 同级同名 `.log` ⇒ **最后一条**能力行的能力名（`能力` / `能力-开工|实现|收尾` 都认；无 ⇒ `null`）。
 *   为什么取**最后一条**：声明可改（agent 发现域选错 ⇒ 再记一次）⇒ 最新一条即当前声明。
 *   ✅ 校验侧取末条：**校验侧也改成末条**（`_capability_choice_lint.py: single_row`）
 *      ⇒ 注入与校验**同口径**；旧三阶段卡的 `stage_row` 仍取首条（不受影响）。
 *      此前两处相反（这边末条 / 那边首条）⇒ agent 一更新声明就"不一致" ⇒ 理性选择永不更新
 *      ⇒ `re-injected` 永远触发不了。⚠️ 但策略层仍是一任务一域（`capabilities/INDEX.md` 明文），
 *      所以 `re-injected` 只是**安全网**，不是主路径（三个真实任务均未触发，且理由正当）。
 */
export function declaredCapOfLog(logPath: string): string | null {
  const raw = readFileSync(logPath, 'utf8').replace(/^\uFEFF/, '')
  const CAP_STATES = ['能力', '能力-开工', '能力-实现', '能力-收尾']
  let found: string | null = null
  for (const line of raw.split(/\r?\n/)) {
    const s = line.trim()
    if (!s.startsWith('|')) continue
    const cells = s.replace(/^\|/, '').replace(/\|$/, '').split('|')
    if (cells.length < 3) continue
    if (CAP_STATES.indexOf(cells[1].trim()) < 0) continue
    // `<name> ｜ 理由：…` ⇒ 取第一段；容忍手改（缺 `｜ 理由：` 时整格当名字）
    const nm = cells[2].trim().split('｜')[0].trim().replace(/^`+|`+$/g, '').trim()
    if (nm !== '') found = nm
  }
  return found
}

/** 声明读失败的探针去重键（每会话每处一条 · ⛔ 不每拍刷屏）。 */
const DECLARED_READ_ERR_SEEN = new Set<string>()

/**
 * **读卡上声明的域能力**（**现读 · ⛔ 不缓存跨阶段**）。
 * 优先级（从稳到不稳，取第一个可用）：
 *   ① 同级同名 `.log` 的**最后一条** `能力` / `能力-开工|实现|收尾` 行 —— 脚本写，格式永远正确；
 *   ② 卡正文「## 使用的能力」节的 `- 能力: `<name>``。
 * 返回：能力名原文（可能是**旧名** ⇒ 由 `domainCapabilityResolvedOf()` 再映射）
 *   / `"none"`（已声明不用能力）/ `null`（**未声明**；读失败同样 `null`）。
 * ⚠️ 读失败 ⇒ `null` + **一条**失败探针（`state:"declared-error"`）—— ⛔ 不静默（铁律②）。
 * ⚠️ 成本：每个"该注入的拍"调用一次（读 1 个 `.log` + 1 张卡，都是 KB 级）。**故意不缓存**：
 *   声明改了而阶段没变时，只有现读才能发现 —— 要的"域不同了又注入"就靠它。
 */
export function declaredDomainCapabilityOf(card: TaskCursor, session: string): string | null {
  if (card === null || card === undefined) return null
  const key = String(card.key || '')
  if (key === '') return null
  try {
    const logPath = cardLogPathOf(key)
    if (existsSync(logPath)) {
      const viaLog = declaredCapOfLog(logPath)
      if (viaLog !== null) return viaLog
    }
  } catch (e) {
    declaredReadErrorOf(session, 'log', e)
  }
  try {
    const viaCard = declaredCapOfCardBody(readFileSync(cardMdPathOf(key), 'utf8'))
    if (viaCard !== null) return viaCard
  } catch (e) {
    declaredReadErrorOf(session, 'card', e)
  }
  return null
}

/** 声明读失败的**失败探针**（铁律②）—— 每会话每处一条（⛔ 不每拍刷屏）。 */
function declaredReadErrorOf(session: string, where: string, err: unknown): void {
  try {
    const k = String(session) + '|' + where
    if (DECLARED_READ_ERR_SEEN.has(k)) return
    DECLARED_READ_ERR_SEEN.add(k)
    emit({
      ev: 'phase-inject', obs: OBS, session, state: 'declared-error', basis: 'declared', where,
      n: 0, chars: 0,
      detail: clip(err instanceof Error ? err.message : String(err), 100),
      note: 'read declared capability failed ⇒ treat as undeclared (⛔ 不猜域)',
      at: Date.now(), mono: mono(),
    })
  } catch { /* 探针自身失败绝不影响宿主 */ }
}

/** `<name>` 是不是**域能力**（`domain-*` 且 `capabilities/<name>.md` 存在）。 */
function isDomainCapFile(name: string): boolean {
  const n = String(name === undefined || name === null ? '' : name).trim()
  if (!/^domain-[^/\\]+$/.test(n)) return false
  try {
    return existsSync(join(domainCapDir(), n + '.md'))
  } catch {
    return false
  }
}

/**
 * **纯函数**：卡上声明 ⇒ **域能力名**（映射不出来 ⇒ `null` ⇒ **不注**）。
 *   ① 声明本身已是域能力 ⇒ 原样；
 *   ② 旧能力名 ⇒ 按 `capabilities/_aliases.json` 映射（域合并时 17 个旧名 ⇒ 8 个域能力）；
 *   ③ 都不是 / 映射目标不是域能力 ⇒ `null`（⛔ 不猜近义、⛔ 不注一个不存在的文件）。
 */
export function domainCapabilityResolvedOf(declared: string): string | null {
  const name = String(declared === undefined || declared === null ? '' : declared)
    .trim().replace(/^`+|`+$/g, '').trim()
  if (name === '' || /[/\\]/.test(name)) return null
  if (isDomainCapFile(name)) return name
  try {
    const p = join(domainCapDir(), '_aliases.json')
    if (!existsSync(p)) return null
    const j = JSON.parse(readFileSync(p, 'utf8').replace(/^\uFEFF/, ''))
    if (j === null || typeof j !== 'object' || Array.isArray(j)) return null
    const mapped = (j as Record<string, unknown>)[name]
    if (typeof mapped !== 'string') return null
    const target = mapped.trim()
    return isDomainCapFile(target) ? target : null
  } catch {
    return null
  }
}

/** **纯函数**：域能力名 ⇒ 注入标题里的 `<域>`（frontmatter `domain:` 原文；读不到 / 为空 ⇒ 用能力名兜底）。 */
export function domainLabelOf(capName: string): string {
  const fm = domainFrontmatterOf(join(domainCapDir(), String(capName) + '.md'))
  return fm === null || fm.domain === '' ? String(capName) : fm.domain
}

/**
 * 🔴 **本拍是否注入「卡上声明的域能力」**（从 `apply()` 原样提炼）。
 * 前置门（与原代码同序、同短路）：`ph` 非空 · 非 S3 · 本拍未注入过 · `domainInject` 开启。
 * @returns `true` = 已把注入文本 push 进 `extras`（调用方据此置 `injectedEventThisStep = true`）；
 *          `false` = 未注入（门未过 / 无唯一卡 / 未声明 / `none` / 映射不到域能力 / 同阶段 dup / 读失败）。
 * ⚠️ `extras` 按引用修改（与原 `extras.push` 是同一个数组）；读失败探针（`state:"declared-error"`）原样保留。
 */

export function applyDeclaredDomainInjection(
  extras: Record<string, unknown>[],
  session: string,
  ist: SessionState,
  ph: AiPhase | null,
  alreadyInjectedThisStep: boolean,
  domainOn: boolean,
): boolean {
  // ── **注入跟随卡上声明的域能力** ─────────────────
  //   位置固定在**格能力块与检索块之前**（沿用同一位置）：声明命中 ⇒ 本拍只注那 3 行。
  //   取代 的"按 topic 猜域"（依据见本节顶部注释：机器猜域精确率 57%/47–59%/83%）。
  //   开关 `domainInject`（缺省 off）⇒ 关时**整段一行都不执行**（A 组逐字不变）。
  //   ⛔ 声明缺失（`null`）/ 声明 `none` / 声明映射不到域能力 ⇒ **本拍不注入**：
  //     `injectedEventThisStep` 保持 false，且下面的检索块被 `!domainOn` 挡住
  //     ⇒ **⛔ 不回退检索判域**（回退 = 继续用机器猜域，与 方向冲突）。
  //   命中 ⇒ **先记账再注入**（`injectedCap` / `sent`；失败不重试，与既有两条路径同口径）。
  if (ph !== null && ph !== 'S3' && !alreadyInjectedThisStep && domainOn) {
    // 🔴 铁律②：catch 里**至少落一条失败探针**（否则 ReferenceError 之类会被静默吞掉，
    //    表现为"开了开关却什么都不发生、日志也干净"）。整段外面必须有自己的 try。
    try {
      // 🔴 铁律①：**不跨 try 块引用变量** ⇒ 卡 / 声明 / 槽位一律在本 try 内**现取**
      const pslotDom = phaseInjectSlotOf(session)
      const mineDom = myOccupiedCards(ist)
      // 必须**恰好 1 张**卡：0 张（还没占卡）/ 多张（判不出该跟谁）⇒ 不注、也不记账
      const cardDom = mineDom.length === 1 ? mineDom[0] : null
      if (cardDom !== null) {
        // **现读**声明（⛔ 不缓存跨阶段 —— 声明改了而同阶段没变，也必须能发现）
        const declaredDom = declaredDomainCapabilityOf(cardDom, session)
        // `null` = 未声明；`none` = 已声明"不用能力" ⇒ **两者都不注入**（⛔ 不猜域兜底）
        if (declaredDom !== null && declaredDom.trim().toLowerCase() !== 'none') {
          // 声明名 ⇒ 域能力名：旧名走 `capabilities/_aliases.json`（读不到映射 ⇒ null ⇒ 不注）
          const capDom = domainCapabilityResolvedOf(declaredDom)
          const introDom = capDom === null ? null : domainIntroOf(capDom)
          if (capDom !== null && introDom !== null) {
            const domainDom = domainLabelOf(capDom)
            const prevCap = pslotDom.injectedCap.get(ph)
            if (prevCap !== undefined && prevCap === capDom) {
              // 该阶段注过**同一个**声明 ⇒ 不重复（每阶段只落一条 dup 读数，⛔ 每拍刷屏）
              if (!pslotDom.declaredDupReported.has(ph)) {
                pslotDom.declaredDupReported.add(ph)
                emit({
                  ev: 'phase-inject', obs: OBS, session, phase: ph, state: 'dup',
                  basis: 'declared', domain: domainDom, capability: capDom, n: 0, chars: 0,
                  note: 'declaration unchanged for this phase ⇒ no re-injection (v51r)',
                  at: Date.now(), mono: mono(),
                })
              }
            } else {
              const textDom = renderDomainInjection(ph, domainDom, capDom, introDom)
              // 先记账再注入（与既有两条路径同口径：失败不重试）
              pslotDom.injectedCap.set(ph, capDom)
              pslotDom.sent.add(ph)
              const probeDom: Record<string, unknown> = {
                ev: 'phase-inject', obs: OBS, session, phase: ph, state: 'injected',
                basis: 'declared', domain: domainDom, capability: capDom,
                n: 1, chars: textDom.length,
                note: 'declared on card (.log / 使用的能力) ⇒ follow the declaration (⛔ 不猜域)',
                at: Date.now(), mono: mono(),
              }
              // 🔴 声明**变了**（该阶段注过**不同** cap）⇒ **再注入一次** + `prev` 留痕
              if (prevCap !== undefined) {
                probeDom.state = 're-injected'
                probeDom.prev = prevCap
              }
              emit(probeDom)
              extras.push(userMessageOf(textDom, 'aios declared domain injection (v51r)'))
              return true
            }
          }
        }
      }
    } catch (e) {
      // 失败探针（铁律②）：⛔ 静默；`state:"declared-error"` 让"看起来没注入"可核对。
      emit({
        ev: 'phase-inject', obs: OBS, session, phase: ph, state: 'declared-error',
        basis: 'declared', n: 0, chars: 0,
        detail: clip(e instanceof Error ? e.message : String(e), 100),
        at: Date.now(), mono: mono(),
      })
    }
  }
  return false
}
