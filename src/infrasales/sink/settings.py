"""Where Source Versions are stored (`SINK__*`)."""

from pydantic import BaseModel


class SinkSettings(BaseModel):
    """The sink: one fsspec URI chooses the backend and the root.

    `file:///data/sink` (the named Docker volume), `file://data/sink` (relative, `make dev`),
    `memory://…` (tests), later `s3://bucket/prefix` (with s3fs installed).
    """

    uri: str = "file:///data/sink"
