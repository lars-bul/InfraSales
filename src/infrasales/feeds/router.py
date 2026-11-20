import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status

from infrasales.audit import service as audit
from infrasales.auth.deps import AdminUser
from infrasales.core.db import Session
from infrasales.core.state import StateKey
from infrasales.feeds import discovery, service
from infrasales.feeds.models import Feed
from infrasales.feeds.schemas import FeedCreate, FeedRead, Suggestion, SuggestRequest
from infrasales.fetch.fetcher import BlockedError, FetchError
from infrasales.fetch.http import Network, UnsafeUrlError
from infrasales.fetch.pacing import OutOfTimeError
from infrasales.fetch.robots import RobotsError

router = APIRouter(prefix="/api/feeds", tags=["feeds"])

NETWORK = StateKey[Network]("network")  # how suggestions reach the web; unset: the real one


@router.get("")
async def list_feeds(_: AdminUser, session: Session) -> list[FeedRead]:
    """Every Feed by name (admins only), with its state: which Feeds work, and why not.

    `sources` counts the Sources its latest versions came from, as `/sources?feed=` lists them;
    `has_sources` says whether it may be deleted.
    """
    return [
        read(feed, has_sources=has, sources=sources)
        for feed, has, sources in await service.listing(session)
    ]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "A Feed has that address already"}},
)
async def add_feed(
    body: FeedCreate, admin: AdminUser, session: Session, request: Request
) -> FeedRead:
    """Add a Feed (admins only): the next scrape reads it. Its slug comes from its name.

    The kind must be one InfraSales reads; its Lister checks the settings. Adding is audited.
    """
    feed = await service.add(session, body)
    if feed is None:
        raise HTTPException(409, "A Feed has that address already")
    audit.record(
        session,
        actor=admin.subject,
        action="feed.created",
        target=feed.slug,
        details={"kind": feed.kind.value, "url": feed.url},
        request=request,
    )
    return read(feed, has_sources=False, sources=0)


@router.delete(
    "/{feed_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"description": "No Feed has that ID"},
        409: {"description": "The Feed has collected Sources"},
    },
)
async def delete_feed(
    feed_id: uuid.UUID, admin: AdminUser, session: Session, request: Request
) -> Response:
    """Delete a Feed that has collected no Sources yet (admins only), e.g. one added by mistake.

    A Feed with Sources stays: the catalog keeps where each Source came from. Deleting is audited.
    """
    try:
        feed = await service.remove(session, feed_id)
    except service.HasSourcesError:
        raise HTTPException(409, "The Feed has collected Sources, so it stays") from None
    if feed is None:
        raise HTTPException(404, "No Feed has that ID")
    audit.record(
        session,
        actor=admin.subject,
        action="feed.deleted",
        target=feed.slug,
        details={"kind": feed.kind.value, "url": feed.url},
        request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def read(feed: Feed, *, has_sources: bool, sources: int) -> FeedRead:
    return FeedRead.model_validate(
        feed.model_dump() | {"has_sources": has_sources, "sources": sources}
    )


@router.post(
    "/suggest",
    responses={
        422: {"description": "The address is not allowed or not readable, or offers no Feed"},
        504: {"description": "The site did not answer in time"},
    },
)
async def suggest_feed(body: SuggestRequest, _: AdminUser, request: Request) -> Suggestion:
    """Suggest the Feed to add for a site (admins only): its feed, else its sitemap.

    Looks at the page's feed links, usual feed paths and the sitemaps robots.txt names,
    obeying robots.txt and pausing between requests, for at most 20 seconds. Nothing is stored.
    """
    try:
        found = await discovery.suggest(body.url, NETWORK.find(request) or Network())
    except UnsafeUrlError:
        raise HTTPException(422, "That address is not allowed") from None
    except BlockedError:
        raise HTTPException(422, "That site blocks InfraSales' bot") from None
    except RobotsError:
        raise HTTPException(422, "robots.txt does not let InfraSales read that address") from None
    except FetchError:
        raise HTTPException(422, "That address could not be read") from None
    except discovery.NothingFoundError:
        raise HTTPException(422, "Neither a feed nor a sitemap was found there") from None
    except TimeoutError:
        raise HTTPException(504, "The site did not answer in time") from None
    except OutOfTimeError:
        raise HTTPException(504, "The site asks for longer pauses than a suggestion has") from None
    return Suggestion(name=found.name, kind=found.kind, url=found.url)
