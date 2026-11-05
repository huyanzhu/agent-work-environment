# QUICKSTART — 从零跑起来

> 本文件是**动手入口**：依赖、首次启动、自检、接进宿主、第一次干活、已知红。
> 想知道「AI-OS 是什么 / 凭什么值得用」读 [README.md](README.md) 与 [workspaces/ai-os-public/](workspaces/ai-os-public/README.md)。

## 0. 一句话

一个 Agent 的**操作平台**：把「能力 / 经验 / 任务卡账本 / 注入通道」做成可机械校验、可复现的一层，让 Agent 干活时更少踩坑。
**现状（诚实）**：结构与机制已验证；「是否真降低 Agent 成本」= 单样本有据、**未全面验证**（见 [workspaces/ai-os-public/EVIDENCE.md](workspaces/ai-os-public/EVIDENCE.md)）。

## 1. 依赖

| 依赖 | 本仓运行读数 | 用于 | 缺了会怎样 |
|---|---|---|---|
| **Python** | 3.13.2（≥3.10 应可） | `tools/` 全部（卡系统、校验闸门、探针） | 卡系统不可用 |
| **Node** | 26.2.0（需原生 TS type-stripping，≥22.6） | `runtime/tests/*.mjs` 直接 `import` `.ts`；`npm test` | runtime 自测不可用 |
| **git** | 2.54.0 | 卡/账本、`_clone_selftest.py` 的隔离自检 | — |
| **fastembed + onnxruntime**（可选） | 未安装时 | 语义检索层（混合通道） | **只走词面通道**（`tools/experience_push.py` 照常可用）；`tools/probes/_scene_probe.py` 打印「怎么办」并 `exit 2`（= 环境未就绪，**不是**读数失败） |

## 2. 首次启动（唯一路径，没有第二种）

```bash
cp -r .aios-sample .aios          # Windows: xcopy /E /I .aios-sample .aios
```

然后**重启宿主**（插件在启动时装载）。

**为什么必须做**（三处口径一致）：

1. **`.aios/` 缺失 ⇒ `inject_probe.json` 不存在 ⇒ 外层注入门关**：阶段注入、节点注入、提醒**都不发生**（零注入）。
2. **`phase_inject.json` 缺省 = 开**（只是第二道门）；**域注入跟卡上声明**（`domainInject` 缺省 `off`）；**经验召回缺省关**。
3. **首次使用 = `cp -r .aios-sample .aios` + 重启宿主**；此后一切按 `.aios-sample` 各文件的显式值运行。

> `.aios/` 是本机运行期目录，被 `.gitignore` 忽略、不随仓库发布；`.aios-sample/` 是它的开关样本。
> 五份开关的逐项含义、缺省值与代码锚点见 [maintenance-skills/runtime-switches.md](maintenance-skills/runtime-switches.md)；
> 样本目录 `.aios-sample/` 内自带一份 `README.md`，说明每份文件开的是什么、怎么验。

## 3. 30 秒自检（克隆后立刻可跑，全部应有读数）

```bash
# ① 卡系统：打印 active 下卡的 State 校验结果
python tools/task_card.py states

# ② 能力库字段校验：应 合计 8 · OK 8 · WARN 0 · FAIL 0
python tools/probes/_capability_field_lint.py

# ③ tools 测试：应 Ran 153 tests · OK
python -m unittest discover -s tools/tests -p "test_*.py"

# ④ runtime 隔离自测：应 合计 208 项 · 通过 207 · 失败 1
node runtime/tests/activation.test.mjs
```

**预期**：①②③④ 全绿，**唯一允许的红是 `S37`**（已知红，见 [docs/LIMITATIONS.md](docs/LIMITATIONS.md)）。

```bash
# ⑤ 可选：克隆可用性自检（在临时 worktree 里跑上面几条）
python tools/probes/_clone_selftest.py
```

## 4. 接进 DSH 宿主（插件形态）

`runtime/aios-activation.ts` 是一个 cordis 风格插件：

```ts
export const name = 'aios-activation'
export const inject = []  // 可注册的工具名；本插件不额外注册
export function apply(ctx: any): void
```

把它加进你 DSH profile 的插件列表（示例意图，**具体字段名以你宿主版本为准**）：

```yaml
plugins:
  - path: <你的克隆目录>/runtime/aios-activation.ts
```

⚠️ **已验 / 未验**：插件能被 `import` 且自测通过（208 项）；**干净环境下的完整宿主装载尚未在别人的机器上验证**。
装不上时先按 §2 确认 `.aios/` 已初始化，再读 `runtime/aios-activation.ts` 顶部的 POLICY 注释。

## 5. 第一次干活（四步）

```bash
# 1) 建卡（🔴 必须带 --project；不带会落 active/ 顶层并打警告）
python tools/task_card.py create "我的第一个任务" --project=示例

# 2) 占卡（排他；被别的会话占着的卡对你不可用）
python tools/task_card.py claim 示例/TASK-YYYYMMDD-001

# 3) 开工先调 auto_capability（what 一句）→ 选 8 个领域里的一个，记进卡（单字段）
python tools/task_card.py capability 示例/TASK-YYYYMMDD-001 \
  --name domain-aios-itself --why "先核状态清单再动手"

# 4) 收工（必须显式给状态）
python tools/task_card.py release 示例/TASK-YYYYMMDD-001 --state=Completed
```

`--name` 用 `none` 表示"本任务不用能力"——**声明 none 与没声明不同**：没声明就不注入，声明 none 也不注入，但账本里能区分。

## 6. 开关：`.aios/` 是**本机目录**（gitignore）

- 初始化前（`.aios/` 不存在）⇒ **零注入**（外层门 `inject_probe.json` 不存在）。
- 初始化后 ⇒ 按 `.aios/*.json` 的显式值运行；文件缺失时回落代码缺省（`phase_inject` 开、`domainInject` 关、经验召回关、R3 唤醒关）。
- 改开关**不用重启**（运行时按 mtime+size 懒读）；写 JSON 一律 **BOM-less**。
- **完整开关清单 + 缺省值 + 判据边界**：见 [maintenance-skills/runtime-switches.md](maintenance-skills/runtime-switches.md)。

## 7. 已知红 / 已知未验（别当成你的环境坏了）

| 项 | 说明 |
|---|---|
| `S37` 单测红 | **已知红**：v4 消息源形状断言。208 项里唯一的失败项，不影响其它机制 |
| 投递是否提升产出 | 🟡 未验证：判对域（机制）已证，产出更好未证 |
| 经验召回命中率 | 🟡 真实任务样本少；0 命中 ≠ 经验库没有（先看探针里的 `query`） |
| `_scene_probe.py` | 需要 fastembed + 已建索引；缺依赖时打印指引并 `exit 2` |
| 浏览器 / 读屏层 | 沙箱里 Chrome 起不来 ⇒ 真实 Tab 顺序、焦点环观感、读屏播报**均未验**；仓内没有 NVDA/VoiceOver 实证 |

完整的当前限制见 [docs/LIMITATIONS.md](docs/LIMITATIONS.md)。

## 8. 目录地图（读哪份）

| 路径 | 是什么 |
|---|---|
| `AGENTS.md` | **宪法**（身份 / 硬约束 / 设计规则 / 证据纪律）—— Agent 开工必读 |
| `README.md` | 产品介绍 + 启动顺序（唯一必读，点名下一步） |
| `ONBOARD.md` | 接入（身份 / 原则 / 收入收工） |
| `TOOL_RUNTIME.md` | Agent 实际用的工具一行式 + 调用约定 |
| `capabilities/` | **能力库**：8 个域能力（50 片）；入口 = `auto_capability`，`INDEX.md` 是目录 |
| `domains/experiences/` | **经验族卡**（6 张）+ 坑清单 `task_cards/memory/PITFALLS.md`（发布版 111 条） |
| `task_cards/` | **任务卡工作记忆**（`active/<项目>/`）+ 卡模板 |
| `runtime/` | 本体（插件）：阶段注入 / 节点注入 / 经验召回 / R3 唤醒，15 模块 |
| `tools/` | 机制：卡系统、校验闸门（`probes/`）、回归门 |
| `maintenance-skills/` | 维护手册：经验族流水线、能力融合、**开关清单** |
| `docs/` | 架构 / 能力 / 配置 / 限制 / 安全 五份 | 
| `workspaces/ai-os-public/` | **对外五件**（问题 / 原则 / 方法 / 证据 / 入口） |

## 9. 想先看证据再决定用不用

读 [workspaces/ai-os-public/EVIDENCE.md](workspaces/ai-os-public/EVIDENCE.md) 的 **D 档（反例）** —— 那里列了被证伪的假设，包括「能力注入有用」。这套东西的诚实性在 D 档，不在 A 档。
