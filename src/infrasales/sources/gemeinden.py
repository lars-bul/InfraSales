"""The Gemeindeverzeichnis of Destatis: every German municipality with its key, size and place.

Destatis publishes it as a workbook ("Alle politisch selbständigen Gemeinden", e.g.
`31122024_Auszug_GV.xlsx`): one row per area, its kind in the first column ("Satzart"; 60 is a
municipality), its regional key split over five columns (Land, Regierungsbezirk, Kreis,
Gemeindeverband, Gemeinde), then name, area, population (based on the 2022 census), the town hall's
post code, the geographic centre and the degree of urbanisation. The AGS is the key without the
Gemeindeverband.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from infrasales.sources.xlsx import sheets

MUNICIPALITY = "60"  # Satzart of a municipality's row
AGS_DIGITS = 8


@dataclass(frozen=True, slots=True)
class MunicipalityRecord:
    ags: str
    name: str
    area_km2: float | None
    population: int | None
    post_code: str | None
    longitude: float | None
    latitude: float | None
    urbanisation: int | None


def _number(text: str) -> float | None:
    try:
        return float(text.replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def read(path: Path) -> tuple[date | None, list[MunicipalityRecord]]:
    """The day the directory describes (from its title, if given) and its municipalities."""
    rows = next(rows for name, rows in sheets(path).items() if name.startswith("Onlineprodukt"))
    as_of = None
    for row in rows[:6]:
        for cell in row:
            if (found := _title_day(cell)) is not None:
                as_of = found
                break
    records: list[MunicipalityRecord] = []
    for row in rows:
        cells = [*row, *[""] * (20 - len(row))]
        if cells[0] != MUNICIPALITY:
            continue
        ags = f"{cells[2]}{cells[3]}{cells[4]}{cells[6]}"
        if len(ags) != AGS_DIGITS or not ags.isdigit():
            continue
        population = _number(cells[9])
        urbanisation = cells[18].strip()
        records.append(
            MunicipalityRecord(
                ags=ags,
                name=cells[7].strip(),
                area_km2=_number(cells[8]),
                population=round(population) if population is not None else None,
                post_code=cells[13].strip() or None,
                longitude=_number(cells[14]),
                latitude=_number(cells[15]),
                urbanisation=int(urbanisation) if urbanisation.isdigit() else None,
            )
        )
    return as_of, records


def _title_day(text: str) -> date | None:
    """The day a title names: "… am 31.12.2024 (Jahr)" is 2024-12-31."""
    marker = text.find(" am ")
    if marker < 0:
        return None
    day = text[marker + 4 : marker + 14]
    parts = day.split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):  # noqa: PLR2004
        return date(int(parts[2]), int(parts[1]), int(parts[0]))
    return None
