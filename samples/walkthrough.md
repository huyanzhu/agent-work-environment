# 样本：一个完整任务的全过程（从建卡到写回）

> 用途：把前面几份样本**串起来** —— 让你看到「能力 / 经验 / 账本」在一次真实任务里各自什么时候出场。
> 场景（虚构）：把一份 CSV 汇总成 JSON，并用另一套算法复算。

## 前置：初始化运行期开关（只做一次）

```bash
cp -r .aios-sample .aios      # Windows: xcopy /E /I .aios-sample .aios
```

> ⛔ 不做这一步：`.aios/` 缺失 ⇒ **零注入**（阶段/节点注入、经验召回都不会发生）。

## 0. 开工：先恢复上下文（AI-OS 的"统一开工发现"）

```bash
python tools/task_start.py
```
输出（样例）：
```
【AI-OS · 工作记忆】请寻找适合本次工作的工作记忆（任务卡）。
· 当前 active：**N 张卡** · M 个项目文件夹
· 已有合适的卡 ⇒ python tools/task_card.py claim <TASK-ID>  **声明占用**
· 没有合适的 ⇒ python tools/task_card.py create "<标题>"
```
> 这一步是**记忆**层：先看你有没有正在做的活。⛔ 不占卡 = 没有焦点，恢复与检索都用不上。

## 1. 建卡 + 占卡

```bash
python tools/task_card.py create "CSV 汇总为 JSON 并独立复算" --project=示例
python tools/task_card.py claim 示例/TASK-20260101-001
```
> ⚠️ **必须带 `--project`**：不带会落 `task_cards/active/` **顶层**（脚本会打印醒目警告），之后无法按项目归档/检索。
> 卡的形状见 `task_cards/active/示例/TASK-20260101-001.md`（样本卡）。

## 2. 记能力（**开工前**，不是做完补记）

```bash
# 先看能力库入口，选一个同域能力
调一次 `auto_capability`（what 写一句在做什么）→ 从返回的 8 个领域词表里选一个
python tools/task_card.py capability 示例/TASK-20260101-001 \
  --name domain-data --why "主改动是数据汇总与复算，属数据域"
```
> ⛔ **不带 `--stage`**：新版卡是单字段「使用的能力」；旧三阶段卡才用 `--stage`，混用会把卡写坏。
> 记账后你会收到一条域能力注入（`样本/探针行` 的 ②）——**那才是"能力在正确时机出现"**。

## 3. 干活时经验来帮忙

跑到一半报错（示例）：
```
PermissionError: [Errno 13] Permission denied: '<tmp>/x.csv'
```
此时可能收到**经验召回**（`样本/探针行` 的 ③），指向经验族卡（如「权限/沙箱错误族」）。
> 判读：`hits:0` 不等于"库里没有"——先查 query 与证据源。

## 4. 收工：填 Outcome + 释放 + 写回

```bash
python tools/task_card.py release 示例/TASK-20260101-001 --state=Completed
```
- 卡上填 `Outcome` / `Confidence` / `Deliverables`（**完成标准**，不是"做完了"三个字）
- 账本由 `Stop` 钩子自动写一条 Entry —— 你看到的是 `样例账本.md` 的形状
- **机制只写事实**（提交 sha / 改动行数），`Outcome / footprint / influence` 三项**归人填**

## 5. 这一趟里三层各自的出场时机

| 时机 | 谁出场 | 干什么 |
|---|---|---|
| 开工前 | **记忆**（`task_start` / 卡） | 告诉你有没有正在做的活、焦点卡是谁 |
| 开工前 | **能力**（`capabilities/`） | 你选一个域能力并记录 ⇒ 触发域能力注入 |
| 开工前 | **能力**（注入） | 把「当 X 时 ⇒ 照做 Y」那句话送进上下文 |
| 干活中 | **经验**（`PITFALLS` / 族卡 / 召回 / 节点） | 踩坑后给"别再踩"；改语料/重建索引时给纪律 |
| 收工 | **账本** | 机制写事实、人写判断，留下可核证据 |

## 6. 想验证"这条链真的跑通了"

```bash
python tools/task_card.py states                       # 卡系统可用
python tools/probes/_capability_field_lint.py          # 能力库合规
python -m unittest discover -s tools/tests -p "test_*.py"
node runtime/tests/activation.test.mjs                 # runtime 自测（S37 是已知红）
python tools/probes/_clone_selftest.py                 # 克隆可用性闸门
```
