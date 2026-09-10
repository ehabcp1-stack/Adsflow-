"""Authentication endpoints. Local development has a one-click demo login."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AdFlowError
from app.core.security import create_access_token, get_current_user, verify_password
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserSettingsUpdate

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "locale": user.locale,
        "director_mode": user.director_mode,
        "organization_id": user.organization_id,
        "organization_name": user.organization.name if user.organization else "",
    }


class InvalidCredentials(AdFlowError):
    code = "invalid_credentials"
    http_status = 401


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise InvalidCredentials("Wrong email or password.", "الإيميل أو كلمة المرور غير صحيحة.")
    return TokenResponse(access_token=create_access_token(user.id), user=_user_payload(user))


@router.post("/dev-login", response_model=TokenResponse)
def dev_login(db: Session = Depends(get_db)) -> TokenResponse:
    """One-click demo sign-in. Disabled by ALLOW_DEV_LOGIN=false."""
    if not settings.ALLOW_DEV_LOGIN:
        raise InvalidCredentials("Dev login is disabled.", "الدخول التجريبي معطّل.")
    user = db.query(User).filter(User.email == settings.DEV_USER_EMAIL).first()
    if not user:
        raise InvalidCredentials(
            "Demo user is not seeded. Run `python -m app.seed`.", "المستخدم التجريبي غير موجود."
        )
    return TokenResponse(access_token=create_access_token(user.id), user=_user_payload(user))


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return _user_payload(user)


@router.patch("/me")
def update_me(
    payload: UserSettingsUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    return _user_payload(user)
