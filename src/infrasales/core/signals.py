"""Stopping long-running commands gracefully, as container platforms ask them to."""

import asyncio
import signal


async def stop_requested() -> None:
    """Return once the process gets SIGINT or SIGTERM."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)
    await stop.wait()
