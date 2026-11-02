# runtime/ — 本体（插件）

> 这是 AI-OS 的**本体**：把能力与经验在**对的时机**送进 Agent 决策空间的那一层。
> 面向 Agent 的使用说明在 [`../TOOL_RUNTIME.md`](../TOOL_RUNTIME.md)；系统级架构（含与 Python 侧的边界）见 [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)。

## 一、模块与依赖（入口 + 15 模块）

```
                  ┌──────────────────────────────────────────┐
                  │ aios-activation.ts  入口：apply / 工具注册 │
                  │ export name / inject / apply / __selftest │
                  │ ⛔ 模块不得反向 import 它                  │
                  └───┬──────────────────────────────────────┘
      ┌───────────────┴──────────────┬───────────────────────────────┐
      ▼                              ▼                               ▼
diagnostics/probe            session/*                     retrieval/*
【L0 底座】                  session-state  ⇄ work-context   python-bridge  → probe
探针 / emit / 开关缓存        lifecycle      → probe          request-builder → probe · py-bridge ·
路径与脚本解析                                                   pending-delivery · session/*
                            activation/*                    experience-recall → probe
                            phase-policy       → probe · session-state(type)
                            declared-domain    → probe · phase-policy · lifecycle · session-state
                            phase-candidates   → probe · phase-policy · declared-domain ·
                                                 request-builder · session/*
                            maintenance/r3-wake → probe · lifecycle · session-state

                            delivery/*
                            pending-delivery  → probe
                            node-hints        → probe · session-state(type) · probe-state(type)
                            probe-state       → probe · phase-policy · phase-candidates ·
                                                 request-builder · python-bridge · session/*
                            phase-injection   → 以上全部（组合层）
```

**分层规则**：

| 层 | 模块 | 允许依赖 |
|---|---|---|
| **L0 底座** | `diagnostics/probe.ts` | ⛔ 任何本地模块（只有 `node:*`） |
| **L1 叶子** | `session/session-state.ts` · `session/work-context.ts` · `delivery/pending-delivery.ts` · `retrieval/python-bridge.ts` · `retrieval/experience-recall.ts` | L0，或彼此**仅 type** |
| **L2 领域** | `session/lifecycle.ts` · `activation/phase-policy.ts` · `activation/declared-domain.ts` · `activation/phase-candidates.ts` · `retrieval/request-builder.ts` · `maintenance/r3-wake.ts` · `delivery/node-hints.ts` | L0–L2 |
| **L3 组合** | `delivery/probe-state.ts` · `delivery/phase-injection.ts` | L0–L2 |
| **入口** | `aios-activation.ts` | 全部 |

**两条类型边例外**（都是 `import type`，Node 擦除后不产生运行时依赖）：

1. `session/session-state.ts` ⇄ `session/work-context.ts` —— 双向**仅 type**（会话状态与工作上下文的类型互引）。
2. `delivery/node-hints.ts` → `delivery/probe-state.ts` —— 仅 type（`NodeId`）。

**五条硬规则**（每条都踩过代价）：

1. ⛔ **模块不得 import `aios-activation.ts`**（反向依赖）。共享件下沉到 L0/L1（如 `name` / `userMessageOf` / `readSwitchCached` / `stripRepoPaths` / `isExecToolName` / `tokenSetOf` 都在 `diagnostics/probe.ts`）。
2. ⛔ **`activation/* → maintenance/*` 禁止**；`delivery/* ↔ maintenance/*` 也不得有横向依赖。两层共享的判据下沉到 `session/lifecycle`。
3. ⛔ **可变 `let` 不能跨模块直接赋值**：模块级 `let` 搬走后，外部只能走 setter（如 `setR3DisarmPending()`）。直接 `= null` 会撞 ESM 只读绑定，抛错且常被业务 `catch` 吞掉 ⇒ 单测红。
4. **类型 import 必须写 `import type`**：类型在 Node 擦除后**不是值导出**，写成值 import 会在运行时抛 `does not provide an export named`。
5. **纯函数 + 单测，接线走真实 handler**：纯函数单测绿 ≠ 接线对。

> 改完依赖跑这几条（全部可复现）。⚠️ 前两条在本地开发目录 `scratch/`（不随发布），发布物里至少跑后三条：
> ```bash
> python scratch/_module_graph.py              # import 图 + 反向/横向依赖 + 重复导出（应：反向 0 · 横向 0）
> python scratch/_cycle_check.py               # 运行时环（应只有 session-state↔work-context 的 type 环）
> python tools/probes/_unbound_refs_lint.py    # 未绑定引用
> python tools/probes/_tsc_lint.py             # tsc strict 零基线
> python tools/probes/_silent_catch_lint.py    # 静默 catch 可观测化 + 调用绑定
> ```

## 二、通道地图（谁在什么时候注入什么）

| 通道 | 触发时机 | 注入什么 | 开关 |
|---|---|---|---|
| **阶段注入** | S1 占卡后 / S2 实质改动后 / S4 收口时 | 能力候选（检索）或**域能力**（声明驱动） | `.aios/phase_inject.json`（**缺省开**） |
| **声明驱动域注入** | 同上，且卡上已声明域能力 | 该域能力的 `intro` + 文件路径（⛔ **不猜域**） | `cap-cells.json` 的 `domainInject`（缺省 `off`） |
| **节点注入** | 命中 N1 改语料 / N2 重建索引 / N3 跑回归门 等节点 | 对应**经验族卡**路径 + 一句纪律 | 经验召回开关（`.aios/experience_recall.json`，缺省**关**） |
| **经验召回** | 工具失败按 `trigger` 分类后 | 相关经验条目（词面通道，**不依赖 fastembed**） | `.aios/experience_recall.json`（缺省**关**） |
| **R3 运行期维护** | 空闲唤醒 / 被 takeover | 维护清单 | `.aios/r3-wake.json`（缺省**关**） |

### 这些通道什么时候真的会跑（首次启动口径）

1. **`.aios/` 缺失 ⇒ `inject_probe.json` 不存在 ⇒ 外层注入门关**：阶段注入、节点注入、提醒**都不发生**（零注入）。
2. **`phase_inject.json` 缺省 = 开**（只是第二道门）；**域注入跟卡上声明**（`domainInject` 缺省 `off`）；**经验召回缺省关**。
3. **首次使用 = `cp -r .aios-sample .aios` + 重启宿主**；此后一切按 `.aios-sample` 各文件的显式值运行。

> 即：两道门是**与**关系 —— 外层 `inject_probe.json`（存在且 `enabled:true` 且 `session` 命中本会话）与内层 `phase_inject.json`（缺省开）。
> 只有外层门开着，内层"缺省开"才有意义。
> **节点注入另算一把门**：它的门是**经验召回开关**（缺省关）——所以 `.aios/` 缺失时它同样不发生。
> 逐项开关见 [`../maintenance-skills/runtime-switches.md`](../maintenance-skills/runtime-switches.md)。

### ⚠️ 「哪些路径现在真的在跑」 vs 「已关闭」

| 路径 | 状态 | 说明 |
|---|---|---|
| `auto_capability` → 内联检索 → Python 检索器 | ✅ **主线** | **同步**调用，最长等 `WORK_REPORT_RETRIEVAL_TIMEOUT_MS = 1500` ms；超时降级为只回 ack |
| 阶段注入 · 域注入 · 节点注入 · 经验召回 | ✅ 按开关 | 见上两张表 |
| **自动发现派发（stage4）** | ⛔ **关闭** | `STAGE4_ENABLED = false`，由 `auto_capability` 内联检索替代；改成 `true` 可回退 |
| **首拍注入** | ⛔ **关闭** | `FIRST_STEP_INJECT_ENABLED = false`，代码保留可回退 |

> ⛔ 别把「自动发现」当成现行主线：现行走的是 **Agent 显式调 `auto_capability`** 或 **阶段/节点注入**，不是 Runtime 自己判断机会后派发。

## 三、改 runtime 的铁律

1. **注入段里现取依赖** —— ⛔ 别引用别处 `try{}` 块里的 `const`：`ReferenceError` 会被上层 `catch` 吞掉 ⇒ **整段注入静默失效**（零报错、零探针）。
2. **`catch` 里至少落一条失败探针** —— 否则出问题只有"什么都没发生"。闸门 `_silent_catch_lint` 会校验**调用已绑定**；只数次数会假绿。
3. **改完追加 POLICY token，重启后先读最后一条 `ev=apply` 确认加载** —— 没重启 = 跑的还是旧代码。
4. **改 `runtime/*.ts` 要 Human 授权**；且**同一批**改测试（SKIP 名单、快照断言）。
5. **搬代码**：注释要随声明走；可变 `let` 不能跨模块搬（用 setter）；类型走 `import type`；测试直接访问的导出要在主模块**再导出**；**脚本写盘前先核目标绝对路径**。

> 第 1–4 条来源见 [`../domains/experiences/runtime_change_family.md`](../domains/experiences/runtime_change_family.md)。

## 四、改它的标准流程

```
① 判定：这事该进 runtime 吗（还是 tools / 能力库 / 经验库更合适？）
② 选接线点：哪一拍注入 / 哪个 trigger 命中 / 哪个 node 判定
③ 写纯函数 + 单测（不读文件、不 spawn ⇒ 可测）
④ 接线（现取依赖 + catch 落失败探针）
⑤ 真实 handler 用例（走 apply/on 的路径，不是只调纯函数）
⑥ POLICY bump → 重启 → 读 ev=apply 验加载 → 跑探针确认真机行为
⑦ 模块归位：这个函数属于哪一层？（见 §一 分层规则；共享就上收 L0）
```

## 五、测试与读数

```bash
node runtime/tests/activation.test.mjs                      # 合计 208 项 · 通过 207 · 失败 1（S37 已知红）
python -m unittest discover -s tools/tests -p "test_*.py"    # Ran 147 tests · OK
```

- 测试**隔离**：`AIOS_*` 环境变量指向 `scratch/_selftest_*`，不碰真实卡与真实探针。
- **SKIP 是显式跳过**（如已停用判据的断言），⛔ 不是死代码。
- 探针日志：`.aios/_aios-activation.probe.log`（50 MiB 阈值轮转，归档 `*.gz`）。
- **入口导出面**有断言（`name` / `inject` / `apply` / `__selftest` / 再导出）—— 搬模块把导出面搬丢会立刻红。
- **测试面已知限制**：各模块**没有独立单测**（只经主入口 + `__selftest`）；`tsc --noEmit` 未接入（类型接线靠 `import type` 纪律 + 只读扫描脚本）。

## 六、排查顺序（注入没出现时）

```
① 初始化：`.aios/` 在吗？`inject_probe.json` 在吗（外层门）？
② 开关：phase_inject 总闸开了吗？（缺省开，但文件存在且 enabled:false 就关了）
③ 声明：卡上「使用的能力」有域能力吗？是 none / 缺行吗？（无声明 ⇒ 不注入，这是设计）
④ 去重：同阶段同能力已注过？探针里会是 state:"dup"（正常）
⑤ 加载：POLICY 尾 token 与你源码里的一致吗？（不一致 = 没重启）
⑥ 证据源：探针日志被轮转过？历史事件在 *.gz 里
⑦ 模块：跑 `_unbound_refs_lint.py` / `_tsc_lint.py`（本地开发目录还有 `scratch/_module_graph.py`）看依赖方向有没有被改歪（反向 / 未批准横向应为 0）
⑧ 子会话：`inject_probe.json` 的 `allowSubagent` 缺省 **true** ⇒ 子 agent 也会注入；没注入先看它是否被显式写成 false
⑨ 召回 0 命中：先看 probe 里 `query` 是不是乱码（失败输出被当 query ⇒ 词面必然 0 命中）
```

## 七、已知限制（如实）

- **宿主装载**：插件能被 `import`、自测通过、在本机真机装载过（`apply` POLICY 与注入到达均可查）；**干净环境（别人机器）的完整 DSH 装载仍未验证**。
- **测试面**：模块无独立单测、`tsc --noEmit` 未接入（见 §五）。
- **单测已知红**：`S37`（v4 消息源形状断言）为已知红，与注入机制无关。
- 真实浏览器/读屏行为未验（与 runtime 无关但常被一起问）。
