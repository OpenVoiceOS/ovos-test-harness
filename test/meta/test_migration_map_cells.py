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

#: Per-twin surface note carried into the xfail marker (condition: a tracked
#: reason must name its surface and owner). Only the twins that need more than
#: the generic owner line appear here.
_PENDING_NOTE = {
    "ovos.skills.fallback.register":
        "FALLBACK-1 registry twin (backcompat's wire surface); "
        "real cell tracked with ovos-test-harness#64.",
    "ovos.skills.fallback.deregister":
        "FALLBACK-1 registry twin (backcompat's wire surface); "
        "real cell tracked with ovos-test-harness#64.",
    "ovos.skills.fallback.ping":
        "FALLBACK-1 ping twin (backcompat's wire surface); "
        "builds on ovos-test-harness#64's fallback-ping wire twin.",
    "ovos.skills.fallback.pong":
        "FALLBACK-1 pong twin (backcompat's wire surface); "
        "builds on ovos-test-harness#64's fallback-ping wire twin.",
}

#: The pending-coverage set is pinned so it can only shrink. Raising this bound
#: is a deliberate, reviewer-visible edit; without it the allowlist becomes the
#: quiet place a fifth undriven twin goes and the meta test stops meaning
#: anything. 18 pre-existing + 4 FALLBACK-1 twins.
MAX_PENDING_TWINS = 22


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
        note = _PENDING_NOTE.get(legacy, "")
        pytest.xfail(
            f"{legacy} <-> {spec}: pending back-compat coverage (owner: harness "
            f"lane); the real fix is a driven cell under test/backcompat/, not "
            f"this list. " + (note + " " if note else "") + "Self-flips to a hard "
            f"failure the day a cell names both spellings, which forces removal.")
    assert driven, (
        f"MIGRATION_MAP twin {legacy} <-> {spec} is named by no cell under "
        f"test/backcompat/. Add one, or admit it in "
        f"test/meta/untested-migration-topics.txt.")


def test_pending_coverage_set_is_pinned():
    """The pending-coverage list may shrink as real cells land but must never
    grow: a new undriven twin cannot be parked here without a reviewed edit that
    raises MAX_PENDING_TWINS and says why."""
    allow = _allowlist()
    assert len(allow) <= MAX_PENDING_TWINS, (
        f"pending-coverage list is {len(allow)} > pin {MAX_PENDING_TWINS}: a "
        f"MIGRATION_MAP twin was parked in test/meta/untested-migration-topics.txt "
        f"instead of being driven by a cell. Add the cell, or raise the pin in a "
        f"reviewed edit that names the surface and its owner.")
    stale = allow - set(MIGRATION_MAP)
    assert not stale, (
        f"untested-migration-topics.txt names topics absent from MIGRATION_MAP: "
        f"{sorted(stale)}. The list tracks real undriven twins only.")
