"""The forecast job: every municipality scored by the active model, with what is known today.

Weekly, before a sales week starts. It reads the public history (ADR 06 §4, Modell A) and replaces
the day's scores, so a run repeated on the same day changes nothing but the scores' run. Learning a
new model is no part of it: a person trains one and decides to activate it
(`infrasales forecast-train`), the heuristic serving until then.
"""

from zoneinfo import ZoneInfo

from infrasales.core.db import Database
from infrasales.core.models import JSONValue
from infrasales.forecast import service
from infrasales.scheduler.registry import JobContext

ZONE = ZoneInfo("Europe/Berlin")  # the day a score is for: the customers' calendar day


async def forecast_job(context: JobContext, *, db: Database) -> JSONValue:
    """Score every municipality for the day the run was scheduled for."""
    as_of = context.scheduled_for.astimezone(ZONE).date()
    async with db.session() as session:
        model = await service.ensure_heuristic(session)
        with context.trace.step("history"):
            history = await service.load_history(session)
        given: JSONValue = {"model": model.version, "as_of": as_of.isoformat()}
        with context.trace.step("predict", given) as step:
            made = await service.predict(session, model, history, as_of, run_id=context.run_id)
            step.finish(made)
    return {"model": model.version, "as_of": as_of.isoformat(), "municipalities": made}
