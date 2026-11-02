@echo off
REM AI-OS wrapup write-back - DSH Stop hook launcher (2026-10-05)
REM
REM NOTE: this file is deliberately ASCII-only. cmd.exe decodes a .cmd with the
REM OEM code page (GBK here), so non-ASCII comments would be re-split into bogus
REM commands. Keep comments English/ASCII.
REM
REM Why a launcher instead of an inline command in hooks.json:
REM   DSH runs hook commands through ctx.shell, which on this host may resolve to
REM   Windows PowerShell 5.1; 5.1 does NOT support `||` ("The token '||' is not a
REM   valid statement separator in this version"), so the previous inline command
REM   `python ... || exit 0` failed as a whole under 5.1.
REM   A .cmd depends on no shell syntax: cmd, pwsh, 5.1 and direct CreateProcess
REM   all run it, and the allow-listed .claude/hooks.json only needs its path.
REM
REM Semantics: ALWAYS exit 0. A failed write must not block the agent; the script
REM itself reports to stderr and DSH records it in hook/result.stderrSummary.

setlocal
set "LOG=<repo>\scratch\_wrapup-hook-invocations.log"
echo [%DATE% %TIME%] launcher invoked args=%* >> "%LOG%"

set "WRAPUP_DECIDE_LOG=1"
set "PYEXE=python"
where python >nul 2>nul
if not "%ERRORLEVEL%"=="0" set "PYEXE=py"
"%PYEXE%" "<repo>\tools\wrapup_sync.py" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [wrapup-hook] python exit code %RC% - write-back may be incomplete; see stderr
exit /b 0
