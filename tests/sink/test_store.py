from pathlib import Path

import pytest

from infrasales.sink.store import Sink
from tests.scrape.support import memory_sink

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["memory", "file"])
def sink(request: pytest.FixtureRequest, tmp_path: Path) -> Sink:
    """The same four operations on both backends InfraSales uses."""
    return memory_sink() if request.param == "memory" else Sink(f"file://{tmp_path}/sink")


async def test_written_files_are_read_listed_and_deleted_by_folder(sink: Sink) -> None:
    await sink.write("2026-10-16T060000Z/news/v1/raw.html", b"<html>")
    await sink.write("2026-10-16T060000Z/news/v1/metadata.json", b"{}")
    await sink.write("2026-10-16T060000Z/wire/v2/raw.html", b"<p>")

    assert await sink.read("2026-10-16T060000Z/news/v1/raw.html") == b"<html>"
    assert await sink.list("2026-10-16T060000Z/news") == [
        "2026-10-16T060000Z/news/v1/metadata.json",
        "2026-10-16T060000Z/news/v1/raw.html",
    ]
    await sink.delete("2026-10-16T060000Z/news/v1")
    await sink.delete("2026-10-16T060000Z/news/v1")  # gone already: fine
    assert await sink.list() == ["2026-10-16T060000Z/wire/v2/raw.html"]
    assert await sink.list("nothing/here") == []


async def test_files_are_written_once(sink: Sink) -> None:
    await sink.write("run/news/v1/raw.html", b"first")

    with pytest.raises(FileExistsError):
        await sink.write("run/news/v1/raw.html", b"second")
    assert await sink.read("run/news/v1/raw.html") == b"first"


async def test_a_missing_file_cannot_be_read(sink: Sink) -> None:
    with pytest.raises(FileNotFoundError):
        await sink.read("run/news/v1/raw.html")


@pytest.mark.parametrize("key", ["", "run/../../etc/passwd", "run//v1", "./run"])
async def test_keys_stay_below_the_root(sink: Sink, key: str) -> None:
    with pytest.raises(ValueError, match="not a sink key"):
        await sink.write(key, b"x")
