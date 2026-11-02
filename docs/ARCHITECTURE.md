# ARCHITECTURE — 当前架构

> 本文只描述**当前这个发布物里真实存在的结构**：宿主怎么触发、Runtime 怎么判定、Python 侧怎么检索、注入了什么。
> 模块级规矩（改代码前必读）在 [`../runtime/README.md`](../runtime/README.md)；开关与判据边界在 [`../maintenance-skills/runtime-switches.md`](../maintenance-skills/runtime-switches.md)。

## 一、全貌

```
┌───────────────────────────── 宿主（DSH / Claude-Code 形态）─────────────────────────────┐
│ 会话事件：session-start · pre/post-execute · turn-end · 工具调用与结果                   │
└──────────┬──────────────────────────────────────────────────────────▲──────────────────┘
           │ 事件 / 工具名 / 卡状态（⛔ 不取对话正文）                    │ 注入（user 消息）
           ▼                                                           │
┌──────────────────────────────────────────────┐                       │
│  runtime/aios-activation.ts  （入口 · 插件）   │                       │
│  ── 会话状态 / 焦点卡 / 阶段判定 / 去重限频     │───────────────────────┘
└───┬──────────────┬───────────────┬───────────┘
    │ ① 阶段注入    │ ② 节点注入     │ ③ 经验召回
    │  S1/S2/S4     │  N1/N2/N3      │  工具失败被分类后
    │  按卡上声明    │  经验族卡       │  词面通道（不依赖 fastembed）
    │               │  门 = 经验召回   │
    ▼               ▼               ▼
┌──────────────────────────────────────────────────────────────┐
│ 检索桥 spawnJson（Python 子进程 · 超时 · stdout/stderr 字节上限）│
│ retrieval-request/v1  →  candidate-set/v1                    │
└───────────┬──────────────────────────────────────────────────┘
            ▼
┌──────────────────────────────────────────────────────────────┐
│ 语料层：capabilities/（8 域 50 片） · domains/experiences/（6 张族卡）│
│         task_cards/memory/PITFALLS.md（发布版 111 条）              │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│ 记忆层：task_cards/active（工作记忆） · task_cards/memory（全局）│
└──────────────────────────────────────────────────────────────┘
            ▲ 写回（Stop hook / 收工记账）
┌───────────┴──────────────────────────────────────────────────┐
│ 机械闸门（tools/probes/*.py）：能力字段+INDEX · 族卡结构 · 族卡成员 │
│                               · PITFALLS 编号 · 静默 catch 可观测化│
└──────────────────────────────────────────────────────────────┘
```

## 二、15 个模块与职责

入口 `runtime/aios-activation.ts` 自身只做：插件生命周期（`name` / `inject` / `apply`）、工具注册（`auto_capability`）、事件接线、`__selftest` 钩子。**判定与渲染都在下面 15 个模块里。**

| 层 | 模块 | 职责 |
|---|---|---|
| **L0 底座** | `diagnostics/probe.ts` | 探针 `emit` / 开关文件读取缓存（按 mtime+size 失效）/ 状态目录与脚本路径解析（三级兜底）/ 文本与路径工具（`clip` / `stripRepoPaths` / `mono` / `userMessageOf`）/ 卡名正则 `CARD_NAME_RE` / `noteCatchFail` |
| **L1 叶子** | `session/session-state.ts` | 会话身份与内存态：`SESSIONS`、`sessionIdOf`、`identityOf`、`TaskCursor` / `Occupancy` / `PendingDelivery` 类型 |
| | `session/work-context.ts` | 工作上下文：最近动作窗口、失败分类与连败（`failKindOf` / `failStreakOf`）、`ActivityItem` |
| | `delivery/pending-delivery.ts` | **投递开关与探针文件的唯一读取处**：delivery / reminder / shadow / stage4 / inject 五类探针文件 + 会话匹配 `sessionAllowsProbe` |
| | `retrieval/python-bridge.ts` | 子进程桥：`spawnJson` / `spawnJsonAsync`、超时、stdout 8 MiB / stderr 256 KiB 上限、**失败分类** |
| | `retrieval/experience-recall.ts` | 经验召回策略：开关、配额、最小分、turn gap、会话去重 |
| **L2 领域** | `session/lifecycle.ts` | 卡生命周期：`focusCardOf` / `myOccupiedCards` / `listCardFiles` / `reminderFor` / 卡字段读取 |
| | `activation/phase-policy.ts` | 阶段判定与开关策略：`phaseOf`、`phaseInjectEnabled`、`capCellsConfig`、`domainInjectEnabled`、`missingCapRecordsOnCard` |
| | `activation/declared-domain.ts` | **声明驱动**域注入：读卡上「使用的能力」→ 注入该域能力 `intro` + 路径（⛔ 不猜域） |
| | `activation/phase-candidates.ts` | 检索请求构造与候选渲染：轴（domain/help/concern）、打分权重、预算、`renderPhaseCandidates` |
| | `retrieval/request-builder.ts` | 失败语义与查询构造：`recallTriggerOf`、`buildExperienceQuery`、候选摘要与来源判定 |
| | `maintenance/r3-wake.ts` | R3：空闲唤醒、维护清单、`disarmR3Wake` / `setR3DisarmPending` |
| | `delivery/node-hints.ts` | 节点提示（N1 改语料 / N2 重建索引 / N3 跑回归门…）的判定与文案 |
| **L3 组合** | `delivery/probe-state.ts` | 一次注入的状态机：取焦点卡 → 组请求 → 调检索桥 → 收候选（供组合层用） |
| | `delivery/phase-injection.ts` | **组合层**：pre/post-execute 上的注入编排 —— 阶段 / 节点 / 召回 / 提醒统一出口与去重 |
| **入口** | `aios-activation.ts` | 插件面 + 工具注册 + 事件接线 |

> 同目录另有 `aios-observe.ts` / `aios-signals.ts` 两个**独立观测插件**：只读事件、不注入、与本插件互不 import；
> 以及 `tests/activation.test.mjs`（208 项自测）。

## 三、依赖图与分层规则

```
L0  diagnostics/probe            （⛔ 零本地 import，只有 node:*）
L1  session/session-state  ⇄ session/work-context      （双向仅 type）
    delivery/pending-delivery    → probe
    retrieval/python-bridge      → probe
    retrieval/experience-recall  → probe
L2  session/lifecycle            → probe · session-state
    activation/phase-policy      → probe · session-state(type)
    activation/declared-domain   → probe · phase-policy · lifecycle · session-state
    activation/phase-candidates  → probe · phase-policy · declared-domain · request-builder · session/*
    retrieval/request-builder    → probe · python-bridge · pending-delivery · session/*
    maintenance/r3-wake          → probe · lifecycle · session-state
    delivery/node-hints          → probe · session-state(type) · probe-state(type)
L3  delivery/probe-state         → probe · phase-policy · phase-candidates · request-builder · python-bridge · session/*
    delivery/phase-injection     → 以上全部
入口 aios-activation.ts          → 全部
```

**四条依赖硬规则**（改代码前必读；运行期另有五条，见 `runtime/README.md`）：

1. ⛔ **模块不得 import 入口**（反向依赖）。共享件下沉到 L0/L1。
2. ⛔ **`activation/* → maintenance/*` 禁止**；`delivery/* ↔ maintenance/*` 也不得有横向依赖。
3. ⛔ **可变 `let` 不跨模块直接赋值** —— 用 setter（ESM 只读绑定会抛错，且常被 `catch` 吞掉）。
4. **类型 import 必须 `import type`** —— 类型在 Node 擦除后不是值导出。

架构校验命令（都在 `tools/probes/` 内、随发布）：

```bash
python tools/probes/_unbound_refs_lint.py
python tools/probes/_tsc_lint.py
```

## 四、四个设计约束

1. **Runtime 与 Retrieval 分离**：TypeScript 侧只决定"**何时触发、注入什么形态**"；"**检索什么、怎么打分**"在 Python 侧（`tools/probes/_retrieval_request_probe.py`）。两侧用版本化 JSON 契约通信。
2. **不猜域**：能力注入跟随**卡上声明**（探针里是 `basis:"declared"`）；卡上没声明 ⇒ 本拍不注入。这是设计，不是故障。
3. **失败必须分类**：子进程结局分为 `spawn-error` / `timeout` / `empty-stdout` / `bad-json` / `empty-object` / `child-error` / `output-too-large` / `stdin-error` / `ok`。⛔ **不把空输出当"零候选"**。
4. **静默要可查**：`catch` 必须落一条 `catch-fail` 探针（限频）；少数**故意静默**处（探针通道自身、`kill` 失败）写明理由。

## 五、与 Python 侧的契约

| 项 | 值 |
|---|---|
| 请求 | `retrieval-request/v1`（stdin，UTF-8，`PYTHONIOENCODING=utf-8` 强制） |
| 响应 | `candidate-set/v1`（stdout，JSON） |
| 同步超时 | `WORK_REPORT_RETRIEVAL_TIMEOUT_MS = 1500`（超时降级为只回 ack） |
| 输出上限 | stdout **8 MiB** · stderr **256 KiB**（超限即 kill 并记 `output-too-large`） |
| 入口脚本 | `tools/probes/_retrieval_request_probe.py`（机制探针目录）· `tools/experience_push.py`（工具目录） |

> 两个目录的解析函数是分开的（`resolveScript` vs `resolveToolScript`）：机制探针与工具脚本不能混。

## 六、运行期数据与环境

| 路径 | 是什么 | 是否随发布 |
|---|---|---|
| `.aios/` | 运行期数据：开关 / 探针日志 / 焦点卡 / R3 标记 | ⛔ 不随发布（gitignore） |
| `.aios-sample/` | 上面那份目录的**开关样本**，首次使用复制为 `.aios/` | ✅ 随发布 |
| `scratch/` | 隔离自测与临时产物 | ⛔ 不随发布（gitignore） |
| `task_cards/` | 工作记忆（卡 + `.log` + 全局记忆） | ✅ 结构随发布，真实卡不随发布 |

状态文件解析有**三级兜底**（`resolveStateFile` / `resolveScript`）：首选 `.aios/<新名>` ▸ 兼容 `.aios/<旧名>` ▸ `scratch/<旧名>` ▸ 回落首选名。
所以升级不会因为文件改名而丢状态；代价是"兼容位"也参与判据——排查时先确认命中的是哪一个。
