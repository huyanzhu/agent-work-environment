# TASK_CARD

> Working Memory — disposable after task close. Not permanent knowledge.
> If information belongs elsewhere, store only the reference here.

---

## Header

```
Task ID:     TASK-YYYYMMDD-001
Type:        Course Project | Bug Fix | Architecture | Refactor | Research | Pattern Review | Maintenance | Experiment
Priority:    Critical | High | Medium | Low
Owner:       <role or instance>
Manager:     <coordinating instance>
Reviewer:    <review instance>
Created:     YYYY-MM-DD HH:mm
Last Updated: YYYY-MM-DD HH:mm
Updated By:  System | Worker | Manager | Review | Human
```

---

## Goal

One sentence. What is the single deliverable this task exists to produce?

---

## Current Status

```
State:         Created | Planning | Executing | Parked | Blocked | Waiting_Human | Reviewing | Completed | Archived
Resume Policy: auto | manual
Current Step:  What is happening right now?
Next Action:   What is the next concrete action?
Resume Point:  Where to pick up if interrupted?
Estimated Finish: YYYY-MM-DD / TBD
```

> 🔴 **`State` 不只是描述，它是「占用声明」**（Human 2026-10-12 裁定）
> 想用一张卡 ⇒ 显式占用（`python tools/task_card.py claim <TASK-ID>`，`Planning`/`Parked` → `Executing`）；
> 本轮结束 ⇒ 显式释放（`release <TASK-ID> --state=Parked|Completed`）。
> ⛔ Runtime/脚本**绝不自动改状态** —— `release` 不推断完成与否；**停止 ≠ 任务结束**。
> `Parked` = 暂停但未完成、可恢复；`Planning` = 尚在规划未开始；`Waiting_Human` = 等的是**人**。
> 校验（只读）：`python tools/task_card.py states`

> **写法规范**（`task_cards/GOAL-INPUT-CONTRACT.md`）
> Runtime 只能从**这一条**取得"当前在对什么对象做什么"⇒ 写成「**动作 + 工作对象**」：
> ① 含**动作词 + 受控工作对象词**（前端 / 后端 / 数据库 / 设计 / 测试 / 部署 / 检索 / 运行时 / 技能 / 记忆 / 文档 / 审核）
> ② ⛔ 不以非施工词开头（等待 / 验收 / 裁定 / 观察期 / 归档 / 确认后 / 待）
> ③ ≤120 字符 ｜ ④ 等待型：`等待 <谁> <什么>；到位后 <动作 + 对象>`
> 正例 `按 REBUILD_PLAN §7 推进前端（S6）` ｜ 反例 `用户验收（试用系统、查看报告）`
> ⚠️ 本说明写在**代码块之外** —— 避免被当作 `Next Action:` 的缩进续行并入（`task_start._next_action()` 会并入续行）

---

## 能力（三处必填 · 从 capabilities/ 选）

> 每处都要作答（`none` 合法，但必须给一句能对上本次改动的理由）；记录走脚本写 `.log`，⛔ 不写本节。
> 开工先调一次 `auto_capability`（`what` 写一句在做什么）⇒ 它返回 8 个领域词表，选一个作为本次任务的能力。
> 需要对照时看 `capabilities/INDEX.md`（8 个域能力 · 一域一文件）；选与你这次改动**同域**的那个。

- [ ] **开工**（claim 后、动手前）→ `python tools/task_card.py capability <ID> --stage start --name <能力|none> --why "<一句>"`
- [ ] **实现**（首次实质改动后）→ `... --stage impl ...`（同一能力贯穿可写「复用」）
- [ ] **收尾**（交付前）→ `... --stage close ...`
- [ ] 校验：`python tools/probes/_capability_choice_lint.py <本卡路径> --stage close` ⇒ PASS

---

## Outcome

```
Unknown | Success | Partial | Abandoned | Cancelled
```

Brief summary of what happened, what was delivered, and any notable deviations.

---

## Confidence

```
High | Medium | Low
Reason: Why this confidence level?
```

---

## Open Questions

Questions that need answers before the task can progress. If Blocked, describe exactly what blocks progress.

---

## Blocked On

```
Human | Decision | External | API | Tool | Dependency
Reason: Why is this blocked?
```

---

## Decision Snapshot

Key decisions made during this task. Reference ADs by ID when applicable.

---

## Knowledge Used

```
Patterns:   PAT-xxx / PAT-xxx
Documents:  TOOL_RUNTIME / ARCHITECTURE_DECISIONS / ...
```

---

## Deliverables

```
Files Created / Modified:

Patterns Created:

Registry Updates:
```

---

## Event Log — 已外置

> 占用 / 收尾留痕在**同级同名文件** `<TASK-ID>.log`（由 `tools/task_card.py` 与 `tools/wrapup_sync.py` 维护）。
> 卡 = **快照**（Goal / Status / Next Action · 永远短）· 日志 = **流水**（`.log`）。
> 2026-10-28 Human 裁定：日志搬到卡外 —— 卡内保留此项指针即可，⛔ 不再写表格。

---

## Notes

Capture observations during the task. Review before close — anything worth a pattern?

---

## Close Checklist

- [ ] Deliverables completed
- [ ] Pattern extracted (if any)
- [ ] Telemetry written
- [ ] Task Card cleaned (open questions resolved, blocked cleared, temp notes removed)
- [ ] Task Card archived
- [ ] 能力三点见上方『能力』节（开工 / 实现 / 收尾 · 记录写 `.log`）

---

> Rule: If information belongs elsewhere, store only the reference here.
> Task Card is Working Memory, not permanent knowledge.

---

## 卡写法规范（⛔ 不参与读取 · 勿并入 Goal 节）

> 依据 `task_cards/GOAL-INPUT-CONTRACT.md`。⚠️ 本节放在末尾是**刻意的**：
> `tools/task_start.py` 会把 `## Goal` **整节**读到 180 字符 —— 规范若写在 Goal 节内，
> 会把规则文本读成 Goal 尾部，并让 `_card_description_lint` 报 G2/G3 假红（2026-11-01 实测多张新卡 450–510 字符）。
>
> **Goal**：
> ① 表达**结果**，不只是动作（判据：能否说出"做完之后世界有什么不同"）
> ② 保留**足以区分任务的对象与领域**；技术专名保留**原始写法**（`Next.js` · `Supabase RLS` · 子系统名）
> ③ ⛔ 不堆关键词 / 实现步骤 / 文件路径 / 测试命令（它们归 `Current Step` / `Next Action` / `Knowledge Used` / `Deliverables`）
> ④ 用**宿主的工作语言**写；⛔ 不要求手工维护英文版本
> ⑤ 方向改变后**旧 Goal 不得继续主导**
> ⑥ **≤180 字符**（`task_start.py` 只读前 180）· ⛔ 不含元信息（施工依据 / 恢复入口 / 基线 / 路径）
>
> **Next Action**：动作 + 明确工作对象（N1/N2 lint 口径）；⛔ 不写「等/看/确认」这类无对象动作。

---

## Constraints

**Size Budget:** Task Card is optimized for active work. Core information (Goal, Status, Next Action, Blocked, Confidence) should remain scannable in one screenful. Historical detail belongs in Telemetry or archived artifacts — not in the active Task Card.

**One Active:** Each Worker may have only one active Executing Task Card at a time unless explicitly coordinated by the Manager.

**Freeze:** No new fields before 20 real tasks. Changes allowed only if: a field is consistently unused, a missing field blocks work, or multi-instance collaboration exposes a structural gap.
