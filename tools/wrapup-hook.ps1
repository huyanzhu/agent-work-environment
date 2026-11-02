# AI-OS wrapup write-back - DSH Stop hook launcher for the PowerShell side (2026-10-05)
# Equivalent to tools/wrapup-hook.cmd, which is the default because it depends on
# no shell syntax at all. Keep this file ASCII-only too: Windows PowerShell 5.1
# reads a BOM-less script as ANSI and would mangle non-ASCII text.
# Semantics: always exit 0 (a failed write must not block the agent; the script
# reports to stderr and DSH records it in hook/result.stderrSummary).

$exe = 'python'
if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { $exe = 'py' }
& $exe '<repo>\tools\wrapup_sync.py' @args
if ($LASTEXITCODE -ne 0) {
    Write-Host "[wrapup-hook] python exit code $LASTEXITCODE - write-back may be incomplete; see stderr"
}
exit 0
