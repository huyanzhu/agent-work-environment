# 样本：一个完整的域能力（虚构 · 对照 `capabilities/_TEMPLATE-domain.md`）

> 用途：让新人看到**填好的**域能力长什么样。这是一个**虚构领域**（`domain-demo`），
> 只演示形状与判据口径，⛔ 不要直接当真实能力使用。
> 真实的 8 个域能力在 `capabilities/domain-*.md`。

---

## 1. frontmatter（就是它自己）

```yaml
---
name: domain-demo
intro: 当要写一次性脚本处理数据时 ⇒ 先断言输入、再算、最后用另一种算法复算同一结论。
axis_domain: [演示]
axis_help: [实现, 验证]
axis_concern: [正确性]
keywords: [演示, 域能力, domain-demo]
domain: 演示
parts:
  - id: domain-demo#assert-input
    domain: 演示
    label: 先断言输入
    one_line: 脚本第一件事断言行数/列名/编码，不合格就退出
    origin: 本库真事 2026-01-01 的 CSV 空值事故
  - id: domain-demo#recompute
    domain: 演示
    label: 换个算法复算
    one_line: 用第二种独立算法复算关键数字，不一致就报错
    origin: 本库真事 2026-01-01（同一数字两法一致才算完）
---
```

## 2. 正文（与片一一对应）

# 演示 能力（域能力）

## 什么时候用

当要写一次性脚本处理数据时 ⇒ 先断言输入、再算、最后用另一种算法复算同一结论。

## 做法

1. **先断言输入** —— 脚本第一件事断言行数/列名/编码，不合格就退出
   > 出处：本库真事（CSV 空值事故）
2. **换个算法复算** —— 用第二种独立算法复算关键数字，不一致就报错
   > 出处：本库真事（同一数字两法一致才算完）

## 片的覆盖来源

| 新片 | 抽象自 |
|---|---|
| `domain-demo#assert-input` | 新片（无旧片祖先 ⇒ 用 `origin:`） |
| `domain-demo#recompute` | 新片（同上） |

---

## 3. 机械校验会检查什么（写完必须跑）

```bash
python tools/probes/_capability_field_lint.py      # 字段口径 + 片数 1–10 + one_line ≤45 字
python tools/probes/_capability_parts_matrix.py    # 片级矩阵 / 覆盖
```

**这条样本的关键示范**：
- `one_line` **必须含动作词**（"断言 / 复算"），⛔ 不写形容词（"清晰""合理"）
- 无旧片祖先时用 `origin:`（写**真实出处**），有祖先才用 `from:`
- `intro` ≤45 字、含 `⇒`，形状是「当 X 时 ⇒ 照做 Y」
