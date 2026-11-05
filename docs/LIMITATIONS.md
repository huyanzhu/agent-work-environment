# LIMITATIONS — 当前限制与已知问题

> 这份文件存在的理由：**把"机制能跑"与"价值已证"分开**。不写清楚限制，读者会把前者当后者。
> 每条限制都给**当前版本能跑出的读数或命令**；跑不出来的一律标 🟡，不写成已实现。

## 一、怎么读

- ✅ **可复核**：有命令、有当前读数，换台机器也应能跑出同一个数。
- 🟡 **未验证**：机制在跑，但样本单批次 / 方向性，或需要作者侧环境才能复现。
- ❌ **未实现 / 未开启**：叙事里有、代码里关着或根本不存在。

## 二、当前读数（可复现，全部在本发布物内）

```bash
python tools/probes/_capability_field_lint.py
#   合计 8 · OK 8 · WARN 0 · FAIL 0
#   INDEX.md 交叉校验：表 8 行 · 文件 8 个 · 问题 0

python tools/task_card.py states
#   ✅ 全部卡的 State 均在值域内（missing=0 · off-vocab=0）

python -m unittest discover -s tools/tests -p "test_*.py"
#   Ran 153 tests · OK

node runtime/tests/activation.test.mjs
#   合计 208 项 · 通过 207 · 失败 1

# （模块图脚本事作者侧工具，不随发布）
#   反向依赖条数: 0
#   横向依赖条数: 0
#   （本地开发目录；不随发布 —— 发布物里用 tools/probes/_unbound_refs_lint.py 与 _tsc_lint.py 兜底）

python tools/probes/_pitfalls_id_lint.py
#   条目 111 · 唯一编号 111 · 合计 3 · OK 3 · FAIL 0

python tools/probes/_clone_selftest.py
#   干净克隆 → 上面四条全绿 → 判定: ✅ 克隆可用（跑完自动清理 worktree）
```

> 这些是**结构读数**，证明"机制在、闸门能跑"，**不证明**"这套东西让 Agent 变强了"。

## 三、机制层限制

| # | 限制 | 档 | 说明 / 怎么判读 |
|---|---|---|---|
| 1 | **单测有一个已知红** | ✅ | `S37`（v4 消息源形状断言）：208 项里唯一失败项。**已知红、与注入机制无关**；出现第二个红才算回归 |
| 2 | **投递能判对域，但"产出更好"仍未证** | 🟡 | 机制现状：`auto_capability` 只给 `what` ⇒ 回 8 个领域词表（不检索）；agent 选域写进卡 ⇒ 运行时按声明注入 S1/S2/S4。**真实任务实测（2026-11-03，3 单）**：选域 **3/3** 正确、能力字段 **3/3** 自行填写；注入到达 2/3（第 3 单根因 hook 偶发漏 `card-cmd`，已加兜底重扫）。**产出是否更好仍未证**：对照实验只到单批次 |
| 3 | **经验召回：触发面窄，但命中不差** | 🟡 | 触发面 = 工具调用失败且非事实型 ⇒ 干净任务天然不触发（这是设计）。真实失败文本 N=10：相关 **7** / 误报 1 / 漏 2（漏的两条是语料缺口）；全量召回 16 次 / 命中 11；族级 top1 13–14/14。**0 命中 ≠ 经验库没有** |
| 4 | **召回 query 乱码：已修，但旧读数要按新口径读** | ✅ | 已加归一化：乱码输入改用「错误分类 + ASCII 签名 + 编码族规范词」，不再送乱码原文。若看到 `query` 仍是乱码，说明宿主未装载新版（`python tools/probes/_live_policy_check.py` 可查） |
| 5 | **命中 ≠ 采用** | ✅ | 探针只记"注入/召回"，不记"有没有被采用"；采用率要在卡 `## Outcome` 里手工留一行 |
| 6 | **候选打开率未重测** | 🟡 | 能力侧不以打开率判成败；打开率只作为"消费的必要条件"，不是价值判据 |
| 7 | **子会话默认也收注入（实测已达）** | ✅ | `allowSubagent` 缺省 true；真实任务实测子会话能收到 S1/S2/S4。若某会话没注入，先查探针里有没有 `card-rescan-fallback`（hook 漏 `card-cmd` 的兜底）与 `phase-inject` |
| 8 | **探针跨会话累积** | ✅ | 探针日志是长日志，读数**不能归因到单次验证**；历史事件在轮转的 `*.gz` 里 |
| 9 | **各模块没有独立单测，但类型闸门已接入** | ✅ | 15 个模块只经主入口 + `__selftest` 覆盖；`tsc --noEmit`（strict 零基线）已通过 `tools/probes/_tsc_lint.py` 接入；另有未绑定引用 / 静默 catch / 注释归属三个静态闸门 |
| 9b | **紧凑流程可能错过注入窗口** | 🟡 | `claim → 记能力 → 写 → release` 若在很短时间内完成，S1/S2 判定窗口可能被跳过（真实任务 1 单复现）。v55 起注入判定前会**兜底重扫卡**并记 `card-rescan-fallback`；但仍不保证每个短流程都恰好命中一次 |
| 10 | **自动发现 / 首拍注入关闭** | ❌ | `STAGE4_ENABLED=false`、`FIRST_STEP_INJECT_ENABLED=false`，代码保留可回退；⛔ 不要当现行主线 |

## 四、环境层限制

| 限制 | 档 | 说明 |
|---|---|---|
| **宿主装载未在干净环境验证** | 🟡 | 插件能 `import`、自测通过、在本机真机装载过；**别人机器上的完整 DSH 装载未验证**。装不上先按 `QUICKSTART.md §2` 确认 `.aios/` 已初始化 |
| **单机 / 单平台** | 🟡 | 现有读数来自 Windows + PowerShell + 单台机器；未在 macOS / Linux 复跑。跨平台的差异点主要是编码与路径分隔符（两者都有专门的经验族卡与闸门） |
| **语义检索是可选依赖** | ✅ | 没有 fastembed/onnxruntime 时只走词面通道；`tools/probes/_scene_probe.py` 会打印指引并 `exit 2`（**环境未就绪**，不是读数失败） |
| **浏览器 / 读屏行为未验** | 🟡 | 沙箱里 Chrome 起不来 ⇒ 真实 Tab 顺序、焦点环观感、读屏播报均未验；仓内没有 NVDA/VoiceOver 实证，"读屏可读名"是按 accname 规则算出来的 |

## 五、范围外（明确不做）

- 不训练 / 不微调 / 不做推理增强 —— 模型强弱是外部变量。
- 不建通用记忆库 / 知识库 / 重复事实存储。
- 不建 telemetry；不建多 Agent 编排 / 通用任务调度平台。
- 不替 Agent 做判断：适用性、采纳、拒绝归 Agent；AI-OS 只负责让材料到场。
- 不追"全自动"：机械动作 → runtime；判断 → Agent；架构决定权 → Human。

## 六、想自己验一条

最短闭环：引一条能力 → 照它做一件小事 → 对比"有没有它"的差别。

```bash
python tools/probes/_clone_selftest.py                       # 先确认包本身是好的
python tools/task_card.py create "<你的任务>" --project=示例
python tools/task_card.py claim 示例/<TASK-ID>
python tools/task_card.py capability 示例/<TASK-ID> --name <域能力> --why "<≥8 字理由>"
# 收工时把「用了哪几条做法、哪条是本来不会做的」写进卡的 Outcome
```

**判据**：撤掉某条能力做法后，交付质量**没有明显变差** ⇒ 这条能力对你是噪音，按 Q5（移除后是否明显退化）自行裁剪。
