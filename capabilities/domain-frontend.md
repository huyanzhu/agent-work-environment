---
name: domain-frontend
intro: 当做页面、觉得丑、或要过可访问性/性能验收时 ⇒ 先立设计令牌与阈值，按屏幕意图构图，用 rubric 与 4.5:1 / LCP 预算修到达标，过三态与键盘/读屏走查才出货。
axis_domain: [前端]
axis_help: [实现]
axis_concern: [美观·风格, 可维护性, 性能]
keywords: [前端, 域能力, domain-frontend, 性能优化, Web Vitals, 首屏加载, 代码分割, 可访问性, a11y, WCAG, 对比度, 键盘可达, 焦点管理, 屏幕阅读器, 触控目标, prefers-reduced-motion]
domain: 前端
# 域能力（一个领域一个文件 · 片不含 class）
parts:
  - id: domain-frontend#tokens
    domain: 前端
    label: 设计令牌
    one_line: 先定颜色 / 间距 / 圆角令牌，再写第一行页面样式
    from: [frontend-ui#tokens]
  - id: domain-frontend#compose
    domain: 前端
    label: 构图生成
    one_line: 按屏幕意图先给空态 / 对话框 / 卡片 / 表单定尺寸与动效（含减动效变体），再写实现
    from: [frontend-ui#compose]
    origin: WCAG 2.2 SC 2.3.3（AAA · 本站当基线）· 2.2.2（A）：动效规格须带 prefers-reduced-motion 分支
  - id: domain-frontend#rubric
    domain: 前端
    label: 出货评分
    one_line: 用 7 类 rubric 打分，按提分幅度修到 80 分
    from: [frontend-ui#rubric]
  - id: domain-frontend#ship
    domain: 前端
    label: 出货判据
    one_line: 核对三态（空 / 载 / 错）齐备与按钮按动作命名，逐条过验收
    from: [frontend-ui#ship]
  - id: domain-frontend#perf-budget
    domain: 前端
    label: 性能预算
    one_line: 先按 LCP / CLS / INP 定预算与验收页，再逐项动手
    from: []
    origin: 外部 Web Vitals 阈值（LCP ≤2.5s · CLS ≤0.1 · INP ≤200ms）；本库无既有片
  - id: domain-frontend#critical-path
    domain: 前端
    label: 关键路径
    one_line: 先砍阻塞渲染的资源，再按首屏必要性定懒加载与预加载
    from: []
    origin: 外部 浏览器关键渲染路径；本库无既有片（最近归属指针在 domains/frontend/patterns/frontend-design.md §4）
  - id: domain-frontend#measure-basis
    domain: 前端
    label: 同口径复测
    one_line: 真机加节流网络测，前后同一口径，未测到的标未验证
    from: []
    origin: 本库真事 TASK-20260823-003 Notes（benchmark 两轮同 URL ⇒ 第二轮全命中索引，21x 失真）
  - id: domain-frontend#a11y-thresholds
    domain: 前端
    label: 可访问阈值
    one_line: 先用对比度 4.5/3 与目标 24（本站 44）的数值线判达标，再改样式
    from: []
    origin: WCAG 2.2 AA SC 1.4.3（正文 4.5:1 / 大字 3:1）· 1.4.11（非文字 3:1）· 2.5.8（目标 24×24，本站按 44）；本库真事 workspaces/demo-project/tests/verify_site.py I3–I5 / L2–L3
  - id: domain-frontend#a11y-semantics
    domain: 前端
    label: 语义与焦点
    one_line: 补可读名称 / label / alt，弹窗管焦点，异步结果用 aria-live 播报
    from: []
    origin: WCAG 2.2 SC 4.1.2 / 1.1.1 / 1.3.1 / 3.3.2（名称与标签）· 2.4.3 / 2.4.7 / 2.4.11 / 2.1.2（焦点）· 4.1.3 / 1.4.1（播报与颜色）；本库真事 TASK-20261101-001（aria-label 与 aria-expanded 矛盾 · 面板收起后焦点掉 body）
  - id: domain-frontend#a11y-walkthrough
    domain: 前端
    label: 可访问走查
    one_line: 用脚本算对比度、跑 axe 与键盘 Tab 走查，没测到的标未验
    from: []
    origin: WCAG 2.2 SC 2.1.1 / 2.4.7 的验证面；本库真事 TASK-20261101-001（静态契约 894→920 + 变异测试；沙箱无浏览器 ⇒ 标未验）+ REVIEW.md 独立复算 20 组对比度
merge_of:
  - frontend-ui
---

# 前端 能力（域能力）

> 由 1 个旧能力合并抽象而成（旧文件在 `capabilities/_archive/`）。
> 一个领域一个文件；片不含阶段字段（Human 口径：领域才是分类轴）。

## 什么时候用

当做页面或觉得丑时 ⇒ 先立设计令牌，再按屏幕意图构图，用 rubric 修到 80 分，过三态验收才出货。
页面已建好、要被问"为什么这么慢 / 优化一下"时 ⇒ 走第 5–7 条（性能预算 → 关键路径 → 同口径复测）。
要做键盘 / 读屏 / 对比度 / 动效偏好这一层时 ⇒ 走第 8–10 条（可访问阈值 → 语义与焦点 → 可访问走查），
动效规格按第 2 条带减动效变体；对比度与触控尺寸的结论要**算出来**，浏览器起不来就标未验。

> ⚠️ 本 intro 一句**未改**（运行时提示会原样引用它，`tools/tests/test_task_card.py` 有字面量断言）；
> 性能方面的入口靠 `axis_concern: 性能` + `keywords`，可访问性方面的入口靠 `keywords`（词表暂无该关注面值），都不靠改这句。
> 改动前查过：`assertIn("当做页面或觉得丑时 ⇒ 先立设计令牌，再按屏幕意图构图", out)` 是**前缀**断言，改尾部不会红；
> 但本卡**仍然没动 intro**（不越界改 `tools/`）⇒ `INDEX.md`「什么时候用」列的 **intro 原句保持不变**，只追加可访问性入口。

## 做法

1. **设计令牌** —— 先定颜色 / 间距 / 圆角令牌，再写第一行页面样式
   > 出处：`frontend-ui#tokens`
2. **构图生成** —— 按屏幕意图先给空态 / 对话框 / 卡片 / 表单定尺寸与动效（含减动效变体），再写实现
   > 出处：`frontend-ui#compose` · WCAG 2.2 2.3.3（AAA · 当基线）/ 2.2.2（A）：动效规格里必须有 reduce 分支
3. **出货评分** —— 用 7 类 rubric 打分，按提分幅度修到 80 分
   > 出处：`frontend-ui#rubric`
4. **出货判据** —— 核对三态（空 / 载 / 错）齐备与按钮按动作命名，逐条过验收
   > 出处：`frontend-ui#ship`
5. **性能预算** —— 先按 LCP / CLS / INP 定预算与验收页，再逐项动手
   > 出处：外部 Web Vitals 阈值 · 无旧片（新增）
6. **关键路径** —— 先砍阻塞渲染的资源，再按首屏必要性定懒加载与预加载
   > 出处：外部 关键渲染路径 · 无旧片（新增）
7. **同口径复测** —— 真机加节流网络测，前后同一口径，未测到的标未验证
   > 出处：`TASK-20260823-003` Notes（benchmark 误测：两轮同 URL ⇒ 21x 失真）· 无旧片
8. **可访问阈值** —— 先用对比度 4.5/3 与目标 24（本站 44）的数值线判达标，再改样式
   > 出处：WCAG 2.2 AA 1.4.3 · 1.4.11 · 2.5.8 · 无旧片（新增）
9. **语义与焦点** —— 补可读名称 / label / alt，弹窗管焦点，异步结果用 aria-live 播报
   > 出处：WCAG 2.2 4.1.2 · 1.1.1 · 1.3.1 · 3.3.2 · 2.4.3 · 2.4.7 · 2.4.11 · 2.1.2 · 4.1.3 · 1.4.1 · 无旧片（新增）
10. **可访问走查** —— 用脚本算对比度、跑 axe 与键盘 Tab 走查，没测到的标未验
   > 出处：WCAG 2.2 2.1.1 / 2.4.7 的验证面 · `TASK-20261101-001` 的静态契约与「浏览器层未验」声明 · 无旧片（新增）

## 性能片的证据状态

> 3 片里 **2 片来自外部标准**（Web Vitals 阈值 / 关键渲染路径），**1 片来自本库真事**（`TASK-20260823-003` 的 benchmark 误测教训）。
> ⚠️ 三片**都没有在页面任务上跑过**（本库 0 个前端性能任务实例）⇒ 证据等级 = **未验证**；首次真实使用后回补读数。
> 跨域说明：**性能是关注面**（`task_cards/NEEDS-VOCAB.md` 第 5 值），不是域。后端 / 数据侧的性能动作归各自域；
> 本文件只收「作用在页面资源与渲染顺序上」的那部分——测量方法**不复制** `domain-backend#baseline`（同一动作不建两份真相），
> 这里只定前端的**具体口径**：真机 + 节流网络，前后同设置。

## 可访问性：8 条做法 → 4 个落点（WCAG 2.2 AA）

> 判层：**可访问性是关注面，不是域**。`task_cards/NEEDS-VOCAB.md` 三轴里**没有**这个值（8 个领域、8 个关注面都不含它），
> 但它的形态与词表里已有的「性能 / 安全」同构：讲的是**页面产物的一个验收属性**，不是"在什么东西上干"。
> ⇒ ⛔ 不新开 `domain-a11y.md`（同一属性词落两根轴会让坐标系自相矛盾；后端 / 文档侧的无障碍动作也会变成两份真相），
> 按「作用在哪个域的产物上」全部落**前端**（页面 DOM / 样式 / 交互产物）。
> 词表缺这个值本身列为 follow-up（补词表值属 Human 裁决，维护卡不动 `NEEDS-VOCAB.md`）。

| # | 待融合做法 | 落点 | 判据（WCAG 2.2） | 能不能机械查 |
|---|---|---|---|---|
| 1 | 对比度：正文 ≥4.5:1，大字 / 非文字 ≥3:1 | 第 8 片 `a11y-thresholds` | 1.4.3（AA）· 1.4.11（AA） | ✅ 算亮度比值，不靠"看着清楚" |
| 2 | 键盘可达：Tab 到达 / 顺序合视觉 / 焦点环可见 | 构在第 9 片 · 验在第 10 片 | 2.1.1（A）· 2.4.3（A）· 2.4.7（AA） | 半自动（静态契约 + 人工 Tab 走查） |
| 3 | 焦点管理：打开进入 / 关闭归还 / `aria-modal` | 第 9 片 | 2.4.3（A）· 2.1.2（A）· 2.4.11（AA · 2.2 新增） | 半自动 |
| 4 | 语义与名称：按钮 / 链接可读名 · 表单 label · 图片 alt（装饰性空 alt） | 第 9 片 | 4.1.2（A）· 1.1.1（A）· 1.3.1（A）· 3.3.2（A）· 2.4.4（A） | ✅ axe / 静态解析 |
| 5 | 目标尺寸 ≥24×24（2.2 AA；本站已按 44px 做，更严） | 第 8 片 | 2.5.8（AA · 2.2 新增） | ✅ 解析 CSS 像素 |
| 6 | 动效偏好：`prefers-reduced-motion` 时关 / 弱化 | 第 2 片 `compose` 的动效规格 | 2.3.3（**AAA** · 本站当基线）· 2.2.2（A） | 半自动（查媒体查询分支） |
| 7 | 状态播报：`aria-live` 报异步结果 · 不靠颜色单独表意 | 第 9 片 | 4.1.3（AA）· 1.4.1（A） | ❌ 需读屏 / 浏览器 |
| 8 | 验证：脚本算对比度 · axe / lighthouse · 键盘走查 · 未验如实标 | 第 10 片 | 方法面，不挂单条 SC | ✅ |

**为什么是 3 新片 + 1 并入，而不是 8 片、也不是 1 句空话**（动作类型判据见 `maintenance-skills/capability-fusion/SKILL.md` §三）：

- **声明 / 构造 / 取证是三种动作**，硬规则要求「同一片共享同一动作类型」⇒ **最少就是 3 片**；压成 2 片要"并且"连接两个动词，过不了 §三。
- ①⑤ 都是「把阈值写成可算的验收线」（产出物 = 一组数字；失败模式 = "看着清楚 / 够大"）⇒ 合 1 片 `a11y-thresholds`。
- ②③④⑦ 都是「把视觉上成立的交互补上程序化语义与焦点」（产出物 = 一棵辅助技术可读可操作的 DOM / 交互结构；失败模式 = 视觉用户能点、键盘与读屏用户进不来）⇒ 合 1 片 `a11y-semantics`。
- ②⑧ 的验证面是「造一条会失败的检查」（产出物 = 走查记录 + 未验清单；失败模式 = 没验就宣称可访问）⇒ 1 片 `a11y-walkthrough`。**与 `measure-basis` 不合并**：那是"前后同口径的可比较读数"（失败模式是口径漂移、21x 失真），这里是 0/1 通路判定，产出物不同。
- ⑥ 不是新动作：`compose` 本来就负责"定动效"⇒ 减动效只是动效规格的一个档位，并进去，变体留一句举例。
- ⛔ 10 片已是 lint 的片数上限（`_capability_field_lint` 域能力 1–10）⇒ "8 条各一片"机械上也过不去。

**证据状态**：

> 3 个新片**都没有旧片祖先**（`from: []`），出处写在 `origin:`：2 片挂 WCAG 2.2 的 success criteria 编号，3 片都带本库真事指针。
> 本库真实跑过的是 `workspaces/demo-project` 的 **WCAG 2.1 AA 子集**：对比度 I3–I5、触控 L2–L3、键盘 T1–T7、alt D1、整卡可读名 Q1–Q2，
> 并把 4 处真实缺口修进契约（894→920，含变异测试）。⚠️ **浏览器层未验**（沙箱禁 Chrome 命名管道）：
> 真实 Tab 顺序、焦点环观感、读屏播报**未目检 / 未自动化** ⇒ 这一层证据等级 = **未验证**。
> 2.2 新增的 2.5.8 / 2.4.11 **没有在本库任何任务上跑过** ⇒ 外部标准，未验证。

## 片的覆盖来源

| 新片 | 抽象自 |
|---|---|
| `domain-frontend#tokens` | `frontend-ui#tokens` |
| `domain-frontend#compose` | `frontend-ui#compose` + WCAG 2.2 2.3.3 / 2.2.2（减动效变体） |
| `domain-frontend#rubric` | `frontend-ui#rubric` |
| `domain-frontend#ship` | `frontend-ui#ship` |
| `domain-frontend#perf-budget` | 新增（无旧片祖先）· 外部 Web Vitals 阈值 |
| `domain-frontend#critical-path` | 新增（无旧片祖先）· 外部关键渲染路径 |
| `domain-frontend#measure-basis` | 新增（无旧片祖先）· `TASK-20260823-003` Notes |
| `domain-frontend#a11y-thresholds` | 新增（无旧片祖先）· WCAG 2.2 1.4.3 / 1.4.11 / 2.5.8 + `verify_site.py` I3–I5 / L2–L3 |
| `domain-frontend#a11y-semantics` | 新增（无旧片祖先）· WCAG 2.2 4.1.2 / 1.1.1 / 1.3.1 / 3.3.2 / 2.4.3 / 2.4.7 / 4.1.3 / 1.4.1 + `TASK-20261101-001` |
| `domain-frontend#a11y-walkthrough` | 新增（无旧片祖先）· WCAG 2.2 2.1.1 / 2.4.7 验证面 + `TASK-20261101-001` 的「浏览器层未验」 |
