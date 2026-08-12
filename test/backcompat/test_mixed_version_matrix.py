"""Mixed-version back-compat matrix: a real bus, two venvs, four combos.

Why this exists
---------------

The conformance suites in ``test/conformance/`` install one stack from
``requirements.txt`` and run against it, and pip installs one package per name.
That is the harness's documented single-ref-per-repo limitation, and it makes a
whole class of bug invisible here: the breakage this suite is about is
*definitionally* cross-version, a skill container frozen months ago talking to
a stack that moved on. Seeing it needs two package sets alive at once, which
means two venvs and a real websocket between them.

This is the harness's cross-repo home for that pattern. ``ovos-core`` carries
its own copy of this suite, deliberately: a stack contract is pinned where the
stack lives, so a breakage is traceable to the repo that caused it. The two
copies are meant to run in parallel and say the same thing.

What moved
----------

OVOS-MSG-1 §2.1.1 builds the per-intent dispatch topic as
``<skill_id>:<intent_name>``. Old ``ovos-workshop`` built it from the
padatious resource **filename**, so the authoring extension leaked onto the
wire as ``<skill_id>:food.order.intent``. Two independent changes then landed:

* ``ovos-padatious >= 2.0.1a1`` folds the suffixed id onto the canonical
  ``<skill_id>:food.order`` at **registration** time, so every match — and
  therefore every dispatch, since ``ovos-core`` forwards ``match.match_type``
  verbatim — is canonical;
* ``ovos-workshop >= 9.3.2a1`` binds the handler to **both** spellings, so a
  skill built against it survives either dispatch.

The interesting cell is the one where those two miss each other: a skill built
against ``ovos-workshop == 9.3.1a2`` binds the suffixed topic **only**, and a
current core dispatches the canonical topic **only**.

The matrix
----------

===================  ==================  =================  ============
combo                skill binds         core dispatches    handler runs
===================  ==================  =================  ============
old skill/old core   suffixed only       suffixed           yes
old skill/new core   suffixed only       canonical          **no**
new skill/old core   both                suffixed           yes
new skill/new core   both                canonical          yes (once)
===================  ==================  =================  ============

Only ``old skill/new core`` is broken, and it is marked
``xfail(strict=True)``. The other three are passing controls: they prove the
harness can see a handler fire at all, so the one red cell is a real finding
and not a broken fixture.

Two channel cells reflect that same gap against the live fleet rather than a
boundary pin: ``stable-skill/dev-core`` and ``testing-skill/dev-core`` build
the skill side straight from the OVOS distro's own constraint files (fetched
fresh in ``build_venvs.sh``), and both currently resolve an ovos-workshop
below the 9.3.2a1 canonical-binding line, so they hit the identical failure
against a dev core. ``dev-skill/stable-core`` and ``dev-skill/testing-core``
are the passing mirror: a dev-workshop skill against either channel's
padatious, which never canonicalizes today, so the suffixed dispatch still
finds a bound handler.

How it gets fixed, and why the fix lands where it does
------------------------------------------------------

The old container does **not** ship an old ``ovos-bus-client``. Its workshop
pin declares a floor, not a ceiling, so a rebuilt container resolves the
current client — this suite asserts that, because the whole repair strategy
depends on it. ``ovos-bus-client#271`` bridges in both directions with no state: the
EMITTER also sends a marked ``.intent``-suffixed twin frame for every intent
topic (reaches a truly frozen image whose baked-in old client cannot be fixed
from outside), and a modern RECEIVER canonicalizes unmarked suffixed traffic
locally (serves a rebuilt container whose floor-pin resolved a new client
under old workshop). Either way the old handler runs unchanged.

Kill-switch role
----------------

These four cells are a gate on the compat train, in both directions:

* the day ``#271`` releases, ``old skill/new core`` starts passing,
  ``strict=True`` turns that into a loud XPASS failure, and the marker comes
  off — the guard is then permanent;
* ``ovos-workshop#500`` removes the suffixed binding, which turns
  ``new skill/old core`` red. That cell must not be deleted to make the PR
  green; it is the signal that the inbound direction (suffixed wire topic →
  canonical local listener) is still missing from the client;
* any PR that drops the compat must flip these deliberately.

Running it
----------

The combo is selected by environment, so one script serves all four CI matrix
entries::

    BACKCOMPAT_COMBO=old-skill/new-core \\
    BACKCOMPAT_SKILL_PYTHON=/path/to/venv_skill_old/bin/python \\
    <core-venv>/bin/pytest test/backcompat/

``test/backcompat/build_venvs.sh`` builds the four venvs with the pins above.
"""
import os
import time
import uuid

import pytest

from ovos_bus_client.message import Message

from .driver import (ACTIVATED_TOPIC, AUDIO_OUTPUT_END_TOPIC,
                     CANONICAL_TOPIC, CONVERSE_FIRED_TOPIC,
                     CONVERSE_MATCH_TOPIC, CONVERSE_REQUEST_TOPIC,
                     CONVERSE_RESPONSE_TOPIC,
                     CONVERSE_TRIGGER_TOPIC, GET_RESPONSE_ANSWER_TOPIC,
                     GET_RESPONSE_DONE_TOPIC, GET_RESPONSE_TIMEOUT,
                     GET_RESPONSE_TRIGGER_TOPIC, LEGACY_TOPIC, SKILL_ID,
                     SPEAK_WAIT_DONE_TOPIC, SPEAK_WAIT_TRIGGER_TOPIC,
                     BusServer, Capture, SkillProcess, converse_match,
                     core_canonicalizes, core_has_pipeline_match_api,
                     dispatch, dispatch_match,
                     dispatch_topic_for, make_converse_service,
                     session_context, wait_for_active_skill,
                     wait_for_response_mode)

#: What each combo is *supposed* to be, so a silent pin drift (a new workshop
#: release changing what it binds, or the padatious fold being reverted) fails
#: as a wrong-vintage error instead of quietly turning a red cell green.
#:
#: Two kinds of cell, kept in the same table on purpose:
#:
#: * boundary-pin cells (``old-*`` / ``new-*``) pin the exact releases either
#:   side of a known behavior change (workshop 9.3.1a2 last-suffixed-only vs
#:   9.3.2a1 first-canonical; padatious 2.0.0a1 last-no-fold vs 2.0.1a1
#:   first-fold). They document WHERE the line is and fail as wrong-vintage if
#:   a release ever moves it.
#: * channel cells (``stable-*`` / ``testing-*``) pin whatever the OVOS distro
#:   constraint files resolve *today* (fetched fresh in build_venvs.sh, never
#:   vendored), so they verify the fleet reality rather than a boundary. As of
#:   this writing both constraints-stable.txt and constraints-testing.txt
#:   floor ovos-workshop and ovos-padatious well below the canonicalization
#:   boundaries above (stable: workshop>=3.4.0,<3.5.0, padatious>=1.4.2,<1.5.0;
#:   testing: workshop>=7.0.6,<8.0.0, padatious>=1.4.3,<2.0.0), so both
#:   channels behave like the "old" boundary side on both axes. A distro pin
#:   bump past a boundary flips the affected channel cell red at the moment it
#:   happens — that is the alarm this design exists for.
COMBOS = {
    # combo id                skill binds suffixed only, core canonicalizes, fires
    "old-skill/old-core":     (True, False, True),
    "old-skill/new-core":     (True, True, False),
    "new-skill/old-core":     (False, False, True),
    "new-skill/new-core":     (False, True, True),
    # channel cells: skill or core side installed per a live distro
    # constraints file, the other side at dev. See build_venvs.sh.
    "stable-skill/dev-core":  (True, True, False),
    "dev-skill/stable-core":  (False, False, True),
    "testing-skill/dev-core": (True, True, False),
    "dev-skill/testing-core": (False, False, True),
}

#: Combos expected to fail today because the skill side is suffixed-only and
#: the core side canonicalizes — the same gap ``old-skill/new-core`` marks,
#: reached via a distro constraints pin instead of a boundary pin.
_BROKEN_CHANNEL_COMBOS = {"stable-skill/dev-core", "testing-skill/dev-core"}

COMBO = os.environ.get("BACKCOMPAT_COMBO", "")
SKILL_PYTHON = os.environ.get("BACKCOMPAT_SKILL_PYTHON", "")

pytestmark = pytest.mark.skipif(
    not COMBO or not SKILL_PYTHON,
    reason="mixed-version matrix needs BACKCOMPAT_COMBO and "
           "BACKCOMPAT_SKILL_PYTHON; see test/backcompat/build_venvs.sh")

#: True in every cell the compat train has to repair — the boundary-pin
#: original plus its channel-pinned reflections. Evaluated at import time so
#: the xfail below can be static and strict.
IS_BROKEN_CELL = COMBO == "old-skill/new-core" or COMBO in _BROKEN_CHANNEL_COMBOS

_XFAIL_REASON = (
    "old skill container (ovos-workshop==9.3.1a2, suffixed binding only) does "
    "not hear a canonical dispatch; needs the #271 bridge (wire twin from the "
    "emitter, or local canonicalization in a modern client), unreleased. XPASS here means #271 shipped — drop "
    "this marker and keep the guard."
    if COMBO not in _BROKEN_CHANNEL_COMBOS else
    f"{COMBO}: the OVOS distro constraints file pins an ovos-workshop below "
    "the 9.3.2a1 canonical-binding boundary, so this channel's skill side is "
    "suffixed-only against a dev core that canonicalizes at registration; "
    "same gap as old-skill/new-core, reached via a live fleet pin instead of "
    "a boundary pin. XPASS here means either the channel moved its pin past "
    "the boundary or #271 shipped — check which, then drop the marker.")


@pytest.fixture(scope="module")
def stack():
    """One bus and one skill process, shared by the read-only observations."""
    if COMBO not in COMBOS:
        pytest.fail(f"unknown BACKCOMPAT_COMBO {COMBO!r}; "
                    f"expected one of {sorted(COMBOS)}")
    server = BusServer()
    skill = None
    try:
        bus = server.client()
        # Capture registration before the skill exists, so the name the core
        # side would key its engine entry on is observed, never assumed.
        registrations = Capture(bus, "padatious:register_intent")
        skill = SkillProcess(SKILL_PYTHON, server.xdg)
        registrations.wait(30)
        yield server, bus, skill, registrations
    finally:
        if skill is not None:
            skill.stop()
        server.stop()


def _registered_name(registrations) -> str:
    names = [m.data.get("name") for m in registrations.messages
             if str(m.data.get("name", "")).startswith(f"{SKILL_ID}:")]
    assert names, ("the skill never registered an intent with the padatious "
                   "contract; nothing to dispatch")
    return names[0]


@pytest.fixture(scope="module")
def converse_service(stack):
    """The real, per-combo ``ConverseService`` from ``driver.
    make_converse_service``, running on the shared bus for the module's
    converse/get_response tests.

    A separate fixture (not folded into ``stack``) so the plain
    intent-dispatch tests above don't pay for it and aren't coupled to it —
    only the interactive-flow tests below ask for this.

    Skips (own reason, never the #271 marker) when this core venv's
    ``ConverseService`` predates the plugin-pipeline ``.match()`` API this
    module's helpers are built on — real today only for the "stable"
    distro channel's ``ovos-core==1.3.1`` pin. See
    ``driver.core_has_pipeline_match_api``.
    """
    if not core_has_pipeline_match_api():
        pytest.skip(
            f"{COMBO}: this core venv's ConverseService predates the "
            f"plugin-pipeline .match() API (pre ovos-core pipeline "
            f"refactor) — converse/get_response routing here uses a "
            f"different, older object model this suite does not adapt to "
            f"yet; unrelated to the #271 canonical-topic gap")
    _server, bus, _skill, _regs = stack
    service = make_converse_service(bus)
    try:
        yield service
    finally:
        service.shutdown()


def test_pins_are_the_intended_vintage(stack):
    """Fail loudly if either side is not the version this combo assumes.

    Without this, a workshop release that quietly changes what it binds would
    turn the broken cell green and be read as "the compat train landed".
    """
    _server, _bus, skill, _regs = stack
    want_suffixed_only, want_canon, _ = COMBOS[COMBO]

    suffixed_only = skill.bound_topics == [LEGACY_TOPIC]
    assert suffixed_only == want_suffixed_only, (
        f"{COMBO}: expected suffixed-only binding={want_suffixed_only}, but "
        f"the skill venv bound {skill.bound_topics}")
    if not want_suffixed_only:
        assert CANONICAL_TOPIC in skill.bound_topics
    assert core_canonicalizes() == want_canon, (
        f"{COMBO}: expected the core venv to canonicalize at registration="
        f"{want_canon}, got {core_canonicalizes()}")


#: Channel cells pin the whole stack from a distro constraints file, which
#: caps ovos-bus-client too — unlike the boundary cells, where only
#: ovos-workshop is pinned and its dependency floor is left to resolve
#: whatever is current. The "frozen container still gets a modern client"
#: assumption below is therefore a boundary-cell property, not a channel-cell
#: one, and asserting it on a channel combo would just report a real fleet
#: fact (the channel's own bus-client ceiling) as if it were a broken
#: assumption.
_CHANNEL_COMBOS = {"stable-skill/dev-core", "dev-skill/stable-core",
                    "testing-skill/dev-core", "dev-skill/testing-core"}


def test_old_container_resolves_a_current_bus_client(stack):
    """The repair strategy assumes the frozen container gets a modern client.

    ``ovos-workshop``'s dependency floor is a lower bound, so even a pinned
    old workshop resolves today's ``ovos-bus-client``. If that ever stopped
    being true, only the emitter-side wire twin of ``#271`` could reach it — so the
    resolution is asserted, not assumed, and the cell documents which
    rule it exercises.

    Channel combos are exempted from the assertion (not skipped outright,
    so the version is still recorded): a distro constraints file pins
    ovos-bus-client alongside everything else, so a low client version there
    is the fleet's own ceiling, not evidence the repair design is broken. A
    real stable/testing-channel container would need a bus-client bump on top
    of a workshop bump to receive the #271 fix; that is a fleet-inventory
    finding for the maintainers, not a compat-design failure.
    """
    _server, _bus, skill, _regs = stack
    client = skill.versions.get("ovos_bus_client", "")
    assert client, f"the skill venv did not report its versions:\n{skill.log}"
    if COMBO not in _CHANNEL_COMBOS:
        assert int(client.split(".")[0]) >= 2, (
            f"the skill venv resolved ovos-bus-client {client}; the "
            f"this cell exercises #271's local canonicalization rule, which "
            f"needs a modern client in the skill process")
    elif int(client.split(".")[0]) < 2:
        print(f"{COMBO}: channel bus-client ceiling is {client} (<2), below "
              f"where #271 would land; this channel needs a bus-client bump "
              f"too, not just a workshop bump, to receive the compat fix")

    # Recorded, not asserted: this is the switch the xfail above waits for.
    # When it turns True the broken cell starts passing and strict xfail
    # converts that into the loud signal to promote the guard.
    print(f"{COMBO}: skill venv = ovos-workshop "
          f"{skill.versions.get('ovos_workshop')}, ovos-bus-client {client}, "
          f"#271 mirror present={skill.versions.get('has_reemit_hook')}")


def test_core_dispatches_the_topic_this_combo_expects(stack):
    """Positive control on the core half, independent of any handler.

    Proves the dispatch really went out and with which spelling, so a silent
    handler in the broken cell can only mean the handler never heard it.
    """
    _server, bus, _skill, regs = stack
    topic = dispatch_topic_for(_registered_name(regs))
    want = CANONICAL_TOPIC if core_canonicalizes() else LEGACY_TOPIC
    assert topic == want

    seen = Capture(bus, topic)
    try:
        dispatch(bus, topic, food="tacos")
        assert seen.wait(), f"the dispatch on {topic!r} never reached the bus"
    finally:
        seen.close()


@pytest.mark.xfail(IS_BROKEN_CELL, strict=True, reason=_XFAIL_REASON)
def test_the_skill_handler_runs(stack):
    """The contract: a canonical dispatch must reach the skill's handler.

    Emitted exactly the way ``IntentService._dispatch_match`` does — the
    matched topic, forwarded with the utterance data — and observed through
    the marker the skill emits from inside the handler.
    """
    _server, bus, skill, regs = stack
    topic = dispatch_topic_for(_registered_name(regs))

    token = uuid.uuid4().hex
    handled = Capture(bus, "backcompat.skill.handled", token=token)
    spoken = Capture(bus, "speak")
    try:
        bus.emit(Message(topic, {"food": "tacos", "token": token},
                         {"session": {"session_id": "backcompat"}}))
        assert handled.wait(), (
            f"{COMBO}: dispatched {topic!r} but the skill handler never ran.\n"
            f"the skill venv bound: {skill.bound_topics}\n"
            f"skill process log:\n{skill.log}")
        assert handled.messages[0].data["topic"] in (topic, LEGACY_TOPIC)
        assert handled.messages[0].data["data"]["food"] == "tacos"
        # ovos-core on the stable/testing channels is old enough (<=2.1.x)
        # that its dialog/TTS plumbing around a bare ``self.speak()`` differs
        # from what this minimal harness sets up for the "new" core checkout,
        # independently of the intent-topic aliasing this suite exists to
        # test. The handler firing (asserted above) is the compat-relevant
        # fact; whether it also spoke is a realism check that only applies
        # where the core side is current.
        if "-core" not in COMBO or not COMBO.endswith(("stable-core",
                                                        "testing-core")):
            assert spoken.wait(), "the handler ran but never spoke"
    finally:
        handled.close()
        spoken.close()


@pytest.mark.xfail(IS_BROKEN_CELL, strict=True, reason=_XFAIL_REASON)
def test_the_handler_runs_exactly_once(stack):
    """A skill bound to both spellings must not answer twice.

    ``new skill/new core`` is where this bites: the skill binds the canonical
    and the suffixed topic, so once the compat mirror of ``#271`` is live the
    same dispatch could reach the same handler down two paths. One utterance,
    one answer.
    """
    _server, bus, skill, regs = stack
    topic = dispatch_topic_for(_registered_name(regs))

    token = uuid.uuid4().hex
    handled = Capture(bus, "backcompat.skill.handled", token=token)
    try:
        bus.emit(Message(topic, {"food": "burritos", "token": token},
                         {"session": {"session_id": "backcompat-once"}}))
        assert handled.wait(), f"{COMBO}: handler never ran for {topic!r}"
        # Keep listening past the first hit for a duplicate, but exit the moment
        # a second dispatch lands: a real double-fire fails fast instead of
        # sleeping out a fixed window, and only the passing case waits the full
        # DUPLICATE_WINDOW deadline (a documented upper bound on how late a
        # duplicate could arrive over the real bus).
        DUPLICATE_WINDOW = 3.0
        handled.wait_for_count(2, timeout=DUPLICATE_WINDOW)
        assert len(handled.messages) == 1, (
            f"{COMBO}: one dispatch on {topic!r} produced "
            f"{len(handled.messages)} handler runs "
            f"(skill bound {skill.bound_topics})")
    finally:
        handled.close()


#: The interactive-flow tests below are NOT marked with the IS_BROKEN_CELL
#: xfail. That marker exists for one specific gap: an old skill binds the
#: suffixed `<skill_id>:<file>.intent` topic only, and a canonicalizing core
#: dispatches `<skill_id>:<file>` only, so registered-intent names never line
#: up. converse and get_response are routed through the real, per-combo
#: `ovos_core.intent_services.converse_service.ConverseService` (see the
#: `converse_service` fixture / `driver.make_converse_service`) — genuine
#: core-side code decides the match, the driver only forwards
#: `match.match_type` verbatim, same as `dispatch()` already does for
#: intents. That match_type is a FIXED literal
#: (`<skill_id>.converse.request` / `<skill_id>.converse.get_response`) in
#: every venv this suite builds, never derived from a registered intent
#: name, so it never touches padatious's registration-time canonicalization.
#: wait_while_speaking is legitimately audio-service territory — there is no
#: core-side code to route it through — and stays a direct simulation of
#: `recognizer_loop:audio_output_end`, also a fixed literal, also unchanged
#: across every venv checked (including the "stable" distro channel's
#: ovos-bus-client==1.3.8a4). There is no boundary pin on any of these three
#: flows, so nothing here should need the same kill switch; if a real gap
#: ever does show up on one of them, give it its own xfail with its own
#: reason instead of folding it into this one (see module docstring: "any PR
#: that drops the compat must flip these deliberately" — a borrowed marker
#: would hide the wrong signal).


def _require_converse_api(skill) -> None:
    """Skip with an honest, own reason if this vintage genuinely has no
    converse/get_response call surface at all — NOT the #271 xfail marker,
    which is about a completely different gap (suffixed vs canonical intent
    topics). Every vintage this suite currently builds against (9.3.1a2,
    dev, and both the "stable" and "testing" distro channel pins) reports
    ``has_converse_api: true`` — see ``skill_process.py``'s ``VERSIONS``
    line — so this is a safety net for a vintage nobody has pinned yet, not
    a marker anyone should expect to see flip today.
    """
    if not skill.versions.get("has_converse_api", True):
        pytest.skip(
            f"{COMBO}: ovos-workshop {skill.versions.get('ovos_workshop')} "
            f"has no converse/get_response machinery on either "
            f"ConversationalSkill or plain OVOSSkill — unrelated to the "
            f"#271 canonical-topic gap, this vintage simply predates the "
            f"call surface these tests exercise")


def test_converse_fires_before_a_followup_utterance_matches_an_intent(
        stack, converse_service):
    """An activated skill's converse() must be offered a follow-up utterance
    ahead of intent matching.

    This is the multi-turn-dialog contract every bus-only skill container
    leans on: ``activate()`` puts the skill on the active list, and the
    pipeline is supposed to try ``converse()`` before falling through to
    intent matching. Genuinely cross-version this time: the driver calls the
    real, per-combo ``ConverseService.match()`` (see ``converse_service``
    fixture / ``driver.make_converse_service``) to decide whether and how to
    route the follow-up utterance, then forwards ``match.match_type``
    verbatim — the same shortcut ``dispatch()`` already takes for the
    food-order intent, except the topic now comes from real core code
    instead of a constant the driver assumes.
    """
    _server, bus, skill, _regs = stack
    _require_converse_api(skill)
    token = uuid.uuid4().hex
    session_id = f"backcompat-converse-{token[:8]}"
    activated = Capture(bus, ACTIVATED_TOPIC, token=token)
    # the real second hop: ConverseService.handle_converse (triggered by
    # dispatch_match below) re-emits to this exact skill-facing topic —
    # capturing it independently of the "converse_fired" marker proves the
    # WIRE contract, not just that the skill's converse() method ran.
    requested = Capture(bus, CONVERSE_REQUEST_TOPIC)
    fired = Capture(bus, CONVERSE_FIRED_TOPIC)
    responded = Capture(bus, CONVERSE_RESPONSE_TOPIC)
    try:
        # self.activate() (real workshop code, either vintage) emits the
        # real "intent.service.skills.activate" message, which the real
        # converse_service.handle_activate_skill_request (bound in its
        # __init__) puts the skill on SessionManager's live active-skills
        # list for this session_id.
        bus.emit(Message(CONVERSE_TRIGGER_TOPIC, {"token": token},
                         session_context(session_id)))
        assert activated.wait(), (
            f"{COMBO}: skill never confirmed activation:\n{skill.log}")
        # activate_skill_request is itself async over the wire (our own
        # "activated" marker races the real core-side session update it
        # rides alongside); wait for the actual evidence — the skill_id
        # showing up on the live session — rather than guessing a delay.
        assert wait_for_active_skill(session_id, SKILL_ID), (
            f"{COMBO}: skill confirmed activation but never showed up on "
            f"the live session's active-skill list")

        match = converse_match(converse_service, ["i changed my mind"],
                               "en-us", session_id)
        assert match is not None, (
            f"{COMBO}: ConverseService.match() found no active skill to "
            f"converse with — activation never reached the real core-side "
            f"session state.\nskill process log:\n{skill.log}")
        assert match.match_type == CONVERSE_MATCH_TOPIC, (
            f"{COMBO}: real ConverseService.match() picked "
            f"{match.match_type!r}, not the expected {CONVERSE_MATCH_TOPIC!r}")
        dispatch_match(bus, match)

        assert requested.wait(), (
            f"{COMBO}: real ConverseService.handle_converse never re-emitted "
            f"onto {CONVERSE_REQUEST_TOPIC!r} — the skill-facing wire hop "
            f"itself never fired, not just the marker.")
        assert fired.wait(), (
            f"{COMBO}: an activated skill's converse() was never reached by "
            f"a follow-up utterance routed through the real converse "
            f"service — a real skill container would silently lose "
            f"multi-turn dialog on this core.\nskill process log:\n"
            f"{skill.log}")
        assert fired.messages[0].data["utterances"] == ["i changed my mind"]

        assert responded.wait(), (
            f"{COMBO}: converse() ran but the skill never answered "
            f"{CONVERSE_RESPONSE_TOPIC!r}")
        assert responded.messages[0].data["result"] is True, (
            "converse() claimed the utterance (returned True) but the "
            "pipeline-facing response says it did not consume it")
    finally:
        activated.close()
        requested.close()
        fired.close()
        responded.close()


def test_get_response_receives_the_answer_utterance(stack, converse_service):
    """A handler blocked in ``get_response()`` must unblock on the answer,
    delivered through the real core-side response-mode match.

    ``OVOSSkill.get_response`` enables response-mode over the real
    ``skill.converse.get_response.enable`` topic, which the real
    ``ConverseService.handle_get_response_enable`` uses to flip
    ``session.utterance_states[skill_id]`` — genuine per-version core state,
    not something the driver sets by hand. The driver then calls the real
    ``ConverseService.match()`` with the answer utterance, gets back
    ``match_type == f"{skill_id}.converse.get_response"`` from that real
    state, and forwards it verbatim, same as the converse test above.

    ``ConverseService.match()`` only considers a skill for
    response-mode if it is ALSO on the session's active-skill list
    (``_collect_converse_skills`` / ``get_active_skills`` gate — see
    ``match()``'s ``gr_skills`` computation) — in a real deployment this is
    implicit, since ``get_response`` is normally called from inside a
    handler for an intent that was just dispatched to this skill, which
    activates it as a side effect. This harness has no intent-dispatch
    pipeline standing that context up, so the skill is activated explicitly
    first, the same way the converse test above does.
    """
    _server, bus, skill, _regs = stack
    _require_converse_api(skill)
    token = uuid.uuid4().hex
    session_id = f"backcompat-getresp-{token[:8]}"
    activated = Capture(bus, ACTIVATED_TOPIC, token=token)
    done = Capture(bus, GET_RESPONSE_DONE_TOPIC, token=token)
    try:
        bus.emit(Message(CONVERSE_TRIGGER_TOPIC, {"token": token},
                         session_context(session_id)))
        assert activated.wait(), (
            f"{COMBO}: skill never confirmed activation:\n{skill.log}")
        assert wait_for_active_skill(session_id, SKILL_ID), (
            f"{COMBO}: skill confirmed activation but never showed up on "
            f"the live session's active-skill list")

        bus.emit(Message(GET_RESPONSE_TRIGGER_TOPIC, {"token": token},
                         session_context(session_id)))
        # get_response's real "skill.converse.get_response.enable" round
        # trip is async over the wire; wait for the actual evidence — the
        # live session's response-mode holder — rather than guessing a
        # delay long enough.
        assert wait_for_response_mode(session_id, SKILL_ID), (
            f"{COMBO}: get_response() never showed up as the live "
            f"session's response-mode holder\nskill process log:\n{skill.log}")

        match = converse_match(converse_service, ["tacos please"], "en-us",
                               session_id)
        assert match is not None, (
            f"{COMBO}: ConverseService.match() found no skill in "
            f"response-mode — get_response's enable call never reached "
            f"real core-side session state.\nskill process log:\n{skill.log}")
        assert match.match_type == GET_RESPONSE_ANSWER_TOPIC, (
            f"{COMBO}: real ConverseService.match() picked "
            f"{match.match_type!r}, not the expected "
            f"{GET_RESPONSE_ANSWER_TOPIC!r}")
        dispatch_match(bus, match)

        assert done.wait(), (
            f"{COMBO}: get_response() never returned after the real "
            f"converse-service match landed.\nskill process log:\n{skill.log}")
        assert done.messages[0].data["answer"] == "tacos please", (
            f"{COMBO}: get_response() returned "
            f"{done.messages[0].data['answer']!r} instead of the answer "
            f"utterance sent")
    finally:
        activated.close()
        done.close()


def test_get_response_completes_without_hanging_when_unanswered(stack):
    """The no-answer path must complete, not hang, within a generous bound.

    This is a plain no-hang smoke test, not a boundedness proof for any
    specific historical fix: ``get_response``'s internal poll loop
    (``__get_response``) has always been bounded by
    ``skills.get_response_timeout`` — pinned low here (see
    :data:`driver.GET_RESPONSE_TIMEOUT` / ``make_shared_config``) so this
    stays fast — regardless of the separate killable-thread stall that
    ovos-workshop 9.3.5a1 fixed for the *external abort* path
    (``mycroft.skills.abort_question`` / ``_handle_killed_wait_response``),
    which this test does not exercise. No answer is ever sent here; this
    only proves the ordinary no-answer path returns.
    """
    _server, bus, skill, _regs = stack
    _require_converse_api(skill)
    token = uuid.uuid4().hex
    session = {"session_id": f"backcompat-getresp-timeout-{token[:8]}"}
    done = Capture(bus, GET_RESPONSE_DONE_TOPIC, token=token)
    try:
        bus.emit(Message(GET_RESPONSE_TRIGGER_TOPIC, {"token": token},
                         {"session": session}))
        # A generous multiple of the pinned poll window, not the window
        # itself: proves the path completes promptly without turning a
        # slightly slow CI runner into a false "it hung" failure.
        assert done.wait(timeout=GET_RESPONSE_TIMEOUT * 4), (
            f"{COMBO}: get_response() never returned with no answer sent — "
            f"looks like a hang rather than a timeout.\nskill process log:\n"
            f"{skill.log}")
        assert done.messages[0].data["answer"] is None, (
            f"{COMBO}: get_response() returned "
            f"{done.messages[0].data['answer']!r} with no answer ever sent")
    finally:
        done.close()


def test_speak_wait_unblocks_on_audio_output_end(stack):
    """``speak(..., wait=True)`` must unblock once audio output ends.

    Exercises the receive side of whatever topic the CURRENT core emits for
    output-end against whatever the OLD workshop's ``wait_while_speaking``
    listens for. Both ``venv_skill_old`` and ``venv_skill_new`` resolve the
    same current ``ovos-bus-client`` off their workshop floor (the property
    ``test_old_container_resolves_a_current_bus_client`` already asserts),
    and that client's ``SessionManager.wait_while_speaking`` is where this
    listens — reading both venvs' ``ovos_bus_client/session.py`` side by
    side shows the same literal ``recognizer_loop:audio_output_end`` topic
    in both, so there is no cross-version drift here for this suite to
    catch today. The driver plays the audio service's part the way
    ``ovoscope`` does: it does not run one, it just emits the end-of-output
    message the real one would.
    """
    _server, bus, skill, _regs = stack
    token = uuid.uuid4().hex
    session = {"session_id": f"backcompat-speakwait-{token[:8]}"}
    done = Capture(bus, SPEAK_WAIT_DONE_TOPIC, token=token)
    try:
        start = time.monotonic()
        bus.emit(Message(SPEAK_WAIT_TRIGGER_TOPIC, {"token": token},
                         {"session": session}))
        # give speak() time to run, set is_speaking, and register its
        # audio_output_end listener before the driver plays audio-service
        # and ends the "output" — wait_while_speaking bails out immediately
        # if it does not see is_speaking already set (see session.py), so
        # firing too early would make this a false pass for the wrong
        # reason (skipped the wait entirely) rather than the wait actually
        # unblocking.
        time.sleep(0.5)
        bus.emit(Message(AUDIO_OUTPUT_END_TOPIC, {}, {"session": session}))
        assert done.wait(), (
            f"{COMBO}: speak(wait=True) never unblocked after "
            f"{AUDIO_OUTPUT_END_TOPIC!r} fired for its session — the old "
            f"skill container would hang forever waiting for audio output "
            f"it will never see end.\nskill process log:\n{skill.log}")
        elapsed = time.monotonic() - start
        # SessionManager.wait_while_speaking's own timeout defaults to 15s;
        # unblocking well under that proves the bridge fired the wait open
        # rather than the call merely timing out on its own.
        assert elapsed < 10, (
            f"{COMBO}: speak(wait=True) took {elapsed:.1f}s to unblock — "
            f"looks like it rode out its own internal timeout instead of "
            f"reacting to {AUDIO_OUTPUT_END_TOPIC!r}")
    finally:
        done.close()


@pytest.mark.skipif(not IS_BROKEN_CELL,
                    reason="the kill switch only has meaning where the "
                           "compat mirror is what makes the handler run")
def test_kill_switch_disables_the_compat_mirror():
    """Inverse control: with ``emit_legacy`` off, the old handler stays silent.

    This is what proves the broken cell above measures the compat bridge and
    not some accident of the fixture. It passes today for the trivial reason
    that no mirror exists; once ``#271`` ships it becomes the real negative
    half of the pair, and a compat-drop PR has to flip the cell above while
    leaving this one green.

    The kill switch is applied on BOTH sides, belt and braces, but the one
    that actually matters here is the DRIVER's: bus-client#271 rule 1 (the
    legacy ``.intent``-suffixed twin) fires inside ``emit()`` in whichever
    process calls it, and the canonical dispatch below is emitted from the
    driver's own bus client, not the skill subprocess. ``server.client(
    emit_legacy=False)`` sets ``OVOS_BUS_EMIT_LEGACY`` for that client before
    it is constructed (see ``BusServer.client``); ``SkillProcess(...,
    emit_legacy=False)`` sets the same flag in the skill subprocess's own
    environment, which matters once the skill side ever emits anything of
    its own.
    """
    server = BusServer()
    skill = None
    try:
        bus = server.client(emit_legacy=False)
        skill = SkillProcess(SKILL_PYTHON, server.xdg, emit_legacy=False)
        token = uuid.uuid4().hex
        handled = Capture(bus, "backcompat.skill.handled", token=token)
        canonical = Capture(bus, CANONICAL_TOPIC, token=token)
        try:
            bus.emit(Message(CANONICAL_TOPIC, {"food": "tacos", "token": token},
                             {"session": {"session_id": "backcompat-off"}}))
            assert canonical.wait(), "the dispatch never reached the bus"
            assert not handled.wait(5), (
                "the old handler ran with emit_legacy disabled — the compat "
                "mirror is not actually gated by the kill switch")
        finally:
            handled.close()
            canonical.close()
    finally:
        if skill is not None:
            skill.stop()
        server.stop()
