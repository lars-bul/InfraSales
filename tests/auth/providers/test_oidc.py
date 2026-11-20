import hashlib
import time
from base64 import urlsafe_b64encode
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey
from pydantic import HttpUrl, SecretStr

from infrasales.app import create_app
from infrasales.auth.providers.oidc import OIDCProvider
from infrasales.auth.settings import OIDCAuthSettings
from infrasales.settings import Settings, WebSettings
from tests.helpers import SAME_ORIGIN, audit_events

pytestmark = pytest.mark.anyio
ISSUER, CLIENT_ID, APP = "https://idp.test", "infrasales", "https://infrasales.test"
KEY = RSAKey.generate_key(2048, parameters={"kid": "idp"})


class FakeIdP:
    """An in-process OpenID provider: discovery, JWKS, and a token endpoint checking PKCE."""

    def __init__(self, issuer: str = ISSUER) -> None:
        self.issuer = issuer  # how it names itself, in its metadata and ID tokens
        self.claims: dict[str, Any] = {"sub": "ada", "name": "Ada", "groups": ["infrasales-admins"]}
        self.id_token_claims: dict[str, Any] = {}  # overrides, e.g. another audience
        self.available = True
        self.end_session = True
        self._nonce = self._challenge = ""
        self.transport = httpx2.MockTransport(self._handle)

    def authorize(self, location: str) -> dict[str, str]:
        """Play the browser at the authorization endpoint; return its query."""
        query = {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}
        self._nonce, self._challenge = query["nonce"], query["code_challenge"]
        return query

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        if not self.available:
            return httpx2.Response(503)
        match request.url.path:
            case "/.well-known/openid-configuration":
                names = ["authorization", "token"] + (["end_session"] if self.end_session else [])
                metadata = {f"{name}_endpoint": f"{ISSUER}/{name}" for name in names}
                return httpx2.Response(
                    200, json=metadata | {"issuer": self.issuer, "jwks_uri": f"{ISSUER}/jwks"}
                )
            case "/jwks":
                return httpx2.Response(200, json=dict(KeySet([KEY]).as_dict()))
            case _:
                return self._token(request)

    def _token(self, request: httpx2.Request) -> httpx2.Response:
        form = parse_qs(request.content.decode())
        digest = hashlib.sha256(form["code_verifier"][0].encode()).digest()
        if urlsafe_b64encode(digest).rstrip(b"=").decode() != self._challenge:
            return httpx2.Response(400, json={"error": "invalid_grant"})
        now = int(time.time())
        claims = {"iss": self.issuer, "aud": CLIENT_ID, "iat": now, "exp": now + 300}
        claims |= {"nonce": self._nonce} | self.claims | self.id_token_claims
        id_token = jwt.encode({"alg": "RS256", "kid": "idp"}, claims, KEY)
        body = {"access_token": "at", "token_type": "Bearer", "id_token": id_token}
        return httpx2.Response(200, json=body)


@pytest.fixture
def idp() -> FakeIdP:
    return FakeIdP()


def _oidc(**overrides: object) -> OIDCAuthSettings:
    return OIDCAuthSettings.model_validate(
        {
            "provider": "oidc",
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
            "client_secret": SecretStr("client-secret"),
            "state_secret": SecretStr("s" * 32),
            "admin_groups": ["infrasales-admins"],
            "viewer_groups": ["infrasales-users"],
        }
        | overrides
    )


@asynccontextmanager
async def _browser(
    settings: Settings, idp: FakeIdP, public_url: str = APP, **auth_settings: object
) -> AsyncGenerator[httpx2.AsyncClient]:
    auth, url = _oidc(**auth_settings), HttpUrl(public_url)
    app_settings = settings.model_copy(update={"auth": auth, "web": WebSettings(public_url=url)})
    app = create_app(app_settings, OIDCProvider(auth, url, idp.transport))
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url=public_url) as client,
    ):
        yield client


@pytest.fixture
async def browser(settings: Settings, idp: FakeIdP) -> AsyncIterator[httpx2.AsyncClient]:
    async with _browser(settings, idp) as client:
        yield client


async def _sign_in(
    browser: httpx2.AsyncClient, idp: FakeIdP, state: str | None = None
) -> httpx2.Response:
    login = await browser.get("/api/auth/login")
    query = idp.authorize(login.headers["location"])
    params = {"code": "code", "state": state or query["state"]}
    return await browser.get("/api/auth/callback", params=params)


async def test_sign_in_starts_at_the_identity_provider_with_pkce(
    browser: httpx2.AsyncClient, idp: FakeIdP
) -> None:
    login = await browser.get("/api/auth/login")

    query = idp.authorize(login.headers["location"])
    assert login.headers["location"].startswith(f"{ISSUER}/authorization?")
    assert (query["response_type"], query["client_id"]) == ("code", CLIENT_ID)
    assert query["redirect_uri"] == f"{APP}/api/auth/callback"
    assert (query["code_challenge_method"], query["scope"]) == ("S256", "openid profile")
    assert "__Host-infrasales_login=" in login.headers["set-cookie"]  # signed, single-use state


async def test_a_signed_in_admin_gets_a_session_and_is_audited(
    browser: httpx2.AsyncClient, idp: FakeIdP, database_url: str
) -> None:
    callback = await _sign_in(browser, idp)

    assert (callback.status_code, callback.headers["location"]) == (303, "/")
    assert "__Host-infrasales_session=" in callback.headers["set-cookie"]
    session = (await browser.get("/api/auth/session")).json()
    assert session == {
        "user": {"subject": "oidc:ada", "name": "Ada", "role": "admin"},
        "provider": "oidc",
    }
    (event,) = await audit_events(database_url)
    assert (event.actor, event.action, event.outcome.value) == ("oidc:ada", "auth.login", "success")


@pytest.mark.parametrize(
    ("groups", "role"),
    [
        (["infrasales-users"], "viewer"),
        ("infrasales-users", "viewer"),  # a single group as a string
        ({"infrasales-admins": {"org": "uni"}}, "admin"),  # an object keyed by role (ZITADEL)
    ],
)
async def test_groups_grant_roles(
    browser: httpx2.AsyncClient, idp: FakeIdP, groups: object, role: str
) -> None:
    idp.claims["groups"] = groups

    await _sign_in(browser, idp)

    assert (await browser.get("/api/auth/session")).json()["user"]["role"] == role


@pytest.mark.parametrize("groups", [["other-app"], None])
async def test_users_outside_the_groups_are_denied(
    browser: httpx2.AsyncClient, idp: FakeIdP, database_url: str, groups: object
) -> None:
    idp.claims["groups"] = groups

    callback = await _sign_in(browser, idp)

    assert callback.headers["location"] == "/?signin=denied"
    assert (await browser.get("/api/auth/session")).json()["user"] is None
    (event,) = await audit_events(database_url)
    assert (event.actor, event.outcome.value) == ("oidc:ada", "failure")


@pytest.mark.parametrize(
    "problem", ["forged state", "other audience", "other issuer", "no code verifier match"]
)
async def test_invalid_callbacks_fail_without_a_session(
    browser: httpx2.AsyncClient, idp: FakeIdP, database_url: str, problem: str
) -> None:
    match problem:
        case "forged state":
            callback = await _sign_in(browser, idp, state="forged")
        case "other audience" | "other issuer":
            claim = "aud" if problem == "other audience" else "iss"
            idp.id_token_claims = {claim: "https://elsewhere.test"}
            callback = await _sign_in(browser, idp)
        case _:
            await browser.get("/api/auth/login")
            login = await browser.get("/api/auth/login")
            query = idp.authorize(login.headers["location"])
            idp.authorize(login.headers["location"].replace(query["code_challenge"], "x"))
            params = {"code": "code", "state": query["state"]}
            callback = await browser.get("/api/auth/callback", params=params)

    assert callback.headers["location"] == "/?signin=failed"
    assert (await browser.get("/api/auth/session")).json()["user"] is None
    (event,) = await audit_events(database_url)
    assert (event.actor, event.outcome.value) == (None, "failure")


@pytest.mark.parametrize(
    ("configured", "signed_in"), [("https://idp.test/", True), (ISSUER, False)]
)
async def test_the_issuer_is_compared_exactly(
    settings: Settings, configured: str, *, signed_in: bool
) -> None:
    """A provider naming itself with a trailing "/" (as Auth0 does) is configured so, and must."""
    idp = FakeIdP(issuer="https://idp.test/")
    async with _browser(settings, idp, issuer=configured) as browser:
        callback = await _sign_in(browser, idp)

    assert callback.headers["location"] == ("/" if signed_in else "/?signin=failed")


async def test_a_subject_of_full_length_signs_in_acts_and_is_audited(
    browser: httpx2.AsyncClient, idp: FakeIdP, database_url: str
) -> None:
    """OpenID Connect allows 255 characters: with "oidc:" they fit wherever subjects are kept."""
    idp.claims["sub"] = "s" * 255
    await _sign_in(browser, idp)

    run = await browser.post("/api/jobs/scrape/runs", headers=SAME_ORIGIN)  # attributed to them

    subject = "oidc:" + "s" * 255
    assert run.status_code == 202
    assert (await browser.get("/api/auth/session")).json()["user"]["subject"] == subject
    assert [event.actor for event in await audit_events(database_url)] == [subject, subject]


@pytest.mark.parametrize("sub", ["", "s" * 256, 42], ids=["empty", "too long", "no string"])
async def test_a_subject_openid_connect_does_not_allow_fails_the_sign_in(
    browser: httpx2.AsyncClient, idp: FakeIdP, database_url: str, sub: object
) -> None:
    idp.claims["sub"] = sub

    callback = await _sign_in(browser, idp)

    assert callback.headers["location"] == "/?signin=failed"
    (event,) = await audit_events(database_url)
    assert (event.actor, event.outcome.value) == (None, "failure")


async def test_an_unreachable_identity_provider_is_reported(
    browser: httpx2.AsyncClient, idp: FakeIdP
) -> None:
    idp.available = False

    login = await browser.get("/api/auth/login")

    assert login.headers["location"] == "/?signin=unavailable"


async def test_sign_out_ends_the_identity_providers_session_too(
    browser: httpx2.AsyncClient, idp: FakeIdP
) -> None:
    await _sign_in(browser, idp)

    logout = await browser.post("/api/auth/logout", headers=SAME_ORIGIN)

    location = urlsplit(logout.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{ISSUER}/end_session"
    assert parse_qs(location.query) == {
        "client_id": [CLIENT_ID],
        "post_logout_redirect_uri": [f"{APP}/"],
    }
    assert "form-action 'self' https://idp.test" in logout.headers["content-security-policy"]


@pytest.mark.parametrize("problem", ["no end_session_endpoint", "unreachable"])
async def test_sign_out_stays_local_when_the_provider_cannot_end_its_session(
    settings: Settings, idp: FakeIdP, problem: str
) -> None:
    idp.end_session = problem != "no end_session_endpoint"
    idp.available = problem != "unreachable"

    async with _browser(settings, idp) as browser:
        logout = await browser.post("/api/auth/logout", headers=SAME_ORIGIN)

    assert logout.headers["location"] == "/"


async def test_plain_http_uses_cookies_without_the_host_prefix(
    settings: Settings, idp: FakeIdP
) -> None:
    async with _browser(settings, idp, public_url="http://localhost:8000") as browser:
        login = await browser.get("/api/auth/login")

    assert login.headers["set-cookie"].startswith("infrasales_login=")


async def test_signing_in_again_replaces_the_previous_session(
    browser: httpx2.AsyncClient, idp: FakeIdP
) -> None:
    await _sign_in(browser, idp)
    previous = browser.cookies["__Host-infrasales_session"]
    idp.claims = {
        "sub": "ada",
        "preferred_username": "ada.lovelace",
        "groups": ["infrasales-users"],
    }

    await _sign_in(browser, idp)
    current = (await browser.get("/api/auth/session")).json()["user"]
    browser.cookies.set("__Host-infrasales_session", previous, domain="infrasales.test")

    assert current == {"subject": "oidc:ada", "name": "ada.lovelace", "role": "viewer"}
    assert (await browser.get("/api/auth/session")).json()["user"] is None
