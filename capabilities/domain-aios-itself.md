---
name: domain-aios-itself
intro: 当给自己（AI-OS）做交付时 ⇒ 开工先核状态与验收清单，实现前把完成定义写成能跑的检查，收口时切下家身份走真实路径核对不变式。
axis_domain: [AI-OS 自身]
axis_help: [验证, 评审]
axis_concern: [正确性]
keywords: [AI-OS 自身, 域能力, domain-aios-itself]
domain: AI-OS 自身
# 域能力（一个领域一个文件 · 片不含 class）
parts:
  - id: domain-aios-itself#state
    domain: AI-OS 自身
    label: 开工核状态
    one_line: 开工先读最新验收清单与状态文件再动手
    from: [self-verification#state]
  - id: domain-aios-itself#criteria
    domain: AI-OS 自身
    label: 完成判据
    one_line: 实现前把「完成」写成一条能跑的检查（不是形容词）
    from: [self-verification#criteria]
  - id: domain-aios-itself#close
    domain: AI-OS 自身
    label: 切下家身份收口
    one_line: 切到下家（接手者）身份走真实路径，再读数据层核对不变式
    from: [self-verification#close]
merge_of:
  - self-verification
---

# AI-OS 自身 能力（域能力）

> 由 1 个旧能力合并抽象而成（旧文件在 `capabilities/_archive/`）。
> 一个领域一个文件；片不含阶段字段（Human 口径：领域才是分类轴）。

## 什么时候用

当给自己（AI-OS）做交付时 ⇒ 开工先核状态与验收清单，实现前把完成定义写成能跑的检查，收口时切下家身份走真实路径核对不变式。

## 做法

1. **开工核状态** —— 开工先读最新验收清单与状态文件再动手
   > 出处：`self-verification#state`
2. **完成判据** —— 实现前把「完成」写成一条能跑的检查（不是形容词）
   > 出处：`self-verification#criteria`
3. **切下家身份收口** —— 切到下家（接手者）身份走真实路径，再读数据层核对不变式
   > 出处：`self-verification#close`

## 片的覆盖来源

| 新片 | 抽象自 |
|---|---|
| `domain-aios-itself#state` | `self-verification#state` |
| `domain-aios-itself#criteria` | `self-verification#criteria` |
| `domain-aios-itself#close` | `self-verification#close` |
