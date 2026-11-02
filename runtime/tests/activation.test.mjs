/**
 * activation.test.mjs — AI-OS v2 / P0 · 隔离自测（本体自测 · 统一入口）
 *
 * 对象：`runtime/aios-activation.ts`（阶段 2 Trigger Resolver + 「§15 延迟发现」增量 + 阶段 4）
 * 方法：临时卡树（`AIOS_CARDS_DIR` 隔离先例）+ mock cordis ctx + hook `console.log` 收探针行
 * 纪律：**不碰真实卡** · **不注入** · **不检索** · 只读断言（探针日志会被追加，session 名带 `selftest-` 前缀便于分辨）
 * 迁移纪律：**逐字等价** —— 硬编码绝对路径一律改为相对解析；用例编号 S1–S86 与原状一一对应，零回退是验收判据。
 */
import assert from 'node:assert/strict'
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { dirname } from 'node:path'

// 🔴 测试隔离：经验召回会 spawn `python tools/experience_push.py` —— 自测不触发外部进程。
process.env.AIOS_EXPERIENCE_RECALL = 'off'
// 🔴 测试隔离：阶段注入会 spawn `python tools/probes/_retrieval_request_probe.py`
//    —— 主套件一律关掉（否则：① 沙箱内 spawn 失败污染读数 ② S132/S133/S87/S88 等
//    「additionalContexts 数量」类断言会被多出的一条 user 消息破坏）。
//    S146 单独 `delete` 该 env 打开接线。
process.env.AIOS_PHASE_INJECT = 'off'

// ── 仓库根：**相对解析**（clone 到任意位置都能跑）────────────────────────────────
//   本文件位于 `<root>/runtime/tests/` ⇒ 上溯两级即 `<root>`。
//   ⚠️ 统一转正斜杠：本体内部的路径分类判据与全部既有断言都以正斜杠形态为准
//      ⇒ 这样 `CARDS` / `PLUGIN` 与原 `scratch/` 版本**逐字等价**（零行为漂移）。
const HERE = dirname(fileURLToPath(import.meta.url)) // <root>/runtime/tests
const ROOT = dirname(dirname(HERE)).replace(/\\/g, '/') // <root>
const SCRATCH = ROOT + '/scratch'

const CARDS = SCRATCH + '/_selftest_cards_deferred'
const PLUGIN = ROOT + '/runtime/aios-activation.ts'
/** 期望的观测版本（与插件 `OBS` 常量同步；改版本时两处一起改）。 */
const OBS_EXPECT = 'v7-turnend-fill'

/** 自测卡模板（含 S2 的 `Goal` / `Next Action` —— 与真实卡模板同形）。 */
function cardFull(id, state, step, goal, next) {
  return [
    '# TASK_CARD — selftest',
    '',
    '```',
    'Task ID:     ' + id,
    '```',
    '',
    '## Goal',
    '',
    goal,
    '',
    '## Current Status',
    '',
    '```',
    'State:         ' + state,
    'Current Step:  ' + step,
    'Next Action:   ' + next,
    '```',
    '',
  ].join('\n')
}

// ── 临时卡树（只读扫描目标）──────────────────────────────────────────────────
rmSync(CARDS, { recursive: true, force: true })
mkdirSync(CARDS + '/projA', { recursive: true })

function card(id, state, step) {
  return [
    '# TASK_CARD — selftest',
    '',
    '```',
    'Task ID:     ' + id,
    '```',
    '',
    '## Current Status',
    '',
    '```',
    'State:         ' + state,
    'Current Step:  ' + step,
    '```',
    '',
  ].join('\n')
}

const C1 = CARDS + '/projA/TASK-20260101-001.md'
const C2 = CARDS + '/projA/TASK-20260101-002.md'
writeFileSync(C1, card('TASK-20260101-001', 'Executing', 'S1'))
writeFileSync(C2, card('TASK-20260101-002', 'Waiting', 'W1'))

// ── 探针收集（hook console.log —— 必须在 import 前装好）─────────────────────
const lines = []
const origLog = console.log
console.log = (...a) => { lines.push(a.map(String).join(' ')) }

// ⚠️ env 必须在插件**求值前**设置 ⇒ 用动态 import（静态 import 会被提升）
process.env.AIOS_CARDS_DIR = CARDS
// ⚠️ 自测**必须**走独立探针通道：否则自测行会污染真实窗口的证据（2026-10-09 实测教训）
process.env.AIOS_PROBE_PATH = SCRATCH + '/_selftest_activation.probe.log'
// ⚠️ Step B′ 递送验证的**启停开关**同样必须在插件求值前指向隔离文件（**绝不碰真实开关**）
const DELIVERY_PROBE = SCRATCH + '/_selftest_delivery_probe.json'
process.env.AIOS_DELIVERY_PROBE = DELIVERY_PROBE
// ⚠️ 3.2 影子发现通道的启停开关**同样**指向隔离文件（**绝不碰真实开关** ⇒ 不产生真实派发）
const SHADOW_PROBE = SCRATCH + '/_selftest_shadow_probe.json'
process.env.AIOS_SHADOW_PROBE = SHADOW_PROBE
// ⚠️ 阶段 4 开关**同样**指向隔离文件（2026-10-15 增：会话通配用例必须能开关 stage4 门，
//    且**绝不**动 `scratch/_stage4_probe.json` —— 那是真实观察窗的开关）
const STAGE4_PROBE = SCRATCH + '/_selftest_stage4_probe.json'
process.env.AIOS_STAGE4_PROBE = STAGE4_PROBE
try { rmSync(STAGE4_PROBE, { force: true }) } catch { /* 静默 */ }
// 🔴 v23 注入实验：**必须**指向隔离位且**默认不存在**（= 关闭）——
//    否则 `.aios/inject_probe.json`（enabled + session "*"）会让每个自测用例都多一条 user 消息，
//    破坏 S37 等"原结果不变 / additionalContexts 数量"类断言。
process.env.AIOS_INJECT_PROBE = SCRATCH + '/_selftest_inject_probe.json'
try { rmSync(process.env.AIOS_INJECT_PROBE, { force: true }) } catch { /* 静默 */ }
// 🔴 **焦点卡接口件同样必须指向隔离位**（2026-10-15 增）—— 且必须在这里（**插件求值之前**）：
//    `writeFocusCard()` 挂在 `tools/pre-execute` 上 ⇒ S79–S86 等**早期用例**也会触发它。
//    ⚠️ 实测教训：初版把它设在文件**尾部** ⇒ 早期用例走了真实路径 ⇒ **污染了真实位
//    `.aios/focus-card.json`**（写进了 `session:"selftest-wildcard-abc"` 与测试临时卡）。
//    ⇒ 与其它探针同一纪律：**隔离 env 一律在 import 之前设**。
const FC_DIR = SCRATCH + '/_selftest_focus_card'
const FC_FILE = FC_DIR + '/focus-card.json'
process.env.AIOS_FOCUS_CARD = FC_FILE
rmSync(FC_DIR, { recursive: true, force: true })
mkdirSync(FC_DIR, { recursive: true })
// 🔴 真实位快照：S95 用它断言"本自测**没有**改动真实运行数据"（**反向**判据）
const REAL_FC = ROOT + '/.aios/focus-card.json'
const REAL_FC_BEFORE = existsSync(REAL_FC) ? readFileSync(REAL_FC, 'utf8') : null
// 🔴 **启动即清空隔离开关**：上一次运行若在断言处失败 ⇒ `clearShadow()` 不会执行 ⇒
//    残留的开关文件会让本次的**同步用例**也派发影子发现（并耗尽 `maxPerSession`）⇒ 污染判读。
try { rmSync(SHADOW_PROBE, { force: true }) } catch { /* 静默 */ }
const mod = await import(pathToFileURL(PLUGIN).href)

// ── 入口面断言（R6 · 2026-11-02 独立审计：宿主三件套从无断言，重导出断了也不会红）──
//    `mod.*` 是宿主实际读的东西；模块化/搬运把导出面搬丢时，这里必须先红。
//    🔴 2026-11-02 修「哑断言」：这里**只定义**断言数据，**登记**放到 `check()` 定义之后 ——
//       原来在此直接用 `console.log` 报 FAIL，而 `console.log` 在第 90 行就被 hook 进探针缓冲区
//       ⇒ 全红也不显示、不进合计、不改退出码（等价于没有断言）。
const ENTRY = [
  ['name 是字符串', typeof mod.name === 'string' && mod.name.length > 0],
  ['name = aios-activation', mod.name === 'aios-activation'],
  ['inject 是数组', Array.isArray(mod.inject)],
  ['apply 是函数', typeof mod.apply === 'function'],
  ['__selftest 存在', mod.__selftest !== undefined && typeof mod.__selftest === 'object'],
  ['outputExceedsLimit 重导出', typeof mod.outputExceedsLimit === 'function'],
  ['switchNeedsReload 重导出', typeof mod.switchNeedsReload === 'function'],
]

function records() {
  return lines
    .map(l => {
      try { return JSON.parse(l.replace(/^\[aios-activation\]\s*/, '')) } catch { return null }
    })
    .filter(Boolean)
}

// ── mock cordis ctx ─────────────────────────────────────────────────────────
const handlers = new Map()
const ctx = {
  effect: (cb) => { const d = cb(); return typeof d === 'function' ? d : () => {} },
  on: (ev, h) => {
    if (!handlers.has(ev)) handlers.set(ev, [])
    handlers.get(ev).push(h)
  },
}
mod.apply(ctx)

const SESS = 'selftest-main'
const SUB = 'selftest-sub'
const agent = (session, header) => ({
  session: { header: Object.assign({ id: session }, header || {}) },
})
const MAIN = agent(SESS, { delegationDepth: 0 })
const SUBAGENT = agent(SUB, { origin: 'subagent', delegationDepth: 1, parentSession: 'x' })

/** waterfall 调用：返回 next 调用次数 + 返回值（约束 2 的回归） */
function wf(ev, payload) {
  const h = (handlers.get(ev) || [])[0]
  assert.ok(h, 'handler missing: ' + ev)
  // 🔴 **贴真实契约**：`tools/pre-execute` 的载荷是 `ToolExecutionInput`
  //    = {callId, rootCallId?, name, arguments, agent?, parent?, signal} —— **没有 turn / step**
  //    （`packages/core/tools/src/index.ts:307-331`）
  //    ⇒ 这里显式**删掉** turn/step：任何依赖它们的实现都会在此暴露
  //      （真实窗口抓到的 §12.10 缺陷，正是旧自测喂了 `turn: 1` 才漏判）
  const p = Object.assign({}, payload)
  if (ev === 'tools/pre-execute') {
    delete p.turn
    delete p.step
  }
  let calls = 0
  const ret = h(p, () => { calls++; return 'NEXT_RET' })
  return { calls, ret }
}
const emit1 = (ev, payload) => {
  const h = (handlers.get(ev) || [])[0]
  assert.ok(h, 'handler missing: ' + ev)
  return h(payload)
}

const userMsg = (text) => ({ role: 'user', content: text })
const results = []
/** 异步用例的完成任务（汇总前必须 await —— v8 起 `tools/post-execute` handler 是 async）。 */
const pending = []
/**
 * 🔴 2026-11-02 **v51r**（Human 定方向「注入跟随卡上声明」）后**已废弃**的用例：
 *   S184/S185/S186 断言的是 **v51q 的「按 topic 猜域 + 判不出就回退检索」**接线 ——
 *   该路径已停用（实测机器猜域精确率 topic 57% / 检索 47–59% / 路径 83%，
 *   均不可作为注入依据 ⇒ 改为读卡上声明）。替代用例：**S188–S193**。
 *   ⇒ 显式 SKIP（⛔ 不静默删、⛔ 不改假绿）：名字留给历史检索，跳过原因写在这里。
 */
const DECLARED_ONLY = true
const DECL_SKIP_NAMES = /^(S184|S185|S186)\b/
function check(name, fn) {
  if (DECLARED_ONLY && DECL_SKIP_NAMES.test(name)) {
    results.push('SKIP  ' + name + ' :: 猜域接线已停用（改为读卡上声明 · 见 S188–S193）')
    return
  }
  try {
    fn()
    results.push('PASS  ' + name)
  } catch (e) {
    results.push('FAIL  ' + name + ' :: ' + (e && e.message ? e.message : String(e)))
  }
}
/**
 * 异步版（保持结果顺序：先占位，完成后回填）。
 * 🔴 **只入队、不立即执行** —— 必须**顺序**跑：本组用例共用同一个开关文件与计数，
 *    并发会互相干扰（自测第一版就是这样自己抓到的）。
 */
function checkAsync(name, fn) {
  if (DECLARED_ONLY && DECL_SKIP_NAMES.test(name)) {
    results.push('SKIP  ' + name + ' :: 猜域接线已停用（改为读卡上声明 · 见 S188–S193）')
    return
  }
  const idx = results.length
  results.push('PENDING  ' + name)
  pending.push(async () => {
    try {
      await fn()
      results[idx] = 'PASS  ' + name
    } catch (e) {
      results[idx] = 'FAIL  ' + name + ' :: ' + (e && e.message ? e.message : String(e))
    }
  })
}

// ── 入口面断言登记（走 `check()` ⇒ 进 results / 进合计 / 影响退出码）──────────────
for (const [label, ok] of ENTRY) {
  check('入口导出面：' + label, () => {
    assert.equal(ok, true, '宿主导出面缺失或类型不对（见上方 ENTRY 定义）')
  })
}

// ── 模块 smoke（R6 遗留 · 2026-11-02）──────────────────────────────────────────
//    入口面断言只覆盖 `mod.*`（宿主实际读的导出面）；**模块自己的 import/导出接线从无断言** ——
//    搬模块时把文件路径接丢 / 导出改名 / 重导出链断，主入口可能仍然全绿。
//    ⇒ 绕过主入口，**直接** import 11 个模块文件（路径相对 PLUGIN 所在目录推导 · ⛔ 不写死盘符），
//      逐个断言「import 成功 + 关键导出存在且类型正确」。
//    计数：每个模块 = 1 项 `check`（共 11 项），走现有 results 计数 ⇒ 合计自然 +11。
//    ⚠️ 这些模块已在主入口 import 时求值过（ESM 缓存）⇒ 这里不会二次执行顶层副作用。
const RUNTIME_DIR = dirname(PLUGIN)
const MODULE_SMOKE = [
  ['M1 diagnostics/probe', 'diagnostics/probe.ts', [
    ['emit', 'function'], ['TAG', 'string'], ['stripRepoPaths', 'function'],
  ]],
  ['M2 session/session-state', 'session/session-state.ts', [
    ['sessionIdOf', 'function'], ['identityOf', 'function'], ['SESSIONS', 'object'],
  ], (ns) => assert.ok(ns.SESSIONS instanceof Map, 'SESSIONS 必须是 Map')],
  ['M3 session/work-context', 'session/work-context.ts', [
    ['toolClassOf', 'function'], ['failKindOf', 'function'], ['trimTurningPoints', 'function'],
  ]],
  ['M4 session/lifecycle', 'session/lifecycle.ts', [
    ['writeFocusCard', 'function'], ['focusCardFile', 'function'], ['FOCUS_CARD_SCHEMA', 'string'],
  ]],
  ['M5 retrieval/python-bridge', 'retrieval/python-bridge.ts', [
    ['spawnJson', 'function'], ['outputExceedsLimit', 'function'], ['SPAWN_MAX_STDOUT_BYTES', 'number'],
  ]],
  ['M6 retrieval/request-builder', 'retrieval/request-builder.ts', [
    ['inlineRetrieval', 'function'], ['buildRetrievalRequest', 'function'], ['recallTriggerOf', 'function'],
  ]],
  ['M7 activation/phase-policy', 'activation/phase-policy.ts', [
    ['phaseOf', 'function'], ['phaseInjectSlotOf', 'function'], ['PHASE_INJECT', 'object'],
  ], (ns) => assert.ok(ns.PHASE_INJECT instanceof Map, 'PHASE_INJECT 必须是 Map')],
  ['M8 activation/declared-domain', 'activation/declared-domain.ts', [
    ['applyDeclaredDomainInjection', 'function'], ['domainCapabilityResolvedOf', 'function'], ['PHASE_TITLE', 'object'],
  ]],
  ['M9 maintenance/r3-wake', 'maintenance/r3-wake.ts', [
    ['installR3Wake', 'function'], ['takeoverFromLog', 'function'], ['r3WakeCycle', 'function'],
  ]],
  ['M10 delivery/pending-delivery', 'delivery/pending-delivery.ts', [
    ['readDeliveryProbe', 'function'], ['sessionAllowsProbe', 'function'], ['deliveryProbeFile', 'function'],
  ]],
  ['M11 delivery/phase-injection', 'delivery/phase-injection.ts', [
    ['applyStepBDelivery', 'function'],
  ]],
  ['M12 activation/phase-candidates', 'activation/phase-candidates.ts', [
    ['buildPhaseRetrievalRequest', 'function'], ['renderPhaseCandidates', 'function'], ['phaseMaxCandidates', 'function'],
  ]],
  ['M13 retrieval/experience-recall', 'retrieval/experience-recall.ts', [
    ['experienceRecallEnabled', 'function'], ['emptyRecallSlot', 'function'], ['recallAllowed', 'function'],
  ]],
  ['M14 delivery/node-hints', 'delivery/node-hints.ts', [
    ['nodeHintOf', 'function'], ['nodeInjectSlotOf', 'function'], ['NODE_INJECT', 'object'],
  ]],
  ['M15 delivery/probe-state', 'delivery/probe-state.ts', [
    ['detectEvents', 'function'], ['emptyEventSlot', 'function'], ['setR3DisarmPending', 'function'], ['buildFirstStepRetrievalRequest', 'function'],
  ], (ns) => assert.ok(ns.DELIVERY_SENT instanceof Map, 'DELIVERY_SENT 必须是 Map')],
]
for (const [label, rel, expects, extra] of MODULE_SMOKE) {
  let ns = null
  let importErr = null
  try {
    ns = await import(pathToFileURL(RUNTIME_DIR + '/' + rel).href)
  } catch (e) {
    importErr = e
  }
  check(label + ' 模块 smoke：可 import 且关键导出类型正确', () => {
    assert.equal(importErr, null, 'import 失败：' + (importErr && importErr.message ? importErr.message : String(importErr)))
    assert.equal(typeof ns, 'object', '模块命名空间必须是对象')
    for (const [sym, type] of expects) {
      assert.ok(sym in ns, '缺少导出：' + sym)
      assert.equal(typeof ns[sym], type, '`' + sym + '` 类型应为 ' + type + '，实际 ' + typeof ns[sym])
    }
    if (extra) extra(ns)
  })
}

const triggers = () => records().filter(r => r.ev === 'trigger')
const lastTrigger = () => triggers()[triggers().length - 1]
const discos = () => records().filter(r => r.ev === 'discovery-opportunity')
// ── 判据类 vs 观察类（本轮 Observe-only 增补后必须分开断言）──
const JUDGEMENT_EV = ['trigger', 'discovery-opportunity', 'discovery-missed']
const judgement = () => records().filter(r => JUDGEMENT_EV.includes(r.ev))
const steps = () => records().filter(r => r.ev === 'step')
const toolSigs = () => records().filter(r => r.ev === 'tool-sig')
const toolResults = () => records().filter(r => r.ev === 'tool-result')
const turnSigs = () => records().filter(r => r.ev === 'turn-sig')

// ── 用例 ────────────────────────────────────────────────────────────────────

emit1('agent/session-start', { agent: MAIN, source: 'startup' })

// S1 基线 + 长输入 ⇒ D + 延迟等待窗口
let r1
check('S1 首观测基线：kind=D 且长输入 ⇒ discovery=waiting', () => {
  r1 = wf('agent/pre-step', {
    agent: MAIN, turn: 1, step: 1, messages: [userMsg('帮我把 Supabase 的 RLS 策略补完整，并跑一次迁移验证')],
  })
  assert.equal(r1.calls, 1, 'next() 必须恰好一次')
  assert.equal(r1.ret, 'NEXT_RET', 'next() 返回值必须原样透传')
  const t = lastTrigger()
  assert.equal(t.kind, 'D')
  assert.equal(t.discovery, 'waiting')
  assert.equal(t.promptClass, 'unclassified')
  assert.equal(t.promptSrc, 'role=user')
  assert.equal(t.waiting, true)
})

// S2 等待窗口内首个实质工具意图 ⇒ deferred 机会
check('S2 等待窗口内 tools/pre-execute(read) ⇒ deferred 机会（仅判定，不递送）', () => {
  const r = wf('tools/pre-execute', { agent: MAIN, turn: 1, step: 1, name: 'read_file', arguments: { file_path: 'x.sql' } })
  assert.equal(r.calls, 1, 'next() 必须恰好一次')
  assert.equal(r.ret, 'NEXT_RET')
  const d = discos()
  assert.equal(d.length, 1)
  assert.equal(d[0].mode, 'deferred')
  assert.equal(d[0].tool, 'read_file')
  assert.equal(d[0].turn, undefined, '载荷无 turn ⇒ 记录里也不得伪造 turn')
  assert.equal(typeof d[0].windowSeq, 'number', '去重键必须是回合序号（不依赖载荷 turn）')
  assert.ok(String(d[0].note).includes('NOT wired'), '必须自述阶段 4 第③段未接（文案校正 2026-10-14：NOT implemented → NOT wired，属既有断言过时）')
})

// S2b 🔴 回归护栏：载荷**只有**真实字段（无 turn/step）时仍必须触发 deferred
check('S2b 真实契约载荷（无 turn/step）⇒ deferred 仍成立', () => {
  // 新回合：先开窗口
  wf('agent/pre-step', { agent: MAIN, turn: 77, step: 1, messages: [userMsg('把这一块的实现整理成可复用的模块，然后补测试')] })
  assert.equal(lastTrigger().discovery, 'waiting')
  const before = discos().length
  const r = wf('tools/pre-execute', {
    agent: MAIN, callId: 'call-real-1', name: 'read', arguments: { file_path: 'a.ts' }, signal: {},
  })
  assert.equal(r.calls, 1)
  assert.equal(discos().length, before + 1, '真实形状载荷也必须触发')
  assert.equal(discos()[discos().length - 1].callId, 'call-real-1')
})

// S3 同回合第二个工具 ⇒ 判据静默（只认首个意图）；**观察行仍会写**（Observe-only 增补）
check('S3 同回合再次工具 ⇒ 判据静默（观察行可增）', () => {
  const jBefore = judgement().length
  const dBefore = discos().length
  const sigBefore = toolSigs().length
  const r = wf('tools/pre-execute', { agent: MAIN, turn: 1, step: 1, name: 'grep', arguments: { pattern: 'rls' } })
  assert.equal(r.calls, 1, '即使静默也必须透明 next()')
  assert.equal(r.ret, 'NEXT_RET')
  assert.equal(discos().length, dBefore, '同一回合只发一次 deferred（相对计数）')
  assert.equal(judgement().length, jBefore, '同回合后续工具不得新增【判据】记录')
  assert.equal(toolSigs().length, sigBefore + 1, '但应留下一条 tool-sig 观察行')
})

// S4 延续型短输入 + 同卡同 step ⇒ C + quiet
check('S4 延续型输入（"继续"）⇒ kind=C 且 discovery=quiet', () => {
  wf('agent/pre-step', { agent: MAIN, turn: 2, step: 1, messages: [userMsg('继续')] })
  const t = lastTrigger()
  assert.equal(t.kind, 'C')
  assert.equal(t.discovery, 'quiet')
  assert.equal(t.promptClass, 'continuation')
  assert.equal(t.waiting, false)
})

// S5 新卡进入 Executing ⇒ A + task_fact（即使输入是延续语，任务事实优先）
check('S5 新卡进入 Executing ⇒ kind=A 且 discovery=task_fact', () => {
  writeFileSync(C2, card('TASK-20260101-002', 'Executing', 'W1'))
  wf('agent/pre-step', { agent: MAIN, turn: 3, step: 1, messages: [userMsg('继续')] })
  const t = lastTrigger()
  assert.equal(t.kind, 'A')
  assert.equal(t.discovery, 'task_fact')
  assert.equal(t.phase, 'ACTIVE')
})

// S6 卡集合变化但无新进入 + 延续输入 ⇒ D + quiet（不猜，也不等待）
check('S6 非新进入的集合变化 ⇒ kind=D 且延续输入 ⇒ quiet', () => {
  writeFileSync(C2, card('TASK-20260101-002', 'Waiting', 'W1'))
  wf('agent/pre-step', { agent: MAIN, turn: 4, step: 1, messages: [userMsg('好的')] })
  const t = lastTrigger()
  assert.equal(t.kind, 'D')
  assert.equal(t.discovery, 'quiet')
})

// S7 等待窗口未等到意图 ⇒ 回合关闭记 missed（不跨回合补做）
check('S7 等待窗口未命中 ⇒ turn-stopping 记 discovery-missed', () => {
  wf('agent/pre-step', { agent: MAIN, turn: 5, step: 1, messages: [userMsg('把这一块也顺手处理一下，然后继续下一步')] })
  assert.equal(lastTrigger().discovery, 'waiting')
  emit1('agent/turn-stopping', { agent: MAIN, turn: 5 })
  const m = records().filter(r => r.ev === 'discovery-missed')
  assert.equal(m.length, 1)
  assert.equal(m[0].turn, 5)
})

// S7b 🔴 2026-10-14 回归护栏：多步回合里 `continuation` **不得关窗**
//   缺陷现场（10-14 · 产品会话 session-37639883）：
//     wSeq=2 pre-step 判 unclassified ⇒ 开窗 → wSeq=3 pre-step 判 continuation ⇒ 关窗
//     → 20:45:05 的 tools/pre-execute 工具意图到达时窗已关 ⇒ 影子链路永不触发、零 stage4。
//   对照（10-12 成功样本 session-73559d36）：wSeq=1 开窗后没有第二次 pre-step ⇒ 恰好命中。
//   ⇒ 本用例锁死"窗口必须跨步存活到首个工具意图"。
check('S7b 多步回合：continuation 不关窗 ⇒ 后续工具意图仍命中 deferred', () => {
  const dBefore = discos().length
  // ① 第一步：方向未定的输入 ⇒ 开窗
  wf('agent/pre-step', { agent: MAIN, turn: 88, step: 1, messages: [userMsg('把这一块也顺手处理一下，然后继续下一步')] })
  assert.equal(lastTrigger().discovery, 'waiting')
  assert.equal(lastTrigger().waiting, true)
  // ② 下一个回合的延续输入 ⇒ 判 continuation（**修复前这一步会关窗**）
  //    ⚠️ 与真实现场同构：10-14 现场 = 「turn N 开窗 → turn N+1 的 pre-step 判 continuation ⇒ 关窗」，
  //       不是同一 turn 的第二个 step（自测实测：同 turn `step=2` 会被判 `unclassified`）。
  wf('agent/pre-step', { agent: MAIN, turn: 89, step: 1, messages: [userMsg('继续')] })
  assert.equal(lastTrigger().promptClass, 'continuation')
  assert.equal(lastTrigger().waiting, true, 'continuation 不得关窗（2026-10-14 修复）')
  // ③ 工具意图到达 ⇒ 仍应命中，且只命中一次
  wf('tools/pre-execute', { agent: MAIN, callId: 'call-s7b-1', name: 'read', arguments: { file_path: 'a.ts' }, signal: {} })
  assert.equal(discos().length, dBefore + 1, '窗口跨步存活后必须命中')
  assert.equal(discos()[discos().length - 1].mode, 'deferred')
  // ④ 同一窗口再来一次工具意图 ⇒ 不再命中（一次机会）
  wf('tools/pre-execute', { agent: MAIN, callId: 'call-s7b-2', name: 'read', arguments: { file_path: 'b.ts' }, signal: {} })
  assert.equal(discos().length, dBefore + 1, '同一窗口只发一次 deferred')
})

// S8 焦点卡 Current Step 变化 ⇒ B + task_fact（§14.8 B 类）
check('S8 Current Step 变化 ⇒ kind=B 且 discovery=task_fact', () => {
  writeFileSync(C1, card('TASK-20260101-001', 'Executing', 'S2'))
  wf('agent/pre-step', { agent: MAIN, turn: 6, step: 1, messages: [userMsg('继续')] })
  const t = lastTrigger()
  assert.equal(t.kind, 'B')
  assert.equal(t.discovery, 'task_fact')
})

// S9 子会话 fail-closed：不评估、不产生 trigger
check('S9 子会话 fail-closed ⇒ 无 trigger、next() 仍恰好一次', () => {
  const before = triggers().length
  emit1('agent/session-start', { agent: SUBAGENT, source: 'startup' })
  const r = wf('agent/pre-step', {
    agent: SUBAGENT, turn: 1, step: 1, messages: [userMsg('这是一段足够长的子会话输入，用来确认子会话不会被评估')],
  })
  assert.equal(r.calls, 1)
  assert.equal(triggers().length, before, '子会话不得产生 trigger 记录')
  const rs = records().filter(x => x.ev === 'session-start' && x.session === SUB)
  assert.equal(rs.length, 1)
  assert.equal(rs[0].identity, 'subagent')
})

// S10 读不到输入 ⇒ fail-closed 到安静（none），并把退化来源写进探针
check('S10 无可读输入 ⇒ discovery=none 且 promptSrc 标注 no-text-content', () => {
  wf('agent/pre-step', { agent: MAIN, turn: 7, step: 1, messages: [{ role: 'user', content: [] }] })
  const t = lastTrigger()
  assert.equal(t.discovery, 'none')
  assert.equal(t.promptClass, 'unknown')
  assert.equal(t.promptSrc, 'no-text-content')
})

// S11 解析退化可见性（防 R4 式静默失效）
check('S11 只在非 user 消息里有文本 ⇒ promptSrc 标注 fallback（退化可见）', () => {
  wf('agent/pre-step', {
    agent: MAIN, turn: 8, step: 1, messages: [{ role: 'assistant', content: 'assistant text here for fallback probe' }],
  })
  const t = lastTrigger()
  assert.ok(String(t.promptSrc).startsWith('last-nonempty-fallback#'), 'must flag degraded parse, got ' + t.promptSrc)
})

// S12 机制类工具不算工作意图
check('S12 机制类工具（task_start / wrapup_sync）不构成工作意图', () => {
  const before = discos().length
  wf('agent/pre-step', { agent: MAIN, turn: 9, step: 1, messages: [userMsg('处理一下这个事情的后续步骤，看看要不要重新跑一遍')] })
  assert.equal(lastTrigger().discovery, 'waiting')
  wf('tools/pre-execute', { agent: MAIN, turn: 9, step: 1, name: 'task_start', arguments: {} })
  assert.equal(discos().length, before, 'task_start 不得触发定向发现机会')
  wf('tools/pre-execute', { agent: MAIN, turn: 9, step: 1, name: 'wrapup_sync', arguments: {} })
  assert.equal(discos().length, before, 'wrapup_sync 不得触发定向发现机会')
  wf('tools/pre-execute', { agent: MAIN, turn: 9, step: 1, name: 'todo_write', arguments: {} })
  const d = discos()
  assert.equal(d.length, before + 1, '计划类工具（todo_write）应构成 T1 意图')
  assert.equal(d[d.length - 1].intentKind, 'plan')
})

// S13 无等待窗口的工具意图 ⇒ 只观察，不发机会
check('S13 无等待窗口的工具意图 ⇒ 记 tool-intent（observation only）', () => {
  const before = discos().length
  wf('agent/pre-step', { agent: MAIN, turn: 10, step: 1, messages: [userMsg('继续')] })
  assert.equal(lastTrigger().discovery, 'quiet')
  wf('tools/pre-execute', { agent: MAIN, turn: 10, step: 1, name: 'edit_file', arguments: {} })
  assert.equal(discos().length, before, '无等待窗口不得发机会')
  const ti = records().filter(r => r.ev === 'tool-intent')
  assert.equal(ti.length, 1)
  assert.equal(ti[0].inWindow, false)
  assert.equal(ti[0].intentKind, 'work')
})

// S14 宿主注入块被剥离后再判长度（否则"继续"会被注入块撑成长输入 ⇒ 每轮等待）
check('S14 短输入 + 大段 system-reminder ⇒ 仍判 continuation（rawLen 另记）', () => {
  const injected = '<system-reminder>' + '工作区指令与记忆块'.repeat(30) + '</system-reminder>'
  wf('agent/pre-step', { agent: MAIN, turn: 11, step: 1, messages: [userMsg('继续' + injected)] })
  const t = lastTrigger()
  assert.equal(t.promptClass, 'continuation')
  assert.ok(t.promptRawLen > 12, 'rawLen 必须显著更大（证明剥离发生），got ' + t.promptRawLen)
  assert.ok(t.promptLen <= 12, 'promptLen 必须是剥离后的短长度，got ' + t.promptLen)
  assert.equal(t.discovery, 'quiet')
})

// ── 本轮 Observe-only 增补的用例（Human 2026-10-09 批准）────────────────────

check('S15 步骤序列：msgs=0 的延续步骤也被记录（只记计数 · 不做语义判决）', () => {
  wf('agent/pre-step', { agent: MAIN, turn: 21, step: 1, messages: [userMsg('把这一块整理成可复用模块并补测试，然后再跑一遍全量回归')] })
  const before = steps().length
  wf('agent/pre-step', { agent: MAIN, turn: 21, step: 2, messages: [] })
  const list = steps()
  assert.equal(list.length, before + 1, 'msgs=0 也必须留下 step 记录')
  const last = list[list.length - 1]
  assert.equal(last.msgs, 0, 'msgs 只记计数')
  assert.equal(last.obs, OBS_EXPECT)
  assert.equal(typeof last.windowSeq, 'number')
  assert.equal(typeof last.mono, 'string')
  assert.ok(!('continue' in last) && !('sameTask' in last), '不得出现任务语义字段')
})

check('S16 工作方向签名：只到目录级 · 剥掉文件名 · 参数原文不落盘', () => {
  const before = toolSigs().length
  wf('tools/pre-execute', { agent: MAIN, callId: 'c-a', name: 'read_file', arguments: { file_path: ROOT + '/supabase/migrations/20261008000002_rls.sql' }, signal: {} })
  wf('tools/pre-execute', { agent: MAIN, callId: 'c-b', name: 'edit_file', arguments: { file_path: ROOT + '/runtime/aios-activation.ts' }, signal: {} })
  wf('tools/pre-execute', { agent: MAIN, callId: 'c-c', name: 'pwsh', arguments: { command: 'git status --short' }, signal: {} })
  const sigs = toolSigs()
  assert.equal(sigs.length, before + 3, '每次工具调用各留一条 tool-sig')
  assert.equal(sigs[before].pathClass, 'supabase/migrations/')
  assert.equal(sigs[before].toolClass, 'read')
  assert.equal(sigs[before + 1].pathClass, 'runtime/')
  assert.equal(sigs[before + 1].toolClass, 'edit')
  assert.equal(sigs[before + 2].pathClass, null, 'command 不是路径参数')
  assert.equal(sigs[before + 2].toolClass, 'exec')
})

checkAsync('S17 工具结果：只记 ok，不记输出内容（v8 起 handler 为 async ⇒ 仍须原样透传）', async () => {
  clearProbe()
  const before = toolResults().length
  const h = handlers.get('tools/post-execute')[0]
  assert.ok(h, 'tools/post-execute handler 存在')
  let calls = 0
  const ret = await h({ agent: MAIN, callId: 'c-a', name: 'read_file' }, { isError: false, content: 'SECRET-CONTENT' }, () => { calls++; return 'R' })
  assert.equal(calls, 1, 'next() 恰好一次')
  assert.equal(ret, 'R', '原样返回（不改错误语义）')
  const rec = toolResults()[before]
  assert.equal(rec.ok, true)
  assert.equal(rec.toolClass, 'read')
})

check('S18 turn-stopping：回合签名汇总 + 回合级状态复位', () => {
  const before = turnSigs().length
  emit1('agent/turn-stopping', { agent: MAIN, turn: 21 })
  const list = turnSigs()
  assert.equal(list.length, before + 1)
  assert.equal(list[before].obs, OBS_EXPECT)
  assert.ok(Array.isArray(list[before].sig))
  assert.ok(list[before].sigLen >= 1, '本回合已有工具签名')
})

check('S19 隐私：任何记录都不含 prompt 正文 / 工具输出 / 文件名 / 命令原文', () => {
  const blob = JSON.stringify(records())
  assert.ok(!blob.includes('把这一块整理成可复用模块'), 'prompt 正文不得落盘')
  assert.ok(!blob.includes('SECRET-CONTENT'), '工具输出不得落盘')
  assert.ok(!blob.includes('20261008000002_rls'), '文件名不得落盘')
  assert.ok(!blob.includes('git status --short'), '命令原文不得落盘')
})

// ── §十八 两处缺口的回归护栏（Human 2026-10-09 裁定后修）────────────────────

check('S20 工作区外路径：只记顶层目录名（可归因 AI-OS / 其他）· 仍不记文件名', () => {
  const PROD = agent('selftest-prod', { delegationDepth: 0, cwd: 'D:/work/demo-app' })
  emit1('agent/session-start', { agent: PROD, source: 'startup' })
  wf('agent/pre-step', { agent: PROD, turn: 1, step: 1, messages: [userMsg('继续做 RLS 策略这一块')] })
  const before = toolSigs().length
  wf('tools/pre-execute', { agent: PROD, callId: 'p-1', name: 'read', arguments: { file_path: ROOT + '/README.md' }, signal: {} })
  wf('tools/pre-execute', { agent: PROD, callId: 'p-2', name: 'read', arguments: { file_path: 'D:/work/other-project/docs/REBUILD_PLAN.md' }, signal: {} })
  const sigs = toolSigs().slice(before)
  // 🔴 2026-11-02（clone 可用性）：期望值不能写死「仓库在 <repo>」——
  //   工作区外路径只记**顶层目录名**，而顶层目录名随克隆位置变化（曾因此让 `S20` 在干净 worktree 里误红）。
  //   ⇒ 从 ROOT 推导：`<repo>` → `AI-os`；`D:/scratch/tmp/x/y` → `scratch`。
  const REPO_TOP = ROOT.split('/')[1]
  assert.equal(sigs[0].pathClass, '<outside>/' + REPO_TOP + '/.md', '本仓顶层目录必须可辨认（克隆到哪都能推）')
  assert.equal(sigs[1].pathClass, '<outside>/work/.md', '其他工作区按顶层目录区分')
  const blob = JSON.stringify(sigs)
  assert.ok(!blob.includes('README') && !blob.includes('REBUILD_PLAN'), '仍不得出现文件名')
})

check('S21 trigger 带 windowSeq · 新回合首条 step 的序号与 trigger 一致（缺口 2 回归）', () => {
  wf('agent/pre-step', { agent: MAIN, turn: 31, step: 1, messages: [userMsg('把这一段逻辑抽成独立模块，并补上对应的回归测试用例')] })
  const t = lastTrigger()
  assert.equal(typeof t.windowSeq, 'number', 'trigger 必须带 windowSeq（A1 关联用）')
  const first = steps()[steps().length - 1]
  assert.equal(first.windowSeq, t.windowSeq, '新回合首条 step 的序号必须与 trigger 一致')
  wf('agent/pre-step', { agent: MAIN, turn: 31, step: 2, messages: [] })
  assert.equal(steps()[steps().length - 1].windowSeq, t.windowSeq, '同回合延续步骤沿用本回合序号')
  assert.equal(steps()[steps().length - 1].msgs, 0)
})

// ── 组合信号（S1 todo / S4 cwd / S2 卡）· Human 2026-10-10 批准 ─────────────

check('S22 S1 todo 计划：keywords 保留核心差异 · overlap/changed 机械可算', () => {
  wf('agent/pre-step', { agent: MAIN, turn: 41, step: 1, messages: [userMsg('开始处理这一块，先看清当前结构再动手')] })
  wf('tools/pre-execute', {
    agent: MAIN, callId: 't-1', name: 'todo_write',
    arguments: { todos: [
      { content: '编写 RLS 迁移并测试访问隔离', status: 'pending' },
      { content: '补齐策略回归用例', status: 'pending' },
    ] }, signal: {},
  })
  const plans = records().filter(r => r.ev === 'todo-plan')
  assert.equal(plans.length, 1)
  const p1 = plans[0]
  assert.equal(p1.count, 2)
  assert.equal(p1.overlapPrev, null, '首次快照无前值')
  assert.equal(p1.changed, false)
  assert.equal(p1.wholeListReplacement, true, '整体替换语义须显式标注')
  assert.ok(p1.keywords.includes('rls'), '关键词须保留 RLS 这一区分性词')
  assert.ok(p1.keywords.some(k => k.indexOf('迁移') >= 0), '须保留"迁移"')
  assert.ok(!JSON.stringify(p1).includes('编写 RLS 迁移并测试访问隔离'), '不得出现 todo 全文')

  wf('tools/pre-execute', {
    agent: MAIN, callId: 't-2', name: 'todo_write',
    arguments: { todos: [{ content: '重构 Hook 适配器并测试事件时序', status: 'in_progress' }] }, signal: {},
  })
  const p2 = records().filter(r => r.ev === 'todo-plan')[1]
  assert.equal(typeof p2.overlapPrev, 'number')
  assert.ok(p2.overlapPrev < 1, '方向不同 ⇒ 重叠度 < 1')
  assert.equal(p2.changed, true, '跨过 CHANGED 阈值 ⇒ 判"变了"')
  assert.ok(p2.keywords.includes('hook'), '新方向关键词须出现 hook（区分性保留）')
})

check('S23 短任务可能没有 todo ⇒ 不得因此判定"没有任务"（S1 非必需）', () => {
  const before = triggers().length
  wf('agent/pre-step', { agent: MAIN, turn: 42, step: 1, messages: [userMsg('把那个迁移文件里的策略补一条，然后跑一次验证')] })
  const t = lastTrigger()
  assert.equal(triggers().length, before + 1)
  assert.equal(t.signals.semantic, false, '本回合无 todo ⇒ semantic=false')
  assert.equal(t.discovery, 'waiting', '判定**照常**进行 —— 不因缺 S1 而放弃机会')
})

check('S24 S4 cwd：换工作目录 ⇒ 记 cwd-obs，step 带 cwdTop/cwdChanged', () => {
  const OTHER = agent('selftest-cwd', { delegationDepth: 0, cwd: 'D:/work/demo-app' })
  emit1('agent/session-start', { agent: OTHER, source: 'startup' })
  wf('agent/pre-step', { agent: OTHER, turn: 1, step: 1, messages: [userMsg('继续把迁移做完')] })
  const st = steps()[steps().length - 1]
  assert.equal(st.cwdTop, 'demo-app', 'S4 只记末段目录名')
  assert.equal(typeof st.cwdChanged, 'boolean')
})

check('S25 S2 卡：焦点不唯一 ⇒ 正确降级为未知（cardMapped=false · 关键词 null）', () => {
  const S25 = agent('selftest-s25', { delegationDepth: 0 })
  emit1('agent/session-start', { agent: S25, source: 'startup' })
  writeFileSync(C1, cardFull('TASK-20260101-001', 'Executing', 'S2', 'selftest goal one', 'do one'))
  writeFileSync(C2, cardFull('TASK-20260101-002', 'Executing', 'W1', 'selftest goal two', 'do two'))
  wf('agent/pre-step', { agent: S25, turn: 1, step: 1, messages: [userMsg('同时推进两件事，先看清整体再说')] })
  wf('agent/pre-step', { agent: S25, turn: 2, step: 1, messages: [userMsg('继续处理这两个方向的内容，别丢')] })
  const t = lastTrigger()
  assert.equal(t.signals.cardMapped, false, '多张 Executing ⇒ 不得猜卡')
  assert.equal(t.cardGoalKeywords, null, '不可关联 ⇒ 必须降级为未知')
  assert.equal(t.cardGoalLen, null)
})

check('S26 记录口径：含派生关键词 · 但不含 todo / 卡 原文', () => {
  const blob = JSON.stringify(records())
  assert.ok(!blob.includes('编写 RLS 迁移并测试访问隔离'), 'todo 原文不得落盘')
  assert.ok(!blob.includes('重构 Hook 适配器并测试事件时序'), 'todo 原文不得落盘')
  assert.ok(!blob.includes('selftest goal one'), '卡 Goal 原文不得入档（结论入档 · 原文不入档）')
  assert.ok(blob.includes('rls') || blob.toLowerCase().includes('"rls"'), '但区分性关键词必须留下')
})

// ── Step A′（WorkContext 六段 + 推理流结构观察）· Human 2026-10-10 裁定 ─────────
//    依据 `p0/HANDOFF §二十六`（裁定）与 `§二十七`（新判据草案）。

const emit2 = (ev, a, b) => {
  const h = (handlers.get(ev) || [])[0]
  assert.ok(h, 'handler missing: ' + ev)
  return h(a, b)
}
const wcFills = () => records().filter(r => r.ev === 'wc-fill')
const reasoningObs = () => records().filter(r => r.ev === 'reasoning-obs')
const streamPaths = () => records().filter(r => r.ev === 'stream-path')

check('S27 WorkContext：意图段进内存 · 探针只落长度 · understanding 恒 null', () => {
  const secretIntent = '把 RLS 迁移的访问隔离策略补完并验证'
  wf('agent/pre-step', { agent: MAIN, turn: 61, step: 1, messages: [userMsg(secretIntent)] })
  const f = wcFills()
  assert.ok(f.length >= 1, 'wc-fill 必须产出')
  const last = f[f.length - 1]
  assert.ok(last.intentLen > 0, 'intentLen 必须 > 0（§二十七 W2）')
  assert.equal(last.understanding, null, '无 LLM ⇒ understanding 必须诚实为 null（不伪装理解）')
  assert.equal(typeof last.segFilled, 'number')
  assert.ok(last.segFilled >= 1, '六段填充计数须可见')
  assert.equal(last.obs, OBS_EXPECT)
  assert.ok(!JSON.stringify(last).includes(secretIntent), '意图正文不得落盘')
})

check('S28 主路径：已提交 assistant/message 的紧凑流 ⇒ 只解析结构量（块数/字符数/Σdt/来源/provider）', () => {
  const SESS_OBJ = { header: { id: SESS } }
  const r1 = '先看 RLS 策略定义'
  const r2 = '，再决定是否改迁移'
  const stream = [
    { type: 'reasoning-chunks', time0: 1000, index: 0, dt: [5, 7], texts: [r1, r2] },
    { type: 'tool-call-chunks', time0: 1012, index: 1, dt: [], id: 'c1', name: 'read', args: ['{"file_path":"x.sql"}'] },
    { type: 'chunk', time: 1100, chunk: { type: 'finish', reason: { kind: 'stop' } } },
  ]
  emit2('session/event', SESS_OBJ, {
    type: 'assistant/message', seq: 42,
    data: { turn: 61, step: 2, message: { source: { provider: 'deepseek', model: 'deepseek-reasoner' } }, stream },
  })
  const o = reasoningObs()
  assert.equal(o.length, 1)
  const x = o[0]
  assert.equal(x.path, 'session-event', '必须走已提交的主路径')
  assert.equal(x.settlement, 'message')
  assert.equal(x.turn, 61)
  assert.equal(x.step, 2)
  assert.equal(x.provider, 'deepseek')
  assert.equal(x.model, 'deepseek-reasoner')
  assert.equal(x.streamLen, 3)
  assert.equal(x.reasoningBlocks, 1)
  assert.equal(x.reasoningChars, r1.length + r2.length, '只累加长度')
  assert.equal(x.reasoningMs, 12, 'Σdt = 5 + 7')
  assert.equal(x.msBasis, 'sum-dt')
  assert.ok(x.streamShape.includes('reasoning-chunks'), '形态签名须可见（实测编码形态）')
  assert.ok(!JSON.stringify(x).includes(r1), '推理文本不得落盘')
  assert.ok(streamPaths().some(p => p.source === 'session-event'), 'stream-path 必须报告走通的路')
})

check('S29 失败/重试/取消走 assistant/attempt ⇒ 与成功提交分开计数（interrupted 单列）', () => {
  const SESS_OBJ = { header: { id: SESS } }
  emit2('session/event', SESS_OBJ, {
    type: 'assistant/attempt', seq: 43,
    data: { turn: 61, step: 3, stream: [{ type: 'reasoning-chunks', time0: 1, index: 0, dt: [3], texts: ['排查失败原因'] }] },
  })
  emit2('session/event', SESS_OBJ, {
    type: 'assistant/message', seq: 44,
    data: { turn: 62, step: 1, interrupted: true, message: { source: { provider: 'deepseek', model: 'deepseek-chat' } }, stream: [] },
  })
  const o = reasoningObs()
  assert.equal(o[o.length - 2].settlement, 'attempt', '失败/重试/取消必须与成功提交区分')
  assert.equal(o[o.length - 1].settlement, 'message')
  assert.equal(o[o.length - 1].interrupted, true)
  assert.equal(o[o.length - 2].reasoningMs, 3)
})

check('S30 后备路径：assistant-stream 的 reasoning-delta ⇒ 只累计长度并报告后备路在用', () => {
  wf('agent/pre-step', { agent: MAIN, turn: 63, step: 1, messages: [userMsg('先看一眼当前结构，再决定怎么改')] })
  emit1('agent/assistant-stream', { agent: MAIN, frame: { type: 'chunk', chunk: { type: 'reasoning-delta', index: 0, text: '后备路径推理片段' } } })
  wf('agent/pre-step', { agent: MAIN, turn: 64, step: 1, messages: [userMsg('继续看结构，别急着动手改动')] })
  const f = wcFills()
  const last = f[f.length - 1]
  assert.ok(last.reasoningLiveChunks >= 1, '后备路径计数必须可见')
  assert.ok(streamPaths().some(p => p.source === 'assistant-stream'), '必须报告后备路在用')
  assert.ok(!JSON.stringify(records()).includes('后备路径推理片段'), '推理文本不得落盘')
})

check('S31 子会话 session/event ⇒ fail-closed（不写推理观察行）', () => {
  const before = reasoningObs().length
  emit2('session/event', { header: { id: SUB } }, {
    type: 'assistant/attempt', seq: 1,
    data: { turn: 1, step: 1, stream: [{ type: 'reasoning-chunks', time0: 1, index: 0, dt: [1], texts: ['子会话推理'] }] },
  })
  assert.equal(reasoningObs().length, before, '子会话不得产生推理观察行')
})

check('S32 活动段/进度段：只记机械事实（工具类别+目录+ok），不含参数原文 · 进度不标语义阶段', () => {
  wf('tools/pre-execute', { agent: MAIN, callId: 'w-1', name: 'edit_file', arguments: { file_path: ROOT + '/runtime/aios-activation.ts' }, signal: {} })
  const h = handlers.get('tools/post-execute')[0]
  h({ agent: MAIN, callId: 'w-1', name: 'edit_file' }, { isError: false }, () => 'R')
  wf('agent/pre-step', { agent: MAIN, turn: 65, step: 1, messages: [userMsg('继续完善这一段实现并补上回归用例')] })
  const f = wcFills()
  const last = f[f.length - 1]
  assert.ok(last.activityLen >= 1, '活动段必须被填充')
  assert.ok(last.activityTools.some(t => String(t).indexOf('edit') === 0), '只记工具类别 + 目录类别')
  assert.ok(Array.isArray(last.progressSignals), '进度段只给机械信号')
  assert.ok(!JSON.stringify(last).includes('aios-activation.ts'), '文件名不得落盘')
  assert.ok(!('stage' in last), '不得输出"调试阶段"之类语义结论字段')
})

check('S33 v7：回合末补记 wc-fill（phase=turn-end）· 与 turn-start 配对（上下文逐步充实）', () => {
  const before = wcFills().length
  wf('agent/pre-step', { agent: MAIN, turn: 71, step: 1, messages: [userMsg('再补一轮验证，把这一段实现收口')] })
  emit1('agent/turn-stopping', { agent: MAIN, turn: 71 })
  const f = wcFills()
  assert.equal(f.length, before + 2, '一个回合应产出 turn-start + turn-end 两份')
  const start = f[f.length - 2]
  const end = f[f.length - 1]
  assert.equal(start.phase, 'turn-start')
  assert.equal(end.phase, 'turn-end')
  assert.equal(start.windowSeq, end.windowSeq, '两份必须属于同一回合')
  assert.ok(end.segFilled >= start.segFilled, '回合内填充不得减少（上下文只应逐步充实）')
  assert.equal(end.understanding, null, '回合末同样不得伪装理解结果')
})

check('S34 v7：wc-fill 带 reasoningLiveChars（后备路径字符数 ⇒ 与主路径 reasoningChars 交叉核对）', () => {
  const f = wcFills()
  const last = f[f.length - 1]
  assert.equal(typeof last.reasoningLiveChars, 'number', '后备路径字符数必须可读')
  assert.equal(typeof last.reasoningLiveChunks, 'number')
  assert.equal(typeof last.reasoningChars, 'number', '主路径字符数同样可读（两者可对照）')
})

// ── Step B′ 最小递送验证（Human 2026-10-10 批准 · 一次性静态标记）──────────────
//    🔴 回归护栏：**默认关闭必须逐字透明**；开启后**不改原结果**、只在 `accept` 上附加

const writeProbe = (o) => writeFileSync(DELIVERY_PROBE, JSON.stringify(o))
const clearProbe = () => { try { rmSync(DELIVERY_PROBE, { force: true }) } catch { /* 静默 */ } }
const deliveryRecs = () => records().filter(r => r.ev === 'delivery-probe')
const postExec = async (agent, decision) => {
  const h = handlers.get('tools/post-execute')[0]
  let calls = 0
  const ret = await h({ agent, callId: 'dp-1', name: 'read_file' }, { isError: false }, () => { calls++; return Promise.resolve(decision) })
  return { calls, ret }
}

checkAsync('S35 递送验证默认关闭（开关文件缺失）⇒ 与旧版**逐字一致**（同一对象引用）', async () => {
  clearProbe()
  const downstream = { kind: 'accept', content: [{ type: 'text', text: 'ORIGINAL' }] }
  const r = await postExec(MAIN, downstream)
  assert.equal(r.calls, 1, 'next() 恰好一次')
  assert.equal(r.ret, downstream, '必须**原样**返回下游 decision（同一引用 ⇒ 零行为变化）')
  assert.ok(!('additionalContexts' in r.ret), '关闭时不得附加任何上下文')
})

checkAsync('S36 开关开启但会话不匹配 ⇒ 仍完全透明', async () => {
  writeProbe({ enabled: true, session: 'someone-else', marker: 'MARKER-X', maxPerSession: 1 })
  const downstream = { kind: 'accept' }
  const r = await postExec(MAIN, downstream)
  assert.equal(r.ret, downstream, '会话不匹配不得附加')
  clearProbe()
})

checkAsync('S37 开关命中 ⇒ 附加固定标记 · 原结果不变 · UserMessage 形状合法', async () => {
  writeProbe({ enabled: true, session: SESS, marker: 'AIOS-DELIVERY-MARKER-001', maxPerSession: 1 })
  const before = deliveryRecs().length
  const downstream = { kind: 'accept', content: [{ type: 'text', text: 'ORIGINAL-CONTENT' }] }
  const r = await postExec(MAIN, downstream)
  const d = r.ret
  assert.equal(r.calls, 1)
  assert.equal(d.kind, 'accept', 'kind 不得改变')
  assert.deepEqual(d.content, downstream.content, '🔴 工具原始结果（content）必须不变')
  assert.equal(d.additionalContexts.length, 1)
  const m = d.additionalContexts[0]
  assert.equal(m.role, 'user')
  assert.ok(/^[0-9a-f-]{36}$/.test(String(m.id)), 'id 必须是 uuid 形状（等价 createUserMessage）')
  assert.equal(m.source.kind, 'plugin')
  assert.equal(m.source.plugin, 'aios-activation')
  assert.equal(m.source.form, 'notice')
  assert.equal(typeof m.source.summary, 'string')
  assert.equal(m.content[0].type, 'text')
  assert.equal(m.content[0].text, 'AIOS-DELIVERY-MARKER-001', '必须是那段固定标记')
  assert.equal(deliveryRecs().length, before + 1, '必须留下一条投递记录')
  clearProbe()
})

checkAsync('S38 block 情形 ⇒ 不改 block 语义（原样透传 · 不附加）', async () => {
  writeProbe({ enabled: true, session: SESS, marker: 'MARKER-BLOCK', maxPerSession: 5 })
  const downstream = { kind: 'block', feedback: [{ type: 'text', text: 'no' }] }
  const r = await postExec(MAIN, downstream)
  assert.equal(r.ret, downstream, 'block 必须原样透传（不改变工具结果语义）')
  clearProbe()
})

checkAsync('S39 一次性：同一 marker 用尽后不再附加（不同 marker 互不干扰）', async () => {
  writeProbe({ enabled: true, session: SESS, marker: 'MARKER-ONCE', maxPerSession: 1 })
  const before = deliveryRecs().length
  const a = await postExec(MAIN, { kind: 'accept' })
  const b = await postExec(MAIN, { kind: 'accept' })
  assert.equal(a.ret.additionalContexts.length, 1, '第一次应附加')
  assert.ok(!('additionalContexts' in b.ret), '第二次不得再附加（一次性）')
  clearProbe()
  assert.equal(deliveryRecs().length, before + 1, '记录数 = 实际附加次数（第二次不留记录）')
})

// ── 阶段 2「内容读取」（Human 2026-10-10 批准实施 · 设计见 STAGE2-REASONING-READ-DESIGN.md）──
//    🔴 机械验证 R1–R6；哨兵串证明**不落原文**；反例断言证明 **turn-stopping 不释放**

const SENTINEL = 'SENTINEL-REASONING-TEXT-MUST-NOT-LEAK-001'
const reasoningTexts = () => records().filter(r => r.ev === 'reasoning-text')
const attemptPairs = () => records().filter(r => r.ev === 'attempt-pair')
const releases = () => records().filter(r => r.ev === 'reasoning-release')
const turnStopObs = () => records().filter(r => r.ev === 'turn-stopping-obs')
const provisionalObs = () => records().filter(r => r.ev === 'provisional-obs')
const evicted = () => records().filter(r => r.ev === 'reasoning-evicted')
let SEQ = 9000
const nextSeq = () => ++SEQ
const sessObj = () => ({ header: { id: SESS } })
const startFrame = (turn, step, attemptId, revision) =>
  emit1('agent/assistant-stream', { agent: MAIN, frame: { type: 'start', attemptId, revision, turn, step } })
const settlement = (turn, step, texts, opts = {}) =>
  emit2('session/event', sessObj(), {
    type: opts.type || 'assistant/message',
    seq: opts.seq === undefined ? nextSeq() : opts.seq,
    data: Object.assign({
      turn,
      step,
      message: { source: { provider: 'selftest-provider', model: 'selftest-model' } },
      stream: texts === null ? [] : [{ type: 'reasoning-chunks', time0: 1, index: 0, dt: [7, 5], texts }],
    }, opts.data || {}),
  })
const turnEnd = (turn, kind = 'completed') =>
  emit2('session/event', sessObj(), { type: 'turn/end', seq: nextSeq(), data: { turn, reason: { kind } } })
const turnStopping = (turn) => emit1('agent/turn-stopping', { agent: MAIN, turn })

check('S40 阶段2 R1/R2：已提交 message 的推理文本进内存 · 探针只落派生量', () => {
  const before = reasoningTexts().length
  startFrame(901, 1, 'attempt-A', 3)
  settlement(901, 1, [SENTINEL])
  const list = reasoningTexts()
  assert.equal(list.length, before + 1, '应建立一条 reasoning-text 记录')
  const rec = list[list.length - 1]
  assert.equal(rec.turn, 901, 'R2：turn 归属')
  assert.equal(rec.step, 1, 'R2：step 归属')
  assert.equal(rec.chars, SENTINEL.length, 'R1：字符数 = 实际文本长度')
  assert.equal(rec.blocks, 1)
  assert.equal(rec.provider, 'selftest-provider')
  assert.equal(rec.confidence, 'assumption', '证据性质：假设级')
  assert.ok(!JSON.stringify(rec).includes('SENTINEL-REASONING'), '🔴 探针记录不得含推理原文')
})

check('S42 阶段2 归属 · 队列唯一 ⇒ fifo-unique（带 attemptId / revision）', () => {
  const before = attemptPairs().length
  startFrame(902, 1, 'attempt-B', 9)
  settlement(902, 1, ['归属测试文本'])
  const p = attemptPairs()
  assert.equal(p.length, before + 1)
  const rec = p[p.length - 1]
  assert.equal(rec.attribution, 'fifo-unique', '队列恰好 1 条 ⇒ 唯一性可保证')
  assert.equal(rec.unavailableReason, null)
  assert.equal(rec.pendingDepth, 1)
  const t = reasoningTexts()[reasoningTexts().length - 1]
  assert.equal(t.revision, 9, 'revision 由 start 帧补订')
})

check('S43 阶段2 归属 · 队列歧义（同 step 两次 start）⇒ unavailable/ambiguous-queue（不猜）', () => {
  startFrame(903, 1, 'attempt-C1', 1)
  startFrame(903, 1, 'attempt-C2', 2)
  settlement(903, 1, ['歧义测试'])
  const rec = attemptPairs()[attemptPairs().length - 1]
  assert.equal(rec.attribution, 'unavailable')
  assert.equal(rec.unavailableReason, 'ambiguous-queue', '🔴 不靠"顺序看起来一致"去猜')
  assert.equal(rec.pendingDepth, 2)
})

check('S44 阶段2 归属 · 无 start 帧 ⇒ unavailable/no-start-seen（原因可区分）', () => {
  settlement(904, 1, ['无 start 测试'])
  const rec = attemptPairs()[attemptPairs().length - 1]
  assert.equal(rec.attribution, 'unavailable')
  assert.equal(rec.unavailableReason, 'no-start-seen', 'R7b：失败原因必须可区分')
})

check('S45 阶段2 · assistant/attempt（provisional）⇒ 只计数 · 不留存文本', () => {
  const beforeTexts = reasoningTexts().length
  const beforeProv = provisionalObs().length
  settlement(905, 1, [SENTINEL + '-PROVISIONAL'], { type: 'assistant/attempt' })
  assert.equal(reasoningTexts().length, beforeTexts, '🔴 不得为 provisional 建 entry')
  const p = provisionalObs()
  assert.equal(p.length, beforeProv + 1, '只记计数')
  assert.ok(p[p.length - 1].chars > 0)
  assert.ok(!JSON.stringify(p[p.length - 1]).includes('SENTINEL'), '计数记录不得含文本')
})

check('S46 阶段2 去重 · 同一 seq 重复投递 ⇒ 只建一次', () => {
  const seq = nextSeq()
  startFrame(906, 1, 'attempt-D', 1)
  settlement(906, 1, ['去重测试'], { seq })
  const after1 = reasoningTexts().length
  settlement(906, 1, ['去重测试'], { seq }) // 同 seq 再投
  assert.equal(reasoningTexts().length, after1, '🔴 重复事件不得重复建 entry')
})

check('S47 阶段2 上限 · 超 32k ⇒ **整条**淘汰并只记数量（不截断）· 3.1 起带 policy', () => {
  const beforeEvict = evicted().filter(r => r.evictedEntries === 1).length
  const bigOf = (n) => ('blk47-' + n + '-').padEnd(12_000, ['q', 'r', 's'][n])
  for (let i = 0; i < 3; i++) {
    startFrame(907, i + 1, 'attempt-E' + i, 1)
    settlement(907, i + 1, [bigOf(i)])
  }
  const es = evicted().filter(r => r.evictedEntries === 1)
  assert.ok(es.length > beforeEvict, '超限必须触发淘汰记录')
  const last = es[es.length - 1]
  assert.equal(last.evictedEntries, 1, '整条淘汰（不是截断半条）')
  assert.ok(last.evictedChars >= 12_000, '淘汰量为整条字符数')
  assert.ok(['P2-duplicate', 'P3-unsheltered', 'P3-over-P1', 'P3-over-P0'].includes(last.policy), '3.1 起必须带 policy')
  assert.ok(['L1', 'L2', 'L3', 'L4'].includes(last.tier), 'v11 起必须带降级层级 tier')
  assert.equal(last.reason, 'memory-budget', '🔴 必须是**预算约束**，不是语义判断')
})

check('S41 生命周期：turn-stopping **不释放** · turn/end **才释放**（R3 双向断言）', () => {
  startFrame(908, 1, 'attempt-F', 1)
  settlement(908, 1, ['生命周期测试文本'])
  const beforeStop = turnStopObs().length
  turnStopping(908)
  const so = turnStopObs()
  assert.equal(so.length, beforeStop + 1, 'turn-stopping 必须留观测')
  assert.ok(so[so.length - 1].retainedEntries >= 1, '🔴 turn-stopping 时材料**仍在**（不得提前清除）')
  assert.equal(releases().filter(r => r.turn === 908).length, 0, '🔴 turn-stopping 不得释放')

  turnEnd(908)
  const rel = releases().filter(r => r.turn === 908)
  assert.equal(rel.length, 1, 'turn/end 必须触发释放')
  assert.equal(rel[0].releasedEntries, 1)
  assert.equal(rel[0].reasonKind, 'completed', '按 turn/end.reason 分类记录')
})

check('S48 阶段2 R5 隐私：全部记录不含任何推理原文（哨兵串机械扫描）', () => {
  const blob = JSON.stringify(records())
  assert.ok(!blob.includes(SENTINEL), '🔴 推理原文不得出现在任何探针记录里')
})

check('S49 阶段2 R4 不参与：判定类记录不得承载推理文本字段', () => {
  const judgementBlob = JSON.stringify(judgement())
  for (const f of ['reasoningEntries', 'reasoningText', '"text"']) {
    assert.ok(!judgementBlob.includes(f), '🔴 判定记录不得承载推理文本字段：' + f)
  }
})

// ── 阶段三 3.1 保留策略第一版（Human 2026-10-10 裁定 `§28.13` · 设计 `STAGE3-DISCOVERY-AB-DESIGN.md §3`）──
//    🔴 淘汰对象 = 「**预算约束下的淘汰对象**」，**不是**"已确认无价值的内容"
//    🔴 机制必须可机械断言：P0 端点 / P1 转折点 / P2 只处理**可证明的重复** / P3 兜底 / R8 / R9

const sleep = (ms) => new Promise(r => setTimeout(r, ms))
/** 释放此前用例留下的全部回合 ⇒ 每个新用例自带干净的预算状态。 */
function drainTurns() {
  // 覆盖前段用例（turn 1–77）与阶段 2/3.1 用例（turn 901+）两段
  for (let t = 0; t <= 100; t++) turnEnd(t)
  for (let t = 900; t <= 999; t++) turnEnd(t)
}
/** 造一段"大且彼此不重复"的文本（防误触 P2）。 */
const bigText = (tag, fill, n = 12_000) => ('blk-' + tag + '-').padEnd(n, fill)

check('S50 3.1 P0：超预算时**端点（首条 + 最新）永不淘汰** · 淘汰对象带 policy', () => {
  drainTurns()
  const q1 = nextSeq()
  const q2 = nextSeq()
  const q3 = nextSeq()
  startFrame(950, 1, 'a1', 1); settlement(950, 1, [bigText('s50-1', 'q')], { seq: q1 })
  startFrame(950, 2, 'a2', 1); settlement(950, 2, [bigText('s50-2', 'r')], { seq: q2 })
  startFrame(950, 3, 'a3', 1); settlement(950, 3, [bigText('s50-3', 's')], { seq: q3 })
  const es = evicted().filter(r => r.turn === 950 && r.evictedEntries === 1)
  assert.ok(es.length >= 1, '3×12k > 32k ⇒ 必须发生淘汰')
  const seqs = es.map(r => r.seqRange[0])
  assert.ok(!seqs.includes(q1), '🔴 P0：该回合**首条永不淘汰**')
  assert.ok(!seqs.includes(q3), '🔴 P0：该回合**最新一条永不淘汰**')
  assert.ok(seqs.includes(q2), '中间那条才是「预算约束下的淘汰对象」')
  assert.ok(es.every(r => r.reason === 'memory-budget' && r.policy !== 'none'), '每条淘汰必须带 policy + reason')
  assert.ok(es.every(r => r.evictedEntries === 1), '整条淘汰（非截断）')
})

checkAsync('S51 3.1 P1：转折点**之前时间最近**的一条受保护（只能按时间关联）', async () => {
  drainTurns()
  clearProbe()
  const qA = nextSeq(), qB = nextSeq(), qC = nextSeq()
  startFrame(951, 1, 'b1', 1); settlement(951, 1, ['A-' + 'a'.repeat(180)], { seq: qA })
  await sleep(5)
  startFrame(951, 2, 'b2', 1); settlement(951, 2, ['B-' + 'b'.repeat(180)], { seq: qB })
  await sleep(5)
  // P1 第 ③ 类转折点：**执行报错**（工具事件载荷无 turn ⇒ 靠回合游标归属）
  const postErr = handlers.get('tools/post-execute')[0]
  await postErr({ agent: MAIN, callId: 'err-1', name: 'read_file' }, { isError: true }, () => Promise.resolve({ kind: 'accept' }))
  await sleep(5)
  startFrame(951, 3, 'b3', 1); settlement(951, 3, [bigText('s51-3', 'q')], { seq: qC })
  startFrame(951, 4, 'b4', 1); settlement(951, 4, [bigText('s51-4', 'r')])
  startFrame(951, 5, 'b5', 1); settlement(951, 5, [bigText('s51-5', 's')])
  const es = evicted().filter(r => r.turn === 951 && r.evictedEntries === 1)
  assert.ok(es.length >= 1, '应发生淘汰')
  const seqs = es.map(r => r.seqRange[0])
  assert.ok(!seqs.includes(qB), '🔴 P1：转折点之前最近的一条（B）必须受保护')
  assert.ok(!seqs.includes(qA), 'P0：首条受保护')
  assert.ok(seqs.includes(qC), '淘汰落在**无保护的中间记录**上（C）')
  assert.ok(es.some(r => r.protectedByP1 >= 1), '必须如实记录 P1 保护计数（派生量）')
})

check('S52 3.1 P2：**完全相等** ⇒ 优先淘汰**较新**的一条（同组保留较早）', () => {
  drainTurns()
  const T = 'DUP-' + 'x'.repeat(300)
  const q1 = nextSeq(), q2 = nextSeq(), q3 = nextSeq(), q4 = nextSeq()
  startFrame(952, 1, 'c1', 1); settlement(952, 1, [T], { seq: q1 })
  startFrame(952, 2, 'c2', 1); settlement(952, 2, [bigText('s52-2', 'r', 20_000)], { seq: q2 })
  startFrame(952, 3, 'c3', 1); settlement(952, 3, [T], { seq: q3 }) // 同一文本再次出现
  startFrame(952, 4, 'c4', 1); settlement(952, 4, [bigText('s52-4', 't', 20_000)], { seq: q4 })
  const es = evicted().filter(r => r.turn === 952 && r.evictedEntries === 1)
  assert.ok(es.length >= 1, '40k+ ⇒ 应发生淘汰')
  const pick = es.find(r => r.policy === 'P2-duplicate')
  assert.ok(pick, '🔴 完全相等的重复必须走 P2（最先淘汰）')
  assert.equal(pick.seqRange[0], q3, '淘汰的是**较新**的那条（同组保留较早的 ' + q1 + '）')
  assert.equal(pick.dupExact, true, '必须区分"完全相等"与"相似度命中"')
})

check('S53 3.1 P2 对照：**相似但不可证明重复**（Jaccard < 0.9）⇒ **不得**被 P2 淘汰', () => {
  drainTurns()
  const X = 'ab'.repeat(100) // bigram 集合 = {ab, ba}
  const Y = 'ab'.repeat(50) + 'z'.repeat(100) // 交集 2 / 并集 4 ⇒ ≈0.5 < 0.9
  const q1 = nextSeq(), q2 = nextSeq(), q3 = nextSeq(), q4 = nextSeq()
  startFrame(953, 1, 'd1', 1); settlement(953, 1, [X], { seq: q1 })
  startFrame(953, 2, 'd2', 1); settlement(953, 2, [Y], { seq: q2 })
  startFrame(953, 3, 'd3', 1); settlement(953, 3, [bigText('s53-3', 'r', 20_000)], { seq: q3 })
  startFrame(953, 4, 'd4', 1); settlement(953, 4, [bigText('s53-4', 't', 20_000)], { seq: q4 })
  const es = evicted().filter(r => r.turn === 953 && r.evictedEntries === 1)
  assert.ok(es.length >= 1, '应发生淘汰')
  assert.ok(!es.some(r => r.policy === 'P2-duplicate'), '🔴 相似 ≠ 语义等价 ⇒ P2 不得命中')
  const fallback = es.find(r => r.policy === 'P3-unsheltered')
  assert.ok(fallback, '应回退到 P3 兜底（v11 的 L2：无保护中间记录）')
  assert.equal(fallback.seqRange[0], q2, 'P3 兜底取 `seq` 最小者（确定性顺序 · **不主张**它不重要）')
  assert.equal(fallback.tier, 'L2')
  assert.equal(fallback.dupSim, false)
})

check('S54 3.1 **端点也受硬预算约束** ⇒ 降级到 L4 淘汰"最新一条"（的 `evictBlocked` 已取消）', () => {
  drainTurns()
  const q1 = nextSeq(), q2 = nextSeq()
  startFrame(954, 1, 'e1', 1); settlement(954, 1, [bigText('s54-1', 'q', 20_000)], { seq: q1 })
  startFrame(954, 2, 'e2', 1); settlement(954, 2, [bigText('s54-2', 'r', 20_000)], { seq: q2 })
  const recs = evicted().filter(r => r.turn === 954 && r.evictedEntries === 1)
  assert.equal(recs.length, 1, '🔴 40k > 32k ⇒ **必须淘汰**（不得停在"全保护"⇒ 这正是被裁定的缺陷）')
  const last = recs[recs.length - 1]
  assert.equal(last.policy, 'P3-over-P0', '降级到最后一层（P0 不是豁免权）')
  assert.equal(last.tier, 'L4')
  assert.equal(last.seqRange[0], q2, '🔴 层内先淘汰**最新**一条（首条的初始方向不可再生）')
  assert.equal(last.retainedEntries, 1, '收敛：只剩首条')
  assert.ok(last.retainedChars <= 32_000, '🔴 R11：预算**硬收敛**')
})

check('S55 3.1 R8：淘汰后 `historyCoverage=partial` · 释放后按剩余回合重算', () => {
  drainTurns()
  const a = nextSeq(), b = nextSeq(), c = nextSeq()
  startFrame(956, 1, 'g1', 1); settlement(956, 1, [bigText('s55-1', 'q')], { seq: a })
  startFrame(956, 2, 'g2', 1); settlement(956, 2, [bigText('s55-2', 'r')], { seq: b })
  startFrame(956, 3, 'g3', 1); settlement(956, 3, [bigText('s55-3', 's')], { seq: c })
  assert.ok(evicted().some(r => r.turn === 956 && r.evictedEntries === 1), '先造出一次淘汰')
  turnStopping(956)
  const lastStop = turnStopObs()[turnStopObs().length - 1]
  assert.equal(lastStop.historyCoverage, 'partial', '🔴 R8：历史不完整必须可见')
  assert.ok(Array.isArray(lastStop.evictedSeqRanges) && lastStop.evictedSeqRanges.length > 0, '缺口区间可落盘（无原文）')
  assert.equal(lastStop.retentionPolicy, 'endpoints+strong-tp+dedup/hard-budget')
  turnEnd(956)
  const rel = releases().filter(r => r.turn === 956).pop()
  assert.equal(rel.coverageBefore, 'partial', '释放前如实记缺口状态')
  drainTurns()
  const tail = releases()[releases().length - 1]
  assert.equal(tail.coverageAfter, 'complete', '🔴 全部释放后按剩余回合重算 ⇒ 回到 complete')
  assert.equal(tail.evictedTurnsRemaining, 0)
})

check('S56 3.1 R8 账目：淘汰区间**两两不相邻**且覆盖全部被淘汰 seq', () => {
  drainTurns()
  const q1 = nextSeq(), q2 = nextSeq(), q3 = nextSeq(), q4 = nextSeq(), q5 = nextSeq()
  for (let i = 1; i <= 5; i++) {
    startFrame(955, i, 'f' + i, 1)
    settlement(955, i, [bigText('s56-' + i, 'qrstu'[i - 1], 9_000)], { seq: [q1, q2, q3, q4, q5][i - 1] })
  }
  const es = evicted().filter(r => r.turn === 955 && r.evictedEntries === 1)
  assert.ok(es.length >= 1, '45k > 32k ⇒ 必须淘汰')
  const evictedSeqs = es.map(r => r.seqRange[0]).sort((a, b) => a - b)
  // 释放前先读回合末的缺口元数据（= R8 的可复核依据）
  turnStopping(955)
  const stopRec = records().filter(r => r.ev === 'turn-stopping-obs' && r.turn === 955).pop()
  assert.ok(stopRec, 'turn-stopping 必须留观测')
  const rs = stopRec.evictedSeqRanges
  for (let i = 1; i < rs.length; i++) assert.ok(rs[i][0] > rs[i - 1][1] + 1, '区间必须两两不相邻')
  for (const sq of evictedSeqs) {
    assert.ok(rs.some(([a, b]) => a <= sq && sq <= b), '🔴 区间必须覆盖被淘汰 seq ' + sq)
  }
  turnEnd(955)
  const rel = releases().filter(r => r.turn === 955).pop()
  assert.equal(rel.coverageBefore, 'partial', '释放前必须如实记"历史不完整"')
  assert.ok(evictedSeqs.length >= 1, '至少一条「预算约束下的淘汰对象」')
})

check('S57 3.1 R5′/R4′：保留策略新增记录**仍不含原文** · 判定记录不含内部字段', () => {
  const blob = JSON.stringify(records())
  assert.ok(!blob.includes(SENTINEL), '🔴 淘汰 / 释放 / 缺口记录不得携带推理原文')
  const evBlob = JSON.stringify(evicted())
  for (const f of ['"text"', 'normalizedText', 'bigramsOf', 'reasoningEntries']) {
    assert.ok(!evBlob.includes(f), '淘汰记录不得承载文本字段：' + f)
  }
  const judgementBlob = JSON.stringify(judgement())
  assert.ok(!judgementBlob.includes('turningPoints'), '🔴 判定记录不得承载保留策略内部状态')
})

check('S58 3.1 护栏：转折点**派生索引**超上限 ⇒ 丢最旧并**如实计数**（推理条目不受影响）', () => {
  drainTurns()
  // 交替"有 path / 无 path" ⇒ 每次都构成一次「工具操作对象变化」
  for (let i = 0; i < 80; i++) {
    wf('tools/pre-execute', Object.assign(
      { agent: MAIN, callId: 'tp' + i, name: 'read_file' },
      i % 2 === 0 ? { arguments: {} } : { arguments: { file_path: 'a/x.md' } },
    ))
  }
  turnStopping(9)
  const rec = records().filter(r => r.ev === 'turn-stopping-obs' && r.turn === 9).pop()
  assert.ok(rec, 'turn-stopping 必须留观测')
  assert.ok(rec.turningPointDropped > 0, '🔴 超上限必须**如实计数**（不静默）')
  const kept = Object.values(rec.turningPointCounts).reduce((n, x) => n + x, 0)
  assert.ok(kept <= 64, '转折点保留量必须在上限内（首版 64）')
})

// ── 阶段三 3.1 **收窄版 v11**（Human 2026-10-10 裁定 · 依据 = 回放复现"预算不收敛"）──
//    🔴 验收：R11 预算硬收敛（S54 已覆盖）· R12 降级链有序 · 弱信号默认不保护 · 强信号三类可产出

const strengthOf = (turn) => {
  const rec = records().filter(r => r.ev === 'turn-stopping-obs' && r.turn === turn).pop()
  return rec !== undefined && rec.turningPointStrength !== undefined ? rec.turningPointStrength : { strong: 0, weak: 0, upgraded: 0 }
}

check('S60 **工具对象变化默认不产生强信号**（弱信号 · 不进保护集合）', () => {
  drainTurns()
  // 🔴 自测的时间尺度是**毫秒级**，而 `TP_ADJACENT_MS = 60s` ⇒ 前面用例的强信号会把本用例的
  //    弱信号"邻接升级"。⇒ 用 `session-start` **重置会话内存态**（含 `lastStrongTpAt`），
  //    让本用例在"无强信号锚点"的干净条件下检验弱信号默认行为。
  emit1('agent/session-start', { agent: MAIN, source: 'startup' })
  wf('agent/pre-step', { agent: MAIN, turn: 960, step: 1, messages: [userMsg('继续推进这一块的实现与验证工作')] })
  wf('tools/pre-execute', { agent: MAIN, callId: 'w1', name: 'read_file', arguments: { file_path: 'a/x.md' } })
  wf('tools/pre-execute', { agent: MAIN, callId: 'w2', name: 'read_file', arguments: { file_path: 'b/y.md' } })
  turnStopping(960)
  const st = strengthOf(960)
  assert.ok(st.weak >= 1, '对象变化必须**登记**为弱信号（不静默丢弃）')
  assert.equal(st.strong, 0, '🔴 默认**不保护**（Human 收窄裁定的核心）')
})

check('S61 **Todo 实质变化** ⇒ 强信号 · 其邻域在超预算时受保护（L3/L4 优先不动它）', () => {
  drainTurns()
  startFrame(961, 1, 'h1', 1); settlement(961, 1, [bigText('s61-1', 'q')])
  const qTodo = nextSeq()
  startFrame(961, 2, 'h2', 1); settlement(961, 2, [bigText('s61-2', 'r')], { seq: qTodo })
  // Todo 实质变化（首次 todo 无 prev ⇒ overlap=null ⇒ changed=false）⇒ 需**两次** todo 才能产生变化
  wf('tools/pre-execute', { agent: MAIN, callId: 't1', name: 'todo_write', arguments: { todos: [{ content: '整理模块 A 并补测试', status: 'pending' }] } })
  wf('tools/pre-execute', { agent: MAIN, callId: 't2', name: 'todo_write', arguments: { todos: [{ content: '改成完全不同的方向：迁移数据库策略', status: 'pending' }] } })
  assert.ok(strengthOf !== undefined)
  turnStopping(961)
  const st = strengthOf(961)
  assert.ok(st.strong >= 1, '🔴 Todo 实质变化 ⇒ 强信号（进保护集合）')
  assert.ok((records().filter(r => r.ev === 'todo-plan').pop() || {}).newDirection === true, '判据：newDirection')
})

check('S62 阶段转变**必须有成功结果支持** —— 只有签名变化不算强信号', () => {
  drainTurns()
  // 回合 962：签名有内容，但**没有成功结果**（read 不算）
  wf('agent/pre-step', { agent: MAIN, turn: 962, step: 1, messages: [userMsg('先看清当前结构，再决定怎么推进这一块')] })
  wf('tools/pre-execute', { agent: MAIN, callId: 'r1', name: 'read_file', arguments: { file_path: 'a/x.md' } })
  turnStopping(962)
  const c1 = records().filter(r => r.ev === 'turn-stopping-obs' && r.turn === 962).pop()
  assert.equal((c1.turningPointCounts['phase-change'] || 0), 0, '🔴 无成功结果 ⇒ 不算阶段转变（不猜）')
  // 回合 963：签名再次变化 **且**本回合有成功结果（edit ok:true）
  wf('agent/pre-step', { agent: MAIN, turn: 963, step: 1, messages: [userMsg('把这一段实现按结论落地，并跑一次验证')] })
  wf('tools/pre-execute', { agent: MAIN, callId: 'e1', name: 'edit_file', arguments: { file_path: 'a/x.md' } })
  const h = handlers.get('tools/post-execute')[0]
  h({ agent: MAIN, callId: 'e1', name: 'edit_file' }, { isError: false }, () => Promise.resolve({ kind: 'accept' }))
  turnStopping(963)
  const c2 = records().filter(r => r.ev === 'turn-stopping-obs' && r.turn === 963).pop()
  assert.ok((c2.turningPointCounts['phase-change'] || 0) >= 1, '有成功结果支持 ⇒ 阶段转变成立（强信号）')
})

check('S63 **任务 / 项目映射变化**（唯一焦点卡切换）⇒ 强信号', () => {
  drainTurns()
  // 🔴 自测卡树会被前面的「组合信号」用例改写 ⇒ **先显式设回已知初始态**，再建基线，最后切换
  writeFileSync(C1, card('TASK-20260101-001', 'Executing', 'S1'))
  writeFileSync(C2, card('TASK-20260101-002', 'Waiting', 'W1'))
  emit1('agent/session-start', { agent: MAIN, source: 'startup' }) // 清 lastFocusKey（隔离前序用例）
  wf('agent/pre-step', { agent: MAIN, turn: 964, step: 1, messages: [userMsg('按当前卡推进这一步的实现与验证')] })
  const t0 = records().filter(r => r.ev === 'trigger').pop()
  assert.ok(typeof t0.focus === 'string' && t0.focus.indexOf('001') >= 0, '基线：焦点 = 001')
  // 切换焦点：C1 → Waiting · C2 → Executing
  writeFileSync(C1, card('TASK-20260101-001', 'Waiting', 'S1'))
  writeFileSync(C2, card('TASK-20260101-002', 'Executing', 'W1'))
  wf('agent/pre-step', { agent: MAIN, turn: 965, step: 1, messages: [userMsg('换到另一张卡的任务继续推进')] })
  const trig = records().filter(r => r.ev === 'trigger').pop()
  assert.ok(typeof trig.focus === 'string' && trig.focus.indexOf('002') >= 0, '焦点卡已切换到 002')
  turnStopping(965)
  const st = strengthOf(965)
  assert.ok(st.strong >= 1, '🔴 焦点卡切换 ⇒ 任务/项目映射变化（强信号）')
  const counts = records().filter(r => r.ev === 'turn-stopping-obs' && r.turn === 965).pop().turningPointCounts
  assert.ok((counts['card-mapping-change'] || 0) >= 1, '按 kind 分桶可见')
  // 还原卡树（不影响后续用例）
  writeFileSync(C1, card('TASK-20260101-001', 'Executing', 'S1'))
  writeFileSync(C2, card('TASK-20260101-002', 'Waiting', 'W1'))
})

// ── 🔴 定向边界测试（Human 2026-10-10 裁定：**真实工作负责证明机制在宿主中运行**；
//    **定向测试负责覆盖自然工作不易触发的分支** —— 不等待、不造真实任务、不制造生产故障）──
//    覆盖：L3 强制降级 / L4 强制降级 / aborted·max-turns 生命周期 / 同一步多块推理 /
//          跨作用域不补配 / 带推理文本的 attempt
//    ⚠️ 事件模拟**只能证明处理代码的行为**；宿主是否**真实发出** aborted / max-turns 等事件，
//       仍须由真实观测单独核实（现为"未观察到"）。

checkAsync('S70 定向 · **强制触发 L3**：L2 候选耗尽 ⇒ 降级淘汰 **P1-强保护**记录（不越级 · 不停止）', async () => {
  drainTurns()
  const h = handlers.get('tools/post-execute')[0]
  // 每条 entry 之后都放一个**强**转折点（tool-error）⇒ 每条都被 P1 保护 ⇒ **L2 候选为 0**
  // 🔴 **必须显式错开时间**：若 entry 与其转折点落在同一毫秒，多个转折点会**全部指向同一条**
  //    （判据是"其之前 `at` 最大者"）⇒ 保护面塌缩 ⇒ 用例**不稳定**（本用例第一版即偶发失败）。
  for (let i = 1; i <= 4; i++) {
    const q = nextSeq()
    startFrame(970, i, 'L3-' + i, 1)
    settlement(970, i, [bigText('s70-' + i, 'qrst'[i - 1], 11_000)], { seq: q })
    await sleep(4)
    h({ agent: MAIN, callId: 'e70-' + i, name: 'read_file' }, { isError: true }, () => Promise.resolve({ kind: 'accept' }))
    await sleep(4)
  }
  const es = evicted().filter(r => r.turn === 970 && r.evictedEntries === 1)
  assert.ok(es.length >= 1, '44k > 32k ⇒ **必须淘汰**（不得停在超预算）')
  assert.ok(es.every(r => r.tier === 'L3'), '🔴 只能走到 L3（L2 已空）')
  assert.ok(es.every(r => r.policy === 'P3-over-P1'), '🔴 降级链标记必须是 `P3-over-P1`')
  assert.ok(es.every(r => r.tierCounts !== undefined && r.tierCounts.L2 === 0), '🔴 R12：淘汰 L3 时 **L2 必为空**')
  assert.equal(evicted().filter(r => r.turn === 970 && r.tier === 'L4').length, 0, '尚不该动用端点')
})

check('S71 定向 · **强制触发 L4**：先 L2 再降 L4（**升序不越级** · 必收敛 · 端点先淘汰最新）', () => {
  drainTurns()
  // 🔴 构造要点：淘汰发生在**每次加入之后** ⇒ 必须让"加入时就存在中间条目"：
  //    e1=20k（20k ≤ 32k）→ e2=**12k**（32k 恰好不超）→ e3=20k（52k 超）
  //    ⇒ P0={e1,e3} · L2={e2} ⇒ 先淘汰 e2 ⇒ 40k 仍超 ⇒ L2 空 ⇒ **降级 L4** 淘汰 e3
  const q1 = nextSeq(), q2 = nextSeq(), q3 = nextSeq()
  startFrame(971, 1, 'L4-1', 1); settlement(971, 1, [bigText('s71-1', 'q', 20_000)], { seq: q1 })
  startFrame(971, 2, 'L4-2', 1); settlement(971, 2, [bigText('s71-2', 'r', 12_000)], { seq: q2 })
  startFrame(971, 3, 'L4-3', 1); settlement(971, 3, [bigText('s71-3', 's', 20_000)], { seq: q3 })
  const es = evicted().filter(r => r.turn === 971 && r.evictedEntries === 1)
  assert.equal(es.length, 2, '52k ⇒ 需淘汰 2 条才收敛（20k）')
  assert.equal(es[0].tier, 'L2', '🔴 **先**用无保护中间记录')
  assert.equal(es[0].policy, 'P3-unsheltered')
  assert.equal(es[0].seqRange[0], q2, '中间那条（e2）先被淘汰')
  assert.equal(es[1].tier, 'L4', '🔴 **再**降级到端点')
  assert.equal(es[1].policy, 'P3-over-P0')
  assert.equal(es[1].seqRange[0], q3, '🔴 L4 **先淘汰"最新一条"**（首条的初始方向不可再生）')
  assert.ok(!es.some(r => r.seqRange[0] === q1), '首条尽可能保留')
  assert.ok(es[1].retainedChars <= 32_000, '🔴 R11：最终**必须收敛**')
  assert.equal(es[1].tierCounts.L2, 0, '降级前 L2 已空')
  assert.equal(es[1].tierCounts.L3, 0, '降级前 L3 也空（本例无 P1 保护）')
})

check('S72 定向 · 异常生命周期：`aborted` / `max-turns` ⇒ 按 `reasonKind` **分类记录并释放**', () => {
  drainTurns()
  startFrame(972, 1, 'ab-1', 1); settlement(972, 1, ['aborted 场景文本'])
  turnStopping(972)
  turnEnd(972, 'aborted')
  const r1 = releases().filter(r => r.turn === 972).pop()
  assert.equal(r1.reasonKind, 'aborted', '🔴 如实分类（不吞成 completed）')
  assert.equal(r1.releasedEntries, 1, '异常结束同样**必须释放**')
  assert.equal(r1.coverageAfter, 'complete')

  startFrame(973, 1, 'mt-1', 1); settlement(973, 1, ['max-turns 场景文本'])
  turnEnd(973, 'max-turns')
  const r2 = releases().filter(r => r.turn === 973).pop()
  assert.equal(r2.reasonKind, 'max-turns')
  assert.equal(r2.releasedEntries, 1)
  // ⚠️ 边界（如实记）：本用例只证明**处理代码**对这两类 reason 的行为；
  //    宿主是否**真实发出** aborted / max-turns，仍须由真实观测单独核实（现为"未观察到"）。
})

check('S73 定向 · 高密度推理：同一提交多块 ⇒ **分条**建 entry · 归属一致 · 同一 seq 去重', () => {
  drainTurns()
  const seq = nextSeq()
  startFrame(974, 1, 'hd-1', 1)
  settlement(974, 1, null, {
    seq,
    data: {
      stream: [
        { type: 'reasoning-chunks', time0: 1, index: 0, dt: [3], texts: ['块一'] },
        { type: 'reasoning-chunks', time0: 2, index: 1, dt: [4], texts: ['块二'] },
        { type: 'reasoning-chunks', time0: 3, index: 2, dt: [5], texts: ['块三'] },
        { type: 'reasoning-chunks', time0: 4, index: 3, dt: [6], texts: ['块四'] },
      ],
    },
  })
  const recs = reasoningTexts().filter(r => r.turn === 974)
  assert.equal(recs.length, 4, '🔴 分条建 entry（**不拼接**成一条）')
  assert.ok(recs.every(r => r.attribution === 'fifo-unique'), '同一提交的归属应一致')
  assert.equal(attemptPairs().filter(r => r.turn === 974).length, 1, '归属每条提交只算一次')
  const before = reasoningTexts().length
  settlement(974, 1, null, { seq, data: { stream: [{ type: 'reasoning-chunks', time0: 1, index: 0, dt: [1], texts: ['重复投递'] }] } })
  assert.equal(reasoningTexts().length, before, '🔴 同一 seq 重复投递不得重复建 entry')
})

check('S74 定向 · 跨作用域**不补配**：别的会话的 start 帧不得被借用（不猜归属）', () => {
  drainTurns()
  const OTHER = agent('selftest-other')
  emit1('agent/assistant-stream', { agent: OTHER, frame: { type: 'start', attemptId: 'other-attempt', revision: 1, turn: 975, step: 1 } })
  settlement(975, 1, ['跨作用域测试文本'])
  const p = attemptPairs().filter(r => r.turn === 975).pop()
  assert.equal(p.attribution, 'unavailable', '🔴 不得跨 session 补配')
  assert.equal(p.unavailableReason, 'no-start-seen', '原因必须可区分（R7b）')
})

check('S75 定向 · **带推理文本**的 attempt ⇒ 明确拒收（不建 entry · 只计数 · 不留存）', () => {
  drainTurns()
  const before = reasoningTexts().length
  startFrame(976, 1, 'at-1', 1)
  settlement(976, 1, null, {
    type: 'assistant/attempt',
    data: { stream: [{ type: 'reasoning-chunks', time0: 1, index: 0, dt: [2], texts: [SENTINEL + '-ATTEMPT'] }] },
  })
  assert.equal(reasoningTexts().length, before, '🔴 attempt **不建 entry**（即使确实带推理文本）')
  const p = provisionalObs().filter(r => r.turn === 976).pop()
  assert.ok(p, '只计数')
  assert.equal(p.blocks, 1, '块数如实计数')
  assert.ok(p.chars > 0, '字符数如实计数')
  assert.ok(!JSON.stringify(p).includes('SENTINEL'), '🔴 计数记录**不得**含推理原文')
})

// ── 阶段三 3.2 **影子发现通道**（Human 2026-10-10 裁定 · 默认关闭 · 不递送）──────────

const shadowRecs = () => records().filter(r => r.ev === 'shadow-ab')
const writeShadow = (o) => writeFileSync(SHADOW_PROBE, JSON.stringify(o))
const clearShadow = () => { try { rmSync(SHADOW_PROBE, { force: true }) } catch { /* 静默 */ } }

checkAsync('S76 影子通道默认关闭（开关缺失）⇒ **完全透明**（decision 同一对象引用 · 无记录）', async () => {
  clearShadow()
  const before = shadowRecs().length
  const downstream = { kind: 'accept', content: [{ type: 'text', text: 'ORIGINAL' }] }
  const r = await postExec(MAIN, downstream)
  assert.equal(r.calls, 1, 'next() 恰好一次')
  assert.equal(r.ret, downstream, '🔴 必须**原样**返回下游 decision（同一引用 ⇒ 零行为变化）')
  await sleep(80)
  assert.equal(shadowRecs().length, before, '关闭时**不得**产生 shadow 记录')
})

checkAsync('S77 开关启用但会话不匹配 ⇒ 仍完全透明', async () => {
  writeShadow({ enabled: true, session: 'someone-else', maxPerSession: 1, timeoutMs: 300 })
  const before = shadowRecs().length
  const downstream = { kind: 'accept' }
  const r = await postExec(MAIN, downstream)
  assert.equal(r.ret, downstream, '会话不匹配不得派发')
  await sleep(80)
  assert.equal(shadowRecs().length, before)
  clearShadow()
})

checkAsync('S78 开关命中 ⇒ 派发并**如实记录**（沙箱内 spawn 失败也**不影响宿主** · 不递送）', async () => {
  writeShadow({ enabled: true, session: SESS, maxPerSession: 10, timeoutMs: 600, topN: 2 })
  const before = shadowRecs().length
  const downstream = { kind: 'accept', content: [{ type: 'text', text: 'KEEP' }] }
  const r = await postExec(MAIN, downstream)
  assert.equal(r.calls, 1)
  assert.equal(r.ret, downstream, '🔴 影子通道**绝不**改动 decision（同一引用）')
  assert.ok(!('additionalContexts' in r.ret), '🔴 **不递送**（绝不附加上下文）')
  // ⚠️ 等待须**覆盖超时上限**（沙箱下 spawn 可能既不 error 也不 close ⇒ 只能等超时落记录）
  await sleep(1_000)
  const recs = shadowRecs()
  assert.ok(recs.length > before, '🔴 必须留 `shadow-ab` 记录（**失败也要如实记**）')
  const last = recs[recs.length - 1]
  assert.ok(['ok', 'spawn-error', 'child-error', 'timeout', 'nonzero', 'bad-json', 'stdin-error', 'skipped'].includes(last.outcome),
    '结果原因必须可区分（实测本沙箱下 child_process 管道受限 ⇒ 这里很可能走失败分支，**这本身就是失败路径的真实覆盖**）')
  assert.ok(typeof last.aChars === 'number' && last.aChars > 0, 'A 组查询长度必须记录（派生量）')
  assert.ok(!JSON.stringify(last).includes('SENTINEL'), '🔴 探针**不得**含推理原文')
  clearShadow()
})

// ── 🔴 2026-10-15 · **会话通配**（Human 原话：「不能只是通过绑定某一段对话 / 不然太麻烦 /
//    最好是可以直接用 哪怕是新开一个对话」）────────────────────────────────────────
//    对象：四个开关文件（delivery / shadow / stage4 / reminder）的 `session` 判据。
//    ⛔ 判据本身（"不匹配任何会话"的默认）**不得被放宽**：空串 / 缺失 / 非法类型仍必须不匹配。
//    ⚠️ 语法层面只允许 ①字面相等 ②`"*"` 任意 ③尾 `*` 前缀 ④数组任一项；⛔ 不支持内嵌通配（不猜）。

const WILD_SESSION = 'selftest-wildcard-abc'
const WILD_MAIN = { session: { header: { id: WILD_SESSION, delegationDepth: 0 } } }
const writeDelivery = (o) => writeFileSync(DELIVERY_PROBE, JSON.stringify(o))
/** 命中的判据：`additionalContexts` 恰好是我们那段 marker（不是别的通道顺带附上的）。 */
const gotMarker = (ret, marker) => Array.isArray(ret.additionalContexts)
  && ret.additionalContexts.some(x => x.content && x.content[0] && x.content[0].text === marker)

checkAsync('S79 `session:"*"` ⇒ **任意会话**（新开会话免人工改绑）', async () => {
  writeDelivery({ enabled: true, session: '*', marker: 'S79-WILDCARD', maxPerSession: 1 })
  const r = await postExec(WILD_MAIN, { kind: 'accept' })
  assert.ok(r.ret !== undefined, '必须原样透传下游 decision')
  assert.ok(gotMarker(r.ret, 'S79-WILDCARD'), '`"*"` 必须对未见过的会话生效')
  clearProbe()
})

checkAsync('S80 尾通配 `前缀*` ⇒ 命中；字面绑定 ⇒ 仍只命中自己（旧行为不变）', async () => {
  writeDelivery({ enabled: true, session: 'selftest-wild*', marker: 'S80-PREFIX', maxPerSession: 1 })
  const a = await postExec(WILD_MAIN, { kind: 'accept' })
  assert.ok(gotMarker(a.ret, 'S80-PREFIX'), '前缀通配必须命中')
  writeDelivery({ enabled: true, session: WILD_SESSION, marker: 'S80-LITERAL', maxPerSession: 1 })
  const b = await postExec(WILD_MAIN, { kind: 'accept' })
  assert.ok(gotMarker(b.ret, 'S80-LITERAL'), '字面 id 绑定必须仍然命中（不得被通配改动破坏）')
  const c = await postExec(MAIN, { kind: 'accept' })
  assert.ok(!gotMarker(c.ret, 'S80-LITERAL'), '🔴 字面绑定的**排他性**必须保持')
  clearProbe()
})

checkAsync('S81 数组形式 ⇒ 任一项命中即算（未列出 ⇒ 不匹配）', async () => {
  writeDelivery({ enabled: true, session: ['someone-else', WILD_SESSION], marker: 'S81-ARRAY', maxPerSession: 1 })
  const a = await postExec(WILD_MAIN, { kind: 'accept' })
  assert.ok(gotMarker(a.ret, 'S81-ARRAY'), '数组任一项命中即算')
  const b = await postExec(MAIN, { kind: 'accept' })
  assert.ok(!gotMarker(b.ret, 'S81-ARRAY'), '未列出的会话不得命中')
  clearProbe()
})

checkAsync('S82 fail-closed 不回退：空串 / 缺字段 / 非法类型 ⇒ **不匹配任何会话**', async () => {
  for (const spec of [{ enabled: true, marker: 'S82-BAD', session: '' },
                      { enabled: true, marker: 'S82-BAD' },
                      { enabled: true, marker: 'S82-BAD', session: [] },
                      { enabled: true, marker: 'S82-BAD', session: ['ok', 7] },
                      { enabled: true, marker: 'S82-BAD', session: 42 }]) {
    writeDelivery(spec)
    const r = await postExec(WILD_MAIN, { kind: 'accept' })
    assert.ok(!gotMarker(r.ret, 'S82-BAD'), '非法绑定不得变成"对全世界开放"：' + JSON.stringify(spec))
  }
  clearProbe()
})

checkAsync('S83 通配**不过度匹配**：`selftest-mai*` 不得命中 `selftest-other`', async () => {
  writeDelivery({ enabled: true, session: 'selftest-mai*', marker: 'S83-NARROW', maxPerSession: 1 })
  const other = { session: { header: { id: 'selftest-other', delegationDepth: 0 } } }
  const r = await postExec(other, { kind: 'accept' })
  assert.ok(!gotMarker(r.ret, 'S83-NARROW'), '前缀必须真的逐字匹配，不得近似')
  clearProbe()
})

checkAsync('S84 通配命中 ⇒ 留 `probe-session` 只读授权行（`spec` 逐字 + mode=pattern · 且**按会话去重**）', async () => {
  // ⚠️ 用**本用例独有**的通配 spec：否则会与 S79 的 `"*"` 授权行撞车（去重键含 spec）
  const SPEC = 'selftest-wildcard-ab*'
  writeDelivery({ enabled: true, session: SPEC, marker: 'S84-AUTH', maxPerSession: 3 })
  const authRecs = () => records().filter(r => r.ev === 'probe-session')
  const mineNow = () => authRecs().filter(r => r.session === WILD_SESSION && r.spec === JSON.stringify(SPEC) && r.granted === true)
  const before = mineNow().length
  await postExec(WILD_MAIN, { kind: 'accept' })
  const mid = mineNow().length
  assert.equal(mid, before + 1, '首次命中必须落一条授权行（否则通配绑定不可取证）')
  await postExec(WILD_MAIN, { kind: 'accept' })
  assert.equal(mineNow().length, mid, '🔴 同一会话重复命中**不得**重复落授权行')
  const rec = mineNow()[0]
  assert.equal(rec.probe, 'delivery', '授权行必须写明是**哪个开关**被放行')
  assert.equal(rec.match, 'pattern', '必须能分辨"通配命中"与"字面命中"')
  assert.equal(rec.spec, JSON.stringify(SPEC), 'spec 必须逐字保留开关原文')
  clearProbe()
})

const writeStage4 = (o) => writeFileSync(STAGE4_PROBE, JSON.stringify(o))
const clearStage4 = () => { try { rmSync(STAGE4_PROBE, { force: true }) } catch { /* 静默 */ } }
const stage4Recs = () => records().filter(r => r.ev === 'stage4')
/**
 * 打开一次 deferred 窗口并给出首个工具意图 ⇒ 走到 `dispatchStage4` 的**门**。
 * ⚠️ 沙箱内：`_field_emit.py` 走的是**真实** `scratch/` 路径 ⇒ 可能落到 `field` 失败分支。
 *    本组用例**只断言"门的行为"**（是否留下 stage4 记录），⛔ 不把失败分支当通过，
 *    也**不**断言 field/retrieval 的成败（那是另一条链的验收）。
 */
function fireDeferred(session, agentObj, tag) {
  wf('agent/pre-step', { agent: agentObj, turn: tag.turn, step: 1, messages: [userMsg('把这一块也顺手处理一下，然后继续下一步')] })
  assert.equal(lastTrigger().discovery, 'waiting', '前置条件：必须开窗')
  const before = stage4Recs().length
  wf('tools/pre-execute', { agent: agentObj, callId: 'call-' + tag.call, name: 'read', arguments: { file_path: tag.call + '.ts' }, signal: {} })
  return stage4Recs().length - before
}

check('S85 阶段4 门：已关闭 stage4 ⇒ 通配也不再派发（代码保留 · 可回退）', () => {
  clearStage4()
  writeStage4({ enabled: true, session: '*', maxPerSession: 3, timeoutMs: 2_000 })
  const n = fireDeferred('selftest-stage4-wild', WILD_MAIN, { turn: 301, call: 's85' })
  // 🔴 Human 2026-10-28 裁定「stage4 关掉」：v30 起出结果的路 = auto_capability 内联检索，
  //    stage4 自 10-19 起 9 天 0 成功（P28）⇒ STAGE4_ENABLED=false 时恒不派发。
  //    ⚠️ 若回退（STAGE4_ENABLED=true），本用例应恢复为"通配必须真的走到 stage4（n===1）"。
  assert.equal(mod.__selftest.STAGE4_ENABLED, false, 'Human 已裁定关闭 stage4（代码保留 · 可回退）')
  assert.equal(n, 0, '关闭后 ⇒ 即使通配绑定也不得派发')
  clearStage4()
})

check('S86 阶段4 门：字面绑定 ⇒ 仍然**只**对该会话开门（通配不得放宽旧行为）', () => {
  clearStage4()
  writeStage4({ enabled: true, session: 'selftest-someone-else', maxPerSession: 3, timeoutMs: 2_000 })
  const n = fireDeferred('selftest-stage4-literal', WILD_MAIN, { turn: 302, call: 's86' })
  assert.equal(n, 0, '字面绑定不匹配 ⇒ 必须零记录（fail-closed 语义不变）')
  clearStage4()
})

// ── 🔴 2026-10-15 新增：四项行为修正的**回归护栏**（S87–S90）────────────────────────
//    ⚠️ 这些用例的**端到端**部分沙箱内做不到：`child_process` 走 `pipe` 会 EPERM
//       ⇒ 阶段 4 检索必然失败 ⇒ 造不出"已排队候选"、也跑不出真实递送。
//       ⇒ 此处只锁**判据语义**；凡未真正观测到的，注释里如实写明（⛔ 不写成"已验证"）。
const SELFTEST = mod.__selftest

check('S87 递送来源是「或」：静态 marker / 提醒 / **排队候选** 任一存在 ⇒ 都不得早退', () => {
  const P = { session: '*', marker: 'x', maxPerSession: 1 }
  const R = { enabled: true, session: '*' }
  // 🔴 缺陷现场：前两者皆空、但候选已排队 —— 修复前这里恒为 false（候选永远递送不出去）
  assert.equal(SELFTEST.deliverySourcesActive(null, null, true), true,
    '🔴 排队候选必须**独立**成立 —— 这是本次修复的核心断言')
  assert.equal(SELFTEST.deliverySourcesActive(P, null, false), true, '静态 marker 单独成立')
  assert.equal(SELFTEST.deliverySourcesActive(null, R, false), true, '提醒单独成立')
  assert.equal(SELFTEST.deliverySourcesActive(P, R, true), true, '三者同在不冲突')
  assert.equal(SELFTEST.deliverySourcesActive(null, null, false), false,
    '三者皆无 ⇒ 必须完全透明（零开销 · 不得凭空进入递送段）')
})

check('S88 候选时效：回合前进 / 兜底超时 / 焦点卡变化 ⇒ 丢弃；同语境 ⇒ 放行', () => {
  const CARD = 'projA/TASK-20260101-001.md'
  const OTHER = 'projA/TASK-20260101-002.md'
  // 🔴 步骤 2：焦点卡从**卡上真相**读 ⇒ 这里构造 {me, cards}
  const occ = (k) => ({ key: k, state: 'Executing', step: '', goal: '', next: '', occupancy: { op: 'claim', session: 'S88-ME' } })
  const ds = (ws) => ({ windowSeq: ws, me: 'S88-ME', cards: [occ(CARD)], cardEdits: new Map([[CARD, 1]]), wc: { cardKey: null } })
  const now = 1_000_000
  const fresh = { text: 'x', windowSeq: 7, cardKey: CARD, at: now }
  const MAX = SELFTEST.PENDING_DELIVERY_MAX_AGE_MS

  assert.equal(SELFTEST.pendingStaleReason(ds(7), fresh, now), null, '同回合 + 同焦点卡 + 未超时 ⇒ 放行')
  assert.equal(SELFTEST.pendingStaleReason(ds(8), fresh, now), 'window-advanced',
    '🔴 回合已前进 ⇒ 上一语境的候选必须丢弃（主闸）')
  assert.equal(SELFTEST.pendingStaleReason(ds(7), fresh, now + MAX + 1), 'expired', '超兜底硬超时 ⇒ 丢弃')
  assert.equal(SELFTEST.pendingStaleReason(ds(7), fresh, now + MAX), null, '恰好到界 ⇒ 不得提前丢（边界）')
  assert.equal(SELFTEST.pendingStaleReason(ds(7), { ...fresh, cardKey: OTHER }, now), 'focus-changed',
    '焦点卡已切换 ⇒ 丢弃')
  const ambiguous = { windowSeq: 7, me: 'S88-ME', cards: [occ(CARD), occ(OTHER)], cardEdits: new Map([[CARD, 1], [OTHER, 1]]), wc: { cardKey: null } }
  assert.equal(SELFTEST.pendingStaleReason(ambiguous, fresh, now), null,
    '🔴 焦点卡多义（判不出）⇒ **不**据此丢弃：不确定 ≠ 已变化（宁少丢不误丢）')
  assert.equal(SELFTEST.pendingStaleReason(ds(8), { ...fresh, cardKey: OTHER }, now + MAX + 1), 'window-advanced',
    '多条同时成立 ⇒ 原因串必须确定（便于 `stage4-drop` 读数判读）')
})

check('S89 状态目录判据：`.aios/` 存在即用它（⛔ 只读探测 · 不写不搬）', () => {
  // ⚠️ 规范化分隔符再比：`join()` 产出平台原生分隔符（Windows 反斜杠），而断言基准是正斜杠
  const d = SELFTEST.aiosStateDir().replace(/\\/g, '/')
  assert.ok(d === ROOT + '/.aios' || d === ROOT + '/scratch',
    '必须落在两个合法候选之一，实际 = ' + d)
  // ⚠️ **本用例不声称验证"动态性"**：本仓库 `.aios/` 恒存在，隔离自测无法在**同一进程内**
  //    先让 `.aios/` 不存在、再让它出现（那要临时删真实目录）。
  //    ⇒ 「插件启动后才创建 `.aios/` 也能被感知」**只能在真实宿主重启窗口验收**
  //      （⛔ 不得据本条声称该行为已验证 —— 证据纪律）。
})

check('S90 状态文件三级兜底：新名 ▸ 同目录旧名 ▸ `scratch/` 旧名（迁移期回归护栏）', () => {
  const T = SCRATCH + '/_selftest_state_dynamic'
  const prev = process.env.AIOS_STATE_DIR
  rmSync(T, { recursive: true, force: true })
  process.env.AIOS_STATE_DIR = T
  // ⚠️ 规范化分隔符：`resolveStateFile()` 内部走 `join()` ⇒ 产出 Windows 反斜杠
  const rs = (n, o) => SELFTEST.resolveStateFile(n, o).replace(/\\/g, '/')
  try {
    assert.equal(rs('new.json', '_old.json'), T + '/new.json',
      '目录与旧名都不存在 ⇒ 返回首选名（读不到 ⇒ fail-closed）')
    mkdirSync(T, { recursive: true })
    writeFileSync(T + '/_old.json', '{}')
    assert.equal(rs('new.json', '_old.json'), T + '/_old.json',
      '🔴 同目录旧名兜底必须**当场**生效（迁移期"改了默认名 ⇒ 开关全军覆没"的修法）')
    writeFileSync(T + '/new.json', '{}')
    assert.equal(rs('new.json', '_old.json'), T + '/new.json',
      '新名一出现 ⇒ 立即优先新名')
  } finally {
    if (prev === undefined) delete process.env.AIOS_STATE_DIR
    else process.env.AIOS_STATE_DIR = prev
    rmSync(T, { recursive: true, force: true })
  }
})

// ── 🔴 2026-10-15 新增：焦点卡跨语言接口 **写入侧**（步 1）的隔离自测（S91–S97）──────────
//    Human 授权范围 = **只做 Runtime 写入侧 + 隔离自测**（⛔ 不动 Hook 消费侧）。
//    纪律：全部用例只碰 `AIOS_FOCUS_CARD` 指向的临时目录，⛔ 不写真实 `.aios/`。
//    ⚠️ `FC_DIR` / `FC_FILE` / `AIOS_FOCUS_CARD` / `REAL_FC_BEFORE` **已在文件顶部**定义
//       （必须在插件 import 之前 —— 否则早期用例会走真实路径，实测踩过）。
const FC = mod.__selftest
const CARD_A = 'projA/TASK-20260101-001.md'
const CARD_B = 'projA/TASK-20260101-002.md'
/** 🔴 步骤 2：本会话 id（判据 = 卡上占用留痕的 `session` 与本值相等）。 */
const ME = 'selftest-me'
/** 伪造 `SessionState`：只带 `focusCardOf()` 需要的字段（⛔ 不构造无关状态）。
 *  🔴 2026-10-16 **步骤 2**：第一参仍是卡 key 数组 —— 但现在会被构造成**卡上真相**
 *     （`State=Executing` + 占用留痕 `claim` + `session=ME`）；
 *     `edits` / `wcCard` 退为**对照项**（已不参与焦点卡判定，保留以断言"它们不再生效"）。 */
const mkState = (claims, edits, wcCard) => ({
  windowSeq: 7,
  me: ME,
  cards: (claims || []).map(k => ({
    key: k, state: 'Executing', step: '', goal: '', next: '',
    occupancy: { op: 'claim', session: ME },
  })),
  cardEdits: new Map((edits || []).map(k => [k, 1])),
  wc: { cardKey: wcCard ?? null },
})
const readFC = () => JSON.parse(readFileSync(FC_FILE, 'utf8'))
const clearFC = () => { try { rmSync(FC_FILE, { recursive: true, force: true }) } catch { /* 静默 */ } }
const fcTmp = () => readdirSync(FC_DIR).filter(n => n.includes('.tmp-'))

check('S91 焦点卡接口 · 合法写入：字段齐备且符合 `focus-card/v1`', () => {
  clearFC()
  assert.equal(FC.writeFocusCard(mkState([CARD_A]), 'selftest-fc-a', 'D:/x'), 'written', '首次写入必须成功')
  const o = readFC()
  assert.equal(o.schema, 'focus-card/v1', 'schema 是**唯一版本标识**')
  assert.equal(o.session, 'selftest-fc-a', 'session 必须逐字落盘（强关联键）')
  assert.equal(o.cwd, 'D:/x')
  assert.equal(o.card, CARD_A)
  assert.equal(o.basis, 'card-claim', '恰好 1 张卡**被本会话占用** ⇒ card-claim（步骤 2：读卡真相）')
  assert.equal(typeof o.windowSeq, 'number')
  assert.equal(typeof o.writtenAt, 'number')
  assert.equal(o.expiresAt - o.writtenAt, FC.FOCUS_CARD_TTL_MS, 'expiresAt 必须自 writtenAt 起算 TTL')
  assert.equal(o.writer, 'aios-activation')
  assert.ok(String(o.writerPolicy).includes('v18'), 'writerPolicy 必须带本体版本（与 ev=apply 同源）')
  // 🔴 字段白名单：⛔ 不得夹带推理原文 / 卡正文 / 工具参数
  assert.deepEqual(Object.keys(o).sort(),
    ['basis', 'card', 'cwd', 'expiresAt', 'schema', 'session', 'windowSeq', 'writer', 'writerPolicy', 'writtenAt'].sort(),
    '字段集必须逐字等于契约 —— 多一个字段就是越界')
})

check('S92 不变不写：重复触发不写；**已过期也不刷新**（不得把旧判定伪装成新鲜证据）', () => {
  clearFC()
  const st = mkState([CARD_A])
  assert.equal(FC.writeFocusCard(st, 'selftest-fc-b', 'D:/x'), 'written')
  const before = readFC()
  const t0 = statSync(FC_FILE).mtimeMs
  const n0 = FC.FOCUS_CARD_STATS.unchanged
  assert.equal(FC.writeFocusCard(st, 'selftest-fc-b', 'D:/x'), 'unchanged', '语义芯未变 ⇒ 必须跳过')
  assert.equal(FC.FOCUS_CARD_STATS.unchanged, n0 + 1, 'unchanged 计数必须递增（供诊断）')
  assert.equal(statSync(FC_FILE).mtimeMs, t0, '🔴 "不写"必须是**真不写**（mtime 不得变）')
  assert.deepEqual(readFC(), before, '文件内容必须逐字不变')
  // 🔴 关键：把 `expiresAt` 手动改到过去（模拟"已过期的旧判定"），再以**同一语义芯**触发
  const stale = Object.assign({}, before, { expiresAt: before.writtenAt - 1 })
  writeFileSync(FC_FILE, JSON.stringify(stale, null, 2) + '\n', 'utf8')
  const mtimeStale = statSync(FC_FILE).mtimeMs
  assert.equal(FC.writeFocusCard(st, 'selftest-fc-b', 'D:/x'), 'unchanged',
    '🔴 语义芯未变 ⇒ 即使已过期也必须 unchanged')
  assert.equal(readFC().expiresAt, stale.expiresAt,
    '🔴🔴 **不得刷新 expiresAt** —— 刷新即"用重写把旧判定伪装成新鲜证据"（Human 2026-10-15 明令禁止）')
  assert.equal(statSync(FC_FILE).mtimeMs, mtimeStale, '过期件同样不得被重写')
})

check('S93 触发时机：占用变化 ⇒ 写；判不出焦点卡 ⇒ 不产生 / 不改动文件', () => {
  clearFC()
  assert.equal(FC.writeFocusCard(mkState([], []), 'selftest-fc-c', 'D:/x'), 'no-card')
  assert.ok(!existsSync(FC_FILE), '⛔ 判不出焦点卡时不得写文件（宁缺毋滥）')
  assert.equal(FC.writeFocusCard(mkState([CARD_A]), 'selftest-fc-c', 'D:/x'), 'written')
  assert.equal(FC.writeFocusCard(mkState([CARD_B]), 'selftest-fc-c', 'D:/x'), 'written',
    '🔴 占用改变必须触发写入')
  assert.equal(readFC().card, CARD_B)
  assert.equal(readFC().basis, 'card-claim')
  // 🔴 2026-10-16（Human 裁定）：**删掉 `env-unique-executing` 兜底** ——
  //    环境里"唯一 Executing"（`wc.cardKey`）**不再**产生焦点卡；且 `no-card` 不得改动既有文件。
  const before = readFC()
  assert.equal(FC.writeFocusCard(mkState([], [], CARD_B), 'selftest-fc-c', 'D:/x'), 'no-card',
    '🔴 无本会话占用 ⇒ 不写（⛔ 不得退回"环境唯一 Executing"）')
  assert.deepEqual(readFC(), before, '🔴 `no-card` 不得改动既有文件')
})

check('S98 占用声明语义：`--dry-run` 不算占用；**多命令逐条识别**；`cardEdits` 不再是焦点卡依据', () => {
  const A = 'projA/TASK-20260101-009.md'
  const ME2 = 'selftest-s98'
  const card = (k, op, sid) => ({
    key: k, state: 'Executing', step: '', goal: '', next: '',
    occupancy: op === null ? null : { op, session: sid },
  })
  // ① 只"编辑过卡"、卡上**没有**占用留痕 ⇒ 判不出焦点卡
  const onlyEdit = { windowSeq: 7, me: ME2, cards: [card(A, null, '')], cardEdits: new Map([[A, 1]]), wc: { cardKey: A } }
  assert.equal(FC.focusCardOf(onlyEdit).key, null, '⛔ 编辑卡 ≠ 占用卡（卡上无占用留痕）')
  assert.equal(FC.focusCardOf(onlyEdit).basis, 'none')
  // ①′ 🔴 步骤 2 核心：卡是 `Executing`、但占用者是**别人** ⇒ 也不认（占用是**排他**的）
  const othersCard = { windowSeq: 7, me: ME2, cards: [card(A, 'claim', 'someone-else')], cardEdits: new Map(), wc: { cardKey: null } }
  assert.equal(FC.focusCardOf(othersCard).key, null, '🔴 别人的占用不认给我（`session` 不符）')
  // ①″ 卡上最后一条是 `release`（无占用者）⇒ 不认
  const released = { windowSeq: 7, me: ME2, cards: [card(A, 'release', ME2)], cardEdits: new Map(), wc: { cardKey: null } }
  assert.equal(FC.focusCardOf(released).key, null, '`release` 后无占用者 ⇒ 不认')
  // ② 卡上占用恰 1 张且**是本会话** ⇒ 焦点卡 = 它
  const mine1 = { windowSeq: 7, me: ME2, cards: [card(A, 'claim', ME2)], cardEdits: new Map(), wc: { cardKey: null } }
  assert.equal(FC.focusCardOf(mine1).key, A)
  assert.equal(FC.focusCardOf(mine1).basis, 'card-claim')
  // ③ 本会话占用 >1 张 ⇒ 不猜
  const mine2 = { windowSeq: 7, me: ME2, cards: [card(A, 'claim', ME2), card(CARD_B, 'claim', ME2)], cardEdits: new Map(), wc: { cardKey: null } }
  assert.equal(FC.focusCardOf(mine2).key, null, '多张占用 ⇒ ⛔ 不猜')
  // ④ `--dry-run` 预览不记占用（命令字面量识别 + dryRun 判据）
  const dry = FC.cardCmdsOf('pwsh', { command: 'python tools/task_card.py claim TASK-20260101-009 --dry-run' })
  assert.equal(dry.length, 1)
  assert.equal(dry[0].dryRun, true, '🔴 `--dry-run` 必须被识别为预览')
  const real = FC.cardCmdsOf('pwsh', { command: 'python tools/task_card.py claim TASK-20260101-009' })
  assert.equal(real[0].dryRun, false, '真占用不得被误判为预览')
  assert.equal(real[0].op, 'claim')
  // ⑤ 🔴 2026-10-16 新增：**一次调用里的多条命令必须逐条识别**
  //    （原 `CARD_CMD_RE.exec()` 只取第一条 ⇒ 第二条起的 claim/release **静默丢失**，实测踩到）
  const multi = FC.cardCmdsOf('pwsh', { command:
    'python tools/task_card.py release TASK-20260101-009 --state=Parked\n'
    + 'python tools/task_card.py claim TASK-20260101-009' })
  assert.equal(multi.length, 2, '🔴 两条命令都要被识别（不得只取第一条）')
  assert.deepEqual(multi.map(x => x.op), ['release', 'claim'])
  assert.equal(multi[0].dryRun, false, '第一行是真 release')
  // ⑥ `--dry-run` 判据**按行**取 —— 混写时不得把真跑的那条也判成预览
  const mixed = FC.cardCmdsOf('pwsh', { command:
    'python tools/task_card.py claim TASK-20260101-009\n'
    + 'python tools/task_card.py claim TASK-20260101-009 --dry-run' })
  assert.deepEqual(mixed.map(x => x.dryRun), [false, true],
    '🔴 `--dry-run` 必须**逐条**判（⛔ 不能用整段文本判 —— 会把真跑的也误判成预览）')
  // ⑦ 非占用类命令 / 非 shell 工具 ⇒ 空数组（不得误记）
  assert.deepEqual(FC.cardCmdsOf('pwsh', { command: 'python tools/task_card.py states' }), [])
  assert.deepEqual(FC.cardCmdsOf('read', { command: 'python tools/task_card.py claim TASK-20260101-009' }), [])
  // ⑧ 🔴 v42（2026-10-30）：**「项目/ID」形式**必须识别（跨项目重名卡的唯一合法占用方式）。
  //    实测缺口：本会话 `claim AI-OS-Adaptation/TASK-20261023-001` 成功占用，但旧正则只认裸 ID
  //    ⇒ 探针无 `card-cmd` 记账 ⇒ `anchor-claimed` 事件永不触发（第一条注入丢失）。
  const prefixed = FC.cardCmdsOf('pwsh', { command: 'python tools/task_card.py claim AI-OS-Adaptation/TASK-20260101-009' })
  assert.equal(prefixed.length, 1, '⑧ 带项目前缀的 claim 必须被识别')
  assert.equal(prefixed[0].op, 'claim')
  assert.equal(prefixed[0].taskId, 'AI-OS-Adaptation/TASK-20260101-009', '⑧ taskId 必须保留项目前缀（用于唯一命中卡）')
  const prefixedRel = FC.cardCmdsOf('pwsh', { command: 'python tools/task_card.py release demo-project/TASK-20260101-010 --state=Parked' })
  assert.equal(prefixedRel.length, 1, '⑧ 带前缀的 release 同样必须识别')
  assert.equal(prefixedRel[0].taskId, 'demo-project/TASK-20260101-010')
  // ⑨ 裸 ID 行为**不得回归**（历史样本 / 单项目下仍在用）
  assert.equal(FC.cardCmdsOf('pwsh', { command: 'python tools/task_card.py claim TASK-20260101-009' })[0].taskId, 'TASK-20260101-009')
})

check('S99 一个对话同时只能占一张卡：多占用 ⇒ **只提醒**（⛔ Runtime 不自动释放/替换）', () => {
  const A = 'projA/TASK-20260101-011.md'
  const B = 'projA/TASK-20260101-012.md'
  // ⚠️ 构造**已被锚定**的会话（`cardReads` 非空）⇒ 隔离出 ⓪ `multi-claim` 分支，
  //    否则会先命中 ① `no-anchor`（提醒判据有顺序）。
  const ME3 = 'selftest-s99'
  const mk = (keys) => ({
    windowSeq: 7,
    me: ME3,
    cards: keys.map(k => ({
      key: k, state: 'Executing', step: '', goal: '', next: '',
      occupancy: { op: 'claim', session: ME3 },
    })),
    cardEdits: new Map(), cardReads: new Map([[A, 1]]),
    wc: { progress: { signals: [] } },
    reminderA: false, reminderB: false, reminderC: false,
  })
  // ① 单张占用 ⇒ 无提醒
  assert.equal(FC.reminderFor(mk([A])), null, '只占一张 ⇒ 无提醒')
  // ② 多张占用 ⇒ 提醒：kind 稳定 · 文案含纪律 / 释放命令 / 状态含义 / 卡名
  const two = mk([A, B])
  const r = FC.reminderFor(two)
  assert.ok(r !== null, '多占用 ⇒ 必须提醒')
  assert.equal(r.kind, 'multi-claim')
  assert.ok(r.text.includes('一个对话同时只能占用一张'), '文案必须说明纪律')
  assert.ok(r.text.includes('release'), '文案必须给出释放命令')
  assert.ok(r.text.includes('进行中'), '文案必须说明「释放 ⇒ 状态回到进行中」（Human 2026-10-16）')
  assert.ok(r.text.includes('TASK-20260101-011.md'), '文案必须列出被占用的卡')
  // ③ 🔴 **不自动改**：提醒前后卡列表必须逐字不变（本补丁的核心边界）
  assert.deepEqual(two.cards.map(c => c.key).sort(), [A, B].sort(),
    '🔴 提醒**不得**改动 `cards`（⛔ Runtime 不自动释放 / 不自动替换）')
  assert.equal(two.cards.length, 2, '占用数不得被提醒改变')
  // ④ 每会话每类一次（防打扰）
  assert.equal(FC.reminderFor(two), null, '同类提醒每会话只发一次')
  // ⑤ 收敛为一张 ⇒ 无提醒
  assert.equal(FC.reminderFor(mk([A])), null, '收敛为一张 ⇒ 无提醒')
  // ⑥ 多占用 ⇒ 焦点卡**判不出**（⛔ 不猜）—— 这正是要提醒收敛的理由
  assert.equal(FC.focusCardOf(two).key, null, '多占用 ⇒ 焦点卡判不出')
  assert.equal(FC.focusCardOf(two).basis, 'card-claims-multiple:2')
})

check('S100 启动回收判据：新进程 ⇒ 卡池里所有 Executing 都是遗留（纯函数 · 无副作用）', () => {
  const cards = [
    { key: 'projA/TASK-20260101-001.md', state: 'Executing' },
    { key: 'projA/TASK-20260101-002.md', state: 'Parked' },
    { key: 'projA/TASK-20260101-003.md', state: 'executing' },  // 大小写不敏感（容错）
    { key: 'projA/TASK-20260101-004.md', state: '' },           // 缺 State
    { key: 'projA/TASK-20260101-005.md', state: 'Reviewing' },
  ]
  const legacy = FC.legacyExecutingCards(cards)
  assert.deepEqual(legacy, ['projA/TASK-20260101-001.md', 'projA/TASK-20260101-003.md'],
    '🔴 只回收 `Executing`（⛔ 不动 Parked / Reviewing / 缺 State）')
  // 🔴 **纯函数**：⛔ 不改入参 · ⛔ 无 I/O —— 回收动作由调用方 spawn **工具**执行（单一 owner）
  assert.equal(cards.length, 5, '判据不得改动入参')
  assert.deepEqual(FC.legacyExecutingCards([]), [], '空卡池 ⇒ 空结果')
})

check('S101 占用留痕解析：`Event Log` 尾行 ⇒ {op, session}（纯函数 · 与写入侧逐字同源）', () => {
  const claimLine = '| 02:40 | Executing | claim 占用（session: session-abc-123） | Worker |'
  const relLine = '| 03:38 | Parked | release 释放（session: -） · startup-recover | Worker |'
  const otherLine = '| 00:18 | Executing | 收尾写回（wrapup_sync 2026-10-16，项目 AI-OS-Adaptation）：提交 `d720272` | Worker |'
  // ① 只有 claim 行
  assert.deepEqual(FC.lastOccupancyOf(claimLine), { op: 'claim', session: 'session-abc-123' })
  // ② 取**最后一条**（release 在后 ⇒ 覆盖前面的 claim）
  assert.deepEqual(FC.lastOccupancyOf(claimLine + '\n' + relLine), { op: 'release', session: '-' })
  // ③ ⛔ 其它 `Event Log` 行（收尾写回）不算占用留痕 ⇒ null
  assert.equal(FC.lastOccupancyOf(otherLine), null, '⛔ 非占用行不得被误认为占用留痕')
  // ④ 与其它行混排时，仍取"**最后一条占用/释放行**"
  assert.deepEqual(FC.lastOccupancyOf(otherLine + '\n' + claimLine + '\n' + otherLine),
    { op: 'claim', session: 'session-abc-123' })
  // ⑤ 空 / 只有表头 ⇒ null（"没有占用者"）
  assert.equal(FC.lastOccupancyOf(''), null)
  assert.equal(FC.lastOccupancyOf('| Time | State | Reason | Changed By |'), null)
})

check('S102 `auto_capability` 载荷判据：必填 / 可信度 / 去重截断（纯函数 · ⛔ 无 I/O · ⛔ 不记原文）', () => {
  const NOW = 1793106893000
  // ① `what` 必填（空白不算）
  assert.equal(FC.buildWorkReport('s1', {}, NOW).ok, false)
  assert.equal(FC.buildWorkReport('s1', { what: '   ', confirmed: 'user' }, NOW).ok, false)
  // ② `confirmed` **可省略**（缺省 agent-inferred）；显式非法值仍拒绝
  const rDefault = FC.buildWorkReport('s1', { what: 'x' }, NOW)
  assert.equal(rDefault.ok, true, '省略 confirmed 应合法')
  assert.equal(rDefault.rep.confirmed, 'agent-inferred', '缺省必须落 agent-inferred')
  assert.equal(FC.buildWorkReport('s1', { what: 'x', confirmed: 'maybe' }, NOW).ok, false)
  // ③ 正常路径：trim · 去重 · 字段回填；⛔ 不改入参
  const args = { what: '  在做作品集首页 ', need: ['前端', '前端', ''], concern: ['美观·风格'], fix: '甲方说太丑', confirmed: 'user' }
  const r = FC.buildWorkReport('s1', args, NOW)
  assert.equal(r.ok, true)
  assert.equal(r.rep.what, '在做作品集首页', '必须 trim')
  assert.deepEqual(r.rep.need, ['前端'], '必须去重并丢空项')
  assert.equal(r.rep.needCount, 1)
  assert.equal(r.rep.concernCount, 1)
  assert.equal(r.rep.confirmed, 'user')
  assert.equal(r.rep.hasFix, true)
  assert.equal(r.rep.hasCard, false)
  assert.equal(r.rep.session, 's1')
  assert.equal(r.rep.at, NOW)
  assert.equal(args.need.length, 3, '⛔ 纯函数不得改动入参')
  // ④ 每轴上限 6；单字段截断 500（防滥用；⛔ 原文不落盘由 record 侧保证）
  const many = Array.from({ length: 12 }, (_, i) => 'n' + String(i))
  const r2 = FC.buildWorkReport('s1', { what: 'x', need: many, concern: many, confirmed: 'agent-inferred' }, NOW)
  assert.equal(r2.rep.need.length, FC.WORK_REPORT_AXIS_MAX)
  assert.equal(r2.rep.concern.length, FC.WORK_REPORT_AXIS_MAX)
  const long = 'a'.repeat(FC.WORK_REPORT_FIELD_MAX + 100)
  const r3 = FC.buildWorkReport('s1', { what: long, confirmed: 'user' }, NOW)
  assert.equal(r3.rep.what.length, FC.WORK_REPORT_FIELD_MAX, '单字段必须截断')
  // ⑤ 环形上限常量（写入侧在 record 内用它；此处只锁值域，⛔ 不触发写盘）
  assert.equal(FC.WORK_REPORT_MAX_PER_SESSION, 8)
})

check('S103 `auto_capability` → 检索请求：字段 → 通道一一对应（纯函数 · ⛔ 无 I/O）', () => {
  const mkRep = (over) => Object.assign({
    id: 'wr-1', session: 's1', at: 1, chars: 9, needCount: 2, concernCount: 1,
    confirmed: 'user', hasFix: true, hasCard: false,
    what: '在做作品集首页', need: ['前端', '实现'], concern: ['美观·风格'],
    fix: '甲方说太丑', note: '', card: '',
  }, over)
  const wc = { historyCoverage: 'complete' }
  const probe = { maxCandidates: 8, maxPerSource: 3 }
  const rep = mkRep({})
  const req = FC.buildRetrievalRequestFromWorkReport(rep, wc, probe)
  // ① 身份 / 预算
  assert.equal(req.schema, 'retrieval-request/v1')
  assert.ok(String(req.request_id).startsWith('rr-wr-'), 'request_id 必须可回溯到 auto_capability')
  assert.equal(req.budget.max_candidates, 8)
  assert.equal(req.budget.max_per_source, 3)
  // ② what → work_topic（topic 通道）
  assert.deepEqual(req.work.work_topic, { state: 'provided', value: '在做作品集首页' })
  // ③ need → 顶层 need（intent 通道）+ 帮助类型 → work_type（role 通道）
  assert.deepEqual(req.need, { state: 'provided', value: '前端 实现', origin: 'agent' })
  assert.deepEqual(req.work.work_type, { state: 'provided', value: '实现' }, '只抽「帮助类型」，⛔ 不把领域词塞进 role')
  // ④ concern → search_terms（keys 通道 · Agent 自供检索键）
  assert.deepEqual(req.search_terms, { state: 'provided', value: ['美观·风格'] })
  // ⑤ fix → unresolved（context 通道 · 只加分不单独构成命中）
  assert.deepEqual(req.work.unresolved, { state: 'provided', value: '甲方说太丑' })
  // ⑥ card 不当检索对象 ⇒ target_refs 保持 unknown（⛔ 不造假精确）
  assert.deepEqual(req.work.target_refs, { state: 'unknown' })
  assert.equal(req.work.history_coverage.state, 'provided')
  // ⑦ 每个 work 字段必须三态（Python `validate` 拒绝缺失）
  for (const k of Object.keys(req.work)) {
    assert.ok(['provided', 'known-absent', 'unknown'].includes(req.work[k].state), 'work.' + k + ' 必须三态')
  }
  // ⑧ 空字段 ⇒ 不添加（⛔ 不制造空信号）
  const bare = FC.buildRetrievalRequestFromWorkReport(mkRep({ need: [], concern: [], fix: '', needCount: 0, concernCount: 0, hasFix: false }), wc, probe)
  assert.deepEqual(bare.need, { state: 'unknown', origin: 'agent' })
  assert.equal(bare.search_terms, undefined, '空 concern ⇒ 不提供 search_terms')
  assert.equal(bare.work.unresolved, undefined, '空 fix ⇒ 不提供 unresolved')
  assert.equal(bare.work.work_type, undefined, '无帮助类型 ⇒ 不提供 work_type（⛔ 不猜）')
  // ⑨ historyCoverage=partial ⇒ incomplete（R8 语义）
  const partial = FC.buildRetrievalRequestFromWorkReport(mkRep({}), { historyCoverage: 'partial' }, probe)
  assert.equal(partial.work.history_coverage.value, 'incomplete')
  // ⑩ 纯函数：不改入参
  assert.equal(rep.need.length, 2, '⛔ 不得改动入参')
  // ⑪ 探针摘要：只派生量（不回显 value 全文）· 带 requestSource
  const obs = FC.stage4RequestObs(req, 'work-report')
  assert.equal(obs.requestSource, 'work-report')
  assert.ok(!JSON.stringify(obs).includes('在做作品集首页'), '探针 ⛔ 不得回显 work_topic 原文')
  assert.deepEqual(obs.fieldsProvided.slice().sort(), ['history_coverage', 'unresolved', 'work_topic', 'work_type'].sort())
  assert.equal(obs.searchTerms.items, 1)
})

check('S104 归属 / 预算 / C 提醒（纯函数 + 只读状态；⛔ 不写盘 · ⛔ 不发消息）', () => {
  // ① 归属：主会话 ⇒ 归自己
  const main = { session: { header: { id: 'main-1', origin: 'main' } } }
  const om = FC.reportOwnerOf(main)
  assert.equal(om.owner, 'main-1')
  assert.equal(om.identity, 'main')
  assert.equal(typeof om.basis, 'string')
  // ② 子会话 + parentSession ⇒ **归父会话**（否则主会话检索永远看不到子会话的自述）
  const sub = { session: { header: { id: 'sub-1', origin: 'subagent', parentSession: 'main-1' } } }
  assert.equal(FC.reportOwnerOf(sub).owner, 'main-1')
  assert.equal(FC.reportOwnerOf(sub).basis, 'parentSession')
  assert.equal(FC.reportOwnerOf(sub).identity, 'subagent')
  // ③ 子会话但拿不到父会话 ⇒ 归自己 + 标注（⛔ 不猜父会话是谁）
  const sub2 = { session: { header: { id: 'sub-2', origin: 'subagent' } } }
  assert.equal(FC.reportOwnerOf(sub2).owner, 'sub-2')
  assert.equal(FC.reportOwnerOf(sub2).basis, 'subagent-without-parent')
  // ④ 调用预算：8 次硬上限（纯函数 · ⛔ 不读模块状态）
  assert.equal(FC.WORK_REPORT_BUDGET_PER_SESSION, 8)
  assert.equal(FC.workReportBudgetLeft(0), 8)
  assert.equal(FC.workReportBudgetLeft(7), 1)
  assert.equal(FC.workReportBudgetLeft(8), 0)
  assert.equal(FC.workReportBudgetLeft(99), 0, '⛔ 不得出现负数')
  // ⑤ C 提醒：有实质改动 + 从未上报 ⇒ 提醒**一次**
  const mkR = (opts) => ({
    windowSeq: 7,
    me: ME,
    cards: (opts.claims || []).map(k => ({ key: k, state: 'Executing', step: '', goal: '', next: '', occupancy: { op: 'claim', session: ME } })),
    cardEdits: new Map((opts.edits || []).map(k => [k, 1])),
    cardReads: new Map(),
    reminderA: true, reminderB: true, reminderC: true, reminderD: false,
    wc: { progress: { signals: opts.signals || [] } },
  })
  FC.WORK_REPORTS.delete(ME)
  const st = mkR({ signals: ['has-edit'] })
  const r = FC.reminderFor(st)
  assert.equal(r.kind, 'work-report', '有实质改动 + 未上报 ⇒ C 提醒')
  assert.ok(r.text.includes('auto_capability'), '提醒必须点名工具')
  assert.equal(FC.reminderFor(st), null, '同类提醒每会话只发一次（⛔ 不重复打扰）')
  // ⑥ 已上报过 ⇒ 不再提醒
  const st2 = mkR({ signals: ['has-edit'] })
  FC.WORK_REPORTS.set(ME, [{ id: 'wr-x' }])
  assert.equal(FC.reminderFor(st2), null, '已上报 ⇒ ⛔ 不提醒')
  FC.WORK_REPORTS.delete(ME)
  // ⑦ 没有实质改动 ⇒ 不提醒（⛔ 不为"只是看看"打扰）
  assert.equal(FC.reminderFor(mkR({ signals: [] })), null)
})

check('S105 R3 维护清单：卡释放 ⇒ 注入一次（纯函数 + 注入卡列表；⛔ 不写盘）', () => {
  FC.MAINT_STATE.delete(ME)
  const shell = { windowSeq: 7, me: ME, cards: [], cardEdits: new Map(), cardReads: new Map(), wc: { progress: { signals: [] } } }
  const cardsOf = (keys) => (keys || []).map(k => ({
    key: k, state: 'Executing', step: '', goal: '', next: '', occupancy: { op: 'claim', session: ME },
  }))
  // ① 首次见到 ⇒ 只建立基线，⛔ 不误报"刚释放"
  assert.equal(FC.maintenanceChecklist(shell, ME, cardsOf(['AI-OS-Adaptation/TASK-X.md'])), null, '首次调用只建基线')
  // ② 占用消失（release）⇒ 给清单，且**强制查漏六项**都在
  //    🔴 2026-10-28 回归点：`s.cards` 在同回合不重扫 ⇒ 必须靠**现扫**（此处以 override 模拟）才看得见释放
  const cl = FC.maintenanceChecklist(shell, ME, cardsOf([]))
  assert.equal(typeof cl, 'string', 'release 后必须给出维护清单')
  for (const k of ['INVENTORY', 'ENV', 'PITFALLS', 'State', 'tests']) {
    assert.ok(cl.includes(k), '清单必须含「' + k + '」')
  }
  assert.ok(cl.includes('TASK-X.md'), '必须点名被释放的卡')
  // ③ 每会话一次（⛔ 不重复打扰）
  assert.equal(FC.maintenanceChecklist(shell, ME, cardsOf([])), null, '⛔ 不重复注入')
  // ④ 从没占用过 ⇒ ⛔ 不报（不该给"没占过卡"的会话发收工维护）
  const other = 'selftest-no-claim'
  FC.MAINT_STATE.delete(other)
  assert.equal(FC.maintenanceChecklist(shell, other, cardsOf([])), null)
  FC.MAINT_STATE.delete(other)
})

check('S106 事件驱动注入：升沿检测 + 每事件一次（⛔ 不再用阶段状态机 ⇒ 抖动通道已移除）', () => {
  // ① 交替 20 步（edit → read×7 → edit …）⇒ **v47 起不再产生任何注入**
  //    （v26 时 = 2 次；v47 T1 砍掉 first-edit / anchor-claimed：实测无上下文触发 17/36 调用、消费 0）
  const slot = { sent: new Set(), count: 0, lastHasEdit: false, lastFailStreak: 0, lastNamedTurn: null }
  const sent = []
  for (let i = 0; i < 20; i++) {
    const hasEdit = i % 8 === 0 && i > 0
    const events = FC.detectEvents(
      { hasEdit, activity: [], cardEdits: 1, intentText: '继续做', turn: 1 }, slot)
    slot.lastHasEdit = hasEdit
    slot.lastFailStreak = 0
    for (const ev of events) if (FC.shouldPublishEvent(slot, ev, 20)) { sent.push(ev); break }
  }
  assert.deepEqual(sent, [], 'v47 T1：纯 edit 交替 ⛔ 再产生注入（旧 v26 = 2 次）')

  // ② v47 T1：first-edit / anchor-claimed **不再产生**（事件类型与文案保留，便于回滚）
  const evAfterEdit = FC.detectEvents(
    { hasEdit: true, activity: [], cardEdits: 3, intentText: '继续', turn: 2 }, slot)
  assert.equal(evAfterEdit.includes('first-edit'), false, 'v47 起 ⛔ 产生 first-edit')
  assert.equal(evAfterEdit.includes('anchor-claimed'), false, 'v47 起 ⛔ 产生 anchor-claimed')

  // ③ stuck = **升沿**（连续失败 0→2 才触发；已在 2 停留不重复）
  const s2 = { sent: new Set(), count: 0, lastHasEdit: false, lastFailStreak: 0, lastNamedTurn: null }
  const evOne = FC.detectEvents(
    { hasEdit: false, activity: [{ ok: true }, { ok: false }], cardEdits: 0, intentText: '', turn: 1 }, s2)
  assert.equal(evOne.includes('stuck'), false, 'streak=1 ⛔ 不触发')
  const evTwo = FC.detectEvents(
    { hasEdit: false, activity: [{ ok: false }, { ok: false }], cardEdits: 0, intentText: '', turn: 1 }, s2)
  assert.ok(evTwo.includes('stuck'), 'streak=2 首次 ⇒ 触发')
  assert.equal(FC.shouldPublishEvent(s2, 'stuck', 20), true)

  // ④ 用户点名：同轮去重（换轮才可再触发）
  const s3 = { sent: new Set(), count: 0, lastHasEdit: false, lastFailStreak: 0, lastNamedTurn: null }
  assert.ok(FC.detectEvents(
    { hasEdit: false, activity: [], cardEdits: 0, intentText: '帮我做个检索', turn: 5 }, s3).includes('user-named'))
  s3.lastNamedTurn = 5
  assert.equal(FC.detectEvents(
    { hasEdit: false, activity: [], cardEdits: 0, intentText: '做个检索', turn: 5 }, s3).includes('user-named'), false,
  '同轮 ⛔ 重复')

  // ⑤ 文案：事实 + 动作，全部点名 auto_capability，且必须短（每会话最多 4 条）
  for (const ev of ['anchor-claimed', 'first-edit', 'stuck', 'user-named']) {
    const t = FC.eventHintText(ev)
    assert.ok(t.length > 0 && t.includes('auto_capability'), ev + ' 文案必须点名 auto_capability')
    assert.ok(t.length < 300, ev + ' 文案必须短')
  }
})

check('S107 阶段判据 + 用户点名（纯函数 · 对应 的模糊例子）', () => {
  const mkS = (opts) => ({
    windowSeq: 1, me: ME,
    cardEdits: new Map((opts.edits || []).map(k => [k, 1])),
    wc: { activity: opts.activity || [], progress: { signals: opts.signals || [] }, intentText: '' },
  })
  // ① Human 给的例子 ⇒ 阶段（判据只用词面/工具序列/连续失败，⛔ 不做语义）
  const cases = [
    { text: '开张卡 继续完成任务', opts: {}, want: 'starting' },
    { text: '开个新卡 新项目 慢慢聊', opts: {}, want: 'planning' },
    { text: '看着有点丑', opts: {}, want: 'shifting' },
    { text: '改一下', opts: {}, want: 'shifting' },
    { text: '检查一下有没有问题', opts: {}, want: 'reviewing' },
    { text: '报错了 搞不定', opts: {}, want: 'stalled' },
    { text: '随便说点什么', opts: {}, want: 'unknown' },
    { text: '继续做', opts: { signals: ['has-edit'] }, want: 'implementing' },
  ]
  for (const c of cases) {
    assert.equal(FC.deriveWorkPhase(mkS(c.opts), c.text), c.want, '「' + c.text + '」⇒ ' + c.want)
  }
  // ② 连续失败 ⇒ stalled（**行为证据优先于词**）
  assert.equal(FC.deriveWorkPhase(mkS({ activity: [{ ok: true }, { ok: false }, { ok: false }] }), '继续'), 'stalled')
  // ③ 用户点名（Human 给的叫法：「做个检索」「找找能力」）
  assert.equal(FC.detectRetrievalRequest('帮我做个检索').hit, true)
  assert.equal(FC.detectRetrievalRequest('帮我做个检索').matched, '做个检索')
  assert.equal(FC.detectRetrievalRequest('找找能力 看有没有前端相关的').hit, true)
  assert.equal(FC.detectRetrievalRequest('继续写代码').hit, false)
  // ④ catalog 式发布：同 key 不重发 · 变 key 才发 · planning/unknown 不发 · 有上限
  const slot = { published: '', count: 0 }
  assert.equal(FC.shouldPublishHint(slot, 'starting', 5), true)
  assert.equal(FC.shouldPublishHint(slot, 'starting', 5), false, '同阶段 ⛔ 不重发（catalog 式）')
  assert.equal(FC.shouldPublishHint(slot, 'implementing', 5), true, '阶段变了 ⇒ 发布')
  assert.equal(FC.shouldPublishHint(slot, 'planning', 5), false, 'planning ⛔ 不打扰')
  assert.equal(FC.shouldPublishHint(slot, 'unknown', 5), false, 'unknown ⛔ 不打扰')
  const cap = { published: '', count: 0 }
  for (let i = 0; i < 3; i++) FC.shouldPublishHint(cap, 'k' + String(i), 3)
  assert.equal(FC.shouldPublishHint(cap, 'k9', 3), false, '到上限 ⇒ 不再发')
  // ⑤ 文案：点名/各阶段有内容；planning/unknown 为空
  for (const k of ['user-named', 'starting', 'implementing', 'shifting', 'stalled']) {
    assert.ok(FC.phaseHintText(k).length > 0, k + ' 必须有文案')
  }
  assert.equal(FC.phaseHintText('planning'), '')
  assert.equal(FC.phaseHintText('unknown'), '')
  assert.ok(FC.phaseHintText('user-named').includes('auto_capability'))
})

check('S108 占用判据：外置 .log 优先 · 回退卡内（防"外置后再次静默失效"）', () => {
  const dir = SCRATCH + '/_selftest_logext'
  rmSync(dir, { recursive: true, force: true })
  mkdirSync(dir, { recursive: true })
  const md = dir + '/TASK-20260101-001.md'
  const log = dir + '/TASK-20260101-001.log'
  const claim = '| 10:00 | Executing | claim 占用（session: s-a） | Worker |'
  const rel = '| 11:00 | Parked | release 释放（session: s-b） | Worker |'
  const hdr = '| Time | State | Reason | Changed By |\n|------|-------|--------|:----------:|\n'
  // 卡内只剩**指针**（新格式）；为测"回退兼容"这里故意留一行旧表格
  writeFileSync(md, '# card\n\n## Event Log — 已外置\n\n> 指针\n\n' + hdr + claim + '\n', 'utf8')
  writeFileSync(log, hdr + claim + '\n' + rel + '\n', 'utf8')
  // ① 优先读 .log（最后一条 = release）
  assert.deepEqual(FC.occupancyOfCard(md), { op: 'release', session: 's-b' }, '必须优先外置日志')
  // ② 无 .log ⇒ 回退卡内（旧卡兼容）
  rmSync(log, { force: true })
  assert.deepEqual(FC.occupancyOfCard(md), { op: 'claim', session: 's-a' }, '回退卡内（兼容未迁移旧卡）')
  // ③ 都没有 ⇒ null（⛔ 不猜）
  rmSync(md, { force: true })
  assert.equal(FC.occupancyOfCard(md), null)
  rmSync(dir, { recursive: true, force: true })
})

check('S109 内联检索：白名单含「位置 + 一句话介绍」（⛔ 正文/预览原文）· 失败不抛 · 渲染可读', () => {
  // ① 归一：`source.id` ⇒ `source`；channels 复制；空项跳过；**正文绝不外泄**
  const set = {
    candidates: [
      { id: 'a', kind: 'capability', name: 'pre_push_evidence_gate', source: { id: 'src1' },
        role: 'verification', hit_channels: ['topic', 'intent'],
        preview: '推送前证据闸门：push 前该跑哪些检查', local_path: 'capabilities/pre_push_evidence_gate.md',
        body: 'SECRET-正文' },
      { id: 'b', kind: 'ledger-chunk', name: 'Entry #63', source: null, role: null,
        preview: 'footprint = NOT_APPLICABLE（这是账本正文开头，很长很长很长很长很长很长很长很长很长很长很长很长）' },
      null,
    ],
    budget_applied: { matched_before_budget: 347 },
    diversity: { channels_used: ['topic', 'intent'] },
  }
  const cands = FC.retrievalCandidatesOf(set)
  assert.equal(cands.length, 2, '空项必须跳过')
  assert.deepEqual(Object.keys(cands[0]).sort(), ['channels', 'id', 'path', 'role', 'source', 'summary'],
    '⛔ 字段白名单：id/来源/角色/通道 + **位置 + 一句话介绍**（⛔ 不给正文 / 分数）')
  assert.equal(cands[0].source, 'src1', '`source.id` 必须归一成 `source`')
  assert.deepEqual(cands[0].channels, ['topic', 'intent'])
  // 🔴 Human 2026-10-28：「返回的应该是**位置 + 每一个能力的一句话介绍**」
  assert.equal(cands[0].path, 'capabilities/pre_push_evidence_gate.md', '必须带**位置**')
  assert.ok(cands[0].summary.includes('推送前证据闸门'), '必须带**一句话介绍**（能力用 description）')
  assert.equal(JSON.stringify(cands).includes('SECRET'), false, '🔴 正文 ⛔ 不得进入工具返回')
  assert.equal(cands[1].role, '', 'null role ⇒ 空串（⛔ 不把 null 写进宿主返回）')
  assert.equal(cands[1].path, '', '无路径 ⇒ 空串')
  assert.ok(cands[1].summary.startsWith('Entry #63'),
    '账本/语料类必须**先用 name**（正文开头不能冒充"一句话介绍"）')
  // ② 形状异常不抛（失败透明）
  assert.deepEqual(FC.retrievalCandidatesOf(null), [])
  assert.deepEqual(FC.retrievalCandidatesOf({}), [])
  // ③ 渲染三态：ok 有候选 / ok 零候选 / 非 ok（⛔ 把"失败"说成"没有匹配"）
  const linesOk = FC.retrievalLinesOf({ state: 'ok', candidates: cands, matchedBeforeBudget: 347, channels: ['topic'] })
  assert.ok(linesOk.some(l => l.includes('候选 2')), 'ok 态必须报候选数')
  assert.ok(linesOk.some(l => l.includes('a') && l.includes('src1')), '必须列出候选 id / 来源')
  assert.ok(linesOk.some(l => l.includes('推送前证据闸门')), '渲染里必须有一句话介绍')
  assert.ok(linesOk.some(l => l.includes('capabilities/pre_push_evidence_gate.md')), '渲染里必须有位置')
  assert.ok(linesOk[linesOk.length - 1].includes('不是建议'), '必须声明"候选不是建议"（不判适用性）')
  assert.ok(FC.retrievalLinesOf({ state: 'ok', candidates: [] })[0].includes('候选 0'))
  assert.ok(FC.retrievalLinesOf({ state: 'timeout', candidates: [] })[0].includes('timeout'))
  assert.deepEqual(FC.retrievalLinesOf(null), [])
  // ④ 常量（⚠️ 首版无实测基线 · ⛔ 不得当作已验证；v48 起候选上限 8 → 3）
  assert.ok(FC.WORK_REPORT_RETRIEVAL_TIMEOUT_MS >= 1000 && FC.WORK_REPORT_RETRIEVAL_TIMEOUT_MS <= 8000,
    '等待上限必须在 1–8s（宿主工具超时的安全区内）')
  assert.equal(FC.WORK_REPORT_RETRIEVAL_MAX_CANDIDATES, 3, 'v48：8 → 3（条数是第一杠杆）')
  assert.ok(FC.WORK_REPORT_RETRIEVAL_SUMMARY_CHARS > 0 && FC.WORK_REPORT_RETRIEVAL_SUMMARY_CHARS <= 200,
    '一句话介绍要有上限（防上下文膨胀）')
})

check('S110 R3 卡驱动唤醒：takeover 判据（纯函数）· 每会话上限 1 · 清单六项', () => {
  // ① 标准 takeover 序列：claim A → release B（takeover from A）→ claim B
  const log = [
    '| 12:00 | Executing | claim 占用（session: session-A） | Worker |',
    '| 12:01 | Parked | release 释放（session: session-B） · takeover from session-A · 用户切对话 | Worker |',
    '| 12:01 | Executing | claim 占用（session: session-B） | Worker |',
  ].join('\n')
  const t = FC.takeoverFromLog(log)
  assert.equal(t.victim, 'session-A', '被抢会话 = `takeover from` 后面的 session')
  assert.equal(t.occupant, 'session-B', '现占用者 = 最后一条 claim')
  // ② 自己 release（无 takeover）⇒ null（⛔ 不触发真唤醒）
  const own = [
    '| 12:00 | Executing | claim 占用（session: session-A） | Worker |',
    '| 12:05 | Parked | release 释放（session: session-A） | Worker |',
  ].join('\n')
  assert.equal(FC.takeoverFromLog(own), null, '自己 release ⛔ 不算 takeover')
  // ③ 不完整 / 空 ⇒ null（⛔ 不猜）
  assert.equal(FC.takeoverFromLog('| 12:00 | Executing | claim 占用（session: session-A） | Worker |'), null)
  assert.equal(FC.takeoverFromLog(''), null)
  // ④ 口径常量：每会话 1 次 · 防抖（一次 takeover 会写卡 + .log 两处）
  assert.equal(FC.R3_MAX_PER_SESSION, 1, 'Human 口径：每会话 1 次')
  assert.ok(FC.R3_WAKE_DEBOUNCE_MS >= 500 && FC.R3_WAKE_DEBOUNCE_MS <= 5000, '防抖窗口需覆盖卡 + .log 双写')
  // ⑤ 唤醒正文必须带六项清单（Agent 要能照着做）
  const text = FC.r3WakeText('TASK-20261028-001')
  for (const k of ['INVENTORY', 'ENV', 'PITFALLS', 'State', '探针', 'tests']) {
    assert.ok(text.includes(k), '清单缺项：' + k)
  }
})

check('S111 两步式选词：axes 只收词表值 · 词表文本 · timeout 1500 · stage4 关闭', () => {
  const now = 1793192000000
  // ① 合法值保留 / 非词表值丢弃 / 去重
  const r = FC.buildWorkReport('selftest-s111', {
    what: '做数据分析页面', confirmed: 'user',
    axes: { domain: ['数据', '不存在的域', '数据'], help: ['实现', '乱写'], concern: ['正确性'] },
  }, now)
  assert.equal(r.ok, true)
  assert.deepEqual(r.rep.axes.domain, ['数据'], '非词表值必须丢弃 + 去重')
  assert.deepEqual(r.rep.axes.help, ['实现'], '非词表值必须丢弃')
  assert.deepEqual(r.rep.axes.concern, ['正确性'])
  // ② 不带 axes ⇒ 空轴（旧调用行为不变）
  const r2 = FC.buildWorkReport('selftest-s111', { what: 'x', confirmed: 'user' }, now)
  assert.deepEqual(r2.rep.axes, { domain: [], help: [], concern: [] })
  // ③ 词表文本 = **8 个领域**（供 Agent 选），不再回三维表
  const vt = FC.vocabText()
  for (const v of ['前端', '后端', '数据', '文档', '产品', '环境·运维', '求职·职业', 'AI-OS 自身']) {
    assert.ok(vt.includes(v), '领域词表缺：' + v)
  }
  assert.ok(vt.includes('domain-'), '词表必须给出域能力名（domain-xxx）')
  assert.ok(vt.includes('能力') && vt.includes('capability'), '词表必须告诉 Agent：写进卡上「能力」字段')
  // ④ timeout 收紧到 1500（Human 裁定）· stage4 关闭（代码保留可回退）
  assert.equal(FC.WORK_REPORT_RETRIEVAL_TIMEOUT_MS, 1500)
  assert.equal(FC.STAGE4_ENABLED, false, 'stage4 已按 Human 裁定关闭')
})

check('S112 能力候选后的打开约束：给「打开文件」的动作指向（可被轨迹核对）', () => {
  // ① 约束句：必须要求**打开文件**（否则打开率仍不可核对）+ 保留"不判适用性"语义
  const nudge = FC.retrievalNudgeText()
  assert.ok(nudge.includes('打开对应能力文件'), '约束必须要求打开文件（可机械核对打开率）')
  assert.ok(nudge.includes('适配或任务需要'), 'Human 口径：适配 / 任务需要时')
  assert.ok(nudge.includes('不是建议'), '⛔ 能力不自判适用性：仍由 Agent 判断，Runtime 只点名动作')
  // ② 候选三行格式不变（v31 回归护栏）
  const set = {
    state: 'ok',
    candidates: [{
      id: 'aios.capabilities:demo', source: 'aios.capabilities', role: 'evidence',
      summary: '一句话介绍', path: 'capabilities/demo.md',
    }],
    matchedBeforeBudget: 12,
    channels: ['axis'],
  }
  const lines = FC.retrievalLinesOf(set)
  assert.ok(lines.some(l => l.includes('→ capabilities/demo.md')), '候选仍给位置')
  assert.ok(lines.some(l => l.includes('一句话介绍')), '候选仍给一句话介绍')
  // ③ 末行只可能是两种之一（⛔ 测试不写真实 `.aios`，故不硬断言开关值）
  const tail = lines[lines.length - 1]
  assert.ok(tail === FC.retrievalNudgeText() || tail.includes('这是候选不是建议'),
    '末行必须是「约束句」或「旧展示句」之一，不得两者叠加')
  // ④ v41 回退：不再有"收益 / 覆盖 / 缺口"三版诱导 —— 约束句只做「打开文件」的动作指向
  const text = FC.retrievalNudgeText()
  assert.ok(!text.includes('更稳妥'), 'v41 回退：不得再有"收益"诱导')
  assert.ok(!text.includes('少返工'), 'v41 回退：不得再有"覆盖"诱导')
  assert.ok(!text.includes('可能漏掉'), 'v41 回退：不得再有"缺口"诱导')
  assert.equal(typeof FC.retrievalNudgeStyle, 'undefined', 'v41：style 选择器已删除（诱导交给工具出现时的注入）')
})

// 🔴 v44（2026-10-30 · Human 裁定「有过注入后就将开关关了」）：R3 唤醒 = **一次性触发器**。
//    判据：成功注入一次（`state:'ok'`）后，`.aios/r3-wake.json` 必须被写回 `enabled:false`；
//    且**保留**文件里的其它字段（合并更新，⛔ 整体重写会误清用户手写的备注/其它键）。
//    ⚠️ 隔离：`disarmR3Wake()` 走 `aiosStateDir()` ⇒ 用 `AIOS_STATE_DIR` 指向 scratch 临时目录，
//       ⛔ 不碰真实 `.aios/r3-wake.json`（同 S90 的隔离纪律）。
check('S113 R3 唤醒 fire-once：成功一次后开关写回默认关（保留其它字段）', () => {
  const T = SCRATCH + '/_selftest_r3_fire_once'
  const prev = process.env.AIOS_STATE_DIR
  rmSync(T, { recursive: true, force: true })
  mkdirSync(T, { recursive: true })
  process.env.AIOS_STATE_DIR = T
  try {
    const file = T + '/r3-wake.json'
    writeFileSync(file, JSON.stringify({ enabled: true, note: 'user note', other: 1 }), 'utf8')
    // ① 成功注入一次 ⇒ 写回默认关
    assert.equal(FC.disarmR3Wake(), true, 'disarm 必须成功')
    const after = JSON.parse(readFileSync(file, 'utf8'))
    assert.equal(after.enabled, false, '🔴 成功一次后开关必须写回 enabled:false（回到默认关）')
    assert.equal(after.note, 'user note', '⚠️ 不得丢失其它字段（合并更新 · data-change-safety）')
    assert.equal(after.other, 1, '⚠️ 不得丢失其它字段')
    // ② 文件缺失 ⇒ 仍要能写回默认关（fail-closed；⛔ 不因读不到就不关）
    rmSync(file, { force: true })
    assert.equal(FC.disarmR3Wake(), true, '文件缺失时也要能写回默认关')
    assert.equal(JSON.parse(readFileSync(file, 'utf8')).enabled, false)
    // ③ 幂等：重复调用仍成功且值为 false（⛔ 不抛）
    assert.equal(FC.disarmR3Wake(), true)
    assert.equal(JSON.parse(readFileSync(file, 'utf8')).enabled, false)
  } finally {
    if (prev === undefined) delete process.env.AIOS_STATE_DIR
    else process.env.AIOS_STATE_DIR = prev
    rmSync(T, { recursive: true, force: true })
  }
})

check('S114 缺口触发：单次工具失败即注入（gap · 每会话一次）', () => {
  // ① streak=1 ⇒ gap 触发（旧 stuck 要连败 2 次 ⇒ 最该提示的时机没提示）
  const slot = { sent: new Set(), count: 0, lastHasEdit: false, lastFailStreak: 0, lastNamedTurn: null }
  const e1 = FC.detectEvents(
    { hasEdit: false, activity: [{ ok: true }, { ok: false }], cardEdits: 0, intentText: '', turn: 1 }, slot)
  assert.ok(e1.includes('gap'), 'streak=1 必须触发 gap（缺口触发）')
  assert.equal(e1.includes('stuck'), false, 'streak=1 仍⛔ 触发 stuck')
  assert.equal(FC.shouldPublishEvent(slot, 'gap', 20), true)
  // ② 每会话一次（Set 去重）
  assert.equal(FC.shouldPublishEvent(slot, 'gap', 20), false)
  // ③ 无失败 ⇒ 不触发
  const slot2 = { sent: new Set(), count: 0, lastHasEdit: false, lastFailStreak: 0, lastNamedTurn: null }
  const e2 = FC.detectEvents(
    { hasEdit: false, activity: [{ ok: true }], cardEdits: 0, intentText: '', turn: 1 }, slot2)
  assert.equal(e2.includes('gap'), false, '无失败 ⛔ 触发 gap')
  // ④ 文案：点名 auto_capability + 短
  const t = FC.eventHintText('gap')
  assert.ok(t.includes('auto_capability'), 'gap 文案必须点名 auto_capability')
  assert.ok(t.includes('请使用它'), 'v45 起文案须带祈使句（Human 2026-10-30 要求）')
  assert.ok(t.length <= 200, 'gap 文案须短（每会话最多几条）')
})

check('S115 T7′ 同一问题第 2 次：词面重合 ≥3 且两条都 ≥5 token（⛔ 无语义判断）', () => {
  const long = '把这个作品集站点的首页改一下，加上能力区和证据区，保持验证全绿'
  assert.equal(FC.isRepeatQuestion('', long), false, '空历史 ⛔ 触发')
  assert.equal(FC.isRepeatQuestion(long, long + '，另外还要更新关于页'), true, '高度重合 ⇒ 触发')
  assert.equal(
    FC.isRepeatQuestion('帮我看看简历的一页排版和字体大小', '把 Dify 的测试改成 SQLite 真实行并跑 pytest'),
    false, '不同问题 ⛔ 触发')
  // token 口径：中文 2-gram + 英文/数字词（≥3）
  const t = FC.tokenSetOf('SQLite 真实行')
  assert.ok(t.has('sqlite'), '英文词入集')
  assert.ok(t.has('真实'), '中文 2-gram 入集')
})

check('S116 T2 缺口分类：事实型失败（路径/重读/参数）不触发 gap', () => {
  const mk = () => ({ sent: new Set(), count: 0, lastHasEdit: false, lastFailStreak: 0, lastNamedTurn: null })
  const evFactual = FC.detectEvents(
    { hasEdit: false, activity: [{ ok: false }], cardEdits: 0, intentText: '', turn: 1, lastFailKind: 'factual' }, mk())
  assert.equal(evFactual.includes('gap'), false, 'factual ⛔ gap')
  const evKnowledge = FC.detectEvents(
    { hasEdit: false, activity: [{ ok: false }], cardEdits: 0, intentText: '', turn: 1, lastFailKind: 'knowledge' }, mk())
  assert.ok(evKnowledge.includes('gap'), 'knowledge ⇒ gap')
  // 分类函数（⛔ 不记正文 · 只回分类）
  assert.equal(FC.failKindOf({ isError: true, content: [{ type: 'text', text: 'Cannot find path D:/x' }] }), 'factual')
  assert.equal(FC.failKindOf({ isError: true, content: [{ type: 'text', text: 'AssertionError: 1 != 2' }] }), 'knowledge')
  assert.equal(FC.failKindOf({ isError: false }), null)
  assert.equal(FC.failKindOf({ isError: true }), 'knowledge', '拿不到内容 ⇒ 保守按知识型（仍允许提示）')
})

check('S117 T5 注入限额：连续 2 条注入未换来检索 ⇒ 停发', () => {
  assert.equal(FC.INJECT_MAX_WITHOUT_RETRIEVAL, 2)
  assert.equal(FC.injectAllowedByBudget(0), true)
  assert.equal(FC.injectAllowedByBudget(1), true)
  assert.equal(FC.injectAllowedByBudget(2), false, '连续 2 条 ⇒ 停发')
})

check('S118 返回层：候选上限 3 + 按 what 词面重合重排（稳定 · ⛔ 不删候选）', () => {
  assert.equal(FC.WORK_REPORT_RETRIEVAL_MAX_CANDIDATES, 3, '8 → 3（9 份访谈 7 份指向条数）')
  const mk = (id, summary, path) => ({ id, source: 'aios.capabilities', role: 'evidence', channels: [], path, summary })
  const cands = [
    mk('aios.capabilities:frontend-ui', '做前端页面 / 组件', 'capabilities/frontend-ui.md'),
    mk('aios.capabilities:self-verification', '没人复核时用可运行检查证明做完', 'capabilities/self-verification.md'),
    mk('aios.capabilities:doc_standards', '决定文档放哪层', 'capabilities/doc_standards.md'),
  ]
  const ranked = FC.rerankCandidatesByWhat(cands, '验收 v47 注入是否生效，用可运行检查证明做完')
  assert.equal(ranked.length, cands.length, '⛔ 不删候选')
  assert.equal(ranked[0].id, 'aios.capabilities:self-verification', '与 what 重合最多的排第一')
  const same = FC.rerankCandidatesByWhat(cands, '')
  assert.deepEqual(same.map(c => c.id), cands.map(c => c.id), '空 what ⇒ 保持原顺序')
  assert.equal(FC.rerankCandidatesByWhat([cands[0]], '任意').length, 1)
})

check('S119 经验召回：UNKNOWN_TOOL/知识型触发 · 事实型不触发 · 限额与去重（纯函数）', () => {
  // ① 触发分类
  assert.equal(FC.recallTriggerOf({ isError: true, content: [{ type: 'text', text: 'Error: UNKNOWN_TOOL: tool "x" not found' }] }), 'unknown-tool')
  assert.equal(FC.recallTriggerOf({ isError: true, content: [{ type: 'text', text: 'web fetch failed: TypeError: fetch failed' }] }), 'knowledge-error')
  assert.equal(FC.recallTriggerOf({ isError: true, content: [{ type: 'text', text: 'Error: old_string not found' }] }), null, '事实型失败不触发（v47 T2 口径）')
  // 权限/沙箱族失败**也**触发经验召回（独立 trigger，不改 failKindOf）
  assert.equal(FC.recallTriggerOf({ isError: true, content: [{ type: 'text', text: 'PermissionError: [Errno 13] Permission denied' }] }), 'permission-error', 'v49c：PermissionError/Errno 13 必须触发')
  assert.equal(FC.recallTriggerOf({ isError: true, content: [{ type: 'text', text: 'pwsh: WinError 5 拒绝访问' }] }), 'permission-error', 'v49c：WinError 5/拒绝访问 必须触发')
  assert.equal(FC.recallTriggerOf({ isError: true, content: [{ type: 'text', text: 'Error: old_string not found' }] }), null, 'v49c 不改变其它事实型失败分类')
  // exec 非零退出未标 isError（P62 · ok:true）但文本含 [exit code: N] + 权限特征
  assert.equal(FC.recallTriggerOf({ isError: false, content: [{ type: 'text', text: 'stdout...\n[exit code: 3]\n[t.py] PermissionError: [Errno 13] Permission denied' }] }), 'exec-permission-error', 'v49d：ok:true + 非零退出 + 权限特征 必须触发')
  assert.equal(FC.recallTriggerOf({ isError: false, content: [{ type: 'text', text: 'all good\n[exit code: 0]' }] }), null, 'v49d：exit 0 不触发')
  assert.equal(FC.recallTriggerOf({ isError: false, content: [{ type: 'text', text: '[exit code: 1] some other error' }] }), null, 'v49d：非权限特征不触发')
  // 🔴 v49e（实测：子 agent 工具结果用 `EXITCODE: 1`，不是 `[exit code: 1]`）
  assert.equal(FC.recallTriggerOf({ isError: false, content: [{ type: 'text', text: 'OUT: PermissionError: [Errno 13] Permission denied\nOUT: FAILED\nEXITCODE: 1\n' }] }), 'exec-permission-error', 'v49e：EXITCODE: N 形式也必须触发')
  assert.equal(FC.recallTriggerOf({ isError: false, content: [{ type: 'text', text: 'all good\nEXITCODE: 0\n' }] }), null, 'v49e：EXITCODE: 0 不触发')
  assert.equal(FC.recallTriggerOf({ isError: false }), null)
  assert.equal(FC.recallTriggerOf(null), null)
  // ② 查询构造：失败文本 + 参数路径
  const q = FC.buildExperienceQuery('read', { path: 'D:/x/y.md' }, { isError: true, content: [{ text: 'UNKNOWN_TOOL' }] })
  assert.ok(q.includes('UNKNOWN_TOOL') && q.includes('y.md'), q)
  assert.ok(!q.includes('D:/x'), 'v49j：绝对路径目录部分必须剥离（保留末段）')
  assert.ok(!q.includes('read'), 'v49g：通用工具名（read）不入 query（避免与语料字段名撞词）')
  const qUnknown = FC.buildExperienceQuery('my_custom_tool', {}, { isError: true, content: [{ text: 'UNKNOWN_TOOL' }] })
  assert.ok(qUnknown.includes('my_custom_tool'), '未知工具名保留（有信息量）')
  // 长结果文本 clip(160) 会截掉 PermissionError ⇒ 查询必须优先含权限特征的行
  const longJunk = 'OUT: ' + 'x'.repeat(180) + '\nOUT: PermissionError: [Errno 13] Permission denied\nEXITCODE: 1'
  const q2 = FC.buildExperienceQuery('pwsh', {}, { isError: false, content: [{ type: 'text', text: longJunk }] })
  assert.ok(q2.includes('PermissionError'), 'v49f：权限行必须进 query（否则 experience_push 0 命中）: ' + q2)
  // ③ 渲染：≤2 条 · 带 title/file · 空 hits ⇒ ''
  const line = FC.renderExperienceRecall({ hits: [
    { title: 'PITFALLS P57', content: 'Chrome 无头导出需 full access', file: 'task_cards/memory/PITFALLS.md' },
    { title: 'PITFALLS P40', content: 'pytest 0o700 目录不可列', file: 'task_cards/memory/PITFALLS.md' },
    { title: 'PITFALLS P99', content: '第三条不该出现', file: '' },
  ] })
  assert.ok(line.includes('PITFALLS P57') && line.includes('（task_cards/memory/PITFALLS.md）'), line)
  assert.ok(!line.includes('P99'), '⛔ 只注入前 2 条')
  assert.equal(FC.renderExperienceRecall({ hits: [] }), '')
  // ④ 限额与去重
  assert.equal(FC.recallAllowed(undefined, 0, 'q'), true)
  assert.equal(FC.recallAllowed({ count: 3, lastTurn: 0, lastQuery: 'q' }, 5, 'q2'), false, '会话上限 3')
  assert.equal(FC.recallAllowed({ count: 1, lastTurn: 5, lastQuery: 'q' }, 6, 'q2'), false, '相邻 <2 turn 不发')
  assert.equal(FC.recallAllowed({ count: 1, lastTurn: 5, lastQuery: 'q' }, 7, 'q2'), true)
  assert.equal(FC.recallAllowed(undefined, 0, ''), false, '空 query 不召回')
})

check('S120 经验过程匹配器（纯函数）：OR 语义 · semantic 跳过 · 空 when 不匹配', () => {
  const rules = [
    { id: 'P61', when: { tool: ['task_card'], cmd: 'claim', error: 'State=Created' }, inject: 'x', semantic: false },
    { id: 'P40', when: { tool: ['pytest'], error: 'WinError 5|PermissionError' }, inject: 'y', semantic: false },
    { id: 'P4', when: {}, inject: 'z', semantic: true },
  ]
  const hit1 = FC.matchExperienceRules({ tool: 'task_card', cmd: 'python tools/task_card.py claim X', error: '报错 State=Created 不可占用' }, rules)
  assert.deepEqual(hit1.map(r => r.id), ['P61'], 'tool/cmd/error 命中')
  const hit2 = FC.matchExperienceRules({ tool: 'pytest', error: 'PermissionError [WinError 5]' }, rules)
  assert.deepEqual(hit2.map(r => r.id), ['P40'], 'error 正则命中')
  assert.equal(FC.matchExperienceRules({ tool: 'read' }, rules).length, 0, '不相关工具不命中')
  assert.equal(
    FC.matchExperienceRules({ tool: 'task_card', cmd: 'claim', error: 'State=Created' },
      [{ id: 'P4', when: {}, inject: 'z', semantic: true }]).length, 0, 'semantic 跳过')
  // OR 语义：只给 tool（无 error）也应命中 P40
  assert.deepEqual(FC.matchExperienceRules({ tool: 'pytest' }, rules).map(r => r.id), ['P40'])
})

check('S94 原子替换：成功不留临时件；**失败不破坏目标、也不留临时件**', () => {
  clearFC()
  assert.equal(FC.writeFocusCard(mkState([CARD_A]), 'selftest-fc-d', 'D:/x'), 'written')
  // ① 原子替换的必要条件是"临时件与目标同目录" ⇒ 成功路径不得残留 `.tmp-`
  assert.deepEqual(fcTmp(), [], '成功写入后不得残留临时件')
  // ② 失败路径：把目标位换成**目录** ⇒ `renameSync` 必失败
  rmSync(FC_FILE, { recursive: true, force: true })
  mkdirSync(FC_FILE, { recursive: true })
  const r = FC.writeFocusCard(mkState([CARD_B]), 'selftest-fc-d', 'D:/x') // 语义芯变了 ⇒ 一定会尝试写
  assert.equal(r, 'failed', 'rename 到目录必失败 ⇒ 必须**如实**返回 failed（⛔ 不抛、⛔ 不谎报成功）')
  assert.ok(existsSync(FC_FILE), '失败后原目标必须**保持存在**（⛔ 不得被删除/截断）')
  assert.deepEqual(fcTmp(), [], '🔴 失败路径必须清理临时件（⛔ 不污染目录）')
  rmSync(FC_FILE, { recursive: true, force: true })
})

check('S95 TTL 语义与路径隔离：只碰临时目录，⛔ 不触真实运行数据', () => {
  assert.equal(FC.focusCardFile(), FC_FILE, '`AIOS_FOCUS_CARD` 必须优先（隔离自测的唯一入口）')
  assert.ok(FC_FILE.startsWith(SCRATCH), '隔离件必须落在 scratch/ 内')
  assert.ok(FC_FILE !== REAL_FC, '隔离路径必须与真实权威位**不同**')
  // 🔴 **反向**判据：本自测**不得**创建/修改真实运行数据
  //    （初版漏洞正在此处：env 设在文件尾部 ⇒ 早期用例写进了真实位）
  const realNow = existsSync(REAL_FC) ? readFileSync(REAL_FC, 'utf8') : null
  assert.equal(realNow, REAL_FC_BEFORE,
    '🔴 隔离自测**绝不得**创建或修改真实 `.aios/focus-card.json`（A6）')
  assert.equal(FC.FOCUS_CARD_TTL_MS, 600_000,
    'TTL 首版值 = 10 分钟（Human 2026-10-15 裁定）· ⚠️ **无实测基线**，⛔ 不得当作已验证')
  assert.equal(FC.FOCUS_CARD_SCHEMA, 'focus-card/v1', 'schema 常量必须与契约逐字一致')
})

check('S96 失败透明：异常不抛到调用方，只累加 failed 计数', () => {
  const prevEnv = process.env.AIOS_FOCUS_CARD
  process.env.AIOS_FOCUS_CARD = FC_DIR + '/no-such-dir/fc.json' // 父目录不存在 ⇒ 写必失败
  try {
    const f0 = FC.FOCUS_CARD_STATS.failed
    let threw = false
    let r = null
    try { r = FC.writeFocusCard(mkState([CARD_A]), 'selftest-fc-e', 'D:/x') } catch { threw = true }
    assert.equal(threw, false, '🔴 写失败**绝不得**抛到调用方（宿主行为不可被影响）')
    assert.equal(r, 'failed', '必须如实返回 failed')
    assert.equal(FC.FOCUS_CARD_STATS.failed, f0 + 1, 'failed 计数必须递增（供诊断）')
  } finally {
    process.env.AIOS_FOCUS_CARD = prevEnv
  }
})

check('S97 写入计数四态齐备（written / unchanged / noCard / failed 各自独立累加）', () => {
  const s = FC.FOCUS_CARD_STATS
  assert.deepEqual(Object.keys(s).sort(), ['failed', 'noCard', 'unchanged', 'written'],
    '计数必须是这四个键（与设计 §六 A6「命中率可按类取数」对齐）')
  assert.ok(s.written > 0, 'written 应已累加')
  assert.ok(s.unchanged > 0, 'unchanged 应已累加')
  assert.ok(s.noCard > 0, 'noCard 应已累加')
  assert.ok(s.failed > 0, 'failed 应已累加')
  // 收尾：清隔离目录（⛔ 不碰真实位）
  rmSync(FC_DIR, { recursive: true, force: true })
})

// **接线**用例 ────────────────────────────────────────
//   缺陷形态（P69）：v49 段用 `s`（前一个 try 块的块级 const）⇒ ReferenceError ⇒ 被 catch 静默吞掉
//   ⇒（a）经验召回永不触发（b）连带吞掉同一次 post-execute 的整段注入（v26 event-hint 等）。
//   ⚠️ 为什么既有 S119 抓不到：本文件顶部设 `AIOS_EXPERIENCE_RECALL='off'` ⇒ 5829 的 `s` 永不求值
//      ⇒ **测试覆盖的只是"默认关路径"，接线 0 覆盖**。本用例**临时解除短路** + 隔离 state 位。
checkAsync('S121 接线：不短路时 knowledge 失败 ⇒ 有 ev=experience-recall 且不吞 inject', async () => {
  const V49 = SCRATCH + '/_selftest_v49'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevOff = process.env.AIOS_EXPERIENCE_RECALL
  const prevInject = process.env.AIOS_INJECT_PROBE
  const prevRemind = process.env.AIOS_REMINDER_PROBE
  rmSync(V49, { recursive: true, force: true })
  mkdirSync(V49, { recursive: true })
  // ① 隔离 state 位（v49 只从 aiosStateDir()/experience_recall.json 读开关）
  process.env.AIOS_STATE_DIR = V49
  delete process.env.AIOS_EXPERIENCE_RECALL           // ② 解除短路（接线才真的执行）
  process.env.AIOS_INJECT_PROBE = V49 + '/inject_probe.json'   // ③ Step B′ 早退门要有 inject 开
  writeFileSync(process.env.AIOS_INJECT_PROBE, JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }))
  process.env.AIOS_REMINDER_PROBE = V49 + '/no_reminder.json'  // ④ 不读真实 reminder 开关
  writeFileSync(V49 + '/experience_recall.json', JSON.stringify({ enabled: true }))
  const AG = agent('selftest-v49-main', { delegationDepth: 0 })
  try {
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('验证 v49 接线')] })
    const execP = { callId: 'selftest-v49-call', name: 'web_fetch', arguments: { url: 'https://x.invalid/a' }, agent: AG }
    wf('tools/pre-execute', execP)
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    const result = { isError: true, content: [{ type: 'text', text: 'Error: web fetch failed: TypeError: fetch failed' }] }
    const out = await h(execP, result, () => ({ kind: 'accept' }))
    assert.ok(out, '必须返回 downstream（⛔ 不得因注入段异常而改变工具结果）')
    const rec = records().filter(r => r.ev === 'experience-recall' && r.session === 'selftest-v49-main')
    assert.equal(rec.length, 1, '🔴 接线必须真的触发（缺陷形态：0 条 · 短路掩盖）')
    assert.equal(rec[0].trigger, 'knowledge-error', '必须是知识型失败触发')
    assert.ok(['ok', 'spawn-error', 'child-error', 'empty-stdout', 'timeout', 'bad-json'].includes(rec[0].state),
      'state 必须是合法读数值（隔离环境 spawn 可能失败，但必须**如实记录**）')
    const inj = records().filter(r => r.ev === 'inject' && r.session === 'selftest-v49-main')
    assert.ok(inj.length >= 1, '🔴 同一次 post-execute 的 v26 注入不得被吞掉（缺陷形态：0 条）')
    // 第二处缺陷：entry 必须解析到 `tools/experience_push.py`（修复前解析到不存在的 `tools/probes/`）
    assert.ok(existsSync(FC.resolveToolScript('experience_push.py')),
      'entry 必须指向真实存在的工具脚本（修复前 = tools/probes/experience_push.py，不存在 ⇒ 恒 spawn-error）')
    // **子会话也必须能触发** —— 此前硬编码 `identity === 'main'`，
    //   导致所有子 agent 任务经验召回 0 触发（且被误读为"任务没有触发面"）。
    const SUB2 = agent('selftest-v49-sub', { origin: 'subagent', delegationDepth: 1, parentSession: 'selftest-v49-main' })
    emit1('agent/session-start', { agent: SUB2, source: 'startup' })
    wf('agent/pre-step', { agent: SUB2, turn: 1, step: 1, messages: [userMsg('子会话验证经验召回')] })
    const execP2 = { callId: 'selftest-v49-sub-call', name: 'web_fetch', arguments: { url: 'https://x.invalid/b' }, agent: SUB2 }
    wf('tools/pre-execute', execP2)
    const out2 = await h(execP2, result, () => ({ kind: 'accept' }))
    assert.ok(out2, '子会话：必须返回 downstream')
    const recSub = records().filter(r => r.ev === 'experience-recall' && r.session === 'selftest-v49-sub')
    assert.equal(recSub.length, 1, '🔴 v49b：子会话必须能触发经验召回（缺陷形态：0 条 · identity 门挡住）')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevOff === undefined) delete process.env.AIOS_EXPERIENCE_RECALL; else process.env.AIOS_EXPERIENCE_RECALL = prevOff
    if (prevInject === undefined) delete process.env.AIOS_INJECT_PROBE; else process.env.AIOS_INJECT_PROBE = prevInject
    if (prevRemind === undefined) delete process.env.AIOS_REMINDER_PROBE; else process.env.AIOS_REMINDER_PROBE = prevRemind
    try { rmSync(V49, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

// 权限/沙箱族的**接线**用例 ─────────────
//   背景：FACTUAL_FAIL_RE 含 拒绝访问/access denied/WinError 5 ⇒ 权限失败被判事实型 ⇒ v49 永不触发，
//   权限族卡无法"自然出现"。v49c 在经验召回入口加独立 trigger `permission-error`（⛔ 不改 failKindOf）。
//   本用例验证：权限失败真的走到 spawn + 留下 `ev=experience-recall{trigger:"permission-error"}`。
checkAsync('S122 接线：权限/沙箱失败 ⇒ trigger=permission-error（不改 fact 口径）', async () => {
  const V49C = SCRATCH + '/_selftest_v49c'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevOff = process.env.AIOS_EXPERIENCE_RECALL
  const prevInject = process.env.AIOS_INJECT_PROBE
  const prevRemind = process.env.AIOS_REMINDER_PROBE
  rmSync(V49C, { recursive: true, force: true })
  mkdirSync(V49C, { recursive: true })
  process.env.AIOS_STATE_DIR = V49C
  delete process.env.AIOS_EXPERIENCE_RECALL
  process.env.AIOS_INJECT_PROBE = V49C + '/inject_probe.json'
  writeFileSync(process.env.AIOS_INJECT_PROBE, JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }))
  process.env.AIOS_REMINDER_PROBE = V49C + '/no_reminder.json'
  writeFileSync(V49C + '/experience_recall.json', JSON.stringify({ enabled: true }))
  const AG = agent('selftest-v49c-main', { delegationDepth: 0 })
  try {
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('验证 v49c 权限族触发')] })
    const execP = { callId: 'selftest-v49c-call', name: 'pwsh', arguments: { command: 'python t.py' }, agent: AG }
    wf('tools/pre-execute', execP)
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    // 用**事实型**文本（含 WinError 5/拒绝访问 ⇒ failKindOf=factual）才能证明 v49c 新增了触发
    const result = { isError: true, content: [{ type: 'text', text: 'pwsh: WinError 5 拒绝访问: D:/x/hello.txt' }] }
    const out = await h(execP, result, () => ({ kind: 'accept' }))
    assert.ok(out, '必须返回 downstream（⛔ 不得因注入段异常而改变工具结果）')
    const rec = records().filter(r => r.ev === 'experience-recall' && r.session === 'selftest-v49c-main')
    assert.equal(rec.length, 1, '🔴 v49c 接线必须真的触发（缺陷形态：0 条 = 仍是事实型不触发）')
    assert.equal(rec[0].trigger, 'permission-error', 'trigger 必须是 permission-error')
    // ⛔ 行为不变：权限失败**仍是** fact
    assert.equal(FC.failKindOf(result), 'factual', 'v49c 不得改变 failKindOf（权限失败仍为 factual）')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevOff === undefined) delete process.env.AIOS_EXPERIENCE_RECALL; else process.env.AIOS_EXPERIENCE_RECALL = prevOff
    if (prevInject === undefined) delete process.env.AIOS_INJECT_PROBE; else process.env.AIOS_INJECT_PROBE = prevInject
    if (prevRemind === undefined) delete process.env.AIOS_REMINDER_PROBE; else process.env.AIOS_REMINDER_PROBE = prevRemind
    try { rmSync(V49C, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

// 触发/查询修复的**纯函数**用例 ────────
//   ⛔ 不 spawn / 不写盘；只断言判据行为（端到端归重启后真实任务复核）。
check('S123 退出标记解析器：EXIT=1 / exit2=1 / EXITCODE=0 等真实格式', () => {
  const mk = t => ({ isError: false, content: [{ type: 'text', text: t }] })
  assert.equal(FC.recallTriggerOf(mk('hello\nexit=0\nexit2=1\n[stderr]\nPermissionError: [WinError 5] 拒绝访问: D:/x'), 'pwsh'),
    'exec-permission-error', 'exit2=1 + 权限特征 ⇒ 必须触发（v49e 漏报形态）')
  assert.equal(FC.recallTriggerOf(mk('EXIT=1\nPermissionError: [Errno 13] Permission denied'), 'pwsh'),
    'exec-permission-error', 'EXIT=1（等号）必须识别')
  assert.equal(FC.recallTriggerOf(mk('EXITCODE=0\nPermissionError: [Errno 13] Permission denied'), 'pwsh'),
    null, 'EXITCODE=0 非零条件不满足 ⇒ 不得触发')
  assert.equal(FC.recallTriggerOf(mk('[exit code: 1]\nPermissionError: 拒绝访问'), 'pwsh'),
    'exec-permission-error', '旧格式（v49d/e）保持（v49h 起须带错误上下文）')
})

check('S124 来源门/形态门：read 结果与文件转储不算执行失败（R2 误触发）', () => {
  const dump = {
    isError: false,
    content: [{ type: 'text', text: '<path>D:/x/PITFALLS.md</path>\n<type>file</type>\n<content>\nP12 PermissionError\n[exit code: 1]\n</content>' }],
  }
  assert.equal(FC.recallTriggerOf(dump, 'read'), null, 'read + 文件转储 ⇒ 不得判 exec-permission-error')
  assert.equal(FC.recallTriggerOf(dump, 'pwsh'), null, '形态门：<path><content> 文件转储 ⇒ 不触发')
  const execLike = { isError: false, content: [{ type: 'text', text: '[exit code: 1]\nPermissionError: 拒绝访问' }] }
  assert.equal(FC.recallTriggerOf(execLike, ''), 'exec-permission-error', 'tool 名未知 ⇒ 保留旧行为（兼容旧调用）')
  assert.equal(FC.recallTriggerOf(execLike, 'read'), null, 'read 显式来源 ⇒ 跳过')
})

check('S125 召回专用事实型：读二进制失败不触发，且 failKindOf 口径不变', () => {
  const r = { isError: true, content: [{ type: 'text', text: 'Error: cannot read "D:\\\\AI-os\\\\work\\\\real-r3\\\\test-output-utf8.log": binary file' }] }
  assert.equal(FC.recallTriggerOf(r, 'read'), null, '读二进制/非文本 = 事实型 ⇒ 不触发经验召回（R3 误报）')
  assert.equal(FC.failKindOf(r), 'knowledge', '⛔ failKindOf 不动（v47 T2 口径原样）')
  const k = { isError: true, content: [{ type: 'text', text: 'Error: web fetch failed: TypeError: fetch failed' }] }
  assert.equal(FC.recallTriggerOf(k, 'web_fetch'), 'knowledge-error', '真正的知识型失败仍触发（行为不变）')
})

check('S126 query 归一：去重 / 判别词优先 / 剥离仓库路径 / 通用工具名不入', () => {
  const r = {
    isError: true,
    content: [{ type: 'text', text: 'Get-CimInstance : 拒绝访问\nGet-CimInstance : 拒绝访问\nHRESULT 0x80041003 PermissionDenied' }],
  }
  const q = FC.buildExperienceQuery('pwsh', { command: 'Get-CimInstance Win32_Process -Filter "ProcessId=$PID"' }, r)
  assert.ok(!q.includes('<repo>'), 'query 不得含仓库绝对路径')
  assert.ok(q.includes('HRESULT') || q.includes('0x80041003'), '判别词必须保留')
  assert.ok(!q.startsWith('pwsh '), 'exec 通用工具名不入 query')
  assert.equal((q.match(/Get-CimInstance : 拒绝访问/g) || []).length, 1, '重复权限行必须去重')
  const r2 = { isError: true, content: [{ type: 'text', text: 'Error: cannot read "D:\\\\AI-os\\\\work\\\\real-r3\\\\x.log": binary file' }] }
  const q2 = FC.buildExperienceQuery('read', {}, r2)
  assert.ok(!q2.includes('AI-os'), '路径剥离：不得含 AI-os')
  assert.ok(!q2.startsWith('read '), 'read 工具名不入 query')
  assert.ok(q2.includes('binary') || q2.includes('cannot read'), '错误签名仍保留')
})

// exec 误报的「错误上下文门」──────
check('S127 错误上下文门：exec 输出嵌文档内容不算执行失败（V3 误报）', () => {
  // V3 实测形态：pwsh 打印 PITFALLS 预览 —— 正文含 P57「拒绝访问」+ P66「[exit code: 1]」，但命令成功
  const docPreview = {
    isError: false,
    content: [{ type: 'text', text: 'P57 | Chrome 无头导出在 workspace-write 沙箱下起不来\r\nERROR crashpad_client_win.cc OpenProcess 拒绝访问 (0x5)\r\n...\r\nP66 | `[exit code: 1]` 被截断\r\n\r\nexit=0\r\n' }],
  }
  assert.equal(FC.recallTriggerOf(docPreview, 'pwsh'), null, '文档预览（无错误上下文）⇒ 不得判 exec-permission-error')
  // 真实失败（含 [stderr]/Traceback/PermissionError:）仍触发
  const realFail = { isError: false, content: [{ type: 'text', text: 'hello\nexit=0\nexit2=1\n[stderr]\nPermissionError: [WinError 5] 拒绝访问' }] }
  assert.equal(FC.recallTriggerOf(realFail, 'pwsh'), 'exec-permission-error', '真实失败（[stderr]）仍触发')
  const realFail2 = { isError: false, content: [{ type: 'text', text: 'EXIT=1\nPermissionError: [Errno 13] Permission denied' }] }
  assert.equal(FC.recallTriggerOf(realFail2, 'pwsh'), 'exec-permission-error', 'PermissionError: 亦算错误上下文')
})

// 权限族失败丢弃命令参数 ──────
check('S128 权限族失败丢弃命令参数（V1 误报：unittest 命中无关台账）', () => {
  const r = { isError: false, content: [{ type: 'text', text: 'PermissionError: [WinError 5] 拒绝访问\n[exit code: 1]' }] }
  const q = FC.buildExperienceQuery('pwsh', { command: 'python -m unittest -v' }, r)
  assert.ok(!q.includes('unittest'), '权限族失败时命令参数不得入 query（避免与错误签名竞争）')
  assert.ok(q.includes('PermissionError') || q.includes('拒绝访问'), '错误签名必须保留')
  // ⛔ 非权限场景仍保留命令上下文（为 unknown-tool / 知识型失败留路）
  const r2 = { isError: true, content: [{ type: 'text', text: 'Error: web fetch failed' }] }
  const q2 = FC.buildExperienceQuery('web_fetch', { command: 'curl https://x.invalid' }, r2)
  assert.ok(q2.includes('curl'), '非权限场景仍保留命令上下文（留路）')
})

// 任意绝对路径剥离 ──────
check('S129 任意绝对路径剥离（V1 终验）：临时目录 token 不得进 query', () => {
  const s = FC.stripRepoPaths("PermissionError: [WinError 5] 拒绝访问: 'D:\\AI\\scratch\\tmp\\dsh-7D6gMQ\\tmpz78it9cl'")
  assert.ok(!s.includes('scratch') && !s.includes('dsh-7D6gMQ'), '目录 token 必须剥离: ' + s)
  assert.ok(s.includes('tmpz78it9cl'), '保留末段文件名: ' + s)
  // repr 双反斜杠形态
  const s2 = FC.stripRepoPaths('D:\\\\AI\\\\scratch\\\\tmp\\\\dsh-x\\\\tmpz')
  assert.ok(!s2.includes('scratch'), '双反斜杠形态也要剥: ' + s2)
})

// R3 接手检查（claim 后向前一个「不同会话」注入）──────
check('S130 R3 接手检查：前一个「不同会话」判定（同一会话重占不注入）', () => {
  const row = (t, st, op, s) => `| ${t} | ${st} | ${op}（session: ${s}） | Worker |`
  const multi = [row('01:00', 'Executing', 'claim 占用', 'A'), row('01:10', 'Parked', 'release 释放', 'A'), row('02:00', 'Executing', 'claim 占用', 'B')].join('\n')
  assert.equal(FC.previousOccupantOf(multi, 'B'), 'A', '前一手是不同会话 ⇒ 返回 A')
  // 同一会话 claim 两次（A claim → release → A claim 当前 A）⇒ 无不同会话前手 ⇒ 不注入
  const sameAgain = [row('01:00', 'Executing', 'claim 占用', 'A'), row('01:10', 'Parked', 'release 释放', 'A'), row('02:00', 'Executing', 'claim 占用', 'A')].join('\n')
  assert.equal(FC.previousOccupantOf(sameAgain, 'A'), null, '同一会话重占 ⇒ 不注入')
  // 前手多次 claim 仍返回同一 A
  const aTwice = [row('01:00', 'Executing', 'claim 占用', 'A'), row('01:10', 'Parked', 'release 释放', 'A'), row('01:20', 'Executing', 'claim 占用', 'A'), row('01:30', 'Parked', 'release 释放', 'A'), row('02:00', 'Executing', 'claim 占用', 'B')].join('\n')
  assert.equal(FC.previousOccupantOf(aTwice, 'B'), 'A', '前手多次 claim ⇒ 仍是 A')
  assert.equal(FC.previousOccupantOf('', 'B'), null)
})

check('S131 接手检查文本：核对项齐全', () => {
  const t = FC.r3HandoffText('AI-OS-Adaptation/TASK-1')
  for (const k of ['接手检查', '另一个会话', 'State', 'Event Log', 'Current Step', 'Next Action', '未写回产出', '维护清单']) {
    assert.ok(t.includes(k), '缺: ' + k)
  }
})

checkAsync('S132 接线：claim 后向前一不同会话注入接手检查（victim 离线 ⇒ no-agent 探针）', async () => {
  const V50 = SCRATCH + '/_selftest_v50'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevInject = process.env.AIOS_INJECT_PROBE
  const prevRemind = process.env.AIOS_REMINDER_PROBE
  rmSync(V50, { recursive: true, force: true })
  mkdirSync(V50, { recursive: true })
  process.env.AIOS_STATE_DIR = V50
  process.env.AIOS_INJECT_PROBE = V50 + '/inject_probe.json'
  writeFileSync(process.env.AIOS_INJECT_PROBE, JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }))
  process.env.AIOS_REMINDER_PROBE = V50 + '/no_reminder.json'
  writeFileSync(V50 + '/r3-wake.json', JSON.stringify({ enabled: true }))
  const CARD = 'TASK-20261101-099'
  const AG = agent('selftest-v50-cur', { delegationDepth: 0 })
  const LOG_LINES = [
    '| 01:00 | Executing | claim 占用（session: selftest-v50-prev） | Worker |',
    '| 01:10 | Parked | release 释放（session: selftest-v50-prev） | Worker |',
    '| 02:00 | Executing | claim 占用（session: selftest-v50-cur） | Worker |',
  ].join('\n')
  try {
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    // 🔴 关键回归：**pre-step 时卡不存在** ⇒ `knownCardKeys` 为空（复现「子 agent 接手」实测场景）。
    //   必须仍能触发（用 taskId 定位 `.log`，⛔ 不依赖 cardKeyOfId）。
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('验证 v50 接手检查')] })
    writeFileSync(CARDS + '/' + CARD + '.md', cardFull(CARD, 'Parked', 0, 'goal', 'next action'))
    writeFileSync(CARDS + '/' + CARD + '.log', LOG_LINES)
    const execP = { callId: 'selftest-v50-call', name: 'pwsh', arguments: { command: 'python tools/task_card.py claim ' + CARD }, agent: AG }
    wf('tools/pre-execute', execP)
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    const out = await h(execP, { isError: false, content: [{ type: 'text', text: 'claimed' }] }, () => ({ kind: 'accept' }))
    assert.ok(out, '必须返回 downstream')
    const rec = records().filter(r => r.ev === 'r3-claim-handoff' && r.session === 'selftest-v50-cur')
    assert.equal(rec.length, 1, '🔴 v50 接线必须触发（缺陷形态：0 条）')
    assert.equal(rec[0].state, 'no-agent', '测试 env 无 agents ⇒ 如实记 no-agent（victim 离线）')
    assert.equal(rec[0].victimSession, 'selftest-v50-prev', '前手会话必须识别为不同会话')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevInject === undefined) delete process.env.AIOS_INJECT_PROBE; else process.env.AIOS_INJECT_PROBE = prevInject
    if (prevRemind === undefined) delete process.env.AIOS_REMINDER_PROBE; else process.env.AIOS_REMINDER_PROBE = prevRemind
    try { rmSync(V50, { recursive: true, force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.log', { force: true }) } catch { /* 静默 */ }
  }
})

// fire-once 关闭告知 ──────
checkAsync('S133 fire-once：注入成功后自动关开关，并向触发会话注入「已关闭，请询问用户」', async () => {
  const V50B = SCRATCH + '/_selftest_v50b'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevInject = process.env.AIOS_INJECT_PROBE
  const prevRemind = process.env.AIOS_REMINDER_PROBE
  rmSync(V50B, { recursive: true, force: true })
  mkdirSync(V50B, { recursive: true })
  process.env.AIOS_STATE_DIR = V50B
  process.env.AIOS_INJECT_PROBE = V50B + '/inject_probe.json'
  writeFileSync(process.env.AIOS_INJECT_PROBE, JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }))
  process.env.AIOS_REMINDER_PROBE = V50B + '/no_reminder.json'
  writeFileSync(V50B + '/r3-wake.json', JSON.stringify({ enabled: true }))
  const CARD = 'TASK-20261101-098'
  const AG = agent('selftest-v50b-cur', { delegationDepth: 0 })
  let followed = 0
  const prevGet = ctx.get
  ctx.get = () => ({ get: () => ({ followup: () => { followed++ } }) })
  try {
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('验证 v50b fire-once')] })
    writeFileSync(CARDS + '/' + CARD + '.md', cardFull(CARD, 'Parked', 0, 'goal', 'next action'))
    writeFileSync(CARDS + '/' + CARD + '.log', [
      '| 01:00 | Executing | claim 占用（session: selftest-v50b-prev） | Worker |',
      '| 02:00 | Executing | claim 占用（session: selftest-v50b-cur） | Worker |',
    ].join('\n'))
    const execP = { callId: 'selftest-v50b-call', name: 'pwsh', arguments: { command: 'python tools/task_card.py claim ' + CARD }, agent: AG }
    wf('tools/pre-execute', execP)
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    const out = await h(execP, { isError: false, content: [{ type: 'text', text: 'claimed' }] }, () => ({ kind: 'accept' }))
    assert.ok(out, '必须返回 downstream')
    assert.equal(followed, 1, '必须向 victim followup 一次')
    // 🔴 fire-once：开关写回 enabled:false
    const wakeNow = JSON.parse(readFileSync(V50B + '/r3-wake.json', 'utf8'))
    assert.equal(wakeNow.enabled, false, '🔴 v50b：注入成功后开关必须自动关（fire-once）')
    const rec = records().filter(r => r.ev === 'r3-claim-handoff' && r.session === 'selftest-v50b-cur')
    assert.equal(rec.length, 1)
    assert.equal(rec[0].state, 'ok')
    const notice = records().filter(r => r.ev === 'r3-disarm-notice' && r.session === 'selftest-v50b-cur')
    assert.equal(notice.length, 1, '必须记录关闭告知探针')
    const outText = JSON.stringify(out)
    assert.ok(outText.includes('自动维护注入已关闭'), '向触发会话注入「已关闭」消息: ' + outText.slice(0, 300))
    assert.ok(outText.includes('请询问用户是否重新开启'), '提示必须要求询问用户')
  } finally {
    if (prevGet === undefined) delete ctx.get; else ctx.get = prevGet
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevInject === undefined) delete process.env.AIOS_INJECT_PROBE; else process.env.AIOS_INJECT_PROBE = prevInject
    if (prevRemind === undefined) delete process.env.AIOS_REMINDER_PROBE; else process.env.AIOS_REMINDER_PROBE = prevRemind
    try { rmSync(V50B, { recursive: true, force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.log', { force: true }) } catch { /* 静默 */ }
  }
})

// 编码类失败触发经验召回 ──────
check('S134 编码类失败触发（E1：UnicodeDecodeError 走 shell · ok:true）', () => {
  const r = {
    isError: false,
    content: [{ type: 'text', text: "OUT: Traceback (most recent call last):\nOUT: UnicodeDecodeError: 'gbk' codec can't decode byte 0xff in position 0: illegal multibyte sequence\nEXITCODE: 1" }],
  }
  assert.equal(FC.recallTriggerOf(r, 'pwsh'), 'exec-encoding-error', '编码失败必须触发 exec-encoding-error')
  // 权限优先：同一输出两者都命中时按权限族
  const both = { isError: false, content: [{ type: 'text', text: 'Traceback\nPermissionError: [Errno 13] Permission denied\nUnicodeDecodeError: illegal multibyte sequence\nEXITCODE: 1' }] }
  assert.equal(FC.recallTriggerOf(both, 'pwsh'), 'exec-permission-error', '权限优先（不改 v49d 行为）')
})

check('S135 编码失败 query 取编码行（丢命令参数 / 路径已剥）', () => {
  const r = {
    isError: false,
    content: [{ type: 'text', text: "OUT: ok\nOUT: UnicodeDecodeError: 'gbk' codec can't decode byte 0xff in position 0\nOUT: [stderr]\nEXITCODE: 1" }],
  }
  const q = FC.buildExperienceQuery('pwsh', { command: "python -c \"json.load(open('report.json'))\"" }, r)
  assert.ok(q.includes('UnicodeDecodeError'), '编码签名必须进 query: ' + q)
  assert.ok(q.includes('codec') || q.includes('0xff') || q.includes('gbk'), '编码特征保留: ' + q)
  assert.ok(!q.includes('report.json'), '编码失败时命令参数不得入 query（避免任务词竞争）: ' + q)
  assert.ok(!q.startsWith('pwsh '), 'exec 通用工具名不入 query')
})

check('S136 反例：read 来源 / 无错误上下文 / exit=0 均不触发', () => {
  const dump = { isError: false, content: [{ type: 'text', text: '<path><repo>\\x.md</path><content>UnicodeDecodeError: codec example</content>EXITCODE: 1' }] }
  assert.equal(FC.recallTriggerOf(dump, 'read'), null, 'read 来源（文件转储）不得触发')
  const docOnly = { isError: false, content: [{ type: 'text', text: 'P54 | 用 PowerShell 整文读写 ⇒ mojibake + BOM\r\nUnicodeDecodeError 示例\r\nEXITCODE: 1' }] }
  assert.equal(FC.recallTriggerOf(docOnly, 'pwsh'), null, '无 [stderr]/Traceback/ERROR: 不得触发（v49h 门）')
  const okExit = { isError: false, content: [{ type: 'text', text: 'Traceback\r\nUnicodeDecodeError: codec\r\nEXITCODE: 0' }] }
  assert.equal(FC.recallTriggerOf(okExit, 'pwsh'), null, 'exit=0 不得触发')
})

// 发布/推送节点（只盯「发布」「推送」两个动作）──────
check('S137 节点识别：只认 push / publish / release 类命令（status/commit/fetch 不认）', () => {
  const hit = ['git push origin main', 'cd repo && git push -u origin feature', 'gh pr create --fill',
    'gh release create v1.0', 'npm publish', 'docker push img:tag']
  for (const c of hit) assert.ok(FC.PUSH_RELEASE_CMD_RE.test(c), '应识别: ' + c)
  const miss = ['git status', 'git commit -m "x"', 'git fetch origin', 'git pull', 'git log --oneline',
    'gh pr list', 'gh api repos/x/y', 'npm install', 'docker build .']
  for (const c of miss) assert.ok(!FC.PUSH_RELEASE_CMD_RE.test(c), '不该识别: ' + c)
  assert.ok(FC.pushReleaseHintText().includes('发布/推送节点'))
  assert.ok(FC.pushReleaseHintText().includes('push_release_family.md'), '必须给族卡指针')
})

checkAsync('S138 接线：push 动作发生时注入节点提示（每会话一次 · 非 vcs 不触发）', async () => {
  const V = SCRATCH + '/_selftest_v49m'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevOff = process.env.AIOS_EXPERIENCE_RECALL
  delete process.env.AIOS_EXPERIENCE_RECALL          // 解除测试顶部短路（否则开关恒 false · 接线不执行）
  rmSync(V, { recursive: true, force: true })
  mkdirSync(V, { recursive: true })
  process.env.AIOS_STATE_DIR = V
  writeFileSync(V + '/experience_recall.json', JSON.stringify({ enabled: true }))
  const AG = agent('selftest-v49m', { delegationDepth: 0 })
  try {
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('发布前核对')] })
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    const call = (cmd) => {
      const p = { callId: 'v49m-' + cmd.replace(/\W/g, '').slice(0, 10), name: 'pwsh', arguments: { command: cmd }, agent: AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    const out1 = await call('git push origin main')
    assert.ok(JSON.stringify(out1).includes('发布/推送节点'), 'push 时必须注入节点提示')
    const injected = records().filter(r => r.ev === 'push-release-hint' && r.session === 'selftest-v49m' && r.state === 'injected')
    assert.equal(injected.length, 1, '必须记 injected 探针')
    const out2 = await call('git status')
    assert.ok(!JSON.stringify(out2).includes('发布/推送节点'), 'git status 不得注入')
    await call('git push --tags')
    const dup = records().filter(r => r.ev === 'push-release-hint' && r.session === 'selftest-v49m' && r.state === 'dup')
    assert.equal(dup.length, 1, '同会话第二次 push 记 dup（每会话一次）')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevOff === undefined) delete process.env.AIOS_EXPERIENCE_RECALL; else process.env.AIOS_EXPERIENCE_RECALL = prevOff
    try { rmSync(V, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

check('S139 限额/限流类错误不当知识缺口（主会话真实误报：subagent limit reached）', () => {
  const r = { isError: true, content: [{ type: 'text', text: 'Error: subagent limit reached (active child limit: 8); wait for an existing child to finish' }] }
  assert.equal(FC.recallTriggerOf(r, 'subagent'), null, '限额错误不得触发经验召回')
  assert.ok(FC.RECALL_QUOTA_RE.test('rate limit exceeded'))
  const k = { isError: true, content: [{ type: 'text', text: 'Error: web fetch failed: TypeError: fetch failed' }] }
  assert.equal(FC.recallTriggerOf(k, 'web_fetch'), 'knowledge-error', '知识型失败仍触发（行为不变）')
})

check('S140 `Access is denied` 措辞也认权限（Start-Transcript 被拒时）', () => {
  const r = { isError: true, content: [{ type: 'text', text: 'Error: Win32 internal error "Access is denied" 0x5 occurred while reading the console output buffer' }] }
  assert.equal(FC.recallTriggerOf(r, 'pwsh'), 'permission-error', 'Access is denied 必须认')
  assert.ok(FC.buildExperienceQuery('pwsh', { command: 'x' }, r).length > 0, 'query 不为空')
})

check('S141 节点提示文案：不假设 origin/main · 补沙箱管道补救', () => {
  const t = FC.pushReleaseHintText()
  assert.ok(!t.includes('origin/main'), '⛔ 不得假设 origin/main（实测分支是 master）: ' + t)
  assert.ok(t.includes('origin/<当前分支>') || t.includes('git ls-remote'), '应给分支自适应或无分支核对方式')
  assert.ok(t.includes('signal pipe') || t.includes('Win32 error 5'), '应含沙箱管道失败的补救提示')
  assert.ok(t.includes('push_release_family.md'), '仍须给族卡指针')
})

check('S142 启动回收 ID：保留项目前缀（P3 真修复 · 跨项目重名不再静默失败）', () => {
  assert.equal(FC.startupRecoverIdOf('active/AI-OS-Adaptation/TASK-20261023-001.md'), 'AI-OS-Adaptation/TASK-20261023-001',
    '⛔ 不得剥掉项目前缀（旧实现 split("/").pop() 的缺陷）')
  assert.equal(FC.startupRecoverIdOf('active/TASK-20261101-001.md'), 'TASK-20261101-001', '平铺卡保持裸 ID')
  assert.equal(FC.startupRecoverIdOf('active/AI-OS-Adaptation/TASK-x.md'.replace(/\\/g, '/')), 'AI-OS-Adaptation/TASK-x')
  assert.equal(FC.startupRecoverIdOf(''), '', '空 key 不炸')
})

check('S143 改本体节点识别：只认「编辑 runtime/*.ts」（含 Windows 路径）', () => {
  assert.ok(FC.RUNTIME_EDIT_PATH_RE.test(ROOT + '/runtime/aios-activation.ts'), '正斜杠路径')
  assert.ok(FC.RUNTIME_EDIT_PATH_RE.test('<repo>\\runtime\\aios-activation.ts'), '反斜杠路径')
  assert.ok(FC.RUNTIME_EDIT_PATH_RE.test('/repo/runtime/x.ts'), 'posix 绝对路径')
  assert.ok(!FC.RUNTIME_EDIT_PATH_RE.test(ROOT + '/runtime/README.md'), '⛔ 非 .ts 不算')
  assert.ok(!FC.RUNTIME_EDIT_PATH_RE.test(ROOT + '/domains/x.ts'), '⛔ 非 runtime/ 不算')
  assert.ok(FC.RUNTIME_EDIT_TOOL_RE.test('edit') && FC.RUNTIME_EDIT_TOOL_RE.test('write'), '编辑类工具')
  assert.ok(!FC.RUNTIME_EDIT_TOOL_RE.test('read'), '⛔ 读取类工具不算')
  assert.ok(FC.runtimeEditHintText().includes('runtime_change_family.md'), '必须给族卡指针')
})

checkAsync('S144 接线：编辑 runtime/*.ts 时注入节点提示（每会话一次 · 非 runtime 不注入）', async () => {
  const V = SCRATCH + '/_selftest_v49q'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevOff = process.env.AIOS_EXPERIENCE_RECALL
  delete process.env.AIOS_EXPERIENCE_RECALL
  rmSync(V, { recursive: true, force: true })
  mkdirSync(V, { recursive: true })
  process.env.AIOS_STATE_DIR = V
  writeFileSync(V + '/experience_recall.json', JSON.stringify({ enabled: true }))
  const AG = agent('selftest-v49q', { delegationDepth: 0 })
  try {
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('改本体')] })
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    const call = (name, filePath) => {
      const p = { callId: 'v49q-' + name + '-' + filePath.length, name, arguments: { file_path: filePath }, agent: AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    const out1 = await call('edit', ROOT + '/runtime/aios-activation.ts')
    assert.ok(JSON.stringify(out1).includes('改本体节点'), '编辑 runtime/*.ts 必须注入节点提示')
    const rec = records().filter(r => r.ev === 'runtime-edit-hint' && r.session === 'selftest-v49q' && r.state === 'injected')
    assert.equal(rec.length, 1, '必须记 injected 探针')
    const out2 = await call('edit', ROOT + '/domains/experiences/x.md')
    assert.ok(!JSON.stringify(out2).includes('改本体节点'), '非 runtime/*.ts 不得注入')
    await call('write', ROOT + '/runtime/aios-activation.ts')
    const dup = records().filter(r => r.ev === 'runtime-edit-hint' && r.session === 'selftest-v49q' && r.state === 'dup')
    assert.equal(dup.length, 1, '同会话第二次改本体记 dup（每会话一次）')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevOff === undefined) delete process.env.AIOS_EXPERIENCE_RECALL; else process.env.AIOS_EXPERIENCE_RECALL = prevOff
    try { rmSync(V, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

// ── 🔴 v51（T20 · W-2/W-3b · Human 2026-11-01 授权 · ⛔ 改完**需重启**才在真实窗口生效）───────
//   设计稿：`task_cards/active/AI-OS-Adaptation/PHASE-INJECTION-DESIGN-2026-11-01.md §4.1–§4.4`
//   口径（Lead 2026-11-01 裁定）：**以能力自报的 `phases` 为准**，⛔ 不叠设计稿 §4.2 的类别门。
//   ⛔ 不复活 v47 砍掉的 `first-edit` 事件（W-4 未授权）—— 这里只做阶段**判定**。
check('S145 阶段判定器：由现有内存态推出 S1/S2/S3/S4/null（纯函数 · ⛔ 不猜）', () => {
  const sig = o => Object.assign({
    ownedCards: 0, releasedCards: 0, releasedThisStep: false,
    hasEdit: false, everEdited: false, failStreak: 0,
  }, o)
  assert.equal(FC.phaseOf(sig({ ownedCards: 1 })), 'S1', '占 1 张卡 + 其后无实质改动 ⇒ S1')
  assert.equal(FC.phaseOf(sig({ ownedCards: 1, everEdited: true })), 'S2', '出现过实质改动（锁存）⇒ S2')
  assert.equal(FC.phaseOf(sig({ ownedCards: 0, hasEdit: true })), 'S2', '本拍 has-edit（滚动窗口）⇒ S2（无卡也算，别把改动漏判）')
  assert.equal(FC.phaseOf(sig({ ownedCards: 1, everEdited: true, failStreak: 2 })), 'S3', '连败 ≥2 ⇒ S3（优先于 S2）')
  assert.equal(FC.phaseOf(sig({ releasedCards: 1, ownedCards: 0 })), 'S4', '已 release 且不再占用 ⇒ S4')
  assert.equal(FC.phaseOf(sig({ releasedCards: 1, ownedCards: 1, releasedThisStep: true })), 'S4',
    '刚 release（卡快照还没刷新）⇒ 当拍即 S4（否则"release 是最后一步"会永远不注）')
  assert.equal(FC.phaseOf(sig({ ownedCards: 1, everEdited: true, failStreak: 2, releasedCards: 1, releasedThisStep: true })), 'S4',
    'S4 优先于 S3/S2')
  assert.equal(FC.phaseOf(sig({})), null, '无任何信号 ⇒ null（⛔ 不猜阶段）')
  assert.equal(FC.phaseOf(sig({ ownedCards: 2 })), null, '多占用 = 异常状态 ⇒ null（⛔ 不猜一张卡）')
  assert.equal(FC.PHASE_TITLE.S1, '决策')
  assert.equal(FC.PHASE_TITLE.S2, '实现')
  assert.equal(FC.PHASE_TITLE.S4, '收口')
})

check('S147 / 阶段能力候选渲染：只出 capabilities/ + 只注 top1 + 去重（`phases` 过滤本体在 python 侧 S15）', () => {
  const cap = (name, intro) => ({
    id: 'aios.capabilities:' + name, name, kind: 'capability',
    local_path: 'capabilities/' + name + '.md', intro,
    source: { id: 'aios.capabilities' }, hit_channels: ['axis'],
    evidence: [{ field: 'axes.help', channel: 'axis', basis: 'axis-label-match', matched: [name], strength: 'strong' }],
  })
  const set = {
    candidates: [
      cap('senior-engineer', '以资深 SaaS 工程师的眼光评审计划与取舍'),
      cap('frontend-ui', '前端样式实现'),
      cap('debug-protocol', '排障步骤'),
      cap('test-driven-development', '先写测试再实现'),
      cap('data-change-safety', '数据变更安全'),
      // 账本 chunk 不是"能力描述" ⇒ 不得注入（阶段注入只注能力包 + 指针）
      { id: 'ledger.proven:abc', name: 'Entry #1', kind: 'ledger-chunk',
        local_path: '样例账本.md', source: { id: 'ledger.proven' }, hit_channels: ['topic'] },
    ],
    budget_applied: { matched_before_budget: 6 },
  }
  const already = new Set(['aios.capabilities:frontend-ui'])
  const r = FC.renderPhaseCandidates(set, 'S1', already)
  assert.equal(r.pool, 5, '池 = capabilities/ 下的候选（账本 chunk 不计）')
  assert.equal(r.ids.length, 1, '🔴 v51i：池 5 条去重后（4 条有效）仍只注 1 条 —— top1')
  assert.equal(r.scores.length, r.ids.length, 'candidates 与 scores 必须等长')
  assert.ok(!r.ids.includes('aios.capabilities:frontend-ui'), '已被 auto_capability 返回过 ⇒ 不再注（设计稿 §4.4）')
  assert.ok(r.text.startsWith('【AI-OS · 决策阶段 · 能力候选】'), '形态照 v31：标签行: ' + r.text.slice(0, 40))
  assert.ok(r.text.includes('  · senior-engineer — '), '必须给"能力名 — 一句话描述": ' + r.text)
  assert.ok(r.text.includes('→ capabilities/senior-engineer.md'), '必须给指针')
  assert.ok(!r.text.includes('样例账本.md'), '账本 chunk 不得注入')
  // 全被去重（池里 5 条能力全部已在"已返回/已注入"集合里）⇒ 空文本（调用方记 no-candidate，⛔ 不注空壳）
  const allIds = new Set(set.candidates.map(c => c.id))
  const r2 = FC.renderPhaseCandidates(set, 'S1', allIds)
  assert.equal(r2.text, '')
  assert.equal(r2.ids.length, 0)
  // 向后兼容：过滤口径由检索侧 `phases` 决定，**缺字段 = 无限制** —— 渲染侧不因"没有 phases 元数据"丢候选
  assert.ok(FC.isCapabilityCandidatePath('capabilities/x.md'))
  assert.ok(FC.isCapabilityCandidatePath('capabilities\\x.md'), 'Windows 分隔符也认')
  assert.ok(!FC.isCapabilityCandidatePath('domains/x.md'))
})

check('S148 阶段检索请求：顶层带 `phase` + 既有字段语义不变（shape 层）', () => {
  const card = {
    key: 'proj/TASK-20260101-001.md', state: 'Executing', step: '',
    goal: '给 runtime 加阶段判定', next: '改 aios-activation.ts', occupancy: null,
  }
  const req = FC.buildPhaseRetrievalRequest('S2', card, { intentText: '用户原始说法', historyCoverage: 'complete' }, 12345)
  assert.ok(req, '有卡 ⇒ 必须给请求（⛔ 不得空手）')
  assert.equal(req.schema, 'retrieval-request/v1')
  assert.equal(req.phase, 'S2', '`phase` 是**新增可选字段**（⛔ 不动既有字段语义）')
  assert.equal(req.request_id, 'phase-S2-12345')
  assert.equal(req.work.target_refs.state, 'unknown', '卡是工作对象、不是检索对象（v20 口径原样）')
  assert.equal(req.work.history_coverage.state, 'provided')
  assert.equal(req.budget.max_candidates, 5, '🔴 v51d：请求 budget 必须同步 5（否则池子还是 3）')
  assert.equal(req.budget.max_candidates, FC.PHASE_BUDGET_CANDIDATES, '🔴 v51i：budget 走池子常量')
  assert.equal(FC.PHASE_BUDGET_CANDIDATES, 5, '🔴 v51i：注入条数改成 1，但 budget **保持 5**（池子够大才轮得到 top1）')
  assert.ok(String(req.work.work_topic.value).includes('给 runtime 加阶段判定'))
})

check('S150 回归：有卡 ⇒ work_topic 只由卡描述拼成（⛔ 不含 intentText）；无卡/无描述 ⇒ null', () => {
  const card = {
    key: 'proj/TASK-20260101-001.md', state: 'Executing', step: '',
    goal: '目标：把注入改成按卡排序', next: '下一步：改 buildPhaseRetrievalRequest', occupancy: null,
  }
  const wc = { intentText: '元话语：我们在讨论阶段注入到底该不该做、怎么做', historyCoverage: 'complete' }
  const req = FC.buildPhaseRetrievalRequest('S2', card, wc, 1)
  assert.ok(req)
  assert.equal(req.work.work_topic.value, '下一步：改 buildPhaseRetrievalRequest ｜ 目标：把注入改成按卡排序',
    '🔴 v51b：topic = <next> ｜ <goal>（分层；只由卡描述拼成）')
  assert.ok(!req.work.work_topic.value.includes('元话语'), '⛔ 不得混入 intentText')
  assert.ok(!JSON.stringify(req).includes('元话语'), '⛔ intentText 不得进入请求的任何字段（实测误报根因）')
  // 无卡 ⇒ null（⛔ 不再用 intentText 兜底）
  assert.equal(FC.buildPhaseRetrievalRequest('S1', null, wc, 2), null, '🔴 v51a：无卡 ⇒ null')
  // 有卡但卡上拼不出 topic ⇒ 同样 null（⛔ 不拿别的东西凑）
  const blank = { key: 'proj/TASK-x.md', state: 'Executing', step: '', goal: '', next: '', occupancy: null }
  assert.equal(FC.buildPhaseRetrievalRequest('S4', blank, wc, 3), null, '🔴 卡上无 Goal/Next ⇒ null')
})

check('S151 排序分层：both ⇒ work_topic = `<next> ｜ <goal>`（next 在前 · 单字符串 · next 超长时 goal 让位）', () => {
  const card = {
    key: 'proj/TASK-20260101-001.md', state: 'Executing', step: '',
    goal: '设计工作认知模块契约（抽象 Goal）', next: '正在改 runtime 注入段的 buildPhaseRetrievalRequest', occupancy: null,
  }
  const wc = { intentText: '元话语：我们再聊聊阶段注入', historyCoverage: 'complete' }
  const req = FC.buildPhaseRetrievalRequest('S2', card, wc, 1)
  assert.ok(req)
  const topic = req.work.work_topic.value
  assert.equal(typeof topic, 'string', '⛔ work_topic 必须仍是**单个字符串**（不改 schema）')
  assert.equal(topic, card.next + FC.PHASE_TOPIC_SEP + card.goal, '整体必须是 `<next> ｜ <goal>`')
  assert.ok(topic.startsWith(card.next), '🔴 next 必须在前（顺序即权重；平铺会稀释具体信息）')
  assert.ok(!JSON.stringify(req).includes('元话语'), '⛔ 不含 intentText')
  assert.deepEqual(Object.keys(req.work).sort(), ['history_coverage', 'target_refs', 'work_topic'],
    '⛔ 不新增 work 字段（只改 work_topic 的字符串形态）')
  // next 超长 ⇒ **goal 让位**（⛔ 不让 goal 挤掉 next）
  const longNext = '改注入段的排序与截断'.repeat(60) // > 400 字
  const req2 = FC.buildPhaseRetrievalRequest('S2', { ...card, next: longNext }, wc, 2)
  const t2 = req2.work.work_topic.value
  assert.equal(t2.length, FC.PHASE_TOPIC_MAX, '上限沿用 400')
  assert.equal(t2, longNext.slice(0, FC.PHASE_TOPIC_MAX), 'next 优先截断：topic 前 400 字全是 next')
  assert.ok(!t2.includes(card.goal), '🔴 goal 必须让位（⛔ 不让 goal 挤掉 next）')
})

check('S152 三分支：只有 goal / 只有 next / 都没有（⇒ null）', () => {
  const base = { key: 'proj/TASK-x.md', state: 'Executing', step: '', goal: '', next: '', occupancy: null }
  const wc = { intentText: '元话语不应出现', historyCoverage: 'complete' }
  const onlyGoal = { ...base, goal: '把阶段注入做成可验证机制' }
  const reqG = FC.buildPhaseRetrievalRequest('S1', onlyGoal, wc, 1)
  assert.ok(reqG)
  assert.equal(reqG.work.work_topic.value, '把阶段注入做成可验证机制', '只有 goal ⇒ 只用 goal')
  const onlyNext = { ...base, next: '改 buildPhaseRetrievalRequest 的 work_topic 分层' }
  const reqN = FC.buildPhaseRetrievalRequest('S2', onlyNext, wc, 2)
  assert.ok(reqN)
  assert.equal(reqN.work.work_topic.value, '改 buildPhaseRetrievalRequest 的 work_topic 分层', '只有 next ⇒ 只用 next')
  assert.equal(FC.buildPhaseRetrievalRequest('S4', base, wc, 3), null, '都空 ⇒ null（v51a 行为不变）')
  // 纯函数直测：空白归一 + 分层 + 空
  assert.equal(FC.phaseTopicOf(null), '')
  assert.equal(FC.phaseTopicOf({ ...base, goal: 'G', next: '  N  ' }), 'N' + FC.PHASE_TOPIC_SEP + 'G', '空白归一')
  assert.equal(FC.phaseTopicOf(base), '')
  assert.equal(FC.phaseTopicOf({ ...base, next: 'N' }), 'N')
})

// ── 🔴 v51c（T20 · 经验侧节点 · Human 2026-11-01 定稿 (a)）：N1 改语料 / N2 重建索引 / N3 跑回归门 ──
//   范式照 v49m（发布/推送）/ v49q（改本体）：纯词面判据 + 每节点每会话一次 Set + 独立早退门。
//   ⛔ N4 改本体 = v49q 已有、N5 发布推送 = v49m 已有 ⇒ 本段不收编它们。
check('S153 N1 识别：编辑语料命中 · 只 read 不命中 · scratch/runtime 不命中', () => {
  // 编辑 `domains/**` ⇒ N1
  assert.equal(FC.nodeHintOf('edit', { file_path: ROOT + '/domains/experiences/x.md' }), 'N1')
  assert.equal(FC.nodeHintOf('write', { path: 'task_cards/memory/PITFALLS.md' }), 'N1', 'PITFALLS.md 也算语料')
  assert.equal(FC.nodeHintOf('apply_patch', { new_path: 'domains/ai-os/patterns/cot_leakage_trim.md' }), 'N1')
  assert.equal(FC.nodeHintOf('edit', { file_path: '<repo>\\domains\\experiences\\inject_digests.md' }), 'N1',
    '反斜杠路径 + 任务清单里的 digest 显式项')
  // ⛔ 只 read / 读取类工具不命中（工具门在调用方挡住）
  assert.equal(FC.nodeHintOf('read', { file_path: ROOT + '/domains/experiences/x.md' }), null, '⛔ read 不算改语料')
  assert.equal(FC.nodeHintOf('grep', { path: ROOT + '/domains' }), null)
  // ⛔ 非语料编辑不命中
  assert.equal(FC.nodeHintOf('edit', { file_path: ROOT + '/scratch/x.md' }), null)
  assert.equal(FC.nodeHintOf('edit', { file_path: ROOT + '/runtime/aios-activation.ts' }), null, 'runtime/*.ts 属 N4（v49q），不在本段')
  assert.equal(FC.nodeHintOf('edit', {}), null, '无路径 ⇒ 不猜')
  // 纯函数直测（路径判据）
  assert.ok(FC.isCorpusEditTarget('domains/x.md'))
  assert.ok(FC.isCorpusEditTarget('task_cards/memory/PITFALLS.md'))
  assert.ok(!FC.isCorpusEditTarget('scratch/domains_copy/x.md'), '⛔ 只要不真的在 domains/ 下就不算')
  assert.ok(!FC.isCorpusEditTarget(''))
})

check('S154 N2/N3 识别：`build` / `_guard_now` 命中；`query` 不命中；`_scene_probe.py --check` **算 N3**', () => {
  // N2：重建索引 —— 只 build 算
  assert.equal(FC.nodeHintOf('pwsh', { command: 'python scratch/semantic_search.py build' }), 'N2')
  assert.equal(FC.nodeHintOf('pwsh', { command: '& $VENV scratch/semantic_search.py build --incremental' }), 'N2')
  assert.equal(FC.nodeHintOf('pwsh', { command: 'python scratch/semantic_search.py query "build 索引"' }), null,
    '⛔ 只查不 build 不算（query 里出现 build 字样也不算）')
  assert.equal(FC.nodeHintOf('pwsh', { command: 'python scratch/semantic_search.py selftest' }), null)
  // N3：跑回归门 —— `_scene_probe.py --check` 判为**算**（实测：`--check` = 与上次快照对比的回归入口）
  assert.equal(FC.nodeHintOf('pwsh', { command: 'python scratch/_guard_now.py' }), 'N3')
  assert.equal(FC.nodeHintOf('pwsh', { command: '$VENV scratch/_scene_probe.py --check' }), 'N3', '_scene_probe --check 算 N3')
  for (const f of ['_family_coverage_2026-11-01.py', '_fp_ablation_2026-11-01.py', '_n30_fp_now.py']) {
    assert.equal(FC.nodeHintOf('pwsh', { command: 'python scratch/' + f }), 'N3', '应识别: ' + f)
  }
  // ⛔ 只看帮助 ≠ 跑回归门；⛔ 读取类工具不按命令判
  assert.equal(FC.nodeHintOf('pwsh', { command: 'python scratch/_guard_now.py --help' }), null)
  assert.equal(FC.nodeHintOf('read', { file_path: 'scratch/_guard_now.py' }), null)
  // 文案三件套：节点名 + 族名/提示 + `→ 路径`
  for (const [t, tag] of [[FC.corpusNodeHintText(), '节点：改语料'], [FC.indexNodeHintText(), '节点：重建索引'],
    [FC.regressionNodeHintText(), '节点：跑回归门']]) {
    assert.ok(t.includes(tag), '缺节点名: ' + tag)
    assert.ok(t.includes('经验 ▸'), '缺族名/通道标签')
    assert.ok(t.includes('→ domains/experiences/selfcheck_judgement_family.md'), '必须给族卡指针')
  }
})

checkAsync('S155 接线：N1 命中注入一次 · 再命中 dup · `read` 零注入 · experience_recall 关 ⇒ 零注入', async () => {
  const V = SCRATCH + '/_selftest_v51c'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevOff = process.env.AIOS_EXPERIENCE_RECALL
  const prevRemind = process.env.AIOS_REMINDER_PROBE
  rmSync(V, { recursive: true, force: true })
  mkdirSync(V, { recursive: true })
  process.env.AIOS_STATE_DIR = V
  delete process.env.AIOS_EXPERIENCE_RECALL // 解除主套件短路（否则门控恒关 · 接线不执行）
  process.env.AIOS_REMINDER_PROBE = V + '/no_reminder.json'
  writeFileSync(V + '/experience_recall.json', JSON.stringify({ enabled: true }))
  const AG = agent('selftest-v51c', { delegationDepth: 0 })
  const AG2 = agent('selftest-v51c-off', { delegationDepth: 0 })
  const mine = sid => records().filter(r => r.ev === 'node-inject' && r.session === sid)
  try {
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    const call = (cid, name, args, ag) => {
      const p = { callId: cid, name, arguments: args, agent: ag || AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('改语料')] })
    // ① N1：编辑 domains 语料 ⇒ 注入一次 + 上下文出现「节点：改语料」
    const out1 = await call('v51c-n1', 'edit', { file_path: ROOT + '/domains/experiences/x.md' })
    assert.ok(out1, '必须返回 downstream')
    const rec1 = mine('selftest-v51c')
    assert.equal(rec1.length, 1, '🔴 N1 必须注入一次（缺陷形态：0 条 = 门控/接线没跑到）')
    assert.equal(rec1[0].node, 'N1')
    assert.equal(rec1[0].state, 'injected')
    assert.ok(rec1[0].chars > 0, '必须记 chars')
    assert.ok(String(rec1[0].target || '') !== '', 'target 必须有 clip 片段')
    assert.ok(!String(rec1[0].target).includes('<repo>') && !String(rec1[0].target).includes('<repo>'),
      '探针只落剥壳后的 clip（⛔ 不落绝对路径）: ' + rec1[0].target)
    const txt1 = JSON.stringify(out1)
    assert.ok(txt1.includes('节点：改语料'), '上下文必须出现节点文案: ' + txt1.slice(0, 300))
    assert.ok(txt1.includes('selfcheck_judgement_family.md'), '必须给族卡指针')
    // ② 再次编辑语料（同节点）⇒ dup（每节点只报一条），且**不再注入文案**
    const out2 = await call('v51c-n1b', 'write', { path: 'task_cards/memory/PITFALLS.md' })
    const rec2 = mine('selftest-v51c')
    assert.equal(rec2.filter(r => r.state === 'dup').length, 1, '重复命中必须记 dup')
    assert.equal(rec2.filter(r => r.state === 'injected').length, 1, '同节点只注入一次（P49 防刷屏）')
    assert.ok(!JSON.stringify(out2).includes('节点：改语料'), 'dup 不得再注入文案')
    // ③ 只 read 同一文件 ⇒ 零新增
    await call('v51c-read', 'read', { file_path: ROOT + '/domains/experiences/x.md' })
    assert.equal(mine('selftest-v51c').length, 2, 'read 不得新增 node-inject（injected + dup 各 1）')
    // ④ N2/N3 接线：exec 命令原文在**真实 handler** 里可得（`exec.arguments.command`）
    //    ⇒ 证明"判据拿不到命令"这个降级不成立
    await call('v51c-n2', 'pwsh', { command: 'python scratch/semantic_search.py build' })
    await call('v51c-n3', 'pwsh', { command: 'python scratch/_guard_now.py' })
    const injectedNodes = mine('selftest-v51c').filter(r => r.state === 'injected').map(r => r.node).sort()
    assert.deepEqual(injectedNodes, ['N1', 'N2', 'N3'], 'N1/N2/N3 各注入一次: ' + JSON.stringify(injectedNodes))
    // ⑤ experience_recall 关 ⇒ 新会话零注入（门控沿用 experience_recall · ⛔ 未新建开关）
    writeFileSync(V + '/experience_recall.json', JSON.stringify({ enabled: false }))
    emit1('agent/session-start', { agent: AG2, source: 'startup' })
    wf('agent/pre-step', { agent: AG2, turn: 1, step: 1, messages: [userMsg('改语料 · 开关关')] })
    const out4 = await call('v51c-off', 'edit', { file_path: ROOT + '/domains/experiences/y.md' }, AG2)
    assert.equal(mine('selftest-v51c-off').length, 0, '🔴 experience_recall 关 ⇒ 零注入')
    assert.ok(!JSON.stringify(out4).includes('节点：改语料'), '关掉后不得注入')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevOff === undefined) delete process.env.AIOS_EXPERIENCE_RECALL; else process.env.AIOS_EXPERIENCE_RECALL = prevOff
    if (prevRemind === undefined) delete process.env.AIOS_REMINDER_PROBE; else process.env.AIOS_REMINDER_PROBE = prevRemind
    try { rmSync(V, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

checkAsync('S149 无卡 ⇒ 静默不注（不发请求 · 探针 no-anchor · 不记账）；之后有了卡该阶段仍能注入', async () => {
  const V = SCRATCH + '/_selftest_v51a'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevInject = process.env.AIOS_INJECT_PROBE
  const prevPhase = process.env.AIOS_PHASE_INJECT
  const prevRemind = process.env.AIOS_REMINDER_PROBE
  const CARD = 'TASK-20261101-096'
  rmSync(V, { recursive: true, force: true })
  mkdirSync(V, { recursive: true })
  process.env.AIOS_STATE_DIR = V
  delete process.env.AIOS_PHASE_INJECT // 打开**阶段**接线（主套件默认 off · 照 P67；首拍接线另由常量门控）
  process.env.AIOS_INJECT_PROBE = V + '/inject_probe.json'
  writeFileSync(process.env.AIOS_INJECT_PROBE, JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }))
  process.env.AIOS_REMINDER_PROBE = V + '/no_reminder.json'
  const AG = agent('selftest-v51a', { delegationDepth: 0 })
  const mine = () => records().filter(r => r.ev === 'phase-inject' && r.session === 'selftest-v51a')
  try {
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('还没有卡，先直接改文件')] })
    const call = (cid, name, args) => {
      const p = { callId: cid, name, arguments: args, agent: AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    // ① 首次实质改动但**还没占卡** ⇒ 进入 S2，但无卡 ⇒ **不发请求**（只落 no-anchor）
    const out1 = await call('v51a-edit', 'edit', { file_path: ROOT + '/scratch/_v51a_edit_probe.md' })
    assert.ok(out1, '必须返回 downstream')
    // ⚠️ v51j/v51k（2026-11-01）：首拍通道（`basis:"first-step"`）**默认关**（开关关 ⇒ 零读数）
    //   ⇒ 下面的 `basis !== 'first-step'` 过滤是**复活时的防污染保险**，关闭态下等价于不过滤。
    //   ⛔ 没有放宽 v51a「无卡 ⇒ 阶段静默」的语义。
    const rec1 = mine().filter(r => r.basis !== 'first-step')
    assert.equal(rec1.length, 1, '阶段通道只应有 1 条探针（no-anchor）；出现 spawn-failed/injected = 仍在发请求')
    assert.equal(rec1[0].phase, 'S2', '无卡但有实质改动 ⇒ S2')
    assert.equal(rec1[0].state, 'no-anchor', '🔴 v51a：无工作卡 ⇒ 静默不注')
    assert.equal(rec1[0].n, 0)
    assert.equal(rec1[0].chars, 0)
    assert.ok(String(rec1[0].note || '').includes('无工作卡'), 'note 必须写明原因: ' + rec1[0].note)
    assert.ok(!JSON.stringify(out1).includes('实现阶段 · 能力候选'),
      '无卡 ⇒ **阶段通道**不得注入候选块（首拍通道走 S1 文案，另算）')
    // ② **不记账**：`sent` 不含 S2（否则"之后再占卡"会被错误锁死）
    const slot = FC.PHASE_INJECT.get('selftest-v51a')
    assert.ok(slot, '会话槽必须已建')
    assert.ok(!slot.sent.has('S2'), '🔴 无卡不得把 S2 记进 sent（否则占卡后永不再注）')
    // ③ 同阶段再触发（仍无卡）⇒ 不再刷 no-anchor（每阶段最多一条）
    await call('v51a-again', 'pwsh', { command: 'git status' })
    assert.equal(mine().filter(r => r.state === 'no-anchor').length, 1, 'no-anchor 每阶段最多一条')
    // ④ 真占了卡 ⇒ 该阶段（S2）仍能正常检索注入（证明没被锁死）
    writeFileSync(CARDS + '/' + CARD + '.md', cardFull(CARD, 'Executing', 0, 'v51a 占卡后应能注入', '再跑一次工具'))
    writeFileSync(CARDS + '/' + CARD + '.log', '| 01:00 | Executing | claim 占用（session: selftest-v51a） | Worker |\n')
    // ⚠️ 必须用**新 turn**（同一 turn 已被评估 ⇒ pre-step 早退、不重扫卡 ⇒ s.cards 仍是旧快照）
    wf('agent/pre-step', { agent: AG, turn: 2, step: 1, messages: [userMsg('占卡后继续')] })
    await call('v51a-with-card', 'pwsh', { command: 'git status' })
    const rec3 = mine().filter(r => r.phase === 'S2' && r.state !== 'no-anchor')
    assert.equal(rec3.length, 1, '🔴 有了卡 ⇒ S2 必须真的去检索（injected/spawn-failed）')
    assert.ok(['injected', 'spawn-failed', 'no-candidate'].includes(rec3[0].state), 'S2 state: ' + rec3[0].state)
    assert.ok(slot.sent.has('S2'), '这次必须记账（每阶段每会话一次）')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevInject === undefined) delete process.env.AIOS_INJECT_PROBE; else process.env.AIOS_INJECT_PROBE = prevInject
    if (prevPhase === undefined) delete process.env.AIOS_PHASE_INJECT; else process.env.AIOS_PHASE_INJECT = prevPhase
    if (prevRemind === undefined) delete process.env.AIOS_REMINDER_PROBE; else process.env.AIOS_REMINDER_PROBE = prevRemind
    try { rmSync(V, { recursive: true, force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.log', { force: true }) } catch { /* 静默 */ }
  }
})

checkAsync('S146 阶段注入接线：S1/S2/S4 各注入一次 · 同阶段再次 ⇒ dup · 未进入阶段 ⇒ 不注入', async () => {
  const V = SCRATCH + '/_selftest_v51'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevInject = process.env.AIOS_INJECT_PROBE
  const prevPhase = process.env.AIOS_PHASE_INJECT
  const prevRemind = process.env.AIOS_REMINDER_PROBE
  const CARD = 'TASK-20261101-097'
  rmSync(V, { recursive: true, force: true })
  mkdirSync(V, { recursive: true })
  process.env.AIOS_STATE_DIR = V
  delete process.env.AIOS_PHASE_INJECT // 打开本用例的接线（主套件默认 off · 照 P67）
  process.env.AIOS_INJECT_PROBE = V + '/inject_probe.json'
  writeFileSync(process.env.AIOS_INJECT_PROBE, JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }))
  process.env.AIOS_REMINDER_PROBE = V + '/no_reminder.json'
  const NONE = agent('selftest-v51-none', { delegationDepth: 0 })
  const AG = agent('selftest-v51', { delegationDepth: 0 })
  const mine = () => records().filter(r => r.ev === 'phase-inject' && r.session === 'selftest-v51')
  try {
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    // ① 未进入阶段（未占卡 / 未改文件 / 未连败）⇒ **零** phase-inject 探针
    emit1('agent/session-start', { agent: NONE, source: 'startup' })
    wf('agent/pre-step', { agent: NONE, turn: 1, step: 1, messages: [userMsg('还没开始占卡，先看看')] })
    const pN = { callId: 'v51-none', name: 'pwsh', arguments: { command: 'git status' }, agent: NONE }
    wf('tools/pre-execute', pN)
    const outN = await h(pN, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    assert.ok(outN, '必须返回 downstream（⛔ 不得因阶段段异常改变工具结果）')
    assert.equal(records().filter(r => r.ev === 'phase-inject' && r.session === 'selftest-v51-none'
      && r.basis !== 'first-step').length, 0,
      // 🔴 v51j/v51k（2026-11-01）：首拍通道**默认关**；过滤保留作复活保险。本条断言的是**阶段通道**零条。
      //   ⛔ 没有放宽"未进入阶段 ⇒ 不猜阶段"的语义。
      '未进入阶段 ⇒ 阶段注入零条（⛔ 不猜阶段）')

    // ② S1：卡上留痕 = 本会话 claim ⇒ 下一次 post-execute 注入一次
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    writeFileSync(CARDS + '/' + CARD + '.md', cardFull(CARD, 'Executing', 0, '给 runtime 加阶段判定', '改 aios-activation.ts'))
    writeFileSync(CARDS + '/' + CARD + '.log', '| 01:00 | Executing | claim 占用（session: selftest-v51） | Worker |\n')
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('占卡后开工')] })
    const call = (cid, cmd) => {
      const p = { callId: cid, name: 'pwsh', arguments: { command: cmd }, agent: AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    const out1 = await call('v51-a', 'git status')
    const rec1 = mine()
    assert.equal(rec1.length, 1, '🔴 S1 进入必须注入一次（缺陷形态：0 条 = 接线没跑到 / 被静默吞掉）')
    assert.equal(rec1[0].phase, 'S1', '探针 phase 必须是 S1')
    assert.ok(['injected', 'spawn-failed', 'no-candidate'].includes(rec1[0].state), 'state 四态之一: ' + rec1[0].state)
    if (rec1[0].state === 'injected') {
      assert.equal(rec1[0].n, 1, '🔴 v51i：注入恰好 1 条（top1；v51d 曾是 ≤5）')
      assert.ok(rec1[0].chars > 0, '必须记 chars')
      const txt = JSON.stringify(out1)
      assert.ok(txt.includes('【AI-OS · 决策阶段 · 能力候选】'), '注入形态 = v31 三行格式: ' + txt.slice(0, 300))
      assert.ok(txt.includes('→ capabilities/'), '必须给能力文件指针（⛔ 不注整包正文）')
    } else {
      assert.equal(rec1[0].n, 0, '未注入 ⇒ n=0')
    }
    // ③ 同阶段再次触发 ⇒ dup（升沿 + 已发 Set · ⛔ 不用"当前水平状态"做节流）
    await call('v51-b', 'git status')
    const rec2 = mine()
    assert.equal(rec2.filter(r => r.state === 'dup').length, 1, '同阶段第二次必须记 dup')
    assert.equal(rec2.filter(r => r.state !== 'dup').length, 1, '同阶段只注入一次（P49 防刷屏）')

    // ④ S2：**首次实质改动**（`has-edit` 升沿）⇒ 再注一次（阶段不同 ⇒ 不撞 Set）
    const pEdit = { callId: 'v51-edit', name: 'edit', arguments: { file_path: ROOT + '/scratch/_v51_edit_probe.md' }, agent: AG }
    wf('tools/pre-execute', pEdit)
    const outEdit = await h(pEdit, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    assert.ok(outEdit, '必须返回 downstream')
    const s2 = mine().filter(r => r.phase === 'S2')
    assert.equal(s2.length, 1, '🔴 S2（首次实质改动）必须注入一次')
    assert.ok(['injected', 'spawn-failed', 'no-candidate'].includes(s2[0].state), 'S2 state: ' + s2[0].state)

    // ⑤ S4：**收口**（成功 release 命令字面量）⇒ 再注一次（当拍即判，不等下一次 pre-step 刷新卡快照）
    const pRel = {
      callId: 'v51-release', name: 'pwsh',
      arguments: { command: 'python tools/task_card.py release ' + CARD + ' --state=Parked' }, agent: AG,
    }
    wf('tools/pre-execute', pRel)
    const outRel = await h(pRel, { isError: false, content: [{ type: 'text', text: 'released' }] }, () => ({ kind: 'accept' }))
    assert.ok(outRel, '必须返回 downstream')
    const s4 = mine().filter(r => r.phase === 'S4')
    assert.equal(s4.length, 1, '🔴 S4（收口）必须注入一次')
    assert.ok(['injected', 'spawn-failed', 'no-candidate'].includes(s4[0].state), 'S4 state: ' + s4[0].state)
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevInject === undefined) delete process.env.AIOS_INJECT_PROBE; else process.env.AIOS_INJECT_PROBE = prevInject
    if (prevPhase === undefined) delete process.env.AIOS_PHASE_INJECT; else process.env.AIOS_PHASE_INJECT = prevPhase
    if (prevRemind === undefined) delete process.env.AIOS_REMINDER_PROBE; else process.env.AIOS_REMINDER_PROBE = prevRemind
    try { rmSync(V, { recursive: true, force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.log', { force: true }) } catch { /* 静默 */ }
  }
})

// 能力注入**打分** + 条数 **3→5** ──────────────────
//   依据（Lead 实测诊断）：`pool:3` = 请求 `budget.max_candidates=3` 截断；放宽后出 7 条能力、`host-runtime-traps`
//   排 #4 被截掉 ⇒ ① 上限 3→5（含请求 budget）② 候选按 0–1 分数降序；分数**只进探针**、不进注入文本。
//   注入 slice **5→1**（只注 top1），请求 `budget` **仍 5**（池子保持）；
//      ⛔ 打分公式 / 渲染文案 / 时机不变 —— 测试只改条数断言。
check('S156 打分纯函数：通道/轴/强证据/命中词越多分越高（0–1 单调）· 无信号 ⇒ 0 且回落 none', () => {
  const raw = o => Object.assign({ id: 'x', hit_channels: [], evidence: [] }, o)
  const weak = raw({ hit_channels: ['topic'], evidence: [{ channel: 'topic', strength: 'weak', matched: ['t1'] }] })
  const mid = raw({ hit_channels: ['topic', 'intent'], evidence: [{ channel: 'topic', strength: 'medium', matched: ['t1', 't2'] }] })
  const strongAxis = raw({
    hit_channels: ['axis', 'topic', 'intent'],
    evidence: [
      { channel: 'axis', strength: 'strong', matched: ['a', 'b', 'c'] },
      { channel: 'topic', strength: 'strong', matched: ['d', 'e'] },
      { channel: 'intent', strength: 'medium', matched: ['f'] },
    ],
  })
  const sw = FC.phaseCapScoreOf(weak)
  const sm = FC.phaseCapScoreOf(mid)
  const ss = FC.phaseCapScoreOf(strongAxis)
  assert.ok(sw > 0 && sw <= 1, '分数必须落在 (0,1]: ' + sw)
  assert.ok(ss > sm && sm > sw, '单调：强轴(' + ss + ') > 中(' + sm + ') > 弱(' + sw + ')')
  assert.equal(FC.phaseCapScoreOf(null), 0)
  assert.equal(FC.phaseCapScoreOf({}), 0, '⛔ 无信号不编分')
  assert.ok(FC.hasCapScoreSignals(weak) && !FC.hasCapScoreSignals({ id: 'x' }))
  // 回落：候选**一个分数信号都没有** ⇒ `score_mode:"none"` + 顺序 = python 返回顺序
  const noSig = {
    candidates: ['a', 'b', 'c'].map(n => ({
      id: 'aios.capabilities:' + n, name: n, kind: 'capability',
      local_path: 'capabilities/' + n + '.md', source: { id: 'aios.capabilities' }, intro: '候选 ' + n,
    })), // ⛔ 无 `hit_channels` / `evidence`
  }
  const r = FC.renderPhaseCandidates(noSig, 'S1', new Set())
  assert.equal(r.scoreMode, 'none', '无信号 ⇒ score_mode=none')
  assert.deepEqual(r.scores, [0], '无信号 ⇒ 只注 1 条，分数 0（⛔ 不编分）')
  assert.deepEqual(r.ids.map(x => x.split(':').pop()), ['a'], '按 python 返回顺序取首条（v51i 只注 top1 · ⛔ 不重排）')
})

check('S157 top1：池 7/5/3 条都只注 1 条，且必须是打分最高的那条（⛔ 不凑数）', () => {
  const mk = (n, chans, strength) => ({
    id: 'aios.capabilities:c' + n, name: 'c' + n, kind: 'capability',
    local_path: 'capabilities/c' + n + '.md', source: { id: 'aios.capabilities' }, intro: '候选 ' + n,
    hit_channels: chans, evidence: chans.map(ch => ({ channel: ch, strength, matched: [ch] })),
  })
  const seven = {
    candidates: [
      mk(1, ['topic'], 'weak'), mk(2, ['axis', 'topic'], 'strong'), mk(3, ['topic', 'intent'], 'medium'),
      mk(4, ['axis', 'topic', 'intent'], 'strong'), mk(5, ['role'], 'weak'), mk(6, ['topic', 'role'], 'medium'),
      mk(7, ['axis'], 'medium'),
    ],
  }
  // 期望 top1：与 `renderPhaseCandidates` **同口径**（分数降序 + 同分保持 python 顺序）
  const topOf = cands => {
    const scored = cands.map((c, i) => ({ id: c.id, i, s: FC.phaseCapScoreOf(c) }))
    scored.sort((a, b) => (b.s - a.s) || (a.i - b.i))
    return scored[0]
  }
  // 🔴 实验核心：池 5 条 ⇒ 只注 1 条，且是最高分那条（不是"池子只有 1 条"）
  const five = seven.candidates.slice(0, 5)
  const wantFive = topOf(five)
  const r5 = FC.renderPhaseCandidates({ candidates: five }, 'S2', new Set())
  assert.equal(r5.ids.length, 1, '🔴 v51i：池 5 ⇒ 注入恰好 1 条')
  assert.equal(r5.scores.length, 1, 'scores 与 ids 等长')
  assert.equal(r5.ids[0], wantFive.id, '🔴 注入的必须是最高分那条: ' + r5.ids[0] + ' vs ' + wantFive.id)
  assert.equal(r5.scores[0], wantFive.s, 'scores[0] 必须是最高分: ' + r5.scores[0] + ' vs ' + wantFive.s)
  // 池 7 / 池 3 同样只注 1 条（⛔ 不凑数、⛔ 不因池小放宽）
  for (const cands of [seven.candidates, seven.candidates.slice(0, 3)]) {
    const want = topOf(cands)
    const rr = FC.renderPhaseCandidates({ candidates: cands }, 'S2', new Set())
    assert.equal(rr.ids.length, 1, '池 ' + cands.length + ' ⇒ 仍只注 1 条')
    assert.equal(rr.ids[0], want.id, '池 ' + cands.length + ' ⇒ top1 必须是最高分')
    assert.equal(rr.scores[0], want.s, '池 ' + cands.length + ' ⇒ scores[0] = 最高分')
  }
  assert.equal(FC.PHASE_MAX_CANDIDATES, 1, '🔴 v51i：注入条数常量 = 1')
  assert.equal(FC.PHASE_BUDGET_CANDIDATES, 5, '🔴 v51i：请求 budget 仍 = 5（池子够大，top1 才有意义）')
})

check('S158 / 探针契约：`candidates` 与 `scores` 等长且都为注入的那条 top1（⛔ 分数不进文本）', () => {
  const mk = (n, chans) => ({
    id: 'aios.capabilities:p' + n, name: 'p' + n, kind: 'capability',
    local_path: 'capabilities/p' + n + '.md', source: { id: 'aios.capabilities' }, intro: '候选 ' + n,
    hit_channels: chans, evidence: chans.map(ch => ({ channel: ch, strength: 'strong', matched: [ch] })),
  })
  const set = {
    candidates: [mk(1, ['topic']), mk(2, ['axis', 'topic']), mk(3, ['axis']), mk(4, ['intent']), mk(5, ['role']),
      mk(6, ['topic', 'intent'])],
  }
  const r = FC.renderPhaseCandidates(set, 'S2', new Set())
  // 接线处就是这两个数组直接进探针（`candidates: rendered.ids.slice(0, PHASE_MAX_CANDIDATES)`）
  const probeCandidates = r.ids.slice(0, FC.PHASE_MAX_CANDIDATES)
  const probeScores = r.scores.slice(0, FC.PHASE_MAX_CANDIDATES)
  assert.equal(r.ids.length, 1, '🔴 v51i：注入 1 条（top1）')
  assert.equal(probeCandidates.length, probeScores.length, '🔴 candidates.length === scores.length')
  assert.equal(probeCandidates.length, 1, '数组内容 = 注入的那 1 条')
  for (const s of probeScores) assert.ok(typeof s === 'number' && s >= 0 && s <= 1, 'scores ∈ [0,1]: ' + s)
  // ⛔ 分数不进注入文本（形态仍是「能力名 — 一句话 + → 路径」）
  for (const s of probeScores) assert.ok(!r.text.includes(String(s)), '⛔ 分数不得写进注入文本: ' + s)
  assert.ok(r.text.includes('  · p') && r.text.includes('→ capabilities/p'), '三行格式不变')
  // 文本行数 = 1 标签 + 1×(名字行+指针行)
  assert.equal(r.text.split('\n').length, 1 + probeCandidates.length * 2)
})

// **同回合 claim ⇒ 本回合即对 Runtime 可见** ─────────────
//   缺陷（P23 探针实录）：`s.cards` 只在 `agent/pre-step` 且 `msgs>0` 时重扫
//     ⇒ 回合开始后才 claim 的卡**本回合看不见** ⇒ claim 紧跟一条
//       `phase-inject{phase:"S2",state:"no-anchor",ownedCards:0}`（阶段判定晚一拍）。
//   修法口径：claim 成功后在 `tools/post-execute` 里**只刷本会话的 `s.cards`**（⛔ 不发事件 /
//     ⛔ 不改全局扫描时机 / ⛔ 不动阶段与节点注入逻辑）。
//   ⚠️ 本用例**不得**在 claim 与断言之间再插一次 `agent/pre-step` —— 那会走"新回合重扫"的旧路径，
//      用例就测不到修复（旧实现在这里恒 0 条 phase-inject：`ownedCards` 0 + 无 edit ⇒ `phaseOf` 返回 null）。
checkAsync('S159 同回合 claim 即可见：回合开始无卡 ⇒ claim 成功那一步即判出 S1（⛔ 不等下一次 pre-step）', async () => {
  const V = SCRATCH + '/_selftest_v51e'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevInject = process.env.AIOS_INJECT_PROBE
  const prevPhase = process.env.AIOS_PHASE_INJECT
  const prevRemind = process.env.AIOS_REMINDER_PROBE
  const CARD = 'TASK-20261101-159'
  const SID = 'selftest-v51e'
  rmSync(V, { recursive: true, force: true })
  mkdirSync(V, { recursive: true })
  process.env.AIOS_STATE_DIR = V
  delete process.env.AIOS_PHASE_INJECT // 打开**阶段**接线（主套件默认 off · 照 P67；首拍接线另由常量门控）
  process.env.AIOS_INJECT_PROBE = V + '/inject_probe.json'
  writeFileSync(process.env.AIOS_INJECT_PROBE, JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }))
  process.env.AIOS_REMINDER_PROBE = V + '/no_reminder.json'
  const AG = agent(SID, { delegationDepth: 0 })
  const mine = () => records().filter(r => r.ev === 'phase-inject' && r.session === SID)
  try {
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    const call = async (cid, name, args) => {
      const p = { callId: cid, name, arguments: args, agent: AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    // ① 回合开始：卡还不存在 ⇒ 快照 0 张（这一步**不能**出现任何 phase-inject：没占卡、没改动、没连败）
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('先把卡建好占用，然后开工')] })
    await call('v51e-pre', 'pwsh', { command: 'git status' })
    // ⚠️ v51j/v51k（2026-11-01）：首拍通道默认关；过滤保留作复活保险 ⇒ 等价于断言阶段通道零条
    assert.equal(mine().filter(r => r.basis !== 'first-step').length, 0,
      '占卡前不得出现**阶段** phase-inject（未进入任何阶段 · ⛔ 不猜）')
    // ② claim 的**工具往返**：`task_card.py` 写卡（State=Executing + `.log` 留痕带 session）——
    //    这里在 pre-execute 与 post-execute 之间落盘，等价于真实工具的执行效果（⛔ 真跑 python）。
    const claimCmd = 'python tools/task_card.py claim ' + CARD
    const pClaim = { callId: 'v51e-claim', name: 'pwsh', arguments: { command: claimCmd }, agent: AG }
    wf('tools/pre-execute', pClaim)
    writeFileSync(CARDS + '/' + CARD + '.md', cardFull(CARD, 'Executing', 0, '同回合 claim 后阶段判定要立刻看见卡', '跑一次工具验证 S1'))
    writeFileSync(CARDS + '/' + CARD + '.log', '| 01:00 | Executing | claim 占用（session: ' + SID + '） | Worker |\n')
    // ③ **同一次** post-execute 里，阶段判定就必须看见这张卡（旧实现：`ownedCards` 仍 0 ⇒ 零探针）
    const outClaim = await h(pClaim, { isError: false, content: [{ type: 'text', text: 'claimed' }] }, () => ({ kind: 'accept' }))
    assert.ok(outClaim, '必须返回 downstream（⛔ 不得因快照刷新改变工具结果）')
    const rec = mine().filter(r => r.basis !== 'first-step')
    assert.equal(rec.length, 1, '🔴 同回合 claim 后必须判出阶段并注入一次（旧实现：0 条 = 快照停在回合开始）')
    assert.equal(rec[0].phase, 'S1', '恰好占用 1 张卡且其后无实质改动 ⇒ S1（探针 phase: ' + rec[0].phase + '）')
    assert.notEqual(rec[0].state, 'no-anchor', '🔴 卡必须同回合可见（no-anchor + ownedCards:0 就是 P23 的缺陷形态）')
    assert.ok(['injected', 'spawn-failed', 'no-candidate'].includes(rec[0].state), 'state 四态之一: ' + rec[0].state)
    // ④ 记账：S1 进 `sent`（每阶段每会话一次）；且**没有多刷**任何一条
    const slot = FC.PHASE_INJECT.get(SID)
    assert.ok(slot && slot.sent.has('S1'), 'S1 必须记账（阶段已进入）')
    // ⑤ ⛔ 不发事件：刷新快照本身**不新增**任何探针（只有既有的 `card-cmd` 诊断 + 阶段注入各一条）
    assert.equal(records().filter(r => r.ev === 'card-snapshot-refresh').length, 0, '正常路径下刷新快照不得落事件')
    assert.equal(records().filter(r => r.ev === 'card-cmd' && r.session === SID && r.op === 'claim').length, 1,
      '既有 `card-cmd` 诊断仍恰好一条（刷新不改变既有记账）')
    // ⑥ 再跑一次工具（同回合）⇒ 只有 dup，不会重复注入（防刷屏口径不变）
    await call('v51e-after', 'pwsh', { command: 'git status' })
    assert.equal(mine().filter(r => r.basis !== 'first-step' && r.state !== 'dup').length, 1,
      '同阶段只注入一次（dup 不计）')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevInject === undefined) delete process.env.AIOS_INJECT_PROBE; else process.env.AIOS_INJECT_PROBE = prevInject
    if (prevPhase === undefined) delete process.env.AIOS_PHASE_INJECT; else process.env.AIOS_PHASE_INJECT = prevPhase
    if (prevRemind === undefined) delete process.env.AIOS_REMINDER_PROBE; else process.env.AIOS_REMINDER_PROBE = prevRemind
    try { rmSync(V, { recursive: true, force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.log', { force: true }) } catch { /* 静默 */ }
  }
})

// **裸 ID claim 必须能解析到回合开始后才出现的卡** ──────
//   实证（真实探针 · 本会话 08:01）：`ev=card-cmd{op:"claim", taskId:"TASK-20261101-017", card:null,
//     note:"ID 未唯一命中卡列表（0 或多个）⇒ ⛔ 不记（不猜）"}` —— 该卡是**同一回合**先 create 后 claim
//     的**平铺卡**，盘上确实存在（State=Executing + `.log` 留痕）。
//   根因：`cardKeyOfId()` 只读 `s.knownCardKeys`（**回合开始** pre-step 的快照 · L6172 赋值）；
//     只刷了 `s.cards`（焦点/阶段判定），**没刷这个 key 缓存** ⇒ 新卡 ⇒ 缓存 0 命中 ⇒ `card:null`。
//   修法口径：缓存解析不到时**现扫一次**（`scanCards()`）再判一次；仍 0/多 ⇒ 仍 `null`（⛔ 不猜）。
//   ⛔ 不碰 `task_card.py` / 不改卡片状态 / 不改既有 `card-cmd` 成功路径语义。
checkAsync('S160 裸 ID claim 解析：回合开始后才建的平铺卡 ⇒ 同回合 claim 即解析到卡 key（⛔ 不再 card:null）', async () => {
  const V = SCRATCH + '/_selftest_v51f'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevPhase = process.env.AIOS_PHASE_INJECT
  const CARD = 'TASK-20261101-160'
  const DUP = 'TASK-20261101-162'
  const SID = 'selftest-v51f'
  rmSync(V, { recursive: true, force: true })
  mkdirSync(V, { recursive: true })
  process.env.AIOS_STATE_DIR = V
  process.env.AIOS_PHASE_INJECT = 'off' // 本用例只验 card-cmd 记账，⛔ 不 spawn 检索
  const AG = agent(SID, { delegationDepth: 0 })
  const claims = () => records().filter(r => r.ev === 'card-cmd' && r.session === SID && r.op === 'claim')
  const rescans = () => records().filter(r => r.ev === 'card-id-rescan' && r.session === SID)
  rmSync(CARDS + '/' + CARD + '.md', { force: true })
  rmSync(CARDS + '/' + CARD + '.log', { force: true })
  rmSync(CARDS + '/' + DUP + '.md', { force: true })
  rmSync(CARDS + '/projA/' + DUP + '.md', { force: true })
  try {
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    const call = async (cid, cmd) => {
      const p = { callId: cid, name: 'pwsh', arguments: { command: cmd }, agent: AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    // ① 回合开始：卡还不存在（= create 与 claim 在同一回合）
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('先把卡建好占用，然后开工')] })
    // ② 工具往返之间落盘（等价于 task_card.py create + claim 的真实效果）
    writeFileSync(CARDS + '/' + CARD + '.md', cardFull(CARD, 'Executing', 0, 'v51f 裸 ID 解析', '跑一次工具验证'))
    writeFileSync(CARDS + '/' + CARD + '.log', '| 01:00 | Executing | claim 占用（session: ' + SID + '） | Worker |\n')
    const out1 = await call('v51f-claim', 'python tools/task_card.py claim ' + CARD)
    assert.ok(out1, '必须返回 downstream')
    assert.equal(claims().length, 1, '一次 claim ⇒ 一条 card-cmd')
    assert.equal(claims()[0].taskId, CARD)
    assert.equal(claims()[0].card, CARD + '.md', '🔴 裸 ID 的平铺卡必须解析到卡 key（旧实现 = null）')
    // ③ 现扫一次的读数（只在缓存解析失败时发生；成功路径不受影响）
    assert.equal(rescans().length, 1, '解析失败 ⇒ 必须现扫一次并留读数（⛔ 不允许零报错零探针）')
    assert.equal(rescans()[0].state, 'hit', '现扫后唯一命中 ⇒ state=hit')
    // ④ 项目/ID 形态仍正常（卡在回合开始快照里 ⇒ 走缓存，不需要现扫）
    await call('v51f-proj', 'python tools/task_card.py claim projA/TASK-20260101-001')
    const proj = claims().filter(r => r.taskId === 'projA/TASK-20260101-001')
    assert.equal(proj.length, 1, '项目/ID 形式仍产生一条 card-cmd')
    assert.equal(proj[0].card, 'projA/TASK-20260101-001.md', '🔴 项目/ID 仍正常')
    // ⑤ 真正不存在的 ID ⇒ 仍 null（⛔ 不猜）
    await call('v51f-missing', 'python tools/task_card.py claim TASK-20260999-999')
    const missing = claims().filter(r => r.taskId === 'TASK-20260999-999')
    assert.equal(missing.length, 1)
    assert.equal(missing[0].card, null, '不存在 ⇒ 仍 null（⛔ 不猜）')
    assert.equal(rescans()[1].state, 'miss', '现扫后仍 0 命中 ⇒ state=miss')
    assert.equal(rescans()[1].hits, 0)
    // ⑥ 重名（平铺 + 项目目录同 ID）⇒ 仍 null（⛔ 不猜）
    writeFileSync(CARDS + '/' + DUP + '.md', cardFull(DUP, 'Executing', 0, 'dup flat', 'x'))
    writeFileSync(CARDS + '/projA/' + DUP + '.md', cardFull(DUP, 'Executing', 0, 'dup proj', 'x'))
    await call('v51f-dup', 'python tools/task_card.py claim ' + DUP)
    const dup = claims().filter(r => r.taskId === DUP)
    assert.equal(dup.length, 1)
    assert.equal(dup[0].card, null, '重名 ⇒ 仍 null（⛔ 不猜）')
    assert.equal(rescans()[2].state, 'miss', '重名 ⇒ state=miss')
    assert.equal(rescans()[2].hits, 2, '重名的两个 key 都要如实计数')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevPhase === undefined) delete process.env.AIOS_PHASE_INJECT; else process.env.AIOS_PHASE_INJECT = prevPhase
    try { rmSync(V, { recursive: true, force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.log', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + DUP + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/projA/' + DUP + '.md', { force: true }) } catch { /* 静默 */ }
  }
})

// 能力注入打分**要有区分度** ────────────────────────────────────
//   实证（Lead 探针 · 2026-11-01 07:42 · `.aios/_aios-activation.probe.log`）：
//     `candidates:["…frontend-ui","…senior-engineer"] · scores:[0.383,0.383]` —— 两条候选**同分**；
//     人为判：`senior-engineer`（评审/设计）相关 · `frontend-ui`（做页面）不相关。
//   根因（读 `phaseCapScoreOf`）：旧公式 0.35*通道多样性 + 0.30*轴命中 + 0.25*证据强度 + 0.10*命中词数；
//     · 通道多样性 `min(1, n/3)`、证据强度 `min(1, (2s+m+0.5w)/3)`、命中词数 `min(1, n/6)` **都会饱和**；
//     · 两条候选若"同通道 + 同轴 + 同强度 + 同命中词数" ⇒ 四项全等 ⇒ **恒同分**（与是否真相关无关）。
//   修法：把**具体匹配**变成可区分信号（全部来自候选 payload + 卡 topic，⛔ 不读正文 / 不调远程）：
//     channelKind（通道种类权重）· matchedCoverage（命中词 ∩ topic 词 / topic 词数）·
//     axisCoverage（轴值命中数）· evidenceLevel（分母 3→4，消饱和）· channelDiversity（保留）。
//   ⛔ 打分公式 / 渲染文本形态 / `score_mode` 语义**不变**；分数仍**只进探针**。
//   注入条数单独收紧 5→1（本用例改看 top1，区分度用同一打分函数分别算两条候选）。
check('S161 打分区分度：真实评审 topic 下 senior-engineer 显著高于 frontend-ui（差 ≥0.05）· 同通道同轴不再恒同分', () => {
  const TOPIC = '按资深工程师视角评审阶段注入设计稿：审查 runtime 注入架构与取舍 ｜ 能力注入打分的有区分度排序（评审）'
  // ⚠️ 以下两条 = 2026-11-01 08:1x 用 `tools/probes/_retrieval_request_probe.py` 以**同一 TOPIC** 实跑到的
  //    `candidate-set/v1` 原始 item（`hit_channels` / `evidence` 逐字复制；⛔ 不编造信号）。
  const senior = {
    id: 'aios.capabilities:senior-engineer', name: 'senior-engineer', kind: 'capability', role: 'evidence',
    local_path: 'capabilities/senior-engineer.md', source: { id: 'aios.capabilities' },
    intro: '以资深 SaaS 工程师的眼光评审计划、架构与取舍，直接给结论。',
    hit_channels: ['topic'],
    evidence: [
      { field: 'work_topic', channel: 'topic', basis: 'structured-key-match', strength: 'strong',
        matched: ['审查', '工程', '师视', '架构', '深工', '程师', '视角', '评审'] },
      { field: 'work_topic', channel: 'topic', basis: 'description-match', strength: 'medium',
        matched: ['审查', '工程', '师视', '架构', '深工', '程师', '视角', '评审'] },
    ],
  }
  const frontend = {
    id: 'aios.capabilities:frontend-ui', name: 'frontend-ui', kind: 'capability', role: 'verification',
    local_path: 'capabilities/frontend-ui.md', source: { id: 'aios.capabilities' },
    intro: '做前端页面、组件，或觉得界面有点丑时，从设计令牌到构图再到审美门禁走一条链。',
    hit_channels: ['topic'],
    evidence: [
      { field: 'work_topic', channel: 'topic', basis: 'structured-key-match', strength: 'strong', matched: ['设计'] },
      { field: 'work_topic', channel: 'topic', basis: 'description-match', strength: 'medium', matched: ['设计'] },
    ],
  }
  const set = { candidates: [frontend, senior], budget_applied: { matched_before_budget: 2 } }
  const r = FC.renderPhaseCandidates(set, 'S1', new Set(), TOPIC)
  assert.equal(r.scoreMode, 'capability-signals', '有信号 ⇒ 仍走打分（`score_mode` 语义不变）')
  assert.equal(r.ids.length, 1, '🔴 v51i：注入只取 top1')
  assert.equal(r.ids[0], senior.id, '🔴 真实相关性：senior-engineer（评审）必须排前')
  // 区分度判据不能只看 `r.scores`（top1 后只剩 1 个分数）⇒ 用同一打分函数对两条候选分别算
  const sSenior = FC.phaseCapScoreOf(senior, TOPIC)
  const sFrontend = FC.phaseCapScoreOf(frontend, TOPIC)
  const gap = sSenior - sFrontend
  assert.ok(gap >= 0.05, '🔴 相关性差必须进分数（≥0.05）: gap=' + gap.toFixed(3) + ' scores=' + JSON.stringify([sSenior, sFrontend]))
  // 形态不变（⛔ 不得为凑分改渲染）；条数由 v51i 定为 1
  assert.equal(FC.PHASE_MAX_CANDIDATES, 1, 'v51i：PHASE_MAX_CANDIDATES = 1')
  assert.equal(r.text.split('\n').length, 1 + r.ids.length * 2, '渲染文本仍是「标签 + 每条两行」')
  assert.ok(r.text.startsWith('【AI-OS · 决策阶段 · 能力候选】'), '标签行不变')
  assert.ok(r.text.includes('  · senior-engineer — ') && r.text.includes('→ capabilities/senior-engineer.md'))
  for (const s of r.scores) assert.ok(!r.text.includes(String(s)), '⛔ 分数仍不进注入文本: ' + s)
  // ⑦ 覆盖比例：同通道同强度下，命中 topic 词**更多**的候选必须更高（旧公式 4 词 vs 1 词只差 0.05）
  const mkT = (n, matched) => ({
    id: 'aios.capabilities:' + n, name: n, kind: 'capability',
    local_path: 'capabilities/' + n + '.md', source: { id: 'aios.capabilities' }, intro: 'x',
    hit_channels: ['topic'],
    evidence: [{ field: 'work_topic', channel: 'topic', basis: 'structured-key-match', strength: 'strong', matched }],
  })
  const topicB = '阶段注入架构取舍评审设计' // 11 个 bigram（阶段/段注/注入/入架/架构/构取/取舍/舍评/评审/审设/设计）
  const coverA = FC.phaseCapScoreOf(mkT('cA', ['阶段', '注入', '架构', '设计']), topicB)
  const coverB = FC.phaseCapScoreOf(mkT('cB', ['阶段']), topicB)
  assert.ok(coverA - coverB >= 0.10,
    '🔴 topic 覆盖比例必须起作用（4/11 vs 1/11）: ' + coverA + ' vs ' + coverB)
  // ⑧ 证据强度不再在 3 分处饱和（1 strong+medium 与 2 strong 必须区分）
  const mkE = (n, ev) => ({
    id: 'aios.capabilities:' + n, name: n, kind: 'capability',
    local_path: 'capabilities/' + n + '.md', source: { id: 'aios.capabilities' }, intro: 'x',
    hit_channels: ['topic'], evidence: ev,
  })
  const twoStrong = FC.phaseCapScoreOf(mkE('e1', [
    { channel: 'topic', strength: 'strong', matched: ['阶段', '注入'] },
    { channel: 'topic', strength: 'strong', matched: ['阶段', '注入'] },
  ]))
  const strongMedium = FC.phaseCapScoreOf(mkE('e2', [
    { channel: 'topic', strength: 'strong', matched: ['阶段', '注入'] },
    { channel: 'topic', strength: 'medium', matched: ['阶段', '注入'] },
  ]))
  assert.ok(twoStrong - strongMedium >= 0.04,
    '🔴 证据强度消饱和：2×strong 必须 > strong+medium（旧公式两者都封顶）: ' + twoStrong + ' vs ' + strongMedium)
  // ⑨ 轴**覆盖数**（不是二元"含 axis"）必须起作用：3 个轴值 > 2 个轴值（命中词数对齐 ⇒ 旧公式同分）
  const axisA = FC.phaseCapScoreOf(mkE('a1', [
    { field: 'axes.help', channel: 'axis', strength: 'strong', matched: ['数据', '前端', '测试'] },
    { channel: 'topic', strength: 'medium', matched: ['阶段'] },
  ]))
  const axisB = FC.phaseCapScoreOf(mkE('a2', [
    { field: 'axes.help', channel: 'axis', strength: 'strong', matched: ['数据', '前端'] },
    { channel: 'topic', strength: 'medium', matched: ['阶段', '注入'] },
  ]))
  assert.ok(axisA - axisB >= 0.03,
    '🔴 轴覆盖数必须进分数（命中词数相同 ⇒ 旧公式同分）: ' + axisA + ' vs ' + axisB)
})

// 阶段检索请求带 `axes`（词表三维标签）──────────────────────────
//   为什么（Lead A/B 实测 · 同一 work_topic）：不带 axes ⇒ capabilities 候选 **3** 条、`axis` 通道证据 0；
//   带 axes ⇒ **5** 条，`senior-engineer` 得 **2** 条 axis 证据（`domain=AI-OS 自身` + `help=评审`）。
//   `axis` 是 python 侧**权重最高**的确定性匹配，但它**只在请求带 axes 时才产生证据**
//   （`tools/probes/_retrieval_request_probe.py:axis_hits` 原注释）；
//   现行 S1 两条候选**同分**（`scores:[0.356,0.356]`）的根因正是"取证件对称、无可区分信号"。
//   来源两级：① 本会话最近一条 `auto_capability`（`latestWorkReport()` 的 need/concern · **只收词表值**）；
//             ② 会话**没有**上报过 ⇒ 按阶段兜底 `help`（domain/concern 拿不到 ⇒ 留空）。
//   ⛔ 不改条数 / 渲染文本 / `score_mode` / 打分公式 / `tools/probes/`；无 axes 时请求形状与旧版**逐字段一致**。
check('S162 有 work_report ⇒ 请求带 axes，且值全部来自 NEEDS-VOCAB 三维', () => {
  const SID = 'selftest-v51h-162'
  const wr = FC.buildWorkReport(SID, {
    what: '评审阶段注入改动', confirmed: 'user',
    // ⚠️ 故意混入两处**非词表值**：必须被丢弃（⛔ 不猜同义词 · ⛔ 不自造值）
    need: ['AI-OS 自身', '评审', '随便写的非法值'],
    concern: ['正确性', '也不是词表值'],
  }, 1793500000000)
  assert.equal(wr.ok, true)
  FC.WORK_REPORTS.set(SID, [wr.rep])
  try {
    const card = {
      key: 'proj/TASK-20260101-001.md', state: 'Executing', step: '',
      goal: '让阶段注入的请求带上词表轴标签', next: '改 buildPhaseRetrievalRequest 的 axes 来源', occupancy: null,
    }
    const req = FC.buildPhaseRetrievalRequest('S1', card, { historyCoverage: 'complete' }, 7, SID)
    assert.ok(req, '有卡 ⇒ 必须有请求')
    assert.deepEqual(req.axes, { domain: ['AI-OS 自身'], help: ['评审'], concern: ['正确性'] },
      '🔴 need/concern 里恰好是词表值的项 ⇒ axes；非法值必须丢弃（实际: ' + JSON.stringify(req.axes) + '）')
    // 逐值复核来源（⛔ 不信任实现自报）
    for (const v of req.axes.domain) assert.ok(FC.WR_DOMAIN_VALUES.includes(v), 'domain 值不在词表: ' + v)
    for (const v of req.axes.help) assert.ok(FC.WR_HELP_TYPES.includes(v), 'help 值不在词表: ' + v)
    for (const v of req.axes.concern) assert.ok(FC.WR_CONCERN_VALUES.includes(v), 'concern 值不在词表: ' + v)
    // 既有字段语义不变
    assert.equal(req.need.state, 'unknown', '⛔ 不改既有字段语义（need 仍 unknown）')
    assert.ok(req.work.work_topic.value.includes('buildPhaseRetrievalRequest'))
  } finally {
    FC.WORK_REPORTS.delete(SID)
  }
})

check('S163 无 work_report ⇒ 按阶段兜底 help（S1/S2/S3/S4 各断言一次 · domain/concern 留空）', () => {
  const SID = 'selftest-v51h-163' // 该会话**没有任何**上报
  FC.WORK_REPORTS.delete(SID) // 确保该会话真的没有上报
  const WANT = {
    S1: ['评审', '设计'],
    S2: ['实现', '验证'],
    S3: ['调试'],
    S4: ['验证', '审计·清理'],
  }
  const card = {
    key: 'proj/TASK-20260101-001.md', state: 'Executing', step: '',
    goal: '阶段能力候选要按词表轴排序', next: '校验四个阶段的兜底 help', occupancy: null,
  }
  for (const ph of ['S1', 'S2', 'S3', 'S4']) {
    const req = FC.buildPhaseRetrievalRequest(ph, card, { historyCoverage: 'complete' }, 100, SID)
    assert.ok(req, ph + '：有卡 ⇒ 必须有请求')
    assert.deepEqual(req.axes, { help: WANT[ph] }, '🔴 ' + ph + ' 兜底 help 必须是 ' + WANT[ph].join('/'))
    assert.equal('domain' in req.axes, false, ph + '：domain 拿不到 ⇒ 留空（⛔ 不编）')
    assert.equal('concern' in req.axes, false, ph + '：concern 拿不到 ⇒ 留空（⛔ 不编）')
    for (const v of req.axes.help) assert.ok(FC.WR_HELP_TYPES.includes(v), ph + '：兜底 help 值必须在词表内: ' + v)
  }
})

check('S164 全非法 + 无默认可用 ⇒ 请求不带 axes（形状与旧版逐字段一致）', () => {
  const SID = 'selftest-v51h-164'
  const wr = FC.buildWorkReport(SID, {
    what: 'x', confirmed: 'user',
    need: ['乱写的甲', '乱写的乙'], concern: ['乱写的丙'],
  }, 1793500000000)
  assert.equal(wr.ok, true)
  FC.WORK_REPORTS.set(SID, [wr.rep])
  try {
    // ① 有上报但**全是非法值** ⇒ 不拿阶段默认去补（默认是"没表达过需求"的兜底）
    const ax = FC.phaseAxesOf('S1', SID)
    assert.equal(ax, null, '🔴 全非法 ⇒ 轴集为空（⛔ 不用 S1 默认 help 覆盖 Agent 已表达的需求）')
    const card = {
      key: 'proj/TASK-20260101-001.md', state: 'Executing', step: '',
      goal: '请求形状向后兼容', next: '验证无 axes 时不新增字段', occupancy: null,
    }
    const req = FC.buildPhaseRetrievalRequest('S1', card, { historyCoverage: 'complete' }, 1, SID)
    assert.ok(req)
    assert.equal('axes' in req, false, '🔴 不带 axes 字段（⛔ 不是 axes:{} / 空数组 / null）')
    assert.deepEqual(Object.keys(req).sort(),
      ['budget', 'need', 'phase', 'request_id', 'schema', 'sources', 'work'],
      '🔴 旧版字段集合逐字一致（向后兼容）')
    // ② "无默认可用"：阶段不在默认表 ⇒ 同样不带（⛔ 不编默认）
    assert.equal(FC.phaseAxesOf('S9', 'selftest-no-report-164'), null, '🔴 无默认可用 ⇒ null（⛔ 不自造）')
    assert.deepEqual(FC.PHASE_DEFAULT_HELP.S1, ['评审', '设计'], '默认表只认 S1–S4（S9 无条目）')
  } finally {
    FC.WORK_REPORTS.delete(SID)
  }
})

// ── 🔴 v51j（2026-11-01 · Lead 实验 B「注入窗口前移」）· 🔴 v51k（2026-11-01 · Human 裁定）**默认关闭** ──
//   历史：首拍注入已按 v51j 实现并真机触发；但真机读数**劣于** claim 后的常规 S1
//     （首拍 topic = 用户首条消息，含【AI-OS · …】引导文本 ⇒ top1 与当时工作无关；
//       同会话 claim 后 topic = 卡的 `Goal ｜ Next Action` ⇒ top1 相关）。
//   ⇒ `FIRST_STEP_INJECT_ENABLED = false` —— 接线点**不调用** `firstStepInjectOnce` ⇒ 零注入、零探针。
//   本组用例改成验「开关关 ⇒ 不注入」；**实现仍在**，请求构造纯函数照旧直接测（复活 = 改常量 true）。
//   ⛔ 没有删用例 / 没有放宽语义：S166 仍验「无卡走 v51a 静默」，S167 仍验「claim 后 S1 逐字不变」。
checkAsync('S165 首拍注入开关默认关 ⇒ 零注入零探针（实现保留 · 请求纯函数仍可测）', async () => {
  // ⓪ 纯函数层：实现**保留**（请求构造 · phase=S1 + topic=用户首条消息 · ≤400 · ⛔ 不用卡的描述 / 不用 intentText）
  {
    assert.equal(FC.FIRST_STEP_INJECT_ENABLED, false, '🔴 v51k：开关必须默认关（Human 裁定）')
    const wc = { intentText: '元话语：随便聊聊阶段注入', historyCoverage: 'complete' }
    const req = FC.buildFirstStepRetrievalRequest('  帮我把 runtime 的注入时机前移到首拍  ', wc, 42, 'selftest-v51j-165')
    assert.ok(req, '🔴 首条消息非空 ⇒ 请求构造仍可用（实现保留 · 只是不再接线）')
    assert.equal(req.schema, 'retrieval-request/v1', '请求形状照旧（⛔ 不新增 schema）')
    assert.equal(req.phase, 'S1', '首拍一律按 S1（决策阶段）构造')
    assert.equal(req.request_id, 'first-step-S1-42', 'request_id 前缀与常规阶段可区分')
    assert.equal(req.work.work_topic.value, '帮我把 runtime 的注入时机前移到首拍', 'topic = 用户首条消息（空白归一）')
    assert.equal(req.budget.max_candidates, FC.PHASE_BUDGET_CANDIDATES, '🔴 v51i 口径不变：budget 仍 = 池子常量 5')
    assert.ok(!JSON.stringify(req).includes('元话语'), '⛔ 不得把 `wc.intentText` 当 topic（它每回合都会被改写）')
    const long = '把首拍注入做成可验证机制'.repeat(60)
    const req2 = FC.buildFirstStepRetrievalRequest(long, wc, 43, '')
    assert.equal(req2.work.work_topic.value.length, FC.PHASE_TOPIC_MAX, '上限沿用 400')
    assert.equal(FC.buildFirstStepRetrievalRequest('   ', wc, 44, ''), null, '空首条消息 ⇒ null（⛔ 不拿空 topic 检索）')
    assert.equal(FC.buildFirstStepRetrievalRequest('', wc, 45, ''), null)
  }
  const V = SCRATCH + '/_selftest_v51j_165'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevInject = process.env.AIOS_INJECT_PROBE
  const prevPhase = process.env.AIOS_PHASE_INJECT
  const prevRemind = process.env.AIOS_REMINDER_PROBE
  const SID = 'selftest-v51j165'
  rmSync(V, { recursive: true, force: true })
  mkdirSync(V, { recursive: true })
  process.env.AIOS_STATE_DIR = V
  delete process.env.AIOS_PHASE_INJECT // 打开**阶段**接线（主套件默认 off · 照 P67；首拍接线另由常量门控）
  process.env.AIOS_INJECT_PROBE = V + '/inject_probe.json'
  writeFileSync(process.env.AIOS_INJECT_PROBE, JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }))
  process.env.AIOS_REMINDER_PROBE = V + '/no_reminder.json'
  const AG = agent(SID, { delegationDepth: 0 })
  const mine = () => records().filter(r => r.ev === 'phase-inject' && r.session === SID)
  try {
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    const call = async (cid) => {
      const p = { callId: cid, name: 'pwsh', arguments: { command: 'git status' }, agent: AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('帮我把 runtime 的注入时机前移到首拍')] })
    // ① 第一拍（第一个工具调用收尾 · 此前零工具调用 · 还没占卡）⇒ 开关关：**不注入、不落任何探针**
    const out1 = await call('v51j-first')
    assert.ok(out1, '必须返回 downstream（⛔ 不得因首拍通道改变工具结果）')
    const rec1 = mine()
    assert.equal(rec1.length, 0, '🔴 开关关 ⇒ 首拍**零探针**（0 条 = 没调用；⛔ 也不许落 skipped 占位）')
    assert.ok(!JSON.stringify(out1).includes('能力候选'), '开关关 ⇒ 不得注入任何候选块')
    const slot = FC.PHASE_INJECT.get(SID)
    assert.ok(slot, '会话槽必须已建（阶段通道照旧工作）')
    assert.equal(slot.firstStepDone, false, '🔴 开关关 ⇒ 首拍锁存不得被触碰（零副作用）')
    // ② 同会话第二/三拍 ⇒ 仍然零条（既无 dup、也无 skipped 噪音）
    await call('v51j-second')
    await call('v51j-third')
    assert.equal(mine().length, 0, '🔴 整会话首拍通道零探针（关闭态完全静默）')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevInject === undefined) delete process.env.AIOS_INJECT_PROBE; else process.env.AIOS_INJECT_PROBE = prevInject
    if (prevPhase === undefined) delete process.env.AIOS_PHASE_INJECT; else process.env.AIOS_PHASE_INJECT = prevPhase
    if (prevRemind === undefined) delete process.env.AIOS_REMINDER_PROBE; else process.env.AIOS_REMINDER_PROBE = prevRemind
    try { rmSync(V, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

checkAsync('S166 开关关 ⇒ 首拍无卡也不注（ 例外不生效）· 无卡第 2 拍仍走 静默', async () => {
  const V = SCRATCH + '/_selftest_v51j_166'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevInject = process.env.AIOS_INJECT_PROBE
  const prevPhase = process.env.AIOS_PHASE_INJECT
  const prevRemind = process.env.AIOS_REMINDER_PROBE
  const SID = 'selftest-v51j166'
  rmSync(V, { recursive: true, force: true })
  mkdirSync(V, { recursive: true })
  process.env.AIOS_STATE_DIR = V
  delete process.env.AIOS_PHASE_INJECT
  process.env.AIOS_INJECT_PROBE = V + '/inject_probe.json'
  writeFileSync(process.env.AIOS_INJECT_PROBE, JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }))
  process.env.AIOS_REMINDER_PROBE = V + '/no_reminder.json'
  const AG = agent(SID, { delegationDepth: 0 })
  const mine = () => records().filter(r => r.ev === 'phase-inject' && r.session === SID)
  try {
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    const call = async (cid, name, args) => {
      const p = { callId: cid, name, arguments: args, agent: AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('先直接看代码，还没建卡')] })
    // ① 首拍：**没有任何卡** ⇒ v51j 的"无卡也注"例外**不生效**（开关关 ⇒ 零注入零探针）
    await call('v51j166-first', 'pwsh', { command: 'git status' })
    assert.equal(mine().filter(r => r.basis === 'first-step').length, 0,
      '🔴 开关关 ⇒ 不得出现 `basis:"first-step"`（任何 state 都不许）')
    assert.equal(mine().length, 0, '首拍零探针（零注入 · ⛔ 不落 skipped 噪音）')
    // ② 第 2 拍：首次实质改动但仍无卡 ⇒ 阶段 S2，走 v51a **静默**（⛔ 不放宽）
    const out2 = await call('v51j166-edit', 'edit', { file_path: ROOT + '/scratch/_v51j166_edit_probe.md' })
    assert.ok(out2, '必须返回 downstream')
    const phase = mine().filter(r => r.basis !== 'first-step')
    assert.equal(phase.length, 1, '第 2 拍必须走阶段通道（S2）')
    assert.equal(phase[0].phase, 'S2', '有实质改动 + 无卡 ⇒ S2')
    assert.equal(phase[0].state, 'no-anchor', '🔴 v51a 语义原样：无卡仍静默（v51j 例外已随开关关闭）')
    assert.equal(phase[0].n, 0)
    assert.ok(!JSON.stringify(out2).includes('实现阶段 · 能力候选'), '无卡的第 2 拍不得注入阶段候选块')
    // ③ 第三拍（仍无卡）⇒ 也不注（no-anchor 每阶段只报一条，不刷屏）
    await call('v51j166-third', 'pwsh', { command: 'git status' })
    assert.equal(mine().filter(r => r.state === 'injected').length, 0,
      '整会话零注入（v51a 语义原样 · 首拍例外已关）')
    assert.equal(mine().filter(r => r.basis === 'first-step').length, 0, '整会话无首拍读数')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevInject === undefined) delete process.env.AIOS_INJECT_PROBE; else process.env.AIOS_INJECT_PROBE = prevInject
    if (prevPhase === undefined) delete process.env.AIOS_PHASE_INJECT; else process.env.AIOS_PHASE_INJECT = prevPhase
    if (prevRemind === undefined) delete process.env.AIOS_REMINDER_PROBE; else process.env.AIOS_REMINDER_PROBE = prevRemind
    try { rmSync(V, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

checkAsync('S167 开关关 ⇒ 首拍零注入零锁存 · claim 后常规 S1 行为逐字不变（仍注一次）', async () => {
  const V = SCRATCH + '/_selftest_v51j_167'
  const prevStateDir = process.env.AIOS_STATE_DIR
  const prevInject = process.env.AIOS_INJECT_PROBE
  const prevPhase = process.env.AIOS_PHASE_INJECT
  const prevRemind = process.env.AIOS_REMINDER_PROBE
  const SID = 'selftest-v51j167'
  const CARD = 'TASK-20261101-167'
  rmSync(V, { recursive: true, force: true })
  mkdirSync(V, { recursive: true })
  process.env.AIOS_STATE_DIR = V
  delete process.env.AIOS_PHASE_INJECT
  process.env.AIOS_INJECT_PROBE = V + '/inject_probe.json'
  writeFileSync(process.env.AIOS_INJECT_PROBE, JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }))
  process.env.AIOS_REMINDER_PROBE = V + '/no_reminder.json'
  const AG = agent(SID, { delegationDepth: 0 })
  const mine = () => records().filter(r => r.ev === 'phase-inject' && r.session === SID)
  rmSync(CARDS + '/' + CARD + '.md', { force: true })
  rmSync(CARDS + '/' + CARD + '.log', { force: true })
  try {
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    const call = async (cid, args) => {
      const p = { callId: cid, name: 'pwsh', arguments: args || { command: 'git status' }, agent: AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('先看看现状，然后再建卡')] })
    // ① 首拍（无卡）⇒ 开关关：首拍通道零读数、零锁存
    await call('v51j167-first')
    assert.equal(mine().filter(r => r.basis === 'first-step').length, 0, '🔴 开关关 ⇒ 首拍通道完全不出现')
    assert.equal(mine().length, 0, '首拍零探针')
    const slot = FC.PHASE_INJECT.get(SID)
    assert.equal(slot.firstStepDone, false, '🔴 开关关 ⇒ 首拍锁存不得被触碰（零副作用）')
    assert.ok(!slot.sent.has('S1'), '首拍不记账（S1 留给 claim 后）')
    // ② 占卡（卡上留痕 = 本会话 claim）⇒ 新回合下一拍，常规 S1 必须仍能注入一次
    writeFileSync(CARDS + '/' + CARD + '.md', cardFull(CARD, 'Executing', 0, '首拍与常规 S1 互不污染', '跑一次工具验证 S1'))
    writeFileSync(CARDS + '/' + CARD + '.log', '| 01:00 | Executing | claim 占用（session: ' + SID + '） | Worker |\n')
    wf('agent/pre-step', { agent: AG, turn: 2, step: 1, messages: [userMsg('占卡后继续')] })
    await call('v51j167-s1')
    const s1 = mine().filter(r => r.phase === 'S1')
    assert.equal(s1.length, 1, '🔴 claim 后常规 S1 仍必须注入一次（与 v51j 之前逐字一致）')
    assert.notEqual(s1[0].state, 'dup', '🔴 常规 S1 不得变 dup（开关关 ⇒ 首拍不记账、不干扰）')
    assert.ok(['injected', 'spawn-failed', 'no-candidate'].includes(s1[0].state), 'S1 state: ' + s1[0].state)
    if (s1[0].state === 'injected') assert.equal(s1[0].n, 1, 'S1 仍只注 1 条')
    assert.equal(slot.sent.has('S1'), true, '常规 S1 用自己的 `sent` 记账（与首拍标记是两套）')
    // ③ S1 不再重复；首拍通道整会话零条
    await call('v51j167-after')
    assert.equal(mine().filter(r => r.basis === 'first-step').length, 0, '首拍通道整会话零条')
    assert.equal(mine().filter(r => r.state !== 'dup').length, 1, 'S1 只注一次（与 v51j 之前逐字一致）')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    if (prevInject === undefined) delete process.env.AIOS_INJECT_PROBE; else process.env.AIOS_INJECT_PROBE = prevInject
    if (prevPhase === undefined) delete process.env.AIOS_PHASE_INJECT; else process.env.AIOS_PHASE_INJECT = prevPhase
    if (prevRemind === undefined) delete process.env.AIOS_REMINDER_PROBE; else process.env.AIOS_REMINDER_PROBE = prevRemind
    try { rmSync(V, { recursive: true, force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + CARD + '.log', { force: true }) } catch { /* 静默 */ }
  }
})


// **格能力用例已删除** ────────────────────────────────────
//   删了：S168 / S169 / S171 / S173 / S175 / S176 / S177 + `CELL_SKIP_NAMES` / `CELL_FEATURE_SKIPPED`
//     （原先是"显式 SKIP —— 代码保留但不再维护"）。
//   为什么现在删：格能力注入依赖的 `capabilities/CELLS.md` 已归档 ⇒ 路径**永远不命中**；
//     运行时实现已于 v51t 删除（`capCellsEnabled()` / `parseCellsTable()` / `cellInjectOf()` …）
//     ⇒ 函数已不存在，留 SKIP 只会让"已删除"看起来像"未执行"（⛔ 不留假绿、⛔ 不留悬空引用）。
//   保留并**改写**（它们盯的 `max` 仍活）：S170（无配置缺省 max=1）· S172（配置写坏回落）·
//     S174（检索路径快照逐字不变）。

// 条数上限改为**文件配置** `.aios/cap-cells.json` ──────────────
//   格能力（阶段 × 领域）代码已删除 ⇒ 本文件**只剩 `max`** 仍是活配置
//     （检索路径 `phaseMaxCandidates()` 的候选条数上限）；`enabled` / `form` 字段保留形状，但不再有
//     格路径消费它们。`AIOS_CAP_CELLS` 环境变量随 `capCellsEnabled()` 一起删除 ⇒ ⛔ 不再有逃生口。
//   缺省（文件不存在 / 解析失败 / enabled·max 字段缺失或类型错）⇒ `{enabled:false, max:1, form:"intro"}`
//   ⇒ 检索路径行为**逐字一致**（S170 盯住缺省、S172 盯住写坏回落）。
const CAPCELLS_DIR = SCRATCH + '/_selftest_v51m'
const CAPCELLS_FILE = CAPCELLS_DIR + '/cap-cells.json'
/** 隔离状态目录跑一段断言（`AIOS_STATE_DIR` 现取 ⇒ 进程内切换即可生效，正好验证"改即生效"）。 */
const withCapCells = (dir, fn) => {
  const prevDir = process.env.AIOS_STATE_DIR
  try {
    if (dir === null) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = dir
    return fn()
  } finally {
    if (prevDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevDir
  }
}
const capCand = (n, chans = ['axis', 'topic']) => ({
  id: 'aios.capabilities:m' + n, name: 'm' + n, kind: 'capability',
  local_path: 'capabilities/m' + n + '.md', intro: '候选 ' + n,
  source: { id: 'aios.capabilities' }, hit_channels: chans,
  evidence: chans.map(ch => ({ field: 'axes.help', channel: ch, basis: 'axis-label-match', matched: ['x'], strength: 'strong' })),
})
const resetCapCells = () => { rmSync(CAPCELLS_DIR, { recursive: true, force: true }); mkdirSync(CAPCELLS_DIR, { recursive: true }) }

check('S170 无配置文件 ⇒ 缺省逐字一致：max=1 · enabled=false（检索路径不受影响）', () => {
  resetCapCells()
  withCapCells(CAPCELLS_DIR, () => {
    assert.deepEqual(FC.capCellsConfig(), { enabled: false, max: 1, form: 'intro' }, '无文件 ⇒ {enabled:false, max:1, form:"intro"}')
    assert.equal(FC.phaseMaxCandidates(), 1, '生效上限 = PHASE_MAX_CANDIDATES = 1')
    assert.equal(FC.PHASE_MAX_CANDIDATES, 1, '缺省常量仍是 1（⛔ 不改既有常量语义）')
    // 检索路径：缺省仍只注 1 条（与改前逐字一致）
    const set = { candidates: [capCand(1), capCand(2), capCand(3)] }
    const r = FC.renderPhaseCandidates(set, 'S1', new Set())
    assert.equal(r.ids.length, 1, '缺省 ⇒ 检索路径仍 top1')
  })
})


check('S172 文件写坏（非法 JSON / 结构不对 / 字段类型错）⇒ 回落缺省，不抛错', () => {
  const assertFallback = (raw, why) => {
    resetCapCells()
    writeFileSync(CAPCELLS_FILE, raw, 'utf8')
    withCapCells(CAPCELLS_DIR, () => {
      let cfg = null
      assert.doesNotThrow(() => { cfg = FC.capCellsConfig() }, why + '：⛔ 不得抛错')
      assert.deepEqual(cfg, { enabled: false, max: 1, form: 'intro' }, why + ' ⇒ 回落缺省')
      assert.equal(FC.phaseMaxCandidates(), 1, why + ' ⇒ 生效上限 1')
      const r = FC.renderPhaseCandidates({ candidates: [capCand(1), capCand(2)] }, 'S1', new Set())
      assert.equal(r.ids.length, 1, why + ' ⇒ 检索渲染仍按缺省 1 条（不抛错）')
    })
  }
  // ① 非法 JSON（截断）
  assertFallback('{"enabled": true, "max": ', '非法 JSON')
  // ② 合法 JSON 但结构不对：数组 / null / 标量
  assertFallback('[1,2,3]', '顶层数组')
  assertFallback('null', '顶层 null')
  assertFallback('"on"', '顶层字符串')
  // ③ 字段类型错 / 越界：enabled 非严格 true ⇒ 关；max 非正整数 ⇒ 回缺省 1
  assertFallback('{"enabled":"yes","max":3}', 'enabled 非布尔 true')
  assertFallback('{"enabled":true,"max":"3"}', 'max 是字符串')
  assertFallback('{"enabled":true,"max":0}', 'max=0（非法上限）')
  assertFallback('{"enabled":true,"max":-1}', 'max 负数')
  assertFallback('{"enabled":true,"max":1.5}', 'max 非整数')
  assertFallback('{"max":3}', '缺 enabled 字段 ⇒ 关（缺省逐字一致）')
  // ④ 中文 Windows 手写 JSON 常带 UTF-8 BOM（r3-wake 同一坑）⇒ 先剥 BOM 再解析，合法文件照常生效
  resetCapCells()
  writeFileSync(CAPCELLS_FILE, '\uFEFF' + JSON.stringify({ enabled: true, max: 2, form: 'action' }), 'utf8')
  withCapCells(CAPCELLS_DIR, () => {
    assert.deepEqual(FC.capCellsConfig(), { enabled: true, max: 2, form: 'action' }, 'BOM 不得让合法配置变成"看起来开了实际是关"')
    assert.equal(FC.phaseMaxCandidates(), 2, 'BOM 文件照常生效（max 读得出 2 ⇒ 检索路径条数上限）')
  })
  rmSync(CAPCELLS_DIR, { recursive: true, force: true })
})


// ── 🔴 v51n 的 **A 组对照**：`enabled:false` ⇒ 输出与改前**逐字一致**（快照式断言）────────────
//   为什么用快照：对照组任何一字漂移都算被污染（⛔ 静默污染）。
//   期望值来源：**改前**真实渲染出的字符串，逐字抄进本用例 —— ⛔ 不来自被测代码的中间结果。
//   格能力代码已删除（`cellInjectOf()` 等不存在）⇒ 本用例**只剩检索路径快照**这一半；
//     它仍是有效回归：`enabled:false` + `max` 无关改动 ⛔ 不得影响检索渲染文本。
const V51N_SNAPSHOT_S1 = '【AI-OS · 决策阶段 · 能力候选】\n  · m1 — 候选 1\n    → capabilities/m1.md'
const V51N_SNAPSHOT_S2 = '【AI-OS · 实现阶段 · 能力候选】\n  · m1 — 候选 1\n    → capabilities/m1.md'

check('S174 enabled:false ⇒ 输出与改前逐字一致（快照 · 仅检索路径）', () => {
  resetCapCells()
  writeFileSync(CAPCELLS_FILE, JSON.stringify({ enabled: false, max: 3 }), 'utf8')
  try {
    withCapCells(CAPCELLS_DIR, () => {
      assert.equal(FC.capCellsConfig().enabled, false, '文件明写 enabled:false')
      // ① 检索路径：文本**逐字**等于改前快照（快照 = 改前实测，⛔ 不是本次实现的产物）
      const set = { candidates: [capCand(1)] }
      assert.equal(FC.renderPhaseCandidates(set, 'S1', new Set()).text, V51N_SNAPSHOT_S1, '② S1 逐字一致')
      assert.equal(FC.renderPhaseCandidates(set, 'S2', new Set()).text, V51N_SNAPSHOT_S2, '② S2 逐字一致')
      // ② 对照组文本里 ⛔ 不得漏进 v51n 的新形态字样（漏进去就是"对照组被改了"）
      const txt = FC.renderPhaseCandidates(set, 'S1', new Set()).text
      assert.equal(txt.includes('你现在要做的'), false, '② 对照组无块标题')
      assert.equal(txt.includes('完成判据：'), false, '② 对照组无判据行')
      assert.equal(txt.includes('你刚在做的'), false, '② 对照组无用途句')
      // ③ max 改动同样不影响对照组文本（关着的路径不该被 max 顺手改动）
      writeFileSync(CAPCELLS_FILE, JSON.stringify({ enabled: false, max: 1 }), 'utf8')
      assert.equal(FC.renderPhaseCandidates(set, 'S1', new Set()).text, V51N_SNAPSHOT_S1, '④ max 改动不影响对照组')
    })
  } finally {
    rmSync(CAPCELLS_DIR, { recursive: true, force: true })
  }
})
// **能力合规提醒（nudge）** ────────────────────────────────
//   前提（实测，⛔ 不改）：能力**注入** 4 轮 15 次 0 次进入决策；「必须填」的三点账本 24+ 卡全 PASS
//   ⇒ runtime 改「合规提醒」：只提醒"还缺记录"，⛔ 不点名任何能力。
//   开关 `.aios/cap-cells.json` 的 `nudge`：`"off"`（缺省）/ `"on"`；`off` ⇒ 一行都不执行、零探针。
const NUDGE_DIR = SCRATCH + '/_selftest_v51p'
const NUDGE_FILE = NUDGE_DIR + '/cap-cells.json'
/** 运行时层用例的公共准备：隔离状态目录 + 打开注入门（阶段判定所在块 + 探针）· 清理由调用方 finally 做。 */
const nudgePrepare = (nudge) => {
  rmSync(NUDGE_DIR, { recursive: true, force: true })
  mkdirSync(NUDGE_DIR, { recursive: true })
  writeFileSync(NUDGE_FILE,
    JSON.stringify({ enabled: false, max: 1, form: 'intro', nudge }), 'utf8')
  process.env.AIOS_STATE_DIR = NUDGE_DIR
  delete process.env.AIOS_PHASE_INJECT // 打开阶段接线（主套件默认 off · 照 P67）
  process.env.AIOS_INJECT_PROBE = NUDGE_DIR + '/inject_probe.json'
  writeFileSync(process.env.AIOS_INJECT_PROBE,
    JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }), 'utf8')
  process.env.AIOS_REMINDER_PROBE = NUDGE_DIR + '/no_reminder.json'
}
const nudgeRestore = (prev) => {
  for (const k of ['AIOS_STATE_DIR', 'AIOS_INJECT_PROBE', 'AIOS_PHASE_INJECT', 'AIOS_REMINDER_PROBE']) {
    if (prev[k] === undefined) delete process.env[k]; else process.env[k] = prev[k]
  }
}
const nudgeLog = (sid, extra = []) => [
  '| 01:00 | Executing | claim 占用（session: ' + sid + '） | Worker |',
  ...extra,
].join('\n') + '\n'
const CAP_ROW = (stage, name = 'none', why = '本轮没有需要的能力就用 none') =>
  '| 01:01 | ' + stage + ' | ' + name + ' ｜ 理由：' + why + ' | Worker |'
const nudgeRecs = (sid) => records().filter(r => r.ev === 'capability-nudge' && r.session === sid)

checkAsync('S178 nudge:"off"（含缺省无字段）⇒ 零探针、零注入（A 组逐字不变）', async () => {
  const prev = {
    AIOS_STATE_DIR: process.env.AIOS_STATE_DIR, AIOS_INJECT_PROBE: process.env.AIOS_INJECT_PROBE,
    AIOS_PHASE_INJECT: process.env.AIOS_PHASE_INJECT, AIOS_REMINDER_PROBE: process.env.AIOS_REMINDER_PROBE,
  }
  const ID = 'TASK-20261101-231'
  const SID = 'selftest-v51p-off'
  try {
    nudgePrepare('off')
    assert.equal(FC.capNudgeEnabled(), false, '文件 nudge:"off" ⇒ 关')
    // 缺省：字段根本不存在 ⇒ 关（`.aios/cap-cells.json` 现状就是这种形态）
    writeFileSync(NUDGE_FILE, JSON.stringify({ enabled: false, max: 1, form: 'intro' }), 'utf8')
    assert.equal(FC.capNudgeEnabled(), false, '缺 nudge 字段 ⇒ 缺省 off')
    // 场景本身**满足提醒条件**（缺开工）—— 用来证明"没提醒"只因为开关 off
    const raw = nudgeLog(SID)
    assert.deepEqual(FC.missingCapRecordsOf(raw), ['start', 'impl', 'close'], '场景缺三处（缺开工）')
    nudgePrepare('off')
    const AG = agent(SID, { delegationDepth: 0 })
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    writeFileSync(CARDS + '/' + ID + '.md', cardFull(ID, 'Executing', 0, 'v51p off 对照', '改文件'))
    writeFileSync(CARDS + '/' + ID + '.log', raw)
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('占卡后开工')] })
    const p = { callId: SID + '-edit', name: 'edit', arguments: { file_path: ROOT + '/scratch/_v51p_edit_probe.md' }, agent: AG }
    wf('tools/pre-execute', p)
    const out = await h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    assert.ok(out, '必须返回 downstream')
    // ① 零探针（off ⇒ 一行都不执行）
    assert.equal(nudgeRecs(SID).length, 0, '🔴 off ⇒ capability-nudge 零探针（不是 dup/no-anchor 占位）')
    // ② 零注入（提醒正文一个字都没进上下文）
    assert.equal(JSON.stringify(out).includes('缺失记录'), false, '🔴 off ⇒ 提醒正文不得出现')
    // ③ 关掉提醒不影响阶段注入本身（该跑还跑 —— 只是没有 nudge）
    const ph = records().filter(r => r.ev === 'phase-inject' && r.session === SID)
    assert.ok(ph.length >= 1, '阶段接线照旧（off 只关 nudge，⛔ 不碰既有注入）')
  } finally {
    nudgeRestore(prev)
    try { rmSync(CARDS + '/' + ID + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + ID + '.log', { force: true }) } catch { /* 静默 */ }
    try { rmSync(NUDGE_DIR, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

checkAsync('S179 nudge:"on" + 缺开工 ⇒ S2 提醒**恰 1 次**；再拍 dup（独立 Set · 不复用 sent）', async () => {
  const prev = {
    AIOS_STATE_DIR: process.env.AIOS_STATE_DIR, AIOS_INJECT_PROBE: process.env.AIOS_INJECT_PROBE,
    AIOS_PHASE_INJECT: process.env.AIOS_PHASE_INJECT, AIOS_REMINDER_PROBE: process.env.AIOS_REMINDER_PROBE,
  }
  const ID = 'TASK-20261101-232'
  const SID = 'selftest-v51p-on'
  try {
    nudgePrepare('on')
    assert.equal(FC.capNudgeEnabled(), true, '文件 nudge:"on" ⇒ 开')
    const AG = agent(SID, { delegationDepth: 0 })
    const h = handlers.get('tools/post-execute')[0]
    assert.ok(h, 'tools/post-execute handler 存在')
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    writeFileSync(CARDS + '/' + ID + '.md', cardFull(ID, 'Executing', 0, 'v51p on', '改文件'))
    writeFileSync(CARDS + '/' + ID + '.log', nudgeLog(SID)) // 只有 claim ⇒ 缺开工
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('占卡后开工')] })
    const call = async (cid, name, args) => {
      const p = { callId: cid, name, arguments: args, agent: AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    const out1 = await call(SID + '-edit', 'edit', { file_path: ROOT + '/scratch/_v51p_edit_probe.md' })
    const rec1 = nudgeRecs(SID)
    assert.equal(rec1.length, 1, '🔴 S2 缺开工 ⇒ 恰好 1 条 capability-nudge 探针')
    assert.equal(rec1[0].stage, 'S2', 'stage = S2')
    assert.equal(rec1[0].missing, 'start', 'missing = start（⛔ 不点名能力）')
    assert.equal(rec1[0].state, 'injected', 'state = injected')
    assert.equal(rec1[0].session, SID, '🔴 探针必带 session（P83）')
    assert.equal(rec1[0].chars, FC.CAP_NUDGE_TEXT.length, 'chars = 提醒正文长度')
    assert.ok(JSON.stringify(out1).includes('缺失记录'), '提醒正文必须真的进上下文')
    // 独立 Set：提醒**不写**阶段注入的 `sent`（提醒 ≠ 能力注入；本拍让位，下拍阶段注入照跑）
    const slot = FC.PHASE_INJECT.get(SID)
    assert.ok(slot, '会话槽必须已建')
    assert.ok(slot.nudgeSent.has('S2'), 'nudgeSent 记 S2（独立 Set）')
    assert.equal(slot.sent.has('S2'), false, '🔴 提醒 ⛔ 不代写 `sent`（否则能力注入被静默吞掉）')
    // 再拍：同阶段已提醒 ⇒ 只落一条 dup，不重复注入
    const out2 = await call(SID + '-again', 'pwsh', { command: 'git status' })
    const rec2 = nudgeRecs(SID)
    const dups = rec2.filter(r => r.state === 'dup')
    assert.equal(dups.length, 1, '再拍 ⇒ 恰好 1 条 dup 探针（⛔ 每拍一条刷屏）')
    assert.equal(dups[0].stage, 'S2', 'dup stage = S2')
    assert.equal(dups[0].missing, 'start', 'dup missing = start')
    assert.equal(rec2.filter(r => r.state === 'injected').length, 1, '每阶段提醒**恰 1 次**')
    assert.equal(JSON.stringify(out2).includes('缺失记录'), false, 'dup 拍不得再注入提醒正文')
    assert.ok(slot.sent.has('S2'), '让位一拍后，既有阶段注入照常记账（⛔ 提醒没有吞掉它）')
  } finally {
    nudgeRestore(prev)
    try { rmSync(CARDS + '/' + ID + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + ID + '.log', { force: true }) } catch { /* 静默 */ }
    try { rmSync(NUDGE_DIR, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

checkAsync('S180 nudge:"on" + 三处齐全 ⇒ S2/S4 都不提醒（判据 = State 列三行）', async () => {
  const prev = {
    AIOS_STATE_DIR: process.env.AIOS_STATE_DIR, AIOS_INJECT_PROBE: process.env.AIOS_INJECT_PROBE,
    AIOS_PHASE_INJECT: process.env.AIOS_PHASE_INJECT, AIOS_REMINDER_PROBE: process.env.AIOS_REMINDER_PROBE,
  }
  const ID = 'TASK-20261101-233'
  const SID = 'selftest-v51p-full'
  try {
    nudgePrepare('on')
    const raw = nudgeLog(SID, [
      CAP_ROW('能力-开工', 'test-driven-development'),
      CAP_ROW('能力-实现', 'test-driven-development'),
      CAP_ROW('能力-收尾', 'test-driven-development'),
    ])
    assert.deepEqual(FC.missingCapRecordsOf(raw), [], '三处齐全 ⇒ 无缺失')
    const AG = agent(SID, { delegationDepth: 0 })
    const h = handlers.get('tools/post-execute')[0]
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    writeFileSync(CARDS + '/' + ID + '.md', cardFull(ID, 'Executing', 0, 'v51p 齐全', '改文件后收口'))
    writeFileSync(CARDS + '/' + ID + '.log', raw)
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('开工')] })
    const call = async (cid, name, args) => {
      const p = { callId: cid, name, arguments: args, agent: AG }
      wf('tools/pre-execute', p)
      return h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    }
    const outS2 = await call(SID + '-edit', 'edit', { file_path: ROOT + '/scratch/_v51p_edit_probe.md' })
    assert.equal(JSON.stringify(outS2).includes('缺失记录'), false, 'S2 三处齐全 ⇒ 不提醒')
    // S4：release 当拍（卡快照仍留旧卡 ⇒ 可读 `.log`；收尾已记录 ⇒ 不提醒）
    const outS4 = await call(SID + '-release', 'pwsh',
      { command: 'python tools/task_card.py release ' + ID + ' --state=Parked' })
    assert.equal(JSON.stringify(outS4).includes('缺失记录'), false, 'S4 收尾已记录 ⇒ 不提醒')
    assert.equal(nudgeRecs(SID).length, 0, '🔴 三处齐全 ⇒ capability-nudge 零探针（不是 dup 占位）')
  } finally {
    nudgeRestore(prev)
    try { rmSync(CARDS + '/' + ID + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + ID + '.log', { force: true }) } catch { /* 静默 */ }
    try { rmSync(NUDGE_DIR, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

checkAsync('S181 nudge:"on" + 缺收尾 ⇒ S4 提醒 1 次（开工/实现已记录也不算齐）', async () => {
  const prev = {
    AIOS_STATE_DIR: process.env.AIOS_STATE_DIR, AIOS_INJECT_PROBE: process.env.AIOS_INJECT_PROBE,
    AIOS_PHASE_INJECT: process.env.AIOS_PHASE_INJECT, AIOS_REMINDER_PROBE: process.env.AIOS_REMINDER_PROBE,
  }
  const ID = 'TASK-20261101-234'
  const SID = 'selftest-v51p-s4'
  try {
    nudgePrepare('on')
    const raw = nudgeLog(SID, [CAP_ROW('能力-开工'), CAP_ROW('能力-实现')])
    assert.deepEqual(FC.missingCapRecordsOf(raw), ['close'], '缺的只有收尾')
    const AG = agent(SID, { delegationDepth: 0 })
    const h = handlers.get('tools/post-execute')[0]
    emit1('agent/session-start', { agent: AG, source: 'startup' })
    writeFileSync(CARDS + '/' + ID + '.md', cardFull(ID, 'Executing', 0, 'v51p 缺收尾', '收口'))
    writeFileSync(CARDS + '/' + ID + '.log', raw)
    wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('开工')] })
    const p = { callId: SID + '-release', name: 'pwsh',
      arguments: { command: 'python tools/task_card.py release ' + ID + ' --state=Parked' }, agent: AG }
    wf('tools/pre-execute', p)
    const out = await h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
    const rec = nudgeRecs(SID)
    assert.equal(rec.length, 1, '🔴 S4 缺收尾 ⇒ 恰好 1 条 capability-nudge')
    assert.equal(rec[0].stage, 'S4', 'stage = S4（收口）')
    assert.equal(rec[0].missing, 'close', 'missing = close')
    assert.equal(rec[0].state, 'injected', 'state = injected')
    assert.ok(JSON.stringify(out).includes('缺失记录'), 'S4 提醒必须真的进上下文')
  } finally {
    nudgeRestore(prev)
    try { rmSync(CARDS + '/' + ID + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + ID + '.log', { force: true }) } catch { /* 静默 */ }
    try { rmSync(NUDGE_DIR, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

check('S182 提醒文本**不含任何** 8 个域能力名（能力名列表断言 · 正文逐字固定）', () => {
  // 来源：`capabilities/INDEX.md` 的 8 个域能力。
  const CAP_NAMES = [
    'domain-aios-itself', 'domain-backend', 'domain-data', 'domain-docs',
    'domain-frontend', 'domain-job-search', 'domain-ops', 'domain-product',
  ]
  assert.equal(CAP_NAMES.length, 8, '能力名列表必须与 capabilities/INDEX.md 的域能力数一致')
  for (const n of CAP_NAMES) {
    assert.equal(FC.CAP_NUDGE_TEXT.includes(n), false, '🔴 提醒文本 ⛔ 不得点名能力：' + n)
  }
  // 正文逐字固定（⛔ 不点名能力 / ⛔ 不带候选·建议·打分；占位符 `<能力名|none>` 不是能力名）
  const EXPECT = '【AI-OS · 缺失记录】本阶段还没有记录「用了哪个能力」。\n'
    + '  → 看一眼 capabilities/INDEX.md，然后用一条命令记录（收口前必须补）：\n'
    + '    python tools/task_card.py capability <TASK-ID> --stage <start|impl|close> --name <能力名|none> --why "<一句>"'
  assert.equal(FC.CAP_NUDGE_TEXT, EXPECT, '提醒正文必须逐字固定（改一个字 = 改实验变量）')
  assert.equal(FC.CAP_NUDGE_TEXT.includes('能力候选'), false, '⛔ 不是能力推荐')
  // 检测只认 **State 列**：理由里提到「能力-开工」不算已记录
  const reasonOnly = '| 01:00 | Executing | 理由里提到 能力-开工 也不算 | Worker |\n'
  assert.ok(FC.missingCapRecordsOf(reasonOnly).includes('start'), '⛔ 不在 Reason 列里匹配')
  // 空 / 读不到 ⇒ 三处全缺
  assert.deepEqual(FC.missingCapRecordsOf(''), ['start', 'impl', 'close'])
  // 表头字面量与 `tools/task_card.py: CAPABILITY_STAGES` 同源
  assert.deepEqual(FC.CAP_RECORD_MARKS, { start: '能力-开工', impl: '能力-实现', close: '能力-收尾' })
})

// **域能力注入**（替代检索打分的阶段注入）────────
//   前提（已定的结构，⛔ 不改）：能力库已域合并 —— `capabilities/domain-*.md` 8 个，一域一文件、
//   片不含 class（`CELLS.md` 已归档）⇒ **判域即选文件**：不检索、不打分、无候选、无条数。
//   开关 `.aios/cap-cells.json` 的 `domainInject`：`"on"` / 缺省 `"off"`；off ⇒ 一行都不执行、零探针。
//   接线位置：**首拍通道之后**、检索回退之前；
//     判不出域 / 域文件缺失 ⇒ 回退旧检索路径。
const DOM_DIR = SCRATCH + '/_selftest_v51q'
const DOM_FILE = DOM_DIR + '/cap-cells.json'
/** 运行时层用例的公共准备（照 `nudgePrepare`）：隔离状态目录 + 打开注入门 + 打开阶段接线。 */
const domPrepare = (domainInject, extra = {}) => {
  rmSync(DOM_DIR, { recursive: true, force: true })
  mkdirSync(DOM_DIR, { recursive: true })
  writeFileSync(DOM_FILE,
    JSON.stringify(Object.assign({ enabled: false, max: 1, form: 'intro', domainInject }, extra)), 'utf8')
  process.env.AIOS_STATE_DIR = DOM_DIR
  delete process.env.AIOS_PHASE_INJECT // 打开阶段接线（主套件默认 off · 照 P67）
  process.env.AIOS_INJECT_PROBE = DOM_DIR + '/inject_probe.json'
  writeFileSync(process.env.AIOS_INJECT_PROBE,
    JSON.stringify({ enabled: true, session: '*', per: 'turn', maxPerSession: 20 }), 'utf8')
  process.env.AIOS_REMINDER_PROBE = DOM_DIR + '/no_reminder.json'
}
const DOM_ENV_KEYS = ['AIOS_STATE_DIR', 'AIOS_INJECT_PROBE', 'AIOS_PHASE_INJECT', 'AIOS_REMINDER_PROBE', 'AIOS_ROOT']
const domEnvSnapshot = () => {
  const o = {}
  for (const k of DOM_ENV_KEYS) o[k] = process.env[k]
  return o
}
const domRestore = (prev) => {
  for (const k of DOM_ENV_KEYS) {
    if (prev[k] === undefined) delete process.env[k]; else process.env[k] = prev[k]
  }
}
const domRecs = (sid) => records().filter(r => r.ev === 'phase-inject' && r.session === sid)
/** `domain-docs.md` 的 `intro` **原文**（用独立正则读文件 ⇒ ⛔ 不借实现函数自证）。 */
const REAL_DOCS_INTRO = (() => {
  const text = readFileSync(ROOT + '/capabilities/domain-docs.md', 'utf8').replace(/^\uFEFF/, '')
  const fm = /^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n/.exec(text)
  assert.ok(fm, 'domain-docs.md 必须有 frontmatter')
  const m = /^intro[ \t]*:[ \t]*(.+)$/m.exec(fm[1])
  assert.ok(m, 'domain-docs.md 的 frontmatter 必须有 intro')
  return m[1].trim()
})()
/** 走**真实** `tools/post-execute` handler 跑一拍（占卡 + pre-step + pre-execute + post-execute）。
 *  `opts.cardBody` / `opts.logText` 可换卡正文与 `.log`（默认 = 无「使用的能力」节 · 只有 claim 行）。 */
const domRun = async (sid, id, goal, next, tool = ['pwsh', { command: 'git status' }], opts = {}) => {
  const AG = agent(sid, { delegationDepth: 0 })
  const h = handlers.get('tools/post-execute')[0]
  assert.ok(h, 'tools/post-execute handler 存在')
  emit1('agent/session-start', { agent: AG, source: 'startup' })
  writeFileSync(CARDS + '/' + id + '.md',
    opts.cardBody !== undefined ? opts.cardBody : cardFull(id, 'Executing', 0, goal, next))
  writeFileSync(CARDS + '/' + id + '.log',
    opts.logText !== undefined ? opts.logText
      : '| 01:00 | Executing | claim 占用（session: ' + sid + '） | Worker |\n')
  wf('agent/pre-step', { agent: AG, turn: 1, step: 1, messages: [userMsg('占卡后开工')] })
  const p = { callId: sid + '-c1', name: tool[0], arguments: tool[1], agent: AG }
  wf('tools/pre-execute', p)
  const out = await h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
  return { out, rec: domRecs(sid) }
}

// **注入跟随卡上声明的域能力**（替代机器猜域）────────────
//   方向（已定 · ⛔ 不重新论证）：机器猜域全部不可靠（topic 57% / 检索 47–59% / 路径 83%）
//   ⇒ 域由 agent 在卡上声明（`.log` 的 `能力` 行 / 卡正文「## 使用的能力」）。
//   Runtime 只**读**声明：未声明 / `none` ⇒ **零注入**（⛔ 不回退猜域）；声明变了 ⇒ 同阶段**再注入一次**。

/** v51r：带「使用的能力」声明的卡正文（与 v4 模板同形；插在 `Current Status` 之前）。 */
const cardWithCap = (id, state, step, goal, next, cap, why = 'v51r selftest') =>
  cardFull(id, state, step, goal, next).replace('## Current Status',
    '## 使用的能力（可 none）\n\n- 能力: `' + cap + '` ｜ ' + why + '\n\n---\n\n## Current Status')
/** v51r：`.log` = claim 留痕（占用真相，必须有）+ 可选的 `能力` 行（脚本写的权威声明）。 */
const logWithCap = (sid, cap, why = 'v51r selftest') =>
  '| 01:00 | Executing | claim 占用（session: ' + sid + '） | Worker |\n'
  + (cap === undefined ? '' : '| 01:01 | 能力 | ' + cap + ' ｜ 理由：' + why + ' | Worker |\n')
/** v51r：同一会话**再拍一拍**（新 turn ⇒ pre-step 重扫卡；槽位/去重状态延续 · 会话⛔ 不重启）。 */
const domNextStep = async (sid, id, opts = {}) => {
  const AG = agent(sid, { delegationDepth: 0 })
  const h = handlers.get('tools/post-execute')[0]
  assert.ok(h, 'tools/post-execute handler 存在')
  const turn = opts.turn !== undefined ? opts.turn : 2
  if (opts.cardBody !== undefined) writeFileSync(CARDS + '/' + id + '.md', opts.cardBody)
  if (opts.logText !== undefined) writeFileSync(CARDS + '/' + id + '.log', opts.logText)
  if (opts.appendLog !== undefined) appendFileSync(CARDS + '/' + id + '.log', opts.appendLog)
  wf('agent/pre-step', { agent: AG, turn, step: 1, messages: [userMsg('继续')] })
  const p = { callId: sid + '-c' + turn, name: 'pwsh', arguments: { command: 'git status' }, agent: AG }
  wf('tools/pre-execute', p)
  const out = await h(p, { isError: false, content: [{ type: 'text', text: 'ok' }] }, () => ({ kind: 'accept' }))
  return { out, rec: domRecs(sid) }
}
/** v51r：最小 `TaskCursor`（`declaredDomainCapabilityOf` 只用到 `key`）。 */
const cardCursor = (id) => ({ key: id + '.md', state: 'Executing', step: '', goal: '', next: '', occupancy: null })
const domCleanup = (ids) => {
  for (const id of ids) {
    try { rmSync(CARDS + '/' + id + '.md', { force: true }) } catch { /* 静默 */ }
    try { rmSync(CARDS + '/' + id + '.log', { force: true }) } catch { /* 静默 */ }
  }
  try { rmSync(DOM_DIR, { recursive: true, force: true }) } catch { /* 静默 */ }
}

check('S183 domainInject:"off" / 字段缺 / 非法 ⇒ 零 `basis:"domain"` 探针、零注入（快照逐字不变）', () => {
  const prevStateDir = process.env.AIOS_STATE_DIR
  // ① 开关读法：缺省 / 文件缺 / 字段缺 / 非法值 ⇒ off；只有恰好 "on" 才开（⛔ 不抛错）
  const cfgCases = [
    [JSON.stringify({ enabled: false, max: 1, form: 'intro' }), false, '字段缺'],
    [JSON.stringify({ enabled: false, max: 1, form: 'intro', domainInject: 'off' }), false, '"off"'],
    [JSON.stringify({ enabled: false, max: 1, domainInject: 'ON' }), false, '"ON"（大小写不是合法值）'],
    [JSON.stringify({ enabled: false, max: 1, domainInject: 'true' }), false, '"true"（字符串不是合法值）'],
    [JSON.stringify({ enabled: false, max: 1, domainInject: true }), false, '布尔 true（类型不对）'],
    [JSON.stringify({ enabled: false, max: 1, domainInject: 1 }), false, '数字 1（类型不对）'],
    [JSON.stringify({ enabled: false, max: 1, domainInject: 'on' }), true, '"on"'],
    // BOM：中文 Windows 手写 JSON 常带 BOM —— 剥了才读得出（⛔ 否则"看起来开了实际是关"）
    ['\uFEFF' + JSON.stringify({ enabled: false, max: 1, domainInject: 'on' }), true, '带 BOM 的 "on"'],
  ]
  try {
    for (const [raw, want, why] of cfgCases) {
      rmSync(DOM_DIR, { recursive: true, force: true })
      mkdirSync(DOM_DIR, { recursive: true })
      writeFileSync(DOM_FILE, raw, 'utf8')
      process.env.AIOS_STATE_DIR = DOM_DIR
      let got = null
      assert.doesNotThrow(() => { got = FC.domainInjectEnabled() }, why + '：⛔ 不得抛错')
      assert.equal(got, want, why + ' ⇒ 开关判定')
    }
    // ② 🔴 **整份校验**：`enabled` / `max` 不可信 ⇒ 即使写了 `domainInject:"on"` 也 off（照 capNudge 口径）
    rmSync(DOM_DIR, { recursive: true, force: true })
    mkdirSync(DOM_DIR, { recursive: true })
    writeFileSync(DOM_FILE, JSON.stringify({ max: 1, domainInject: 'on' }), 'utf8')
    assert.equal(FC.domainInjectEnabled(), false, '缺 enabled ⇒ 整份不可信 ⇒ off')
    writeFileSync(DOM_FILE, JSON.stringify({ enabled: false, max: 0, domainInject: 'on' }), 'utf8')
    assert.equal(FC.domainInjectEnabled(), false, 'max 非法 ⇒ 整份不可信 ⇒ off')
    // ③ 文件根本不存在 ⇒ off（⛔ 不抛错）
    rmSync(DOM_FILE, { force: true })
    assert.doesNotThrow(() => assert.equal(FC.domainInjectEnabled(), false), '文件缺 ⇒ off 且不抛错')
    assert.equal(FC.domainInjectOf('on'), 'on', '纯函数只认 "on"')
    assert.equal(FC.domainInjectOf('yes'), 'off', '其它任何值 ⇒ off')
    assert.equal(FC.domainInjectOf(undefined), 'off', '缺省 ⇒ off')
  } finally {
    if (prevStateDir === undefined) delete process.env.AIOS_STATE_DIR; else process.env.AIOS_STATE_DIR = prevStateDir
    try { rmSync(DOM_DIR, { recursive: true, force: true }) } catch { /* 静默 */ }
  }
})

checkAsync('S184 domainInject:"on" + 域判得出（文档）⇒ 恰 1 条 `basis:"domain"` 探针 + 注入文本含该域 intro 原文 + 指向 domain-docs.md', async () => {
  const prev = domEnvSnapshot()
  const ID = 'TASK-20261102-181'
  const SID = 'selftest-v51q-on'
  try {
    domPrepare('on')
    assert.equal(FC.domainInjectEnabled(), true, '文件 domainInject:"on" ⇒ 开')
    // 真实 handler 一拍：卡在占 + topic 含「文档」⇒ 判域「文档」⇒ domain-docs（不检索、不打分）
    const { out, rec } = await domRun(SID, ID, '把这次交付的文档写清楚', '整理文档结构并补说明书')
    // ① 探针：恰好 1 条 · basis:"domain" · domain · capability · state · chars · n:1 · 必带 session
    const dom = rec.filter(r => r.basis === 'domain')
    assert.equal(dom.length, 1, '🔴 恰好 1 条 `basis:"domain"` 探针（⛔ 不多不少）：' + JSON.stringify(rec))
    assert.equal(dom[0].state, 'injected', 'state = injected')
    assert.equal(dom[0].domain, '文档', 'domain = 判出的域')
    assert.equal(dom[0].capability, 'domain-docs', 'capability = 该域的能力文件名')
    assert.equal(dom[0].n, 1, 'n = 1（域路径恒一条，⛔ 不是候选数）')
    assert.equal(dom[0].session, SID, '🔴 探针必带 session（P83）')
    assert.equal(dom[0].phase, 'S1', 'phase = S1（占卡后、未实质改动）')
    // ② 注入文本：标题 + intro **原文** + 位置行（逐字）
    const text = '【AI-OS · 决策 · 文档能力】\n  ' + REAL_DOCS_INTRO + '\n  → capabilities/domain-docs.md'
    assert.equal(dom[0].chars, text.length, 'chars = 注入文本长度')
    const ctx = JSON.stringify(out)
    assert.ok(ctx.includes('【AI-OS · 决策 · 文档能力】'), '注入标题必须真的进上下文：' + ctx.slice(0, 300))
    assert.ok(ctx.includes(REAL_DOCS_INTRO), '🔴 注入必须含 domain-docs frontmatter 的 intro 原文（⛔ 不改写）')
    assert.ok(ctx.includes('→ capabilities/domain-docs.md'), '注入必须带域能力位置')
    // ③ 域路径命中 ⇒ 本拍不再走检索注入（既有路径让位 · 每拍最多一条注入）
    assert.equal(rec.length, 1, '🔴 本拍恰好一条 phase-inject（域注入命中 ⇒ 检索路径让位）')
  } finally {
    domRestore(prev)
    domCleanup([ID])
  }
})

checkAsync('S185 domainInject:"on" + 判不出域 ⇒ 回退既有检索路径（⛔ 不静默吞掉）', async () => {
  const prev = domEnvSnapshot()
  const ID = 'TASK-20261102-182'
  const SID = 'selftest-v51q-nodomain'
  try {
    domPrepare('on')
    // topic 里**没有任何**域词（⛔ 不用 activity 目录兜底 ⇒ 判定只看 topic）
    const topic = '继续处理手头的事 ｜ 把这件事做完'
    assert.equal(FC.inferDomainOf(topic), null, '该 topic 必须判不出域（用例前提）')
    const { out, rec } = await domRun(SID, ID, '把这件事做完', '继续处理手头的事')
    // ① 判不出域 ⇒ ⛔ 不吞注入：既有检索路径必须照常落探针（哪怕是 spawn-failed / no-candidate）
    assert.equal(rec.length, 1, '🔴 判不出域 ⇒ 既有检索路径仍落一条探针（不是零探针）')
    assert.equal(rec[0].basis, undefined, '🔴 不得落 `basis:"domain"`')
    assert.equal(rec[0].domain, undefined, '不得带 `domain` 字段')
    assert.equal(rec[0].capability, undefined, '不得带 `capability` 字段')
    assert.ok(['injected', 'spawn-failed', 'no-candidate'].includes(rec[0].state),
      '既有路径状态（injected / spawn-failed / no-candidate）：' + rec[0].state)
    // ② 上下文里没有域能力注入文本
    assert.equal(JSON.stringify(out).includes('能力】'), false, '判不出域 ⇒ 一个字的域注入都不该有')
    // ③ 回退的证据是"开关是开的、探针却不是 domain"（⛔ 不是零注入、⛔ 不是 default 关掉后什么都不做）
    assert.equal(FC.domainInjectEnabled(), true, '本用例开关确实是开的（⛔ 别把"回退"误判成"开关关"）')
    // `sent` 由**既有检索路径**先记账再 spawn（不是域路径写的）⇒ 该阶段仍照旧只注一次
    const slot = FC.PHASE_INJECT.get(SID)
    assert.ok(slot, '会话槽必须已建')
    assert.equal(slot.sent.has('S1'), true, '既有检索路径接管（先记账再 spawn ⇒ 回退真的发生了）')
  } finally {
    domRestore(prev)
    domCleanup([ID])
  }
})

checkAsync('S186 domainInject:"on" + 域判出但 domain-<x>.md 不存在（隔离根）⇒ 回退且 ⛔ 不抛错', async () => {
  const prev = domEnvSnapshot()
  const ID = 'TASK-20261102-183'
  const SID = 'selftest-v51q-nofile'
  const EMPTY_ROOT = SCRATCH + '/_selftest_v51q_root'
  try {
    domPrepare('on')
    // 隔离根：`capabilities/` 存在但**没有**任何 `domain-*.md`
    rmSync(EMPTY_ROOT, { recursive: true, force: true })
    mkdirSync(EMPTY_ROOT + '/capabilities', { recursive: true })
    process.env.AIOS_ROOT = EMPTY_ROOT
    // ① 纯函数：读不到文件 ⇒ null（⛔ 不抛错）
    assert.doesNotThrow(() => {
      assert.equal(FC.domainCapabilityOf('文档'), null, '隔离根里没有 domain-*.md ⇒ null')
      assert.equal(FC.domainIntroOf('domain-docs'), null, '隔离根里读不到 intro ⇒ null')
    }, '隔离根：⛔ 读失败不得抛错')
    // 域判定本身照旧（判定与文件存在性解耦）
    assert.equal(FC.inferDomainOf('整理文档结构并补说明书'), '文档', '域仍判得出（锅在文件缺失，不在判定）')
    // ② 真实 handler：域判得出但文件缺 ⇒ **回退**既有检索路径，且⛔ 不得落 domain-error
    const { rec } = await domRun(SID, ID, '把这次交付的文档写清楚', '整理文档结构并补说明书')
    assert.equal(rec.length, 1, '域文件缺 ⇒ 既有检索路径仍落一条探针（不是零探针）')
    assert.equal(rec[0].basis, undefined, '🔴 回退：不得落 `basis:"domain"`')
    assert.equal(rec[0].state === 'domain-error', false, '🔴 不抛错 ⇒ 不得出现 `state:"domain-error"`')
    assert.ok(['injected', 'spawn-failed', 'no-candidate'].includes(rec[0].state), '回退 state：' + rec[0].state)
  } finally {
    if (prev.AIOS_ROOT === undefined) delete process.env.AIOS_ROOT
    try { rmSync(EMPTY_ROOT, { recursive: true, force: true }) } catch { /* 静默 */ }
    domRestore(prev)
    domCleanup([ID])
  }
})

check('S187 注入文本逐字 3 行 · ⛔ 无「能力候选」/打分/`n=` 之类旧字段文案', () => {
  // 快照：标题（阶段中文取 PHASE_TITLE：S2 = 实现）+ intro 原文 + 位置行，**一个字都不多**
  const EXPECT = '【AI-OS · 实现 · 文档能力】\n'
    + '  ' + REAL_DOCS_INTRO + '\n'
    + '  → capabilities/domain-docs.md'
  const got = FC.renderDomainInjection('S2', '文档', 'domain-docs', REAL_DOCS_INTRO)
  assert.equal(got, EXPECT, '注入文本必须逐字等于 3 行形状')
  const lines = got.split('\n')
  assert.equal(lines.length, 3, '恒 3 行（标题 / intro / 位置）')
  assert.equal(lines[0], '【AI-OS · 实现 · 文档能力】', '第 1 行：阶段中文（PHASE_TITLE）+ 域 + 「能力】」')
  assert.equal(lines[1], '  ' + REAL_DOCS_INTRO, '第 2 行：intro **原文**（缩进 2 格 · ⛔ 不改写）')
  assert.equal(lines[2], '  → capabilities/domain-docs.md', '第 3 行：位置')
  // ⛔ 旧检索路径的字段/文案一个都不许混进来
  for (const bad of ['能力候选', '打分', 'score', 'scores', 'n=', 'top1', '· 能力候选', 'match']) {
    assert.equal(got.includes(bad), false, '⛔ 注入文本不得出现旧字段文案：' + bad)
  }
  // 阶段中文取的是既有 PHASE_TITLE（⛔ 不另立映射）
  for (const [ph, title] of Object.entries(FC.PHASE_TITLE)) {
    assert.ok(FC.renderDomainInjection(ph, '文档', 'domain-docs', 'x').startsWith('【AI-OS · ' + title + ' · 文档能力】'),
      '阶段中文必须来自 PHASE_TITLE：' + ph)
  }
  // 真实 frontmatter 的 intro 原文（独立正则）与实现读出来的一致（防"读错字段"）
  assert.equal(FC.domainIntroOf('domain-docs'), REAL_DOCS_INTRO, 'domainIntroOf 必须返回 frontmatter 的 intro 原文')
  assert.equal(FC.domainCapabilityOf('文档'), 'domain-docs', '文档 ⇒ domain-docs（现读 capabilities/domain-*.md）')
  assert.equal(FC.inferDomainOf('整理文档结构并补说明书'), '文档', '域判定复用既有词表（文档）')
  assert.equal(FC.inferDomainOf('把这件事做完'), null, '无域词 ⇒ null（⛔ 不猜）')
})

// **注入跟随卡上声明的域能力** ─────────────────────────────
//   四件事（⛔ 不重新论证方向）：① 读声明（`.log` **末条** > 卡正文「## 使用的能力」）
//   ② 注入（同一声明 ⇒ 不重复；**声明变了 ⇒ 同阶段再注入一次**）
//   ③ 停用猜域（`inferDomainOf` / `domainCapabilityOf` 保留为纯函数，注入路径不再调用）
//   ④ POLICY 尾 token `+v51r-declared-domain`。
//   以下用例盯的都是**接线**（真实 `tools/post-execute` handler）与探针读数，⛔ 不只测纯函数。

checkAsync('S188 domainInject:"off" ⇒ 零 `basis:"declared"` 探针（快照逐字不变 · 声明在也不读）', async () => {
  const prev = domEnvSnapshot()
  const ID = 'TASK-20261102-184'
  const SID = 'selftest-v51r-off'
  const goal = '把 v51r 接上'
  const next = '改 runtime 注入段'
  try {
    // ① 开关读法：字段缺 / "off" / 非法值 ⇒ off，且⛔ 不抛错（与 S183 同一口径，这里只钉 off 的接线）
    for (const [di, why] of [[undefined, '字段缺'], ['off', '"off"'], ['yes', '非法值']]) {
      domPrepare(di)
      assert.doesNotThrow(() => {
        assert.equal(FC.domainInjectEnabled(), false, why + ' ⇒ off')
      }, why + '：⛔ 不得抛错')
    }
    // ② 真实 handler：卡上**真的声明了** `domain-docs`，但开关 off ⇒ 声明通道一行都不执行
    domPrepare('off')
    assert.equal(FC.domainInjectEnabled(), false, '本用例开关确实是关的（⛔ 别把"关闭"误判成"没声明"）')
    const cardBody = cardWithCap(ID, 'Executing', 0, goal, next, 'domain-docs')
    const { rec } = await domRun(SID, ID, goal, next, undefined,
      { cardBody, logText: logWithCap(SID, 'domain-docs') })
    // 声明**读得到** ⇒ "零注入"是开关挡的，不是声明缺失（否则本用例是空转）
    assert.equal(FC.declaredDomainCapabilityOf(cardCursor(ID), SID), 'domain-docs', '声明必须读得到')
    // 零声明探针；且探针形状与改前**逐字一致**
    assert.equal(rec.filter(r => r.basis === 'declared').length, 0, 'off ⇒ 零 `basis:"declared"`：' + JSON.stringify(rec))
    assert.equal(rec.filter(r => r.basis === 'domain').length, 0, 'off ⇒ 也不再落 v51q 的 `basis:"domain"`：' + JSON.stringify(rec))
    for (const r of rec) {
      assert.equal('basis' in r, false, 'off ⇒ 探针无 `basis` 键（快照不变）：' + JSON.stringify(r))
      assert.equal('capability' in r, false, 'off ⇒ 探针无 `capability` 键（快照不变）：' + JSON.stringify(r))
    }
    // 旧路径照旧：本拍最多一条 phase-inject，状态落在旧词汇里
    assert.ok(rec.length <= 1, '旧路径每拍最多一条注入：' + JSON.stringify(rec))
    if (rec.length === 1) {
      assert.ok(['injected', 'spawn-failed', 'no-candidate'].includes(rec[0].state), '旧路径状态：' + rec[0].state)
    }
  } finally {
    domRestore(prev)
    domCleanup([ID])
  }
})

checkAsync('S189 domainInject:"on" + 声明 `domain-docs` ⇒ 恰 1 条 `basis:"declared"` + intro 原文 + 指向 domain-docs.md', async () => {
  const prev = domEnvSnapshot()
  const ID = 'TASK-20261102-185'
  const SID = 'selftest-v51r-declared'
  // topic 故意写成**后端**味道 —— 声明是文档 ⇒ 注入必须是文档（证明"声明赢过猜域"）
  const goal = '把 v51r 接上'
  const next = '改后端接口与数据库迁移'
  try {
    domPrepare('on')
    assert.equal(FC.domainInjectEnabled(), true, '文件 domainInject:"on" ⇒ 开')
    assert.equal(FC.inferDomainOf(next), '后端', '用例前提：这段 topic 用旧猜域会判成"后端"')
    const { out, rec } = await domRun(SID, ID, goal, next, undefined,
      { cardBody: cardWithCap(ID, 'Executing', 0, goal, next, 'domain-docs'), logText: logWithCap(SID, 'domain-docs') })
    // ① 探针：恰好 1 条 · basis:"declared" · capability/domain/state/chars/n · **必带 session**
    const decl = rec.filter(r => r.basis === 'declared')
    assert.equal(decl.length, 1, '🔴 恰好 1 条 `basis:"declared"`：' + JSON.stringify(rec))
    assert.equal(decl[0].state, 'injected', 'state = injected')
    assert.equal(decl[0].capability, 'domain-docs', 'capability = 卡上声明的域能力')
    assert.equal(decl[0].domain, '文档', 'domain = 该能力 frontmatter 的域名（⛔ 不是猜出来的）')
    assert.equal(decl[0].n, 1, 'n = 1（域路径恒一条）')
    assert.equal(decl[0].session, SID, '🔴 探针必带 session（P83）')
    assert.equal(decl[0].phase, 'S1', 'phase = S1（占卡后、未实质改动）')
    // ② 注入文本：标题 + intro **原文** + 位置行（逐字 3 行 · 形状不变）
    const text = '【AI-OS · 决策 · 文档能力】\n  ' + REAL_DOCS_INTRO + '\n  → capabilities/domain-docs.md'
    assert.equal(decl[0].chars, text.length, 'chars = 注入文本长度')
    const ctx = JSON.stringify(out)
    assert.ok(ctx.includes('【AI-OS · 决策 · 文档能力】'), '注入标题必须真的进上下文：' + ctx.slice(0, 300))
    assert.ok(ctx.includes(REAL_DOCS_INTRO), '🔴 必须含 domain-docs frontmatter 的 intro 原文（⛔ 不改写）')
    assert.ok(ctx.includes('→ capabilities/domain-docs.md'), '必须带域能力位置')
    // ③ 本拍只此一条（声明命中 ⇒ 检索/格路径让位）
    assert.equal(rec.length, 1, '本拍恰好一条 phase-inject')
  } finally {
    domRestore(prev)
    domCleanup([ID])
  }
})

checkAsync('S190 domainInject:"on" + 卡上**未声明** ⇒ 零注入（⛔ 不回退猜域 · 猜得出域也不猜）', async () => {
  const prev = domEnvSnapshot()
  const ID = 'TASK-20261102-186'
  const SID = 'selftest-v51r-undeclared'
  const goal = '把这件事做完'
  const next = '改后端接口与数据库迁移'
  try {
    domPrepare('on')
    // 前提：这段 topic **猜得出**域（后端）—— 若实现还在猜域，就一定会注进来
    assert.equal(FC.inferDomainOf(next), '后端', '用例前提：旧猜域会把这段 topic 判成"后端"')
    // 卡：无「使用的能力」节（v4 模板占位之前的状态）· `.log` 只有 claim 行 ⇒ **未声明**
    const { out, rec } = await domRun(SID, ID, goal, next)
    assert.equal(FC.declaredDomainCapabilityOf(cardCursor(ID), SID), null, '用例前提：确实读不到声明')
    // ① 零 phase-inject 探针（不是"零 declared"—— 旧检索判域也必须一条都不落）
    assert.equal(rec.length, 0, '🔴 未声明 ⇒ **零注入零探针**（⛔ 不回退检索判域）：' + JSON.stringify(rec))
    assert.equal(rec.filter(r => r.basis === 'declared').length, 0, '无 `basis:"declared"`')
    assert.equal(rec.filter(r => r.basis === 'retrieval').length, 0, '无 `basis:"retrieval"`')
    // ② 上下文里没有注入文本
    assert.equal(JSON.stringify(out).includes('能力】'), false, '未声明 ⇒ 一个字的注入文本都不该有')
    // ③ 也没记账（`sent` 不写 —— 有了声明该阶段仍应能注）
    const slot = FC.PHASE_INJECT.get(SID)
    assert.ok(slot, '会话槽必须已建')
    assert.equal(slot.sent.has('S1'), false, '未声明 ⇒ 不记账（⛔ 把阶段锁死）')
  } finally {
    domRestore(prev)
    domCleanup([ID])
  }
})

checkAsync('S191 domainInject:"on" + 声明 `none` ⇒ 零注入（已声明"不用能力" ≠ 未声明）', async () => {
  const prev = domEnvSnapshot()
  const ID = 'TASK-20261102-187'
  const SID = 'selftest-v51r-none'
  const goal = '把这件事做完'
  const next = '改后端接口与数据库迁移'
  try {
    domPrepare('on')
    const { out, rec } = await domRun(SID, ID, goal, next, undefined,
      { cardBody: cardWithCap(ID, 'Executing', 0, goal, next, 'none'), logText: logWithCap(SID, 'none') })
    // 声明**读到了**（值是 "none"）—— 零注入是因为"不用能力"，不是因为"读不到"
    assert.equal(FC.declaredDomainCapabilityOf(cardCursor(ID), SID), 'none', '用例前提：声明值就是 none')
    assert.equal(rec.length, 0, '🔴 `none` ⇒ 零注入零探针：' + JSON.stringify(rec))
    assert.equal(JSON.stringify(out).includes('能力】'), false, '`none` ⇒ 一个字的注入文本都不该有')
  } finally {
    domRestore(prev)
    domCleanup([ID])
  }
})

checkAsync('S192 同一声明 ⇒ dup（不重复）· 声明改成 `domain-backend` 再拍 ⇒ `state:"re-injected"` + prev=domain-docs', async () => {
  const prev = domEnvSnapshot()
  const ID = 'TASK-20261102-188'
  const SID = 'selftest-v51r-reinject'
  const goal = '把 v51r 接上'
  const next = '改 runtime 注入段'
  try {
    domPrepare('on')
    // ① 第一拍：声明 domain-docs ⇒ 注入
    const s1 = await domRun(SID, ID, goal, next, undefined,
      { cardBody: cardWithCap(ID, 'Executing', 0, goal, next, 'domain-docs'), logText: logWithCap(SID, 'domain-docs') })
    const d1 = s1.rec.filter(r => r.basis === 'declared')
    assert.equal(d1.length, 1, '第一拍恰 1 条：' + JSON.stringify(s1.rec))
    assert.equal(d1[0].state, 'injected')
    assert.equal(d1[0].capability, 'domain-docs')
    // ② 第二拍：声明**没变** ⇒ ⛔ 不重复注入，只落**一条** dup 读数
    const s2 = await domNextStep(SID, ID, { turn: 2 })
    const d2 = s2.rec.filter(r => r.basis === 'declared')
    assert.equal(d2.length, 2, '第二拍要落 dup 读数：' + JSON.stringify(s2.rec))
    assert.equal(d2[1].state, 'dup', '同一声明 ⇒ dup（⛔ 重复注入）')
    assert.equal(d2[1].capability, 'domain-docs')
    assert.equal(d2[1].n, 0, 'dup 不注 ⇒ n=0')
    assert.equal(JSON.stringify(s2.out).includes('能力】'), false, 'dup 那拍上下文里不该再有注入文本')
    // ③ 第三拍：**声明变了**（`.log` 追加一条 = 现实中 agent 再记一次能力）⇒ 同阶段**再注入一次**
    const s3 = await domNextStep(SID, ID, {
      turn: 3,
      cardBody: cardWithCap(ID, 'Executing', 0, goal, next, 'domain-backend'),
      appendLog: '| 02:00 | 能力 | domain-backend ｜ 理由：改成后端 | Worker |\n',
    })
    const d3 = s3.rec.filter(r => r.basis === 'declared')
    assert.equal(d3.length, 3, '声明变了 ⇒ 恰好再注一条：' + JSON.stringify(s3.rec))
    assert.equal(d3[2].state, 're-injected', '🔴 声明变了 ⇒ `state:"re-injected"`')
    assert.equal(d3[2].prev, 'domain-docs', '🔴 `prev` = 上一次注入所用的域能力')
    assert.equal(d3[2].capability, 'domain-backend', 'capability = 新声明')
    assert.equal(d3[2].domain, '后端', 'domain = 新声明的域名')
    assert.equal(d3[2].phase, 'S1', '同阶段（S1）再注一次 —— 这正是"域不同了又注入"')
    const ctx3 = JSON.stringify(s3.out)
    assert.ok(ctx3.includes('→ capabilities/domain-backend.md'), '再注入的文本必须指向新域能力：' + ctx3.slice(0, 300))
    // `.log` 的**末条**才是声明（优先级①）—— 取首条就会永远注不进去
    assert.equal(FC.declaredCapOfLog(CARDS + '/' + ID + '.log'), 'domain-backend', '`.log` 末条 = 当前声明')
  } finally {
    domRestore(prev)
    domCleanup([ID])
  }
})

checkAsync('S193 声明旧能力名 `doc_standards` ⇒ 经 `capabilities/_aliases.json` 映射为 domain-docs 后注入', async () => {
  const prev = domEnvSnapshot()
  const ID = 'TASK-20261102-189'
  const SID = 'selftest-v51r-alias'
  const goal = '把 v51r 接上'
  const next = '整理文档结构并补说明书'
  try {
    domPrepare('on')
    // 声明只在**卡正文**（`.log` 无能力行）⇒ 顺带证明优先级②这条路也通
    const { out, rec } = await domRun(SID, ID, goal, next, undefined,
      { cardBody: cardWithCap(ID, 'Executing', 0, goal, next, 'doc_standards') })
    assert.equal(FC.declaredDomainCapabilityOf(cardCursor(ID), SID), 'doc_standards', '用例前提：卡正文里的旧名读得到')
    const decl = rec.filter(r => r.basis === 'declared')
    assert.equal(decl.length, 1, '🔴 恰 1 条 `basis:"declared"`：' + JSON.stringify(rec))
    assert.equal(decl[0].capability, 'domain-docs', '🔴 旧名必须**映射**成域能力名')
    assert.equal(decl[0].domain, '文档', 'domain = 映射后能力的域名')
    assert.equal(JSON.stringify(decl[0]).includes('doc_standards'), false, '探针里⛔ 不回显旧名')
    const ctx = JSON.stringify(out)
    assert.ok(ctx.includes('→ capabilities/domain-docs.md'), '注入必须指向**映射后**的域能力：' + ctx.slice(0, 300))
    // 纯函数层：映射表读法（⛔ 不猜近义 / 映射目标不是域能力 ⇒ null）
    assert.equal(FC.domainCapabilityResolvedOf('domain-docs'), 'domain-docs', '已是域能力 ⇒ 原样')
    assert.equal(FC.domainCapabilityResolvedOf('doc_standards'), 'domain-docs', '旧名 ⇒ 域能力')
    assert.equal(FC.domainCapabilityResolvedOf('self-verification'), 'domain-aios-itself', '旧名 ⇒ 域能力（第二例）')
    assert.equal(FC.domainCapabilityResolvedOf('no_such_cap'), null, '映射表里没有 ⇒ null（⛔ 不注）')
    assert.equal(FC.domainCapabilityResolvedOf('domain-not-exist'), null, '形如域能力但文件不存在 ⇒ null')
  } finally {
    domRestore(prev)
    domCleanup([ID])
  }
})

// **纯乱码 query ⇒ 词面召回 0 命中** ──────────
//   现场：`exec-encoding-error` 反复触发（`\uFFFD` 命中 ENCODING_FAIL_RE）但探针 `hits` 恒 0。
//   手工复现：`experience_push.py "���"` ⇒ `empty query after tokenization`；
//             `"��� [exit code: 1]"` ⇒ `no relevant past experience found`。
//   根因：整段输出被控制台解码成替换字符 ⇒ 特征行里没有可分词的真实词。
//   修法：特征行不含 3+ 连续 ASCII 字母时，补编码族规范词（⛔ 不改检索算法，只补 query 词）。
check('S194 纯乱码失败 ⇒ query 补编码族规范词（否则词面召回恒 0）', () => {
  const mojibake = '[stderr]\n\uFFFD\uFFFD\uFFFD\n[exit code: 1]\n'
  const res = { isError: false, content: [{ type: 'text', text: mojibake }] }
  assert.equal(FC.recallTriggerOf(res, 'pwsh'), 'exec-encoding-error', '前提：纯乱码应触发编码族')
  const q = FC.buildExperienceQuery('pwsh', {}, res)
  for (const need of ['乱码', '编码', 'gbk', 'codec']) {
    assert.ok(q.includes(need), '纯乱码 query 必须补 `' + need + '`（否则分词为空 ⇒ 0 命中）：' + q)
  }
  // ⛔ 反向：**有真实错误签名**时不得被补词污染（原 query 已能命中编码族）
  const real = { isError: false, content: [{ type: 'text', text:
    'UnicodeEncodeError: \'gbk\' codec can\'t encode character \'\\u2192\' in position 5: illegal multibyte sequence\n[exit code: 1]\n' }] }
  const q2 = FC.buildExperienceQuery('pwsh', {}, real)
  assert.ok(q2.includes('UnicodeEncodeError'), '真实签名必须保留：' + q2)
  assert.ok(!q2.includes('mojibake'), '有 ASCII 签名时⛔ 不补规范词（避免污染原有排名）：' + q2)
})

// ── **子进程输出硬上限**的判据（纯函数锁行为）────────
//   背景：spawnJson / 影子 A-B 两处 spawn 原先只做超时兜底，out += String(d) 无字节上限
//   ⇒ 子进程误开 debug / 异常刷栈可把宿主内存打爆，且**零探针**。
check('S195 子进程输出上限判据：超限才算超限（边界不误杀）', () => {
  const f = mod.outputExceedsLimit
  assert.equal(typeof f, 'function', 'outputExceedsLimit 必须是导出函数（否则不可测）')
  assert.equal(f(0, 1, 8), false, '未到上限⇒不超')
  assert.equal(f(7, 1, 8), false, '恰好等于上限⇒不超（边界）')
  assert.equal(f(8, 1, 8), true, '超 1 字节⇒超限')
  assert.equal(f(0, 9, 8), true, '单块就超⇒超限')
  assert.equal(f(0, 0, 0), false, '0 上限 + 0 字节⇒不超')
  assert.equal(f(0, 1, 0), true, '0 上限 + 1 字节⇒超限')
})

// ── 开关缓存失效判据（纯函数）──────────────────
//   背景：readInjectProbe() 每步 pre-execute 都读盘 + JSON.parse ⇒ 热路径 IO。
//   改法：按 mtime+size 缓存**解析结果**，每次仍 stat（「改即生效」语义不变）。
check('S196 开关缓存失效判据：mtime 或 size 变才重读', () => {
  const f = mod.switchNeedsReload
  assert.equal(typeof f, 'function', 'switchNeedsReload 必须是导出函数（否则不可测）')
  assert.equal(f(100, 10, 100, 10), false, 'mtime/size 都没变 ⇒ 命中缓存')
  assert.equal(f(100, 10, 101, 10), true, 'mtime 变 ⇒ 重读')
  assert.equal(f(100, 10, 100, 11), true, 'size 变 ⇒ 重读（同秒内改大小也要生效）')
  assert.equal(f(0, 0, 0, 0), false, '首次 0/0 也视为命中（调用方用 Map 有无判断首读）')
})

// 召回 query 的乱码归一化（发布前观察：7 次召回 5 次 query 是乱码 ⇒ 0 命中）
check('S197 召回 query 乱码归一化：不含替换字符 · 带错误分类与 ASCII 签名', async () => {
  const rb = await import(pathToFileURL(RUNTIME_DIR + '/retrieval/request-builder.ts').href)
  assert.equal(typeof rb.buildExperienceQuery, 'function', 'buildExperienceQuery 必须导出（否则不可测）')
  // 现场形态：控制台把 GBK 输出解成替换字符 + 残留 ASCII 签名
  const garbled = { isError: true, content: '\uFFFD\uFFFD{\u0000 SyntaxError: Unexpected token \uFFFD, gbk codec' }
  const q1 = rb.buildExperienceQuery('pwsh', { command: 'python x.py' }, garbled)
  assert.equal(typeof q1, 'string')
  assert.ok(q1.length > 0, 'query 不能为空')
  assert.ok(!/\uFFFD|\u0000/.test(q1), 'query 不得携带替换字符/NUL：' + q1)
  assert.ok(/syntax-error|encoding-error/.test(q1), 'query 必须带错误分类：' + q1)
  assert.ok(/SyntaxError/.test(q1), 'query 应保留 ASCII 签名：' + q1)
  // 正常文本不被改写（只做乱码归一化）
  const plain = { isError: true, content: 'permission denied: HRESULT 0x80041003 PermissionDenied' }
  const q2 = rb.buildExperienceQuery('pwsh', {}, plain)
  assert.ok(/PermissionDenied|HRESULT|permission/i.test(q2), '正常失败文本应原样进入 query：' + q2)
})

// `allowSubagent` 缺省改为**开**（子 agent 承担真实工作时不再落在注入盲区）
check('S198 allowSubagent 缺省开 · 显式 false 才关', async () => {
  const pd = await import(pathToFileURL(RUNTIME_DIR + '/delivery/pending-delivery.ts').href)
  assert.equal(typeof pd.readInjectProbe, 'function', 'readInjectProbe 必须导出（否则不可测）')
  const fs = await import('node:fs')
  const path = await import('node:path')
  const os = await import('node:os')
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'aios-probe-'))
  const file = path.join(dir, 'inject_probe.json')
  const prev = process.env.AIOS_INJECT_PROBE
  try {
    fs.writeFileSync(file, JSON.stringify({ enabled: true, session: '*' }), 'utf8')
    process.env.AIOS_INJECT_PROBE = file
    const a = pd.readInjectProbe()
    assert.ok(a !== null, '开关应被读入')
    // 缺省（未写 allowSubagent）⇒ 允许子会话
    assert.equal(a.allowSubagent, true, 'allowSubagent 缺省应为 true：' + JSON.stringify(a))
    fs.writeFileSync(file, JSON.stringify({ enabled: true, session: '*', allowSubagent: false }), 'utf8')
    const b = pd.readInjectProbe()
    assert.equal(b.allowSubagent, false, '显式 false 必须生效：' + JSON.stringify(b))
  } finally {
    if (prev === undefined) delete process.env.AIOS_INJECT_PROBE
    else process.env.AIOS_INJECT_PROBE = prev
    try { fs.rmSync(dir, { recursive: true, force: true }) } catch { /* 清理失败不影响判据 */ }
  }
})

// 🔴 **顺序**执行异步用例（共用开关文件 ⇒ 并发会互相干扰）；⚠️ 必须**调用**（`task()`）——
//    只写 `await task` 会在 await 一个函数值后立即完成，用例根本没跑（本自测抓到过这个错）。
for (const task of pending) await task()
console.log = origLog
const discoCounts = records().filter(r => r.ev === 'trigger').pop()
console.log('\n=== AI-OS 隔离自测：aios-activation（§15 延迟发现增量）===')
for (const line of results) console.log(line)
const failed = results.filter(x => x.startsWith('FAIL'))
// 🔴 护栏：**未完成**的异步用例必须算失败，不得被当作"通过"（曾出现"PENDING 却报 40/40"）
const stuck = results.filter(x => x.startsWith('PENDING'))
if (stuck.length > 0) for (let i = 0; i < results.length; i++) if (results[i].startsWith('PENDING')) results[i] = 'FAIL  ' + results[i].slice('PENDING  '.length) + ' :: 未执行完成（异步用例未被 await）'
const failedFinal = results.filter(x => x.startsWith('FAIL'))
console.log('\n合计 ' + results.length + ' 项 · 通过 ' + (results.length - failedFinal.length) + ' · 失败 ' + failedFinal.length + (stuck.length > 0 ? '（其中 ' + stuck.length + ' 项为未执行完成）' : ''))
console.log('末次 trigger 的累计计数：' + JSON.stringify(discoCounts ? discoCounts.discoCounts : null))
rmSync(CARDS, { recursive: true, force: true })
process.exitCode = failedFinal.length === 0 && failed.length === 0 ? 0 : 1
