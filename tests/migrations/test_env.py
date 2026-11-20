import argparse
import os
from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory

from infrasales.core import schema

VERSIONS = Path(schema.__file__).parent.parent / "migrations" / "versions"


def test_migrations_apply_and_match_the_models(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"

    schema.upgrade(url)

    command.check(schema.alembic_config(url))  # raises if a model changed without a migration


def test_revisions_form_one_line() -> None:
    script = ScriptDirectory.from_config(schema.alembic_config(""))

    assert len(script.get_heads()) <= 1
    assert all(revision.revision.isdigit() for revision in script.walk_revisions())


def test_autogenerate_without_model_changes_writes_nothing(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    schema.upgrade(url)
    config = schema.alembic_config(url)
    config.cmd_opts = argparse.Namespace(autogenerate=True)
    # New revisions go to a temporary directory: a failing run never writes into the repository.
    written = tmp_path / "versions"
    written.mkdir()
    config.set_main_option("path_separator", "os")
    config.set_main_option("version_locations", os.pathsep.join([str(VERSIONS), str(written)]))

    command.revision(config, autogenerate=True, version_path=str(written))

    assert list(written.iterdir()) == []
