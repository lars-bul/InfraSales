import asyncio
import gc
import logging
import threading

import pytest

from infrasales.core.tasks import finish_within, in_thread, raise_if_cancelled

pytestmark = pytest.mark.anyio


def _nothing() -> None:
    return None


async def test_the_result_or_failure_is_passed_on() -> None:
    async def answer() -> int:
        return 42

    async def fail() -> None:
        raise ValueError

    assert await finish_within(answer(), stop=_nothing, grace=1) == 42
    with pytest.raises(ValueError):  # noqa: PT011  # the work's own error
        await finish_within(fail(), stop=_nothing, grace=1)


async def _cancel(task: asyncio.Task[None], times: int = 1) -> None:
    for _ in range(times):
        task.cancel()
        await asyncio.sleep(0)


@pytest.mark.parametrize("cancellations", [1, 3])
async def test_cancelled_work_is_stopped_and_awaited_until_it_ends(cancellations: int) -> None:
    started, stopped, stops = asyncio.Event(), asyncio.Event(), list[str]()

    async def stoppable() -> None:
        started.set()
        await stopped.wait()  # the copy in flight, finishing once asked to stop
        await asyncio.sleep(0.05)

    def stop() -> None:
        stops.append("stop")
        stopped.set()

    task = asyncio.create_task(finish_within(stoppable(), stop=stop, grace=5))
    await started.wait()
    await _cancel(task, cancellations)
    assert not task.done()  # waits for the work to end
    await asyncio.wait([task])

    assert (task.cancelled(), stops) == (True, ["stop"])


async def test_work_that_will_not_end_is_left_after_the_grace(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stuck thread cannot hold its caller: the cancellation takes effect after `grace`."""
    started, release = asyncio.Event(), asyncio.Event()

    async def stuck() -> None:
        started.set()
        await release.wait()
        raise ConnectionError  # how it ends, long after nobody waits for it

    loop = asyncio.get_running_loop()
    task = asyncio.create_task(finish_within(stuck(), stop=_nothing, grace=0.1))
    await started.wait()
    cancelled_at = loop.time()
    await _cancel(task, 2)
    await asyncio.wait([task])
    waited = loop.time() - cancelled_at
    release.set()
    await asyncio.sleep(0.01)
    gc.collect()

    assert task.cancelled()
    assert 0.1 <= waited < 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]  # its error retrieved


async def test_work_cancelled_itself_ends_the_caller_too() -> None:
    async def gives_up() -> None:
        raise asyncio.CancelledError

    task = asyncio.create_task(finish_within(gives_up(), stop=_nothing, grace=1))
    await asyncio.wait([task])

    assert task.cancelled()


async def test_work_in_a_thread_of_its_own_passes_its_outcome_on() -> None:
    def where() -> tuple[str, bool]:
        thread = threading.current_thread()
        return thread.name, thread.daemon

    def fail() -> None:
        raise ValueError

    assert await in_thread(where, name="worker") == ("worker", True)  # not waited for at exit
    with pytest.raises(ValueError):  # noqa: PT011  # the work's own error
        await in_thread(fail, name="worker")


async def test_a_cancellation_surfacing_as_an_error_still_ends_a_retrying_loop() -> None:
    """A driver may report a cancellation as an error of its own: the loop stops all the same."""
    attempts = 0

    async def query() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise ConnectionError from None  # as psycopg does now and then

    async def retrying() -> None:
        nonlocal attempts
        while True:
            attempts += 1
            try:
                await query()
            except ConnectionError:
                raise_if_cancelled()

    task = asyncio.create_task(retrying())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.wait([task], timeout=1)

    assert (task.cancelled(), attempts) == (True, 1)
