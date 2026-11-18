"""服务端会话存储。

凭证只保存在服务端内存里，前端按需读取。演示用途，进程重启即清空。
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from . import lark

COOKIE_NAME = "feishu_demo_sid"
SESSION_TTL = 3600  # 1 小时


@dataclass
class Session:
    """一个浏览器会话对应的全部状态。"""

    sid: str
    created_at: float = field(default_factory=time.time)

    # 阶段 A
    registration: lark.Registration | None = None
    next_app_poll_at: float = 0.0
    app_preset: bool = False  # 凭证来自 .env，第 1 步扫码建应用整体跳过

    # 阶段 B
    login: lark.LoginFlow | None = None
    next_login_poll_at: float = 0.0

    # 结果
    scopes: list[str] = field(default_factory=list)
    user: dict[str, Any] = field(default_factory=dict)
    user_access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    refresh_expires_at: float = 0.0
    refresh_count: int = 0

    @property
    def app_id(self) -> str:
        return self.registration.client_id if self.registration else ""

    @property
    def app_secret(self) -> str:
        return self.registration.client_secret if self.registration else ""

    @property
    def has_app(self) -> bool:
        return bool(self.app_id and self.app_secret)

    @property
    def logged_in(self) -> bool:
        return bool(self.user_access_token and self.user)


class SessionStore:
    """内存会话表（单进程演示够用）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get_or_create(self, sid: str | None) -> Session:
        self._evict_expired()
        if sid and sid in self._sessions:
            return self._sessions[sid]
        new_sid = secrets.token_urlsafe(24)
        session = Session(sid=new_sid)
        creds = lark.preset_app_credentials()
        if creds:
            # 预置凭证：直接当作「已拿到应用」，前端从第 2 步开始
            session.registration = lark.Registration(
                device_code="",
                verification_url="",
                client_id=creds[0],
                client_secret=creds[1],
            )
            session.app_preset = True
        self._sessions[new_sid] = session
        return session

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        return self._sessions.get(sid)

    def reset(self, sid: str | None) -> None:
        if sid:
            self._sessions.pop(sid, None)

    def _evict_expired(self) -> None:
        cutoff = time.time() - SESSION_TTL
        for sid in [s for s, sess in self._sessions.items() if sess.created_at < cutoff]:
            self._sessions.pop(sid, None)


store = SessionStore()
