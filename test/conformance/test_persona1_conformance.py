"""OVOS-PERSONA-1 conformance suite.

Encodes the normative *Conformance* clauses (§12) and the message-shape rules of
OVOS-PERSONA-1 (``ovos/org/architecture/persona.md``) as ovoscope end-to-end
assertions against the integrated OVOS stack: ovos-core's orchestrator driving
the ``ovos-persona-pipeline-plugin`` (a ConfidenceMatcherPipeline loaded as the
``-high``/``-low`` stages). A throwaway ``Alice`` persona backed by the always-on
``ovos-solver-failure-plugin`` is injected via ``pipeline_config`` so the match
-> dispatch -> speak flow runs without a network solver.

Each test class maps to one spec section; each method docstring quotes the
MUST/SHOULD clause and its level. Drivers and the xfail discipline are described
in ``_conformance.py``. Topic literals are used throughout — OVOS-PERSONA-1
defines its bus surface (§11) as literal strings and ``SpecMessage`` carries no
persona members.

Coverage map (clause -> status against the pinned stack):
- §4   no-persona mode: stage returns None on a neutral utterance ... green
- §7.1 unset persona_id -> None (no-persona mode) ................... green
- §7.1 route 1 summon command is detected and claimed .............. green
- §7.1 route 1 release command is detected and claimed ............. xfail (active persona is session-resident #185; not carried across turns)
- §7.1 route 1 check (active persona) command is claimed ........... green
- §7.1 route 1 one-off `ask` query is claimed and answered ......... green
- §5   summon dispatch is answered (confirmation spoken) ........... green
- §7.2 active persona claims a neutral (non-command) utterance ..... green
- §7.4 Match.lang is the resolved language of the match ............ green
- §8.1 handler speaks the response on `ovos.utterance.speak` ....... green
- §3/§5 summon sets `session.persona_id` via updated_session ....... xfail (in-memory active_personas dict; persona_id never set on session)
- §6   release clears `session.persona_id` ......................... xfail (clears in-memory dict; persona_id never touched on session)
- §7.1 unsupported persona_id -> None .............................. xfail (still claims via persona:query / fallback)
- §11  summon broadcasts `ovos.persona.activated` .................. xfail (emits 'persona.openvoiceos.activate')
- §11  dismiss broadcasts `ovos.persona.dismissed` ................. xfail (no dismiss broadcast)
- §8.5 out-of-band `ovos.persona.query` -> `ovos.persona.answer` ... xfail (MAY; not implemented — no answer)
- §8.7 `ovos.persona.list` -> `ovos.persona.list.response` ......... xfail (SHOULD; not implemented — no response)
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

from ovoscope import get_minicroft

from ._conformance import (
    capture,
    first,
    reset_namespace,
    types,
    use_spec_namespace,
    utterance,
)

# Normative clauses that are not bus-observable from the integrated stack and so
# are not asserted here:
# not bus-observable: §7.3 latency discipline (return Match fast, defer generation)
#   — internal timing, no distinct bus surface.
# not bus-observable: §8.4 conversation history keyed on session_id — plugin-internal
#   (MAY-internal) storage.
# not bus-observable: §8.6 stop awareness during generation — the failure solver
#   answers instantly, so there is no long-running generation to interrupt.
# not bus-observable: §2/§9 persona internals (black-box agent, capability tags,
#   multi-plugin coexistence) — no observable bus contract beyond the topics above.

PERSONA_HIGH = "ovos-persona-pipeline-plugin-high"
PERSONA_LOW = "ovos-persona-pipeline-plugin-low"
PERSONA_PLUGIN = "ovos-persona-pipeline-plugin"
PERSONA_SKILL_ID = "persona.openvoiceos"
PIPELINE = [PERSONA_HIGH, PERSONA_LOW]

# The injected test persona identity.
ALICE = "Alice"

# A persona definition driven by the always-on failure solver: it answers every
# query with a fixed string, so the match -> dispatch -> speak flow completes
# with no network or model. Written under a temp personas_path passed to the
# plugin via pipeline_config in setUpModule.
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402

_PERSONAS_DIR = tempfile.mkdtemp(prefix="persona-conf-")
with open(os.path.join(_PERSONAS_DIR, f"{ALICE}.json"), "w") as _f:
    json.dump({"name": ALICE,
               "solvers": ["ovos-solver-failure-plugin"]}, _f)

# A neutral utterance that does NOT trip the summon/ask/list/check intent
# matchers, so it exercises the active-persona catch-all (route 2) rather than
# route 1.
NEUTRAL = "the sky is blue today"

_MC = None


def setUpModule():
    global _MC
    LOG.set_level("ERROR")
    use_spec_namespace()
    try:
        _MC = get_minicroft(
            [],
            pipeline_config={"persona": {"personas_path": _PERSONAS_DIR,
                                         "handle_fallback": True}},
        )
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


def _persona_dispatch_types(recs):
    return [t for t in types(recs)
            if t.startswith("persona:") or t.startswith("ovos.persona")
            or t in ("ovos.utterance.speak", "ovos.utterance.handled")]


# ─────────────────────────────────────────────────────────────────────────────
# §3 — The `persona_id` session field
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3PersonaIdField(TestCase):
    """§3: ``persona_id`` is the session-resident field that identifies the active
    persona. When set, persona stages whose identities include it MUST claim
    (§7.1 route 2); summon MUST set it via ``Match.updated_session`` (§5)."""

    def test_active_persona_id_is_claimed(self):
        """§3/§7.1 route 2 MUST: when ``session.persona_id`` is set to a supported
        value, the persona stage claims the utterance (dispatches ``persona:*``)."""
        recs = capture(_MC, utterance(NEUTRAL, "p-active", PIPELINE,
                                      persona_id=ALICE), 6.0)
        self.assertIn("persona:query", types(recs))

    def test_summon_sets_session_persona_id(self):
        """§5/§3 MUST: a summon sets ``session.persona_id`` via
        ``Match.updated_session`` — observable on the dispatch's carried session."""
        recs = capture(_MC, utterance("summon Alice", "p-summon-sets", PIPELINE), 5.0)
        d = first(recs, "persona:summon")
        self.assertIsNotNone(d, "summon was not matched")
        sess = d.context.get("session") or {}
        self.assertEqual(sess.get("persona_id"), ALICE)


# ─────────────────────────────────────────────────────────────────────────────
# §4 / §7.1 — No-persona mode
# ─────────────────────────────────────────────────────────────────────────────

class TestSec4NoPersonaMode(TestCase):
    """§4/§7.1: with no persona active (``persona_id`` absent) the persona stage
    MUST decline every utterance that is not an embedded persona command —
    ``match`` returns ``None`` and only the deterministic pipeline runs."""

    def test_no_persona_declines_neutral(self):
        """§4/§7.1 MUST: a neutral utterance with no active persona is declined by
        the persona stage — no ``persona:*`` dispatch fires (only the end-marker
        terminates the utterance)."""
        recs = capture(_MC, utterance(NEUTRAL, "p-none", [PERSONA_HIGH]), 4.0)
        self.assertFalse(any(t.startswith("persona:") for t in types(recs)),
                         f"persona stage claimed in no-persona mode: {types(recs)}")
        self.assertIn("ovos.utterance.handled", types(recs))

    @pytest.mark.xfail(strict=True,
                       reason="PERSONA-1 §7.1 MUST return None when session.persona_id "
                              "is set to an UNSUPPORTED value; the plugin still claims "
                              "(persona:query / fallback) instead of declining")
    def test_unsupported_persona_id_declines(self):
        """§7.1 MUST: when ``session.persona_id`` is a value the plugin does not
        support, ``match`` returns ``None`` (let another stage handle it) — no
        ``persona:*`` dispatch fires."""
        recs = capture(_MC, utterance(NEUTRAL, "p-unsup", PIPELINE,
                                      persona_id="no-such-persona-xyz"), 5.0)
        self.assertFalse(any(t.startswith("persona:") for t in types(recs)),
                         f"persona stage claimed an unsupported persona_id: {types(recs)}")


# ─────────────────────────────────────────────────────────────────────────────
# §5 / §7.1 route 1 — Summon (embedded persona command)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec5Summon(TestCase):
    """§5/§7.1 route 1: the plugin detects a summon utterance during ``match``,
    claims it (emitting a confirmation response), and activates the persona for
    subsequent utterances."""

    def test_summon_is_claimed(self):
        """§5/§7.1 route 1 MUST: a summon command is detected and claimed — the
        plugin dispatches its summon handler."""
        recs = capture(_MC, utterance("summon Alice", "p-summon", PIPELINE), 5.0)
        self.assertIn("persona:summon", types(recs))

    def test_summon_speaks_confirmation(self):
        """§5/§8.1: the summon handler emits a confirmation on
        ``ovos.utterance.speak``."""
        recs = capture(_MC, utterance("summon Alice", "p-summon-speak", PIPELINE), 5.0)
        self.assertIn("ovos.utterance.speak", types(recs))

    @pytest.mark.xfail(strict=True,
                       reason="PERSONA-1 §11 advisory: a persona that becomes active "
                              "SHOULD broadcast 'ovos.persona.activated'; the plugin "
                              "emits 'persona.openvoiceos.activate' instead")
    def test_summon_broadcasts_activated(self):
        """§11: activation is announced (best-effort) on ``ovos.persona.activated``."""
        recs = capture(_MC, utterance("summon Alice", "p-summon-act", PIPELINE), 5.0)
        self.assertIn("ovos.persona.activated", types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §6 — Dismiss (release)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec6Dismiss(TestCase):
    """§6/§7.1 route 1: the plugin detects a release intent during ``match``,
    claims it, and returns the session to no-persona mode by clearing
    ``persona_id``."""

    def _summon_then(self, session_id, release_utt):
        _MC.bus.emit(utterance("summon Alice", session_id, PIPELINE))
        time.sleep(1.5)
        return capture(_MC, utterance(release_utt, session_id, PIPELINE), 5.0)

    @pytest.mark.xfail(strict=True,
                       reason="PERSONA-1 §6/§7.1 route 1 MUST claim a release while a "
                              "persona is active. ovos-persona @dev made the active persona "
                              "session-resident via session.persona_id (#185): the release "
                              "matcher gates on `active_persona`, which is now read from the "
                              "inbound session rather than an in-process active_personas dict. "
                              "Because this harness summons and releases in separate turns and "
                              "the stateless `utterance()` helper does not carry the summon's "
                              "Match.updated_session (persona_id) into the next turn, the "
                              "release utterance arrives with no active persona and is not "
                              "claimed (ovos.intent.unmatched).")
    def test_release_is_claimed(self):
        """§6/§7.1 route 1 MUST: a release command (while a persona is active) is
        detected and claimed — the plugin dispatches its release handler."""
        recs = self._summon_then("p-release", "stop talking to alice")
        self.assertIn("persona:release", types(recs))

    @pytest.mark.xfail(strict=True,
                       reason="PERSONA-1 §6 MUST clear session.persona_id on dismiss via "
                              "Match.updated_session; the plugin clears its in-memory "
                              "active_personas dict and leaves the session's persona_id "
                              "(here pre-set to Alice) untouched")
    def test_release_clears_session_persona_id(self):
        """§6 MUST: dismiss clears ``persona_id`` from the session via
        ``Match.updated_session``. Drive it with ``persona_id`` already set on the
        inbound session, so a conformant release MUST clear it — the divergence is
        that the field passes through unchanged."""
        _MC.bus.emit(utterance("summon Alice", "p-release-clear", PIPELINE))
        time.sleep(1.5)
        recs = capture(_MC, utterance("stop talking to alice", "p-release-clear",
                                      PIPELINE, persona_id=ALICE), 5.0)
        d = first(recs, "persona:release")
        self.assertIsNotNone(d, "release was not matched")
        sess = d.context.get("session") or {}
        self.assertIn(sess.get("persona_id"), (None, ""),
                      "release did not clear a pre-set session.persona_id")


# ─────────────────────────────────────────────────────────────────────────────
# §7 — Match contract (embedded commands + active catch-all)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec7MatchContract(TestCase):
    """§7.1 route 1 / §7.2: embedded persona commands (ask, list, check) are
    evaluated before the active-persona catch-all; an active persona then claims
    every utterance that reaches it (§7.2)."""

    def test_oneoff_ask_is_claimed_and_answered(self):
        """§5/§7.1 route 1 MUST: a one-off ``ask`` query is claimed (``persona:query``)
        and answered via the handler, without requiring an active persona."""
        recs = capture(_MC, utterance("ask Alice what is the time", "p-ask",
                                      PIPELINE), 6.0)
        seq = types(recs)
        self.assertIn("persona:query", seq)
        self.assertIn("ovos.utterance.speak", seq)

    def test_check_active_is_claimed(self):
        """§7.1 route 1: a check ("which persona is active") command claims the
        utterance for an introspection response."""
        recs = capture(_MC, utterance("which persona is active", "p-check",
                                      PIPELINE), 5.0)
        self.assertIn("persona:check", types(recs))

    def test_list_personas_is_claimed(self):
        """§7.1 route 1: a list-personas command claims the utterance for an
        introspection response."""
        recs = capture(_MC, utterance("list personas", "p-list", PIPELINE), 5.0)
        self.assertIn("persona:list", types(recs))

    def test_active_persona_claims_neutral_utterance(self):
        """§7.2 MUST: when a persona is active (``persona_id`` supported), the plugin
        claims every utterance that reaches it — including a neutral, non-command
        utterance (the defining behaviour of an active persona)."""
        recs = capture(_MC, utterance(NEUTRAL, "p-catchall", PIPELINE,
                                      persona_id=ALICE), 6.0)
        self.assertIn("persona:query", types(recs))

    def test_match_lang_is_resolved(self):
        """§7.4 MUST: ``Match.lang`` is the resolved BCP-47 language of the match —
        forwarded on the dispatch payload."""
        recs = capture(_MC, utterance(NEUTRAL, "p-lang", PIPELINE,
                                      persona_id=ALICE, lang="en-US"), 6.0)
        d = first(recs, "persona:query")
        self.assertIsNotNone(d, "active persona did not claim")
        self.assertEqual(d.data.get("lang"), "en-US")


# ─────────────────────────────────────────────────────────────────────────────
# §8 — Handler contract
# ─────────────────────────────────────────────────────────────────────────────

class TestSec8Handler(TestCase):
    """§8.1: the persona handler generates a natural-language response and emits it
    via ``ovos.utterance.speak``; the utterance terminates with one end-marker."""

    def test_handler_speaks_response(self):
        """§8.1 MUST: the handler emits its response on ``ovos.utterance.speak``."""
        recs = capture(_MC, utterance(NEUTRAL, "p-speak", PIPELINE,
                                      persona_id=ALICE), 6.0)
        self.assertIn("ovos.utterance.speak", types(recs))

    def test_handler_terminates_once(self):
        """§8.1/PIPELINE-1 §9.5: a persona-handled utterance terminates with
        exactly one ``ovos.utterance.handled`` end-marker."""
        recs = capture(_MC, utterance(NEUTRAL, "p-speak-eof", PIPELINE,
                                      persona_id=ALICE), 6.0)
        self.assertEqual(types(recs).count("ovos.utterance.handled"), 1)

    @pytest.mark.xfail(strict=True,
                       reason="PERSONA-1 §8.5 MAY out-of-band query: when implemented "
                              "the plugin MUST answer 'ovos.persona.query' on "
                              "'ovos.persona.answer'; the pinned plugin does not "
                              "implement the out-of-band interface (no answer emitted)")
    def test_out_of_band_query_answers(self):
        """§8.5: an out-of-band ``ovos.persona.query`` is answered on
        ``ovos.persona.answer`` (request/response, bypassing the pipeline)."""
        recs = capture(_MC, Message("ovos.persona.query",
                                    {"persona_id": ALICE, "utterance": "hi"},
                                    {}), 4.0)
        self.assertIn("ovos.persona.answer", types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §8.7 / §11 — Persona discovery
# ─────────────────────────────────────────────────────────────────────────────

class TestSec87Discovery(TestCase):
    """§8.7/§11: a persona plugin SHOULD respond to ``ovos.persona.list`` with the
    ``persona_id`` values it supports on ``ovos.persona.list.response``."""

    @pytest.mark.xfail(strict=True,
                       reason="PERSONA-1 §8.7/§11 SHOULD respond to 'ovos.persona.list' "
                              "on 'ovos.persona.list.response'; the pinned plugin does "
                              "not implement the discovery interface (no response)")
    def test_persona_list_responds(self):
        """§8.7 SHOULD: ``ovos.persona.list`` is answered on
        ``ovos.persona.list.response`` enumerating supported identities."""
        recs = capture(_MC, Message("ovos.persona.list", {}, {}), 3.0)
        self.assertIn("ovos.persona.list.response", types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §11 — Best-effort dismiss broadcast
# ─────────────────────────────────────────────────────────────────────────────

class TestSec11DismissBroadcast(TestCase):
    """§11: a persona dismissed from a session SHOULD broadcast
    ``ovos.persona.dismissed`` (best-effort; consumers MUST NOT rely on it)."""

    @pytest.mark.xfail(strict=True,
                       reason="PERSONA-1 §11 advisory: dismiss SHOULD broadcast "
                              "'ovos.persona.dismissed'; the pinned plugin emits no "
                              "dismiss broadcast")
    def test_dismiss_broadcasts(self):
        """§11: a release broadcasts ``ovos.persona.dismissed`` (best-effort)."""
        _MC.bus.emit(utterance("summon Alice", "p-dismiss-bc", PIPELINE))
        time.sleep(1.5)
        recs = capture(_MC, utterance("stop talking to alice", "p-dismiss-bc",
                                      PIPELINE), 5.0)
        self.assertIn("ovos.persona.dismissed", types(recs))
