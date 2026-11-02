---
name: domain-backend
intro: 当要改代码 / 修 bug / 删冗余代码，或动并发 / 事务 / 迁移路径时 ⇒ 先立可复现基线，再划并发边界、留重放退路，用最窄检查证明，最后分级结论。
axis_domain: [后端]
axis_help: [实现, 调试, 验证]
axis_concern: [正确性, 可维护性]
keywords: [后端, 域能力, domain-backend, 并发, 事务, 幂等, 迁移]
domain: 后端
# 域能力（一个领域一个文件 · 片不含 class）
parts:
  - id: domain-backend#baseline
    domain: 后端
    label: 先立基线
    one_line: 先造最小确定性复现或读现有检查读数，再动手；一次只改一个变量
    from: [debug-protocol#repro, senior-engineer#review, self-verification#checks]
  - id: domain-backend#red-first
    domain: 后端
    label: 先红后绿
    one_line: 先写一个会失败的测试并亲眼看它按预期理由失败，再写最小代码转绿
    from: [test-driven-development#red, test-driven-development#green, test-driven-development#gate]
  - id: domain-backend#tx-scope
    domain: 后端
    label: 划并发边界
    one_line: 先划事务边界与锁范围，写明跨边界一致性策略和读旧值的可接受窗口
    from: [new]
  - id: domain-backend#replay-safe
    domain: 后端
    label: 留重放退路
    one_line: 重试前先证明幂等，改语义先双写兼容读并留回滚开关
    from: [new]
  - id: domain-backend#reconcile
    domain: 后端
    label: 权威层对账
    one_line: 界面与行为不符时读权威数据层，还原写出它的路径，别对照派生物猜
    from: [debug-protocol#reconcile, debug-protocol#realpath]
  - id: domain-backend#narrow-check
    domain: 后端
    label: 最窄证据
    one_line: 每个行为变更选最窄会失败的检查；并发用压测或交错证明，未复现标未验证
    from: [pre_push_evidence_gate#select, senior-engineer#blockers]
  - id: domain-backend#tradeoff
    domain: 后端
    label: 取舍与结论
    one_line: 先列 3 个取舍与各自反例，再直接给结论
    from: [senior-engineer#tradeoff]
  - id: domain-backend#proof-or-drop
    domain: 后端
    label: 证明或拒绝
    one_line: 每个候选先分消费者，再用调用点证据证明或明确拒绝，别凭感觉删
    from: [simplification_audit#context, simplification_audit#survey, simplification_audit#prove]
  - id: domain-backend#verdict
    domain: 后端
    label: 分级收口
    one_line: 一句结论 + Critical/Worth/Watch-outs 分级；勾完清单才算完成
    from: [senior-engineer#verdict, debug-protocol#report, simplification_audit#report, test-driven-development#checklist]
merge_of:
  - debug-protocol
  - pre_push_evidence_gate
  - self-verification
  - senior-engineer
  - simplification_audit
  - test-driven-development
---

# 后端 能力（域能力）

> 由 6 个旧能力合并抽象而成（旧文件在 `capabilities/_archive/`）。
> 一个领域一个文件；片不含阶段字段（Human 口径：领域才是分类轴）。
> 融合「并发与事务安全」：新增 2 片（`#tx-scope` / `#replay-safe`）+ 1 条变体并入 `#narrow-check`；
> 新增片 `from: [new]` = 无旧片可追（来源：外部 skill「并发与事务安全」+ 本次归纳）。

## 什么时候用

当要改代码 / 修 bug / 删冗余代码，或动并发 / 事务 / 迁移路径时 ⇒ 先立可复现基线，再划并发边界、留重放退路，用最窄检查证明，最后分级结论。

## 做法

1. **先立基线** —— 先造最小确定性复现或读现有检查读数，再动手；一次只改一个变量
   > 出处：`debug-protocol#repro` · `senior-engineer#review` · `self-verification#checks`
2. **先红后绿** —— 先写一个会失败的测试并亲眼看它按预期理由失败，再写最小代码转绿
   > 出处：`test-driven-development#red` · `test-driven-development#green` · `test-driven-development#gate`
3. **划并发边界** —— 先划事务边界与锁范围，写明跨边界一致性策略和读旧值的可接受窗口；一个事务只做一件事，跨服务/跨库写明最终一致或补偿、别假装原子；同一行乐观锁（版本号）优先于悲观锁，热点行写明锁等待与超时；读写分离写明读到旧值到哪一步还算数
   > 出处：新建 · 外部 skill「并发与事务安全」+ 本次归纳（`from: [new]`，无旧片可追）
4. **留重放退路** —— 重试 / 重复提交前先证明幂等（唯一键 · 状态机 · 去重表）；改字段或改语义先双写 + 兼容读再切换，并留回滚开关；没证明幂等就上重试 = 把重复副作用当偶发
   > 出处：新建 · 外部 skill「并发与事务安全」+ 本次归纳（`from: [new]`，无旧片可追）
5. **权威层对账** —— 界面与行为不符时读权威数据层，还原写出它的路径，别对照派生物猜
   > 出处：`debug-protocol#reconcile` · `debug-protocol#realpath`
6. **最窄证据** —— 每个行为变更选最窄会失败的检查证明，不反射跑全量；并发缺陷用可复现压测或交错证明，跑不出来就如实标「未验证」——未复现 ≠ 已验证
   > 出处：`pre_push_evidence_gate#select` · `senior-engineer#blockers` · 并入「并发取证」变体（无旧片）
7. **取舍与结论** —— 先列 3 个取舍与各自反例，再直接给结论
   > 出处：`senior-engineer#tradeoff`
8. **证明或拒绝** —— 每个候选先分消费者，再用调用点证据证明或明确拒绝，别凭感觉删
   > 出处：`simplification_audit#context` · `simplification_audit#survey` · `simplification_audit#prove`
9. **分级收口** —— 一句结论 + Critical / Worth / Watch-outs 分级；逐条勾完检查清单才算完成
   > 出处：`senior-engineer#verdict` · `debug-protocol#report` · `simplification_audit#report` · `test-driven-development#checklist`

## 片的覆盖来源

| 新片 | 抽象自 |
|---|---|
| `domain-backend#baseline` | `debug-protocol#repro` · `senior-engineer#review` · `self-verification#checks` |
| `domain-backend#red-first` | `test-driven-development#red` · `test-driven-development#green` · `test-driven-development#gate` |
| `domain-backend#tx-scope` | `new`（外部 skill「并发与事务安全」+ 本次归纳；无旧片） |
| `domain-backend#replay-safe` | `new`（同上；无旧片） |
| `domain-backend#reconcile` | `debug-protocol#reconcile` · `debug-protocol#realpath` |
| `domain-backend#narrow-check` | `pre_push_evidence_gate#select` · `senior-engineer#blockers` · 并入「并发取证」变体 |
| `domain-backend#tradeoff` | `senior-engineer#tradeoff` |
| `domain-backend#proof-or-drop` | `simplification_audit#context` · `simplification_audit#survey` · `simplification_audit#prove` |
| `domain-backend#verdict` | `senior-engineer#verdict` · `debug-protocol#report` · `simplification_audit#report` · `test-driven-development#checklist` |
