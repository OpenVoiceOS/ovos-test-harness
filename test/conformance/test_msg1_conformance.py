"""OVOS-MSG-1 conformance suite.

Encodes the normative *Conformance* clauses (§7) and the envelope / routing /
derivation / serialization rules of OVOS-MSG-1
(``ovos/org/architecture/msg-1.md``) as assertions against the **integrated
stack's** Message type — ``ovos_bus_client.message.Message`` — the value the
whole OVOS runtime actually produces and consumes on the bus.

Why the bus-client Message (not the reference)
----------------------------------------------
``ovos_spec_tools.message.Message`` is the *reference* implementation of
MSG-1 — it is correct by construction. The interesting conformance question
is whether the **runtime** envelope (``ovos_bus_client.Message``, the type
every component on the bus exchanges) satisfies the same MUSTs. Each test
therefore asserts the spec mandate against ``ovos_bus_client.Message`` and,
where the spec text references a derivation the runtime offers under the same
name (``forward`` / ``reply`` / ``response``), exercises that.

The reference Message is imported as ``RefMessage`` and used only to
demonstrate, in the docstring-quoted divergences, the behaviour the spec
mandates where the bus-client diverges — never to weaken an assertion.

xfail discipline
----------------
Each test asserts what the spec MANDATES and runs it against the live
bus-client Message. Where the bus-client diverges from the spec the test is
decorated ``@pytest.mark.xfail(strict=True, reason="MSG-1 §X MUST …; stack
does …")`` so it flips to a pass automatically once the runtime is brought
into conformance. Conformant clauses are green. Pure-prose, non-observable
requirements are skipped with a ``# not bus-observable`` note.
"""
import json
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

# Reference implementation of MSG-1 — correct by construction. Imported only
# to contrast spec-mandated behaviour in docstrings; assertions target the
# runtime ``Message`` above.
from ovos_spec_tools.message import Message as RefMessage
from ovos_spec_tools.message import MalformedMessage
from ovos_spec_tools.intent_topics import is_intent_topic


# ─────────────────────────────────────────────────────────────────────────────
# §2 — The envelope
# ─────────────────────────────────────────────────────────────────────────────

class TestSec2Envelope(TestCase):
    """§2: a Message is a JSON object with exactly ``type`` / ``data`` /
    ``context``; absent ``data`` / ``context`` mean ``{}``; unknown top-level
    keys MUST be rejected."""

    def test_serialized_has_only_envelope_keys(self):
        """§2 (producer): a serialized Message carries no top-level key beyond
        ``type``, ``data``, ``context``. MUST."""
        obj = json.loads(Message("a.b", {"x": 1}, {"source": "A"}).serialize())
        self.assertEqual(set(obj.keys()), {"type", "data", "context"})

    def test_absent_data_context_default_to_empty(self):
        """§2: "consumers MUST treat an absent ``data`` or ``context`` as
        equivalent to ``{}``." A Message deserialized from a payload carrying
        only ``type`` MUST present ``data == {}`` and ``context == {}``."""
        m = Message.deserialize(json.dumps({"type": "a.b"}))
        self.assertEqual(m.data, {})
        self.assertEqual(m.context, {})

    def test_unknown_top_level_key_rejected(self):
        """§2: "Other top-level keys MUST NOT appear; consumers MUST reject any
        Message with unknown top-level keys." Deserializing a payload with an
        extra top-level key MUST fail. MUST. (Conformant: ovos-bus-client 2.4+
        adopted the MSG-1 reference envelope, which raises MalformedMessage.)"""
        payload = json.dumps({"type": "a.b", "data": {}, "extra": 1})
        with self.assertRaises((ValueError, AssertionError, KeyError)):
            Message.deserialize(payload)

    def test_reference_rejects_unknown_top_level_key(self):
        """§2 cross-check: the reference envelope rejects unknown top-level
        keys as the spec mandates (anchors the divergence above). MUST."""
        with self.assertRaises(MalformedMessage):
            RefMessage.deserialize(json.dumps({"type": "a.b", "extra": 1}))


class TestSec21Type(TestCase):
    """§2.1: ``type`` is a non-empty string matching the topic syntax (ASCII
    letters/digits/``.``/``:``/``_``/``-``, no whitespace)."""

    def test_empty_type_is_nonconformant_on_serialize(self):
        """§2.1: an emitted Message MUST have a non-empty ``type`` string.
        Serializing a Message built with an empty ``type`` MUST NOT yield a
        conformant wire object — a conformant producer rejects it. MUST.
        (Conformant: ovos-bus-client 2.4+ raises on serializing an empty
        type.)"""
        with self.assertRaises((ValueError, AssertionError)):
            Message("").serialize()

    def test_whitespace_in_type_is_nonconformant(self):
        """§2.1: ``type`` MUST contain no whitespace. A Message whose ``type``
        contains a space MUST NOT serialize to a conformant wire object — a
        conformant producer rejects it. MUST."""
        with self.assertRaises((ValueError, AssertionError)):
            Message("a b").serialize()


class TestSec22Data(TestCase):
    """§2.2: ``data`` is a JSON object; key order is not significant."""

    def test_data_key_order_not_significant(self):
        """§2.2: "consumers MUST NOT reject a Message because of key order."
        Two payloads differing only in ``data`` key order deserialize to equal
        ``data`` maps. MUST."""
        a = Message.deserialize('{"type":"t","data":{"x":1,"y":2}}')
        b = Message.deserialize('{"type":"t","data":{"y":2,"x":1}}')
        self.assertEqual(a.data, b.data)


class TestSec23Context(TestCase):
    """§2.3: ``context`` is topic-independent metadata; a consumer MUST NOT
    reject a Message over a context key and MUST ignore unknown context keys."""

    def test_unknown_context_key_tolerated(self):
        """§2.3: "A consumer MUST NOT reject a Message because of the presence
        … of any ``context`` key; a consumer that does not understand a
        ``context`` key MUST ignore it." An arbitrary context key round-trips
        without error. MUST."""
        m = Message.deserialize(json.dumps(
            {"type": "t", "context": {"x-tracing-id": "abc", "vendor": {"z": 1}}}))
        self.assertEqual(m.context.get("x-tracing-id"), "abc")
        self.assertEqual(m.context.get("vendor"), {"z": 1})

    def test_empty_context_tolerated(self):
        """§2.3 / §7 (consumer): an empty ``context`` object is well-formed and
        accepted. MUST."""
        m = Message.deserialize(json.dumps({"type": "t", "context": {}}))
        self.assertEqual(m.context, {})


class TestSec211IdentifierSeparator(TestCase):
    """§2.1.1: a topic assembled at runtime from named identifiers — e.g. the
    ``<skill_id>:<intent_name>`` dispatch topic — is only unambiguously
    parseable if the identifiers used as components do NOT contain the
    separator character the topic uses structurally. "a topic shaped
    ``<A>:<B>`` requires A and B to not contain ``:``." An identifier that
    carries the separator MUST NOT be used as a topic component."""

    @staticmethod
    def _left(topic):
        """Parse ``<A>:<B>`` on the FIRST colon."""
        a, _, b = topic.partition(":")
        return a, b

    @staticmethod
    def _right(topic):
        """Parse ``<A>:<B>`` on the LAST colon."""
        a, _, b = topic.rpartition(":")
        return a, b

    def test_colon_free_identifiers_round_trip_unambiguously(self):
        """§2.1.1 (positive control): colon-free component identifiers assemble
        a dispatch topic that parses back to exactly the same
        ``(skill_id, intent_name)`` regardless of which end a consumer splits
        from — there is exactly one separator, so the topic is unambiguous.
        MUST (the parseability §2.1.1 guarantees)."""
        skill_id, intent_name = "skill-weather.openvoiceos", "current"
        topic = f"{skill_id}:{intent_name}"
        self.assertTrue(is_intent_topic(topic))
        self.assertEqual(self._left(topic), (skill_id, intent_name))
        self.assertEqual(self._right(topic), (skill_id, intent_name))

    def test_colon_in_identifier_makes_topic_ambiguous(self):
        """§2.1.1: an identifier that contains the structural separator breaks
        unambiguous parseability. A ``skill_id`` carrying a ``:`` yields a
        dispatch topic ``<a>:<b>:<c>`` that two conformant consumers split into
        DIFFERENT components — first-colon parsing recovers a different
        ``(skill_id, intent_name)`` than last-colon parsing — so neither
        recovers the identifiers the topic was built from. Such an identifier
        MUST NOT be used as a topic component. MUST NOT."""
        skill_id, intent_name = "org:weather", "current"
        topic = f"{skill_id}:{intent_name}"
        # The two conformant parses disagree — the topic is not unambiguously
        # parseable, which is exactly what §2.1.1 forbids the identifier to cause.
        self.assertNotEqual(self._left(topic), self._right(topic))
        # And at least one parse fails to recover the original skill_id.
        self.assertNotEqual(self._left(topic), (skill_id, intent_name))


# ─────────────────────────────────────────────────────────────────────────────
# §3 — Routing keys
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3Routing(TestCase):
    """§3.2 / §3.3 / §3.4: ``source`` / ``destination`` are opaque routing
    metadata; ``destination`` MAY be a string or an array; absence == broadcast;
    consumers MUST NOT ascribe structure beyond string equality."""

    def test_source_destination_round_trip_opaque(self):
        """§3.4: ``source`` / ``destination`` are opaque strings preserved
        verbatim across (de)serialization — the envelope ascribes no structure
        to them beyond string equality. MUST."""
        m = Message("t", {}, {"source": "sat:7f::node",
                              "destination": "core/main"})
        rt = Message.deserialize(m.serialize())
        self.assertEqual(rt.context["source"], "sat:7f::node")
        self.assertEqual(rt.context["destination"], "core/main")

    def test_destination_array_preserved(self):
        """§3.3: ``destination`` MAY be an array of strings; it is preserved
        verbatim as a list. MUST (carry the §3.3 array form)."""
        rt = Message.deserialize(
            Message("t", {}, {"destination": ["a", "b"]}).serialize())
        self.assertEqual(rt.context["destination"], ["a", "b"])

    def test_absent_destination_is_broadcast(self):
        """§3.3: "Absence (or an empty array) means broadcast." A Message
        without ``destination`` is well-formed and carries no destination —
        the consumer MUST NOT require it. MUST (consumer §7)."""
        m = Message.deserialize(json.dumps({"type": "t", "context": {"source": "A"}}))
        self.assertIsNone(m.context.get("destination"))


# ─────────────────────────────────────────────────────────────────────────────
# §4 — The session carrier
# ─────────────────────────────────────────────────────────────────────────────

class TestSec4Session(TestCase):
    """§4 / §4.1: ``session`` rides inside ``Message.context``; propagation
    preserves it unchanged; a producer MUST NOT modify a ``session`` already
    present during propagation."""

    def test_session_rides_in_context(self):
        """§4: the session carrier lives at ``Message.context['session']``.
        MUST (carrier location)."""
        sess = Session("s-loc")
        m = Message("t", {}, {"session": sess.serialize()})
        self.assertIn("session", m.context)
        self.assertEqual(m.context["session"]["session_id"], "s-loc")

    def test_forward_preserves_session_unchanged(self):
        """§4.1 / §5.1: "A producer MUST NOT modify a ``session`` already
        present on the source Message during propagation." ``forward`` carries
        the session value through unchanged. MUST."""
        sess = Session("s-fwd").serialize()
        src = Message("t.req", {}, {"session": sess})
        fwd = src.forward("t.relay", {"x": 1})
        self.assertEqual(fwd.context.get("session"), sess)

    def test_reply_preserves_session_unchanged(self):
        """§4.1 / §5.2 step 3: ``reply`` preserves ``session`` unchanged across
        the routing reversal. MUST."""
        sess = Session("s-rep").serialize()
        src = Message("t.req", {}, {"session": sess, "source": "A", "destination": "B"})
        rep = src.reply("t.req.response", {})
        self.assertEqual(rep.context.get("session"), sess)

    def test_forward_does_not_mutate_source_session(self):
        """§4.1: propagation MUST NOT modify the source Message's ``session``.
        Mutating the derived Message's context must not leak back to the
        source. MUST (independence of derived context)."""
        sess = Session("s-iso").serialize()
        src = Message("t.req", {}, {"session": sess})
        fwd = src.forward("t.relay")
        fwd.context["session"] = {"session_id": "tampered"}
        self.assertEqual(src.context["session"]["session_id"], "s-iso")


# ─────────────────────────────────────────────────────────────────────────────
# §5 — Message derivations
# ─────────────────────────────────────────────────────────────────────────────

class TestSec51Forward(TestCase):
    """§5.1 ``forward(T', D')``: produces ``{type: T', data: D', context: C}``
    with ``context`` (including ``source`` / ``destination`` / ``session``)
    preserved unchanged; the forwarder does NOT become the new ``source``."""

    def _fwd(self):
        src = Message("t.req", {"q": 1},
                      {"source": "EMITTER", "destination": "CORE",
                       "session": Session("s-fwd2").serialize()})
        return src, src.forward("t.relay", {"r": 2})

    def test_forward_sets_type_and_data(self):
        """§5.1: the result's ``type`` is ``T'`` and ``data`` is ``D'``. MUST."""
        _, fwd = self._fwd()
        self.assertEqual(fwd.msg_type, "t.relay")
        self.assertEqual(fwd.data, {"r": 2})

    def test_forward_preserves_routing_keys(self):
        """§5.1: ``context`` is preserved unchanged, including ``source`` and
        ``destination`` — the forwarder does NOT become the new ``source``.
        MUST."""
        _, fwd = self._fwd()
        self.assertEqual(fwd.context.get("source"), "EMITTER")
        self.assertEqual(fwd.context.get("destination"), "CORE")


class TestSec52Reply(TestCase):
    """§5.2 ``reply(T', D')``: copies ``C`` and reverses the §3 routing keys so
    the new Message is addressed back to the source's producer."""

    def test_reply_swaps_when_both_present(self):
        """§5.2 steps 1-2: with both ``source`` and ``destination`` set on the
        source, the reply's ``destination`` is the old ``source`` and its
        ``source`` is the old ``destination``. MUST."""
        src = Message("t.req", {}, {"source": "ASKER", "destination": "CORE"})
        rep = src.reply("t.req.response", {})
        self.assertEqual(rep.context.get("destination"), "ASKER")
        self.assertEqual(rep.context.get("source"), "CORE")

    def test_reply_source_only_addresses_back(self):
        """§5.2 step 1: "If ``C.source`` is set, the new context's
        ``destination`` is set to ``C.source``." This MUST hold even when the
        source Message carries no ``destination``. MUST. (Conformant:
        bus-client 2.4+ performs the swap on each key independently.)"""
        src = Message("t.req", {}, {"source": "ASKER"})
        rep = src.reply("t.req.response", {})
        self.assertEqual(rep.context.get("destination"), "ASKER")

    def test_reply_destination_only_sets_source(self):
        """§5.2 step 2: "If ``C.destination`` is set and is a single string,
        the new context's ``source`` is set to ``C.destination``." MUST.
        (Conformant in bus-client 2.4+.)"""
        src = Message("t.req", {}, {"destination": "CORE"})
        rep = src.reply("t.req.response", {})
        self.assertEqual(rep.context.get("source"), "CORE")

    def test_reply_preserves_other_context_keys(self):
        """§5.2 step 3: all other ``context`` keys are preserved unchanged.
        MUST."""
        src = Message("t.req", {}, {"source": "A", "destination": "B",
                                    "x-trace": "zz"})
        rep = src.reply("t.req.response", {})
        self.assertEqual(rep.context.get("x-trace"), "zz")

    def test_reply_does_not_mutate_source_context(self):
        """§5.2: the reply derives from a copy of ``C`` — mutating the reply's
        context MUST NOT alter the source Message. MUST (independence)."""
        src = Message("t.req", {}, {"source": "A", "destination": "B"})
        rep = src.reply("t.req.response", {})
        rep.context["source"] = "TAMPERED"
        self.assertEqual(src.context["source"], "A")


class TestSec53Response(TestCase):
    """§5.3 ``response(D')``: equivalent to ``reply(T + '.response', D')`` —
    a reply whose topic is the source topic suffixed with ``.response``."""

    def test_response_suffixes_type(self):
        """§5.3: "A ``response`` is a ``reply`` whose topic is the source topic
        suffixed with ``.response``." MUST."""
        src = Message("ovos.intent.list", {}, {"source": "A", "destination": "B"})
        resp = src.response({"intents": []})
        self.assertEqual(resp.msg_type, "ovos.intent.list.response")

    def test_response_applies_reply_routing(self):
        """§5.3: ``response`` delegates to ``reply``, so the §5.2 routing
        reversal applies — the response is addressed back to the asker. MUST
        (when both routing keys present, the §5.2 swap is conformant)."""
        src = Message("ovos.intent.list", {}, {"source": "ASKER", "destination": "CORE"})
        resp = src.response({})
        self.assertEqual(resp.context.get("destination"), "ASKER")


# §5.4 — "No central correlation": fully-prose non-prescription. There is no
# observable behaviour to assert — the spec mandates the *absence* of a host
# correlation index, not any positive bus event. The only positive raw-material
# claims it makes (response suffix §5.3, session preservation §4) are covered by
# TestSec53Response and TestSec4Session above.
# not bus-observable: §5.4


# ─────────────────────────────────────────────────────────────────────────────
# §6 — Serialization
# ─────────────────────────────────────────────────────────────────────────────

class TestSec6Serialization(TestCase):
    """§6: a Message serializes to a single UTF-8 JSON object; numbers MUST be
    finite; a payload that cannot be parsed as a conforming object MUST be
    treated as malformed and MUST NOT be silently coerced."""

    def test_serialized_is_single_json_object(self):
        """§6: "A serialized Message is a single top-level JSON object — not a
        JSON array, not a stream of objects." MUST."""
        obj = json.loads(Message("t", {"x": 1}).serialize())
        self.assertIsInstance(obj, dict)

    def test_key_order_not_relied_on(self):
        """§6: "Object key order is not significant. Producers and consumers
        MUST NOT rely on it." A reordered serialization deserializes equal.
        MUST."""
        m = Message("t", {"b": 2, "a": 1}, {"d": 4, "c": 3})
        reordered = json.dumps({"context": m.context, "data": m.data, "type": m.msg_type})
        rt = Message.deserialize(reordered)
        self.assertEqual((rt.msg_type, rt.data, rt.context),
                         (m.msg_type, m.data, m.context))

    def test_non_finite_number_rejected_on_serialize(self):
        """§6: serializing a Message whose ``data`` carries a non-finite number
        MUST NOT emit an invalid-JSON ``NaN``/``Infinity`` token — it MUST be
        rejected. MUST. (Conformant: bus-client 2.4+ serializes with
        ``allow_nan=False`` and raises on a non-finite number.)"""
        with self.assertRaises((ValueError, AssertionError)):
            Message("t", {"x": float("nan")}).serialize()

    def test_unparsable_payload_treated_as_malformed(self):
        """§6 / §7 (consumer): "A consumer that cannot parse a received payload
        as a JSON object conforming to §2 MUST treat it as malformed and MUST
        NOT silently coerce it." Deserializing non-JSON MUST raise rather than
        return a coerced Message. MUST."""
        with self.assertRaises(Exception):
            Message.deserialize("this is not json {")


# ─────────────────────────────────────────────────────────────────────────────
# §7 — Conformance (producer / consumer MUSTs not covered above)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec7Conformance(TestCase):
    """§7: producer MUST give ``data`` / ``context`` JSON-object values when
    present; consumer MUST NOT require ``source`` / ``destination`` / ``session``
    to be present (all optional)."""

    def test_producer_data_context_are_objects(self):
        """§7 (producer): when present, ``data`` and ``context`` are JSON-object
        values. The serialized envelope's ``data`` / ``context`` are objects.
        MUST."""
        obj = json.loads(Message("t", {"x": 1}, {"source": "A"}).serialize())
        self.assertIsInstance(obj["data"], dict)
        self.assertIsInstance(obj["context"], dict)

    def test_consumer_accepts_bare_type_message(self):
        """§7 (consumer): "not require any of ``source``, ``destination``, or
        ``session`` to be present — they are all optional, and a Message
        without them is well-formed." A bare ``{"type": …}`` deserializes
        cleanly. MUST."""
        m = Message.deserialize(json.dumps({"type": "ovos.utterance.handle"}))
        self.assertEqual(m.msg_type, "ovos.utterance.handle")
        self.assertEqual(m.context, {})
