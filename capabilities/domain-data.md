---
name: domain-data
intro: 当改库 / 迁移 / 回填时 ⇒ 先确认备份可还原，先建触发器再回填，部分更新用显式判空。
axis_domain: [数据]
axis_help: [实现, 验证]
axis_concern: [正确性]
keywords: [数据, 域能力, domain-data]
domain: 数据
# 域能力（一个领域一个文件 · 片不含 class）
parts:
  - id: domain-data#backup
    domain: 数据
    label: 备份可还原
    one_line: 先查备份是否含 -wal 且能还原，再动数据
    from: [data-change-safety#backup]
  - id: domain-data#index
    domain: 数据
    label: 索引回填
    one_line: 先建表触发器再 rebuild 回填，之后才删改存量
    from: [data-change-safety#index]
  - id: domain-data#patch
    domain: 数据
    label: 部分更新
    one_line: 部分更新用 !== undefined 判字段是否传来，别用 truthy 判
    from: [data-change-safety#patch]
merge_of:
  - data-change-safety
---

# 数据 能力（域能力）

> 由 1 个旧能力合并抽象而成（旧文件在 `capabilities/_archive/`）。
> 一个领域一个文件；片不含阶段字段（Human 口径：领域才是分类轴）。

## 什么时候用

当改库 / 迁移 / 回填时 ⇒ 先确认备份可还原，先建触发器再回填，部分更新用显式判空。

## 做法

1. **备份可还原** —— 先查备份是否含 -wal 且能还原，再动数据
   > 出处：`data-change-safety#backup`
2. **索引回填** —— 先建表触发器再 rebuild 回填，之后才删改存量
   > 出处：`data-change-safety#index`
3. **部分更新** —— 部分更新用 !== undefined 判字段是否传来，别用 truthy 判
   > 出处：`data-change-safety#patch`

## 片的覆盖来源

| 新片 | 抽象自 |
|---|---|
| `domain-data#backup` | `data-change-safety#backup` |
| `domain-data#index` | `data-change-safety#index` |
| `domain-data#patch` | `data-change-safety#patch` |
