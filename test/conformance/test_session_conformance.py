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
strict xfail so it flips loudly when the orchestrator starts draining it.
Drivers are described in ``_conformance.py``.
"""
import time
from typing import Optional
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, UtteranceState
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
        time.sleep(2)
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
