from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.projects.models import (
    MetricKind,
    Municipality,
    MunicipalityMetric,
    PostCode,
    Signal,
    SignalKind,
    Tender,
)
from infrasales.sources import load
from infrasales.sources.bew import FundedProject
from infrasales.sources.notice_signals import NoticeSignal
from infrasales.sources.store import resolver
from tests.sources.support import gemeindeverzeichnis, streets
from tests.sources.test_doe import month
from tests.sources.test_zensus import page

pytestmark = pytest.mark.anyio
FIXTURES = Path(__file__).parent / "fixtures" / "ted"


@pytest.fixture
async def db(database_url: str, tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(database_url)
    async with db.session() as session:
        await load.load_gemeinden(session, gemeindeverzeichnis(tmp_path / "gv.xlsx"))
        path = streets(
            tmp_path / "streets.csv",
            [
                ("Hauptstr.", "69117", "Heidelberg", "08221000"),
                ("Weg", "02625", "Bautzen", "14625020"),
            ],
        )
        await load.load_post_codes(session, path)
        session.add(Municipality(ags="14625020", name="Bautzen, Stadt"))
    yield db
    await db.dispose()


async def test_the_directory_and_post_codes_load_and_load_again(
    db: Database, tmp_path: Path
) -> None:
    async with db.session() as session:
        again = await load.load_gemeinden(session, gemeindeverzeichnis(tmp_path / "gv2.xlsx"))
        heidelberg = (
            await session.exec(select(Municipality).where(Municipality.ags == "08221000"))
        ).one()
        codes = (await session.exec(select(PostCode))).all()

    assert again.text() == "0 new, 3 updated, 0 skipped"
    assert (heidelberg.post_code, heidelberg.latitude, heidelberg.urbanisation) == (
        "69117",
        49.40768,
        1,
    )
    assert len(codes) == 2


async def test_teds_pages_and_a_months_export_load_as_tenders(db: Database, tmp_path: Path) -> None:
    async with db.session() as session:
        from_ted = await load.load_ted(session, FIXTURES, FIXTURES)
        from_doe = await load.load_doe(session, [month(tmp_path / "2025-06.csv.zip")])
        tenders = (await session.exec(select(Tender))).all()

    assert from_ted.new >= 1
    assert from_doe.text() == "3 new, 0 updated, 0 skipped, 1 awards"
    bautzen = next(t for t in tenders if t.title.startswith("Fernwärmeerschließung"))
    assert bautzen.municipality_ags == "14625020"


async def test_bew_projects_load_as_feasibility_signals_of_their_municipality(
    db: Database, tmp_path: Path
) -> None:
    rows = [
        FundedProject(
            1,
            "Stadtwerke Heidelberg Wärmenetz Süd",
            "69117",
            "Heidelberg",
            "Baden-Württemberg",
            100.0,
        ),
        FundedProject(2, "Irgendwer", "99999", "Nirgendwo", "Bayern", 5.0),
    ]
    with patch.object(load.bew, "read", return_value=rows):
        async with db.session() as session:
            result = await load.load_bew(session, tmp_path / "unused.pdf")
        async with db.session() as session:
            again = await load.load_bew(session, tmp_path / "unused.pdf")
            (signal,) = (await session.exec(select(Signal))).all()

    assert (result.new, result.skipped, again.updated) == (1, 1, 1)
    assert (signal.kind, signal.municipality_ags, signal.ref) == (
        SignalKind.FEASIBILITY_STUDY,
        "08221000",
        "bt:20/13968:1",
    )
    assert signal.note.startswith("BEW Modul 1: Stadtwerke Heidelberg")


async def test_the_census_loads_as_metrics_of_its_day(db: Database, tmp_path: Path) -> None:
    rows = [
        {
            "AGS": "08221000",
            "GEBAEUDEART_SYS_1": 100,
            "ENERGIETRAEGER__1": 60,
            "ENERGIETRAEGER__8": 30,
        }
    ]
    folder = page(tmp_path / "z", [*rows, {"AGS": "99999999", "ENERGIETRAEGER__1": 1}])
    async with db.session() as session:
        first = await load.load_zensus(session, folder)
    async with db.session() as session:
        again = await load.load_zensus(session, folder)
        metrics = {m.metric: m for m in (await session.exec(select(MunicipalityMetric))).all()}

    assert (first.skipped, again.new) == (5, 0)  # the unknown municipality's five figures
    assert metrics[MetricKind.DISTRICT_HEATING_SHARE].value == 0.3
    assert metrics[MetricKind.DISTRICT_HEATING_SHARE].available_on.isoformat() == "2022-05-15"


async def test_notice_signals_are_stored_at_their_municipality(db: Database) -> None:
    def found(ref: str, post_code: str | None, buyer: str | None) -> NoticeSignal:
        return NoticeSignal(
            kind=SignalKind.HEAT_PLAN_STARTED,
            ref=ref,
            available_on=date(2024, 3, 1),
            title="Kommunale Wärmeplanung",
            url=None,
            post_code=post_code,
            city=None,
            buyer=buyer,
            buyer_post_code=None,
            buyer_city=None,
            nuts=None,
        )

    async with db.session() as session:
        places = await resolver(session)
        result = await load.store_signals(
            session,
            [found("a", "69117", None), found("b", None, "Stadt Bautzen"), found("c", None, None)],
            places,
        )
        signals = {s.ref: s.municipality_ags for s in (await session.exec(select(Signal))).all()}

    assert (result.new, result.skipped) == (2, 1)
    assert signals == {"a": "08221000", "b": "14625020"}


async def test_teds_pages_give_their_early_steps_as_signals(db: Database) -> None:
    async with db.session() as session:
        result = await load.load_ted_signals(session, FIXTURES)

    assert result.new == 0  # the fixtures hold no heat plan, study or heat source
