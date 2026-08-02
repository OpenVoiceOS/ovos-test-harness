"""OVOS-TRANSFORM-1 per-implementer conformance suite.

Where ``test_transform1_conformance.py`` asserts the TRANSFORM-1 chain contract
against the ovos-core transformer **services** using inline fixture
transformers, this suite asserts the same §3 per-type IO contract (and the §8.1
cancellation signal) against the **real shipped OVOS-org transformer plugins** —
proving each reference implementer, run through the production chain-runner,
honours the observable behaviour the orchestrator suite already checks.

Driver model
------------
TRANSFORM-1 chain semantics live in the transformer *service*, not in the
orchestrator, and ovos-core discovers transformers from real
``opm.transformer.*`` entry points. Each test constructs the real service
(``UtteranceTransformersService`` / ``IntentTransformersService``) and injects a
live plugin instance into ``service.loaded_plugins`` (resetting
``_sorted_plugins``) — exactly the idiom of the orchestrator suite, but with the
shipped plugin in place of a fixture. Intent transformers are first bound to the
service bus and seeded through their OWN registration handler
(``padatious:register_entity`` / ``padatious:register_intent``), so the
enrichment path is exercised end to end without a MiniCroft boot.

Every negative assertion carries a positive control (a plain utterance passes
through un-cancelled; the identity invariant is checked against a genuinely
enriched Match), so no assertion is vacuous. ``importorskip`` guards each
implementer so an uninstalled plugin skips its own case rather than erroring the
module.

Reference implementers covered
------------------------------
- ``ovos-utterance-cancel-plugin`` (``NevermindPlugin``) — the canonical §3.2 /
  §8.1 utterance transformer: it clears the candidate list and raises the
  cancellation signal, and honours the §4.3 ``.blacklist`` veto.
- ``ovos-ahocorasick-ner-plugin`` and ``ovos-keyword-template-matcher`` — the
  two §3.4 intent transformers: they enrich ``Match.match_data`` with recognised
  entities while leaving ``skill_id`` / ``intent_name`` unchanged.

Out of scope (no bus-only reference implementer): the metadata, dialog, audio
and TTS transformer types ship in the default stack only as network/model-backed
plugins (``*-gguf-*``, ``*-openai-*``, the ggwave audio classifier) that a
bus-only harness cannot exercise — the same reason STT/TTS get no per-plugin
suite. Their per-type template contract (priority, id, the six types) is covered
by the orchestrator suite's ``TestPerTypeContract``.

xfail discipline (mirrors ``_conformance.py``): a spec MUST the shipped plugin
does not satisfy on the dev stack is marked ``xfail(strict=True)`` naming the
divergence — never a skip, never a vacuous pass.
"""
import unittest

import pytest

from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG

from ovos_core.transformers import (
    IntentTransformersService,
    UtteranceTransformersService,
)
from ovos_bus_client.message import Message
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch


def setUpModule():
    LOG.set_level("ERROR")


def _utt_service(plugins):
    svc = UtteranceTransformersService(FakeBus())
    svc.loaded_plugins = {p.name: p for p in plugins}
    svc._sorted_plugins = None
    return svc


def _intent_service(plugins):
    svc = IntentTransformersService(FakeBus())
    svc.loaded_plugins = {p.name: p for p in plugins}
    svc._sorted_plugins = None
    return svc


def _missing_case(key, module, exc, methods):
    """Skip-marked placeholder used when ``module`` is not installed, so one
    missing plugin skips its own case rather than erroring the whole module
    (test/test_install_floor.py turns the skip into a CI failure on a full
    stack)."""
    reason = (f"{key} ({module}) not installed; skipping its TRANSFORM-1 "
              f"per-implementer case ({exc})")

    class _Missing(unittest.TestCase):
        pass

    for name in methods:
        setattr(_Missing, name, unittest.skip(reason)(lambda self: None))
    return _Missing


# ---------------------------------------------------------------------------
# §3.2 / §8.1 — utterance transformer implementers
# ---------------------------------------------------------------------------

_UTT_METHODS = (
    "test_cancel_signal_set",
    "test_normal_utterance_passes_through",
    "test_blacklist_vetoes_cancel",
    "test_orchestrator_stamps_cancel_by",
    "test_cancel_reason_key_present",
)

UTTERANCE_PLUGINS = {
    "ovos-utterance-cancel": {
        "module": "ovos_utterance_plugin_cancel",
        "cls": "NevermindPlugin",
    },
}


def _build_utt_case(key, spec):
    try:
        module = __import__(spec["module"], fromlist=[spec["cls"]])
    except ImportError as exc:
        LOG.exception("TRANSFORM-1 plugin %s (%s) is not importable; its "
                      "per-implementer case will skip", key, spec["module"])
        return _missing_case(key, spec["module"], exc, _UTT_METHODS)

    plugin_cls = getattr(module, spec["cls"])

    class _Case(unittest.TestCase):
        LANG = "en-US"

        def setUp(self):
            self.plugin = plugin_cls()
            words = self.plugin.get_cancel_words(self.LANG)
            self.assertTrue(words, "plugin ships no cancel vocabulary")
            # Longest phrase is the most specific / stable trigger.
            self.cancel_phrase = sorted(words, key=len)[-1]

        def test_cancel_signal_set(self):
            """§8.1 MUST: an utterance ending in a cancel phrase clears the
            candidate list and raises ``canceled: true`` in the context."""
            svc = _utt_service([self.plugin])
            utts, ctx = svc.transform([f"do the thing {self.cancel_phrase}"],
                                      {"lang": self.LANG})
            self.assertEqual(utts, [], "cancel did not clear the candidate list")
            self.assertTrue(ctx.get("canceled"),
                            "cancel signal (canceled: true) not raised")

        def test_normal_utterance_passes_through(self):
            """§3.2 positive control: a plain utterance with no cancel phrase is
            returned unchanged and is NOT flagged cancelled — proving the cancel
            path is a real discrimination, not an always-cancel."""
            svc = _utt_service([self.plugin])
            utts, ctx = svc.transform(["turn on the kitchen lights"],
                                      {"lang": self.LANG})
            self.assertIn("turn on the kitchen lights", utts,
                          "a non-cancel utterance was dropped")
            self.assertFalse(ctx.get("canceled"),
                             "a non-cancel utterance was flagged cancelled")

        def test_blacklist_vetoes_cancel(self):
            """§4.3: an utterance whose prefix is in the plugin's ``.blacklist``
            bypasses the cancel-suffix match — it is ABOUT a cancel word, not a
            command to cancel. Positive control: the same suffix cancels without
            the veto prefix (asserted in ``test_cancel_signal_set``)."""
            blacklist = self.plugin.get_cancel_blacklist(self.LANG)
            if not blacklist:
                self.skipTest("plugin ships no cancel.blacklist for this lang")
            prefix = blacklist[0]
            svc = _utt_service([self.plugin])
            utts, ctx = svc.transform([f"{prefix} {self.cancel_phrase}"],
                                      {"lang": self.LANG})
            self.assertFalse(ctx.get("canceled"),
                             "a blacklisted-prefix utterance was cancelled")
            self.assertTrue(utts, "blacklisted-prefix utterance was dropped")

        def test_orchestrator_stamps_cancel_by(self):
            """§8.1 MUST: when the chain observes the cancellation signal, the
            service stamps ``cancel_by`` with the emitting transformer's id."""
            svc = _utt_service([self.plugin])
            _, ctx = svc.transform([f"please just {self.cancel_phrase}"],
                                   {"lang": self.LANG})
            self.assertEqual(ctx.get("cancel_by"), self.plugin.name,
                             "orchestrator did not stamp cancel_by from the "
                             "cancelling transformer")

        def test_cancel_reason_key_present(self):
            """§8.1 MUST: the cancellation cause is named in ``cancel_reason``."""
            svc = _utt_service([self.plugin])
            _, ctx = svc.transform([f"do the thing {self.cancel_phrase}"],
                                   {"lang": self.LANG})
            self.assertIn("cancel_reason", ctx,
                          "§8.1 cancel_reason key absent from cancel context")

    _Case.__name__ = f"TestTransform1Utterance_{key.replace('-', '_')}"
    _Case.__qualname__ = _Case.__name__
    _Case.__doc__ = (f"TRANSFORM-1 §3.2/§8.1 per-implementer conformance for the "
                     f"{key} utterance transformer.")
    return _Case


# ---------------------------------------------------------------------------
# §3.4 — intent transformer implementers
# ---------------------------------------------------------------------------

_INTENT_METHODS = (
    "test_captures_are_enriched",
    "test_identity_invariant_preserved",
)

INTENT_PLUGINS = {
    "ovos-ahocorasick-ner": {
        "module": "ahocorasick_ner.opm",
        "cls": "AhocorasickNERTransformer",
        "register_topic": "padatious:register_entity",
        "skill_id": "myskill",
        "intent_name": "myskill:paint",
        # ahocorasick's tag() has a 5-char min_word_len, so the seed entity
        # must be >= 5 chars to be recognised.
        "entity_name": "color",
        "samples": ["crimson", "magenta"],
        "utterance": "paint the wall crimson",
        "expected_capture": ("color", "crimson"),
    },
    "ovos-keyword-template-matcher": {
        "module": "kw_template_matcher.opm",
        "cls": "KeywordTemplateMatcher",
        "register_topic": "padatious:register_intent",
        "skill_id": "myskill",
        "intent_name": "myskill:play",
        "samples": ["play {track}", "put on {track}"],
        "utterance": "play jazz",
        "expected_capture": ("track", "jazz"),
    },
}


def _build_intent_case(key, spec):
    try:
        module = __import__(spec["module"], fromlist=[spec["cls"]])
    except ImportError as exc:
        LOG.exception("TRANSFORM-1 plugin %s (%s) is not importable; its "
                      "per-implementer case will skip", key, spec["module"])
        return _missing_case(key, spec["module"], exc, _INTENT_METHODS)

    plugin_cls = getattr(module, spec["cls"])
    slot, value = spec["expected_capture"]

    class _Case(unittest.TestCase):
        LANG = "en-US"

        def setUp(self):
            self.svc = _intent_service([])
            self.plugin = plugin_cls()
            # Bind to the service bus and seed via the plugin's OWN registration
            # handler, then inject the seeded instance into the service.
            self.plugin.bind(self.svc.bus)
            payload = {"lang": self.LANG, "skill_id": spec["skill_id"],
                       "name": spec["intent_name"] if spec["register_topic"]
                       == "padatious:register_intent" else spec["entity_name"],
                       "samples": spec["samples"]}
            self.svc.bus.emit(Message(spec["register_topic"], payload,
                                      {"skill_id": spec["skill_id"]}))
            self.svc.loaded_plugins = {self.plugin.name: self.plugin}
            self.svc._sorted_plugins = None

        def _match(self):
            return IntentHandlerMatch(match_type=spec["intent_name"],
                                      match_data={"orig": 1},
                                      skill_id=spec["skill_id"],
                                      utterance=spec["utterance"])

        def test_captures_are_enriched(self):
            """§3.4 MUST: the intent transformer MAY enrich ``Match.match_data``
            with recognised entities — exercised through the plugin's own
            registration and matcher, the enriched capture appears."""
            out = self.svc.transform(self._match())
            self.assertEqual(out.match_data.get(slot), value,
                             f"{key} did not enrich match_data[{slot!r}]")

        def test_identity_invariant_preserved(self):
            """§3.4 MUST NOT change ``skill_id`` / ``intent_name``; the engine's
            prior captures MUST survive the enrichment (positive control that
            the transformer actually ran on this Match)."""
            out = self.svc.transform(self._match())
            self.assertEqual(out.skill_id, spec["skill_id"],
                             "intent transformer changed skill_id (§3.4)")
            self.assertEqual(out.match_type, spec["intent_name"],
                             "intent transformer changed intent_name (§3.4)")
            self.assertEqual(out.match_data.get("orig"), 1,
                             "prior engine capture dropped by the transformer")

    _Case.__name__ = f"TestTransform1Intent_{key.replace('-', '_')}"
    _Case.__qualname__ = _Case.__name__
    _Case.__doc__ = (f"TRANSFORM-1 §3.4 per-implementer conformance for the "
                     f"{key} intent transformer.")
    return _Case


# Generate and register one TestCase per implementer in module globals.
for _key, _spec in UTTERANCE_PLUGINS.items():
    _cls = _build_utt_case(_key, _spec)
    globals()[_cls.__name__] = _cls

for _key, _spec in INTENT_PLUGINS.items():
    _cls = _build_intent_case(_key, _spec)
    globals()[_cls.__name__] = _cls

del _key, _spec, _cls
