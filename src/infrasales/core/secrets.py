"""Secrets kept in the database, encrypted with Fernet under `SECRETS_KEY` (ADR 05)."""

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr


class UnreadableSecretError(Exception):
    """Sealed under another key, or altered."""


class SecretBox:
    def __init__(self, key: SecretStr) -> None:
        try:
            self._fernet = Fernet(key.get_secret_value())
        except ValueError:
            msg = "SECRETS_KEY must be a Fernet key: run `infrasales secrets-key` for one"
            raise ValueError(msg) from None

    def seal(self, secret: str) -> str:
        return self._fernet.encrypt(secret.encode()).decode()

    def open(self, sealed: str) -> str:
        try:
            return self._fernet.decrypt(sealed).decode()
        except InvalidToken:
            raise UnreadableSecretError from None


def new_key() -> str:
    return Fernet.generate_key().decode()
