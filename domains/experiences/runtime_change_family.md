---
title: 改 Runtime/注入管道时（改本体 · 加触发点 · 写注入段都算）
family: Runtime 改造
form: inject
status: pilot
trigger: 改 runtime, aios-activation, 注入段, post-execute, pre-execute, 触发点, 探针, emit, notify, POLICY, 重启, ReferenceError, try catch, spawn, 解析, 节流
keywords: runtime, aios-activation, ts, post-execute, pre-execute, inject, trigger, emit, probe, policy, restart, referenceerror, catch, spawn, frontmatter, regex, throttle, session
alias: ReferenceError 被吞, 整段注入静默失效, 零探针, catch 吞异常, spawn 级联假失败, \s* 跨行吞行, 块式列表读成 1 条, 订阅不存在事件, 滚动窗口抖动刷屏, 裸 ID 正则, emit 缺 session, knownCardKeys 空, 卡 key 带 .md, POLICY 没升, 待重启, 注入没出现也没报错, 像是被吞了, 提醒每隔几步重复一次
---

改 `runtime/*.ts`（或它的注入/触发管道）时，先对号入座；⛔ 不要以为"单测过了就没问题"——这类坑的典型形态是**零报错、零探针、整段静默失效**。

**做法 A · 注入段的作用域与异常（P69/P67）**
- 注入段里用了**前一个 `try{}` 的块级 `const`** ⇒ `ReferenceError` 被外层 `catch` 吞掉 ⇒ **整段注入静默失效**（连带吞掉同次投递的其它来源）→ 注入段内**现取**依赖；`catch` 里**至少落一条失败探针**
- 在 `post-execute` 注入段新增 `spawn`（python/网络）⇒ 未隔离会让多个异常用例**级联假失败** → 测试文件顶部设 `AIOS_*='off'`，运行时**每次触发时重读** env

**做法 B · 解析与节流（P70/P49）**
- frontmatter/键值解析用 `\s*` 会**跨行**吞掉下一行（块式 `- 项` 被读成 1 条）→ 冒号后空白一律 `[ \t]*`；块式列表逐行解析 + 用已知条数对账
- 用"当前水平状态"做投放节流 ⇒ 状态抖动就刷屏 → 用**升沿事件 + 已发集合**，验收判据 = 交替 20 步注入次数 ≤ 事件种类数

**做法 C · 加新触发点的实现坑（P83/P84）**
- 命令字面量识别必须覆盖**工具接受的全部调用形式**（如卡命令有「项目/ID」写法 ⇒ 正则不能只认裸 ID）
- 探针 `emit` **必须带 `session`**，否则按会话断言全失败
- 子 agent 的 `knownCardKeys` 可能**为空** ⇒ 依赖 `cardKeyOfId` 的新触发点会被整块跳过 → 改用 taskId 定位
- 卡 key 可能带 `.md`，拼 `.log` 路径要兼容两种形态

**做法 D · 改完必升 POLICY + 重启（P6）**
- 不升 POLICY 串 ⇒ `ev=apply` 与上次**逐字相同**，判不出新代码是否加载 → 追加版本 token、重启后先读最后一条 apply
- ⛔ 单测"通过"不等于接线成立：接线类改动必须有一条**走真实 handler 的异步用例**

**验证**：单测全量 + 接线用例；`ev=apply` 尾部能看到新 token；触发点有探针可核。
**覆盖的坑（成员声明）**：P2 · P3 · P4 · P6 · P15 · P17 · P18 · P23 · P24 · P26 · P28 · P35 · P49 · P51 · P53 · P55 · P67 · P69 · P70 · P72 · P76 · P77 · P80 · P81 · P82 · P83 · P84（共 27 条）
**细节指针**：`task_cards/memory/PITFALLS.md` P6 / P17 / P35 / P49 / P67 / P69 / P70 / P72

**同义现象（命中这些也算遇到本族）**：ReferenceError 被吞 · 整段注入静默失效 · 零探针 · **注入没出现也没有任何报错（像是被吞了）** · catch 吞异常 · spawn 级联假失败 · `\s*` 跨行吞行 · 块式列表读成 1 条 · 订阅不存在事件 · 滚动窗口抖动刷屏 · **提醒每隔几步就重复一次 / 同一句反复出现** · 裸 ID 正则 · emit 缺 session · knownCardKeys 空 · 卡 key 带 .md · POLICY 没升 · 待重启。
