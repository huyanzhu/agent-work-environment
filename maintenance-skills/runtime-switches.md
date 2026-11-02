# Runtime 开关清单（权威 · 受管）

> **为什么要有这份**：`.aios/` 整个目录被 `.gitignore` 忽略 ⇒ 开关状态**只在本机**，新克隆/换机只有缺省值。
> 所以「有哪些开关、缺省是什么、首次使用该写什么」必须落在**版本控制里**（就是本文件 + `.aios-sample/`）。
>
> 纪律：改开关**不用重启**（运行时按 mtime+size 懒读，改即生效）；写 JSON 一律 **BOM-less**；改完**读最后一条 `ev=apply` 或复跑一次探针**确认生效。

## 〇、首次使用：先初始化，再谈开关

```bash
cp -r .aios-sample .aios          # Windows: xcopy /E /I .aios-sample .aios
# 然后重启宿主（插件在启动时装载）
```

**唯一口径**：

1. **`.aios/` 缺失 ⇒ `inject_probe.json` 不存在 ⇒ 外层注入门关**：阶段注入、节点注入、提醒**都不发生**（零注入）。
2. **`phase_inject.json` 缺省 = 开**（只是第二道门）；**域注入跟卡上声明**（`domainInject` 缺省 `off`）；**经验召回缺省关**。
3. **首次使用 = `cp -r .aios-sample .aios` + 重启宿主**；此后一切按 `.aios-sample` 各文件的显式值运行。

## 一、生产开关（4 个）

| 文件 | 作用 | 缺省（文件缺失时） | `.aios-sample` 建议值 | 代码锚点 |
|---|---|---|---|---|
| `.aios/cap-cells.json` | `max` = 检索候选上限 · `claimHint` = 开工提示文案 · `domainInject` = **声明驱动的域注入** | `max=2` · `claimHint="generic"` · `domainInject="off"` | `{"max":1,"claimHint":"generic","domainInject":"on"}` | `capCellsConfig` · `phaseMaxCandidates` · `capNudgeEnabled` |
| `.aios/phase_inject.json` | **阶段注入总闸**（含检索注入；也是域注入的总闸） | **开** | `{"enabled":true}` | `phaseInjectEnabled` |
| `.aios/experience_recall.json` | 失败签名触发的经验召回 | **关** | `{"enabled":true}` | `experienceRecallEnabled` |
| `.aios/r3-wake.json` | **R3 空闲唤醒 / 记忆维护** | **关**（缺失 / 非严格 `true` ⇒ 关） | `{"enabled":false}`（需要时再开） | `r3WakePath` · `disarmR3Wake` |

> `domainInject` 的语义：`on` = **跟随卡上声明**（卡上没声明就不注入）；`off` = 连声明也不读。
> ⚠️ 关掉 `domainInject` **不等于"不注入"**，而是回落到检索候选注入；想测"完全无注入"必须同时关 `phase_inject` 或移走 `inject_probe.json`。

## 二、注入总闸与探针通道（5 个）

| 文件 | 是什么 | 缺省（文件缺失时） | `.aios-sample` 建议值 |
|---|---|---|---|
| `.aios/inject_probe.json` | **注入总闸**：阶段注入 / 节点注入 / 提醒的**外层门** | **关**（不存在 ⇒ 零注入） | `{"enabled":true,"session":"*","allowSubagent":true}` |
| `.aios/reminder_probe.json` | 提醒型递送（周期提醒） | **关** | 不带（需要时自建） |
| `.aios/shadow_probe.json` | shadow dispatch 对照探针 | **关** | 不带 |
| `.aios/stage4_probe.json` | 自动发现（stage4）投递探针 | **关** | 不带（`STAGE4_ENABLED=false` 已在代码里关） |
| `.aios/delivery_probe.json` | 静态 marker 投递探针 | **关** | 不带 |

> `inject_probe.json` 必须带 `session`（`"*"` = 本机所有会话）：只写 `{"enabled":true}` 会让**整块注入静默失效**。
> `enabled` 必须是**严格 `true`**；`session` 为空串 / 缺失 / 非法类型 ⇒ **不匹配任何会话**（fail-closed）。
> **`experience_recall.json` 同时是「节点注入」的门**（N1 改语料 / N2 重建索引 / N3 跑回归门）——这也是它缺省关时节点提示不出现的原因。

## 三、状态文件（⛔ 不是开关，别手改）

| 文件 | 是什么 |
|---|---|
| `.aios/focus-card.json` | 当前焦点卡（由 Runtime 写） |
| `.aios/r3-wake-state.json` | R3 每会话一次性标记 |
| `.aios/_aios-activation.probe.log` | 探针日志本体（50 MiB 阈值轮转，`.gz` 归档） |

## 四、环境变量（16 个 · 覆盖同名开关，测试/隔离用）

```
AIOS_STATE_DIR · AIOS_PROBES_DIR · AIOS_ROOT · AIOS_CARDS_DIR · AIOS_PROBE_PATH
AIOS_PHASE_INJECT · AIOS_EXPERIENCE_RECALL · AIOS_INJECT_PROBE · AIOS_REMINDER_PROBE
AIOS_SHADOW_PROBE · AIOS_SHADOW_ENTRY · AIOS_STAGE4_PROBE · AIOS_STAGE4_FIELD
AIOS_STAGE4_RETRIEVAL · AIOS_DELIVERY_PROBE · AIOS_FOCUS_CARD
```

- 优先级：**环境变量 > `.aios/*.json` > 代码缺省**
- 自测一律用 `AIOS_*` 指向 `scratch/_selftest_*`（隔离纪律：**import 之前**设好）

## 五、不是文件开关的两个代码常量

| 名字 | 状态 |
|---|---|
| `STAGE4_ENABLED`（自动发现派发） | 代码常量 `false`；改成 `true` 可回退 |
| `FIRST_STEP_INJECT_ENABLED`（首拍注入） | 代码常量 `false`；代码保留可回退 |

> `cap-cells.json` 里的 `enabled` / `form` 是**惰性字段**（无消费者），保留只为形状兼容。
> `capabilities/capabilities/_archive/CELLS.md` 已归档到 `capabilities/_archive/`，⛔ 不要再找它，也不要用 `AIOS_CAP_CELLS`。

## 六、怎么核对现状

Windows（PowerShell）：

```powershell
Get-ChildItem .aios -Filter *.json |
  Where-Object { $_.Length -lt 4096 } |
  ForEach-Object { $_.Name + " = " + (Get-Content $_.FullName -Raw).Trim }
```

macOS / Linux（bash）：

```bash
for f in cap-cells phase_inject experience_recall r3-wake \
         inject_probe reminder_probe shadow_probe stage4_probe delivery_probe; do
  p=".aios/$f.json"
  if [ -f "$p" ]; then echo "$f = $(tr -d '\n' < "$p")"; else echo "$f = (缺省)"; fi
done
```

## 七、投递的三个「已知失真」（判据边界，不是故障）

> 不知道这三条，就会把「没注入 / 命不中 / 没用上」误读成能力没用或环境坏了。

### 7.1 子会话投递（`inject_probe.json` 的 `allowSubagent`）

- 运行门：`identity === 'main' || (allowSubagent && subagent)`
- **缺省 `allowSubagent=true`** ⇒ 子 agent（subagent 会话）**也会收到**阶段注入/节点注入
- 只想让主会话收 ⇒ 在该文件显式写 `"allowSubagent": false`（改后**不用重启**）
- 判读：子会话没注入时，先看这个字段是不是被显式关掉了（⛔ 不要把「关掉的开关」当成故障）

### 7.2 经验召回的 query 会被**失败输出原文**污染

- query 取自失败输出片段 ⇒ 当失败本身是编码问题（GBK/乱码）时，query 也是乱码 ⇒ 词面检索必然 0 命中
- 判读：**召回 0 命中 ≠ 经验库没有该经验**；先看 probe 里的 `query` 字段是不是乱码

### 7.3 「命中」不等于「采用」

- 探针只记「注入了/召回了」，**不记有没有被采用**
- 要算采用率 ⇒ 收工时在卡 `## Outcome` 里填一行「投递采用」（见卡模板）
- 否则只能得到否决性结论（"注入了 N 次 / 成为决策输入 0 次"）

## 八、与安全边界的关系

开关的选择本身就是安全边界的一部分：缺失/写错一律按**关**处理，不会"猜一个差不多的值"继续跑。
完整边界见 [`../docs/SECURITY.md`](../docs/SECURITY.md)。
