# ruff: noqa: E501  # a month's export, one row per line
from datetime import date
from pathlib import Path

from infrasales.projects.models import TenderKind, TenderStatus
from infrasales.sources import doe
from tests.sources.support import export

AWARD = "a1"  # an award of a heat network's construction, one lot
CALL = "c1"  # a call for two lots of planning
OTHER = "o1"  # a school: not read


def month(path: Path) -> Path:
    def row(notice: str, **values: str) -> dict[str, str]:
        return {"noticeIdentifier": notice, "noticeVersion": "01", **values}

    return export(
        path,
        {
            "notice.csv": [
                row(AWARD, procedureIdentifier="p-a", noticeType="can-standard", publicationDate="2025-05-30T22:00:00Z"),
                row(CALL, procedureIdentifier="p-c", noticeType="cn-standard", publicationDate="2025-06-02T00:00:00Z"),
                row(OTHER, procedureIdentifier="p-o", noticeType="cn-standard", publicationDate="2025-06-02T00:00:00Z"),
            ],
            "lot.csv": [row(AWARD, lotIdentifier="LOT-0000"), row(CALL, lotIdentifier="LOT-0001"), row(CALL, lotIdentifier="LOT-0002")],
            "purpose.csv": [
                row(AWARD, lotIdentifier="", mainNature="works", title="Fernwärmeerschließung Trasse Ost", estimatedValue="", description=""),
                row(CALL, lotIdentifier="", mainNature="services", title="Planung Wärmenetz Meersburg", estimatedValue="250000", description=""),
                row(OTHER, lotIdentifier="", mainNature="works", title="Neubau Grundschule", estimatedValue="", description=""),
            ],
            "classification.csv": [
                row(AWARD, lotIdentifier="", mainClassificationCode="45231000", additionalClassificationCodes=""),
                row(CALL, lotIdentifier="", mainClassificationCode="71320000", additionalClassificationCodes="71322000"),
                row(OTHER, lotIdentifier="", mainClassificationCode="45214200", additionalClassificationCodes=""),
            ],
            "placeOfPerformance.csv": [
                row(AWARD, lotIdentifier="", placePerformanceCity="02625 Bautzen", placePerformancePostCode="", placePerformanceCountrySubdivision="DED2C"),
                row(CALL, lotIdentifier="", placePerformanceCity="Meersburg", placePerformancePostCode="88709", placePerformanceCountrySubdivision="DE147"),
            ],
            "duration.csv": [row(CALL, lotIdentifier="LOT-0001", durationStartDate="", durationPeriod="2", durationPeriodUnit="YEAR", durationEndDate="")],
            "procedure.csv": [row(AWARD, procedureType="de-open"), row(CALL, procedureType="neg-w-call")],
            "organisation.csv": [
                row(AWARD, organisationName="Energie- und Wasserwerke Bautzen GmbH", organisationRole="buyer", organisationPostCode="02625", organisationCity="Bautzen", organisationCountryCode="DEU", winnerSize="", organisationIdentifier=""),
                row(AWARD, organisationName="Tiefbau Lausitz GmbH", organisationRole="winner", organisationPostCode="02977", organisationCity="Hoyerswerda", organisationCountryCode="DEU", winnerSize="small", organisationIdentifier="DE123"),
            ],
            "procedureLotResult.csv": [row(AWARD, lotIdentifier="LOT-0000", procedureLotResultNumber="0", winnerChosen="selec-w", tenderValueLowest="410000", tenderValueHighest="530000")],
            "receivedSubmissions.csv": [row(AWARD, procedureLotResultNumber="0", receivedSubmissionsCount="4", receivedSubmissionsType="tenders")],
            "contract.csv": [row(AWARD, contractIdentifier="CON-1", winnerDecisionDate="", contractConclusionDate="2025-05-20T00:00:00+02:00", contractFrameworkAgreement="")],
            "additionalInformation.csv": [row(CALL, lotIdentifier="LOT-0001", suitableForSMEs="true")],
            "tender.csv": [row(AWARD, tenderIdentifier="TEN-1", lotIdentifier="LOT-0000", tenderValue="415000")],
        },
    )  # fmt: skip


def test_a_month_gives_its_heat_network_notices_as_lots(tmp_path: Path) -> None:
    lots = doe.lots_of_month(month(tmp_path / "2025-06.csv.zip"))

    assert sorted((lot.notice_id, lot.lot) for lot in lots) == [
        (AWARD, "LOT-0000"),
        (CALL, "LOT-0001"),
        (CALL, "LOT-0002"),
    ]


def test_an_award_gives_winner_offers_values_and_the_place(tmp_path: Path) -> None:
    (award,) = [
        lot for lot in doe.lots_of_month(month(tmp_path / "m.zip")) if lot.notice_id == AWARD
    ]

    assert (award.status, award.kind, award.procedure) == (
        TenderStatus.AWARDED,
        TenderKind.CONSTRUCTION,
        "de-open",
    )
    assert (
        award.offers,
        award.lowest_offer_eur,
        award.highest_offer_eur,
        award.award_value_eur,
    ) == (4, 410000, 530000, 415000)
    assert award.awarded_on == date(2025, 5, 20)
    assert (award.place_city, award.buyer_post_code) == ("02625 Bautzen", "02625")
    assert [(a.winner_name, a.size, a.post_code) for a in award.awards] == [
        ("Tiefbau Lausitz GmbH", "small", "02977")
    ]
    assert award.relevance.reason == "words:title"


def test_a_call_gives_each_lot_with_its_duration_and_suitability(tmp_path: Path) -> None:
    calls = [lot for lot in doe.lots_of_month(month(tmp_path / "m.zip")) if lot.notice_id == CALL]

    assert {(lot.kind, lot.status, lot.lots) for lot in calls} == {
        (TenderKind.PLANNING, TenderStatus.PUBLISHED, 2)
    }
    first = next(lot for lot in calls if lot.lot == "LOT-0001")
    assert (first.duration_months, first.sme_suitable, first.estimated_value_eur) == (
        24,
        True,
        250000,
    )
    assert first.key == "proc:p-c:LOT-0001"
