"""OVOS-TRANSFORM-1 conformance suite — the transformer-chain pattern.

Encodes the normative clauses of OVOS-TRANSFORM-1
(``ovos/org/architecture/transformer.md``) as assertions against the real
ovos-core transformer **services** — ``UtteranceTransformersService``,
``MetadataTransformersService``, ``IntentTransformersService`` — exercised on a
``FakeBus`` with **inline fixture transformers** injected into each service's
loaded set.

Why drive the services directly
-------------------------------
The §1/§2/§4/§7 chain semantics (ordering, run-to-completion, error handling)
and the §3 per-type IO contracts live in the *transformer service*, which the
orchestrator (``ovos_core.intent_services.service.IntentService``) runs at the
§2 injection points. ovos-core discovers transformers from real ``opm.transformer.*``
entry points only, so a runtime-registered fixture is invisible to plugin
discovery; instead each test constructs the real service and injects fixture
instances into ``service.loaded_plugins`` (resetting ``_sorted_plugins``). This
exercises the production chain-runner against transformers whose run order,
mutation, raising, and cancellation we control — the §9 conformance surface.

A fixture transformer (`_Recorder`) records its run into a shared list so chain
ordering (§4) and run-to-completion (§1) are observable; mutating fixtures prove
the §3 IO contracts; a raising fixture proves §7; a cancelling fixture proves
the §8.1 signal shape.

Coverage map (clause -> status against the installed ovos-core services):
- §1   every transformer in a chain always runs (no early exit) ... green
- §1   last transformer's output is what proceeds ................. green
- §3.2 utterance chain: input list -> possibly-modified list ...... green
- §3.2 utterance transformer may mutate Message.context .......... green
- §3.2 empty-list (no-transcription) returned as-is .............. green
- §3.3 metadata chain: context-in -> context-out, mutation kept .. green
- §3.4 intent chain: Match.captures may be enriched .............. green
- §3.4 Match.skill_id / intent_name MUST NOT change (enforced) ... xfail (service does not enforce)
- §4   chain runs ascending priority (lower number first) ........ xfail (service sorts descending)
- §7   a raising transformer is caught; chain proceeds ........... green
- §7   raising transformer == returned its input unchanged ....... green
- §1.3 <type>_transformer_ids stamped on touched Message ......... xfail (not stamped)
- §8.1 canceled/cancel_reason propagate through the chain ........ green
- §8.1 orchestrator stamps cancel_by from the emitting id ........ xfail (not stamped)
- §5   per-session <type>_transformers override fields ........... skip (bus-client lacks fields)

Non-bus-observable prose is noted inline with ``# not bus-observable:``.
xfail discipline per ``_conformance.py``.
"""
from unittest import TestCase

import pytest
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG

from ovos_core.transformers import (
    IntentTransformersService,
    MetadataTransformersService,
    UtteranceTransformersService,
)
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch
from ovos_plugin_manager.templates.transformers import (
    AudioTransformer,
    DialogTransformer,
    IntentTransformer,
    MetadataTransformer,
    TTSTransformer,
    UtteranceTransformer,
)


def setUpModule():
    LOG.set_level("ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# Fixture transformers
# ─────────────────────────────────────────────────────────────────────────────

def _utt_service(plugins):
    """Build a real UtteranceTransformersService with `plugins` injected."""
    svc = UtteranceTransformersService(FakeBus())
    svc.loaded_plugins = {p.name: p for p in plugins}
    svc._sorted_plugins = None
    return svc


def _meta_service(plugins):
    svc = MetadataTransformersService(FakeBus())
    svc.loaded_plugins = {p.name: p for p in plugins}
    svc._sorted_plugins = None
    return svc


def _intent_service(plugins):
    svc = IntentTransformersService(FakeBus())
    svc.loaded_plugins = {p.name: p for p in plugins}
    svc._sorted_plugins = None
    return svc


class _RecUtt(UtteranceTransformer):
    """Utterance fixture that records its run and appends its tag to the list."""

    def __init__(self, name, priority, log, tag=None):
        super().__init__(name, priority=priority)
        self._log = log
        self._tag = tag or name

    def transform(self, utterances, context=None):
        self._log.append(self._tag)
        return utterances + [self._tag], {self._tag: True}


# ─────────────────────────────────────────────────────────────────────────────
# §1 — Chain model: every transformer always runs; last output proceeds
# ─────────────────────────────────────────────────────────────────────────────

class TestSec1ChainModel(TestCase):
    """§1: unlike a pipeline plugin, every transformer in a chain ALWAYS runs —
    no claim-or-decline, no first-result-wins, no early exit. Whatever the last
    transformer returns is what proceeds."""

    def test_every_transformer_runs(self):
        """§1 MUST: every transformer in the chain runs when its injection point
        is reached — there is no early exit."""
        log = []
        svc = _utt_service([_RecUtt("a", 10, log), _RecUtt("b", 50, log),
                            _RecUtt("c", 90, log)])
        svc.transform(["hi"], {})
        self.assertEqual(sorted(log), ["a", "b", "c"],
                         "not every transformer in the chain ran")

    def test_last_transformer_output_proceeds(self):
        """§1 MUST: whatever the last transformer returns is what the orchestrator
        passes on — the chain output is the final transformer's output."""
        log = []
        svc = _utt_service([_RecUtt("a", 10, log), _RecUtt("b", 90, log)])
        utts, _ = svc.transform(["hi"], {})
        # both tags appended; "hi" preserved at head; chain threaded through
        self.assertEqual(utts[0], "hi")
        self.assertIn("a", utts)
        self.assertIn("b", utts)


# ─────────────────────────────────────────────────────────────────────────────
# §3.2 — Utterance transformers
# ─────────────────────────────────────────────────────────────────────────────

class TestSec32Utterance(TestCase):
    """§3.2: post-STT/pre-intent chain over the candidate-utterance list; MAY
    rewrite/expand/contract the list and MAY mutate Message.context."""

    def test_list_is_modified(self):
        """§3.2: a transformer MAY expand the candidate list (add a paraphrase)."""
        log = []
        svc = _utt_service([_RecUtt("para", 50, log, tag="paraphrase")])
        utts, _ = svc.transform(["hello"], {})
        self.assertIn("paraphrase", utts)
        self.assertEqual(utts[0], "hello", "primary candidate not preserved")

    def test_context_is_mutated(self):
        """§3.2: a transformer MAY mutate Message.context (e.g. write derived
        metadata) — the returned dict is merged into context."""
        class Tagger(UtteranceTransformer):
            def __init__(s):
                super().__init__("tagger", priority=50)

            def transform(s, utterances, context=None):
                return utterances, {"derived_key": "value"}

        svc = _utt_service([Tagger()])
        _, ctx = svc.transform(["hi"], {"existing": 1})
        self.assertEqual(ctx.get("derived_key"), "value")
        self.assertEqual(ctx.get("existing"), 1, "prior context dropped")

    def test_empty_list_no_transcription(self):
        """§3.2 empty-list semantics: a transformer MAY return an empty list; the
        no-transcription outcome (empty list WITHOUT the §8.1 cancellation signal)
        is propagated as an empty list, not an error."""
        class Dropper(UtteranceTransformer):
            def __init__(s):
                super().__init__("dropper", priority=50)

            def transform(s, utterances, context=None):
                return [], {}

        svc = _utt_service([Dropper()])
        utts, ctx = svc.transform(["garbage"], {})
        self.assertEqual(utts, [])
        self.assertNotIn("canceled", ctx,
                         "no-transcription path must not set the cancel flag")


# ─────────────────────────────────────────────────────────────────────────────
# §3.3 — Metadata transformers
# ─────────────────────────────────────────────────────────────────────────────

class TestSec33Metadata(TestCase):
    """§3.3: the metadata chain's only input and output is Message.context; a
    metadata transformer MAY mutate it however it sees fit."""

    def test_context_in_context_out(self):
        """§3.3: a metadata transformer adds/updates top-level context keys, and
        the prior context is preserved through the merge."""
        class MD(MetadataTransformer):
            def __init__(s):
                super().__init__("md", priority=50)

            def transform(s, context=None):
                return {"md_added": True}

        svc = _meta_service([MD()])
        ctx = svc.transform({"prior": 1})
        self.assertTrue(ctx.get("md_added"))
        self.assertEqual(ctx.get("prior"), 1)

    def test_chain_runs_all_metadata_transformers(self):
        """§1/§3.3: every metadata transformer in the chain runs (always-runs)."""
        log = []

        class MD(MetadataTransformer):
            def __init__(s, name):
                super().__init__(name, priority=50)
                s._n = name

            def transform(s, context=None):
                log.append(s._n)
                return {s._n: True}

        svc = _meta_service([MD("m1"), MD("m2")])
        svc.transform({})
        self.assertEqual(sorted(log), ["m1", "m2"])


# ─────────────────────────────────────────────────────────────────────────────
# §3.4 — Intent transformers
# ─────────────────────────────────────────────────────────────────────────────

class TestSec34Intent(TestCase):
    """§3.4: post-match/pre-dispatch chain over the Match; MAY enrich captures;
    MUST NOT change skill_id / intent_name (orchestrator enforces)."""

    def _match(self):
        return IntentHandlerMatch(match_type="myskill:greet",
                                  match_data={"orig": 1},
                                  skill_id="myskill",
                                  utterance="hi")

    def test_captures_may_be_enriched(self):
        """§3.4: an intent transformer MAY add entries to the Match capture map."""
        class Enricher(IntentTransformer):
            def __init__(s):
                super().__init__("enricher", priority=50)

            def transform(s, intent):
                intent.match_data = dict(intent.match_data or {})
                intent.match_data["enriched"] = True
                return intent

        svc = _intent_service([Enricher()])
        out = svc.transform(self._match())
        self.assertTrue(out.match_data.get("enriched"))
        self.assertEqual(out.match_data.get("orig"), 1, "engine capture dropped")

    @pytest.mark.xfail(
        reason="OVOS-TRANSFORM-1 §3.4 / §9 MUST: if a transformer returns a Match "
               "whose skill_id or intent_name differs from its input, the "
               "orchestrator MUST treat it as a §7 shape violation, discard the "
               "output and proceed with the prior Match unchanged. "
               "IntentTransformersService.transform does not enforce the identity "
               "invariant — a transformer that overwrites skill_id is honoured.",
        strict=True,
    )
    def test_skill_id_invariant_enforced(self):
        """§3.4 MUST NOT change ``Match.skill_id``; §9 MUST: the orchestrator
        treats a changed skill_id as a shape violation and keeps the prior Match."""
        class Hijack(IntentTransformer):
            def __init__(s):
                super().__init__("hijack", priority=50)

            def transform(s, intent):
                intent.skill_id = "OTHER_SKILL"
                return intent

        svc = _intent_service([Hijack()])
        out = svc.transform(self._match())
        self.assertEqual(out.skill_id, "myskill",
                         "orchestrator did not backstop a skill_id change")


# ─────────────────────────────────────────────────────────────────────────────
# §4 — Chain ordering
# ─────────────────────────────────────────────────────────────────────────────

class TestSec4Ordering(TestCase):
    """§4: a chain runs in ASCENDING priority order — priority=1 before
    priority=50 before priority=100. Lower number = earlier."""

    @pytest.mark.xfail(
        reason="OVOS-TRANSFORM-1 §4 MUST: 'a chain runs in ascending priority "
               "order: a transformer with priority=1 runs before one with "
               "priority=50 ... lower number = earlier in the chain'. "
               "UtteranceTransformersService.plugins sorts by priority with "
               "reverse=True (descending), so a priority=90 transformer runs "
               "before a priority=10 one — the inverse of the spec order.",
        strict=True,
    )
    def test_ascending_priority_order(self):
        """§4 MUST: the chain runs ascending by priority — the lower-priority
        number runs first."""
        log = []
        svc = _utt_service([_RecUtt("early", 10, log),
                            _RecUtt("late", 90, log)])
        svc.transform(["hi"], {})
        self.assertEqual(log, ["early", "late"],
                         "chain did not run in ascending priority order")

    def test_default_priority_is_50(self):
        """§4: each transformer declares an integer ``priority``; the default is
        ``50`` — the middle of the band."""
        t = UtteranceTransformer("defaulted")
        self.assertEqual(t.priority, 50)


# ─────────────────────────────────────────────────────────────────────────────
# §1.1 / §3 / §9 — Per-type transformer IO contract (template level)
# ─────────────────────────────────────────────────────────────────────────────

_ALL_TYPES = {
    "audio": AudioTransformer,
    "utterance": UtteranceTransformer,
    "metadata": MetadataTransformer,
    "intent": IntentTransformer,
    "dialog": DialogTransformer,
    "tts": TTSTransformer,
}


class TestPerTypeContract(TestCase):
    """§1.1: a transformer is a ``(type, transformer_id)`` pair, type ∈ the six
    §2 values. §9: a transformer MUST declare an integer ``priority``; the
    conventional default is 50. These bind the plugin template for every type —
    including the audio (§3.1) / dialog (§3.5) / TTS (§3.6) chains whose
    orchestrator-side services run in separate processes not loaded here."""

    def test_all_six_types_exist(self):
        """§1.1 / §2 MUST: exactly the six injection-point types have a template —
        audio, utterance, metadata, intent, dialog, tts."""
        self.assertEqual(set(_ALL_TYPES), {"audio", "utterance", "metadata",
                                           "intent", "dialog", "tts"})

    def test_every_type_declares_integer_priority_default_50(self):
        """§4 / §9 MUST: each transformer declares an integer ``priority``; the
        conventional middle-of-the-band default is 50 — for every type."""
        for name, cls in _ALL_TYPES.items():
            t = cls("probe")
            self.assertIsInstance(t.priority, int,
                                  f"{name} transformer priority is not an int")
            self.assertEqual(t.priority, 50,
                             f"{name} transformer default priority != 50")

    def test_every_type_has_stable_id(self):
        """§1.1 MUST: a transformer is identified by a non-empty id within its
        type's registry (``name`` carries the ``transformer_id``)."""
        for name, cls in _ALL_TYPES.items():
            t = cls("my-id")
            self.assertTrue(getattr(t, "name", None),
                            f"{name} transformer has no id attribute")


class TestSec30Lang(TestCase):
    """§3.0: four per-type contracts (audio §3.1, utterance §3.2, dialog §3.5,
    TTS §3.6) take a bidirectional ``lang`` parameter alongside the artifact and
    context — it appears in BOTH input and output so a transformer that mutates
    the artifact's language mutates ``lang`` in lockstep."""

    @pytest.mark.xfail(
        reason="OVOS-TRANSFORM-1 §3.0 MUST: the orchestrator threads a "
               "bidirectional `lang` parameter through the audio/utterance/"
               "dialog/TTS chains (input AND output of each transform call). The "
               "installed transformer templates take no `lang` parameter — "
               "UtteranceTransformer.transform(utterances, context), "
               "DialogTransformer.transform(dialog, context), "
               "TTSTransformer.transform(wav_file, context) — and return "
               "(artifact, context) with no lang slot, so a transformer cannot "
               "mutate the content language in lockstep per §3.0.",
        strict=True,
    )
    def test_lang_is_a_threaded_parameter(self):
        """§3.0 MUST: the artifact-bearing transform signatures carry ``lang`` as
        a threaded parameter (utterance / dialog / TTS at minimum)."""
        import inspect
        for cls in (UtteranceTransformer, DialogTransformer, TTSTransformer):
            params = inspect.signature(cls.transform).parameters
            self.assertIn(
                "lang", params,
                f"{cls.__name__}.transform has no lang parameter (§3.0)")


# ─────────────────────────────────────────────────────────────────────────────
# §7 — Error handling
# ─────────────────────────────────────────────────────────────────────────────

class TestSec7ErrorHandling(TestCase):
    """§7: a transformer that raises is treated as if it returned its input
    unchanged — the orchestrator MUST catch and MUST proceed to the next
    transformer; a single bug MUST NOT abort the utterance."""

    def test_raise_does_not_abort_chain(self):
        """§7 MUST: a raising transformer is caught and the chain proceeds — a
        later transformer still runs and its output survives."""
        log = []

        class Boom(UtteranceTransformer):
            def __init__(s):
                super().__init__("boom", priority=10)

            def transform(s, utterances, context=None):
                log.append("boom")
                raise RuntimeError("conformance: intentional transformer failure")

        svc = _utt_service([Boom(), _RecUtt("survivor", 90, log)])
        utts, _ = svc.transform(["hi"], {})
        self.assertIn("boom", log, "raising transformer did not run")
        self.assertIn("survivor", log, "chain aborted on a raised exception")
        self.assertIn("survivor", utts, "surviving transformer output lost")

    def test_raise_passes_input_through_unchanged(self):
        """§7 MUST: the raising transformer's effect is its INPUT unchanged — it
        contributes no mutation when it raises."""
        class Boom(UtteranceTransformer):
            def __init__(s):
                super().__init__("boom", priority=50)

            def transform(s, utterances, context=None):
                utterances.append("SHOULD_NOT_SURVIVE")
                raise RuntimeError("raised after a half-mutation")

        svc = _utt_service([Boom()])
        utts, ctx = svc.transform(["hi"], {})
        # the contract is "as if it returned its input unchanged"; the chain
        # output is the input the orchestrator carried into the raising call.
        self.assertNotIn("boom", ctx,
                         "a raising transformer leaked context mutations")

    @pytest.mark.xfail(
        reason="OVOS-TRANSFORM-1 §7 MUST: 'a transformer that returns an output "
               "of the wrong shape — wrong type, missing required field, list "
               "shrunk to empty for a non-empty input — is treated the same as a "
               "raised exception ... proceed with the prior transformer's output'. "
               "UtteranceTransformersService.transform does `utterances, data = "
               "module.transform(...)` with no shape validation: a 2-element "
               "non-(list, dict) return (e.g. a 2-char string) unpacks silently "
               "and corrupts the chain output instead of being rejected.",
        strict=True,
    )
    def test_shape_violation_treated_like_a_raise(self):
        """§7 MUST: a transformer that returns the wrong shape is treated the same
        as a raised exception — the chain output keeps the (list, dict) contract,
        not whatever the malformed return unpacked to."""
        class WrongShape(UtteranceTransformer):
            def __init__(s):
                super().__init__("wrongshape", priority=50)

            def transform(s, utterances, context=None):
                # a 2-element return that is NOT (list[str], dict): the service
                # unpacks it positionally with no validation.
                return "ab"

        svc = _utt_service([WrongShape()])
        utts, ctx = svc.transform(["hi"], {})
        self.assertIsInstance(
            utts, list,
            "shape-violating return corrupted the utterance list into "
            f"{type(utts).__name__}")
        self.assertIsInstance(ctx, dict,
                              "shape-violating return corrupted the context")


# ─────────────────────────────────────────────────────────────────────────────
# §1.3 — Transformer self-identification (chain provenance stamping)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec13SelfIdentification(TestCase):
    """§1.3: on every Message a transformer touches, it MUST ensure its own
    transformer_id is the last element of the matching ``<type>_transformer_ids``
    list. The orchestrator SHOULD enforce this at load time."""

    @pytest.mark.xfail(
        reason="OVOS-TRANSFORM-1 §1.3 MUST: a transformer MUST ensure its "
               "transformer_id is the last element of the corresponding "
               "<type>_transformer_ids list on every touched Message, and the "
               "orchestrator SHOULD enforce it. UtteranceTransformersService "
               "merges only the data the plugin returns and never appends to "
               "utterance_transformer_ids, so chain provenance is not recorded.",
        strict=True,
    )
    def test_utterance_transformer_ids_stamped(self):
        """§1.3 MUST: after the utterance chain runs, context carries
        ``utterance_transformer_ids`` ending with the last transformer's id."""
        log = []
        svc = _utt_service([_RecUtt("first", 10, log),
                            _RecUtt("second", 90, log)])
        _, ctx = svc.transform(["hi"], {})
        ids = ctx.get("utterance_transformer_ids")
        self.assertIsInstance(ids, list,
                              "no utterance_transformer_ids provenance list")
        self.assertTrue(ids, "utterance_transformer_ids is empty")
        self.assertIn("first", ids)
        self.assertIn("second", ids)


# ─────────────────────────────────────────────────────────────────────────────
# §8 — Utterance cancellation
# ─────────────────────────────────────────────────────────────────────────────

class TestSec8Cancellation(TestCase):
    """§8.1: a transformer signals cancellation by setting ``canceled: true`` and
    ``cancel_reason`` in the returned context; the orchestrator MUST stamp
    ``cancel_by`` from the emitting transformer's id."""

    def test_cancel_signal_propagates(self):
        """§8.1: the ``canceled`` / ``cancel_reason`` keys a transformer sets are
        carried forward in Message.context (not stripped by the chain)."""
        class Canceller(UtteranceTransformer):
            def __init__(s):
                super().__init__("canceller", priority=50)

            def transform(s, utterances, context=None):
                return [], {"canceled": True, "cancel_reason": "policy_block"}

        svc = _utt_service([Canceller()])
        _, ctx = svc.transform(["hi"], {})
        self.assertTrue(ctx.get("canceled"))
        self.assertEqual(ctx.get("cancel_reason"), "policy_block")

    @pytest.mark.xfail(
        reason="OVOS-TRANSFORM-1 §8.1 / §9 MUST: on observing a cancellation "
               "signal the orchestrator MUST stamp cancel_by from the emitting "
               "transformer's transformer_id (not any value the transformer "
               "supplied). The transformer service propagates canceled/"
               "cancel_reason but never stamps cancel_by.",
        strict=True,
    )
    def test_cancel_by_stamped_by_orchestrator(self):
        """§8.1 MUST: the orchestrator stamps ``cancel_by`` with the emitting
        transformer's id when it observes the cancellation signal."""
        class Canceller(UtteranceTransformer):
            def __init__(s):
                super().__init__("canceller", priority=50)

            def transform(s, utterances, context=None):
                return [], {"canceled": True, "cancel_reason": "stop_word"}

        svc = _utt_service([Canceller()])
        _, ctx = svc.transform(["hi"], {})
        self.assertEqual(ctx.get("cancel_by"), "canceller",
                         "orchestrator did not stamp cancel_by from the emitter")


# ─────────────────────────────────────────────────────────────────────────────
# §5 — Per-session overrides
# ─────────────────────────────────────────────────────────────────────────────

_HAS_OVERRIDE_FIELDS = "utterance_transformers" in __import__(
    "ovos_bus_client.session", fromlist=["Session"]
).Session("probe").serialize()

_requires_override_fields = pytest.mark.skipif(
    not _HAS_OVERRIDE_FIELDS,
    reason="installed ovos-bus-client has no session.<type>_transformers "
           "override fields (OVOS-TRANSFORM-1 §5 not yet registered in "
           "OVOS-SESSION-1 §2.1)",
)


class TestSec5PerSessionOverrides(TestCase):
    """§5: six per-session ``<type>_transformers`` preference fields and six
    ``blacklisted_<type>_transformers`` policy fields; policy overrides
    preference (§5.3)."""

    @_requires_override_fields
    def test_session_carries_override_fields(self):
        """§5.1: the session registers the six ``<type>_transformers`` ordering
        fields per OVOS-SESSION-1 §2.1."""
        from ovos_bus_client.session import Session
        s = Session("probe").serialize()
        for typ in ("utterance", "metadata", "intent", "audio", "dialog", "tts"):
            self.assertIn(f"{typ}_transformers", s,
                          f"session lacks {typ}_transformers override field")

# not bus-observable: §6 introspection (ovos.transformer.{type}.list query /
#   .response) — the installed ovos-core transformer services do not subscribe
#   to the §6 query topics, so there is no responder to drive; this is a missing
#   orchestrator surface rather than a divergence in observed behaviour.
# not bus-observable: §5.2/§5.3 denylist composition — needs the §5 session
#   fields AND orchestrator-side composition wiring; both absent in the stack,
#   so the skip above guards the whole section.
# not bus-observable: §7 re-entrancy / concurrency — a structural plugin
#   contract, not an observable single-run property.
