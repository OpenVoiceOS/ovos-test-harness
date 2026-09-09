"""Two skill containers of different vintages, on one bus, at the same time.

The 4-tuple cell space carries a single ``S`` axis, so it can say what
happens when *the* skill container is old or new, but not what happens when
an old one and a new one are both attached to the same bus. That
combination is the ordinary case in a deployment, not an exotic one: a skill
is resolved as its own container and two of them have no reason to agree on
a version.

What this asserts is the property the single-S cells cannot reach. The two
containers resolve different ``ovos-workshop`` majors, they bind different
spellings of their own dispatch topic, and each one answers the dispatch
addressed to it while staying silent on the other's.

The two venvs come from ``build_venvs.sh``: ``venv_skill_testing`` is the
distro testing channel's ``ovos-workshop``, ``venv_skill_new`` tracks
``ovos-workshop`` at dev.
"""
import os
import uuid

import pytest

from .driver import (BusServer, Capture, SkillProcess, DISPATCH_TIMEOUT)

SKILL_A = "backcompat.vintage.a"
SKILL_B = "backcompat.vintage.b"

HANDLED_TOPIC = "backcompat.skill.handled"

VENV_A = os.environ.get("BACKCOMPAT_SKILL_PYTHON_OLD")
VENV_B = os.environ.get("BACKCOMPAT_SKILL_PYTHON_NEW")

pytestmark = pytest.mark.skipif(
    not (VENV_A and VENV_B),
    reason="set BACKCOMPAT_SKILL_PYTHON_OLD and BACKCOMPAT_SKILL_PYTHON_NEW "
           "to two skill venvs built by build_venvs.sh")


@pytest.fixture(scope="module")
def two_vintages():
    bus = BusServer()
    a = SkillProcess(VENV_A, bus.xdg, skill_id=SKILL_A)
    b = SkillProcess(VENV_B, bus.xdg, skill_id=SKILL_B)
    try:
        yield bus, a, b
    finally:
        b.stop()
        a.stop()
        bus.proc.terminate()


def dispatch_topic(skill: SkillProcess) -> str:
    """The one topic this container actually bound for its intent."""
    bound = [t for t in skill.bound_topics
             if t.startswith(f"{skill.skill_id}:")
             and not t.endswith(".trigger")]
    assert len(bound) == 1, f"{skill.skill_id} bound {bound!r}"
    return bound[0]


def test_the_two_containers_are_different_vintages(two_vintages):
    """The premise. If both venvs resolved the same workshop there is no
    mixed-version cell here and every assertion below is vacuous."""
    _, a, b = two_vintages
    va = a.versions["ovos_workshop"]
    vb = b.versions["ovos_workshop"]
    assert va != vb, f"both containers resolved ovos-workshop {va}"
    assert va.split(".")[0] != vb.split(".")[0], (
        f"the two containers share a major: {va} and {vb}")


def test_each_container_binds_its_own_spelling(two_vintages):
    """The vintages disagree about how a dispatch topic is spelled, which is
    the reason a single dispatch has to reach both."""
    _, a, b = two_vintages
    assert dispatch_topic(a) != dispatch_topic(b).replace(SKILL_B, SKILL_A), (
        "both containers spell the dispatch topic the same way, so this cell "
        "is not crossing the boundary it claims to")


@pytest.mark.parametrize("target,other", [("a", "b"), ("b", "a")])
def test_a_dispatch_reaches_its_own_container_only(two_vintages, target, other):
    """Each container answers what is addressed to it, and neither answers
    for the other. A shared bus is not a shared identity."""
    bus_server, a, b = two_vintages
    skills = {"a": a, "b": b}
    to, notto = skills[target], skills[other]

    bus = bus_server.client()
    token = uuid.uuid4().hex
    handled = Capture(bus, HANDLED_TOPIC, token=token)
    try:
        bus.emit(_order(dispatch_topic(to), token))
        assert handled.wait(timeout=DISPATCH_TIMEOUT), (
            f"{to.skill_id} never answered on {dispatch_topic(to)}:\n{to.log}")
        answered = {m.data["skill_id"] for m in handled.messages}
        assert answered == {to.skill_id}, (
            f"expected only {to.skill_id} to answer, got {answered}")
        assert notto.skill_id not in answered
    finally:
        bus.close()


def test_a_canonical_dispatch_still_reaches_the_old_container(two_vintages):
    """The claim that makes the mixed bus work.

    The old container bound the suffixed spelling and nothing else, and its
    own ``ovos-bus-client`` is too old to carry the receive-side mirror. A
    core that has moved to the canonical spelling therefore reaches it only
    through the send-side legacy twin, which is built by the EMITTER's
    bus-client from the emitter's own migration map. Emitting the canonical
    topic here and seeing the old skill answer is that twin doing its job.
    """
    bus_server, a, _ = two_vintages
    legacy = dispatch_topic(a)
    assert legacy.endswith(".intent"), (
        f"this cell needs an old container that bound the suffixed spelling; "
        f"{a.skill_id} bound {legacy!r}")
    assert not a.versions["has_reemit_hook"], (
        "the old container carries the mirror itself, so the emitter's twin "
        "is not what this cell would be measuring")

    canonical = legacy[: -len(".intent")]
    assert canonical not in a.bound_topics

    bus = bus_server.client()
    token = uuid.uuid4().hex
    handled = Capture(bus, HANDLED_TOPIC, token=token)
    try:
        bus.emit(_order(canonical, token))
        assert handled.wait(timeout=DISPATCH_TIMEOUT), (
            f"{a.skill_id} never answered a canonical dispatch on "
            f"{canonical!r}, so the legacy twin did not reach it:\n{a.log}")
        assert {m.data["skill_id"] for m in handled.messages} == {a.skill_id}
    finally:
        bus.close()


def _order(topic: str, token: str):
    from ovos_bus_client.message import Message
    return Message(topic, {"token": token}, {"session": {"session_id": token}})
