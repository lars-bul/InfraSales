"""Sign-in providers start sessions their own way; everything after sign-in is shared.

Only the configured provider is imported: with basic sign-in, OpenID Connect's libraries are
never loaded.
"""

from typing import Literal, Protocol

from fastapi import FastAPI, Request
from pydantic import HttpUrl

from infrasales.auth.settings import AuthSettings, BasicAuthSettings
from infrasales.core.state import StateKey


class AuthProvider(Protocol):
    form_targets: str  # origins sign-in forms or redirects go to besides the app (CSP)

    @property
    def name(self) -> Literal["basic", "oidc"]:
        """How the UI signs in: a form, or a redirect."""
        ...

    @property
    def public_url(self) -> HttpUrl:
        """Where browsers reach the app: https makes the session cookie Secure."""
        ...

    def install(self, app: FastAPI) -> None:
        """Add the provider's sign-in routes (and middleware, if it needs any)."""
        ...

    async def logout_url(self, request: Request, /) -> str:
        """Where the browser goes after signing out."""
        ...


AUTH_PROVIDER = StateKey[AuthProvider]("auth_provider")


def load_provider(settings: AuthSettings, public_url: HttpUrl) -> AuthProvider:
    if isinstance(settings, BasicAuthSettings):
        from infrasales.auth.providers.basic import BasicProvider

        return BasicProvider(settings, public_url)
    from infrasales.auth.providers.oidc import OIDCProvider

    return OIDCProvider(settings, public_url)
