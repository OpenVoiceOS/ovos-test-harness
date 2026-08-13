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


def pytest_collection_modifyitems(config, items):
    global _LAST_PRUNE_SUMMARY
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
    marker count."""
    if _LAST_PRUNE_SUMMARY is not None:
        terminalreporter.write_line(_LAST_PRUNE_SUMMARY)
