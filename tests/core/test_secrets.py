import pytest
from pydantic import SecretStr

from infrasales.core.secrets import SecretBox, UnreadableSecretError, new_key

BOX = SecretBox(SecretStr(new_key()))


def test_a_sealed_secret_opens_again_and_never_shows_in_the_sealed_text() -> None:
    sealed = BOX.seal("sk-or-v1-secret")

    assert "sk-or-v1-secret" not in sealed
    assert BOX.open(sealed) == "sk-or-v1-secret"
    assert BOX.seal("sk-or-v1-secret") != sealed


def test_a_secret_sealed_under_another_key_is_unreadable() -> None:
    sealed = SecretBox(SecretStr(new_key())).seal("sk-or-v1-secret")

    with pytest.raises(UnreadableSecretError):
        BOX.open(sealed)


def test_a_tampered_secret_is_unreadable() -> None:
    sealed = BOX.seal("sk-or-v1-secret")

    with pytest.raises(UnreadableSecretError):
        BOX.open(sealed[:-4] + "AAAA")


def test_only_a_fernet_key_makes_a_box() -> None:
    with pytest.raises(ValueError, match="SECRETS_KEY"):
        SecretBox(SecretStr("too-short"))
