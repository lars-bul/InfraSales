"""Sign-in configuration: `AUTH__PROVIDER` picks the provider, its own settings follow."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, SecretStr, model_validator

from infrasales.auth.models import Role
from infrasales.core.fields import CommaSeparated, ExactUrl


class BasicAuthSettings(BaseModel):
    """Built-in sign-in: a fixed set of users sharing one password (sample users by default).

    Meant for development, demos and tests; production setups use OpenID Connect.
    """

    provider: Literal["basic"]
    password: SecretStr = Field(min_length=8)  # AUTH__PASSWORD or /run/secrets/auth__password
    users: dict[str, Role] = Field(  # AUTH__USERS='{"alice": "admin", "vera": "viewer"}'
        default_factory=lambda: {"alice": Role.ADMIN, "vera": Role.VIEWER}
    )


class OIDCAuthSettings(BaseModel):
    """OpenID Connect with the organization's identity provider: the production choice.

    Register the app as a confidential client with the redirect URI
    `{WEB__PUBLIC_URL}/api/auth/callback` and `{WEB__PUBLIC_URL}/` as post-logout redirect.
    """

    provider: Literal["oidc"]
    issuer: ExactUrl  # AUTH__ISSUER, exactly as the provider's `iss`: with its "/", if any
    client_id: str = Field(min_length=1)
    client_secret: SecretStr  # AUTH__CLIENT_SECRET or /run/secrets/auth__client_secret
    state_secret: SecretStr = Field(min_length=32)  # signs the short-lived sign-in state cookie
    scope: str = "openid profile"
    groups_claim: str = "groups"  # the ID token claim listing the user's groups or roles
    admin_groups: CommaSeparated = Field(default_factory=list[str])  # AUTH__ADMIN_GROUPS=a,b
    viewer_groups: CommaSeparated = Field(default_factory=list[str])

    @model_validator(mode="after")
    def _someone_may_sign_in(self) -> Self:
        if not self.admin_groups and not self.viewer_groups:
            msg = "set AUTH__ADMIN_GROUPS and/or AUTH__VIEWER_GROUPS: nobody else may sign in"
            raise ValueError(msg)
        return self


AuthSettings = Annotated[BasicAuthSettings | OIDCAuthSettings, Field(discriminator="provider")]
