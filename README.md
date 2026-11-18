# feishu-demo

一个最小可用的飞书（Feishu / Lark）登录演示，**前后端分离**：

1. **获取应用凭证** —— 用手机飞书扫码，或在**本机浏览器**打开链接。飞书页面让用户选择「创建飞书应用」或「使用已有应用」；无论哪种，本演示都会拿到对应的 App ID + App Secret。
2. **用户登录授权** —— 在本机浏览器打开授权页点一次「确认授权」即可（也可改用手机扫码），后端拿到 `user_access_token` 与 **`refresh_token`**。
3. **调用飞书接口** —— 用拿到的 token 真实调用 `/open-apis/authen/v1/user_info`，并演示用 `refresh_token` 刷新出新 access_token。

**项目里不硬编码任何 App ID / Secret**，凭证完全在运行时获得，且只保存在服务端内存中。

> **为什么是两次确认？** 这不是本演示的设计，而是飞书机制本身的边界：第 1 次确认只负责
> **创建/选择应用并签发 App ID + Secret**（`registerApp`，返回字段只有 `client_id` / `client_secret` /
> `user_info.open_id` / `tenant_brand`，不含任何 token）；用户的
> `user_access_token` / `refresh_token` 必须由第 2 次「用户授权」确认发放。官方 SDK 与
> `@larksuite/cli` 同样是两次：`config init` 建应用 + `auth login` 授权。
>
> **想只确认一次？** 在 `backend/.env` 里填好 `LARK_APP_ID` / `LARK_APP_SECRET`（用你自己已有的应用），
> 第 1 步会自动跳过，整个演示只剩第 2 步的「确认授权」。见下方「配置项」。

---

## 快速开始

需要 Python 3.13+（用 [uv](https://docs.astral.sh/uv/) 管理）、Node.js 18+。

### 后端

```bash
cd backend
cp .env.example .env          # 可选：按需修改配置
uv sync                       # 安装依赖
uv run uvicorn app.main:app --reload --port 8000
```

后端跑在 http://127.0.0.1:8000。

### 前端

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

打开 **http://127.0.0.1:5173**，按页面上的三个步骤依次点击即可。

> Vite 已配置把 `/api` 代理到 `http://127.0.0.1:8000`，前后端同源，httpOnly cookie 可直接工作。

---

## 你需要具备的条件

**不需要**事先在开放平台创建应用 —— 本演示就是现场扫码创建的。

唯一要求：你的飞书账号在目标企业内**有权限创建自建应用**。普通成员通常需要企业管理员在
「飞书管理后台 → 安全与合规 → 开发者权限」中开放自建应用创建权限。若走「使用已有应用」分支，
则需要该应用对你可见。

---

## 配置项（backend/.env）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LARK_BRAND` | `feishu` | `feishu`（国内版）或 `lark`（国际版），决定使用哪套域名与凭证存储 |
| `LARK_SCOPES` | `offline_access` | 第 2 步申请的权限点，空格或逗号分隔。`offline_access` 会被自动追加（拿 `refresh_token` 的最低要求） |
| `LARK_SOURCE` | `node-sdk/feishu-demo` | 扫码链接上的来源标记 |
| `LARK_APP_ID` / `LARK_APP_SECRET` | 空 | **可选**。填了就跳过第 1 步（不再扫码建应用），直接用这套凭证做用户授权，全程只需一次确认 |

**只想确认一次（推荐）** —— 用你自己的应用凭证：

```bash
# backend/.env
LARK_APP_ID=cli_xxxxxxxxxxxxxxxx
LARK_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

重启后端后，第 1 步显示「已跳过」，页面直接从第 2 步开始。注意凭证与 token 要配套：
扫码流程签发的 `refresh_token` 只对当时那套凭证有效，换了应用要重新授权。

**关于 scope**：默认只要 `offline_access`，因为飞书在申请未在应用后台声明的权限点时会报
`20067` / `20068`。想演示更多权限，先在应用后台「权限管理」里声明，再写进 `LARK_SCOPES`：

```bash
LARK_SCOPES=offline_access contact:user.base:readonly
```

页面上会展示实际授予的 scope 列表，方便对照。

---

## 接口调用链

三步背后真实发生的 HTTP 请求（均在服务端发起，浏览器只与自己的后端通信）：

| 步骤 | 请求 | 说明 |
|---|---|---|
| 1 | `POST https://accounts.feishu.cn/oauth/v1/app/registration`<br>`action=begin` | 拿到 `device_code` + 确认链接（本机浏览器打开或手机扫码） |
| 1 | 同上，`action=poll` + `device_code` | 确认完成后返回 `client_id` + `client_secret`（**此步不发放任何 token**） |
| 2 | `POST https://accounts.feishu.cn/oauth/v1/device_authorization`<br>`client_id`, `scope`(含 `offline_access`)，客户端认证用 HTTP Basic | 用户授权用的设备码；本机浏览器打开链接点「确认授权」即可 |
| 2 | `POST https://accounts.feishu.cn/oauth/v3/token`<br>`grant_type=urn:ietf:params:oauth:grant-type:device_code` | 换 `access_token` + `refresh_token` |
| 3 | `GET https://open.feishu.cn/open-apis/authen/v1/user_info`<br>`Authorization: Bearer <user_access_token>` | 演示调用 |
| 3 | `POST https://accounts.feishu.cn/oauth/v3/token`<br>`grant_type=refresh_token` | `refresh_token` 是一次性的，每次刷新换新的 |

轮询遵循 RFC 8628：默认 5 秒；飞书返回 `slow_down` 时把间隔 +5 秒（上限 60 秒）；
`expired_token` / `invalid_grant` 视为过期需重来；`access_denied`（用户拒绝）终止流程。

---

## 项目结构

```
backend/
  app/
    lark.py    # 飞书三个流程的 HTTP 客户端（无第三方 SDK 依赖，只用 httpx）
    store.py   # 内存会话存储；凭证只在这里
    main.py    # FastAPI 路由
  scripts/
    mock_server.py  # 本地联调用的假数据服务（不消耗真实凭证）
frontend/
  index.html   # 三步向导页面
  src/main.js  # 轮询与渲染（二维码由前端本地用 qrcode 生成）
  src/style.css
```

## 不扫码也能调前端

想在不消耗真实凭证的情况下检查页面渲染：

```bash
cd backend
uv run uvicorn scripts.mock_server:app --port 8001     # 假数据后端

cd frontend
API_TARGET=http://127.0.0.1:8001 npm run dev           # 把代理指向它
```

它会用固定响应替换飞书的网络调用，其余路由逻辑与真实后端完全一致。

## 设计要点

- **凭证只保存在服务端**：飞书返回的 App Secret 与 token 存在后端内存里，前端按需读取展示；
  页面底部「重置本次演示」会立即清空。
- **会话隔离**：httpOnly cookie + 服务端内存字典，演示用够了；进程重启即清空。
- **不发送 `addons`**：官方 SDK 的 `addons` 会向应用增量写入权限；若用户选择「使用已有应用」，
  那等于改动他的现有应用配置。本演示不做这种副作用，创建出的应用保持平台默认模板。
- **轮询在后端节流**：前端定时调 `/api/*/poll`，后端按 `interval` 节流，避免打爆飞书接口。

---

## 已知限制与注意事项

- **凭证获取机制属于「官方公开但文档外」**：`accounts.feishu.cn` 上的
  `app/registration`、`device_authorization`、`oauth/v3/token` 三个端点，飞书只把契约写在
  官方 SDK 源码里（Node / Go / Java 三个 SDK 的 `registerApp` 均以 MIT 协议公开，README 有完整参数表），
  开放平台文档站没有对应的独立页面。本演示已用真实请求验证其可用，但这类接口无文档稳定性承诺，
  飞书版本变动时需回看官方 SDK 源码。
- **本演示用普通 Bearer，不实现 DPoP**。飞书 CLI 默认 `dpopMode=preferred`（可选），
  普通客户端可直接工作。若你的应用在服务端被配置为强制 DPoP，需要额外实现 DPoP 证明。
- **需要一个真实飞书账号**：两次确认都要在飞书侧完成登录/授权，自动化测试无法替代。
  第 2 步可以只在本机浏览器点确认，不必用手机；第 1 步若走扫码创建应用则需手机飞书。
  想彻底免扫码，用 `.env` 预置凭证（见「配置项」）。
- **演示应用 = 扫码者拥有**：扫码创建出的应用归属于扫码的那个飞书账号。若在正式环境使用，
  请据此设计凭证托管与回收策略。
