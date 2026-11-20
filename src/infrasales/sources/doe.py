"""The Datenservice Öffentlicher Einkauf (oeffentlichevergabe.de): German notices, as lots.

Its open data API (`/api/notice-exports?pubMonth=YYYY-MM&format=csv.zip`, public domain, no login)
exports a month's notices as CSV tables keyed by notice and version: notices, lots, purposes
(titles, natures, values), classifications (CPV), places, durations, procedures, organisations
(buyers, winners), results, received submissions, contracts. It has what TED has, and the national
procedures below the EU thresholds (VOB/A, UVgO) on top: most municipal civil works.

A month holds about 27,000 notices; only those whose titles or main codes may concern a heat
network are read in full (`infrasales.sources.heat` decides). Winners are listed per notice, not per
lot: they are kept for a notice with one awarded lot.
"""

import csv
import io
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from infrasales.projects.models import TenderStatus
from infrasales.sources.heat import NETWORK_CODES, NETWORK_WORDS, PIPELINE_WORKS, kind_of, relevance
from infrasales.sources.notice_signals import kind_of as signal_kind
from infrasales.sources.records import AwardRecord, LotRecord, months, status_of

EXPORT_URL = "https://oeffentlichevergabe.de/api/notice-exports?pubMonth={month}&format=csv.zip"
NOTICE_URL = "https://oeffentlichevergabe.de/ui/de/search/details?noticeId={notice}"
CODES = re.compile(r"\d{8}")
FIELD_LIMIT = 64 * 1024 * 1024  # some descriptions run past csv's default of 128 KiB

type Row = dict[str, str]
type Key = tuple[str, str]  # notice id, version


def _rows(archive: zipfile.ZipFile, name: str) -> Iterator[Row]:
    if name not in archive.namelist():
        return
    csv.field_size_limit(FIELD_LIMIT)
    with archive.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))


def _day(text: str | None) -> date | None:
    return date.fromisoformat(text[:10]) if text and len(text) >= 10 else None  # noqa: PLR2004


def _amount(text: str | None) -> int | None:
    try:
        value = float(text or "")
    except ValueError:
        return None
    return round(value) if value >= 1 else None


def _codes(row: Row) -> list[str]:
    return CODES.findall(
        f"{row.get('mainClassificationCode', '')} {row.get('additionalClassificationCodes', '')}"
    )


def candidates(archive: zipfile.ZipFile) -> set[str]:
    """The notices whose titles or codes may concern a heat network."""
    found: set[str] = set()
    for row in _rows(archive, "purpose.csv"):
        if NETWORK_WORDS.search((row.get("title") or "").lower()):
            found.add(row["noticeIdentifier"])
    for row in _rows(archive, "classification.csv"):
        if set(_codes(row)) & NETWORK_CODES:
            found.add(row["noticeIdentifier"])
    return found


def wider_candidates(archive: zipfile.ZipFile) -> set[str]:
    """The notices of early steps (heat plans, studies, heat sources) and pipeline awards."""
    found: set[str] = set()
    for row in _rows(archive, "purpose.csv"):
        if signal_kind(row.get("title") or "") is not None:
            found.add(row["noticeIdentifier"])
    results = {
        r["noticeIdentifier"] for r in _rows(archive, "notice.csv") if r.get("formType") == "result"
    }
    for row in _rows(archive, "classification.csv"):
        if row["noticeIdentifier"] in results and (
            row.get("mainClassificationCode") or ""
        ).startswith(PIPELINE_WORKS):
            found.add(row["noticeIdentifier"])
    return found


def _latest(rows: Iterator[Row], wanted: set[str]) -> dict[Key, list[Row]]:
    grouped: defaultdict[Key, list[Row]] = defaultdict(list)
    for row in rows:
        if row["noticeIdentifier"] in wanted:
            grouped[row["noticeIdentifier"], row["noticeVersion"]].append(row)
    return grouped


def lots_of_month(
    path: Path, *, wider: bool = False
) -> list[LotRecord]:  # the tables joined per notice
    """The heat network candidates of a month's export, as lots."""
    with zipfile.ZipFile(path) as archive:
        extra: set[str] = wider_candidates(archive) if wider else set()
        wanted = candidates(archive) | extra
        notices = _latest(_rows(archive, "notice.csv"), wanted)
        latest: dict[str, Key] = {}
        for notice_id, version in notices:
            if notice_id not in latest or version > latest[notice_id][1]:
                latest[notice_id] = (notice_id, version)
        keep = set(latest.values())
        tables = {
            name: {
                k: v
                for k, v in _latest(_rows(archive, f"{name}.csv"), wanted).items()
                if k in keep
            }
            for name in (
                "lot", "purpose", "classification", "placeOfPerformance", "duration", "procedure",
                "organisation", "procedureLotResult", "receivedSubmissions", "contract",
                "additionalInformation", "tender",
            )
        }  # fmt: skip
    records: list[LotRecord] = []
    for key in sorted(keep):
        notice = notices[key][0]
        records.extend(
            _lots(key, notice, {name: table.get(key, []) for name, table in tables.items()})
        )
    return records


def _by_lot(rows: list[Row]) -> dict[str, Row]:
    return {row.get("lotIdentifier", ""): row for row in rows}


def _lots(key: Key, notice: Row, tables: dict[str, list[Row]]) -> list[LotRecord]:
    published = _day(notice.get("publicationDate"))
    notice_type = notice.get("noticeType") or ""
    results = _by_lot(tables["procedureLotResult"])
    any_winner = any(r.get("winnerChosen") == "selec-w" for r in results.values())
    status = status_of(notice_type, awarded=any_winner or not results)
    if status is None or published is None:
        return []
    lot_ids = [row["lotIdentifier"] for row in tables["lot"]] or [""]
    purposes = _by_lot(tables["purpose"])
    classes = _by_lot(tables["classification"])
    places = _by_lot(tables["placeOfPerformance"])
    durations = _by_lot(tables["duration"])
    extras = _by_lot(tables["additionalInformation"])
    procedure = tables["procedure"][0] if tables["procedure"] else {}
    buyers = [o for o in tables["organisation"] if o.get("organisationRole") == "buyer"]
    buyer = buyers[0] if buyers else {}
    winners = [
        o for o in tables["organisation"] if o.get("organisationRole") in {"winner", "tenderer"}
    ]
    awarded_lots = [lot for lot, r in results.items() if r.get("winnerChosen") == "selec-w"]
    offers = {
        r["procedureLotResultNumber"]: int(r["receivedSubmissionsCount"])
        for r in tables["receivedSubmissions"]
        if r.get("receivedSubmissionsType") == "tenders"
        and r.get("receivedSubmissionsCount", "").isdigit()
    }
    values = {r.get("lotIdentifier", ""): _amount(r.get("tenderValue")) for r in tables["tender"]}
    contract = tables["contract"][0] if tables["contract"] else {}
    procedure_purpose = purposes.get("", {})
    procedure_class = classes.get("", {})
    procedure_place = places.get("", {})
    records: list[LotRecord] = []
    for lot in lot_ids:
        purpose = purposes.get(lot) or procedure_purpose
        cls = classes.get(lot) or procedure_class
        place = places.get(lot) or procedure_place
        result = results.get(lot, {})
        codes = tuple(dict.fromkeys(_codes(cls) + _codes(procedure_class)))
        main = CODES.findall(cls.get("mainClassificationCode", ""))[:1]
        title = (purpose.get("title") or procedure_purpose.get("title") or key[0])[:500]
        description = purpose.get("description") or procedure_purpose.get("description")
        duration = durations.get(lot, {})
        lot_status = status
        if status is TenderStatus.AWARDED and result and result.get("winnerChosen") != "selec-w":
            lot_status = TenderStatus.CANCELLED
        lot_winners = (
            winners if lot_status is TenderStatus.AWARDED and len(awarded_lots) <= 1 else []
        )
        records.append(
            LotRecord(
                source="doe",
                notice_id=key[0],
                notice_type=notice_type,
                procedure_ref=notice.get("procedureIdentifier") or None,
                lot=lot or None,
                title=title,
                kind=kind_of(
                    purpose.get("mainNature") or procedure_purpose.get("mainNature"), main or codes
                ),
                status=lot_status,
                published_on=published,
                relevance=relevance(
                    main,
                    codes,
                    [purpose.get("title"), procedure_purpose.get("title")],
                    [description],
                ),
                cpv=codes,
                description=description,
                buyer_name=buyer.get("organisationName") or None,
                buyer_post_code=buyer.get("organisationPostCode") or None,
                buyer_city=buyer.get("organisationCity") or None,
                place_post_code=place.get("placePerformancePostCode") or None,
                place_city=place.get("placePerformanceCity") or None,
                place_nuts=place.get("placePerformanceCountrySubdivision") or None,
                procedure=procedure.get("procedureType") or None,
                lots=len(lot_ids) if lot_ids != [""] else None,
                framework=bool(
                    result.get("frameworkMaximumValue") or result.get("frameworkEstimatedValue")
                )
                or contract.get("contractFrameworkAgreement") == "true",
                duration_months=_months(duration),
                sme_suitable=_flag(extras.get(lot, {}).get("suitableForSMEs")),
                awarded_on=_day(contract.get("winnerDecisionDate"))
                or _day(contract.get("contractConclusionDate"))
                if lot_status is TenderStatus.AWARDED
                else None,
                contract_end_on=_day(duration.get("durationEndDate")),
                estimated_value_eur=_amount(purpose.get("estimatedValue")),
                award_value_eur=values.get(lot) if lot_status is TenderStatus.AWARDED else None,
                lowest_offer_eur=_amount(result.get("tenderValueLowest")),
                highest_offer_eur=_amount(result.get("tenderValueHighest")),
                offers=offers.get(result.get("procedureLotResultNumber", "")),
                awards=tuple(
                    AwardRecord(
                        winner_name=w["organisationName"].strip(),
                        winner_identifier=w.get("organisationIdentifier") or None,
                        post_code=w.get("organisationPostCode") or None,
                        city=w.get("organisationCity") or None,
                        country=w.get("organisationCountryCode") or None,
                        size=w.get("winnerSize") or None,
                    )
                    for w in lot_winners
                    if w.get("organisationName")
                ),
                url=NOTICE_URL.format(notice=key[0]),
            )
        )
    return records


def _months(duration: Row) -> float | None:
    period = duration.get("durationPeriod")
    if period:
        try:
            return months(float(period), duration.get("durationPeriodUnit"))
        except ValueError:
            return None
    start, end = _day(duration.get("durationStartDate")), _day(duration.get("durationEndDate"))
    if start and end and end >= start:
        return round((end - start).days / 30.4375, 2)
    return None


def _flag(text: str | None) -> bool | None:
    if text in {"true", "false"}:
        return text == "true"
    return None
