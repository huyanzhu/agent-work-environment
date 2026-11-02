# task_cards/ — 工作记忆（任务卡 + 项目卡）

> 卡 = **快照**（Goal / Status / Next Action，永远短）· 日志 = **流水**（同级同名 `.log`，由脚本追加）。
> `Event Log` 已外置：卡内只留一行指针，⛔ 不把流水写回卡里（卡变长会让运行时读尾部失效）。

## 是什么

把「当前在做什么、下一步做什么、做过什么决策」写在卡上，让下一轮或另一个会话能恢复上下文，
不必重新支付已支付的成本。**卡是 disposable 的工作记忆**，不是永久知识（知识沉淀到 `capabilities/` / `domains/` / `memory/PITFALLS.md`）。

## 目录结构

```text
task_cards/
├── README.md                    ← 本文件
├── GOAL-INPUT-CONTRACT.md       ← Goal / Next Action 的描述规范
├── NEEDS-VOCAB.md               ← 检索用的词表（能力 = 8 个领域）
├── _TASK_CARD_template.v4.md    ← 当前模板（新建卡默认用它）
├── _TASK_CARD_template.v2/v3.md ← 旧版模板（迁移用，新卡不用）
├── memory/                      ← 全局记忆（发布物只带模板，真实内容不进版本控制）
├── active/                      ← 进行中的卡
│   └── <项目>/                  ← 项目文件夹（运行时创建）
│       ├── PROJECT.md           ← 项目级工作记忆（跨任务复用更新）
│       └── TASK-YYYYMMDD-001.md ← 任务卡（+ 同级 .log）
└── archive/                     ← 已关闭的卡
```

## 怎么做

| 时机 | 动作 |
|---|---|
| **任务开始** | `python tools/task_card.py create "<标题>" --project=<项目名>`（⛔ 不带 `--project` 会落到 `active/` 顶层，脚本会警告） |
| **开工先选能力** | 调一次 `auto_capability`（`what` 一句）⇒ 8 个领域词表；选一个记录：`python tools/task_card.py capability <项目>/<TASK-ID> --name domain-xxx --why "<一句>"`（`none` = 明确声明不用） |
| **占用 / 释放** | `claim <项目>/<TASK-ID>`（Planning/Parked → Executing）；结束 `release <项目>/<TASK-ID> --state=Parked\|Completed`（必须显式） |
| **卡住** | 更新 `Current Status`：`State` / `Current Step` / `Next Action` / `Resume Point` |
| **收口** | 填 `Outcome`（含「投递采用」）· `Confidence` · `Knowledge Used` · `Deliverables` · `Close Checklist` |
| **关闭** | 完成且用户确认后 `python tools/task_card.py archive <项目>/<TASK-ID> --confirm` |
| **项目级** | 项目文件夹内维护 `PROJECT.md`（产出位置 / 已核实事实 / 待办），跨任务复用 |
| **写回** | 卡的流水由 Stop hook（`tools/wrapup_sync.py`）自动追加；手工调用只用于补写 |
| **自检** | `python tools/probes/_card_description_lint.py`（Goal / Next Action）；`python tools/task_card.py states`（State 值域） |

## 规范

### `Goal`

1. 表达**结果**，不只是动作（判据：说完之后世界有什么不同）
2. 保留足以区分任务的对象与领域；技术专名保留原始写法
3. ⛔ 不堆关键词 / 实现步骤 / 文件路径 / 测试命令
4. 用宿主的工作语言；⛔ 不要求英文版
5. 方向改变后旧 Goal 不得继续主导
6. **≤ 180 字符**（`task_start.py` 只读前 180）；⛔ 不含元信息（施工依据 / 盘符路径）

### `Next Action`

1. **N1** 含「动作词 + 受控工作对象词」
2. **N2** 不以非施工词开头（等待 / 验收 / 裁定 / 归档 / 确认后）
3. **N3 ≤ 120 字符**
4. **N4** 等待型写「等待 <谁> <什么>；到位后 <动作 + 对象>」

受控工作对象词表（12 类）：`前端` · `后端` · `数据库` · `设计` · `测试` · `部署` · `检索` · `运行时` · `技能` · `记忆` · `文档` · `审核`。
未覆盖的真实对象 ⇒ 先登记再使用（见 `GOAL-INPUT-CONTRACT.md`）。

## 纪律

- **不预设计字段（Freeze）**：⛔ 不新增字段；字段写法是写作要求，不是新字段
- ⛔ 不批量改写历史卡：新写法从新卡起
- **一次一张卡**：同一会话同一时刻只占一张 `Executing` 卡（多实例协作需显式协调）
- 卡变长就外置：流水进 `.log`，卡只留指针

## 已知限制

- `task_start.py` 扫描 `active/` 下所有 `.md`（仅排除 `_` 开头）⇒ 项目级 `README.md` / `PROJECT.md` 可能被当作"任务卡"列出（噪点；`task-start-hook.py` 已用严格正则规避）
- 旧模板（v2/v3）保留仅用于迁移；v4 卡给 `--stage` 会被拒绝
