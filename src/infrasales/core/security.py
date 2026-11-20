"""Browser hardening for every response: CSP and security headers, CSRF and a body limit."""

from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_MAX_BODY_BYTES = 1 << 20  # 1 MiB; the API takes small JSON and form bodies only
_CSP = "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class BodyTooLargeError(HTTPException):
    """Raised mid-stream when a body without Content-Length grows past the limit.

    An HTTP exception, so the app answers 413 itself, also while parsing a JSON body.
    """

    def __init__(self) -> None:
        super().__init__(413, "Request body too large")


class SecurityMiddleware:
    """CSRF protection, security and caching headers, and a request body limit.

    Same-origin is decided by Fetch Metadata (`Sec-Fetch-Site`), falling back to comparing
    `Origin` with the app's public origin: scheme, host and port. Requests carrying neither are
    not from a browser and cannot be CSRF.
    """

    def __init__(self, app: ASGIApp, *, origin: str, form_targets: str = "") -> None:
        """`origin`: the app's public URL (`WEB__PUBLIC_URL`), where browsers reach it.

        `form_targets`: origins a form may submit or redirect to besides 'self' (the IdP).
        """
        self.app = app
        if (public := _origin(origin)) is None:
            msg = f"{origin!r} is no origin"
            raise ValueError(msg)
        self._origin = public
        csp = f"{_CSP}; form-action 'self' {form_targets}".strip()
        self._headers = {"Content-Security-Policy": csp} | _HEADERS

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        send = self._with_headers(send, scope["path"])
        headers = Headers(scope=scope)
        length = headers.get("content-length", "")
        if scope["method"] not in _SAFE_METHODS and not self._is_same_origin(headers):
            await PlainTextResponse("Cross-origin request rejected", 403)(scope, receive, send)
        elif length.isdigit() and int(length) > _MAX_BODY_BYTES:
            await _too_large()(scope, receive, send)
        else:
            await self._with_body_limit(scope, receive, send)

    def _is_same_origin(self, headers: Headers) -> bool:
        if site := headers.get("sec-fetch-site"):
            return site in {"same-origin", "none"}
        origin = headers.get("origin")
        return origin is None or _origin(origin) == self._origin

    def _with_headers(self, send: Send, path: str) -> Send:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in self._headers.items():
                    response_headers.setdefault(name, value)
                response_headers.setdefault("Cache-Control", _cache_control(path))
            await send(message)

        return send_with_headers

    async def _with_body_limit(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Count bodies without Content-Length as they stream; answer 413 past the limit."""
        received, responded = 0, False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > _MAX_BODY_BYTES:
                raise BodyTooLargeError
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal responded
            responded = responded or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except BodyTooLargeError:
            if responded:
                raise
            await _too_large()(scope, receive, tracked_send)


def _too_large() -> PlainTextResponse:
    return PlainTextResponse("Request body too large", status_code=413)


def _origin(url: str) -> tuple[str, str, int] | None:
    """Scheme, host and port, the port made explicit; None for what is no origin (`null`)."""
    try:
        parts = urlsplit(url)
        port = parts.port or _DEFAULT_PORTS.get(parts.scheme)
    except ValueError:  # malformed, e.g. `http://[`, or an invalid port
        return None
    if not parts.hostname or port is None:
        return None
    return parts.scheme, parts.hostname, port


def _cache_control(path: str) -> str:
    if path.startswith("/assets/"):  # content-hashed build output
        return "public, max-age=31536000, immutable"
    if path.startswith(("/api/", "/healthz", "/readyz")):
        return "no-store"  # personal or live data
    return "no-cache"  # the UI shell: always revalidate
