---
title: 遇到推送/发布问题（git · gh · PR 都算）
family: 推送/发布
form: inject
status: pilot
trigger: 推送失败, 推送代码, git push, gh api, PR, pull request, credential, token, could not read Username, 404, trailing comma, 合法 JSON, 干净 base, upstream, jq, LF CRLF, 发布
keywords: git, github, gh, push, pull, pr, credential, helper, token, remote, origin, api, json, trailing, comma, base, diff, sha, jq, powershell, 推送, 发布, 行尾
alias: signal pipe, Win32 error 5, exit code 66, could not read Username, accepts 1 arg(s), pulls/N/files, contents?ref=, %2F, LF will be replaced by CRLF, failed to parse json, 夹带残留, 接口报参数数量不对, 确认没别人的东西混进来
---

遇到推送、拉取或 GitHub API 的问题时，先判断属于哪一类，按下表照做；⛔ 不要先怀疑账号或网络。

**做法 A · git push 失败：沙箱凭据 / 沙箱管道**
- `fatal error - couldn't create signal pipe, Win32 error 5` / `failed to execute prompt script (exit code 66)` / `could not read Username` ⇒ 沙箱限制 git 的 credential helper（⛔ 不是登录失效、不是网络问题；`gh auth status` 正常、`git fetch` 也正常）→ 用 `gh auth token` 取 token，`git -c credential.helper= push "https://<token>@github.com/<owner>/<repo>.git" main`；⛔ 不把 token 写进 remote/文件；推后核对 `origin/<当前分支>`（或 `git ls-remote`）已前进
- 🔴 **观察扩展**：`sh.exe: *** fatal error - couldn't create signal pipe, Win32 error 5` + `Could not read from remote repository` —— **本地 `file://` 传输也经 `sh.exe`**，被 DSH 沙箱“不能建管道”挡死（`git ls-remote` 同报错、bare 仓 0 refs）⇒ **不是凭据问题、也不是仓库配置**；处置 = 提权（`danger-full-access`）或换非 `sh` 传输；⛔ 不要反复改 remote/凭据
- 反复提示 `LF will be replaced by CRLF` ⇒ 行尾警告不是失败；需要时统一 `git config core.autocrlf`

**做法 B · gh api 的静默坑**
- 带 `-f` 的 GET 被当 POST（`accepts 1 arg(s), received 3`）→ 查询加 `--method GET`
- endpoint 里分支名含 `/` 直接 404（`%2F` 仍 404）→ 用 `git/ref/heads/<ref>` 查分支存在性
- 传文件后 `contents?ref=` 查该文件也 404，看起来像「没传上去」（实际 commit 存在）→ **以 PR diff 为准**（`pulls/N/files` 的 `.sha`/`.patch`）；推送用 `PUT repos/<fork>/contents/<path>` + `-F content=@<单行 b64 文件>`
- `pwsh` 里 `gh api -q '<jq>'` 的引号被 PowerShell 吃掉（报 `failed to parse json`）→ 换双引号/转义，或把查询写进临时脚本

**做法 C · PR 前：干净 base + 严格 JSON**
- 用「源码拷贝」当 PR 工作区 ⇒ 副本可能被别的会话改过（夹带 28 行残留）→ ① 目标文件 sha 核对 ② **全副本**与 upstream 比对 ③ 发现残留先备份再从 upstream 重建
- 删 JSON 字段后残留 `,}` / `,]` ⇒ 严格 JSON 破损（verify 报「不是合法 JSON」）→ 删完立刻 `python -c "import json; json.load(open(p,encoding='utf-8'))"` 或跑 verify

**验证**：推后核对 `origin/<当前分支>`（或 `git ls-remote`）已前进；PR 以 diff 为准（⛔ 不用 contents+ref 判成败）；JSON/产物跑校验脚本。
**覆盖的坑（成员声明）**：P14 · P37 · P41 · P42 · P43 · P71 · P88（共 7 条）
> 口径：**P39 / P44 / P47 已不在本族** —— 它们随「做法 D · 对外文案/账本」一起移出（不同解）⇒ 细节指针与探针期望集同步删除（P85 同代纪律）。
**细节指针**：`task_cards/memory/PITFALLS.md` P14 / P37 / P41 / P42 / P43 / P71 / P88

**同义现象（命中这些也算遇到本族）**：gh api 报 `accepts 1 arg(s)` · **接口报参数数量/个数不对** · 查分支文件 404 · 分支名带斜杠 · `git push` Win32 error 5 · signal pipe · `sh.exe … signal pipe` · Could not read from remote repository（本地 file:// 也算）· exit code 66 · could not read Username · credential helper · token 推送 · trailing comma · JSON 不是合法 JSON · 干净 base · **提交前想确认没别人的东西混进来（夹带/残留）** · PR 夹带 · 残留改动 · LF CRLF · gh -q 被 shell 吃掉 · 推送失败 · PR diff 对不上。

**已移出**：对外文案/账本口径（不同解）→ 单独维护（已归档）· 相关坑见 PITFALLS P47/P71
