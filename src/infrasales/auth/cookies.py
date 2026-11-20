"""The session cookie: `__Host-` prefixed and Secure on https, HttpOnly and SameSite=Lax always.

No Max-Age: the browser drops it when closed; the server enforces the session's lifetime.
"""

from fastapi import Request, Response
from pydantic import HttpUrl


def _cookie(public_url: HttpUrl) -> tuple[str, bool]:
    secure = public_url.scheme == "https"
    return ("__Host-infrasales_session" if secure else "infrasales_session"), secure


def session_token(request: Request, public_url: HttpUrl) -> str | None:
    name, _ = _cookie(public_url)
    return request.cookies.get(name)


def set_session_cookie(response: Response, token: str, public_url: HttpUrl) -> None:
    name, secure = _cookie(public_url)
    response.set_cookie(name, token, path="/", secure=secure, httponly=True, samesite="lax")


def clear_session_cookie(response: Response, public_url: HttpUrl) -> None:
    name, secure = _cookie(public_url)
    response.delete_cookie(name, path="/", secure=secure, httponly=True, samesite="lax")
