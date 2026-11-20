from datetime import date
from pathlib import Path

from infrasales.sources import gemeinden
from tests.sources.support import gemeindeverzeichnis


def test_every_municipality_row_is_read_with_its_key_size_and_place(tmp_path: Path) -> None:
    as_of, records = gemeinden.read(gemeindeverzeichnis(tmp_path / "gv.xlsx"))

    assert as_of == date(2024, 12, 31)
    assert [r.ags for r in records] == ["08221000", "08421000", "08226095"]
    heidelberg = records[0]
    assert (heidelberg.name, heidelberg.population, heidelberg.post_code) == (
        "Heidelberg, Stadt",
        162273,
        "69117",
    )
    assert (heidelberg.area_km2, heidelberg.latitude, heidelberg.longitude) == (
        108.83,
        49.40768,
        8.69079,
    )
    assert [r.urbanisation for r in records] == [1, 1, 2]
