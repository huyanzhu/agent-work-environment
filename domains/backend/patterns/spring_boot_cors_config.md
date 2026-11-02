---
rule_id: spring_boot_cors_config
title: Spring Boot 3.x CORS 配置方法
trigger:
  - CORS 跨域请求被拒
  - Access-Control-Allow-Origin 错误
  - 前后端分离项目跨域问题
  - 前端无法调后端 API
alias:
  - CORS 配置
  - 跨域
  - 前后端分离
condition: Spring Boot 3.x + Spring Security 6.x
action:
  do:
    - 在 SecurityConfig 中添加 .cors(cors -> cors.configurationSource(corsConfig()))
    - 创建 corsConfig() 方法，addAllowedOriginPattern("*")
    - addAllowedMethod("*") + addAllowedHeader("*") + setAllowCredentials(true)
    - 注册到 UrlBasedCorsConfigurationSource
  dont:
    - 不要用 WebMvcConfigurer + addCorsMappings（会被 Security 覆盖）
    - 不要 allowCredentials(true) + allowedOrigin("*") 混用（浏览器拒绝）
keywords:
  - CORS
  - 跨域
  - Spring Boot
  - 配置
  - 前端
---

> ⚠️ 重建：原文件为 GBK mojibake 且 YAML 结构破损（双 frontmatter 分隔符）；以下按还原残片重建，**非逐字原文**。

# Spring Boot 3.x CORS 配置

## 问题
Spring Boot 3 + Spring Security 6 下，仅在 `WebMvcConfigurer` 里写 `addCorsMappings` 不生效——请求仍被 Security 拦截。

## 正确做法
在 `SecurityConfig` 的安全过滤链上挂 CORS：

```java
http.cors(cors -> cors.configurationSource(corsConfig()))
```

并定义 `corsConfig()`：`addAllowedOriginPattern("*")`、`addAllowedMethod("*")`、`addAllowedHeader("*")`、`setAllowCredentials(true)`，注册到 `UrlBasedCorsConfigurationSource`。

## 两个坑
- `WebMvcConfigurer + addCorsMappings` 会被 Security 覆盖（不生效）
- `allowCredentials(true)` 与 `allowedOrigin("*")` 不能混用（浏览器拒绝）
