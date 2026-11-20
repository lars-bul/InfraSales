import uuid
from datetime import UTC, date, datetime, timedelta

from infrasales.core.models import JSONValue
from infrasales.projects.facts import current_facts, current_phase
from infrasales.projects.models import Claim, ClaimState, Origin, Phase, ProjectEvent, Sector

PROJECT = uuid.uuid7()
T0 = datetime(2026, 1, 5, tzinfo=UTC)


def claim(
    field: str,
    value: JSONValue,
    *,
    origin: Origin = Origin.MODEL,
    state: ClaimState = ClaimState.ACCEPTED,
    days: int = 0,
) -> Claim:
    return Claim(
        project_id=PROJECT,
        field=field,
        value=value,
        origin=origin,
        state=state,
        created_at=T0 + timedelta(days=days),
    )


def event(phase: Phase, occurred_on: date | None, *, days: int = 0) -> ProjectEvent:
    return ProjectEvent(
        project_id=PROJECT,
        phase=phase,
        occurred_on=occurred_on,
        known_since=T0 + timedelta(days=days),
        claim_id=uuid.uuid7(),
    )


def test_facts_come_from_accepted_claims_only() -> None:
    claims = [
        claim("trench_length_km", 4.2),
        claim("connections", 900, state=ClaimState.PENDING),
        claim("capacity_mw", 12.0, state=ClaimState.REJECTED),
    ]

    assert current_facts(Sector.HEAT_NETWORK, claims) == {"trench_length_km": 4.2}


def test_a_curators_claim_beats_a_models_and_the_newest_wins_within_an_origin() -> None:
    claims = [
        claim("trench_length_km", 3.0, days=0),
        claim("trench_length_km", 3.5, days=2),
        claim("connections", 800, origin=Origin.CURATOR, days=0),
        claim("connections", 950, days=5),
    ]

    assert current_facts(Sector.HEAT_NETWORK, claims) == {
        "trench_length_km": 3.5,
        "connections": 800,
    }


def test_a_value_the_sector_refuses_counts_as_no_claim() -> None:
    claims = [
        claim("trench_length_km", 2.0, days=0),
        claim("trench_length_km", -1, days=3),  # not a length
        claim("heat_sources", ["heat_pump", "solar_thermal"]),
        claim("pipe_material", "steel"),  # no field of heat networks
    ]

    assert current_facts(Sector.HEAT_NETWORK, claims) == {
        "trench_length_km": 2.0,
        "heat_sources": ["heat_pump", "solar_thermal"],
    }


def test_no_events_no_phase() -> None:
    assert current_phase([]) is None


def test_the_phase_is_that_of_the_latest_event_by_when_it_happened() -> None:
    events = [
        event(Phase.DECISION, date(2026, 3, 1), days=0),
        event(Phase.STUDY, date(2025, 6, 1), days=10),  # learned later, happened earlier
    ]

    assert current_phase(events) is Phase.DECISION


def test_on_one_day_the_later_phase_wins_and_undated_events_count_last() -> None:
    same_day = [event(Phase.FUNDING, date(2026, 3, 1)), event(Phase.DECISION, date(2026, 3, 1))]

    assert current_phase(same_day) is Phase.FUNDING
    assert current_phase([*same_day, event(Phase.TENDER, None)]) is Phase.TENDER


def test_a_cancellation_ends_the_project_until_a_later_event_takes_it_up_again() -> None:
    cancelled = [
        event(Phase.DECISION, date(2026, 3, 1)),
        event(Phase.CANCELLED, date(2026, 3, 1)),
    ]

    assert current_phase(cancelled) is Phase.CANCELLED
    assert current_phase([*cancelled, event(Phase.STUDY, date(2027, 1, 10))]) is Phase.STUDY
