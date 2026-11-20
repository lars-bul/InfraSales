from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.projects.imports import (
    MAX_ERRORS,
    ImportKind,
    MunicipalityRow,
    import_csv,
    parse,
    read_rows,
)
from infrasales.projects.models import (
    MetricKind,
    Municipality,
    MunicipalityMetric,
    Signal,
    SignalKind,
    Tender,
    TenderOrigin,
    TenderStatus,
)

pytestmark = pytest.mark.anyio

MUNICIPALITIES = """ags,name,population,population_as_of,area_km2
08221000,Heidelberg,162000,2024-12-31,108.8
08421000,Ulm,128000,,118.7
"""


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[Database]:
    db = Database(database_url)
    async with db.session() as session:
        assert (await import_csv(session, ImportKind.MUNICIPALITIES, MUNICIPALITIES)).ok
    yield db
    await db.dispose()


def test_rows_are_read_by_header_with_commas_or_semicolons_and_a_bom() -> None:
    assert read_rows("\ufeffags;name\n08221000;Heidelberg\n\n") == [
        {"ags": "08221000", "name": "Heidelberg"}
    ]
    assert read_rows("ags,name\n08221000,Heidelberg\n") == [
        {"ags": "08221000", "name": "Heidelberg"}
    ]


def test_an_invalid_row_is_named_by_its_line_and_field() -> None:
    rows = read_rows("ags,name,population\n08221000,Heidelberg,-1\n8221000,Ulm,\n")

    parsed, errors = parse(MunicipalityRow, rows)

    assert parsed == []
    assert errors[0].startswith("line 2: population:")
    assert errors[1].startswith("line 3: ags: Value error, an AGS has eight digits")


async def test_municipalities_are_imported_and_updated_by_their_ags(db: Database) -> None:
    again = "ags,name,population\n08221000,Heidelberg,163000\n08111000,Stuttgart,610000\n"
    async with db.session() as session:
        result = await import_csv(session, ImportKind.MUNICIPALITIES, again)
    async with db.session() as session:
        stored = {m.ags: m for m in await session.exec(select(Municipality))}

    assert (result.inserted, result.updated) == (1, 1)
    assert stored["08221000"].population == 163_000
    assert stored["08221000"].area_km2 == 108.8  # not in the file: kept
    assert stored["08421000"].area_km2 == 118.7
    assert len(stored) == 3


async def test_signals_are_imported_once_per_ref(db: Database) -> None:
    signals = (
        "kind,ags,available_on,occurred_on,ref,note,url\n"
        "council_decision,08221000,2025-06-12,2025-06-05,ris:hd:2025-117,Netz Süd,"
        "https://example.org/117\n"
        "funding_granted,08421000,2025-09-01,,bafa:2025:ulm,,\n"
    )
    async with db.session() as session:
        first = await import_csv(session, ImportKind.SIGNALS, signals)
    async with db.session() as session:
        second = await import_csv(session, ImportKind.SIGNALS, signals)
    async with db.session() as session:
        stored = {s.ref: s for s in await session.exec(select(Signal))}

    assert (first.inserted, second.inserted, second.updated) == (2, 0, 2)
    council = stored["ris:hd:2025-117"]
    assert (council.kind, council.occurred_on, council.note) == (
        SignalKind.COUNCIL_DECISION,
        date(2025, 6, 5),
        "Netz Süd",
    )
    assert (stored["bafa:2025:ulm"].note, stored["bafa:2025:ulm"].url) == ("", None)


async def test_a_file_with_one_bad_row_imports_nothing(db: Database) -> None:
    signals = (
        "kind,ags,available_on,ref\n"
        "council_decision,08221000,2025-06-12,a\n"
        "rumour,08221000,2025-06-12,b\n"
        "council_decision,09162000,2025-06-12,c\n"
        "council_decision,08221000,2025-06-12,a\n"
    )
    async with db.session() as session:
        result = await import_csv(session, ImportKind.SIGNALS, signals)
    async with db.session() as session:
        stored = (await session.exec(select(Signal))).all()

    assert not result.ok
    assert [error.split(":")[0] for error in result.errors] == ["line 3", "line 4", "line 5"]
    assert "import the municipalities first" in result.errors[1]
    assert "the same record as line 2" in result.errors[2]
    assert stored == []


async def test_errors_are_reported_up_to_a_limit(db: Database) -> None:
    rows = "".join(f"rumour,08221000,2025-06-12,r{i}\n" for i in range(MAX_ERRORS + 5))
    async with db.session() as session:
        result = await import_csv(session, ImportKind.SIGNALS, "kind,ags,available_on,ref\n" + rows)

    assert len(result.errors) == MAX_ERRORS


async def test_tenders_are_imported_by_origin_and_ref(db: Database) -> None:
    tenders = (
        "origin;ref;kind;status;title;ags;framework;cpv;available_on;published_on;"
        "estimated_value_eur\n"
        "notice;2025/S 123-456789;construction;published;Wärmenetz Bahnstadt;08221000;true;"
        "45231100|45232140;2025-06-27;2025-06-27;4200000\n"
        "preview;2025/S 123-456789;construction;planned;Wärmenetz Bahnstadt;08221000;;;"
        "2025-02-01;;\n"
    )
    async with db.session() as session:
        result = await import_csv(session, ImportKind.TENDERS, tenders)
    async with db.session() as session:
        stored = {t.origin: t for t in await session.exec(select(Tender))}

    assert result.inserted == 2
    notice = stored[TenderOrigin.NOTICE]
    assert (notice.framework, notice.cpv, notice.estimated_value_eur) == (
        True,
        ["45231100", "45232140"],
        4_200_000,
    )
    assert stored[TenderOrigin.PREVIEW].status is TenderStatus.PLANNED


@pytest.mark.parametrize(
    ("row", "error"),
    [
        ("notice;x;construction;published;T;;false;2025-01-01;", "needs published_on"),
        ("notice;x;construction;planned;T;;true;2025-01-01;", "exclusive to subscribers"),
    ],
)
async def test_a_tender_must_be_consistent(db: Database, row: str, error: str) -> None:
    header = "origin;ref;kind;status;title;ags;exclusive;available_on;published_on\n"
    async with db.session() as session:
        result = await import_csv(session, ImportKind.TENDERS, header + row + "\n")

    assert error in result.errors[0]


async def test_metrics_are_imported_by_municipality_kind_day_and_source(db: Database) -> None:
    metrics = (
        "ags,metric,as_of,available_on,value,source\n"
        "08221000,district_heating_share,2022-05-15,2024-06-01,0.12,zensus-2022\n"
        "08221000,gas_heating_share,2022-05-15,2024-06-01,0.48,zensus-2022\n"
    )
    async with db.session() as session:
        first = await import_csv(session, ImportKind.METRICS, metrics)
    async with db.session() as session:
        again = await import_csv(session, ImportKind.METRICS, metrics.replace("0.12", "0.13"))
    async with db.session() as session:
        stored = {m.metric: m.value for m in await session.exec(select(MunicipalityMetric))}

    assert (first.inserted, again.updated) == (2, 2)
    assert stored == {MetricKind.DISTRICT_HEATING_SHARE: 0.13, MetricKind.GAS_HEATING_SHARE: 0.48}


async def test_a_share_lies_between_zero_and_one(db: Database) -> None:
    metrics = (
        "ags,metric,as_of,available_on,value,source\n"
        "08221000,gas_heating_share,2022-05-15,2024-06-01,48,zensus\n"
    )
    async with db.session() as session:
        result = await import_csv(session, ImportKind.METRICS, metrics)

    assert "between 0 and 1" in result.errors[0]
