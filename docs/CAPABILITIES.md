# CAPABILITIES — 能力与经验机制

> 本文回答三件事：**语料长什么样**（能力 / 经验）、**它们怎么进入决策**、**怎么加新的而不把结构搞坏**。
> 运行时的通道实现见 [`ARCHITECTURE.md](ARCHITECTURE.md)；判据边界见 [`LIMITATIONS.md](LIMITATIONS.md)。

## 一、两类语料

| 语料 | 位置 | 规模（当前） | 回答什么 |
|---|---|---|---|
| **域能力** | `capabilities/domain-*.md` | 8 个域能力 · 50 片 | **该怎么做**（可照做的方法清单） |
| **经验族卡** | `domains/experiences/*.md` | 6 张 | **什么时候该想起什么**（现象 → 分类 → 处置） |
| **坑清单** | `task_cards/memory/PITFALLS.md` | 发布版 111 条（源码 112；P 编号唯一连续） | **别再踩**（单条坑 + 触发条件 + 处置） |

### 1.1 域能力的文件结构

一个领域一个文件，**片（parts）不按阶段分**——领域是唯一分类轴。

```yaml
---
name: domain-data
intro: 当改库 / 迁移 / 回填时 ⇒ 先确认备份可还原，先建触发器再回填，部分更新用显式判空。
axis_domain: [数据]          # 词表：领域（唯一决定选哪个能力的轴）
axis_help: [实现, 验证]       # 历史字段（仅检索修饰，不参与选能力）：帮助类型
axis_concern: [正确性]        # 历史字段（仅检索修饰，不参与选能力）：关注面
keywords: [数据, 域能力, domain-data]
domain: 数据
parts:
  - id: domain-data#backup
    domain: 数据
    label: 备份可还原
    one_line: 先查备份是否带 -wal 且能还原，再动数据
    from: [data-change-safety#backup]   # 或 origin: <真实出处>
merge_of:
  - data-change-safety
---
```

- `intro` 就是注入到 Agent 上下文的那一句（形状是「当 X 时 ⇒ 照做 Y」）。
- `parts[].one_line` 必须含**动作词**（先 / 再 / 用 / 别 / 查 / 留…），⛔ 不写形容词。
- `from` / `origin` 至少给一个：来自旧能力合并，或真实出处（标准条款 / 本库真事）。
- 三个 `axis_*` 字段与 `task_cards/NEEDS-VOCAB.md` 的**同一套词表**取值；只改一边 ⇒ lint FAIL。

### 1.2 INDEX 是目录与校验锚（入口动作是 `auto_capability`）

`auto_capability` 是能力库的**入口动作**（调一次就返回 8 个域词表）；`capabilities/INDEX.md` 是**目录**：一行一个域能力，含领域、片数、什么时候用。
机械闸门会做**交叉校验**：表行数 = `domain-*.md` 文件数、片数 = `parts` 实际条数。改能力不改 INDEX ⇒ FAIL。

### 1.3 旧名字不会失效

`capabilities/_aliases.json` 把历史能力名映射到域能力（如 `doc_standards → domain-docs`、`senior-engineer → domain-backend`）。
所以卡上写旧名字仍能被识别成对应域能力；⛔ 不要靠"改名"来让旧记录失效。

## 二、经验机制：族卡 + 坑清单

### 2.1 族卡 = 同一问题域的一组坑 + 一组做法 + 一组判据

族卡不是单条坑的详情，而是**问题域**的组织形式：

```yaml
---
title: 遇到中文乱码/编码错误（改文件、读输出、重定向都算）
family: 中文编码/乱码
form: inject
status: pilot
trigger: [乱码, mojibake, 编码错误, BOM, 读回乱码, ...]   # 现象词、报错关键词
keywords: [乱码, encoding, utf-8, gbk, bom, ...]          # 打分里权重最高的两个字段
alias: [锟斤拷, 问号方块, 中文变怪字, ...]
---
```

- **`trigger` / `keywords` 是召回的高权重字段**：缺 frontmatter 的族卡在召回里**几乎命中不到**。
- 正文必须有 **「覆盖的坑（成员声明）」** 一行，列出它覆盖的 `P<编号>`。
- 成员声明里的编号必须与 `PITFALLS.md` **逐一对上**（或写进"未随发布"名单），否则闸门 FAIL。

### 2.2 坑清单的编号纪律

- 编号 **唯一 · 连续 · 表格 5 列**；新增坑**追加**，不重排。
- 每条 = 现象 + 触发条件 + 处置；判"换机后是否仍成立"决定它是否随发布。

## 三、它们怎么进入决策

| 入口 | 谁触发 | 拿到的形态 |
|---|---|---|
| **显式拉取** `auto_capability` | Agent 一句 `what`（不填别的字段也行）⇒ 先回 8 个领域词表；带 `need` 才回检索候选（`confirmed` 已可省略：缺省 = `agent-inferred`） | 词表 8 行；候选 ≤3 条，每条 ≤80 字 + 路径摘要 |
| **阶段注入 · 域能力** | S1 占卡后 / S2 实质改动后 / S4 收口 | 卡上**声明的**域能力的 `intro` + 文件路径 |
| **节点注入** | 命中 N1 改语料 / N2 重建索引 / N3 跑回归门… | 经验族卡路径 + 一句纪律 |
| **经验召回** | 工具失败被分类（权限 / 编码 / 退出码…） | 相关经验条目（词面通道，不依赖 fastembed） |

**打分口径**：先按词面（`trigger` / `keywords` 权重最高，`alias` 其次）筛，再按三维轴与覆盖率加权；检索执行在 Python 侧（`tools/probes/_retrieval_request_probe.py`），TS 侧只决定"何时问、问什么"。

## 四、怎么用（Agent 侧的动作）

1. 调一次 `auto_capability`（`what` 写一句在做什么即可，⛔ 不用先填别的字段）——它返回 **8 个领域词表**；从里面选**一个**与本次主改动同域的域能力，read 全文并照它做。
2. 把选择记在卡上（v4 单字段卡）：
   ```bash
   python tools/task_card.py capability <项目>/<TASK-ID> --name domain-backend --why "主改动是并发边界，先立基线"
   ```
   `--name none` = 明确声明"本任务不用能力"（与"没声明"不同）。
3. 只想看"现在会提示哪个域能力"（只读、不记账）：`python tools/task_card.py capability-hint <TASK-ID>`。
4. ⛔ 不要一次选多个域；跨域任务按**主改动**所在域选。

## 五、怎么加新的（别绕过闸门）

| 加什么 | 前置判据（能力族 / 经验族**同一条**） | 模板 | 校验 |
|---|---|---|---|
| 一个域能力（或给现有域加片） | **现有 8 域覆盖不到才加域**；能塞进现有域就加片，⛔ 不加域 | `capabilities/_TEMPLATE-domain.md` | `python tools/probes/_capability_field_lint.py`（含 INDEX 交叉校验） |
| 一张经验族卡 | **现有 6 族覆盖不到才加族**；有相关族 ⇒ **不动**（新坑并入该族） | `domains/experiences/_TEMPLATE-family.md` | `_family_field_lint.py` + `_family_members_lint.py` |
| 一条坑 | 编号唯一且连续（P# 是稳定引用键） | `task_cards/memory/PITFALLS.template.md` | `_pitfalls_id_lint.py` |

> **共同规则（能力族 / 经验族一致）**：**有相关族 ⇒ 不动；没有 ⇒ 才加**。族/域数量**不是 KPI**，
> 不为"看起来完整"新增。新增族卡时必须写一句「**为什么不复用现有族**」；新增域时必须写「为什么不塞进现有域」。
> 新增同批完成：登记/成员声明/期望集 + 对应 lint 全绿 + （经验族）回归门。

新增**领域**（不是给现有域加片）要走三步：① 先扩 `task_cards/NEEDS-VOCAB.md` 的领域轴；② `axis_domain` 与每一片的 `parts[].domain` 取同一个词表值；③ 同步 `capabilities/INDEX.md`（加行 + 改「N 个域能力」计数）。
没有机械闸门抓"漏改 INDEX"以外的嘴瓢——只能靠这张清单。

## 六、判据边界（读数字前先读这段）

- **integrated ≠ consumed ≠ valuable**：接进语料 ≠ 被调用 ≠ 有价值。
- **命中 ≠ 采用**：探针只记"注入了 / 召回了"，不记"有没有被采用"。要算采用率，收工时在卡 `## Outcome` 里填一行「投递采用」。
- **能力侧不以"打开率"判成败**：打开只是消费的必要条件，不是充分条件。
- **注入判对域 ≠ 产出更好**：域判对是可复核的机制读数；"产出是否变好"需要对照实验，见 [`LIMITATIONS.md](LIMITATIONS.md)。
