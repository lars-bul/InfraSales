"""The learned model: a discrete-time hazard model, fitted as an L2-regularised logistic regression.

Each row is a municipality on a day (a quarter's first); its label says whether a heat network's
construction was put out to tender within the horizon after it. Features are standardised, so
the coefficients compare, and a reason's effect is its coefficient times how far the
municipality lies from the training mean. Fitted by Newton's method: with a few dozen features the
Hessian is small, and it converges in a handful of steps.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from infrasales.core.models import JSONValue
from infrasales.forecast.scoring import Reason, explain, sigmoid

L2 = 1.0  # ridge penalty on the standardised coefficients, not on the intercept
MAX_STEPS = 50
TOLERANCE = 1e-8

type Matrix = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Logistic:
    features: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[float, ...]
    intercept: float
    calibrated = True  # its score is a probability

    def _z(self, x: Sequence[float]) -> list[float]:
        return [(v - m) / s for v, m, s in zip(x, self.mean, self.scale, strict=True)]

    def score(self, x: Sequence[float]) -> float:
        return sigmoid(
            self.intercept + sum(c * z for c, z in zip(self.coef, self._z(x), strict=True))
        )

    def reasons(self, x: Sequence[float], baseline: Sequence[float]) -> list[Reason]:
        """Why `x` scores higher than `baseline`, effects in log-odds of the standardised model."""
        weights = [c / s for c, s in zip(self.coef, self.scale, strict=True)]
        return explain(self.features, weights, x, baseline)

    def parameters(self) -> dict[str, JSONValue]:
        return {
            "mean": list(self.mean),
            "scale": list(self.scale),
            "coef": list(self.coef),
            "intercept": self.intercept,
        }

    @classmethod
    def from_parameters(
        cls, features: Sequence[str], parameters: Mapping[str, JSONValue]
    ) -> Logistic:
        def floats(key: str) -> tuple[float, ...]:
            values = parameters.get(key)
            if not isinstance(values, list) or len(values) != len(features):
                msg = f"stored model has no {key} for its {len(features)} features"
                raise ValueError(msg)
            return tuple(float(v) for v in values)  # pyright: ignore[reportArgumentType]

        intercept = parameters.get("intercept")
        if not isinstance(intercept, (int, float)):
            msg = "stored model has no intercept"
            raise ValueError(msg)  # noqa: TRY004  # a stored model's shape, not a caller's type
        return cls(
            tuple(features), floats("mean"), floats("scale"), floats("coef"), float(intercept)
        )


def fit(x: Matrix, y: NDArray[np.int_], features: Sequence[str], l2: float = L2) -> Logistic:
    """The model fitted to rows `x` and labels `y` (0 or 1)."""
    if x.shape != (len(y), len(features)):
        msg = f"{x.shape} rows do not fit {len(y)} labels and {len(features)} features"
        raise ValueError(msg)
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale == 0] = 1.0  # a constant feature: no effect, no division by zero
    design = np.hstack([np.ones((len(y), 1)), (x - mean) / scale])
    penalty = np.full(design.shape[1], l2)
    penalty[0] = 0.0  # the intercept is not shrunk
    target = y.astype(np.float64)
    weights = np.zeros(design.shape[1])
    for _ in range(MAX_STEPS):
        p = 1 / (1 + np.exp(-(design @ weights)))
        gradient = design.T @ (p - target) + penalty * weights
        hessian = (design * (p * (1 - p))[:, None]).T @ design + np.diag(penalty)
        step = np.linalg.solve(hessian, gradient)
        weights -= step
        if float(np.max(np.abs(step))) < TOLERANCE:
            break
    return Logistic(
        tuple(features),
        tuple(float(v) for v in mean),
        tuple(float(v) for v in scale),
        tuple(float(v) for v in weights[1:]),
        float(weights[0]),
    )
