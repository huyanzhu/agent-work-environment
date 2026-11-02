# 这里是哪（发布物地图 + 架构图）

> 只列**本发布物里真实存在**的路径；⛔ 不引用作者私有工作仓的东西。

## 一分钟

| 想干什么 | 去哪 |
|---|---|
| 先看懂它是什么 | `README.md`（启动顺序）→ `workspaces/ai-os-public/PROBLEM.md` |
| 5 分钟跑起来 | **`QUICKSTART.md`**（§3 装进宿主；**首次必须 `cp -r .aios-sample .aios`**） |
| 看它凭什么值得用 | `workspaces/ai-os-public/EVIDENCE.md`（**先读 D 档：被证伪的假设**） |
| 改 runtime | `runtime/README.md`（五条铁律 + 「哪些路径现在真的在跑」+ 排查顺序） |
| 开关在哪 | `maintenance-skills/runtime-switches.md` · 样本在 `.aios-sample/` |
| 证据读数 | `evidence/READINGS-2026-11-02.md`（包内可复跑 / 需私有仓，两栏不混） |

## 架构图（数据流）

```
                ┌──────────────────────── 宿主（DSH / Claude-Code 形态）────────────────────────┐
                │  会话事件：session-start · pre/post-execute · turn-end · 工具调用与结果        │
                └───────────┬───────────────────────────────────────────────▲──────────────────┘
                            │ 事件/工具名/卡状态（⛔ 不取正文）                │
                            ▼                                                │ 注入（user 消息 /
                ┌───────────────────────────────┐                            │ additionalContexts）
                │  runtime/aios-activation.ts    │                            │
                │  ── 会话状态 / 焦点卡 / 阶段判定 │                            │
                │  ── 去重与限频（每拍最多一条）    │────────────────────────────┘
                └───┬───────────┬───────────┬────┘
      ① 阶段注入 (S1/S2/S4) │   ② 节点注入  │  ③ 经验召回（失败触发）
        按卡上**声明**的域能力 │  (N1/N2/N3)  │  词面通道（不依赖 fastembed）
                            ▼               ▼
                ┌──────────────────────────────────────────────┐
                │ 检索桥 spawnJson（Python 子进程 · 超时+**输出上限**）│
                │ retrieval-request/v1 → candidate-set/v1       │
                └───────────┬──────────────────────────────────┘
                            ▼
        ┌───────────────────────────────────────────────────────────────┐
        │ 语料层：capabilities/（8 域 50 片）  domains/（6 族卡+patterns） │
        │         task_cards/memory/PITFALLS.md（发布版 111 条）           │
        └───────────────────────────────────────────────────────────────┘
        ┌───────────────────────────────────────────────────────────────┐
        │ 记忆层：task_cards/active（工作记忆）   task_cards/memory（全局）│
        └───────────────────────────────────────────────────────────────┘
                ▲
                │ 写回（Stop hook / 收工记账）
        ┌───────┴───────────────────────────────────────────────────────┐
        │ 五个机械闸门：能力字段+INDEX · 族卡结构 · 族卡成员 · PITFALLS 编号 │
        │               · 静默 catch 可观测化（tools/probes/*.py）        │
        └───────────────────────────────────────────────────────────────┘
```

**四个设计约束**（改动前先读，来源 `runtime/README.md`）：
1. **Runtime 与 Retrieval 分离**：TS 负责"何时触发"，Python 负责"检索什么"。
2. **不猜域**：能力注入跟随**卡上声明**（`basis:"declared"`）；无声明 ⇒ 本拍不注入（设计，不是故障）。
3. **失败必须分类**：子进程 `spawn-error / timeout / empty-stdout / bad-json / output-too-large` 各不相同，⛔ 不把空输出当"零候选"。
4. **静默要可查**：19 处 catch 接 `catch-fail` 探针（限频）；5 处**故意静默**（探针通道自身 / kill 失败）并写明理由。

## 四层结构

| 层 | 目录 | 是什么 |
|---|---|---|
| **约定层** | `AGENTS.md` · `README.md` · `ONBOARD.md` · `TOOL_RUNTIME.md` | 宪法 / 启动顺序 / 工具一行式 |
| **记忆层** | `task_cards/`（`README.md` + 当前模板（v4）+ 旧版模板 + `memory/` 三份空模板与 PITFALLS 发布版） | 任务卡 = 工作记忆；`memory/` = 全局记忆（本机事实**内容未随发布**） |
| **语料层** | `capabilities/`（8 域 50 片）· `domains/`（6 族卡 + patterns） | 该怎么做（能力）与别再踩（经验） |
| **机制层** | `runtime/`（插件本体 · 主文件 ~4k 行 + 模块）· `tools/`（卡系统 / 5 个闸门 / 回归门）· `.aios-sample/`（开关样本） | 投递接线与可机械校验的动作 |

## 五个机械闸门（都能跑，失败 exit 1）

| 闸门 | 抓什么 |
|---|---|
| `tools/probes/_capability_field_lint.py` | 能力 frontmatter / 片结构 / **INDEX 交叉校验**（表行数=文件数、片数一致） |
| `tools/probes/_family_field_lint.py` | 族卡 frontmatter 必填（`trigger`/`keywords` 是召回高权重）+ 正文锚点 |
| `tools/probes/_family_members_lint.py` | 族卡「成员声明」的坑号必须真实存在（或在该名单里） |
| `tools/probes/_pitfalls_id_lint.py` | PITFALLS 编号**唯一 / 连续 / 表格 5 列** |
| `tools/probes/_silent_catch_lint.py` | 静默 catch 不许回退（接线 ≥10、`catch-fail` 存在、真空 catch ≤5） |

## 想自己加东西

| 加什么 | 模板 | 样本 | 校验 |
|---|---|---|---|
| 一张任务卡 | `task_cards/_TASK_CARD_template.v4.md` | `task_cards/active/示例/TASK-20260101-001.md` | `python tools/probes/_card_description_lint.py` |
| 一个域能力 | `capabilities/_TEMPLATE-domain.md` | `samples/capability-sample.md` | `_capability_field_lint.py`（含 INDEX） |
| 一张经验族卡 | `domains/experiences/_TEMPLATE-family.md` | `samples/experience-family-sample.md` | `_family_field_lint.py` + `_family_members_lint.py` |
| 一条坑 | `task_cards/memory/PITFALLS.template.md` | `task_cards/memory/PITFALLS.md` | `_pitfalls_id_lint.py` |
| 全局记忆三件 | `task_cards/memory/{INVENTORY,TODO}.template.md` + `README.md` | — | — |

## 首次使用的两个开关动作（漏了会"什么都没发生"）

```bash
cp -r .aios-sample .aios    # Windows: xcopy /E /I .aios-sample .aios
# 重启宿主；然后有卡占用的会话里应出现：【AI-OS · 决策 · <域>能力】 … → capabilities/domain-*.md
```
⚠️ `.aios/inject_probe.json` 必须含 `"session": "*"` —— 只写 `{"enabled":true}` 会让**整块注入静默失效**（P103，已踩过）。

## 已知不在这份发布物里

作者的真实任务卡 / 成功账本 / 个人项目交付物 / 第三方 skill 原文 —— 详见 `RELEASE.md §四`。
