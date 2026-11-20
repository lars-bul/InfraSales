"""What the Feed API reads and writes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from infrasales.core.fields import ExactUrl
from infrasales.core.models import JSONValue
from infrasales.extract import registry
from infrasales.feeds import kinds
from infrasales.feeds.models import MAX_URL_LENGTH, FeedCategory, FeedKind, FeedState
from infrasales.fetch.fetcher import FetcherName

type Address = Annotated[ExactUrl, Field(max_length=MAX_URL_LENGTH)]


class FeedCreate(BaseModel):
    """A Feed to add; its slug is derived from its name."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    kind: FeedKind
    url: Address  # the feed, sitemap or API address, kept exactly as given
    category: FeedCategory = Field(default=FeedCategory.PRESS, description="What the Feed is")
    settings: dict[str, JSONValue] = Field(
        default_factory=dict[str, JSONValue],
        validate_default=True,  # the kind may need settings
        description="What the kind's Lister needs",
    )
    extractor: str | None = Field(default=None, description="Reads every document of the Feed")

    @field_validator("kind")
    @classmethod
    def _readable(cls, kind: FeedKind) -> FeedKind:
        if kind not in kinds.LISTERS:
            msg = f"Feeds of kind {kind} cannot be read yet"
            raise ValueError(msg)
        return kind

    @field_validator("settings")
    @classmethod
    def _settings_of_the_kind(
        cls, settings: dict[str, JSONValue], info: ValidationInfo
    ) -> dict[str, JSONValue]:
        """The settings as the kind's Lister reads them; unknown keys are refused."""
        if (kind := info.data.get("kind")) is None:  # the kind was refused already
            return settings
        model = kinds.LISTERS[kind].settings
        try:
            return model.model_validate(settings).model_dump(mode="json", exclude_unset=True)
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(map(str, problem['loc'])) or 'settings'}: {problem['msg']}"
                for problem in error.errors()
            )
            msg = f"invalid settings for kind {kind}: {problems}"
            raise ValueError(msg) from None

    @field_validator("extractor")
    @classmethod
    def _known_extractor(cls, extractor: str | None) -> str | None:
        if extractor is not None and extractor not in registry.EXTRACTORS:
            msg = f"no extractor named {extractor!r}"
            raise ValueError(msg)
        return extractor


class FeedRead(BaseModel):
    id: UUID
    name: str
    slug: str  # names the Feed's folders in the sink
    kind: FeedKind
    category: FeedCategory
    url: str
    settings: dict[str, JSONValue]
    fetcher: FetcherName
    extractor: str | None
    enabled: bool
    state: FeedState
    last_error: str | None
    last_scraped_at: datetime | None
    created_at: datetime
    has_sources: bool  # Sources name it: it cannot be deleted
    sources: int  # the Sources its latest version came from: those `?feed=<slug>` lists


class SuggestRequest(BaseModel):
    url: Address  # a site's address, e.g. its home page


class Suggestion(BaseModel):
    """What to add for a site: its kind and the address of its feed or sitemap."""

    name: str  # the site's title, else its host
    kind: FeedKind
    url: str
