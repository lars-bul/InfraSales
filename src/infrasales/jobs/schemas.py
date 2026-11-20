"""A job's runs as the run history shows them: who started each one, and what it did."""

from pydantic import BaseModel, ValidationError

from infrasales.core.models import JSONValue
from infrasales.jobs.names import JobName
from infrasales.scheduler.schemas import ActivityQuery, JobRunRead, RunQuery


class FailedFeed(BaseModel):
    feed: str  # the Feed's slug
    reason: str  # its `last_error`: "blocked", "http 404", …


class FeedOverlap(BaseModel):
    """Which of a Feed's addresses other Feeds list too (`scrape.FeedOverlap`, as stored)."""

    own: int  # addresses only it lists
    shared: int  # addresses another Feed lists too
    listed_with: dict[str, int]  # by the other Feed's slug: listed by both in the run
    filed_under: dict[str, int]  # by the other Feed's slug: filed under it before the run


class FeedOutcome(BaseModel):
    """How a Source Collection run read one Feed (`scrape.FeedOutcome`, as stored)."""

    feed: str  # the Feed's slug
    items: int  # listed: 0 when the listing failed or was out of time
    new: int  # stored as new Source Versions: new URLs, or changed texts
    unchanged: int  # known, checked again, the same text
    known: int  # known, not due for a check yet
    seen: int  # listed before in the run, by this Feed or another
    failed: int  # could not be got or read: skipped
    unread: int | None  # listed, left for the next run; None: not even listed
    reason: str | None  # the Feed failed: its `last_error`; None: it did not
    out_of_time: bool  # its share of the run's time was used up
    seconds: float  # how long reading it took
    overlap: FeedOverlap | None = None  # None in results stored before it was counted
    walled: list[str] = []  # other sites whose bot wall kept documents from it; none before


class SourceCollectionResult(BaseModel):
    """What a finished Source Collection run did (`ScrapeResult`, as stored)."""

    feeds_read: int  # enabled Feeds it tried to read, failed ones included
    versions_new: int  # Source Versions committed
    versions_unchanged: int  # known Sources checked again and found unchanged
    documents_failed: int  # listed documents that could not be got or read
    failed_feeds: list[FailedFeed]
    feeds: list[FeedOutcome] = []  # each Feed, in reading order; none in older results


class FeedUnderway(BaseModel):
    """The Feed a running Source Collection reads now (`scrape.Underway`, as reported)."""

    feed: str  # the Feed's slug
    items: int | None  # listed; None: still listing
    done: int  # items handled so far, whatever became of them
    new: int  # stored as new Source Versions so far


class SourceCollectionProgress(BaseModel):
    """How far a running Source Collection got (`ScrapeResult.progress`, as reported)."""

    feeds_total: int  # the enabled Feeds it reads
    feeds_done: int  # read to the end so far, failed ones included
    versions_new: int  # Source Versions committed so far
    current: FeedUnderway | None  # the Feed being read; None between two
    latest: FeedOutcome | None  # the Feed read to the end last; None before the first


class RunProgress(JobRunRead):
    """A run as "Run now" follows it: where to look into it, how often tried, how far it got."""

    langfuse_url: str | None = None
    max_attempts: int  # the scheduler's limit, as configured: "attempt 2 of 3"
    # How far its latest attempt got, as last reported; finished, how far the last one got. None
    # while it waits for an attempt or its first report, and for jobs that report none.
    progress: SourceCollectionProgress | None = None


class RunHistoryEntry(RunProgress):
    """A run in the run history."""

    triggered_by: str | None  # the admin's pseudonymous subject; None: the schedule started it
    # None while it runs. Only Source Collection's result has a type so far.
    result: SourceCollectionResult | None


class JobRunsQuery(RunQuery):
    """Which runs to read across the jobs: of one job if asked, else of every job."""

    job: JobName | None = None


class JobsActivityQuery(ActivityQuery):
    """Which runs to count over time across the jobs: of one job if asked, else of every job."""

    job: JobName | None = None


def typed_result(job: str, stored: JSONValue) -> SourceCollectionResult | None:
    """A run's stored result as the history shows it; None for one stored in an older shape."""
    return _typed(SourceCollectionResult, job, stored)


def typed_progress(job: str, stored: JSONValue) -> SourceCollectionProgress | None:
    """A run's reported progress as "Run now" shows it; None for one in another shape."""
    return _typed(SourceCollectionProgress, job, stored)


def _typed[T: BaseModel](model: type[T], job: str, stored: JSONValue) -> T | None:
    if job != JobName.SCRAPE or stored is None:
        return None
    try:
        return model.model_validate(stored)
    except ValidationError:
        return None
