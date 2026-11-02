---
rule_id: mojibake_prevention
title: 中文文件不乱码的四条硬规则
trigger:
  - 用 PowerShell 读写中文 Markdown/JSON/源码
  - 文件出现 鈥/锛/涓/杞/锟斤拷 等字样
  - 需要整文替换（Get-Content -Raw + Set-Content）
  - 生成或转换文件后要写回
condition: Windows + PowerShell + UTF-8 工程
action:
  do:
    - 改文件只用 edit/write 工具（增量替换，不整文读写）
    - 必须整文处理时用 Python open(..., encoding='utf-8') 或 Node fs.readFileSync(p,'utf8')
    - 写回用 [IO.File]::WriteAllText(p,s,[Text.UTF8Encoding]::new($false))（无 BOM）
    - 写完立刻验证：读回前 40 字 + mojibake 特征串 + 首三字节是否 EF BB BF
  dont:
    - 不用 PowerShell > / Out-File 把内容交给别的工具读（UTF-16 带 BOM）
    - 不在 GBK 控制台里肉眼判断"文件是否乱码"
    - 不用 Get-Content 整文读中文再 Set-Content 写回
keywords:
  - mojibake
  - encoding
  - utf-8
  - powershell
  - bom
  - 乱码

knowledge_position: Standalone
knowledge_cluster: FC-001 Encoding
epistemology_tag: OBSERVATION
confidence: HIGH
---

# 中文文件不乱码的四条硬规则

## 现象
中文 Markdown / JSON / 源码出现 `鈥`、`锛`、`涓`、`杞`、`锟斤拷` 等字样；或 UTF-8 解码不报错但内容坏；或 JSON 首字节有 BOM 导致 `json.load` 失败。

## 根因（三个不同机制，别混）
1. **PowerShell 5.1 的 `>` / `Out-File` 默认写 UTF-16LE（带 BOM）** ⇒ 下游按 UTF-8 读必炸（`0xff in position 0`）。
2. **`Set-Content -Encoding utf8` 带 BOM**（PS5.1）⇒ JSON/YAML 解析失败。
3. **GBK 字节被当 UTF-8 解码再写回** ⇒ 生成 mojibake（**合法 UTF-8，但语义已坏**）；此后**无法无损还原**（GBK 映射有损，观察约 10% 字符变 `?`）。

## 四条硬规则
1. 改文件只用 `edit` / `write` 工具（增量替换）。
2. 必须整文处理：Python `open(..., encoding='utf-8')` 或 Node `fs.readFileSync(p,'utf8')`。
3. 写回无 BOM：`[IO.File]::WriteAllText(p,s,[Text.UTF8Encoding]::new($false))`；⛔ 不用 `Set-Content -Encoding utf8`。
4. 写完立刻验证：读回前 40 字 + 特征串 `鈥|锛|涓|杞|锟斤拷` + 首三字节是否 `EF BB BF`。

## 已损坏时
1. 先查 git 历史：`git log --all --oneline -- <file>`；有正确版本 ⇒ `git checkout <commit> -- <file>`。
2. 无正确版本 ⇒ mojibake 还原：`raw.encode('gbk', errors='replace').decode('utf-8', errors='replace')`——**有损**（观察 3 文件丢 40–84 字符），只能当重建残片。
3. 损失大 ⇒ 备份原件（`scratch/mojibake-backup/`）→ 按残片重建 → 文件头标「重建非原文」。

## 判据
- 反例：`git diff` 出现整文件替换、中文变 `鈥?` ⇒ 已破坏。
- 正例：`git diff` 只显示预期几行；`json.load` 成功；首三字节非 BOM。
