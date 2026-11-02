---
name: domain-docs
intro: 当要写 / 搬 / 拆 / 发文档时 ⇒ 结构先行，语料审计只跑最便宜的探针，变更分类决定动哪里，最后汇报增量与例外。
axis_domain: [文档]
axis_help: [写作, 评审, 审计·清理]
axis_concern: [可维护性, 一致·预算]
keywords: [文档, 域能力, domain-docs]
domain: 文档
# 域能力（一个领域一个文件 · 片不含 class）
parts:
  - id: domain-docs#structure-first
    domain: 文档
    label: 结构先行
    one_line: 先定位主题与子文档，再按用途定层级（教程 or 参考）
    from: [doc_standards#structure]
  - id: domain-docs#scope-budget
    domain: 文档
    label: scope 与预算
    one_line: 先确认 scope 与排除；超预算按搬运、压缩、抬预算处理并说明理由
    from: [prose_standard#scope, doc_standards#budget]
  - id: domain-docs#audit-cheap
    domain: 文档
    label: 最便宜探针先行
    one_line: 先跑最便宜的机械探针，再逐段判语料冗余或缺口
    from: [doc_standards#audit, prose_standard#coverage]
  - id: domain-docs#proposition-keep
    domain: 文档
    label: 命题保全
    one_line: 删前先枚举命题；只删可解析性已丧失的引用，actor / 条件 / 模态例外都留住
    from: [prose_standard#proposition, cot_leakage_trim#keep, cot_leakage_trim#head-test]
  - id: domain-docs#classify-change
    domain: 文档
    label: 变更分类
    one_line: 先给变更分类，再决定动源、manifest 还是结构；新增页字段显式设定
    from: [doc_site_projection#classify, doc_site_projection#manifest]
  - id: domain-docs#links-gate
    domain: 文档
    label: 链接与门禁
    one_line: 源里只写仓库相对链接、缺失目标让构建失败；提交前跑预览与 diff 检查
    from: [doc_site_projection#links, doc_site_projection#gate]
  - id: domain-docs#report
    domain: 文档
    label: 增量汇报
    one_line: 先改源再改派生物，汇报词数增量、例外理由与实际跑过的检查
    from: [doc_standards#report, prose_standard#workflow, cot_leakage_trim#fix]
merge_of:
  - cot_leakage_trim
  - doc_site_projection
  - doc_standards
  - prose_standard
---

# 文档 能力（域能力）

> 由 4 个旧能力合并抽象而成（旧文件在 `capabilities/_archive/`）。
> 一个领域一个文件；片不含阶段字段（Human 口径：领域才是分类轴）。

## 什么时候用

当要写 / 搬 / 拆 / 发文档时 ⇒ 结构先行，语料审计只跑最便宜的探针，变更分类决定动哪里，最后汇报增量与例外。

## 做法

1. **结构先行** —— 先定位主题与子文档，再按用途定层级（教程 or 参考）
   > 出处：`doc_standards#structure`
2. **scope 与预算** —— 先确认 scope 与排除；超预算按搬运、压缩、抬预算处理并说明理由
   > 出处：`prose_standard#scope` · `doc_standards#budget`
3. **最便宜探针先行** —— 先跑最便宜的机械探针，再逐段判语料冗余或缺口
   > 出处：`doc_standards#audit` · `prose_standard#coverage`
4. **命题保全** —— 删前先枚举命题；只删可解析性已丧失的引用，actor / 条件 / 模态例外都留住
   > 出处：`prose_standard#proposition` · `cot_leakage_trim#keep` · `cot_leakage_trim#head-test`
5. **变更分类** —— 先给变更分类，再决定动源、manifest 还是结构；新增页每个 manifest 字段显式设定
   > 出处：`doc_site_projection#classify` · `doc_site_projection#manifest`
6. **链接与门禁** —— 源里只写仓库相对链接、缺失目标让构建失败；提交前跑预览与 diff 检查
   > 出处：`doc_site_projection#links` · `doc_site_projection#gate`
7. **增量汇报** —— 先改源再改派生物，汇报词数增量、例外理由与实际跑过的检查
   > 出处：`doc_standards#report` · `prose_standard#workflow` · `cot_leakage_trim#fix`

## 片的覆盖来源

| 新片 | 抽象自 |
|---|---|
| `domain-docs#structure-first` | `doc_standards#structure` |
| `domain-docs#scope-budget` | `prose_standard#scope` · `doc_standards#budget` |
| `domain-docs#audit-cheap` | `doc_standards#audit` · `prose_standard#coverage` |
| `domain-docs#proposition-keep` | `prose_standard#proposition` · `cot_leakage_trim#keep` · `cot_leakage_trim#head-test` |
| `domain-docs#classify-change` | `doc_site_projection#classify` · `doc_site_projection#manifest` |
| `domain-docs#links-gate` | `doc_site_projection#links` · `doc_site_projection#gate` |
| `domain-docs#report` | `doc_standards#report` · `prose_standard#workflow` · `cot_leakage_trim#fix` |
