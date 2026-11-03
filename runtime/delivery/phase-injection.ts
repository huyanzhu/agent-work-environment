/**
 * phase-injection.ts — 从 `runtime/aios-activation.ts` 的 `apply()` 提炼。
 * 内容 = `tools/post-execute` 里「**Step B′ · 递送**」段的完整依赖闭包（104 个顶层声明逐字搬入，
 * 只加 `export`）＋ `applyStepBDelivery()`（原段语句原样搬入，仅整体缩进 −2）。
 * 🔴 其中「阶段打分 / 候选渲染」闭包（22 个顶层声明）已**纯移动**到
 *   `runtime/activation/phase-candidates.ts`；本文件以 `import` + `export { … }` 保持原导出面与调用点。
 * 🔴 行为零变化：门控顺序 / 探针字段 / 去重口径 / `try/catch` 边界 / `await next()` 次数**逐字保留**；
 *   段内唯一的跨段可变状态 `R3_DISARM_PENDING` 随声明搬来，另加 `setR3DisarmPending()`（ESM 导入绑定只读）。
 * ⛔ 本文件为机械搬家产物（`scratch/_b2_extract.py` 可复现）；改逻辑请改回主模块并跑 184 项自测。
 */

import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { OBS, WORK_REPORTS, aiosStateDir, clip, emit, mono, resolveScript, resolveToolScript, userMessageOf, EXEC_TOOL_RE, isExecToolName, stripRepoPaths, noteCatchFail } from '../diagnostics/probe.ts'
import type { PendingDelivery, SessionState, TaskCursor } from '../session/session-state.ts'
import { SESSIONS, sessionIdOf } from '../session/session-state.ts'
import type { ActivityItem, WorkContext } from '../session/work-context.ts'
import { failKindOf, failStreakOf } from '../session/work-context.ts'
import { spawnJsonAsync } from '../retrieval/python-bridge.ts'
import type { AiPhase, PhaseInjectSlot } from '../activation/phase-policy.ts'
import { CAP_NUDGE_NEED, CAP_NUDGE_TEXT, PHASE_BUDGET_CANDIDATES, capCellsConfig, capNudgeEnabled, domainInjectEnabled, missingCapRecordsOnCard, phaseInjectEnabled, phaseInjectSlotOf, phaseOf } from '../activation/phase-policy.ts'
import { PHASE_TITLE, applyDeclaredDomainInjection } from '../activation/declared-domain.ts'
import { readDeliveryProbe, readReminderProbe, readInjectProbe, deliverySourcesActive, noteProbeAuth, sessionAllowsProbe } from './pending-delivery.ts'

import { focusCardOf, myOccupiedCards, reminderFor, scanCards } from '../session/lifecycle.ts'
import { STAGE4_RETRIEVAL_ENTRY, WR_HELP_TYPES, WR_DOMAIN_VALUES, WR_CONCERN_VALUES, RETURNED_CAPABILITY_IDS, rememberCapabilityIds, isCapabilityCandidatePath, PERMISSION_FAIL_RE, EXIT_MARK_RE, EXEC_ERROR_CONTEXT_RE, ENCODING_FAIL_RE, ENCODING_DETAIL_RE, looksLikeFileDump, RECALL_FACTUAL_EXTRA_RE, RECALL_QUOTA_RE, COMMON_TOOL_NAME_RE, PERMISSION_DETAIL_RE, resultTextOf, recallTriggerOf, buildExperienceQuery, WORK_REPORT_RETRIEVAL_SUMMARY_CHARS, cleanOneLine, summaryForCandidate, retrievalCandidatesOf } from '../retrieval/request-builder.ts'
import type { RetrievalCandidate } from '../retrieval/request-builder.ts'
import type { WorkReportRecord } from '../diagnostics/probe.ts'
import { tokensOf, latestWorkReport, phaseMaxCandidates, PHASE_RETRIEVAL_TIMEOUT_MS, PHASE_TOPIC_MAX, PHASE_TOPIC_SEP, phaseTopicOf, PHASE_DEFAULT_HELP, vocabPicked, phaseAxesOf, buildPhaseRetrievalRequest, phaseRequestOf, PHASE_SCORE_W, PHASE_CHANNEL_W, PHASE_COVERAGE_FULL, hasCapScoreSignals, phaseCapScoreOf, renderPhaseCandidates, INJECT_MAX_WITHOUT_RETRIEVAL, injectAllowedByBudget, EXPERIENCE_RECALL_MIN_SCORE, renderExperienceRecall } from '../activation/phase-candidates.ts'
import type { ExperienceRecallSlot } from '../retrieval/experience-recall.ts'
import { EXPERIENCE_RECALL_ENTRY, EXPERIENCE_RECALL_TIMEOUT_MS, EXPERIENCE_RECALL_MAX_PER_SESSION, EXPERIENCE_RECALL_MIN_TURN_GAP, EXPERIENCE_RECALL, experienceRecallEnabled, emptyRecallSlot, recallAllowed } from '../retrieval/experience-recall.ts'
import type { NodeId } from './probe-state.ts'
import { PUSH_RELEASE_CMD_RE, pushReleaseHintText, PUSH_RELEASE_HINT_SEEN, RUNTIME_EDIT_HINT_SEEN, RUNTIME_EDIT_PATH_RE, RUNTIME_EDIT_TOOL_RE, runtimeEditHintText, NODE_CORPUS_DOMAINS_RE, NODE_CORPUS_PITFALLS_RE, NODE_CORPUS_DIGEST_RE, NODE_INDEX_BUILD_RE, NODE_REGRESSION_CMD_RE, NODE_HELP_ONLY_RE, corpusNodeHintText, indexNodeHintText, regressionNodeHintText, nodeHintTextOf, NODE_INJECT, emptyNodeInjectSlot, nodeInjectSlotOf, isCorpusEditTarget, nodeHintOf, CMD_ARG_KEYS, pickCommandArg } from './node-hints.ts'
import type { InjectEvent, EventSlot, NodeInjectSlot } from './probe-state.ts'
import { DELIVERY_SENT, INJECT_EVENTS, emptyEventSlot, FIRST_STEP_INJECT_ENABLED, firstStepInjectOnce, DELIVERY_ERR_SEEN, detectEvents, shouldPublishEvent, R3_DISARM_PENDING, setR3DisarmPending, PENDING_DELIVERY_MAX_AGE_MS, pendingStaleReason, eventHintText, nodeTargetPathOf } from './probe-state.ts'
import { buildFirstStepRetrievalRequest, capabilityIdsOf, detectRetrievalRequest, RETRIEVAL_WORDS } from './probe-state.ts'
export { tokensOf, latestWorkReport, phaseMaxCandidates, PHASE_RETRIEVAL_TIMEOUT_MS, PHASE_TOPIC_MAX, PHASE_TOPIC_SEP, phaseTopicOf, PHASE_DEFAULT_HELP, vocabPicked, phaseAxesOf, buildPhaseRetrievalRequest, phaseRequestOf, PHASE_SCORE_W, PHASE_CHANNEL_W, PHASE_COVERAGE_FULL, hasCapScoreSignals, phaseCapScoreOf, renderPhaseCandidates, INJECT_MAX_WITHOUT_RETRIEVAL, injectAllowedByBudget, EXPERIENCE_RECALL_MIN_SCORE, renderExperienceRecall } from '../activation/phase-candidates.ts'

/**
 * **瞬时工作方向签名**（「在内存中处理 todo 内容，形成临时的工作方向签名」）。
 * 实现为**机械 token 集合**：拉丁词 + CJK 2-gram（避开分词依赖）。
 * 🔴 该集合是**内存态 · 不落盘**（见文件头两层纪律）。
 * ⚠️ 它**不是**语义标签（"数据库访问策略"这类标签需要 LLM）⇒ 只用于**一致性比较**，不作事实。
 */
export async function applyStepBDelivery(
  exec: any,
  result: any,
  next: any,
): Promise<any> {
  // ── Step B′ · 递送（**默认全部关闭** · 开关为本地文件 · 每次重读）─────────────────
  //    🔴 顺序：先读开关（**读不到即透明**）⇒ 再 `await next()`（**恰好一次 · 不额外等待**）
  //       ⇒ 再决定是否附加。**任何失败都原样透传下游 decision**。
  //    🔴 **不改 `block` 语义**（不动工具原始结果）⇒ 只在 `accept` 上附加 `additionalContexts`
  //    ① v8 静态 marker（历史验证件 · `_delivery_probe.json`）
  //    ② **提醒型递送**（批准 · `_reminder_probe.json`）
  const probe = readDeliveryProbe()
  const remind = readReminderProbe()
  // 🔴 **三个递送来源各自独立**（修 · 原实现是**静默失效**）：
  //    ① 静态 marker（`delivery_probe.json`）· ② 提醒（`reminder_probe.json`）· ③ **候选（阶段 4）**
  //    ⚠️ ③ 的开关是 `_stage4_probe.json` 的 `delivery:"deliver"` —— 与 ①② **不是同一个文件**。
  //       原实现写成「①② 皆空 ⇒ `return next()`」⇒ 把 ③ 的授权也交给了 ①②：
  //       一旦两个探针都不在（或提醒被刻意关掉）⇒ 候选**即便已排队也永远递送不出去**，
  //       且**零报错、零探针记录**（`stage4-deliver` 恒为 0）。⇒ 此处只判"有没有活要干"。
  const preSession = sessionIdOf(exec && exec.agent)
  const preState = SESSIONS.get(preSession)
  // 🔴 v55 兜底：hook 可能没把 `card-cmd` 送到本会话 ⇒ `s.cards` 陈旧 ⇒
  //    注入判定看不到「本会话占用的 Executing 卡」⇒ 整段注入静默不发生。
  //    这里在判定前**只读地现扫一次**（低成本；⛔ 不写文件、⛔ 不改卡、不改变判定方向）。
  if (preState !== undefined) {
    try {
      if (myOccupiedCards(preState).length === 0) {
        const freshCards = scanCards()
        preState.cards = freshCards
        emit({
          ev: 'card-rescan-fallback', obs: OBS, session: preSession,
          hit: myOccupiedCards(preState).length, cards: freshCards.length,
          note: 'hook 未送 card-cmd ⇒ 注入判定前现扫一次（v55 · ⛔ 不猜）',
          at: Date.now(), mono: mono(),
        })
      }
    } catch (err) {
      noteCatchFail('inject:rescan-fallback', err)
    }
  }
  const hasQueuedCandidate = preState !== undefined && preState.pendingDelivery !== null
  // 注入实验是**第四个来源**（与 ①②③ 独立）—— 只要它开着，就不得早退，
  //    否则"提醒关掉/无候选"时会把它一起静默吞掉（与 修过的同类缺陷同源）。
  const injectOn = readInjectProbe() !== null
  // 发布/推送节点提示是**第五个来源**（与 ①②③④ 独立）—— 否则提醒/候选/注入探针都没开时，
  //   「经验召回开关」开着也到不了这里 ⇒ 节点提示会被静默吞掉（与 修过的同类缺陷同源）。
  const pushNodeOn = experienceRecallEnabled()
  // 改本体节点是**第六个来源**（同上，独立于早退门）。
  const runtimeNodeOn = experienceRecallEnabled()
  // 🔴 （经验侧）：三个新节点（N1 改语料 / N2 重建索引 / N3 跑回归门）是**第七个来源**
  //   —— 与 / 同一门控（`experience_recall`），必须**独立**参与早退门，
  //   否则别的来源都没开时节点注入会被静默吞掉（修过的同类缺陷 · 家族）。
  const nodeInjectOn = experienceRecallEnabled()
  if (!deliverySourcesActive(probe, remind, hasQueuedCandidate) && !injectOn && !pushNodeOn && !runtimeNodeOn && !nodeInjectOn) return next()
  const downstream = await next()
  try {
    const session = sessionIdOf(exec && exec.agent)
    // 🔴 开关读到了 ⇒ 记一次"本会话是否被放行"（**含通配** · 每个会话每个开关只落一条）。
    //    没有这行，通配绑定就变成**不可见状态**（事后无法判"插件此刻到底对谁开机"）。
    if (probe !== null) noteProbeAuth('delivery', session, probe.session, session, sessionAllowsProbe(probe.session, session))
    if (remind !== null) noteProbeAuth('reminder', session, remind.session, session, sessionAllowsProbe(remind.session, session))
    if (!downstream || downstream.kind !== 'accept') return downstream
    const extras: Record<string, unknown>[] = []
    // ①·零前 🔴 **关闭告知** —— 自动维护注入因 fire-once 刚被关，
    //   向**触发会话**（接手方 b）注入「已关闭，请询问用户是否开启」（⛔ 不自动重开）。
    if (R3_DISARM_PENDING !== null && R3_DISARM_PENDING.session === session) {
      const p = R3_DISARM_PENDING
      setR3DisarmPending(null)
      emit({ ev: 'r3-disarm-notice', obs: OBS, session, card: p.card, state: 'injected', note: 'fire-once: r3-wake auto-disabled after claim-handoff; ask user to re-enable', at: Date.now(), mono: mono() })
      extras.push(userMessageOf('【AI-OS · R3 自动维护注入已关闭】已向上一手对话注入接手检查（`' + p.card + '`）；自动维护注入（`.aios/r3-wake.json`）已**自动关闭**（fire-once）。**请询问用户是否重新开启**（⛔ 不自动开启）。', 'aios R3 auto-disabled notice'))
    }
    // ①·零·a 🔴 **发布/推送节点** —— 只盯「发布」「推送」两个动作。
    //   节点从 exec 的参数里可发现（命令文本）⇒ 动作发生时给族卡指针 + 核对清单（⛔ 不等到失败）。
    //   每会话一次（push→PR→merge 连做不刷屏）；探针只落命令 clip 片段（⛔ 不落全文）。
    if (pushNodeOn) {
      const pcmd = exec !== null && exec !== undefined && exec.arguments !== null && exec.arguments !== undefined
        ? String((exec.arguments as Record<string, any>).command || '') : ''
      if (pcmd !== '' && PUSH_RELEASE_CMD_RE.test(pcmd)) {
        if (PUSH_RELEASE_HINT_SEEN.has(session)) {
          emit({ ev: 'push-release-hint', obs: OBS, session, trigger: 'push-release-node', state: 'dup', at: Date.now(), mono: mono() })
        } else {
          PUSH_RELEASE_HINT_SEEN.add(session)
          emit({
            ev: 'push-release-hint', obs: OBS, session, trigger: 'push-release-node', state: 'injected',
            cmd: clip(stripRepoPaths(pcmd), 120), ok: !(result && (result as any).isError),
            at: Date.now(), mono: mono(),
          })
          extras.push(userMessageOf(pushReleaseHintText(), 'aios push/release node hint (v49m)'))
        }
      }
    }
    // ①·零·b 🔴 「改本体节点」= 编辑 `runtime/*.ts`。
    //   这类坑零报错、零探针（整段注入静默失效），⇒ 在动作发生的当下给族卡指针 + 四条铁律。
    //   每会话一次；探针只落路径 clip 片段（⛔ 不落正文）。
    if (runtimeNodeOn) {
      const rtool = exec !== null && exec !== undefined && exec.name !== undefined ? String(exec.name) : ''
      const ra = exec !== null && exec !== undefined && exec.arguments !== null && exec.arguments !== undefined
        ? exec.arguments as Record<string, any> : {}
      const rpath = String(ra.file_path || ra.path || ra.new_path || '')
      if (rpath !== '' && RUNTIME_EDIT_TOOL_RE.test(rtool) && RUNTIME_EDIT_PATH_RE.test(rpath)) {
        if (RUNTIME_EDIT_HINT_SEEN.has(session)) {
          emit({ ev: 'runtime-edit-hint', obs: OBS, session, trigger: 'runtime-edit-node', state: 'dup', at: Date.now(), mono: mono() })
        } else {
          RUNTIME_EDIT_HINT_SEEN.add(session)
          emit({
            ev: 'runtime-edit-hint', obs: OBS, session, trigger: 'runtime-edit-node', state: 'injected',
            path: clip(stripRepoPaths(rpath), 120), tool: rtool, at: Date.now(), mono: mono(),
          })
          extras.push(userMessageOf(runtimeEditHintText(), 'aios runtime-edit node hint (v49q)'))
        }
      }
    }
    // ①·零·c 🔴 （经验侧 · 定稿 (a)）：**三个新节点** ——
    //   N1 改语料（`domains/**` / `task_cards/memory/PITFALLS.md`）· N2 重建索引（`semantic_search.py build`）·
    //   N3 跑回归门（`_guard_now.py` / `_scene_probe.py`（含 `--check`）/ `_family_coverage_` / `_fp_ablation_` / `_n30_`）。
    //   高风险动作发生的**当下**给「自检与判据族」指针（⛔ 不注正文；⛔ 门控沿用 `experience_recall`，不新建开关）。
    //   每个节点每会话一次（Set · ⛔ 不用水平状态节流）；重复 ⇒ `state:"dup"`（每节点只报一条）。
    //   本段只用**本段现取**的局部量（`session` / `exec` / `NODE_INJECT`），⛔ 不引用别处 try 块的变量。
    if (nodeInjectOn) {
      const nslot = nodeInjectSlotOf(session)
      const nTool = exec !== null && exec !== undefined && exec.name !== undefined ? String(exec.name) : ''
      const nArgs = exec !== null && exec !== undefined ? exec.arguments : undefined
      const nid = nodeHintOf(nTool, nArgs)
      if (nid !== null) {
        if (nslot.sent.has(nid)) {
          if (!nslot.dupReported.has(nid)) {
            nslot.dupReported.add(nid)
            emit({ ev: 'node-inject', obs: OBS, session, node: nid, state: 'dup', chars: 0, tool: nTool, at: Date.now(), mono: mono() })
          }
        } else {
          nslot.sent.add(nid)
          const nText = nodeHintTextOf(nid)
          // 探针只落**目标 clip 片段**（编辑路径 / 命令），⛔ 不落正文
          const nTarget = nid === 'N1' ? nodeTargetPathOf(nArgs) : pickCommandArg(nArgs)
          emit({
            ev: 'node-inject', obs: OBS, session, node: nid, state: 'injected', chars: nText.length,
            tool: nTool, name: nid === 'N1' ? 'corpus-edit' : (nid === 'N2' ? 'index-build' : 'regression-gate'),
            target: clip(stripRepoPaths(nTarget), 120), at: Date.now(), mono: mono(),
          })
          extras.push(userMessageOf(nText, 'aios node hint (v51c)'))
        }
      }
    }
    // ①·零 **经验召回**（事件触发 · 与能力检索分开；只注入一句经验）
    //   触发：UNKNOWN_TOOL（最硬）/ 权限/沙箱族失败（permission-error）/ 非事实型失败；
    //   ⛔ 其余事实型失败不触发（T2 口径）。
    //   每会话 ≤3 次、相邻 ≥2 turn、同 query 不连发；失败静默（⛔ 不影响工具结果）。
    // 🔴 `s` 是前面那个 `try{}` 的**块级 const** —— 在此不可见 ⇒
    //   ReferenceError 被 6007 的 catch 静默吞掉，**连带吞掉整段注入**（/reminder/R3/候选）。
    //   ⇒ 现取（与同段其它注入源 `SESSIONS.get(session)` 同口径）。
    const sB = SESSIONS.get(session)
    // 🔴 **放行子会话**。此前硬编码 `identity === 'main'`
    //   ⇒ 所有「子 agent 执行的任务」经验召回 0 触发（EXP2/EXP3/ 共 8 个样本），
    //   且被误读为"任务没有触发面"。与 （`allowSubagent`）/ （`work_report` 归父会话）
    //   两条通道口径不一致 ⇒ 这里改为与它们一致：main 与 subagent 都放行。
    //   限额/冷却仍按**各自 session** 计（子会话独立配额，⛔ 不共享父会话名额）。
    const recallIdentityOk = sB !== undefined && (sB.identity === 'main' || sB.identity === 'subagent')
    if (experienceRecallEnabled() && recallIdentityOk) {
      // 工具名先取（来源门需要）—— ⛔ 不改其余调用顺序
      const etool = exec !== null && exec !== undefined && exec.name !== undefined ? String(exec.name) : ''
      const trig = recallTriggerOf(result, etool)
      if (trig !== null) {
        const eq = buildExperienceQuery(etool, exec !== null && exec !== undefined ? exec.arguments : undefined, result)
        const slot = EXPERIENCE_RECALL.get(session)
        const recallTurn = sB.currentTurn !== null ? sB.currentTurn : -1
        if (recallAllowed(slot, recallTurn, eq)) {
          const got = await spawnJsonAsync(
            EXPERIENCE_RECALL_ENTRY, { query: eq, n: 2, min: EXPERIENCE_RECALL_MIN_SCORE }, EXPERIENCE_RECALL_TIMEOUT_MS,
            ['--stdin-json'])
          const line = got.outcome === 'ok' ? renderExperienceRecall(got.value) : ''
          const hitCount = got.outcome === 'ok' && got.value !== null && got.value !== undefined && Array.isArray(got.value.hits)
            ? got.value.hits.length : 0
          emit({
            ev: 'experience-recall', obs: OBS, session, state: got.outcome, trigger: trig,
            hits: hitCount, query: clip(eq, 80), chars: line.length,
            note: 'v49 event-triggered experience recall (⛔ 不注入候选列表)',
            at: Date.now(), mono: mono(),
          })
          // 🔴 （读数 · R2）：**0 命中/空注入不消耗配额与冷却** —— 此前"尝试即计数"，
          //   误触发会吃掉 1/3 配额并封锁 2 turn。仍记 `lastQuery`（防同 query 连发）；仅真正注入才 +1。
          //   ⛔ 只改经验召回自身；不改其它注入源（/reminder/R3/候选）任何行为。
          const prev: ExperienceRecallSlot = slot !== undefined ? slot : emptyRecallSlot()
          EXPERIENCE_RECALL.set(session, {
            count: prev.count + (line !== '' ? 1 : 0),
            lastTurn: line !== '' ? recallTurn : prev.lastTurn,
            lastQuery: eq,
          })
          if (line !== '') extras.push(userMessageOf(line, 'aios experience recall (v49)'))
        }
      }
    }
    // ① v8 静态 marker
    if (probe !== null && sessionAllowsProbe(probe.session, session).hit) {
      const sent = DELIVERY_SENT.get(probe.marker) ?? 0
      if (sent < probe.maxPerSession) {
        DELIVERY_SENT.set(probe.marker, sent + 1)
        emit({
          ev: 'delivery-probe',
          obs: OBS,
          session,
          n: sent + 1,
          markerLen: probe.marker.length,
          mode: 'static-marker',
          note: 'Step B′ one-shot: static marker attached via tools/post-execute (no async prep, no retrieval)',
          at: Date.now(),
          mono: mono(),
        })
        extras.push(userMessageOf(probe.marker))
      }
    }
    // ② 提醒型递送（**只提醒** · ⛔ 不代替宿主动作）
    if (remind !== null && sessionAllowsProbe(remind.session, session).hit) {
      const rs = SESSIONS.get(session)
      if (rs !== undefined && rs.identity === 'main') {
        const r = reminderFor(rs)
        if (r !== null) {
          emit({
            ev: 'reminder',
            obs: OBS,
            session,
            kind: r.kind,
            chars: r.text.length,
            cardEdits: rs.cardEdits.size,
            cardReads: rs.cardReads.size,
            note: 'reminder-only: 不自动 claim / 不改 State / 不 release',
            at: Date.now(),
            mono: mono(),
          })
          extras.push(userMessageOf(r.text, 'aios task-card reminder'))
        }
      }
    }
    // **移除「release 后向本会话注入维护清单」**（原 段）。
    //    维护改为「claim 后向前一个**不同会话**注入接手检查」——见 `tools/post-execute` card-cmd 段的 块。
    //    ⛔ `maintenanceChecklist()` 保留（/ 幂等与单测仍引用），但它**不再由 release 触发**；
    //    ⛔ 不自动改知识 / 卡 / 家底本（执行者永远是 Agent）。
    // ②·补二 **事件驱动注入**（替换 阶段状态机 —— 见文件上方 注释）
    //    只发离散事实事件（边沿触发 · 每事件每会话一次），⛔ 不再推断阶段；
    //    ⛔ 只送文本（不改行为、不改卡、不注入候选）；`ev=inject` 记 event/n/named，便于算"注入→上报"间隔
    {
      const ip = readInjectProbe()
      if (ip !== null && sessionAllowsProbe(ip.session, session).hit) {
        const ist = SESSIONS.get(session)
        if (ist !== undefined && (ist.identity === 'main' || (ip.allowSubagent && ist.identity === 'subagent'))) {
          let slot = INJECT_EVENTS.get(session)
          if (slot === undefined) {
            slot = emptyEventSlot()
            INJECT_EVENTS.set(session, slot)
          }
          const hasEdit = ist.wc.progress.signals.includes('has-edit')
          const named = detectRetrievalRequest(ist.wc.intentText)
          const events = detectEvents({
            hasEdit,
            activity: ist.wc.activity,
            cardEdits: ist.cardEdits.size,
            intentText: ist.wc.intentText,
            turn: ist.currentTurn,
            lastFailKind: ist.lastFailKind,
            repeatQuestion: ist.repeatQuestion,
          }, slot)
          // 🔴 先推进「上一拍」基线（发不发都要推进 —— 否则升沿会被下一拍重复触发）
          slot.lastHasEdit = hasEdit
          slot.lastFailStreak = failStreakOf(ist.wc.activity)
          if (named.hit) slot.lastNamedTurn = ist.currentTurn
          // 本拍是否已发过事件提示（阶段注入让位 —— **每拍最多一条**注入，防叠加刷屏）
          let injectedEventThisStep = false
          for (const ev of events) {
            // 🔴 T5：**注入限额** —— 连续 2 条注入仍未换来检索 ⇒ 本会话停发。
            //   证据：`dacf` 22 次提示 → 2 次调用 → 0 次打开（卡第 39 批）；刷屏本身就是「信任稀释」。
            if (!injectAllowedByBudget(ist.injectsSinceRetrieval)) {
              emit({
                ev: 'inject-skip', obs: OBS, session, event: ev, reason: 'budget:no-retrieval',
                n: slot.count, injects: ist.injectsSinceRetrieval, at: Date.now(), mono: mono(),
              })
              break
            }
            if (!shouldPublishEvent(slot, ev, ip.maxPerSession)) continue
            const text = eventHintText(ev, slot.lastFailStreak)
            emit({
              ev: 'inject', obs: OBS, session, kind: 'event-hint', event: ev,
              n: slot.count, turn: ist.currentTurn, chars: text.length,
              named: named.hit, matched: named.hit ? named.matched : null,
              note: 'edge-triggered fact event (v26) — runtime → host as user message',
              at: Date.now(), mono: mono(),
            })
            extras.push(userMessageOf(text, 'aios event hint (runtime user message)'))
            ist.injectsSinceRetrieval += 1
            injectedEventThisStep = true
            break // 每拍最多一条（防多事件叠加刷屏）
          }

          // ── 🔴 **阶段进入**时注入能力描述（升沿 + 已发 Set · ⛔ 不是每步）──
          //   S1（占卡后）/ S2（首次实质改动）/ S4（收口）⇒ 走 `spawnJson` 调检索（带 `phase`）⇒ 取 top1 条（； 按分排序前 5）
          //   ⇒ 注入「能力名 — 一句话描述 + → capabilities/<file>」（照 三行格式 · ⛔ 不注整包正文）。
          //   ⛔ S3（受阻）不在此注：设计稿 §4.2 的 S3 类别门由**既有失败触发通道**承担（⛔ 不改既有注入源）。
          //   本节只能注入一条 user 消息/步：本步已发事件提示 ⇒ 让位（下一拍再发，Set 未记账 ⇒ 不会漏）。
          if (phaseInjectEnabled() && !injectedEventThisStep) {
            // 🔴 故障：**不跨 try 块引用变量** ⇒ 这里一律现取
            const pslot = phaseInjectSlotOf(session)
            // 🔴 **本拍是否走「卡上声明」通道** —— 一个开关、两处消费
            //   （① 声明注入块 ② 关掉下面的"检索判域"回退）。⚠️ 本常量声明在**任何 try 之外**
            //   ⇒ 不构成 那种"别处 try 抛了 ⇒ 这里 ReferenceError"（铁律①）。
            const domainOn = domainInjectEnabled()
            // ── **会话首拍**注入一次（独立标记 · ⛔ 不复用阶段 `sent`）─────────────────
            //   🔴 **默认关闭** —— 常量门控在这里，关时**不调用** `firstStepInjectOnce`
            //   ⇒ 零注入、零探针（⛔ 不落 skipped 占位）；实现保留，改常量即复活。
            //   放在常规阶段块**之前**：首拍 = "任何工具调用之后、任何工作之前"这个窗口，优先用它。
            //   真注到了 ⇒ 本拍不再注阶段（守住「每拍最多一条注入」，与事件提示的让位口径一致）；
            //   没注成（spawn-failed / no-candidate）⇒ 阶段块照旧跑（⛔ 不因首拍失败而吞掉既有通道）。
            const firstStepText = FIRST_STEP_INJECT_ENABLED
              ? await firstStepInjectOnce(session, ist, pslot)
              : ''
            if (firstStepText !== '') {
              extras.push(userMessageOf(firstStepText, 'aios first-step capability candidates (v51j)'))
              injectedEventThisStep = true
            }
            const hasEditNow = ist.wc.progress.signals.includes('has-edit')
            if (hasEditNow) pslot.everEdited = true
            const ph = phaseOf({
              ownedCards: myOccupiedCards(ist).length,
              releasedCards: ist.cardReleaseCount,
              releasedThisStep: ist.releaseJustObserved,
              hasEdit: hasEditNow,
              everEdited: pslot.everEdited,
              failStreak: failStreakOf(ist.wc.activity),
            })
            if (ph !== null && ist.releaseJustObserved) ist.releaseJustObserved = false
            // ── 🔴 **能力合规提醒**（只提醒"还缺记录" · ⛔ 不点名能力）────────────
            //   时机：S2（首次实质改动后）缺 `能力-开工` / S4（收口）缺 `能力-收尾` —— 各提醒一次。
            //   每会话每阶段最多 1 次：**独立 Set**（`nudgeChecked` / `nudgeSent` / `nudgeDupReported`，
            //     ⛔ 不复用阶段注入的 `sent`）；复查只落一条 `state:"dup"`。
            //   开关 `nudge` 缺省 off ⇒ 整个 `if` 第一项就短路 ⇒ **一行都不执行、零探针**（A 组逐字不变）。
            //   `.log` 只在**每阶段首次进入**读一次（≤2 次/会话）⇒ ⛔ 不按每拍读盘。
            //   本拍已发过别的注入（事件提示 / 首拍）⇒ 让位（下一拍再判；Set 未记账 ⇒ 不会漏）。
            if (capNudgeEnabled() && (ph === 'S2' || ph === 'S4') && !injectedEventThisStep) {
              const nudgePhase = ph
              const needNudge = CAP_NUDGE_NEED[nudgePhase]
              const mineNudge = myOccupiedCards(ist)
              const cardNudge = mineNudge.length === 1 ? mineNudge[0] : null
              // 无卡 / 多卡 ⇒ 无唯一对象可查（⛔ 不猜）；也不记账 ⇒ 有了卡该阶段仍能提醒。
              if (needNudge !== undefined && cardNudge !== null) {
                if (pslot.nudgeSent.has(nudgePhase)) {
                  // 已提醒过：每阶段只落一条 dup 读数（⛔ 每拍一条把探针刷满）
                  if (!pslot.nudgeDupReported.has(nudgePhase)) {
                    pslot.nudgeDupReported.add(nudgePhase)
                    emit({
                      ev: 'capability-nudge', obs: OBS, session, stage: nudgePhase, missing: needNudge,
                      state: 'dup', n: 0, chars: 0,
                      note: 'already nudged this phase (independent Set · ⛔ 不复用 phase-inject sent)',
                      at: Date.now(), mono: mono(),
                    })
                  }
                } else if (!pslot.nudgeChecked.has(nudgePhase)) {
                  // 本阶段首次进入 ⇒ 读一次 `.log` 判"三处记录缺哪处"（之后同阶段不再读盘）
                  pslot.nudgeChecked.add(nudgePhase)
                  if (missingCapRecordsOnCard(cardNudge).includes(needNudge)) {
                    pslot.nudgeSent.add(nudgePhase)
                    emit({
                      ev: 'capability-nudge', obs: OBS, session, stage: nudgePhase, missing: needNudge,
                      state: 'injected', n: 1, chars: CAP_NUDGE_TEXT.length,
                      note: 'compliance nudge: record the capability you used (⛔ 不点名任何能力)',
                      at: Date.now(), mono: mono(),
                    })
                    extras.push(userMessageOf(CAP_NUDGE_TEXT, 'aios capability compliance nudge (v51p)'))
                    // 每拍最多一条注入（与事件提示/格注入同一口径）：本拍让位，阶段检索下一拍再跑
                    injectedEventThisStep = true
                  }
                }
              }
            }
            // ── **注入跟随卡上声明的域能力** ─────────────────
            //   逻辑已提炼到 `runtime/activation/declared-domain.ts: applyDeclaredDomainInjection()`（阶段B）；
            //   位置/语义逐字保留：格能力块与检索块之前 · 命中 ⇒ 本拍只注那 3 行 · ⛔ 未声明/none ⇒ 零注入、不回退判域。
            if (applyDeclaredDomainInjection(extras, session, ist, ph, injectedEventThisStep, domainOn)) injectedEventThisStep = true
            // `domainInject` 开着时**关掉"检索判域"回退** —— 旧路径用 topic / 检索反推域
            //   （读数精确率 47–59% / 57%）⇒ 回退就等于继续用机器猜域，与 定的方向冲突。
            //   声明缺失 / `none` ⇒ 本拍**零注入**（S190/S191 盯住这条）。
            if (ph !== null && ph !== 'S3' && !injectedEventThisStep && !domainOn) {
              if (pslot.sent.has(ph)) {
                // 每阶段只报一条 dup（⛔ 别每拍一条把探针刷满）
                if (!pslot.dupReported.has(ph)) {
                  pslot.dupReported.add(ph)
                  emit({
                    ev: 'phase-inject', obs: OBS, session, phase: ph, state: 'dup',
                    n: 0, chars: 0, sent: [...pslot.sent],
                    note: 'each phase injected at most once per session (edge + sent Set · ⛔ 不用水平状态节流)',
                    at: Date.now(), mono: mono(),
                  })
                }
              } else {
                // **卡是唯一排序输入** —— 请求只由卡的 `Goal`+`Next Action` 构造；
                //    无卡 ⇒ **静默不注**（典型：S2 出现在占卡之前 —— 读数误报样本；或 S4 且卡快照已刷新为无卡），
                //    ⛔ 不再用 `intentText` 兜底。
                const mine = myOccupiedCards(ist)
                const card = mine.length === 1 ? mine[0] : null
                // 带上 `session`（axes 的第一级来源 = 本会话最近一条 `auto_capability`）；
                //    ⛔ 不改阶段判定 / 卡快照 / spawn 时机 —— 只多一个"请求里带什么"的纯函数入参。
                const req = buildPhaseRetrievalRequest(ph, card, ist.wc, Date.now(), session)
                if (req === null) {
                  // ⚠️ **不加入 `pslot.sent`** —— 等真占了卡，该阶段仍应能正常注入（⛔ 不把阶段锁死）。
                  // 只落一条 no-anchor 读数（每阶段最多一条，防每拍刷屏）。
                  if (!pslot.noAnchorReported.has(ph)) {
                    pslot.noAnchorReported.add(ph)
                    emit({
                      ev: 'phase-inject', obs: OBS, session, phase: ph, state: 'no-anchor',
                      n: 0, chars: 0, ownedCards: mine.length,
                      note: '无工作卡 ⇒ 不注入（卡描述是候选排序依据）',
                      at: Date.now(), mono: mono(),
                    })
                  }
                } else {
                  // 🔴 先记账再 spawn：**失败不重试** —— 防"spawn 慢/失败 ⇒ 每拍重试"变成刷屏（同源风险）。
                  //    代价：一次 spawn 失败会跳过该阶段（如实由 `state:"spawn-failed"` 可见，⛔ 不静默）。
                  pslot.sent.add(ph)
                  const got = await spawnJsonAsync(STAGE4_RETRIEVAL_ENTRY, { request: req }, PHASE_RETRIEVAL_TIMEOUT_MS)
                  if (got.outcome !== 'ok' || got.value === null || got.value === undefined) {
                    emit({
                      ev: 'phase-inject', obs: OBS, session, phase: ph, state: 'spawn-failed',
                      outcome: got.outcome, n: 0, chars: 0,
                      detail: clip(got.detail !== undefined ? got.detail : '', 100),
                      at: Date.now(), mono: mono(),
                    })
                  } else if (got.value.ok === false) {
                    const errs = Array.isArray(got.value.request_errors) ? got.value.request_errors : []
                    emit({
                      ev: 'phase-inject', obs: OBS, session, phase: ph, state: 'no-candidate',
                      why: 'request-invalid', errors: errs.slice(0, 3), n: 0, chars: 0,
                      at: Date.now(), mono: mono(),
                    })
                  } else {
                    // 把**同一份** topic（`buildPhaseRetrievalRequest` 的输入）喂给打分 ——
                    //   只影响 `scores`（探针），⛔ 不改请求、不改条数、不写进注入文本。
                    const rendered = renderPhaseCandidates(got.value, ph, capabilityIdsOf(session), phaseTopicOf(card))
                    if (rendered.text === '') {
                      emit({
                        ev: 'phase-inject', obs: OBS, session, phase: ph, state: 'no-candidate',
                        n: 0, chars: 0, pool: rendered.pool, matched: rendered.matched,
                        score_mode: rendered.scoreMode,
                        at: Date.now(), mono: mono(),
                      })
                    } else {
                      // 记下已注 id（跨阶段去重：同一能力不在两个阶段各注一次）
                      rememberCapabilityIds(session, rendered.ids)
                      emit({
                        ev: 'phase-inject', obs: OBS, session, phase: ph, state: 'injected',
                        n: rendered.ids.length, chars: rendered.text.length,
                        pool: rendered.pool, matched: rendered.matched,
                        // `candidates` 与 `scores` **等长且同序**（验证轮的原始数据；
                        //   ⛔ 分数不进注入文本，只进探针）
                        // `rendered.*` 已按生效上限切片 ⇒ 直接照录；`cap_max` = 本次生效的 max
                        candidates: rendered.ids,
                        scores: rendered.scores,
                        cap_max: phaseMaxCandidates(),
                        score_mode: rendered.scoreMode,
                        note: 'phase entry → capability DESCRIPTION + pointer (top·cap_max · scored · ⛔ 不注整包正文)',
                        at: Date.now(), mono: mono(),
                      })
                      extras.push(userMessageOf(rendered.text, 'aios phase capability candidates (v51)'))
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    // ③ **候选型递送**（第③段 · **唯一注入源 = Runtime** ⇒ Hook 的 `field_candidates` 保持停用）
    //    `pendingDelivery` 只在 `_stage4_probe.json` 的 `delivery:"deliver"` 时才会被写入
    //    ⇒ 这里**不需要**再判一次开关（写入端即唯一授权点）。
    //    🔴 但**必须**核对时效（增）：异步产出 ⇒ 递送前逐项校验，
    //       过期即**丢弃**并留派生读数（`ev=stage4-drop`）—— ⛔ 绝不把上一语境的候选递出去。
    {
      const ds = SESSIONS.get(session)
      if (ds !== undefined && ds.pendingDelivery !== null) {
        const pd = ds.pendingDelivery
        ds.pendingDelivery = null // 无论递不递都**消费掉**（一次性 · 防反复判同一份过期件）
        const stale = pendingStaleReason(ds, pd, Date.now())
        if (stale !== null) {
          emit({
            ev: 'stage4-drop', obs: OBS, session, reason: stale,
            ageMs: Date.now() - pd.at, chars: pd.text.length,
            issuedWindowSeq: pd.windowSeq, nowWindowSeq: ds.windowSeq,
            issuedCard: pd.cardKey, nowCard: focusCardOf(ds).key,
            note: 'stale candidate dropped before delivery (never entered model context)',
            at: Date.now(), mono: mono(),
          })
        } else {
          ds.deliveredCount += 1
          emit({
            ev: 'stage4-deliver', obs: OBS, session, chars: pd.text.length, n: ds.deliveredCount,
            windowSeq: pd.windowSeq, card: pd.cardKey, ageMs: Date.now() - pd.at,
            note: 'candidates delivered via tools/post-execute additionalContexts (sole injector = Runtime)',
            at: Date.now(), mono: mono(),
          })
          extras.push(userMessageOf(pd.text, 'aios capability candidates (runtime)'))
        }
      }
    }
    if (extras.length === 0) return downstream
    const prior = Array.isArray(downstream.additionalContexts) ? downstream.additionalContexts : []
    return { ...downstream, additionalContexts: [...prior, ...extras] }
  } catch (stepBErr) {
    // 🔴 注入段失败**必须可见** —— 此前 `catch { return downstream }`
    //   会把一个注入源的异常（如某处的 ReferenceError）连同**整段注入**一起吞掉，且探针 0 条。
    //   每会话每 where 只落一条（防每步刷屏）；探针自身失败绝不影响宿主。
    try {
      const es = sessionIdOf(exec && exec.agent)
      const ek = es + '|stepB'
      if (!DELIVERY_ERR_SEEN.has(ek)) {
        DELIVERY_ERR_SEEN.add(ek)
        emit({
          ev: 'delivery-error', obs: OBS, session: es, where: 'stepB',
          msg: clip(String(stepBErr !== null && stepBErr !== undefined && (stepBErr as any).message !== undefined
            ? (stepBErr as any).message : stepBErr), 120),
          at: Date.now(), mono: mono(),
        })
      }
    } catch { /* 探针自身失败绝不影响宿主 */ }
    // 递送自身失败 ⇒ 原样透传（**绝不**因递送而改变工具结果）
    return downstream
  }
}
