import pytest
from pydantic import ValidationError

from infrasales.forecast.models import ForecastModel, ModelKind
from infrasales.forecast.schemas import ModelSummary, RankingQuery


def test_a_region_is_an_ags_prefix() -> None:
    assert RankingQuery(region="08").region == "08"
    assert RankingQuery().region == ""
    with pytest.raises(ValidationError):
        RankingQuery(region="Baden-Württemberg")
    with pytest.raises(ValidationError):
        RankingQuery(region="082210001")


def test_a_page_holds_at_most_500() -> None:
    with pytest.raises(ValidationError):
        RankingQuery(limit=501)


def test_only_a_learned_models_score_is_a_probability() -> None:
    calibrated = {
        kind: ModelSummary.of(
            ForecastModel(name="n", version="v", kind=kind, horizon_months=24)
        ).calibrated
        for kind in ModelKind
    }

    assert calibrated == {
        ModelKind.HEURISTIC: False,
        ModelKind.LOGISTIC: True,
        ModelKind.CHOICE: False,
    }
