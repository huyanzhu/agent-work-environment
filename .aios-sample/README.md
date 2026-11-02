# .aios-sample/ — 运行期开关样本（**首次使用必须初始化**）

> 本仓不含 `.aios/`（运行期状态目录，被 gitignore）⇒ **直接 clone 就是零注入**。
> `.aios/` 是**本机目录**、不进版本控制；这个目录是它的开关样本。

## 初始化（一次即可）

```bash
cp -r .aios-sample .aios          # Windows: xcopy /E /I .aios-sample .aios
```

然后**重启宿主**（插件在启动时装载）。

## 首次启动的唯一口径

1. **`.aios/` 缺失 ⇒ `inject_probe.json` 不存在 ⇒ 外层注入门关**：阶段注入、节点注入、提醒**都不发生**（零注入）。
2. **`phase_inject.json` 缺省 = 开**（只是第二道门）；**域注入跟卡上声明**（`domainInject` 缺省 `off`）；**经验召回缺省关**。
3. **首次使用 = `cp -r .aios-sample .aios` + 重启宿主**；此后一切按本目录各文件的显式值运行。

没有"两种都行"：不初始化 `.aios/`，就是零注入。

## 五份开关

| 文件 | 作用 | 样本值 |
|---|---|---|
| `inject_probe.json` | **注入总闸**（阶段注入 / 节点注入 / 提醒的外层门） | `{"enabled":true,"session":"*","allowSubagent":true}` |
| `phase_inject.json` | 阶段注入（S1 占卡后 / S2 首次改动 / S4 收口） | `{"enabled":true}` |
| `cap-cells.json` | 域能力注入；`domainInject:"on"` = 跟随卡上声明 | `{"enabled":false,"max":1,"form":"intro","claimHint":"generic","domainInject":"on"}` |
| `experience_recall.json` | 失败后经验召回；**同时是节点注入（N1/N2/N3）的门** | `{"enabled":true}` |
| `r3-wake.json` | R3 收工维护唤醒（fire-once） | `{"enabled":false}`（默认关，需要时再开） |

> `inject_probe.json` **必须带 `session`**（`"*"` = 本机所有会话）——只写 `{"enabled":true}` 会让**整块注入静默失效**。
> `enabled` 必须是**严格 `true`**；`session` 为空串 / 缺失 / 非法类型 ⇒ **不匹配任何会话**（fail-closed）。
> `cap-cells.json` 的 `enabled` / `form` 是惰性字段（无消费者），保留只为形状兼容。

## 子会话也会收到注入（已知门）

`inject_probe.json` 的 `allowSubagent` **缺省 true** ⇒ 子 agent（subagent 会话）**也会收到**注入（样本里显式写 `true`，便于核对）。
只想让主会话收：写 `"allowSubagent": false`（改后不用重启）。
⛔ 这是设计门，不是故障；判读前先看这个字段。

## 召回的 query 可能被乱码污染（已知失真）

失败输出是 GBK/乱码时，召回 query 也是乱码 ⇒ 词面检索 0 命中。**0 命中 ≠ 经验库没有**，先看探针里的 `query`。

## 命中 ≠ 采用

探针只记「注入/召回」，不记「有没有被采用」。收工时在卡 `## Outcome` 填「投递采用」（见卡模板）。

## 验收判据（3 条 · 都在本包可复现）

1. 会话里出现 `【AI-OS · 决策 · <域>能力】` 开头的注入消息（格式逐字 3 行：标题 / `intro` 原文 / `→ capabilities/<域能力>.md`）
2. 探针 `.aios/_aios-activation.probe.log` 出现 `phase-inject{state:"injected",basis:"declared"}`
3. 卡上**先记能力**再开工：`python tools/task_card.py capability <项目>/<TASK-ID> --name domain-xxx --why "…"`
   （⛔ 没声明能力就不会注入 —— 这是设计，不是故障）
