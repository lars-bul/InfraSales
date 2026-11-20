from pydantic import SecretStr

from infrasales.ai.providers import BASE_URLS, Connection, Provider


def test_each_service_is_reached_at_its_own_address_over_https() -> None:
    connections = [Connection(provider, SecretStr("sk-test")) for provider in Provider]

    assert [c.base_url for c in connections] == [BASE_URLS[p] for p in Provider]
    assert all(url.startswith("https://") for url in BASE_URLS.values())


def test_a_connection_never_shows_its_key() -> None:
    connection = Connection(Provider.OPENROUTER, SecretStr("sk-or-secret"))

    assert "sk-or-secret" not in repr(connection)
