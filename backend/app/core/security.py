"""Authentication foundation.

V1 ships a simple JWT + dev-login flow so local development is never blocked.
The interfaces are production-shaped: swap `authenticate_user` for a real IdP
later without touching routers.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AdFlowError, NotFound

ALGORITHM = "HS256"


class Unauthorized(AdFlowError):
    code = "unauthorized"
    http_status = 401


def hash_password(password: str) -> str:
    salt = settings.SECRET_KEY.encode()
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000).hex()


def verify_password(password: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(password), hashed)


def create_access_token(subject: str, extra: Optional[dict] = None) -> str:
    payload = {
        "sub": subject,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.now(timezone.utc),
        **(extra or {}),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:  # pragma: no cover - defensive
        raise Unauthorized("Your session expired. Please sign in again.", "انتهت الجلسة. سجّل دخول مرة ثانية.") from exc


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Resolve the current user.

    In development (ALLOW_DEV_LOGIN) an absent token falls back to the demo
    user so the whole product stays testable in the browser.
    """
    from app.models import User

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        payload = decode_token(token)
        user = db.get(User, payload.get("sub"))
        if user:
            return user

    if settings.ALLOW_DEV_LOGIN:
        user = db.query(User).filter(User.email == settings.DEV_USER_EMAIL).first()
        if user:
            return user
        raise NotFound("Demo user is not seeded yet. Run `python -m app.seed`.", "المستخدم التجريبي غير موجود.")

    raise Unauthorized("Authentication required.", "تحتاج تسجيل دخول.")
