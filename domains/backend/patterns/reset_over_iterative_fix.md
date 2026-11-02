---
rule_id: reset_over_iterative_fix
title: 3轮修不好就该重置（reset 优于迭代修补）
trigger:
  - 同一问题连续修改3次以上仍未解决
  - 多个变量交叉影响难以定位根因
condition: 已尝试多轮修复仍无效
action:
  do:
    - 备份当前代码
    - 从已知可工作版本或从零重建最简版本
    - 确认基础功能正常后再逐步添加特性
  dont:
    - 继续在第4+轮迭代上叠补丁
    - 同时修改多个不确定的变量
keywords:
  - reset
  - retry
  - fix
  - iteration
  - restart

knowledge_position: Standalone
knowledge_cluster: 
epistemology_tag: OBSERVATION
confidence: HIGH
---

> ⚠️ 重建：原文件为 GBK mojibake（git 历史 8546b73「v1 原样」引入时即坏，无正确版本）；以下按还原残片补全，**非逐字原文**。

# 重置优于迭代修补

## 问题
> 连续打了 6 轮补丁，问题依然存在。最终全量重置为最简版本后一切正常。

## 规律
当一个问题的连续修改 3 次以上仍无法解决时，说明根因判断有误，或修改引入了新的交叉干扰。此时继续修补的效率远低于从干净状态重建。

## 修复步骤
1. 备份当前代码（git stash / 另存）
2. 导入或重建最简可工作版本
3. 确认基础功能正常
4. 逐一添加特性，每加一个验证一次
