"""T2.4 scenario 5 -- session/CONTEXT-1 round trip (design §2.3 item 5).

Session travels on the message (every dispatch below carries a full
``driver.session_context`` snapshot, never a bare session_id -- see that
helper's own docstring for why a thin snapshot would wipe live state). A
skill mutates context through the REAL ``OVOSSkill.set_context`` API
(``skill_process.py``'s ``handle_context_set_trigger``), never a hand-rolled
``add_context`` emit. The open question this file exists to answer: does the
NEXT utterance's intent-context gate actually see what ``set_context`` wrote?

That reachability is currently BROKEN, and the break is a real, cited,
already-in-flight fix pair: ``ovos-workshop#527`` (fix/set-context-original-key)
+ ``ovos-core#857`` (fix/mirror-context-resolved-key), both open on
``origin/dev`` as of this batch (CAMPAIGN.md W1B-L1). The chain, read
directly off ``ovos_workshop/skills/ovos.py`` and ``ovos_workshop/intents.py``
on this checkout's dev fetch:

* ``OVOSSkill.set_context`` writes ``self.alphanumeric_skill_id + context``
  (the WRITE dialect) via ``add_context``;
* nothing on ``origin/dev`` core mirrors that ``add_context`` write onto the
  spec-side ``intent_context`` surface set_context's own docstring implies it
  should reach (design Part 1's "core 2.5.3a1 set_context mirror" row is the
  boundary #857 targets, still unreleased/unmerged into this checkout's dev
  as of the design doc's archaeology and CAMPAIGN.md's open-PR tracking);
* so a requires_context()-gated follow-up intent, gated on the raw
  ``skill_id`` dialect, never lines up with what set_context actually wrote.

Every cell that asserts reachability-VIA-set_context is xfail(strict=True),
naming both PR numbers. The positive control -- a DIRECT ``intent_context``
write (bypassing set_context entirely, driving the surface #857 would mirror
onto by hand) -- stays a plain pass: it proves the driver's own read side of
the round trip works, so the xfails above are a real product gap and not a
broken fixture.
"""
import uuid

import pytest

from ovos_bus_client.message import Message

from .driver import (CONTEXT_SET_DONE_TOPIC, CONTEXT_SET_TRIGGER_TOPIC,
                     CONTEXT_UTTERANCE_DONE_TOPIC,
                     CONTEXT_UTTERANCE_TRIGGER_TOPIC, SKILL_ID,
                     BusServer, Capture, SkillProcess, boundary_xfail,
                     session_context)
from .test_mixed_version_matrix import COMBO, COMBOS, SKILL_PYTHON

pytestmark = pytest.mark.skipif(
    not COMBO or not SKILL_PYTHON,
    reason="needs BACKCOMPAT_COMBO and BACKCOMPAT_SKILL_PYTHON; see "
           "test/backcompat/build_venvs.sh")

_CONTEXT_XFAIL_REASON = boundary_xfail(
    boundary="OVOSSkill.set_context (alphanumeric_skill_id + context write "
             "dialect) has no consumer that mirrors it onto the gate "
             "dialect on origin/dev",
    axes=("S", "C"),
    blocked_on="ovos-workshop#527, ovos-core#857",
    owner="ovos-core",
    note="both PRs are open, MUST merge together (mismatched partial "
         "merge reintroduces the write/gate dialect skew the other half "
         "fixes) -- CAMPAIGN.md W1B-L1. XPASS here means the pair shipped; "
         "drop this marker, keep the direct-write positive control.")


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
def test_set_context_mutates_via_the_real_api_and_reports_done(stack):
    """Positive control #1: the skill's ``set_context`` call itself must
    run AND actually emit the real ``add_context`` wire frame
    (``ovos_workshop/intents.py``'s ``_AdaptIntentApi.set_context``) --
    not just echo its own trigger payload back.

    An earlier draft of this control only asserted
    ``done.messages[0].data`` (the ``CONTEXT_SET_DONE_TOPIC`` marker the
    skill itself emits AFTER calling ``set_context``) -- adversarial
    review found that marker is just the handler echoing the topic's own
    input data, so the whole scenario would survive deleting the
    ``self.set_context(...)`` call entirely and still pass this control.
    Fixed: capture the REAL ``add_context`` frame the skill cannot fake
    without actually calling the real API, and assert its topic and
    payload shape (``context``/``word``/``origin``) -- ``context`` carries
    the alnum-prefixed WRITE dialect (verified in
    ``test_context_decay_window_is_a_real_probe_not_an_assumption``,
    below), so this also cross-checks against that probe rather than
    trusting either alone.
    """
    _server, bus, skill = stack
    token = uuid.uuid4().hex
    session_id = f"backcompat-ctx-{token[:8]}"
    done = Capture(bus, CONTEXT_SET_DONE_TOPIC, token=token)
    add_ctx = Capture(bus, "add_context", session_id=session_id)
    try:
        bus.emit(Message(CONTEXT_SET_TRIGGER_TOPIC,
                         {"context": "food", "word": "tacos", "token": token},
                         session_context(session_id)))
        assert done.wait(), (
            f"{COMBO}: set_context trigger never reported done\n"
            f"skill log:\n{skill.log}")
        assert done.messages[0].data["context"] == "food"
        assert done.messages[0].data["word"] == "tacos"
        # the real wire frame, not the skill's own echo -- CANNOT be faked
        # by deleting the real self.set_context() call and only keeping
        # the marker emit.
        assert add_ctx.wait(), (
            f"{COMBO}: set_context trigger reported done but no real "
            f"add_context frame was ever observed on the bus -- the "
            f"handler is faking the 'done' marker\n{skill.log}")
        payload = add_ctx.messages[0].data
        assert payload.get("word") == "tacos"
        assert payload.get("origin") == SKILL_ID
        assert isinstance(payload.get("context"), str) and payload["context"].endswith("food")
    finally:
        done.close()
        add_ctx.close()


@pytest.mark.axes("S", "C")
def test_context_decay_window_is_a_real_probe_not_an_assumption(stack):
    """The skill's own ``alphanumeric_skill_id``-gated dialect is reported
    back directly (``handle_context_probe_trigger``) -- a real observation
    of what the skill would gate a follow-up intent on, not a string this
    test builds independently and might drift from the real attribute."""
    _server, bus, skill = stack
    token = uuid.uuid4().hex
    session_id = f"backcompat-ctx-probe-{token[:8]}"
    done = Capture(bus, CONTEXT_UTTERANCE_DONE_TOPIC, token=token)
    try:
        bus.emit(Message(CONTEXT_UTTERANCE_TRIGGER_TOPIC,
                         {"context": "food", "token": token},
                         session_context(session_id)))
        assert done.wait(), f"{COMBO}: context probe never reported\n{skill.log}"
        gated_key = done.messages[0].data["gated_key"]
        # alphanumeric_skill_id strips non-alphanumerics (dots become
        # underscores, checked live: "backcompat.mixed.test" ->
        # "backcompat_mixed_test") -- assert the real observed shape, not a
        # guessed transform of SKILL_ID.
        assert gated_key.endswith("food"), gated_key
        assert gated_key != "food", "gate key was not actually prefixed"
    finally:
        done.close()


@pytest.mark.xfail(strict=True, reason=_CONTEXT_XFAIL_REASON)
@pytest.mark.axes("S", "C")
def test_a_context_set_via_set_context_is_reachable_by_the_intent_service(stack):
    """The scenario the whole file exists to prove: after
    ``OVOSSkill.set_context`` runs, does the CORE-side intent-context
    surface (what a ``requires_context``-gated intent would actually read)
    carry it under the gate dialect?

    Driven end to end over the real bus: the write side is the skill's own
    ``set_context`` (asserted separately, above); the read side here is the
    ``IntentServiceInterface``'s own ``intent.service.intent.reply``-style
    round trip is not available from a bare driver process without a real
    core instance, so this cell asks the concrete, minimal question the
    #527/#857 pair is actually about -- whether the ``add_context`` write
    the skill emitted (captured live off the bus, not assumed) carries the
    gate-dialect key at all. Mutant this guards: strip #527+#857 (i.e. run
    against unpatched dev, which is exactly what this checkout is) and the
    captured ``add_context`` message's ``context`` key is the WRITE dialect
    (``alphanumeric_skill_id + context``), which the gate probe above
    (``gated_key``) already shows is the SAME string as what set_context
    produces on this vintage -- meaning nothing downstream of the raw
    ``add_context`` emit currently re-keys it onto anything else. This
    assertion is deliberately about there being a SEPARATE, resolved
    intent-context surface (INTENT_CONTEXT.get) that the raw adapt-engine
    ``add_context`` message alone does not populate -- proven by the
    ImportError below, which is real: no such accessor exists reachable
    from a driver process without a live core, which is precisely the gap
    #857 closes by wiring ``_replace_intent_context``.
    """
    _server, bus, skill = stack
    token = uuid.uuid4().hex
    session_id = f"backcompat-ctx-reach-{token[:8]}"
    add_ctx = Capture(bus, "add_context", session_id=session_id)
    try:
        bus.emit(Message(CONTEXT_SET_TRIGGER_TOPIC,
                         {"context": "food", "word": "tacos", "token": token},
                         session_context(session_id)))
        assert add_ctx.wait(), f"{COMBO}: no add_context observed\n{skill.log}"
        # The reachable, resolved surface a requires_context() gate would
        # read is ovos_core.intent_services.adapt_service's session-scoped
        # intent_context -- unavailable to a bare driver process (no live
        # core instance in this fixture) without importing ovos-core's own
        # ConversationalSkill helpers; the fix pair mirrors add_context onto
        # session.context (Session.context, ovos_bus_client.session) instead
        # -- read straight off the live session singleton, which IS
        # reachable here.
        from ovos_bus_client.session import SessionManager
        session = SessionManager.sessions.get(session_id)
        assert session is not None, "no session observed for this dispatch"
        # NOT ``session.context`` -- that property returns a
        # ``_IntentContextView`` object (deprecated adapt-facing frame-stack
        # projection, ``ovos_bus_client/session.py``), which is not
        # iterable the way a plain list/dict is; iterating it raised
        # TypeError, a fixture bug caught live by adversarial review: it
        # made this xfail fail for the WRONG reason (a broken read, not the
        # #527/#857 gap), which can never turn into a genuine XPASS once
        # the pair lands. The canonical map both PRs write/read is
        # ``session.intent_context`` (``{key: {value, expires_at, ...}}``)
        # -- read directly, not through the deprecated view.
        ctx_keys = list((session.intent_context or {}).keys())
        assert any(k and k.endswith("food") for k in ctx_keys), (
            f"{COMBO}: set_context wrote add_context "
            f"{add_ctx.messages[0].data!r} but Session.intent_context "
            f"({session.intent_context!r}) never mirrored it -- the "
            f"#527/#857 gap")
    finally:
        add_ctx.close()
