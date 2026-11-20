import asyncio
import signal
import sys

import pytest

from infrasales.core.signals import stop_requested


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="Windows ends the process on raise_signal")
@pytest.mark.parametrize("signal_number", [signal.SIGTERM, signal.SIGINT])
async def test_a_stop_signal_ends_the_wait(signal_number: signal.Signals) -> None:
    waiting = asyncio.create_task(stop_requested())
    await asyncio.sleep(0)

    signal.raise_signal(signal_number)

    async with asyncio.timeout(5):
        await waiting
