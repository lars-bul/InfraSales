"""Who wins a heat network contract: a conditional logit over the firms active in the market.

Every award notice is a choice: of the firms that could have won (those that won any heat network
contract of the kind within the years before), one did. The model learns what sets the winner
apart from the others, from public data alone:

- distance from the firm's seat to the work (log of 1 + km): local firms win more;
- the firm's earlier wins with the same buyer: incumbents win more;
- its earlier wins in the same Land and in all, and whether it is large.

The chance that firm f wins tender t is exp(x_ft·β) over the sum of exp(x_ct·β) over the firms c
of t's market. A contractor's own chance follows from where it sits and what it won (public awards
under its names, and its own bids): `chance`. The model is fitted by Newton's method with a ridge
penalty, and backtested by time: fitted on awards before a cut, judged on the awards after it
(the winner's rank among the firms; the log-likelihood against a model knowing only distance).
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from infrasales.forecast.features import add_months

FEATURES = ("log_distance", "buyer_wins", "land_wins", "all_wins", "large")
MARKET_YEARS = 4  # a firm is in the market for a tender if it won within this many years before
AHEAD_YEARS = 2  # … or within this many after: most winners win for the first time
L2 = 0.5
MAX_STEPS = 50
HALVINGS = 30
TOLERANCE = 1e-8
EARTH_KM = 6371.0
UNKNOWN_DISTANCE_KM = 300.0  # a firm or a site without coordinates: far, not unknown


def distance_km(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
    """The great-circle distance between two (latitude, longitude) points."""
    if a is None or b is None:
        return UNKNOWN_DISTANCE_KM
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


@dataclass(frozen=True, slots=True)
class Award:
    """An award of the past: which firm won what, where and when."""

    tender: str  # the tender's id
    day: date
    buyer: str  # the buyer's name, normalised
    land: str  # the AGS's first two digits of the work
    place: tuple[float, float] | None  # where the work is
    firm: str  # the winner's name, normalised
    firm_place: tuple[float, float] | None  # where the winner sits
    large: bool
    heat: bool = True  # a heat network's; else another pipeline's, which tells of the market


@dataclass(slots=True)
class Market:
    """The firms and their wins, in time: what a tender's choice set and features come from."""

    awards: list[Award]
    seats: dict[str, tuple[float, float] | None] = field(
        default_factory=dict[str, tuple[float, float] | None]
    )
    large: dict[str, bool] = field(default_factory=dict[str, bool])

    @classmethod
    def of(cls, awards: Iterable[Award]) -> Market:
        ordered = sorted(awards, key=lambda award: (award.day, award.tender, award.firm))
        seats: dict[str, tuple[float, float] | None] = {}
        large: dict[str, bool] = {}
        for award in ordered:
            seats[award.firm] = award.firm_place or seats.get(award.firm)
            large[award.firm] = large.get(award.firm, False) or award.large
        return cls(ordered, seats, large)

    def before(self, day: date) -> list[Award]:
        return [award for award in self.awards if award.day < day]

    def firms(self, day: date, *, ahead: bool = False) -> set[str]:
        """The firms in the market on `day`: those that won within the years before.

        With `ahead`, also those that win within the years after: the firms that existed and
        competed then, newcomers included. A fit must not be told that a winner is the one firm
        without earlier wins, which it would be against a market of past winners only; a firm's
        features still count only what it won before the day.
        """
        since = add_months(day, -12 * MARKET_YEARS)
        until = add_months(day, 12 * AHEAD_YEARS) if ahead else day
        return {
            award.firm
            for award in self.awards
            if award.heat and since <= award.day < until and award.day != day
        }


@dataclass(frozen=True, slots=True)
class Firm:
    """A firm as a choice: where it sits, and what it won before."""

    name: str
    place: tuple[float, float] | None
    large: bool
    wins: Sequence[Award]  # its earlier wins


def features(firm: Firm, buyer: str, land: str, place: tuple[float, float] | None) -> list[float]:
    """A firm's features for a tender of `buyer` in `land` at `place`, in the order of FEATURES."""
    return [
        math.log1p(distance_km(firm.place, place)),
        math.log1p(sum(1 for w in firm.wins if w.buyer == buyer)),
        math.log1p(sum(1 for w in firm.wins if w.land == land)),
        math.log1p(len(firm.wins)),
        1.0 if firm.large else 0.0,
    ]


@dataclass(frozen=True, slots=True)
class Choice:
    """A tender's choice: the features of every firm of its market, the winner first."""

    tender: str
    day: date
    x: np.ndarray  # (firms, features)


def choices(market: Market, awards: Iterable[Award], *, pipelines: bool = True) -> list[Choice]:
    """The choice each award made, against the heat network firms of its day.

    A firm's earlier wins count its pipeline works of other media too (`pipelines`): the
    utility whose water mains it lays knows it.
    """
    wins_by_firm: defaultdict[str, list[Award]] = defaultdict(list)
    for award in market.awards:
        if pipelines or award.heat:
            wins_by_firm[award.firm].append(award)
    result: list[Choice] = []
    for award in awards:
        others = market.firms(award.day, ahead=True) - {award.firm}
        if not others:
            continue
        names = [award.firm, *sorted(others)]
        rows = [
            features(
                Firm(name, market.seats.get(name), market.large.get(name, False),
                     [w for w in wins_by_firm[name] if w.day < award.day]),
                award.buyer, award.land, award.place,
            )
            for name in names
        ]  # fmt: skip
        result.append(Choice(award.tender, award.day, np.array(rows, dtype=np.float64)))
    return result


@dataclass(frozen=True, slots=True)
class WinModel:
    coef: tuple[float, ...]
    features: tuple[str, ...] = FEATURES

    def utility(self, x: Sequence[float]) -> float:
        return sum(c * v for c, v in zip(self.coef, x, strict=True))

    def probabilities(self, rows: np.ndarray) -> np.ndarray:
        utilities = rows @ np.array(self.coef)
        utilities -= utilities.max()
        weights = np.exp(utilities)
        return weights / weights.sum()

    def parameters(self) -> dict[str, float]:
        return dict(zip(self.features, self.coef, strict=True))

    @classmethod
    def from_parameters(cls, parameters: Mapping[str, float]) -> WinModel:
        return cls(tuple(float(parameters.get(name, 0.0)) for name in FEATURES))


def _log_likelihood(
    data: Sequence[Choice], used: Sequence[int], beta: np.ndarray, l2: float
) -> float:
    total = -0.5 * l2 * float(beta @ beta)
    for choice in data:
        u = choice.x[:, used] @ beta
        top = float(u.max())
        total += float(u[0]) - top - math.log(float(np.exp(u - top).sum()))
    return total


def fit(data: Sequence[Choice], l2: float = L2, columns: Sequence[int] | None = None) -> WinModel:
    """The coefficients maximising the penalised conditional likelihood (winner in row 0)."""
    used = list(columns) if columns is not None else list(range(len(FEATURES)))
    beta = np.zeros(len(used))
    current = _log_likelihood(data, used, beta, l2)
    for _ in range(MAX_STEPS):
        gradient = -l2 * beta
        hessian = -l2 * np.eye(len(used))
        for choice in data:
            x = choice.x[:, used]
            u = x @ beta
            p = np.exp(u - u.max())
            p /= p.sum()
            mean = p @ x
            gradient += x[0] - mean
            hessian -= (x * p[:, None]).T @ x - np.outer(mean, mean)
        step = np.linalg.solve(hessian, gradient)
        for _ in range(HALVINGS):  # Newton's step, halved until the likelihood rises
            candidate = beta - step
            value = _log_likelihood(data, used, candidate, l2)
            if value >= current:
                break
            step /= 2
        else:
            break
        beta, current = candidate, value
        if float(np.max(np.abs(step))) < TOLERANCE:
            break
    coef = [0.0] * len(FEATURES)
    for i, column in enumerate(used):
        coef[column] = float(beta[i])
    return WinModel(tuple(coef))


@dataclass(frozen=True, slots=True)
class WinBacktest:
    cut: date
    trained: int
    tested: int
    mean_firms: float  # firms per tender's market
    top1: float  # share of tenders whose winner the model ranked first
    top5: float
    log_likelihood: float  # per tender, of the full model
    log_likelihood_distance: float  # per tender, of a model knowing only distance
    log_likelihood_uniform: float  # per tender, every firm alike
    model: WinModel

    def as_json(self) -> dict[str, object]:
        return {
            "cut": self.cut.isoformat(),
            "trained": self.trained,
            "tested": self.tested,
            "mean_firms": round(self.mean_firms, 1),
            "top1": round(self.top1, 3),
            "top5": round(self.top5, 3),
            "log_likelihood": round(self.log_likelihood, 3),
            "log_likelihood_distance": round(self.log_likelihood_distance, 3),
            "log_likelihood_uniform": round(self.log_likelihood_uniform, 3),
            "coefficients": {k: round(v, 3) for k, v in self.model.parameters().items()},
        }


def backtest(market: Market, cut: date, *, pipelines: bool = True) -> WinBacktest:
    """Fit on the heat network awards before `cut`, judge on those from it on.

    The market (its firms, their seats and earlier wins) comes from every pipeline award; the
    choices learned from and judged are the heat network awards'.
    """
    data = choices(market, [award for award in market.awards if award.heat], pipelines=pipelines)
    train = [c for c in data if c.day < cut]
    test = [c for c in data if c.day >= cut]
    if not train or not test:
        msg = f"{len(train)} awards to train on, {len(test)} to test on"
        raise ValueError(msg)
    model = fit(train)
    distance_only = fit(train, columns=[0])
    ranks: list[int] = []
    ll, ll_distance, ll_uniform = 0.0, 0.0, 0.0
    for choice in test:
        p = model.probabilities(choice.x)
        ranks.append(int((p > p[0]).sum()) + 1)
        ll += math.log(max(float(p[0]), 1e-12))
        ll_distance += math.log(max(float(distance_only.probabilities(choice.x)[0]), 1e-12))
        ll_uniform += -math.log(len(choice.x))
    n = len(test)
    return WinBacktest(
        cut=cut,
        trained=len(train),
        tested=n,
        mean_firms=sum(len(c.x) for c in test) / n,
        top1=sum(1 for r in ranks if r == 1) / n,
        top5=sum(1 for r in ranks if r <= 5) / n,  # noqa: PLR2004
        log_likelihood=ll / n,
        log_likelihood_distance=ll_distance / n,
        log_likelihood_uniform=ll_uniform / n,
        model=model,
    )


def chance(  # noqa: PLR0913  # the model, the market, the firm and the tender
    model: WinModel,
    market: Market,
    contractor: Firm,
    *,
    buyer: str,
    land: str,
    place: tuple[float, float] | None,
    day: date,
) -> float:
    """The chance `contractor` wins a tender of `buyer` at `place` on `day`, if it bids.

    Against the firms of the market on that day, as the model weighs them.
    """
    wins_by_firm: defaultdict[str, list[Award]] = defaultdict(list)
    for award in market.before(day):
        wins_by_firm[award.firm].append(award)
    others = market.firms(day) - {contractor.name}
    rows = [features(contractor, buyer, land, place)] + [
        features(
            Firm(name, market.seats.get(name), market.large.get(name, False), wins_by_firm[name]),
            buyer, land, place,
        )
        for name in sorted(others)
    ]  # fmt: skip
    return float(model.probabilities(np.array(rows, dtype=np.float64))[0])
