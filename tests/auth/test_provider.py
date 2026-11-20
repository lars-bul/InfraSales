from pydantic import HttpUrl, SecretStr

from infrasales.auth.provider import load_provider
from infrasales.auth.providers.basic import BasicProvider
from infrasales.auth.providers.oidc import OIDCProvider
from infrasales.auth.settings import BasicAuthSettings, OIDCAuthSettings


def test_basic_settings_load_the_basic_provider() -> None:
    settings = BasicAuthSettings(provider="basic", password=SecretStr("long-enough"))

    provider = load_provider(settings, HttpUrl("http://localhost:8000"))

    assert isinstance(provider, BasicProvider)
    assert provider.form_targets == ""


def test_oidc_settings_load_the_oidc_provider() -> None:
    settings = OIDCAuthSettings(
        provider="oidc",
        issuer="https://idp.test/realms/infrasales",
        client_id="infrasales",
        client_secret=SecretStr("secret"),
        state_secret=SecretStr("s" * 32),
        admin_groups=["infrasales-admins"],
    )

    provider = load_provider(settings, HttpUrl("https://infrasales.test"))

    assert isinstance(provider, OIDCProvider)
    assert provider.form_targets == "https://idp.test"
