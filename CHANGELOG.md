# Changelog

> 当前版本：**0.1.18**。版本号的唯一事实源是 `package.json` 的 `version` 字段；
> 发布物的 `package.json`、Git tag 与本文件标题应保持三处一致。

## 0.1.18

- **子会话默认参与投递**：`inject_probe.json` 的 `allowSubagent` 缺省为开，子 agent 承担的工作不再默认落在注入盲区；只想让主会话收可显式写 `false`。
- **召回查询不再携带乱码**：失败输出被控制台解码污染时，查询改用「错误分类 + ASCII 签名 + 编码族规范词」，避免词面检索恒 0 命中。
- **投递判读说明**：`maintenance-skills/runtime-switches.md` 集中列出三种「看起来没生效」的情况（子会话门、query 被乱码污染、命中≠采用），并给出判读步骤。
- **任务卡增加采用记录**：`## Outcome` 新增「投递采用」，收工时可以区分「注入过」与「真的被用上」。
- **文档结构调整**：新增 `docs/{ARCHITECTURE,CAPABILITIES,CONFIGURATION,LIMITATIONS,SECURITY}.md`，README/QUICKSTART 统一首次启动口径。
- **发布可校验**：`tools/probes/_release_manifest.py` 生成/校验发布树 `MANIFEST.sha256`；版本以 `package.json` 为单一来源。
