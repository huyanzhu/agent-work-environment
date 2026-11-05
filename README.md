# AI-OS

> 🚀 **克隆后想直接用？先读 [QUICKSTART.md](QUICKSTART.md)**（依赖 / 首次启动 / 30 秒自检 / 接进宿主 / 第一次干活 / 已知红）。

**一个会生长的 Agent 工作环境。**

大多数 Agent 系统在解决"给 Agent 加能力"。
但能力存在，不等于能力会被用到。

真正要解决的是两件事：能力怎么在正确的时候自己出现；真实工作怎么反过来让环境变强。

AI-OS 面向 Agent 运行：在 Agent 工作流的关键 **Hook** 上，让知识、工具和可装配能力按需进入决策空间——通过**可验证**的辅助能力，降低 Agent 的认知、执行、协作成本。

## 它解决什么问题

一条能力要真正起作用，必须连过四道断点：**存在 → 被用 → 被读 → 有价值**。
绝大多数系统只做第一道（把能力写进仓库），而失败发生在后面三道：能力在场，但不在需要的那一刻。

AI-OS 的全部工作都压在这四道断点上：

| 断点 | AI-OS 的做法 |
|---|---|
| 存在 → 被用 | 不靠 Agent 自觉去翻：开工恢复、占卡、阶段/节点注入由 **Runtime** 在确定性时点触发 |
| 被用 → 被读 | 注入的是**路径 + 一句纪律**，不是全文；能力注入跟随**卡上声明**，不猜 |
| 被读 → 有价值 | 收尾写回把"用了什么、产出什么"留成可复核的账本，价值判断交给 Human 与机械字段 |
| 环境变强 | 真实工作产生的经验沉淀为**经验族卡**与**坑清单**，下一轮开工就能被召回 |

## 适用 / 不适用

**适合**：

- 你在用 Agent 做**多轮、跨会话**的真实工作，需要"中断后从哪继续"。
- 你有一批**做事方法**（能力）与**踩过的坑**（经验），希望它们在正确时机自己出现，而不是靠记忆。
- 你愿意接受机械判据：每个结论要么能指回文件/探针读数，要么标"未验证"。

**不适合**：

- 想要"更强的模型"——AI-OS 不训练、不微调、不做推理增强。
- 想要通用记忆库 / 知识库 / 多 Agent 编排平台——这些不在当前范围内（见 [docs/LIMITATIONS.md](docs/LIMITATIONS.md)）。
- 要求"装上就有效"——投递通道**实测能判对域、能力字段会被自行填写**（真实任务 3/3），但**是否提升产出仍未证**（见 [workspaces/ai-os-public/EVIDENCE.md](workspaces/ai-os-public/EVIDENCE.md)）。

## 快速开始

```bash
git clone https://github.com/huyanzhu/agent-work-environment.git
cd agent-work-environment
cp -r .aios-sample .aios      # 首次使用必做：Windows 用 xcopy /E /I .aios-sample .aios
```

然后**重启宿主**（插件在启动时装载），把这句话给你的 Agent：

```text
接入 AI-OS：先读 README.md，再按 QUICKSTART.md 做。
```

### 首次启动的唯一路径（README / QUICKSTART / runtime/README 三处同文）

1. **`.aios/` 缺失 ⇒ `inject_probe.json` 不存在 ⇒ 外层注入门关**：阶段注入、节点注入、提醒**都不发生**（零注入）。
2. **`phase_inject.json` 缺省 = 开**（只是第二道门）；**域注入跟卡上声明**（`domainInject` 缺省 `off`）；**经验召回缺省关**。
3. **首次使用 = `cp -r .aios-sample .aios` + 重启宿主**；此后一切按 `.aios-sample` 各文件的显式值运行。

> 没有"两种都行"：不初始化 `.aios/`，就是零注入；要看到注入，只有上面这一条路径。
> 开关清单与缺省值见 [maintenance-skills/runtime-switches.md](maintenance-skills/runtime-switches.md)。

## 30 秒自检（克隆后立刻可跑）

```bash
python tools/task_card.py states                          # 卡系统：打印 State 校验结果
python tools/probes/_capability_field_lint.py             # 能力库：合计 8 · OK 8
python -m unittest discover -s tools/tests -p "test_*.py" # 应：Ran 153 tests · OK
node runtime/tests/activation.test.mjs                    # 应：合计 208 项 · 通过 207 · 失败 1
```

唯一允许的红是 `S37`（已知红，见 [docs/LIMITATIONS.md](docs/LIMITATIONS.md)）。

## 它由什么组成

| 层 | 目录 / 文件 | 是什么 |
|---|---|---|
| **约定层** | `AGENTS.md` · `README.md` · `ONBOARD.md` · `TOOL_RUNTIME.md` | 宪法 / 启动顺序 / 接入 / 工具一行式 |
| **记忆层** | `task_cards/` | 任务卡 = 工作记忆；卡是快照，占用与收尾流水外置到同级 `.log` |
| **语料层** | `capabilities/` · `domains/` | 8 个域能力（50 片）+ 经验族卡与坑清单 |
| **机制层** | `runtime/` · `tools/` · `.aios-sample/` | 投递接线（15 模块插件）+ 卡系统/校验闸门 + 开关样本（首次使用复制为 `.aios/`） |

Runtime 的分层、模块依赖图与硬规则见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)；
能力与经验机制见 [docs/CAPABILITIES.md](docs/CAPABILITIES.md)。

## 三条通道（当前真实在跑的）

| 通道 | 触发时机 | 注入什么 |
|---|---|---|
| **显式拉取** `auto_capability` | Agent 说清"做什么 + 要哪类能力"（`confirmed` 可省略：缺省 = `agent-inferred`；只有对方确认过才写 `user`） | 只给 `what` ⇒ 回 8 个领域词表；带 `need` + `confirmed` ⇒ 检索候选随工具返回（≤3 条，带路径摘要） |
| **阶段注入** | S1 占卡后 / S2 实质改动后 / S4 收口时 | 卡上声明的域能力 `intro` + 文件路径（⛔ 不猜域） |
| **节点注入 / 经验召回** | 命中改语料、重建索引、跑回归门等节点；或工具失败被分类 | 对应经验族卡路径 + 一句纪律 / 相关经验条目 |

⚠️ **未打开的部分**：自动发现派发（Runtime 自己判断"现在是个发现机会"）是**关闭**状态，只保留代码可回退；
首拍注入同样关闭。⛔ 不要把"自动发现"当成现行主线——现行走的是 Agent 显式调用或阶段/节点注入。

## 证据现状（当前读数）

| 项 | 状态 | 依据 |
|---|---|---|
| 工作记忆（任务卡） | ✅ 机制跑通 | 9 态 `State`、`claim`/`release` 排他占用、`.log` 外置留痕、`takeover` 接管 |
| 开工发现（`tools/task_start.py`） | ✅ 只读、按输入分级 | 无参 = 任务恢复；带任务描述 = 材料发现 |
| 能力库 / 经验库 | ✅ 结构可机械校验 | 8 域 50 片 · 6 张经验族卡 · 111 条坑清单；5 个闸门可跑 |
| 阶段注入判对域 | ✅ 机制可复核 + 真实任务实测 | 声明驱动注入；真实任务 3 单选域 3/3 正确、注入到达 2/3（第 3 单 hook 漏事件，v55 已加兜底） |
| 投递是否提升产出 | 🟡 未验证 | 判对域 ≠ 产出更好；对照实验样本量小 |
| 自动发现 / 首拍注入 | ❌ 关闭 | 开关关，代码保留 |

> 口径：**integrated ≠ consumed ≠ valuable**。✅ 只到"机制可复核"，不到"价值已证明"。
> 完整的 A/B/C/D 四档证据与"这份证据不证明什么"见 [workspaces/ai-os-public/EVIDENCE.md](workspaces/ai-os-public/EVIDENCE.md)。

## 文档地图

| 想知道 | 去哪 |
|---|---|
| 从零跑起来 | [QUICKSTART.md](QUICKSTART.md) |
| 架构与模块依赖 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 能力与经验机制 | [docs/CAPABILITIES.md](docs/CAPABILITIES.md) |
| 当前限制与已知问题 | [docs/LIMITATIONS.md](docs/LIMITATIONS.md) |
| 安全边界 | [docs/SECURITY.md](docs/SECURITY.md) |
| 开关清单与缺省值 | [maintenance-skills/runtime-switches.md](maintenance-skills/runtime-switches.md) |
| 为什么值得用 / 证据有多硬 | [workspaces/ai-os-public/README.md](workspaces/ai-os-public/README.md) |
| 改 runtime 的规矩 | [runtime/README.md](runtime/README.md) |

## Agent 接入（启动顺序）

1. 读 `AGENTS.md`（身份 / 硬约束 / 设计规则 / 证据纪律）
2. 读 `TOOL_RUNTIME.md`（工具：是什么、什么时候用）
3. 开工时调一次 `auto_capability`（`what` 一句即可）→ 拿 **8 个领域词表**，选一个写进卡「能力」字段；需要恢复上下文再跑 `python tools/task_start.py`
4. 动手前占卡：`python tools/task_card.py claim <项目>/<TASK-ID>`

## License

[Apache License 2.0](LICENSE)
