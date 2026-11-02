# Changelog

> 当前版本：**0.1.21**。版本号的唯一事实源是 `package.json` 的 `version` 字段；
> 发布物的 `package.json`、Git tag 与本文件标题应保持三处一致。

## 0.1.21

- **`auto_capability` 不再要求 `confirmed`**：省略即视为 `agent-inferred`（自己推断，只当假设存）；
  只有对方确认过才写 `user`。⇒ 调工具只需要一句 `what`。
- **`need` 是可选项，不是流程的一部分**：不带 `need` ⇒ 只返回 8 个领域词表；
  带 `need`（可再带 `axes`）⇒ 才走检索候选。日常流程（拿词表 → 选域 → 写卡 → 按声明注入）不需要它。
- 文档同步：`README` / `docs/CAPABILITIES` 的 `confirmed` 说明改为"可省略"。

## 0.1.20

- **检索路径文档补 `confirmed`**：`auto_capability` 的检索分支要求 `confirmed`（`user` / `agent-inferred`）；
  只给 `what` 仍直接返回 8 个领域词表（不检索、不记录）。
- **工作记忆入口文档重写**：`task_cards/README.md` 按真实目录与流程重写（去掉不存在的历史树、内部项目名与旧口径）。
- **文档一致性修复**：经验族卡 6 张（原写 12）· 配置缺省 `max=1`/`claimHint=off` 对齐代码 ·
  `CONFIGURATION` 版本对齐 · 证据包读数标注当日口径 · RELEASE 附录文件数与干净 clone 一致（271）·
  `TOOL_RUNTIME` 去内部项目名/死引用 · `samples/walkthrough.md` 补首次初始化 `.aios`。
- **默认值单一事实源**：`.aios-sample` 的值收敛到随发布模块 `tools/aios_switches.py`；
  新增默认契约测试（样本文件 / README / 事实源逐值一致），修复干净克隆里测试必红的问题（147 tests）。
- **门禁加固**：新增「文档数字 vs 产物实测」（README 写错即红）；过时项与断链纳入发布前扫描。

## 0.1.19

- **调 `auto_capability` 先给「8 个领域词表」**：只写一句 `what` 即可（不需要先填 need/axes/concern），
  返回 8 个域能力及一句做法，agent 自己选一个写进卡上「能力」字段；带 `need` 仍走检索。
- **claim 提示改为指向检索工具**：`claim` 尾部提示「用 `auto_capability` → 它会给出 8 个领域词表，选一个」，
  不再让 agent 自己翻 `INDEX.md`。
- **任务卡模板减重**：`## 使用的能力` 只留一个字段 `- 能力: \`（未记录）\``（去掉流程说明）。
- **默认值单一事实源**：`.aios-sample` 的 5 份开关值收敛到 assembler 的 `SWITCH_SAMPLE`，
  新增 `test_default_contract` 断言「代码缺省 / 样本推荐值 / 样本 README」一致。
- **部署闸门**：`tools/probes/_live_policy_check.py` 比对「宿主已装载 POLICY」与「源码 POLICY」，
  不一致直接提示重启 —— 避免"源码修了、线上还是旧行为"。
- **配置文档补两列**：`docs/CONFIGURATION.md` 的开关表区分「代码缺省（fail-closed）」与「`.aios-sample` 推荐值」。

## 0.1.18

- **子会话默认参与投递**：`inject_probe.json` 的 `allowSubagent` 缺省为开，子 agent 承担的工作不再默认落在注入盲区；只想让主会话收可显式写 `false`。
- **召回查询不再携带乱码**：失败输出被控制台解码污染时，查询改用「错误分类 + ASCII 签名 + 编码族规范词」，避免词面检索恒 0 命中。
- **投递判读说明**：`maintenance-skills/runtime-switches.md` 集中列出三种「看起来没生效」的情况（子会话门、query 被乱码污染、命中≠采用），并给出判读步骤。
- **任务卡增加采用记录**：`## Outcome` 新增「投递采用」，收工时可以区分「注入过」与「真的被用上」。
- **文档结构调整**：新增 `docs/{ARCHITECTURE,CAPABILITIES,CONFIGURATION,LIMITATIONS,SECURITY}.md`，README/QUICKSTART 统一首次启动口径。
- **发布可校验**：`tools/probes/_release_manifest.py` 生成/校验发布树 `MANIFEST.sha256`；版本以 `package.json` 为单一来源。
