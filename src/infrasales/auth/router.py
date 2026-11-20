from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from infrasales.audit import service as audit
from infrasales.auth import sessions
from infrasales.auth.cookies import clear_session_cookie, session_token
from infrasales.auth.deps import OptionalUser, public_url
from infrasales.auth.provider import AUTH_PROVIDER
from infrasales.auth.schemas import SessionInfo
from infrasales.core.db import Session
from infrasales.core.models import utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/session")
async def read_session(request: Request, user: OptionalUser) -> SessionInfo:
    """Who is signed in (if anyone), and how to sign in."""
    return SessionInfo(user=user, provider=AUTH_PROVIDER.get(request).name)


@router.post("/logout", response_class=RedirectResponse, status_code=303)
async def logout(request: Request, session: Session) -> RedirectResponse:
    """End the session (a form post); the browser follows the redirect."""
    if token := session_token(request, public_url(request)):
        if user := await sessions.resolve(session, token, utcnow()):
            audit.record(session, actor=user.subject, action="auth.logout", request=request)
        await sessions.end(session, token)
    logout_url = await AUTH_PROVIDER.get(request).logout_url(request)
    response = RedirectResponse(logout_url, status_code=303)
    clear_session_cookie(response, public_url(request))
    return response
