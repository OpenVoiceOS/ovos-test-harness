"""Pytest bootstrap for the OVOS cross-repo conformance harness.

Ensures the repository root is importable so the conformance suites resolve
their ``test.conformance`` package (the suites use relative imports against the
``_conformance`` helper module).

It also enforces the collection floor: on a run that claims to install the full
stack (``OVOS_CONFORMANCE_EXPECT_FULL=1``, set by the integration workflow), a
conformance module that collects zero tests is an install failure, not a quiet
green. See ``test/test_install_floor.py`` for the import-level companion.

Channel mode
------------

When ``OVOS_CHANNEL`` names an OVOS distro release channel (``stable`` or
``testing``), the stack under test is whatever that channel ships, which is far
behind dev. Large parts of the spec are simply not implemented there yet, so a
plain red/green verdict carries no information.

``test/channel_gaps/<channel>.txt`` records exactly which suites and node ids
that channel fails today. This bootstrap then:

* does not collect the modules that do not import on the channel, and
* marks the listed node ids ``xfail(strict=True)``.

So the job is green on the KNOWN gap set and red on anything else — a new
breakage, a gap the channel has since closed (strict xfail turns XPASS into a
failure), or a listed node id that no longer exists. ``test/test_channel_gaps.py``
holds the other half of the guard.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from test.channel_compat.gaps import read_gaps  # noqa: E402

CONFORMANCE_DIR = os.path.join(os.path.dirname(__file__), "test", "conformance")
CHANNEL = os.environ.get("OVOS_CHANNEL") or None


def _expected_conformance_modules():
    """Every ``test_*_conformance.py`` file that must yield tests."""
    if not os.path.isdir(CONFORMANCE_DIR):
        return set()
    names = {name for name in os.listdir(CONFORMANCE_DIR)
             if name.startswith("test_") and name.endswith(".py")}
    if CHANNEL is not None:
        # A channel legitimately cannot import some suites; that is recorded in
        # the gaps file and guarded by test/test_channel_gaps.py instead.
        names -= {os.path.basename(m) for m in read_gaps(CHANNEL)[0]}
    return names


def pytest_ignore_collect(collection_path, config):
    """Skip suites that do not import on the channel under test."""
    if CHANNEL is None:
        return None
    rel = os.path.relpath(str(collection_path), os.path.dirname(__file__))
    if rel.replace(os.sep, "/") in read_gaps(CHANNEL)[0]:
        return True
    return None


def _apply_channel_gaps(config, items):
    """Strict-xfail the node ids this channel is known to fail."""
    _, failing, xpassing = read_gaps(CHANNEL)
    known = failing | xpassing
    where = f"test/channel_gaps/{CHANNEL}.txt"
    collected = set()
    for item in items:
        nodeid = item.nodeid
        collected.add(nodeid)
        if nodeid in failing:
            marker = pytest.mark.xfail(
                strict=True, reason=f"known {CHANNEL}-channel gap ({where})")
        elif nodeid in xpassing:
            # The suite marks this xfail(strict) for a dev-stack reason that
            # does not hold on this channel. Relax it rather than expect a
            # failure the channel does not produce. append=False so this marker
            # is the one pytest evaluates.
            marker = pytest.mark.xfail(
                strict=False,
                reason=f"the suite's strict xfail does not apply on the "
                       f"{CHANNEL} channel ({where})")
        else:
            continue
        item.add_marker(marker, append=False)
    if config.option.keyword or config.option.markexpr:
        return  # a filtered run collects a subset, so absence proves nothing
    stale = sorted(known - collected)
    if stale:
        raise pytest.UsageError(
            f"test/channel_gaps/{CHANNEL}.txt lists node ids that no longer "
            f"exist: {stale}. Delete them, or fix the rename.")


def pytest_collection_modifyitems(session, config, items):
    """Fail the run when a conformance module contributed no tests."""
    if CHANNEL is not None:
        _apply_channel_gaps(config, items)
    if os.environ.get("OVOS_CONFORMANCE_EXPECT_FULL") != "1":
        return
    if config.option.keyword or config.option.markexpr:
        return  # a filtered run is expected to collect a subset
    collected = {os.path.basename(str(item.fspath)) for item in items}
    missing = sorted(_expected_conformance_modules() - collected)
    if missing:
        raise pytest.UsageError(
            "OVOS_CONFORMANCE_EXPECT_FULL=1 but these conformance modules "
            f"collected no tests (broken install?): {missing}")
