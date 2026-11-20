import pytest
from pydantic import ValidationError

from infrasales.feeds.kinds import LISTERS


def test_each_kind_refuses_settings_it_does_not_know() -> None:
    for lister in LISTERS.values():
        with pytest.raises(ValidationError):
            lister.settings.model_validate({"no_such_setting": 1})
