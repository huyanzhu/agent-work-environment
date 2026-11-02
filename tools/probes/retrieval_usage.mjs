// retrieval_usage.mjs — **只读**：从真实会话轨迹抽「检索候选有没有被打开/使用」
// 为什么存在
//   G3 的"检索有没有用"以前靠 Agent 自判"相关/采纳" ⇒ 读数被自己证伪（声称采纳 2 条，
//   轨迹里 capabilities/ 打开 **0 次**）。这个探针把判断换成**机械读数**：
//     · 检索调了几次、返回多少候选
//     · 候选指向的文件**被打开了几次**（read/write/edit）
//     · 哪些会话打开过哪个能力
//   ⇒ 「看到了」与「用了」第一次可以被分开统计，不再依赖自查。
// 用法：
//   node tools/probes/retrieval_usage.mjs [sessionsDir] [limit] [needle...]
//   默认 sessionsDir = %USERPROFILE%/.dsh/sessions · limit = 15
//   needle 例：capabilities/self-verification.md capabilities/frontend-ui.md
// 口径（如实）：
//   · 只扫 `session.v4.jsonl.zstd`（DSH v4 会话日志），按 mtime 取最近 limit 个
//   · "打开"= tool/call 的 file_path/path 命中 needle；**打开是消费的必要条件、不是充分条件**
//   · 不读正文、不写盘、不上传；只输出计数与路径
import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'

const sessionsDir = process.argv[2] || path.join(process.env.USERPROFILE || process.env.HOME || '.', '.dsh', 'sessions')
const limit = Number(process.argv[3] || 15)
const needles = process.argv.slice(4)
const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])

function listSessions(dir) {
  const out = []
  const walk = (d) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name)
      if (e.isDirectory()) walk(p)
      else if (e.name === 'session.v4.jsonl.zstd') out.push({ p, mt: fs.statSync(p).mtimeMs })
    }
  }
  walk(dir)
  return out.sort((a, b) => b.mt - a.mt).slice(0, limit)
}

function decodeLines(file) {
  const buf = fs.readFileSync(file)
  const starts = []
  for (let i = 0; i + 4 <= buf.length; i++) {
    if (buf[i] === MAGIC[0] && buf[i + 1] === MAGIC[1] && buf[i + 2] === MAGIC[2] && buf[i + 3] === MAGIC[3]) starts.push(i)
  }
  const pieces = []
  for (let k = 0; k < starts.length; k++) {
    const a = starts[k], b = k + 1 < starts.length ? starts[k + 1] : buf.length
    try { pieces.push(zlib.zstdDecompressSync(buf.subarray(a, b)).toString('utf8')) } catch { /* 跳帧 */ }
  }
  return pieces.join('').split('\n').filter(Boolean)
}

const capOpens = new Map() // key -> { n, strict, sessions:Set }（宽松口径：含 Windows 反斜杠）
let toolCalls = 0
let workReports = 0
let scanned = 0
let decoded = 0
let openStrict = 0 // 严格口径（只认 `capabilities/`，历史数字可比）
let openLoose = 0 // 宽松口径（`capabilities\` 也算）

for (const f of listSessions(sessionsDir)) {
  let lines
  try { lines = decodeLines(f.p); decoded++ } catch { continue }
  scanned++
  const sid = path.basename(path.dirname(f.p))
  for (const l of lines) {
    if (!l.includes('"tool/call"')) continue
    let d
    try { d = JSON.parse(l).data } catch { continue }
    toolCalls++
    if (d.name === 'auto_capability' || d.name === 'work_report') workReports++ // v38 改名；旧名保留兼容历史会话
    let args
    try { args = JSON.parse(d.arguments) } catch { continue }
    const p = args.file_path || args.path || ''
    // 🔴 旧口径只认正斜杠 `capabilities/`，而 Windows 工具调用路径多为
    //    反斜杠 `capabilities\` ⇒ 系统性漏计（84 会话读数：严格 24 次 vs 宽松 207 次）。
    //    现两种口径并列输出：严格（与历史数字可比）+ 宽松（真实打开次数）。
    if (typeof p !== 'string' || !/capabilities[\\/]/i.test(p)) continue
    openLoose++
    const isStrict = p.includes('capabilities/')
    if (isStrict) openStrict++
    const key = p.split(/capabilities[\\/]/i)[1] || p
    const cur = capOpens.get(key) || { n: 0, strict: 0, sessions: new Set() }
    cur.n++
    if (isStrict) cur.strict++
    cur.sessions.add(sid)
    capOpens.set(key, cur)
  }
}

console.log('扫描会话 = ' + scanned + '（解码 ' + decoded + ' · 最近 ' + limit + ' 个）· 目录 ' + sessionsDir)
console.log('tool/call = ' + toolCalls + ' · auto_capability（旧名 work_report）= ' + workReports)
console.log('capabilities 文件打开：严格口径(正斜杠/)= ' + openStrict + ' · 宽松口径(含反斜杠)= ' + openLoose)
console.log('\n被打开过的 capabilities/ 文件（宽松口径 · ⟂ 后为严格口径计数）：')
if (capOpens.size === 0) console.log('  （无 —— 一次都没有）')
else for (const [k, v] of [...capOpens.entries()].sort((a, b) => b[1].n - a[1].n)) {
  console.log('  ' + k + '  ×' + v.n + (v.strict !== v.n ? '（严格 ' + v.strict + '）' : '') + '  会话数=' + v.sessions.size)
}

if (needles.length > 0) {
  console.log('\n指定候选是否被打开：')
  for (const n of needles) {
    const hit = [...capOpens.entries()].filter(([k]) => n.includes(k) || k.includes(n))
    console.log('  ' + n + ' ⇒ ' + (hit.length ? '打开 ' + hit.reduce((s, [, v]) => s + v.n, 0) + ' 次' : '**0 次**'))
  }
}
