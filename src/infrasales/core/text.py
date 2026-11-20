"""Text as documents and feeds give it: any value, maybe a string, maybe blank."""


def stripped(value: object) -> str | None:
    """`value` without surrounding whitespace if it is a string with any text, else None."""
    return value.strip() or None if isinstance(value, str) else None
