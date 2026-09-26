"""The fallback poll across two vintages, on a real bus.

OVOS-FALLBACK-1 §6.1 names the poll pair `ovos.fallback.ping` and
`ovos.fallback.pong`. Every shipped FallbackSkill subscribes to the legacy
`ovos.skills.fallback.ping` alone, so the day a core emits the canonical
spelling the only thing still reaching those skills is the legacy twin that
ovos-bus-client puts on the wire.

That twin is built by the EMITTER's own client, from the emitter's own
migration map. The receiving container has no say in it, and does not need a
map, a translator, or any spec-tools at all. A single-process test cannot show
that, because one process has one bus-client and therefore one map; this cell
runs the emitter and the subscriber as separate processes from separate venvs
so the asymmetry is real.

The subscriber comes from `build_venvs.sh`'s `venv_skill_testing`, the distro
testing channel's ovos-workshop.

The answer travelling BACK is the other half, and it is where this rig found a
real defect. The old subscriber replies with the ping's context, so its pong
inherited `_namespace_compat_twin` and a modern receiver read a genuine answer
as a duplicate. ovos-bus-client#377 fixed that by believing the marker only
when the canonical frame was witnessed. Both directions are asserted below.
"""
import json
import os
import threading
import time
import uuid

import pytest
import websocket

from .driver import BusServer, Capture, FallbackProcess, DISPATCH_TIMEOUT

CANONICAL_PING = "ovos.fallback.ping"
LEGACY_PING = "ovos.skills.fallback.ping"
LEGACY_PONG = "ovos.skills.fallback.pong"

# This file read BACKCOMPAT_SKILL_PYTHON_OLD, a name nothing exported, so the
# skipif below was always true: all four cells skipped in every matrix job and
# the job still reported green.
#
# The name it needs is BACKCOMPAT_WIRE_TWIN_PYTHON, not BACKCOMPAT_SKILL_PYTHON.
# The premise below is a subscriber carrying NO ovos_spec_tools, and
# venv_skill_old pins ovos-spec-tools==1.10.0a1 (build_venvs.sh), so pointing
# here at the cell's own skill venv makes the premise false: the assertion reads
# '1.10.0a1' where it requires 'absent'. Only venv_wire_twin_old is genuinely
# pre-spec-tools (bus-client==1.5.0, no NamespaceTranslator), and it is the venv
# test_wire_twin_old_listener.py gates on under this same name.
OLD_SKILL_PYTHON = os.environ.get("BACKCOMPAT_WIRE_TWIN_PYTHON")

pytestmark = pytest.mark.skipif(
    not OLD_SKILL_PYTHON,
    reason="set BACKCOMPAT_WIRE_TWIN_PYTHON to venv_wire_twin_old from "
           "build_venvs.sh")


@pytest.fixture(scope="module")
def legacy_subscriber():
    bus = BusServer()
    skill = FallbackProcess(OLD_SKILL_PYTHON, bus.xdg,
                            skill_id="backcompat.fallback.old")
    try:
        yield bus, skill
    finally:
        skill.stop()
        bus.proc.terminate()


def test_the_subscriber_is_legacy_only_and_unaided(legacy_subscriber):
    """The premise every assertion below rests on. This container listens for
    the legacy poll and for nothing canonical, and it carries neither the
    send-side twin nor a migration map of its own, so nothing local to it can
    rescue a canonical emit."""
    _, skill = legacy_subscriber
    assert LEGACY_PING in skill.bound_topics
    assert CANONICAL_PING not in skill.bound_topics
    assert skill.versions["has_namespace_twin"] is False
    assert skill.versions["ovos_spec_tools"] == "absent"


def test_a_canonical_ping_reaches_the_legacy_only_subscriber(legacy_subscriber):
    """The compatibility claim itself: a modern emitter reaches a container
    that has no idea the canonical spelling exists.

    Read off a RAW websocket, not off a modern bus-client. A modern client
    suppresses the answer (see the cell below), so a modern client cannot be
    the instrument that decides whether the answer exists.
    """
    bus_server, skill = legacy_subscriber
    wire = RawWire(bus_server.port)
    bus = bus_server.client()
    token = uuid.uuid4().hex
    try:
        wire.clear()
        bus.emit(_ping(token))
        twin = wire.wait(LEGACY_PING, timeout=DISPATCH_TIMEOUT)
        assert twin is not None, (
            f"the emitter put no legacy twin on the wire:\n{wire.types()}")
        assert twin["context"].get("_namespace_compat_twin") is True

        pong = wire.wait(LEGACY_PONG, timeout=DISPATCH_TIMEOUT)
        assert pong is not None, (
            "the legacy-only subscriber never answered the twin:\n"
            f"{wire.types()}\n{skill.log}")
        assert pong["data"].get("skill_id") == skill.skill_id, pong["data"]
    finally:
        bus.close()
        wire.close()


def test_a_modern_listener_is_delivered_the_pong(legacy_subscriber):
    """What a modern caller actually gets.

    This cell was `xfail(strict=True)` while the receive rule suppressed any
    frame carrying `_namespace_compat_twin`. The old subscriber copies the
    ping's context into its reply, marker included (OVOS-MSG-1 5.2 preserves
    every other context key), so a genuine answer looked like a duplicate of
    a canonical frame that never existed.

    ovos-bus-client#377 makes the marker believable only when the canonical
    frame was actually witnessed, so an inherited marker no longer suppresses
    anything. The cell turned XPASS the moment that landed, which is what a
    strict xfail is for; the marker is gone and the assertion stands on its
    own.
    """
    bus_server, skill = legacy_subscriber
    bus = bus_server.client()
    token = uuid.uuid4().hex
    pong = Capture(bus, LEGACY_PONG)
    try:
        bus.emit(_ping(token))
        assert pong.wait(timeout=DISPATCH_TIMEOUT), (
            "no modern listener was given the pong, though the raw wire "
            f"carries it:\n{skill.log}")
    finally:
        bus.close()


def test_the_twin_is_what_carries_it(legacy_subscriber):
    """The same emit with the emitter's wire twin turned off must put NO
    legacy frame on the wire.

    Without this the cell above passes for any reason at all, including the
    subscriber having quietly bound the canonical spelling after all. The
    flag is read from the environment at client construction, so it is set
    around the build of this one client and restored at once.
    """
    bus_server, skill = legacy_subscriber
    wire = RawWire(bus_server.port)
    os.environ["OVOS_BUS_WIRE_LEGACY_TWINS"] = "false"
    try:
        bus = bus_server.client()
    finally:
        os.environ.pop("OVOS_BUS_WIRE_LEGACY_TWINS", None)
    token = uuid.uuid4().hex
    try:
        wire.clear()
        bus.emit(_ping(token))
        assert wire.wait(CANONICAL_PING, timeout=DISPATCH_TIMEOUT), (
            f"the canonical emit itself never reached the wire:\n{wire.types()}")
        assert wire.wait(LEGACY_PING, timeout=3.0) is None, (
            "a legacy twin reached the wire with the twin flag off, so the "
            f"flag is not what puts it there:\n{wire.types()}")
        assert wire.wait(LEGACY_PONG, timeout=1.0) is None, (
            "the legacy-only subscriber answered with no twin on the wire, "
            f"so the twin is not what carries it:\n{wire.types()}")
    finally:
        bus.close()
        wire.close()


class RawWire:
    """Every frame the bus broadcast, read off a bare websocket.

    No bus-client, so nothing here bridges, twins, modernizes or suppresses:
    this is the wire itself, which is the only instrument that can settle
    what an emitter sent and what a subscriber answered.
    """

    def __init__(self, port: int):
        self.frames = []
        self._ready = threading.Event()
        self._ws = websocket.WebSocketApp(
            f"ws://127.0.0.1:{port}/core",
            on_message=lambda _w, raw: self.frames.append(raw),
            on_open=lambda _w: self._ready.set())
        threading.Thread(target=self._ws.run_forever, daemon=True).start()
        assert self._ready.wait(10), "raw websocket never opened"

    def clear(self):
        del self.frames[:]

    def _parsed(self):
        out = []
        for raw in list(self.frames):
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
        return out

    def types(self):
        return [d.get("type") for d in self._parsed()]

    def wait(self, msg_type: str, timeout: float):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for d in self._parsed():
                if d.get("type") == msg_type:
                    return d
            time.sleep(0.1)
        return None

    def close(self):
        self._ws.close()


def _ping(token: str):
    from ovos_bus_client.message import Message
    return Message(CANONICAL_PING, {"utterances": ["hello"], "lang": "en-us",
                                    "token": token},
                   {"session": {"session_id": token}})
