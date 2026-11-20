# Minimal stub: Authlib ships no type information. Only the API infrasales.auth.providers.oidc uses;
# `Any` mirrors Authlib's untyped **kwargs and JSON payloads.
from typing import Any

from starlette.requests import Request
from starlette.responses import RedirectResponse

class OAuthError(Exception):
    error: str | None

class StarletteOAuth2App:
    async def load_server_metadata(self) -> dict[str, Any]: ...
    async def authorize_redirect(
        self, request: Request, redirect_uri: str | None = None, **kwargs: Any
    ) -> RedirectResponse: ...
    async def authorize_access_token(self, request: Request, **kwargs: Any) -> dict[str, Any]: ...

class OAuth:
    def register(self, name: str, overwrite: bool = False, **kwargs: Any) -> StarletteOAuth2App: ...
