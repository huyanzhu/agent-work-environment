# 配置总览

> 这一页回答四件事：**有哪些开关 · 缺省是什么 · 怎么改 · 改完要不要重启**。
>
> 版本口径：本文对应 **0.1.20**。版本号的唯一事实源是 `package.json` 的 `version` 字段；
> 发布物 `package.json`、Git tag 与 `CHANGELOG.md` 标题应三处一致。
>
> 三条纪律：
> 1. **缺省保守**：文件缺失 / JSON 损坏 / 类型不对 ⇒ 按「关」处理，并在 stderr 留一行诊断（不静默）。
> 2. **开关文件运行期懒读**：改 `.aios/*.json` 或 `.claude/aios-exposure.json` **不需要重启宿主**。
> 3. **`.aios/` 不入库**（被 `.gitignore` 忽略）：新克隆必须先执行一次初始化，否则默认零注入。

## 0. 首次配置

```bash
# 1) 运行期开关：把样本目录复制成实例目录（一次即可；Windows 用 xcopy /E /I .aios-sample .aios）
cp -r .aios-sample .aios

# 2) Hook 动作开关：本仓已带保守样例（默认全关）。要启用某项，见 §2。
#    若你的发布物没有这个文件，按 §2 的完整样例新建。

# 3) 重启宿主一次：`.claude/hooks.json` 与插件在启动时读取。
#    之后改上面两个目录里的开关文件，都不需要再重启。
```

| 配置层 | 文件 | 何时读 | 改后要重启吗 |
|---|---|---|---|
| 运行期开关 | `.aios/*.json` | 运行期每次用到时懒读 | **否** |
| Hook 动作开关 | `.claude/aios-exposure.json` | 每次 hook 调用（新进程） | **否** |
| Hook 接线 | `.claude/hooks.json` | 宿主 / 插件启动时读一次 | **是** |
| 宿主路径 / 环境变量 | 进程环境 | 进程启动时 | **是**（重开宿主） |

## 1. `.aios/` 运行期开关（5 份）

> 这 5 份是 `.aios-sample/` 里的样本；复制后放在 `.aios/`。**样本值是演示值，不是全部保守缺省** ——
> 每份的代码缺省以下表为准。

| 文件 | 作用 | 代码缺省（文件缺失/非法） | `.aios-sample` 推荐值 | 怎么改 | 改后要重启吗 |
|---|---|---|---|---|---|
| `inject_probe.json` | 事件提示注入；**阶段注入的外层门**（也参与节点提示 / 提醒的早退判断） | **关**（`readInjectProbe` 返回 null） | `{"enabled": true, "session": "*", "allowSubagent": true}` | `{"enabled": true, "session": "*"}`；要子会话也收加 `"allowSubagent": true` | 否 |
| `phase_inject.json` | 阶段注入总开关（S1 占卡后 / S2 首次改动 / S4 收口） | **开**（`AIOS_PHASE_INJECT=off` 可强制关） | `{"enabled": true}` | `{"enabled": false}` 关闭；删除文件或写 `true` 打开 | 否 |
| `experience_recall.json` | 失败签名触发的经验召回 + 节点提示 | **关** | `{"enabled": true}`（推荐开） | `{"enabled": true}` 打开 | 否 |
| `r3-wake.json` | R3 空闲唤醒（卡被 takeover 后自动拉起维护） | **关**（只认严格 `true`） | `{"enabled": false}`（需要时手动开） | `{"enabled": true}` 打开；建议先确认你确实需要空闲会话被自动拉起 | 否 |
| `cap-cells.json` | 阶段候选上限 · claim 提示 · 声明驱动的域注入 | `max=1` · `claimHint=off` · `domainInject=off` | `claimHint=generic` · `domainInject=on` | 见 §1.5；`enabled` / `form` 是惰性字段（无消费者） | 否 |

### 1.1 `inject_probe.json` —— 注入外层门

```json
{"enabled": true, "session": "*", "allowSubagent": true}
```

- `session` **必须存在**：`"*"` = 本机所有会话；也可写具体会话匹配串。只写 `enabled:true` 而没有 `session`
  ⇒ 解析失败 ⇒ 整块**静默不注入**（常见坑）。
- `allowSubagent`：是否也向子 agent 会话注入。该缺省在版本间变过（有的版本 `false`，当前源码为 `true`）——
  **建议显式写，不要依赖省略**。
- 关掉 = 写 `"enabled": false` 或删除文件。它是阶段注入与事件提示的**外层门**：这里关着，阶段注入就不会发生；
  节点提示 / 提醒另有各自开关（`experience_recall.json` / `reminder_probe.json`），不由此文件单独决定。

### 1.2 `phase_inject.json` —— 阶段注入

```json
{"enabled": true}
```

- 缺省**开**；只有显式 `"enabled": false` 才关。
- 外层还要求 `inject_probe.json` 放行；两把门都开才真的注入。
- 环境变量 `AIOS_PHASE_INJECT=off` 可强制关（测试隔离用）。

### 1.3 `experience_recall.json` —— 经验召回 / 节点提示

```json
{"enabled": true}
```

- 缺省**关**；只有严格 `"enabled": true` 才开。
- 打开后：失败签名会触发经验族卡召回；发布/推送、改 runtime、改语料、重建索引、跑回归门等节点也会出提示。
- 召回 query 可能被失败输出的乱码污染 ⇒ **0 命中 ≠ 经验库没有**；先看探针里的 `query`（见
  `maintenance-skills/runtime-switches.md §七`）。

### 1.4 `r3-wake.json` —— R3 空闲唤醒

```json
{"enabled": false}
```

- 缺省**关**；只认严格布尔 `true`。UTF-8 BOM 会被读侧剥掉，但建议用无 BOM 的 UTF-8 保存。
- 关着时：卡被别的会话 takeover 后，不会有空闲会话被自动拉起做维护；维护提示只在该会话下次活动时出现。

### 1.5 `cap-cells.json` —— 候选上限 / claim 提示 / 域注入

```json
{
  "enabled": false,
  "max": 1,
  "form": "intro",
  "claimHint": "generic",
  "domainInject": "on"
}
```

- `max`：阶段候选条数上限，正整数；缺省 `1`。
- `claimHint`：`off`（缺省，claim 输出保持原文）/ `generic`（claim 尾部加通用能力提示）/ `cell`（按域给提示）。
- `domainInject`：`"on"` = 只注卡上**声明**的域能力；缺省 / 其他值 = `off`。
- `enabled` / `form`：**惰性字段**（格能力已删除，保留只为形状兼容），改它们不改变行为。
- 上例是 `.aios-sample/` 的演示值（`claimHint` 与 `domainInject` 是开的）；要保守就把这两项改成
  `"off"`，或直接删掉文件用缺省。

## 2. `.claude/aios-exposure.json` —— Hook 动作开关

### 2.1 作用与缺省

- `tools/aios-hook.py` 是 SessionStart / UserPromptSubmit / Stop 的**唯一入口**；它每次被调用时读这个文件，
  决定哪些 action 真的执行。
- **缺省全关**：文件缺失、读失败、JSON 非法、顶层不是对象、缺 `actions` 对象 ⇒ 全部 action 关闭，
  并在 stderr 留一行诊断（fail-closed，但不静默）。
- 只有 `tools/aios-hook.py` 的代码白名单里的 7 个 action 会被执行；文件里多写的名字**忽略**。

### 2.2 文件结构

```json
{
  "actions": {
    "action_name": {"enabled": false}
  }
}
```

- `actions`：**必填**，对象。
- `actions.<name>.enabled`：**只有严格布尔 `true` 才算开**；字符串 `"true"`、`1` 都不算。
- `actions.<name>.hosts`：可选，字符串数组；限定该 action 只在指定宿主生效（`"cc"` / `"dsh"`）。
  缺省或空数组 = 全宿主。
- `actions.<name>.event` / `.kind`、顶层的 `_role` / `_discipline` / `_enable_order` / `_how_to_enable`：
  **只是给人看的元数据，代码不读**。实际事件与类型由 `tools/aios-hook.py` 的 `ACTIONS` 白名单决定；
  JSON 不支持注释，说明可以放在这些键里，也可以放在本文。

### 2.3 七个 action

| action | 事件 | 类型 | 样例缺省 | 开启后会发生什么 |
|---|---|---|---|---|
| `task_recovery` | SessionStart | 注入 | `false` | 会话开始注入可恢复的任务卡、Goal、下一步与路径 |
| `material_discovery` | UserPromptSubmit | 注入 | `false` | 用本轮 prompt（+ 唯一确定卡的 Goal）检索经验 / 能力候选 |
| `field_candidates` | UserPromptSubmit | 注入 | `false` | 卡字段驱动能力候选（Top-3，池过窄则不注） |
| `ownership_lost` | UserPromptSubmit | 注入 | `false` | 本会话曾占用、当前已不占用的卡 ⇒ 注入收工维护清单 |
| `r3_notice_start` | SessionStart | 注入 | `false` | 每会话一次告知 R3 空闲唤醒的开 / 关状态 |
| `r3_notice_lost` | UserPromptSubmit | 注入 | `false` | 卡被别的会话 takeover 且 R3 关 ⇒ 每卡一次告知 |
| `wrapup_writeback` | Stop | 写回 | `false` | 自动写回任务卡 Event Log 与样例账本事实 |

### 2.4 建议的开启顺序

1. **先开写回型** `wrapup_writeback`：它只写「发生了什么」，不污染观察，先让收工记账成立。
2. **再逐个开注入型**：`task_recovery` → `material_discovery` → `field_candidates` → R3 两条。
3. **一次只开一个**，用探针（`.aios/_aios-activation.probe.log`）确认归因后再开下一个；
   同时开多个会失去「哪条注入真的有用」的判断力。
4. 子会话收不到注入时，先看 `inject_probe.json` 的 `allowSubagent`，⛔ 不要先怀疑能力库。

### 2.5 生效方式与已知边界

- **改即生效，不需要重启**：每次 hook 调用都是新进程，重新读文件。这正是把开关放在这里、而不是
  `.claude/hooks.json` 里的原因（`hooks.json` 只在宿主启动时读一次）。
- **`hosts` 门依赖宿主环境**：DSH 托管进程通常会向子进程导出 `DSH_*`；若 hook 子进程看不到这些变量，
  会被判成 `cc`。此时 `hosts` 门可能拦不住，需直接写 `"enabled": false` 硬关。
- **写回型会改文件，注入型会改模型上下文**：先读 §2.4，再逐项打开。

## 3. 环境变量

> 完整列表（16 个）与优先级、测试隔离用法见
> [`maintenance-skills/runtime-switches.md`](../maintenance-skills/runtime-switches.md) §四。
> 这里只列最常用的一组；**⛔ 不在此复制全部细节**。

| 变量 | 作用 | 缺省 | 怎么改 | 改后要重启吗 |
|---|---|---|---|---|
| `AIOS_ROOT` | 覆盖仓库根（开关 / 卡片 / 探针的解析基准） | 插件自身位置 | 设为目标仓库绝对路径 | 是（进程环境） |
| `AIOS_STATE_DIR` | 覆盖运行期状态目录（默认 `<root>/.aios`） | `<root>/.aios` | 指向隔离目录（测试用） | 是 |
| `AIOS_PHASE_INJECT` | `off` = 强制关阶段注入 | 未设置（按文件缺省） | 设 `off` | 是 |
| `AIOS_EXPERIENCE_RECALL` | `off` = 强制关经验召回 | 未设置 | 设 `off` | 是 |
| `AIOS_FOCUS_CARD` | 覆盖焦点卡文件路径（hook 诊断用） | `<root>/.aios/focus-card.json` | 设为文件路径 | 是 |
| `AIOS_HOOK_STATE_DIR` | hook 幂等状态的兜底目录 | `<root>/.aios` 不可写时才用 | 设为可写目录 | 是（需让宿主进程带上新环境） |
| `DSH_*` / `CLAUDE_SESSION_ID` | 宿主提供的会话 / 宿主标识 | 由宿主注入 | ⛔ 不要手写伪造 | — |

- 优先级：**环境变量 > `.aios/*.json` > 代码缺省**。
- 自测请把 `AIOS_*` 指向 `scratch/` 下的隔离目录，并在 **import / 启动之前**设好。

## 4. 改完要不要重启（速查）

| 你改了什么 | 要重启吗 | 怎么确认生效 |
|---|---|---|
| `.aios/*.json` 任一开关 | **否** | 改完触发一次对应事件，看 `.aios/_aios-activation.probe.log` 最后一条 `ev=apply` / `ev=inject` |
| `.claude/aios-exposure.json` | **否** | 看 hook 的 stderr 诊断；开启的 action 应不再出现「关闭 ⇒ 跳过」 |
| `.claude/hooks.json` | **是** | 重启宿主后，事件能调用到 `tools/aios-hook.py` |
| 插件 / runtime 代码 | **是** | 重启宿主后看插件是否装载 |
| 环境变量 | **是** | 重开宿主后让进程重新读环境 |

## 5. 校验配置（可复制）

```bash
# 1) Hook 动作开关：必须是合法 JSON
python -c "import json,io; json.load(io.open('.claude/aios-exposure.json',encoding='utf-8'))"

# 2) 接入自检：仓库完整性 / hook 路径 / python / node / DSH home（默认只预演，不写文件）
python tools/install.py --list

# 3) 发布树完整性（在已组装的发布树根目录执行）
python tools/probes/_release_manifest.py --root .                  # 生成 MANIFEST.sha256
python tools/probes/_release_manifest.py --root . --verify MANIFEST.sha256
```

> `.claude/hooks.json` 与 `tools/aios-hook.py` 的路径约定：前者每个事件调用
> `python <项目根>/tools/aios-hook.py <Event>`；后者以自身位置推项目根
> （`ROOT = dirname(dirname(__file__))`），再读 `<ROOT>/.claude/aios-exposure.json` 与 `<ROOT>/.aios/`。
> 两种写法（`$<你的项目目录> 或本仓库绝对路径）都指向同一个项目根，约定一致。
