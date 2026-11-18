"""FastAPI 后端：飞书扫码建应用 → 用户授权 → 调用接口的演示。

前端只轮询状态，所有敏感值（App Secret、token）都留在服务端。
"""

from __future__ import annotations

import time
from typing import Any

from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from . import lark  # noqa: E402  （必须在 load_dotenv 之后导入）
from .store import COOKIE_NAME, Session, store  # noqa: E402

app = FastAPI(title="feishu-demo", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_session(sid: str | None, response: Response) -> Session:
    """取当前会话；首次访问时下发 cookie。"""
    session = store.get_or_create(sid)
    if sid != session.sid:
        response.set_cookie(
            COOKIE_NAME,
            session.sid,
            httponly=True,
            samesite="lax",
            max_age=3600,
        )
    return session


def require_app(session: Session) -> None:
    if not session.has_app:
        raise HTTPException(status_code=409, detail="请先完成第 1 步：获取应用凭证")


def require_login(session: Session) -> None:
    require_app(session)
    if not session.logged_in:
        raise HTTPException(status_code=409, detail="请先完成第 2 步：飞书登录授权")
    if session.expires_at and time.time() > session.expires_at:
        raise HTTPException(
            status_code=409, detail="access_token 已过期，请点「刷新 access_token」"
        )


def session_state(session: Session) -> dict[str, Any]:
    """返回给前端的整体状态。"""
    now = time.time()
    return {
        "step": 3 if session.logged_in else (2 if session.has_app else 1),
        "app": (
            {
                "app_id": session.app_id,
                "app_secret": session.app_secret,
                "owner": session.registration.user_info if session.registration else {},
            }
            if session.has_app
            else None
        ),
        "app_source": "env" if session.app_preset else "scan",
        "login": (
            {
                "user": session.user,
                "scopes": session.scopes,
                "refresh_token": session.refresh_token,
                "refresh_token_expires_in": max(
                    0, int(session.refresh_expires_at - now)
                ),
                "access_token_expires_in": max(0, int(session.expires_at - now)),
                "refresh_count": session.refresh_count,
            }
            if session.logged_in
            else None
        ),
        "requested_scopes": lark.effective_scopes(),
    }


# ---------------------------------------------------------------------------
# 阶段 A：获取应用凭证
# ---------------------------------------------------------------------------


@app.post("/api/app/begin")
async def app_begin(
    response: Response, feishu_demo_sid: str | None = Cookie(default=None)
) -> dict[str, Any]:
    session = current_session(feishu_demo_sid, response)
    if session.app_preset:
        raise HTTPException(
            status_code=409, detail="应用凭证已由 backend/.env 预置，第 1 步已跳过"
        )
    try:
        session.registration = await lark.app_registration_begin()
    except lark.LarkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # 首次立刻可查，之后按 interval 节流
    session.next_app_poll_at = 0.0
    reg = session.registration
    return {
        "verification_url": reg.verification_url,
        "user_code": reg.user_code,
        "expires_in": reg.expires_in,
    }


@app.get("/api/app/poll")
async def app_poll(
    response: Response, feishu_demo_sid: str | None = Cookie(default=None)
) -> dict[str, Any]:
    session = current_session(feishu_demo_sid, response)
    if session.app_preset:
        raise HTTPException(
            status_code=409, detail="应用凭证已由 backend/.env 预置，第 1 步已跳过"
        )
    reg = session.registration
    if reg is None:
        raise HTTPException(status_code=409, detail="请先调用 /api/app/begin")

    now = time.time()
    if now < session.next_app_poll_at:
        return {
            "status": "pending",
            "retry_after": round(session.next_app_poll_at - now, 1),
        }

    try:
        result = await lark.app_registration_poll(reg)
    except lark.LarkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    session.next_app_poll_at = now + max(reg.interval, 2)
    if result["status"] == "success":
        return {
            "status": "success",
            "app_id": reg.client_id,
            "app_secret": reg.client_secret,
            "owner": reg.user_info,
        }
    if result["status"] == "error":
        detail = (
            f"{result.get('error') or '未知错误'}: "
            f"{result.get('error_description') or '飞书未返回详细说明'}"
        )
        raise HTTPException(status_code=502, detail=detail)
    return result


@app.post("/api/app/reveal")
async def app_reveal(
    response: Response, feishu_demo_sid: str | None = Cookie(default=None)
) -> dict[str, Any]:
    """单独取明文凭证，便于复制到别处使用。"""
    session = current_session(feishu_demo_sid, response)
    require_app(session)
    return {"app_id": session.app_id, "app_secret": session.app_secret}


# ---------------------------------------------------------------------------
# 阶段 B：用户登录授权
# ---------------------------------------------------------------------------


@app.post("/api/login/begin")
async def login_begin(
    response: Response, feishu_demo_sid: str | None = Cookie(default=None)
) -> dict[str, Any]:
    session = current_session(feishu_demo_sid, response)
    require_app(session)
    try:
        session.login = await lark.login_begin(session.app_id, session.app_secret)
    except lark.LarkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session.next_login_poll_at = 0.0
    flow = session.login
    return {
        "verification_url": flow.verification_url,
        "user_code": flow.user_code,
        "expires_in": flow.expires_in,
        "scopes": lark.effective_scopes(),
    }


@app.get("/api/login/poll")
async def login_poll(
    response: Response, feishu_demo_sid: str | None = Cookie(default=None)
) -> dict[str, Any]:
    session = current_session(feishu_demo_sid, response)
    require_app(session)
    flow = session.login
    if flow is None:
        raise HTTPException(status_code=409, detail="请先调用 /api/login/begin")

    now = time.time()
    if now < session.next_login_poll_at:
        return {
            "status": "pending",
            "retry_after": round(session.next_login_poll_at - now, 1),
        }

    try:
        result = await lark.login_poll(flow, session.app_id, session.app_secret)
    except lark.LarkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    session.next_login_poll_at = now + max(flow.interval, 2)
    if result["status"] != "success":
        if result["status"] == "error":
            detail = (
                f"{result.get('error') or '未知错误'}: "
                f"{result.get('error_description') or '飞书未返回详细说明'}"
            )
            raise HTTPException(status_code=502, detail=detail)
        return result

    tokens = result["tokens"]
    session.user_access_token = tokens.get("access_token", "")
    session.refresh_token = tokens.get("refresh_token", "")
    session.scopes = (tokens.get("scope") or "").split()
    expires_in = int(tokens.get("expires_in") or 7200)
    refresh_expires_in = int(tokens.get("refresh_token_expires_in") or 604800)
    session.expires_at = now + expires_in
    session.refresh_expires_at = now + refresh_expires_in

    # 顺手调一次 user_info，这样第 2 步就能看到登录的是谁
    try:
        info = await lark.get_user_info(session.user_access_token)
        session.user = info.get("data") or {}
    except lark.LarkError as exc:
        session.user = {"error": str(exc)}

    return {
        "status": "success",
        "user": session.user,
        "scopes": session.scopes,
        "refresh_token": session.refresh_token,
        "expires_in": expires_in,
        "refresh_token_expires_in": refresh_expires_in,
    }


# ---------------------------------------------------------------------------
# 阶段 C：调用飞书接口
# ---------------------------------------------------------------------------


@app.get("/api/me")
async def me(
    response: Response, feishu_demo_sid: str | None = Cookie(default=None)
) -> dict[str, Any]:
    """用 user_access_token 真实调用飞书「获取用户信息」接口。"""
    session = current_session(feishu_demo_sid, response)
    require_login(session)
    try:
        return await lark.get_user_info(session.user_access_token)
    except lark.LarkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/refresh")
async def refresh(
    response: Response, feishu_demo_sid: str | None = Cookie(default=None)
) -> dict[str, Any]:
    """用 refresh_token 换新的 access_token，证明 refresh_token 可用。"""
    session = current_session(feishu_demo_sid, response)
    require_app(session)
    if not session.refresh_token:
        raise HTTPException(status_code=409, detail="没有 refresh_token，请先完成第 2 步")
    try:
        tokens = await lark.refresh_user_token(
            session.refresh_token, session.app_id, session.app_secret
        )
    except lark.LarkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    now = time.time()
    session.user_access_token = tokens.get("access_token", session.user_access_token)
    # refresh_token 是一次性的，每次刷新都会换新的
    session.refresh_token = tokens.get("refresh_token", "")
    session.scopes = (tokens.get("scope") or "").split() or session.scopes
    session.expires_at = now + int(tokens.get("expires_in") or 7200)
    session.refresh_expires_at = now + int(
        tokens.get("refresh_token_expires_in") or 604800
    )
    session.refresh_count += 1

    return {
        "status": "success",
        "refresh_count": session.refresh_count,
        "access_token_expires_in": int(tokens.get("expires_in") or 7200),
        "refresh_token": session.refresh_token,
        "refresh_token_expires_in": int(tokens.get("refresh_token_expires_in") or 0),
        "access_token_prefix": session.user_access_token[:12],
    }


# ---------------------------------------------------------------------------
# 状态与重置
# ---------------------------------------------------------------------------


@app.get("/api/state")
async def state(
    response: Response, feishu_demo_sid: str | None = Cookie(default=None)
) -> dict[str, Any]:
    session = current_session(feishu_demo_sid, response)
    return session_state(session)


@app.post("/api/reset")
async def reset(
    response: Response, feishu_demo_sid: str | None = Cookie(default=None)
) -> dict[str, Any]:
    store.reset(feishu_demo_sid)
    response.delete_cookie(COOKIE_NAME)
    return {"status": "reset"}
