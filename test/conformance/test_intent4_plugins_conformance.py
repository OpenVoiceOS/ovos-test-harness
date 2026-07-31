"""OVOS-INTENT-4 per-plugin *registration-compliance* conformance suite.

Where ``test_intent4_conformance.py`` asserts the INTENT-4 bus contract against
the ovos-core **orchestrator**, this suite asserts it against **each individual
intent-pipeline plugin** — proving that every matcher consumes the INTENT-4 spec
registration topic and becomes matchable, while still honouring the legacy
registration path (back-compat).

It is data-driven: a module-level :data:`PLUGINS` registry holds one entry per
matcher plugin, and :func:`_build_case` generates one :class:`E2EPipelineHarness`
subclass per entry (injected into module globals so pytest collects them).

Engine kinds (INTENT-4 §5 / §6 / §11)
-------------------------------------
- ``"keyword"`` engines (adapt, palavreado) consume
  ``ovos.intent.register.keyword`` (``SpecMessage.INTENT_REGISTER_KEYWORD``,
  §5) with a four-key ``required``/``optional``/``one_of``/``excluded`` payload,
  and register legacy intents via ``register_vocab`` + ``register_intent``.
- ``"template"`` engines (padacioso, nebulento, padatious, m2v, linha-fina,
  markov) consume ``ovos.intent.register.template``
  (``SpecMessage.INTENT_REGISTER_TEMPLATE``, §6) with inline ``samples``, and
  register legacy intents via ``padatious:register_intent``.

Per-plugin assertions
---------------------
``test_spec_registration_is_matchable``
    Emit the spec registration topic for this engine kind, send a matching
    utterance, and assert dispatch of ``<skill_id>:<intent_name>``.
``test_legacy_registration_still_matches``
    Register via the legacy engine-family path and assert it still matches —
    this MUST be green for every plugin (back-compat is non-negotiable).

xfail discipline (mirrors ``_conformance.py``)
----------------------------------------------
A plugin whose INTENT-4 adoption is INSTALLED (its ``requirements.txt`` pin
carries the spec-topic consumer) has a GREEN spec test. A plugin pinned at a ref
WITHOUT the adoption marks its ``test_spec_registration_is_matchable``
``@pytest.mark.xfail(strict=True, reason=...)`` — it flips to a pass once the
adoption ref is pinned. ``adapt`` and ``padacioso`` are deliberately kept at
``@dev`` (they are load-bearing for the orchestrator suites), so their spec
tests xfail until their adoption branch can be pinned without disturbing those
suites.

A plugin that fails to import (not installed in the combo under test) is SKIPPED
via :func:`pytest.importorskip` at class-build time, so it never errors the
whole module.
"""
import time
import unittest
from typing import Any, Dict, List, Optional

import pytest

ovoscope = pytest.importorskip(
    "ovoscope", reason="ovoscope not installed; skipping INTENT-4 plugin suite"
)

from ovoscope import E2EPipelineHarness  # noqa: E402
from ovos_bus_client.message import Message  # noqa: E402
from ovos_spec_tools import SpecMessage  # noqa: E402

REGISTER_KEYWORD = str(SpecMessage.INTENT_REGISTER_KEYWORD)
REGISTER_TEMPLATE = str(SpecMessage.INTENT_REGISTER_TEMPLATE)


# ---------------------------------------------------------------------------
# Plugin registry — one entry per matcher plugin under test.
# ---------------------------------------------------------------------------
#
# Fields:
#   module        : importable package name (importorskip guard).
#   pipeline_id   : OPM ``opm.pipeline`` entry-point name MiniCroft is pinned to.
#   config_key    : key under ``Configuration()["intents"]`` for plugin config.
#   plugin_config : dict merged into that config before MiniCroft starts.
#   engine_kind   : "keyword" (§5) or "template" (§6) — selects the spec topic
#                   and the legacy registration path.
#   intent        : the ``intent_name`` registered in the tests.
#   utterance     : an utterance that must match ``intent``.
#   keyword       : (keyword engines) the §5 required-descriptor dict.
#   samples       : (template engines) the §6 sample list.
#   spec_xfail    : reason string -> spec test is xfail; None -> spec test green.
#   fuzzy         : retry the capture a few times (fuzzy/heavy engines race the
#                   pipeline-ready state on the first match after a fresh boot).
#   decoy         : register a second, clearly-different intent alongside the
#                   target. Multi-class classifier engines (linha-fina, markov)
#                   need >=2 labels to discriminate; a lone intent cannot train
#                   a meaningful boundary. The decoy never matches the target
#                   utterance — it only provides a negative class.

_LIGHTS_KEYWORD = {
    "TurnOff": ["off", "disable", "shutdown"],
    "Light": ["light", "lights", "lamp"],
}
_HELLO = ["hello", "hi there", "hey", "greetings", "good morning"]
_M2V_SAMPLES = ["turn off the lights", "switch off the lights", "lights off please"]
# A clearly-distinct decoy intent (never matches "hello") so classifier engines
# have a negative class to train against.
_DECOY_INTENT = "weather"
_DECOY_SAMPLES = ["what is the weather", "will it rain today",
                  "is it sunny outside", "weather forecast please"]

PLUGINS: Dict[str, Dict[str, Any]] = {
    # -- keyword engines (§5) ------------------------------------------------
    "adapt": {
        "module": "ovos_adapt",
        "pipeline_id": "ovos-adapt-pipeline-plugin",
        "config_key": "adapt",
        "plugin_config": {},
        "engine_kind": "keyword",
        "intent": "lights_off",
        "utterance": "turn off the lights",
        "keyword": _LIGHTS_KEYWORD,
        # adapt is pinned @dev (load-bearing for the orchestrator suites: it
        # carries the #47 None-blacklist guard the INTENT-3 suite relies on).
        # @dev does not yet consume the §5 spec topic, so the spec test xfails.
        "spec_xfail": "adapt INTENT-4 adoption pending on @dev "
                      "(kept @dev — load-bearing for the INTENT-3 suite)",
    },
    "palavreado": {
        "module": "palavreado",
        "pipeline_id": "palavreado",
        "config_key": "palavreado",
        "plugin_config": {},
        "engine_kind": "keyword",
        "intent": "lights_off",
        "utterance": "turn off the lights",
        "keyword": _LIGHTS_KEYWORD,
        # adoption merged to @dev -> spec test green.
        "spec_xfail": None,
    },
    # -- template engines (§6) ----------------------------------------------
    "padacioso": {
        "module": "padacioso",
        "pipeline_id": "ovos-padacioso-pipeline-plugin",
        "config_key": "padacioso",
        "plugin_config": {},
        "engine_kind": "template",
        "intent": "hello",
        "utterance": "hello",
        "samples": _HELLO,
        # padacioso is pinned @dev (load-bearing: it is the PADACIOSO_HIGH
        # driver with the lru_cache fix the orchestrator suites depend on).
        "spec_xfail": "padacioso INTENT-4 adoption pending on @dev "
                      "(kept @dev — load-bearing PADACIOSO_HIGH driver)",
        "fuzzy": True,
    },
    "nebulento": {
        "module": "nebulento",
        "pipeline_id": "ovos-nebulento-pipeline-plugin",
        "config_key": "nebulento",
        "plugin_config": {"strategy": "TOKEN_SET_RATIO"},
        "engine_kind": "template",
        "intent": "hello",
        "utterance": "hello",
        "samples": _HELLO,
        # adoption merged to @dev -> spec test green.
        "spec_xfail": None,
        "fuzzy": True,
    },
    "padatious": {
        "module": "ovos_padatious",
        "pipeline_id": "ovos-padatious-pipeline-plugin",
        "config_key": "padatious",
        # instant_train -> each registration trains synchronously so a following
        # utterance matches deterministically; conf_low keeps short greetings in.
        "plugin_config": {"instant_train": True, "conf_low": 0.6},
        "engine_kind": "template",
        "intent": "hello",
        "utterance": "hello",
        "samples": _HELLO,
        # pinned @feat/intent-4-adoption -> spec test green.
        "spec_xfail": None,
        "fuzzy": True,
        "settle": 2.0,
        "timeout": 12.0,
    },
    "m2v": {
        "module": "ovos_m2v_pipeline",
        # prototype mode is the only mode that ingests fresh samples e2e.
        "pipeline_id": "ovos-m2v-prototype-pipeline",
        "config_key": "ovos_m2v_prototype_pipeline",
        # The smallest published model2vec model keeps the download tiny while
        # exercising a real encoder end-to-end (no mock).
        "plugin_config": {
            "mode": "prototype",
            "model": "minishlab/potion-base-2M",
            "prototype_k": 5,
        },
        "engine_kind": "template",
        "intent": "lights_off",
        "utterance": "turn off the lights",
        "samples": _M2V_SAMPLES,
        # pinned @feat/intent-4-adoption -> spec test green.
        "spec_xfail": None,
        "fuzzy": True,
        "settle": 1.5,
    },
    "linha-fina": {
        "module": "linha_fina",
        "pipeline_id": "ovos-linha-fina-pipeline-plugin",
        "config_key": "ovos-linha-fina-pipeline-plugin",
        # lower the low-confidence floor so a clean match still clears the bar
        # with a small training set.
        "plugin_config": {"conf_low": 0.2},
        "engine_kind": "template",
        "intent": "hello",
        "utterance": "hello",
        "samples": _HELLO,
        # multi-class classifier -> a clearly-distinct negative class lets it
        # train a meaningful decision boundary on a tiny corpus.
        "decoy": True,
        # adoption merged to @dev (linha-fina #17: §6 template consumer, which
        # also fixed the unhashable-Session lru_cache key) -> both tests green.
        "spec_xfail": None,
        "fuzzy": True,
    },
    "markov": {
        "module": "ovos_markov_pipeline",
        "pipeline_id": "ovos-markov-pipeline-plugin",
        "config_key": "ovos-markov-pipeline-plugin",
        # instant_train trains every registration synchronously; the low conf
        # floor + small order keep a clean greeting match above threshold with
        # a tiny corpus (mirrors the plugin's own e2e config).
        "plugin_config": {
            "order": 1, "instant_train": True,
            "conf_high": 0.50, "conf_med": 0.30, "conf_low": 0.15,
        },
        "engine_kind": "template",
        "intent": "hello",
        "utterance": "hello",
        "samples": _HELLO,
        # No decoy: the perplexity ensemble mis-ranks a competing label on a
        # tiny corpus; with the single target label the greeting matches cleanly.
        # adoption merged to @dev (markov #11: §6 template consumer) -> green.
        "spec_xfail": None,
        "fuzzy": True,
    },
}


# ---------------------------------------------------------------------------
# Harness factory
# ---------------------------------------------------------------------------

def _descs(d: Optional[Dict[str, List[str]]]) -> List[Dict[str, Any]]:
    """Build the §5.2 ``{name, samples}`` descriptor list from a dict."""
    return [{"name": n, "samples": s} for n, s in (d or {}).items()]


def _missing_case(key: str, spec: Dict[str, Any], exc: BaseException) -> type:
    """A placeholder TestCase that skips — used when ``spec['module']`` is not
    installed in the combo under test, so one missing plugin SKIPS its own case
    rather than erroring (or skipping) the whole module."""
    reason = (f"{key} ({spec['module']}) not installed; skipping its "
              f"INTENT-4 registration-compliance case ({exc})")

    class _Missing(unittest.TestCase):
        @unittest.skip(reason)
        def test_spec_registration_is_matchable(self):  # pragma: no cover
            pass

        @unittest.skip(reason)
        def test_legacy_registration_still_matches(self):  # pragma: no cover
            pass

    return _Missing


def _build_case(key: str, spec: Dict[str, Any]) -> type:
    """Generate one :class:`E2EPipelineHarness` subclass for ``spec``.

    If the plugin is not importable in the combo under test, return a
    skip-marked placeholder so collection of the rest of the suite is unaffected.
    """
    try:
        __import__(spec["module"])
    except Exception as exc:  # not installed / import error -> skip this case
        return _missing_case(key, spec, exc)

    engine_kind = spec["engine_kind"]
    intent_name = spec["intent"]
    utterance = spec["utterance"]
    settle = spec.get("settle", 1.0)
    timeout = spec.get("timeout", 5.0)
    fuzzy = spec.get("fuzzy", False)
    decoy = spec.get("decoy", False)
    skill_id = f"intent4_{key.replace('-', '_')}.skill"

    class _Case(E2EPipelineHarness):
        PIPELINE_ID = spec["pipeline_id"]
        CONFIG_KEY = spec["config_key"]
        PLUGIN_CONFIG = dict(spec["plugin_config"])
        SKILL_ID = skill_id

        # -- helpers ----------------------------------------------------

        def _capture(self) -> Optional[Message]:
            """``send_and_capture`` for the registered intent, with a small
            retry for fuzzy/heavy engines that race pipeline-ready on a fresh
            boot."""
            expected = [f"{self.SKILL_ID}:{intent_name}"]
            attempts = 4 if fuzzy else 1
            for _ in range(attempts):
                msg = self.send_and_capture(
                    utterance, expected_types=expected, timeout=timeout
                )
                if msg is not None:
                    return msg
                time.sleep(0.5)
            return None

        def _emit_template(self, name, samples) -> None:
            self.bus.emit(Message(REGISTER_TEMPLATE, {
                "skill_id": self.SKILL_ID,
                "intent_name": name,
                "lang": self.DEFAULT_LANG,
                "samples": samples,
            }, {"skill_id": self.SKILL_ID}))

        def _register_spec(self) -> None:
            """Emit the INTENT-4 spec registration for this engine kind.

            Classifier engines (``decoy``) also get a clearly-distinct negative
            class so they can train a meaningful decision boundary.
            """
            if engine_kind == "keyword":
                payload = {
                    "skill_id": self.SKILL_ID,
                    "intent_name": intent_name,
                    "lang": self.DEFAULT_LANG,
                    "required": _descs(spec["keyword"]),
                    "optional": [],
                    "one_of": [],
                    "excluded": [],
                }
                self.bus.emit(Message(REGISTER_KEYWORD, payload,
                                      {"skill_id": self.SKILL_ID}))
            else:
                if decoy:
                    self._emit_template(_DECOY_INTENT, _DECOY_SAMPLES)
                self._emit_template(intent_name, spec["samples"])
            time.sleep(settle)

        def _register_legacy(self) -> None:
            """Register the same intent via the legacy engine-family path."""
            if engine_kind == "keyword":
                from ovoscope import register_adapt_intent, register_adapt_vocab
                from ovos_workshop.intents import IntentBuilder

                builder = IntentBuilder(f"{self.SKILL_ID}:{intent_name}")
                for name, words in spec["keyword"].items():
                    register_adapt_vocab(self.bus, f"{self.SKILL_ID}:{name}", words)
                    builder = builder.require(f"{self.SKILL_ID}:{name}")
                register_adapt_intent(self.bus, builder)
            else:
                from ovoscope import register_padatious_intent
                if decoy:
                    register_padatious_intent(
                        self.bus, f"{self.SKILL_ID}:{_DECOY_INTENT}",
                        _DECOY_SAMPLES,
                    )
                register_padatious_intent(
                    self.bus, f"{self.SKILL_ID}:{intent_name}", spec["samples"]
                )
            time.sleep(settle)

        # -- tests ------------------------------------------------------

        def test_spec_registration_is_matchable(self):
            """The plugin consumes the INTENT-4 spec registration topic and the
            intent becomes matchable (§5 keyword / §6 template)."""
            self._register_spec()
            msg = self._capture()
            self.assertIsNotNone(
                msg, f"{key}: expected a match from spec-topic registration "
                     f"({'keyword §5' if engine_kind == 'keyword' else 'template §6'})"
            )
            self.assertEqual(msg.msg_type, f"{self.SKILL_ID}:{intent_name}")

        def test_legacy_registration_still_matches(self):
            """Back-compat: the legacy registration path still matches."""
            self._register_legacy()
            msg = self._capture()
            self.assertIsNotNone(
                msg, f"{key}: legacy registration must still match"
            )
            self.assertEqual(msg.msg_type, f"{self.SKILL_ID}:{intent_name}")

    _Case.__name__ = f"TestIntent4Registration_{key.replace('-', '_')}"
    _Case.__qualname__ = _Case.__name__
    _Case.__doc__ = (
        f"INTENT-4 registration-compliance for the {key} pipeline "
        f"({engine_kind} engine, pipeline_id={spec['pipeline_id']!r})."
    )

    # Apply xfail to the spec test for plugins without the adoption installed.
    if spec.get("spec_xfail"):
        _Case.test_spec_registration_is_matchable = pytest.mark.xfail(
            strict=True, reason=spec["spec_xfail"]
        )(_Case.test_spec_registration_is_matchable)

    # Apply xfail to the legacy test for a plugin whose legacy path is itself
    # broken against the installed stack (documented real divergence).
    if spec.get("legacy_xfail"):
        _Case.test_legacy_registration_still_matches = pytest.mark.xfail(
            strict=True, reason=spec["legacy_xfail"]
        )(_Case.test_legacy_registration_still_matches)

    return _Case


# Generate and register one TestCase per plugin in module globals.
for _key, _spec in PLUGINS.items():
    _cls = _build_case(_key, _spec)
    _name = f"TestIntent4Registration_{_key.replace('-', '_')}"
    _cls.__name__ = _name
    _cls.__qualname__ = _name
    globals()[_name] = _cls

del _key, _spec, _cls, _name
