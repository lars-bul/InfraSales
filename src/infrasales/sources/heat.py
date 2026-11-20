"""Whether a notice concerns a heat network, and what kind of contract it is.

The CPV codes alone do not tell: a query for district-heating mains (45232140) also returns its
siblings, plain heating works in a building (45232141); a school's notice may list a heat transfer
station (45232142) among twenty codes; and "district heating" (09323000) is heat bought from an
existing network, no construction at all. So a notice counts when its main code or its own words
say heat network, and the rule that decided is kept with it (`relevance`), to be checked and
changed later.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from infrasales.projects.models import TenderKind

# Codes that name a heat network outright.
NETWORK_CODES = frozenset(
    {
        "45232140",  # Bauarbeiten für Fernheizungsleitungen
        "45232142",  # Bauarbeiten für Wärmeübergabestationen
        "45251250",  # Bauarbeiten für Fernheizkraftwerke (Fernheizzentralen)
    }
)
HEAT_SUPPLY_CODE = "09323000"  # Fernwärme: heat bought, not a network built
PIPELINE_CODES = frozenset({"45231000", "45231100", "45232000", "45232100"})  # pipelines in general
# Pipelines of other media (water, gas, sewers): the same firms lay them, often for the same
# utilities. Their awards tell who works where and for whom (`infrasales.forecast.winners`).
PIPELINE_WORKS = ("45231", "45232")
HEATING = "4523214"  # heating works, heat transfer stations: no pipeline of another medium

# Words that name a heat network or its parts (lower case).
NETWORK_WORDS = re.compile(
    r"fernwärme|nahwärme|wärmenetz|wärmeleitung|wärmetrasse|wärmeverbund|fernheiz|"
    r"wärmeverteilnetz|wärmeübergabestation|wärmeauskopplung|energiezentrale|heizzentrale|"
    r"heat network|district heating",
)
# Words for heat bought from a network, or a building's own connection to it: no construction
# opportunity on a network, though they show one exists.
SUPPLY_WORDS = re.compile(
    r"lieferung von (fern|nah)wärme|bezug von (fern|nah)wärme|wärmelieferung|fernwärmeliefer"
)
CONNECTION_WORDS = re.compile(r"hausanschluss|fernwärmeanschluss|anschluss an (das|die) fernwärme")
PLANNING_CODE = re.compile(r"^71")  # architectural, engineering and planning services


@dataclass(frozen=True, slots=True)
class Relevance:
    heat_network: bool
    reason: str  # the rule that decided, e.g. "code:45232140" or "words:title"


def _words(texts: Iterable[str | None]) -> str:
    return " ".join(text.lower() for text in texts if text)


def relevance(  # noqa: PLR0911  # one return per rule, in order
    main_codes: Iterable[str],
    codes: Iterable[str],
    titles: Iterable[str | None],
    descriptions: Iterable[str | None] = (),
) -> Relevance:
    """Whether a notice concerns a heat network, and by which rule.

    From its main CPV codes, all its codes, its own titles (never a title made of a code's name)
    and descriptions; the first rule that applies decides.
    """
    main = {code[:8] for code in main_codes}
    every = {code[:8] for code in codes} | main
    title = _words(titles)
    description = _words(descriptions)
    if SUPPLY_WORDS.search(title) or main == {HEAT_SUPPLY_CODE}:
        return Relevance(heat_network=False, reason="heat-supply")
    if CONNECTION_WORDS.search(title) and not NETWORK_CODES & main:
        return Relevance(heat_network=False, reason="connection")
    if found := sorted(NETWORK_CODES & main):
        return Relevance(heat_network=True, reason=f"code:{found[0]}")
    if NETWORK_WORDS.search(title):
        return Relevance(heat_network=True, reason="words:title")
    if NETWORK_WORDS.search(description) and every & (NETWORK_CODES | PIPELINE_CODES):
        return Relevance(heat_network=True, reason="words:description+code")
    if NETWORK_CODES & every:
        return Relevance(heat_network=False, reason="secondary-code")
    if any(code.startswith(PIPELINE_WORKS) and not code.startswith(HEATING) for code in main):
        return Relevance(heat_network=False, reason="pipeline")
    return Relevance(heat_network=False, reason="no-network")


def kind_of(nature: str | None, codes: Iterable[str]) -> TenderKind:  # noqa: PLR0911  # by nature, then code
    """The kind of contract: from the notice's main nature, else from its codes."""
    code_list = [code[:8] for code in codes]
    if nature == "works":
        return TenderKind.CONSTRUCTION
    if nature == "supplies":
        return TenderKind.SUPPLY
    if nature == "services":
        planning = any(PLANNING_CODE.match(code) for code in code_list)
        return TenderKind.PLANNING if planning else TenderKind.SERVICE
    if any(code.startswith("45") for code in code_list):
        return TenderKind.CONSTRUCTION
    if any(PLANNING_CODE.match(code) for code in code_list):
        return TenderKind.PLANNING
    if any(code.startswith(("42", "43", "44", "31")) for code in code_list):
        return TenderKind.SUPPLY
    return TenderKind.SERVICE
