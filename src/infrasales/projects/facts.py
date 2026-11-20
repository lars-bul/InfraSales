"""What a project states now, computed from its claims and status events (ADR 06 §2)."""

from collections.abc import Iterable

from pydantic import ValidationError

from infrasales.core.models import JSONValue
from infrasales.projects import sectors
from infrasales.projects.models import (
    PHASES,
    Claim,
    ClaimState,
    Origin,
    Phase,
    ProjectEvent,
    Sector,
)

_PRECEDENCE = list(Origin)  # rising: a curator's claim beats a model's


def _rank(claim: Claim) -> tuple[int, float]:
    return _PRECEDENCE.index(claim.origin), claim.created_at.timestamp()


def current_facts(sector: Sector, claims: Iterable[Claim]) -> dict[str, JSONValue]:
    """One value per field of the sector's facts: from the accepted claim that ranks highest.

    The highest origin wins, and the newest claim among those of one origin. A value the
    sector's schema refuses counts as no claim, so the claim below it takes over.
    """
    schema, known = sectors.schema(sector), sectors.fields(sector)
    ranked = sorted(
        (c for c in claims if c.state is ClaimState.ACCEPTED and c.field in known),
        key=_rank,
        reverse=True,
    )
    chosen: dict[str, JSONValue] = {}
    for claim in ranked:
        if claim.field in chosen:
            continue
        try:
            schema.model_validate({claim.field: claim.value})
        except ValidationError:
            continue
        chosen[claim.field] = claim.value
    return schema.model_validate(chosen).model_dump(mode="json", exclude_defaults=True)


def _order(phase: Phase) -> int:
    return PHASES.index(phase) if phase in PHASES else len(PHASES)  # cancelled: after all


def _when(event: ProjectEvent) -> tuple[int, str, float, float]:
    known = event.known_since.timestamp()
    if event.occurred_on is None:
        return 1, "", known, _order(event.phase)
    return 0, event.occurred_on.isoformat(), _order(event.phase), known


def current_phase(events: Iterable[ProjectEvent]) -> Phase | None:
    """The phase of the latest event, by when it happened; None without any.

    Events without a date count after those with one, in the order we learned of them. Between
    events of one date, the later phase wins, and a cancellation after all of them. A project
    taken up again after a cancellation has its later event win.
    """
    latest = max(events, key=_when, default=None)
    return latest.phase if latest else None
