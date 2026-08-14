"""OVOS-STOP-1 — dual-emit-OFF conformance mode.

The rest of the STOP-1 suite (``test_stop1_conformance.py``) runs under full
production dual-emit (``websocket.modernize`` / ``websocket.emit_legacy`` both
``True``, the :func:`use_spec_namespace` default). Under that mode, a "spec
topic observed" assertion cannot by itself distinguish native spec-namespace
code from the ``modernize`` bridge mirroring a legacy emission onto the spec
topic — both look identical on the wire.

This module runs a subset of the SAME assertions with
``use_spec_namespace(dual_emit=False)`` — both flags off, bridge fully
disabled. A spec topic can reach the bus here ONLY via code that emits it
natively; there is no other path. A green result here is real V1-native
evidence, not bridge echo.

Coverage map (clause -> status against current ovos-core@dev, dual-emit OFF):
- §5.1 the utterance-turn end-marker ``ovos.utterance.handled`` fires
  natively (no legacy counterpart exists to bridge it) ........... green
- §5.3 global stop broadcasts natively on ``ovos.stop`` .......... green (STOP-1 wiring landed, ovos-core#802; native emit confirmed with the bridge fully disabled)
"""
from ovos_utils.log import LOG

from ._conformance import STOP_HIGH, capture, reset_namespace, types, \
    use_spec_namespace, utterance

_MC = None


def setUpModule():
    global _MC
    LOG.set_level("ERROR")
    use_spec_namespace(dual_emit=False)  # bridge fully OFF: native emission only
    try:
        from ._conformance import wait_ready
        from ovoscope import get_minicroft
        _MC = get_minicroft([])
        wait_ready(_MC, settle=1.0)
    except BaseException:
        reset_namespace()
        raise


def tearDownModule():
    try:
        if _MC is not None:
            _MC.stop()
    finally:
        reset_namespace()


def test_utterance_handled_fires_natively_with_bridge_disabled():
    """§5.1: exactly one ``ovos.utterance.handled`` end-marker, with the
    modernize/emit_legacy bridge fully disabled. There is no legacy
    counterpart topic for the bridge to mirror onto ``ovos.utterance.handled``
    in the first place, so a pass here proves the orchestrator's own entry/exit
    contract is spec-namespace-native, not an artifact of dual-emit."""
    recs = capture(_MC, utterance("stop", "stop-dualoff-eof", [STOP_HIGH]), 4.0,
                   eof_types=None)
    assert types(recs).count("ovos.utterance.handled") == 1


def test_global_stop_broadcast_topic_native_only():
    """§5.3, dual-emit OFF: with the bridge disabled, ``ovos.stop`` can only
    appear if ovos-core emits it natively. It does not."""
    recs = capture(_MC, utterance("stop", "stop-dualoff-bcast", [STOP_HIGH]), 4.0)
    assert "ovos.stop" in types(recs)
