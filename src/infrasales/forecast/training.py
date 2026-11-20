"""Training and backtesting on the public history: what a forecast could have known, and what came.

Rows are snapshots: a municipality on the first day of a quarter, with the features of that day
(`features.features`) and whether a heat network's construction was put out to tender within the
horizon after it (`features.label`). A snapshot's label is only known once its horizon has passed,
so training uses snapshots whose horizon ends by the last day observed.

The backtest splits by time, never by municipality: it trains on the snapshots whose horizon ended
before the cut and tests on those after it, as the model would have been used. A cut leaves both
sides needing positives; without enough of them the model cannot be learned (`NotEnoughDataError`):
the hard limit where only more history helps, not more code.
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from infrasales.core.models import JSONValue
from infrasales.forecast import evaluation, logistic
from infrasales.forecast.features import (
    FEATURES,
    HORIZON_MONTHS,
    History,
    add_months,
    features,
    label,
    months_between,
    next_tender,
    quarters,
)
from infrasales.forecast.heuristic import Heuristic
from infrasales.forecast.scoring import Scorer

MIN_POSITIVES = 30  # on each side of the backtest's cut: fewer, and its measures are noise
TOP_K = (10, 50)  # what a sales team works through: the top of the list
HISTORY_YEARS = 8  # how far back snapshots start, at most


class NotEnoughDataError(Exception):
    """Too few tenders in the history to learn a model from, or to judge it."""

    def __init__(self, positives: int, needed: int) -> None:
        super().__init__(f"{positives} positive snapshots, {needed} needed")
        self.positives = positives
        self.needed = needed


@dataclass(frozen=True, slots=True)
class Snapshot:
    ags: str
    as_of: date


@dataclass(frozen=True, slots=True)
class Dataset:
    rows: tuple[Snapshot, ...]
    x: logistic.Matrix
    y: np.ndarray[tuple[int], np.dtype[np.int_]]

    @property
    def positives(self) -> int:
        return int(self.y.sum())

    def where(self, keep: Sequence[bool]) -> Dataset:
        mask = np.array(keep, dtype=bool)
        rows = tuple(row for row, kept in zip(self.rows, keep, strict=True) if kept)
        return Dataset(rows, self.x[mask], self.y[mask])


def observed_until(history: History) -> date | None:
    """The last day the history covers: labels up to it are known."""
    return history.last_day()


def snapshot_days(history: History, horizon_months: int, since: date | None = None) -> list[date]:
    """The quarters whose label is known: from the history's start to a horizon before its end."""
    last = observed_until(history)
    if last is None:
        return []
    first_fact = min(
        (
            fact.available_on
            for facts in (*history.signals.values(), *history.tenders.values())
            for fact in facts
        ),
        default=last,
    )
    first = max(first_fact, add_months(last, -12 * HISTORY_YEARS), since or first_fact)
    return quarters(first, add_months(last, -horizon_months))


def dataset(history: History, days: Sequence[date], horizon_months: int) -> Dataset:
    """Every municipality on every day of `days`, with its features and label."""
    rows = tuple(Snapshot(ags, day) for day in days for ags in sorted(history.places))
    x = np.array([features(history, row.ags, row.as_of) for row in rows], dtype=np.float64).reshape(
        len(rows), len(FEATURES)
    )
    y = np.array(
        [label(history, row.ags, row.as_of, horizon_months) for row in rows], dtype=np.int_
    )
    return Dataset(rows, x, y)


def measure(
    scorer: Scorer, data: Dataset, history: History, *, calibrated: bool
) -> dict[str, JSONValue]:
    """How `scorer` ranks the rows of `data`: per day, then averaged, as a list is used per day."""
    scores = [scorer.score(row) for row in data.x.tolist()]
    labels = [int(v) for v in data.y.tolist()]
    by_day: dict[date, list[int]] = {}
    for i, row in enumerate(data.rows):
        by_day.setdefault(row.as_of, []).append(i)
    metrics: dict[str, JSONValue] = {
        "rows": len(labels),
        "positives": sum(labels),
        "roc_auc": _round(evaluation.roc_auc(labels, scores)),
        "average_precision": _round(evaluation.average_precision(labels, scores)),
        "brier": _round(evaluation.brier(labels, scores)) if calibrated else None,
    }
    for k in TOP_K:
        per_day = [
            evaluation.precision_at([labels[i] for i in rows], [scores[i] for i in rows], k)
            for rows in by_day.values()
        ]
        known = [p for p in per_day if p is not None]
        metrics[f"precision_at_{k}"] = _round(statistics.fmean(known)) if known else None
    metrics["lead_months_median"] = _lead_time(data, scores, labels, by_day, history)
    return metrics


def _lead_time(
    data: Dataset,
    scores: Sequence[float],
    labels: Sequence[int],
    by_day: dict[date, list[int]],
    history: History,
) -> float | None:
    """How many months before its tender a hit in the top of the list was there: the head start."""
    leads: list[float] = []
    for rows in by_day.values():
        top = sorted(rows, key=lambda i: scores[i], reverse=True)[: max(TOP_K)]
        for i in top:
            if labels[i]:
                row = data.rows[i]
                tender = next_tender(history, row.ags, row.as_of)
                if tender is not None:
                    leads.append(months_between(row.as_of, tender))
    return round(statistics.median(leads), 1) if leads else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


@dataclass(frozen=True, slots=True)
class Backtest:
    cut: date  # trained on snapshots whose horizon ended by it, tested on those from it on
    heuristic: dict[str, JSONValue]
    learned: dict[str, JSONValue]

    def as_json(self) -> dict[str, JSONValue]:
        return {"cut": self.cut.isoformat(), "heuristic": self.heuristic, "learned": self.learned}


def backtest(  # noqa: PLR0913  # what is learned from, and what is left out
    history: History,
    horizon_months: int = HORIZON_MONTHS,
    min_positives: int = MIN_POSITIVES,
    l2: float = logistic.L2,
    *,
    drop: Sequence[str] = (),
    since: date | None = None,
) -> Backtest:
    """The heuristic and a learned model on the latest snapshots, the model learned on earlier ones.

    The cut is the latest day leaving `min_positives` positive snapshots to test on; training uses
    only snapshots whose horizon ended by the cut, so no label it learns from was unknown then.
    Raises `NotEnoughDataError` when either side has too few.
    """
    days = snapshot_days(history, horizon_months, since)
    data = without(dataset(history, days, horizon_months), drop)
    if data.positives < 2 * min_positives:
        raise NotEnoughDataError(data.positives, 2 * min_positives)
    cut = _cut(data, days, min_positives)
    train = data.where([add_months(row.as_of, horizon_months) <= cut for row in data.rows])
    test = data.where([row.as_of >= cut for row in data.rows])
    if train.positives < min_positives:
        raise NotEnoughDataError(train.positives, min_positives)
    model = logistic.fit(train.x, train.y, FEATURES, l2)
    new = test.where(
        [not row[FEATURES.index("construction_tenders_before")] for row in test.x.tolist()]
    )
    heuristic = measure(Heuristic.default(), test, history, calibrated=False)
    learned = measure(model, test, history, calibrated=True)
    if new.rows:  # the municipalities that never tendered construction: where a lead is news
        heuristic["new"] = measure(Heuristic.default(), new, history, calibrated=False)
        learned["new"] = measure(model, new, history, calibrated=True)
    return Backtest(cut, heuristic, learned)


def without(data: Dataset, names: Sequence[str]) -> Dataset:
    """The dataset with the named features held at zero: what they add, by leaving them out."""
    if not names:
        return data
    x = data.x.copy()
    for name in names:
        x[:, FEATURES.index(name)] = 0.0
    return Dataset(data.rows, x, data.y)


def _cut(data: Dataset, days: Sequence[date], min_positives: int) -> date:
    """The latest snapshot day from which on at least `min_positives` positives remain."""
    positives_from = 0
    for day in reversed(days):
        positives_from += sum(
            int(y) for row, y in zip(data.rows, data.y.tolist(), strict=True) if row.as_of == day
        )
        if positives_from >= min_positives:
            return day
    return days[0]


def train(
    history: History,
    horizon_months: int = HORIZON_MONTHS,
    min_positives: int = MIN_POSITIVES,
    l2: float = logistic.L2,
    *,
    since: date | None = None,
) -> tuple[logistic.Logistic, date]:
    """A model learned on every snapshot whose label is known, and the last day they cover."""
    days = snapshot_days(history, horizon_months, since)
    data = dataset(history, days, horizon_months)
    if data.positives < min_positives:
        raise NotEnoughDataError(data.positives, min_positives)
    last = observed_until(history)
    assert last is not None  # there are positives, so there are facts  # noqa: S101
    return logistic.fit(data.x, data.y, FEATURES, l2), last
