"""Meta-test: no migrating event may be absent from this harness.

``pairs.py`` claims to account for every entry of
``ovos_spec_tools.messages.MIGRATION_MAP``. That claim decays the moment a
topic is added to the map upstream: the new pair silently has no cell, no
skip and no known-gap row, and the suite stays green while the property it
exists to protect goes unchecked. Silent absence is the failure mode this
whole directory is about, so it is itself a test.

Every pair must be accounted for three times over — by the registry, by a
module that drives it or a reason naming the service that would, and by a row
in ``docs/known-gaps.md`` for the ones nothing drives yet. A pair that has
none of those turns this red and names itself.
"""
import pathlib

import pytest
from ovos_spec_tools.messages import MIGRATION_MAP

from .pairs import COMPONENT_CELLS, SERVICE_SKIPS, pairs

ROOT = pathlib.Path(__file__).parent.parent.parent
KNOWN_GAPS = ROOT / "docs" / "known-gaps.md"


def test_every_migrating_pair_is_accounted_for():
    """The registry covers the map exactly — no pair without an entry."""
    accounted = set(COMPONENT_CELLS) | set(SERVICE_SKIPS)
    missing = sorted(set(MIGRATION_MAP) - accounted)
    assert not missing, (
        f"these migrating topics have neither a component cell nor a named "
        f"skip in test/migration/pairs.py: {missing}. Add a cell that drives "
        f"the pair against its component, or a skip naming the service one "
        f"would need.")


def test_registry_carries_no_topic_the_map_dropped():
    """A rename that leaves the map must leave the registry with it."""
    stale = sorted((set(COMPONENT_CELLS) | set(SERVICE_SKIPS)) - set(MIGRATION_MAP))
    assert not stale, (
        f"test/migration/pairs.py records topics that are no longer in "
        f"MIGRATION_MAP: {stale}")


@pytest.mark.parametrize("legacy,module", sorted(COMPONENT_CELLS.items()))
def test_component_cell_module_drives_both_names(legacy, module):
    """A pair claimed as covered must have a module that names both topics.

    The check is deliberately literal: it cannot judge whether the cell is a
    good one, but it does catch the common decay, where a module is refactored
    until only the spec name is left and the legacy half of the pair quietly
    stops being exercised."""
    path = ROOT / module
    assert path.is_file(), f"{module} is claimed to cover {legacy!r} but does not exist"
    source = path.read_text()
    spec = MIGRATION_MAP[legacy].value
    for topic in (legacy, spec):
        assert topic in source, (
            f"{module} is claimed to cover the {legacy!r} pair but never "
            f"mentions {topic!r}")


@pytest.mark.parametrize("legacy,reason", sorted(SERVICE_SKIPS.items()))
def test_skip_reason_names_the_service(legacy, reason):
    """A skip is a TODO cell, so it has to say what would close it."""
    assert reason.startswith("needs "), (
        f"the skip reason for {legacy!r} must start with 'needs ' and name the "
        f"service: {reason!r}")
    assert "ovos-" in reason, (
        f"the skip reason for {legacy!r} names no OVOS component: {reason!r}")


@pytest.mark.parametrize("legacy", sorted(SERVICE_SKIPS))
def test_skipped_pair_is_a_documented_gap(legacy):
    """Whatever the suite skips, the gap catalogue lists."""
    assert legacy in KNOWN_GAPS.read_text(), (
        f"{legacy!r} is skipped for want of a service but has no row in "
        f"docs/known-gaps.md")


def test_generic_suite_parametrizes_the_whole_map():
    """The bus-level cells iterate the map itself, not a copy of it."""
    assert [legacy for legacy, _ in pairs()] == list(MIGRATION_MAP)
