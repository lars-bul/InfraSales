from infrasales.extract.registry import EXTRACTORS


def test_every_extractor_names_itself_and_its_version() -> None:
    assert all(
        name == extractor.name and extractor.version for name, extractor in EXTRACTORS.items()
    )
