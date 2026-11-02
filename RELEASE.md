# Agent 的工作环境（可核）

> **AI-OS 的本体发布物**：约定层 + 工作记忆 + 校验门 + 一条**仍在验证中**的投递通道。
>
> 一句话：**AI-OS = Agent 的工作环境（可核）**。

## 这份发布物是什么

| 层 | 内容 |
|---|---|
| **约定层** | `AGENTS.md`（宪法 / L1 / 硬约束）· `README.md`（启动顺序）· `ONBOARD.md` · `TOOL_RUNTIME.md` |
| **工作记忆** | 任务卡（结构即判据：State 值域 / 占卡排他 / Event Log 外置）+ 全局记忆（三份空模板 + PITFALLS） |
| **校验门** | `tools/probes/*`（能力字段 / 回归门 / 克隆闸门）+ `tools/tests` |
| **能力** | 该怎么做（`capabilities/` 域能力与做法片） |
| **经验** | 别再踩（`domains/experiences/` 族卡 + `PITFALLS`） |
| **投递通道** | `runtime/`（阶段注入 / 节点注入 / 经验召回 / 声明驱动域注入）—— ⚠️ **唯一被反复证伪的部分**，见 `docs/LIMITATIONS.md` |

⛔ **不含**：任何人的任务卡正文、项目交付物、成功账本正文、第三方 skill 原文 —— 那些是"被它服务过的工作"，不是本体。

## 怎么开始

见 `QUICKSTART.md`。最短路径：

```bash
git clone https://github.com/<user>/agent-work-environment.git
cd agent-work-environment
cp -r .aios-sample .aios     # Windows: xcopy /E /I .aios-sample .aios
# 重启宿主
```

## 怎么自检（都可复现）

```bash
python tools/probes/_clone_selftest.py                 # 干净克隆四道闸门
node runtime/tests/activation.test.mjs                 # 运行时自测（唯一已知红：S37）
python -m unittest discover -s tools/tests -p "test_*.py"
python tools/probes/_release_manifest.py --root . --verify MANIFEST.sha256   # 文件完整性
```

读数与「已知红是哪一条」见 `docs/LIMITATIONS.md`；证据档位口径见 `workspaces/ai-os-public/EVIDENCE.md`。

## 边界与安全

- 配置层 fail-closed（缺文件 / 非法 JSON / 开关值不严格为 `true` ⇒ 关或不生效）——见 `docs/SECURITY.md`
- 注入只注入文本，不落推理原文；子进程有超时与输出上限
- 已知限制清单见 `docs/LIMITATIONS.md`

---

## 附录：实测文件数（**组装时自动生成** · ⛔ 手写数字会漂）

| 路径 | 文件数 |
|---|---|
| `AGENTS.md` | 1 |
| `CHANGELOG.md` | 1 |
| `LICENSE` | 1 |
| `MAP.md` | 1 |
| `ONBOARD.md` | 1 |
| `QUICKSTART.md` | 1 |
| `README.md` | 1 |
| `TOOL_RUNTIME.md` | 1 |
| `capabilities/` | 12 |
| `docs/` | 5 |
| `domains/` | 109 |
| `evidence/` | 3 |
| `maintenance-skills/` | 8 |
| `package.json` | 1 |
| `runtime/` | 21 |
| `samples/` | 4 |
| `task_cards/` | 14 |
| `tools/` | 63 |
| `workspaces/` | 6 |
| `样例账本.md` | 1 |
| `RELEASE.md` | 1 |
| **合计** | **256** |

> 生成命令：`python tools/release_assemble.py`（作者侧工具，**未随发布**）。
