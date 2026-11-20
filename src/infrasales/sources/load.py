"""Loading the public sources into the database: what `infrasales load <source>` runs.

Each loader reads raw files as they were downloaded (kept unchanged, ADR 06 §10) and writes the
public zone: municipalities, post codes, tenders with their awards, signals. Loading again updates.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from infrasales.projects.models import (
    Municipality,
    MunicipalityMetric,
    PostCode,
    Signal,
    SignalKind,
)
from infrasales.sources import bew, doe, gemeinden, notice_signals, ted, ted_xml, zensus
from infrasales.sources.places import Resolver, read_streets
from infrasales.sources.records import LotRecord
from infrasales.sources.store import Stored, resolver, store

BATCH = 1000


@dataclass(slots=True)
class Loaded:
    new: int = 0
    updated: int = 0
    skipped: int = 0
    awards: int = 0

    def text(self) -> str:
        awards = f", {self.awards} awards" if self.awards else ""
        return f"{self.new} new, {self.updated} updated, {self.skipped} skipped{awards}"


async def load_gemeinden(session: AsyncSession, path: Path) -> Loaded:
    """The Gemeindeverzeichnis: every municipality, updated by its AGS."""
    as_of, records = gemeinden.read(path)
    stored = {m.ags: m for m in await session.exec(select(Municipality))}
    result = Loaded()
    for record in records:
        municipality = stored.get(record.ags)
        if municipality is None:
            municipality = Municipality(ags=record.ags, name=record.name)
            result.new += 1
        else:
            result.updated += 1
        municipality.name = record.name
        municipality.area_km2 = record.area_km2 if record.area_km2 and record.area_km2 > 0 else None
        municipality.population = record.population
        municipality.population_as_of = as_of
        municipality.post_code = record.post_code
        municipality.latitude = record.latitude
        municipality.longitude = record.longitude
        municipality.urbanisation = record.urbanisation
        session.add(municipality)
    return result


async def load_post_codes(session: AsyncSession, path: Path) -> Loaded:
    """OpenPLZ's streets, summed per post code, locality and municipality: replaces what was."""
    await session.exec(delete(PostCode))
    result = Loaded()
    for area in read_streets(path):
        session.add(
            PostCode(
                post_code=area.post_code,
                locality=area.locality[:200],
                municipality_ags=area.ags,
                streets=area.streets,
            )
        )
        result.new += 1
        if result.new % BATCH == 0:
            await session.flush()
    return result


def ted_lots(folder: Path, xml_folder: Path | None) -> list[LotRecord]:
    """The lots of TED's stored search pages; an older notice's read from its XML when stored."""
    records: list[LotRecord] = []
    for notice in ted.read_pages(folder):
        api = ted.lots_of(notice)
        number = str(notice["publication-number"])
        xml_path = xml_folder / f"{number}.xml" if xml_folder else None
        if "procedure-identifier" not in notice and xml_path is not None and xml_path.exists():
            api = ted_xml.merged(
                api, ted_xml.lots_of_xml(number, xml_path.read_text(encoding="utf-8"))
            )
        records.extend(api)
    return records


async def load_lots(session: AsyncSession, lots: Iterable[LotRecord]) -> Loaded:
    places = await resolver(session)
    stored: Stored = await store(session, lots, places)
    return Loaded(stored.tenders_new, stored.tenders_updated, stored.skipped, stored.awards_new)


async def load_ted(session: AsyncSession, folder: Path, xml_folder: Path | None = None) -> Loaded:
    return await load_lots(session, ted_lots(folder, xml_folder))


async def load_doe(session: AsyncSession, paths: Iterable[Path]) -> Loaded:
    """The Datenservice's monthly CSV exports, oldest first.

    Heat network tenders, pipeline awards, and the early steps (heat plans, studies, heat
    sources) as dated signals.
    """
    total = Loaded()
    places = await resolver(session)
    for path in sorted(paths):
        lots = doe.lots_of_month(path, wider=True)
        await store_signals(session, notice_signals.signals_of(lots), places)
        month = await load_lots(session, lots)
        total.new += month.new
        total.updated += month.updated
        total.skipped += month.skipped
        total.awards += month.awards
        await session.flush()
    return total


async def load_bew(session: AsyncSession, path: Path) -> Loaded:
    """BEW Modul 1 projects of Drucksache 20/13968, as feasibility-study signals."""
    places = await resolver(session)
    known = set(places.names)
    refs = {
        s.ref: s
        for s in await session.exec(
            select(Signal).where(col(Signal.ref).startswith("bt:20/13968:"))
        )
    }
    result = Loaded()
    for project in bew.read(path):
        ags = places.resolve(project.post_code, project.town)
        if ags not in known:
            result.skipped += 1
            continue
        ref = f"bt:20/13968:{project.number}"
        signal = refs.get(ref) or Signal(
            kind=SignalKind.FEASIBILITY_STUDY,
            municipality_ags=ags,
            available_on=bew.DRUCKSACHE_20_13968,
            ref=ref,
        )
        result.updated += ref in refs
        result.new += ref not in refs
        signal.municipality_ags = ags
        signal.note = f"BEW Modul 1: {project.text} ({project.grant_eur:,.0f} €)"[:300]
        signal.url = "https://dserver.bundestag.de/btd/20/139/2013968.pdf"
        session.add(signal)
    return result


async def load_ted_signals(session: AsyncSession, folder: Path) -> Loaded:
    """TED's early steps (heat plans, studies, heat sources) as dated signals."""
    lots = [lot for notice in ted.read_pages(folder) for lot in ted.lots_of(notice)]
    return await store_signals(session, notice_signals.signals_of(lots), await resolver(session))


async def store_signals(
    session: AsyncSession, signals: Iterable[notice_signals.NoticeSignal], places: Resolver
) -> Loaded:
    """Signals of the notices, at their municipality; loading again updates them."""
    wanted = list(signals)
    refs = [signal.ref for signal in wanted]
    stored: dict[str, Signal] = {}
    for start in range(0, len(refs), BATCH):
        statement = select(Signal).where(col(Signal.ref).in_(refs[start : start + BATCH]))
        stored.update({s.ref: s for s in await session.exec(statement)})
    known = set(places.names)
    result = Loaded()
    for found in wanted:
        ags = (
            places.resolve(found.post_code, found.city, found.nuts)
            or places.resolve(found.buyer_post_code, found.buyer_city, found.nuts)
            or places.resolve_buyer(found.buyer, found.nuts)
        )
        if ags not in known:
            result.skipped += 1
            continue
        signal = stored.get(found.ref) or Signal(
            kind=found.kind, municipality_ags=ags, available_on=found.available_on, ref=found.ref
        )
        result.updated += found.ref in stored
        result.new += found.ref not in stored
        signal.kind = found.kind
        signal.municipality_ags = ags
        signal.available_on = found.available_on
        signal.occurred_on = found.available_on
        signal.note = found.title[:300]
        signal.url = found.url
        session.add(signal)
    await session.flush()
    return result


async def load_zensus(session: AsyncSession, folder: Path) -> Loaded:
    """The 2022 census by municipality, as metrics of the census day (`sources.zensus`)."""
    known = set(await session.exec(select(Municipality.ags)))
    stored = {
        (m.municipality_ags, m.metric): m
        for m in await session.exec(
            select(MunicipalityMetric).where(col(MunicipalityMetric.source) == zensus.SOURCE)
        )
    }
    result = Loaded()
    for figure in zensus.read_pages(folder):
        if figure.ags not in known:
            result.skipped += 1
            continue
        metric = stored.get((figure.ags, figure.metric)) or MunicipalityMetric(
            municipality_ags=figure.ags,
            metric=figure.metric,
            as_of=zensus.CENSUS_DAY,
            available_on=zensus.CENSUS_DAY,
            value=figure.value,
            source=zensus.SOURCE,
        )
        result.updated += (figure.ags, figure.metric) in stored
        result.new += (figure.ags, figure.metric) not in stored
        metric.value = figure.value
        session.add(metric)
        if result.new % BATCH == 0:
            await session.flush()
    return result
