# 注入摘要库

```text
用途：一长串的 pattern / 能力只给**指针**；这里每条是 **≤1 句「照做就行」**，走 inject 通道直接注入。
格式：`- **主题**：一句话处置 → 指针`
口径：Human —— 「简短的直接注入，一长串跟能力一样 ⇒ 给指针」；本库是「短」的那一侧。
维护：新增长 pattern / 能力时同步加一条摘要；⛔ 不复制正文（细节在指针处）。
```

- **权限/沙箱错误**：先提权（`require_escalated`），别 loop 换 API 绕过；提权后仍失败按 EFP-001 四诊断。→ domains/backend/patterns/escalation_workflow.md
- **改 bug 三次没好**：停手，从干净状态重置到最简可工作版本，再逐个加特性验证。→ domains/ai-os/patterns/debug_protocol.md
- **动数据前先答四问**：备份可还原 / 索引已回填 / 部分更新不误清 / 跨机不搬目录。→ capabilities/data-change-safety.md
- **Windows 上写中文文件**：只用 `edit`/`write`；整文用 Python/Node 显式 UTF-8；写回无 BOM；写完读回验证。→ domains/experiences/mojibake_prevention.md
- **改本体必升 POLICY 串**：否则 `ev=apply` 相同、判不出是否加载新代码。→ task_cards/memory/PITFALLS.md（P6）
- **交接写「待重启」前先读最后一条 `ev=apply`**：policy 已含新版本就别白等重启。→ task_cards/memory/PITFALLS.md（P63）
- **权限/沙箱错误族**：遇到 PermissionError / WinError 5 / Errno 13 / 拒绝访问 / access denied / file access denied / workspace-write / 工作区外写 / 临时目录 / mkdtemp / 0700 时先对号入座——提权（pytest/Chrome/通用 sandbox）或临时目录换位置（别用 mkdtemp 的 0700 目录，用默认 mode/已存在目录）→ domains/experiences/permission_sandbox_family.md
- **中文乱码/编码错误族**：遇到乱码/编码错误先判"写坏了 / 读错了 / 传丢了"——改文件别用 PowerShell 整文读写 · 读文件显式 UTF-8 · 重定向/管道用 `Out-File -Encoding utf8`（PS 5.1 的 `>` 写 UTF-16）· ⚠️ UTF-8 能解码 ≠ 内容正常 → domains/experiences/encoding_errors_family.md
- **推送/发布族**：git push 报 signal pipe/exit 66/could not read Username = 沙箱挡 credential helper（用 `gh auth token` + `-c credential.helper=`）· gh api `-f` 被当 POST 加 `--method GET` · 分支名带 `/` 查 `git/ref/heads/` · 传文件后 404 以 PR diff 为准 · 删 JSON 字段先验 `json.load` · PR 前核全副本防夹带 → domains/experiences/push_release_family.md
