/** node-hints.ts —— 由 `runtime/aios-activation.ts` 拆出（纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { NodeInjectSlot } from './probe-state.ts'
import { nodeTargetPathOf } from './probe-state.ts'
import { POLICY, clip, isExecToolName } from './../diagnostics/probe.ts'
import type { NodeId } from './probe-state.ts'
import { SESSIONS } from './../session/session-state.ts'

export const CMD_ARG_KEYS = ['command', 'cmd', 'script']

export function pickCommandArg(args: unknown): string {
  if (!args || typeof args !== 'object') return ''
  const a = args as Record<string, unknown>
  for (const k of CMD_ARG_KEYS) if (typeof a[k] === 'string' && a[k]) return String(a[k])
  return ''
}

/**
 * 🔴 **本会话占用的卡**（**判据唯一来源** · 步骤 2：读**卡上的真相**）：
 *   `State == Executing` **且** 卡内 `Event Log` 最后一条占用行的 `op == 'claim'`
 *   **且** 该行 `session == 本会话`。
 * ⛔ 只读卡 ⇒ 与工具写的真相**同源**（被拒的 `claim` 不改卡、不写留痕 ⇒ 不会被误认）。
 * ⛔ 那条 `session` 正是「**占用是排他的**」的落地：别人的占用不认给我。
 */

export const PUSH_RELEASE_CMD_RE = /(^|[\s;&|()"'=])git\s+push\b|\bgh\s+(release\b|pr\s+(create|merge)\b)|\bnpm\s+publish\b|\bdocker\s+push\b|\btwine\s+upload\b/i

/** 节点提示文本（族卡指针 + 五条核对；⛔ 不塞正文，细节走指针）。
 *  🔴 读数修正（子 agent 反馈）：①⛔ 不假设 `origin/main`（读数分支是 master）⇒ 用 `origin/<当前分支>` 或 `git ls-remote`；
 *  ⑤ 补「push 报 sh.exe/管道错 = 沙箱限制（不是凭据）」——本地 file:// 传输也经 sh.exe，被沙箱挡（扩展）。 */

export function pushReleaseHintText(): string {
  return '【AI-OS · 发布/推送节点】动手前后各核一遍（同族处置 → `domains/experiences/push_release_family.md`）：'
    + '① 推后核 `origin/<当前分支>`（或 `git ls-remote`）已前进；② PR 以 diff 为准（`pulls/N/files`），提交前核**全副本**防夹带；'
    + '③ 删 JSON 字段后先 `json.load` 复验；④ `gh api` 查询加 `--method GET`、分支名带 `/` 用 `git/ref/heads/`；'
    + '⑤ push 报 `sh.exe … signal pipe / Win32 error 5` 或 `Could not read from remote repository` ⇒ **沙箱挡管道（不是凭据问题）**，需提权或换非 sh 传输。'
}

/** 每会话只提示一次（push→PR→merge 连续动作不刷屏）。 */

export const PUSH_RELEASE_HINT_SEEN = new Set<string>()

/** 🔴 （「按可发现的节点」）：**改本体节点** —— 只盯「编辑 `runtime/*.ts`」这一个动作。
 *  节点可发现：编辑类工具的 `path`/`file_path` 参数命中 `runtime/<文件>.ts` ⇒ 动作发生时给 Runtime 改造族卡指针 + 四条铁律
 *  （这类坑的典型形态是**零报错、零探针、整段静默失效**，事后极难归因，所以要在动作发生的当下提醒）。
 *  ⛔ 不看结果（改完就提示）；每会话一次；探针只落路径的 clip 片段。 */

export const RUNTIME_EDIT_PATH_RE = /(^|[\\/])runtime[\\/][^\\/]+\.ts$/i

export const RUNTIME_EDIT_TOOL_RE = /^(edit|write|edit_file|write_file|apply_patch|multiedit|patch|str_replace)$/i

export const RUNTIME_EDIT_HINT_SEEN = new Set<string>()

export function runtimeEditHintText(): string {
  return '【AI-OS · 改本体节点】改 `runtime/*.ts` 的四条铁律（族卡 → `domains/experiences/runtime_change_family.md`）：'
    + '① 注入段里**现取**依赖（⛔ 别引用别处 `try{}` 的 const：`ReferenceError` 会被 catch 吞 ⇒ **整段注入静默失效**）；'
    + '② catch 里**至少落一条失败探针**（否则零报错、零探针）；③ 接线类改动要有**走真实 handler** 的异步用例；'
    + '④ 改完追加 POLICY token，重启后先读最后一条 `ev=apply` 确认加载。'
}

/** **执行类工具门** —— `exec-permission-error` 只对"命令执行"类工具生效；
 *  `read/grep/glob/...` 的结果是**数据**（可能包含错误格式示例文本），不算执行失败。
 *  兼容：tool 名未知（`''`）⇒ 返回 `null`（旧行为：只按文本判，旧纯函数调用不破）。 */

export const NODE_CORPUS_DOMAINS_RE = /(^|[\\/])domains[\\/]/i

export const NODE_CORPUS_PITFALLS_RE = /(^|[\\/])task_cards[\\/]memory[\\/]PITFALLS\.md$/i

export const NODE_CORPUS_DIGEST_RE = /(^|[\\/])domains[\\/]experiences[\\/]inject_digests\.md$/i

/** N2 判据：**重建索引** —— `semantic_search.py build`（⛔ `query`/`selftest` 不算）。
 *  判据取「脚本名后紧跟 `build` 作为下一个 token」⇒ `semantic_search.py query "build 索引"` **不命中**
 *  （读数 CLI 形态：`$VENV scratch/semantic_search.py build`）。 */

export const NODE_INDEX_BUILD_RE = /semantic_search\.py["']?\s+build\b/i

/** N3 判据：**跑回归门** —— 命令里出现下列回归入口之一即命中
 *  （已确认：`_guard_now.py` = paraphrase/N=30 回归门；`_scene_probe.py --check` = 快照对比回归用）。
 *  ⚠️ 只排除明显不执行的 `--help`/`-h`（否则"看帮助"也会被当成跑回归门）。 */

export const NODE_REGRESSION_CMD_RE = /_guard_now\.py|_scene_probe\.py|_family_coverage_|_fp_ablation_|_n30_/i

export const NODE_HELP_ONLY_RE = /--help\b|(^|\s)-h(\s|$)/i

/** 注入文案：**族名 + 一句判据提示 + `→ 路径`**（与经验族注入形态一致 · ⛔ 不注正文）。 */

export function corpusNodeHintText(): string {
  return '【AI-OS · 节点：改语料】\n'
    + '经验 ▸ 判读读数与判据时（自检 · 期望集 · 统计口径）\n'
    + '      → domains/experiences/selfcheck_judgement_family.md\n'
    + '      （语料变了 ⇒ 探针期望集必须同代；新条目先查纯向量余量）'
}

export function indexNodeHintText(): string {
  return '【AI-OS · 节点：重建索引】\n'
    + '经验 ▸ 判读读数与判据时（自检 · 期望集 · 统计口径）\n'
    + '      → domains/experiences/selfcheck_judgement_family.md\n'
    + '      （重建后先跑回归门读数再宣告达标；对比先对齐语料版本指纹）'
}

export function regressionNodeHintText(): string {
  return '【AI-OS · 节点：跑回归门】\n'
    + '经验 ▸ 判读读数与判据时（自检 · 期望集 · 统计口径）\n'
    + '      → domains/experiences/selfcheck_judgement_family.md\n'
    + '      （读数降了先判是语料/索引/期望集哪一代不同；⛔ 不拿"已改善"当已验证）'
}

export function nodeHintTextOf(node: NodeId): string {
  if (node === 'N1') return corpusNodeHintText()
  if (node === 'N2') return indexNodeHintText()
  return regressionNodeHintText()
}

/** 节点注入的会话级状态（**内存** · 与 `SESSIONS` 同一生命周期 —— `dropSession()` 同步释放）。
 *  🔴 去重口径：**每节点每会话一次**（Set）；`dup` 读数每节点也只报一条（防每拍刷屏）。 */

export const NODE_INJECT = new Map<string, NodeInjectSlot>()

export function emptyNodeInjectSlot(): NodeInjectSlot {
  return { sent: new Set(), dupReported: new Set() }
}

export function nodeInjectSlotOf(session: string): NodeInjectSlot {
  let slot = NODE_INJECT.get(session)
  if (slot === undefined) {
    slot = emptyNodeInjectSlot()
    NODE_INJECT.set(session, slot)
  }
  return slot
}

/** 工具参数里的**目标路径**（编辑类工具：`file_path` / `path` / `new_path`）。 */

export function isCorpusEditTarget(rawPath: string): boolean {
  const p = String(rawPath || '').replace(/\\/g, '/')
  if (p === '') return false
  return NODE_CORPUS_DOMAINS_RE.test(p) || NODE_CORPUS_PITFALLS_RE.test(p) || NODE_CORPUS_DIGEST_RE.test(p)
}

/**
 * **节点判定（纯函数 · 供 S153/S154）**：`(工具名, 参数)` ⇒ `N1|N2|N3|null`。
 * 边界：
 *   · N1 只认**编辑类工具**（复用 的同一集合 ⇒ ⛔ 不造第二套工具名单）；`read`/`grep` **不命中**；
 *   · N2/N3 只认**执行类工具**（`isExecToolName`）—— 工具名未知（`null`）时**仍按命令判**（防真实宿主工具名未知导致静默漏报）；
 *   · ⛔ 只看动作不看结果（改完/跑完就提示）；⛔ 不涉及正文。
 */

export function nodeHintOf(tool: string, args: unknown): NodeId | null {
  const t = String(tool === null || tool === undefined ? '' : tool).trim()
  // N1：编辑语料
  if (RUNTIME_EDIT_TOOL_RE.test(t)) {
    if (isCorpusEditTarget(nodeTargetPathOf(args))) return 'N1'
    return null
  }
  const cmd = pickCommandArg(args)
  if (cmd === '') return null
  if (isExecToolName(t) === false) return null // 明确的读取类工具 ⇒ 不按命令判（防 read 的结果/参数误命中）
  // N2：重建索引（只 build 算，query 不算）
  if (NODE_INDEX_BUILD_RE.test(cmd)) return 'N2'
  // N3：跑回归门（`--help` 不算）
  if (NODE_REGRESSION_CMD_RE.test(cmd) && !NODE_HELP_ONLY_RE.test(cmd)) return 'N3'
  return null
}

/** T5：注入限额 —— 连续 2 条注入仍未换来检索 ⇒ 停发（⛔ 不刷屏）。 */
