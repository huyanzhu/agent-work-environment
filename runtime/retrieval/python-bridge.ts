/** python-bridge.ts —— 由 `runtime/aios-activation.ts` 拆出（纯移动）。
 *  ⛔ 本文件只做「搬家」：逻辑与原文件逐字一致；改动逻辑请改在原模块并跑 184 项自测。
 */


import { spawn } from 'node:child_process'


import { OBS, clip, emit, mono } from './../diagnostics/probe.ts'

export const SPAWN_MAX_STDOUT_BYTES = 8 * 1024 * 1024

export const SPAWN_MAX_STDERR_BYTES = 256 * 1024

/** 纯函数（导出供自测）：累计 acc 再收 chunk 字节后是否超限。 */

export function outputExceedsLimit(accBytes: number, chunkBytes: number, limit: number): boolean {
  return accBytes + chunkBytes > limit
}

/** 纯函数：字符串按 UTF-8 计字节数（不依赖 Buffer 全局，测试环境一致）。 */

export function utf8Bytes(s: string): number {
  let n = 0
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i)
    n += c < 0x80 ? 1 : c < 0x800 ? 2 : c >= 0xd800 && c <= 0xdbff ? 4 : 3
  }
  return n
}

export function spawnJson(entry: string, payload: Record<string, unknown>, timeoutMs: number,
                   done: (outcome: string, parsed: any, detail?: string) => void,
                   extraArgs: string[] = []): void {
  let child: any
  try {
    // 🔴 （读数 · /R2）：stdin 以 UTF-8 写（L2481），但 Windows 下 python 子进程
    //   默认按 locale(cp936/GBK) 解码 ⇒ 含中文的 payload 变 mojibake（经验检索 hits 恒 0）。
    //   ⇒ 显式固定子进程编码（对**所有** spawnJson 通道生效：经验召回 / stage4 能力检索 / 影子通道）。
    //   ⛔ 不改调用方语法/超时/分类 —— 只修传输层，为其他通道留同一处修复。
    const childEnv: Record<string, string | undefined> = { ...process.env }
    childEnv.PYTHONIOENCODING = 'utf-8'
    childEnv.PYTHONUTF8 = '1'
    child = spawn('python', [entry, ...extraArgs], { stdio: ['pipe', 'pipe', 'pipe'], env: childEnv })
  } catch (err) {
    done('spawn-error', null, clip(String(err), 120))
    return
  }
  let out = ''
  let errOut = ''
  let settled = false
  const finish = (outcome: string, parsed: any, detail?: string): void => {
    if (settled) return
    settled = true
    clearTimeout(timer)
    done(outcome, parsed, detail)
  }
  const timer = setTimeout(() => {
    try {
      child.kill()
    } catch {
      /* ⛔ 不落探针（批3 判定）：这里是 `child.kill()` 失败 —— kill 失败时子进程要么已退出、要么会被上层超时/关闭路径兜底；在此 emit 会在最坏路径上叠加 IO 风险 */
    }
    finish('timeout', null)
  }, timeoutMs)
  // 两侧都要字节上限（超限即 kill + 探针 + 归类失败），⛔ 不允许无界累积
  let outBytes = 0
  let errBytes = 0
  const tooLarge = (stream: 'stdout' | 'stderr', bytes: number, limit: number): void => {
    try {
      child.kill()
    } catch {
      /* ⛔ 不落探针（批3 判定）：这里是 `child.kill()` 失败 —— kill 失败时子进程要么已退出、要么会被上层超时/关闭路径兜底；在此 emit 会在最坏路径上叠加 IO 风险 */
    }
    emit({
      ev: 'spawn-output-limit', obs: OBS,
      stream, bytes, limit, entry: String(entry).split(/[\\/]/).pop(), at: Date.now(), mono: mono(),
    })
    finish('output-too-large', null, stream + '=' + String(bytes))
  }
  child.stdout.on('data', (d: any) => {
    const chunk = String(d)
    outBytes += utf8Bytes(chunk)
    if (outputExceedsLimit(outBytes, 0, SPAWN_MAX_STDOUT_BYTES)) {
      tooLarge('stdout', outBytes, SPAWN_MAX_STDOUT_BYTES)
      return
    }
    out += chunk
  })
  child.stderr.on('data', (d: any) => {
    const chunk = String(d)
    errBytes += utf8Bytes(chunk)
    if (outputExceedsLimit(errBytes, 0, SPAWN_MAX_STDERR_BYTES)) {
      tooLarge('stderr', errBytes, SPAWN_MAX_STDERR_BYTES)
      return
    }
    errOut += chunk
  })
  child.on('error', (err: any) => finish('child-error', null, clip(String(err), 120)))
  child.on('close', () => {
    // 🔴 **空输出必须与"零候选"严格分开**（历史教训：影子通道曾 30 次记 `outcome:'ok'` 却全为 null
    //    ⇒ 看起来像"无候选"，实则子进程什么都没说回来）。如实分类 + 带 stderr 摘要。
    const trimmed = out.trim()
    if (trimmed === '') {
      finish('empty-stdout', null, 'stderr=' + clip(errOut.trim(), 100))
      return
    }
    let parsed: any = null
    try {
      parsed = JSON.parse(trimmed)
    } catch {
      finish('bad-json', null, 'stdout=' + out.length + ' stderr=' + errOut.length)
      return
    }
    if (parsed === null || typeof parsed !== 'object' || Object.keys(parsed).length === 0) {
      finish('empty-object', null, 'stdout=' + out.length)
      return
    }
    if (parsed.error !== undefined) {
      finish('child-error', null, clip(String(parsed.error), 60))
      return
    }
    finish('ok', parsed)
  })
  try {
    child.stdin.write(JSON.stringify(payload), 'utf8')
    child.stdin.end()
  } catch {
    finish('stdin-error', null)
  }
}

/** `spawnJson` 的 Promise 包装 —— `post-execute` 需要 await 才能在同一决策里注入。 */

export function spawnJsonAsync(entry: string, payload: Record<string, unknown>, timeoutMs: number,
                        extraArgs: string[] = []):
  Promise<{ outcome: string; value: any; detail?: string }> {
  return new Promise(resolve => {
    spawnJson(entry, payload, timeoutMs, (outcome, value, detail) => resolve({ outcome, value, detail }), extraArgs)
  })
}
