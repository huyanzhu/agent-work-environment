# 样本：探针行长什么样（怎么确认"注入真的发生了"）

> 用途：新人想知道"系统到底有没有注入/召回"时，看的是**探针日志**。
> 真实日志在 `.aios/_aios-activation.probe.log`（缺失 = 还没接过宿主；按 50 MiB 阈值轮转，归档 `*.gz`）。

每行格式：`[aios-activation] {JSON}`。下面是四类关键事件的**样例**（字段含义见注释）。

## ① 插件加载（改完代码/重启后**先看这一条**）

```json
{"ev":"apply","plugin":"aios-activation","policy":"activation+…+v51r-declared-domain+v51s-encoding-query-fallback+v51t-cell-code-removed","cardsDir":"<repo>/task_cards/active","obs":"…","t":1762000000000}
```
> `policy` 尾部 token = **当前加载的版本**。与源码里的 POLICY 不一致 ⇒ 没重启，跑的还是旧代码。

## ② 阶段注入（能力在"对的时机"出现）

```json
{"ev":"phase-inject","phase":"S1","state":"injected","basis":"declared","capability":"domain-frontend","domain":"前端","n":1,"chars":132,"session":"session-…","at":1762000001000}
{"ev":"phase-inject","phase":"S1","state":"dup","basis":"declared","capability":"domain-frontend","domain":"前端","n":0,"session":"session-…","at":1762000002000}
```
> `state`：`injected` 真注入 · `dup` 同阶段同能力已注过（正常去重）· `declared-error` 声明解析失败。
> `basis`：`declared` = 跟随卡上声明的域能力（⛔ 不猜域）。`capability` 为空 = 走检索候选通道。

## ③ 经验召回（失败后给"别再踩"）

```json
{"ev":"experience-recall","trigger":"exec-permission-error","hits":2,"chars":412,"state":"ok","session":"session-…","at":1762000003000}
```
> `trigger` 是失败类型分类；**`hits:0` 先查 query 能否分词 / 证据源是否还在**（别直接读成"库里没有"）。

## ④ 节点注入（场景触发：改语料 / 重建索引 / 跑回归门）

```json
{"ev":"node-inject","node":"N2","state":"injected","session":"session-…","at":1762000004000}
```

---

## 自己验一遍的最小命令

```bash
# 有没有加载过？（没有 .aios 目录 = 还没接过宿主）
python - <<'PY'
import io, json, os
p = ".aios/_aios-activation.probe.log"
if not os.path.isfile(p):
    print("(日志不存在：插件还没在宿主里跑过)"); raise SystemExit
last = None
for line in io.open(p, encoding="utf-8", errors="replace"):
    try: d = json.loads(line.split("] ", 1)[1])
    except Exception: continue
    if d.get("ev") == "apply": last = d
print("加载的 POLICY 尾 token:", (last or {}).get("policy", "(无 apply 记录)").split("+")[-1])
PY
```
