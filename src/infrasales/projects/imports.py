"""CSV imports of public data: municipalities, signals, tenders and municipality metrics.

What a curator collected by hand, a dataset someone published, or what a collector wrote out: one
row per record, headed by the field names below, comma- or semicolon-separated, UTF-8. A file is
imported whole or not at all: any invalid row refuses it, every error named by its line. Rows
are matched by their key (a municipality's AGS, a signal's ref, a tender's origin and ref, a
metric's municipality, kind, day and source), so importing a file again updates, never doubles;
an update changes the values a row gives, and keeps those of its blank or missing cells.

Dates are ISO (2026-03-01); empty cells are empty values; a tender's CPV codes are separated by
`|`; yes/no fields take true/false, 1/0, yes/no.
"""

import csv
import io
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.projects.models import (
    MAX_NAME_LENGTH,
    MetricKind,
    Municipality,
    MunicipalityMetric,
    Sector,
    Signal,
    SignalKind,
    Tender,
    TenderKind,
    TenderOrigin,
    TenderStatus,
)

CHUNK = 500  # keys looked up per query
MAX_ERRORS = 50  # errors reported per file: the first ones show what is wrong


class ImportKind(StrEnum):
    MUNICIPALITIES = "municipalities"
    SIGNALS = "signals"
    TENDERS = "tenders"
    METRICS = "metrics"


def _ags(value: str) -> str:
    if not (len(value) == 8 and value.isdigit()):  # noqa: PLR2004  # the AGS has eight digits
        msg = "an AGS has eight digits, e.g. 08221000"
        raise ValueError(msg)
    return value


def _codes(value: object) -> object:
    if isinstance(value, str):
        return [code.strip() for code in value.split("|") if code.strip()]
    return value


type Ags = Annotated[str, AfterValidator(_ags)]


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


class MunicipalityRow(_Row):
    ags: Ags
    name: str = Field(min_length=1, max_length=200)
    population: int | None = Field(default=None, ge=0)
    population_as_of: date | None = None
    area_km2: float | None = Field(default=None, gt=0)


class SignalRow(_Row):
    kind: SignalKind
    ags: Ags
    available_on: date
    occurred_on: date | None = None
    ref: str = Field(min_length=1, max_length=512)
    note: str = Field(default="", max_length=MAX_NAME_LENGTH)
    url: str | None = Field(default=None, max_length=2048)


class TenderRow(_Row):
    origin: TenderOrigin
    ref: str = Field(min_length=1, max_length=200)
    kind: TenderKind
    status: TenderStatus
    title: str = Field(min_length=1, max_length=500)
    ags: Ags | None = None
    buyer_name: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    lot: str | None = Field(default=None, max_length=100)
    framework: bool = False
    procedure: str | None = Field(default=None, max_length=64)
    cpv: Annotated[list[str], BeforeValidator(_codes)] = Field(default_factory=list[str])
    available_on: date
    published_on: date | None = None
    deadline_on: date | None = None
    awarded_on: date | None = None
    contract_end_on: date | None = None
    offers: int | None = Field(default=None, ge=0)
    estimated_value_eur: int | None = Field(default=None, ge=0)
    award_value_eur: int | None = Field(default=None, ge=0)
    winner_name: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    url: str | None = Field(default=None, max_length=2048)
    exclusive: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> TenderRow:
        if self.status is not TenderStatus.PLANNED and self.published_on is None:
            msg = f"a {self.status} tender needs published_on"
            raise ValueError(msg)
        if self.exclusive and self.origin is not TenderOrigin.PRIVATE_REQUEST:
            msg = "only a private builder's request is exclusive to subscribers"
            raise ValueError(msg)
        return self


class MetricRow(_Row):
    ags: Ags
    metric: MetricKind
    as_of: date
    available_on: date
    value: float
    source: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _share(self) -> MetricRow:
        if self.metric.value.endswith("_share") and not 0 <= self.value <= 1:
            msg = f"{self.metric} is a share between 0 and 1"
            raise ValueError(msg)
        return self


@dataclass(slots=True)
class ImportResult:
    inserted: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list[str])

    @property
    def ok(self) -> bool:
        return not self.errors


def read_rows(text: str) -> list[dict[str, str]]:
    """The rows of a CSV text, by header; comma or semicolon, whichever the header uses."""
    text = text.removeprefix("\ufeff")
    header = text.split("\n", 1)[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [
        {(key or "").strip(): (value or "") for key, value in row.items()}
        for row in reader
        if any((value or "").strip() for value in row.values())
    ]


@dataclass(frozen=True, slots=True)
class _Spec[R: _Row]:
    row: type[R]
    table: type[SQLModel]
    key: Callable[[R], tuple[object, ...]]  # the row's key
    stored_key: Callable[[Any], tuple[object, ...]]  # a stored record's key
    lookup: str  # the column narrowing the stored records to look at
    values: Callable[[R], dict[str, object]]


def _signal_values(row: SignalRow) -> dict[str, object]:
    return {
        "kind": row.kind,
        "municipality_ags": row.ags,
        "available_on": row.available_on,
        "occurred_on": row.occurred_on,
        "ref": row.ref,
        "note": row.note,
        "url": row.url,
    }


def _tender_values(row: TenderRow) -> dict[str, object]:
    values = row.model_dump(exclude={"ags"})
    return {**values, "municipality_ags": row.ags, "sector": Sector.HEAT_NETWORK}


def _metric_values(row: MetricRow) -> dict[str, object]:
    values = row.model_dump(exclude={"ags"})
    return {**values, "municipality_ags": row.ags}


_SPECS: dict[ImportKind, _Spec[Any]] = {
    ImportKind.MUNICIPALITIES: _Spec(
        MunicipalityRow,
        Municipality,
        key=lambda row: (row.ags,),
        stored_key=lambda stored: (stored.ags,),
        lookup="ags",
        values=lambda row: row.model_dump(),
    ),
    ImportKind.SIGNALS: _Spec(
        SignalRow,
        Signal,
        key=lambda row: (row.ref,),
        stored_key=lambda stored: (stored.ref,),
        lookup="ref",
        values=_signal_values,
    ),
    ImportKind.TENDERS: _Spec(
        TenderRow,
        Tender,
        key=lambda row: (row.origin, row.ref),
        stored_key=lambda stored: (stored.origin, stored.ref),
        lookup="ref",
        values=_tender_values,
    ),
    ImportKind.METRICS: _Spec(
        MetricRow,
        MunicipalityMetric,
        key=lambda row: (row.ags, row.metric, row.as_of, row.source),
        stored_key=lambda stored: (
            stored.municipality_ags,
            stored.metric,
            stored.as_of,
            stored.source,
        ),
        lookup="municipality_ags",
        values=_metric_values,
    ),
}


type Lined[R] = list[tuple[int, R]]  # rows by their line in the file; the header is line 1


def parse[R: _Row](row_type: type[R], rows: Sequence[dict[str, str]]) -> tuple[Lined[R], list[str]]:
    """The valid rows by their line, and an error per invalid one, named by its line."""
    parsed: Lined[R] = []
    errors: list[str] = []
    for line, raw in enumerate(rows, start=2):
        try:
            filled = {name: value for name, value in raw.items() if value.strip()}  # blank: default
            parsed.append((line, row_type.model_validate(filled)))
        except ValidationError as error:
            reasons = "; ".join(
                f"{'.'.join(str(part) for part in issue['loc']) or 'row'}: {issue['msg']}"
                for issue in error.errors()
            )
            errors.append(f"line {line}: {reasons}")
    return parsed, errors


async def import_csv(session: AsyncSession, kind: ImportKind, text: str) -> ImportResult:
    """Import a CSV text of `kind`: all of it, or nothing and the errors why."""
    spec = _SPECS[kind]
    rows, errors = parse(spec.row, read_rows(text))
    errors += _duplicates(spec, rows)
    if kind is not ImportKind.MUNICIPALITIES:
        errors += await _unknown_places(session, rows)
    if errors:
        errors.sort(key=_line)
        return ImportResult(errors=errors[:MAX_ERRORS])
    stored = await _stored(session, spec, [row for _, row in rows])
    result = ImportResult()
    for _, row in rows:
        values = spec.values(row)
        if (record := stored.get(spec.key(row))) is None:
            session.add(spec.table(**values))
            result.inserted += 1
        else:  # what the row gives; a blank or missing cell keeps the stored value
            given = {_COLUMNS.get(name, name) for name in row.model_fields_set}
            for name, value in values.items():
                if name in given:
                    setattr(record, name, value)
            session.add(record)
            result.updated += 1
    await session.flush()
    return result


_COLUMNS = {"ags": "municipality_ags"}  # a row's field, where its column is named otherwise


def _line(error: str) -> int:
    return int(error.split(":", 1)[0].removeprefix("line "))


def _duplicates(spec: _Spec[Any], rows: Lined[_Row]) -> list[str]:
    seen: dict[tuple[object, ...], int] = {}
    errors: list[str] = []
    for line, row in rows:
        key = spec.key(row)
        if key in seen:
            errors.append(f"line {line}: the same record as line {seen[key]}")
        seen.setdefault(key, line)
    return errors


async def _unknown_places(session: AsyncSession, rows: Lined[_Row]) -> list[str]:
    wanted = {ags for _, row in rows if isinstance(ags := getattr(row, "ags", None), str)}
    known: set[str] = set()
    for chunk in _chunks(sorted(wanted)):
        statement = select(Municipality.ags).where(col(Municipality.ags).in_(chunk))
        known.update(await session.exec(statement))
    return [
        f"line {line}: no municipality {ags}; import the municipalities first"
        for line, row in rows
        if isinstance(ags := getattr(row, "ags", None), str) and ags not in known
    ]


async def _stored(
    session: AsyncSession, spec: _Spec[Any], rows: Sequence[_Row]
) -> dict[tuple[object, ...], Any]:
    column = getattr(spec.table, spec.lookup)
    lookups = sorted({str(spec.values(row)[spec.lookup]) for row in rows})
    stored: dict[tuple[object, ...], Any] = {}
    for chunk in _chunks(lookups):
        for record in await session.exec(select(spec.table).where(col(column).in_(chunk))):
            stored[spec.stored_key(record)] = record
    return stored


def _chunks(values: Sequence[str]) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), CHUNK):
        yield values[start : start + CHUNK]
