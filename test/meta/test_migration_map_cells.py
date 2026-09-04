"""Meta-test: every legacy/spec topic twin owes a back-compat cell.

`ovos_spec_tools.messages.MIGRATION_MAP` is the ecosystem's list of legacy
topics that a spec topic replaced. Each entry is a promise that a component
speaking the old name and a component speaking the new one still understand
each other, and four of them carry a lossy payload transform. Nothing was
parametrized over the map, so adding an entry added no cell and most of the
twins were named in no test at all.

This test walks the map and requires each legacy topic and its spec topic to
be named somewhere under `test/backcompat/`. A twin that is not yet driven
goes in `untested-migration-topics.txt`, which can only shrink.
"""
import pathlib

import pytest
from ovos_spec_tools.messages import MIGRATION_MAP

HERE = pathlib.Path(__file__).parent
BACKCOMPAT = HERE.parent / "backcompat"
ALLOWLIST = HERE / "untested-migration-topics.txt"


def _cells_text():
    return "\n".join(p.read_text() for p in sorted(BACKCOMPAT.glob("*.py")))


def _allowlist():
    return {line.strip() for line in ALLOWLIST.read_text().split("\n")
            if line.strip() and not line.startswith("#")}


@pytest.mark.parametrize("legacy", sorted(MIGRATION_MAP))
def test_migration_twin_has_a_backcompat_cell(legacy):
    spec = MIGRATION_MAP[legacy].value
    text = _cells_text()
    driven = legacy in text and spec in text
    if legacy in _allowlist():
        assert not driven, (
            f"{legacy} <-> {spec} is now driven by a back-compat cell; drop it "
            f"from test/meta/untested-migration-topics.txt — the list is a "
            f"ratchet.")
        pytest.xfail(f"no back-compat cell names {legacy} <-> {spec}")
    assert driven, (
        f"MIGRATION_MAP twin {legacy} <-> {spec} is named by no cell under "
        f"test/backcompat/. Add one, or admit it in "
        f"test/meta/untested-migration-topics.txt.")
