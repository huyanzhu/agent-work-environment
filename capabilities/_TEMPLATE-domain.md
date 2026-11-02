---
# 复制本文件为 `domain-<领域>.md`（一域一文件）。
# ⚠️ 字段口径由 `tools/probes/_capability_field_lint.py` 机械校验：改完必须跑它。
#
# 🔴 **要新增一个"领域"（不是往现有域加片）时，先扩词表**：
#   1) 编辑 `task_cards/NEEDS-VOCAB.md` 的领域轴，加上新领域名；
#   2) 下面的 `axis_domain` 与**每一片的 `parts[].domain`** 都必须取**同一个**词表值
#      （两处都受值域校验；只在 axis_domain 换、parts 不换 ⇒ lint FAIL）；
#   3) 同步入口：`capabilities/INDEX.md`（加行 + 改「8 个域能力」计数）、`AXES-MAP.md`、
#      `README/QUICKSTART` 里的「8 域 / 50 片」。
#   ⛔ 没有机械闸门会因为你漏改 INDEX 而报错 —— 只能靠这条清单。
name: domain-<领域标识>
# intro = 注入到 Agent 上下文的那一句（含「⇒」，形状是「当 X 时 ⇒ 照做 Y」）
#   参考：现有 8 个域能力的 intro 长度 45–88 字（lint **不校验** intro 长度）
intro: 当<做什么>时 ⇒ <先做什么>，<再做什么>，<最后交付什么>。
axis_domain: [<领域名 · 必须来自 task_cards/NEEDS-VOCAB.md 的领域轴>]
axis_help: [<帮助类型 · 如 实现 / 评审 / 验证>]
axis_concern: [<关注面 · 如 正确性 / 可维护性>]
keywords: [<领域名>, 域能力, domain-<领域标识>]
domain: <领域名>
# 一个领域一个文件；片不含阶段字段（Human 口径：领域才是分类轴）
parts:
  - id: domain-<领域标识>#<片标识>
    domain: <领域名>
    label: <片名（2–6 字）>
    # one_line ≤45 字 · 必须含**动作词**（先/再/用/判/查/留…），⛔ 不写形容词
    one_line: <一句话做法>
    # 出处二选一至少一条：
    #   from: 由旧能力/旧片合并而来（写旧片 id）
    #   origin: 无旧片祖先时写真实出处（标准条款号 / 本库真事）
    from: [<旧片 id>]
    # origin: <WCAG 2.2 4.1.2 / 具体失败形态的 …>
---

# <领域名> 能力（域能力）

> 本文件 = 该领域的**做法库**。片（parts）与正文「做法」必须**一一对应**。

## 什么时候用

<与 frontmatter 的 `intro` 一致 · 一句话>

## 做法

1. **<片名>** —— <一句话做法>
   > 出处：`from:` 或 `origin:`
2. **<片名>** —— …

## 片的覆盖来源

| 新片 | 抽象自 |
|---|---|
| `domain-<领域标识>#<片标识>` | `<旧片 id>` |
