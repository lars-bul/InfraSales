"""Scores from features, and the reasons for them: shared by the heuristic and the learned model.

A score is a weighted sum through the logistic function. Its reasons are the features that lift
it most above a typical municipality's (the baseline), so a large city does not show "population"
as its reason every time.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from infrasales.core.models import JSONValue

TOP_REASONS = 3


@dataclass(frozen=True, slots=True)
class Reason:
    feature: str
    value: float  # the feature's value for this municipality
    effect: float  # how much it lifts the score's log-odds above the baseline

    def as_json(self) -> dict[str, JSONValue]:
        return {
            "feature": self.feature,
            "value": round(self.value, 4),
            "effect": round(self.effect, 4),
        }


class Scorer(Protocol):
    @property
    def features(self) -> tuple[str, ...]: ...

    def score(self, x: Sequence[float]) -> float:
        """The score of a municipality with features `x`, between 0 and 1."""
        ...

    def reasons(self, x: Sequence[float], baseline: Sequence[float]) -> list[Reason]:
        """Why `x` scores higher than `baseline`, the strongest reasons first."""
        ...


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    exp = math.exp(z)
    return exp / (1 + exp)


def explain(
    names: Sequence[str],
    weights: Sequence[float],
    x: Sequence[float],
    baseline: Sequence[float],
    top: int = TOP_REASONS,
) -> list[Reason]:
    """The features that lift the score above the baseline most, at most `top` of them."""
    effects = [
        Reason(name, value, weight * (value - base))
        for name, weight, value, base in zip(names, weights, x, baseline, strict=True)
    ]
    lifting = [reason for reason in effects if reason.effect > 0]
    return sorted(lifting, key=lambda reason: reason.effect, reverse=True)[:top]


def mean_vector(rows: Sequence[Sequence[float]], width: int) -> list[float]:
    """The column means of `rows`: the typical municipality reasons are measured against."""
    if not rows:
        return [0.0] * width
    return [sum(column) / len(rows) for column in zip(*rows, strict=True)]
