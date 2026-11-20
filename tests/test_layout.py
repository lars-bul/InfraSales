"""Every source module has a test module at its mirrored path: `a/b.py` → `tests/a/test_b.py`.

Packages stay empty (`__init__.py` holds no code), so each unit of behaviour lives in a module
that the rule above can see.
"""

from pathlib import Path

import infrasales

SOURCE = Path(infrasales.__file__).parent
TESTS = Path(__file__).parent
SKIPPED = ("migrations",)  # Alembic scripts: covered by the migration tests


def _modules() -> list[Path]:
    return [
        path.relative_to(SOURCE)
        for path in sorted(SOURCE.rglob("*.py"))
        if not path.relative_to(SOURCE).parts[0].startswith(SKIPPED)
    ]


def test_every_module_has_a_test_module() -> None:
    missing = [
        str(module)
        for module in _modules()
        if module.name != "__init__.py"
        and not (TESTS / module.parent / f"test_{module.name}").is_file()
    ]

    assert missing == []


def test_packages_hold_no_code() -> None:
    packages = [module for module in _modules() if module.name == "__init__.py"]

    assert [str(p) for p in packages if (SOURCE / p).read_text().strip()] == []
