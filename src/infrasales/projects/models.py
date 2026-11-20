"""The project file (ADR 06): municipalities, actors, projects, their claims and status events.

These are public facts: they belong to no tenant. Every value of a project is a claim with its
evidence; what a project shows (`Project.facts`, `Project.phase`) is computed from its accepted
claims and status events (`infrasales.projects.facts`), never written by hand.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field

from infrasales.core.models import (
    SUBJECT_LENGTH,
    BaseTable,
    JSONType,
    JSONValue,
    UTCDateTime,
    enum_type,
)

AGS_LENGTH = 8  # the official municipality key: Land 2, Regierungsbezirk 1, Kreis 2, Gemeinde 3
POST_CODE_LENGTH = 10  # five digits in Germany; room for a neighbour country's
MAX_NAME_LENGTH = 300
MAX_QUOTE_LENGTH = 2000  # a sentence or two: a quote proves a claim, it does not copy a page


class Sector(StrEnum):
    """The kind of infrastructure a project builds; each has its own facts (`sectors`)."""

    HEAT_NETWORK = "heat_network"


class Phase(StrEnum):
    """Where a project stands, in the order of its life; the same in every sector."""

    HEAT_PLAN = "heat_plan"  # an area the municipal heat plan finds suitable
    STUDY = "study"  # a feasibility study is commissioned or done
    DECISION = "decision"  # a council or board decided to build
    FUNDING = "funding"  # public funding granted (e.g. BEW)
    TENDER = "tender"  # planning or construction put out to tender
    AWARD = "award"  # a contract was awarded
    CONSTRUCTION = "construction"
    OPERATION = "operation"
    CANCELLED = "cancelled"  # stopped: it leaves the order above


PHASES = [phase for phase in Phase if phase is not Phase.CANCELLED]


class ProjectKind(StrEnum):
    NEW_BUILD = "new_build"  # a network where there is none
    EXTENSION = "extension"  # an existing network grows
    CONVERSION = "conversion"  # an existing network moves to renewable heat


class Publication(StrEnum):
    DRAFT = "draft"  # not checked yet: only the back office sees it
    PUBLISHED = "published"  # customers see it, as far as their entitlement reaches
    WITHDRAWN = "withdrawn"  # was published, no longer shown; its ID stays reserved


class ActorKind(StrEnum):
    """What an organisation is. People are never actors (ADR 06 §8)."""

    UTILITY = "utility"  # a Stadtwerk or regional supplier
    NETWORK_OPERATOR = "network_operator"
    PLANNER = "planner"  # an engineering or planning office
    CONTRACTOR = "contractor"  # civil works, pipe laying, plant construction
    MANUFACTURER = "manufacturer"
    ADMINISTRATION = "administration"  # a municipality's, district's or state's administration
    # Private builders (ADR 06 §5): they build heat networks outside public procurement, mostly.
    ENERGY_SERVICE = "energy_service"  # contracting, energy service companies
    COOPERATIVE = "cooperative"  # energy cooperatives, Bioenergiedörfer
    HOUSING = "housing"  # housing companies with district networks
    DEVELOPER = "developer"  # project developers of new quarters
    INDUSTRY = "industry"  # companies with waste heat
    OTHER = "other"


class ActorRole(StrEnum):
    """What an actor does in one project."""

    OWNER = "owner"  # the Vorhabenträger: who builds and pays
    OPERATOR = "operator"
    PLANNER = "planner"
    CONTRACTOR = "contractor"
    SUPPLIER = "supplier"
    FUNDER = "funder"


class Origin(StrEnum):
    """Who made a claim, in rising precedence: a curator's claim beats a model's."""

    MODEL = "model"
    DATASET = "dataset"  # a structured dataset: OCDS, the Marktstammdatenregister, …
    MUNICIPALITY = "municipality"  # the municipality itself, as a customer
    CONTRACTING_AUTHORITY = "contracting_authority"  # a utility or operator, e.g. in its preview
    CURATOR = "curator"


class ClaimState(StrEnum):
    PENDING = "pending"  # waits for a curator
    ACCEPTED = "accepted"  # counts for the project's facts
    REJECTED = "rejected"  # kept, so the same mistake is recognised again


class Municipality(BaseTable, table=True):
    """A municipality, by its official key: the backbone of every region (an AGS prefix)."""

    ags: str = Field(max_length=AGS_LENGTH, unique=True)
    name: str = Field(max_length=200)
    population: int | None = Field(default=None, ge=0)
    population_as_of: date | None = None
    area_km2: float | None = Field(default=None, gt=0)
    post_code: str | None = Field(default=None, max_length=POST_CODE_LENGTH)  # its town hall's
    latitude: float | None = Field(default=None, ge=-90, le=90)  # its geographic centre
    longitude: float | None = Field(default=None, ge=-180, le=180)
    urbanisation: int | None = Field(
        default=None, ge=1, le=3
    )  # 1 dense, 2 middle, 3 thin (Eurostat)


class PostCode(BaseTable, table=True):
    """Where a post code lies: per locality and municipality, by how many of its streets do.

    From OpenPLZ (OpenStreetMap, ODbL); `infrasales.sources.places` resolves notices' addresses.
    The municipality is no foreign key: OpenStreetMap may know a merger before Destatis does.
    """

    __table_args__ = (UniqueConstraint("post_code", "locality", "municipality_ags"),)

    post_code: str = Field(max_length=POST_CODE_LENGTH, index=True)
    locality: str = Field(max_length=200)
    municipality_ags: str = Field(max_length=AGS_LENGTH)
    streets: int = Field(ge=1)


class Actor(BaseTable, table=True):
    """An organisation that takes part in projects. Merged into another, it points there."""

    name: str = Field(max_length=MAX_NAME_LENGTH, index=True)
    kind: ActorKind = Field(sa_type=enum_type(ActorKind))
    seat_ags: str | None = Field(
        default=None, foreign_key="municipality.ags", max_length=AGS_LENGTH, index=True
    )
    register_id: str | None = Field(default=None, max_length=100)  # e.g. "HRB 12345, AG Ulm"
    mastr_id: str | None = Field(default=None, max_length=20, unique=True)  # Marktstammdaten
    merged_into_id: uuid.UUID | None = Field(default=None, foreign_key="actor.id")


class Project(BaseTable, table=True):
    """A project in a municipality, under an ID that is never given out again.

    `phase` and `facts` are what its status events and accepted claims say now; a merged project
    points at the one it became, and its ID leads there.
    """

    __table_args__ = (Index("ix_project_sector_municipality_ags", "sector", "municipality_ags"),)

    public_id: str = Field(max_length=16, unique=True)  # `infrasales.projects.ids`
    sector: Sector = Field(sa_type=enum_type(Sector))
    kind: ProjectKind | None = Field(default=None, sa_type=enum_type(ProjectKind))
    title: str = Field(max_length=MAX_NAME_LENGTH)
    municipality_ags: str = Field(foreign_key="municipality.ags", max_length=AGS_LENGTH)
    phase: Phase | None = Field(default=None, sa_type=enum_type(Phase))
    publication: Publication = Field(
        default=Publication.DRAFT, sa_type=enum_type(Publication), index=True
    )
    facts: dict[str, JSONValue] = Field(default_factory=dict, sa_type=JSONType)  # per sector
    facts_version: int = 1  # of the sector's facts schema they were computed with
    merged_into_id: uuid.UUID | None = Field(default=None, foreign_key="project.id")


class Claim(BaseTable, table=True):
    """One statement about a project, with where it stands and who made it.

    New readings add claims; none is overwritten. Its evidence is a Source Version, a page and a
    quote copied word for word (`quote_found`: the quote stands in that version's text).
    """

    __table_args__ = (Index("ix_claim_project_id_field", "project_id", "field"),)

    project_id: uuid.UUID = Field(foreign_key="project.id")
    field: str = Field(max_length=64)  # a field of the sector's facts, or "title", "kind", …
    value: JSONValue = Field(sa_type=JSONType, nullable=False)  # alias hides that None is refused
    source_version_id: uuid.UUID | None = Field(
        default=None, foreign_key="source_version.id", index=True
    )
    page: int | None = Field(default=None, ge=1)  # 1-based, in the document as stored
    quote: str | None = Field(default=None, max_length=MAX_QUOTE_LENGTH)
    quote_found: bool = False
    origin: Origin = Field(sa_type=enum_type(Origin))
    origin_detail: str = Field(default="", max_length=255)  # model and version, dataset, …
    state: ClaimState = Field(default=ClaimState.PENDING, sa_type=enum_type(ClaimState), index=True)
    reviewed_by: str | None = Field(default=None, max_length=SUBJECT_LENGTH)
    reviewed_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    # The run that made it; job runs are pruned long before claims, which then keep NULL.
    run_id: uuid.UUID | None = Field(
        default=None, foreign_key="job_run.id", ondelete="SET NULL", index=True
    )


class ProjectActor(BaseTable, table=True):
    """That an actor has a role in a project, as a claim says."""

    __table_args__ = (UniqueConstraint("project_id", "actor_id", "role"),)

    project_id: uuid.UUID = Field(foreign_key="project.id")
    actor_id: uuid.UUID = Field(foreign_key="actor.id", index=True)
    role: ActorRole = Field(sa_type=enum_type(ActorRole))
    claim_id: uuid.UUID | None = Field(default=None, foreign_key="claim.id")


class ProjectEvent(BaseTable, table=True):
    """A project reaching a phase: when it happened, and since when we know (ADR 06 §2).

    `known_since` is when the first document saying so was collected, never later: the backtest
    counts a signal's lead time from it.
    """

    __table_args__ = (Index("ix_project_event_project_id_phase", "project_id", "phase"),)

    project_id: uuid.UUID = Field(foreign_key="project.id")
    phase: Phase = Field(sa_type=enum_type(Phase))
    occurred_on: date | None = None  # None: the documents give no date
    known_since: datetime = Field(sa_type=UTCDateTime, index=True)
    claim_id: uuid.UUID = Field(foreign_key="claim.id")


class SignalKind(StrEnum):
    """What a signal tells about a municipality's way to a heat network (ADR 06 §7)."""

    HEAT_PLAN_STARTED = "heat_plan_started"  # the municipal heat planning began
    HEAT_PLAN_ADOPTED = "heat_plan_adopted"  # the council adopted the heat plan
    FEASIBILITY_STUDY = "feasibility_study"  # commissioned or done, e.g. under BEW module 1
    COUNCIL_DECISION = "council_decision"  # to build, extend or convert a network
    FUNDING_GRANTED = "funding_granted"  # BEW or a state programme
    ROADMAP_PUBLISHED = "roadmap_published"  # an operator's heat network roadmap (WPG)
    HEAT_COMPANY_FOUNDED = "heat_company_founded"  # a company to build or run heat networks
    JOB_POSTING = "job_posting"  # a utility hires for heat networks
    HEAT_SOURCE_PROJECT = "heat_source_project"  # a large heat pump, waste heat, geothermal
    BUDGET_ALLOCATED = "budget_allocated"  # a budget line or a loan authorisation
    GAS_CONCESSION_ENDS = "gas_concession_ends"  # `occurred_on`: the day it ends


class Signal(BaseTable, table=True):
    """Evidence that a municipality moves towards a heat network, before or beside any project.

    `available_on` is the first day the public could know it: a document's publication, or the day
    we collected it if that is all we know. A forecast only uses what was available by its date,
    so a backtest never learns from the future (ADR 06 §2, two time axes).
    """

    __table_args__ = (
        Index("ix_signal_municipality_ags_available_on", "municipality_ags", "available_on"),
    )

    kind: SignalKind = Field(sa_type=enum_type(SignalKind))
    municipality_ags: str = Field(foreign_key="municipality.ags", max_length=AGS_LENGTH)
    project_id: uuid.UUID | None = Field(default=None, foreign_key="project.id")
    actor_id: uuid.UUID | None = Field(default=None, foreign_key="actor.id")
    occurred_on: date | None = None  # None: the evidence gives no date
    available_on: date
    ref: str = Field(max_length=512, unique=True)  # where it is from: an import can be repeated
    note: str = Field(default="", max_length=MAX_NAME_LENGTH)
    url: str | None = Field(default=None, max_length=2048)
    claim_id: uuid.UUID | None = Field(default=None, foreign_key="claim.id")


class MetricKind(StrEnum):
    """A figure about a municipality that a forecast may use."""

    POPULATION = "population"
    DWELLINGS = "dwellings"  # Wohnungen, from the census
    GAS_HEATING_SHARE = "gas_heating_share"  # 0 to 1, of buildings heated by gas
    DISTRICT_HEATING_SHARE = "district_heating_share"  # 0 to 1, of buildings on district heat
    OIL_HEATING_SHARE = "oil_heating_share"  # 0 to 1, of buildings heated by oil
    HEAT_PUMP_SHARE = "heat_pump_share"  # 0 to 1, heat pumps, solar or geothermal heat
    MULTI_FAMILY_SHARE = "multi_family_share"  # 0 to 1, of buildings with 7 or more dwellings
    HOUSING_COMPANY_SHARE = "housing_company_share"  # 0 to 1, owned by a municipality,
    # a cooperative or a housing company: few owners decide for many dwellings
    OLD_BUILDING_SHARE = "old_building_share"  # 0 to 1, built before 1979
    BUILDINGS = "buildings"  # with dwellings


class MunicipalityMetric(BaseTable, table=True):
    """A figure about a municipality as of a day, from a named source, public since a day."""

    __table_args__ = (UniqueConstraint("municipality_ags", "metric", "as_of", "source"),)

    municipality_ags: str = Field(foreign_key="municipality.ags", max_length=AGS_LENGTH)
    metric: MetricKind = Field(sa_type=enum_type(MetricKind))
    as_of: date  # the day the figure describes, e.g. the census day
    available_on: date  # the day it was published
    value: float
    source: str = Field(max_length=100)  # e.g. "zensus-2022"


class TenderKind(StrEnum):
    PLANNING = "planning"  # planning services, e.g. from Leistungsphase 2
    CONSTRUCTION = "construction"  # civil works and pipe laying: what forecasts are about
    SUPPLY = "supply"  # pipes, fittings, heat pumps
    SERVICE = "service"  # operation, maintenance, other services


class TenderStatus(StrEnum):
    PLANNED = "planned"  # announced, not yet published (Vergabevorschau, prior information)
    PUBLISHED = "published"
    AWARDED = "awarded"
    CANCELLED = "cancelled"


class TenderOrigin(StrEnum):
    """Where a tender comes from (ADR 06 §5)."""

    NOTICE = "notice"  # a public notice: TED, the Datenservice Öffentlicher Einkauf (OCDS)
    PREVIEW = "preview"  # a contracting authority's Vergabevorschau: open to all
    PRIVATE_REQUEST = "private_request"  # a private builder's request: for subscribers only


class Tender(BaseTable, table=True):
    """A contract to be awarded for a project: planning, construction or supply, or one lot of it.

    Unique by origin and `ref` (the notice's number, the preview entry's or request's id), so an
    import can be repeated. `available_on` is when the public could first know of it.
    """

    __table_args__ = (
        UniqueConstraint("origin", "ref"),
        Index("ix_tender_municipality_ags_published_on", "municipality_ags", "published_on"),
        Index("ix_tender_buyer_name_published_on", "buyer_name", "published_on"),
    )

    origin: TenderOrigin = Field(sa_type=enum_type(TenderOrigin))
    ref: str = Field(max_length=200)
    sector: Sector = Field(default=Sector.HEAT_NETWORK, sa_type=enum_type(Sector))
    kind: TenderKind = Field(sa_type=enum_type(TenderKind))
    status: TenderStatus = Field(sa_type=enum_type(TenderStatus))
    title: str = Field(max_length=500)
    # Where the work is done; None until it is resolved to a municipality.
    municipality_ags: str | None = Field(
        default=None, foreign_key="municipality.ags", max_length=AGS_LENGTH
    )
    project_id: uuid.UUID | None = Field(default=None, foreign_key="project.id", index=True)
    buyer_actor_id: uuid.UUID | None = Field(default=None, foreign_key="actor.id")
    buyer_name: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    lot: str | None = Field(default=None, max_length=100)
    framework: bool = False  # a framework agreement over several years
    procedure: str | None = Field(default=None, max_length=64)  # open, restricted, negotiated, …
    cpv: list[str] = Field(default_factory=list[str], sa_type=JSONType)
    available_on: date
    published_on: date | None = None
    deadline_on: date | None = None
    awarded_on: date | None = None
    contract_end_on: date | None = None  # a framework's or contract's end: a new tender may follow
    offers: int | None = Field(default=None, ge=0)
    estimated_value_eur: int | None = Field(default=None, ge=0)
    award_value_eur: int | None = Field(default=None, ge=0)
    winner_actor_id: uuid.UUID | None = Field(default=None, foreign_key="actor.id")
    winner_name: str | None = Field(default=None, max_length=MAX_NAME_LENGTH)
    url: str | None = Field(default=None, max_length=2048)
    source_version_id: uuid.UUID | None = Field(default=None, foreign_key="source_version.id")
    exclusive: bool = False  # a private request offered to subscribers only (ADR 06 §5)
    # Where a notice came from and how it hangs together: its source ("ted", "doe", "csv"), the
    # procedure its notices share (prior information, contract notice, award), the notice's type.
    source: str = Field(default="csv", max_length=16)
    procedure_ref: str | None = Field(default=None, max_length=100, index=True)
    notice_type: str | None = Field(default=None, max_length=32)  # eForms, e.g. "cn-standard"
    # Where the buyer sits and where the work is done, as the notice says.
    buyer_post_code: str | None = Field(default=None, max_length=POST_CODE_LENGTH)
    buyer_city: str | None = Field(default=None, max_length=200)
    place_post_code: str | None = Field(default=None, max_length=POST_CODE_LENGTH)
    place_city: str | None = Field(default=None, max_length=200)
    place_nuts: str | None = Field(default=None, max_length=8)  # NUTS 3, e.g. "DE125"
    # The form of the award (ADR 06 §7): how many lots, how long, decided how.
    lots: int | None = Field(default=None, ge=1)  # lots of the whole procedure
    duration_months: float | None = Field(default=None, ge=0)
    price_only: bool | None = None  # awarded by price alone, no quality criterion
    sme_suitable: bool | None = None
    lowest_offer_eur: int | None = Field(default=None, ge=0)
    highest_offer_eur: int | None = Field(default=None, ge=0)
    # Whether it concerns a heat network, and the rule that says so (`infrasales.sources.heat`).
    heat_network: bool = True
    relevance: str = Field(default="", max_length=64)


class TenderAward(BaseTable, table=True):
    """Who won a tender (a lot), as the award notice says.

    A lot may have several winners: a framework agreement with several contractors.
    """

    __table_args__ = (UniqueConstraint("tender_id", "winner_name"),)

    tender_id: uuid.UUID = Field(foreign_key="tender.id", ondelete="CASCADE")
    winner_name: str = Field(max_length=MAX_NAME_LENGTH, index=True)
    winner_identifier: str | None = Field(default=None, max_length=100)  # e.g. a VAT number
    winner_post_code: str | None = Field(default=None, max_length=POST_CODE_LENGTH)
    winner_city: str | None = Field(default=None, max_length=200)
    winner_country: str | None = Field(default=None, max_length=3)  # ISO 3166-1 alpha-3
    winner_size: str | None = Field(default=None, max_length=16)  # micro, small, medium, large
    winner_ags: str | None = Field(default=None, max_length=AGS_LENGTH)  # resolved from its address
    value_eur: int | None = Field(default=None, ge=0)
    actor_id: uuid.UUID | None = Field(default=None, foreign_key="actor.id")
