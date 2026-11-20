"""Command-line entry point: `infrasales <command>`.

Each command imports what it needs when it runs: `infrasales migrate` never loads the web stack.
"""

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from importlib.metadata import version
from typing import TYPE_CHECKING, NoReturn

from pydantic import ValidationError

from infrasales.core.logs import configure_logging
from infrasales.forecast.features import HORIZON_MONTHS
from infrasales.projects.imports import ImportKind
from infrasales.settings import MaintenanceSettings, Settings, WorkerSettings

if TYPE_CHECKING:
    from infrasales.forecast.features import History


def _load[S: MaintenanceSettings](settings_class: type[S]) -> S:
    settings = settings_class.load()
    configure_logging(log_format=settings.log_format, level=settings.log_level)
    return settings


def web(args: argparse.Namespace) -> None:
    """Serve the API and the UI."""
    import uvicorn

    from infrasales.app import create_app

    settings = _load(Settings)
    reload: bool = args.reload  # development: a fresh process per code change
    uvicorn.run(
        "infrasales.app:from_environment" if reload else create_app(settings),
        factory=reload,
        reload=reload,
        reload_dirs=["src"] if reload else None,
        host=settings.web.host,
        port=settings.web.port,
        proxy_headers=True,  # trusted proxies: FORWARDED_ALLOW_IPS (default 127.0.0.1)
        server_header=False,
        timeout_graceful_shutdown=10,  # in-flight requests drain; then the worker (README)
        log_config=None,  # keep the structured logging configured above
        access_log=False,  # one structured line per request instead
    )


def worker(_: argparse.Namespace) -> None:
    """Run the scheduler on its own (with SCHEDULER__ENABLED=false on the web servers)."""
    import asyncio

    from infrasales.ai import service as ai
    from infrasales.config.service import store_defaults
    from infrasales.core.db import Database
    from infrasales.jobs.catalog import catalog
    from infrasales.observability import start_telemetry
    from infrasales.scheduler.worker import Worker, serve

    settings = _load(WorkerSettings)
    telemetry = start_telemetry(settings)

    async def run() -> None:
        db = Database(settings.database_url.get_secret_value(), settings.database_pool)
        try:
            await store_defaults(db)  # the schedules it plans by
            await ai.seed(db, settings, settings.secret_box())
            await serve(Worker(db, catalog(settings, db), settings.scheduler, telemetry=telemetry))
        finally:
            await db.dispose()
            if telemetry:
                telemetry.shutdown()

    asyncio.run(run())


def migrate(_: argparse.Namespace) -> None:
    """Apply database migrations, then grant the app and retention roles least privilege."""
    from infrasales.core.grants import grant
    from infrasales.core.schema import upgrade

    settings = _load(MaintenanceSettings)
    url = settings.database_url.get_secret_value()
    upgrade(url)
    if roles := settings.database_roles():
        grant(url, roles)


_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def _duration(text: str) -> timedelta:
    """`30s`, `15m`, `24h` or `7d`."""
    if match := re.fullmatch(r"(\d+)([smhd])", text):
        amount = int(match[1])
        if amount > 0:
            return timedelta(**{_UNITS[match[2]]: amount})
    msg = f"not a positive duration like 24h: {text!r}"
    raise argparse.ArgumentTypeError(msg)


def prune(args: argparse.Namespace) -> None:
    """Delete data past its retention period; with --every, keep doing so."""
    import asyncio

    from infrasales import retention
    from infrasales.core.db import Database
    from infrasales.sink.store import Sink

    settings = _load(MaintenanceSettings)

    async def run() -> None:
        db = Database(settings.database_url.get_secret_value(), settings.database_pool)
        try:
            await retention.run(db, Sink(settings.sink.uri), settings.retention, args.every)
        finally:
            await db.dispose()

    asyncio.run(run())


def revoke(args: argparse.Namespace) -> None:
    """End every session of a person at once, e.g. after removing them from an admin group."""
    import asyncio

    from infrasales.audit import service as audit
    from infrasales.auth import sessions
    from infrasales.core.db import Database

    settings = _load(MaintenanceSettings)
    subject: str = args.subject

    async def run() -> int:
        db = Database(settings.database_url.get_secret_value(), settings.database_pool)
        try:
            async with db.session() as session:
                ended = await sessions.revoke(session, subject)
                details = {"sessions": ended}
                audit.record(
                    session, actor=None, action="auth.revoked", target=subject, details=details
                )
        finally:
            await db.dispose()
        return ended

    sys.stdout.write(f"{asyncio.run(run())} session(s) of {subject} ended\n")


def secrets_key(_: argparse.Namespace) -> None:
    """Print a new SECRETS_KEY, which encrypts the stored API keys."""
    from infrasales.core.secrets import new_key

    sys.stdout.write(new_key() + "\n")


def openapi(_: argparse.Namespace) -> None:
    """Print the OpenAPI document (`make api-types` writes it to openapi.json)."""
    from infrasales.app import openapi as document

    sys.stdout.write(json.dumps(document(), indent=2) + "\n")


def import_data(args: argparse.Namespace) -> None:
    """Import a CSV file of public data: municipalities, signals, tenders or metrics."""
    import asyncio
    from pathlib import Path

    from infrasales.core.db import Database
    from infrasales.projects.imports import ImportKind, ImportResult, import_csv

    settings = _load(MaintenanceSettings)
    kind = ImportKind(args.kind)
    text = Path(args.file).read_text(encoding="utf-8-sig")

    async def run() -> ImportResult:
        db = Database(settings.database_url.get_secret_value(), settings.database_pool)
        try:
            async with db.session() as session:
                return await import_csv(session, kind, text)
        finally:
            await db.dispose()

    result = asyncio.run(run())
    if not result.ok:
        sys.stderr.write("".join(f"{error}\n" for error in result.errors))
        raise SystemExit(1)
    sys.stdout.write(f"{kind}: {result.inserted} new, {result.updated} updated\n")


def _history(settings: MaintenanceSettings) -> History:
    import asyncio

    from infrasales.core.db import Database
    from infrasales.forecast import service

    async def run() -> History:
        db = Database(settings.database_url.get_secret_value(), settings.database_pool)
        try:
            async with db.session() as session:
                return await service.load_history(session)
        finally:
            await db.dispose()

    return asyncio.run(run())


def _not_enough(error: Exception) -> NoReturn:
    sys.stderr.write(
        f"infrasales: too little history to learn from ({error}): "
        "the heuristic keeps serving until more tenders are known\n"
    )
    raise SystemExit(1)


def forecast_backtest(args: argparse.Namespace) -> None:
    """Backtest the heuristic and a learned forecast model on the public history."""
    from infrasales.forecast.training import NotEnoughDataError, backtest

    history = _history(_load(MaintenanceSettings))
    try:
        drop = [name for name in (args.drop or "").split(",") if name]
        result = backtest(history, horizon_months=args.horizon, drop=drop, since=args.since)
    except NotEnoughDataError as error:
        _not_enough(error)
    sys.stdout.write(json.dumps(result.as_json(), indent=2) + "\n")


def forecast_train(args: argparse.Namespace) -> None:
    """Learn a forecast model from the whole history and store it with its backtest."""
    import asyncio

    from infrasales.core.db import Database
    from infrasales.forecast import service
    from infrasales.forecast.training import NotEnoughDataError, backtest, train

    settings = _load(MaintenanceSettings)
    history = _history(settings)
    try:
        tested = backtest(history, horizon_months=args.horizon, since=args.since)
        model, until = train(history, horizon_months=args.horizon, since=args.since)
    except NotEnoughDataError as error:
        _not_enough(error)

    async def run() -> str:
        db = Database(settings.database_url.get_secret_value(), settings.database_pool)
        try:
            async with db.session() as session:
                stored = await service.store_learned(
                    session,
                    model,
                    horizon_months=args.horizon,
                    trained_until=until,
                    metrics=tested.as_json(),
                    by="cli",
                )
                if args.activate:
                    await service.activate(session, stored)
                return stored.version
        finally:
            await db.dispose()

    version = asyncio.run(run())
    state = "active" if args.activate else "stored inactive; --activate to serve it"
    sys.stdout.write(json.dumps(tested.as_json(), indent=2) + f"\n{version}: {state}\n")


def forecast_predict(args: argparse.Namespace) -> None:
    """Score every municipality with the active forecast model (the heuristic until one is)."""
    import asyncio

    from infrasales.core.db import Database
    from infrasales.forecast import service
    from infrasales.jobs.forecast import ZONE

    settings = _load(MaintenanceSettings)
    as_of: date = args.as_of or datetime.now(ZONE).date()

    async def run() -> tuple[str, int]:
        db = Database(settings.database_url.get_secret_value(), settings.database_pool)
        try:
            async with db.session() as session:
                model = await service.ensure_heuristic(session)
                made = await service.predict(
                    session, model, await service.load_history(session), as_of
                )
                return model.version, made
        finally:
            await db.dispose()

    version, made = asyncio.run(run())
    sys.stdout.write(f"{made} municipalities scored for {as_of} by {version}\n")


def load(args: argparse.Namespace) -> None:
    """Load downloaded public data: gemeinden, postcodes, ted, doe or bew."""
    import asyncio
    from pathlib import Path

    from infrasales.core.db import Database
    from infrasales.core.schema import import_models
    from infrasales.sources import load as loaders

    import_models()  # tenders refer to the catalog's source versions
    settings = _load(MaintenanceSettings)
    paths = [Path(path) for path in args.paths]

    async def run() -> str:
        db = Database(settings.database_url.get_secret_value(), settings.database_pool)
        try:
            async with db.session() as session:
                match args.source:
                    case "gemeinden":
                        loaded = await loaders.load_gemeinden(session, paths[0])
                    case "postcodes":
                        loaded = await loaders.load_post_codes(session, paths[0])
                    case "ted":
                        xml = paths[1] if len(paths) > 1 else None
                        loaded = await loaders.load_ted(session, paths[0], xml)
                    case "doe":
                        files = [
                            f
                            for p in paths
                            for f in (sorted(p.glob("*.csv.zip")) if p.is_dir() else [p])
                        ]
                        loaded = await loaders.load_doe(session, files)
                    case "ted-signals":
                        loaded = await loaders.load_ted_signals(session, paths[0])
                    case "zensus":
                        loaded = await loaders.load_zensus(session, paths[0])
                    case _:
                        loaded = await loaders.load_bew(session, paths[0])
                return loaded.text()
        finally:
            await db.dispose()

    sys.stdout.write(f"{args.source}: {asyncio.run(run())}\n")


def forecast_wins(args: argparse.Namespace) -> None:
    """Backtest and fit who wins heat network contracts, from public awards; store it as active."""
    import asyncio

    from infrasales.core.db import Database
    from infrasales.core.schema import import_models
    from infrasales.forecast import opportunities, winners

    import_models()
    settings = _load(MaintenanceSettings)
    cut: date = args.cut

    async def run() -> str:
        db = Database(settings.database_url.get_secret_value(), settings.database_pool)
        try:
            async with db.session() as session:
                market = winners.Market.of(await opportunities.awards(session))
                tested = winners.backtest(market, cut)
                heat_only = winners.backtest(market, cut, pipelines=False)
                sys.stderr.write(
                    f"heat network wins only: {json.dumps(heat_only.as_json())}{chr(10)}"
                )
                heat = [award for award in market.awards if award.heat]
                model = winners.fit(winners.choices(market, heat))
                last = max(award.day for award in market.awards)
                stored = await opportunities.store_win_model(
                    session, model, tested.as_json(), trained_until=last
                )
                return json.dumps(tested.as_json(), indent=2) + f"\n{stored.version}: active"
        finally:
            await db.dispose()

    try:
        sys.stdout.write(asyncio.run(run()) + "\n")
    except ValueError as error:
        sys.stderr.write(f"infrasales: {error}\n")
        raise SystemExit(1) from error


def tenant(args: argparse.Namespace) -> None:
    """Create a tenant with its owner, profile and site (a customer's first login)."""
    import asyncio
    import re as regex

    from infrasales.core.db import Database
    from infrasales.core.schema import import_models
    from infrasales.forecast.winners import UNKNOWN_DISTANCE_KM
    from infrasales.tenancy import service as tenancy

    import_models()
    settings = _load(MaintenanceSettings)

    async def run() -> str:
        db = Database(settings.database_url.get_secret_value(), settings.database_pool)
        try:
            async with db.session() as session:
                created = await tenancy.create(
                    session,
                    name=args.name,
                    slug=args.slug or regex.sub(r"[^a-z0-9]+", "-", args.name.lower()).strip("-"),
                    kind=args.kind,
                    owner=args.owner,
                    names=args.firm_name or [args.name],
                    site_post_code=args.post_code,
                    reach_km=args.reach_km or int(UNKNOWN_DISTANCE_KM / 2),
                )
                return f"{created.slug}: {created.id}"
        finally:
            await db.dispose()

    sys.stdout.write(asyncio.run(run()) + "\n")


COMMANDS: dict[str, Callable[[argparse.Namespace], None]] = {
    "web": web,
    "worker": worker,
    "migrate": migrate,
    "prune": prune,
    "revoke": revoke,
    "secrets-key": secrets_key,
    "openapi": openapi,
    "import": import_data,
    "load": load,
    "forecast-wins": forecast_wins,
    "tenant": tenant,
    "forecast-backtest": forecast_backtest,
    "forecast-train": forecast_train,
    "forecast-predict": forecast_predict,
}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="infrasales", description="InfraSales")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('infrasales')}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    parsers = {name: commands.add_parser(name, help=cmd.__doc__) for name, cmd in COMMANDS.items()}
    parsers["web"].add_argument("--reload", action="store_true", help="restart on code changes")
    parsers["prune"].add_argument("--every", type=_duration, help="repeat, e.g. 24h (a service)")
    parsers["revoke"].add_argument("subject", help="as in the audit trail, e.g. oidc:<sub>")
    parsers["import"].add_argument("kind", choices=[kind.value for kind in ImportKind])
    parsers["import"].add_argument("file", help="a CSV file, UTF-8, headed by the field names")
    parsers["load"].add_argument(
        "source", choices=["gemeinden", "postcodes", "ted", "ted-signals", "doe", "bew", "zensus"]
    )
    parsers["forecast-wins"].add_argument(
        "--cut", type=date.fromisoformat, default=date(2025, 1, 1), help="backtest from this day"
    )
    parsers["tenant"].add_argument("name", help="the company's name, e.g. Muster Tiefbau GmbH")
    parsers["tenant"].add_argument(
        "--slug", help="its short name in addresses (default: from the name)"
    )
    parsers["tenant"].add_argument(
        "--kind",
        default="contractor",
        choices=["contractor", "contracting_authority", "private_builder", "financier", "platform"],
    )
    parsers["tenant"].add_argument(
        "--owner", required=True, help="the owner's subject, e.g. basic:alice"
    )
    parsers["tenant"].add_argument(
        "--firm-name", action="append", help="a name it wins awards under"
    )
    parsers["tenant"].add_argument("--post-code", help="its site's post code")
    parsers["tenant"].add_argument("--reach-km", type=int, help="how far it goes for work")
    parsers["load"].add_argument(
        "paths", nargs="+", help="the downloaded file(s); ted: pages folder [xml folder]"
    )
    for name in ("forecast-backtest", "forecast-train"):
        parsers[name].add_argument(
            "--horizon", type=int, default=HORIZON_MONTHS, help="months a tender counts within"
        )
    parsers["forecast-backtest"].add_argument(
        "--since", type=date.fromisoformat, help="snapshots from this day: one data regime"
    )
    parsers["forecast-backtest"].add_argument(
        "--drop", help="features to leave out, by comma: what they add (see forecast.features)"
    )
    parsers["forecast-train"].add_argument(
        "--since", type=date.fromisoformat, help="snapshots from this day: one data regime"
    )
    parsers["forecast-train"].add_argument(
        "--activate", action="store_true", help="serve the predictions with it from now on"
    )
    parsers["forecast-predict"].add_argument(
        "--as-of", type=date.fromisoformat, help="the day, e.g. 2026-01-05 (default: today)"
    )
    args = parser.parse_args(argv)
    try:
        COMMANDS[args.command](args)
    except ValidationError as error:  # secrets never appear: settings hide input in errors
        parser.exit(2, f"infrasales: invalid configuration\n{error}\n")
