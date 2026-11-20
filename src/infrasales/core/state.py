"""Typed access to what the application holds for its lifetime."""

from starlette.applications import Starlette
from starlette.requests import HTTPConnection


class StateKey[T]:
    def __init__(self, name: str) -> None:
        self.name = name

    def set(self, app: Starlette, value: T) -> None:
        setattr(app.state, self.name, value)

    def get(self, connection: HTTPConnection) -> T:
        """The value; it is set when the application is created or started."""
        return getattr(connection.app.state, self.name)

    def find(self, connection: HTTPConnection) -> T | None:
        """The value, or None if the application has none."""
        return getattr(connection.app.state, self.name, None)
