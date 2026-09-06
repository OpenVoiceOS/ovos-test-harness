"""Per-implementer conformance for the answering-plugin specs
(OVOS-PERSONA-1 and OVOS-FALLBACK-1).

Where ``test_persona1_conformance.py`` / ``test_fallback1_conformance.py``
assert the PERSONA-1 and FALLBACK-1 bus contracts against the ovos-core
orchestrator, this suite asserts the SAME observable contract against the
**shipped OVOS-org reference implementers** of each spec's pluggable answering
role — proving the implementer, exercised through the orchestrator, honours the
contract end to end.

It is data-driven: a registry per family holds one entry per reference
implementer and generates one TestCase each. A single MiniCroft is shared by the
whole module (``setUpModule``) — it loads the fallback catch-all skill AND
mounts a persona per registered solver, so every implementer is exercised
against one boot rather than one boot each.

Families and implementers
-------------------------
- PERSONA-1: the pluggable role is a **question-solver** backing a persona. The
  only network/model-free OVOS-org reference solver in the default stack is
  ``ovos-solver-failure-plugin`` (the always-on solver the orchestrator suite
  itself uses). Each registered solver is mounted as its own persona; with that
  persona active the test asserts the §7.2/§8.1 flow — ``persona:query`` claimed
  and a response spoken on ``ovos.utterance.speak`` — runs through THAT solver.
  (The §7.1 route-1 "ask <persona>" embedded command needs ``handle_fallback``
  on, which would enrol the persona in the fallback pool and pre-empt the
  FALLBACK implementer below; that route is a persona-plugin behaviour already
  covered by the orchestrator suite, so the shared boot keeps ``handle_fallback``
  off and drives the solver through the active-persona route.) Network/model
  solvers (openai, gguf, wolfram, wikipedia) cannot run on a bus-only harness and
  are out of scope, like STT/TTS.
- FALLBACK-1: the pluggable role is a **FallbackSkill**. The default-stack
  reference implementer is ``ovos-skill-fallback-unknown`` (the ``priority:100``
  catch-all). The test drives a no-match utterance and asserts the §5/§6 cycle —
  query (ping) before dispatch (request), a ``.pong``/``.response`` from the
  skill, and exactly one ``ovos.utterance.handled`` end-marker. That end-marker
  count is 1 only under the CI-pinned ovos-workshop carrying the PIPELINE-1 §9.5
  double-emit fix (``fix/core-owns-utterance-handled-fallback-converse``); on an
  unpinned local venv it is 2, exactly as the orchestrator fallback suite's own
  ``test_exactly_one_handled`` behaves.

COMMON-QUERY-1 is intentionally not given a per-implementer suite here: its
pluggable answering role is a CommonQuerySkill, and every OVOS-org CQ skill in
the default stack (wikipedia, duckduckgo, wolfram) needs network, so none can be
exercised on a bus-only harness — the same reason STT/TTS are excluded. The CQ
pipeline plugin and the skill-side poll/answer contract are covered at
orchestrator level in ``test_common_query1_conformance.py`` with an in-process
fixture skill.

Every negative assertion carries a positive control (the no-winner path still
terminates; the persona claim is proven by a dispatched ``persona:query``), so
no assertion is vacuous. ``importorskip`` guards each implementer. xfail
discipline follows ``_conformance.py``.
"""
import json
import os
import shutil
import tempfile
import time
import unittest

import pytest
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

from ovoscope import PERSONA_PIPELINE, get_minicroft

from ._conformance import (
    DEFAULT_EOF_TYPES,
    PADACIOSO_HIGH,
    capture,
    first,
    reset_namespace,
    types,
    use_spec_namespace,
    utterance,
    wait_ready,
)

PERSONA_HIGH = "ovos-persona-pipeline-plugin-high"
PERSONA_LOW = "ovos-persona-pipeline-plugin-low"
PERSONA_PIPELINE = [PERSONA_HIGH, PERSONA_LOW]

FALLBACK_HIGH = "ovos-fallback-pipeline-plugin-high"
FALLBACK_LOW = "ovos-fallback-pipeline-plugin-low"
FALLBACK_PIPELINE = [PADACIOSO_HIGH, FALLBACK_HIGH, FALLBACK_LOW]

UNKNOWN_ID = "ovos-skill-fallback-unknown.openvoiceos"

# A neutral utterance that does NOT trip the persona command matchers, so it
# exercises the active-persona catch-all rather than a summon/ask/list/check.
NEUTRAL = "the sky is blue today"
# A no-match utterance that no deterministic matcher claims, forcing fallback.
NOMATCH = "zxqw blah blah"


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

# PERSONA-1: solver plugin id -> the persona identity mounted on it.
PERSONA_SOLVERS = {
    "ovos-solver-failure-plugin": {
        "module": "ovos_solver_failure_plugin",
        # A plain single-word identity the §7.1 route-1 "ask <persona> ..."
        # matcher parses cleanly (the orchestrator persona suite uses the same).
        "persona": "Alice",
    },
}

# FALLBACK-1: fallback skill id -> its importable module (importorskip guard).
FALLBACK_SKILLS = {
    "ovos-skill-fallback-unknown": {
        "module": "ovos_skill_fallback_unknown",
        "skill_id": UNKNOWN_ID,
    },
}


_MC = None
_PERSONAS_DIR = None


def _write_personas() -> str:
    """One persona JSON per registered solver whose plugin is importable."""
    path = tempfile.mkdtemp(prefix="solver-conf-")
    for solver_id, spec in PERSONA_SOLVERS.items():
        try:
            __import__(spec["module"])
        except ImportError:
            continue
        with open(os.path.join(path, f"{spec['persona']}.json"), "w") as f:
            json.dump({"name": spec["persona"], "solvers": [solver_id]}, f)
    return path


def setUpModule():
    global _MC, _PERSONAS_DIR
    LOG.set_level("ERROR")
    _PERSONAS_DIR = _write_personas()
    use_spec_namespace()
    try:
        # One boot serves both families: the fallback catch-all skill is loaded,
        # and the personas dir mounts a persona per solver. handle_fallback is
        # off so the persona stage never pre-empts the fallback pool.
        _MC = get_minicroft(
            [UNKNOWN_ID],
            pipeline_config={"persona": {"personas_path": _PERSONAS_DIR,
                                         "handle_fallback": False}},
            extra_pipelines=PERSONA_PIPELINE,
        )
        wait_ready(_MC)
    except BaseException:
        reset_namespace()
        raise


def tearDownModule():
    try:
        if _MC is not None:
            _MC.stop()
    finally:
        try:
            reset_namespace()
        finally:
            if _PERSONAS_DIR:
                shutil.rmtree(_PERSONAS_DIR, ignore_errors=True)


# ---------------------------------------------------------------------------
# PERSONA-1 — solver-backed persona implementers
# ---------------------------------------------------------------------------

def _missing_case(key, module, exc, methods):
    reason = f"{key} ({module}) not installed; skipping its case ({exc})"

    class _Missing(unittest.TestCase):
        pass

    for name in methods:
        setattr(_Missing, name, unittest.skip(reason)(lambda self: None))
    return _Missing


_PERSONA_METHODS = ("test_active_persona_claims",
                    "test_active_persona_speaks")


def _build_persona_case(solver_id, spec):
    try:
        __import__(spec["module"])
    except ImportError as exc:
        LOG.exception("PERSONA-1 solver %s (%s) not importable; case will skip",
                      solver_id, spec["module"])
        return _missing_case(solver_id, spec["module"], exc, _PERSONA_METHODS)

    persona = spec["persona"]
    slug = solver_id.replace("-", "_")

    class _Case(unittest.TestCase):

        def _active(self):
            return capture(_MC, utterance(NEUTRAL, f"solv-{slug}-active",
                                          PERSONA_PIPELINE, persona_id=persona),
                           6.0)

        def test_active_persona_claims(self):
            """§7.2 MUST: with this solver's persona active, the stage claims a
            neutral (non-command) utterance — it dispatches ``persona:query``,
            routing the utterance into THIS solver plugin. Positive control: the
            dispatch fires (not merely 'no unmatched')."""
            seq = types(self._active())
            self.assertIn("persona:query", seq,
                          f"{solver_id}: active persona did not claim")

        def test_active_persona_speaks(self):
            """§8.1 MUST: the handler generates a response from this solver and
            emits it on ``ovos.utterance.speak`` — proving the answer flows
            through the solver end to end, not just that the stage claimed."""
            seq = types(self._active())
            self.assertIn("ovos.utterance.speak", seq,
                          f"{solver_id}: solver produced no spoken response")

    _Case.__name__ = f"TestPersona1Solver_{slug}"
    _Case.__qualname__ = _Case.__name__
    _Case.__doc__ = (f"PERSONA-1 per-implementer conformance for the {solver_id} "
                     f"question-solver (mounted as persona {persona!r}).")
    return _Case


# ---------------------------------------------------------------------------
# FALLBACK-1 — fallback-skill implementers
# ---------------------------------------------------------------------------

_FALLBACK_METHODS = ("test_fallback_request_and_handled",
                     "test_query_precedes_dispatch",
                     "test_skill_responds",
                     "test_exactly_one_handled")


def _build_fallback_case(key, spec):
    try:
        __import__(spec["module"])
    except ImportError as exc:
        LOG.exception("FALLBACK-1 skill %s (%s) not importable; case will skip",
                      key, spec["module"])
        return _missing_case(key, spec["module"], exc, _FALLBACK_METHODS)

    skill_id = spec["skill_id"]
    slug = key.replace("-", "_")

    class _Case(unittest.TestCase):

        def _fallback(self, session_id, eof_types=DEFAULT_EOF_TYPES):
            return capture(_MC, utterance(NOMATCH, session_id, FALLBACK_PIPELINE),
                           5.0, eof_types=eof_types)

        def test_fallback_request_and_handled(self):
            """§5/§6.4 MUST: a no-match utterance reaches the catch-all, which is
            dispatched its ``request`` and the turn terminates with a
            ``handled`` end-marker."""
            seq = types(self._fallback(f"fb-{slug}-req"))
            self.assertIn(f"ovos.skills.fallback.{skill_id}.request", seq,
                          f"{key}: catch-all was not dispatched")
            self.assertIn("ovos.utterance.handled", seq)

        def test_query_precedes_dispatch(self):
            """§5/§6 MUST: the pool is polled (ping) BEFORE any handler is
            dispatched its ``request`` — willingness first."""
            seq = types(self._fallback(f"fb-{slug}-order"))
            ping = "ovos.skills.fallback.ping"
            req = f"ovos.skills.fallback.{skill_id}.request"
            self.assertIn(ping, seq, f"{key}: no fallback ping observed")
            self.assertIn(req, seq, f"{key}: no dispatch observed")
            self.assertLess(seq.index(ping), seq.index(req),
                            f"{key}: dispatch preceded the willingness poll")

        def test_skill_responds(self):
            """§6.2 MUST: the selected skill answers — a ``.pong`` claim and a
            per-skill ``.response`` carrying its result."""
            seq = types(self._fallback(f"fb-{slug}-resp"))
            self.assertIn("ovos.skills.fallback.pong", seq,
                          f"{key}: skill did not claim on pong")
            self.assertIn(f"ovos.skills.fallback.{skill_id}.response", seq,
                          f"{key}: skill emitted no response")

        def test_exactly_one_handled(self):
            """§6.4 MUST: a fallback-answered utterance terminates with exactly
            one ``ovos.utterance.handled`` (positive control: the count is 1,
            not 0 — the turn really ran — and not >1)."""
            recs = self._fallback(f"fb-{slug}-eof", eof_types=None)
            self.assertEqual(types(recs).count("ovos.utterance.handled"), 1,
                             f"{key}: end-marker count != 1")

    _Case.__name__ = f"TestFallback1Skill_{slug}"
    _Case.__qualname__ = _Case.__name__
    _Case.__doc__ = (f"FALLBACK-1 per-implementer conformance for the {key} "
                     f"catch-all skill ({skill_id}).")
    return _Case


# Generate and register one TestCase per implementer in module globals.
for _sid, _spec in PERSONA_SOLVERS.items():
    _cls = _build_persona_case(_sid, _spec)
    globals()[_cls.__name__] = _cls

for _key, _spec in FALLBACK_SKILLS.items():
    _cls = _build_fallback_case(_key, _spec)
    globals()[_cls.__name__] = _cls

del _sid, _key, _spec, _cls
