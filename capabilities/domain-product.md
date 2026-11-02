---
name: domain-product
intro: 当想法模糊、需求没定时 ⇒ 过 Problem 闸门，有实质歧义才列选项等裁决，按 Discovery 契约填 confidence，最后出四件套。
axis_domain: [产品]
axis_help: [设计, 评审]
axis_concern: [正确性]
keywords: [产品, 域能力, domain-product]
domain: 产品
# 域能力（一个领域一个文件 · 片不含 class）
parts:
  - id: domain-product#problem-gate
    domain: 产品
    label: Problem 闸门
    one_line: Problem 确认前只复述问题，不提方案与技术栈
    from: [idea_to_project#problem]
  - id: domain-product#ambiguity
    domain: 产品
    label: 歧义门
    one_line: 有实质歧义才列假设与选项，列完即结束、等裁决
    from: [idea_to_project#ambiguity]
  - id: domain-product#discovery
    domain: 产品
    label: 结构化理解
    one_line: 按 Discovery 契约填 confidence，未知用 null 并说明
    from: [idea_to_project#discovery]
  - id: domain-product#delivery-4
    domain: 产品
    label: 交付四件套
    one_line: 按 流程 → 验收 → 数据模型 → 接口草图 顺序出四件套
    from: [idea_to_project#delivery]
merge_of:
  - idea_to_project
---

# 产品 能力（域能力）

> 由 1 个旧能力合并抽象而成（旧文件在 `capabilities/_archive/`）。
> 一个领域一个文件；片不含阶段字段（Human 口径：领域才是分类轴）。

## 什么时候用

当想法模糊、需求没定时 ⇒ 过 Problem 闸门，有实质歧义才列选项等裁决，按 Discovery 契约填 confidence，最后出四件套。

## 做法

1. **Problem 闸门** —— Problem 确认前只复述问题，不提方案与技术栈
   > 出处：`idea_to_project#problem`
2. **歧义门** —— 有实质歧义才列假设与选项，列完即结束、等裁决
   > 出处：`idea_to_project#ambiguity`
3. **结构化理解** —— 按 Discovery 契约填 confidence，未知用 null 并说明
   > 出处：`idea_to_project#discovery`
4. **交付四件套** —— 按 流程 → 验收 → 数据模型 → 接口草图 顺序出四件套
   > 出处：`idea_to_project#delivery`

## 片的覆盖来源

| 新片 | 抽象自 |
|---|---|
| `domain-product#problem-gate` | `idea_to_project#problem` |
| `domain-product#ambiguity` | `idea_to_project#ambiguity` |
| `domain-product#discovery` | `idea_to_project#discovery` |
| `domain-product#delivery-4` | `idea_to_project#delivery` |
