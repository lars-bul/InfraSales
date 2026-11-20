import pytest

from infrasales.core.text import stripped


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  A title \n", "A title"),
        ("   ", None),
        ("", None),
        (None, None),
        (42, None),
        (["A title"], None),
    ],
)
def test_only_a_string_with_text_is_kept_stripped(value: object, expected: str | None) -> None:
    assert stripped(value) == expected
