# capabilities/ — Capability Space（可装配能力空间 · 域合并后）

> 与 domains/（知识）并列的第二种消费空间。
> **结构**：**一个领域一个文件** ⇒ 本目录现为 **8 个域能力（50 片）**；**领域是唯一分类轴**，片不含 `class`（也不要求 `phases`）；旧 8 个域能力文件与格装配表 `capabilities/_archive/CELLS.md` 已归档到 `capabilities/_archive/`（⛔ 只读、不再改），旧能力名经 `capabilities/_aliases.json` 映射到域能力（历史账本仍有效）。

## 这里放什么

- **8 个域能力文件**（一域一文件）：`domain-frontend` / `domain-backend` / `domain-data` / `domain-docs` / `domain-product` / `domain-ops` / `domain-job-search` / `domain-aios-itself`。
- 每个文件 = **frontmatter**（`name` / `intro` / `axis_domain` / `axis_help` / `axis_concern` / `keywords` / `domain` / `parts[]` / `merge_of`）+ **正文**（什么时候用 / 做法 / 片的覆盖来源）。
- **片（part）** = 可装配的最小单位，字段 `id` / `domain` / `label` / `one_line` / `from`；一个域能力内含 3–9 片。**片不带 `class`**，也没有阶段字段。
- 索引与说明：`INDEX.md`（8 行 · 什么时候用哪个域）· `AXES-MAP.md`（内部检索登记表，不随发布）· 本文件 · `_aliases.json`（旧名 → 域能力）。
- `_archive/` = 历史件（旧能力 + `capabilities/_archive/CELLS.md`，不随发布），⛔ 只读引用，不再新增或修改。
- 不默认拆解。只有真实证据证明需要拆成原子方法时，才拆进 `domains/`（知识 / pattern）。

## 与 domains/ 的区别

| | domains/（知识） | capabilities/（可装配能力） |
|---|---|---|
| 消费语义 | 检索 → 读 → 采纳（信息） | 检索 → 装配 → 激活工作模式（装载） |
| 单位 | pattern / experience / guideline（可拆分） | 域能力（一域一文件 · 内含多个片） |
| 通道 | experience_push（任务开始知识检索） | capabilities/INDEX.md（任务开始能力检索；入口工具 = `auto_capability`） |

## 规则

- **新增域的前置判据**：现有 8 域覆盖不到才加**域**；能塞进现有域就加**片**，⛔ 不加域（详见 `docs/CAPABILITIES.md §五`）。族数量不是 KPI。
- **领域是唯一分类轴**：先调 `auto_capability`（`what` 一句）拿 8 个领域词表，按本次**主改动所在域**选**一个**域能力，⛔ 不要一次选多个域；跨域任务也按**主改动**选，⛔ 不按阶段拆成多个能力。
- 记录（v4 缺省卡 · 单字段）：`python tools/task_card.py capability <TASK-ID> --name <域能力名|none> --why "…"`（⛔ 省略 `--stage`；只有旧 v1/v2/v3 三阶段卡才用 `--stage start|impl|close`）。
- 只想先看「现在会提示哪个能力」而不写记录（**只读 · 不记账**）：`python tools/task_card.py capability-hint <TASK-ID>` —— `--stage` **可省略**（按单字段卡口径，与 `claim` 同一文案）；显式给 `start|impl|close` 仍接受，但域合并后提示按**域**出，阶段不再改变文案。
- **`none` 是合法值**：本次改动没有可装配的同域能力（或照做只会误导）时用它；⛔ 不能不答，理由须 ≥8 字符且对得上本次改动（「不需要 / 无」会被拒）。
- 片不写 `class`、不要求 `phases`（域合并后两者都不是必填字段）；新增片一律挂在某个 `domain-*.md` 里。
- Global / Callable / Searchable / Conditional / Assembled 是 Exposure/Activation 模式，不是 Capability 的类型；`condition:` 至今 **0 个**域能力有。
- 裁决引 evolution/decisions.md。

### `none` 与记录落点（v4）

- 卡（`## 使用的能力（可 none）`）上只有一行：

  ```text
  - 能力: `none` ｜ <为什么不需要域能力>
  ```

- `.log`（同级同名）写一条：

  ```text
  | HH:MM | 能力 | none ｜ 理由：<同一句> | Worker |
  ```

- **什么时候用 `none`**：本次改动在 8 个域里找不到同域能力可装配（或选一个照做会误导）。跨域 ≠ 一定 `none`：按主改动选一个，选不出才 `none`。
- **校验器判据**（`tools/probes/_capability_choice_lint.py` · 单字段卡）：`.log` 有 State=`能力` 的行、`name` 非空 ⇒ 按 `name` 判；`name=none` ⇒ **PASS**，且**不要求**该会话 read 过 `capabilities/`（`name≠none` 才要求 read ≥ 1 次）。
- ❌ 只有**缺 `能力` 行**才 FAIL（detail：「缺 `能力` 记录」）；`none` 不会被当成"缺记录"。
- 计时：该行时间不得晚于该会话首次 `edit`；探针取不到 / 卡建在首次 edit 之后 ⇒ `timing: n/a`，不判失败。v4 卡给 `--stage` ⇒ `task_card.py` **拒绝**（阶段行会把卡形态翻成旧三阶段）。
- 重记（同一张 v4 卡再跑一次）：卡上 `- 能力:` 覆盖为最新值，`.log` 追加一行；**lint 与注入都取「末条」`能力` 行**（last-wins）—— 因为跨域任务的第二段可能换成另一个域能力，只能更新声明；若校验读首条，更新就会被判成「不一致」。⚠️ 旧三阶段卡（v1/v2/v3）仍按「首条」判。
- 旧三阶段卡（v1/v2/v3）：`--stage start|impl|close`；`close` 的 `none` 同样 PASS 且不要求 read，`start` 只判时间早于首次 edit。

## 读数（可复跑）

- `python tools/probes/_capability_field_lint.py` ⇒ 8 个文件 · OK 8 / WARN 0 / FAIL 0
- `python tools/probes/_capability_parts_matrix.py` ⇒ 8 个域能力 · 50 个片 · 领域覆盖 8/8
