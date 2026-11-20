import pytest

from infrasales.extract import media
from infrasales.extract.registry import EXTRACTORS


@pytest.mark.parametrize(
    ("media_type", "extension", "extractor"),
    [
        ("text/html", "html", "html"),
        ("application/xhtml+xml", "html", "html"),  # the exact name before the suffix
        ("application/atom+xml", "xml", "passthrough"),
        ("application/ld+json", "json", "passthrough"),
        ("application/x-pdf", "pdf", "pdf"),
        ("text/plain", "txt", None),
    ],
)
def test_a_media_type_names_its_raw_file_and_its_extractor(
    media_type: str, extension: str, extractor: str | None
) -> None:
    assert media.known(media_type) == media.MediaType(extension, extractor)


@pytest.mark.parametrize("media_type", ["image/png", "", "application/vnd.foo+zip"])
def test_other_media_types_are_unknown(media_type: str) -> None:
    assert media.known(media_type) is None


def test_every_extractor_named_by_a_media_type_exists() -> None:
    named = {t.extractor for t in [*media.KNOWN.values(), *media.BY_SUFFIX.values()]}
    assert named - {None} <= set(EXTRACTORS)
