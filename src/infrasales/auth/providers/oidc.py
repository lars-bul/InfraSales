"""Sign-in with OpenID Connect: the Authorization Code flow with PKCE, then a server session.

Only this module imports Authlib and the signed sign-in state cookie (itsdangerous): with
other providers, neither is loaded.
"""

from collections.abc import Iterable
from typing import Any, Literal, cast
from urllib.parse import urlencode, urlsplit

import httpx2
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import RedirectResponse
from joserfc.errors import JoseError
from pydantic import HttpUrl
from starlette.middleware.sessions import SessionMiddleware

from infrasales.audit import service as audit
from infrasales.audit.models import Outcome
from infrasales.auth import sessions
from infrasales.auth.cookies import session_token, set_session_cookie
from infrasales.auth.models import Role, User
from infrasales.auth.settings import OIDCAuthSettings
from infrasales.core.db import Session
from infrasales.core.models import SUBJECT_LENGTH, utcnow

# Authlib, the IdP's HTTP responses, ID token validation (joserfc), a response without ID token
_FAILURES = (OAuthError, httpx2.HTTPError, JoseError, KeyError, ValueError)


class OIDCProvider:
    name: Literal["oidc"] = "oidc"

    def __init__(
        self,
        settings: OIDCAuthSettings,
        public_url: HttpUrl,
        transport: httpx2.AsyncBaseTransport | None = None,  # tests: an in-process IdP
    ) -> None:
        self._settings = settings
        self.public_url = public_url
        self._app_url = str(public_url).rstrip("/")
        self._issuer = settings.issuer  # exactly: ID tokens' `iss` must equal it
        issuer = urlsplit(self._issuer)
        self.form_targets = f"{issuer.scheme}://{issuer.netloc}"  # sign-out redirects there
        # OpenID Connect Discovery: the issuer without a trailing "/", then the well-known path
        discovery = f"{self._issuer.rstrip('/')}/.well-known/openid-configuration"
        self._client = OAuth().register(
            "oidc",
            server_metadata_url=discovery,
            client_id=settings.client_id,
            client_secret=settings.client_secret.get_secret_value(),
            client_kwargs={
                "scope": settings.scope,
                "code_challenge_method": "S256",  # PKCE
                "timeout": 10,
                "transport": transport,
            },
        )

    def install(self, app: FastAPI) -> None:
        secure = self.public_url.scheme == "https"
        app.add_middleware(  # Authlib's state, nonce and PKCE verifier: signed, 10 minutes
            SessionMiddleware,
            secret_key=self._settings.state_secret.get_secret_value(),
            session_cookie="__Host-infrasales_login" if secure else "infrasales_login",
            max_age=600,
            same_site="lax",
            https_only=secure,
        )
        router = APIRouter(prefix="/api/auth", include_in_schema=False)  # browser redirects
        router.add_api_route("/login", self.login, methods=["GET"])
        router.add_api_route("/callback", self.callback, methods=["GET"])
        app.include_router(router)

    async def login(self, request: Request) -> RedirectResponse:
        """Send the browser to the identity provider."""
        try:
            return await self._client.authorize_redirect(
                request, f"{self._app_url}/api/auth/callback"
            )
        except httpx2.HTTPError:
            return RedirectResponse("/?signin=unavailable", status_code=303)

    async def callback(self, request: Request, session: Session) -> RedirectResponse:
        """The identity provider sends the browser back: validate, then start a session."""
        try:
            # Authlib checks state, PKCE, signature, nonce and expiry; issuer and audience too:
            expected = {
                "iss": {"essential": True, "values": [self._issuer]},
                "aud": {"essential": True, "values": [self._settings.client_id]},
            }
            token = await self._client.authorize_access_token(request, claims_options=expected)
            claims: dict[str, Any] = token["userinfo"]
            subject = _subject(claims["sub"])
        except _FAILURES as error:
            reason = {"reason": type(error).__name__}
            failure = Outcome.FAILURE
            audit.record(session, actor=None, action="auth.login", outcome=failure, details=reason)
            return RedirectResponse("/?signin=failed", status_code=303)
        finally:
            request.session.clear()  # the sign-in state is single-use
        role = self._role(claims.get(self._settings.groups_claim))
        outcome = Outcome.SUCCESS if role else Outcome.FAILURE
        audit.record(session, actor=subject, action="auth.login", outcome=outcome, request=request)
        if role is None:  # deny by default: only the configured groups may sign in
            return RedirectResponse("/?signin=denied", status_code=303)
        if previous := session_token(request, self.public_url):
            await sessions.end(session, previous)
        name = str(claims.get("name") or claims.get("preferred_username") or claims["sub"])
        user = User(subject=subject, name=name[:255], role=role)
        token_value = await sessions.start(session, user, utcnow())
        response = RedirectResponse("/", status_code=303)
        set_session_cookie(response, token_value, self.public_url)
        return response

    def _role(self, groups: object) -> Role | None:
        """The highest role the user's groups grant; None if they grant none."""
        member = _names(groups)
        if member & set(self._settings.admin_groups):
            return Role.ADMIN
        if member & set(self._settings.viewer_groups):
            return Role.VIEWER
        return None

    async def logout_url(self, _: Request, /) -> str:
        """End the identity provider's session too (RP-initiated logout), if it supports it."""
        try:
            endpoint = (await self._client.load_server_metadata()).get("end_session_endpoint")
        except httpx2.HTTPError:
            return "/"  # the local session ends either way
        if not endpoint:
            return "/"
        query = {"client_id": self._settings.client_id}
        query["post_logout_redirect_uri"] = f"{self._app_url}/"
        return f"{endpoint}?{urlencode(query)}"


def _subject(sub: object) -> str:
    """The person's ID: the provider's `sub`, a string of at most 255 characters, prefixed."""
    subject = f"oidc:{sub}"
    if not isinstance(sub, str) or not sub or len(subject) > SUBJECT_LENGTH:
        msg = "the sub claim is not a string of 1 to 255 characters"
        raise ValueError(msg)
    return subject


def _names(groups: object) -> set[str]:
    """Group names from the claim: a list, one string, or an object keyed by group (ZITADEL)."""
    if isinstance(groups, str):
        return {groups}
    if isinstance(groups, Iterable):
        return {str(group) for group in cast("Iterable[object]", groups)}
    return set()
