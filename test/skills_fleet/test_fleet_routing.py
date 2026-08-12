"""Fleet-level cross-skill intent-routing suite.

The per-skill ovoscope suites each boot a MiniCroft with exactly one skill
installed. That setup cannot catch cross-skill intent theft: if skill B's
vocabulary happens to overlap skill A's, B silently wins every time A's suite
runs alone, because there is no B in that MiniCroft to steal from A. This
module is the one test in the OVOS ecosystem that boots every fleet skill in
the golden corpus into a SINGLE MiniCroft and asserts each golden utterance
still routes to the skill that authored it.

Corpus
------
``golden_utterances.jsonl`` is a vendored copy of the ovoscope golden-utterance
dataset (skill_id / utterance / intent_method / intent_label / intent_type /
expected_messages / needs_manual). Rows with ``needs_manual: true`` need a
human in the loop (audio capture, GUI state, follow-up dialog) and are
skipped — not a routing assertion this harness can make unattended.
``quarantine.jsonl`` holds rows pulled out because the row itself, not the
routing, was wrong; see FINDINGS.md.

Fixed conflicts are hard failures. Known, triaged conflicts and coverage gaps
are ``xfail(strict=True)`` entries in ``xfail_registry.json``, each carrying a
category (``conflict`` names both the expected and the thieving skill;
``coverage-gap`` names the skill whose vocabulary should have matched) and a
human-readable reason. See FINDINGS.md for the full triage.
"""
import time

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG
from ovos_utils.process_utils import ProcessState

from ovoscope import get_minicroft

from ._fleet import (fleet_skill_ids, installed_id, load_corpus,
                      load_xfail_registry, row_key)

ENTRY_TOPIC = "recognizer_loop:utterance"
EOF_TYPES = {
    "ovos.utterance.handled",
    "mycroft.skill.handler.complete",
    "complete_intent_failure",
    "ovos.intent.unmatched",
}
BOOT_SETTLE = 3.0
CAPTURE_TIMEOUT = 8.0
CAPTURE_SETTLE = 0.4

_ROWS = load_corpus()
_FLEET_IDS = fleet_skill_ids(_ROWS)
_XFAIL = load_xfail_registry()

_MC = None


def setup_module(_module):
    global _MC
    LOG.set_level("ERROR")
    # A real fleet boot of ~30 skills has been observed taking 10-20 minutes
    # end to end (each skill's padatious/padacioso intent training runs
    # in-process at load time); this generous ceiling is a real observed
    # figure, not a guess -- see FINDINGS.md "Boot population".
    _MC = get_minicroft(_FLEET_IDS, max_wait=1800)
    deadline = time.monotonic() + 60
    state = getattr(getattr(_MC, "status", None), "state", None)
    while state != ProcessState.READY:
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"fleet MiniCroft not READY within 60s of get_minicroft() "
                f"returning (observed state={state}, "
                f"{len(_FLEET_IDS)} skills requested)")
        time.sleep(0.2)
        state = getattr(getattr(_MC, "status", None), "state", None)
    time.sleep(BOOT_SETTLE)


def teardown_module(_module):
    if _MC is not None:
        _MC.stop()


def _capture(utterance_text: str, lang: str = "en-US"):
    """Send one utterance turn and return every bus Message observed.

    ``FakeBus.emit`` runs every handler synchronously, in-thread. A skill
    whose fallback ``can_answer()`` raises instead of returning (see
    FINDINGS.md's ``ovos-skill-wolfie`` / ``ovos-skill-wordnet`` quarantine)
    was observed stalling that negotiation indefinitely on this bus; those
    two skills are excluded from ``_FLEET_IDS`` (their corpus rows are
    quarantined) specifically so ``emit`` here is never asked to run a
    handler known to hang. Emitting on a background thread was tried as a
    generic guard against this, but it raced the skill handlers against this
    driver's own polling loop and changed which skill "won" a genuine
    cross-skill conflict from one run to the next -- a driver bug that would
    make the suite non-reproducible. Emitting in-thread trades "a future
    unknown hang could stall the suite" for determinism against a known-hung
    population; if a NEW skill introduces the same can_answer() bug, it needs
    the same quarantine treatment, not a threading workaround here.
    """
    recs = []

    def _rec(serialized):
        if isinstance(serialized, Message):
            recs.append(serialized)
            return
        try:
            recs.append(Message.deserialize(serialized))
        except Exception:  # noqa: BLE001 - corrupt payload, not fatal here
            pass

    sess = Session(f"fleet-{abs(hash(utterance_text))}")
    sess.lang = lang
    msg = Message(ENTRY_TOPIC, {"utterances": [utterance_text], "lang": lang},
                  {"session": sess.serialize(), "source": "A", "destination": "B"})

    _MC.bus.on("message", _rec)
    try:
        deadline = time.monotonic() + CAPTURE_TIMEOUT
        _MC.bus.emit(msg)
        seen_eof = False
        while time.monotonic() < deadline:
            if any(m.msg_type in EOF_TYPES for m in recs):
                seen_eof = True
                break
            time.sleep(0.05)
        if seen_eof:
            time.sleep(CAPTURE_SETTLE)
    finally:
        _MC.bus.remove("message", _rec)
    return recs


def _claimant(recs, fleet_ids):
    """Best-effort: which fleet skill_id claimed this utterance turn.

    ``ovos.intent.unmatched`` is authoritative: the intent pipeline itself is
    declaring no skill matched, so this returns ``None`` immediately even if
    some OTHER skill's message shows up in the same capture window (a skill
    answering an unrelated ``ovos.skills.fallback.ping`` "can I handle this? no"
    probe still carries its own ``context.skill_id`` on the ``.pong`` reply,
    which is not a claim and must not be read as one).

    Otherwise the primary signal is a msg_type of the shape
    ``<skill_id>:<intent_name>`` matching a booted fleet id — the topic the
    intent pipeline dispatches to when it selects that skill's registered
    intent, which fires regardless of whether the skill's handler goes on to
    raise. A ``speak``/``context.skill_id`` fallback covers the rare
    dispatch shape without a colon-qualified topic. Deliberately does NOT
    fall back to "any message in the capture window naming a fleet
    skill_id": a 6-8s window catches background/periodic activity from
    unrelated skills (observed: another skill's own
    ``mycroft.skill.handler.complete`` from an unrelated scheduled event,
    landing in the same window as a skill whose OWN handler then raised) —
    reading that as a claim produced false cross-skill-theft positives that
    were not real theft.
    """
    types_seen = {m.msg_type for m in recs}
    if "ovos.intent.unmatched" in types_seen:
        return None
    for m in recs:
        if ":" in m.msg_type:
            prefix = m.msg_type.split(":", 1)[0]
            if prefix in fleet_ids:
                return prefix
    for m in recs:
        ctx_skill = (m.context or {}).get("skill_id")
        if ctx_skill in fleet_ids and m.msg_type == "speak":
            return ctx_skill
    return None


def _pipeline_stage(recs):
    """The last pipeline-identifying context field seen, for failure output."""
    for m in reversed(recs):
        ctx = m.context or {}
        for key in ("pipeline", "pipeline_id", "matcher"):
            if key in ctx:
                return f"{key}={ctx[key]}"
    return "unknown"


def _mark_for(row):
    xf = _XFAIL.get(row_key(row))
    if xf is None:
        return None
    category = xf["category"]
    reason = xf["reason"]
    return pytest.mark.xfail(strict=True, reason=f"[{category}] {reason}")


def _param_id(row):
    utt = row["utterance"][:40].replace(" ", "_")
    return f"{row['skill_id']}::{utt}"


def _params():
    for row in _ROWS:
        mark = _mark_for(row)
        marks = [mark] if mark else []
        yield pytest.param(row, id=_param_id(row), marks=marks)


@pytest.mark.parametrize("row", list(_params()))
def test_utterance_routes_to_expected_skill(row):
    expected = installed_id(row["skill_id"])
    recs = _capture(row["utterance"])
    actual = _claimant(recs, set(_FLEET_IDS))

    if actual is None:
        raise AssertionError(
            f"no fleet skill claimed the utterance {row['utterance']!r}; "
            f"expected {expected!r}. pipeline stage: {_pipeline_stage(recs)}. "
            f"messages seen: {[m.msg_type for m in recs]}")

    if actual != expected:
        raise AssertionError(
            f"cross-skill intent theft: utterance {row['utterance']!r} was "
            f"expected to route to {expected!r} but {actual!r} claimed it "
            f"instead. pipeline stage: {_pipeline_stage(recs)}. "
            f"messages seen: {[m.msg_type for m in recs]}")
