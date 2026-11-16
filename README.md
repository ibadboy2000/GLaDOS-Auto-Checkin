# 📌 GLaDOS 自动签到

## 浏览器签到（2026-11-16）

本次改进先读取官网积分记录（UTC+8），已签到账号直接返回“已签到”及今日所得积分，不再次点击。记录无法核对时暂停提交。
对于尚未签到的账号，先等待官网 challenge 加载，并在需要 Turnstile 时等待原生组件报告验证就绪（最多 90 秒），再由官网页面完成证明与提交。等待超时会失败退出，记录 `checkin_posted=false`，不会提交无效验证或自动重试签到 POST。
手动运行默认启用 `verify_only`，与分支 push 验证一样跳过通知、兑换，且任一账号失败均返回失败。模拟测试成功只说明流程正确；当天已签到的账号通过预检也不代表新的云端签到或 Cloudflare 验证已通过。
分支 push 还会启用只读的验证就绪检查：即使今天已签到，也等待网站原生 Turnstile 就绪，但绝不再次提交。手动验证可勾选 `probe_verification`；常规定时签到不启用此检查。

**验证状态：尚未恢复 GitHub 免费托管环境的无人值守签到，不应作为已修复版本合并。**

- [Linux Chromium 试运行](https://github.com/ibadboy2000/GLaDOS-Auto-Checkin/actions/runs/43722927718)：7 项测试通过，两个真实账号返回 `device-mismatch`，Turnstile 等待超时。
- [Windows Chrome 试运行](https://github.com/ibadboy2000/GLaDOS-Auto-Checkin/actions/runs/43723752017)：7 项测试通过，两个真实账号不再返回设备不匹配，但均返回 `reason=turnstile`、`tsState=timeout`；签到未记录。
- 上述试运行未发送通知、未兑换积分。仅迁移 Cookie、改用 Windows 或恢复旧浏览器脚本均未使本次云端验证成功。
- [Windows Chrome 诊断运行](https://github.com/ibadboy2000/GLaDOS-Auto-Checkin/actions/runs/43725307578)：8 项测试通过；两个真实账号均有 1 个验证 iframe，Cloudflare 主域名无记录到的网络失败，有成功的 HTTP 200 响应，页面 Date 与本机时间差为 0–1 秒；仍返回 `reason=turnstile`、`tsState=timeout`，未取得有效验证令牌。未捕获到六位客户端错误码，未观察到可见复选框；这些信息不能证明已识别出服务端具体判定规则。
- 诊断中的 `verification_script_loaded=false` 只识别原始脚本地址，可能受 `api.js` 重定向影响，不能据此断言脚本加载失败：已改为跟踪重定向链，并增加测试；验证 iframe 已实际加载。页面 Date 仅作参考，不等于权威时钟校验。
- Cloudflare 官方说明：[生产验证不支持自动化浏览器及 Playwright 等框架](https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/)；[PAT 请求的 HTTP 401 可能是正常回退](https://developers.cloudflare.com/cloudflare-challenges/troubleshooting/challenge-solve-issues/)，不能单独作为被拦截或环境故障的依据。
- 还需要能够在托管环境正常通过的网站验证流程或服务方支持的自动化方式；本分支不包含人工验证绕过、令牌伪造或第三方验证码服务。

默认使用标准 Playwright Chromium 打开官网签到页，由页面获取 challenge 并处理 Turnstile，再读取实际签到接口结果。现有 `COOKIES`、多账号、通知渠道和定时时间继续使用。

- GitHub Actions 使用 Windows 免费托管环境中预装的标准 Chrome，安装 `requirements.txt` 和测试用 Chromium。
- 登录设备不匹配或验证需要人工处理时会报告失败；浏览器模式不能保证所有运行环境均可无人值守通过验证。
- `codex/restore-browser-checkin` 分支的 push 会自动验证，验证时不发通知、不兑换积分，要求每个账号均成功或已签到。
- 积分兑换仅在签到成功或已签到且达到所配阈值时执行。
- 本地运行：`pip install -r requirements.txt`、`python -m playwright install chromium`，设置 `COOKIES` 后执行 `python checkin.py`。
- 如需诊断旧接口，可显式设置 `GLADOS_CHECKIN_MODE=http`；该模式不执行网页验证。

---

一个基于 **GitHub Actions** 的 **GLaDOS 自动签到脚本**。

**无需服务器、无需编程基础**，每天自动帮你签到。

---

## ✨ 功能特性

- ✅ 每天自动签到，已签到自动识别
- 👥 支持多账号（`|||`、`&` 或换行连接）
- 📊 查询总积分和剩余天数
- 📬 8 种推送渠道：PushDeer / Server酱 / Telegram / PushPlus / 钉钉 / 飞书 / 企业微信 / 云湖
- 🔄 网络请求自动重试（指数退避）
- 🔒 日志脱敏（邮箱/Cookie 自动隐藏）
- ✅ Cookie 结构预验证（前缀无关，自动兼容 `koa:` / `gld:` 等任意前缀）
- 🔧 每月自动空提交保活
- 💎 积分自动兑换（可选，消耗积分兑换会员天数）
- 🆓 完全免费

---

## 📂 项目结构

```
.
├── checkin.py                 # 签到脚本
└── .github/workflows/
    └── glados.yml             # GitHub Actions 配置
```

---

## 🚀 使用教程

### 第一步：Fork 本项目

点击右上角 **Fork**，Fork 到你自己的 GitHub 账号下。

---

### 第二步：获取 GLaDOS Cookie

1. 打开浏览器，登录 https://glados.cloud
2. 按 **F12** 打开开发者工具
3. 找到 `Application` → `Cookies` → `glados.cloud`
4. 复制完整 Cookie 内容

示例（官网当前签发的是 `gld:` 前缀）：
```
gld:sess=xxxxxx; gld:sess.sig=yyyyyy
```

旧版签发的 `koa:sess=xxxxxx; koa:sess.sig=yyyyyy` 同样支持，**两种前缀任选其一，无需手动转换**。

⚠️ **必须是完整的一整段**，且 `sess` 与 `sess.sig` 两个字段**必须同时存在、前缀一致**。
只复制其中一个会导致签到失败（脚本会明确指出缺少哪个字段）。

> 💡 脚本采用**结构校验**：只校验「`<前缀>:sess` 与同前缀 `:sess.sig` 成对」，
> 不写死具体前缀。因此 GLaDOS 即便再次变更前缀名，脚本也能自动识别，无需修改代码。
> **不要把 `gld:` 改成 `koa:`** —— 改前缀会让服务端无法识别 session，导致「没有权限」。

---

### 第三步：添加 GitHub Secrets

进入你 Fork 后的仓库：

1. **Settings** → **Secrets and variables** → **Actions** → **Secrets** 标签页
2. 点击 **New repository secret**
3. 添加：
   - **Name**：`COOKIES`
   - **Value**：粘贴刚才复制的 Cookie
4. 点击 **Save**

⚠️ **必须填在 Secrets，不是 Variables。** 填错位置脚本会读不到值，直接报
`未检测到 COOKIES`。变量名必须是 `COOKIES`，不能有多余空格。

---

### 第四步：（可选）配置推送

在 GitHub Secrets 中添加对应的环境变量：

| 渠道 | 必填环境变量 | 可选 |
|------|-------------|------|
| PushDeer | `SENDKEY` | - |
| Server酱 | `SERVERCHAN_KEY` | - |
| Telegram | `TG_BOT_TOKEN` + `TG_CHAT_ID` | - |
| PushPlus | `PUSHPLUS_TOKEN` | - |
| 钉钉机器人 | `DINGTALK_WEBHOOK` | `DINGTALK_SECRET` |
| 飞书机器人 | `FEISHU_WEBHOOK` | `FEISHU_SECRET` |
| 企业微信机器人 | `WECOM_BOT_WEBHOOK` | - |
| 云湖机器人 | `YUNHU_TOKEN` + `YUNHU_RECV_ID` | `YUNHU_RECV_TYPE` |

> 🔑 **钉钉 / 飞书加签说明**：若机器人启用了「加签」校验，则 `DINGTALK_WEBHOOK` + `DINGTALK_SECRET`（或 `FEISHU_WEBHOOK` + `FEISHU_SECRET`）**必须同时配置**。只配 webhook 不配 secret 时，脚本会发送无签名请求并给出告警，加签机器人将鉴权失败。

---

### 第五步：（可选）积分自动兑换

在 GitHub Secrets 中添加 `EXCHANGE_PLAN`（或 `GLADOS_EXCHANGE_PLAN`，二选一）即可启用自动兑换积分功能。**不配置则默认不兑换**，不影响任何现有签到逻辑。

| 配置值 | 消耗积分 | 兑换天数 |
|--------|---------|---------|
| `plan100` | 100 积分 | 10 天 |
| `plan200` | 200 积分 | 30 天 |
| `plan500` | 500 积分 | 100 天 |

机制说明：

- 每次签到后，仅在**总积分 ≥ 计划所需积分**时才调用兑换接口，否则自动跳过（不会浪费积分）。
- 兑换结果会附加到签到日志行末尾，例如：`| 兑换:🎁 兑换成功(+30天)`。
- 兑换失败 / 异常**不影响**签到结果与运行退出码。

---

## 👥 多账号配置

多个账号的 Cookie 用 `|||`、`&` 或**换行**连接（三种分隔符均可混用，推荐使用 `|||` 以避免与 Cookie 值冲突）：

```
cookie_账号1 ||| cookie_账号2 ||| cookie_账号3
```

或

```
cookie_账号1
cookie_账号2
cookie_账号3
```

⚠️ Cookie 值本身不得包含 `|||`、`&` 或换行符，否则会被错误拆分。推荐使用 `|||` 作为分隔符，因为 Cookie 值中几乎不可能出现该字符串。

---

## ⏰ 签到时间

每天 **UTC 04:00**（北京时间 **中午 12 点**）自动运行。

---

## 📋 签到结果

| 状态 | 说明 |
|------|------|
| ✅ 成功 | 签到成功，显示获得积分 |
| 🔄 已签到 | 今日已签到过 |
| ❌ 失败 | 签到失败，显示原因 |

---

## ❓ 常见问题

**Q: 签到提示「没有权限」/ 鉴权失败？**

A: 说明 Cookie 已失效或复制不完整，**请重新登录 GLaDOS 获取最新 Cookie 并更新 Secrets 中的 `COOKIES`**。
若日志提示「会话字段不成对」或输出了「实际键名」，则多为复制遗漏了 `sess` / `sess.sig` 其中之一，重新完整复制即可。

> 💡 脚本会自动识别 `koa:` / `gld:` 等任意前缀，**无需手动修改前缀**；反之，手动把前缀改错（如把 `gld:` 改成 `koa:`）会让服务端无法识别 session。

**Q: Cookie 有有效期吗？**

A: 有。Cookie 会随会话过期，需重新登录获取最新 Cookie 并更新 Secrets。

**Q: Actions 被暂停了？**

A: 项目内置每月空提交保活。如仍被暂停，手动触发一次 `workflow_dispatch`。

**Q: 日志中的邮箱为什么显示不完整？**

A: 出于隐私保护，邮箱会自动脱敏（如 `te***t@example.com`）。

**Q: 可以同时配置多个推送渠道吗？**

A: 可以，配置多个 Secrets 即可同时推送。

---

## 🔄 更新日志

### v2.1.1

**问题修复**
- 修复 GLaDOS 变更 Cookie 前缀（`koa:sess` → `gld:sess`）导致的签到失败：`validate_cookie` 原先把 `koa:sess` 写死校验，新版 Cookie 被误判为「缺少必要字段」，签到请求根本未发出，表现为「❌ 失败(没有权限)」

**优化改进**
- Cookie 校验改为**前缀无关的结构校验**：只校验「`<任意前缀>:sess` 与同前缀 `:sess.sig` 成对」，不再枚举任何前缀名——GLaDOS 未来再次变更前缀通常无需改代码即可自动适配
- 新增 `normalize_cookie`：自动剥离粘贴时混入的首尾引号、空白与 `Cookie:` 头名
- 新增自诊断日志：校验成功时打印识别到的会话前缀；失败时输出**实际解析到的键名**，前缀变化可一眼定位
- 服务端鉴权失败（没有权限 / 未登录等）与格式错误分开提示，明确引导「重新获取 Cookie」
- `glados.yml`：`COOKIES` 支持 `secrets` 与 `vars` 双路读取

---

### v2.1.0

**功能新增**
- 新增积分自动兑换功能（#9，可选配置 `EXCHANGE_PLAN` / `GLADOS_EXCHANGE_PLAN`，支持 plan100/plan200/plan500 三档策略；默认关闭，不影响现有签到）
- 兑换请求单次尝试不重试（非幂等操作，避免响应丢失后重复扣积分）

---

### v2.0.0

**功能新增**
- 新增 Telegram Bot 推送
- 新增 PushPlus（推送加）推送
- 新增钉钉机器人推送（支持加签验证）
- 新增飞书机器人推送（支持加签验证）
- 新增企业微信机器人推送
- 新增云湖机器人推送
- 新增总积分查询功能
- 新增网络请求自动重试机制（指数退避）
- 新增 Cookie 格式预验证
- 新增日志脱敏处理（邮箱/Cookie 自动隐藏）
- 新增每月自动空提交保活机制

**问题修复**
- 修复 PushPlus 推送域名问题
- 修复飞书机器人加签算法

**优化改进**
- Python 版本升级至 3.11
- 多账号间请求增加随机延迟
- GitHub Actions 添加超时和并发控制
- 代码整合为单文件，简化部署

---

## 📄 许可证

MIT License

