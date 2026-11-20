"""The sink: files of Source Versions behind four operations, over fsspec.

Keys are `/`-separated paths below the root (`2026-10-16T060000Z/tiefbau-aktuell/<id>/raw.html`),
never local paths. Files are written once and never renamed, appended to or edited (S3 cannot
rename); a Source Version is deleted as a whole folder. Only this module uses fsspec.

fsspec's local backend blocks: every call runs in a thread, so the worker's heartbeats go on.
Writes are not atomic, and need not be: readers trust only committed catalog rows (ADR 03 §4).
"""

import asyncio
import contextlib
import posixpath

from fsspec.core import url_to_fs

from infrasales.core.state import StateKey


class Sink:
    def __init__(self, uri: str) -> None:
        """The sink at `uri` (`file:///data/sink`, `memory://tests`); nothing is touched yet."""
        self._fs, root = url_to_fs(uri)
        self._root = root.rstrip("/")

    def _path(self, key: str) -> str:
        parts = key.strip("/").split("/")
        if any(part in {"", ".", ".."} for part in parts):
            msg = f"not a sink key: {key!r}"
            raise ValueError(msg)
        return f"{self._root}/{'/'.join(parts)}"

    async def write(self, key: str, data: bytes) -> None:
        """Write a new file; raises `FileExistsError` if `key` was written before."""
        path = self._path(key)

        def write() -> None:
            self._fs.makedirs(posixpath.dirname(path), exist_ok=True)
            self._fs.pipe_file(path, data, mode="create")

        await asyncio.to_thread(write)

    async def read(self, key: str) -> bytes:
        """The file's bytes; raises `FileNotFoundError` if there is none."""
        return await asyncio.to_thread(self._fs.cat_file, self._path(key))

    async def list(self, folder: str = "") -> list[str]:
        """The keys of every file below `folder` (all of them for ""), sorted; [] if none."""
        path = self._path(folder) if folder.strip("/") else self._root
        found = await asyncio.to_thread(self._fs.find, path)
        return sorted(name.removeprefix(f"{self._root}/") for name in found)

    async def delete(self, folder: str) -> None:
        """Delete `folder` with everything in it; a folder that is gone already is fine."""
        path = self._path(folder)

        def delete() -> None:
            with contextlib.suppress(FileNotFoundError):
                self._fs.rm(path, recursive=True)

        await asyncio.to_thread(delete)


SINK = StateKey[Sink]("sink")  # the web app's, for reading Source Versions' files
