/**
 * aios-activation.ts — AI-OS 激活时机判定（Trigger Resolver）+ 延迟发现策略挂载点
 * ── 内存状态边界（硬约束）──────────────────────────────────────────────────
 *   插件内存**只**保存会话级控制状态（身份 / phase / 去重游标）——
 *   **不是事实源 · 重启即丢** · ⛔ 不得据此声称任务卡已 `Executing` ·
 *   ⛔ 不得把"发现过一次"当作 Agent 已阅读 / 采纳。
 * ── 挂载范围 ───────────────────────────────────────────────────────────────
 *   ① **只读扫卡**：`msgs>0` 时只读扫描 `task_cards/active/**` 的 State / Current Step。
 *   ② **上行端口 `auto_capability`**（`ctx.tools`）= 工作模块的**唯一输入端口**：
 *      载荷 = 结构化最小字段 + 可选自由文本；**立即 ack 不阻塞**；语料只存**内存**；
 *      探针只落**派生量**（⛔ 不落原文）。子会话也可调用，但语料**归父会话**
 *      （`header.parentSession`；拿不到父会话 ⇒ 归自己并在 ack 注明）。
 *      每会话**调用预算**硬上限，超限**明确拒绝**（⛔ 不静默丢最旧）。
 *      首次「有实质改动但从未上报」⇒ 提醒一次（⛔ 不常驻 · ⛔ 不重复）。
 *   ③ **检索输入 = `auto_capability` 的字段**：按字段构造 `retrieval-request/v1`
 *      （**字段 → 通道** 显式路由，映射见 `buildRetrievalRequestFromWorkReport` 注释）——
 *      ⛔ 不是把材料拼成一个字符串（否则找不出"是哪个字段召回的"）。
 *      ⛔ 不建独立 `work_state` 文件：检索的输入就是语料。
 *   ④ 卡**释放后**注入「维护清单」（README §四 强制查漏六项 + 探针体积 + tests），**每会话一次**。
 *      收尾提醒与维护清单全部由 R3 承担（`reminderB` / maintain 通道已移除）。
 *   ⑤ 重启由 执行（Agent ⛔ 不得动宿主进程树）。
 * ── 只做 / 不做（边界）─────────────────────────────────────────────────────
 *   ✅ 只输出「是否存在发现机会 + 依据」，不调 Python、不读候选、不注入一个字符。
 *   ❌ 不写任何事实文件 · ⛔ 不建 `runtime-session-state.json` · ⛔ 不新增 Event Log 事件类型。
 *   ❌ 不自动改知识 / 卡 / 家底本（执行者永远是 **Agent**）。
 *   ❌ 不拆独立插件（独立插件要改宿主 profile，在沙箱外）。
 * ── 依据（可回源）─────────────────────────────────────────────────────────
 *   `AUTOMATION-BOUNDARY.md §14.8` 四类介入时机（A 进入任务 / B 阶段变化 / C 普通对话 / D 无法确定）
 *   三优先级：① **任务事实驱动** ▸ ② prompt 辅助识别 ▸ ③ **证据不足就保持安静**
 *   §14.8 🔴「**C 类『保持安静』的前提就是去重机制**」—— 本插件的内存状态**就是**那个前提
 *   §14.9.3 约束①（内存状态只控制流程，不冒充事实）· 约束②（每轮极轻量检查）
 *   §14.9.1（发现核心共享、不迁 TS）—— 本插件**不做检索 / 评分**，只读卡的**两个字段**
 *   §15.1 三个时刻（T0 用户表达目标 / T1 Agent 形成计划 / T2 开始实际工作）
 *   §15.3 延迟发现流水线 · §15.4 两阶段机制 · §15.5 执行纪律（先取 T1/T2 可观察性证据）
 * ── 判据口径（勿丢）───────────────────────────────────────────────────────
 *   · 工具 / 路径签名 = **"工作方向的观测代理"**，**不是**真实任务阶段的**权威键** ——
 *     同一签名可能属于同一阶段，也可能跨多个阶段 ⇒ **只提供证据，不能单独作结论**。
 *     故 `§十四` 把该项拆成两版：**签名重复情况**（本次观测即可算）与
 *     **真实阶段内去重**（需可核实的阶段边界）；本插件**只服务前者**。
 *   · **`msgs=0` 只记 `msgs=0`** —— 它是"当前步骤的输入消息计数"，
 *     **不得**被解释成"用户在继续同一任务"。
 *   · **没有下一次 `pre-step`** ⇒ 不能推断"后续是否及时递送"，
 *     也**不得把不存在的事件记为失败**。
 *   · **短任务（一两个回合）同样有值**：完整事件序列即可用于时序与方向观察；
 *     只有短 prompt 而无任何方向信号 ⇒ 如实记 `UNKNOWN`，不强行推断。
 *   · 「**存在** Executing 卡」**不能**作为 A 类判据（基线非零 ⇒ 恒真）⇒ 用
 *     「**Executing 集合发生变化**（有新卡进入）」，且**首次观测只建基线、不触发**。
 *   · 卡事实只决定"**能否立即**触发"；**能否进入延迟等待由输入决定**
 *     （任务卡**不是**发现的先决条件）。
 *   · `CONTINUATION_MAX_CHARS` / `TODO_CHANGED_JACCARD` / `TODO_NEW_DIRECTION_JACCARD` /
 *     工具名白名单都是**首版值 · 无验证基线** ⇒ ⛔ 不得当成"已验证"。
 *   · ⚠️ 教训：**mock 自测若喂了真实载荷没有的字段，就会漏判真实缺陷**
 *     ⇒ 自测里 `tools/pre-execute` 的载荷必须与 `ToolExecutionInput` 同形（**无** `turn` / `step`）。
 * ── 隐私与数据边界 ────────────────────────────────────────────────────────
 *   🔴 **不得以"不知道使用者在做什么"来证明尊重隐私**：隐私边界约束信息的**控制、流向和用途**，
 *     **不是预先削弱**工具理解工作的能力。三层边界**互相独立 · 不得混为一谈**：
 *     ① **了解**（内存）：允许读取足以理解当前工作的相关内容（prompt 正文 · todo 原文 ·
 *        卡 `Goal` · 计划 · 实际操作）。⛔ 不因"它是原始内容"就改选信息不足的间接推断。
 *     ② **保存**（本地探针）：按用途决定 —— 跨步骤需要维持的状态**不必**为形式上的隐私强删；
 *        无用的内容也**不必**为"将来可能有用"而无限期保留。
 *     ③ **传播**（写进仓库文档 / 账本 ⇒ 会被 git 提交）：**另一项独立授权** ——
 *        本地理解**不自动**意味着允许外传 / 同步 / 无关用途；⚠️ 发往远程模型服务的边界
 *        要与本地处理区分开。仍守「**结论入档 · 原文不入档**」。
 *   🔴 **保留的硬边界**：不订阅 `agent/assistant-stream` ⇒ **不读隐藏推理 `reasoning-delta`**。
 *      它防的是"读取模型的**内部思维过程**"，**不是**"工具了解**工作内容**" —— 两者不可混同。
 *   🔴 **探针口径**：只落**足以验证机制**的**派生量** —— **区分性关键词**（保留「RLS / 迁移 / 隔离」
 *      vs「Hook / 适配 / 时序」的**核心差异**）· 相似度 · 长度 · 状态分布；
 *      ⛔ 不为形式上的最小化而只记类别计数（那会丢掉核心差异）。
 *      不记 prompt 正文、消息内容、文件内容、凭证；工具参数**一个都不记**（只记工具名）。
 * ── 推理流读取（A 阶段观测）───────────────────────────────────────────────
 *   🔴 路径优先序：① **优先**从**已提交的 Session 事件**读完整 Assistant Stream
 *      （`session/event` 是 **post-commit 追加馈送**；`assistant/message` / `assistant/attempt`
 *      的 `data.stream` 是**紧凑保存的完整流**）⇒ 三优势：**不复制原文** · 统计**完整步骤** ·
 *      能**区分成功提交与失败 / 重试 / 取消**。
 *      ② **后备**：`agent/assistant-stream`（**emit，非 waterfall**，零短路风险）只累计
 *      `reasoning-delta` 的结构量。探针用 `ev:'stream-path'` 报告**实际走通的是哪条路**。
 *   🔴 **能力上限（不得越界声称）**：只能证明「推理内容在实际路线中是否可用 + 时序与规模」；
 *      **不能**证明它改善任务理解（后者须由**有 / 无推理输入**的对照实验回答）。
 *   🔴 **时序事实**：`assistant-stream` 在模型请求**进行中**产生，而 `pre-step` 在其**之前**
 *      ⇒ 推理**只能影响后续步骤**，**不能追溯**改变最初的决定。
 *   🔴 **证据级别**：推理文本 = Agent 对任务的**自我解释（假设级证据）**，可能含错误假设 /
 *      被放弃方向 ⇒ ⛔ 不得与「用户意图」「执行结果」同级当作事实。
 *   🔴 **措辞纪律**：读的是「**模型已输出并暴露给宿主的推理文本**」，
 *      **不是**「对模型内部全部认知过程的透明访问」—— 此区别是防止过度声称。
 *   ✅ 严格 Observe-only：**不改判据 · 不改阈值 · 不注入 · 不检索 · 不改变 Agent 行为**。
 * ── 三条实现约束（勿删）───────────────────────────────────────────────────
 *   ⚠️ 1. **零外部包 import** —— 插件位于仓库根，裸包名解析不到 DSH 的 node_modules
 *         （依据 `vendor/loader/src/config/tree.ts:145-161`）。只用 `node:` 内置模块。
 *   ⚠️ 2. **`agent/pre-step` 与 `tools/pre-execute` 都是 waterfall** ⇒ 必须透明调用 `next()`
 *         **恰好一次**并原样返回其结果，否则短路 `hooks-claude-code` 的现有链路
 *         （`api-catalog.ts:3094-3099`）。
 *   ⚠️ 3. **身份无法确定时必须 fail-closed** —— 无 session header ⇒ `unknown` ⇒ **不评估**。
 *         **子会话**：身份非 `main` ⇒ **不写本插件的观察行**；子会话可见性仍由
 *         `session-start` / `subagent-start|end` 提供，**绝不并入主会话统计**。
 * ── 已知 UNKNOWN（如实标注，⛔ 不得当成已验证）──────────────────────────────
 *   ⚠️ A. `CONTINUATION_MAX_CHARS` 是**首版值 · 无验证基线** ⇒ 需按 `promptLen` 分布复调。
 *   ⚠️ B. T0 **刻意不判「明确目标」** —— 自然语言没有可靠纯机械判据。
 *         ⇒ 本版只有两条路：**任务事实（卡）触发立即机会**，或**进入延迟等待**。
 *   ⚠️ C. `agent/pre-step` 载荷里 `messages` 的**真实结构未验证**（只确认过条数）⇒
 *         解析做了多形态兼容 + fallback，并**把 `promptSrc` 写进探针**：出现
 *         `last-nonempty-fallback#n` 或 `no-text-content` ⇒ 说明解析退化
 *         （⛔ 不要读成"用户就是输入了延续语"）。
 *   ⚠️ D. 工具名白名单是**首版值**：未列名的工具 ⇒ 不当作工作意图（保守漏，不误报）。
 *   ⚠️ E. **宿主注入块剥离**（`INJECTED_BLOCK_RE`：`<system-reminder>` / `<noema-memory>` 等）
 *         覆盖的是**已知形态**；真实注入形态**未验证** ⇒ 故同时记 `promptRawLen`：
 *         两者差值 = 被剥掉的量；若差值长期为 0 而输入明显含注入块 ⇒ **形态未覆盖，须补**。
 *         为什么必须剥：用户只打「继续」，注入块会把它撑成长输入 ⇒ 每轮都开等待窗口
 *         ⇒ **正是 `§14.8` 要避免的"每轮出现"**。
 *   ⚠️ F. `tools/pre-execute` 的载荷**没有 `turn`** ⇒ 去重键用**回合序号**
 *         `windowSeq` / `observedSeq`，**不读 `turn`**。
 *         ⚠️ `todo_write` 是整体替换（last-write-wins）⇒ **每次都必须比较新旧快照**，
 *         ⛔ 不能把某一条 todo 的增删直接当成任务边界。
 *         ⚠️ S1 / S2 已知局限：短任务可能**根本不调用** `todo_write`，它也可能在**已开始
 *         部分工作之后**才出现；卡**可能未被提及**、内容**可能过时**、多张 `Executing` 时
 *         焦点不可判 ⇒ 只在**能唯一可靠关联**时使用；**读不到卡不得让 Runtime 失去感知能力**。
 */
import { existsSync, readFileSync, readdirSync, watch } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { spawn } from 'node:child_process'

import { join } from 'node:path'
import { AIOS_ROOT, aiosStateDir, AIOS_PROBES_DIR, OBS, POLICY, TAG, HEAD_BYTES, TAIL_BYTES, mono, probePaths, resolveStateFile, resolveScript, resolveToolScript, emit, clip, readHead, readTail } from './diagnostics/probe.ts'
import type { SessionState, TaskCursor, Occupancy } from './session/session-state.ts'
import { SESSIONS, MAX_SESSIONS, identityOf, sessionIdOf } from './session/session-state.ts'
import type { WorkContext, ActivityItem, EvidenceMeta, PendingStart, ProgressObs, ReasoningEntry, ReasoningObs, TodoLite, ToolClass, TurningPoint, TurningPointKind } from './session/work-context.ts'
import { FACTUAL_FAIL_RE, REASONING_TURN_CHARS_MAX, TP_ADJACENT_MS, TURNING_POINT_MAX, trimTurningPoints, upgradeAdjacentWeak, toolClassOf, pushStrongTp, failStreakOf, failKindOf } from './session/work-context.ts'
import { SPAWN_MAX_STDOUT_BYTES, SPAWN_MAX_STDERR_BYTES, outputExceedsLimit, utf8Bytes, spawnJson, spawnJsonAsync } from './retrieval/python-bridge.ts'
import type { PhaseSignals, AiPhase, PhaseInjectSlot, CapCellsConfig, CapCellsForm, CapNudgeState, DomainInjectState, CapRecordStage } from './activation/phase-policy.ts'
import { phaseOf, phaseInjectSlotOf, emptyPhaseInjectSlot, PHASE_INJECT, phaseInjectEnabled, capCellsConfig, CELL_FORM_DEFAULT, cellFormOf, capNudgeEnabled, capNudgeOf, domainInjectEnabled, domainInjectOf, missingCapRecordsOnCard, missingCapRecordsOf, CAP_RECORD_MARKS, cardLogPathOf, PHASE_MAX_CANDIDATES, PHASE_BUDGET_CANDIDATES, CAP_NUDGE_NEED, CAP_NUDGE_TEXT } from './activation/phase-policy.ts'
import { CARDS_DIR } from './diagnostics/probe.ts'
import { PHASE_TITLE, domainCapDir, domainFrontmatterOf, domainIntroOf, renderDomainInjection, declaredDomainCapabilityOf, declaredCapOfLog, declaredCapOfCardBody, domainCapabilityResolvedOf, domainLabelOf, cardMdPathOf, applyDeclaredDomainInjection } from './activation/declared-domain.ts'
import { applyStepBDelivery, tokensOf, latestWorkReport, phaseMaxCandidates, PHASE_TOPIC_MAX, PHASE_TOPIC_SEP, phaseTopicOf, PHASE_DEFAULT_HELP, phaseAxesOf, buildPhaseRetrievalRequest, PHASE_SCORE_W, hasCapScoreSignals, phaseCapScoreOf, renderPhaseCandidates, INJECT_MAX_WITHOUT_RETRIEVAL, injectAllowedByBudget, EXPERIENCE_RECALL_MIN_SCORE, renderExperienceRecall } from './delivery/phase-injection.ts'
import { capabilityIdsOf, buildFirstStepRetrievalRequest, RETRIEVAL_WORDS, detectRetrievalRequest } from './delivery/probe-state.ts'
import { setR3DisarmPending, INJECT_EVENTS, FIRST_STEP_INJECT_ENABLED, DELIVERY_ERR_SEEN, detectEvents, shouldPublishEvent, eventHintText, PENDING_DELIVERY_MAX_AGE_MS, pendingStaleReason } from './delivery/probe-state.ts'
import { pickCommandArg, PUSH_RELEASE_CMD_RE, pushReleaseHintText, RUNTIME_EDIT_PATH_RE, RUNTIME_EDIT_TOOL_RE, runtimeEditHintText, NODE_CORPUS_DOMAINS_RE, NODE_CORPUS_PITFALLS_RE, NODE_CORPUS_DIGEST_RE, NODE_INDEX_BUILD_RE, NODE_REGRESSION_CMD_RE, NODE_HELP_ONLY_RE, corpusNodeHintText, indexNodeHintText, regressionNodeHintText, nodeHintTextOf, NODE_INJECT, emptyNodeInjectSlot, nodeInjectSlotOf, isCorpusEditTarget, nodeHintOf } from './delivery/node-hints.ts'
import { EXPERIENCE_RECALL_MAX_PER_SESSION, EXPERIENCE_RECALL_MIN_TURN_GAP, emptyRecallSlot, recallAllowed } from './retrieval/experience-recall.ts'
import type { R3Takeover } from './maintenance/r3-wake.ts'
import { takeoverFromLog, scanTakeovers, r3WakePath, r3WakeStatePath, r3WakeEnabled, loadR3WakeState, saveR3WakeState, disarmR3Wake, r3WakeText, r3HandoffText, r3WakeCycle, installR3Wake, R3_WAKE_WINDOW_MS, R3_MAX_PER_SESSION, probeSizeMb, MAINT_MAX_PER_SESSION, MAINT_STATE, R3_WAKE_DEBOUNCE_MS, R3_WAKE_POLL_MS } from './maintenance/r3-wake.ts'
import { listCardFiles, focusCardOf, myOccupiedCards, reminderFor } from './session/lifecycle.ts'
import { CARD_NAME_RE, WORK_REPORTS } from './diagnostics/probe.ts'
import { noteCatchFail, CATCH_FAIL_SEEN } from './diagnostics/probe.ts'
import { userMessageOf, readSwitchCached, SWITCH_CACHE, switchNeedsReload, name } from './diagnostics/probe.ts'
import type { InjectProbe, ProbeSessionSpec, SessionMatch, DeliveryProbe, ReminderProbe, ShadowProbe, Stage4Probe } from './delivery/pending-delivery.ts'
import { parseProbeSessions, probePatternHit, sessionAllowsProbe, PROBE_AUTH_SEEN, noteProbeAuth, readDeliveryProbe, readReminderProbe, injectProbeFile, readInjectProbe, readShadowProbe, readStage4Probe, deliverySourcesActive, PROGRESS_WINDOW, deliveryProbeFile, reminderProbeFile, shadowProbeFile, stage4ProbeFile } from './delivery/pending-delivery.ts'
import { FOCUS_CARD_SCHEMA, FOCUS_CARD_TTL_MS, focusCardFile, FOCUS_CARD_STATS, focusCardCore, writeFocusCard, cardLogPathOfTaskId, lastOccupancyOf, occupancyOfCard, field, scanCards, legacyExecutingCards, startupRecoverIdOf, STARTUP_RECOVER_STATS, STARTUP_RECOVER_RAN, startupRecover } from './session/lifecycle.ts'
import type { Identity, Phase, Snapshot, TriggerKind, Discovery, PromptClass, PendingDelivery } from './session/session-state.ts'
import type { EvidenceSrc, TpUpgradedBy, Attribution, UnavailableReason } from './session/work-context.ts'

import { stripRepoPaths, EXEC_TOOL_RE, isExecToolName, tokenSetOf } from './diagnostics/probe.ts'
import type { RetrievalCandidate } from './retrieval/request-builder.ts'
import { STAGE4_RETRIEVAL_ENTRY, STAGE4_TOPIC_PHRASES, STAGE4_ROLE_MAP, stage4Uniq, buildRetrievalRequest, WR_HELP_TYPES, WR_DOMAIN_VALUES, WR_CONCERN_VALUES, buildRetrievalRequestFromWorkReport, RETURNED_CAPABILITY_IDS, rememberCapabilityIds, isCapabilityCandidatePath, PERMISSION_FAIL_RE, EXIT_MARK_RE, EXEC_ERROR_CONTEXT_RE, ENCODING_FAIL_RE, ENCODING_DETAIL_RE, looksLikeFileDump, RECALL_FACTUAL_EXTRA_RE, RECALL_QUOTA_RE, COMMON_TOOL_NAME_RE, PERMISSION_DETAIL_RE, resultTextOf, recallTriggerOf, buildExperienceQuery, WORK_REPORT_FIELD_MAX, WORK_REPORT_AXIS_MAX, buildWorkReport, WORK_REPORT_RETRIEVAL_TIMEOUT_MS, WORK_REPORT_RETRIEVAL_MAX_CANDIDATES, WORK_REPORT_RETRIEVAL_MAX_PER_SOURCE, WORK_REPORT_RETRIEVAL_SUMMARY_CHARS, cleanOneLine, summaryForCandidate, retrievalCandidatesOf, rerankCandidatesByWhat, retrievalNudgeEnabled, inlineRetrieval } from './retrieval/request-builder.ts'
import type { WorkReportRecord } from './diagnostics/probe.ts'
export { name, switchNeedsReload } from './diagnostics/probe.ts'
export { outputExceedsLimit } from './retrieval/python-bridge.ts'

// ── 仓库根 / 运行期目录解析（⛔ 不写死本机路径 · clone 到任意位置必须可用）──────────────
// 自 `另一仓库` 的**参数化版本**回流（`HANDOFF §四十五` 未清项之「参数化回流」）。
//   优先级：`AIOS_ROOT` 环境变量 ▸ 插件自身位置（本文件位于 `<root>/runtime/`）▸ `cwd`。
//   · `AIOS_STATE_DIR` —— **运行期实例数据**（开关文件 / 探针日志 / 生成缓存）：`<root>/.aios`
//     若存在则用它；否则**回退**旧路径 `<root>/scratch`（迁移期读旧读数用的兼容位，
//     避免"改了本体 ⇒ 旧开关突然全失效"）。`tools/probes/` 属**随仓库发布的机制探针**，不在此列。
//   · `AIOS_PROBES_DIR` —— 机制探针（`_field_emit.py` 等）。
export const inject: string[] = []

const T0 = Date.now()

/** 与 `tools/task_start.py` 的 `CARD_NAME_RE` **同源判据**（排除 PROJECT.md / README / 模板 / OPERATIONS 兜底日志）。 */
const CONTINUATION_MAX_CHARS = 12

/**
 * 观测 schema 版本 —— **先导样本（无此字段）不得与本版样本混算**。
 * `v5-todo-cwd` = 组合信号增补（S1 todo 计划 · S4 cwd · S2 卡 Goal）。
 * `v6-workctx` = **Step A′**（`p0/HANDOFF §二十六` · 裁定）：
 *                 WorkContext 六段内存快照 + 证据元数据 + **推理流结构观察**（A 阶段）。
 *   🔴 A 阶段**只采集结构量**：不保存推理原文 · 不参与发现查询 · 不递送 · 不改变激活行为。
 *   🔴 A 的能力上限：只能证明「推理内容是否可用 + 时序与规模」，**不能**证明它改善任务理解。
 * `v7-turnend-fill` = **口径修正 + 补观测**（批准 · 首取数驱动）：
 *   · 首取数抓到 `W1` 口径缺陷：**首个被评估回合**尚无任何历史证据 ⇒ `segFilled` 必然偏低，
 *     用它会**把"首回合正常"误判成"机制失效"**（读数同一回合内 `segFilled` 2 → 5）
 *   ⇒ ① **回合末**再记一份 `wc-fill`（`phase:'turn-end'`，与回合初 `turn-start` 配对）
 *     ② `wc-fill` 增 `reasoningLiveChars`（后备路径字符数 ⇒ 与主路径 `reasoningChars` **交叉核对**）
 *   ⚠️ 段 2g（9 条 v6 记录）因此**作废** ⇒ 新起点 = 重启后 `apply` 行（本版本标记）
 */
const SIG_MAX = 24

// ── ③ 组合信号（S1 / S4 / S2）· 裁定 ──────────────────────────

/**
 * ⚠️ **首版阈值 · 无验证基线（UNKNOWN）**：todo 新旧快照的 token 重叠度（Jaccard）。
 *   ≥ CHANGED ⇒ 视为"计划未实质变化"；< CHANGED ⇒ "变了"；< NEW_DIRECTION ⇒ "疑似新方向"。
 */
const TODO_CHANGED_JACCARD = 0.8
const TODO_NEW_DIRECTION_JACCARD = 0.4

/** 动作类别词表（**机械匹配** · 只输出**类别计数**，**不落原文**）。 */
const TODO_ACTION_RES: Array<[string, RegExp]> = [
  ['implement', /实现|编写|新增|添加|开发|创建|implement|add|write|create/i],
  ['test', /测试|验证|回归|用例|test|verify|spec/i],
  ['migrate', /迁移|migrat|schema|sql|rls|策略|数据库|database/i],
  ['refactor', /重构|整理|拆分|抽取|抽象|refactor|cleanup/i],
  ['diagnose', /排查|定位|诊断|修复|调试|fix|debug|investigate/i],
  ['docs', /文档|说明|记录|注释|doc|readme|comment/i],
  ['review', /审查|复核|检查|核对|review|audit|check/i],
]

function todoItemsOf(args: unknown): TodoLite[] | null {
  if (!args || typeof args !== 'object') return null
  const raw = (args as Record<string, unknown>).todos
  if (!Array.isArray(raw)) return null
  const out: TodoLite[] = []
  for (const it of raw) {
    if (!it || typeof it !== 'object') continue
    const o = it as Record<string, unknown>
    const c = typeof o.content === 'string' ? o.content : ''
    if (!c) continue
    out.push({ content: c, status: typeof o.status === 'string' ? o.status : 'unknown' })
  }
  return out
}

function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 && b.size === 0) return 1
  let inter = 0
  for (const x of a) if (b.has(x)) inter++
  const uni = a.size + b.size - inter
  return uni === 0 ? 1 : inter / uni
}

/** 关键词条数上限。 */
const KEYWORD_MAX = 8

/**
 * **区分性关键词**（**派生量** · 可落盘；原文只在内存）。
 * 🔴 依据 原则修正：**不得只记类别计数** —— 那会丢掉**核心差异**
 *   （「编写 RLS 迁移并测试访问隔离」与「重构 Hook 适配器并测试事件时序」的动作类别完全一样）。
 * 机械提取：拉丁词 + CJK 2-gram，按（频次, 长度）排序取前 N。
 *   例：⇒ `rls / 迁移 / 测试 / 访问 / 隔离`  vs  `hook / 重构 / 适配 / 测试 / 时序`
 */
function keywordsOf(items: string[]): string[] {
  const latin = new Map<string, number>()
  const cjk = new Map<string, number>() // ⚠️ Map 保**插入顺序**：CJK 用"首次出现顺序"而非字典序
  const bump = (m: Map<string, number>, t: string) => m.set(t, (m.get(t) || 0) + 1)
  for (const raw of items) {
    const s = String(raw || '').toLowerCase()
    for (const w of s.match(/[a-z0-9_]{2,}/g) || []) bump(latin, w)
    const seg = s.replace(/[^\u4e00-\u9fff]+/g, ' ')
    for (const part of seg.split(/\s+/)) {
      for (let i = 0; i + 2 <= part.length; i++) bump(cjk, part.slice(i, i + 2))
    }
  }
  // 拉丁词优先（区分性最强，如 rls / hook），按频次降序；CJK 2-gram 按**首次出现顺序**
  // （避免字典序把"迁移"这类高区分词与"移并"这类跨词噪声同等对待而挤出前 N）
  const latinSorted = Array.from(latin.entries())
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
    .map(e => e[0])
  return latinSorted.concat(Array.from(cjk.keys())).slice(0, KEYWORD_MAX).map(k => k.slice(0, 12))
}

/** 归一到 2 位小数（只落数值 · 不落集合）。 */
function round2(x: number): number {
  return Number(x.toFixed(2))
}

/** 轻量内容哈希（**内存比较用** · 只落"是否变化"的布尔，不落哈希本身）。 */
function hashOf(s: string): string {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return (h >>> 0).toString(16)
}

/** 动作类别计数（**只输出类别** · 不输出原文）。 */
function actionClassesOf(items: string[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const it of items) {
    for (const [k, re] of TODO_ACTION_RES) {
      if (re.test(it)) out[k] = (out[k] || 0) + 1
    }
  }
  return out
}

/** 状态分布（只计数）。 */
function statusCountsOf(items: TodoLite[]): Record<string, number> {
  const out: Record<string, number> = { pending: 0, in_progress: 0, completed: 0, other: 0 }
  for (const it of items) {
    if (out[it.status] !== undefined) out[it.status]++
    else out.other++
  }
  return out
}

/** 归一化长度极值（只记 min/max · 不记分布明细）。 */
function lenStatsOf(items: string[]): { min: number; max: number } {
  if (items.length === 0) return { min: 0, max: 0 }
  let min = Infinity
  let max = 0
  for (const it of items) {
    const n = normalizedLen(it)
    if (n < min) min = n
    if (n > max) max = n
  }
  return { min: min === Infinity ? 0 : min, max }
}

/** 工具类别（**只用于聚合观察**；不改变 `intentKindOf` 的判据）。 */
const PATH_ARG_KEYS = ['file_path', 'filePath', 'path', 'notebook_path', 'directory']

function pickPathArg(args: unknown): string {
  if (!args || typeof args !== 'object') return ''
  const a = args as Record<string, unknown>
  for (const k of PATH_ARG_KEYS) if (typeof a[k] === 'string' && a[k]) return String(a[k])
  return ''
}

/**
 * 目标路径 → **目录类别**（**剥掉文件名** · 最多两级目录 · 工作区外只记 `<outside>` + 扩展名）。
 * ⚠️ 这是**观测代理**，**不是**任务阶段的权威键（见文件头口径修正）。
 */
function pathClassOf(raw: string, cwd: string): string {
  if (!raw) return ''
  const norm = raw.replace(/\\/g, '/')
  const base = (cwd || '').replace(/\\/g, '/').replace(/\/+$/, '')
  const inside = base !== '' && (norm === base || norm.toLowerCase().startsWith(base.toLowerCase() + '/'))
  if (!inside) {
    const ext = (norm.match(/\.[A-Za-z0-9]{1,8}$/) || [''])[0]
    // 🔴 **放宽一级（裁定 · `§十八.3` 缺口 1）**：工作区外只记**顶层目录名**，
    //    用于区分「AI-OS 本体（`<outside>/AI-os/`）」与其他工作区（如 `<outside>/AI/`）；
    //    **仍不记文件名、不记更深层路径**。
    //    ⚠️ 代价（如实记）：顶层目录名本身可能含项目名等敏感信息 —— 这是"可归因性 vs 隐私"的
    //    一次**显式取舍**，不是无意泄露；若要回退 ⇒ 恢复为只写 `<outside>` + 扩展名。
    const parts = norm.replace(/^[A-Za-z]:\//, '').split('/').filter(Boolean)
    const top = parts.length >= 2 ? parts[0] : ''
    return '<outside>' + (top ? '/' + top + '/' : '') + ext
  }
  const rel = norm === base ? '' : norm.slice(base.length + 1)
  const parts = rel.split('/').filter(Boolean)
  if (parts.length <= 1) return './'
  return parts.slice(0, Math.min(2, parts.length - 1)).join('/') + '/'
}

/** 工作区基准（从会话 header 取；取不到退回 AI-OS 根）。 */
function cwdOf(agent: any): string {
  const h = agent && agent.session && agent.session.header
  return h && typeof h.cwd === 'string' && h.cwd ? h.cwd : AIOS_ROOT
}

/** **单调时钟**（纳秒字符串）：跨事件定序用，不受系统时间调整影响。 */
type IntentKind = 'plan' | 'work' | 'none'
/**
 * 发现机会判定（**本插件唯一的输出** —— 不代表已检索、更不代表已递送或已使用）。
 *   task_fact —— 任务卡事实触发（A/B 类）⇒ 立即机会
 *   waiting   —— 已打开延迟等待窗口（§15.4 阶段②）
 *   deferred  —— 等待窗口内等到实质工作意图 ⇒ **定向发现机会成立**（阶段 4 才递送）
 *   quiet     —— 保持安静（延续型输入 · §14.8 C 类）
 *   none      —— 证据不足且输入不可判（§14.8 ③）
 *   missed    —— 等待窗口在本回合内关闭，未等到意图（如实记，不补做）
 */
interface PromptProbe {
  text: string
  src: string
}

/**
 * **待递送的候选项**（第③段 · 增）。
 * 🔴 为什么不能只存 `string`：检索是**异步**的，产出与递送之间**至少隔着一次工具调用**
 *    ⇒ 若这段时间里**回合已前进**或**焦点卡已切换**，这条候选描述的是**上一个语境**，
 *      递出去就是噪声（甚至错误引导）。只存文本 ⇒ **结构上无从核对** ⇒ 必须连身份一起存。
 * ⛔ 本结构**不是**事实源：内存态、重启即丢、只用于"这条读数还算不算数"。
 */
const PENDING_QUEUE_MAX = 4
/** 已处理事件 seq 去重集合上限（LRU 淘汰 · 保守值 · UNVERIFIED）。 */
const SEEN_SEQ_MAX = 2_048

// ── 阶段三 3.1 · 保留策略第一版（裁定 `§28.13` · 设计见
//    `p0/STAGE3-DISCOVERY-AB-DESIGN.md` §3）─────────────────────────────────────
// 🔴 **定位**：内存**预算管理** —— **不是**价值判断。
//    被淘汰对象一律称「**预算约束下的淘汰对象**」，**不得**称"已确认无价值的内容"。
// 🔴 **只依赖已采集的机械证据**：四类转折点（Todo 实质变化 / 工具对象变化 / 报错或 attempt /
//    回合签名变化）—— **不引入**语义判断、**不调远程 LLM**。
// 🔴 **四级优先级**： 端点（首条 + 最新 · 永不淘汰）> 转折点邻域（按**时间**关联）
//    > **可证明的重复**（最先淘汰）> 兜底（🔴 记录为**预算约束**的信息损失）。

/** 保留策略标记（落盘 · 供判读"用的是哪一版策略"）。 */
const RETENTION_POLICY = 'endpoints+strong-tp+dedup/hard-budget'
/**  判据：字符 2-gram Jaccard 阈值（**首版值 · UNVERIFIED**）。 */
const DUP_JACCARD = 0.9
/**  护栏：规范化长度 < 此值的 entry **不参与**相似度判定（防短串偶然高重合误伤）。 */
const DUP_MIN_CHARS = 20
/**
 * 转折点列表上限（**首版值 · UNVERIFIED**）。
 * ⚠️ 转折点是**派生索引**（不是推理原文）：超限丢**最旧**只削弱早先转折点的保护效果，
 *    **不删除任何推理条目**；丢了多少**如实计数**（`turningPointDropped`），不静默。
 */
const TP_SUSTAIN_COUNT = 5

/** 四类**机械可观测**转折点（`§28.13`）。🔴 只有机械证据，**不证明**对应推理本身重要。 */
const ACTIVITY_MAX = 16
/** 进度信号的回看窗口。 */
function emptyReasoning(): ReasoningObs {
  return {
    committedMessages: 0,
    attempts: 0,
    interrupted: 0,
    blocks: 0,
    chars: 0,
    ms: 0,
    liveChunks: 0,
    liveChars: 0,
    source: 'none',
    streamShapes: [],
    provider: null,
    model: null,
    lastTurn: null,
    lastStep: null,
    lastAt: null,
  }
}

function emptyWorkContext(): WorkContext {
  return {
    intentText: '',
    intentLen: 0,
    intentMeta: null,
    plan: null,
    planMeta: null,
    reasoning: emptyReasoning(),
    cwd: '',
    cwdTop: '',
    cardKey: null,
    activity: [],
    progress: { editsSinceLastExec: 0, consecutiveFailures: 0, lastOk: null, signals: [] },
    understanding: null,
    reasoningEntries: [],
    reasoningChars: 0,
    reasoningEvictedEntries: 0,
    reasoningEvictedChars: 0,
    pendingAttempts: new Map(),
    seenSeq: new Set(),
    provisionalAttempts: 0,
    turningPoints: [],
    historyCoverage: 'complete',
    retentionPolicy: RETENTION_POLICY,
    evictedSeqRanges: [],
    evictedTurns: new Set(),
    turningPointDropped: 0,
    overBudgetFloor: 0,
  }
}

/** 会话键（`session/event` 只给 `Session`，形态与 `agent.session` 一致 ⇒ 兼容多形态取法）。 */
function sessionKeyOf(session: any): string {
  if (!session) return 'unknown'
  const h = session.header || (session.session && session.session.header)
  if (h && h.id !== undefined) return String(h.id)
  if (session.id !== undefined) return String(session.id)
  return 'unknown'
}

/**
 * **从已提交的紧凑流里只取结构量**（`AssistantStreamRecord[]`）——
 *   `{type:'reasoning-chunks', time0, index, dt:number[], texts:string[]}` ⇒ 块数 / 字符数 / Σdt。
 *   ⚠️ 同时兼容**已解码**的 `{type:'reasoning-delta', text}` 形态（后备 / 未来形态）。
 *   🔴 **只返回长度与计数**：`texts` 的内容在此函数内即被丢弃，绝不外流。
 */
function scanAssistantStream(stream: unknown): { blocks: number; chars: number; ms: number; shapes: string[] } {
  let blocks = 0
  let chars = 0
  let ms = 0
  const shapes = new Set<string>()
  if (!Array.isArray(stream)) return { blocks, chars, ms, shapes: [] }
  for (const rec of stream) {
    if (!rec || typeof rec !== 'object') {
      shapes.add('non-object')
      continue
    }
    const t = (rec as Record<string, unknown>).type
    if (typeof t !== 'string') {
      shapes.add('untyped')
      continue
    }
    shapes.add(t)
    if (t === 'reasoning-chunks') {
      const texts = (rec as Record<string, unknown>).texts
      if (Array.isArray(texts)) {
        blocks += 1
        for (const x of texts) if (typeof x === 'string') chars += x.length
      }
      const dt = (rec as Record<string, unknown>).dt
      if (Array.isArray(dt)) for (const d of dt) if (typeof d === 'number') ms += d
    } else if (t === 'reasoning-delta') {
      const text = (rec as Record<string, unknown>).text
      if (typeof text === 'string') {
        blocks += 1
        chars += text.length
      }
    }
  }
  return { blocks, chars, ms, shapes: Array.from(shapes).slice(0, 8) }
}

/**
 * **阶段 2**：从已提交紧凑流里取出推理**文本**（按 `reasoning-chunks` 记录**分条**）。
 * 🔴 返回值**只进内存 WorkContext**；`turn/end` 到达即释放；**绝不落盘**。
 * ⚠️ 形态未覆盖 ⇒ 返回空数组，由调用方标 `parse-degraded`，**不猜内容**。
 */
function scanReasoningTexts(stream: unknown): Array<{ text: string; chars: number; ms: number }> {
  const out: Array<{ text: string; chars: number; ms: number }> = []
  if (!Array.isArray(stream)) return out
  for (const rec of stream) {
    if (!rec || typeof rec !== 'object') continue
    const t = (rec as Record<string, unknown>).type
    if (t === 'reasoning-chunks') {
      const texts = (rec as Record<string, unknown>).texts
      if (!Array.isArray(texts)) continue
      const text = texts.filter((x): x is string => typeof x === 'string').join('')
      let ms = 0
      const dt = (rec as Record<string, unknown>).dt
      if (Array.isArray(dt)) for (const d of dt) if (typeof d === 'number') ms += d
      out.push({ text, chars: text.length, ms })
    } else if (t === 'reasoning-delta') {
      const text = (rec as Record<string, unknown>).text
      if (typeof text === 'string') out.push({ text, chars: text.length, ms: 0 })
    }
  }
  return out
}

/**
 * **阶段 2 · 归属**（复核修正：**显式标识优先 · FIFO 有条件兜底**）。
 *   ① 事件带显式 `attemptId`（当前契约**不带** ⇒ 保留为前向兼容）⇒ `explicit-id`
 *   ② 同 `(turn, step)` 的 pending 队列**恰好 1 条** ⇒ `fifo-unique`
 *   ③ 队列 **> 1**（重试 ⇒ 无法排除歧义）⇒ `unavailable/ambiguous-queue`
 *      🔴 **不靠"顺序看起来一致"去猜**
 *   ④ 队列为空 ⇒ `unavailable/no-start-seen`
 *   🔴 作用域严格限定同一 session 的同一 (turn, step)；**不跨作用域补配**。
 */
function attributeOf(
  s: SessionState,
  turn: number,
  step: number,
  explicitId: string | null,
): {
  attribution: Attribution
  unavailableReason: UnavailableReason | null
  attemptId: string | null
  revision: number | null
  pendingDepth: number
} {
  if (explicitId !== null) {
    return { attribution: 'explicit-id', unavailableReason: null, attemptId: explicitId, revision: null, pendingDepth: -1 }
  }
  const key = turn + ':' + step
  const q = s.wc.pendingAttempts.get(key)
  const depth = q === undefined ? 0 : q.length
  if (depth === 1 && q !== undefined) {
    const p = q[0]
    q.shift()
    if (q.length === 0) s.wc.pendingAttempts.delete(key)
    return { attribution: 'fifo-unique', unavailableReason: null, attemptId: p.attemptId, revision: p.revision, pendingDepth: 1 }
  }
  if (depth > 1) {
    // 歧义 ⇒ **不清空、不猜测**（如实降级 · 留待后续裁定）
    return { attribution: 'unavailable', unavailableReason: 'ambiguous-queue', attemptId: null, revision: null, pendingDepth: depth }
  }
  return { attribution: 'unavailable', unavailableReason: 'no-start-seen', attemptId: null, revision: null, pendingDepth: 0 }
}

/**
 * **阶段 2 · 释放**（🔴 正式释放点 = `session/event` 的 **`turn/end`**，**不是** `turn-stopping`）。
 * 释放该会话指定 turn 的全部推理原文 + 清空其 pending；返回释放量。
 * 🔴 释放后**不得**有任何路径再读取这些文本（`text` 显式置空）。
 */
function releaseTurn(s: SessionState, session: string, turn: number, reasonKind: string): void {
  const coverageBefore = s.wc.historyCoverage
  const kept: ReasoningEntry[] = []
  let releasedEntries = 0
  let releasedChars = 0
  for (const e of s.wc.reasoningEntries) {
    if (e.turn === turn) {
      releasedEntries += 1
      releasedChars += e.chars
      e.text = '' // 显式断开引用
    } else {
      kept.push(e)
    }
  }
  s.wc.reasoningEntries = kept
  s.wc.reasoningChars = kept.reduce((n, e) => n + e.chars, 0)
  let pendingCleared = 0
  for (const k of Array.from(s.wc.pendingAttempts.keys())) {
    if (k.startsWith(turn + ':')) {
      pendingCleared += (s.wc.pendingAttempts.get(k) || []).length
      s.wc.pendingAttempts.delete(k)
    }
  }
  // ── 阶段三 3.1：转折点随回合释放；`historyCoverage` **按剩余回合重算**（R8 的语义基础）──
  s.wc.turningPoints = s.wc.turningPoints.filter(tp => tp.turn !== turn)
  s.pendingWeakTpIndex = null // 🔴 数组已变 ⇒ 待定下标失效，必须清空（防误升级）
  s.wc.evictedTurns.delete(turn)
  s.wc.historyCoverage = s.wc.evictedTurns.size > 0 ? 'partial' : 'complete'
  emit({
    ev: 'reasoning-release',
    obs: OBS,
    session,
    turn,
    reasonKind,
    releasedEntries,
    releasedChars,
    pendingCleared,
    keptEntries: kept.length,
    coverageBefore,
    coverageAfter: s.wc.historyCoverage,
    evictedTurnsRemaining: s.wc.evictedTurns.size,
    at: Date.now(),
    mono: mono(),
  })
}

// ── 阶段三 3.1 · 保留策略（四级优先级 · 裁定 `§28.13`）────────────
//   🔴 术语纪律：淘汰对象 = 「**预算约束下的淘汰对象**」，**不得**称"已确认无价值的内容"。

/**
 * 转折点列表裁剪（丢**最旧**的派生索引 · 条目本身不动 · 如实计数）。
 * 返回 push 后新元素的下标（考虑丢最旧造成的位移）。
 */
function pushWeakTp(s: SessionState, kind: TurningPointKind, turn: number | null): void {
  const at = Date.now()
  const adjacent = s.lastStrongTpAt !== null && (at - s.lastStrongTpAt) <= TP_ADJACENT_MS
  s.wc.turningPoints.push({
    at,
    kind,
    strength: adjacent ? 'strong' : 'weak',
    upgradedBy: adjacent ? 'adjacent' : null,
    turn,
  })
  const idx = trimTurningPoints(s)
  s.pendingWeakTpIndex = adjacent ? null : idx
}

/** 弱信号升级条件 (b)：同一 `pathClass` 已连续出现 ≥ `TP_SUSTAIN_COUNT` 次 ⇒ 回溯升级。 */
function trySustainUpgrade(s: SessionState): void {
  if (s.pathClassRun < TP_SUSTAIN_COUNT) return
  const i = s.pendingWeakTpIndex
  if (i === null) return
  const tp = s.wc.turningPoints[i]
  if (tp === undefined || tp.strength !== 'weak') {
    s.pendingWeakTpIndex = null
    return
  }
  tp.strength = 'strong'
  tp.upgradedBy = 'sustained'
  s.pendingWeakTpIndex = null
}

/**  规范化：**只**折叠空白 + 小写（🔴 不做语义归一 / 同义词替换）。 */
function normalizeForDup(text: string): string {
  return text.replace(/\s+/g, '').toLowerCase()
}

/** 字符 2-gram 集合（相似度用）。 */
function bigramsOf(s: string): Set<string> {
  const out = new Set<string>()
  for (let i = 0; i + 1 < s.length; i++) out.add(s.slice(i, i + 2))
  return out
}

/**
 * 「**明确重复**」判定 —— 🔴 **只处理可证明的重复**（文本相似 ≠ 语义等价）。
 *   `'exact'` = 规范化后**完全相等**（无阈值）
 *   `'sim'`   = 字符 2-gram Jaccard ≥ `DUP_JACCARD`（首版阈值 · UNVERIFIED）
 *   `null`    = **不构成**明确重复 ⇒ **不得**据此降级
 */
function dupKindOf(a: string, b: string): 'exact' | 'sim' | null {
  const na = normalizeForDup(a)
  const nb = normalizeForDup(b)
  if (na === '' || nb === '') return null
  if (na === nb) return 'exact'
  if (na.length < DUP_MIN_CHARS || nb.length < DUP_MIN_CHARS) return null // 短文本护栏
  return jaccard(bigramsOf(na), bigramsOf(nb)) >= DUP_JACCARD ? 'sim' : null
}

/**
 * 3.1（收窄）· 保护集合（** 端点** + **-强**转折点邻域）。
 *   🔴 **只有 `strength:'strong'` 的转折点进保护集合** —— 弱信号（工具对象变化）默认**不保护**。
 *   🔴 关联**只能按时间**（工具事件载荷无 `turn`/`step` · `§12.10`）：
 *      取「`entry.at ≤ tp.at` 中 `at` 最大者」= 转折点**之前时间最近的一条**。
 *   🔴 转折点找不到更早的 entry ⇒ 该转折点**不产生保护**（如实计 `tpUnmatched`）。
 */
function protectedSets(s: SessionState): {
  p0: Set<string>
  p1: Set<string>
  tpUnmatched: number
  tpCrossTurn: number
} {
  const p0 = new Set<string>()
  const p1 = new Set<string>()
  let tpUnmatched = 0
  let tpCrossTurn = 0
// **按回合**保护首条 + 最新一条（🔴 但**不是豁免权** —— 见 §3.1.2：降级到 L4 时仍会淘汰）
  const byTurn = new Map<number, ReasoningEntry[]>()
  for (const e of s.wc.reasoningEntries) {
    const list = byTurn.get(e.turn)
    if (list === undefined) byTurn.set(e.turn, [e])
    else list.push(e)
  }
  for (const list of byTurn.values()) {
    let min = list[0]
    let max = list[0]
    for (const e of list) {
      if (e.seq < min.seq) min = e
      if (e.seq > max.seq) max = e
    }
    p0.add(min.key)
    p0.add(max.key)
  }
// 每个**强**转折点保护「其之前时间最近的一条」
  for (const tp of s.wc.turningPoints) {
    if (tp.strength !== 'strong') continue // 🔴 收窄的核心：弱信号不进保护集合
    let best: ReasoningEntry | null = null
    for (const e of s.wc.reasoningEntries) {
      if (e.at > tp.at) continue
      if (best === null || e.at > best.at || (e.at === best.at && e.seq > best.seq)) best = e
    }
    if (best === null) {
      tpUnmatched += 1
      continue
    }
    if (tp.turn !== null && best.turn !== tp.turn) tpCrossTurn += 1 // 如实暴露时间关联的弱点
    p1.add(best.key)
  }
  return { p0, p1, tpUnmatched, tpCrossTurn }
}

/** 当时转折点的强度分布（**派生量** · 收窄是否生效的机械证据）。 */
function tpStrengthCountsOf(s: SessionState): { strong: number; weak: number; upgraded: number } {
  let strong = 0
  let weak = 0
  let upgraded = 0
  for (const tp of s.wc.turningPoints) {
    if (tp.strength === 'strong') strong += 1
    else weak += 1
    if (tp.upgradedBy !== null) upgraded += 1
  }
  return { strong, weak, upgraded }
}

interface EvictionPick {
  entry: ReasoningEntry
  /** 🔴 policy 取值集合可机械区分 / 样本（统计脚本按此切分）。 */
  policy: 'P2-duplicate' | 'P3-unsheltered' | 'P3-over-P1' | 'P3-over-P0'
  tier: 'L1' | 'L2' | 'L3' | 'L4'
  dupExact: boolean
  dupSim: boolean
  protectedP0: number
  protectedP1: number
  tpUnmatched: number
  tpCrossTurn: number
  tierCounts: { L2: number; L3: number; L4: number }
}

const oldestOf = (list: ReasoningEntry[]): ReasoningEntry => list.reduce((a, b) => (a.seq <= b.seq ? a : b))

/**
 * 在候选池内找「**可证明重复**」且存在**更早兄弟**的条目（保留较早的一条 · 淘汰较新者）。
 * 🔴 比较对象是**全部** entry（含受保护者）—— 只要求淘汰对象本身在候选池内。
 */
function pickDuplicate(s: SessionState, pool: ReasoningEntry[]): { entry: ReasoningEntry; kind: 'exact' | 'sim' } | null {
  const hits: Array<{ entry: ReasoningEntry; kind: 'exact' | 'sim' }> = []
  for (const c of pool) {
    for (const o of s.wc.reasoningEntries) {
      if (o.key === c.key || o.seq >= c.seq) continue // 只认"更早的兄弟"
      const k = dupKindOf(o.text, c.text)
      if (k !== null) {
        hits.push({ entry: c, kind: k })
        break
      }
    }
  }
  if (hits.length === 0) return null
  hits.sort((a, b) => a.entry.seq - b.entry.seq)
  return hits[0]
}

/**
 * 3.1（收窄）· **分层降级链**选一条「**预算约束下的淘汰对象**」。
 *   L1 = 可证明重复（最先淘汰）→ L2 = 无保护中间 → L3 = -强保护 → L4 = 端点
 *   层内顺序：L1/L2/L3 = `seq` **最小**；🔴 **L4 = `seq` 最大**（先淘汰"最新一条" ——
 *   该位置会被后续条目自然接替，而"首条 = 初始方向"不可再生）。
 *   `null` = 物理下限（内存只剩 1 条）⇒ 调用方记 `overBudgetFloor` 并停止。
 * 🔴 该链**保证预算收敛**（这是 约定的核心要求）。
 */
function pickEviction(s: SessionState): EvictionPick | null {
  const prot = protectedSets(s)
  const unsheltered = s.wc.reasoningEntries.filter(e => !prot.p0.has(e.key) && !prot.p1.has(e.key))
  const p1Only = s.wc.reasoningEntries.filter(e => prot.p1.has(e.key) && !prot.p0.has(e.key))
  const p0Only = s.wc.reasoningEntries.filter(e => prot.p0.has(e.key))
  const tierCounts = { L2: unsheltered.length, L3: p1Only.length, L4: p0Only.length }
  const base = {
    protectedP0: prot.p0.size,
    protectedP1: prot.p1.size,
    tpUnmatched: prot.tpUnmatched,
    tpCrossTurn: prot.tpCrossTurn,
    tierCounts,
  }
  // ── L2：无保护中间记录（重复在其中最先被淘汰）──
  if (unsheltered.length > 0) {
    const dup = pickDuplicate(s, unsheltered)
    if (dup !== null) {
      return { entry: dup.entry, policy: 'P2-duplicate', tier: 'L1', dupExact: dup.kind === 'exact', dupSim: dup.kind === 'sim', ...base }
    }
    return { entry: oldestOf(unsheltered), policy: 'P3-unsheltered', tier: 'L2', dupExact: false, dupSim: false, ...base }
  }
  // ── L3：-强保护对象（无 L2 候选时才动用 ⇒ R12 降级链有序）──
  if (p1Only.length > 0) {
    const dup = pickDuplicate(s, p1Only)
    if (dup !== null) {
      return { entry: dup.entry, policy: 'P2-duplicate', tier: 'L1', dupExact: dup.kind === 'exact', dupSim: dup.kind === 'sim', ...base }
    }
    return { entry: oldestOf(p1Only), policy: 'P3-over-P1', tier: 'L3', dupExact: false, dupSim: false, ...base }
  }
  // ── L4： 端点（最后才动用 · 且先淘汰"最新一条"）──
  if (p0Only.length > 1) {
    return {
      entry: p0Only.reduce((a, b) => (a.seq >= b.seq ? a : b)),
      policy: 'P3-over-P0',
      tier: 'L4',
      dupExact: false,
      dupSim: false,
      ...base,
    }
  }
  return null // 物理下限
}

/** 合并序号区间（升序 · 相邻/重叠即合并 ⇒ `evictedSeqRanges` 两两不相邻）。 */
function mergeSeqRange(ranges: Array<[number, number]>, seq: number): void {
  ranges.push([seq, seq])
  ranges.sort((a, b) => a[0] - b[0])
  const merged: Array<[number, number]> = []
  for (const r of ranges) {
    const last = merged[merged.length - 1]
    if (last !== undefined && r[0] <= last[1] + 1) last[1] = Math.max(last[1], r[1])
    else merged.push([r[0], r[1]])
  }
  ranges.length = 0
  for (const r of merged) ranges.push(r)
}

/**
 * 3.1 · 腾出预算：**整条**淘汰「预算约束下的淘汰对象」，循环至满足预算或无可淘汰对象。
 * 🔴 只记**派生量**（policy / 保护计数 / seq 区间 / 缺口状态）—— **绝不落原文**。
 * 🔴 `R8`：每次淘汰更新 `historyCoverage` / `evicted*` / `evictedSeqRanges`（账目可机械核对）。
 */
function evictToBudget(s: SessionState, session: string): void {
  while (s.wc.reasoningChars > REASONING_TURN_CHARS_MAX) {
    const pick = pickEviction(s)
    if (pick === null) {
      // 🔴 **物理下限**：内存只剩 1 条仍超预算 ⇒ 停止并**如实记**（取消了 的
      //    "全保护即可超预算" —— 那是被裁定的缺陷；这里只有**不可再淘汰**这一种诚实情形）
      s.wc.overBudgetFloor += 1
      emit({
        ev: 'reasoning-evicted',
        obs: OBS,
        session,
        policy: 'none',
        tier: 'floor',
        reason: 'memory-budget',
        overBudgetFloor: s.wc.overBudgetFloor,
        evictedEntries: 0,
        evictedChars: 0,
        retainedEntries: s.wc.reasoningEntries.length,
        retainedChars: s.wc.reasoningChars,
        coverageAfter: s.wc.historyCoverage,
        at: Date.now(),
        mono: mono(),
      })
      return
    }
    const idx = s.wc.reasoningEntries.indexOf(pick.entry)
    if (idx < 0) return
    s.wc.reasoningEntries.splice(idx, 1)
    s.wc.reasoningChars -= pick.entry.chars
    s.wc.reasoningEvictedEntries += 1
    s.wc.reasoningEvictedChars += pick.entry.chars
    s.wc.evictedTurns.add(pick.entry.turn)
    mergeSeqRange(s.wc.evictedSeqRanges, pick.entry.seq)
    s.wc.historyCoverage = 'partial'
    emit({
      ev: 'reasoning-evicted',
      obs: OBS,
      session,
      turn: pick.entry.turn,
      step: pick.entry.step,
      policy: pick.policy, // P2-duplicate / P3-unsheltered / P3-over-P1 / P3-over-P0
      tier: pick.tier, // L1 / L2 / L3 / L4 —— 降级链是否按序执行的机械证据（R12）
      reason: 'memory-budget', // 🔴 预算约束 —— **不是**语义判断
      dupExact: pick.dupExact,
      dupSim: pick.dupSim,
      protectedByP0: pick.protectedP0,
      protectedByP1: pick.protectedP1,
      tierCounts: pick.tierCounts, // 该次淘汰时各层候选数（R12 的机械依据）
      tpStrengthCounts: tpStrengthCountsOf(s), // 强 / 弱 / 已升级（收窄是否生效的证据）
      seqRange: [pick.entry.seq, pick.entry.seq],
      evictedEntries: 1, // 整条（不是截断半条）
      evictedChars: pick.entry.chars,
      retainedEntries: s.wc.reasoningEntries.length,
      retainedChars: s.wc.reasoningChars,
      coverageAfter: 'partial',
      tpUnmatched: pick.tpUnmatched,
      tpCrossTurn: pick.tpCrossTurn,
      at: Date.now(),
      mono: mono(),
    })
  }
}

/**
 * **阶段 2**：把一次已提交结算里的推理文本组织进内存 WorkContext（🔴 **只写不判**）。
 *   · `assistant/attempt`（失败 / 重试 / 取消）⇒ **不建 entry**，只 `provisionalAttempts += 1`
 *   · `assistant/message` ⇒ 每条 `reasoning-chunks` 建一条 entry；**归属每条提交只算一次**（复用）
 *   · 超 `REASONING_TURN_CHARS_MAX` ⇒ 按**阶段三 3.1 保留策略**（`evictToBudget`）选
 *     「**预算约束下的淘汰对象**」并**整条**移除 + 只记派生量（🔴 **不是**语义判断）
 * 🔴 本函数**不做**任何判定 / 检索 / 递送；文本**不落盘**（探针只记派生量）。
 */
function collectReasoningText(
  s: SessionState,
  session: string,
  settlement: 'message' | 'attempt',
  data: Record<string, unknown>,
  seq: number | null,
  interrupted: boolean,
  r: ReasoningObs,
): void {
  const turn = typeof data.turn === 'number' ? data.turn : null
  const step = typeof data.step === 'number' ? data.step : null
  const texts = scanReasoningTexts(data.stream)

  if (settlement === 'attempt') {
    s.wc.provisionalAttempts += 1
    // ── 阶段三 3.1： 第 ④ 类**强**转折点（重试 / 取消 = attempt）──
    pushStrongTp(s, 'attempt', turn)
    emit({
      ev: 'provisional-obs',
      obs: OBS,
      session,
      turn,
      step,
      blocks: texts.length,
      chars: texts.reduce((n, x) => n + x.chars, 0), // 只计数 · **不留存文本**
      at: Date.now(),
      mono: mono(),
    })
    return
  }
  if (turn === null || step === null) return // 无归属坐标 ⇒ 不建 entry（不猜）

  const explicitId = typeof data.attemptId === 'string' ? data.attemptId : null
  // 🔴 归属**每条提交只算一次**并复用到该提交的所有 entry（一条提交 = 一个 attempt）
  const a = attributeOf(s, turn, step, explicitId)
  let totalChars = 0
  for (const item of texts) {
    const entry: ReasoningEntry = {
      key: session + '#' + String(seq === null ? 'noseq' : seq),
      session,
      turn,
      step,
      seq: seq === null ? -1 : seq,
      settlement: 'message',
      interrupted,
      text: item.text, // 🔴 仅内存
      chars: item.chars,
      blocks: texts.length,
      ms: item.ms,
      provider: r.provider,
      model: r.model,
      attribution: a.attribution,
      unavailableReason: a.unavailableReason,
      attemptId: a.attemptId,
      revision: a.revision,
      nature: 'agent-self-explanation',
      confidence: interrupted ? 'interrupted' : 'assumption',
      at: Date.now(),
    }
    s.wc.reasoningEntries.push(entry)
    s.wc.reasoningChars += entry.chars
    totalChars += entry.chars
    emit({
      ev: 'reasoning-text',
      obs: OBS,
      session,
      turn,
      step,
      seq,
      chars: entry.chars,
      blocks: entry.blocks,
      ms: entry.ms,
      provider: entry.provider,
      model: entry.model,
      attribution: entry.attribution,
      unavailableReason: entry.unavailableReason,
      revision: entry.revision,
      confidence: entry.confidence,
      at: entry.at,
    })
  }
  if (texts.length > 0) {
    emit({
      ev: 'attempt-pair',
      obs: OBS,
      session,
      turn,
      step,
      attribution: a.attribution,
      unavailableReason: a.unavailableReason,
      pendingDepth: a.pendingDepth,
      entryCount: texts.length,
      chars: totalChars,
      at: Date.now(),
      mono: mono(),
    })
  }
  // ── 上限淘汰（**阶段三 3.1 保留策略** · 整条 · 只记数量 · 不截断半句）──
  //    🔴 替换 FIFO： 端点 + 转折点邻域受保护 · 可证明重复优先 · 兜底
  evictToBudget(s, session)
}

/** 压入一条活动证据（环形上限 · 只留最近窗口）。 */
function pushActivity(wc: WorkContext, item: ActivityItem): void {
  wc.activity.push(item)
  if (wc.activity.length > ACTIVITY_MAX) wc.activity.splice(0, wc.activity.length - ACTIVITY_MAX)
}

/**
 * 进度段：**只由活动序列机械派生**（表明确：**不得**直接标注"调试阶段"等语义结论）。
 *   ⇒ 输出去到"信号"级：`has-edit` / `exec-after-edit` / `exec-failed` / `read-only-so-far`。
 */
function deriveProgress(activity: ActivityItem[]): ProgressObs {
  const recent = activity.slice(-PROGRESS_WINDOW)
  const signals: string[] = []
  const isEdit = (a: ActivityItem) => a.cls === 'edit' || a.cls === 'write'
  const hasEdit = recent.some(isEdit)
  const hasExec = recent.some(a => a.cls === 'exec')
  const hasRead = recent.some(a => a.cls === 'read' || a.cls === 'search')
  if (hasEdit) signals.push('has-edit')
  if (hasExec) signals.push('has-exec')
  if (hasRead && !hasEdit) signals.push('read-only-so-far')

  let lastEditIdx = -1
  let lastExecIdx = -1
  for (let i = 0; i < recent.length; i++) {
    if (isEdit(recent[i])) lastEditIdx = i
    if (recent[i].cls === 'exec') lastExecIdx = i
  }
  if (lastEditIdx >= 0 && lastExecIdx > lastEditIdx) signals.push('exec-after-edit')

  let editsSinceLastExec = 0
  for (let i = activity.length - 1; i >= 0; i--) {
    if (activity[i].cls === 'exec') break
    if (isEdit(activity[i])) editsSinceLastExec++
  }

  let consecutiveFailures = 0
  for (let i = activity.length - 1; i >= 0; i--) {
    if (activity[i].ok === false) consecutiveFailures++
    else if (activity[i].ok === true) break
    else continue
  }

  let lastOk: boolean | null = null
  for (let i = activity.length - 1; i >= 0; i--) {
    if (activity[i].ok !== null) {
      lastOk = activity[i].ok
      break
    }
  }
  if (lastOk === false) signals.push('last-result-failed')
  if (consecutiveFailures > 0) signals.push('consecutive-failures')

  return { editsSinceLastExec, consecutiveFailures, lastOk, signals }
}

/**
 * WorkContext → 探针可落盘的**填充摘要**（不含任何原文）。
 *   🔴 这是「保存」层的落点：只落**是否填充 / 派生量**，不落内容。
 */
function wcFillOf(wc: WorkContext): Record<string, unknown> {
  const segFilled =
    (wc.intentLen > 0 ? 1 : 0) +
    (wc.plan !== null ? 1 : 0) +
    (wc.reasoning.source !== 'none' ? 1 : 0) +
    (wc.cwd !== '' ? 1 : 0) +
    (wc.activity.length > 0 ? 1 : 0) +
    (wc.progress.signals.length > 0 ? 1 : 0)
  return {
    segFilled, // 0–6：至少 3 段非空 ⇒ 判"上下文已获知"（`§二十七 W1`）
    intentLen: wc.intentLen,
    intentPresent: wc.intentLen > 0,
    planPresent: wc.plan !== null,
    planCount: wc.plan !== null ? wc.plan.count : null,
    planKeywords: wc.plan !== null ? wc.plan.keywords : null,
    planChanged: wc.plan !== null ? wc.plan.changed : null,
    reasoningSource: wc.reasoning.source,
    reasoningBlocks: wc.reasoning.blocks,
    reasoningChars: wc.reasoning.chars,
    envCwdTop: wc.cwdTop || null,
    cardKey: wc.cardKey,
    activityLen: wc.activity.length,
    activityTools: wc.activity.slice(-PROGRESS_WINDOW).map(a => a.cls + (a.pathClass ? ':' + a.pathClass : '')),
    progressSignals: wc.progress.signals,
    progressEditsSinceLastExec: wc.progress.editsSinceLastExec,
    progressConsecutiveFailures: wc.progress.consecutiveFailures,
    understanding: wc.understanding, // 🔴 恒 null（诚实标注）
    // ── 阶段三 3.1 · 保留策略的**信息缺口可见性**（R8 · **派生量** · 无原文）──
    historyCoverage: wc.historyCoverage,
    retentionPolicy: wc.retentionPolicy,
    reasoningEntriesRetained: wc.reasoningEntries.length,
    reasoningEvictedEntries: wc.reasoningEvictedEntries,
    reasoningEvictedChars: wc.reasoningEvictedChars,
    evictedSeqRanges: wc.evictedSeqRanges,
    evictedTurns: Array.from(wc.evictedTurns),
    turningPointCounts: (() => {
      const out: Record<string, number> = {}
      for (const tp of wc.turningPoints) out[tp.kind] = (out[tp.kind] || 0) + 1
      return out
    })(),
    // 🔴 强度分桶（收窄是否生效的机械证据 · 只有 strong 进保护集合）
    turningPointStrength: (() => {
      const out = { strong: 0, weak: 0, upgraded: 0 }
      for (const tp of wc.turningPoints) {
        if (tp.strength === 'strong') out.strong += 1
        else out.weak += 1
        if (tp.upgradedBy !== null) out.upgraded += 1
      }
      return out
    })(),
    turningPointDropped: wc.turningPointDropped,
    overBudgetFloor: wc.overBudgetFloor,
  }
}

// ── 阶段三 3.2 · **影子发现通道**（A/B 对照 · 裁定）──────────────────
// 🔴 **授权与边界（逐条硬约束）**：
//   · **只做本地发现**：**不改** `post-execute` 的下游 decision（**不递送**）· **不调远程 LLM**
//   · 推理文本**只在内存**并**经 stdin** 传给**本地** Python 子进程 ⇒ **不落盘 · 不进探针 · 不回显**
//   · 探针只落**派生量**：候选 **id（仓库相对路径）** / 分数 / `gate` / 耗时 / 查询长度 / 失败原因
//   · 开关 = **本地文件 · 每次重读 · 缺失即完全透明**（默认不存在 · 同 v8 递送探针的纪律）
//   · **绝不阻塞**：异步 spawn + 超时 kill + 每会话 1 并发；**任何失败只记探针**，不影响宿主
//   · 🔴 **任务卡正文不入 A 组查询**（`§4.1`）：A 组只用 意图 / 计划 / 环境 / 活动
const SHADOW_ENTRY = process.env.AIOS_SHADOW_ENTRY || resolveScript('_shadow_discovery.py', '_shadow_discovery.py')
/** B 组追加的推理文本上限（**首版值 · UNVERIFIED** · 防查询过大）。 */
const SHADOW_REASONING_CHARS = 8_000

function shadowQueryA(wc: WorkContext): string {
  const parts: string[] = []
  if (wc.intentText !== '') parts.push(wc.intentText)
  if (wc.plan !== null) parts.push(wc.plan.items.map(t => t.content).join(' '))
  if (wc.cwdTop !== '') parts.push(wc.cwdTop)
  for (const a of wc.activity.slice(-PROGRESS_WINDOW)) parts.push(a.tool + (a.pathClass === null ? '' : ' ' + a.pathClass))
  return parts.join('\n')
}

/** **B 组 = A + 推理文本**（按 `seq` 升序 · 截到上限）⇒ 🔴 **仅此一项不同**。 */
function shadowQueryB(a: string, wc: WorkContext): string {
  let text = ''
  for (const e of wc.reasoningEntries.slice().sort((x, y) => x.seq - y.seq)) text += e.text + '\n'
  return a + '\n' + text.slice(0, SHADOW_REASONING_CHARS)
}

const SHADOW_INFLIGHT = new Map<string, number>()
const SHADOW_DONE = new Map<string, number>()
/** 🔴 诊断去重（`shadow-dispatch` · 每会话一条）：只用于"为什么没派发"，不参与任何决策。 */
const SHADOW_DIAG = new Set<string>()

/**
 * 异步派发一次影子发现（**绝不阻塞宿主** · 失败只记探针）。
 * 🔴 不写任何文件、不改任何 decision、不碰注入开关。
 */
function dispatchShadow(s: SessionState, session: string, turn: number | null): void {
  const probe = readShadowProbe()
  if (probe === null) return
  const m = sessionAllowsProbe(probe.session, session)
  if (!m.hit) return
  noteProbeAuth('shadow', session, probe.session, session, m)
  const done = SHADOW_DONE.get(session) ?? 0
  if (done >= probe.maxPerSession) return
  if ((SHADOW_INFLIGHT.get(session) ?? 0) > 0) {
    emit({ ev: 'shadow-ab', obs: OBS, session, turn, outcome: 'skipped', reason: 'inflight', at: Date.now(), mono: mono() })
    return
  }
  const a = shadowQueryA(s.wc)
  if (a.trim() === '') return
  const b = shadowQueryB(a, s.wc)
  SHADOW_INFLIGHT.set(session, 1)
  SHADOW_DONE.set(session, done + 1)
  const at = Date.now()
  const base = { obs: OBS, session, turn, aChars: a.length, bChars: b.length - a.length - 1 }
  let child: any
  try {
    child = spawn('python', [SHADOW_ENTRY], { stdio: ['pipe', 'pipe', 'pipe'] })
  } catch (err) {
    SHADOW_INFLIGHT.set(session, 0)
    emit({ ...base, ev: 'shadow-ab', outcome: 'spawn-error', detail: clip(String(err), 120), at, mono: mono() })
    return
  }
  let out = ''
  let errOut = ''
  let settled = false
  const finish = (outcome: string, extra: Record<string, unknown>): void => {
    if (settled) return
    settled = true
    clearTimeout(timer)
    SHADOW_INFLIGHT.set(session, 0)
    emit({ ...base, ...extra, ev: 'shadow-ab', outcome, at, mono: mono() })
  }
  const timer = setTimeout(() => {
    try {
      child.kill()
    } catch (err) {
      noteCatchFail('shadow:S1', err)
      /* 静默 */
    }
    finish('timeout', { timeoutMs: probe.timeoutMs })
  }, probe.timeoutMs)
  child.stdout.on('data', (d: any) => {
    out += String(d)
  })
  child.stderr.on('data', (d: any) => {
    errOut += String(d)
  })
  child.on('error', (err: any) => finish('child-error', { detail: clip(String(err), 120) }))
  child.on('close', () => {
    // 🔴 只解析**结构化**输出；失败如实分类（`bad-json` / `nonzero`）—— 不猜
    let parsed: any = null
    try {
      parsed = JSON.parse(out.trim() === '' ? '{}' : out.trim())
    } catch {
      finish('bad-json', { stdoutChars: out.length, stderrChars: errOut.length })
      return
    }
    if (parsed === null || parsed.error !== undefined) {
      finish('nonzero', { detail: clip(String(parsed && parsed.error), 60) })
      return
    }
    const ids = (arm: any): string[] => (arm && Array.isArray(arm.candidates) ? arm.candidates.map((c: any) => String(c.id)) : [])
    const scores = (arm: any): number[] => (arm && Array.isArray(arm.candidates) ? arm.candidates.map((c: any) => Number(c.score)) : [])
    // 🔴 **诊断字段**（只落标识 + 原因 + 命中数 · **无原文**）：区分"无候选"是
    //    「命中不足 / 无信号」还是「**命中密度被长查询稀释**」—— 否则 A/B 结果无法判读。
    const rej = (arm: any): string[] => (arm && Array.isArray(arm.topRejects)
      ? arm.topRejects.slice(0, 2).map((r: any) => String(r.id) + '|' + String(r.reason) + '|' + String(r.hits))
      : [])
    finish('ok', {
      gateA: parsed.A ? String(parsed.A.gate) : null,
      gateB: parsed.B ? String(parsed.B.gate) : null,
      topA: ids(parsed.A),
      topB: ids(parsed.B),
      scoreA: scores(parsed.A),
      scoreB: scores(parsed.B),
      qeffA: parsed.A && typeof parsed.A.queryEffective === 'number' ? parsed.A.queryEffective : null,
      qeffB: parsed.B && typeof parsed.B.queryEffective === 'number' ? parsed.B.queryEffective : null,
      rejA: rej(parsed.A),
      rejB: rej(parsed.B),
      msA: parsed.A ? parsed.A.elapsedMs : null,
      msB: parsed.B ? parsed.B.elapsedMs : null,
      totalMs: parsed.shared ? parsed.shared.totalMs : null,
      // 🔴 **无原文**：只有候选标识（仓库相对路径）与派生量
    })
  })
  try {
    child.stdin.write(JSON.stringify({ queries: { A: a, B: b }, topN: probe.topN }), 'utf8')
    child.stdin.end()
  } catch {
    finish('stdin-error', {})
  }
}

// ── 阶段 4 · **接通核心 → Retrieval → 核心**（主线裁定）───────────────
// 定位（`HANDOFF §架构交接`：**一个发现核心 + 两个适配器** · DSH 原生插件 = 主路线）：
//   ① 核心（本文件）用**焦点卡 + 工作窗口 + 活动证据**确定焦点对象 ⇒ 构造**最小**检索请求
//   ② Retrieval（`scratch/_retrieval_request_probe.py` · `retrieval-request/v1` · 自测 21/21）
//      按**既定规则**发现 / 筛选 ⇒ 返回 `candidate-set/v1`
//   ③ 核心收候选、保留**来源与身份** ⇒ 决定如何递送（🔴 第 3 步**未做** · 尚未产生模型可见上下文）
// 🔴 边界（逐条硬约束 · 与影子通道同纪律）
//   · **默认完全透明**：开关文件缺失 / 非法 / 未启用 ⇒ ⛔ 不 spawn · 不写探针
//   · **不递送**：本段不注入任何上下文 ⇒ 与 Hook 侧**不构成双重注入**
//   · **不写非探针文件** · **不落推理原文**（⛔ 不向 Retrieval 传推理文本 · 只落派生量）
//   · **绝不阻塞**：异步 spawn + 超时 kill + 每会话 1 并发；任何失败只记探针
//   · ⛔ **不新增第二套检索判据** —— 打分 / 闸门 / 来源枚举一律复用 Retrieval 侧既有实现
const STAGE4_FIELD_ENTRY = process.env.AIOS_STAGE4_FIELD || resolveScript('_field_emit.py', '_field_emit.py')
const STAGE4_REASONING_ENTRIES = 20
/**
 * 推理文本的**字符上限**（与影子通道同量级 · 防 stdin 过大）。
 * 🔴 推理文本**只在内存**，**只经 stdin** 传给**本地** python 子进程 —— ⛔ 不落盘 · 不回显 · 不进探针。
 */
const STAGE4_REASONING_CHARS = 8_000

/**
 * `auto_capability` ⇒ `retrieval-request/v1`（**纯函数** · 供单测 · ⛔ 无 I/O）。
 * 三态纪律：每个 `work` 字段必须是 `provided` / `unknown` / `known-absent` 之一（Python `validate` 会拒缺失）。
 */
const STAGE4_INFLIGHT = new Map<string, number>()
const STAGE4_DONE = new Map<string, number>()

/**
 * 请求的**派生读数**（⛔ 不回显 value 全文 ⇒ 只落字段名 / 字符数 / 条目数）。
 * 新增 `requestSource` 与顶层 `need` / `search_terms` 的派生量 —— 判读"请求由谁构造"（可回溯）。
 */
function stage4RequestObs(req: Record<string, unknown>, requestSource: string): Record<string, unknown> {
  const work = (req.work ?? {}) as Record<string, any>
  const provided: string[] = []
  const sizes: Record<string, number> = {}
  for (const k of Object.keys(work)) {
    const f = work[k]
    if (f && f.state === 'provided') {
      provided.push(k)
      sizes[k] = Array.isArray(f.value) ? f.value.length : String(f.value ?? '').length
    }
  }
  const sizeOf = (v: any): number => (v === undefined || v === null ? 0 : (Array.isArray(v) ? v.length : String(v).length))
  const need = (req.need ?? {}) as Record<string, any>
  const st = (req.search_terms ?? {}) as Record<string, any>
  return {
    requestSource,
    fieldsProvided: provided,
    sizes,
    need: need.state === 'provided' ? { chars: sizeOf(need.value) } : { state: String(need.state ?? 'not-stated') },
    searchTerms: st.state === 'provided' ? { items: sizeOf(st.value) } : null,
    roles: req.roles_needed ?? [],
    budget: req.budget ?? null,
  }
}

// ── 🔴 **焦点卡**（唯一依据 · `p0/RESPONSIBILITY-BOUNDARIES.md §2`）────────────
// 为什么不能用旧判据（两项都是实际踩到的）：
//   · **git 工作区改动**：工作区是**跨会话共享**的，且本仓纪律是「不提交」⇒ 多个会话的卡改动
//     同时躺在工作区里 ⇒ Hook 侧读数判出「改动文件指向 6～8 张卡」⇒ 永远不唯一。
//   · **`Executing` 张数**：那是**状态副作用**，两张同时 `Executing` 就不可判（`pickFocus` ⇒ null）。
// 本判据用**本会话自己的工具调用**（`edit` / `write` 命中卡文件）⇒ 天然会话级、天然唯一，
// 且与卡规范一致（「使用一张卡必然留下改动」—— `task_cards/README.md`：进行时更新 `Current Status`
// **并追加 `Event Log`**）。
const CARD_FILE_RE = /^TASK-\d{8}-\d{3}\.md$/i

/**
 * 工具参数里的路径 → **卡 key**（相对 `task_cards/active/` 的 posix 路径，与 `TaskCursor.key` 同形）。
 * ⛔ 非卡文件一律 `null`（只认 `TASK-YYYYMMDD-NNN.md` 这一种名字 —— 与 `wrapup_sync.CARD_NAME_RE`
 * 口径一致；`-OPERATIONS.md` 这类派生件**不算卡**）。
 */
function cardRelOf(raw: string | null): string | null {
  if (raw === null || raw === '') return null
  const p = raw.replace(/\\/g, '/')
  const marker = 'task_cards/active/'
  const i = p.toLowerCase().indexOf(marker)
  if (i < 0) return null
  const rel = p.slice(i + marker.length)
  const seg = rel.split('/')
  if (!CARD_FILE_RE.test(seg[seg.length - 1])) return null
  return rel
}

/** `task_card.py … claim|release TASK-YYYYMMDD-NNN`（可选前置 `--flag`）。
 *  **一次工具调用里可能有多条命令** ⇒ 必须逐条扫描（见 `cardCmdsOf()`）。 */
/** `claim` 支持**「项目/ID」**形式（`claim AI-OS-Adaptation/TASK-…`）。
 *  为什么必须支持：卡 ID **跨项目重名**（读数 `TASK-20261023-001` 同时存在于 AI-OS-Adaptation /
 *  demo-project）⇒ 裸 ID 会被 `task_card.py` **拒绝**（要求「项目/ID」定位）⇒ 跨项目重名卡
 *  **只能**用带前缀形式占用。旧正则只认裸 ID ⇒ 这类占用对 Runtime 完全不可见（`cardEdits` 不记
 *  ⇒ `anchor-claimed` 事件永不触发）。读数： 本会话 claim 带前缀成功，探针无
 *  `card-cmd` 记账、无 anchor 事件 —— 就是这个缺口。 */
const CARD_CMD_RE = /task_card\.py\s+(?:--\S+\s+)*(claim|release)\s+(?:([^\s/\\]+)\/)?(TASK-\d{8}-\d{3})/i

/**
 * 该工具调用里的**全部**占用 / 释放命令 ⇒ `[{ op, taskId, dryRun }]`（无匹配 ⇒ `[]`）。
 * 🔴 **逐条扫描**（原实现用 `CARD_CMD_RE.exec()`，**只取第一条**）：
 *    实际踩到 —— 一次调用里写
 *      `python tools/task_card.py release X --state=Parked` 换行 `python tools/task_card.py claim X`
 *    ⇒ 只有 `release` 被记账、`claim` **静默丢失**（占用没建立，零报错、零诊断）。
 *    判据 = 用带 `g` 的副本循环 `exec` 直到没有更多匹配。
 * ⛔ `--dry-run` = **无副作用预览**，不算占用；判据取**该条命令所在行**
 *    （⛔ 不是整段文本 —— 否则"第一条真跑、第二条预览"的混写会被整体误判）。
 */
function cardCmdsOf(tool: string, args: unknown): Array<{ op: string; taskId: string; dryRun: boolean }> {
  if (!/^(pwsh|bash|shell|exec)$/i.test(tool)) return []
  const cmd = pickCommandArg(args)
  if (cmd === '') return []
  const out: Array<{ op: string; taskId: string; dryRun: boolean }> = []
  const re = new RegExp(CARD_CMD_RE.source, 'gi')
  let m: RegExpExecArray | null
  while ((m = re.exec(cmd)) !== null) {
    const lineStart = cmd.lastIndexOf('\n', m.index) + 1
    let lineEnd = cmd.indexOf('\n', m.index)
    if (lineEnd === -1) lineEnd = cmd.length
    const line = cmd.slice(lineStart, lineEnd)
    // 分组 1 = op · 2 = **可选项目前缀** · 3 = ID ⇒ taskId 统一成「项目/ID」（有前缀时）。
    const proj = m[2] as string | undefined
    out.push({
      op: m[1].toLowerCase(),
      taskId: proj === undefined ? m[3] : proj + '/' + m[3],
      dryRun: /--dry-run\b/.test(line),
    })
    if (out.length >= 8) break                        // 防御：异常长的命令不让它无限循环
    if (m.index === re.lastIndex) re.lastIndex += 1    // 零宽匹配保护
  }
  return out
}

/** `TASK-ID` ⇒ 命中的**卡 key 列表**（`项目/TASK-x.md` 与平铺 `TASK-x.md` 都认）。
 *  🔴 抽出来供调用方**计数**（`miss` 读数要如实记"0 个/2 个"，⛔ 不只说 null）。 */
function cardKeyHitsOf(keys: readonly string[], taskId: string): string[] {
  const want = taskId + '.md'
  return keys.filter(k => k === want || k.endsWith('/' + want))
}

/**
 * `TASK-ID` ⇒ **卡 key**（从最近一次扫到的卡列表里找）。
 * 🔴 **唯一命中才算可确定**：0 个或多个同名 ID ⇒ `null`（⛔ 不猜 —— 现实中确实有重复 ID）。
 * ⚠️ 本函数**只读缓存**（`s.knownCardKeys` = 回合开始 pre-step 的快照，L6172）。
 *    回合开始后才建的卡（同一回合 `create` + `claim`）⇒ 缓存 0 命中。
 *    现扫兜底在调用点（post-execute `card-cmd` 段）—— 那里有 `session` 可以落失败读数。
 */
function cardKeyOfId(s: SessionState, taskId: string): string | null {
  const hits = cardKeyHitsOf(s.knownCardKeys, taskId)
  return hits.length === 1 ? hits[0] : null
}

/** 领域词表（**只服务 `inferDomainOf()` 的域判定**；格能力已删，⛔ 不参与检索、⛔ 不回写卡）。
 *  顺序 = 平票时的优先级。 */
const CELL_DOMAIN_WORDS: ReadonlyArray<{ domain: string; words: readonly string[] }> = [
  { domain: '前端', words: ['前端', '页面', '界面', '组件', '样式', '布局', '视觉', '美化', '配色', '响应式', 'ui', 'css'] },
  { domain: '后端', words: ['后端', '服务端', '接口', 'api', '鉴权', '并发', '事务', '网关'] },
  { domain: '数据', words: ['数据', '数据库', '迁移', '备份', '索引', '报表', '查询', 'sql', 'sqlite', 'mysql', '字段'] },
  { domain: '文档', words: ['文档', '说明书', '手册', '注释', '措辞', '散文', 'readme', '文档站'] },
  { domain: '产品', words: ['产品', '需求', '用户故事', '立项', '范围', '方案', '想法'] },
  { domain: '环境·运维', words: ['部署', '运维', '环境', '服务器', '进程', '沙箱', 'docker', 'powershell', 'windows', '路径'] },
  { domain: '求职·职业', words: ['求职', '简历', '面试', '作品集', '岗位', '招聘', 'jd', '自我介绍'] },
  { domain: 'AI-OS 自身', words: ['ai-os', 'aios', 'runtime', '运行时', '探针', '任务卡', '注入', '检索', '装配', '能力片'] },
]

/** 目录兜底（前缀匹配 · 先具体后宽泛；只对既有 `pathClass` 的目录级形态生效）。 */
const CELL_DOMAIN_DIRS: ReadonlyArray<readonly [string, string]> = [
  ['domains/frontend', '前端'],
  ['domains/backend', '后端'],
  ['domains/data', '数据'],
  ['domains/database', '数据'],
  ['domains/docs', '文档'],
  ['domains/doc', '文档'],
  ['domains/product', '产品'],
  ['domains/ops', '环境·运维'],
  ['domains/env', '环境·运维'],
  ['domains/career', '求职·职业'],
  ['domains/job', '求职·职业'],
  ['domains/ai-os', 'AI-OS 自身'],
  ['capabilities/', 'AI-OS 自身'],
  ['runtime/', 'AI-OS 自身'],
  ['tools/', 'AI-OS 自身'],
  ['task_cards/', 'AI-OS 自身'],
]

/** 扩展名兜底（只收**判得出**的；`.ts` / `.js` 两边都可能 ⇒ ⛔ 不收，宁可判不出）。
 *  ⚠️ 只在工作区外路径上可见（见上方边界①）。 */
const CELL_DOMAIN_EXTS: Record<string, string> = {
  tsx: '前端', jsx: '前端', vue: '前端', html: '前端', css: '前端', scss: '前端', sass: '前端', less: '前端',
  sql: '数据',
  md: '文档', mdx: '文档', rst: '文档', txt: '文档',
  py: '后端', go: '后端', java: '后端', rs: '后端', cs: '后端', php: '后端',
  ps1: '环境·运维', sh: '环境·运维', yml: '环境·运维', yaml: '环境·运维', toml: '环境·运维',
}

/** 单个领域词在文本里的位置（ASCII 词加词界，防 `ui` 命中 `build`；中文直接 indexOf）。 */
function cellWordAt(text: string, word: string): number {
  if (/^[A-Za-z0-9_.-]+$/.test(word)) {
    const re = new RegExp('(?<![A-Za-z0-9_-])' + word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?![A-Za-z0-9_-])', 'i')
    const m = re.exec(text)
    return m === null ? -1 : m.index
  }
  return text.indexOf(word)
}

/** `pathClass` ⇒ 领域（目录前缀优先；工作区外路径再试扩展名；都判不出 ⇒ null）。 */
function cellDomainOfPathClass(pathClass: string): string | null {
  const p = String(pathClass).replace(/\\/g, '/').toLowerCase()
  if (p === '') return null
  for (const pair of CELL_DOMAIN_DIRS) {
    if (p.startsWith(pair[0])) return pair[1]
  }
  const ext = (p.match(/\.([a-z0-9]{1,8})$/) || ['', ''])[1]
  if (ext !== '' && CELL_DOMAIN_EXTS[ext] !== undefined) return CELL_DOMAIN_EXTS[ext]
  return null
}

/**
 * **纯函数**：`work_topic`（+ 最近活动目录）⇒ 领域（8 值之一 / `null` = 判不出）。
 *   ① 词面：按**最早出现**定域（同位置取更长的词；再平票按 `CELL_DOMAIN_WORDS` 顺序）；
 *   ② 兜底：最近一条非空 `pathClass` 的目录 / 扩展名；
 *   ③ 判不出 ⇒ `null`。
 *   **格能力注入已删除** ⇒ 本函数**只**被 `inferDomainOf()` 调用（纯函数 · 单测仍断言）；
 *     ⛔ 不再有"命中格 / 回退检索注入"的调用方 —— 名字里的 `Cell` 是历史，⛔ 不要据此复活格路径。
 */
function inferCellDomain(topic: string, activity: readonly ActivityItem[] = []): string | null {
  const t = String(topic === undefined || topic === null ? '' : topic)
  let best: { domain: string; at: number; len: number } | null = null
  if (t !== '') {
    for (const d of CELL_DOMAIN_WORDS) {
      for (const w of d.words) {
        const at = cellWordAt(t, w)
        if (at < 0) continue
        if (best === null || at < best.at || (at === best.at && w.length > best.len)) {
          best = { domain: d.domain, at, len: w.length }
        }
      }
    }
  }
  if (best !== null) return best.domain
  for (let i = activity.length - 1; i >= 0; i--) {
    const pc = activity[i].pathClass
    if (pc === null || pc === undefined || pc === '') continue
    const d = cellDomainOfPathClass(pc)
    if (d !== null) return d
  }
  return null
}

// ── 🔴 **域能力注入**的三个纯函数（域判定 / 域⇒文件 / 渲染）────────────
//   为什么不再打分：能力库已域合并（8 个 `domain-*.md`，一域一文件）⇒ 域判定完就只剩**一个**文件，
//   打分与 top-N 都是多余变量。
//   🔴 **本节的「猜域」只保留为纯函数（历史 + 单测），⛔ 注入路径不再调用**：
//     读数：机器猜域精确率 —— topic 词表 **57%** / 检索工具 **47–59%** / 路径 **83%**，
//     均不可作为注入依据 ⇒ 已改为**读卡上声明**（`declaredDomainCapabilityOf()`）。

/**
 * **纯函数（⛔ 注入路径不再调用）**：`work_topic` ⇒ 域（8 值之一 / `null` = 判不出）。
 *   **复用同一份词表与口径**（`CELL_DOMAIN_WORDS` + `inferCellDomain()`）—— ⛔ 不新写第二套词表，
 *   否则两处判域迟早漂移（"域注入说文档、检索说后端"）。
 *   ⚠️ `activity` 恒空（只喂文本）：域注入的输入**只能**是"本会话占用卡的 topic"（与
 *      `buildPhaseRetrievalRequest` 同源）—— ⛔ 不拿最近活动目录兜底，否则同一 topic 会因
 *      上一步读了什么目录而换域（不可复现，A/B 也就无法归因）。
 *   🔴 读数：**机器猜域精确率 topic 57% / 检索 47–59% / 路径 83%，均不可作为注入依据**
 *      ⇒ 注入已改为**读卡上声明**。本函数**保留**（纯函数 · 单测 S187 仍在断言它），
 *      ⛔ 但**不再被注入路径调用** —— 改它不会改注入行为。
 */
function inferDomainOf(text: string): string | null {
  return inferCellDomain(String(text === undefined || text === null ? '' : text), [])
}

/**
 * **纯函数（⛔ 注入路径不再调用）**：域 ⇒ 域能力名（即 `capabilities/<capName>.md`
 *   的 `<capName>`；判不出 ⇒ `null`）。
 *   判据：扫 `capabilities/domain-*.md` 的**当前**文件，读 frontmatter 的 `domain:` 字段，
 *     **恰好相等**才命中（⛔ 不做域别名 / ⛔ 不做模糊匹配）。
 *   **每次现读、无缓存** ⇒ 改 / 删能力文件立即生效；读目录或读文件失败 ⇒ `null`（⛔ 不抛错）。
 *   🔴 读数：**机器猜域精确率 topic 57% / 检索 47–59% / 路径 83%，均不可作为注入依据**
 *      ⇒ 注入已改为**读卡上声明**。本函数**保留**（单测 S187 仍断言它 / 域标签读法复用
 *      `domainFrontmatterOf()`），⛔ 但**不再被注入路径调用**。
 */
function domainCapabilityOf(domain: string): string | null {
  const want = String(domain === undefined || domain === null ? '' : domain).trim()
  if (want === '') return null
  try {
    for (const f of readdirSync(domainCapDir())) {
      if (!/^domain-[^/\\]+\.md$/i.test(f)) continue
      const fm = domainFrontmatterOf(join(domainCapDir(), f))
      if (fm === null || fm.domain !== want) continue
      return f.replace(/\.md$/i, '')
    }
    return null
  } catch {
    return null
  }
}

/** **文件转储形态门** —— read/grep 结果的结构是 `<path>…</path><content>…</content>`；
 *  这类文本可能恰好包含错误格式示例（R2 读 PITFALLS 误触发），⛔ 不当作执行失败。 */
const REPEAT_MIN_OVERLAP = 3
const REPEAT_MIN_TOKENS = 5

/** T7′：「同一问题第 2 次」的**词面**近似（⛔ 不做语义 —— Runtime 边界）。 */
function isRepeatQuestion(prev: string, cur: string): boolean {
  const a = tokenSetOf(prev)
  const b = tokenSetOf(cur)
  if (a.size < REPEAT_MIN_TOKENS || b.size < REPEAT_MIN_TOKENS) return false
  let hit = 0
  for (const t of b) if (a.has(t)) hit++
  return hit >= REPEAT_MIN_OVERLAP
}

// ── （**纯函数 · 未接线**）：经验过程匹配器 ────────────────────
//   设计：`EXPERIENCE-MATCHER-DESIGN-.md`；规则来源：`PITFALLS-WHEN-RULES-.md`
//   （67 条 → 59 机械可判 / 8 纯语义）。⛔ 本批只加纯函数 + 单测，不改运行时行为；
//   接线（pre/post-execute 读规则表 → 命中注入）需 约定+ 重启。
interface ExperienceSignals {
  tool?: string
  path?: string
  cmd?: string
  error?: string
  repeat?: number
  env?: string
}
interface ExperienceRuleWhen {
  tool?: string[]
  path?: string
  cmd?: string
  error?: string
  repeat?: number
  env?: string
}
interface ExperienceRule {
  id: string
  when: ExperienceRuleWhen
  inject: string
  source?: string
  semantic?: boolean
}

/** 纯函数：信号 × 规则 → 命中规则（**OR** 语义 · 空 when 不匹配 · semantic 跳过）。 */
function matchExperienceRules(signals: ExperienceSignals, rules: readonly ExperienceRule[]): ExperienceRule[] {
  const out: ExperienceRule[] = []
  const low = (v: string | undefined): string => String(v === undefined || v === null ? '' : v).toLowerCase()
  const has = (v: string | undefined): boolean => v !== undefined && v !== null && v !== ''
  const reHit = (pattern: string, value: string | undefined): boolean => {
    if (!has(value)) return false
    try {
      return new RegExp(pattern, 'i').test(String(value))
    } catch {
      return String(value).toLowerCase().includes(pattern.toLowerCase())
    }
  }
  for (const r of rules) {
    if (r.semantic === true) continue
    const w = r.when !== undefined && r.when !== null ? r.when : {}
    const toolHit = Array.isArray(w.tool) && w.tool.length > 0 && has(signals.tool) &&
      w.tool.some(t => low(signals.tool) === low(t) || low(signals.tool).startsWith(low(t)))
    const hit = toolHit ||
      (has(w.path) && has(signals.path) && low(signals.path).includes(low(w.path))) ||
      (has(w.cmd) && has(signals.cmd) && low(signals.cmd).includes(low(w.cmd))) ||
      reHit(String(w.error !== undefined ? w.error : ''), signals.error) ||
      (typeof w.repeat === 'number' && typeof signals.repeat === 'number' && signals.repeat >= w.repeat) ||
      (has(w.env) && has(signals.env) && low(signals.env).includes(low(w.env)))
    if (hit) out.push(r)
  }
  return out
}

/** 样例规则（供单测；⛔ 不参与运行时 —— 接线时从 `PITFALLS-WHEN-RULES` 生成）。 */
const SAMPLE_EXPERIENCE_RULES: ExperienceRule[] = [
  { id: 'P61', when: { tool: ['task_card'], cmd: 'claim', error: 'State=Created' }, inject: 'create 后先把 State 改 Planning，再 claim', semantic: false },
  { id: 'P40', when: { tool: ['pytest'], error: 'WinError 5|PermissionError' }, inject: '用全新 basetemp 并放宽权限', semantic: false },
  { id: 'P63', when: { tool: ['pwsh'], cmd: 'Select-Object' }, inject: '验收前先读最后一条 ev=apply', semantic: false },
  { id: 'P4', when: {}, inject: '语义类：按 R3 新链路排查', semantic: true },
]

// ── 「该出现」= **阶段信号**，不是词表字面命中（裁定并授权试）──────
//   依据「出现肯定很模糊 —— '看着有点丑' / '改一下' / '开张卡继续' /
//     '开个新卡·新项目·慢慢聊' / '最后开始实现'」⇒ 这些是**阶段**，不是类型。
//   ⇒ 两轴分离：**轴 A 该不该出现 = 阶段**（规则判 · 不做语义）；**轴 B 出现什么 = 类型**（可留空）。
//   ⇒ **用户点名**「做个检索 / 找找能力」= 最高优先级（压过阶段）—— 词表里 `检索` 本就是帮助类型。
//   发布形态 = **catalog 式**：同一阶段不重复发，**阶段变了才换**（DSH skill catalog 同法 · 成本 ×1）。
type WorkPhase = 'planning' | 'starting' | 'implementing' | 'shifting' | 'reviewing' | 'stalled' | 'unknown'

/** 阶段词表（**只做字符串包含** · ⛔ 不猜语义、不调模型）。加词先写进本表并配单测。 */
const PHASE_WORDS: Record<string, readonly string[]> = {
  planning: ['新项目', '新卡', '慢慢聊', '慢聊', '先聊', '先想想', '想清楚', '规划', '还没开始', '不急'],
  starting: ['开张卡', '开个卡', '开工', '开始', '开张', '继续完成', '接着做', '继续任务', '接着干'],
  reviewing: ['检查', '审一下', '审一遍', '有没有问题', 'review', '复查', '验收'],
  shifting: ['不对', '丑', '重来', '换个', '不是这样', '不好看', '太丑', '改一下', '调整一下'],
  stalled: ['卡住', '不行', '报错', '失败', '怎么都不', '一直不', '搞不定'],
}

/**
 * 判定**工作阶段**（**纯函数** · 供单测）。
 * 优先级：stalled > shifting > reviewing > planning > starting > implementing。
 * ⛔ 不做语义推断：只用「词面包含 + 工具序列 + 连续失败」三类机械信号。
 */
function deriveWorkPhase(s: SessionState, text: string): WorkPhase {
  const t = String(text || '')
  const hasWord = (list: readonly string[]): boolean => list.some(w => t.includes(w))
  // 连续失败（最近 activity 尾部 ok===false 的条数）—— stalled 的**行为证据**，比词更硬
  const act = Array.isArray(s.wc.activity) ? s.wc.activity : []
  let streak = 0
  for (let i = act.length - 1; i >= 0; i--) {
    const a = act[i] as { ok?: boolean | null }
    if (a.ok === false) streak += 1
    else break
  }
  if (streak >= 2 || hasWord(PHASE_WORDS.stalled)) return 'stalled'
  if (hasWord(PHASE_WORDS.shifting)) return 'shifting'
  if (hasWord(PHASE_WORDS.reviewing)) return 'reviewing'
  const edited = s.wc.progress.signals.includes('has-edit')
  if (hasWord(PHASE_WORDS.planning) && !edited) return 'planning'
  if (hasWord(PHASE_WORDS.starting) || (s.cardEdits.size > 0 && !edited)) return 'starting'
  if (edited) return 'implementing'
  return 'unknown'
}

/** 阶段 → 注入文案（`''` = 不注入）。⛔ 只给情境，**不给类型**（"丑→美观"这类规则猜不到）。 */
function phaseHintText(key: string): string {
  switch (key) {
    case 'user-named':
      return '【AI-OS · 检索】你要求做一次检索。请调用 `auto_capability`：`what` 写当前在做什么，`need` 可填'
        + '（前端 / 后端 / 文档 / 调试 / 检索 / 评审…）—— 它会按字段去查能力 / 经验 / 候选。'
    case 'starting':
      return '【AI-OS · 开工】开始干活 / 开张卡后，先调一次 `auto_capability` 报「在做什么 + 需要哪类能力」，'
        + '后面的检索才有依据（⛔ 不必每步都报）。'
    case 'implementing':
      return '【AI-OS · 能力提示】需要某类能力时调 `auto_capability`（need 取词表三维）—— 它会按字段去查能力 / 经验 / 候选。'
    case 'shifting':
      return '【AI-OS · 方向变了】如果觉得不对 / 要改方向，重新调一次 `auto_capability` 说明新的「在做什么 + 哪不对」，'
        + '它会据此重新检索。'
    case 'stalled':
      return '【AI-OS · 卡住了】要不要调一次 `auto_capability`（`what`=卡在哪，`need` 可填「调试」）？'
        + '它会去找相关经验 / 排障做法。'
    default:
      return ''
  }
}

/** 阶段发布计数（**内存 · 会话级** · `dropSession` 同步释放）。 */
const PHASE_STATE = new Map<string, { published: string; count: number }>()

/**
 * 是否该发布（**纯函数** · 供单测）：catalog 式 —— **同一 key 不重复发**，变了才发，有上限。
 * `planning` / `unknown` 一律不发（还没到该打扰的时候）。
 */
function shouldPublishHint(slot: { published: string; count: number }, key: string, max: number): boolean {
  if (key === '' || key === 'unknown' || key === 'planning') return false
  if (slot.count >= max) return false
  if (slot.published === key) return false
  slot.published = key
  slot.count += 1
  return true
}

/**
 * 提醒判据（**全机械** · 每会话每类一次 · 调用即"记账已发"）：
 *   ⓪ `multi-claim` —— **一个对话同时占用了 > 1 张卡**（补丁）
 *   ① `no-anchor`  —— 本会话**既没改过卡、也没读过卡** ⇒ 还没有工作锚点
 *   ② `maintain` —— **已有锚点**（读过或改过卡）**且确有成功结果** ⇒ 该维护卡了
 * ⛔ 不含任何"看起来像新任务"的语义猜测；⛔ 不判断"任务是否完成"（停止 ≠ 结束）。
 * 🔴 三类提醒**都不代替宿主动作** —— 尤其 ⓪：Runtime ⛔ **不会**自动释放/替换多出来的占用，
 *    只把异常**说出来**让 Agent 收敛（`GOAL-INPUT-CONTRACT.md §2.6 S2 ①`：
 *    「Runtime / 脚本绝不自动改 `State`」）。
 */
function maintenanceChecklist(s: SessionState, session: string, cardsOverride?: TaskCursor[]): string | null {
  let now: Set<string>
  try {
    const cards = cardsOverride !== undefined ? cardsOverride : scanCards()
    now = new Set(myOccupiedCards(Object.assign({}, s, { cards }) as SessionState).map(c => String(c.key)))
  } catch {
    return null // 扫描失败 ⇒ 静默（⛔ 不影响宿主）
  }
  const st = MAINT_STATE.get(session)
  if (st === undefined) {
    MAINT_STATE.set(session, { owned: now, count: 0 })
    return null // 首次见到该会话 ⇒ 只建立基线，⛔ 不误报"刚释放"
  }
  const released = [...st.owned].filter(k => !now.has(k))
  st.owned = now
  // 🔴 （读数驱动）：从「每会话**一次**」改为「**每次失去占用**都提示 · 每会话上限 3」。
  //   读数场景：本对话 12:47 占卡 → 12:40 已用掉一次提示 → 12:50 被**另一个对话**
  //   （release --reason=takeover-orphan + claim）抢走 ⇒ `delivered=true` 早退 ⇒ **维护被吞掉**。
  //   ⇒ 同一个"失去占用"事件必须能被提示，否则"收工维护"在最该出现时缺席。
  if (st.count >= MAINT_MAX_PER_SESSION || released.length === 0) return null
  st.count += 1
  const names = released.map(k => String(k).split('/').pop()).join(' · ')
  // 🔴 （主线收尾 · 选 B）：把「R3 唤醒=关」的**模式边界**并入同一条清单。
  //   理由：hook 侧的 `ownership_lost` / `r3_notice_lost` 在 DSH 宿主下**不再注入**
  //   （唯一注入源纪律 = Runtime），它们原来的那半句信息由这里补齐；纯 CC 路线仍由 hook 出。
  // 🔴 「R3 状态提示**只需要会话开始**」⇒ 卡释放清单**不再带 R3 状态句**；
  //   唯一出口 = hook `r3_notice_start`（SessionStart，每会话一次，开/关都给）。
  const r3Tail = ''
  return '【AI-OS · 收工维护（R3）】卡 `' + names + '` 已释放。请逐条过一遍（Runtime 只提醒，⛔ 不自动改任何东西）：\n'
    + '1. INVENTORY：本次造出"别的对话会用到"的东西了吗？没登记就补一行（只给指针）。\n'
    + '2. ENV：机器 / 账号能力面有变化吗？（模型 / API / 工具版本 / 权限）\n'
    + '3. PITFALLS：这次踩到会再咬人的坑了吗？（现象 · 触发条件 · 处置）\n'
    + '4. 卡：State / Event Log / Next Action 是否是**当前**实况？\n'
    + '5. 探针体积：`.aios` 探针约 ' + String(probeSizeMb()) + ' MB（阈值待定）。\n'
    + '6. tests：`node runtime/tests/activation.test.mjs` 是否绿（已知红 1 = S37）。\n'
    + '维护完再开新工作；⛔ 不存密钥值 · ⛔ 不把一次性产物登记进 INVENTORY。'
    + r3Tail
}

// ── 🔴 · **R3 卡驱动唤醒（档 2）**───────────────
//   目标：本会话占用的卡被**别的会话 takeover** 后，**真唤醒**会话注入维护清单。
//   口径（定）：仅 takeover 触发（自己 release ⛔ 不触发）· 全部会话 ·
//     每会话 1 次 · 开关 `.aios/r3-wake.json` **默认关**（缺失 / 非严格 true ⇒ 关）。
//   触发源 = **卡文件真相**：`.log` 里「最后 = claim(B)，上一条 = release，reason 含
//     `takeover from A`」⇒ 被抢会话 = A ⇒ `agents.get(A)` → `agent.followup(清单)`。
//   ⇒ 不依赖本会话事件，**跨重启可用**（启动 5s 后补扫一次；窗口 30 分钟）。
//   ⚠️ 拿不到 live agent 时不冷恢复，只记探针（`state:'no-agent'`）。
//   ⛔ 不改卡 / 不写知识 / 不递送候选 —— 只投一条 user 消息（followup）。
function previousOccupantOf(raw: string, currentSession: string): string | null {
  if (!raw) return null
  const rows: { op: string; session: string }[] = []
  const re = /\|\s*(claim 占用|release 释放)（session:\s*([^）]*)）/g
  let m: RegExpExecArray | null
  while ((m = re.exec(raw)) !== null) {
    rows.push({ op: m[1] === 'claim 占用' ? 'claim' : 'release', session: String(m[2] || '').trim() })
  }
  for (let i = rows.length - 1; i >= 0; i--) {
    const r = rows[i]
    if (r.op === 'claim' && r.session !== '' && r.session !== currentSession) return r.session
  }
  return null
}

/**
 * 🔴 「**有过注入后就将开关关了**」⇒ R3 唤醒 = **一次性触发器**。
 *   真唤醒**注入成功一次**后，Runtime 自动把 `.aios/r3-wake.json` 写回 `enabled:false`（回到默认关）。
 *   为什么让 Runtime 自己关（而不是在维护清单里让 Agent 自查）：
 *     · R3 唤醒长期开着会**每 15s 轮询 + 常驻 fs.watch**；验收/测试时打开后极易**忘关**
 *       （读数： 打开 → 13:xx 仍是开，用户确认「可能是忘关了」）。
 *     · 一次性触发器的语义更贴合它原本的用途（「卡被 takeover ⇒ 提醒原会话收尾」是一次性事件）。
 *   边界（逐条）：
 *     ① 只在 **真的注入了**（`state:'ok'`）后关；`no-agent` / `failed` ⛔ 不关（没送达，不算用过）。
 *     ② **保留文件里的其它字段**（只改 `enabled`；⛔ 整体重写会误清用户手写的备注/其它键）。
 *     ③ **原子写**（同目录临时件 + rename），失败只记探针，⛔ 不影响唤醒本身。
 *     ④ 关掉后本进程内的 `enabled` 变量不再重读 ⇒ 调用方 `break`，不再唤醒其它受害会话。
 * @returns 是否成功写回（测试/诊断用）
 */
const STAGE4_DELIVER_TOP = 3

function renderCandidates(set: Record<string, any>, fieldObs: Record<string, unknown>, cardKey: string): string {
  const cands = Array.isArray(set.candidates) ? set.candidates : []
  const div = (set.diversity ?? {}) as Record<string, any>
  const lines: string[] = []
  lines.push('【AI-OS 能力候选（Runtime · 卡锚定）】')
  lines.push('焦点 `' + String(fieldObs.object ?? '-') + '`（' + String(fieldObs.confidence ?? '-')
    + ' · ' + String(fieldObs.source ?? '-') + ' · 卡 `' + cardKey + '`）')
  lines.push('候选 ' + cands.length + ' · 来源 '
    + (Array.isArray(div.sources) ? div.sources.join(' · ') : '-')
    + '（通道 ' + (Array.isArray(div.channels_used) ? div.channels_used.join(',') : '-') + '）')
  for (const c of cands.slice(0, STAGE4_DELIVER_TOP)) {
    const src = c.source ? String(c.source.id) : '-'
    lines.push('  · ' + String(c.id) + '  [' + src + '/' + String(c.role ?? '-') + ']')
  }
  lines.push('判据：字段→通道 + 类别对齐 · ⛔ 不含适用性结论（采不采纳由你判断）')
  lines.push('⚠️ 这是**候选**不是建议；不采纳不影响本步继续。')
  return lines.join('\n')
}

/**
 * 「本次 `post-execute` 是否有**任何**递送理由」—— 三个来源的逻辑**或**。
 * 🔴 抽成纯函数是为了**可隔离自测**：沙箱内 `child_process` 走 `pipe` 会 EPERM
 *    ⇒ 阶段 4 检索必然失败 ⇒ 造不出"已排队候选"这一前置条件，
 *    只能在判据层断言（端到端归真实宿主窗口验收）。
 * ⛔ 语义必须是"或"：**任一**来源存在即不得早退 —— 这正是 修的缺陷
 *    （原实现把它写成了"仅前两个来源的或"，第三个来源被静默吞掉）。
 */
const STAGE4_ENABLED = false
let STAGE4_DISABLED_ONCE = false

function dispatchStage4(s: SessionState, session: string): void {
  // 约定关闭 ⇒ 不再派发（只记一条一次性的探针，便于核验"确实关了"）
  if (!STAGE4_ENABLED) {
    if (!STAGE4_DISABLED_ONCE) {
      STAGE4_DISABLED_ONCE = true
      emit({
        ev: 'stage4', obs: OBS, session, outcome: 'disabled-by-human',
        note: 'Human 2026-10-28 裁定关闭（auto_capability 内联检索替代）· STAGE4_ENABLED=true 可回退',
        at: Date.now(), mono: mono(),
      })
    }
    return
  }
  // 🔴 **T3-lite**「轮开始时扫的卡」在同回合 claim 之后**已过期**——
  //   `s.cards` 只在 `agent/pre-step` 且 `msgs>0` 时重扫 ⇒ 本回合内 claim 的卡 stage4 看不见
  //   ⇒ 恒 `no-focus-card`（读数：重启后两次 stage4 都是这个原因，即使卡确实被占用）。
  //   ⇒ 派发前**现扫一次**（成本：~27 张 head + 1–2 张 `.log`/tail；stage4 是**低频率**事件，可接受）。
  //   ⚠️ 只刷新 `s.cards`（**卡池快照**），⛔ 不写文件、⛔ 不改卡、⛔ 不影响判定方向。
  try { s.cards = scanCards() } catch { /* 扫描失败 ⇒ 用旧快照（⛔ 不阻塞派发） */ }
  const probe = readStage4Probe()
  if (probe === null) return
  const m = sessionAllowsProbe(probe.session, session)
  if (!m.hit) return
  noteProbeAuth('stage4', session, probe.session, session, m)
  if ((STAGE4_DONE.get(session) ?? 0) >= probe.maxPerSession) return
  if ((STAGE4_INFLIGHT.get(session) ?? 0) > 0) {
    emit({ ev: 'stage4', obs: OBS, session, windowSeq: s.windowSeq, outcome: 'skipped-inflight', at: Date.now(), mono: mono() })
    return
  }
  // 🔴 焦点卡：**唯一依据 = `focusCardOf()`**（本会话的卡改动 ▸ 退回唯一 `Executing`）
  //    ⛔ 不得改用「git 工作区改动」或「`Executing` 张数」（`RESPONSIBILITY-BOUNDARIES.md §2` / V-2）
  const focus = focusCardOf(s)
  const cardKey = focus.key
  if (cardKey === null || cardKey === '') {
    emit({
      ev: 'stage4', obs: OBS, session, windowSeq: s.windowSeq, outcome: 'no-focus-card',
      focusBasis: focus.basis, cardEdits: s.cardEdits.size, at: Date.now(), mono: mono(),
    })
    return
  }
  const cardRel = 'task_cards/active/' + cardKey
  const t0 = Date.now()
  STAGE4_INFLIGHT.set(session, 1)
  STAGE4_DONE.set(session, (STAGE4_DONE.get(session) ?? 0) + 1)
  const base = {
    obs: OBS, session, windowSeq: s.windowSeq, card: cardKey,
    focusBasis: focus.basis, cardEdits: s.cardEdits.size,
  }
  // 🔴 活动证据：只作**探针派生读数**（供判读"卡 ↔ 会话是否错配"）
  const activityObs = s.wc.activity.slice(-PROGRESS_WINDOW)
    .map(a => a.tool + ':' + (a.pathClass === null ? '-' : String(a.pathClass)))

  // ── 🔴 推理文本 = **交叉裁决的输入**（**卡定对象，推理只做验证**）────────────────────
  //   为什么必须传：不传 ⇒ `counts` 为空 ⇒ 交叉裁决**从不触发** ⇒ `source` 恒为 `card-only`、
  //   `confidence` 恒为 `medium`。读数这条链在阶段 4 上曾是**空转**的。
  //   🔴 纪律（与影子通道完全一致）：
  //     · **只在内存**（`wc.reasoningEntries` 本就只在内存，`turn/end` 释放）
  //     · **只经 stdin** 传给**本地** python 子进程 —— ⛔ 不落盘 · ⛔ 不回显 · ⛔ 不进探针
  //     · 探针只记**条数 + 字符数**（派生量）
  //     · `allow_reason_only=False`（`_field_emit` 默认）⇒ 推理**永不取代卡对象**
  const reasonEntries = s.wc.reasoningEntries.slice().sort((x, y) => x.seq - y.seq)
  const reasoning: string[] = []
  let reasonChars = 0
  for (const e of reasonEntries.slice(-STAGE4_REASONING_ENTRIES)) {
    const t = String(e.text)
    if (reasonChars + t.length > STAGE4_REASONING_CHARS) break
    reasoning.push(t)
    reasonChars += t.length
  }

  // ① 字段：**已验证的**焦点对象产出机制（卡 + 推理**交叉裁决**）
  spawnJson(STAGE4_FIELD_ENTRY, { card: cardRel, session, reasoning }, probe.timeoutMs, (o1, field, detail1) => {
    if (o1 !== 'ok' || field === null || field === undefined) {
      STAGE4_INFLIGHT.set(session, 0)
      emit({ ...base, ev: 'stage4', step: 'field', outcome: o1, detail: detail1 ?? null, ms: Date.now() - t0, at: Date.now(), mono: mono() })
      return
    }
    const degraded = field.degraded === true
    const fieldObs = {
      object: typeof field.object === 'string' ? field.object : null,
      confidence: field.confidence ?? null,
      source: field.source ?? null,
      degraded,
      reasons: field.reasons ?? [],
      phrases: Array.isArray(field.phrases) ? field.phrases : [],
      categories: Array.isArray(field.categories) ? field.categories : [],
      activity: activityObs,
      // 🔴 只记**派生量**：推理条数与字符数 —— ⛔ 绝不落推理原文（纪律同影子通道）
      reasoning: { blocks: reasoning.length, chars: reasonChars },
      // 🔴 推理侧的**对象计数**（只计数、无原文）—— 判读"卡 ↔ 会话是否错配"的依据：
      //    `source=card-only` 而此处又出现**别的**对象 ⇒ 卡说的与会话在做的不是一件事
      reasonObjects: (field.evidence && field.evidence.reason_object_counts) || {},
    }
    if (degraded) {
      STAGE4_INFLIGHT.set(session, 0)
      emit({ ...base, ev: 'stage4', step: 'field', outcome: 'degraded-no-dispatch', field: fieldObs, ms: Date.now() - t0, at: Date.now(), mono: mono() })
      return
    }
    // ① Runtime 构造**请求**：🔴 —— 有 `auto_capability` ⇒ **按其字段**构造（work-report 通道）；
    //    否则回退到事件推导（旧通道保留 ⇒ 两条路可对照，⛔ 不删旧证据）
    const wr = latestWorkReport(session)
    const reqSource = wr !== null ? 'work-report' : 'event-derived'
    if (wr === null) {
      // 🔴 · **该用未用可数**：检索已到时机、但本会话从未 `auto_capability`
      //    ⇒ 只记一条派生读数（⛔ 不改行为、⛔ 不注入、⛔ 不拦派发）—— 用来回答"是不是只靠自觉"
      emit({
        ...base, ev: 'work-report-missed',
        triggerKind: s.lastTriggerKind ?? null, basis: s.activationBasis ?? null,
        reminderSent: s.reminderD === true,
        note: 'retrieval fired via event-derived channel; host never reported',
        at: Date.now(), mono: mono(),
      })
    }
    const req = wr !== null ? buildRetrievalRequestFromWorkReport(wr, s.wc, probe) : buildRetrievalRequest(field, s.wc, probe)
    // ② Retrieval（独立进程 · 既定规则）
    spawnJson(STAGE4_RETRIEVAL_ENTRY, { request: req }, probe.timeoutMs, (o2, set, detail2) => {
      STAGE4_INFLIGHT.set(session, 0)
      if (o2 !== 'ok' || set === null || set === undefined) {
        emit({
          ...base, ev: 'stage4', step: 'retrieval', outcome: o2, detail: detail2 ?? null,
          field: fieldObs, request: stage4RequestObs(req, reqSource), ms: Date.now() - t0, at: Date.now(), mono: mono(),
        })
        return
      }
      // ③ 核心收候选：**只取身份 / 来源 / 角色 / 通道** —— ⛔ 不取 `preview`（避免原文进探针）
      const cands = Array.isArray(set.candidates) ? set.candidates : []
      const status: Record<string, number> = {}
      for (const st of (Array.isArray(set.source_status) ? set.source_status : [])) {
        const k = String(st.status)
        status[k] = (status[k] ?? 0) + 1
      }
      const budget = (set.budget_applied ?? {}) as Record<string, any>
      emit({
        ...base,
        ev: 'stage4',
        step: 'retrieval',
        outcome: 'ok',
        field: fieldObs,
        request: stage4RequestObs(req, reqSource),
        result: {
          candidates: cands.length,
          truncated: budget.truncated === true,
          matchedBeforeBudget: budget.matched_before_budget ?? null,
          diversity: set.diversity ?? null,
          gaps: Array.isArray(set.gaps) ? set.gaps.map((g: any) => String(g.kind)) : [],
          sourceStatus: status,
          top: cands.slice(0, 5).map((c: any) => ({
            id: String(c.id),
            source: c.source ? String(c.source.id) : null,
            role: c.role ?? null,
            channels: c.hit_channels ?? [],
          })),
        },
        delivery: probe.deliver ? 'queued-for-next-post-execute' : 'probe-only (delivery off)',
        ms: Date.now() - t0,
        at: Date.now(),
        mono: mono(),
      })
      // ③ **存起来待递送**（第③段）—— 递送发生在**下一次** `post-execute`
      //    （检索是异步的 ⇒ 本次工具已经执行完，只能下一次带出）。`deliver` 关闭 ⇒ 不存（探针-only）。
      if (probe.deliver) {
        const st = SESSIONS.get(session)
        if (st !== undefined && st.deliveredCount < probe.maxPerSession) {
          st.pendingDelivery = {
            text: renderCandidates(set, fieldObs, cardKey),
            // 🔴 两处都用**派发时**快照，⛔ 不用回调时的 `s.windowSeq` / `Date.now()`：
            //    本回调是异步的，届时回合可能已前进 ⇒ 那会把"产出语境"记成"回收语境"，
            //    时效校验就永远判不出过期（自证成立的假护栏）。
            windowSeq: base.windowSeq,
            cardKey,
            at: t0,
          }
        }
      }
    })
  })
}

/**
 * 构造一条**合法的** `UserMessage`（`additionalContexts` 的元素类型）。
 * 🔴 上游 `createUserMessage()` 除了补 `id = randomUUID()` 与 freeze（`llm/src/message.ts:190-211`）
 *    不做别的 ⇒ 两者都用 `node:` 内置能力**手工等价实现**，**不引入任何外部 import**（守约束 1）。
 * ⚠️ `source` 必须是**生产者自有**的 kind（`session-format-v3-to-v4/message-sources.ts`）：
 *    v4 已废弃 `{ kind:'plugin', plugin }` 包装（`producerKind()` 对未登记插件一律改写为 `plugin:<name>`），
 *    再写 `kind:'plugin'` 会被 `assertV4MessageSources` 判为
 *    "format v4 message requires a producer-owned source kind" 并让整轮失败。
 */
function textOfContent(c: any): string {
  if (typeof c === 'string') return c
  if (Array.isArray(c)) {
    let out = ''
    for (const part of c) out += textOfContent(part)
    return out
  }
  if (c && typeof c === 'object') {
    if (typeof c.text === 'string') return c.text
    if (typeof c.content === 'string') return c.content
    if (Array.isArray(c.parts)) return textOfContent(c.parts)
  }
  return ''
}

/**
 * 取本回合的用户输入文本。优先 `role==='user'`；取不到才退到"最后一条有文本的消息"，
 * 并在 `src` 里**如实标注退化** —— 让真实窗口能分辨"判据保守"与"解析失效"。
 */
function extractPrompt(messages: any): PromptProbe {
  if (!Array.isArray(messages) || messages.length === 0) return { text: '', src: 'no-messages' }
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (!m || typeof m !== 'object' || m.role !== 'user') continue
    const t = textOfContent(m.content)
    if (t) return { text: t, src: 'role=user' }
  }
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (!m || typeof m !== 'object') continue
    const t = textOfContent(m.content)
    if (t) return { text: t, src: 'last-nonempty-fallback#' + i }
  }
  return { text: '', src: 'no-text-content' }
}

/** 归一化长度：去掉空白 / 标点 / 符号后剩几个字符（只用于阈值比较）。 */
function normalizedLen(s: string): number {
  try {
    return s.replace(/[\s\p{P}\p{S}]/gu, '').length
  } catch {
    return s.replace(/\s+/g, '').length
  }
}

/**
 * 剥离**宿主注入块**再判长度 —— 它们不是用户输入。
 * ⚠️ 未剥 ⇒ 用户只打了「继续」，但工作区指令 / 记忆块被并入同一条消息 ⇒ 长度虚高
 *    ⇒ 几乎每轮都判 unclassified ⇒ 每轮开等待窗口 ⇒ **正是 `§14.8` 要避免的"每轮出现"**。
 * ⚠️ 已知形态有限（真实注入形态**未验证**）⇒ 同时记录 `promptRawLen`：若真实窗口里
 *    rawLen 与 len 差很大，就是本剥离在起作用；若两者相同而输入明显含注入块 ⇒ 形态未覆盖，需补。
 */
const INJECTED_BLOCK_RE = /<(system-reminder|noema-memory|local-command-stdout|command-name)>[\s\S]*?<\/\1>/gi

function stripInjected(s: string): string {
  try {
    return s.replace(INJECTED_BLOCK_RE, ' ')
  } catch {
    return s
  }
}

/** 机械分类：**只回答"是不是极短输入"**，不回答"是不是明确的新任务"（见文件头 UNKNOWN B）。 */
function classifyPrompt(raw: string): { cls: PromptClass; len: number } {
  if (!raw) return { cls: 'unknown', len: 0 }
  const n = normalizedLen(raw)
  if (n === 0) return { cls: 'continuation', len: 0 }
  return { cls: n <= CONTINUATION_MAX_CHARS ? 'continuation' : 'unclassified', len: n }
}

// ── T1/T2：工作意图（§15.1 T1/T2 · 只认工具名，不记参数）────────────────────

/** 🔴 排除 AI-OS 自身机制类工具 —— 机制调用不是"工作方向"信号。 */
const MECHANISM_TOOL_RE = /^(task_start|task-start|wrapup_sync|wrapup-|task_card|experience_push|observe_extract|aios|noema)/i
/** T1：组织工作计划的工具（"形成可观察计划"）。 */
const PLAN_TOOL_RE = /^(todo_write|update_plan|write_plan|plan)/i
/** T2：实际工作工具（读 / 搜 / 改 / 跑）。**首版白名单 · 未列名的不算**（保守漏，不误报）。 */
const WORK_TOOL_RE = /^(read|grep|glob|edit|write|multi_edit|apply_patch|pwsh|powershell|bash|shell|run_command|exec_command|cat|ls|list_dir|find|rg|fd|node|python|git|npm|pnpm|web_fetch|web_search|notebook)/i

function intentKindOf(tool: string): IntentKind {
  if (!tool) return 'none'
  if (MECHANISM_TOOL_RE.test(tool)) return 'none'
  if (PLAN_TOOL_RE.test(tool)) return 'plan'
  if (WORK_TOOL_RE.test(tool)) return 'work'
  return 'none'
}

// ── 卡事实分类（阶段 2 原判据 · **未改**）────────────────────────────────

function pickFocus(list: TaskCursor[]): TaskCursor | null {
  return list.length === 1 ? list[0] : null
}

/**
 * §14.8 四类时机分类（机械判据 · 保守优先 · 顺序即优先级）。
 *   **基线** —— 首次观测（无游标）⇒ **D**：无法区分"新进入"与"早就在做"，不触发
 *   A 进入任务 —— `Executing` **集合出现新成员**（恰好一张 ⇒ 唯一可判）
 *   B 阶段变化 —— 焦点卡未变但 `Current Step` 变了
 *   C 普通对话 —— 焦点卡同 step ⇒ **保持安静**（去重在此生效）
 *   D 无法确定 —— 无卡 / 无 Executing / 多张同时新进入 / 焦点不可判 ⇒ **不猜**
 */
function classify(prev: Snapshot | null, cards: TaskCursor[]): { kind: TriggerKind; detail: string; focus: TaskCursor | null } {
  if (cards.length === 0) return { kind: 'D', detail: 'no active card matched', focus: null }

  const exec = cards.filter(c => /^executing$/i.test(c.state))
  if (exec.length === 0) return { kind: 'D', detail: 'no card in Executing', focus: null }

  if (prev === null) {
    return {
      kind: 'D',
      detail: 'baseline established (' + exec.length + ' Executing) — first observation never triggers',
      focus: pickFocus(exec),
    }
  }

  const fresh = exec.filter(c => !prev.execKeys.includes(c.key))
  if (fresh.length === 1) {
    return { kind: 'A', detail: 'card entered Executing: ' + fresh[0].key, focus: fresh[0] }
  }
  if (fresh.length > 1) {
    return { kind: 'D', detail: fresh.length + ' cards entered Executing at once — cannot disambiguate', focus: null }
  }

  // 无新进入 ⇒ 判定焦点卡是否延续 / 阶段是否变化
  if (exec.length === 1) {
    const cur = exec[0]
    if (prev.focus !== null && prev.focus.key === cur.key) {
      if ((prev.focusStep || '') !== (cur.step || '')) return { kind: 'B', detail: 'Current Step changed', focus: cur }
      return { kind: 'C', detail: 'same card, same step — stay quiet', focus: cur }
    }
    return { kind: 'D', detail: 'Executing set changed without a fresh entry — cannot attribute', focus: cur }
  }

  if (prev.focus !== null) {
    const same = exec.find(c => c.key === prev.focus!.key)
    if (same !== undefined) {
      if ((prev.focusStep || '') !== (same.step || '')) {
        return { kind: 'B', detail: 'Current Step changed (multi-Executing)', focus: same }
      }
      return { kind: 'C', detail: 'known card continues (multi-Executing) — stay quiet', focus: same }
    }
  }
  return {
    kind: 'D',
    detail: 'multiple Executing (' + exec.length + '), none newly entered — focus not determinable',
    focus: null,
  }
}

function emptyCounts(): Record<TriggerKind, number> {
  return { A: 0, B: 0, C: 0, D: 0 }
}

function emptyDiscoCounts(): Record<Discovery, number> {
  return { task_fact: 0, waiting: 0, deferred: 0, quiet: 0, none: 0, missed: 0 }
}

function dropSession(session: string): void {
  SESSIONS.delete(session)
  STAGE4_DONE.delete(session)
  STAGE4_INFLIGHT.delete(session)
  SHADOW_DONE.delete(session)
  SHADOW_DIAG.delete(session)
  // R3 的会话级基线（**同一生命周期** —— 只增不减会无界增长，与上面四个集合同理）
  MAINT_STATE.delete(session)
  // 事件驱动注入的会话级状态（Set + 升沿基线 · 同上）
  INJECT_EVENTS.delete(session)
  // 注入段失败探针的去重键（同上）
  for (const k of DELIVERY_ERR_SEEN) if (k.startsWith(session + '|')) DELIVERY_ERR_SEEN.delete(k)
  // 阶段发布计数（同上）
  PHASE_STATE.delete(session)
  // 🔴 阶段注入状态 + 已返回能力 id（同一生命周期 —— 只增不减会无界增长）
  PHASE_INJECT.delete(session)
  RETURNED_CAPABILITY_IDS.delete(session)
  // 🔴 （经验侧节点）：N1/N2/N3 的每节点每会话状态（同上 —— 只增不减会无界增长）
  NODE_INJECT.delete(session)
}

function stateFor(session: string, agent: any): SessionState {
  let s = SESSIONS.get(session)
  if (s === undefined) {
    const id = identityOf(agent)
    s = {
      identity: id.identity,
      basis: id.basis,
      phase: 'IDLE',
      todoSeenThisTurn: false,
      lastEvalTurn: null,
      cursor: null,
      counts: emptyCounts(),
      discoCounts: emptyDiscoCounts(),
      promptClass: 'unknown',
      waiting: false,
      windowSeq: 0,
      observedSeq: -1,
      intentSeenInWindow: false,
      turnSig: [],
      deferredSeen: false,
      lastTriggerKind: null,
      lastDiscovery: null,
      activationBasis: null,
      lastStepKey: null,
      todoSig: null,
      lastCwd: '',
      lastGoalHash: '',
      currentTurn: null,
      lastTurnSig: [],
      lastFocusKey: null,
      turnHadSuccess: false,
      lastStrongTpAt: null,
      pathClassRun: 0,
      lastPathClass: null,
      me: session,
      cards: [],
      cardEdits: new Map(),
      cardReads: new Map(),
      // 🔴 阶段判定（S4 收口）的内存记账 —— 与 `SESSIONS` 同生命周期
      cardReleaseCount: 0,
      releaseJustObserved: false,
      firstUserText: '', // 首条用户消息（首拍注入的 topic · 首次 pre-step 锁存）
      postExecuteCount: 0, // 本会话第几次 post-execute（首拍判定 = === 1）
      knownCardKeys: [],
      pendingDelivery: null,
      deliveredCount: 0,
      reminderA: false,
      reminderB: false,
      reminderC: false,
      reminderD: false,
      pendingWeakTpIndex: null,
      // 触发层调优状态（仅内存）
      lastUserTextClean: '',
      repeatQuestion: false,
      lastFailKind: null,
      injectsSinceRetrieval: 0,
      wc: emptyWorkContext(),
    }
    if (SESSIONS.size >= MAX_SESSIONS) {
      const oldest = SESSIONS.keys().next()
      // 🔴 走 `dropSession`（而不是只 `SESSIONS.delete`）⇒ 附属的会话级集合**同步**释放
      if (!oldest.done) dropSession(oldest.value)
    }
    SESSIONS.set(session, s)
  }
  return s
}

/**
 * 插件入口。只订阅回答阶段 2 验收所必需的事件。
 * @param ctx cordis Context（显式 `any`：见文件头约束 1）
 */
// ── 上行端口 `auto_capability`（工作模块的**唯一输入端口** · 授权）──────
//   契约：`CHANNEL-work_report-v0.1.md`（载荷 · 三条硬规则 · 可知性 A+C； 工具改名 `auto_capability`，文件名保留旧名）
//        `CONCLUSIONS-.md §十三/§十四`（检索输入 = 语料；⛔ 不建独立 `work_state` 文件）
//   边界（逐条硬约束 · ⛔ 不得扩大）
//     · **只记录宿主主动说的话** —— ⛔ 不推断、不猜语义（"工作理解"的责任在宿主 · #65）
//     · 探针只落**派生量**（字符数 / 计数 / 可信度）—— ⛔ 不落原文（与推理原文同一纪律）
//     · **立即 ack 不阻塞**；"结果稍后注入" —— 本版 ⛔ **不注入**（递送仍 `probe-only`）
//     · ⛔ 不改卡 · ⛔ 不判适用性 · ⛔ 不调远程 · ⛔ 不互相调用
//     · 语料只存**内存**（插件卸载即消失）⇒ 才由检索读取；⛔ 不落盘
//   为什么用 `ctx.inject(['tools'], …)` 而**不是** `export const inject = ['tools']`：
//     后者会让**整个插件**等 tools 就绪才 ACTIVE（现有提醒 / 焦点卡 / 探针全在下游）⇒ 时序回归风险；
//     `ctx.inject` 是**非阻塞**的"服务就绪后再做"（先例：`tool-schedule/src/index.ts:444`）。
const WORK_REPORT_NAME = 'auto_capability'
/** 每会话内存环形上限（防滥用 · ⛔ 不落盘 · 不是"任务事实"）。 */
const WORK_REPORT_MAX_PER_SESSION = 8
/** 单字段截断（内存侧；探针只记字符数，⛔ 不记内容）。 */
const WORK_REPORT_BUDGET_PER_SESSION = 8

/** 工具描述 = **常驻说明书**（可知性 A · DSH 每步把 tool schema 收进上下文）。
 *  🔴 改口径：「当你想用某种能力、或**要做某件事**时调它，就能得到想要的能力；
 *     例如做前端时调研它 → 返回前端相关 skill」⇒ 描述里**先给场景与效果**，再给边界。 */
const WORK_REPORT_DESC = [
  '**能力自动化通道**：说清你在做什么，**请使用它**，以便更好的完成任务 —— 相关工具 / 经验会自动找给你（不用你逐个去翻能力库）。',
  '例如：做前端页面时调它（need 写「前端」）→ 返回前端相关的 skill / 经验 / 候选；改文档时 → 返回文档类的。',
  '用户若说「做个检索」「找找能力」「查一下有没有相关经验」—— 也是调它（这类**点名**请求优先响应）。',
  '什么时候用：开始一件事时 · 想要某类能力时 · 方向变了 · 被甲方否定了 · 发现自己缺什么时。有变化才说，不必每步都报。',
  '什么时候别用：不要用它写日志 / 报账；不要上报你还没跟对方确认过的判断。',
  'confirmed **可省略**：缺省 = agent-inferred（你自己推断，只当假设存）；只有对方确认过才写 user。',
  '**调它就会先给你「8 个领域词表」**（前端 / 后端 / 数据 / 文档 / 产品 / 环境·运维 / 求职·职业 / AI-OS 自身）——'
    + '你从里面选一个，写进卡上「能力」字段即可；不需要先填别的字段。',
  '示例：{"what":"做作品集首页"} ⇒ 返回领域词表；选 `domain-job-search` 后用 task_card.py capability 记录。',
  '调用后会**同步跑一次检索**，把候选直接返回给你（id / 来源 / 角色 / 命中通道；最多等几秒）。',
].join('\n')

/** 参数 schema（**raw JSON Schema** · 与 `defineTool` 编译产物同形 —— 本文件零外部 import ⇒ 手写）。 */
const WORK_REPORT_PARAMS = {
  type: 'object',
  additionalProperties: false,
  properties: {
    what: { type: 'string', description: '必填：一句话说明现在在做什么（宿主的工作语言）。' },
    need: { type: 'array', items: { type: 'string' }, description: '能力类型（NEEDS-VOCAB 三维取值；每轴最多 6 个）。' },
    concern: { type: 'array', items: { type: 'string' }, description: '这次最在意什么（每轴最多 6 个）。' },
    fix: { type: 'string', description: '哪里不对：转述对方原话要点。' },
    note: { type: 'string', description: '自由文本补充（可选）。' },
    confirmed: { type: 'string', enum: ['user', 'agent-inferred'], description: '可省略：缺省=agent-inferred；user=对方确认过。' },
    card: { type: 'string', description: '任务卡（可省略；Runtime 用焦点卡补）。' },
    // 🔴 （「两步式选词」）：第一次 `phase:"vocab"` 只回词表（不检索），
    //    第二次带 `axes` 提交 ⇒ 按词表值做**确定性匹配**。默认 `submit`（旧调用行为不变）。
    phase: { type: 'string', enum: ['vocab', 'submit'], description: '两步式：先 "vocab" 拿词表（不检索），再从词表选值用 "submit" 提交（默认 submit）。' },
    axes: {
      type: 'object',
      additionalProperties: false,
      description: '从词表选（第二步）：三维值，每轴最多 6 个；⛔ 不要自创值（非词表值会被忽略）。',
      properties: {
        domain: { type: 'array', items: { type: 'string' }, description: '领域（如 前端 / 数据 / AI-OS 自身）。' },
        help: { type: 'array', items: { type: 'string' }, description: '帮助类型（如 实现 / 评审 / 调试）。' },
        concern: { type: 'array', items: { type: 'string' }, description: '关注面（如 正确性 / 可维护性）。' },
      },
    },
  },
  required: [],
}

/** 一条上报（**语料只留内存**）。⛔ 不含推理原文 · ⛔ 不含工具输出。 */
function reportOwnerOf(agent: any): { owner: string; identity: string; basis: string } {
  const self = agent !== undefined && agent !== null ? sessionIdOf(agent) : ''
  const id = agent !== undefined && agent !== null ? identityOf(agent) : { identity: 'unknown' as Identity, basis: 'no-agent' }
  if (id.identity === 'subagent') {
    const h = agent !== null && agent !== undefined && agent.session !== undefined ? agent.session.header : undefined
    const parent = h !== undefined && h !== null && typeof h.parentSession === 'string' ? String(h.parentSession) : ''
    if (parent !== '') return { owner: parent, identity: 'subagent', basis: 'parentSession' }
    return { owner: self, identity: 'subagent', basis: 'subagent-without-parent' }
  }
  return { owner: self, identity: String(id.identity), basis: id.basis }
}

/** 该会话还剩几次上报预算（**纯函数** · 供单测；⛔ 不读模块状态）。 */
function workReportBudgetLeft(used: number): number {
  return Math.max(0, WORK_REPORT_BUDGET_PER_SESSION - used)
}

/**
 * 🔴 · **词表文本**（两步式第一步 `phase:"vocab"` 返回给 Agent）。
 * 每次调用重读 `NEEDS-VOCAB.md`（小文件）· 读失败回退编译内常量（三维值，无示例词）。
 * ⛔ 不写文件 · ⛔ 不缓存（改词表即生效）· ⛔ 不占上报预算（这不是一次上报）。
 */
function vocabText(): string {
  const head = '【AI-OS · 领域词表】从下列 8 个**领域**里选一个 —— 就是你卡上「能力」要填的那个（一个域一个文件）：\n'
  const tail = '\n选好后：把该域写进卡 —— `python tools/task_card.py capability <ID> --name domain-xxx --why "<一句>"`；'
    + 'Runtime 按声明投递该域能力。⛔ 不要自创域。'
  try {
    const raw = readFileSync(join(AIOS_ROOT, 'capabilities', 'INDEX.md'), 'utf8')
    const rows: string[] = []
    for (const line of raw.split('\n')) {
      const m = /^\|\s*\d+\s*\|\s*`(domain-[a-z0-9-]+)`\s*\|\s*([^|]+?)\s*\|\s*\d+\s*\|\s*(.+?)\s*\|\s*$/.exec(line)
      if (m !== null) rows.push('· `' + m[1] + '`（' + m[2] + '）' + m[3])
    }
    if (rows.length > 0) return head + rows.join('\n') + tail
  } catch (err) {
    noteCatchFail('state:vocab', err)
    /* 回退常量 */
  }
  return head + WR_DOMAIN_VALUES.map(d => '· `' + d + '`').join('\n') + tail
}

/**
 * 规范化 + 校验（**纯函数** · 供单测）。⛔ 只做类型 / 长度约束，**不猜语义**。
 * 判据：`what` 非空 · `confirmed` 只能是两值之一（`CHANNEL §三` 三条硬规则）。
 */
function recordWorkReport(rep: WorkReportRecord, meta?: { identity?: string; basis?: string }): number {
  const list = WORK_REPORTS.get(rep.session) ?? []
  list.push(rep)
  while (list.length > WORK_REPORT_MAX_PER_SESSION) list.shift()
  WORK_REPORTS.set(rep.session, list)
  emit({
    ev: 'work-report', obs: OBS, session: rep.session, id: rep.id,
    chars: rep.chars, needCount: rep.needCount, concernCount: rep.concernCount,
    confirmed: rep.confirmed, hasFix: rep.hasFix, hasCard: rep.hasCard,
    identity: meta !== undefined && meta.identity !== undefined ? meta.identity : 'unknown',
    ownerBasis: meta !== undefined && meta.basis !== undefined ? meta.basis : 'unknown',
    total: list.length, budgetLeft: workReportBudgetLeft(list.length),
    note: '只记派生量 · ⛔ 不落原文', at: rep.at, mono: mono(),
  })
  return list.length
}

// ── · 「检索」同步返回（授权 · 一次改动解 G1+G2）────────────────────
//    🔴 为什么要动：stage4 的 deferred 等待窗口与「工作推进改卡 `Current Step` ⇒ verdict B ⇒ 关窗」
//       **互斥** ⇒ 读数 181 次派发里 153 次 `no-focus-card`、10-19 起 9 天 0 次成功。
//       `auto_capability` 是**明确事件 + 同步调用** ⇒ 检索直接在它里面跑，结果**随工具返回**。
//    纪律：⛔ 不落原文（只派生量）· ⛔ 不改卡 · ⛔ 不走注入通道（随工具返回）· 任何失败只降级为 ack。
//    ⛔ 不删 stage4（降为「无上报时的兜底」）· ⛔ 不开递送（`delivery` 仍 `probe-only`）。

/** 内联检索的宿主等待上限（超时/失败只降级为 ack · ⛔ 不影响上报成功）。
 *  🔴 3000 → **1500ms**（检索侧读数 300–400ms，1500 仍留 4x 余量）。 */
function retrievalNudgeText(): string {
  return '【AI-OS · 能力候选】以上候选不是建议：若**与当前任务适配或任务需要**，'
    + '请**打开对应能力文件**（`→` 那行）读取详细做法再动手；不适用可忽略，不影响本步继续。'
}

/**
 * **纯函数**：把检索结果渲染成**给宿主的文本行**（工具 `render` 用）。
 * 与 `renderCandidates()`（stage4 递送）刻意分开：那条走注入链、这条走**工具返回**（不占注入源）。
 * 每条候选三行：`id [来源/角色]` → 一句话介绍 → 位置。
 */
function retrievalLinesOf(r: any): string[] {
  if (r === null || r === undefined || typeof r !== 'object') return []
  const state = String(r.state !== undefined ? r.state : 'unknown')
  const cands: RetrievalCandidate[] = Array.isArray(r.candidates) ? r.candidates : []
  if (state !== 'ok') return ['检索未完成：' + state + '（不影响你继续；需要时可再调一次）']
  if (cands.length === 0) return ['候选 0（检索正常，但这一组字段没有匹配）—— 直接 grep / glob 关键词可能更快。']
  const head = '候选 ' + String(cands.length)
    + (typeof r.matchedBeforeBudget === 'number' && r.matchedBeforeBudget >= 0
      ? ' · 匹配 ' + String(r.matchedBeforeBudget) : '')
    + (Array.isArray(r.channels) && r.channels.length > 0 ? ' · 通道 ' + r.channels.join(',') : '')
  const lines = [head]
  for (const c of cands.slice(0, WORK_REPORT_RETRIEVAL_MAX_CANDIDATES)) {
    lines.push('  · ' + c.id + '  [' + c.source + '/' + c.role + ']')
    if (c.summary !== '') lines.push('    ' + c.summary)
    if (c.path !== '') lines.push('    → ' + c.path)
  }
  lines.push(retrievalNudgeEnabled()
    ? retrievalNudgeText()
    : '⚠️ 这是候选不是建议；不采纳不影响本步继续。')
  return lines
}

/**
 *  · **内联检索**：记录完一条上报后，**同步**跑一次检索（宿主最多等 `WORK_REPORT_RETRIEVAL_TIMEOUT_MS`）。
 * 失败/超时 ⇒ 把 `outcome` 原样作为 `state` 返回（⛔ 不抛 · ⛔ 不影响已成功的上报 ack）。
 */
function registerWorkReportTool(ctx: any): void {
  const registry = ctx !== null && ctx !== undefined && ctx.tools !== undefined && typeof ctx.tools.register === 'function' ? ctx.tools : null
  if (registry === null) {
    emit({ ev: 'work-report', obs: OBS, outcome: 'no-tools-service', at: Date.now(), mono: mono() })
    return
  }
  try {
    registry.register({
      name: WORK_REPORT_NAME,
      description: WORK_REPORT_DESC,
      parameters: WORK_REPORT_PARAMS,
      output: {
        schema: {
          type: 'object',
          additionalProperties: false,
          properties: {
            ok: { type: 'boolean' },
            id: { type: 'string' },
            note: { type: 'string' },
            // 两步式第一步只回词表（不检索、不记录）
            vocab: { type: 'string' },
            // 检索结果随**工具返回**（⛔ 不走注入通道）。schema 故意宽松：
            //    只声明顶层形状，深字段由 `retrievalLinesOf()` 以**白名单**渲染 ——
            //    避免未来检索侧加字段时被输出校验整条打回（`output.schema` 校验失败 = 整次调用失败）。
            retrieval: {
              type: 'object',
              properties: {
                state: { type: 'string' },
                candidates: { type: 'array' },
                channels: { type: 'array' },
                matchedBeforeBudget: { type: 'number' },
                ms: { type: 'number' },
              },
            },
          },
          required: ['ok', 'id', 'note'],
        },
        // 先回一句话（⛔ 不回显宿主上报的原文），再把**候选**逐行列出
        render: (_args: unknown, value: any) => {
          const head = String(value !== null && value !== undefined && value.note !== undefined ? value.note : '')
          // 🔴 两步式第一步：只回词表
          if (value !== null && value !== undefined && typeof value.vocab === 'string') {
            return [{ type: 'text', text: head + '\n' + value.vocab }]
          }
          const lines = [head, ...retrievalLinesOf(value !== null && value !== undefined ? value.retrieval : null)]
          return [{ type: 'text', text: lines.join('\n') }]
        },
      },
      // ⚠️ `exec` = `ToolRunContext`（含 `agent` / `signal` / `callId`）；这里只用 `agent` 取会话 id
      async execute(args: unknown, exec: any): Promise<unknown> {
        const agent = exec !== null && exec !== undefined ? exec.agent : undefined
        const who = reportOwnerOf(agent)
        const owner = who.owner
        // 🔴 两步式第一步：只回词表（不记录、不占预算、不检索）
        const a: Record<string, unknown> = args !== null && typeof args === 'object' ? args as Record<string, unknown> : {}
        // 用户口径：**调它先给领域词表**（不需要先填 need/axes/concern 等字段）
        const noAxes = (a.need === undefined || (Array.isArray(a.need) && a.need.length === 0))
          && a.axes === undefined && a.concern === undefined
        if (a.phase === 'vocab' || (a.phase !== 'submit' && noAxes)) {
          emit({ ev: 'work-report', obs: OBS, session: owner, identity: who.identity, outcome: 'vocab', at: Date.now(), mono: mono() })
          return {
            ok: true, id: '',
            note: '这是领域词表（**未记录、未检索**）：从 8 个领域里选一个，写进卡上「能力」字段即可。',
            vocab: vocabText(),
          }
        }
        // 🔴 调用预算（Hard cap）：超了**明确拒绝**（⛔ 不静默丢弃最旧一条 —— 那会让宿主以为上报成功）
        const used = (WORK_REPORTS.get(owner) ?? []).length
        if (used >= WORK_REPORT_BUDGET_PER_SESSION) {
          emit({
            ev: 'work-report', obs: OBS, session: owner, identity: who.identity,
            outcome: 'budget-exhausted', used, budget: WORK_REPORT_BUDGET_PER_SESSION,
            at: Date.now(), mono: mono(),
          })
          return {
            ok: false, id: '',
            note: '本会话上报预算已用尽（' + String(WORK_REPORT_BUDGET_PER_SESSION) + ' 次）—— 用已有信息继续工作，⛔ 不要重复上报。',
          }
        }
        const built = buildWorkReport(owner, args, Date.now())
        if (!built.ok || built.rep === null) {
          emit({ ev: 'work-report', obs: OBS, session: owner, identity: who.identity, outcome: 'rejected', why: built.why, at: Date.now(), mono: mono() })
          return { ok: false, id: '', note: '未记录：' + built.why }
        }
        const rep = built.rep
        recordWorkReport(rep, { identity: who.identity, basis: who.basis })
        // 检索**就在这一步**跑（不再等 stage4 的窗口 —— 那条路读数 9 天 0 次成功）。
        //    失败/超时 ⇒ 只降级为 ack；⛔ 不让宿主因为检索坏了而拿不到"已记录"。
        const retrieval = await inlineRetrieval(rep, owner)
        // 🔴 T5：检索**真的被调用了** ⇒ 注入限额清零（下一轮可以再提示）。
        {
          const sty = SESSIONS.get(owner)
          if (sty !== undefined) sty.injectsSinceRetrieval = 0
        }
        return {
          ok: true,
          id: rep.id,
          note: '已记录 ' + rep.id + '（' + String(rep.chars) + ' 字符 · confirmed=' + rep.confirmed
            + ' · ' + who.identity + '）' + (who.basis === 'parentSession' ? '已归并到主会话' : '')
            + '；检索已同步返回（候选见下）。',
          retrieval,
        }
      },
    })
    emit({ ev: 'work-report', obs: OBS, outcome: 'registered', tool: WORK_REPORT_NAME, at: Date.now(), mono: mono() })
  } catch (err) {
    emit({ ev: 'work-report', obs: OBS, outcome: 'register-failed', detail: clip(String(err), 160), at: Date.now(), mono: mono() })
  }
}

/**
 * **仅供隔离自测**的判据入口（`runtime/tests/activation.test.mjs`）。
 * 🔴 为什么必须导出：这两条判据的**端到端**验证要真实 `spawn`（阶段 4 检索），
 *    而沙箱内 `child_process` 走 `pipe` 会 EPERM ⇒ 检索必然失败 ⇒ 造不出"已排队候选"。
 *    ⇒ 判据单独可测（纯函数 · 无副作用 · 不读文件 · 不写探针），端到端归真实宿主窗口验收。
 * ⛔ DSH 宿主只读 `name` / `inject` / `apply` —— 本导出**不参与**宿主契约，改它不影响链路。
 */
export const __selftest = {
  deliverySourcesActive, pendingStaleReason, PENDING_DELIVERY_MAX_AGE_MS,
  aiosStateDir, resolveStateFile,
  // 工具脚本解析（`<root>/tools/`）—— 供 S121 断言 entry 指向真实文件
  resolveToolScript,
  // 焦点卡接口（步 1 · 只写侧）
  writeFocusCard, FOCUS_CARD_STATS, FOCUS_CARD_TTL_MS, FOCUS_CARD_SCHEMA, focusCardFile,
  // 焦点卡判据（步骤 2：读**卡上真相** · 供 S98 断言"编辑卡 ≠ 占用卡"）
  focusCardOf, cardCmdsOf, myOccupiedCards,
  // 占用留痕解析（步骤 2：`Event Log` 尾行 ⇒ `{op, session}` · 供 S101 单测纯函数）
  lastOccupancyOf,
  // 提醒判据（`multi-claim` 补丁 · 供 S99 断言"多占用 ⇒ 只提醒、不自动改"）
  reminderFor,
  // 启动回收判据（作废上个进程的遗留占用 · 供 S100 单测纯函数）
  legacyExecutingCards,
  // 启动回收 ID 解析（真修复 · 不剥项目前缀 · 供 S142）
  startupRecoverIdOf,
  //  上行端口（纯函数 · 供 S102 断言校验/截断；⛔ 不暴露写盘或注册副作用）
  buildWorkReport, WORK_REPORT_MAX_PER_SESSION, WORK_REPORT_AXIS_MAX, WORK_REPORT_FIELD_MAX,
  //  两步式选词（纯函数 + 常量 · 供 S111；⛔ 不写盘 / 不检索）
  vocabText, WR_DOMAIN_VALUES, WR_HELP_TYPES, WR_CONCERN_VALUES, STAGE4_ENABLED,
  //  内联检索（纯函数 · 供 S109 断言「只带白名单字段 / 失败不抛」；⛔ 不触发 spawn）
  retrievalCandidatesOf, retrievalLinesOf,
  WORK_REPORT_RETRIEVAL_TIMEOUT_MS, WORK_REPORT_RETRIEVAL_MAX_CANDIDATES, WORK_REPORT_RETRIEVAL_MAX_PER_SOURCE,
  WORK_REPORT_RETRIEVAL_SUMMARY_CHARS,
  //  字段 → 通道映射（纯函数 · 供 S103 断言；⛔ 不触发 spawn / 不读文件）
  buildRetrievalRequestFromWorkReport, stage4RequestObs,
  //  归属 / 预算 / C 提醒（纯函数 + 只读状态 · 供 S104；⛔ 不写盘）
  reportOwnerOf, workReportBudgetLeft, WORK_REPORT_BUDGET_PER_SESSION, WORK_REPORTS,
  //  R3 维护判据（纯函数 + 只读模块状态 · 供 S105；⛔ 不写盘）
  maintenanceChecklist, MAINT_STATE, MAINT_MAX_PER_SESSION,
  //  R3 卡驱动唤醒（纯函数 + 常量 · 供 S110；⛔ 不触发 watcher / 不读真实卡 / 不写盘）
  takeoverFromLog, r3WakeText, disarmR3Wake, R3_MAX_PER_SESSION, R3_WAKE_DEBOUNCE_MS, R3_WAKE_WINDOW_MS,
  // claim 后向前一不同会话注入接手检查（纯函数 · 供 S130/S131）
  previousOccupantOf, r3HandoffText,
  //  事件驱动注入（纯函数 + 只读状态 · 供 S106；⛔ 不写盘）
  //   ⚠️ 的 shouldInjectHint / INJECT_STATE / INJECT_HINT_TEXT 已随 **删除**
  detectEvents, shouldPublishEvent, eventHintText, INJECT_EVENTS,
  //  触发层调优（纯函数 · 供 S115/S116/S117；⛔ 不读文件 / 不写盘）
  failKindOf, tokenSetOf, isRepeatQuestion, injectAllowedByBudget,
  INJECT_MAX_WITHOUT_RETRIEVAL, REPEAT_MIN_OVERLAP, REPEAT_MIN_TOKENS,
  //  返回层调优（纯函数 · 供 S118；⛔ 不改检索器）
  rerankCandidatesByWhat,
  //  经验召回（纯函数 · 供 S119；⛔ 不 spawn / 不写盘）
  recallTriggerOf, buildExperienceQuery, renderExperienceRecall, recallAllowed, emptyRecallSlot,
  EXPERIENCE_RECALL_MAX_PER_SESSION, EXPERIENCE_RECALL_MIN_SCORE, EXPERIENCE_RECALL_MIN_TURN_GAP,
  // （真实任务观测后）：触发/查询的纯函数与常量（供 S123–S126；⛔ 不 spawn / 不读文件）
  EXIT_MARK_RE, EXEC_TOOL_RE, isExecToolName, looksLikeFileDump, RECALL_FACTUAL_EXTRA_RE,
  // 发布/推送节点（纯函数 + 正则 · 供 S137/S138；⛔ 不写盘 / 不发消息）
  PUSH_RELEASE_CMD_RE, pushReleaseHintText,
  // 改本体节点（纯函数 + 正则 · 供 S143/S144）
  RUNTIME_EDIT_PATH_RE, RUNTIME_EDIT_TOOL_RE, runtimeEditHintText,
  // 限额/限流类错误不当知识缺口（纯常量 · 供 S139）
  RECALL_QUOTA_RE,
  EXEC_ERROR_CONTEXT_RE,
  stripRepoPaths, COMMON_TOOL_NAME_RE, PERMISSION_DETAIL_RE,
  //  经验过程匹配器（纯函数 · 供 S120；⛔ 未接线 / 不读文件）
  matchExperienceRules, SAMPLE_EXPERIENCE_RULES,
  //  能力候选后的打开约束（纯函数 + 只读开关 · 供 S112；⛔ 不写盘）
  retrievalNudgeText, retrievalNudgeEnabled,
  //  阶段判据（纯函数 · 供 S107；⛔ 不读文件）
  deriveWorkPhase, detectRetrievalRequest, phaseHintText, shouldPublishHint, PHASE_STATE, PHASE_WORDS, RETRIEVAL_WORDS,
  // ////阶段判定 + 按 phases 注入能力描述 + topic 分层 + 打分 + 注入条数（=1）（供 S145–S152/S156–S158）
  //   ⛔ 不触发 spawn（`spawnJson` 只在真实 post-execute 接线里跑）/ ⛔ 不写盘
  phaseOf, PHASE_TITLE, buildPhaseRetrievalRequest, renderPhaseCandidates, isCapabilityCandidatePath,
  // （实验 B）：**会话首拍**请求构造（纯函数 · 供 S165；⛔ 不 spawn / 不写盘）
  buildFirstStepRetrievalRequest,
// 首拍注入的**总开关常量**（供 S165 断言"默认关"；关闭态零注入零探针）
  FIRST_STEP_INJECT_ENABLED,
  phaseTopicOf, PHASE_TOPIC_MAX, PHASE_TOPIC_SEP,
// 请求的 `axes` 两级来源（纯函数 + 常量 · 供 S162–S164；⛔ 不读文件 / 不 spawn）
  phaseAxesOf, PHASE_DEFAULT_HELP,
// 打分纯函数 + 权重常量（⛔ 不读文件 / 不调远程；分数只进探针）
  phaseCapScoreOf, hasCapScoreSignals, PHASE_SCORE_W,
  phaseInjectEnabled, phaseInjectSlotOf, emptyPhaseInjectSlot, PHASE_INJECT, PHASE_MAX_CANDIDATES,
// 请求 `budget` 的池子常量（与注入条数解耦 · 供 S148/S157 断言）
  PHASE_BUDGET_CANDIDATES,
  rememberCapabilityIds, capabilityIdsOf, RETURNED_CAPABILITY_IDS,
  // 🔴 格能力（阶段 × 领域）已**整段删除**（`CELLS.md` 已归档 ⇒ 无活引用）；
  //   对应导出（capCellsEnabled / parseCellsTable / cellOf / renderCellCandidates / cellInjectOf /
  //   inferCellDomain / cellDomainOfPathClass / CELL_CLASS_OF_PHASE）同步移除 ⇒ ⛔ 不留悬空导出。
  // A/B 前置之后：**只剩** `.aios/cap-cells.json` 的 `max` 读法（检索路径 `phaseMaxCandidates()` 在用）
  //   ⚠️ 会读 `.aios/cap-cells.json`（懒读 · 无缓存）⇒ 测试用 `AIOS_STATE_DIR` 隔离
  capCellsConfig, phaseMaxCandidates,
  // 能力**合规提醒**（nudge）—— 开关读法 / 三处记录检测 / 提醒正文
  //   （纯函数 + 只读 `.log` · ⛔ 不 spawn / ⛔ 不写盘；`nudge:"off"`（缺省）⇒ 接线段零执行零探针）
  capNudgeEnabled, capNudgeOf, missingCapRecordsOf, missingCapRecordsOnCard,
  CAP_NUDGE_TEXT, CAP_NUDGE_NEED, CAP_RECORD_MARKS,
  // （已授权「1可以」）：**域能力注入** —— 开关读法 / 域判定 / 域⇒能力名 /
  //   intro 原文 / 注入文本渲染（纯函数 + 只读 `capabilities/domain-*.md`）
  //   （⛔ 不 spawn / ⛔ 不写盘；`domainInject:"off"`（缺省）⇒ 接线段零执行零探针）
  domainInjectEnabled, domainInjectOf, inferDomainOf, domainCapabilityOf, domainIntroOf, renderDomainInjection,
  // **注入跟随卡上声明的域能力** —— 声明读取（`.log` 末条 /
  //   卡正文「## 使用的能力」）/ 旧名 ⇒ 域能力映射（`_aliases.json`）/ 域标签
  //   （纯函数 + 只读卡与 `.log` · ⛔ 不 spawn / ⛔ 不写盘 · 不回退猜域）
  declaredDomainCapabilityOf, declaredCapOfLog, declaredCapOfCardBody,
  domainCapabilityResolvedOf, domainLabelOf, cardMdPathOf,
  // （经验侧节点）：N1/N2/N3 判据 + 文案 + 会话级状态（纯函数 + 只读状态 · 供 S153–S155）
  //   ⛔ 不 spawn / 不读文件 / 不写盘；`NODE_INJECT` 只作"每节点每会话一次"的只读断言入口
  nodeHintOf, isCorpusEditTarget, nodeHintTextOf, corpusNodeHintText, indexNodeHintText, regressionNodeHintText,
  NODE_INJECT, nodeInjectSlotOf, emptyNodeInjectSlot, NODE_HELP_ONLY_RE,
  NODE_CORPUS_DOMAINS_RE, NODE_CORPUS_PITFALLS_RE, NODE_CORPUS_DIGEST_RE, NODE_INDEX_BUILD_RE, NODE_REGRESSION_CMD_RE,
  //  占用判据（外置日志优先 · 供 S108；⚠️ 会读文件，测试只用隔离临时卡树）
  occupancyOfCard,
}

/** 🔴 （审计）：**静默失败的可观测化** —— 每个 `where` 每进程只记一次
 *   （⛔ 不刷屏；⛔ 探针通道自身失败时不递归 emit）。
 *   背景：`apply` 里 9 处 catch 的注释都写着「观察/判定失败绝不影响决策链」——这正是 ** 故障同款**：
 *   失败静默 ⇒ 注入/判定不出、且零探针，事后只能靠"什么都没发生"反推。 */
export function apply(ctx: any): void {
  // ⚠️ `policy` 串是**版本标记**：改同一 entry 的文件内容**不热重载**（`p0/HANDOFF §10.2 ④`），
  //    故重启后用这一行判定"是否真的加载了新内容"
  //    （`v2-windowseq` = 修掉 turn 依赖 · `v3-step-sig` = 两项 Observe-only 增补
  //     · `v4-winseq-topdir` = 补 `trigger.windowSeq` + 修 step 首条序号 + 工作区外放宽顶层目录名
  //     · `v5-todo-cwd` = 组合信号增补：S1 todo 计划 · S4 cwd · S2 卡 Goal/Next Action）。
  //     · `v6-workctx` = Step A′：WorkContext 六段 + 证据元数据 + 推理流结构观察（Observe-only）。
  //     · `v7-turnend-fill` = 口径修正：回合末补记 `wc-fill`（`turn-end`）+ `reasoningLiveChars`。
  //     · `v8-delivery-probe` = **Step B′ 最小递送验证**（`§二十六 26.13` · 批准）：
  //        `tools/post-execute` 可附 `additionalContexts`（**默认关闭 · 开关为本地文件 · 每次重读**）。
  //     · `v9-reasoning-read` = **阶段 2「内容读取」**（批准实施）：
  //        推理**文本**进内存 WorkContext · 显式标识优先/FIFO 有条件归属 · 32k 上限整条淘汰 ·
  //        **正式释放点 = `session/event` 的 `turn/end`**（`turn-stopping` 只作观测）。
  //        ⚠️ `OBS` **仍刻意不升版**（保住段 2h 连续性）：本次**只增可选事件**，不改既有字段语义。
  //     · `-retention-policy` = **阶段三 3.1 保留策略第一版**（裁定 `§28.13`
  //        + `§三十` 3.1「实施第一版」）：淘汰由 **FIFO** 换成 ** 端点 + 转折点 + 可证明重复
  //        + 兜底**；新增信息缺口元数据（`historyCoverage` / `evicted*` / `evictedSeqRanges`）= **R8**；
  //        全保护时 `evictBlocked:'all-protected'`（**允许超预算**，不静默丢保护对象）。
  //        🔴 本版**仍不递送 · 不检索 · 不调远程**；淘汰 = **内存预算管理**，
  //           被淘汰对象称「**预算约束下的淘汰对象**」，**不得**称"已确认无价值的内容"。
  //        ⚠️ `OBS` 仍**不升版**（只增可选字段；解析纪律见 `STAGE2-...-DESIGN.md §7.1`）。
  //     · `-narrowed-p1-hard-budget` = **阶段三 3.1 收窄版**（裁定 ·
  //        依据 = 只读回放在**两组真实历史数据**上复现"预算不收敛"· `§31.7`/`§31.8`）：
  //        ① **总字符上限 = 硬约束**（任何保留偏好不得覆盖）⇒ **分层降级链**
  //           L1 → L2 无保护 → L3 -强 → L4 ⇒ **保证收敛**； **不再是豁免权**
  //        ② **收窄 **：只有**强信号**进保护集合 —— Todo 实质变化 / 任务·项目映射变化（焦点卡切换）/
  //           **有明确结果支持的阶段转变** / 报错·attempt；**工具对象变化降为弱信号**（默认不保护·
  //           仅 `TP_ADJACENT_MS` 邻接或 `TP_SUSTAIN_COUNT` 持续才升级）
  //        ③ `evictBlocked:'all-protected'` **取消** ⇒ 改为 `overBudgetFloor`（**物理下限** · 如实记）
  //        ④ 参数由**回放选定**（非拍脑袋）：`TP_ADJACENT_MS = 60s` / `TP_SUSTAIN_COUNT = 5`
  //     · `-shadow-discovery` = **阶段三 3.2 影子发现通道**：
  //        `tools/post-execute` 之后**异步**派发一次 A/B 本地发现（A = 现有工作上下文 ·
  //        B = A + 推理文本 · **仅此一项不同**）⇒ 经 **stdin** 传**本地 Python** 子进程，
  //        **只写探针派生量**（候选 id / 分数 / gate / 耗时 / 查询长度 / 失败原因）。
  //        🔴 **默认关闭**（本地开关文件缺失即**完全透明**）· **不递送** · 不调远程 · 不落原文 ·
  //           **不阻塞**（异步 + 超时 kill + 每会话 1 并发）· 任何失败只记探针。
  //        ⚠️ A 组**不含任务卡正文**（`AB-DESIGN §4.1`）⇒ 检验"检索是否依赖任务卡"。
  //     · `-delivery-boundary+stale-guard` = **阶段 1 第一刀：四项行为修正**
  //        ① 递送边界：三来源**逻辑或**（`deliverySourcesActive()`）—— 修掉"候选递送被静态/提醒探针绑架"
  //        ② 候选时效：`pendingDelivery` 带身份（回合序号/焦点卡/时间戳）⇒ 过期即丢弃 + `ev=stage4-drop`
  //        ③ 状态目录与四个探针路径改为**每次调用重算**（启动后创建 `.aios/` 也能被感知）
  //        ④ 会话级集合统一生命周期（`dropSession()` · 随 `SESSIONS` 上限一起释放）
  //        ⛔ 未动检索权重/阈值/语料 · ⛔ 未打开递送 · ⛔ 未动 Hook 越界职责
  emit({ ev: 'apply', plugin: name, t: T0, cardsDir: CARDS_DIR, obs: OBS, policy: POLICY })

  // 挂上行端口 `auto_capability`（**不阻塞插件就绪** —— 用 `ctx.inject` 等 `tools`，不改 `inject` 声明）
  try {
    if (typeof ctx.inject === 'function') {
      ctx.inject(['tools'], (toolCtx: any) => { registerWorkReportTool(toolCtx) })
    } else {
      // 老宿主没有 `ctx.inject` ⇒ 退化为直接尝试（tools 已就绪时成立；否则只记探针）
      registerWorkReportTool(ctx)
    }
  } catch (err) {
    emit({ ev: 'work-report', obs: OBS, outcome: 'wire-failed', detail: clip(String(err), 160), at: Date.now(), mono: mono() })
  }

  // 🔴 **启动回收**（异步 · ⛔ 不阻塞插件加载）—— 作废上一个进程的遗留占用。
  //    ⚠️ 这一步**破例**让 Runtime 触发"改卡 State"（写入口仍是 `task_card.py`）；
  //    只在新进程启动时做一次 ⇒ 之后的 `Executing` 必定是本进程内某个会话 claim 的。
  setTimeout(() => { try { startupRecover() } catch { /* 静默 */ } }, 0)

  // 🔴 · **R3 卡驱动唤醒（档 2）** —— watcher 常驻监听卡目录；**是否唤醒由
  //    `.aios/r3-wake.json` 决定**（默认关 ⇒ 改即生效，无需重启）。失败只记探针。
  try {
    installR3Wake(ctx)
  } catch (err) {
    emit({ ev: 'r3-wake', obs: OBS, state: 'install-failed', detail: clip(String(err), 160), at: Date.now(), mono: mono() })
  }

  ctx.effect(() => {
    emit({ ev: 'active', plugin: name, note: 'trigger resolver attached', at: Date.now() })
    return () => {
      emit({ ev: 'dispose', plugin: name, sessions: SESSIONS.size, at: Date.now() })
      // 内存状态随插件卸载消失 —— 这正是它"不是事实源"的体现。
      // 🔴 附属的会话级集合同步清空（它们与 `SESSIONS` 是**同一生命周期** —— 见 `dropSession()`；
      //    残留会在"卸载后重新 apply"时变成幽灵条目：会话已被遗忘，计数却还在）。
      SESSIONS.clear()
      STAGE4_DONE.clear()
      STAGE4_INFLIGHT.clear()
      SHADOW_DONE.clear()
      SHADOW_DIAG.clear()
      // 🔴 阶段注入的会话级状态（同生命周期）
      PHASE_INJECT.clear()
      RETURNED_CAPABILITY_IDS.clear()
      // 🔴 （经验侧节点）：N1/N2/N3 的会话级状态（同生命周期）
      NODE_INJECT.clear()
    }
  }, 'aios-activation: lifetime')

  // ── 身份确定 + 任务边界（§14.8 信号表 / §14.9 隔离）──
  ctx.on('agent/session-start', (payload: any) => {
    const p = payload || {}
    const id = identityOf(p.agent)
    const session = sessionIdOf(p.agent)
    const s = stateFor(session, p.agent)
    s.identity = id.identity
    s.basis = id.basis
    // §12.0.1：开工时还不知道用户要做什么 ⇒ 一律 IDLE，不因 resume/startup 本身激活
    s.phase = 'IDLE'
    s.lastEvalTurn = null
    // 等待窗口**不跨回合、更不跨会话**：会话开始一律清空
    s.waiting = false
    s.intentSeenInWindow = false
    s.windowSeq = 0
    s.observedSeq = -1
    s.promptClass = 'unknown'
    // 回合级观察状态同样清空（会话开始 ⇒ 不继承任何上一回合的签名）
    s.turnSig = []
    s.deferredSeen = false
    s.lastTriggerKind = null
    s.lastDiscovery = null
    s.activationBasis = null
    s.lastStepKey = null
    // 组合信号的内存态同样清空（会话开始 ⇒ 不继承任何上一会话的签名 / 哈希）
    s.todoSig = null
    s.lastCwd = ''
    s.lastGoalHash = ''
    // 阶段三 3.1：回合游标与上一回合签名同样不跨会话继承
    s.currentTurn = null
    s.lastTurnSig = []
    s.lastFocusKey = null
    s.turnHadSuccess = false
    s.lastStrongTpAt = null
    s.pathClassRun = 0
    s.lastPathClass = null
    s.pendingWeakTpIndex = null
    // Step A′：WorkContext 是**可重建的会话内快照** ⇒ 会话开始一律重建（不继承上一会话）
    s.wc = emptyWorkContext()
    emit({
      ev: 'session-start',
      session,
      source: p.source,
      identity: id.identity,
      basis: id.basis,
      phase: s.phase,
      at: Date.now(),
    })
  })

  // ── 每步极轻量检查（§14.9.3 约束②）· waterfall ⇒ 必须透明 next() ──
  ctx.on('agent/pre-step', (payload: any, next: any) => {
    try {
      const p = payload || {}
      const session = sessionIdOf(p.agent)
      const turn = typeof p.turn === 'number' ? p.turn : null
      const msgs = Array.isArray(p.messages) ? p.messages.length : 0
      const s = stateFor(session, p.agent)

      // fail-closed：子会话 / 身份未知 ⇒ 不评估、**也不写观察行**（§14.9 硬约束 + 口径）
      if (s.identity !== 'main') return next()
      // 同一 turn 已被**评估**过（有 turn 时）—— 只用于「判定去重」
      const alreadyEvaluated = turn !== null && s.lastEvalTurn === turn
      // 🔴 **观察去重按 `(turn, step)`**，不是按 turn —— 否则同回合的延续步骤（`msgs=0`）会被误吞
      //    （记录**每一个** `pre-step`）
      const stepKey = turn !== null && typeof p.step === 'number' ? turn + ':' + p.step : turn !== null ? 't' + turn : null
      const stepSeen = stepKey !== null && s.lastStepKey === stepKey
      /**
       * 🔴 **本回合序号**（`§十八.4` 缺口 2 的修法）：
       * 判定块里的 `s.windowSeq += 1` 发生在 `step` 记录**之后** ⇒ 直接用它会把新回合的第一条
       * 记成上一回合的序号（读数：新回合首条记 `windowSeq:0`，而 `trigger` / 机会记 `1`）。
       * ⇒ 新回合第一条（`msgs > 0` 且未被评估过）预记 `s.windowSeq + 1`；同回合延续步骤沿用 `s.windowSeq`。
       */
      const seqForThisStep = msgs > 0 && !alreadyEvaluated ? s.windowSeq + 1 : s.windowSeq

      // ── ③ S4：工作目录（**环境信号** · 裁定）──
      //    ⚠️ 已知局限：一个项目目录内可交替执行多个任务；换目录也**不一定**意味着换任务
      const cwdNow = cwdOf(p.agent)
      const cwdTop = cwdNow.replace(/\\/g, '/').split('/').filter(Boolean).pop() || ''
      const cwdChanged = s.lastCwd !== '' && s.lastCwd !== cwdNow
      if (cwdChanged) {
        emit({ ev: 'cwd-obs', obs: OBS, session, cwdTop, windowSeq: seqForThisStep, mono: mono(), at: Date.now() })
      }
      s.lastCwd = cwdNow
      // ── Step A′ ④ 环境段：证据 + 元数据（cwd 原文只留内存 · 探针只落末段目录名）──
      s.wc.cwd = cwdNow
      s.wc.cwdTop = cwdTop
      // 阶段三 3.1：回合游标（工具事件无 turn ⇒ 转折点靠它按时间归属）
      if (turn !== null) s.currentTurn = turn

      // ── ① 步骤序列观察（批准 · **先记录，再做任何判定**）──
      //    ⚠️ 含 `msgs=0` 的延续步骤 —— 此前被静默跳过 ⇒ 看不到"deferred 之后还有没有模型步骤"
      //    🔴 `msgs` **只记计数**，不得解释为"用户在继续同一任务"（口径修正）
      if (!stepSeen) {
        s.lastStepKey = stepKey
        const missing: string[] = []
        if (turn === null) missing.push('turn')
        if (typeof p.step !== 'number') missing.push('step')
        emit({
          ev: 'step',
          obs: OBS,
          session,
          identity: s.identity,
          turn: turn !== null ? turn : 'unknown',
          step: typeof p.step === 'number' ? p.step : 'unknown',
          msgs, // 🔴 只记计数 · 不是任务语义判决
          windowSeq: seqForThisStep, // 本回合序号（新回合首条 = s.windowSeq + 1）
          cwdTop, // S4 环境信号（只记**末段目录名**）
          cwdChanged, // S4 是否换了工作目录
          phase: s.phase,
          discovered: s.lastDiscovery, // 本回合已判定的机会（null = 尚未判定）
          deferred: s.deferredSeen, // 本回合是否已出现 deferred
          triggerKind: s.lastTriggerKind,
          reasonBasis: s.activationBasis,
          sig: s.turnSig.slice(0, SIG_MAX), // 截止当前的回合签名（目录类别 · 无文件名）
          sigLen: s.turnSig.length,
          fieldsMissing: missing,
          // Step A′：推理结束 → 本步的**时间余量**（观测项④ · `§二十七 W5`）
          gapSinceReasoningMs: s.wc.reasoning.lastAt === null ? null : Math.max(0, Date.now() - s.wc.reasoning.lastAt),
          wcSegFilled: wcFillOf(s.wc).segFilled,
          mono: mono(),
          at: Date.now(),
        })
      }

      // 同 turn 内延续（msgs=0）：不评估、不重复发现 —— §14.8 C 类的基础
      if (msgs === 0) return next()
      // 同一 turn 已评估过 ⇒ 去重
      if (alreadyEvaluated) return next()

      // ── 新回合开始：重置**回合级观察状态**（签名 / 已 deferred / 激活标签）──
      s.turnSig = []
      s.deferredSeen = false
      s.lastTriggerKind = null
      s.lastDiscovery = null
      s.activationBasis = null
      s.todoSeenThisTurn = false // 回合级复位（`todoSig` 跨回合保留，二者不同）

      // ── T0：本回合输入性质（机械分类 · 不记正文；先剥宿主注入块）──
      const u = extractPrompt(p.messages)
      const cleanUser = stripInjected(u.text)
      const pc = classifyPrompt(cleanUser)
      const rawLen = normalizedLen(u.text)

      // 🔴 T7′：「同一问题第 2 次」—— **词面重合** + **期间未推进**（纯机械 · ⛔ 不判语义）。
      //   为什么加「未推进」：正常长任务的分步指令也会重复提到同一文件；只有「上次没推进」才说明有问题。
      //   ⚠️ 不做「用户否定语」关键词匹配：会误命中（"不对齐""不正确"），且 Runtime 不做语义（旧裁定）。
      {
        const poorProgress = failStreakOf(s.wc.activity) >= 1 || s.wc.progress.editsSinceLastExec === 0
        s.repeatQuestion = isRepeatQuestion(s.lastUserTextClean, cleanUser) && poorProgress
        s.lastUserTextClean = cleanUser
      }

      // ── Step A′ ① 意图段（**最重要的直接意图来源** · `§24.6` 补的正是这一项）──
      //    🔴 正文只进**内存**（供后续发现查询用）；探针只落 `intentLen`（`§二十六 26.6`）。
      s.wc.intentText = u.text
      // **锁存第一条用户消息**（`firstUserText` · 只写一次）—— 会话首拍注入的 topic 来源。
      //    ⚠️ 用 `cleanUser`（已剥宿主注入块 · 与 prompt 分类同口径）：宿主塞的「【AI-OS · …】」提示块
      //       不是用户说的话，混进 topic 会把检索带偏。⛔ 后续回合**不得**覆盖（`wc.intentText` 每回合都会变）。
      if (s.firstUserText === '') s.firstUserText = cleanUser
      s.wc.intentLen = pc.len
      s.wc.intentMeta = {
        src: 'user-message',
        at: Date.now(),
        seq: s.windowSeq,
        turn,
        step: typeof p.step === 'number' ? p.step : null,
        scope: 'main',
      }

      const phaseBefore: Phase = s.phase
      s.phase = 'CANDIDATE'
      // 回合序号 +1（**不依赖载荷 `turn`** —— 见 SessionState.windowSeq 注释）
      s.windowSeq += 1

      const cards = scanCards()
      // 🔴 步骤 2：把卡列表挂到会话态 —— 焦点卡 / `multi-claim` 判据都从它读（**真相来源**）。
      s.cards = cards
      const verdict = classify(s.cursor, cards)
      s.counts[verdict.kind] += 1
      if (turn !== null) s.lastEvalTurn = turn

      // ── 机会判定（§14.8 三优先级：任务事实 ▸ prompt 辅助 ▸ 证据不足保持安静）──
      //    ⚠️ 卡事实只决定"能否**立即**触发"；能否进入延迟等待由**输入**决定
      //       （§14.9：任务卡不是发现的先决条件；且真实基线常为多张 Executing ⇒ D 类）
      let discovery: Discovery
      let reason: string
      let basis: string // 激活依据**标签**（只作记录 · 不是判据）
      if (verdict.kind === 'A' || verdict.kind === 'B') {
        discovery = 'task_fact'
        reason = verdict.detail
        basis = 'card-fact-' + verdict.kind
        s.waiting = false
      } else if (pc.cls === 'unclassified') {
        // 输入有实质长度但方向未定 ⇒ 不立即发现，打开等待窗口（§15.3 / §15.4 阶段②）
        discovery = 'waiting'
        reason = 'vague input (len=' + pc.len + ') — defer discovery until first substantive tool intent; card facts: ' + verdict.detail
        basis = 'prompt-unclassified'
        s.waiting = true
        s.intentSeenInWindow = false // 开窗即复位 ⇒ 本窗口还有一次机会
      } else if (pc.cls === 'continuation') {
        discovery = 'quiet'
        reason = 'continuation-like input (len=' + pc.len + ') — stay quiet; card facts: ' + verdict.detail
        basis = 'prompt-continuation'
        // 🔴 修复（读数驱动 · 非推断）：**continuation 不得关窗**。
        //    「对话在继续」不构成放弃等待的理由；开窗的目的是等**首个实质工具意图**。
        //    原实现在多步回合下 **100% 错过**：
        //      · 同一用户回合里，第一次 pre-step 看到原始输入（可能 unclassified ⇒ 开窗），
        //        后续 pre-step 看到的是"agent 已在工作"的上下文（必然判 continuation）；
        //      · 而 `tools/pre-execute`（工具意图）总是排在 pre-step 之后
        //        ⇒ 窗口在等到意图之前就被下一次 pre-step 关掉。
        //    实际对照：10-12 `session-73559d36` wSeq=1 开窗后**没有**第二次 pre-step ⇒ 恰好命中 6 次；
        //              10-14 `session-37639883` wSeq=2 开窗 → wSeq=3 的 pre-step 判 continuation ⇒ 关窗
        //              ⇒ 20:45:05 的工具意图落空、零 stage4。
        //    上界仍由 `turn-stopping`（本文件 L3736-3749）保证：未命中 ⇒ 关窗 + `discovery-missed`。
        // s.waiting = false
      } else {
        // 读不到输入 ⇒ §14.8 ③ 证据不足就保持安静（fail-closed 到安静，不猜）
        discovery = 'none'
        reason = 'prompt not readable (' + u.src + ') — fail-closed to quiet; card facts: ' + verdict.detail
        basis = 'prompt-unreadable'
        s.waiting = false
      }
      s.discoCounts[discovery] += 1
      // 供 `step` 记录关联本回合的激活与依据（**标签 · 非判据**）
      s.lastTriggerKind = verdict.kind
      s.lastDiscovery = discovery
      s.activationBasis = basis

      s.phase = discovery === 'task_fact'
        ? 'ACTIVE'
        : discovery === 'waiting' ? 'CANDIDATE'
        : discovery === 'quiet' ? phaseBefore
        : 'IDLE'

      const exec = cards.filter(c => /^executing$/i.test(c.state))
      const focus = verdict.focus !== null ? verdict.focus : (s.cursor !== null ? s.cursor.focus : null)
      s.cursor = {
        execKeys: exec.map(c => c.key),
        focus,
        focusStep: focus !== null ? focus.step : '',
      }

      // ── ③ S2：卡 `Goal` / `Next Action`（**条件性辅助** · 裁定）──
      //    🔴 **只在焦点唯一（`verdict.focus !== null`）时使用** —— 复用 R2「不猜卡」判据；
      //       ⚠️ 多张 `Executing` 时**正确降级为未知**（`cardMapped:false`），**不得**猜一张
      const cardMapped = verdict.focus !== null
      // ── 阶段三 3.1第 ② 类**强**转折点（**任务 / 项目映射变化** = 焦点卡切换）──
      //    🔴 只在**唯一焦点**时判定（多张 `Executing` ⇒ 无法唯一确定 ⇒ 如实不判 · 沿用 R2「不猜卡」）
      const focusKey = cardMapped ? verdict.focus!.key : null
      if (focusKey !== null && s.lastFocusKey !== null && focusKey !== s.lastFocusKey) {
        pushStrongTp(s, 'card-mapping-change', turn)
      }
      if (focusKey !== null) s.lastFocusKey = focusKey
      const goalRaw = cardMapped ? verdict.focus!.goal : ''
      const goalHash = goalRaw ? hashOf(goalRaw) : '' // 空 goal ⇒ 不参与"是否变化"检测
      const goalChanged = goalHash !== '' && s.lastGoalHash !== '' && goalHash !== s.lastGoalHash
      if (goalHash !== '') s.lastGoalHash = goalHash

      emit({
        ev: 'trigger',
        obs: OBS,
        session,
        windowSeq: s.windowSeq, // 🔴 §十八.4 缺口 2 的修法：此前缺此字段 ⇒ A1 触发归属关联不上
        turn,
        step: p.step,
        msgs,
        identity: s.identity,
        phase: s.phase,
        kind: verdict.kind,
        detail: verdict.detail,
        discovery,
        activationBasis: basis, // 激活依据标签（记录用）
        signals: {
          // 三类信号（框架）——**只记"本回合是否可用"，不记内容**
          semantic: s.todoSeenThisTurn, // S1：**本回合**是否已出现 todo 计划
          environment: cwdTop !== '', // S4：是否有工作目录
          cardMapped, // S2：卡是否能**唯一**关联（不可 ⇒ 正确降级为未知）
          behavioral: s.turnSig.length > 0, // T2：是否已有工具活动
        },
        cardGoalLen: cardMapped ? normalizedLen(verdict.focus!.goal) : null, // 只长度
        cardNextLen: cardMapped ? normalizedLen(verdict.focus!.next) : null,
        // 🔴 S2 的**派生关键词**（不记原文 ≠ 只记长度 —— 要保留核心差异）
        cardGoalKeywords: cardMapped ? keywordsOf([verdict.focus!.goal]) : null,
        cardNextKeywords: cardMapped ? keywordsOf([verdict.focus!.next]) : null,
        cardGoalChanged: goalChanged, // 只布尔（哈希不落盘）
        reason: clip(reason, 160),
        promptClass: pc.cls,
        promptLen: pc.len,
        promptRawLen: rawLen, // ⚠️ 与 promptLen 的差值 = 宿主注入块被剥掉的量
        promptSrc: u.src, // ⚠️ 退化可见：出现 fallback/no-text ⇒ 解析失效，不是判据结论
        waiting: s.waiting,
        focus: focus !== null ? focus.key : null,
        focusState: focus !== null ? focus.state : null,
        focusStep: focus !== null ? clip(focus.step, 60) : null,
        cards: cards.length,
        executing: exec.length,
        counts: s.counts,
        discoCounts: s.discoCounts,
        at: Date.now(),
      })

      // ── Step A′：WorkContext 汇总（**填充情况落盘 · 原文不落盘**）──
      //    ⑥ 进度段只由活动序列**机械派生**（不标"调试/验证阶段"等语义结论 —— 明确禁止）
      s.wc.progress = deriveProgress(s.wc.activity)
      s.wc.cardKey = cardMapped ? verdict.focus!.key : null
      // 🔴 缓存卡 key 列表 —— 供 `cardCmdOf` 把命令行里的 `TASK-ID` 还原成卡 key
      //    （`claim` / `release` 走命令行 ⇒ `cardEdits` 看不见 ⇒ 见 `cardCmdOf` 的缺口说明）
      s.knownCardKeys = cards.map(c => c.key)
      emit({
        ev: 'wc-fill',
        obs: OBS,
        phase: 'turn-start', // 🔴 与 `turn-end` 配对：直接回答"上下文在一个回合内是否变得完整"
        session,
        windowSeq: s.windowSeq,
        turn,
        step: typeof p.step === 'number' ? p.step : null,
        ...wcFillOf(s.wc),
        // 推理流（A 阶段）：结构量与来源，**无原文**
        reasoningCommitted: s.wc.reasoning.committedMessages,
        reasoningAttempts: s.wc.reasoning.attempts,
        reasoningInterrupted: s.wc.reasoning.interrupted,
        reasoningLiveChunks: s.wc.reasoning.liveChunks,
        reasoningLiveChars: s.wc.reasoning.liveChars, // 后备路径字符数 ⇒ 与主路径 `reasoningChars` **交叉核对**
        reasoningProvider: s.wc.reasoning.provider,
        reasoningModel: s.wc.reasoning.model,
        reasoningMsBasis: 'sum-dt',
        gapSinceReasoningMs: s.wc.reasoning.lastAt === null ? null : Math.max(0, Date.now() - s.wc.reasoning.lastAt),
        mono: mono(),
        at: Date.now(),
      })
    } catch (err) {
      noteCatchFail('apply:A1', err)
      /* 观察/判定失败绝不影响决策链 */
    }
    return next()
  })

  // ── T1/T2：首个实质工作意图（§15.1 · 只认工具名，不记参数）──
  //    ⚠️ waterfall ⇒ next() 恰好一次、原样返回（约束 2）
  //    🔴 **去重键 = 回合序号（`observedSeq` vs `windowSeq`），不是载荷里的 turn** ——
  //       真实载荷 `ToolExecutionInput` **没有 turn**（§12.10）。这是本插件被真实窗口抓到的第一个缺陷。
  ctx.on('tools/pre-execute', (exec: any, next: any) => {
    try {
      const e = exec || {}
      const session = sessionIdOf(e.agent)
      const s = SESSIONS.get(session)
      // 🔴 **subagent 也进观测** —— 只把「注入段」放给了子 agent
      //   （`allowSubagent`），但事件信号（活动序列 / `has-edit` / `cardEdits`）全部产自本段
      //   与 post-execute 的 main 门内 ⇒ 子 agent 的 `detectEvents` 永远拿不到升沿
      //   ⇒ `anchor-claimed` / `first-edit` / `stuck` 永不触发（读数：2 个 fresh
      //   子 agent 会话探针只有 subagent-start / shadow-dispatch / probe-session 三行）。
      //   ⇒ 观测与注入**解耦**：观测放行 subagent；是否真的注入仍由 `allowSubagent` 控。
      //   ⚠️ 未知身份仍 fail-closed（`identity === 'unknown'` 不评估）。
      if (s !== undefined && (s.identity === 'main' || s.identity === 'subagent')) {
        const tool = e.name !== undefined ? String(e.name) : ''
        const callId = e.callId !== undefined ? String(e.callId) : null
        const kind = intentKindOf(tool)

        // ── ② 工作方向签名观察──
        //    ⚠️ 签名 = **工作方向的观测代理**，**不是**任务阶段的权威键（文件头口径修正）
        //    🔴 `arguments` **只取** path 类值用于算**目录类别**；参数原文不落盘
        const cls = toolClassOf(tool)
        const pcls = pathClassOf(pickPathArg(e.arguments), cwdOf(e.agent))
        // ── 🔴 **本会话的卡改动**（焦点卡的唯一依据 · `p0/RESPONSIBILITY-BOUNDARIES.md §2`）──
        //    ⛔ 只记**卡文件**路径（`task_cards/active/**/TASK-*.md`）；其它路径一律不记（隐私 + 体积）。
        //    "新建卡"同样命中（`write` 一个此前不存在的卡文件 ⇒ 也是本会话的卡）。
        if (/^(edit|write|multi_edit|notebook_edit)$/i.test(tool)) {
          const edited = cardRelOf(pickPathArg(e.arguments))
          if (edited !== null) s.cardEdits.set(edited, (s.cardEdits.get(edited) ?? 0) + 1)
        }
        // 🔴 **读卡观测**（与上面同一口径）—— 只用于**提醒判据**（"已关联"）与审计，
        //    ⛔ 不参与焦点卡判定（焦点卡 = `State` 占用 ▸ 见 `focusCardOf` 的过渡说明）
        if (/^(read|notebook_read)$/i.test(tool)) {
          const readCard = cardRelOf(pickPathArg(e.arguments))
          if (readCard !== null) s.cardReads.set(readCard, (s.cardReads.get(readCard) ?? 0) + 1)
        }
        // ── 🔴 焦点卡跨语言接口 · **写入侧**（步 1 · 授权）──────────────
        //    时机：**每次工具执行前**（此刻 `cardEdits` 刚被上面的块更新 ⇒ 反映最新焦点卡）。
        //    ⚠️ "不相关事件不触发**写入**"由 `writeFocusCard()` 内部的**语义芯比对**保证：
        //       焦点卡未变 ⇒ 返回 `'unchanged'` 且**完全不碰文件**（不是"调了但没效果"）。
        //    🔴 `cwdOf(e.agent)` 只用于**诊断**（设计 §四 决策 3：`cwd` 不作硬拒绝条件）。
        // 🔴 补充：焦点卡接口件是**全局单文件**（语义 = 当前**主对话**的焦点卡）⇒ 观测放行
        //    subagent 后，**写入仍只允许 main**（子会话即便偶然占卡也不得覆盖主会话焦点）。
        if (s.identity === 'main') {
          try {
            writeFocusCard(s, session, cwdOf(e.agent))
          } catch (err) {
            noteCatchFail('apply:A2', err)
            /* `writeFocusCard()` 内部已兜底计数 ⇒ 这里只再加一层"绝不外溢" */
          }
        }
        // ── 阶段三 3.1（收窄）： 第 ⑤ 类**弱**转折点（工具**操作对象变化**）──
        //    🔴 **默认不保护**（"从编辑一个文件转向编辑另一个文件，可能只是同一任务的正常推进"）。
        //    升级条件：(a) 距最近强信号 ≤ `TP_ADJACENT_MS`（pushWeakTp 内判定）
        //              (b) 之后同一 `pathClass` 连续出现 ≥ `TP_SUSTAIN_COUNT` 次（回溯升级）
        const prevAct = s.wc.activity.length > 0 ? s.wc.activity[s.wc.activity.length - 1] : null
        const changedObject = prevAct !== null && (prevAct.pathClass !== (pcls || null) || prevAct.cls !== cls)
        if (changedObject) {
          pushWeakTp(s, 'tool-object-change', s.currentTurn)
          s.pathClassRun = 1
          s.lastPathClass = pcls || null
        } else if (prevAct !== null) {
          // 对象未变 ⇒ 累计"持续"计数（同一 `pathClass` 连续出现）
          if (s.lastPathClass === (pcls || null)) s.pathClassRun += 1
          else {
            s.pathClassRun = 1
            s.lastPathClass = pcls || null
          }
          trySustainUpgrade(s) // 达到阈值 ⇒ 回溯升级待定弱转折点
        }
        if (s.turnSig.length < SIG_MAX) s.turnSig.push(cls + (pcls ? ':' + pcls : ''))
        emit({
          ev: 'tool-sig',
          obs: OBS,
          session,
          windowSeq: s.windowSeq,
          callId,
          tool,
          toolClass: cls,
          pathClass: pcls || null, // 只到目录级 · 无文件名
          deferred: s.deferredSeen,
          mono: mono(),
          at: Date.now(),
        })

        // ── Step A′ ⑤ 活动段（证据 + 元数据 · **参数原文不入**）──
        //    ⚠️ 该载荷无 `turn` / `step`（§12.10）⇒ 元数据里诚实记 `null`，不伪造
        pushActivity(s.wc, {
          tool,
          cls,
          pathClass: pcls || null,
          callId,
          ok: null, // 结果由 `tools/post-execute` 回填
          meta: { src: 'tool', at: Date.now(), seq: s.windowSeq, turn: null, step: null, scope: 'main' },
        })
        s.wc.progress = deriveProgress(s.wc.activity)

        // ── ③ S1：todo 计划（**瞬时解析 · 原文与签名都不落盘** · 裁定）──
        //    ⚠️ `todo_write` 是**整体替换（last-write-wins）** ⇒ 每次调用都必须与上次快照比较；
        //       **不得**把某一条 todo 的增删直接当成任务边界
        if (cls === 'plan' && /^todo_write/i.test(tool)) {
          const todos = todoItemsOf(e.arguments)
          if (todos !== null) {
            const contents = todos.map(t => t.content)
            const sig = tokensOf(contents) // 内存态签名（不落盘）
            const prev = s.todoSig
            const overlap = prev === null ? null : jaccard(sig, prev)
            const changed = overlap !== null && overlap < TODO_CHANGED_JACCARD
            const newDirection = overlap !== null && overlap < TODO_NEW_DIRECTION_JACCARD
            s.todoSig = sig // 仅内存留存（不落盘 · 不持久化 · 重启即丢）
            s.todoSeenThisTurn = true // 回合级：本回合已有计划
            // ── 阶段三 3.1： 第 ① 类**强**转折点（Todo **实质变化**）──
            //    ⚠️ 外部事件是**机械证据**，**不能证明**对应推理本身一定重要（如实记）
            if (newDirection) pushStrongTp(s, 'todo-new-direction', s.currentTurn)
            else if (changed) pushStrongTp(s, 'todo-changed', s.currentTurn)
            const lens = lenStatsOf(contents)
            const kws = keywordsOf(contents)
            // ── Step A′ ② 计划段（**内存**留完整条目；探针只落派生量）──
            //    🔴 Todo 是「**计划证据**」，**不得**直接认定为已完成事实（`§24.1` 四类事实）
            s.wc.plan = {
              count: todos.length,
              status: statusCountsOf(todos),
              keywords: kws,
              changed,
              newDirection,
              items: todos, // 内存 · 供发现使用 · 不落盘
            }
            s.wc.planMeta = {
              src: 'todo',
              at: Date.now(),
              seq: s.windowSeq,
              turn: null, // `tools/pre-execute` 载荷无 turn（§12.10）⇒ 诚实记 null
              step: null,
              scope: 'main',
            }
            emit({
              ev: 'todo-plan',
              obs: OBS,
              session,
              windowSeq: s.windowSeq,
              callId,
              count: todos.length,
              status: statusCountsOf(todos), // 只计数
              lenMin: lens.min,
              lenMax: lens.max,
              actions: actionClassesOf(contents), // 只类别计数（辅助）
              keywords: kws, // 🔴 区分性关键词（派生量 · 保留核心差异）
              overlapPrev: overlap === null ? null : round2(overlap), // 只数值 · 无集合
              changed,
              newDirection,
              wholeListReplacement: true, // 提醒判读者：last-write-wins
              mono: mono(),
              at: Date.now(),
            })
          }
        }

        // 同一回合只观察**首个**实质意图（`tools/pre-execute` 每个工具调用都会触发）
        if (kind !== 'none' && s.observedSeq !== s.windowSeq) {
          s.observedSeq = s.windowSeq
          const inWindow = s.waiting && !s.intentSeenInWindow
          if (inWindow) {
            s.intentSeenInWindow = true
            s.deferredSeen = true // 供 `step` 记录"本回合是否已 deferred"
            s.waiting = false // 命中即关窗：一次机会，不重复
            s.phase = 'ACTIVE'
            s.discoCounts.deferred += 1
            emit({
              ev: 'discovery-opportunity',
              mode: 'deferred',
              obs: OBS,
              session,
              windowSeq: s.windowSeq,
              callId,
              identity: s.identity,
              phase: s.phase,
              intentKind: kind,
              tool,
              discoCounts: s.discoCounts,
              note: 'stage 4 · steps 1-2 wired (focus card → focus object → minimal retrieval request → candidates); delivery (step 3) NOT wired ⇒ no injection',
              at: Date.now(),
            })
            // 阶段 4 第①＋②段：**就在这个时机**（deferred 命中 = 首个实质工作意图）派发一次发现。
            //   🔴 只落探针 · 不递送 ⇒ 宿主上下文零变化；任何失败都不得阻塞宿主。
            try {
              dispatchStage4(s, session)
            } catch (err) {
              noteCatchFail('apply:A3', err)
              /* 静默 */
            }
          } else {
            emit({
              ev: 'tool-intent',
              obs: OBS,
              session,
              windowSeq: s.windowSeq,
              callId,
              identity: s.identity,
              intentKind: kind,
              tool,
              inWindow: false,
              waiting: s.waiting,
              note: s.waiting ? 'window already used this turn' : 'no waiting window — observation only',
              at: Date.now(),
            })
          }
        }
      }
    } catch (err) {
      noteCatchFail('apply:A4', err)
      /* 观察失败绝不影响工具行为 */
    }
    return next()
  })

  // ── ② 工具**调用结果**观察（批准 · 只记成功/失败，不记输出内容）──
  //    ⚠️ `tools/post-execute` 同样是 waterfall ⇒ `next()` 恰好一次（不改错误语义）
  //    🔴 v8：本 handler 改为 `async` **仅为** Step B′ 递送验证需要把上下文**折进**下游 decision；
  //       **默认关闭 ⇒ 第一条 `return next()` 与旧版逐字一致**（自测 S35 断言"同一对象引用"）。
  ctx.on('tools/post-execute', async (exec: any, result: any, next: any) => {
    try {
      const e = exec || {}
      const session = sessionIdOf(e.agent)
      const s = SESSIONS.get(session)
      // 与 pre-execute 同一口径 —— **subagent 也回填观测**（活动结果的 ok / progress /
      //   `has-edit` 的升沿靠这里派生； 当时只放行注入段 ⇒ 子 agent 事件永远不升沿）。
      if (s !== undefined && (s.identity === 'main' || s.identity === 'subagent')) {
        // 🔴 （实验 B）：**首拍计数** —— 每次进入 post-execute 就 +1（放在任何门控之前），
        //    `=== 1` 即"本会话第一个工具调用刚收尾"。⛔ 不用 `wc.activity.length`：同一 step 的**并行**
        //    工具调用会一次塞进多条活动 ⇒ 首拍会被误判成"已开工"。
        s.postExecuteCount += 1
        const tool = e.name !== undefined ? String(e.name) : ''
        emit({
          ev: 'tool-result',
          obs: OBS,
          session,
          windowSeq: s.windowSeq,
          callId: e.callId !== undefined ? String(e.callId) : null,
          tool,
          toolClass: toolClassOf(tool),
          ok: result && typeof result.isError === 'boolean' ? !result.isError : null,
          mono: mono(),
          at: Date.now(),
        })

        // ── Step A′ ⑤ 活动段：把执行结果回填到对应活动（**只记 ok · 不记输出内容**）──
        const okv = result && typeof result.isError === 'boolean' ? !result.isError : null
        // 🔴 T2：记下失败**类型**（只落分类，⛔ 不落结果原文）——`gap` 事件据此放过「事实型失败」。
        //    证据：`30520faa` 路径 typo 类失败触发检索，它自己评「预期基本为 0」（卡第 37 批）。
        s.lastFailKind = failKindOf(result)
        // ── 阶段三 3.1： 第 ④ 类**强**转折点（**执行报错**）──
        if (okv === false) pushStrongTp(s, 'tool-error', s.currentTurn)
        // ── 阶段三 3.1「有明确结果支持的阶段转变」需要本回合**确有成功结果** ──
        //    🔴 按 `toolClass` 判（`edit_file` / `write_file` / `pwsh` … ⇒ edit/write/exec），
        //       不用工具名精确匹配（否则真实工具名对不上 ⇒ 判据静默失效）
        if (okv === true && ['exec', 'edit', 'write'].includes(toolClassOf(tool))) s.turnHadSuccess = true
        // 🔴 **占用 / 释放动作观测**（**焦点卡的唯一来源** · 见 `cardCmdsOf` 的说明）
        //    只在**成功**时记账：`claim` 被拒（如冲突）时卡的 `State` 没变，
        //    若此时记账 ⇒ `focusCardOf` 会给出**虚假焦点**。
        //    ⛔ `--dry-run` 不算占用（预览无副作用，见 `cardCmdsOf` 的 `dryRun`）。
        if (okv === true) {
          // 🔴 **逐条**处理：一次调用可含多条命令 —— 原实现在此**静默丢掉第二条之后**的全部
          for (const cc of cardCmdsOf(tool, e.arguments)) {
            if (cc.dryRun) {
              emit({
                ev: 'card-cmd', obs: OBS, session, op: cc.op, taskId: cc.taskId, card: null,
                note: '`--dry-run` ⇒ ⛔ 不记占用（预览不是占用）',
                at: Date.now(), mono: mono(),
              })
              continue
            }
            // 🔴 `release` 的**内存记账** —— 阶段判定 `S4 收口` 的唯一来源。
            //    放在 `cardKeyOfId` 解析**之前**：ID 没能唯一命中卡列表时（`knownCardKeys` 为空 /
            //    同 ID 多卡）也照样记账 —— 阶段判定只需要"本会话确实 release 过"，不需要卡 key。
            //    ⚠️ 只有 `okv === true`（外层门）才走到这里 ⇒ 被拒的 release 不会被误记。
            if (cc.op === 'release') {
              s.cardReleaseCount += 1
              s.releaseJustObserved = true
            }
            // `claim` 成功后**同回合**刷新**本会话**的卡快照。
            //   缺陷（探针实录 `phase-inject{phase:"S2",state:"no-anchor",ownedCards:0}` 紧跟 claim）：
            //     `s.cards` 只在 `agent/pre-step` 且 `msgs>0` 时重扫（见 L6039-6041）⇒ 回合开始后 claim 的卡
            //     **本回合不可见** ⇒ `myOccupiedCards()` 恒 0 ⇒ 阶段判定与焦点卡（步骤 2）都晚一拍。
            //   修法：**只刷本会话的 `s.cards`**（与 `dispatchStage4` 的 T3-lite 现扫同一口径，`policy` 已有先例）——
            //     ⛔ 不发事件（下面的 `card-cmd` 已足够留痕）· ⛔ 不改全局扫描时机 · ⛔ **不动阶段/节点注入逻辑**。
            //   ⚠️ **只对 `claim`**：`release` 后保留旧快照，是 S4（收口）注入时"卡描述还能用"的既有依据
            //     （阶段语义属 写域，本卡不碰）。
            if (cc.op === 'claim') {
              try {
                s.cards = scanCards()
              } catch (err) {
                // 铁律②：catch 里**至少落一条失败探针**（⛔ 不允许"零报错、零探针"）——
                // 扫描失败 ⇒ 沿用旧快照（行为回落到修复前），但**必须可见**。
                emit({
                  ev: 'card-snapshot-refresh', obs: OBS, session, state: 'failed',
                  detail: clip(String(err), 120), at: Date.now(), mono: mono(),
                })
              }
            }
            // **claim 后向前一个「不同会话」注入接手检查**。
            //   ⛔ 不依赖 `cardKeyOfId`/`knownCardKeys` —— 读数子 agent 接手时 `knownCardKeys` 可能为空
            //   （cardKeyOfId 返回 null ⇒ 挂在 key 判定之后的 会被整块跳过）；这里直接用 `taskId` 定位 `.log`。
            //   条件：① 开关 `.aios/r3-wake.json` 开；② `.log` 最近一条 claim 的 session ≠ 本会话
            //   （同一会话 claim 两次 ⇒ 不注入）；③ 每个 victim 每会话最多 1 次（R3_MAX_PER_SESSION）。
            //   ⛔ 只投一条 user 消息（followup）；⛔ 不改卡 / 不写知识 / 不递送候选。
            if (cc.op === 'claim' && r3WakeEnabled()) {
              let victim: string | null = null
              try { victim = previousOccupantOf(readTail(cardLogPathOfTaskId(cc.taskId)), session) } catch { victim = null }
              if (victim !== null) {
                const wstate = loadR3WakeState()
                if ((wstate[victim] || 0) < R3_MAX_PER_SESSION) {
                  let agent: any
                  try {
                    const ag = ctx.get('agents')
                    agent = ag !== undefined && ag !== null && typeof ag.get === 'function' ? ag.get(victim) : undefined
                  } catch { agent = undefined }
                  if (agent !== undefined && agent !== null && typeof agent.followup === 'function') {
                    try {
                      agent.followup(userMessageOf(r3HandoffText(cc.taskId), 'aios R3 claim-handoff'))
                      wstate[victim] = 1
                      saveR3WakeState(wstate)
                      emit({ ev: 'r3-claim-handoff', obs: OBS, session, state: 'ok', card: cc.taskId, victimSession: victim, at: Date.now(), mono: mono() })
                      // 🔴 **fire-once** —— 成功向前手注入一次后自动关闭
                      //   自动维护注入（复用 的 `disarmR3Wake()` 口径），并记待告知标记；
                      //   本次 post-execute 的 Step B′ 段会向**触发会话（接手方 b）**投「已关闭，请询问用户」。
                      try { disarmR3Wake() } catch { /* 静默：关门失败不影响已送达的注入 */ }
                      setR3DisarmPending({ session, card: cc.taskId })
                    } catch (err) {
                      emit({ ev: 'r3-claim-handoff', obs: OBS, session, state: 'failed', card: cc.taskId, victimSession: victim, detail: clip(String(err), 120), at: Date.now(), mono: mono() })
                    }
                  } else {
                    // victim 已离线 ⇒ 如实记 no-agent（⛔ 不冷恢复）；仍写状态位防重复。
                    wstate[victim] = 1
                    saveR3WakeState(wstate)
                    emit({ ev: 'r3-claim-handoff', obs: OBS, session, state: 'no-agent', card: cc.taskId, victimSession: victim, at: Date.now(), mono: mono() })
                  }
                }
              }
            }
            let key = cardKeyOfId(s, cc.taskId)
            // 🔴 （家族后半）：缓存解析不到 ⇒ **现扫一次再判**。
            //   实证（真实探针）：同一回合 `create` + `claim` 的**平铺卡**（`TASK-20261101-017`）⇒
            //   `card:null`；本函数只读 `s.knownCardKeys` = **回合开始**快照（只刷了 `s.cards`）。
            //   判据不变：现扫后**唯一命中**才算确定；0 个 / 多个 ⇒ 照样 null（⛔ 不猜）。
            //   失败必落读数（铁律②）—— 扫描失败 ⇒ 回落到修复前行为（不记），但**可见**。
            if (key === null) {
              try {
                const fresh = scanCards()
                if (fresh.length > 0) s.knownCardKeys = fresh.map(c => c.key)
                const hits = cardKeyHitsOf(s.knownCardKeys, cc.taskId)
                key = hits.length === 1 ? hits[0] : null
                emit({
                  ev: 'card-id-rescan', obs: OBS, session, taskId: cc.taskId,
                  state: key === null ? 'miss' : 'hit', hits: hits.length,
                  cards: s.knownCardKeys.length,
                  note: '缓存（回合开始快照）未唯一命中 ⇒ 现扫一次再判（v51f · ⛔ 仍不猜）',
                  at: Date.now(), mono: mono(),
                })
              } catch (err) {
                key = null
                emit({
                  ev: 'card-id-rescan', obs: OBS, session, taskId: cc.taskId, state: 'failed',
                  hits: 0, detail: clip(String(err), 120), at: Date.now(), mono: mono(),
                })
              }
            }
            if (key === null) {
              emit({
                ev: 'card-cmd', obs: OBS, session, op: cc.op, taskId: cc.taskId, card: null,
                note: 'ID 未唯一命中卡列表（0 或多个）⇒ ⛔ 不记（不猜）',
                at: Date.now(), mono: mono(),
              })
              continue
            }
            // 🔴 步骤 2：**不再**用命令字面量记占用（读数：被拒的 `claim` 也会被记账 ⇒ 与卡上真相不一致）。
            //    ⇒ 这里只保留**诊断事件**与 `cardEdits`（后者只服务提醒判据"动过卡"）。
            //    占用的真相由**卡**提供（`Event Log` 留痕 ⇒ `scanCards()` 的 `occupancy`）。
            s.cardEdits.set(key, (s.cardEdits.get(key) ?? 0) + 1)
            emit({
              ev: 'card-cmd', obs: OBS, session, op: cc.op, taskId: cc.taskId, card: key,
              cardEdits: s.cardEdits.size,
              note: 'observed via pwsh command literal (claim/release) — **仅诊断**（占用真相在卡上）',
              at: Date.now(), mono: mono(),
            })
            // claim 后接手检查的触发已**前置**到 `cardKeyOfId` 之前（不依赖 knownCardKeys，见上）。
          }
        }
        const cid = e.callId !== undefined ? String(e.callId) : null
        let filled = false
        if (cid !== null) {
          for (let i = s.wc.activity.length - 1; i >= 0; i--) {
            if (s.wc.activity[i].callId === cid) {
              s.wc.activity[i].ok = okv
              filled = true
              break
            }
          }
        }
        if (!filled) {
          // 兜底：载荷缺 callId 时回填**最后一条尚未回填**的活动（并如实依赖注释说明这是近似）
          for (let i = s.wc.activity.length - 1; i >= 0; i--) {
            if (s.wc.activity[i].ok === null) {
              s.wc.activity[i].ok = okv
              break
            }
          }
        }
        s.wc.progress = deriveProgress(s.wc.activity)
      }
    } catch (err) {
      noteCatchFail('apply:A5', err)
      /* 观察失败绝不影响工具行为与错误语义 */
    }

    // ── 阶段三 3.2 · **影子发现**（默认关闭 · 异步 · **不递送** · 失败不影响宿主）──
    //    🔴 授权边界：不改 `downstream` decision（不递送）· 不调远程 · 推理文本只经 stdin 传本地子进程
    try {
      const shSession = sessionIdOf(exec && exec.agent)
      const sh = SESSIONS.get(shSession)
      // 🔴 `shadow-dispatch`（**诊断行** · 每个会话只落一条 · 加）：
      //    「post-execute 到了、但影子没派发」这件事**无法从既有探针分辨**是哪一道检查拦的：
      //      · `no-agent`      —— 载荷里根本没有 `agent` ⇒ `shSession='unknown'`
      //      · `no-session`    —— 会话状态不在 `SESSIONS`（键不一致 / 该会话没有 start/pre-step）
      //      · `not-main`      —— 身份不是 main（子会话）
      //      · `probe-null`    —— 开关文件读不到/非法（`readShadowProbe()` 返回 null）
      //      · `dispatched`    —— 通过 ⇒ 随后必有 `probe-session` 或 `shadow-ab`
      //    ⛔ 只落**判据名与标识**，不落任何正文（同既有纪律）。
      if (!SHADOW_DIAG.has(shSession)) {
        SHADOW_DIAG.add(shSession)
        let why = 'dispatched'
        if (!(exec && exec.agent && exec.agent.session && exec.agent.session.header)) why = 'no-agent'
        else if (sh === undefined) why = 'no-session'
        else if (sh.identity !== 'main') why = 'not-main'
        else if (readShadowProbe() === null) why = 'probe-null'
        emit({
          ev: 'shadow-dispatch', obs: OBS, session: shSession, why,
          hasAgent: !!(exec && exec.agent), identity: sh === undefined ? null : sh.identity,
          sessions: SESSIONS.size, at: Date.now(), mono: mono(),
        })
      }
      if (sh !== undefined && sh.identity === 'main') dispatchShadow(sh, shSession, sh.currentTurn)
    } catch (err) {
      noteCatchFail('apply:A6', err)
      /* 影子派发失败绝不影响宿主行为 */
    }

    // ── Step B′ · 递送（**默认全部关闭** · 开关为本地文件 · 每次重读）─────────────────
    //    🔴 逻辑已提炼到 `runtime/delivery/phase-injection.ts: applyStepBDelivery()`；
    //       顺序/门控/探针/去重逐字保留：先读开关（读不到即透明）⇒ `await next()` **恰好一次** ⇒ 再决定附加。
    //       任何失败都原样透传下游 decision（⛔ 不改 `block` 语义）；`try/catch(stepBErr)` 仍在函数内原样保留。
    return await applyStepBDelivery(exec, result, next)
  })

  // ── Step A′ · 推理流结构观察（**A 阶段** · 裁定）──────────────
  // 🔴 **路径优先序**
  //    ① **优先**：`session/event` —— **post-commit 追加馈送**（`api-catalog.ts:3366-3372`），
  //       读 `assistant/message` / `assistant/attempt` 的 `data.stream`（**紧凑保存的完整流**）
  //       ⇒ 不复制原文 · 统计**完整步骤** · 可分成功提交 / 失败重试取消
  //    ② **后备**：`agent/assistant-stream`（**emit · 非 waterfall**）只累计 `reasoning-delta` 帧
  //    `ev:'stream-path'` 报告**实际走通的是哪条路** —— 这正是 A 阶段要回答的问题之一。
  // 🔴 **只取结构量**（块数 / 字符数 / Σdt / 形态签名）：推理文本**不留存、不落盘**。
  // 🔴 **时序**：推理产生于请求进行中 ⇒ 只能影响**后续**步骤；`gapSinceReasoningMs` 即其度量。

  /** 「哪条路真正走通」只报一次/来源（防日志膨胀）。 */
  const REPORTED_PATHS = new Set<string>()
  /** 收到但**无法归属**到已知 main 会话的提交数（作用域 / 时序问题的诊断量 · 不落内容）。 */
  const STREAM_UNMAPPED = { count: 0, lastType: null as string | null }

  function reportStreamPath(which: 'session-event' | 'assistant-stream', detail: string): void {
    if (REPORTED_PATHS.has(which)) return
    REPORTED_PATHS.add(which)
    emit({ ev: 'stream-path', obs: OBS, source: which, detail, unmapped: STREAM_UNMAPPED.count, at: Date.now(), mono: mono() })
  }

  /**
   * **主路径**：已提交的 Assistant 流（post-commit）。
   * ⚠️ `session/event` 的签名为 `(session, event)`；此处兼容"载荷对象"形态，避免宿主约定差异导致静默失效。
   */
  ctx.on('session/event', (session: any, event: any) => {
    try {
      if (event === undefined && session && typeof session === 'object' && session.event) {
        event = session.event
        session = session.session
      }
      const e = event || {}
      const t = e.type

      // ── 阶段 2 · **正式释放点**：`turn/end`（🔴 **不是** `turn-stopping` —— 后者可被 steering 逆转）──
      if (t === 'turn/end') {
        const key = sessionKeyOf(session)
        const s = SESSIONS.get(key)
        if (s === undefined || s.identity !== 'main') return
        const d = e.data && typeof e.data === 'object' ? (e.data as Record<string, unknown>) : {}
        const turnN = typeof d.turn === 'number' ? d.turn : null
        if (turnN === null) return
        const reasonRaw = d.reason && typeof d.reason === 'object' ? (d.reason as Record<string, unknown>) : null
        const reasonKind = reasonRaw && typeof reasonRaw.kind === 'string' ? reasonRaw.kind : 'unknown'
        releaseTurn(s, key, turnN, reasonKind)
        return
      }

      if (t !== 'assistant/message' && t !== 'assistant/attempt') return
      const key = sessionKeyOf(session)
      const s = SESSIONS.get(key)
      // fail-closed：未注册会话 / 非 main ⇒ **不写观察行**（绝不把别的会话并进主会话统计）
      if (s === undefined || s.identity !== 'main') {
        STREAM_UNMAPPED.count += 1
        STREAM_UNMAPPED.lastType = typeof t === 'string' ? t : null
        return
      }
      const data = e.data && typeof e.data === 'object' ? (e.data as Record<string, unknown>) : {}
      const seq = typeof e.seq === 'number' ? e.seq : null

      // ── 阶段 2 · 去重（同 `seq` 只处理一次 · 重复投递不得重复计数）──
      if (seq !== null) {
        if (s.wc.seenSeq.has(seq)) return
        s.wc.seenSeq.add(seq)
        if (s.wc.seenSeq.size > SEEN_SEQ_MAX) {
          const oldest = s.wc.seenSeq.values().next()
          if (!oldest.done) s.wc.seenSeq.delete(oldest.value)
        }
      }

      const scan = scanAssistantStream(data.stream)
      const r = s.wc.reasoning
      if (t === 'assistant/message') r.committedMessages += 1
      else r.attempts += 1
      const interrupted = data.interrupted === true
      if (interrupted) r.interrupted += 1
      r.blocks += scan.blocks
      r.chars += scan.chars
      r.ms += scan.ms
      r.source = 'session-event'
      for (const sh of scan.shapes) if (!r.streamShapes.includes(sh)) r.streamShapes.push(sh)
      const msg = data.message && typeof data.message === 'object' ? (data.message as Record<string, unknown>) : null
      const srcOfMsg = msg && msg.source && typeof msg.source === 'object' ? (msg.source as Record<string, unknown>) : null
      if (srcOfMsg) {
        if (typeof srcOfMsg.provider === 'string') r.provider = srcOfMsg.provider
        if (typeof srcOfMsg.model === 'string') r.model = srcOfMsg.model
      }
      r.lastTurn = typeof data.turn === 'number' ? data.turn : null
      r.lastStep = typeof data.step === 'number' ? data.step : null
      r.lastAt = Date.now()
      // 阶段三 3.1：回合游标（提交事件带 turn ⇒ 最可靠的来源）
      if (typeof data.turn === 'number') s.currentTurn = data.turn
      reportStreamPath('session-event', 'post-commit assistant settlement feed')

      // ── 阶段 2 · 推理**文本**（仅内存 · 只写不判 · 归类见 §5.2C/D/E）──
      try {
        collectReasoningText(s, key, t === 'assistant/message' ? 'message' : 'attempt', data, seq, interrupted, r)
      } catch (err) {
        noteCatchFail('apply:A7', err)
        /* 文本收集失败绝不影响结构量记录与宿主 */
      }

      emit({
        ev: 'reasoning-obs',
        obs: OBS,
        session: key,
        path: 'session-event',
        settlement: t === 'assistant/message' ? 'message' : 'attempt',
        interrupted,
        seq: typeof e.seq === 'number' ? e.seq : null,
        turn: data.turn !== undefined ? data.turn : null,
        step: data.step !== undefined ? data.step : null,
        provider: r.provider,
        model: r.model,
        streamLen: Array.isArray(data.stream) ? (data.stream as unknown[]).length : null,
        streamShape: scan.shapes, // **形态签名**（读数编码形态 · 不含内容）
        reasoningBlocks: scan.blocks,
        reasoningChars: scan.chars,
        reasoningMs: scan.ms,
        msBasis: 'sum-dt', // ⚠️ 近似的推理时长：Σ 相邻 delta 时间差
        at: Date.now(),
        mono: mono(),
      })
    } catch (err) {
      noteCatchFail('apply:A8', err)
      /* 观察失败绝不影响已提交的追加（同 `session/event` 的隔离保证） */
    }
  })

  /**
   * `agent/assistant-stream`：**两个用途**
   *   ① 后备路径（A 阶段）：只认 `reasoning-delta` chunk · 只累计长度
   *   ② **阶段 2**：只认 **`start` 帧**（每个 attempt 恰好一条 · 非高频）⇒ 取 `attemptId`/`revision` 进 pending
   *      —— 用于补订已提交事件缺失的归属标识（(b)）
   * ⚠️ 高频的只是 `chunk` 帧；`start` 帧成本 ≈ 每次模型请求 1 条。
   */
  ctx.on('agent/assistant-stream', (payload: any) => {
    try {
      const f = payload && payload.frame
      if (!f) return

      // ── 阶段 2 · `start` 帧 ⇒ pending 队列（FIFO **有条件**归属的依据）──
      if (f.type === 'start') {
        const s = SESSIONS.get(sessionIdOf(payload.agent))
        if (s === undefined || s.identity !== 'main') return
        const turn = typeof f.turn === 'number' ? f.turn : null
        const step = typeof f.step === 'number' ? f.step : null
        if (turn === null || step === null) return
        const key = turn + ':' + step
        const q = s.wc.pendingAttempts.get(key) ?? []
        q.push({
          attemptId: typeof f.attemptId === 'string' ? f.attemptId : 'unknown',
          revision: typeof f.revision === 'number' ? f.revision : null,
          at: Date.now(),
        })
        while (q.length > PENDING_QUEUE_MAX) q.shift() // 防重试风暴膨胀（丢最旧）
        s.wc.pendingAttempts.set(key, q)
        return
      }

      if (f.type !== 'chunk') return
      const c = f.chunk
      if (!c || c.type !== 'reasoning-delta') return
      const s = SESSIONS.get(sessionIdOf(payload.agent))
      if (s === undefined || s.identity !== 'main') return
      const text = typeof c.text === 'string' ? c.text : ''
      const r = s.wc.reasoning
      r.liveChunks += 1
      r.liveChars += text.length
      if (r.source === 'none') r.source = 'assistant-stream'
      if (!r.streamShapes.includes('reasoning-delta')) r.streamShapes.push('reasoning-delta')
      r.lastAt = Date.now()
      reportStreamPath('assistant-stream', 'transient chunk feed (fallback path in use)')
    } catch (err) {
      noteCatchFail('apply:A9', err)
      /* 静默 */
    }
  })

  // ── 回合收尾（serial，无 next；返回 undefined ⇒ 不阻塞、不 steer）──
  ctx.on('agent/turn-stopping', (payload: any) => {
    const p = payload || {}
    const session = sessionIdOf(p.agent)
    const s = SESSIONS.get(session)
    // ── ② 回合签名汇总（回合级观察 · 便于按回合聚合；**不是**阶段键）──
    if (s !== undefined && s.identity === 'main') {
      emit({
        ev: 'turn-sig',
        obs: OBS,
        session,
        windowSeq: s.windowSeq,
        turn: p.turn !== undefined ? p.turn : 'unknown',
        sig: s.turnSig.slice(0, SIG_MAX),
        sigLen: s.turnSig.length,
        deferred: s.deferredSeen,
        // Step A′：本回合的推理流结构量与来源（便于按回合聚合 · **无原文**）
        reasoningBlocks: s.wc.reasoning.blocks,
        reasoningChars: s.wc.reasoning.chars,
        reasoningSource: s.wc.reasoning.source,
        reasoningCommitted: s.wc.reasoning.committedMessages,
        reasoningAttempts: s.wc.reasoning.attempts,
        at: Date.now(),
      })
      // ── 阶段三 3.1第 ③ 类**强**转折点 —— **有明确结果支持**的阶段转变 ──
      //    条件（**两条同时满足**）：(a) 与上一回合签名不同；(b) **本回合确有成功结果**
      //    （`ok:true` 且 `exec`/`edit`/`write`）
      //    🔴 只满足 (a) ⇒ **不算**强信号（那只是"看起来换了个方向"）—— 这是收窄的关键一处
      const sigNow = s.turnSig.join('|')
      const sigPrev = s.lastTurnSig.join('|')
      if (sigNow !== '' && sigPrev !== '' && sigNow !== sigPrev && s.turnHadSuccess) {
        pushStrongTp(s, 'phase-change', typeof p.turn === 'number' ? p.turn : s.currentTurn)
      }
      s.lastTurnSig = s.turnSig.slice()
      s.turnSig = []
      s.deferredSeen = false
      s.turnHadSuccess = false // 回合级复位（成功结果只对**本回合**的阶段转变负责）

      // ── Step A′（v7）：**回合末**再记一份 WorkContext 填充（`phase:'turn-end'`）──
      //    🔴 与回合初那份（`turn-start`）配对 ⇒ 直接回答「上下文在一个回合内是否变得完整」
      //       首取数教训：只看回合初，会把"首回合尚无历史证据"误判成"机制失效"（W1 口径缺陷）
      s.wc.progress = deriveProgress(s.wc.activity)
      emit({
        ev: 'wc-fill',
        obs: OBS,
        phase: 'turn-end',
        session,
        windowSeq: s.windowSeq,
        turn: p.turn !== undefined ? p.turn : null,
        step: null,
        ...wcFillOf(s.wc),
        reasoningCommitted: s.wc.reasoning.committedMessages,
        reasoningAttempts: s.wc.reasoning.attempts,
        reasoningInterrupted: s.wc.reasoning.interrupted,
        reasoningLiveChunks: s.wc.reasoning.liveChunks,
        reasoningLiveChars: s.wc.reasoning.liveChars,
        reasoningProvider: s.wc.reasoning.provider,
        reasoningModel: s.wc.reasoning.model,
        reasoningMsBasis: 'sum-dt',
        gapSinceReasoningMs: s.wc.reasoning.lastAt === null ? null : Math.max(0, Date.now() - s.wc.reasoning.lastAt),
        mono: mono(),
        at: Date.now(),
      })
    }
    if (s !== undefined && s.identity === 'main' && s.waiting) {
      // 等待窗口**不跨回合**：未等到意图 ⇒ 如实记 missed，不补做、不攒着
      s.waiting = false
      s.discoCounts.missed += 1
      emit({
        ev: 'discovery-missed',
        session,
        turn: p.turn,
        identity: s.identity,
        phase: s.phase,
        discoCounts: s.discoCounts,
        note: 'waiting window closed without substantive tool intent',
        at: Date.now(),
      })
    }
    emit({ ev: 'turn-stopping', obs: OBS, session, turn: p.turn, phase: s ? s.phase : 'unknown', at: Date.now() })

    // ── 阶段 2 · **生命周期观测点** ──
    //    🔴 **不得**据 `turn-stopping` 释放工作上下文：它可被 `agent.steer()` 逆转
    //       （"fresh steering runs another step" ⇒ 那一步仍在同一 turn 内、仍可能合法使用本 turn 的材料）。
    //       正式释放点 = `session/event` 的 `turn/end`。
    if (s !== undefined && s.identity === 'main') {
      emit({
        ev: 'turn-stopping-obs',
        obs: OBS,
        session,
        turn: p.turn !== undefined ? p.turn : null,
        note: 'observation only — NOT a release point (steering may run another step); release happens at session turn/end',
        retainedEntries: s.wc.reasoningEntries.length,
        retainedChars: s.wc.reasoningChars,
        // 阶段三 3.1：本回合结束时的缺口状态与转折点（**派生量** · 无原文）
        historyCoverage: s.wc.historyCoverage,
        retentionPolicy: s.wc.retentionPolicy,
        evictedSeqRanges: s.wc.evictedSeqRanges,
        turningPointCounts: (() => {
          const out: Record<string, number> = {}
          for (const tp of s.wc.turningPoints) out[tp.kind] = (out[tp.kind] || 0) + 1
          return out
        })(),
        turningPointDropped: s.wc.turningPointDropped,
        // 🔴 强度分桶（只有 strong 进保护集合 ⇒ 收窄是否生效的机械证据）
        turningPointStrength: tpStrengthCountsOf(s),
        overBudgetFloor: s.wc.overBudgetFloor,
        at: Date.now(),
        mono: mono(),
      })
    }
  })

  // ── 子会话边界（用于对照；子会话本身永不评估）──
  ctx.on('subagent/start', (info: any) => {
    emit({
      ev: 'subagent-start',
      id: info && info.id ? String(info.id) : null,
      provider: info && info.provider ? String(info.provider) : null,
      at: Date.now(),
    })
  })
  ctx.on('subagent/end', (info: any) => {
    emit({ ev: 'subagent-end', id: info && info.id ? String(info.id) : null, at: Date.now() })
  })
}
