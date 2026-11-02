---
rule_id: wxml_ternary_breaks_binding
title: WXML三元表达式阻断数据绑定
trigger:
  - WXML class="{{cond ? 'a' : 'b'}}"
  - setData不生效但无报错
  - 页面部分渲染但不完整
condition: 微信小程序 WXML 中包含 ? : 三元表达式
action:
  do:
    - 将 WXML 中所有三元表达式移至 JS 预处理
    - 用 setData 传递计算好的类名字段
  dont:
    - 在 WXML 属性中使用 ? : 三元
keywords:
  - wxml
  - ternary
  - binding
  - wechat
  - miniapp

knowledge_position: Cluster
knowledge_cluster: FC-004 WeChat Miniapp
epistemology_tag: OBSERVATION
confidence: HIGH
---

> ⚠️ 重建：原文件为 GBK mojibake（git 历史 8546b73「v1 原样」引入时即坏，无正确版本）；以下按还原残片补全，**非逐字原文**。

# WXML三元表达式导致数据绑定失效

## 问题
在微信小程序的 WXML 中，`class="{{cond ? 'class-a' : 'class-b'}}"` 这样的三元表达式会导致 WXML 编译器静默失败：页面虽然能部分渲染，但所有数据绑定（setData）完全不生效，且控制台无报错。

## 根因
WXML 的 Mustache `{{}}` 内不允许使用引号字符串字面量（`'a'`），三元表达式中的引号导致编译器解析异常、静默失败。

## 修复
把所有条件逻辑移到 JS 层，通过 setData 传递计算好的类名：

```javascript
this.setData({ catBarClass: count > 0 ? "bar-active" : "bar" })
```

WXML 中直接使用 `class="{{catBarClass}}"`。

## 判定指标
- 部分渲染但 setData 不生效
- WXML 中存在带引号字面量的三元表达式
