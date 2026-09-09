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
"""
import os
import uuid

import pytest

from .driver import BusServer, Capture, FallbackProcess, DISPATCH_TIMEOUT

CANONICAL_PING = "ovos.fallback.ping"
LEGACY_PING = "ovos.skills.fallback.ping"
LEGACY_PONG = "ovos.skills.fallback.pong"

OLD_SKILL_PYTHON = os.environ.get("BACKCOMPAT_SKILL_PYTHON_OLD")

pytestmark = pytest.mark.skipif(
    not OLD_SKILL_PYTHON,
    reason="set BACKCOMPAT_SKILL_PYTHON_OLD to a skill venv from build_venvs.sh")


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
    that has no idea the canonical spelling exists."""
    bus_server, skill = legacy_subscriber
    bus = bus_server.client()
    token = uuid.uuid4().hex
    pong = Capture(bus, LEGACY_PONG)
    try:
        bus.emit(_ping(token))
        assert pong.wait(timeout=DISPATCH_TIMEOUT), (
            "the legacy-only subscriber never answered a canonical ping, so "
            f"the emitter's wire twin did not reach it:\n{skill.log}")
        answered = {m.data.get("skill_id") for m in pong.messages}
        assert skill.skill_id in answered, answered
    finally:
        bus.close()


def test_the_twin_is_what_carries_it(legacy_subscriber):
    """The same emit with the emitter's wire twin turned off must NOT arrive.

    Without this the test above passes for any reason at all, including the
    subscriber having quietly bound the canonical spelling after all.
    """
    bus_server, skill = legacy_subscriber
    os.environ["OVOS_BUS_WIRE_LEGACY_TWINS"] = "false"
    try:
        bus = bus_server.client()
    finally:
        os.environ.pop("OVOS_BUS_WIRE_LEGACY_TWINS", None)
    token = uuid.uuid4().hex
    pong = Capture(bus, LEGACY_PONG)
    try:
        bus.emit(_ping(token))
        assert not pong.wait(timeout=3.0), (
            "the legacy-only subscriber answered a canonical ping with the "
            "wire twin disabled, so the twin is not what carries it")
    finally:
        bus.close()


def _ping(token: str):
    from ovos_bus_client.message import Message
    return Message(CANONICAL_PING, {"utterances": ["hello"], "lang": "en-us",
                                    "token": token},
                   {"session": {"session_id": token}})
