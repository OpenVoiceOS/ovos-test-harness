"""Every migrating event, exercised under both of its names.

For each pair in ``ovos_spec_tools.messages.MIGRATION_MAP`` this drives a live
bus with a subscriber on each name and asserts the three properties the
migration window rests on: an emission on the legacy name reaches a consumer
that has already moved to the spec name, an emission on the spec name reaches
a consumer that has not moved yet, and the bridge that makes both true
delivers each event exactly once to each side. A double delivery is as much a
breakage as a missing one — a skill that acts on the event twice is worse than
one that never hears it.

The bus here is ``ovos_utils.fakebus.FakeBus``, which carries the same
``NamespaceTranslator`` bridge the real ``MessageBusClient`` does and resolves
the ``websocket.modernize`` / ``websocket.emit_legacy`` flags at construction,
so these cells run in process and need no service. Component-level proof —
that the legacy topic still produces the *effect*, not just the delivery —
belongs to the modules named in ``pairs.COMPONENT_CELLS``; the pairs with no
such module report themselves here as skipped cells naming the service they
need, so the gap is counted rather than invisible.
"""
import pytest
from ovos_bus_client.message import Message
from ovos_config.config import Configuration
from ovos_spec_tools.messages import MIGRATION_PAYLOAD_TRANSFORMS

from .pairs import COMPONENT_CELLS, SERVICE_SKIPS, pair_ids, pairs

PAIRS = pairs()
IDS = pair_ids()

SKILL_ID = "migration.test"

#: What a payload-compatible pair carries through unchanged.
PAYLOAD = {"skill_id": SKILL_ID, "intent_name": "probe", "lang": "en-US",
           "utterance": "probe", "uri": "file:///probe.wav"}

#: The INTENT-4 management topics change shape across the rename, so the
#: bridge reshapes rather than forwards. They are emitted in the shape their
#: own name expects, and what survives the reshape is the intent identity —
#: the rest is documented loss at ``MIGRATION_PAYLOAD_TRANSFORMS``.
LEGACY_MANAGEMENT_PAYLOAD = {"intent_name": f"{SKILL_ID}:probe"}


def _payload(topic, legacy):
    if legacy not in MIGRATION_PAYLOAD_TRANSFORMS:
        return dict(PAYLOAD)
    if topic == legacy:
        return dict(LEGACY_MANAGEMENT_PAYLOAD)
    return {"skill_id": SKILL_ID, "intent_name": "probe"}


@pytest.fixture
def bus():
    """A bus with the production dual-emit flags, set before construction."""
    from ovos_utils.fakebus import FakeBus
    ws = Configuration().setdefault("websocket", {})
    previous = {k: ws.get(k) for k in ("modernize", "emit_legacy")}
    ws["modernize"] = ws["emit_legacy"] = True
    try:
        yield FakeBus()
    finally:
        for key, value in previous.items():
            if value is None:
                ws.pop(key, None)
            else:
                ws[key] = value


def _deliveries(bus, emit_on, listen_on, legacy):
    """Emit once on ``emit_on``; return what arrived on ``listen_on``."""
    received = []
    handler = received.append
    bus.on(listen_on, handler)
    try:
        bus.emit(Message(emit_on, _payload(emit_on, legacy)))
    finally:
        bus.remove(listen_on, handler)
    return received


@pytest.mark.parametrize("legacy,spec", PAIRS, ids=IDS)
def test_legacy_emission_reaches_a_migrated_consumer(bus, legacy, spec):
    """A peer still emitting the pre-spec name must reach a consumer that has
    already moved to the spec name."""
    received = _deliveries(bus, legacy, spec, legacy)
    assert received, f"emitting {legacy!r} never reached a {spec!r} subscriber"
    data = received[0].data
    if legacy in MIGRATION_PAYLOAD_TRANSFORMS:
        # a reshaped payload keeps the intent identity, whether it arrives
        # split into skill_id/intent_name or still joined by the colon
        name = data.get("intent_name", "")
        got = name if ":" in name else f"{data.get('skill_id', '')}:{name}"
        expected = f"{SKILL_ID}:probe"
    else:
        got, expected = data.get("skill_id"), SKILL_ID
    assert got == expected, (
        f"{legacy!r} -> {spec!r} arrived with an unrecognisable payload: "
        f"{received[0].data}")


@pytest.mark.parametrize("legacy,spec", PAIRS, ids=IDS)
def test_spec_emission_reaches_an_unmigrated_consumer(bus, legacy, spec):
    """A component emitting the spec name must still reach the consumers that
    have not migrated — the promise that keeps old skills working."""
    received = _deliveries(bus, spec, legacy, legacy)
    assert received, f"emitting {spec!r} never reached a {legacy!r} subscriber"


@pytest.mark.parametrize("legacy,spec", PAIRS, ids=IDS)
def test_bridge_delivers_each_event_exactly_once(bus, legacy, spec):
    """Both names are live at once, so a consumer subscribed to either one
    must see one event per emission, whichever name it was sent under."""
    for emit_on in (legacy, spec):
        for listen_on in (legacy, spec):
            received = _deliveries(bus, emit_on, listen_on, legacy)
            assert len(received) == 1, (
                f"emitting {emit_on!r} delivered {len(received)} messages to a "
                f"{listen_on!r} subscriber; the bridge must not double-deliver")


@pytest.mark.parametrize("legacy", sorted(SERVICE_SKIPS), ids=sorted(SERVICE_SKIPS))
def test_component_effect(legacy):
    """The component-level half of each pair with no cell yet.

    These are visible TODO cells on purpose: the reason names the service a
    real cell needs, and ``test_migration_coverage.py`` keeps the list honest
    against the map."""
    pytest.skip(f"no component-level cell for {legacy!r}: {SERVICE_SKIPS[legacy]}")


def test_component_cells_are_not_also_skipped():
    """A pair is proven or it is skipped, never recorded as both."""
    overlap = sorted(set(COMPONENT_CELLS) & set(SERVICE_SKIPS))
    assert not overlap, f"pairs claimed as covered and skipped at once: {overlap}"
