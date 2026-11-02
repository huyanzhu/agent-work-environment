/** request-builder.ts —— 由 `runtime/aios-activation.ts` 拆出（阶段-1 · 检索闭包 · 纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */
import { existsSync, readFileSync, readdirSync, watch } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { spawn } from 'node:child_process'
import { join } from 'node:path'
import type { Stage4Probe } from './../delivery/pending-delivery.ts'
import { OBS, aiosStateDir, clip, emit, isExecToolName, mono, resolveScript, stripRepoPaths, tokenSetOf } from './../diagnostics/probe.ts'

import { spawnJson } from './python-bridge.ts'
import { field } from './../session/lifecycle.ts'
import { SESSIONS } from './../session/session-state.ts'
import type { WorkContext } from './../session/work-context.ts'
import { FACTUAL_FAIL_RE, failKindOf } from './../session/work-context.ts'
import type { WorkReportRecord } from './../diagnostics/probe.ts'

export const STAGE4_RETRIEVAL_ENTRY = process.env.AIOS_STAGE4_RETRIEVAL || resolveScript('_retrieval_request_probe.py', '_retrieval_request_probe.py')
/** 进入 `work_topic` 的领域短语上限（**最小输入** · 防长查询稀释密度）。 */

export const STAGE4_TOPIC_PHRASES = 3
/**
 * 传给字段产出器的推理**条数上限** —— `produce()` 侧只用 `reason_window`（20）近窗口 ⇒ 不必发全量。
 */

export const STAGE4_ROLE_MAP: Record<string, string> = {
  设计: 'guidance',
  开发工具: 'guidance',
  集成: 'integration',
  测试: 'verification',
  审核: 'verification',
}

export function stage4Uniq(seq: string[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const x of seq) {
    if (x !== '' && !seen.has(x)) {
      seen.add(x)
      out.push(x)
    }
  }
  return out
}

/**
 * ① **Runtime 决定"向 Retrieval 提供什么"**（最小输入 · `RETRIEVAL-INTERFACE-DESIGN.md §2`）。
 * 🔴 只提供：**焦点对象 + 领域短语**（`work_topic`）＋ 角色映射 ＋ 历史完整性 ＋ 预算。
 * ⛔ 不提供：意图原文 / 推理文本 / 计划原文 / 整卡正文（"⛔ 不得把字段拼成一个巨大字符串"）。
 * 🔴 `target_refs` **不提供**：活动证据里的 `pathClass` 是**目录类别**（如 `server/services/`），
 *    而 `identifier` 通道是**字面包含**（路径 / 文件名）⇒ 提供它只会制造"看似精确、实则零命中"的假象；
 *    精确对象来源（卡的 `Resume Point` / `Deliverables` 路径）属**下一刀**，不在范围内。
 */

export function buildRetrievalRequest(field: Record<string, unknown>, wc: WorkContext, probe: Stage4Probe): Record<string, unknown> {
  const obj = typeof field.object === 'string' ? field.object : ''
  const phrases = Array.isArray(field.phrases) ? field.phrases.map((p: unknown) => String(p)) : []
  const cats = Array.isArray(field.categories) ? field.categories.map((c: unknown) => String(c)) : []
  const topic = [obj].concat(phrases.slice(0, STAGE4_TOPIC_PHRASES)).filter(s => s !== '').join(' ')
  const roles = stage4Uniq(cats.map(c => STAGE4_ROLE_MAP[c]).filter((r): r is string => typeof r === 'string'))

  const work: Record<string, unknown> = {
    work_topic: topic === '' ? { state: 'unknown' } : { state: 'provided', value: topic },
    target_refs: { state: 'unknown' },
    history_coverage: {
      state: 'provided',
      value: wc.historyCoverage === 'partial' ? 'incomplete' : 'complete',
    },
  }
  const req: Record<string, unknown> = {
    schema: 'retrieval-request/v1',
    request_id: 'rr-stage4-' + String(Date.now()),
    need: { state: 'unknown', origin: 'runtime' },
    work,
    sources: { mode: 'all-discoverable', ids: [] },
    budget: { max_candidates: probe.maxCandidates, max_per_source: probe.maxPerSource },
  }
  if (roles.length > 0) req.roles_needed = roles
  return req
}

// ── **按 `auto_capability` 的字段**构造检索请求（"字段 → 通道" · 与 Python `FIELD_CHANNELS` 一一对应）──
//   依据 `CONCLUSIONS-.md §十四`（输入 = `auto_capability` 的语料/字段）+
//        口径：「agent 调用工具并输出那些字段 → 到检索侧**根据字段**做检索」。
//   映射表（每条边都有语义理由，⛔ 不拼成一个巨大字符串 —— 那会退化成"找不出是哪个字段召回的"）：
//     what    → `work.work_topic`   （topic 通道：主题词面）
//     need    → 顶层 `need`          （intent 通道：语义需求主通道 · origin=agent）
//     need 中的**帮助类型** → `work.work_type`（role 通道：显式角色映射；无命中即不判，⛔ 不猜）
//     concern → 顶层 `search_terms`  （keys 通道：**Agent 自供检索键** · Python 侧 `keys_hits`）
//     fix     → `work.unresolved`   （context 通道：**只加分、不单独构成命中**）
//     note    → ⛔ **不进检索**（自由文本会发散；只留在内存记录里）
//     card    → `work.target_refs` 保持 `unknown`（卡是**工作对象**、不是**检索对象**；
//                ⛔ 不做"看似精确、实则零命中"的假象 —— 与 `target_refs` 原注释同一纪律）

export const WR_HELP_TYPES: readonly string[] = ['实现', '评审', '调试', '验证', '写作', '设计', '审计·清理', '检索', '维护', '协作·版本']
// 🔴 （「先做词表 → 按词表整理能力」）：**词表三维值**（⛔ 与
//    `task_cards/NEEDS-VOCAB.md` 手工同步 —— 改那里必须同步这里）。
//    用途：把 `need` / `concern` 里**恰好是词表值**的项抽出来，作为 `axes`（确定性匹配通道），
//    与"自由文本走词面通道"并存 —— 选词就是选词，写话就是写话，不混。

export const WR_DOMAIN_VALUES: readonly string[] = ['前端', '后端', '数据', '文档', '产品', '环境·运维', '求职·职业', 'AI-OS 自身']

export const WR_CONCERN_VALUES: readonly string[] = ['正确性', '可维护性', '可扩展性', '美观·风格', '性能', '安全', '一致·预算', '成本']

/** 本会话**最近一条** `auto_capability`（内存 · ⛔ 不落盘 · 无则 `null`）。 */

export function buildRetrievalRequestFromWorkReport(rep: WorkReportRecord, wc: WorkContext, probe: Stage4Probe): Record<string, unknown> {
  const helps = rep.need.filter(x => WR_HELP_TYPES.includes(x))
  const work: Record<string, unknown> = {
    work_topic: rep.what !== '' ? { state: 'provided', value: rep.what } : { state: 'unknown' },
    target_refs: { state: 'unknown' },
    history_coverage: {
      state: 'provided',
      value: wc.historyCoverage === 'partial' ? 'incomplete' : 'complete',
    },
  }
  if (helps.length > 0) work.work_type = { state: 'provided', value: helps.join(' ') }
  if (rep.fix !== '') work.unresolved = { state: 'provided', value: rep.fix }
  const needText = rep.need.join(' ')
  const req: Record<string, unknown> = {
    schema: 'retrieval-request/v1',
    request_id: 'rr-' + rep.id,
    need: needText !== '' ? { state: 'provided', value: needText, origin: 'agent' } : { state: 'unknown', origin: 'agent' },
    work,
    sources: { mode: 'all-discoverable', ids: [] },
    budget: { max_candidates: probe.maxCandidates, max_per_source: probe.maxPerSource },
  }
  if (rep.concern.length > 0) req.search_terms = { state: 'provided', value: rep.concern }
  // **axes**（词表三维标签）—— 只收**恰好等于词表值**的项（⛔ 不猜同义词）。
  //    有 axes ⇒ Python 侧 `axis_hits()` 做确定性匹配（权重 4.0，高于任何词面通道）。
  const axes: Record<string, string[]> = {}
  const domain = rep.need.filter(x => WR_DOMAIN_VALUES.includes(x))
  const concern = Array.from(new Set(
    rep.concern.concat(rep.need).filter(x => WR_CONCERN_VALUES.includes(x)),
  ))
  if (domain.length > 0) axes.domain = domain
  if (helps.length > 0) axes.help = helps
  if (concern.length > 0) axes.concern = concern
  // 两步式**显式 axes 优先**（只收词表值 · 已在 buildWorkReport 过滤；空轴不覆盖）
  const ax = rep.axes
  if (ax !== undefined && (ax.domain.length + ax.help.length + ax.concern.length) > 0) {
    const picked: Record<string, string[]> = {}
    if (ax.domain.length > 0) picked.domain = ax.domain
    if (ax.help.length > 0) picked.help = ax.help
    if (ax.concern.length > 0) picked.concern = ax.concern
    req.axes = picked
  } else if (Object.keys(axes).length > 0) req.axes = axes
  return req
}

/** 一次**异步** `python <entry>`（stdin JSON ⇒ stdout JSON）· 超时 kill · 失败**如实分类**。 */
/** 🔴 （审计）：子进程输出**硬上限** —— 防止误开 debug / 异常刷栈把宿主内存打爆。
 *   两处 spawn 都只做超时兜底，`out += String(d)` **无字节上限**（L2190/2193 · L2480/2481），
 *   极端情况 OOM 杀掉整个宿主，且**零探针**。 */

export const RETURNED_CAPABILITY_IDS = new Map<string, Set<string>>()

export function rememberCapabilityIds(session: string, ids: readonly string[]): void {
  if (ids.length === 0) return
  let set = RETURNED_CAPABILITY_IDS.get(session)
  if (set === undefined) {
    set = new Set()
    RETURNED_CAPABILITY_IDS.set(session, set)
  }
  for (const id of ids) if (id !== '') set.add(id)
}

/** 候选是否是**能力包**（路径在 `capabilities/` 下）—— 阶段注入只注「能力描述 + 指针」，不注账本/语料 chunk。 */

export function isCapabilityCandidatePath(p: string): boolean {
  return String(p || '').replace(/\\/g, '/').toLowerCase().startsWith('capabilities/')
}

/**
 * **纯函数**：卡 ⇒ `work_topic`（**分层表达：Next Action 在前、Goal 在后**）。
 * 为什么分层（定稿 · 读数驱动）：主线卡的 `Goal` 很抽象
 *   （"设计工作认知模块契约…"）、`Next Action` 才具体（"正在改 runtime 注入段"）——
 *   平铺拼接后具体信息被抽象话语稀释，检索偏（读数：已占卡仍返回 `frontend-ui` 之类无关候选）。
 *   ⇒ 形态固定为 `<Next Action> ｜ <Goal>`（顺序即权重；检索侧是词面/向量匹配，**不改 python 侧**）。
 * 分支（与设计稿一致）：
 *   · 两者都有 ⇒ `<next> ｜ <goal>`
 *   · 只有 next ⇒ 只用 next；只有 goal ⇒ 只用 goal；都空 ⇒ `''`（调用方 `=> null`， 行为不变）
 *   · **长度上限 400**：先放 next；**next 超长时 goal 让位**（⛔ 不让 goal 挤掉 next）。
 * ⛔ 只用卡上的 `Goal` / `Next Action` —— **绝不**引入 `intentText`（已删，S150 拦回归）。
 */

export const PERMISSION_FAIL_RE = /拒绝访问|access denied|access is denied|permission denied|PermissionError|WinError\s*(5|32)|Errno\s*13|EACCES|EPERM|权限不足/i

// ── 🔴 （真实任务观测后 · 触发/查询修复 · 全部纯函数）────────────────
//   证据：3 个真实任务（R2/R3/ · `scratch/_recall_rootcause_notes.md`）暴露 3 个缺陷：
//     ① R3 真权限失败的退出标记是 `exit2=1` / `EXIT=1` / `EXITCODE=0`（等号）⇒ 旧正则漏报；
//     ② R2 用 `read` 读 PITFALLS（正文含错误格式示例）⇒ 被当成执行失败（误触发）；
//     ③ R3 读二进制失败被判知识型 ⇒ 触发召回并命中无关台账（误报）。
//   ⛔ 边界：全部只做**词面/结构**判定；⛔ 不改 `FACTUAL_FAIL_RE`（T2 gap 口径原样）。

/** **退出标记解析器** —— 在 两种格式之外补读数的第三种/第四种：
 *  `EXIT=1` / `exit2=1`（等号）、`EXITCODE=0`（等号）。⛔ 只认非零；仍须 AND `PERMISSION_FAIL_RE`。 */

export const EXIT_MARK_RE = /\[exit code: [1-9]\d*\]|\bexitcode\s*[:=]\s*[1-9]\d*|\bEXIT\s*=\s*[1-9]\d*|\bexit2?\s*=\s*[1-9]\d*/i

/** （读数 · V3）：**执行错误上下文门** —— exec 结果里"文档内容恰好含错误字串"不得判权限失败。
 *  读数：`pwsh` 打印 PITFALLS 预览，正文含 「拒绝访问」+ 「`[exit code: 1]`」⇒ 被误触发（注入权限族 = 误报）。
 *  真实失败输出必有其一：`[stderr]` 段 / `Traceback` / `ERROR:` / `PermissionError:`。
 *  ⛔ 只用于 exec 触发分支；不改其它触发类型 / 不改 failKindOf。 */

export const EXEC_ERROR_CONTEXT_RE = /\[stderr\]|Traceback|\bERROR:|PermissionError:/

/** 🔴 （真实任务读数）：**编码类失败触发** —— 编码族卡已进语料，但触发面没有编码类。
 *  读数：`UnicodeDecodeError: 'gbk' codec can't decode byte 0xff …`（UTF-16LE+BOM 文件被 locale cp936 读），
 *  走 shell 时结果 `ok:true`⇒ / 的权限路径不进、isError 路径也不进 ⇒ 0 注入（漏报）。
 *  预检：同一条 query 喂运行时词面通道 ⇒ 命中 `PITFALLS `（编码族成员）⇒ 触发一加即能召回。
 *  ⛔ 边界不变：只做词面判定；⛔ 不收 "decode"/"encode" 单词（太泛）；⛔ 不改 `FACTUAL_FAIL_RE`/`failKindOf`。 */

export const ENCODING_FAIL_RE = /UnicodeDecodeError|UnicodeEncodeError|codec can't (decode|encode)|invalid start byte|invalid continuation byte|illegal multibyte sequence|illegal byte sequence|\bmojibake\b|\uFFFD/i

/** 编码失败的**判别词**行（query 优先取这些行 · 同 权限做法）。 */

export const ENCODING_DETAIL_RE = /codepage|codec|utf-?8|utf-?16|gbk|gb2312|cp936|bom|0xff|0xfe|invalid start byte|illegal multibyte|unicodedecodeerror|unicodeencodeerror/i

/** **发布/推送节点** —— 节点是可发现的，**只盯「发布」「推送」两个动作**。
 *  做法：exec 工具的 `command` 参数里出现 push / publish / release 类命令 ⇒ **在动作发生时**就给族卡指针 + 核对清单
 *  （⛔ 不等到失败：失败另有 / 触发；这里管「做之前/做之后该核什么」）。
 *  只认这两类动词 ⇒ 误报面天然窄（`git status/commit/fetch/pull/log` 等一律不触发）。
 *  ⛔ 边界：只做词面判定（不读语义）；探针只落命令的 clip 片段，不落全文。 */

export function looksLikeFileDump(text: string): boolean {
  return /<path>[\s\S]*?<\/path>/.test(text) && /<content>[\s\S]*?<\/content>/.test(text)
}

/** **召回专用事实型扩充**（⛔ 不动 `FACTUAL_FAIL_RE` —— 它同时驱动 T2 gap 口径）。
 *  `cannot read … binary file` = "读取目标不可读"这一事实，不是知识缺口 ⇒ 不触发经验召回。 */

export const RECALL_FACTUAL_EXTRA_RE = /cannot read|binary file|is not a text file|not valid utf-8|not utf-8/i

/** 🔴 （读数误报 · 主会话）：**资源/限额类错误不算知识缺口** —— 派子 agent 时命中
 *  `Error: subagent limit reached (active child limit: 8)`，被 `failKindOf` 判成 knowledge ⇒ 注入无关经验
 *  （EXP-AER-001「更新标准要校验旧流程」），与实际处境毫无关系。这类"等一下/少开几个就好"的错误不触发经验召回。
 *  ⛔ 只收明确的限额/限流/容量措辞；⛔ 不改 `failKindOf`（T2 gap 口径原样）。 */

export const RECALL_QUOTA_RE = /active child limit|subagent limit|rate limit|rate-limited|quota exceeded|too many (active|requests|children|open files)|capacity exceeded|max(imum)? [^.\n]{0,24}reached|limit reached/i

/** **query 归一化**（通用，不只权限族）——
 *  ① 工具名：exec/读写类通用工具名不入 query（`read`/`pwsh` 与语料字段名撞词）；
 *  ② 仓库绝对路径剥离为 `<path>`（`仓库根\work\…` 会与账本的 `work/ai-os` 假重叠）。 */

export const COMMON_TOOL_NAME_RE = /^(pwsh|powershell|bash|sh|zsh|cmd|cmd\.exe|exec|shell|run|terminal|read|write|edit|grep|glob|list|task|job_kill|auto_capability|work_report)$/i
/** 权限失败的**判别词**行（保留优先级高于重复的权限行）。 */

export const PERMISSION_DETAIL_RE = /HRESULT|0x80041003|PermissionDenied|CimException|Win32_Process|Get-CimInstance|Errno\s*13|WinError\s*5/i
/** （读数 · V1 终验）：**剥任意绝对路径的目录部分**（保留末段文件名）。
 *  背景： 只剥 `仓库根\` 前缀；V1 的临时目录 `<旧脑根>\<文件>\tmp\dsh-…` 未被剥，其 token
 *  （`ai`/`scratch`/`tmp`）与台账条目假重叠 ⇒ 命中 Entry #17/#19（误报）。兼容 repr 的双反斜杠形态。
 *  ⛔ 只用于 query 构造；不改检索器/阈值。 */

export function resultTextOf(result: any): string {
  let text = ''
  try {
    const c = result !== null && result !== undefined ? result.content : undefined
    if (Array.isArray(c)) {
      for (const x of c) text += String(x !== null && x !== undefined && x.text !== undefined ? x.text : '') + '\n'
    } else if (typeof c === 'string') {
      text = c
    } else if (result !== null && result !== undefined && typeof result.output === 'string') {
      text = result.output
    }
  } catch { /* 取不到 ⇒ 空 */ }
  return text
}

/** 纯函数：本拍是否触发经验召回。
 *  `unknown-tool` = 调了不存在/被 restrict 的工具（DSH 最硬信号）；
 *  `permission-error` = 权限/沙箱族失败（选 B：权限族要能自然出现）；
 *  `exec-permission-error` = **exec 非零退出未标 isError**但文本含 `[exit code: N≠0]` / `EXITCODE: N≠0` + 权限特征（/）；
 *  `knowledge-error` = 非事实型失败（事实型失败不触发 —— 沿用 T2 口径）。 */

export function recallTriggerOf(result: any, toolName: string = ''): 'unknown-tool' | 'knowledge-error' | 'permission-error' | 'exec-permission-error' | 'exec-encoding-error' | null {
  if (result === null || result === undefined) return null
  const text = resultTextOf(result)
  if (result.isError !== true) {
    // 🔴 /DSH 里 pwsh 非零退出**不计入 isError**（读数 ok:true），
    //   而权限错误大量发生在 shell 命令里 ⇒ 用「非零退出标记 + 权限特征」补一条触发。
    //    读数修正：**子 agent 工具结果用 `EXITCODE: 1`**（不是 `[exit code: 1]`）⇒ 两种都认。
    //   🔴 （读数 · R3）：还有 `EXIT=1` / `exit2=1` / `EXITCODE=0`（等号）⇒ 交给
    //   `EXIT_MARK_RE`（通用解析器）。
    //   🔴 来源门/形态门（R2 误触发）：`read/grep/...` 的结果是数据 —— 其正文里的
    //   `PermissionError` + `[exit code: 1]` 示例不构成执行失败；`<path><content>` 文件转储同理。
    //   ⛔ 不改其它 ok:true 结果的行为；tool 名未知（旧纯函数调用）保留旧行为。
    if (isExecToolName(toolName) === false || looksLikeFileDump(text)) return null
    // 🔴 （V3 误报）：exec 输出里**嵌入了文档内容**（pwsh 打印 PITFALLS 预览含 「拒绝访问」+
    //   「[exit code: 1]」）⇒ 必须有**错误上下文标记**才算执行失败（⛔ 只影响本分支）。
    if (!EXEC_ERROR_CONTEXT_RE.test(text)) return null
    if (EXIT_MARK_RE.test(text) && PERMISSION_FAIL_RE.test(text)) return 'exec-permission-error'
    // 编码类失败 —— 同一条「执行失败」门，只换特征词。
    //   顺序在权限之后：同一输出两者都命中时按权限族（权限的处置更硬）；⛔ 不影响 exit=0 / 无错误上下文的输出。
    if (EXIT_MARK_RE.test(text) && ENCODING_FAIL_RE.test(text)) return 'exec-encoding-error'
    return null
  }
  if (/UNKNOWN_TOOL|unknown tool/i.test(text)) return 'unknown-tool'
  if (PERMISSION_FAIL_RE.test(text)) return 'permission-error'
  // 🔴 （R3 误报）：读二进制/非文本失败 = 事实型（⛔ 不改 failKindOf；只在此入口短路）。
  if (RECALL_FACTUAL_EXTRA_RE.test(text)) return null
  // 限额/限流/容量类错误 = 资源问题，不是知识缺口 ⇒ 不触发经验召回。
  if (RECALL_QUOTA_RE.test(text)) return null
  return failKindOf(result) === 'knowledge' ? 'knowledge-error' : null
}

/** 纯函数：召回查询 = 失败文本要点（截断）+ 可选工具名 + 参数里的命令/路径。
 *  ① 通用工具名（read/pwsh/…）不入 query；② 权限行**去重**且**判别词行优先**；
 *  ③ 仓库绝对路径剥离为 `<path>`；④ **乱码输入先归一化**（见 `looksMojibake()`）；
 *  ⛔ 不改检索算法/条数（仍由 experience_push 决定）。 */

/** 失败输出是否被控制台解码污染（替换字符 / NUL / GBK-as-UTF8 典型 Latin-1 连串）。
 *  为什么需要：查询取自失败输出原文 ⇒ 失败本身是编码问题（GBK/乱码）时 query 也是乱码，
 *  词面通道必然 0 命中（0 命中 ≠ 经验库没有）。⇒ 乱码时改为「错误分类 + ASCII 签名 + 规范词」。 */
function looksMojibake(s: string): boolean {
  if (s === '') return false
  if (/[\uFFFD\x00]/.test(s)) return true
  return /[À-ÿĂ-ž]{3,}/.test(s)
}

/** 从乱码文本里抢救 ASCII 签名（`UnicodeEncodeError` / `SyntaxError` / `gbk` / 路径片段…）。 */
function salvageAsciiTokens(s: string): string[] {
  const found = s.match(/[A-Za-z][A-Za-z0-9_.:\\/-]{2,}/g) || []
  const out: string[] = []
  const seen = new Set<string>()
  for (const t of found) {
    const k = t.toLowerCase()
    if (seen.has(k)) continue
    seen.add(k)
    out.push(t)
    if (out.length >= 8) break
  }
  return out
}

/** 失败分类标签（与 `recallTriggerOf()` 的分类同口径，只用于构造 query 词）。 */
function recallClassOf(raw: string): string {
  if (ENCODING_FAIL_RE.test(raw) || /Unicode(Encode|Decode)Error|codec/i.test(raw)) return 'encoding-error'
  if (/SyntaxError|Unexpected token/i.test(raw)) return 'syntax-error'
  if (PERMISSION_FAIL_RE.test(raw)) return 'permission-error'
  return 'tool-error'
}

export function buildExperienceQuery(tool: string, args: any, result: any): string {
  const parts: string[] = []
  const toolName = String(tool === null || tool === undefined ? '' : tool).trim()
  if (toolName !== '' && !COMMON_TOOL_NAME_RE.test(toolName)) parts.push(toolName)
  const raw = resultTextOf(result)
  let text = stripRepoPaths(raw).replace(/\s+/g, ' ').trim()
  const mojibake = looksMojibake(raw)
  // 权限族失败时，`clip(text,160)` 常只截到路径/`EXITCODE`，把
  //   `PermissionError` 截掉 ⇒ experience_push 0 命中。⇒ 优先取**含权限特征的行**放进 query。
// 在此基础上**去重**并让**判别词行**（HRESULT/0x80041003/PermissionDenied/…）优先。
  if (PERMISSION_FAIL_RE.test(raw)) {
// 判别词行（HRESULT/PermissionDenied/…）即使不被 PERMISSION_FAIL_RE 覆盖
    //   （如 `PermissionDenied` 无空格）也要保留 —— 它们才是该场景的判别信号。
    const lines = raw.split(/\r?\n/).map((l) => stripRepoPaths(l).trim())
      .filter((l) => l !== '' && (PERMISSION_FAIL_RE.test(l) || PERMISSION_DETAIL_RE.test(l)))
    if (lines.length > 0) {
      const out: string[] = []
      const seen = new Set<string>()
      const push = (l: string): void => {
        const key = l.replace(/\s+/g, ' ').toLowerCase()
        if (seen.has(key)) return
        seen.add(key)
        out.push(l)
      }
      for (const l of lines) if (PERMISSION_DETAIL_RE.test(l)) push(l)   // 判别词行优先
      for (const l of lines) if (!PERMISSION_DETAIL_RE.test(l)) push(l)  // 其余权限行补位
      text = out.slice(0, 2).join(' ')
    }
  }
  // 编码类失败同样优先取**编码特征行** —— `clip(160)` 会截掉
  //   `UnicodeDecodeError: 'gbk' codec can't decode …` 之外的内容，直接命中编码族（/族卡）。
  if (!PERMISSION_FAIL_RE.test(raw) && ENCODING_FAIL_RE.test(raw)) {
    const lines = raw.split(/\r?\n/).map((l) => stripRepoPaths(l).trim())
      .filter((l) => l !== '' && (ENCODING_FAIL_RE.test(l) || ENCODING_DETAIL_RE.test(l)))
    if (lines.length > 0) {
      const out: string[] = []
      const seen = new Set<string>()
      for (const l of lines) {
        const key = l.replace(/\s+/g, ' ').toLowerCase()
        if (seen.has(key)) continue
        seen.add(key)
        out.push(l)
      }
      text = out.slice(0, 2).join(' ')
    }
    // 纯乱码 query ⇒ 词面通道 0 命中：当特征行里**不含 3+ 连续 ASCII 字母**时补一组编码族规范词。
    //  ⛔ 不改检索算法，只补 query 词。
    if (!mojibake && !/[A-Za-z]{3,}/.test(text)) {
      text = (text + ' 中文乱码 编码 gbk utf-8 codec mojibake').trim()
    }
  }
  // 🔴 乱码无差别归一化：查询不携带乱码原文 —— 只用「错误分类 + ASCII 签名 + 编码族规范词」。
  //   否则乱码片段会与真正的判别词竞争，检索 0 命中（实际复现：`��{\x00 SyntaxError…` ⇒ 0 命中）。
  if (mojibake) {
    const klass = recallClassOf(raw)
    const salvaged = salvageAsciiTokens(raw)
    const canon = klass === 'encoding-error' ? '中文乱码 编码 gbk utf-8 codec mojibake' : ''
    text = [klass, salvaged.join(' '), canon].filter((x) => x !== '').join(' ').trim()
  }
  if (text !== '') parts.push(clip(text, 160))
  // 🔴 （读数 · V1）：权限族失败时**丢弃命令/查询参数** —— `python -m unittest -v` 的
  //   `unittest` 等任务上下文词会与错误签名竞争，检索到无关台账（Entry #17 = 误报）。错误签名自足；
  //   ⛔ 非权限场景仍保留命令上下文（为 unknown-tool / 知识型失败留路）。
  // 编码族失败同理（`json`/`report` 等任务词会与 `codec`/`0xff` 竞争）⇒ 一并丢弃命令参数。
  const permFail = PERMISSION_FAIL_RE.test(raw) || ENCODING_FAIL_RE.test(raw)
  try {
    const a = args !== null && args !== undefined && typeof args === 'object' ? args as Record<string, any> : {}
    const keys = permFail ? ['path', 'file_path'] : ['path', 'file_path', 'command', 'query']
    for (const k of keys) {
      const v = a[k]
      if (typeof v === 'string' && v !== '') parts.push(clip(stripRepoPaths(v), 80))
    }
  } catch { /* 参数取不到 ⇒ 只用失败文本 */ }
  return parts.join(' ').trim()
}

/** 纯函数：限额 + 去重（每会话 ≤N 次、相邻 ≥2 turn、同一 query 不连发）。 */

export const WORK_REPORT_FIELD_MAX = 500
/** 每个轴（need / concern）的条数上限 —— 词表"合计 ≤6"的落地。 */

export const WORK_REPORT_AXIS_MAX = 6
/** 每会话**调用预算**（授权「调用预算也可以有」· 首版值 8 ⇒ 改这一处即可）。 */

export function buildWorkReport(session: string, args: unknown, now: number): { ok: boolean; why: string; rep: WorkReportRecord | null } {
  const a: Record<string, unknown> = args !== null && typeof args === 'object' ? args as Record<string, unknown> : {}
  const str = (v: unknown): string => typeof v === 'string' ? v.trim().slice(0, WORK_REPORT_FIELD_MAX) : ''
  const list = (v: unknown): string[] => {
    if (!Array.isArray(v)) return []
    const out: string[] = []
    for (const x of v) {
      const s = str(x)
      if (s !== '' && !out.includes(s)) out.push(s)
      if (out.length >= WORK_REPORT_AXIS_MAX) break
    }
    return out
  }
  const what = str(a.what)
  if (what === '') return { ok: false, why: 'what 必填（一句话在做什么）', rep: null }
  const confirmed = str(a.confirmed)
  if (confirmed !== 'user' && confirmed !== 'agent-inferred') {
    return { ok: false, why: 'confirmed 必填，且只能是 user / agent-inferred', rep: null }
  }
  const need = list(a.need)
  const concern = list(a.concern)
  const fix = str(a.fix)
  const note = str(a.note)
  const card = str(a.card)
  // 两步式显式 axes —— **只收词表值**（非词表值丢弃，⛔ 不猜同义词）
  const axisList = (v: unknown, allow: readonly string[]): string[] => {
    if (!Array.isArray(v)) return []
    const out: string[] = []
    for (const x of v) {
      const s = str(x)
      if (s !== '' && allow.includes(s) && !out.includes(s)) out.push(s)
      if (out.length >= WORK_REPORT_AXIS_MAX) break
    }
    return out
  }
  const axesIn: Record<string, unknown> = a.axes !== null && typeof a.axes === 'object' ? a.axes as Record<string, unknown> : {}
  const axes = {
    domain: axisList(axesIn.domain, WR_DOMAIN_VALUES),
    help: axisList(axesIn.help, WR_HELP_TYPES),
    concern: axisList(axesIn.concern, WR_CONCERN_VALUES),
  }
  const chars = what.length + need.join(' ').length + concern.join(' ').length + fix.length + note.length + card.length
  return {
    ok: true,
    why: '',
    rep: {
      id: 'wr-' + String(now).slice(-9) + '-' + Math.random().toString(36).slice(2, 6),
      session, at: now, chars,
      needCount: need.length, concernCount: concern.length,
      confirmed, hasFix: fix !== '', hasCard: card !== '',
      what, need, concern, fix, note, card, axes,
    },
  }
}

/** 记录（内存环形 + 探针派生量）；返回该会话当前条数。⛔ 不写盘、⛔ 不记原文。 */

export const WORK_REPORT_RETRIEVAL_TIMEOUT_MS = 1500
/** 内联检索取数上限（与 `stage4_probe.json` 默认值同口径 · ⛔ 不读该开关文件）。
 *  🔴 8 → **3**。依据：9 份回放访谈里 7 份指向「条数」是第一杠杆
 *     （`6884`：8 条里 1 条相关 = 12.5%，压到 3 条 = 33%；`95e4`：只开 rank 1）；
 *     大样本里候选打开也集中在 rank 1（卡第 38/39 批）。 */

export const WORK_REPORT_RETRIEVAL_MAX_CANDIDATES = 3

export const WORK_REPORT_RETRIEVAL_MAX_PER_SOURCE = 3

/** 一句话介绍的截断长度（3 条 × 80 字 ⇒ 上下文预算更可控）。 */

export const WORK_REPORT_RETRIEVAL_SUMMARY_CHARS = 80

/** 清洗成"一句话"：去标题井号 / 成对强调符 / 行首列表与引用 / 反引号 + 压缩空白。
 *  ⚠️ 只去**成对**标记（`**` `__` `` ` ``）—— 单词内的下划线/连字符是**标识符**，⛔ 不得删
 *  （读数：删掉后 `NOT_APPLICABLE` 变成 `NOTAPPLICABLE`、文件名被粘成一串）。 */

export function cleanOneLine(raw: any): string {
  return String(raw === null || raw === undefined ? '' : raw)
    .replace(/^#+\s*/gm, '')
    .replace(/\*\*|__|`/g, '')
    .replace(/^\s*[>*-]\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * **纯函数**：候选的「一句话介绍」。
 * · 能力 / 技能 / MCP → 用 `description`（trigger 首句，最像"一句话介绍"）
 * · 语料 / 账本 / 经验 → 先用 `name`（`Entry #63` / `ASSERT-RECALC-001` 这类可读名），再补 40 字描述
 *   （账本 chunk 的 `description` 是**正文开头**，直接当"介绍"会出来一段正文 —— 实际踩到）
 */

export function summaryForCandidate(kind: string, name: string, desc: string): string {
  const d = cleanOneLine(desc)
  const n = cleanOneLine(name)
  if (kind === 'capability' || kind === 'skill' || kind === 'mcp' || kind === 'tool') {
    return clip(d !== '' ? d : n, WORK_REPORT_RETRIEVAL_SUMMARY_CHARS)
  }
  const tail = clip(d, 40)
  const head = n !== '' ? n : ''
  if (head !== '' && tail !== '') return clip(head + ' · ' + tail, WORK_REPORT_RETRIEVAL_SUMMARY_CHARS)
  return clip(head !== '' ? head : tail, WORK_REPORT_RETRIEVAL_SUMMARY_CHARS)
}

/** 候选归一后的最小结构（**给宿主的唯一字段白名单** · ⛔ 不含正文 / `preview` 原文）。 */

export interface RetrievalCandidate {
  id: string
  source: string
  role: string
  channels: string[]
  /** 位置：仓库相对路径（空串 = 该来源无本地路径，如外部缓存） */
  path: string
  /** 一句话介绍：能力用 description；语料/账本用 name（截断）· ⛔ 不是正文 */
  summary: string
}

/**
 * **纯函数**：`candidate-set/v1` ⇒ 给宿主的最小结构（`CHANNEL §六` 边界）。
 * 🔴 约定「返回的应该是**位置 + 每一个能力的一句话介绍**」
 *    ⇒ 白名单加 `path` / `summary`（仍是派生量：路径 + 一句话，⛔ 不带正文）。
 * 空项跳过、字段强制成字符串 ⇒ 单测可直接断言"没有原文泄漏"。
 */

export function retrievalCandidatesOf(set: any): RetrievalCandidate[] {
  const cands = set !== null && set !== undefined && Array.isArray(set.candidates) ? set.candidates : []
  const out: RetrievalCandidate[] = []
  for (const c of cands) {
    if (c === null || c === undefined) continue
    const src = c.source !== null && c.source !== undefined && typeof c.source === 'object' ? c.source : {}
    const descRaw = c.preview !== undefined && c.preview !== null ? c.preview
      : (c.description !== undefined && c.description !== null ? c.description : '')
    // 「每一类能力都可以专门做一个关于自己的介绍；候选返回时直接返回它 + 位置」
    //    ⇒ 能力自带 `intro`（frontmatter 字段）优先；没有 intro 的（语料 / 账本）才走 name/description 规则。
    const intro = cleanOneLine(c.intro)
    out.push({
      id: String(c.id !== undefined && c.id !== null ? c.id : ''),
      source: String(src.id !== undefined && src.id !== null ? src.id : ''),
      role: String(c.role !== undefined && c.role !== null ? c.role : ''),
      channels: Array.isArray(c.hit_channels) ? c.hit_channels.map((x: any) => String(x)) : [],
      path: String(c.local_path !== undefined && c.local_path !== null ? c.local_path : ''),
      summary: intro !== ''
        ? clip(intro, WORK_REPORT_RETRIEVAL_SUMMARY_CHARS)
        : summaryForCandidate(
          String(c.kind !== undefined && c.kind !== null ? c.kind : ''),
          String(c.name !== undefined && c.name !== null ? c.name : ''),
          String(descRaw),
        ),
    })
  }
  return out
}

/**
 * 🔴 按「与 `what` 的词面重合度」**重排**候选（稳定排序 · ⛔ 不删候选 · ⛔ 不做语义）。
 *   依据：9 份回放访谈中 7 份指向排序/条数——`95e4` 只打开 rank 1；`6884` 候选名与 what 名词重合才开，
 *     `frontend-ui` / `senior-engineer` 这类通用卡每次都出现、稀释焦点（卡第 38/39 批）。
 *   与检索器 `rank_key()` 的关系：那是**通道多样性**排序（语料侧）；这里只做**后置稳定重排** ——
 *     ⛔ 不改检索器、⛔ 不丢候选，同分时保持原顺序（检索器顺序仍是第二判据）。
 */

export function rerankCandidatesByWhat(cands: RetrievalCandidate[], what: string): RetrievalCandidate[] {
  const w = tokenSetOf(what)
  if (w.size === 0 || cands.length < 2) return cands
  const scoreOf = (c: RetrievalCandidate): number => {
    const t = tokenSetOf([c.id, c.summary, c.path].join(' '))
    let hit = 0
    for (const x of t) if (w.has(x)) hit++
    return hit
  }
  return cands
    .map((c, i) => ({ c, i, s: scoreOf(c) }))
    .sort((a, b) => (b.s - a.s) || (a.i - b.i))
    .map(x => x.c)
}

/**
 * **能力候选后的「打开约束」开关**。
 * 为什么： 只返回「id / 一句话介绍 / 位置」——`intro` 足以让人判断"这跟我的任务搭不搭、
 *   大概怎么做"，于是 Agent**看到候选却一次都不打开文件**（15 会话 1950 次
 *   工具调用 / 16 次 auto_capability / capabilities 被打开 1 次）。缺的不是更详细的介绍，是
 *   「什么时候该打开」这条**动作指向**。
 * 口径「适配 或 任务需要时，请打开详细能力」。
 * 开关：`.aios/retrieval-nudge.json` —— **缺省 = 开**（这是要验证的机制）；
 *   `{"enabled": false}` ⇒ 回到 的纯展示句。读侧容忍 BOM· 改文件即生效。
 */

export function retrievalNudgeEnabled(): boolean {
  try {
    const raw = JSON.parse(readFileSync(join(aiosStateDir(), 'retrieval-nudge.json'), 'utf8').replace(/^\uFEFF/, ''))
    return !(raw !== null && typeof raw === 'object' && (raw as Record<string, unknown>).enabled === false)
  } catch {
    return true // 缺省开（文件不存在 / 读失败 ⇒ 仍然给约束，⛔ 不因缺省而静默退化）
  }
}

/**
 *  约束句（纯文本，便于自测与替换）。
 * 🔴 **回退** 的「收益 / 覆盖 / 缺口」三版诱导 —— 能力出现时只需要两样东西：
 *   ① 候选本身的**描述**（三行：id / 一句话介绍 / → 位置）；
 *   ② 一个可机械核对的**打开动作指向**（"打开对应能力文件"）。
 *   诱导文案不再放在这里 —— 它应该在「**工具出现时**」的注入里（`eventHintText`）。
 */

export function inlineRetrieval(rep: WorkReportRecord, owner: string): Promise<Record<string, unknown>> {
  const t0 = Date.now()
  const st = SESSIONS.get(owner)
  const wc = st !== undefined ? st.wc : ({ historyCoverage: 'complete' } as any)
  let req: Record<string, unknown>
  try {
    req = buildRetrievalRequestFromWorkReport(rep, wc, {
      maxCandidates: WORK_REPORT_RETRIEVAL_MAX_CANDIDATES,
      maxPerSource: WORK_REPORT_RETRIEVAL_MAX_PER_SOURCE,
    } as any)
  } catch (err) {
    const ms = Date.now() - t0
    emit({
      ev: 'retrieval-corpus', obs: OBS, session: owner, id: rep.id, state: 'request-failed',
      detail: clip(String(err), 120), chars: rep.chars, ms, at: Date.now(), mono: mono(),
    })
    return Promise.resolve({ state: 'request-failed', candidates: [], channels: [], matchedBeforeBudget: -1, ms })
  }
  return new Promise(resolve => {
    spawnJson(STAGE4_RETRIEVAL_ENTRY, { request: req }, WORK_REPORT_RETRIEVAL_TIMEOUT_MS, (outcome, set, detail) => {
      const ms = Date.now() - t0
      if (outcome !== 'ok' || set === null || set === undefined) {
        emit({
          ev: 'retrieval-corpus', obs: OBS, session: owner, id: rep.id, state: outcome,
          detail: detail !== undefined ? detail : null, chars: rep.chars, ms,
          at: Date.now(), mono: mono(),
        })
        resolve({ state: outcome, candidates: [], channels: [], matchedBeforeBudget: -1, ms })
        return
      }
      // 后置重排（按与 what 的词面重合度 · 稳定 · ⛔ 不删候选），再交渲染层截 top-N
      const cands = rerankCandidatesByWhat(retrievalCandidatesOf(set), rep.what)
      // 🔴 （设计稿 §4.4）：记下**已返回给宿主**的能力 id ⇒ 阶段注入据此去重。
      //    ⚠️ 只记 `capabilities/` 下的能力包（阶段注入的候选池同口径）。
      rememberCapabilityIds(owner, cands.filter(c => isCapabilityCandidatePath(c.path)).map(c => c.id))
      const budget = (set.budget_applied !== null && set.budget_applied !== undefined ? set.budget_applied : {}) as Record<string, any>
      const div = (set.diversity !== null && set.diversity !== undefined ? set.diversity : {}) as Record<string, any>
      const matched = typeof budget.matched_before_budget === 'number' ? budget.matched_before_budget : -1
      const channels = Array.isArray(div.channels_used) ? div.channels_used.map((x: any) => String(x)) : []
      emit({
        ev: 'retrieval-corpus', obs: OBS, session: owner, id: rep.id, state: 'ok',
        chars: rep.chars, needCount: rep.needCount, concernCount: rep.concernCount,
        candidates: cands.length, matchedBeforeBudget: matched, channels, ms,
        requestSource: 'work-report', nudge: retrievalNudgeEnabled(), at: Date.now(), mono: mono(),
      })
      resolve({ state: 'ok', candidates: cands, matchedBeforeBudget: matched, channels, ms })
    })
  })
}

/** 注册工具（**失败透明**：任何异常只记探针，⛔ 绝不阻塞插件加载）。 */
