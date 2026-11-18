"""飞书（Feishu/Lark）客户端：设备码流程 + 应用凭证注册 + 用户接口调用。

这里用到的三个端点是官方 SDK（Node/Go/Java 的 `registerApp`）在用的机制，
契约只写在 SDK 源码里，开放平台文档站没有独立页面：

- POST /oauth/v1/app/registration        扫码创建/复用应用，直接换到 App ID + Secret
- POST /oauth/v1/device_authorization    用户授权（RFC 8628 设备码）
- POST /oauth/v3/token                   设备码换 token / refresh_token 刷新

全程不需要预先硬编码任何 App ID / App Secret。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

BRAND = os.getenv("LARK_BRAND", "feishu").strip().lower()

_HOSTS = {
    "feishu": {
        "accounts": "https://accounts.feishu.cn",
        "open": "https://open.feishu.cn",
    },
    "lark": {
        "accounts": "https://accounts.larksuite.com",
        "open": "https://open.larksuite.com",
    },
}
if BRAND not in _HOSTS:
    raise ValueError(f"LARK_BRAND 只能是 feishu 或 lark，收到：{BRAND!r}")

ACCOUNTS_HOST = _HOSTS[BRAND]["accounts"]
OPEN_HOST = _HOSTS[BRAND]["open"]

APP_REGISTRATION_URL = f"{ACCOUNTS_HOST}/oauth/v1/app/registration"
DEVICE_AUTHORIZATION_URL = f"{ACCOUNTS_HOST}/oauth/v1/device_authorization"
TOKEN_URL = f"{ACCOUNTS_HOST}/oauth/v3/token"
USER_INFO_URL = f"{OPEN_HOST}/open-apis/authen/v1/user_info"

# 设备码授权类型（RFC 8628）
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

# 演示默认只要 offline_access——这是拿到 refresh_token 的最低要求。
# 想演示更多权限时在 .env 里覆盖 LARK_SCOPES。
DEFAULT_SCOPES = ["offline_access"]
REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def effective_scopes() -> list[str]:
    """解析 LARK_SCOPES，并强制带上 offline_access（否则拿不到 refresh_token）。"""
    raw = os.getenv("LARK_SCOPES", "").strip()
    if raw:
        scopes = [s for s in raw.replace(",", " ").split() if s]
    else:
        scopes = list(DEFAULT_SCOPES)
    if "offline_access" not in scopes:
        scopes.append("offline_access")
    # 去重但保持顺序
    return list(dict.fromkeys(scopes))


def preset_app_credentials() -> tuple[str, str] | None:
    """从 .env 读取预置的应用凭证（可选）。

    填了之后第 1 步（扫码创建/选择应用）整体跳过，整个演示只剩一次
    「用户授权」确认。留空则走默认的扫码建应用流程。
    """
    app_id = os.getenv("LARK_APP_ID", "").strip()
    app_secret = os.getenv("LARK_APP_SECRET", "").strip()
    if app_id and app_secret:
        return app_id, app_secret
    return None


class LarkError(RuntimeError):
    """飞书侧的确定性失败（非 transient）。"""

    def __init__(self, code: str, description: str) -> None:
        self.code = code
        self.description = description
        super().__init__(f"{code}: {description}")


@dataclass
class Registration:
    """一次「扫码注册应用」的会话状态。"""

    device_code: str
    verification_url: str
    user_code: str = ""
    interval: int = 5
    expires_in: int = 240
    user_info: dict[str, Any] = field(default_factory=dict)
    client_id: str = ""
    client_secret: str = ""


@dataclass
class LoginFlow:
    """一次「用户授权」的会话状态。"""

    device_code: str
    verification_url: str
    user_code: str = ""
    interval: int = 5
    expires_in: int = 240


# ---------------------------------------------------------------------------
# 阶段的公共解析
# ---------------------------------------------------------------------------


def _parse_device_flow(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    """从 begin / device_authorization 的响应里取出二维码所需信息。"""
    device_code = payload.get("device_code")
    if not device_code:
        raise LarkError(
            payload.get("error", "invalid_response"),
            payload.get("error_description")
            or f"{source} 未返回 device_code：{payload!r}",
        )

    verification_url = (
        payload.get("verification_uri_complete") or payload.get("verification_uri") or ""
    )

    def _as_int(key: str, default: int) -> int:
        try:
            return int(payload.get(key) or default)
        except (TypeError, ValueError):
            return default

    return {
        "device_code": str(device_code),
        "verification_url": verification_url,
        "user_code": payload.get("user_code", "") or "",
        "interval": _as_int("interval", 5),
        "expires_in": _as_int("expires_in", 240),
    }


def _classify_poll_error(error: str) -> str:
    """把 token 端点的错误分类成 UI 需要处理的几种状态。

    注意：调用方必须先用 _extract_tokens 判断成功，不能把空 error 当成错误。
    """
    if not error:
        return "unknown"
    if error == "authorization_pending":
        return "pending"
    if error == "slow_down":
        return "slow_down"
    if error in ("expired_token", "invalid_grant"):
        return "expired"
    if error == "access_denied":
        return "denied"
    return "error"


def _extract_tokens(payload: dict[str, Any]) -> dict[str, Any] | None:
    """从响应里取出 token 包；兼容顶层与 data 包裹两种形状。

    成功响应的标志是有 access_token——绝不能靠「有没有 error」判断，
    因为成功响应根本没有 error 字段。
    """
    if payload.get("access_token"):
        return payload
    data = payload.get("data")
    if isinstance(data, dict) and data.get("access_token"):
        return data
    return None


# ---------------------------------------------------------------------------
# 阶段 A：扫码创建 / 复用应用，拿到 App ID + Secret
# ---------------------------------------------------------------------------


def _with_tracking_params(verification_url: str, *, source: str) -> str:
    """给扫码链接补上 SDK 用的来源标记参数（from / source / tp）。"""
    if not verification_url:
        return verification_url
    tracking = urlencode({"from": "sdk", "source": source, "tp": "sdk"})
    sep = "&" if "?" in verification_url else "?"
    return f"{verification_url}{sep}{tracking}"


async def app_registration_begin(*, client: httpx.AsyncClient | None = None) -> Registration:
    """开始「一键创建/复用应用」：返回二维码链接。

    注意：不传 createOnly，飞书页面才会让用户二选一（创建 / 使用已有）。
    """
    form = {
        "action": "begin",
        "archetype": "PersonalAgent",
        "auth_method": "client_secret",
        "request_user_info": "open_id tenant_brand",
    }
    source = os.getenv("LARK_SOURCE", "node-sdk/feishu-demo")
    async with _client(client) as c:
        resp = await c.post(APP_REGISTRATION_URL, data=form)
    payload = _json(resp)
    parsed = _parse_device_flow(payload, source="app/registration begin")
    parsed["verification_url"] = _with_tracking_params(
        parsed["verification_url"], source=source
    )
    return Registration(**parsed)


async def app_registration_poll(
    reg: Registration, *, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """轮询一次注册结果。返回 {'status': ...} 形态。"""
    form = {"action": "poll", "device_code": reg.device_code}
    async with _client(client) as c:
        resp = await c.post(APP_REGISTRATION_URL, data=form)
    payload = _json(resp, allow_error=True)

    if payload.get("client_id") and payload.get("client_secret"):
        reg.client_id = payload["client_id"]
        reg.client_secret = payload["client_secret"]
        reg.user_info = payload.get("user_info") or {}
        return {"status": "success"}

    error = str(payload.get("error", ""))
    if error in ("authorization_pending", ""):
        return {"status": "pending"}
    if error == "slow_down":
        reg.interval = min(reg.interval + 5, 60)
        return {"status": "slow_down", "interval": reg.interval}
    if error in ("expired_token", "invalid_grant"):
        return {"status": "expired"}
    if error in ("access_denied",):
        return {"status": "denied"}
    return {
        "status": "error",
        "error": error or "unknown",
        "error_description": payload.get("error_description", ""),
    }


# ---------------------------------------------------------------------------
# 阶段 B：用户授权（设备码）→ refresh_token
# ---------------------------------------------------------------------------


async def login_begin(
    client_id: str,
    client_secret: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> LoginFlow:
    """用应用凭证发起用户授权设备码流程。

    这个端点要求做客户端认证：只传 client_id 会被拒（invalid_client 20140）。
    官方 SDK 用 HTTP Basic（client_id:client_secret），这里保持一致。
    """
    scopes = effective_scopes()
    form = {"client_id": client_id, "scope": " ".join(scopes)}
    async with _client(client) as c:
        resp = await c.post(
            DEVICE_AUTHORIZATION_URL, data=form, auth=(client_id, client_secret)
        )
    payload = _json(resp)
    parsed = _parse_device_flow(payload, source="device_authorization")
    return LoginFlow(**parsed)


async def login_poll(
    flow: LoginFlow,
    client_id: str,
    client_secret: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """轮询一次 token；成功时返回 token 包。"""
    form = {
        "grant_type": DEVICE_CODE_GRANT,
        "device_code": flow.device_code,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    async with _client(client) as c:
        resp = await c.post(TOKEN_URL, data=form)
    payload = _json(resp, allow_error=True)

    # 必须先判成功：成功响应里没有 error 字段，靠 error 分类会把它误判成失败。
    tokens = _extract_tokens(payload)
    if tokens is not None:
        return {"status": "success", "tokens": tokens}

    status = _classify_poll_error(str(payload.get("error") or ""))
    if status == "pending":
        return {"status": "pending"}
    if status == "slow_down":
        flow.interval = min(flow.interval + 5, 60)
        return {"status": "slow_down", "interval": flow.interval}
    if status == "expired":
        return {"status": "expired"}
    if status == "denied":
        return {"status": "denied"}
    if status == "unknown":
        # 既没有 token 也没有 error：极少数中间态，继续轮询即可
        return {"status": "pending"}
    return {
        "status": "error",
        "error": str(payload.get("error") or "unknown_error"),
        "error_description": str(payload.get("error_description") or ""),
    }


async def refresh_user_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """用 refresh_token 换新的 access_token（refresh_token 一次性）。"""
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    async with _client(client) as c:
        resp = await c.post(TOKEN_URL, data=form)
    payload = _json(resp, allow_error=True)

    tokens = _extract_tokens(payload)
    if tokens is None:
        raise LarkError(
            str(payload.get("error") or "refresh_failed"),
            str(payload.get("error_description") or "刷新失败，未返回 access_token"),
        )
    return tokens


# ---------------------------------------------------------------------------
# 阶段 C：用 user_access_token 调飞书接口
# ---------------------------------------------------------------------------


async def get_user_info(
    user_access_token: str, *, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """演示调用：获取用户信息。基础字段无需额外权限。"""
    headers = {
        "Authorization": f"Bearer {user_access_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    async with _client(client) as c:
        resp = await c.get(USER_INFO_URL, headers=headers)
    payload = _json(resp, allow_error=True)
    code = payload.get("code")
    if code not in (0, None):
        raise LarkError(
            str(code), str(payload.get("msg") or "调用 user_info 失败")
        )
    return payload


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _json(resp: httpx.Response, *, allow_error: bool = False) -> dict[str, Any]:
    """解析响应；必要时抛出带上下文的错误。"""
    try:
        payload = resp.json()
    except ValueError as exc:  # 非 JSON 响应
        snippet = resp.text[:300]
        raise LarkError(
            f"http_{resp.status_code}", f"飞书返回了非 JSON 响应：{snippet!r}"
        ) from exc

    if not isinstance(payload, dict):
        raise LarkError("invalid_response", f"响应结构异常：{payload!r}")

    if allow_error:
        return payload

    if resp.status_code >= 400:
        raise LarkError(
            str(payload.get("error", f"http_{resp.status_code}")),
            str(payload.get("error_description") or payload.get("msg") or resp.text[:300]),
        )
    return payload


class _client:
    """复用外部传入的 AsyncClient，或者临时创建一个。"""

    def __init__(self, client: httpx.AsyncClient | None) -> None:
        self._external = client
        self._owned: httpx.AsyncClient | None = None

    async def __aenter__(self) -> httpx.AsyncClient:
        if self._external is not None:
            return self._external
        self._owned = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        return self._owned

    async def __aexit__(self, *exc: object) -> None:
        if self._owned is not None:
            await self._owned.aclose()
