"""Axis-marker pruning for the mixed-version matrix (design §2.4/§3.1).

A cell run is one venv pair (an eventual triple, once the audio simulator
lands in T2.3). Most of the eight scenarios only depend on some of the four
axes (S/C/M/A) -- see the pruning table in design §2.4. Running a scenario
against an axis that's already at reference ("new") vintage in the current
cell can't show anything a single-vintage run wouldn't
(``cells.is_redundant``).

Rather than *skip* those tests -- which would still report "1 skipped" and
make raw pass/fail counts look like more coverage happened than really did
-- this hook DESELECTS them, the same mechanism ``-k``/``-m`` filtering
uses: they show up under pytest's own "N deselected" accounting, not under
"passed" or "skipped", so a cell's real test count stays honest and visible
in ``-v`` output.

Only applies to boundary-tier cells (the four ``BOUNDARY_ALIASES`` and
whatever other 4-tuple cells get built in T2.3+); channel cells pin the
whole stack from a live distro file rather than crossing individual axes
(design §2.5), so pruning does not apply to them and they keep running
their full scenario set.

The summary line is also written via ``pytest_terminal_summary`` (not just
``print()`` during collection), because ``print()`` output during
collection is swallowed unless the run passes ``-s`` -- CI does not, so
without this the deselection reason would never make it into CI logs at
all (an adversarial-review finding on the first cut of this file).

This ``pytest_terminal_summary`` hook also drives the T2.6 findings feed
(design §4.2): once a run finishes, ``findings.write_findings`` walks every
xfailed/xpassed report and writes ``backcompat-findings-<cell>.json`` next
to wherever pytest was invoked from, for
``.github/workflows/backcompat_matrix.yml``'s ``summarize`` job to collect
across all cells and render ``FINDINGS/SPRINT.md``. See ``findings.py`` for
the record schema and how it recovers a test's ``axes``/boundary/blocked_on
fields.
"""
import os

import pytest

from .cells import is_redundant, resolve_cell

COMBO = os.environ.get("BACKCOMPAT_COMBO", "")

#: Set by pytest_collection_modifyitems, read by pytest_terminal_summary.
#: Module-level rather than a config attribute: this conftest only ever
#: runs inside one pytest process per cell, so there is no cross-run state
#: to worry about, and it keeps the terminal-summary hook from needing to
#: recompute anything.
_LAST_PRUNE_SUMMARY = None

#: nodeid -> tuple of axes crossed by that test's own
#: ``@pytest.mark.axes(...)`` marker, captured once at collection time (the
#: only point a ``pytest.Item`` and its markers are both cheaply available)
#: so ``findings.py``'s ``pytest_terminal_summary``-time record collection
#: doesn't need the collected ``Item`` objects, which terminalreporter
#: results don't carry. Populated for every item seen at collection,
#: including items with no ``axes`` marker at all (empty tuple) and items
#: later deselected by the pruning above -- deselected items never reach
#: `call` phase, so they never produce a findings record either way, but
#: recording their axes too keeps this dict's population logic independent
#: of the pruning decision, rather than one more thing to keep in sync.
AXES_BY_NODEID = {}


def pytest_sessionstart(session):
    from . import findings
    findings.reset_records()


def pytest_runtest_logreport(report):
    from . import findings
    findings.record_report(report, AXES_BY_NODEID)


def pytest_collection_modifyitems(config, items):
    global _LAST_PRUNE_SUMMARY
    for item in items:
        marker = item.get_closest_marker("axes")
        AXES_BY_NODEID[item.nodeid] = tuple(marker.args) if marker else ()

    cell = resolve_cell(COMBO)
    if cell is None:
        # no BACKCOMPAT_COMBO set (bare collection), an unrecognized combo
        # (test_mixed_version_matrix.py's own `stack` fixture is what
        # raises on that), or a channel-tier combo -- none of those get
        # axis pruning.
        return

    keep = []
    deselected = []
    for item in items:
        marker = item.get_closest_marker("axes")
        if marker is None:
            keep.append(item)
            continue
        if is_redundant(marker.args, cell):
            deselected.append(item)
        else:
            keep.append(item)

    if not deselected:
        _LAST_PRUNE_SUMMARY = (
            f"[backcompat axis pruning] cell={cell} combo={COMBO!r}: "
            f"deselected 0/{len(keep)} -- nothing pruned")
        return

    config.hook.pytest_deselected(items=deselected)
    items[:] = keep
    names = ", ".join(sorted(i.name for i in deselected))
    total = len(deselected) + len(keep)
    _LAST_PRUNE_SUMMARY = (
        f"[backcompat axis pruning] cell={cell} combo={COMBO!r}: "
        f"deselected {len(deselected)}/{total} axis-redundant scenario(s)"
        f" -- {names}")
    print(f"\n{_LAST_PRUNE_SUMMARY}")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Re-state the pruning decision in the terminal summary, which -- unlike
    plain ``print()`` during collection -- always renders, ``-s`` or not, so
    a CI log always carries the reason a cell's test count doesn't match its
    marker count. Also writes this cell's findings feed (design §4.2) --
    see ``findings.write_findings`` -- so the ``backcompat_matrix.yml``
    ``summarize`` job has something to download regardless of which cell
    ran."""
    if _LAST_PRUNE_SUMMARY is not None:
        terminalreporter.write_line(_LAST_PRUNE_SUMMARY)

    from . import findings
    path = findings.write_findings(exitstatus=exitstatus)
    if path is not None:
        terminalreporter.write_line(
            f"[backcompat findings] wrote {path}")
