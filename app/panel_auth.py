"""Independent staff login: salted passwords, revocable sessions and CSRF."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete

from app.config import get_settings
from app.staff import scope as staff_scope
from app.store.models import StaffAccount, StaffSession
from app.store.postgres import get_session
from app.store.redis_store import get_redis

router = APIRouter(prefix="/api/agenda")
COOKIE = "__Host-waia_session"
SESSION_DAYS = 30


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


def password_hash(password: str) -> str:
    if not 12 <= len(password) <= 256:
        raise ValueError("Usa una contraseña de 12 a 256 caracteres")
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def password_matches(password, stored):
    try:
        algo, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
        ).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False


def origin_check(request):
    configured = urlsplit(get_settings().public_base_url)
    expected = f"{configured.scheme}://{configured.netloc}"
    if request.headers.get("origin") != expected:
        raise HTTPException(403, "Origen no autorizado")


@dataclass(frozen=True)
class Principal:
    username: str
    phone: str
    scope: str
    csrf: str
    token_hash: str


def authenticated(request: Request) -> Principal:
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 128:
        raise HTTPException(401, "Inicia sesión")
    digest = hashlib.sha256(token.encode()).hexdigest()
    with get_session() as session:
        login = session.get(StaffSession, digest)
        if login is None or login.expires_at <= utc_now():
            raise HTTPException(401, "Tu sesión venció")
        account = session.get(StaffAccount, login.username)
        scope = staff_scope(account.wa_id) if account and account.active else None
        if not scope:
            raise HTTPException(401, "Acceso revocado")
        return Principal(account.username, account.wa_id, scope, login.csrf, digest)


def authorized_write(
    request: Request, user: Annotated[Principal, Depends(authenticated)]
) -> Principal:
    origin_check(request)
    if not hmac.compare_digest(
        request.headers.get("x-csrf-token", "").encode(), user.csrf.encode()
    ):
        raise HTTPException(403, "Actualiza la página e intenta de nuevo")
    return user


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=256)


def login_limit(request, username):
    try:
        redis = get_redis()
        host = request.client.host if request.client else "unknown"
        for subject, maximum in ((f"user:{username}", 8), (f"ip:{host}", 100)):
            key = "panel-login:" + hashlib.sha256(subject.encode()).hexdigest()
            count = redis.incr(key)
            if count == 1:
                redis.expire(key, 900)
            if count > maximum:
                raise HTTPException(429, "Demasiados intentos. Intenta en 15 minutos")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Acceso temporalmente no disponible") from exc


@router.post("/login")
def login(body: Login, request: Request, response: Response):
    origin_check(request)
    username = body.username.lower()
    login_limit(request, username)
    with get_session() as session:
        account = session.get(StaffAccount, username)
        # Constant work for unknown usernames to avoid a cheap account oracle.
        stored = account.password_hash if account else "scrypt$" + "00" * 16 + "$" + "00" * 64
        matches = password_matches(body.password, stored)
        if not matches or not account or not account.active or not staff_scope(account.wa_id):
            raise HTTPException(401, "Usuario o contraseña incorrectos")
        session.execute(delete(StaffSession).where(StaffSession.expires_at <= utc_now()))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        session.add(
            StaffSession(
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                username=username,
                csrf=csrf,
                expires_at=utc_now() + timedelta(days=SESSION_DAYS),
            )
        )
        session.commit()
    response.set_cookie(
        COOKIE,
        token,
        secure=True,
        httponly=True,
        samesite="strict",
        max_age=SESSION_DAYS * 86400,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.get("/session")
def session_info(user: Annotated[Principal, Depends(authenticated)]):
    return {"username": user.username, "scope": user.scope, "csrf": user.csrf}


@router.post("/logout")
def logout(response: Response, user: Annotated[Principal, Depends(authorized_write)]):
    with get_session() as session:
        session.execute(delete(StaffSession).where(StaffSession.token_hash == user.token_hash))
        session.commit()
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict", path="/")
    return {"ok": True}
