---
title: 权限/沙箱错误族（先对号入座，再照做）
family: 权限/沙箱
status: pilot
trigger: 权限错误, 沙箱拒绝, PermissionError, WinError 5, 拒绝访问, access denied, Permission denied, Errno 13, mkdtemp, 临时目录, 0700, file access denied, workspace-write, escalation available, 工作区外写, 越权写
keywords: 权限, 沙箱, sandbox, 提权, danger-full-access, basetemp, 0700, Errno 13, WinError, mkdtemp, 临时目录, 拒绝访问, file, access, denied, workspace-write, escalation, write, 工作区外, 越权
alias: WMI, Get-CimInstance, CIM, HRESULT 0x80041003, PermissionDenied, CimException, Win32_Process, 进程查询, Get-CimInstance 拒绝访问, 0x80041003
---

遇到权限拒绝时，先判断属于哪一类，按下表照做；⛔ 不要整段照抄，也⛔ 不要先怀疑代码逻辑。

**做法 A · 提权（放开沙箱）**
- DSH 工作区里跑 `pytest` 报 `PermissionError [WinError 5]` / `rmtree` 拒绝访问 → 提权（`danger-full-access`）+ 每次用**全新** `--basetemp` 路径；⛔ 不要花时间查 ACL
- `Chrome --headless` 导出 PDF / 截图起不来（`crashpad_client_win` / `mojo ... 拒绝访问`）→ 提权；以产物是否存在判成功
- 通用 `Sandbox` / 权限错误（`PermissionError`、`拒绝访问`、`sandbox`）→ 先提权；⛔ 别 loop 换 API 绕过；提权后仍失败按 EFP-001 四诊断

**做法 B · 临时目录：换位置 + 选对目录模式**
- 系统临时区写不了（`%TEMP%` 被重定向且不可写）→ 产物/临时目录落**工作区内**
- ⚠️ `tempfile.mkdtemp()` 建的目录是 **mode 0700**：本机沙箱下这种目录**不可写、不可列举、不可删除**（`PermissionError [Errno 13]` / `WinError 5`）——只换位置不够
- 🔎 **根因**：DSH 沙箱给受限令牌的写权限来自**父目录继承**的 `S-1-4-*` 授权项；`os.mkdir(path, 0o700)` 会写入**显式 DACL**、切断继承 ⇒ 新目录连创建者都不可写，`chmod` 报 `WinError 5 拒绝访问`，也删不掉。**不是**「TEMP 在工作区外」
- 处置（三选一，按代价从低到高）：
  1. 不用 `mkdtemp()`：`os.mkdir()`（默认 mode）或 0755+ 的目录，或直接写**已存在**的目录
 2. **必须用 `mkdtemp()` 时**：只在调用期间把 `os.mkdir` 的 mode 补丁成默认 `0o777`（`try/finally` 还原）——观察写入/读回/清理全部成功
  3. 已产生的 0700 目录删不掉 ⇒ 需本机普通终端 `icacls "<目录>" /reset /T`（或 `takeown /f <目录> /r /d y`）后删
- 验证 = 先往目录里写一个小文件（`Test-Path` 不够，0700 目录也存在但写不进）

**验证**：`Test-Path <产物>` 存在且可读；报错文本里不再出现 `PermissionError` / `拒绝访问`。
**覆盖的坑（成员声明）**：P12 · P33 · P40 · P57 · P78 · P87（共 6 条）
**同义现象**：`PermissionError` · `WinError 5` · `拒绝访问` · `access denied` · `Permission denied` · `Errno 13` · `sandbox` · 文件动不了 · 工具说权限不够 · 无头浏览器导出 PDF 静默失败 · 临时文件夹删不掉 · `mkdtemp` · `0700` · 提权后仍失败。
