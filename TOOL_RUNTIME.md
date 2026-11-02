# AI-OS 工具运行时（Agent 实际使用的）

> 本文档 = 工具入口：每个工具一句话（是什么 / 什么时候用）。
> **当前工作入口（2026-10-09 起）**：`task_cards/README.md`（总项目 `AI-OS v2` + 三子项目：P0 / 强化与适配 / 顾问重构）。
> 请阅读 `README.md` 并按照规范执行；正在执行或执行过不管。

## 1. 工具一行式

| 工具 | 是什么 | 什么时候用 |
|---|---|---|
| `tools/task_card.py` | 任务卡管理：`list`（看进行中卡片，含项目文件夹）· `create <标题>`（建卡）· `archive TASK-ID --confirm`（归档：任务完成 + 用户确认）· **`claim TASK-ID`**（显式占用：`Planning`/`Parked` → `Executing`）· **`release TASK-ID --state=Parked\|Completed`**（显式释放 · 必填）· **`states`**（只读状态校验：报缺失 / 值域外） | 开工建卡记目标；**开工用 `claim` 声明占用，本轮结束用 `release` 声明释放**（`State` = 占用声明 · ⛔ 脚本不自动改 · 停止 ≠ 结束）；任务完成且用户确认后归档；项目级状态用 `PROJECT.md`（项目文件夹内） |
| `tools/experience_push.py` | 经验推送：按当前任务描述检索相关经验并**直接展示内容摘要（命中请采纳）**（Don't Pay Twice）。**外部记忆默认关闭**：仅检索当前环境（SUCCESS_LOG + domains + 项目内 `.workbuddy`）；设置 `AIOS_EXTERNAL_MEMORY` 环境变量才接入外部记忆（显式 opt-in） | 任务开始或卡住时运行；命中即采纳 |
| `tools/task_start.py` | **开工视图**（2026-10-09 职责收敛后）：**无参 = 只做任务恢复**（有哪些卡可能要继续 + 卡内 Goal / 下一步 / 路径）；**带任务描述 = 加做材料发现**（经验 / 能力候选，与 R4 **同源判据**）。收敛依据：开工时**还不知道用户要做什么**，实测无 prompt 时能力 trigger **9/9 全命中** = 噪声（`AUTOMATION-BOUNDARY.md §12.0.1 §12.2`） | 每轮开工：先跑**无参**版恢复上下文；需要**按任务**检索经验 / 能力时带描述（或 `--auto`）重跑 |
| `tools/aios-hook.py` | **R0 稳定入口（dispatcher）**：`.claude/hooks.json` 三个事件都指向它（`<Event>` = `SessionStart` / `UserPromptSubmit` / `Stop`）。它读**运行期开关** `.claude/aios-exposure.json`，按开关决定跑哪些 action，汇总成**一行 JSON**。**只做路由** —— 不是状态源 · 不做判断 · 任何路径 `exit 0` | **不需要手工调用**；要开/关一个暴露 ⇒ **改 `.claude/aios-exposure.json` 一行即生效，不需要重启**（这是它存在的唯一理由 · `§12.1`）· 诊断看轨迹 `hook/result` 的 stderr |
| `tools/task-start-hook.py` | R1「**任务恢复**」的可独立执行**薄壳**：输出 Claude Code 方言的一行 JSON（`hookSpecificOutput.additionalContext`；实测 **949 字符 / 1520 字节**）。收敛后 runtime 正常路径已走 `tools/aios-hook.py`，本文件只作**直连 / 自测**入口（`§11.5 ⑤` 保留已验证件） | **不需要手工调用**（挂在宿主 `SessionStart` 上）；需要**绕过开关**做单点验证时直连它 |
| `tools/observe_extract.py` | 观察提取（NC-001）：从 session JSONL 提取结构化观察（能力使用 Trace / token 成本 / 时间 / 推理片段 / Artifact） | Evolution 侧需要 Cost/Time/Trace 证据时运行（Evidence Primitive 候选，等自然需求） |
| `tools/wrapup_sync.py` | 收尾写回（**写回型**）：① 任务卡 Event Log（R2）② **账本 `样例账本.md`**（R3 —— **只写机械事实**，`Outcome` / `footprint` 留占位「待补」，判断归 Agent / Human）。**选卡不猜**：显式 `TASK-ID` ▸ `--project <目录>` ▸ git 改动事实；**无法唯一确定 ⇒ 跳过 + 留诊断**（**不再靠 mtime** · `§12.4.1 ①`）。`--dry-run` 可**无副作用**预览 | 任务结束收尾；`--dry-run` 可安全预览将写入的内容。⚠️ **不支持 `--help`：任何调用都会尝试写回** —— **不要用它试探用法**（2026-09-30 实测误触发，issue `WRAPUP_HELP_HAS_SIDE_EFFECT`） |

## 1.5 维护层（AI-OS 基础设施 · 非普通任务上下文）

| 入口 | 是什么 | 什么时候用 |
|---|---|---|
| `maintenance-skills/health-check/` | 只读体检：扫描基础设施 → Finding/Severity/Infrastructure/Suggested Maintenance Skill/Evidence | 需要体检时；输出交 Human 裁决，不自动修 |
| `maintenance-skills/INDEX.md` | 维护能力发现入口（discovery surface） | 需要找/执行维护 Skill 时（如 knowledge-maintenance） |

## 2. 工具调用约定

- 允许串行与并行 tool 调用；并行建议单批不超过 80 并发（已验证安全值）。
- 任何时候只允许一个活跃 tool stream；前一工具完全结束后再启动下一个。
- Provider 侧错误（`invalid_request_error` 等）不影响 Agent 状态，处理方法：停止当前 stream，等待下一条用户消息。
- Framework 侧错误（`insufficient_tool_messages` 等）属框架层，停止、不 replay。
- 超时允许一次有限重试；再次失败报告 timeout。
- 未知错误码分类为 unknown，不追溯映射到 tool lifecycle error。

## 3. 不要做的事

- 不要假设存在 v1 的 phantom "自动 Bootstrap Assembly"（已归档）；统一开工发现由真实工具 `tools/task_start.py` 承担（见工具表）。
- 不要用 `--help` 试探未知工具：至少 `tools/wrapup_sync.py` **不支持 `--help`，任何调用都会执行持久化写回**（issue `WRAPUP_HELP_HAS_SIDE_EFFECT`，open/low，2026-09-30 实测）。查用法读本文件。
- 不要为"让 AI-OS 看起来完整"而新建 Runtime / Telemetry / State Enforcer——动机锁。
- 不要把 provider error 当成 Agent 状态损坏（架构层解耦）。

## 4. 优先级

本文件 < `AGENTS.md`（宪法）< 当前任务指令。它是工具层约定，不是治理栈。

## 5. 故障语义（免疫器官，2026-08-05 从 BOOT.md 找回）

> 故障隔离判据（源自 BOOT.md）。判据用途：**这些错误是运行层故障，不是知识库/宪法损坏**——看到它们不要启动"查 domains/改宪法"的修复路径，那是错误归因。

**Runtime Layer Failure（默认解释为运行层故障，不代表 Brain/Constitution/Memory 损坏）**：
- `insufficient tool messages`
- `invalid_request_error`
- `stream disconnect`
- `metadata fallback`

**对应行动**：
- 停止当前 stream，等待下一条用户消息（provider 侧）；框架侧停止、不 replay。
- **禁止**因此怀疑 domains/AGENTS.md/MEMORY 损坏而去重写它们（错误归因——WFI-005 C7/C8 判据："工具限制被误判为架构缺陷"是可复用失败模式）。
- 超时允许一次有限重试；再次失败报告 timeout。
- 未知错误码分类为 unknown，不追溯映射。

## 6. 决策质量（WFI-005 三级诊断，2026-08-05 从 archive 找回）

> 第一纪元 WFI-005 三级决策模型（验证报告 WFI-005-VAL 2026-06-15：10 个真实 Runtime/Tool/Sandbox 案例回放，**省步骤 43%、0 误判、0 漏诊**）。遇错时的诊断顺序——**从最可能的层开始，不跳过、不跳到最严重的**：

**Level 1 · Permission First（权限优先）**：
- 信号：`Access Denied` / 权限错误
- 动作：优先 escalate（require_escalated / 换权限路径），不要先查 ACL/怀疑数据损坏
- C1/C2 实证：原 4-7 步 → 2 步（escalate 即成功）

**Level 2 · Tool Boundary（工具边界）**：
- 信号：`insufficient_tool_messages` / 工具/沙箱/Provider 异常 / 并发限制
- 动作：检查 sandbox/shell/工具/Provider 限制——**不要**直接怀疑架构缺陷/知识损坏
- C7/C8 实证：并发读取触发 insufficient_tool_messages 被误判为 Brain corruption；并行工具调用异常被误判为架构缺陷（实测 168 次调用零异常=并行不是根因）→ **"工具限制被误判为架构缺陷"是本项目最贵的误判模式**

**Level 3 · Systemic（系统性）**：
- 信号：上述两层排除后仍异常
- 动作：才进入系统层（架构/数据/知识库）排查

**纪律**：三级是**顺序闸门**不是菜单——Level 1 信号没排除前不进 Level 2，Level 2 没排除前不进 Level 3。误判的代价 > 漏诊的代价（误判=错误归因+污染诊断路径）。
