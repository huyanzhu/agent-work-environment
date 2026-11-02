@echo off
REM Diagnostic launcher (2026-10-05): record exactly what the DSH hook process can
REM do, then forward to the real launcher. ASCII-only on purpose (cmd.exe OEM decoding).
REM
REM Everything is echoed to stdout/stderr so the bridge's hook/result.stderrSummary
REM carries it even when file writes are denied.

setlocal
echo [diag] launcher-executed
echo [diag] cwd=%CD%
echo [diag] args=%*
call "<repo>\tools\wrapup-hook.cmd" %* 1>"<repo>\scratch\_diag-fwd.out" 2>"<repo>\scratch\_diag-fwd.err"
echo [diag] forward-exit=%ERRORLEVEL%
echo [diag] stdout-file:
type "<repo>\scratch\_diag-fwd.out" 2>nul
echo [diag] stderr-file:
type "<repo>\scratch\_diag-fwd.err" 2>nul
exit /b 0
