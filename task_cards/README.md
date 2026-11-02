# task_cards/ — 工作记忆（任务卡 + 项目卡）

> 🔴 **2026-10-28 变更：`Event Log` 已外置** —— 占用 / 收尾留痕写在本卡**同级同名 `.log`**（如 `TASK-20261023-001.log`）。
> 卡 = **快照**（Goal / Status / Next Action · 永远短）· 日志 = **流水**（`.log`）。
> 原因（P24 实测）：日志留在卡里会让卡越来越长，Runtime 的"读尾部"判据被挤出窗口 ⇒
> 占用 / 焦点卡 / stage4 / R3 **全部静默失效**。卡内只保留一行指针，⛔ 不再写表格。

## 怎么做

| 时机 | 动作 |
|---|---|
| **任务开始** | `python tools/task_card.py create "<标题>" --project=<项目名>`（🔴 **必须带 `--project`**；不带会落 `active/` **顶层** ⇒ 无法按项目归档 / 检索，脚本会打印醒目警告）。也可复制 `_TASK_CARD_template.md` 到 `active/<项目>/`，命名 `TASK-YYYYMMDD-001.md`，填 `Header` ＋ `Goal`（**宿主想达成什么结果**）＋ `Next Action`（**当前在对什么对象做什么**） |
| **任务进行** | 更新 `Current Status`：`State`（状态）· `Current Step`（此刻在做什么）· `Next Action`（下一步：动作 + 对象）· `Resume Point`（中断后从哪继续）；并追加 `Event Log`。<br>⚠️ **如实性要求**（2026-10-12）：① `State` 必须落在 `_TASK_CARD_template.md` 的值域内，且**值的首个 token 就是值本身**（注释归 `Current Step` / `Notes` —— ⛔ 不写 `Active（…）` / `Waiting` 这类值域外写法）；② `Next Action` 只写**当前**动作 + 对象，⛔ 不写已完成项（见 `GOAL-INPUT-CONTRACT.md` **N6**）。<br>这两条的理由是**卡自身的如实记录**（⛔ 不是"为某个消费者定制字段"）；`Runtime` 能从卡里读出什么属**它的读取能力**，见 `p0/RESPONSIBILITY-BOUNDARIES.md §1` |
| **占用 / 释放** | 想用一张卡 ⇒ `python tools/task_card.py claim <TASK-ID>`（`Planning` / `Parked` → `Executing`）；本轮结束 ⇒ `release <TASK-ID> --state=Parked\|Completed`（**必须显式指定**）。⛔ 脚本/Runtime **不自动改状态** · **停止 ≠ 任务结束** · `Completed` ≠ 已归档。只读校验：`python tools/task_card.py states`。🔴 2026-10-16 起：`claim` / `release` 成功后会**自动向卡内 `Event Log` 追加留痕（含 session id）** ⇒「谁在占用」可跨会话追溯（此前只活在 Runtime 内存里）。🔴 **只能占用「未被占用」的卡** —— 被别的对话占用的卡对你 = **不可用**（占用是**排他**的：它只属于占用者，⛔ 不是"谁都能用"）；Runtime 只在**新进程启动时**回收上个进程的遗留占用（`--reason=startup-recover`）。 |
| **任务收口** | 填 `Outcome`（结果）· `Confidence`（置信 + 理由）· `Knowledge Used`（用到的材料）· `Deliverables`（产出）· `Close Checklist` |
| **任务关闭** | 仅当**已完成且已获用户确认**后归档：`python tools/task_card.py archive TASK-ID --confirm`；阶段/项目未完则保持 `active` |
| **项目级** | 项目文件夹内建 `PROJECT.md`（进度 / 技术债 / 下一步），Phase 间复用更新 |
| **收尾写回** | 卡的 `Event Log` **由 Stop hook 自动追加**（`tools/wrapup_sync.py`）；手工调用仅用于补写 |
| **写完自检** | `python tools/probes/_card_description_lint.py` —— 机械检查 `Goal` 与 `Next Action` 是否符合规范 |

**两条关键字段的一句话记法**：

- `Goal` —— **宿主想达成什么结果**
- `Next Action` —— **当前在对什么对象做什么**（Runtime 靠这条找能力，必须写成「动作 + 工作对象」）

完整规范见 §规范。

## 是什么

**Agent 的工作记忆**：把「当前在做什么、下一步做什么、做过什么决策」写在**卡**上，
让下一轮、或另一个会话，能恢复上下文，不必**重新支付已支付的成本**。

- **第一形态**：本目录是 v1 实现的原样复刻（多卡目录 + `active/` `archive/` + 手工建卡/归档），
  ⛔ 不是新设计；通过真实使用观察后再重塑（第一形态 ≠ 终局）。
- **替代关系**：`CURRENT_GOAL.md` 已删除（被 task_cards 替代）；`resume.py` 已删除
  （入口职责由 `ONBOARD.md` 与 `tools/task_card.py` 承接）。
- **层级**：
  - `active/` — 进行中的卡。支持**项目文件夹**（`<项目>/` = `PROJECT.md` 项目级工作记忆
    ＋ 各 Phase 任务卡），也支持平铺单卡。
  - `active/demo-project/` — **总项目入口**（`README.md` + `HANDOFF.md` + 三子项目），
    **只放入口文档、不含卡**。
  - `archive/` — 已关闭的卡。
  - **`memory/`** — ★ **全局记忆**（跨工作共享，⛔ 不是知识库、⛔ 不存密钥值）：
    `INVENTORY.md`（**我有什么**：项目/产物/文件 + 位置 + 工作记忆在哪）、
    `ENV.md`（**我能用什么**：模型/API/账号/代理/权限/路径/工具版本）、
    `PITFALLS.md`（**我踩过什么**：会再咬人的坑 + 触发条件 + 处置）。
    写入时点：**卡被释放后由 R3（工作后 runtime）维护**；开工由 R1 读取/探测（R1/R3 尚未实现，当前 Agent 手维护）。
    架构与裁定见 `active/AI-OS-Adaptation/ARCHITECTURE-ALIGNMENT-2026-10-27.md`。

```text
task_cards/
├── README.md                 ← 本文件
├── GOAL-INPUT-CONTRACT.md    ← 描述规范（Goal + Next Action）
├── _TASK_CARD_template.md    ← 卡片模板
├── NEEDS-VOCAB.md            ← 「我需要什么」能力类型词表（三维 · 试用中）
├── memory/                   ← 全局记忆（INVENTORY / ENV / PITFALLS）
├── active/
│   ├── demo-project/             ← 总项目入口（README + HANDOFF + 子项目；不含卡）
│   ├── <项目>/               ← 项目文件夹（运行时创建）
│   │   ├── PROJECT.md        ← 项目级工作记忆（跨 Phase 复用更新）
│   │   └── TASK-YYYYMMDD-001.md
│   └── TASK-YYYYMMDD-001.md  ← 平铺单卡（任务级）
└── archive/
    └── TASK-YYYYMMDD-001.md
```

**观察点**（随真实使用记录，⛔ 不预先设计）：Agent 是否自然建卡/读卡/更新卡/归档 · 在什么时机使用
（开工/中途/卡住/收口）· 哪些字段被重复读取、哪些没人看 · 是否真的减少了"重新支付已支付成本" ·
是否与其它能力组合（`experience_push` / `wrapup_sync` / `SUCCESS_LOG`）· 项目级与任务级工作记忆是否自发形成并被后续 Phase 消费。

## 规范

### `Goal` 规范

1. 表达**结果**，不只是动作
2. 保留**足以区分任务的对象与领域**；技术专名保留**原始写法**
3. ⛔ 不把关键词 / 实现步骤 / 文件路径 / 测试命令堆进 `Goal`
4. 用**宿主的工作语言**写；⛔ 不要求手工维护英文版本
5. 方向改变后，**旧 `Goal` 不得继续主导**
6. 长度 **≤ 180 字符**（`tools/task_start.py` 只读前 180）· ⛔ **不含元信息**
   （施工依据 / 恢复入口 / 基线 / 盘符路径等 —— 它们归 `Knowledge Used` / `Resume Point`）

### `Next Action` 规范

1. **N1** 含「**动作词 + 受控工作对象词**」
2. **N2** 不以**非施工词**开头（等待 / 验收 / 裁定 / 观察期 / 归档 / 确认后 / 待）
3. **N3** 长度 **≤ 120 字符**
4. **N4** 等待型必须自带"到位后做什么"：`等待 <谁> <什么>；到位后 <动作 + 对象>`

正例：`按 REBUILD_PLAN §7 推进前端（S6）` ｜ 反例：`用户验收（试用系统、查看报告）`

**受控工作对象词表**（12 类）：
`前端` · `后端` · `数据库` · `设计` · `测试` · `部署` · `检索` · `运行时` · `技能` · `记忆` · `文档` · `审核`
—— 遇到词表未覆盖的真实对象（如 `评估层` / `Governor` / `可观测性`）⇒ **先登记，再使用**。

> 判据、正反例、实测依据与扩展登记规则：**`GOAL-INPUT-CONTRACT.md`**

### 纪律

- **不预设计字段（Freeze）**：⛔ 不新增字段。上面的字段写法是**写作要求**，⛔ 不是新字段。
- **先不新造工具**：使用方式 = 手工复制模板 + 移入/移出目录；观察后如需才补。
- **不围绕本目录建系统**：它是能力之一（观察样本），不是中心。
- ⛔ **不批量改写历史卡**：`active/` 下的 58 张卡中有 46 张是缺 `Goal` 的旧式卡；
  新写法**从新卡与新字段更新起**。
- **池 / 键 / 候选口径的问题独立记录**，⛔ 不混进"卡写得对不对"。

### 已知缺陷

`tools/task_start.py` 的 `task_cards()` 扫描 `active/` 下**所有** `.md`（仅排除 `_` 开头）
⇒ 会把项目级 `README.md` / `PROJECT.md` 当作"任务卡"列出（噪点）。
`tools/task-start-hook.py` 已用严格正则规避；修 `task_start.py` 属 P0「职责收敛」范围。
