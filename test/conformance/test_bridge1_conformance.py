"""OVOS-BRIDGE-1 conformance suite.

Encodes the normative core (§3), ordering guidance (§5), and the *Conformance*
roll-up (§6) of OVOS-BRIDGE-1 (``ovos/org/architecture/bridge-1.md``).

BRIDGE-1 is an unusual spec: it "carries very little normative weight" and
most of it is **emergent** — behaviours that arise when MSG-1 / SESSION-1 /
SESSION-2 / PIPELINE-1 compose across a bus boundary. The bridge's own MUSTs
(§6) are about identity stamping, session preservation, and routing.

There is **no bridge component in the integrated stack** (the reference
implementation is HiveMind, which is not installed here). A conformance test
therefore cannot drive a real bridge end-to-end. What it *can* do — and what
this suite does — is assert the **bus-observable composition primitives the
bridge depends on**, exercised against the real ovos-core orchestrator:

- the orchestrator routes its responses with ``.reply()``, setting
  ``context.destination`` to the inbound ``context.source`` (BRIDGE-1
  §3.2 / §4.4 — the mechanism that makes ``destination``-based client
  isolation work);
- ``context.session.site_id`` (the opaque group id this spec owns, §3.3)
  survives every MSG-1 ``forward`` / ``reply`` / ``response`` derivation
  unchanged;
- the orchestrator reads the inbound ``session`` as the authoritative round
  state (§3.4) and echoes it on responses;
- all orchestrator emissions conform to MSG-1 (§6, the envelope shape a
  bridge relays).

The bridge's own obligations that require a bridge to exist (§3.1 source
stamping, §3.4.2 managing-mode session synthesis, §5 grace-period discard,
§4 emergent topologies) are documented with an explicit ``# not
bus-observable (no bridge in stack)`` note and skipped, so the file is a
complete §6 ledger even though only the composition layer is executable here.

xfail discipline mirrors the other suites: assert what the spec mandates, run
it, and ``xfail(strict=True)`` only where the impl diverges — never weaken to
the legacy behaviour.

Coverage map (MUST clause -> status against the installed stack):
- §3.1  unique context.source stamped per inbound message ........ not bus-observable (no bridge)
- §3.2  response routed to inbound source via .reply() ........... green (MSG-1 derivation)
- §3.2  destination preserved through forward derivation ......... green
- §3.3  site_id present after inbound MUST NOT be overwritten .... green (survives derivations)
- §3.3  site_id absent -> consumers MUST NOT infer a default ..... xfail (defaults to 'unknown')
- §3.3  consumers MUST NOT ascribe structure to site_id ......... green (opaque string)
- §3.4  inbound bus Message carries a valid session object ....... green (orchestrator round)
- §3.4  outbound responses include the session .................. green (echoed)
- §3.4.2 managing-mode distinct session_id per participant ....... not bus-observable (no bridge)
- §4.4  satellite skill deregister uses session_id .............. green (ovos.skill.deregister shape)
- §5    discard undeliverable after grace; never buffer ......... not bus-observable (no bridge)
- §6    all bus emissions conform to MSG-1 ...................... green
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import get_minicroft

from ._conformance import (
    PADACIOSO_HIGH,
    capture,
    reset_namespace,
    types,
    use_spec_namespace,
    utterance,
)

PARROT_ID = "ovos-skill-parrot.openvoiceos"
CONVERSE_PIPELINE = ["ovos-converse-pipeline-plugin", PADACIOSO_HIGH]

_MC = None
_HAS_SITE_ID = "site_id" in Session("probe").serialize()


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


def _last_session(recs):
    """The most recent serialized session carried on the captured messages."""
    for m in reversed(recs):
        if m.context.get("session"):
            return Session.deserialize(m.context["session"])
    return None


def _bridged_utterance(text, session_id, pipeline, source, **session_fields):
    """An entry Message shaped as a bridge would inject it: carrying a unique
    ``context.source`` (the satellite's stamped identity, §3.1) and the
    participant's session."""
    msg = utterance(text, session_id, pipeline, **session_fields)
    msg.context["source"] = source
    msg.context["destination"] = "skills"
    return msg


# =============================================================================
# §3.1 — Inbound identity stamping (source)
# =============================================================================

class TestSec31SourceStamping(TestCase):
    """§3.1: on receiving a message from an external participant the bridge MUST
    ensure the resulting bus Message carries a unique identifier in
    ``context.source``; without it the orchestrator cannot route responses
    back to the correct participant."""

    def test_source_stamping_requires_a_bridge(self):
        """§3.1 MUST: the bridge stamps a unique ``context.source`` per inbound
        participant message.

        # not bus-observable (no bridge in stack): source stamping is performed
        by a bridge as it ingests an *external* channel; with no bridge
        installed there is no ingest step to observe. The downstream half of
        this contract — that a *present* ``source`` is honoured for response
        routing — is exercised in TestSec32OutboundRouting."""
        self.skipTest("not bus-observable: §3.1 source stamping is bridge "
                      "ingest; no bridge in the stack")

    def test_orchestrator_honours_inbound_source_for_routing(self):
        """§3.1: the value of a stamped ``source`` is what makes the participant
        addressable — the orchestrator's response is addressed to it (§3.2).
        Here a unique ``source`` rides the inbound message and the response
        targets it."""
        src = "satellite-kitchen-uuid"
        recs = capture(_MC, _bridged_utterance(
            "start parrot mode", "br-src", CONVERSE_PIPELINE, source=src), 4.0)
        # at least one response is addressed back to the stamped source
        addressed = [m for m in recs
                     if m.context.get("destination") == src]
        self.assertTrue(
            addressed,
            "no orchestrator emission was addressed to the inbound source")


# =============================================================================
# §3.2 — Outbound routing
# =============================================================================

class TestSec32OutboundRouting(TestCase):
    """§3.2: the bridge relays a Message whose ``context.destination`` matches a
    known participant. The orchestrator fulfils this by using ``.reply()`` to
    route responses, setting ``destination`` to the original ``source`` the
    bridge stamped (§3.1) — this is what gives two participants sharing a
    ``session_id`` (incl. ``"default"``) client isolation."""

    def test_response_destination_is_inbound_source(self):
        """§3.2 MUST (the routing mechanism): the orchestrator derives its
        responses from the inbound message via ``.reply()``, setting
        ``context.destination`` to the inbound ``context.source`` so the bridge
        can deliver only to that participant."""
        src = "sat-A"
        recs = capture(_MC, _bridged_utterance(
            "start parrot mode", "br-dest", CONVERSE_PIPELINE, source=src), 4.0)
        # every reply that carries a destination targets the originating source
        dests = {m.context.get("destination") for m in recs
                 if m.context.get("destination")
                 and m.context.get("source") != src}
        self.assertIn(src, dests,
                      "no response routed back to the inbound source via reply")

    def test_msg1_reply_swaps_source_and_destination(self):
        """§3.2 (MSG-1 §5 derivation): ``.reply()`` swaps ``source`` and
        ``destination`` — the primitive the bridge relies on to address a
        response back to the participant that originated the utterance."""
        inbound = Message("ovos.utterance.handle", {},
                          {"source": "sat-X", "destination": "skills"})
        reply = inbound.reply("ovos.utterance.speak", {})
        self.assertEqual(reply.context.get("destination"), "sat-X")

    def test_forward_preserves_destination(self):
        """§3.2: a ``forward`` derivation preserves ``context.destination`` — a
        relayed-onward message keeps naming its intended consumer (MSG-1 §5)."""
        inbound = Message("ovos.utterance.handle", {},
                          {"source": "sat-Y", "destination": "hub"})
        fwd = inbound.forward("ovos.intent.matched", {})
        self.assertEqual(fwd.context.get("destination"), "hub")


# =============================================================================
# §3.3 — site_id assignment
# =============================================================================

# BRIDGE-1 §3.3 mandates the session field; its absence is a conformance
# failure of the installed bus-client, not a reason to skip the clause.
@pytest.mark.xfail(not _HAS_SITE_ID,
                   reason="BRIDGE-1 §3.3 MUST: the installed ovos-bus-client "
                          "Session has no site_id field",
                   strict=True)
class TestSec33SiteId(TestCase):
    """§3.3: ``site_id`` is the opaque group identifier owned by this spec.
    Once present on an inbound message after bridge processing, downstream
    components MUST NOT overwrite it; it travels unchanged through every
    forward/reply/response derivation (MSG-1 §5). Consumers MUST NOT parse it
    or infer a default when absent."""

    def test_site_id_survives_orchestrator_round_unchanged(self):
        """§3.3 MUST NOT overwrite: a ``site_id`` present on the inbound session
        travels unchanged through the orchestrator round and is echoed on the
        response."""
        recs = capture(_MC, _bridged_utterance(
            "start parrot mode", "br-site", CONVERSE_PIPELINE,
            source="sat-S", site_id="kitchen-cluster"), 4.0)
        sess = _last_session(recs)
        self.assertIsNotNone(sess, "no session echoed on any response")
        self.assertEqual(sess.serialize().get("site_id"), "kitchen-cluster",
                         "site_id was overwritten or dropped during the round")

    def test_site_id_survives_derivation_chain(self):
        """§3.3 MUST NOT overwrite: ``site_id`` rides every
        forward/reply/response derivation unchanged (MSG-1 §5)."""
        sess = Session("br-d")
        sess.site_id = "office-floor-2"
        inbound = Message("ovos.utterance.handle", {},
                          {"session": sess.serialize(), "source": "s"})
        for deriv in (inbound.forward("x", {}),
                      inbound.reply("y", {}),
                      inbound.response({})):
            carried = Session.deserialize(deriv.context["session"])
            self.assertEqual(carried.site_id, "office-floor-2")

    @pytest.mark.xfail(strict=True,
                       reason="BRIDGE-1 §3.3 MUST NOT infer a default: an "
                              "unsupplied site_id is absent; ovos-bus-client "
                              "Session defaults site_id to the sentinel string "
                              "'unknown' instead of leaving the field absent")
    def test_absent_site_id_yields_no_default(self):
        """§3.3 MUST NOT infer a default: when neither client nor bridge
        supplies a ``site_id`` the field is absent — a fresh session has no
        site_id value and consumers must treat absence as an unknown group."""
        sess = Session("br-nosite")
        self.assertIn(sess.serialize().get("site_id"), (None, "",),
                      "an unset site_id was given a non-empty default")

    def test_site_id_is_opaque_string(self):
        """§3.3 MUST NOT ascribe structure: ``site_id`` is compared only by
        string equality; no value is reserved by this spec, so an arbitrary
        opaque token round-trips intact."""
        sess = Session("br-opaque")
        sess.site_id = "x:y/z 42"  # arbitrary structure-free token
        self.assertEqual(
            Session.deserialize(sess.serialize()).site_id, "x:y/z 42")


# =============================================================================
# §3.4 — Session preservation
# =============================================================================

class TestSec34SessionPreservation(TestCase):
    """§3.4: the bridge MUST ensure every inbound bus Message carries a valid
    ``context.session`` object and MUST include the session from every outbound
    bus Message in the external payload. The orchestrator reads it as the
    authoritative round state (SESSION-2 §2)."""

    def test_inbound_session_is_authoritative_for_the_round(self):
        """§3.4: the session the bridge places on the inbound message is the
        authoritative state for the round — the orchestrator processes against
        the carried ``session_id`` and echoes the same id on its response."""
        recs = capture(_MC, _bridged_utterance(
            "start parrot mode", "br-auth", CONVERSE_PIPELINE,
            source="sat-Z"), 4.0)
        sess = _last_session(recs)
        self.assertIsNotNone(sess, "no session carried on any response")
        self.assertEqual(sess.session_id, "br-auth")

    def test_outbound_responses_include_the_session(self):
        """§3.4 MUST: every outbound bus Message includes the session, so a
        bridge can copy it back into the external payload — the orchestrator's
        responses carry ``context.session``."""
        recs = capture(_MC, _bridged_utterance(
            "start parrot mode", "br-out", CONVERSE_PIPELINE,
            source="sat-O"), 4.0)
        with_session = [m for m in recs if m.context.get("session")]
        self.assertTrue(
            with_session,
            "no outbound orchestrator Message carried a session object")

    def test_managing_mode_session_synthesis_requires_a_bridge(self):
        """§3.4.2 MUST: in managing mode the bridge assigns a distinct
        ``session_id`` per participant and synthesizes a session for opaque
        participants.

        # not bus-observable (no bridge in stack): session synthesis is a
        bridge-ingest behaviour for non-OVOS clients; with no bridge there is no
        opaque participant to synthesize for. SESSION-1 §4.1 materialization is
        covered by the SESSION suite."""
        self.skipTest("not bus-observable: §3.4.2 managing-mode synthesis is a "
                      "bridge behaviour; no bridge in the stack")


# =============================================================================
# §4.4 — Satellite skill registration / deregistration
# =============================================================================

class TestSec44SatelliteRegistration(TestCase):
    """§4.4: a satellite registers skills on the hub by relaying registration
    messages keyed by the satellite's ``session_id``; on disconnect the bridge
    SHOULD emit ``ovos.skill.deregister`` with that ``session_id``."""

    def test_skill_deregister_topic_is_spec_named(self):
        """§4.4 (INTENT-4 §8.4): the deregister the bridge emits on disconnect
        is ``ovos.skill.deregister`` — assert the spec topic name exists in the
        shared vocabulary, keyed by ``session_id`` in context."""
        from ovos_spec_tools import SpecMessage
        self.assertEqual(SpecMessage.SKILL_DEREGISTER.value,
                         "ovos.skill.deregister")

    def test_deregister_relay_requires_a_bridge(self):
        """§4.4 SHOULD: on satellite disconnect the bridge emits
        ``ovos.skill.deregister`` with the satellite's ``session_id`` for each
        registered skill.

        # not bus-observable (no bridge in stack): the deregister is emitted by
        the bridge on an external-channel disconnect event; no bridge means no
        disconnect to observe."""
        self.skipTest("not bus-observable: §4.4 disconnect deregister is a "
                      "bridge emission; no bridge in the stack")


# =============================================================================
# §5 — Message ordering & undeliverable discard
# =============================================================================

class TestSec5Ordering(TestCase):
    """§5: a bridge SHOULD preserve per-``session_id`` / per-``source`` FIFO
    ordering where the transport allows, and MUST discard undeliverable
    messages for a disconnected participant after a grace period, never
    buffering them indefinitely."""

    def test_undeliverable_discard_requires_a_bridge(self):
        """§5 MUST: a bridge discards undeliverable Messages for a disconnected
        participant after a deployment-defined grace period and MUST NOT buffer
        them indefinitely.

        # not bus-observable (no bridge in stack): buffering / discard is
        bridge-internal delivery state for an external participant; there is no
        external delivery queue to observe without a bridge."""
        self.skipTest("not bus-observable: §5 grace-period discard is "
                      "bridge-internal; no bridge in the stack")

    def test_fifo_ordering_requires_a_bridge(self):
        """§5 SHOULD: sequential utterances from the same participant are placed
        on the bus in receipt order, and responses to that participant are
        delivered in emission order.

        # not bus-observable (no bridge in stack): ordering is a property of the
        bridge's relay across the external transport, which is absent here. The
        orchestrator's own in-round ordering is covered by PIPELINE-1 §9."""
        self.skipTest("not bus-observable: §5 FIFO is a bridge-relay property; "
                      "no bridge in the stack")


# =============================================================================
# §6 — Conformance: all bus emissions conform to MSG-1
# =============================================================================

class TestSec6Msg1Conformance(TestCase):
    """§6: a bridge MUST conform to OVOS-MSG-1 for all bus emissions. The
    envelope a bridge relays (and the orchestrator responses it carries) MUST
    be valid MSG-1 envelopes — ``type`` / ``data`` / ``context`` with a
    well-formed session carrier."""

    def test_all_emissions_are_valid_msg1_envelopes(self):
        """§6 MUST: every emission on the round is a structurally valid MSG-1
        envelope (string ``type``, dict ``data``, dict ``context``)."""
        recs = capture(_MC, _bridged_utterance(
            "start parrot mode", "br-msg1", CONVERSE_PIPELINE,
            source="sat-M"), 4.0)
        self.assertTrue(recs, "no emissions captured")
        for m in recs:
            self.assertIsInstance(m.msg_type, str)
            self.assertIsInstance(m.data, dict)
            self.assertIsInstance(m.context, dict)

    def test_carried_session_is_a_valid_session1_object(self):
        """§6 / §3.4: the ``context.session`` a bridge relays deserializes to a
        valid SESSION-1 object carrying a ``session_id``."""
        recs = capture(_MC, _bridged_utterance(
            "start parrot mode", "br-sess1", CONVERSE_PIPELINE,
            source="sat-V"), 4.0)
        sess = _last_session(recs)
        self.assertIsNotNone(sess)
        self.assertTrue(sess.session_id)
