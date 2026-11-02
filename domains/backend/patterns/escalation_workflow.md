---
rule_id: escalation_workflow
title: 权限/Sandbox 相关错误时请求提权而非绕过
trigger:
  - Access Denied
  - Permission Denied
  - sandbox_block
  - 拒绝访问
  - write restriction
  - file lock
  - approval required
  - escalation approved but failed
  - approval granted but write denied
condition: 错误为权限或 sandbox 限制类问题。由 environment_first.md Level 1 前置决策路由至此
action:
  do:
    - 判断权限类型（sandbox / ACL / path）
    - 判断 sandbox 限制类型（network / filesystem / GUI）
    - 判断是否需要用户授权
    - 优先请求 escalate（require_escalated）
    - 若 escalate 不可用，提供 fallback 方案（先写可写目录再人工移动）
    - |
      若 escalate 已批准但操作仍失败:
          → 执行 Escalation Failure Diagnosis:
            1. 检查是否为 Sandbox Tracking Lock
               - 文件创建后被 sandbox 追踪锁定 → 后续同文件操作被拒绝
               - 同文件跨 shell 调用写入也失败
               - 特征: 首次操作成功，后续被拒
               - 方案: 单次 shell 调用内完成全部写入（变量声明 → 写入 → 验证）
            2. 检查是否为 Prefix Rule 非持久化
               - prefix_rule 批准后未跨 tool call 持久生效
               - 特征: 批准后同操作仍被拒绝
               - 方案: 每次写入单独 escalate，而非依赖规则
            3. 检查是否为 Component Runtime Permission Gap
               - 组件（如 Telemetry Writer）初始化成功但运行权限不足
               - 特征: 加载/初始化 OK，写入失败
               - 方案: 组件本身无 escalate 机制 → 记录 OBS，等待架构修复
            4. 检查是否为 Environment Constraint
               - 目标路径本身不可写（如只读目录、Registry 保护）
               - 特征: 所有写入方法均失败
               - 方案: 写入可写路径后人工移动
    - 禁止将 escalate 后失败立即升级为: Architecture Issue / Workflow Issue / Definition Drift
    - 输出说明原因
  dont:
    - silent retry
    - 循环尝试不同绕过方法（COM → echo → powershell）
    - 自动 fallback 到非预期路径
    - 为权限问题 debug governance 或 reasoning
    - 在 escalate 前执行 Tool Boundary Analysis
    - escalate 失败后立即怀疑架构/工作流/定义漂移
    - 对 escalate 后失败进行连续 retry
keywords:
  - escalate
  - sandbox
  - permission
  - 提权
  - 拒绝访问
  - escalation approved
  - file lock
  - sandbox tracking lock
  - prefix rule
  - EFP-001
  - require_escalated
  - fallback
knowledge_position: Cluster
knowledge_cluster: FC-002 Escalation
epistemology_tag: PATTERN
confidence: HIGH
related_rules:
  - environment_first.md (Level 1 — Permission First 决策路由)
  - tool_boundary.md (Level 2 — escalate 后分析 + EFP-001 分类)
  - WFI-004 (本规则 — Escalation Failure Pattern)
---

> 格式修复：原文正文被压成一整段（旧 import 造成的可读性问题），本次只重排结构与标题，⛔ 未改语义。

# Escalation Workflow（权限失败：先提权，不绕过）

- 层级：Learned Rule (Tools)
- 版本：v1.2（WFI-004 — Escalation Failure Pattern）
- 来源：Desktop 写入流程验证 / EFP-001 Audit

## 前置决策

本规则由 `environment_first.md` 的 **Level 1 Permission First** 决策路由触发。
请不要直接从此规则开始——应先通过 `environment_first.md` 的错误分类判断。

## 规则

遇到失败时：

1. 判断是否是权限问题（sandbox? ACL? path?）
2. 判断是否是 sandbox 限制（network? filesystem? GUI?）
3. 判断是否需要用户授权
4. **优先请求 escalate（`require_escalated`）**
5. 若 escalate 不可用 → fallback（先写可写目录再人工移动）
6. 若 escalate 已批准但操作仍失败 → **EFP-001 诊断**（见下节）
7. 禁止 silent retry

## EFP-001: Escalation Failure Pattern

### 核心原则

**Escalate 成功 ≠ 操作一定成功。**
escalate 只是绕过了 sandbox 的初始权限检查，不解除：

- 文件追踪锁（sandbox 对已创建文件的追踪）
- Prefix Rule 的 session 边界（批准不跨 tool call 持久）
- 组件本身的运行时权限（初始化成功 ≠ 写入权限）

### 诊断流程

```text
escalate 已批准 + 操作仍失败
    │
    ▼
1. Sandbox Tracking Lock 检查
   - 首次写入成功？后续同文件被拒？
   - 是 → 单 shell 调用内完成写入
   - 否 → 继续
    │
    ▼
2. Prefix Rule 非持久化检查
   - prefix_rule 批准后仍被拒？
   - 是 → 每次写入单独 escalate
   - 否 → 继续
    │
    ▼
3. Component Runtime Gap 检查
   - 组件加载/初始化通过但写入失败？
   - 是 → 记录 OBS，等待架构修复
   - 否 → 继续
    │
    ▼
4. Environment Constraint 检查
   - 目标路径只读/受保护？
   - 是 → 写入可写路径 + 人工移动
   - 否 → 升级为 Level 2 Analysis
```

### 单次调用完成写入策略

当确认为 Sandbox Tracking Lock 时：

```powershell
# 在单次 shell 调用内完成全部操作：
$content = "..."
[System.IO.File]::WriteAllText('target.md', $content, [System.Text.Encoding]::UTF8)
Test-Path 'target.md'
```

### 禁止

- escalate 失败后立即升级为 Architecture / Workflow / Definition Issue
- 对 escalate 后失败进行连续 retry
- 循环尝试不同 API（WriteAllText → Add-Content → Out-File）

## 核心区别

**权限问题 ≠ logic error。** 不要为权限问题 debug governance 或 reasoning；先按上面的路径提权 / 诊断，再谈其他。
