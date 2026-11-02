---
title: 遇到工具调用/参数用错（编辑·写文件·命令参数都算）
family: 工具使用/参数误用
form: inject
status: pilot
trigger: 工具报错, 参数错, file no longer exists, re-read the file, 同名重建, edit 吞注释, 语法断裂, Select-Object -First, 提前关管道, echo 报错, gh api -q, failed to parse json, 参数类型, 工具不校验, 删除前扫描, 引用扫描, 裸文件名, 误删, scratch 清理
keywords: write, edit, 同名, 重建, 删除, 吞, 注释, 语法, 括号, 管道, select-object, first, echo, 引号, jq, json, 参数, 类型, 校验, tool, 引用, 扫描, basename, scratch, 清理, 误删
alias: file no longer exists, re-read the file, 同名重建失败, 删了再写写不进, 大块 edit 吞注释, 注释尾悬空, 语法断裂, Select-Object -First 假失败, 提前关管道, echo; 报错, missing mandatory parameters, gh -q 被吃掉, failed to parse json, 参数类型错, 复用同一个文件名, 传错参数没报错, 带引号的参数传不进去, 改完代码跑不起来, 清理时删掉了还在用的文件, 引用扫描只扫带路径的写法, 裸文件名引用被漏掉, 删完才发现脚本还在用它
---

遇到"工具报错但代码没错""命令跑完了却报失败""改完文件语法断了"这类问题时，先对号入座；⛔ 不要先怀疑业务逻辑。

**做法 A · write 对已删除的同路径文件：换名字**
- 删掉某个文件后想用**同名** `write` 重建 ⇒ 报 `file no longer exists — re-read the file, then retry`，而 `read` 又读不到（无法满足"re-read"）→ **换文件名或换目录**重建；⛔ 别在"删除+同名重建"上反复试
- 场景：**想复用同一个文件名**，但工具拒绝写入（同名重建被拒）→ 同上：换文件名/目录，⛔ 别反复试

**做法 B · 大块 edit 会吞掉相邻块**
- 大块 `edit` 替换时常把**紧随其后的注释/代码块开头**一起吞掉 ⇒ 语法断裂（注释尾悬空、括号不配）→ 改完**立即**跑语法检查/编译/单测；大改拆成小步替换

**做法 C · PowerShell 管道/语法坑**
- `| Select-Object -First N` 会**提前关管道** ⇒ 被截断进程以非零码退出（假失败）→ 看完整输出再判成败
- 裸 `echo;` 当分隔符 ⇒ `Cannot process command because of one or more missing mandatory parameters` → 用 `Write-Host ''`
- `gh api -q '<jq>'` 的单引号被 PowerShell 吃掉（`failed to parse json`）→ 换双引号/转义，或把查询写进临时脚本

**做法 D · 工具不校验参数**
- 宿主注册的工具**不校验模型参数**：类型错也会进 `execute` ⇒ 传参前自己核必填项与类型；报错往往是下游崩的，不是参数报的
- 场景：**给工具传了错的参数，它没报错，跑到深处才炸** → 这就是"不校验参数"的典型症状：传参前自核类型/必填，别等下游崩

**做法 E · 删文件前先做全量引用扫描（P95）**
- 清理 / 删除文件前必须用**裸 basename 全仓扫**（脚本里常写裸文件名：`PREPARED` 表、`Test-Path` + `Copy-Item`），⛔ 只扫 `scratch/<文件名>` 这类**带目录前缀**的形式 —— 前缀式扫描会把"有引用"判成"零提及"
- 删除后**再复扫一次**（P95 实例正是删后裸名复扫才暴露）；"零提及"必须由裸名扫描给出，并区分**消费方引用**与清单 / 会话转录的**自证性提及**
- 不可逆删除前先记删前清单或留备份；判据 = 每个待删名在全仓（不只 scratch）至少一次裸名扫描有结论

**验证**：改完跑语法检查/复跑命令；报错里不再出现 `file no longer exists` / `missing mandatory parameters` / `failed to parse json`；删除类操作有裸名扫描 + 删后复扫两轮读数。
**覆盖的坑（成员声明）**：P20 · P22 · P37 · P46 · P65 · P66 · P92 · P95（共 8 条；P92 = v4 单字段卡给 --stage 把卡写坏 · P95 = 删除前引用扫描只扫前缀 ⇒ 误删）
> 口径：只收「**照本族做法做就够了**」的坑。P1/P52/P61 属**已撤任务卡族遗留**（机制已修 · 原族已撤），⛔ 不用本族顶班（会造成假覆盖）；P16/P48/P62/P64 属邻接但处置不在本族（环境 / junction 判据 / 探针计数口径 / 工具可见性），单列为无族。
**细节指针**：`task_cards/memory/PITFALLS.md` P20 / P22 / P37 / P46 / P65 / P66 / P92 / P95

**同义现象（命中这些也算遇到本族）**：file no longer exists · re-read the file · 同名重建失败 · 删了再写写不进 · 大块 edit 吞注释 · 注释尾悬空 · 语法断裂 · Select-Object -First 假失败 · 提前关管道 · echo; 报错 · missing mandatory parameters · gh -q 被吃掉 · failed to parse json · 参数类型错 · 工具不校验参数 · 复用同一个文件名 · 传错参数没报错 · 带引号的参数传不进去 · 改完代码跑不起来 · **清理时删掉了还在用的文件** · **引用扫描只扫带路径的写法** · **裸文件名引用被漏掉** · **删完才发现脚本还在用它**。
