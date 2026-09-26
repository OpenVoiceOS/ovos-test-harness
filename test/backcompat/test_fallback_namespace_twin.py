"""Back-compat cells for the four fallback topic twins.

ovos-spec-tools 1.12.0a1 (#146) added four entries to
:data:`ovos_spec_tools.messages.MIGRATION_MAP`:

==================================  ===========================
legacy topic                        spec topic
==================================  ===========================
``ovos.skills.fallback.register``   ``ovos.fallback.register``
``ovos.skills.fallback.deregister`` ``ovos.fallback.deregister``
``ovos.skills.fallback.ping``       ``ovos.fallback.ping``
``ovos.skills.fallback.pong``       ``ovos.fallback.pong``
==================================  ===========================

Each entry is a promise: a component that speaks the old name and a
component that speaks the new name still hear each other. These cells drive
that promise on a real ``ovos-messagebus`` with real ``MessageBusClient``
instances, for each twin and in both directions.

Three things are asserted per twin:

1. A current subscriber hears the OTHER spelling exactly once, with the
   bus-client flags at their default position. Exactly once, because the
   receive-side counterpart and the send-side wire twin must not both
   deliver.
2. A spec-spelled emit puts a legacy-spelled frame on the wire. A raw
   websocket reader stands in for a subscriber with no translator (an old
   bus-client). It sees only literal frames, so this is the delivery an old
   subscriber depends on.
3. Positive control, with both flags OFF: the same spelling still arrives,
   and the other spelling does not. This proves that (1) and (2) come from
   the flags and not from a listener that hears everything.

The gate is the env var ``FALLBACK_TWIN_CELLS``, never importability. The
job that installs ``ovos-messagebus`` sets it, so a broken install fails
these cells instead of skipping them.
"""
import json
import os
import threading
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("FALLBACK_TWIN_CELLS") != "1",
    reason="fallback twin cells need a real ovos-messagebus; set "
           "FALLBACK_TWIN_CELLS=1 where it is installed")

#: legacy topic -> spec topic, spelled out so a MIGRATION_MAP change that
#: renames a twin fails test_map_still_names_these_twins, not a timeout.
FALLBACK_TWINS = {
    "ovos.skills.fallback.register": "ovos.fallback.register",
    "ovos.skills.fallback.deregister": "ovos.fallback.deregister",
    "ovos.skills.fallback.ping": "ovos.fallback.ping",
    "ovos.skills.fallback.pong": "ovos.fallback.pong",
}

#: How long a cell waits after the emit before it counts. A duplicate
#: delivery lands inside this window, so the count is read after it closes.
SETTLE = 0.8

DIRECTIONS = [(legacy, spec) for legacy, spec in FALLBACK_TWINS.items()] + \
             [(spec, legacy) for legacy, spec in FALLBACK_TWINS.items()]


class _WireReader:
    """A raw websocket client on the bus: it records every literal frame and
    has no namespace translator."""

    def __init__(self, port: int):
        import websocket
        self.frames = []
        self._lock = threading.Lock()
        self._open = threading.Event()
        self.ws = websocket.WebSocketApp(
            f"ws://127.0.0.1:{port}/core",
            on_open=lambda _ws: self._open.set(),
            on_message=self._on_message)
        threading.Thread(target=self.ws.run_forever, daemon=True).start()
        if not self._open.wait(30):
            raise RuntimeError("raw wire reader could not connect to the bus")

    def _on_message(self, _ws, raw):
        frame = json.loads(raw)
        with self._lock:
            self.frames.append(frame)

    def topics_for(self, token: str) -> list:
        with self._lock:
            return [f["type"] for f in self.frames
                    if (f.get("data") or {}).get("token") == token]

    def close(self):
        self.ws.close()


@pytest.fixture(scope="module")
def bus_server():
    from .driver import BusServer
    server = BusServer()
    wire = None
    try:
        wire = _WireReader(server.port)
        yield server, wire
    finally:
        if wire is not None:
            wire.close()
        server.stop()


@pytest.fixture(scope="module")
def default_pair(bus_server):
    """Emitter and subscriber with the bus-client flags at their defaults."""
    server, _ = bus_server
    emitter, subscriber = server.client(), server.client()
    yield emitter, subscriber
    emitter.close()
    subscriber.close()


@pytest.fixture(scope="module")
def flags_off_pair(bus_server):
    """Emitter and subscriber with OVOS_BUS_EMIT_LEGACY and OVOS_BUS_MODERNIZE
    both false."""
    server, _ = bus_server
    emitter = server.client(emit_legacy=False, modernize=False)
    subscriber = server.client(emit_legacy=False, modernize=False)
    yield emitter, subscriber
    emitter.close()
    subscriber.close()


def _emit_and_count(emitter, subscriber, emit_topic, listen_topics):
    """Emit one tokenised message; return (token, {topic: count})."""
    from ovos_bus_client.message import Message

    from .driver import Capture
    token = uuid.uuid4().hex
    caps = {t: Capture(subscriber, t, token=token) for t in listen_topics}
    try:
        emitter.emit(Message(emit_topic, {"token": token}))
        time.sleep(SETTLE)
        return token, {t: len(c.messages) for t, c in caps.items()}
    finally:
        for c in caps.values():
            c.close()


def test_map_still_names_these_twins():
    """The cells below are only about MIGRATION_MAP if the map still pairs
    these topics."""
    from ovos_spec_tools.messages import MIGRATION_MAP
    for legacy, spec in FALLBACK_TWINS.items():
        assert legacy in MIGRATION_MAP, f"{legacy} left MIGRATION_MAP"
        assert MIGRATION_MAP[legacy].value == spec, (
            f"MIGRATION_MAP now pairs {legacy} with "
            f"{MIGRATION_MAP[legacy].value}, not {spec}")


@pytest.mark.parametrize("emit_topic,other_topic", DIRECTIONS,
                         ids=[f"{a}->{b}" for a, b in DIRECTIONS])
def test_subscriber_hears_the_other_spelling_once(default_pair, emit_topic,
                                                  other_topic):
    """Default flags: a subscriber on the other spelling receives the
    message exactly once."""
    emitter, subscriber = default_pair
    _, counts = _emit_and_count(emitter, subscriber, emit_topic,
                                [other_topic])
    assert counts[other_topic] == 1, (
        f"emit on {emit_topic}: a subscriber on {other_topic} received "
        f"{counts[other_topic]} messages, expected exactly 1")


@pytest.mark.parametrize("legacy,spec", list(FALLBACK_TWINS.items()))
def test_spec_emit_puts_a_legacy_frame_on_the_wire(bus_server, default_pair,
                                                   legacy, spec):
    """Default flags: a spec-spelled emit puts a legacy-spelled frame on the
    wire, which is the only delivery a subscriber with no translator gets."""
    _, wire = bus_server
    emitter, subscriber = default_pair
    token, _ = _emit_and_count(emitter, subscriber, spec, [])
    frames = wire.topics_for(token)
    assert frames.count(spec) == 1, f"wire frames for the emit: {frames}"
    assert frames.count(legacy) == 1, (
        f"emit on {spec}: no legacy {legacy} frame on the wire, so a "
        f"subscriber with no translator never hears it; frames: {frames}")


@pytest.mark.parametrize("emit_topic,other_topic", DIRECTIONS,
                         ids=[f"{a}->{b}" for a, b in DIRECTIONS])
def test_positive_control_flags_off(flags_off_pair, emit_topic, other_topic):
    """Both flags OFF: the same spelling arrives once and the other spelling
    does not arrive, so the default-flag cells measure the flags."""
    emitter, subscriber = flags_off_pair
    _, counts = _emit_and_count(emitter, subscriber, emit_topic,
                                [emit_topic, other_topic])
    assert counts[emit_topic] == 1, (
        f"flags OFF: a subscriber on {emit_topic} received "
        f"{counts[emit_topic]} messages for its own spelling; the listener "
        f"is dead and no cell in this module can be trusted")
    assert counts[other_topic] == 0, (
        f"flags OFF: a subscriber on {other_topic} still received "
        f"{counts[other_topic]} messages; the default-flag cells do not "
        f"measure the flags")
