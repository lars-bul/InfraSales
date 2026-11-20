from typing import Any

from fsspec.spec import AbstractFileSystem

def url_to_fs(url: str, **kwargs: Any) -> tuple[AbstractFileSystem, str]: ...
