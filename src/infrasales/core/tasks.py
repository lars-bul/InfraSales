"""Waiting for work that cannot be interrupted, such as a blocking call in a thread."""

import asyncio
import concurrent.futures
import contextlib
import threading
from collections.abc import Awaitable, Callable


def in_thread[T](work: Callable[[], T], *, name: str) -> asyncio.Future[T]:
    """Run blocking `work` in a daemon thread of its own; await its outcome."""
    outcome = concurrent.futures.Future[T]()
    outcome.set_running_or_notify_cancel()  # running from now on: it cannot be called off

    def run() -> None:
        try:
            outcome.set_result(work())
        except BaseException as error:  # noqa: BLE001  # handed to whoever awaits it
            outcome.set_exception(error)

    threading.Thread(target=run, name=name, daemon=True).start()
    return asyncio.wrap_future(outcome)


async def finish_within[T](work: Awaitable[T], *, stop: Callable[[], object], grace: float) -> T:
    """Await `work`; if cancelled meanwhile, `stop` it and wait up to `grace` seconds for it."""
    task = asyncio.ensure_future(work)
    task.add_done_callback(_retrieve)
    try:
        await asyncio.wait([task])  # waiting for a task, unlike awaiting it, never cancels it
    except asyncio.CancelledError:
        stop()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + grace
        while not task.done() and (left := deadline - loop.time()) > 0:
            with contextlib.suppress(asyncio.CancelledError):  # cancelled again: still waiting
                await asyncio.wait([task], timeout=left)
        raise
    return task.result()


def raise_if_cancelled() -> None:
    """Stop the current task if it was asked to, whatever error its cancellation surfaced as."""
    if (task := asyncio.current_task()) and task.cancelling():
        raise asyncio.CancelledError


def _retrieve[T](task: asyncio.Future[T]) -> None:
    if not task.cancelled():
        task.exception()
