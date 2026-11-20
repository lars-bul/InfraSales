from typing import Literal

from pydantic import BaseModel

from infrasales.auth.models import User


class SessionInfo(BaseModel):
    user: User | None  # None: not signed in
    provider: Literal["basic", "oidc"]  # how the UI signs in: a form, or a redirect
