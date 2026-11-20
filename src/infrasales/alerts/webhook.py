"""Alerts to a chat webhook: `{"text": …}`, as Slack, Mattermost and Google Chat take it."""

import httpx2

from infrasales.scheduler.registry import Notice

_TIMEOUT_SECONDS = 10


class WebhookError(Exception):
    """The webhook did not take the alert. Its URL holds a token: it is never in the message."""

    def __init__(self, failure: object) -> None:
        super().__init__(f"the alert webhook failed: {failure}")


class WebhookNotifier:
    def __init__(self, url: str, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._url, self._transport = url, transport  # transport: tests answer in-process

    async def notify(self, notice: Notice) -> None:
        message = {"text": f"{notice.subject()}\n{notice.text()}"}
        client = httpx2.AsyncClient(transport=self._transport, timeout=_TIMEOUT_SECONDS)
        try:
            async with client:
                (await client.post(self._url, json=message)).raise_for_status()
        except httpx2.HTTPStatusError as error:  # its message names the URL
            raise WebhookError(error.response.status_code) from None
        except httpx2.HTTPError as error:  # likewise
            raise WebhookError(type(error).__name__) from None
