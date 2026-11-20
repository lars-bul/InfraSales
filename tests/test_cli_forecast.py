"""The commands that fill the public history and run the forecast on it."""

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from sqlmodel import select

from infrasales.cli import main
from infrasales.core.db import Database
from infrasales.forecast import heuristic
from infrasales.forecast.features import History
from infrasales.forecast.models import ForecastModel, Prediction
from tests.forecast.support import store, world


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch, database_url: str) -> str:
    monkeypatch.setenv("DATABASE_URL", database_url)
    return database_url


def stored_world(database_url: str, history: History) -> None:
    async def run() -> None:
        db = Database(database_url)
        try:
            await store(db, history)
        finally:
            await db.dispose()

    asyncio.run(run())


def stored[T](database_url: str, table: type[T]) -> list[T]:
    async def run() -> list[T]:
        db = Database(database_url)
        try:
            async with db.session() as session:
                return list((await session.exec(select(table))).all())
        finally:
            await db.dispose()

    return asyncio.run(run())


@pytest.mark.usefixtures("database")
def test_import_reads_a_csv_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file = tmp_path / "gemeinden.csv"
    file.write_text("\ufeffags;name\n08221000;Heidelberg\n08421000;Ulm\n", encoding="utf-8")

    main(["import", "municipalities", str(file)])

    assert capsys.readouterr().out == "municipalities: 2 new, 0 updated\n"


@pytest.mark.usefixtures("database")
def test_an_invalid_import_names_its_errors_and_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = tmp_path / "signale.csv"
    file.write_text("kind,ags,available_on,ref\nrumour,08221000,2025-01-01,x\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        main(["import", "signals", str(file)])

    assert exit_info.value.code == 1
    assert capsys.readouterr().err.startswith("line 2: kind:")


@pytest.mark.usefixtures("database")
def test_without_enough_history_backtest_and_training_stop_and_say_why(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for command in (["forecast-backtest"], ["forecast-train"]):
        with pytest.raises(SystemExit) as exit_info:
            main(command)

        assert exit_info.value.code == 1
        assert "too little history to learn from" in capsys.readouterr().err


def test_predict_scores_every_municipality_with_the_heuristic(
    database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    stored_world(database, world(places=20))

    main(["forecast-predict", "--as-of", "2026-01-05"])

    assert capsys.readouterr().out == (
        f"20 municipalities scored for 2026-01-05 by {heuristic.VERSION}\n"
    )
    assert len(stored(database, Prediction)) == 20


def test_backtest_prints_how_the_heuristic_and_a_learned_model_rank(
    database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    stored_world(database, world())

    main(["forecast-backtest", "--horizon", "12"])

    result = json.loads(capsys.readouterr().out)
    assert set(result) == {"cut", "heuristic", "learned"}
    assert result["learned"]["roc_auc"] > 0.8


def test_a_trained_model_is_stored_and_only_activated_when_asked(
    database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    stored_world(database, world())

    main(["forecast-train", "--horizon", "12"])
    inactive = capsys.readouterr().out
    main(["forecast-train", "--horizon", "12", "--activate"])
    active = capsys.readouterr().out

    models = {m.version: m for m in stored(database, ForecastModel)}
    assert "stored inactive" in inactive
    assert active.rstrip().endswith(": active")
    assert [m.active for m in models.values()].count(True) == 1
    serving = next(m for m in models.values() if m.active)
    assert (serving.horizon_months, serving.trained_by) == (12, "cli")
    learned = serving.metrics["learned"]
    assert isinstance(learned, Mapping)
    assert isinstance(learned["roc_auc"], float)
    assert learned["roc_auc"] > 0.8
