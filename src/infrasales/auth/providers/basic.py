"""Built-in sign-in: a form posts a user name and the shared password."""

from hmac import compare_digest
from typing import Literal
from urllib.parse import parse_qs

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import RedirectResponse
from pydantic import HttpUrl

from infrasales.audit import service as audit
from infrasales.audit.models import Outcome
from infrasales.auth import sessions
from infrasales.auth.cookies import session_token, set_session_cookie
from infrasales.auth.models import User
from infrasales.auth.settings import BasicAuthSettings
from infrasales.core.db import Session
from infrasales.core.models import utcnow


class BasicProvider:
    name: Literal["basic"] = "basic"
    form_targets = ""

    def __init__(self, settings: BasicAuthSettings, public_url: HttpUrl) -> None:
        self._settings = settings
        self.public_url = public_url

    def install(self, app: FastAPI) -> None:
        router = APIRouter(prefix="/api/auth", include_in_schema=False)  # browser form target
        router.add_api_route("/login", self.login, methods=["POST"])
        app.include_router(router)

    async def logout_url(self, _: Request, /) -> str:
        return "/"

    async def login(self, request: Request, session: Session) -> RedirectResponse:
        """Sign in from the form (urlencoded); always redirect back to the app."""
        form = parse_qs((await request.body()).decode(errors="replace"))
        username = form.get("username", [""])[0]
        password = form.get("password", [""])[0]
        role = self._settings.users.get(username)
        expected = self._settings.password.get_secret_value().encode()
        # Compared even for unknown users: the response time does not reveal who exists.
        valid = compare_digest(password.encode(), expected) and role is not None
        subject = f"basic:{username}" if role else None  # mistyped names are never recorded
        outcome = Outcome.SUCCESS if valid else Outcome.FAILURE
        audit.record(session, actor=subject, action="auth.login", outcome=outcome, request=request)
        if not valid or role is None:
            return RedirectResponse("/?signin=failed", status_code=303)
        if previous := session_token(request, self.public_url):  # no session fixation
            await sessions.end(session, previous)
        user = User(subject=f"basic:{username}", name=username, role=role)
        token = await sessions.start(session, user, utcnow())
        response = RedirectResponse("/", status_code=303)
        set_session_cookie(response, token, self.public_url)
        return response
