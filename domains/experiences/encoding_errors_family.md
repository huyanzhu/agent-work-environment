---
title: 遇到中文乱码/编码错误（改文件、读输出、重定向都算）
family: 中文编码/乱码
form: inject
status: pilot
trigger: 乱码, mojibake, 编码错误, 中文乱码, UTF-8, UTF-16, GBK, BOM, 读回乱码, 命令行中文, 中文被吃掉, 引号消失, 重定向, 管道输出, Get-Content, Out-File, Set-Content, PowerShell 写中文, 文档中文全坏, 开关不生效, JSON 解析失败, 配置回落缺省
keywords: 乱码, mojibake, 编码, encoding, utf-8, utf-16, gbk, bom, ef bb bf, 中文, 读回, 重定向, 管道, out-file, set-content, get-content, powershell, 恢复, 原始, 开关, 配置, json, 回落, 缺省, 静默
alias: 锛, 鈥, 涓, 锟斤拷, 问号方块, 中文变怪字, 编码被搞坏, 乱码文件, 中文全坏, 打开全是乱码, 写进去变成奇怪符号, 读回来是问号和方块, 好好的中文突然不对, 开关开了却没生效, 配置被写成 BOM, JSON 解析不了, 配置静默回落成缺省值
---

遇到中文乱码或编码错误时，先判断是"写坏了 / 读错了 / 传丢了"，按下表照做；⛔ 不要先怀疑内容本身。

**做法 A · 改文件只用 edit/write（⛔ 不用 PowerShell 整文读写）**
- 用 PowerShell `Replace()` 做「读全文→替换→写回」⇒ 中文变 mojibake + 加 BOM + 行尾变化；已损坏后**不可无损还原** → 改文件一律用 `edit` / `write` 工具（增量替换）
- 必须整文处理时用 Python / Node 显式 `encoding='utf-8'`（写回无 BOM），写前先备份

**做法 B · 读文件显式按 UTF-8**
- `Get-Content` 读中文 md 出现乱码（默认编码与控制台代码页不一致）→ 用 `read` 工具，或 `Get-Content -Encoding utf8`
- 读到乱码先怀疑**读侧编码**；UTF-8 能解码 ≠ 内容正常（mojibake 后不可逆）

**做法 C · 重定向/管道输出显式 UTF-8**
- PowerShell 5.1 的 `>` 写 UTF-16LE（带 BOM）⇒ 下游按 UTF-8 读必炸 → 用 `Out-File -Encoding utf8` 或 `[IO.File]::WriteAllText(..., UTF8Encoding($false))`
- 命令输出存 JSON / 文本给别的进程读之前，先确认编码，再读回验证

**做法 D · 写 JSON 配置/开关一律 BOM-less（P94）**
- PS 5.1 的 `Set-Content -Encoding utf8`（以及 `Out-File -Encoding utf8`）**必带 `EF BB BF`** ⇒ 读侧 `JSON.parse` / `json.load` 直接抛 ⇒ 被 catch 成"关 / 缺省" ⇒ **开关看起来开了实际没开、且零报错**（P32 的写侧真因）
- 写配置用 `[IO.File]::WriteAllText(p,s,[Text.UTF8Encoding]::new($false))` 或 python `open(p,'w',encoding='utf-8')` / node `fs.writeFileSync(p,s,'utf8')`；写完**读首 3 字节**核非 BOM
- 判读：变更开关/配置**不生效且零报错** ⇒ 第一怀疑 BOM，⛔ 别先怀疑"没重启"

**验证**：读回文件前 200 字确认中文正常、无 `锛/鈥/涓` 类乱码、无 BOM（`Format-Hex` 看前 3 字节不是 EF BB BF）；写过的 JSON 配置文件同样核首 3 字节。
**覆盖的坑（成员声明）**：P13 · P21 · P32 · P54 · P56 · P68 · P79 · P94（共 8 条）
**细节指针**：`domains/experiences/mojibake_prevention.md`（四条硬规则）· `task_cards/memory/PITFALLS.md` P32 / P94

**同义现象（命中这些也算遇到本族）**：中文乱码 · 编码错误 · mojibake · UTF-8 / UTF-16 / GBK · BOM · 读回乱码 · 命令行中文被吃掉 · 引号消失 · 文档中文全坏 · 重定向后读不了 · 写文件后中文变怪字 · **写进去的中文变成奇怪符号** · **读回来是问号和方块（原本好好的）** · **好好的中文突然全不对了** · `锛` `鈥` `涓` · PowerShell 读写中文 · 编码被搞坏 · 恢复原始中文 · **开关打开了却没生效** · **配置被静默回落成缺省值** · **JSON 文件解析失败（明明没改错）** · **写配置后要查 BOM**。
