"""OVOS session-evolution conformance suite.

Cross-cuts the session-resident state that PIPELINE-1, CONVERSE-1 and
FALLBACK-1 each own, asserting — through real ovos-core interactions — that the
orchestrator carries and updates the session correctly and echoes the updated
session back on its responses:

- ``active_handlers`` recency / head-first dedup .... PIPELINE-1 §7.1
- ``converse_handlers`` owner ordering .............. CONVERSE-1 §2.1
- ``fallback_handlers`` pool field .................. FALLBACK-1 §4
- ``response_mode`` / get-response capture .......... CONVERSE-1 §2.2
- ``updated_session`` echoed on responses .......... SESSION-2

The installed bus-client carries the spec session fields (``active_handlers``,
``converse_handlers``, ``fallback_handlers``, ``response_mode``) and, per
SESSION-1 §3.4, omits them from the serialized form when empty (empty ≡
omission), so presence is only asserted on populated sessions. The one clause
the stack does not yet populate — ``converse_handlers`` — is tracked as a
a strict expected-fail so it flips loudly when the orchestrator starts draining it.
Drivers are described in ``_conformance.py``.

Coverage map (clause -> status against the installed stack):
- PIPELINE-1 §7.1 dispatch records the skill as active ........... green
- PIPELINE-1 §7.1 re-activation dedups head-first ................ green
- PIPELINE-1 §7.1 session.active_handlers carries the skill ...... green
- CONVERSE-1 §2.1 owners ordered most-recently-activated first ... green
- CONVERSE-1 §2.1 session.converse_handlers mirrors the ordering .. xfail (not drained yet)
- CONVERSE-1 §2.2 get-response sets the response state ........... green
- CONVERSE-1 §2.2 session.response_mode carries the state ........ green
- FALLBACK-1 §4   session.fallback_handlers carries the pool ..... green
- SESSION-2       session_id preserved on the response ........... green
- SESSION-2       a session mutation rides the forward ........... green
- SESSION-2 §2.6  a handler-boundary write rides forward/reply/response  green
- SESSION-2 §2.6  the same write on CollectionMessage/GUIMessage . green
- SESSION-2 §2.6  no derived Message means no bus-visible effect . green
- SESSION-2 §2.6  SessionManager.bind pins the round session for get/derive  green
- SESSION-2 §2.6  bind refuses a non-store default / an id mismatch  green
- SESSION-1 §2.1  an omitted field resolves to the deployment default ... green
- SESSION-1 §2.1  an explicit null is treated as omitted (not deferral) . green
- SESSION-1 §3.1  empty/absent session resolves to session_id default ... xfail (bus-client mints a random uuid)
- SESSION-1 §3.1  per-session state keyed on session_id (A not in B) .... green
- SESSION-2 §2.1  the bus leaves session untouched in transit .......... green
- SESSION-1 §3.5  ``location`` round-trips the three keys ............... green
- SESSION-1 §3.5  ``Session.timezone`` resolves from ``location.tz`` .... green
- SESSION-1 §3.5  a partial ``location`` is accepted .................... green
- SESSION-1 §3.5  the session ``tz`` wins over the configured zone ...... green
- SESSION-1 §3.5  an absent ``tz`` falls back to the configured zone .... green

``location`` is the §3.5 three-key field ``{lat, lon, tz}``. ``tz`` is the one
key the spec gives normative consumer behaviour to, and it is the surface
``ovos-skill-alerts``' DST differential (PR #183) depends on end-to-end
(``SessionManager.get(message).timezone`` -> ``dateutil.tz.gettz``); these
cells catch a breaking rename or precedence change at the producing repo
instead of only downstream in that skill's tests.

SESSION-1 §2.1 / §3.1 are asserted at the consumer (``Session`` deserialize)
level, the same way the recency/ordering clauses above assert against the
``Session`` object directly; the keying and bus-statelessness clauses are
asserted end-to-end against the orchestrator. Clauses that need a capability
not present in this stack (the §4.1 default-materialization-on-derivation
rule, the SESSION-1 §6 finite-number / unparseable-``session`` malformed
path, and the SESSION-2 §5.1 orchestrator session-merge MUST — the latter
overlapping CONTEXT-1 §5.3) are tracked in ``docs/known-gaps.md`` rather than
encoded, because a blind strict expected-fail could XPASS on the CI stack.
"""
import time
from typing import Optional
from unittest import TestCase
from unittest.mock import patch

import pytest
from ovos_bus_client.message import CollectionMessage, GUIMessage, Message
from ovos_bus_client.session import Session, SessionManager, UtteranceState
import ovos_bus_client.session as bus_client_session
from ovos_utils.log import LOG

from ovoscope import get_minicroft

from ._conformance import (
    PADACIOSO_HIGH,
    capture,
    reset_namespace,
    use_spec_namespace,
    utterance,
)

PARROT_ID = "ovos-skill-parrot.openvoiceos"
CONVERSE_PIPELINE = ["ovos-converse-pipeline-plugin", PADACIOSO_HIGH]

_MC = None


def setUpModule():
    global _MC
    LOG.set_level("ERROR")
    use_spec_namespace()
    try:
        _MC = get_minicroft([PARROT_ID])
        from ._conformance import wait_ready
        wait_ready(_MC)
    except BaseException:
        reset_namespace()
        raise


def tearDownModule():
    try:
        if _MC is not None:
            _MC.stop()
    finally:
        reset_namespace()


def _last_session(recs) -> Optional[Session]:
    """The most recent serialized session carried on the captured messages."""
    for m in reversed(recs):
        if m.context.get("session"):
            return Session.deserialize(m.context["session"])
    return None


def _require_session(case, recs) -> Session:
    """``_last_session`` or a clear failure.

    Without this guard a strict-xfail test that never got a session at all
    dies with ``AttributeError: 'NoneType'`` — which counts as the expected
    failure and hides the real reason. Failing here names the actual problem.
    """
    sess = _last_session(recs)
    case.assertIsNotNone(
        sess, "no session was echoed on any captured response; the turn did "
              f"not complete. saw: {[m.msg_type for m in recs]}")
    return sess


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE-1 §7.1 — active-handler recency and head-first dedup
# ─────────────────────────────────────────────────────────────────────────────

class TestActiveHandlerRecency(TestCase):
    """PIPELINE-1 §7.1: on each accepted dispatch the orchestrator stamps the
    skill as the most-recent active handler. Re-activating the same skill must
    not duplicate it — it moves to the head (dedup)."""

    def test_activation_updates_session_active_skills(self):
        """Dispatching to a skill records it in the session's active list,
        echoed back on the response (§7.1)."""
        recs = capture(_MC, utterance("start parrot mode", "se-active",
                                      CONVERSE_PIPELINE), 4.0)
        sess = _last_session(recs)
        self.assertIsNotNone(sess, "no session echoed on any response")
        self.assertIn(PARROT_ID, [s[0] for s in sess.active_skills])

    def test_reactivation_is_head_first_dedup(self):
        """Re-activating an already-active skill keeps a single entry at the head
        of the active list — recency dedup (§7.1)."""
        sess = Session("se-dedup")
        sess.lang = "en-US"
        sess.activate_skill("other.skill")
        sess.activate_skill(PARROT_ID)
        sess.activate_skill(PARROT_ID)  # re-activate
        ids = [s[0] for s in sess.active_skills]
        self.assertEqual(ids.count(PARROT_ID), 1, "duplicate active-skill entry")
        self.assertEqual(ids[0], PARROT_ID, "re-activated skill must be head")

    def test_active_handlers_spec_field(self):
        """The spec field ``session.active_handlers`` carries the dispatched skill
        head-first (§7.1)."""
        recs = capture(_MC, utterance("start parrot mode", "se-active-spec",
                                      CONVERSE_PIPELINE), 4.0)
        sess = _require_session(self, recs)
        handlers = sess.serialize().get("active_handlers") or []
        owners = [h.get("skill_id") if isinstance(h, dict) else h for h in handlers]
        self.assertIn(PARROT_ID, owners)


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSE-1 §2.1 — converse owner ordering
# ─────────────────────────────────────────────────────────────────────────────

class TestConverseOwnerOrdering(TestCase):
    """CONVERSE-1 §2.1: converse owners are ordered most-recently-activated
    first; the active-skill list is the legacy carrier of that ordering."""

    def test_owner_ordering_most_recent_first(self):
        """The most recently activated owner is at index 0 (§2.1)."""
        sess = Session("se-cv-order")
        sess.lang = "en-US"
        sess.activate_skill("a.skill")
        sess.activate_skill("b.skill")
        self.assertEqual(sess.active_skills[0][0], "b.skill")

    @pytest.mark.xfail(
        reason="the stack does not yet drain the converse owner ordering into "
               "session.converse_handlers (CONVERSE-1 §2.1)",
        strict=True,
    )
    def test_converse_handlers_spec_field(self):
        """``session.converse_handlers`` mirrors the converse owner ordering
        (§2.1). Strict-xfailed until the orchestrator populates the field."""
        recs = capture(_MC, utterance("start parrot mode", "se-cv-spec",
                                      CONVERSE_PIPELINE), 4.0)
        sess = _require_session(self, recs)
        handlers = sess.serialize().get("converse_handlers") or []
        owners = [h.get("skill_id") if isinstance(h, dict) else h for h in handlers]
        self.assertIn(PARROT_ID, owners)


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSE-1 §2.2 — response mode / get-response capture
# ─────────────────────────────────────────────────────────────────────────────

class TestResponseMode(TestCase):
    """CONVERSE-1 §2.2: a skill in response mode captures the next utterance.
    ovos-core models this with ``session.utterance_states`` (RESPONSE) toggled by
    ``skill.converse.get_response.enable`` / ``.disable``."""

    def test_get_response_enable_sets_response_state(self):
        """Enabling get-response marks the skill RESPONSE in the session, so the
        converse stage routes the next utterance to it; disabling clears it back
        to the default INTENT state (§2.2).

        ``utterance_states`` carries the ``UtteranceState`` *value* (string), and
        under the spec ``response_mode`` model INTENT is the absence of a response
        window — a disabled skill is simply not present in the mapping. The
        assertion accepts either the enum or its value and treats a missing key as
        INTENT so it holds across the legacy dict and the spec projection."""
        sess = Session("se-respmode")
        sess.lang = "en-US"

        sess.enable_response_mode(PARROT_ID)
        self.assertIn(sess.utterance_states.get(PARROT_ID),
                      (UtteranceState.RESPONSE, UtteranceState.RESPONSE.value))

        sess.disable_response_mode(PARROT_ID)
        # INTENT is the default: either stamped explicitly or implied by absence.
        self.assertIn(sess.utterance_states.get(PARROT_ID),
                      (None, UtteranceState.INTENT, UtteranceState.INTENT.value))

    def test_response_mode_spec_field(self):
        """``session.response_mode`` names the owner holding response mode (§2.2).
        Empty response mode is omitted from the serialized form (SESSION-1 §3.4:
        empty ≡ omission), so presence is asserted only while an owner holds it."""
        sess = Session("se-respmode-spec")
        sess.lang = "en-US"
        # no owner -> the field is omitted, not serialized empty (§3.4)
        self.assertNotIn("response_mode", sess.serialize())

        sess.enable_response_mode(PARROT_ID)
        mode = sess.serialize().get("response_mode")
        self.assertIsNotNone(mode, "response_mode not serialized while held")
        owner = mode.get("skill_id") if isinstance(mode, dict) else mode
        self.assertEqual(owner, PARROT_ID)

        sess.disable_response_mode(PARROT_ID)
        self.assertNotIn("response_mode", sess.serialize())


# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK-1 §4 — fallback_handlers session field
# ─────────────────────────────────────────────────────────────────────────────

class TestFallbackHandlersField(TestCase):
    """FALLBACK-1 §4: ``session.fallback_handlers`` orders the pool when present.
    The field is optional (omission == registered-priority order)."""

    def test_fallback_handlers_spec_field(self):
        """``session.fallback_handlers`` is carried on the session and round-trips
        through serialization (§4). An empty pool is omitted from the serialized
        form (SESSION-1 §3.4: empty ≡ omission)."""
        sess = Session("se-fb-field")
        sess.lang = "en-US"
        # empty pool -> omitted, not serialized as [] (§3.4)
        self.assertNotIn("fallback_handlers", sess.serialize())

        sess.fallback_handlers = ["fallback.a", "fallback.b"]
        data = sess.serialize()
        self.assertEqual(data.get("fallback_handlers"),
                         ["fallback.a", "fallback.b"])
        self.assertEqual(Session.deserialize(data).fallback_handlers,
                         ["fallback.a", "fallback.b"])


# ─────────────────────────────────────────────────────────────────────────────
# SESSION-2 — updated_session echoed on responses
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdatedSessionEcho(TestCase):
    """SESSION-2: the orchestrator MUST echo the (possibly mutated) session on its
    responses so the next turn rides on the current state."""

    def test_session_id_preserved_on_response(self):
        """The echoed session keeps the same ``session_id`` as the entry (§2)."""
        recs = capture(_MC, utterance("zxqw blah blah", "se-echo-id",
                                      [PADACIOSO_HIGH]), 4.0)
        sess = _last_session(recs)
        self.assertIsNotNone(sess, "no session echoed on any response")
        self.assertEqual(sess.session_id, "se-echo-id")

    def test_mutation_rides_forward(self):
        """A pipeline-side activation is reflected in the echoed session, so the
        change rides forward to the next turn (SESSION-2 §2.6)."""
        recs = capture(_MC, utterance("start parrot mode", "se-echo-mut",
                                      CONVERSE_PIPELINE), 4.0)
        sess = _last_session(recs)
        self.assertIsNotNone(sess)
        self.assertIn(PARROT_ID, [s[0] for s in sess.active_skills])


# ─────────────────────────────────────────────────────────────────────────────
# SESSION-2 §2.6 — handler-boundary mutation, propagated via SessionManager
# ─────────────────────────────────────────────────────────────────────────────

class TestSec26HandlerBoundaryMutation(TestCase):
    """SESSION-2 §2.6: "a dispatched handler … MAY mutate session in-place;
    its emissions via ``forward``/``reply``/``response`` … carry the mutated
    session forward. A handler that emits no Message has no bus-visible way
    to propagate its session mutations." Exercised directly against
    ``ovos_bus_client``'s ``SessionManager``/``Message`` carrier — the
    handler-boundary write-then-derive round-trip is a property of those
    classes, not of the orchestrator, so no minicroft boot is needed. MUST
    (carrier)."""

    def test_handler_write_rides_forward_reply_response(self):
        """§2.6: a handler that reads its session off the dispatch Message
        via ``SessionManager.get``, mutates it in place, and derives
        ``forward``/``reply``/``response`` sees the mutation on all three.
        MUST."""
        msg = Message("skill.dispatch", {}, {"session": Session("se-26-a").serialize()})
        sess = SessionManager.get(msg)
        sess.activate_skill("probe.skill")
        for derived in (msg.forward("probe.skill.activate"),
                       msg.reply("skill.dispatch.response"),
                       msg.response({})):
            self.assertIn("probe.skill",
                          [s[0] for s in derived.context["session"]["active_skills"]])

    def test_collection_and_gui_message_carry_the_same_mutation(self):
        """§2.6: the handler boundary is not special-cased to plain
        ``Message`` — ``CollectionMessage``/``GUIMessage`` (whose
        non-standard constructors force hand-built derivations) carry a
        mutation made through the session bound via ``SessionManager.get``
        the same way. This is the surface bus-client < 2.11.4a1 lost: their
        ``forward``/``reply`` stamped from the registry's default-session
        fallback only, never from the session a caller actually bound to the
        source Message. MUST."""
        cmsg = CollectionMessage("collect.query", "handler.id", "q-1",
                                 data={}, context={"session": Session("se-26-b").serialize()})
        SessionManager.get(cmsg).activate_skill("probe.skill")
        self.assertIn("probe.skill",
                      [s[0] for s in cmsg.forward("collect.something")
                       .context["session"]["active_skills"]])

        gmsg = GUIMessage("gui.value.set", foo="bar")
        gmsg.context = {"session": Session("se-26-c").serialize()}
        SessionManager.get(gmsg).activate_skill("probe.skill")
        self.assertIn("probe.skill",
                      [s[0] for s in gmsg.forward("gui.something")
                       .context["session"]["active_skills"]])

    def test_emitting_no_message_has_no_bus_visible_effect(self):
        """§2.6, negative control: a handler that mutates the *object*
        returned by ``SessionManager.get`` but never derives a Message from
        the one it was given has nothing on the wire — the spec's "a handler
        that emits no Message has no bus-visible way to propagate its
        session mutations." A message BUILT BEFORE the mutation (frozen at
        construction, never derived from the dispatch Message afterwards)
        still carries its own pre-mutation snapshot. MUST NOT."""
        msg = Message("skill.dispatch", {}, {"session": Session("se-26-d").serialize()})
        unrelated = Message("some.other.topic", {}, {"session": Session("se-26-d").serialize()})
        SessionManager.get(msg).activate_skill("probe.skill")
        self.assertNotIn(
            "probe.skill",
            [s[0] for s in unrelated.context["session"].get("active_skills", [])])

    def test_bind_makes_get_and_derivations_see_the_orchestrator_round_session(self):
        """§2.6 (implementation detail powering it): an orchestrator that
        opens its own round session at intake and wants every later
        ``SessionManager.get``/derivation in that round to see that exact
        object — mutations included, per ``SessionManager.bind``'s
        docstring — binds it explicitly instead of letting ``get`` rebuild
        one lazily. After ``bind``, ``get`` returns the bound object and a
        mutation on it is what a derivation stamps. MUST (implementation
        contract; SessionManager itself is not spec-mandated)."""
        msg = Message("some.topic", {}, {})
        default = SessionManager.get_default_session()
        self.addCleanup(SessionManager.reset_default_session)
        bound = SessionManager.bind(msg, default)
        self.assertIs(bound, default)
        self.assertIs(SessionManager.get(msg), default)
        default.activate_skill("probe.skill")
        derived = msg.forward("some.topic.derived")
        self.assertIn("probe.skill",
                      [s[0] for s in derived.context["session"]["active_skills"]])

    def test_bind_refuses_a_default_shaped_session_that_is_not_the_store(self):
        """§2.6 (implementation contract): binding a freshly built
        default-shaped ``Session`` — rather than the registry's own
        ``get_default_session()`` object — would make ``get`` (which returns
        the binding) and the derivation stamp (which reads the store)
        disagree about the same Message, so ``bind`` refuses it with
        ``ValueError``. MUST NOT silently accept."""
        msg = Message("some.other.topic", {}, {})
        not_the_store = Session.deserialize({"session_id": "default"})
        with self.assertRaises(ValueError):
            SessionManager.bind(msg, not_the_store)

    def test_bind_refuses_a_session_id_mismatch(self):
        """§2.6 (implementation contract): a Message whose own carrier names
        one session id cannot be bound to a different named session — that
        is two disagreeing claims about which session the Message belongs
        to, not "the binding wins", so ``bind`` raises ``ValueError``. MUST
        NOT silently accept."""
        msg = Message("t", {}, {"session": {"session_id": "sat-2"}})
        other_named = Session("sat-1")
        with self.assertRaises(ValueError):
            SessionManager.bind(msg, other_named)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION-1 §2.1 — omission means default; null is not a deferral sentinel
# ─────────────────────────────────────────────────────────────────────────────

class TestSec21OmissionAndNull(TestCase):
    """SESSION-1 §2.1: a producer MAY omit any field ("let the orchestrator
    decide"); the consumer fills it with its deployment default at the point
    of consumption. ``null`` is NOT a deferral sentinel — a consumer that
    encounters an explicit ``null`` MUST treat it as if the field were omitted
    and MUST NOT reject the Message solely because of it (spec §64, §71)."""

    def test_omitted_field_resolves_to_default(self):
        """A session that omits ``lang`` deserializes with the deployment
        default, not an empty/None value (§2.1)."""
        sess = Session.deserialize({"session_id": "s1-omit"})
        self.assertTrue(sess.lang, "omitted lang did not resolve to a default")

    def test_explicit_null_treated_as_omitted(self):
        """An explicit ``null`` on a field is treated as omission: the consumer
        substitutes the default and does not raise (§2.1). This is the
        positive control that ``null`` is not a deferral sentinel."""
        default = Session.deserialize({"session_id": "s1-null-ctl"}).lang
        sess = Session.deserialize({"session_id": "s1-null", "lang": None})
        self.assertEqual(
            sess.lang, default,
            "explicit null lang was not treated as an omitted field")


# ─────────────────────────────────────────────────────────────────────────────
# SESSION-1 §3.1 — session identity and per-session keying
# ─────────────────────────────────────────────────────────────────────────────

class TestSec31SessionIdentity(TestCase):
    """SESSION-1 §3.1: an omitted ``session_id`` (an absent ``session``, an
    empty ``session: {}``) is filled by the consumer with the reserved value
    ``"default"`` (spec §95, §99). The installed ``ovos-bus-client`` mints a
    fresh random uuid instead, so the clause is strict-xfailed until it fills
    the reserved value."""

    @pytest.mark.xfail(
        reason="ovos-bus-client Session.deserialize mints a random uuid for a "
               "session with no session_id; SESSION-1 §3.1 fills the reserved "
               "value 'default'",
        strict=True,
    )
    def test_empty_session_resolves_to_default_id(self):
        """An empty session resolves to ``session_id: 'default'`` (§3.1)."""
        self.assertEqual(Session.deserialize({}).session_id, "default")


class TestSec31PerSessionKeying(TestCase):
    """SESSION-1 §3.1 (spec §227): a consumer that maintains per-session state
    MUST key that state on ``session_id`` — state for session A MUST NOT be
    visible to session B."""

    def test_state_for_session_a_not_visible_to_b(self):
        """Activating a skill in session A leaves session B's echoed session
        without that active handler (§3.1 keying)."""
        recs_a = capture(_MC, utterance("start parrot mode", "se-keying-a",
                                        CONVERSE_PIPELINE), 4.0)
        sess_a = _require_session(self, recs_a)
        # positive control: A really did activate the skill
        self.assertIn(PARROT_ID, [s[0] for s in sess_a.active_skills],
                      "session A did not activate the skill; test is vacuous")

        recs_b = capture(_MC, utterance("zxqw blah blah", "se-keying-b",
                                        [PADACIOSO_HIGH]), 4.0)
        sess_b = _require_session(self, recs_b)
        self.assertEqual(sess_b.session_id, "se-keying-b")
        self.assertNotIn(
            PARROT_ID, [s[0] for s in sess_b.active_skills],
            "session A's active handler leaked into session B")


# ─────────────────────────────────────────────────────────────────────────────
# SESSION-2 §2.1 — the bus is stateless transport
# ─────────────────────────────────────────────────────────────────────────────

class TestSec21BusStateless(TestCase):
    """SESSION-2 §2.1 (spec §543): the message bus MUST be stateless with
    respect to session — it MUST NOT interpret, mutate, persist, or
    special-case it. A Message placed on the bus is delivered to observers
    with its ``session`` byte-identical to what was emitted."""

    def test_bus_leaves_session_untouched_in_transit(self):
        """A session carried on a Message the orchestrator does not consume is
        delivered to a bus observer unchanged (§2.1)."""
        sent = Session("se-bus-stateless")
        sent.lang = "pt-PT"
        sent.activate_skill("probe.skill")
        payload = sent.serialize()

        seen = []
        def _rec(serialized):
            msg = serialized if isinstance(serialized, Message) \
                else Message.deserialize(serialized)
            if msg.msg_type == "ovos.test.session.probe":
                seen.append(msg.context.get("session"))
        _MC.bus.on("message", _rec)
        try:
            _MC.bus.emit(Message("ovos.test.session.probe", {},
                                 {"session": payload}))
            time.sleep(0.5)
        finally:
            _MC.bus.remove("message", _rec)

        self.assertTrue(seen, "probe message was not delivered to the observer")
        self.assertEqual(seen[-1], payload,
                         "the bus mutated the session in transit")

# ─────────────────────────────────────────────────────────────────────────────
# §3.5 — location
# ─────────────────────────────────────────────────────────────────────────────

_CHICAGO = {"lat": 41.85, "lon": -87.65, "tz": "America/Chicago"}
_LISBON = {"lat": 38.72, "lon": -9.14, "tz": "Europe/Lisbon"}
_LEGACY_CHICAGO_CONFIG = {
    "city": {"code": "Chicago", "name": "Chicago"},
    "coordinate": {"latitude": 41.85, "longitude": -87.65},
    "timezone": {"code": "America/Chicago", "name": "America/Chicago",
                 "dstOffset": 0.0, "offset": -360.0},
}


class TestSec35Location(TestCase):
    """§3.5: ``location`` recognizes exactly three keys — ``lat``, ``lon`` and
    ``tz`` — each independently omissible. The one key the specification gives
    normative consumer behaviour to is ``tz``: when present it is the IANA zone
    a consumer MUST use to resolve wall-clock time for that session; when
    absent the consumer resolves against its own deployment-configured zone.

    ovos-skill-alerts PR #183 built a DST-correctness feature on exactly this
    surface — two sessions with distinct zones resolve two distinct UTC
    instants through ``SessionManager.get(message).timezone``. These cells pin
    the clause at the producing repo (``ovos-bus-client``) so a rename or a
    precedence change is caught before it reaches a downstream skill."""

    def test_location_round_trips_the_three_keys(self):
        """§3.5: the three-key ``location`` object serializes and deserializes
        unchanged. MUST."""
        sess = Session("se-loc-roundtrip", lang="en-US",
                       location_prefs=dict(_CHICAGO))
        data = sess.serialize()
        self.assertEqual(data.get("location"), _CHICAGO)
        self.assertEqual(Session.deserialize(data).location, _CHICAGO)

    def test_timezone_reads_location_tz(self):
        """§3.5: "When ``location.tz`` is present, it is the IANA zone name a
        consumer MUST use to resolve wall-clock time for that session."."""
        sess = Session("se-loc-tzread", lang="en-US",
                       location_prefs=dict(_CHICAGO))
        self.assertEqual(sess.timezone, "America/Chicago")

    def test_partial_location_is_accepted(self):
        """§3.5: "Each of ``lat``, ``lon``, and ``tz`` is independently
        omissible; a ``location`` object MAY carry any subset." A tz-only
        location still resolves wall-clock time. MUST."""
        sess = Session("se-loc-partial", location_prefs={"tz": "Europe/Lisbon"})
        self.assertEqual(sess.serialize().get("location"),
                         {"tz": "Europe/Lisbon"})
        self.assertEqual(sess.timezone, "Europe/Lisbon")

    def test_session_tz_wins_over_the_configured_zone(self):
        """§3.5: the session-carried ``tz`` is what a consumer resolves against
        — it is not overridden by the deployment configuration. MUST."""
        configured = {"location": dict(_LEGACY_CHICAGO_CONFIG)}
        with patch.object(bus_client_session, "Configuration",
                          lambda: configured):
            configured_zone = Session("se-loc-configured").timezone
            self.assertEqual(configured_zone, "America/Chicago")

            overriding = Session("se-loc-override", lang="en-US",
                                 location_prefs=dict(_LISBON))
            msg = Message("recognizer_loop:utterance", {},
                          {"session": overriding.serialize()})
            got = SessionManager.get(msg)

            self.assertEqual(got.timezone, "Europe/Lisbon")
            self.assertNotEqual(got.timezone, configured_zone,
                                "session-carried zone did not win over the "
                                "configured zone")

    def test_absent_tz_falls_back_to_the_configured_zone(self):
        """§3.5: "When ``location.tz`` is absent, the consumer resolves
        wall-clock time against its own deployment-configured timezone."."""
        configured = {"location": dict(_LEGACY_CHICAGO_CONFIG)}
        with patch.object(bus_client_session, "Configuration",
                          lambda: configured):
            sess = Session.deserialize({"session_id": "se-loc-absent"})
            self.assertEqual(sess.location, {},
                             "session carried a location it was never given")
            msg = Message("recognizer_loop:utterance", {},
                          {"session": sess.serialize()})
            self.assertEqual(SessionManager.get(msg).timezone,
                             "America/Chicago")
