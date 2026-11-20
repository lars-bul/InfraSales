from infrasales.auth.models import Role, User
from infrasales.auth.schemas import SessionInfo


def test_session_info_serializes_for_the_ui() -> None:
    vera = User(subject="basic:vera", name="vera", role=Role.VIEWER)

    assert SessionInfo(user=vera, provider="basic").model_dump(mode="json") == {
        "user": {"subject": "basic:vera", "name": "vera", "role": "viewer"},
        "provider": "basic",
    }
    assert SessionInfo(user=None, provider="basic").model_dump()["user"] is None
