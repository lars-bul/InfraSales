from sqlmodel import Field

from infrasales.core.models import BaseTable, JSONType, JSONValue


class ConfigEntry(BaseTable, table=True):
    """One global setting: a key and its JSON value, validated by the key's schema."""

    key: str = Field(max_length=64, unique=True)  # a ConfigKey; plain text keeps old keys readable
    value: dict[str, JSONValue] = Field(sa_type=JSONType)
    revision: int = Field(default=1, sa_column_kwargs={"server_default": "1"})  # existing rows
