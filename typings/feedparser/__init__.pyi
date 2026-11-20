# Minimal stub: feedparser ships no type information. Only the API infrasales.feeds.rss uses;
# `Any` mirrors its dictionaries of whatever a feed holds.
from typing import Any

class FeedParserDict(dict[str, Any]):
    def __getattr__(self, name: str) -> Any: ...

def parse(url_file_stream_or_string: bytes | str, **kwargs: Any) -> FeedParserDict: ...
