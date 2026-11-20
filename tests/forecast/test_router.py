from datetime import date

import httpx2
import pytest
from sqlmodel import select

from infrasales.core.db import Database
from infrasales.forecast import heuristic, service
from infrasales.forecast.features import FEATURES, History
from infrasales.forecast.logistic import Logistic
from infrasales.forecast.models import ForecastModel
from infrasales.projects.models import SignalKind, TenderKind
from infrasales.scheduler.models import JobRun
from tests.forecast.support import HEIDELBERG, ULM, WALDDORF, construction, signal, store
from tests.helpers import SAME_ORIGIN, audit_actions, sign_in

pytestmark = pytest.mark.anyio

AS_OF = date(2026, 1, 5)


async def scored(database_url: str) -> None:
    """Three municipalities, Heidelberg with signals, scored by the heuristic on `AS_OF`."""
    db = Database(database_url)
    history = History.of(
        [HEIDELBERG, ULM, WALDDORF],
        signals=[
            (HEIDELBERG.ags, signal(SignalKind.COUNCIL_DECISION, date(2025, 6, 1))),
            (HEIDELBERG.ags, signal(SignalKind.FUNDING_GRANTED, date(2025, 9, 1))),
        ],
        tenders=[(HEIDELBERG.ags, construction(date(2024, 3, 1), kind=TenderKind.PLANNING))],
    )
    await store(db, history)
    async with db.session() as session:
        model = await service.ensure_heuristic(session)
        await service.predict(session, model, await service.load_history(session), AS_OF)
    await db.dispose()


async def test_the_ranking_is_for_signed_in_users(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/api/forecast/municipalities")).status_code == 401


async def test_before_any_model_ran_the_ranking_is_empty(client: httpx2.AsyncClient) -> None:
    await sign_in(client, "vera")

    response = await client.get("/api/forecast/municipalities")

    assert response.json() == {"model": None, "as_of": None, "total": 0, "items": []}


async def test_the_ranking_puts_the_municipality_with_signals_first(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await scored(database_url)
    await sign_in(client, "vera")

    ranking = (await client.get("/api/forecast/municipalities")).json()

    assert ranking["model"] == {
        "version": heuristic.VERSION,
        "kind": "heuristic",
        "horizon_months": 24,
        "calibrated": False,
    }
    assert (ranking["as_of"], ranking["total"]) == ("2026-01-05", 3)
    first = ranking["items"][0]
    assert (first["rank"], first["ags"], first["name"]) == (1, HEIDELBERG.ags, "Heidelberg")
    assert {reason["feature"] for reason in first["reasons"]} <= set(FEATURES)
    assert first["reasons"][0]["effect"] > 0


async def test_the_ranking_is_filtered_by_region_and_paged(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await scored(database_url)
    await sign_in(client, "vera")

    region = (await client.get("/api/forecast/municipalities?region=08226")).json()
    page = (await client.get("/api/forecast/municipalities?limit=1&offset=1")).json()
    invalid = await client.get("/api/forecast/municipalities?region=BW")

    assert [(i["rank"], i["ags"]) for i in region["items"]] == [(1, WALDDORF.ags)]
    assert region["total"] == 1
    assert [i["rank"] for i in page["items"]] == [2]
    assert invalid.status_code == 422


async def test_a_municipalitys_file_shows_score_rank_features_and_evidence(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await scored(database_url)
    await sign_in(client, "vera")

    file = (await client.get(f"/api/forecast/municipalities/{HEIDELBERG.ags}")).json()

    assert (file["name"], file["rank"], file["total"], file["as_of"]) == (
        "Heidelberg",
        1,
        3,
        "2026-01-05",
    )
    assert [point["as_of"] for point in file["history"]] == ["2026-01-05"]
    assert file["history"][0]["score"] == file["score"]
    assert [s["kind"] for s in file["signals"]] == ["funding_granted", "council_decision"]
    assert [t["kind"] for t in file["tenders"]] == ["planning"]
    assert [f["name"] for f in file["features"]] == list(FEATURES)
    seen = {f["name"]: f["value"] for f in file["features"]}
    assert seen["recent_council_decision"] > 0


async def test_a_municipality_not_scored_yet_has_its_evidence_but_no_score(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    db = Database(database_url)
    await store(db, History.of([ULM]))
    await db.dispose()
    await sign_in(client, "vera")

    file = (await client.get(f"/api/forecast/municipalities/{ULM.ags}")).json()
    missing = await client.get("/api/forecast/municipalities/09162000")

    assert (file["score"], file["rank"], file["model"], file["features"]) == (None, None, None, [])
    assert missing.status_code == 404


async def test_admins_see_the_models_and_activate_one(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await scored(database_url)
    db = Database(database_url)
    learned = Logistic(
        FEATURES, (0.0,) * len(FEATURES), (1.0,) * len(FEATURES), (0.1,) * len(FEATURES), -3.0
    )
    async with db.session() as session:
        stored = await service.store_learned(
            session, learned, horizon_months=24, trained_until=AS_OF, metrics={}, by="cli"
        )
    await sign_in(client, "vera")
    assert (await client.get("/api/forecast/models")).status_code == 403
    await sign_in(client, "alice")

    before = (await client.get("/api/forecast/models")).json()
    activated = await client.post(f"/api/forecast/models/{stored.id}/activate", headers=SAME_ORIGIN)
    ranking = (await client.get("/api/forecast/municipalities")).json()

    assert [(m["version"], m["active"]) for m in before] == [
        (stored.version, False),
        (heuristic.VERSION, True),
    ]
    assert activated.json()["active"] is True
    assert ranking["model"]["calibrated"] is True
    assert ranking["as_of"] is None  # its first run is queued, not done
    async with db.session() as session:
        queued = (await session.exec(select(JobRun))).all()
        active = (await session.exec(select(ForecastModel).where(ForecastModel.active))).all()
    await db.dispose()
    assert [run.job for run in queued] == ["forecast"]
    assert [m.id for m in active] == [stored.id]
    assert ("basic:alice", "forecast.model_activated", "success") in await audit_actions(
        database_url
    )


async def test_activating_the_active_model_changes_nothing(
    client: httpx2.AsyncClient, database_url: str
) -> None:
    await scored(database_url)
    await sign_in(client, "alice")
    (model,) = (await client.get("/api/forecast/models")).json()

    response = await client.post(
        f"/api/forecast/models/{model['id']}/activate", headers=SAME_ORIGIN
    )
    unknown = await client.post(
        "/api/forecast/models/0190e1c8-0000-7000-8000-000000000000/activate", headers=SAME_ORIGIN
    )

    assert response.json()["active"] is True
    assert unknown.status_code == 404
    assert "forecast.model_activated" not in [a for _, a, _ in await audit_actions(database_url)]
