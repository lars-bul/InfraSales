# ADR 01: Baseline architecture

Status: **Accepted**. Written for the project this codebase comes from; [ADR 06](06_adr_infrasales.md)
says what changed for InfraSales. Where the two differ, ADR 06 applies.

## Context

InfraSales collects documents from many places on the web, runs scheduled jobs that read them with
language models, and shows the results in a web interface: to its own team in the back office and
to customers in their area. It is meant for real, productive use, so the usual requirements of a
production system apply: security, resource efficiency, scalability and an audit trail. So do data
protection (the GDPR), accessibility and the EU AI Act. And the usual code-quality rules apply:
tests, linting and type checks.

Where it will run is not decided yet. So it stays portable, especially in its database, its
sign-in and its external logging.

## Requirements

| Area | Requirement |
|---|---|
| Privacy | Collect only the personal data a feature needs; use pseudonymous IDs instead of names wherever possible. Delete personal data after fixed periods. Document the processing ([PRIVACY.md](../../PRIVACY.md)). Sign contracts and check transfers for every external service that receives personal data. |
| Security | Protect sessions, forms and responses as OWASP recommends: secure cookies, checks against cross-site requests, security headers. Protect the software supply chain: locked and hashed dependencies, a waiting period for new releases, vulnerability scans, a software bill of materials. Keep secrets out of the repository. Log security-relevant events and protect the logs. |
| Access | All data needs a signed-in user, and changes need the right role. Only the health checks, the sign-in flow and the static interface files (which hold no data) are public. |
| AI Act | Mark AI-generated content in a machine-readable way and label it visibly. Make no decisions about people, so that InfraSales stays outside the high-risk areas. |
| Accessibility | The web interface meets WCAG 2.1 level AA. |
| Operations | Trusted users change the configuration in the web interface, without a redeployment or server access. Use few resources: one small process, nearly idle between runs. Scale out by adding instances, without running a job twice at the same time. Recover by itself from crashes, restarts and outages. Keep an audit trail of sign-ins and changes. Stay portable: database, sign-in and telemetry are chosen by configuration. |
| Quality | Every change passes the tests, strict type checks and linting. Builds are reproducible, and releases are versioned. |

## Core Architectural and Framework Choices

### How we compare options

We compare options with the same four questions:

| Question | What it asks |
|---|---|
| **Fit** | Does it cover what InfraSales needs (see the requirements)? |
| **Effort** | How much do we have to build now, and for every change later? |
| **Maintenance** | What must we maintain: languages, tools, services, our own code? Can new developers pick it up? |
| **Risk** | How mature and stable is it, and how hard would it be to switch later? |

Popularity only counts under *Maintenance*.

### Python, version control and packaging

InfraSales is a documented and version-controlled Python application. We develop it in this
repository and check every commit message against
[Conventional Commits](https://www.conventionalcommits.org/). Version control must cover the
dependencies too. That is why we use a package manager with a lockfile.

We chose **[uv](https://docs.astral.sh/uv/)**. One tool manages the Python version, the virtual
environment and the dependencies. Its [lockfile](https://docs.astral.sh/uv/concepts/projects/layout/#the-lockfile)
covers all platforms and Python versions in one file, with a sha256 hash for every package. Its
[`exclude-newer`](https://docs.astral.sh/uv/concepts/resolution/#dependency-cooldowns) setting adds
a cooldown: we only install releases that are at least a week old, so a freshly published malicious
version cannot reach us at once. [`uv audit`](https://docs.astral.sh/uv/reference/cli/#uv-audit)
checks the lockfile for known vulnerabilities (still a preview). Astral, uv's maker, reports large
speed-ups over pip-tools, Poetry and PDM in its own
[benchmarks](https://github.com/astral-sh/uv/blob/main/BENCHMARKS.md).

**Cost:** uv is still version 0.x and comes from one company. If we ever need to leave it,
`uv export` writes a standard requirements file with hashes.

<details><summary>Alternatives to uv</summary>

| Option | Fit | Effort | Maintenance | Risk |
|---|---|---|---|---|
| **uv** (chosen) | Python versions, environments, one lock for all platforms, hashes, cooldown | Low: one tool | One tool to learn | Version 0.x, one vendor; `uv export` as a way out |
| pip with requirements files | A lock only for the current platform: [`pip lock`](https://pip.pypa.io/en/stable/cli/pip_lock/) is experimental | High: several tools to combine | The standard everyone knows | Low |
| pip-tools | Hashed pins, but the [output depends on the environment](https://github.com/jazzband/pip-tools); no Python versions | Medium | Small and known | Low |
| Poetry | Lockfile and packaging; installing Python is [experimental](https://python-poetry.org/docs/cli/#python) | Low | Well known: 20% in the [Python Developers Survey 2024](https://lp.jetbrains.com/python-developers-survey-2024/) | Low: stable 2.x |
| PDM | Standards-based lock; uses uv only [experimentally](https://pdm-project.org/en/latest/usage/uv/) | Low | Less known | Medium |
| Pipenv | Lockfile with hashes | Low | Known: 8% in the same survey | Low |

Poetry is the closest alternative. uv wins because it also manages Python versions and gives us
the release cooldown in one setting.

</details>

### Web Interface

A small team runs InfraSales, with little time for day-to-day IT operations. So trusted users
must be able to change most settings themselves, at any time, without server access, a
redeployment or IT staff: the Feeds, the schedules, the AI connections and models. This needs a
web interface, and a backend that keeps these settings safe without wasting resources. The same
interface shows what InfraSales has found: to our team in the back office, and to customers in
their area (ADR 06 §9).

**Cost:** a web interface is a second code base. We keep it small and fully tested.

### A modular, portable monolith

We expect at most a few dozen people in the interface at the same time for a long while. The interface's static files carry a content hash in their name and may
be cached for a year (`public, max-age=31536000, immutable`), so the reverse proxy can serve them.
API responses are personal and never cached (`no-store`). A public CDN would conflict with the
access rules, and InfraSales does not need one.

So there is no need for separately scaled microservices. To save maintenance effort and stay
efficient, we build one modular, portable application: it serves the web interface and the API,
and it runs the jobs on their schedules. Martin
Fowler's [MonolithFirst](https://martinfowler.com/bliki/MonolithFirst.html) makes the same point:
most successful microservice systems started as a monolith, and microservices come with an
[extra cost](https://martinfowler.com/bliki/MicroservicePremium.html) that only pays off for very
complex systems. Inside, InfraSales still keeps clear boundaries, like Shopify's
[modular monolith](https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity):
one package per feature, a `core` that imports no feature, and type checks that reject import
cycles (see [Internal architecture](#internal-architecture)).

**Cost:** the application scales only as a whole. At this size that is fine. If it ever changes,
the feature packages are where we would split it.

### A built-in scheduler

Documents must be collected and read on schedule without anyone starting it. We built
the scheduler into the application. This is the most expensive decision in this record. So we
explain it in three steps: why a CronJob alone is not enough, why we did not adopt an existing
PostgreSQL queue, and what our choice costs.

#### Why a CronJob alone is not enough

The obvious tool for a weekly job is a cron job: a crontab entry or a Kubernetes CronJob that starts
the job at a fixed time. Three reasons speak against relying on it alone:

1. **Schedules must change at runtime.** A cron schedule lives in a crontab or a manifest. Changing
   it needs server access and a redeployment – exactly what we want to avoid. In InfraSales, an
   admin changes a schedule in the web interface, where the change is checked, versioned and
   audited.
2. **Run state is needed anyway.** The Kubernetes documentation itself says that a CronJob starts a
   job only *about* once per scheduled time: sometimes twice, sometimes not at all. So jobs should
   be safe to run twice ([CronJob limitations](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/#cron-job-limitations)).
   To run a job safely twice (send a mail, call a paid model), we need a record of what was already done – state in a
   database. Once that state exists, the rest of what a reliable pipeline needs builds on it: a run
   history, retries with growing pauses, steps that a retry can skip, alerts after repeated
   failures, a safe "run now" button, and no overlapping runs. Cron offers none of these.
3. **Portability.** cron, [systemd timers](https://man7.org/linux/man-pages/man5/systemd.timer.5.html),
   Kubernetes CronJobs and cloud schedulers all behave differently, also when a run was missed.
   Plain cron assumes a machine that is always on; that is why
   [anacron](https://man7.org/linux/man-pages/man8/anacron.8.html) exists. A systemd timer only
   catches up with `Persistent=true`. A Kubernetes CronJob depends on its `startingDeadlineSeconds`.
   We do not know yet where InfraSales will run, so the built-in scheduler behaves the same
   everywhere. After downtime it catches up the latest missed run.

Where cron fits, we use it: data retention (`infrasales prune`) keeps no state, may safely run twice and
needs no runtime settings, so it may run as a CronJob.

#### Build it, or use a PostgreSQL queue library?

Once run state lives in the database, a job queue in PostgreSQL is the natural design. Runs are
rows, and a worker takes one with `SELECT … FOR UPDATE SKIP LOCKED`, which skips the rows other
workers are taking. The PostgreSQL documentation recommends
[`SKIP LOCKED`](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE) for
exactly this: several workers taking jobs from one table without waiting for each other. Libraries
such as [Solid Queue](https://github.com/rails/solid_queue) (Rails), [pg-boss](https://github.com/timgit/pg-boss)
(Node.js) and [Procrastinate](https://procrastinate.readthedocs.io/en/stable/) (Python) build on
the same idea.

**Procrastinate** is the strongest candidate. It is a Python library under the MIT licence, marked
production-ready, developed since 2019, with 9 releases in the last twelve months. It supports
async code, retries with growing pauses, locks that run jobs one at a time, cancellation, and
schedules read from the database. We compared it with our own scheduler:

| Need | Built-in scheduler (chosen) | Procrastinate 3.10 |
|---|---|---|
| Schedules edited in the interface | Stored in the database and planned by the scheduler | Periodic tasks are fixed in code. For schedules from a database, its documentation suggests a frequent task that reads them and starts jobs ([dynamic scheduling](https://procrastinate.readthedocs.io/en/stable/howto/advanced/cron.html#dynamic-scheduling)). We would write that part ourselves |
| One run per scheduled time, even with several workers | A unique rule per scheduled time | Guaranteed for periodic tasks; with schedules from the database, our own planning code must ensure it |
| Retries with growing pauses | Yes | Yes ([retry strategies](https://procrastinate.readthedocs.io/en/stable/howto/advanced/retry.html)) |
| At most one running attempt per job | A partial unique index | Yes ([locks](https://procrastinate.readthedocs.io/en/stable/howto/advanced/locks.html)) |
| Taking over the job of a crashed worker | Automatic, once its lease runs out | It detects stalled jobs by a heartbeat; retrying them needs a task of our own ([stalled jobs](https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html)) |
| Stopping a job | Cancellation, a time limit and a bounded shutdown | Cancel and abort ([cancellation](https://procrastinate.readthedocs.io/en/stable/howto/advanced/cancellation.html)); time limits and shutdown would need checking |
| Steps a retry can skip (a mail written once, each recipient recorded) | Yes | Not included – stays our code |
| Alerts after repeated failures | Yes | Not included – stays our code |
| Run history and "run now" in the interface | Our own tables, shaped for the interface | Its job tables could be read, which ties the interface to the library's internal schema; the "run now" keys stay our code |
| SQLite for development | Yes | No – PostgreSQL 13 or newer only |
| Database schema | Part of our Alembic migrations, with least-privilege roles | Its own SQL migrations, applied separately before and after each upgrade ([migrations](https://procrastinate.readthedocs.io/en/stable/howto/production/migrations.html)), plus rights on its tables and functions |
| Code we own | job queue | Less queue code, but planning, steps, alerts, history and glue code remain |
| Maintenance | We fix bugs ourselves | The library's maintainers fix the queue; we follow its upgrades |

**Decision.** We keep the built-in scheduler for now. Procrastinate would take over the generic
part – taking jobs, leases, retries and locks, but the parts that make our scheduling special would stay our code, the library
would add a second migration process, and it would tie the queue to the library's schema. For a
handful of jobs, the switch does not pay off yet.

<details><summary>Other alternatives</summary>

| Option | Fit | Effort | Maintenance | Risk |
|---|---|---|---|---|
| A CronJob or crontab alone | No runtime schedules, no run state | Low at first; everything around it is extra work | Differs from platform to platform | Runs twice or not at all |
| APScheduler 3.x | Schedules inside the process; its [FAQ](https://apscheduler.readthedocs.io/en/3.x/faq.html) says a job store must not be shared between processes | Low | A known library | Runs twice or are missed with several instances |
| Celery beat with workers | A mature task queue | High: a message broker (RabbitMQ or Redis) and exactly [one beat process](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html) | Two more services to run | Tasks run twice if two beat processes run |

</details>

How runs, leases and steps work in detail is explained with
the [data model](#data-model).

### Deployment

This diagram shows the general idea. One container image runs in three roles:

- the **monolith** with the web interface, the API and the scheduler; it can run on a single machine or as several instances in a cluster;
- the **migration service**, which updates the database schema before the application starts;
- the **retention service**, which deletes expired data.

Around it:

- **Reverse proxy:** handles TLS and can cache the static interface files.
- **Identity provider:** any OpenID Connect provider signs users in. For customers it will be
  one that knows organisations, so that a customer's users, invitations and single sign-on are
  managed there (ADR 06 §3).
- **Database:** PostgreSQL 18 in production, SQLite for development (see
  [Database](#database)).
- **Language model provider:** any service with an OpenAI-compatible API, behind the model adapter
  (see [ADR 02](02_adr_openai_compatible_llm.md)).
- **SMTP server and webhook endpoint:** deliver mails and the alerts (see
  [Alerting](#alerting)).
- **OTLP collector** (e.g. Grafana) **and Langfuse:** optional traces, logs and metrics.

The connections: HTTPS from the browser to the reverse proxy, and plain HTTP from the proxy to the
application on the internal network. HTTPS to the identity provider, the language model provider,
the webhook and Langfuse. OTLP over HTTP to the collector. SMTP with TLS and certificate
checks. The database connection with TLS and certificate checks (`sslmode=verify-full` in the
production example profile).

Personal data only travels where it must:

| Where | What | Kind |
|---|---|---|
| Browser, identity provider and application | Sign-in: the application receives a user ID and a display name. It asks for no e-mail address (scope `openid profile`) | personal |
| Session row in the database | Pseudonymous user ID, display name and role; expires after at most 24 hours and is then deleted | personal, short-lived |
| Audit trail | Pseudonymous user ID, action, network shortened to /24 or /48 | pseudonymous |
| Configuration and SMTP server | Recipient addresses; only the mail server receives them | personal |
| Run steps | SHA-256 hashes of recipient addresses, to skip those already served | pseudonymous |
| Traces | The pseudonymous ID of the admin who started a run | pseudonymous |
| Language model provider, Langfuse | Document text, which may name third parties; Langfuse only when content tracing is on | third-party personal data possible |

### Database

For production we use **PostgreSQL** ([ADR 06 §6](06_adr_infrasales.md): PostgreSQL only).
The scheduler relies on two of its features:
[partial unique indexes](https://www.postgresql.org/docs/current/indexes-partial.html), which let
the database itself enforce "at most one running run per job", and `SKIP LOCKED` for the queue. For
grouping similar articles later, the [pgvector](https://github.com/pgvector/pgvector)
extension adds vector search (exact, or approximate with HNSW and IVFFlat indexes) in the same
database, so embeddings need no extra system. SQLite serves development and trials on a single
machine; the same code and migrations run on both.

Large articles and prompts may later need file storage: a folder on the server, or S3-compatible
storage. This is deliberately left open for now.

**Cost:** a database server to run, back up and update.

<details><summary>Alternatives to PostgreSQL</summary>

| Option | Fit | Effort | Maintenance | Risk |
|---|---|---|---|---|
| **PostgreSQL** (chosen) | Partial unique indexes, `SKIP LOCKED`, JSON, vector search via pgvector | Low | Widely known: the most used database in the [Stack Overflow Developer Survey 2025](https://survey.stackoverflow.co/2025/technology) (55.6%) | Low |
| MySQL or MariaDB | Has [`SKIP LOCKED`](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html) (MariaDB also vector indexes), but no partial indexes ([MySQL](https://dev.mysql.com/doc/refman/8.4/en/create-index.html), [MariaDB](https://mariadb.com/kb/en/create-index/)) | Medium: our uniqueness rules for runs would need workarounds with generated columns | Widely known | Low |
| SQLite in production | One writer at a time per database file; made for local storage, not for client/server use ([SQLite](https://www.sqlite.org/whentouse.html)) | Low | No server | Several instances cannot share it |
| A separate vector database | Specialised search | Medium | One more system to run and secure | Medium |

</details>

### Alerting

For now we read "notification of processing errors" as a message by e-mail and/or a
webhook to an application or board of choice, such as a team chat. A job that keeps failing sends
an alert from its second of three attempts on, and again when it fails for good. An alert names the
job, the run, the attempt and the type of the error – never details or personal data. In-app
notifications for users may follow (to be decided).

### Migrations and retention

The deployment diagram shows two short-lived services next to the application.

**Migrations.** Every change to the database schema is a versioned
[Alembic](https://alembic.sqlalchemy.org/en/latest/) migration in the repository. The migration
service applies new migrations before a new version starts. A test checks that applying all
migrations gives exactly the tables the models describe.

Rolling updates – where old and new instances run side by side for a while – need one more rule:
every migration must keep the previous release working. We follow expand/contract: add first,
remove only in a later release. This is a discipline that we check in review; no tool enforces it.
The readiness probe `/readyz` checks the structural part: the tables, columns, indexes, unique
rules and empty-value rules that the running build relies on. It cannot check behaviour. So a
change in the meaning of existing data needs extra care and a test of its own.

**Retention.** The GDPR requires that personal data are kept no longer than necessary
(Art. 5(1)(e)). The retention service deletes expired data in small batches: the audit
trail after 180 days, finished job runs with their steps after 90 days, sessions once they have
expired (at most 24 hours after sign-in). Source Versions are kept for good
([ADR 06 §7](06_adr_infrasales.md)); a period can still be set ([ADR 03 §8](03_adr_scraper_sink.md#8-retention)). All periods can be
configured, every deletion is itself audited, and the service uses its own database role, which
may only read and delete data and record what it deleted. One exception follows from deleting
files together with rows: the role may also lock Sources and mark Source Versions `deleted` before
it deletes their folders and rows, the deletion protocol of ADR 03 §3 and §8 (`UPDATE` on
`source` and `source_version`; it changes no other column). [PRIVACY.md](../../PRIVACY.md) lists
every stored item with its legal basis and period.

**Why auditing sign-ins and changes is allowed – and expected.** The audit trail records who signed
in, who changed what, and when. This is part of data protection, not in conflict with
it: we must be able to prove that we follow the rules (accountability, GDPR Art. 5(2))
and must keep the processing secure (Art. 32). The German data protection authorities'
[Standard Data Protection Model](https://www.datenschutz-mv.de/static/DS/Dateien/Datenschutzmodell/Bausteine/SDM-V3.1_Protokollieren_V2.0.pdf)
and the [BSI](https://www.bsi.bund.de/SharedDocs/Downloads/DE/BSI/Grundschutz/IT-GS-Kompendium_Einzel_PDFs_2023/04_OPS_Betrieb/OPS_1_1_5_Protokollierung_Edition_2023.pdf?__blob=publicationFile)
both count logging among these measures. We keep the trail lean: pseudonymous IDs instead of
names, networks shortened to /24 or /48, only the necessary details, and reading the trail is
itself audited.

### Backend: FastAPI, Authlib and SQLModel

For the core Python framework we chose **[FastAPI](https://fastapi.tiangolo.com/)**. InfraSales is
an API, a separate interface and a background scheduler in one process, and FastAPI fits that
shape:

- It is **async**, so one process can serve the API and run the scheduler, whose work – scraping
  and model calls – mostly waits on the network.
- It **checks every request and response** with Pydantic and derives an
  [OpenAPI](https://fastapi.tiangolo.com/features/) contract from the code. We generate the typed
  API client of the interface from this contract.
- Its **dependency injection** keeps the access rules (signed in, admin) short and visible on every
  route.

**Cost:** FastAPI is widely used but still version 0.x, and its documentation advises
[pinning a version range](https://fastapi.tiangolo.com/deployment/versions/), because minor
releases can break things. Our lockfile, automated updates and tests catch that. It is built on
Starlette, which has reached version 1.

FastAPI has no OpenID Connect sign-in of its own: its
[`OpenIdConnect`](https://fastapi.tiangolo.com/reference/security/#fastapi.security.OpenIdConnect)
class only describes the scheme in the OpenAPI document. So we use the OpenID Connect client of
**[Authlib](https://docs.authlib.org/en/stable/oauth2/client/web/starlette.html)** for Starlette. It
reads the provider's discovery document, runs the sign-in flow with PKCE, and checks the ID token
(signature, issuer, audience, nonce and expiry). After sign-in the backend keeps no tokens: it
starts its own session and gives the browser only a session cookie that scripts cannot read
(HttpOnly). [RFC 10017](https://www.rfc-editor.org/rfc/rfc10017) (OAuth 2.0 for Browser-Based
Applications) covers this case. Applications whose interface and API share one domain need no OAuth
in the browser at all. They can sign users in with OpenID Connect and then keep their own session;
the RFC leaves this setup outside the scope of its patterns
([§ 7.1](https://www.rfc-editor.org/rfc/rfc10017#section-7.1)). Keeping tokens out of the browser is
also why it strongly recommends a backend for applications that handle personal data
([§ 6.1.4.3](https://www.rfc-editor.org/rfc/rfc10017#section-6.1.4.3)).

To work with the database we use **[SQLModel](https://sqlmodel.tiangolo.com/)** with
**[Alembic](https://alembic.sqlalchemy.org/en/latest/)** for migrations, on SQLAlchemy 2. SQLModel
comes from FastAPI's author, and FastAPI's own [SQL tutorial](https://fastapi.tiangolo.com/tutorial/sql-databases/)
uses it. One class can be both the table and its validation model, which saves duplicate field
definitions. It does not rule out drift: where the API shows something different from the table,
there are still two models (for example [`ConfigEntry`](../../src/infrasales/config/models.py) and
`ConfigEntryRead` in [`config/schemas.py`](../../src/infrasales/config/schemas.py)). Drift between the
API and the interface is caught by tests: one fails when the checked-in `openapi.json` is out of
date, and the interface's lint fails when its generated types are. SQLModel is a thin layer over
[SQLAlchemy 2](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html), so where we need
special SQL (`INSERT … ON CONFLICT DO NOTHING`, `FOR UPDATE SKIP LOCKED`) we use SQLAlchemy
directly. Alembic is SQLAlchemy's own migration tool, written by its author. Its
[autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) proposes migrations from
the models, and we always review them.

**Cost:** SQLModel is still version 0.0.x (Beta). Because it is a thin layer over SQLAlchemy, the
risk stays small.

<details><summary>Alternatives to FastAPI, Authlib and SQLModel</summary>

| Web framework | Fit | Effort | Maintenance | Risk |
|---|---|---|---|---|
| **FastAPI** (chosen) | Async, request checks, an OpenAPI contract for the typed client | Low | Widely used: 38% in the [Python Developers Survey 2024](https://lp.jetbrains.com/python-developers-survey-2024/); SQLModel and Authlib document it directly | Version 0.x: minor releases can break; pinned and updated with tests |
| Django with Django REST Framework | Admin, ORM and sign-in built in; [transactions do not work in async code yet](https://docs.djangoproject.com/en/stable/topics/async/) | Medium: much of it stays unused next to a React interface | Very well known; [long-term support releases](https://docs.djangoproject.com/en/dev/internals/release-process/#term-Long-term-support-release) get three years of security fixes | Low |
| Flask | A small [WSGI framework](https://flask.palletsprojects.com/en/stable/); request checks, OpenAPI and database only through extensions | Medium | Well known | Low |
| [Litestar](https://docs.litestar.dev/latest/) | Similar features to FastAPI | Low | Fewer users, guides and integrations | Medium |

Django is the strongest alternative for long-term maintenance, thanks to its long-term support
releases. We chose FastAPI because an async API with a background scheduler in one process fits it
better; Moreover, most of us have experience with this framework.

| Sign-in library | Fit | Effort | Maintenance | Risk |
|---|---|---|---|---|
| **Authlib** (chosen) | Discovery, PKCE, nonce and ID token checks; documented for Starlette and FastAPI | Low | One library | Low |
| fastapi-users | Complete user management, which we do not need | Medium | In [maintenance mode](https://github.com/fastapi-users/fastapi-users): security fixes only | Medium |
| joserfc or python-jose alone | Tokens only | High: the sign-in flow and sessions by hand | Our own security code | High |
| oauthlib | Complete, but low-level | High: [no Starlette integration](https://github.com/oauthlib/oauthlib) | Glue code of our own | Medium |

| Database access | Fit | Effort | Maintenance | Risk |
|---|---|---|---|---|
| **SQLModel with Alembic** (chosen) | One class for table and validation; SQLAlchemy underneath for special SQL | Low | Same author as FastAPI; Alembic is SQLAlchemy's own tool | SQLModel is 0.0.x; the thin layer keeps the risk small |
| Plain SQLAlchemy 2 | Everything | Medium: a separate Pydantic model for every table | Very well known | Low |
| Django ORM | Mature | Only available inside Django | Known | Low |
| [Tortoise ORM](https://pypi.org/project/tortoise-orm/) | Async, similar to Django | Low | Less known | Marked Alpha on PyPI |
| Peewee | Small and simple | Async only through an [extension](https://docs.peewee-orm.com/en/latest/peewee/asyncio.html) | Known | Low |
| [Piccolo](https://piccolo-orm.readthedocs.io/en/latest/) | Async, with its own migrations | Low | Less known | Medium |

</details>

### Frontend: React

For the interface we chose **[React](https://react.dev)** with TypeScript, built with
[Vite](https://vite.dev/guide/). React is not the only option that fits. For today's screens –
forms, tables and a progress display – htmx with pages rendered on the server would work too. It
can [poll for updates](https://htmx.org/docs/#polling) with a single attribute. Its own
[guidance](https://htmx.org/essays/when-to-use-hypermedia/) only warns about pages with many updates
that depend on each other. We chose React for three reasons specific to InfraSales:

1. **The planned screens.** The project file with its timeline and evidence, the curation queue,
   filters over thousands of projects, a map and the customer area. That means a lot of state in
   the browser, which is where React is strong. The
   "run now" flow already keeps state in the browser: it reuses its request key across retries and
   keeps following a run through outages.
2. **A typed contract.** The interface's API types are generated from the backend's OpenAPI
   contract. A changed field breaks the build instead of the page.
3. **Accessibility checks in every component test.** [Testing Library](https://testing-library.com/docs/queries/about#priority)
   finds elements by their role, as assistive technology does, and
   [axe-core](https://github.com/dequelabs/axe-core) checks WCAG rules in the same tests.
   Colour contrast needs a real layout and is checked by hand, so an accessibility review stays part
   of going live.

All texts go through i18next, so a German interface can follow.

**Cost:** a second language (TypeScript) and toolchain (Node, pnpm, Vite) with their own packages to
keep up to date. This is the strongest argument for htmx, which would keep InfraSales to Python and
HTML. Renovate, the lockfile and the one-week release cooldown cover these packages as well.

<details><summary>Alternatives to React</summary>

| Option | Fit | Effort | Maintenance | Risk |
|---|---|---|---|---|
| **React** (chosen) | Rich state in the browser, a typed client, accessibility checks in component tests | Medium | TypeScript and Node to maintain; the most used frontend library (44.7% in the [Stack Overflow Developer Survey 2025](https://survey.stackoverflow.co/2025/technology)) | Low |
| htmx with pages rendered on the server | Good for today's screens (polling built in); harder for much state in the browser | Low now, higher for the planned screens | Python and HTML only | Low |
| [Vue](https://vuejs.org/guide/introduction.html) | Similar to React | Medium | Fewer people know it (17.6%) | Low |
| [Svelte](https://svelte.dev/docs/svelte/overview) | Similar, compiled | Medium | Fewest people know it (7.2%) | Low |
| [Angular](https://angular.dev/overview) | A complete framework | High for a small interface | 18.2% | Low |

</details>

### AI: Pydantic AI and Langfuse

For the AI logic we chose **[Pydantic AI](https://pydantic.dev/docs/ai/overview/)**:

- It works with **any model provider** through one interface, including
  [OpenAI-compatible APIs](https://pydantic.dev/docs/ai/models/openai/#openai-compatible-models)
  ([ADR 02](02_adr_openai_compatible_llm.md)), so we can switch models without code changes.
- It returns **typed results** checked by Pydantic. This matters when the classification
  must return structured data.
- Its [`TestModel`](https://pydantic.dev/docs/ai/guides/testing/) lets every test run **without
  calling – or paying for – a model**.
- It reports what it does through **OpenTelemetry**, so its traces reach Langfuse or any other
  backend.
- We install only what we use (`pydantic-ai-slim` and the `openai` client). Version 1 came out
  in September 2025 with a [stability promise](https://pydantic.dev/articles/pydantic-ai-v1),
  version 2 in June 2026 under a published
  [version policy](https://pydantic.dev/docs/ai/project/version-policy/).

**Cost:** a young framework with frequent releases. We pin it in the lockfile and update it with
tests.

For tracing we chose **[Langfuse](https://langfuse.com/docs)**. Its core is open source under the
[MIT licence](https://github.com/langfuse/langfuse/blob/main/LICENSE) and can be
[self-hosted](https://langfuse.com/self-hosting); its cloud has an
[EU region](https://langfuse.com/security/data-regions). It accepts OpenTelemetry directly,
[works with Pydantic AI](https://langfuse.com/integrations/frameworks/pydantic-ai), and adds what
work with language models needs: one session per run, prompt management, evaluations and cost
tracking. ClickHouse bought Langfuse in January 2026 and
[committed](https://langfuse.com/blog/joining-clickhouse) to keeping the core MIT-licensed and
self-hostable.

Detailed tracing causes overhead that is only worth it in production. So tracing – like every
other capability that is not needed – stays off unless it is configured. In the end the application
needs only a database to run (the language model is mocked by default), a language model provider
for real use, and an SMTP server to actually deliver mail. Everything else can be switched
on when needed.

<details><summary>Alternatives to Pydantic AI and Langfuse</summary>

| AI framework | Fit | Effort | Maintenance | Risk |
|---|---|---|---|---|
| **Pydantic AI** (chosen) | Any provider, typed results, a test model, OpenTelemetry | Low | One library, in the Pydantic style the backend already uses | Young: version 1 in 2025 |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) | Long-running agents with saved state and durable execution | Medium | A large ecosystem | Its durable execution duplicates our scheduler's run state and steps |
| [LangChain](https://docs.langchain.com/oss/python/langchain/overview) | The largest ecosystem; its agents are built on LangGraph | Medium | A large ecosystem | More layers than a weekly pipeline needs |
| The provider's own SDK only | The simplest option, fewest dependencies | Higher: retries, result checks, switching providers and tracing by hand | Small | Tied to one provider |

For a pipeline this simple, the provider's own SDK is the strongest alternative. Pydantic AI saves
us the result checks, provider switching, test model and tracing that we would otherwise write
ourselves.

| Tracing | Fit | Effort | Maintenance | Risk |
|---|---|---|---|---|
| **Langfuse** (chosen) | Traces of model calls, sessions, prompts, evaluations, costs; OpenTelemetry | Low | Open-source core (MIT), self-hostable, EU region | New owner since 2026; the core stays MIT (stated commitment) |
| An OTLP collector only (e.g. Grafana) | General traces, no views for model calls | Low | Already supported | Low |
| LangSmith | Tight LangChain integration | Low | Proprietary; self-hosting only in the [Enterprise plan](https://docs.langchain.com/langsmith/self-hosted) | Tied to one vendor |
| [Arize Phoenix](https://github.com/Arize-ai/phoenix) | OpenTelemetry-based, self-hostable | Low | Elastic License 2.0: source-available, not open source | Medium |
| [Logfire](https://pydantic.dev/logfire) | From the Pydantic team | Low | Closed-source server; self-hosting only for enterprise customers | Tied to one vendor |

</details>

### Internal architecture

At this stage the internal architecture implements the core functions and aims to be reliable,
failsafe and self-healing. Runs survive crashes and restarts. Another worker takes over
a crashed worker's run once its lease runs out. Failures are retried with growing pauses, and
recorded steps are skipped. A shutdown hands a running job back instead of losing it. The readiness
probe takes an
instance out of rotation while the database cannot be reached or its schema does not suit the
build. What each of these promises assumes, and where it ends, is listed under
[Guarantees and their limits](#guarantees-and-their-limits).

Errors are handled so that they can be debugged later. Every response carries a request ID, which
also appears in the structured logs. An unexpected error returns only that ID, never internal
details. A database outage returns 503 with `Retry-After`. Failing jobs raise alerts automatically
(see [Alerting](#alerting)), and every sign-in attempt, failed ones included, is recorded in the
audit trail – without the name when someone mistyped it.

#### Components

The monolith is split along its features. Each component is a Python package with its own tables,
API models, logic and routes:

| Component | Job |
|---|---|
| frontend | The browser interface: schedules, run now and run history, audit log |
| auth | Signs users in – built-in users for development, OpenID Connect in production – and keeps sessions on the server |
| audit | Records who did what, and when; admins can read the trail, nobody can change it through the application |
| config | Holds the global settings (today the two schedules) and refuses edits that would overwrite each other |
| jobs | The jobs themselves (Source Collection; the pipeline of ADR 06 §5 follows), their catalog and the "run now" endpoints |
| feeds | The Feeds: their table, one Lister per kind (RSS, sitemap, the APIs), the Feed endpoints ([ADR 03](03_adr_scraper_sink.md)) |
| fetch | The one way documents are got: public addresses only, a size cap, robots.txt, pauses, bot walls |
| extract | Turns a document's bytes into its text: HTML, PDF, passthrough; which extractor reads what |
| catalog | The `source` and `source_version` tables and their operations: write, check, list, retain, delete a Source Version |
| sink | Stores the files of each Source Version: a local volume today, S3 later (fsspec) |
| scheduler | Plans due runs, leases each to one worker, retries failures, keeps the run history and steps |
| ai | Builds the language model from the settings (an OpenAI-compatible API or a mock) and keeps to the service's rate limit |
| mail | Sends mail over SMTP, or logs it when no server is configured |
| alerts | Tells people when a job keeps failing or a Feed becomes blocked, by e-mail and/or webhook |
| core | The foundation: database, logging, telemetry, security headers, health checks; it imports no feature |

Where InfraSales talks to the outside world, a component depends on a small interface, and the
settings choose the implementation. This pattern is called ports and adapters. The interfaces are
`Mailer` (SMTP or log), `Notifier` (e-mail, webhook), `AuthProvider` (built-in or OpenID Connect),
the language `Model`, `JobTelemetry`, and the `Ledger` of delivered copies. The scrape job adds
`Lister` (one per Feed kind), `Fetcher` (`http` today), `Extractor` (HTML, PDF, passthrough), the
`Sink` (a local volume or S3) and the `Notice` a `Notifier` delivers (a failing run, a blocked
Feed). The job catalog is the
one place where they are wired together. So swapping an integration does not touch the job logic,
and tests replace integrations without mocking libraries.

The core endpoints:

| Method and path | What it does | Access |
|---|---|---|
| `GET /healthz`, `GET /readyz` | Liveness; readiness (database reachable, schema suits the build) | public |
| `GET /api/auth/login`, `GET /api/auth/callback` | OpenID Connect sign-in: redirect to the identity provider, then check its answer and start a session (development: `POST /api/auth/login` with built-in users) | public |
| `GET /api/auth/session` | Who is signed in, if anyone, and how sign-in works | public |
| `POST /api/auth/logout` | Ends the session, with OpenID Connect also at the identity provider | public, checked against cross-site requests |
| `GET /api/config` | Lists the settings | viewer, admin |
| `PUT /api/config/{key}` | Changes a schedule; needs the current revision (`If-Match`), otherwise 412 | admin |
| `POST /api/jobs/{job}/runs` | Run now: queues a run; safe to repeat with an `Idempotency-Key` | admin |
| `GET /api/jobs/{job}/runs`, `…/runs/active`, `…/runs/{run_id}` | Run history, the active manual run, the progress of one run | admin |
| `GET /api/audit-events` | The audit trail, filtered and paged; reading it is itself audited | admin |

The static interface is served from `/`. The interactive API documentation (`/docs`) and
`/openapi.json` are switched off. The API contract is the reviewed `openapi.json` in the repository,
from which the interface's types are generated.

Sign-in follows the OpenID Connect standards:

- the [authorization code flow](https://openid.net/specs/openid-connect-core-1_0.html#CodeFlowAuth)
  (OpenID Connect Core 1.0, § 3.1), with
  [ID token validation](https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation)
  (§ 3.1.3.7);
- the provider's settings from
  [OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html);
- logout through [RP-Initiated Logout 1.0](https://openid.net/specs/openid-connect-rpinitiated-1_0.html);
- all on top of [OAuth 2.0](https://www.rfc-editor.org/rfc/rfc6749) with PKCE
  ([RFC 7636](https://www.rfc-editor.org/rfc/rfc7636)) and the current
  [OAuth security best practice](https://www.rfc-editor.org/rfc/rfc9700) (RFC 9700).

#### Data model

Every table builds on a common **base table**: an `id` that is a UUID version 7, plus `created_at`
and `updated_at` timestamps. UUIDv7 IDs are unique without a central counter and sorted by time, so
new rows land at the end of the index and the run history can be paged by ID. A fixed naming rule
gives every index and constraint a predictable name, which keeps migrations easy to review.

| Table | Why it exists |
|---|---|
| `auth_session` | Sessions on the server: the browser holds only a random token; the database stores its hash, the pseudonymous user ID, the role and the expiry |
| `audit_event` | The audit trail, append-only; the application's database role may add to it, but never change or delete it |
| `config_entry` | The global settings, created by a migration; a `revision` counter makes a conflicting edit fail cleanly (`If-Match`, `ETag`) |
| `job_run` | One row per scheduled time or manual run: status, attempts, lease, result, progress of the current attempt, type of the last error |
| `job_step` | Work a run has finished, so that a retry can skip it |
| `job_trigger` | The key of each "run now" request and the run that answered it |

**How runs and steps work:**

- **Planning.** Every instance works out the latest due time of each active schedule and inserts it
  as a run. A unique rule on `(job, scheduled_for)` with `INSERT … ON CONFLICT DO NOTHING` makes
  this safe: however many instances plan at once, each scheduled time becomes exactly one run.
- **Taking a run.** A worker takes the oldest due run with `FOR UPDATE SKIP LOCKED` and gets a
  60-second lease on it. Other workers skip the rows being taken, so each attempt belongs to one
  worker.
- **Holding it.** While the job runs, its worker renews the lease every 15 seconds. If renewing
  fails for too long, or another worker has taken over, it stops the job itself.
- **Recovering.** If a worker crashes, its lease runs out and another worker takes the run over;
  this counts as an attempt. Failures are retried after 60 seconds, then 120 seconds, up to three
  attempts. Then the run fails for good and raises an alert. On shutdown, a running job gets a few
  seconds to finish; otherwise it goes back into the queue.
- **One at a time.** Partial unique indexes allow at most one running run per job, and at most one
  queued or running manual run. The database enforces this, even when requests race.
- **Steps.** A job records finished work as steps of its run. A retry starts the job again from the
  top, but skips every recorded step: a mail is not written again, and recipients recorded
  in the ledger (by a hash of their address) are skipped.

#### Guarantees and their limits

| What we promise | What it assumes | Where it ends | How we check it |
|---|---|---|---|
| One run per scheduled time | The unique rule on `(job, scheduled_for)` | – (the database enforces it) | Tests on SQLite and PostgreSQL |
| At most one running attempt per job | The partial unique index; taking a run skips jobs that are running | – (the database enforces it) | Tests with several workers on PostgreSQL |
| A crashed worker's run goes on | Another worker is running; the lease runs out after 60 seconds | A worker that freezes (rather than crashes) for longer than its lease may briefly overlap with the one that took over, until its next renewal fails | Tests for lost leases and takeovers |
| A retry does not redo finished work | The work was recorded as a step | Work after the last recorded step runs again, and effects outside the database can repeat ([`Steps.once`](../../src/infrasales/scheduler/steps.py)) | Tests for steps and retries |
| Each recipient gets a mail | The SMTP server accepts the copy, and the ledger records it | A copy accepted but not yet recorded is sent again: at least once, not exactly once | Tests for the mail ledger |
| Old instances keep working during an update | Every migration follows expand/contract | A change in meaning that the structure check cannot see | Review; `/readyz` checks the structure |
| The API, its contract and the interface agree | Shared field definitions; the checked-in contract; generated types | Separate read models (such as `ConfigEntry` and `ConfigEntryRead`) can drift in meaning | A test for `openapi.json`; the interface's lint checks its generated types |

So InfraSales runs every job at least once, and duplicates are kept small: a crash at the worst
moment repeats at most the work since the last recorded step.

## Requirements related to testing – Ensuring Correctness

The repository has strict guardrails: full test coverage, strict type checks and linting with all
rules. They may be relaxed later. For this baseline they help us find mistakes in the
security-relevant code early and keep them from coming back. They also let us update dependencies
quickly when a vulnerability appears, without putting the service and its data at risk.

Full coverage has a clear limit: it shows that every line and branch ran in a test, not that the
code is correct or secure. Our reviews found failure cases in fully covered code. So coverage is
one check among several:

- **Backend:** pytest with full line and branch coverage, run against SQLite and against
  PostgreSQL 18 (database roles, several workers at once, migrations). Every source module has a
  test module, which a test enforces. OpenID Connect is tested against an identity provider that
  runs inside the test process.
- **Frontend:** Vitest with full coverage; Testing Library tests that use the interface the way a
  person does, with axe-core accessibility checks.
- **Static checks:** ruff with all rules, pyright in strict mode, Biome, strict TypeScript.
- **Bugs:** every fix comes with a test that fails without the fix.
- **Reviews:** the scheduler and the security code went through several review rounds; that is
  where the failure cases above were found.
- **Gates:** hooks on every commit (formatting, linting, type checks, secret scanning with gitleaks,
  Conventional Commits) and the full test suite before every push.
- **Supply chain:** `uv audit` and `pnpm audit`, a Trivy scan of the container image, a CycloneDX
  software bill of materials, and Renovate updates after a waiting period of seven days.

A CI pipeline is not committed yet; `make ci` runs everything such a pipeline would check.

## References

All sources were accessed on 2026-10-04.

**Guidance and standards**

- W3C: [WCAG 2.1](https://www.w3.org/TR/WCAG21/), [WCAG 2.2](https://www.w3.org/TR/WCAG22/);
  ETSI [EN 301 549 V3.2.1](https://www.etsi.org/deliver/etsi_en/301500_301599/301549/03.02.01_60/en_301549v030201p.pdf)
- Datenschutzkonferenz, Standard Data Protection Model, module 43 "Protokollieren":
  <https://www.datenschutz-mv.de/static/DS/Dateien/Datenschutzmodell/Bausteine/SDM-V3.1_Protokollieren_V2.0.pdf>
- BSI IT-Grundschutz: [OPS.1.1.5 Protokollierung](https://www.bsi.bund.de/SharedDocs/Downloads/DE/BSI/Grundschutz/IT-GS-Kompendium_Einzel_PDFs_2023/04_OPS_Betrieb/OPS_1_1_5_Protokollierung_Edition_2023.pdf?__blob=publicationFile),
  [APP.3.1 Webanwendungen und Webservices](https://www.bsi.bund.de/SharedDocs/Downloads/DE/BSI/Grundschutz/IT-GS-Kompendium_Einzel_PDFs_2023/06_APP_Anwendungen/APP_3_1_Webanwendungen_und_Webservices_Edition_2023.pdf?__blob=publicationFile)
- OWASP: [Top 10:2025](https://top10.owasp.org/2025/),
  [Application Security Verification Standard 5.0](https://owasp.org/www-project-application-security-verification-standard/)
- NIST SP 800-218, Secure Software Development Framework: <https://csrc.nist.gov/pubs/sp/800/218/final>;
  SLSA v1.2: <https://slsa.dev/spec/v1.2/>
- OpenID Connect: [Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html),
  [Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html),
  [RP-Initiated Logout 1.0](https://openid.net/specs/openid-connect-rpinitiated-1_0.html)
- IETF: [RFC 6749](https://www.rfc-editor.org/rfc/rfc6749) (OAuth 2.0),
  [RFC 7636](https://www.rfc-editor.org/rfc/rfc7636) (PKCE),
  [RFC 9700](https://www.rfc-editor.org/rfc/rfc9700) (OAuth 2.0 Security Best Current Practice),
  [RFC 10017](https://www.rfc-editor.org/rfc/rfc10017) (OAuth 2.0 for Browser-Based Applications)
- The Twelve-Factor App: [III Config](https://12factor.net/config),
  [IV Backing services](https://12factor.net/backing-services);
  [Semantic Versioning](https://semver.org/); [Conventional Commits](https://www.conventionalcommits.org/)

**Surveys**

- JetBrains and Python Software Foundation, Python Developers Survey 2024: <https://lp.jetbrains.com/python-developers-survey-2024/>
- Stack Overflow Developer Survey 2025, Technology: <https://survey.stackoverflow.co/2025/technology>

**Frameworks and tools**

- uv: [documentation](https://docs.astral.sh/uv/), [benchmarks](https://github.com/astral-sh/uv/blob/main/BENCHMARKS.md),
  [lockfile](https://docs.astral.sh/uv/concepts/projects/layout/#the-lockfile),
  [dependency cooldowns](https://docs.astral.sh/uv/concepts/resolution/#dependency-cooldowns),
  [`uv audit`](https://docs.astral.sh/uv/reference/cli/#uv-audit); alternatives:
  [pip lock](https://pip.pypa.io/en/stable/cli/pip_lock/), [pip-tools](https://github.com/jazzband/pip-tools),
  [Poetry](https://python-poetry.org/docs/cli/#python), [PDM](https://pdm-project.org/en/latest/usage/uv/)
- FastAPI: [features](https://fastapi.tiangolo.com/features/),
  [versions](https://fastapi.tiangolo.com/deployment/versions/),
  [`OpenIdConnect`](https://fastapi.tiangolo.com/reference/security/#fastapi.security.OpenIdConnect),
  [SQL tutorial](https://fastapi.tiangolo.com/tutorial/sql-databases/); alternatives:
  [Django and async](https://docs.djangoproject.com/en/stable/topics/async/),
  [Django release process](https://docs.djangoproject.com/en/dev/internals/release-process/),
  [Flask](https://flask.palletsprojects.com/en/stable/), [Litestar](https://docs.litestar.dev/latest/)
- Authlib, Starlette client: <https://docs.authlib.org/en/stable/oauth2/client/web/starlette.html>;
  alternatives: [fastapi-users](https://github.com/fastapi-users/fastapi-users),
  [oauthlib](https://github.com/oauthlib/oauthlib)
- [SQLModel](https://sqlmodel.tiangolo.com/); [Alembic](https://alembic.sqlalchemy.org/en/latest/)
  and its [autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html);
  [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html); alternatives:
  [Tortoise ORM](https://pypi.org/project/tortoise-orm/),
  [Peewee asyncio](https://docs.peewee-orm.com/en/latest/peewee/asyncio.html),
  [Piccolo](https://piccolo-orm.readthedocs.io/en/latest/)
- PostgreSQL: [locking clause (`SKIP LOCKED`)](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE),
  [partial indexes](https://www.postgresql.org/docs/current/indexes-partial.html);
  [pgvector](https://github.com/pgvector/pgvector); MySQL 8.4:
  [`CREATE INDEX`](https://dev.mysql.com/doc/refman/8.4/en/create-index.html),
  [locking reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html); MariaDB:
  [`CREATE INDEX`](https://mariadb.com/kb/en/create-index/);
  [SQLite: appropriate uses](https://www.sqlite.org/whentouse.html)
- [React](https://react.dev), [Vite](https://vite.dev/guide/),
  [Testing Library query priority](https://testing-library.com/docs/queries/about#priority),
  [axe-core](https://github.com/dequelabs/axe-core); alternatives: htmx
  [polling](https://htmx.org/docs/#polling) and [when to use hypermedia](https://htmx.org/essays/when-to-use-hypermedia/),
  [Vue](https://vuejs.org/guide/introduction.html), [Svelte](https://svelte.dev/docs/svelte/overview),
  [Angular](https://angular.dev/overview)
- Pydantic AI: [overview](https://pydantic.dev/docs/ai/overview/),
  [OpenAI-compatible models](https://pydantic.dev/docs/ai/models/openai/#openai-compatible-models),
  [testing](https://pydantic.dev/docs/ai/guides/testing/),
  [version 1 announcement](https://pydantic.dev/articles/pydantic-ai-v1),
  [version policy](https://pydantic.dev/docs/ai/project/version-policy/); alternatives:
  [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview),
  [LangChain](https://docs.langchain.com/oss/python/langchain/overview)
- Langfuse: [documentation](https://langfuse.com/docs),
  [licence](https://github.com/langfuse/langfuse/blob/main/LICENSE),
  [self-hosting](https://langfuse.com/self-hosting), [data regions](https://langfuse.com/security/data-regions),
  [Pydantic AI integration](https://langfuse.com/integrations/frameworks/pydantic-ai),
  [joining ClickHouse](https://langfuse.com/blog/joining-clickhouse); alternatives:
  [LangSmith self-hosting](https://docs.langchain.com/langsmith/self-hosted),
  [Arize Phoenix](https://github.com/Arize-ai/phoenix), [Logfire](https://pydantic.dev/logfire)

**Scheduling**

- Kubernetes, CronJob: <https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/>
- [anacron(8)](https://man7.org/linux/man-pages/man8/anacron.8.html),
  [systemd.timer(5)](https://man7.org/linux/man-pages/man5/systemd.timer.5.html)
- Procrastinate: [documentation](https://procrastinate.readthedocs.io/en/stable/),
  [periodic tasks and dynamic scheduling](https://procrastinate.readthedocs.io/en/stable/howto/advanced/cron.html#dynamic-scheduling),
  [retries](https://procrastinate.readthedocs.io/en/stable/howto/advanced/retry.html),
  [locks](https://procrastinate.readthedocs.io/en/stable/howto/advanced/locks.html),
  [stalled jobs](https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html),
  [cancellation](https://procrastinate.readthedocs.io/en/stable/howto/advanced/cancellation.html),
  [migrations](https://procrastinate.readthedocs.io/en/stable/howto/production/migrations.html),
  [releases on PyPI](https://pypi.org/project/procrastinate/#history)
- Other PostgreSQL-backed job queues: [Solid Queue](https://github.com/rails/solid_queue),
  [pg-boss](https://github.com/timgit/pg-boss)
- [APScheduler 3.x FAQ](https://apscheduler.readthedocs.io/en/3.x/faq.html),
  [Celery periodic tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)

**Architecture**

- Martin Fowler: [MonolithFirst](https://martinfowler.com/bliki/MonolithFirst.html),
  [MicroservicePremium](https://martinfowler.com/bliki/MicroservicePremium.html)
- Shopify Engineering, Deconstructing the Monolith: <https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity>
- Michael Nygard, Documenting Architecture Decisions: <https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions>
