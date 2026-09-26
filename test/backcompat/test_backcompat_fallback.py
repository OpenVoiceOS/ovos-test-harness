"""T2.4 scenario 7 -- fallback (design §2.3 item 7).

Registration (``ovos.skills.fallback.register``), the ping/pong poll
(``ovos.skills.fallback.ping``/``.pong``), and the per-skill request/response
round trip (``ovos.skills.fallback.<skill_id>.request``/``.response``) --
all verbatim from ``ovos_workshop/skills/fallback.py`` on current dev, driven
through a real ``FallbackSkill`` subclass in ``skill_process.py``
(``BACKCOMPAT_ENABLE_FALLBACK=1``), never a hand-rolled stand-in for the
class's own bus wiring.

OWNER RULING (2026-08-14) on the ``can_answer`` abstract-method boundary
(workshop 9.3.9a1, #523): skill↔workshop is NOT a compat axis -- skills pin
min/max ovos-workshop and resolve as a unit with it, so "S=old-shaped
skill running under an S=new-abstract workshop" is not a reachable mix by
real dependency resolution (the same R1 collapse that already folds a
skill's resolved bus-client into the S axis, design §2.1). The
load-failure xfail cell this file used to build (a fallback skill that
never overrides ``can_answer``, deliberately instantiated against BOTH S
vintages to show it only breaks on S=new) has been REMOVED per this
ruling. This file now only ever builds one fallback skill shape -- a real
``can_answer`` override -- exercised under whichever S-axis workshop
vintage the combo already pins (``cells.py``'s existing S axis), never a
mixed skill/workshop vintage inside one container.

In its place: the resolution-tier metadata-skew guard (originally entity
item (f), now the GENERAL pattern per the ruling) gets its own instance
here, for the fallback fixture specifically -- see
``driver.assert_fixture_resolves_its_own_workshop_constraints``.
"""
import uuid

import pytest

from ovos_bus_client.message import Message

from .driver import (FALLBACK_PING_TOPIC, FALLBACK_PONG_TOPIC,
                     FALLBACK_REGISTER_TOPIC, SKILL_ID,
                     BusServer, Capture, SkillProcess,
                     assert_fixture_resolves_its_own_workshop_constraints,
                     boundary_xfail, fallback_can_answer_takes_message,
                     fallback_request_topic, fallback_response_topic)
from .test_mixed_version_matrix import COMBO, COMBOS, SKILL_PYTHON

pytestmark = pytest.mark.skipif(
    not COMBO or not SKILL_PYTHON,
    reason="needs BACKCOMPAT_COMBO and BACKCOMPAT_SKILL_PYTHON; see "
           "test/backcompat/build_venvs.sh")

#: Real-symbol, cross-venv capability probe (driver._skill_venv_probe),
#: computed once at collection time -- CI finding: the "stable" channel
#: pin (ovos-workshop==3.4.0) has FallbackSkill.can_answer(self,
#: utterances, lang), the pre-#339 two-parameter form; skill_process.py's
#: fixture always defines the modern single-parameter can_answer(self,
#: message) (matching what current docs teach). On the legacy signature,
#: FallbackSkill._handle_fallback_ack calls can_answer(utts, lang) --
#: TWO positional args -- against a one-parameter method: TypeError,
#: swallowed by the speak_errors=False wrapper into a log line, never a
#: pong. Guarded so bare collection (no BACKCOMPAT_SKILL_PYTHON set)
#: never calls the probe with an empty interpreter path.
_CAN_ANSWER_TAKES_MESSAGE = (fallback_can_answer_takes_message(SKILL_PYTHON)
                             if SKILL_PYTHON else True)

_CAN_ANSWER_SIGNATURE_XFAIL_REASON = boundary_xfail(
    boundary="ovos-workshop<5.0.0a1 (#339) has FallbackSkill.can_answer"
             "(self, utterances, lang) -- the pre-refactor two-parameter "
             "form. A skill written against current docs (can_answer(self, "
             "message)) never receives a pong on this vintage: "
             "_handle_fallback_ack calls it with 2 positional args, which "
             "raises TypeError inside the wrapped event handler "
             "(speak_errors=False swallows it into a log line, not a "
             "crash) -- so no pong is ever sent. Live-verified via "
             "driver.fallback_can_answer_takes_message against the "
             "CI-failing stable channel pin (3.4.0).",
    axes=("S",),
    blocked_on=None,
    owner="ovos-workshop",
    note="the ping/pong PROTOCOL itself is present verbatim on this "
         "vintage (ovos.skills.fallback.ping/.pong, register_fallback -- "
         "all live-verified present in 3.4.0's fallback.py); only the "
         "can_answer CALLING CONVENTION differs. Real-symbol probe, not "
         "a channel-wide assumption: the 'testing' channel pin "
         "(7.0.10a1) is already past #339 and is NOT gated by this "
         "marker -- live-verified its pong round trip passes today.")


@pytest.fixture(scope="module")
def server():
    if COMBO not in COMBOS:
        pytest.fail(f"unknown BACKCOMPAT_COMBO {COMBO!r}")
    s = BusServer()
    yield s
    s.stop()


@pytest.fixture(scope="module")
def fallback_skill(server):
    """The one fallback skill shape this file builds: a real
    ``can_answer`` override, under whichever S-axis workshop this combo
    already pins (see module docstring for why there is no second,
    mixed-vintage shape).

    The ``ovos.skills.fallback.register`` frame fires from inside
    ``initialize()``, i.e. DURING ``SkillProcess.__init__`` -- before this
    fixture (or any test) can bind a ``Capture`` on the driver's own bus
    client. Adversarial review caught an earlier draft that opened the
    capture only inside the test, AFTER this fixture had already returned
    a fully-initialized skill: that capture could never see the one real
    registration frame that ever fires, so the assertion on it was dead
    code -- the whole test stayed green even with ``register_fallback()``
    deleted from ``fallback.py`` outright. Fixed: bind the capture on a
    bus client that connects and starts listening BEFORE the skill
    process is spawned, so the real frame is actually caught.
    """
    import os
    bus = server.client()
    registered = Capture(bus, FALLBACK_REGISTER_TOPIC)
    os.environ["BACKCOMPAT_ENABLE_FALLBACK"] = "1"
    try:
        skill = SkillProcess(SKILL_PYTHON, server.xdg)
    finally:
        os.environ.pop("BACKCOMPAT_ENABLE_FALLBACK", None)
    yield skill, registered
    registered.close()
    skill.stop()


@pytest.mark.axes("S")
def test_registration_frame_fires_regardless_of_can_answer_signature(server, fallback_skill):
    """Positive control, ungated: ``register_fallback()`` must emit the
    real ``ovos.skills.fallback.register`` frame (captured BEFORE the
    skill process spawns -- see the ``fallback_skill`` fixture's
    docstring for why that ordering matters) on EVERY vintage this suite
    builds, including the legacy ``can_answer`` calling convention --
    registration itself never calls ``can_answer``, so it is not gated
    the way the ping/pong round trip below is.
    """
    skill, registered = fallback_skill
    assert registered.wait(timeout=15), (
        f"{COMBO}: no ovos.skills.fallback.register frame observed -- "
        f"register_fallback() may have been deleted or never called\n"
        f"{skill.log}")
    matching_reg = [m for m in registered.messages
                    if m.data.get("skill_id") == SKILL_ID]
    assert matching_reg, (
        f"registration frames never named {SKILL_ID}: "
        f"{[m.data for m in registered.messages]}")


@pytest.mark.xfail(not _CAN_ANSWER_TAKES_MESSAGE, strict=True,
                   reason=_CAN_ANSWER_SIGNATURE_XFAIL_REASON)
@pytest.mark.axes("S")
def test_a_can_answer_fallback_skill_answers_the_ping_pong_poll(server, fallback_skill):
    """The ping/pong round trip: on a vintage whose ``FallbackSkill.
    can_answer`` takes the modern single ``message`` parameter, a real
    ``can_answer`` override must construct, answer, and report
    ``can_handle=True``. Vintage-gated (``driver.
    fallback_can_answer_takes_message``) -- see this module's own
    boundary constant for why the legacy calling convention makes this
    genuinely fail instead."""
    skill, _registered = fallback_skill
    bus = server.client()
    pong = Capture(bus, FALLBACK_PONG_TOPIC)
    try:
        bus.emit(Message(FALLBACK_PING_TOPIC, {}))
        assert pong.wait(), f"{COMBO}: no fallback pong\n{skill.log}"
        matching = [m for m in pong.messages
                   if m.data.get("skill_id") == SKILL_ID]
        assert matching, f"pong messages did not include {SKILL_ID}: " \
                         f"{[m.data for m in pong.messages]}"
        assert matching[0].data["can_handle"] is True
    finally:
        pong.close()


@pytest.mark.axes("S", "C")
def test_the_fallback_handler_answers_exactly_once(server, fallback_skill):
    """The per-skill request/response round trip, and the exactly-once
    contract every fallback handler owes the poll: one request, one
    ``.response`` with ``result: True``."""
    skill, _registered = fallback_skill
    bus = server.client()
    token = uuid.uuid4().hex
    resp_topic = fallback_response_topic(SKILL_ID)
    resp = Capture(bus, resp_topic)
    try:
        bus.emit(Message(fallback_request_topic(SKILL_ID),
                         {"utterances": ["do the taco thing"], "token": token},
                         {"session": {"session_id": f"backcompat-fb-{token[:8]}"}}))
        assert resp.wait(), f"{COMBO}: no fallback response\n{skill.log}"
        resp.wait_for_count(2, timeout=1.5)
        assert len(resp.messages) == 1, (
            f"{COMBO}: fallback request answered {len(resp.messages)} times")
        assert resp.messages[0].data["result"] is True
    finally:
        resp.close()


@pytest.mark.axes("S")
def test_fallback_fixture_resolves_its_own_workshop_constraints(fallback_skill):
    """Resolution-tier metadata-skew guard, fallback-fixture instance
    (OWNER RULING 2026-08-14 -- see ``driver.
    assert_fixture_resolves_its_own_workshop_constraints`` and this
    module's docstring for why this replaces the removed load-failure
    cell): the fallback skill's own resolved ovos-workshop must actually
    CONTAIN (real specifier check, not string-sniffed) the ovos-bus-client
    this S-axis venv installed."""
    skill, _registered = fallback_skill
    assert_fixture_resolves_its_own_workshop_constraints(skill, COMBO)
