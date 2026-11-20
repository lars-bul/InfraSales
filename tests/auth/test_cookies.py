from fastapi import Response
from pydantic import HttpUrl
from starlette.requests import Request

from infrasales.auth.cookies import clear_session_cookie, session_token, set_session_cookie


def _request(cookie: str) -> Request:
    return Request({"type": "http", "headers": [(b"cookie", cookie.encode())]})


def test_https_cookies_are_host_bound_and_secure() -> None:
    response = Response()

    set_session_cookie(response, "token", HttpUrl("https://infrasales.example"))

    header = response.headers["set-cookie"]
    assert header.startswith("__Host-infrasales_session=token;")
    assert all(part in header for part in ("HttpOnly", "Path=/", "SameSite=lax", "Secure"))
    assert "Max-Age" not in header  # dropped when the browser closes


def test_plain_http_cookies_work_on_localhost() -> None:
    response = Response()

    set_session_cookie(response, "token", HttpUrl("http://localhost:8000"))

    assert response.headers["set-cookie"].startswith("infrasales_session=token;")
    assert "Secure" not in response.headers["set-cookie"]


def test_the_token_is_read_from_the_matching_cookie() -> None:
    https = HttpUrl("https://infrasales.example")

    assert session_token(_request("__Host-infrasales_session=abc"), https) == "abc"
    assert session_token(_request("infrasales_session=abc"), https) is None


def test_clearing_expires_the_cookie() -> None:
    response = Response()

    clear_session_cookie(response, HttpUrl("http://localhost:8000"))

    assert 'infrasales_session=""' in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]
