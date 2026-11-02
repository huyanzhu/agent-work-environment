# METHOD — AI-OS 怎么推进工作

> 本文只回答"具体怎么推进"：一个任务从发现到收尾，每一步落在哪个文件、哪条命令上。
> 每条做法都对得上本仓的真实行为；对不上的写进 §七，不写成方法。

## 工作链

```text
发现 → 建卡 → 取证 → 写回 → 验证权外置 → 维护
```

六步不是流程表演：每步都有一个**落点**（文件 / 命令 / 判据）。落不了点的步骤不做。

## 一、发现：先恢复，再按需找材料

- **两个时点、两种输入**（`tools/task_start.py`）：无任务描述 ⇒ 只做**任务恢复**（有哪些卡可能要继续）；带任务描述 ⇒ **材料发现**（这一步有哪些经验 / 能力值得考虑）。
- **恢复是自动的**：`SessionStart` hook 经 `tools/aios-hook.py`（`task_recovery`）注入**任务恢复提示**（目录 / 用法 / 动作，不列卡内容）⇒ 不靠 Agent 记得去读。
- **发现是限量的**：经验 ≤2 条、能力 ≤2 个；经验阈值 `KNOW_MIN_SCORE = 8.0`、能力需 ≥2 个 trigger 命中（`CAP_MIN_TRIGGER_HITS = 2`）。**命中不足就返回空**，不硬凑候选。这两个阈值是**首版值、无实测基线**，标未验证。
- **进行时按需拉取**：`auto_capability` 内联检索、候选随工具返回（≤3 条）。
- **反例**：开工时还不知道要做什么就硬送能力 ⇒ trigger 全命中 = 构造性噪声。**先有对象，再找材料。**

## 二、建卡：占卡即声明，卡只放快照

- **动手前先占卡**：`claim` 把 `Created|Planning|Parked` → `Executing`，占用**排他**；每轮结束 `release --state=Parked|Completed`（必须显式给值，脚本不推断完成）。抢别人的卡只能走 `takeover --reason`，两步都留痕。
- **State 有值域**：`Created | Planning | Executing | Parked | Blocked | Waiting_Human | Reviewing | Completed | Archived`。值域外写法由 `python tools/task_card.py states` 抓出。
- **卡 = 快照，流水 = `.log`**：占用 / 收尾留痕外置到同级 `.log`。卡变长会让 Runtime 的尾部读取窗口读不到关键字段 ⇒ 焦点卡 / 投递 / 唤醒**零报错失效**（见 [`PRINCIPLES.md`](PRINCIPLES.md) §三）。
- **字段是判据入口**：`Goal` ≤180 字符、只写结果；`Next Action` = 动作 + 受控工作对象、≤120 字符、只一条；`State` 首个 token 即值。完整规范在 `task_cards/GOAL-INPUT-CONTRACT.md`。
- **能力记一行**（v4 单字段卡）：
  ```bash
  python tools/task_card.py capability <项目>/<TASK-ID> --name domain-backend --why "主改动是并发边界，先立基线"
  ```
  理由 ≥8 字且不能空泛；能力名必须在 `capabilities/` 里（或 `none`）。校验：`python tools/probes/_capability_choice_lint.py`。

## 三、取证：先定"哪一格失败"，只采机械字段

- **先定位断点**：存在 → 被用 → 被读 → 有价值。报"没效果"前先答"它卡在哪一格"。
- **只用可复核读数**：探针事件、`read`/`write` 轨迹、是否进 diff；⛔ 不用 Agent 自报。
- **单批次 = 未验证**；**`CLEAN` ≠ 对**；方向性知识不能写成已验证。每条结论标 ✅/🟡/❌，并指回文件或命令。
- **不把"机制在跑"读成"生效"**：退出码 0 而账本停更的情况真实发生过 ⇒ 判据看**末条时间**，不看退出码。
- **判据本身也会被裁**：能力侧不以"打开率"判成败（打开是消费的必要条件，不是充分条件）。
- **规模按读数报**：8 个域能力（50 片）· 12 张经验族卡 · 111 条坑 · 143 个 tools 用例 · 208 项 runtime 自测 —— 是现状，不是里程碑。跨会话累积的探针**不能归因到单次验证**。

## 四、写回：完成标准先写死，事实由工具提

- **显式完成标准**：`Outcome` / `Confidence` / `Knowledge Used` / `Deliverables` + `Close Checklist`。
- **写回不猜卡**：`tools/wrapup_sync.py` 的选卡顺序 = 显式 `TASK-ID` ▸ 显式 `--project` ▸ git 改动事实（改动直指卡文件 ▸ 改动落在项目文件夹）；判不出就跳过并留诊断，**宁漏不错**。
- **只写机械事实**：账本追加"本次提交 + 改动文件"，`Outcome` / `footprint` / `influence` 一律留占位「待补」——**机制不给自己打分**。
- **幂等键 =（卡, commit）**；不新增状态文件——"AI-OS 可以有自己的 loop，不能有自己的账本"。
- **反例**：手工调写回在连续几次真实任务中 0 次被调用（两个不同执行者）⇒ 写回必须挂 Stop hook，不能写进纪律。
- **现状**：自动写回链 ✅（`tools/wrapup_sync.py` 挂在 Stop hook 上）；"Stop 每轮必触发"🟡。

## 五、验证权外置：验证者不能是被验证者

- **身份即约束**：用户 / 设计者 / 开发者 / 使用者 / 初步验收是同一个 Agent ⇒ **不自证**。
- **判据只用机械字段**：调用数、候选被打开次数、是否进 diff；不用"我采纳了"。
- **独立对照**：一个完全不用 AI-OS 的干净子代理也能交付 ⇒ 「AI-OS 是必要条件」拿到反向证据。这条质疑的不是机制，而是**必要性**。
- **小样本先由 Human 判几条**，标准稳了才放宽；可回源率 100% 是谈价值的前置，独特发现率 > 误报率要求 N≥20。
- **现状**：判据条款 ✅；"每条候选可回源"仍是要求而非读数 🟡。

## 六、维护：造它的人登记，维护清单对账

- **四件各管一段**（`task_cards/memory/`）：`INVENTORY` 我有什么 · `ENV` 我能用什么 · `PITFALLS` 我踩过什么 · `TODO` 我欠什么。判入规则：别的对话会用到 → `INVENTORY`，会再踩 → `PITFALLS`。
- **条目必须带指针**：位置 / 状态 / 来源 / 时间 / 可信度；超 30 天未复核按"可能过期"处理；同一事实两处不一致以 memory 为准。
- **卡释放后的查漏清单**：`INVENTORY` 有新东西没登记？`ENV` 有变化？`PITFALLS` 有新坑？卡状态对吗？探针多大？测试绿吗？
- **坑要能回喂**：`PITFALLS` 被 `tools/experience_push.py` 逐条切块进召回语料 ⇒ 维护产物直接进下一次发现。
- **现状**：维护清单**由 Runtime 提醒**（R3 唤醒，缺省关），"⛔ 不自动改任何东西"——记忆三件仍由 Agent 手维护 🟡。

## 七、三档现状（对不上方法的不写成方法）

### ✅ 机制可复核

- 9 态卡 + 排他 `claim` / `release` / `takeover` + `.log` 外置留痕（`tools/task_card.py`）
- 能力选择记录 + 机械 lint（只从 `.log` 读，出 PASS / FAIL / SKIP）
- 收尾写回：选卡不猜、只写机械事实、占位不自评分（`tools/wrapup_sync.py`）
- 开工恢复：`SessionStart` 自动注入任务恢复提示（不列卡内容）
- 结构闸门 5 个 + 克隆自检 1 条（`tools/probes/*.py`），全部可跑

### 🟡 试过但未成立（别重复走）

- 把"开工先检索"写进宪法：最有利条件下仍未执行
- 手工调写回：连续几次真实任务 0 次 ⇒ 纪律不能当机制
- 无任务描述就推能力：构造性噪声
- 经验召回能减少重复踩坑：机制在跑，效果未证
- 自动发现（stage4）：**代码在，开关关**

### ❌ 不写成方法

- Exposure 五模式 / Assembled 装载器 / 模式调度器：执行层 0 引用、0 个 `condition:`、无装载器
- 多能力 / 多阶段编排：未建、未测
- "真实工作自动让环境变强"的闭环：写回半环仍手做

## 指针

| 要什么 | 去哪 |
|---|---|
| 卡怎么写 | `task_cards/README.md` · `task_cards/GOAL-INPUT-CONTRACT.md` |
| 工具什么时候用 | `TOOL_RUNTIME.md` |
| 已经踩过的坑 | `task_cards/memory/PITFALLS.md` |
| 当前限制 | [`../../docs/LIMITATIONS.md`](../../docs/LIMITATIONS.md) |
