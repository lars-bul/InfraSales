import re

import pytest

from infrasales.projects.ids import new_public_id, parse_public_id


def test_a_new_id_is_short_and_readable() -> None:
    public_id = new_public_id()

    assert re.fullmatch(r"P-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}", public_id)


def test_new_ids_differ() -> None:
    assert len({new_public_id() for _ in range(1000)}) == 1000


@pytest.mark.parametrize(
    "typed",
    ["P-7K2M-9XQ4", "p-7k2m-9xq4", "P7K2M9XQ4", "7K2M-9XQ4", " 7k2m 9xq4 ", "P-7K2M-9XQ4\n"],
)
def test_an_id_is_read_whatever_its_case_hyphens_and_prefix(typed: str) -> None:
    assert parse_public_id(typed) == "P-7K2M-9XQ4"


def test_letters_easily_misread_are_read_as_the_ones_they_look_like() -> None:
    assert parse_public_id("P-IL0O-UUUU") == "P-1100-VVVV"


def test_an_id_starting_with_p_needs_no_prefix() -> None:
    assert parse_public_id("PK2M-9XQ4") == "P-PK2M-9XQ4"


@pytest.mark.parametrize("typed", ["", "P-", "P-7K2M-9XQ", "P-7K2M-9XQ45", "P-7K2M-9XQ!"])
def test_text_that_names_no_id_is_refused(typed: str) -> None:
    assert parse_public_id(typed) is None
