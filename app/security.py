import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import AdminUser, settings

_basic = HTTPBasic(realm="Training Admin")


def require_admin(creds: HTTPBasicCredentials = Depends(_basic)) -> AdminUser:
    user = settings.admins.get(creds.username)
    if not user or not secrets.compare_digest(creds.password.encode(), user.password.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials",
                            headers={"WWW-Authenticate": 'Basic realm="Training Admin"'})
    return user


def new_token() -> str:
    return secrets.token_urlsafe(24)


def verified_assignment_id(request: Request) -> int | None:
    return request.session.get("assignment_id")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]
