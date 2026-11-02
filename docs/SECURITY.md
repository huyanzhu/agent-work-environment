# SECURITY — 安全边界

> 这份文件回答：**这套东西信任什么、不信什么、出错时往哪边倒**。
> 一句话：**fail-closed**（缺失 / 写错 / 不认识 ⇒ 一律按"关"或"拒绝"处理），而不是猜一个差不多能跑的值。

## 一、信任模型

| 项 | 事实 |
|---|---|
| 部署形态 | 跑在你 Agent 工作目录里的插件（`runtime/aios-activation.ts`）+ 本机 CLI 工具（`tools/`） |
| 运行身份 | 与你的 Agent 同一个 OS 用户；没有特权提升，也没有额外沙箱 |
| 网络 | **不联网**：检索走本地 Python 子进程；不建 telemetry、不外发数据 |
| 数据面 | `.aios/`（运行期：开关 / 探针 / 焦点卡）· `task_cards/`（工作记忆）；前者被 `.gitignore` 忽略，不随仓库发布 |
| 信任的输入 | 宿主给的事件（会话 / 工具名 / 结果）与**本机文件系统** |
| 不信任的输入 | 对话正文（⛔ 不读）、用户拼出来的路径（⛔ 不直接拼进路径） |

## 二、fail-closed 一览

| 场景 | 行为（倒向哪边） | 依据 |
|---|---|---|
| `.aios/inject_probe.json` 不存在 | **零注入**（阶段 / 节点 / 提醒全不发生） | `readInjectProbe` 返回 `null` |
| `enabled` 不是**严格 `true`** | 关 | 同上 |
| `session` 为空串 / 缺失 / 非法类型 | **不匹配任何会话** | `parseProbeSessions` → `null` |
| 开关 JSON 解析失败 | 回落缺省，不抛错 | `readSwitchCached(..., fallback)` |
| `.aios/phase_inject.json` 不存在 | **开**（唯一"缺省开"的开关，但仍受外层门约束） | `phaseInjectEnabled` |
| 卡模板值不认识 | **报错且不落卡**（⛔ 不静默回落） | `task_card.py` |
| `--project` 越界 / 非法 | **拒绝**（不建卡） | `_project_problem` |
| 卡名不符合形状 | 不读（正则白名单） | `CARD_NAME_RE` |
| 工具脚本不在 `tools/` 下 | **退出**（`FAIL-CLOSED`） | `tools/_root_guard.py` |
| 根不是 AI-OS 结构树 | **退出**（`FAIL-CLOSED`） | 同上 |
| 检索子进程空 stdout | 记 `empty-stdout`，**不当作零候选** | `python-bridge.ts` |
| 子进程输出超上限 | kill + 记 `output-too-large` | 同上 |

## 三、路径边界（越界防护）

1. **状态文件路径不接受外部输入**：所有 `.aios/*.json`、探针日志、焦点卡的路径都由**固定常量名**拼 `aiosStateDir` 得到；`aiosStateDir` 只会是 `<仓库根>/.aios`（不存在时回落 `<仓库根>/scratch`）。没有任何一处把用户输入拼进路径。
2. **脚本路径固定目录**：`resolveScript` 只解析 `tools/probes/`（以及兼容位 `.aios/` / `scratch/`）；`resolveToolScript` 只解析 `tools/`。机制探针与工具脚本不混用解析函数。
3. **卡名白名单**：读取侧用 `CARD_NAME_RE = /^(?:TASK-\d{8}-\d{3}|T\d{3}-[^.]+)\.md$/` —— 只有这个形状的卡名会被读，`..` 与路径分隔符无法进入。
4. **项目名当"名字"而不是"路径"**：`--project` 拒绝绝对路径 / 盘符 / UNC、拒绝 `..` 路径段、拒绝路径分隔符与 Windows 非法字符（`<>:"|?*`）与控制字符、拒绝前后空格与尾随点，最后用 `commonpath` 兜底断言仍在 `task_cards/active` 之下。
5. **工具自带结构断言**：`_root_guard.py` 在任何工具启动时断言"脚本位于 `tools/` 下"且"根目录是 AI-OS 结构树（`AGENTS.md` + `capabilities/INDEX.md` + `domains/patterns`）"，否则立即 `exit` 非零。防止仓库被搬到非 AI-OS 树后**静默读错语料**。

## 四、注入边界

- 注入 = 往会话里追加一条 **user 文本消息**。它**不改**任务卡、不改候选、不改工具行为、不改状态机。
- 只注入「路径 + 一句纪律 + `intro`」，不注入全文；摘要按字符上限截断。
- 注入内容在开关关闭时**只落探针**（宿主上下文零变化）。
- ⛔ **不落推理原文**：观测插件（`aios-signals.ts`）显式丢弃 `reasoning-delta` / `text-delta` / `argumentsDelta` 的内容，只保留类型、长度与时序。
- 工具名可记；工具参数只记**脱敏摘要**（`stripRepoPaths` 去掉本机绝对路径）。

## 五、子进程边界

| 项 | 值 |
|---|---|
| 启动方式 | `python <固定脚本> ...`，stdin 传 JSON |
| 编码 | 强制 `PYTHONIOENCODING=utf-8` · `PYTHONUTF8=1`（不依赖宿主 locale） |
| 超时 | 注入通道 1500 ms；召回通道有自己的预算（超时即 kill 并分类） |
| 输出上限 | stdout **8 MiB** · stderr **256 KiB**（超限即 kill + 记 `output-too-large`） |
| 结局分类 | `spawn-error` / `timeout` / `empty-stdout` / `bad-json` / `empty-object` / `child-error` / `output-too-large` / `stdin-error` / `ok` |

## 六、数据与隐私

- `.aios/` 与 `scratch/` 被 `.gitignore` 忽略：开关、探针日志、焦点卡**不进版本控制**。
- 探针日志是**本机明文**：记录事件、截断摘要、失败输出片段（可能含文件路径与命令片段），按 50 MiB 阈值轮转并 `.gz` 归档。⛔ 分享前自行脱敏。
- 真实任务卡与账本是**工作记忆**，不随发布；发布物里的卡与账本是虚构样例。
- 发布物由组装器脱敏（姓名 / 邮箱 / 本机绝对路径 / 个人项目名）；组装器本身**不随发布**（它含排除清单）。

## 七、不承诺的部分（威胁模型之外）

- ⛔ **不防同一 OS 用户**：能读这个仓库的人就能读 `.aios/`。不做加密、不做权限隔离。
- ⛔ **不防恶意宿主**：插件信任宿主给的事件与工具名；宿主被攻陷时本插件不提供额外保护。
- ⛔ **不做网络访问控制**：因为它不联网。
- ⛔ **它不是"安全产品"**：这里的安全边界是「**别把误配当正常、别让路径越界静默写错地方**」，不是对抗有权限的攻击者。

> 与"当前限制"配套阅读：[`LIMITATIONS.md`](LIMITATIONS.md)；开关的逐项缺省值：[`../maintenance-skills/runtime-switches.md`](../maintenance-skills/runtime-switches.md)。
