"""OVOS-CONTEXT-1 conformance suite.

Encodes the normative *Conformance* clauses (§8) and the entry / scope / decay /
mutation / gating rules of OVOS-CONTEXT-1
(``ovos/org/architecture/intent-context.md``) as assertions against the
integrated OVOS stack.

Two observable surfaces
-----------------------
CONTEXT-1 splits cleanly into two layers, tested differently:

1. **The carrier** — ``session.intent_context`` as a field of the OVOS-SESSION-1
   session that rides inside ``Message.context`` (CONTEXT-1 §2, §4.1
   propagation, §3 key shapes). This is owned by the session wire shape and is
   exercised through the real ``ovos_bus_client.Session`` carrier and the
   MSG-1 ``forward`` / ``reply`` derivations. ovos-bus-client 2.4+ inherits the
   spec-tools session, so the carrier is conformant — these clauses are green.

2. **The orchestrator / engine behaviour** — the decay tick (§4), the
   ``ovos.session.sync`` entry-by-entry merge (§5.3), the positive / negative
   gating contracts (§6 / §6.1), and the §7 context-supplied slot fill. These
   are owned by ovos-core (the orchestrator) and the intent engines
   (adapt / padatious). The installed stack still uses the **legacy**
   frame-based ``session.context`` (``IntentContextManager``) and adapt's
   own context-entity matching; it implements **none** of CONTEXT-1's flat
   ``session.intent_context`` decaying-map model, ``requires_context`` /
   ``excludes_context`` gating, or ``ovos.session.sync`` merge. Those clauses
   are therefore ``xfail`` end-to-end against ovos-core, each citing the
   legacy mechanism it should replace.

xfail discipline
----------------
Every test asserts what CONTEXT-1 MANDATES and runs it. Carrier clauses the
stack already satisfies are green. Orchestrator/engine clauses the stack does
not yet implement are ``@pytest.mark.xfail(strict=False, reason=…)`` so they
flip to pass once core/engines adopt the spec. Pure-prose, non-observable
requirements are skipped with a ``# not bus-observable`` note.
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import get_minicroft, register_padatious_intent

from ._conformance import (
    PADACIOSO_HIGH,
    capture,
    first,
    reset_namespace,
    types,
    use_spec_namespace,
    utterance,
)


# A live CONTEXT-1 entry (§2) and a dead one, for the structural clauses.
def _entry(value=None, expires_at=None, turns_remaining=None):
    e = {"value": value}
    if expires_at is not None:
        e["expires_at"] = expires_at
    if turns_remaining is not None:
        e["turns_remaining"] = turns_remaining
    return e


def _is_live(entry, now):
    """The §2 liveness predicate, stated verbatim from the spec, for asserting
    what a conformant orchestrator's prune step (§4) must compute. An entry is
    live iff turns_remaining is unset/null/>0 AND expires_at is
    unset/null/>now."""
    tr = entry.get("turns_remaining")
    ea = entry.get("expires_at")
    turns_ok = tr is None or tr > 0
    clock_ok = ea is None or ea > now
    return turns_ok and clock_ok


# ─────────────────────────────────────────────────────────────────────────────
# §2 — The context entry and its carrier (session-level, conformant)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec2EntryCarrier(TestCase):
    """§2: ``session.intent_context`` is a flat map key -> entry carried inside
    the session; an entry carries ``value`` / ``expires_at`` /
    ``turns_remaining``; an absent map is equivalent to ``{}``."""

    def test_intent_context_is_a_session_field(self):
        """§2: ``session.intent_context`` is a registered field of the session
        carrier. The runtime session round-trips it. MUST (carrier)."""
        s = Session("ic-field")
        s.intent_context = {"person": _entry("Bob", turns_remaining=3)}
        rt = Session.deserialize(s.serialize())
        self.assertEqual(rt.serialize().get("intent_context"),
                         {"person": {"value": "Bob", "turns_remaining": 3}})

    def test_absent_intent_context_equivalent_to_empty(self):
        """§2: "An absent ``session.intent_context`` is equivalent to ``{}``."
        A fresh session omits the field (SESSION-1 omit-when-empty), which a
        consumer reads as the empty map. MUST."""
        ser = Session("ic-absent").serialize()
        self.assertEqual(ser.get("intent_context") or {}, {})

    def test_entry_fields_round_trip(self):
        """§2: an entry's ``value`` / ``expires_at`` / ``turns_remaining`` fields
        survive (de)serialization verbatim. MUST (entry shape)."""
        s = Session("ic-entry")
        s.intent_context = {"k": _entry("v", expires_at=1717000000.0, turns_remaining=2)}
        rt = Session.deserialize(s.serialize()).serialize()["intent_context"]["k"]
        self.assertEqual(rt, {"value": "v", "expires_at": 1717000000.0,
                              "turns_remaining": 2})

    def test_flag_entry_value_is_null(self):
        """§2: a flag entry carries ``value: null`` (presence-only). The null
        value round-trips as JSON null. MUST."""
        s = Session("ic-flag")
        s.intent_context = {"in_confirmation": _entry(None, turns_remaining=1)}
        rt = Session.deserialize(s.serialize()).serialize()["intent_context"]
        self.assertIsNone(rt["in_confirmation"]["value"])

    def test_liveness_predicate(self):
        """§2: "An entry is live iff both: ``turns_remaining`` is unset/null/>0;
        ``expires_at`` is unset/null/> current Unix time." This is the predicate
        a conformant orchestrator's §4 prune MUST compute. MUST (predicate)."""
        now = time.time()
        self.assertTrue(_is_live(_entry("v"), now))
        self.assertTrue(_is_live(_entry("v", turns_remaining=1), now))
        self.assertFalse(_is_live(_entry("v", turns_remaining=0), now))
        self.assertFalse(_is_live(_entry("v", expires_at=now - 1), now))
        self.assertTrue(_is_live(_entry("v", expires_at=now + 100), now))


# ─────────────────────────────────────────────────────────────────────────────
# §3 — Scopes encoded in the key shape (carrier-level, conformant)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3KeyShapes(TestCase):
    """§3: scope is encoded in the key — a bare key is shared, a
    ``<skill_id>:<key>`` key is private. The ``:`` is the single load-bearing
    separator; both segments are bound by MSG-1 §2.1.1 (no ``:``)."""

    def test_bare_and_prefixed_keys_preserved(self):
        """§3: bare (shared) and prefixed (private) keys are stored verbatim in
        ``session.intent_context`` and survive the carrier round-trip. MUST."""
        s = Session("ic-scope")
        s.intent_context = {
            "person": _entry("Bob", turns_remaining=3),                  # shared
            "tea.skill:in_confirmation": _entry(None, turns_remaining=1),  # private
        }
        rt = Session.deserialize(s.serialize()).serialize()["intent_context"]
        self.assertIn("person", rt)
        self.assertIn("tea.skill:in_confirmation", rt)

    def test_prefixed_key_has_exactly_one_separator(self):
        """§3 / §2: "A prefixed key contains exactly one ``:``." The owner /
        sub-key split is unambiguous — splitting on the first ``:`` recovers the
        owner. MUST (key-shape rule the orchestrator relies on)."""
        key = "people.skill:last_query"
        owner, _, subkey = key.partition(":")
        self.assertEqual(owner, "people.skill")
        self.assertNotIn(":", subkey)


# ─────────────────────────────────────────────────────────────────────────────
# §4 / §4.1 — Propagation of the carrier across derivations (conformant)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec4Propagation(TestCase):
    """§4.1 / MSG-1 §5: ``session.intent_context`` rides inside the session
    carrier and is propagated unchanged across ``forward`` / ``reply``."""

    def _msg_with_ctx(self):
        s = Session("ic-prop")
        s.intent_context = {"person": _entry("Bob", turns_remaining=3)}
        return Message("t.req", {}, {"session": s.serialize()})

    def test_forward_propagates_intent_context(self):
        """§4.1: a derived ``forward`` Message carries the source's
        ``intent_context`` unchanged (MSG-1 §5.1 preserves ``session``). MUST."""
        fwd = self._msg_with_ctx().forward("ovos.session.sync")
        self.assertEqual(fwd.context["session"].get("intent_context"),
                         {"person": {"value": "Bob", "turns_remaining": 3}})

    def test_reply_propagates_intent_context(self):
        """§4.1: a derived ``reply`` Message preserves ``intent_context`` across
        the routing reversal (MSG-1 §5.2 step 3). MUST."""
        rep = self._msg_with_ctx().reply("t.req.response")
        self.assertEqual(rep.context["session"].get("intent_context"),
                         {"person": {"value": "Bob", "turns_remaining": 3}})


# ─────────────────────────────────────────────────────────────────────────────
# §5 — Mutation pathways (orchestrator behaviour — unimplemented -> xfail)
# ─────────────────────────────────────────────────────────────────────────────

_LEGACY_NOTE = (
    "the installed ovos-core still uses the legacy frame-based "
    "session.context (IntentContextManager) and implements none of "
    "CONTEXT-1's session.intent_context map"
)

# Shared minicroft for the end-to-end orchestrator clauses.
SKILL_ID = "ovos-skill-hello-world.openvoiceos"
_MC = None


def setUpModule():
    global _MC
    LOG.set_level("CRITICAL")
    use_spec_namespace()
    _MC = get_minicroft([SKILL_ID])
    time.sleep(2)


def tearDownModule():
    if _MC is not None:
        _MC.stop()
    reset_namespace()


def _sync_and_readback(session_id, intent_context):
    """Emit an ``ovos.session.sync`` carrying ``intent_context``, then run an
    utterance and read back the orchestrator's working ``intent_context`` from
    the session echoed on the responses. Returns the read-back map (or ``{}``).
    """
    s = Session(session_id)
    s.lang = "en-US"
    s.pipeline = [PADACIOSO_HIGH]
    sync = Message("ovos.session.sync",
                   {"session_data": s.serialize(),
                    "session": {**s.serialize(), "intent_context": intent_context}},
                   {"session": s.serialize()})
    capture(_MC, sync, 1.5)
    recs = capture(_MC, utterance("zxqw blah blah", session_id, [PADACIOSO_HIGH]), 3.0)
    for m in reversed(recs):
        if m.context.get("session"):
            return Session.deserialize(m.context["session"]).serialize().get(
                "intent_context") or {}
    return {}


class TestSec53SessionSyncMerge(TestCase):
    """§5.3: on ``ovos.session.sync`` the orchestrator MUST apply the
    ``intent_context`` payload **entry-by-entry** — present entry objects set or
    replace; ``null`` entries delete; absent keys are unchanged."""

    @pytest.mark.xfail(strict=False,
                       reason="CONTEXT-1 §5.3 MUST apply ovos.session.sync "
                              "intent_context entry-by-entry into the working "
                              f"session; {_LEGACY_NOTE}, and ovos-core does not "
                              "consume an ovos.session.sync intent_context "
                              "payload at all (no merge handler).")
    def test_sync_sets_entry(self):
        """§5.3: a present entry object in the sync payload sets/replaces that
        key in the orchestrator's working ``intent_context``. MUST."""
        ic = _sync_and_readback("ic-sync-set",
                                {"person": _entry("Bob", turns_remaining=3)})
        self.assertIn("person", ic)
        self.assertEqual(ic["person"]["value"], "Bob")

    @pytest.mark.xfail(strict=False,
                       reason="CONTEXT-1 §5.3 MUST apply the ovos.session.sync "
                              "intent_context payload entry-by-entry — a null "
                              "entry deletes while a co-present entry object "
                              f"sets; {_LEGACY_NOTE} and consumes no sync "
                              "payload, so neither the set nor the delete lands "
                              "in the orchestrator's working session.")
    def test_sync_null_deletes_entry(self):
        """§5.3: "a key present in the payload with a ``null`` entry removes that
        key from the working map" while a co-present entry object sets its key.
        A conformant merge of ``{kept: <entry>, gone: null}`` yields a working
        map with ``kept`` present and ``gone`` absent. MUST. (Asserting ``kept``
        is present is what distinguishes a real merge from the legacy no-op
        that leaves the map empty.)"""
        ic = _sync_and_readback("ic-sync-del",
                                {"kept": _entry("here", turns_remaining=3),
                                 "gone": None})
        self.assertIn("kept", ic)        # the entry-object set landed
        self.assertNotIn("gone", ic)     # the null delete removed the key


# §5.1 (Match.updated_session) and §5.2 (transformer in-place) are mutation
# pathways that require, respectively, a CONTEXT-1-aware pipeline plugin and a
# CONTEXT-1-aware transformer — neither exists in the installed stack, and both
# write through the same unimplemented session.intent_context the §5.3 tests
# already exercise end-to-end. Their orchestrator-visible effect is identical to
# §5.3's (an entry appears in the working map), so they are not separately
# bus-observable beyond TestSec53SessionSyncMerge.
# not bus-observable (beyond §5.3): §5.1, §5.2


# ─────────────────────────────────────────────────────────────────────────────
# §4 — Decay (orchestrator behaviour — unimplemented -> xfail)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec4Decay(TestCase):
    """§4: decay runs once per utterance dispatch — prune dead entries before
    the match round, decrement every live ``turns_remaining`` after it."""

    @pytest.mark.xfail(strict=False,
                       reason="CONTEXT-1 §4 MUST prune dead entries before the "
                              "match round and decrement turns_remaining after "
                              f"it; {_LEGACY_NOTE} (no per-utterance "
                              "intent_context prune/decrement tick).")
    def test_turns_remaining_decremented_after_round(self):
        """§4: "After the match round … decrement every live entry's
        ``turns_remaining`` by 1." An entry synced with ``turns_remaining: 2``
        reads back as ``1`` after one utterance. MUST."""
        # seed turns_remaining=2, run one utterance, expect 1 on read-back
        s = Session("ic-decay")
        s.lang = "en-US"
        s.pipeline = [PADACIOSO_HIGH]
        s.intent_context = {"person": _entry("Bob", turns_remaining=2)}
        recs = capture(_MC, utterance("zxqw blah blah", "ic-decay",
                                      [PADACIOSO_HIGH],
                                      intent_context=s.intent_context), 3.0)
        ic = {}
        for m in reversed(recs):
            if m.context.get("session"):
                ic = Session.deserialize(m.context["session"]).serialize().get(
                    "intent_context") or {}
                break
        self.assertEqual(ic.get("person", {}).get("turns_remaining"), 1)

    @pytest.mark.xfail(strict=False,
                       reason="CONTEXT-1 §4 MUST prune a dead (turns_remaining "
                              f"== 0) entry before the first matcher; {_LEGACY_NOTE}.")
    def test_dead_entry_pruned_before_match(self):
        """§4: "remove the entry if it is no longer live" — a
        ``turns_remaining: 0`` entry is dead on arrival and pruned before any
        matcher sees it. MUST."""
        recs = capture(_MC, utterance("zxqw blah blah", "ic-prune",
                                      [PADACIOSO_HIGH],
                                      intent_context={"person": _entry("Bob", turns_remaining=0)}),
                       3.0)
        ic = {}
        for m in reversed(recs):
            if m.context.get("session"):
                ic = Session.deserialize(m.context["session"]).serialize().get(
                    "intent_context") or {}
                break
        self.assertNotIn("person", ic)


# ─────────────────────────────────────────────────────────────────────────────
# §6 / §6.1 — Gating contracts (engine behaviour — unimplemented -> xfail)
# ─────────────────────────────────────────────────────────────────────────────

GATED_INTENT = "ctx.skill:gated"
GATED_SAMPLES = ["the secret phrase", "open sesame now", "do the gated thing"]


class TestSec6RequiresContext(TestCase):
    """§6: an engine MUST NOT report an intent as matched unless every
    ``requires_context`` key has a live entry, resolved per §3.1."""

    @pytest.mark.xfail(strict=False,
                       reason="CONTEXT-1 §6 MUST gate an intent declaring "
                              "requires_context on a live context entry; the "
                              "installed padacioso/adapt engines do not read "
                              "session.intent_context nor honour a "
                              "requires_context declaration (legacy adapt uses "
                              "its own context-entity matching), so the gate is "
                              "not enforced — the intent matches regardless.")
    def test_requires_context_blocks_without_entry(self):
        """§6: with no live entry at the gate key, an intent declaring
        ``requires_context`` MUST NOT match. MUST."""
        register_padatious_intent(_MC.bus, GATED_INTENT, GATED_SAMPLES)
        time.sleep(1)
        # no intent_context set -> the gate is unsatisfied -> MUST NOT dispatch
        recs = capture(_MC, utterance("the secret phrase", "ic-gate-block",
                                      [PADACIOSO_HIGH]), 3.0)
        self.assertNotIn(GATED_INTENT, types(recs))

    # The complementary "matches when the gate IS live" direction is deliberately
    # NOT asserted as a conformance test: on the non-conformant stack the intent
    # matches anyway (the gate is never consulted), so a "matches-when-live" test
    # passes for the wrong reason and could never reveal the divergence. The
    # falsifiable half of the §6 contract is the *suppression* asserted above.
    # not a conformance discriminator: §6 positive (match-when-live)


class TestSec61ExcludesContext(TestCase):
    """§6.1: an engine MUST NOT report an intent as matched if any
    ``excludes_context`` key is live in the session, resolved per §3.1."""

    @pytest.mark.xfail(strict=False,
                       reason="CONTEXT-1 §6.1 MUST suppress an intent declaring "
                              "excludes_context when the excluded key is live; "
                              "the installed engines do not honour "
                              "excludes_context against session.intent_context.")
    def test_excludes_context_blocks_when_entry_live(self):
        """§6.1: with the excluded key live in the session, the intent declaring
        ``excludes_context`` MUST NOT match (fire-once / modal-suppression
        pattern). MUST."""
        register_padatious_intent(_MC.bus, GATED_INTENT, GATED_SAMPLES)
        time.sleep(1)
        ic = {"ctx.skill:said_it": _entry(None, turns_remaining=5)}
        recs = capture(_MC, utterance("open sesame now", "ic-excl-block",
                                      [PADACIOSO_HIGH], intent_context=ic), 3.0)
        self.assertNotIn(GATED_INTENT, types(recs))


# §3.1 scope resolution (private vs shared key selection) is the resolution
# *internal* to the §6 / §6.1 gate checks above — it has no bus event of its
# own; its effect is observable only as a gate pass/fail, which the §6 / §6.1
# tests assert. A standalone scope-resolution test would re-assert the same
# unimplemented gating path.
# not bus-observable (beyond §6/§6.1): §3.1


# ─────────────────────────────────────────────────────────────────────────────
# §7 — Context-supplied slot fill (engine behaviour — unimplemented -> xfail)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec7ContextSuppliedSlot(TestCase):
    """§7: when a ``requires_context`` key also names a slot of the intent and
    the utterance did not fill it, the engine MUST populate ``Match.slots[key]``
    from the entry's non-null value (utterance-produced value wins)."""

    @pytest.mark.xfail(strict=False,
                       reason="CONTEXT-1 §7 MUST fill a match slot from a "
                              "context entry's value when a requires_context key "
                              "names an unfilled slot; the installed engines "
                              "implement no requires_context binding and no "
                              "context-supplied slot promotion, so the dispatch "
                              "carries no context-sourced slot.")
    def test_context_value_fills_unfilled_slot(self):
        """§7: a non-null context value for a ``requires_context`` key that also
        names a slot is promoted into ``Match.slots`` on the dispatch, keyed
        unprefixed. MUST."""
        register_padatious_intent(_MC.bus, GATED_INTENT,
                                  ["how tall is the person", "tell me about them"])
        time.sleep(1)
        ic = {"person": _entry("Bob", turns_remaining=3)}  # shared
        recs = capture(_MC, utterance("how tall is the person", "ic-slot",
                                      [PADACIOSO_HIGH], intent_context=ic), 3.0)
        msg = first(recs, GATED_INTENT)
        self.assertIsNotNone(msg, "gated intent did not dispatch")
        self.assertEqual(msg.data.get("person") or
                         (msg.data.get("slots") or {}).get("person"), "Bob")


# ─────────────────────────────────────────────────────────────────────────────
# §8 — Conformance: read-only carrier on ordinary messages (orchestrator)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec8ReadOnlyCarrier(TestCase):
    """§8: the orchestrator MUST treat ``session.intent_context`` on ordinary
    (non-``ovos.session.sync``) Messages as **read-only** — the carrier
    propagates the current snapshot; only the §5 pathways write it."""

    def test_ordinary_message_intent_context_carried_through(self):
        """§8: an ``intent_context`` carried on an ordinary utterance rides
        through to the echoed session unchanged (the orchestrator does not drop
        or rewrite it). MUST. (Conformant: ovos-core propagates the session
        carrier's ``intent_context`` field through to its responses untouched —
        the read-only carry-through the §8 conformance clause requires. Note it
        carries the snapshot but does not yet *act* on it; the decay/gating
        clauses above remain xfail.)"""
        ic = {"person": _entry("Bob")}  # no decay -> unchanged read-back
        recs = capture(_MC, utterance("zxqw blah blah", "ic-ro",
                                      [PADACIOSO_HIGH], intent_context=ic), 3.0)
        read = {}
        for m in reversed(recs):
            if m.context.get("session"):
                read = Session.deserialize(m.context["session"]).serialize().get(
                    "intent_context") or {}
                break
        self.assertEqual(read.get("person", {}).get("value"), "Bob")
