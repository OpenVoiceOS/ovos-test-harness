"""Install floor for the conformance run.

A conformance suite that skips itself because an optional stack piece failed to
import reports green. On a CI job whose whole purpose is to install the full
stack, that green is a lie: the suite proved nothing.

These tests turn such a skip into a failure. They run only when
``OVOS_CONFORMANCE_EXPECT_FULL=1`` — the integration workflow sets it, and a
local run with a partial stack does not, so local skipping stays convenient.

The companion check lives in ``conftest.py``: it fails the session when a
conformance module collects zero tests.
"""
import importlib
import os

import pytest

EXPECT_FULL = os.environ.get("OVOS_CONFORMANCE_EXPECT_FULL") == "1"

pytestmark = pytest.mark.skipif(
    not EXPECT_FULL,
    reason="OVOS_CONFORMANCE_EXPECT_FULL is not set: partial stacks may skip "
           "suites locally",
)

# Optional stack pieces whose absence silently disables a whole suite.
GATED_MODULES = {
    "ovos_media.player": "OVOS-OCP-1 Virtual Media Player clauses "
                         "(test_ocp1_conformance.py)",
    "ovos_gui.namespace": "GUI-1 service clauses (test_gui1_conformance.py)",
}


@pytest.mark.parametrize("module,suite", sorted(GATED_MODULES.items()))
def test_gated_stack_piece_is_importable(module, suite):
    """The full stack is installed, so every suite-gating module must import."""
    try:
        importlib.import_module(module)
    except ImportError as exc:
        pytest.fail(f"{module} is not importable, so {suite} would skip "
                    f"silently on a full-stack run: {exc}")


def test_no_intent4_plugin_case_is_a_missing_placeholder():
    """Every INTENT-4 plugin case is a real case, not a not-installed stub."""
    mod = importlib.import_module(
        "test.conformance.test_intent4_plugins_conformance")
    missing = [name for name, obj in vars(mod).items()
               if isinstance(obj, type) and obj.__name__ == "_Missing"]
    assert not missing, (
        "these INTENT-4 plugin cases degraded to not-installed placeholders on "
        f"a full-stack run: {sorted(missing)}")
