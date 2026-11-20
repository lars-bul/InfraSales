"""The heuristic: weights set by hand from how heat networks come about, for the start.

Before there is data to learn from, it ranks municipalities by the signals that precede a
construction tender: a planned or earlier planning tender, a council decision, funding, a heat
plan. Its score orders municipalities; it is not a probability (`Heuristic.calibrated`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from infrasales.core.models import JSONValue
from infrasales.forecast.features import FEATURES
from infrasales.forecast.scoring import Reason, explain, sigmoid

VERSION = "heuristic-1"
BIAS = -7.0
# Log-odds per unit of each feature. Counts enter as log(1 + n), shares as 0 to 1.
WEIGHTS: Mapping[str, float] = {
    "log_population": 0.25,
    "log_density": 0.15,
    "large_city": 0.3,
    "plan_deadline_passed": 0.3,
    "heat_plan_started": 0.3,
    "heat_plan_adopted": 0.8,
    "years_since_heat_plan": 0.1,
    "recent_feasibility_study": 1.2,
    "recent_council_decision": 1.4,
    "recent_funding_granted": 1.4,
    "recent_roadmap_published": 0.8,
    "recent_heat_company_founded": 0.8,
    "recent_job_posting": 0.6,
    "recent_heat_source_project": 0.8,
    "recent_budget_allocated": 1.0,
    "gas_concession_ends_soon": 0.4,
    "construction_planned": 2.5,
    "recent_planning_tenders": 1.5,
    "recent_construction_tenders": 0.6,
    "construction_tenders_before": 0.3,
    "framework_ends_soon": 1.5,
    "district_heating_share": 1.0,
    "gas_heating_share": 0.3,
    "oil_heating_share": 0.0,
    "heat_pump_share": -0.3,
    "multi_family_share": 1.0,
    "housing_company_share": 0.8,
    "old_building_share": 0.2,
}


@dataclass(frozen=True, slots=True)
class Heuristic:
    weights: tuple[float, ...]
    bias: float = BIAS
    features: tuple[str, ...] = FEATURES
    calibrated = False  # its score orders; it is no probability

    @classmethod
    def default(cls) -> Heuristic:
        return cls(tuple(WEIGHTS[name] for name in FEATURES))

    @classmethod
    def from_parameters(
        cls, features: Sequence[str], parameters: Mapping[str, JSONValue]
    ) -> Heuristic:
        """The heuristic as stored: its weights by feature name, missing ones as 0."""
        weights = parameters.get("weights")
        stored: Mapping[str, JSONValue] = weights if isinstance(weights, Mapping) else {}
        bias = _number(parameters.get("bias"))
        return cls(
            tuple(_number(stored.get(name)) or 0.0 for name in features),
            BIAS if bias is None else bias,
            tuple(features),
        )

    def parameters(self) -> dict[str, JSONValue]:
        weights: dict[str, JSONValue] = dict(zip(self.features, self.weights, strict=True))
        return {"weights": weights, "bias": self.bias}

    def score(self, x: Sequence[float]) -> float:
        return sigmoid(self.bias + sum(w * v for w, v in zip(self.weights, x, strict=True)))

    def reasons(self, x: Sequence[float], baseline: Sequence[float]) -> list[Reason]:
        return explain(self.features, self.weights, x, baseline)


def _number(value: JSONValue) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
