"""The tripwire for every known-red cell (``cells.KNOWN_RED_CELLS``).

A known-red cell runs every scenario under ``xfail(strict=False)`` with the
recorded reason (``conftest.py``). This test is the one item that runs
plain in that cell. It asserts the reason is still true against the
packages the core venv resolved, so the day a release closes the gap the
cell reports one loud failure here instead of a quiet row of XPASS marks.
That failure is the signal to drop the ``KNOWN_RED_CELLS`` entry.

Runs in the core venv (the workflow invokes the core venv's pytest), so
the imports below read the same packages the core process runs.
"""
import os
from importlib.metadata import version

import pytest

from .cells import OTHER, REFERENCE, axis_values, known_red_reason, resolve_cell

COMBO = os.environ.get("BACKCOMPAT_COMBO", "")
CELL = resolve_cell(COMBO)


@pytest.mark.known_red_tripwire
def test_old_core_cohort_still_cannot_run_current_matchers():
    if CELL is None or known_red_reason(CELL) is None:
        pytest.skip(f"{COMBO!r} is not a known-red cell")
    values = axis_values(CELL)
    if not (values["C"] == OTHER and values["M"] == REFERENCE):
        pytest.skip(f"{COMBO!r} is known red for another reason")

    from ovos_spec_tools.messages import SpecMessage
    import ovos_spec_tools

    spec_tools = version("ovos-spec-tools")
    bus_client = version("ovos-bus-client")
    padatious = version("ovos-padatious")

    # the matcher side: current padatious imports a spec-tools 1.11.0a1 name
    assert hasattr(ovos_spec_tools, "REGISTERED_TYPES"), (
        f"ovos-spec-tools {spec_tools} has no REGISTERED_TYPES, so "
        f"ovos-padatious {padatious} resolved against a release below "
        f"1.11.0a1; the venv no longer floors spec-tools with the matchers")

    # the core side: the 2.5.5a2 cohort's bus client needs a name that
    # release removed. If both hold, the cell is still red for the recorded
    # reason. If either stops holding, a release closed the gap: drop the
    # KNOWN_RED_CELLS entry and let the cell run plain.
    assert not hasattr(SpecMessage, "SESSION_SYNC"), (
        f"ovos-spec-tools {spec_tools} still has SpecMessage.SESSION_SYNC")
    from ovos_bus_client.client import client as bc_client
    import inspect
    src = inspect.getsource(bc_client)
    assert "SpecMessage.SESSION_SYNC" in src, (
        f"ovos-bus-client {bus_client} no longer emits SESSION_SYNC on "
        f"connect: the C=old cohort moved, drop the KNOWN_RED_CELLS entry "
        f"and re-run the cell plain")
