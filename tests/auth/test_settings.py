import pytest
from pydantic import SecretStr, ValidationError

from infrasales.auth.models import Role
from infrasales.auth.settings import BasicAuthSettings, OIDCAuthSettings
from infrasales.settings import Settings


def test_basic_sign_in_has_two_sample_users() -> None:
    settings = BasicAuthSettings(provider="basic", password=SecretStr("long-enough"))

    assert settings.users == {"alice": Role.ADMIN, "vera": Role.VIEWER}


def test_the_shared_password_must_not_be_trivial() -> None:
    with pytest.raises(ValidationError, match="at least 8"):
        BasicAuthSettings(provider="basic", password=SecretStr("short"))


def test_sign_in_is_configured_through_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x.db")
    monkeypatch.setenv("AUTH__PROVIDER", "basic")
    monkeypatch.setenv("AUTH__PASSWORD", "from-the-environment")
    monkeypatch.setenv("AUTH__USERS", '{"bob": "admin"}')

    auth = Settings.load().auth

    assert isinstance(auth, BasicAuthSettings)
    assert auth.password.get_secret_value() == "from-the-environment"
    assert auth.users == {"bob": Role.ADMIN}


def test_sign_in_must_be_chosen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x.db")
    monkeypatch.delenv("AUTH__PROVIDER", raising=False)

    with pytest.raises(ValidationError, match="auth"):
        Settings.load()


def test_oidc_is_configured_through_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x.db")
    for name, value in {
        "PROVIDER": "oidc",
        "ISSUER": "https://idp.example.org",
        "CLIENT_ID": "infrasales",
        "CLIENT_SECRET": "secret",
        "STATE_SECRET": "s" * 32,
        "ADMIN_GROUPS": "infrasales-admins, sales-team",
    }.items():
        monkeypatch.setenv(f"AUTH__{name}", value)

    auth = Settings.load().auth

    assert isinstance(auth, OIDCAuthSettings)
    assert auth.admin_groups == ["infrasales-admins", "sales-team"]
    assert auth.viewer_groups == []


def test_oidc_without_any_group_lets_nobody_in() -> None:
    with pytest.raises(ValidationError, match="AUTH__ADMIN_GROUPS"):
        OIDCAuthSettings.model_validate(
            {
                "provider": "oidc",
                "issuer": "https://idp.test",
                "client_id": "infrasales",
                "client_secret": "secret",
                "state_secret": "s" * 32,
            }
        )
