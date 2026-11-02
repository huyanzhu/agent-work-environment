---
name: domain-ops
intro: 当要跨机器 / 跨进程 / 推送，或只写不读的日志在长胖时 ⇒ 先看现场留回滚网，写文件守编码，跨边界重跑不搬，推送前后都核对，日志轮转先 dry-run。
axis_domain: [环境·运维]
axis_help: [实现, 维护, 验证]
axis_concern: [正确性, 安全]
keywords: [环境·运维, 域能力, domain-ops, 日志轮转, 日志, gzip, dry-run]
domain: 环境·运维
# 域能力（一个领域一个文件 · 片不含 class）
parts:
  - id: domain-ops#survey
    domain: 环境·运维
    label: 现场与回滚网
    one_line: 开工先 git status 看现场；改乱看 diff、回原样用 checkout
    from: [version-collaboration#survey, version-collaboration#safety]
  - id: domain-ops#write-safe
    domain: 环境·运维
    label: 写文件纪律
    one_line: 改文件只用 edit/write，写完读回查 BOM 与乱码
    from: [host-runtime-traps#write]
  - id: domain-ops#transport-seam
    domain: 环境·运维
    label: 传内容与工具接缝
    one_line: 内容先落 UTF-8 文件再交外部程序；起进程 -Wait；路径统一斜杠
    from: [host-runtime-traps#transport, host-runtime-traps#path]
  - id: domain-ops#readback
    domain: 环境·运维
    label: 读回核对
    one_line: 按判据核 diff、JSON 解析与读回首 40 字
    from: [host-runtime-traps#verify]
  - id: domain-ops#cross-machine
    domain: 环境·运维
    label: 跨机边界
    one_line: 换机器重跑 init.sql，不直接搬数据目录
    from: [data-change-safety#migrate]
  - id: domain-ops#push-scope
    domain: 环境·运维
    label: outgoing 范围
    one_line: 先核实 base 与 outgoing 范围，已提交与 worktree 分开看
    from: [pre_push_evidence_gate#scope]
  - id: domain-ops#push-lease
    domain: 环境·运维
    label: 重写保护与推后核对
    one_line: 重写推送前记远端 OID 用 force-with-lease；推后核对 ref 与 CI
    from: [pre_push_evidence_gate#lease, pre_push_evidence_gate#verify]
  - id: domain-ops#land-chain
    domain: 环境·运维
    label: 小步落库
    one_line: 每完成一个功能立即小 commit；依赖链按实时状态整链落库，完成才删分支
    from: [version-collaboration#small, version-collaboration#land]
  - id: domain-ops#log-rotate
    domain: 环境·运维
    label: 日志轮转
    one_line: 只写不读的日志先 dry-run 再 gzip 轮转，留 N 份归档
    origin: 探针日志曾长到 481 MB ⇒ 轮转脚本（gzip 轮转 + 保留 N 份 + dry-run 护栏）
merge_of:
  - data-change-safety
  - host-runtime-traps
  - pre_push_evidence_gate
  - version-collaboration
---

# 环境·运维 能力（域能力）

> 由 4 个旧能力合并抽象而成（旧文件在 `capabilities/_archive/`）。
> 一个领域一个文件；片不含阶段字段（Human 口径：领域才是分类轴）。

## 什么时候用

当要跨机器 / 跨进程 / 推送，或只写不读的日志在长胖时 ⇒ 先看现场留回滚网，写文件守编码，跨边界重跑不搬，推送前后都核对，日志轮转先 dry-run。

## 做法

1. **现场与回滚网** —— 开工先 git status 看现场；改乱看 diff、回原样用 checkout；依赖链用干净 worktree
   > 出处：`version-collaboration#survey` · `version-collaboration#safety`
2. **写文件纪律** —— 改文件只用 edit/write，写完读回查 BOM 与乱码
   > 出处：`host-runtime-traps#write`
3. **传内容与工具接缝** —— 内容先落 UTF-8 文件再交给外部程序；起进程用 -Wait；拼路径统一斜杠；参数先落文件避开前导空格
   > 出处：`host-runtime-traps#transport` · `host-runtime-traps#path`
4. **读回核对** —— 按判据核 diff、JSON 解析与读回首 40 字
   > 出处：`host-runtime-traps#verify`
5. **跨机边界** —— 换机器重跑 init.sql，不直接搬数据目录
   > 出处：`data-change-safety#migrate`
6. **outgoing 范围** —— 先核实 base 与 outgoing 范围，已提交与 worktree 分开看
   > 出处：`pre_push_evidence_gate#scope`
7. **重写保护与推后核对** —— 重写推送前记远端 OID、用 force-with-lease；推后核对远端 ref 与 CI，pending 如实报
   > 出处：`pre_push_evidence_gate#lease` · `pre_push_evidence_gate#verify`
8. **小步落库** —— 每完成一个功能立即小 commit；依赖链按实时状态整链落库，完成才删分支
   > 出处：`version-collaboration#small` · `version-collaboration#land`
9. **日志轮转** —— 只写不读的日志先 dry-run 再 gzip 轮转，留 N 份归档
   > 出处：探针日志曾长到 481 MB ⇒ 轮转脚本（gzip 轮转 + 保留 N 份 + dry-run 护栏）

## 片的覆盖来源

| 新片 | 抽象自 |
|---|---|
| `domain-ops#survey` | `version-collaboration#survey` · `version-collaboration#safety` |
| `domain-ops#write-safe` | `host-runtime-traps#write` |
| `domain-ops#transport-seam` | `host-runtime-traps#transport` · `host-runtime-traps#path` |
| `domain-ops#readback` | `host-runtime-traps#verify` |
| `domain-ops#cross-machine` | `data-change-safety#migrate` |
| `domain-ops#push-scope` | `pre_push_evidence_gate#scope` |
| `domain-ops#push-lease` | `pre_push_evidence_gate#lease` · `pre_push_evidence_gate#verify` |
| `domain-ops#land-chain` | `version-collaboration#small` · `version-collaboration#land` |
| `domain-ops#log-rotate` | 探针日志曾长到 481 MB ⇒ 轮转脚本（无旧片祖先） |
