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


# Capabilities gated by a `skipif` inside a conformance suite. On a partial
# local stack the suite skips the clause cleanly; on a full-stack CI run the
# capability MUST be present, or the clause skipped silently and the green is a
# lie — exactly the false-coverage failure mode `skipif` creates. Each entry is
# a deterministic presence probe returning ``(present, how_to_get_it)``.
def _workshop_has_spec_dual_emit():
    """ovos-workshop exposes the §8/§9.6 spec bus-message dual-emit.

    Gate for ``test_pipeline1_conformance`` ``_requires_spec_workshop``
    (``OVOSSkill._intent_handler_data``).
    """
    from ovos_workshop.skills.ovos import OVOSSkill
    return (hasattr(OVOSSkill, "_intent_handler_data"),
            "install an ovos-workshop carrying the spec bus-message dual-emit "
            "(OVOSSkill._intent_handler_data)")


def _bus_client_has_transformer_override_fields():
    """ovos-bus-client Session carries the TRANSFORM-1 §5 override fields.

    Gate for ``test_transform1_conformance`` ``_requires_override_fields``
    (``session.<type>_transformers``).
    """
    from ovos_bus_client.session import Session
    return ("utterance_transformers" in Session("probe").serialize(),
            "install an ovos-bus-client whose Session registers the "
            "OVOS-TRANSFORM-1 §5 <type>_transformers override fields "
            "(OVOS-SESSION-1 §2.1)")


GATED_CAPABILITIES = {
    "pipeline1 §8/§9.6 (handler trio + speak dual-emit)":
        _workshop_has_spec_dual_emit,
    "transform1 §5 (per-session <type>_transformers overrides)":
        _bus_client_has_transformer_override_fields,
}


@pytest.mark.parametrize("clause,probe", sorted(GATED_CAPABILITIES.items()))
def test_skipif_gated_capability_is_present(clause, probe):
    """A full-stack run installs the capability every ``skipif``-guarded clause
    needs; if it is absent the clause skipped silently and CI is falsely green."""
    present, remedy = probe()
    assert present, (
        f"{clause} is absent on a full-stack run, so that conformance clause "
        f"skipped silently and reported green without proving anything: {remedy}")


def test_no_intent4_plugin_case_is_a_missing_placeholder():
    """Every INTENT-4 plugin case is a real case, not a not-installed stub."""
    mod = importlib.import_module(
        "test.conformance.test_intent4_plugins_conformance")
    missing = [name for name, obj in vars(mod).items()
               if isinstance(obj, type) and obj.__name__ == "_Missing"]
    assert not missing, (
        "these INTENT-4 plugin cases degraded to not-installed placeholders on "
        f"a full-stack run: {sorted(missing)}")
