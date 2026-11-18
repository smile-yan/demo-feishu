"""仅用于本地联调：用假的飞书响应跑通前端三步，不消耗真实凭证。

用法：
    uv run uvicorn scripts.mock_server:app --port 8001

它复用真实的 app/main.py 路由，只把 lark 模块里的网络调用替换成固定响应，
这样可以在不扫码的情况下检查前端每一步的渲染是否正确。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.lark as L  # noqa: E402

FAKE_APP_ID = "cli_demo00000000001"
FAKE_APP_SECRET = "DEMO_SECRET_VALUE_1234567890abcd"
FAKE_USER = {
    "name": "张三",
    "en_name": "Zhang San",
    "avatar_url": "https://example.com/avatar.png",
    "open_id": "ou_demo1234567890",
    "union_id": "on_demo4567890",
    "email": "demo@example.com",
    "tenant_key": "tenant_demo",
}


async def fake_app_begin(**kw):
    return L.Registration(
        device_code="dev_app",
        verification_url="https://open.feishu.cn/page/launcher?user_code=DEMO-1234&from=sdk",
        user_code="DEMO-1234",
        interval=2,
        expires_in=3600,
    )


async def fake_app_poll(reg, **kw):
    reg.client_id = FAKE_APP_ID
    reg.client_secret = FAKE_APP_SECRET
    reg.user_info = {"open_id": "ou_owner", "tenant_brand": "feishu"}
    return {"status": "success"}


async def fake_login_begin(client_id, client_secret, **kw):
    return L.LoginFlow(
        device_code="dev_login",
        verification_url="https://accounts.feishu.cn/qr?user_code=DEMO-5678",
        user_code="DEMO-5678",
        interval=2,
        expires_in=240,
    )


async def fake_login_poll(flow, client_id, client_secret, **kw):
    return {
        "status": "success",
        "tokens": {
            "access_token": "u-demo-access-token-abcdefghijklmnop",
            "token_type": "Bearer",
            "refresh_token": "ur-demo-refresh-token-1234567890abcdefghij",
            "expires_in": 7200,
            "refresh_token_expires_in": 604800,
            "scope": "offline_access",
        },
    }


async def fake_user_info(token, **kw):
    return {"code": 0, "msg": "success", "data": FAKE_USER}


async def fake_refresh(refresh_token, client_id, client_secret, **kw):
    return {
        "access_token": "u-demo-access-token-NEW000000000000",
        "token_type": "Bearer",
        "refresh_token": "ur-demo-refresh-NEW1111111111",
        "expires_in": 7200,
        "refresh_token_expires_in": 604800,
        "scope": "offline_access",
    }


L.app_registration_begin = fake_app_begin
L.app_registration_poll = fake_app_poll
L.login_begin = fake_login_begin
L.login_poll = fake_login_poll
L.get_user_info = fake_user_info
L.refresh_user_token = fake_refresh

from app.main import app  # noqa: E402,F401  （导入即生效，路由仍是真实的）
