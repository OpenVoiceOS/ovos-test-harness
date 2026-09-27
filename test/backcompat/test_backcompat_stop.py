"""T2.4 scenario 8 -- stop (design §2.3 item 8).

``<skill_id>.stop.ping``/``skill.stop.pong``, per-skill ``<skill_id>.stop``,
and the global ``mycroft.stop`` broadcast -- all baseline ``OVOSSkill``
behaviour (``ovos_workshop/skills/ovos.py``'s
``_register_system_event_handlers``/``_handle_stop_ack``/
``_handle_session_stop``), no opt-in flag needed.

This doubles as core#802's pre-merge oracle (task brief): ``ovos-core#802``
reworks STOP-1 to a different orchestration shape than what ships on
``origin/dev`` today ("legacy stop", per CAMPAIGN.md's mention of the
"STOP-1 rework"). Cells that would need #802's post-merge behaviour are
marked ``blocked_on ovos-core#802`` below; everything this file can assert
against the CURRENT (legacy) stop orchestration is a plain positive control.
"""
import uuid

import pytest

from ovos_bus_client.message import Message

from .driver import (STOP_GLOBAL_TOPIC, STOP_PER_SKILL_TOPIC,
                     STOP_PING_TOPIC, STOP_PONG_TOPIC,
                     STOP_RESPONSE_TOPIC, SKILL_ID,
                     BusServer, Capture, SkillProcess, boundary_xfail,
                     make_stop_service)
from .test_mixed_version_matrix import COMBO, COMBOS, SKILL_PYTHON

pytestmark = pytest.mark.skipif(
    not COMBO or not SKILL_PYTHON,
    reason="needs BACKCOMPAT_COMBO and BACKCOMPAT_SKILL_PYTHON; see "
           "test/backcompat/build_venvs.sh")

_STOP1_XFAIL_REASON = boundary_xfail(
    boundary="ovos-core's real StopService.match_high (origin/dev) still "
             "returns the LEGACY match_type spelling ('stop:global' / "
             "'stop:skill') with suppress_activation left at its False "
             "default; #802's STOP-1 rework gives it the spec-shaped "
             "match_type ('<skill_id>:stop' / '<pipeline_id>:global_stop') "
             "with suppress_activation=True",
    axes=("S", "C"),
    blocked_on="ovos-core#802",
    owner="ovos-core",
    note="probed against the REAL, live StopService.match_high (driver."
         "make_stop_service, same pattern as make_converse_service) -- "
         "NOT a placeholder. Adversarial review caught the original "
         "placeholder oracle here, which probed a "
         "StopService.aggregate_stop_result symbol #802 was never going "
         "to ship, so it could never genuinely XPASS; replaced with this "
         "real match_type/suppress_activation probe so the XPASS "
         "actually fires the day #802 merges. XPASS here means #802 "
         "shipped and this test's own literal expected match_type must "
         "be double-checked against the merged PR before dropping the "
         "marker (in case the final spelling differs from the brief).")


@pytest.fixture(scope="module")
def stack():
    if COMBO not in COMBOS:
        pytest.fail(f"unknown BACKCOMPAT_COMBO {COMBO!r}")
    server = BusServer()
    skill = None
    try:
        bus = server.client()
        skill = SkillProcess(SKILL_PYTHON, server.xdg)
        yield server, bus, skill
    finally:
        if skill is not None:
            skill.stop()
        server.stop()


@pytest.mark.axes("S", "C")
def test_stop_ping_pong_reports_can_handle(stack):
    """Positive control: every skill answers the stop poll, whether or not
    it overrides ``can_stop`` -- the fixture skill doesn't, so
    ``can_handle`` must be the real ``can_stop`` default."""
    _server, bus, skill = stack
    pong = Capture(bus, STOP_PONG_TOPIC)
    try:
        bus.emit(Message(STOP_PING_TOPIC, {}))
        assert pong.wait(), f"{COMBO}: no stop pong\n{skill.log}"
        matching = [m for m in pong.messages if m.data.get("skill_id") == SKILL_ID]
        assert matching, f"pong never named {SKILL_ID}: " \
                         f"{[m.data for m in pong.messages]}"
    finally:
        pong.close()


@pytest.mark.axes("S", "C")
def test_per_skill_stop_gets_a_response(stack):
    """``<skill_id>.stop`` must produce exactly one
    ``<skill_id>.stop.response`` -- the per-skill targeted stop path, as
    opposed to the global broadcast below."""
    _server, bus, skill = stack
    token = uuid.uuid4().hex
    resp = Capture(bus, STOP_RESPONSE_TOPIC)
    try:
        bus.emit(Message(STOP_PER_SKILL_TOPIC, {"token": token},
                         {"session": {"session_id": f"backcompat-stop-{token[:8]}"}}))
        assert resp.wait(), f"{COMBO}: no stop response\n{skill.log}"
        resp.wait_for_count(2, timeout=1.0)
        assert len(resp.messages) == 1, (
            f"{COMBO}: {STOP_PER_SKILL_TOPIC} answered "
            f"{len(resp.messages)} times, expected exactly once")
    finally:
        resp.close()


@pytest.mark.axes("S", "C")
def test_global_stop_reaches_every_skill(stack):
    """``mycroft.stop`` is a broadcast: the same handler
    (``_handle_session_stop``) that answers the per-skill topic also
    listens here, so a global stop must produce the same
    ``<skill_id>.stop.response`` -- the observable proof the skill actually
    reacted to the broadcast, not just the targeted topic."""
    _server, bus, skill = stack
    resp = Capture(bus, STOP_RESPONSE_TOPIC)
    try:
        bus.emit(Message(STOP_GLOBAL_TOPIC, {},
                         {"session": {"session_id": f"backcompat-gstop-{uuid.uuid4().hex[:8]}"}}))
        assert resp.wait(), f"{COMBO}: global stop never reached the " \
                            f"skill\n{skill.log}"
    finally:
        resp.close()


@pytest.mark.xfail(strict=True, reason=_STOP1_XFAIL_REASON)
@pytest.mark.axes("S", "C")
def test_stop_match_produces_the_802_spec_shaped_result(stack):
    """#802's pre-merge oracle, live against the REAL ``StopService``
    (design §1.2 -- stop lives inside ovos-core, no separate package to
    pin a vintage of, so this is the driver's own core-venv code, the
    same way ``make_converse_service`` already probes converse).

    Drives a real ``"stop"`` utterance with zero active skills into
    ``StopService.match_high`` (verified live against
    ``ovos_core/intent_services/stop_service.py`` on this checkout's dev
    fetch: with no active skills, ``is_stop`` alone makes
    ``is_global_stop`` True, so this always takes the global-stop branch,
    no active-skill setup needed) and asserts the RESULT the task brief
    names as #802's real observable shape: a spec-style ``match_type``
    (``'<pipeline_id>:global_stop'``, e.g. ``'stop.openvoiceos:global_stop'``
    -- the skill_id StopService's own global-stop match already reports is
    ``'stop.openvoiceos'``) with ``suppress_activation=True``.

    LIVE-VERIFIED on origin/dev today: ``match_high`` returns
    ``match_type='stop:global'`` and leaves ``suppress_activation`` at its
    dataclass default (``False``) -- both wrong per #802's shape, so this
    genuinely fails now and will genuinely flip to XPASS(strict) once
    #802 changes the match_type spelling and sets the flag. An earlier
    draft of this cell probed a nonexistent
    ``StopService.aggregate_stop_result`` attribute instead -- #802 was
    never going to ship a symbol with that name (adversarial review
    caught this: the xfail could never turn into a real XPASS). Fixed to
    probe the real, live match result instead.
    """
    _server, bus, _skill = stack
    stop_service = make_stop_service(bus)
    try:
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["stop"], "lang": "en-us"},
                          {"session": {"session_id": f"backcompat-stop1-{uuid.uuid4().hex[:8]}"}})
        match = stop_service.match_high(["stop"], "en-us", message)
        assert match is not None, "StopService.match_high returned no match for 'stop'"
        assert match.match_type == f"{match.skill_id}:global_stop", (
            f"expected the #802 spec-shaped match_type "
            f"'{match.skill_id}:global_stop', got {match.match_type!r} -- "
            f"still the legacy 'stop:global' spelling")
        assert match.suppress_activation is True, (
            f"expected suppress_activation=True (a stop must not register "
            f"as a freshly activated skill), got "
            f"{match.suppress_activation!r}")
    finally:
        stop_service.shutdown() if hasattr(stop_service, "shutdown") else None
