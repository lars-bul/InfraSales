import json
from collections.abc import Callable

import httpx2
import pytest

from infrasales.alerts.webhook import WebhookError, WebhookNotifier
from tests.alerts.support import FAILED

pytestmark = pytest.mark.anyio
URL = "https://hooks.test/services/T0KEN"


async def test_an_alert_is_posted_as_text() -> None:
    posted: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        posted.append(request)
        return httpx2.Response(200)

    await WebhookNotifier(URL, httpx2.MockTransport(answer)).notify(FAILED)

    (request,) = posted
    assert str(request.url) == URL
    assert json.loads(request.content) == {"text": f"{FAILED.subject()}\n{FAILED.text()}"}


def _refused(_: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(500)


def _unreachable(request: httpx2.Request) -> httpx2.Response:
    message = f"cannot reach {request.url}"  # as httpx2 says it: with the URL, and its token
    raise httpx2.ConnectError(message, request=request)


@pytest.mark.parametrize(
    ("answer", "failure"), [(_refused, "failed: 500"), (_unreachable, "failed: ConnectError")]
)
async def test_a_failed_post_raises_without_naming_the_url(
    answer: Callable[[httpx2.Request], httpx2.Response], failure: str
) -> None:
    with pytest.raises(WebhookError, match=failure) as raised:
        await WebhookNotifier(URL, httpx2.MockTransport(answer)).notify(FAILED)

    assert "T0KEN" not in str(raised.value)
    assert raised.value.__suppress_context__  # nor in a chained error's message
