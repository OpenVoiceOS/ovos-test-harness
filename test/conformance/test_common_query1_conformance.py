"""OVOS-COMMON-QUERY-1 conformance suite.

Encodes the normative *Conformance* clauses (§14) and the message-shape rules of
OVOS-COMMON-QUERY-1 (``ovos/org/architecture/common-query.md``) as ovoscope
end-to-end assertions against the integrated OVOS stack: ovos-core's orchestrator
driving the ``ovos-common-query-pipeline-plugin`` contest, with an in-process
common-query skill fixture (``_FakeWikiSkill``) as the answering skill.

Each test class maps to one spec section; each method docstring quotes the
MUST/SHOULD clause and its level. Drivers and the xfail discipline are described
in ``_conformance.py``. Topic literals are used throughout — OVOS-COMMON-QUERY-1
defines its bus surface (§13) as literal strings and ``SpecMessage`` carries no
common-query members.

Coverage map (clause -> status against the pinned stack):
- §6.1 plugin broadcasts ``ovos.common_query.ping`` (discovery) ..... green
- §6.2 a skill claims on ``ovos.common_query.pong`` ................. green
- §9   no winner -> ``match`` None -> fallback still reached ........ green
- §9   no-winner contest does not speak a common-query answer ...... green
- §6.1 a NEW per-utterance contest pings before broadcasting ....... xfail (plugin pings only at load; never re-broadcasts during match)
- §3   reserved intent_name ``common_query`` dispatch topic ........ xfail (legacy 'question:action.<skill_id>'; and the contest crashes)
- §7.1 full-answer request ``<skill_id>:common_query`` ............. xfail (legacy 'question:query'; and the contest crashes)
- §7.1 answer on ``<skill_id>.common_query.response`` .............. xfail (legacy 'question:query.response'; and the contest crashes)
- §9   ``Match.skill_id`` == ``pipeline_id`` ....................... xfail (skill_id == answering skill; and the contest crashes)
- §9   ``slots.answer`` carries the selected answer ................ xfail (legacy match_data; and the contest crashes)
- §10  handler speaks the selected answer .......................... xfail (the contest crashes before any answer is selected)

Stack divergence note (the dominant cause of the §7–§10 xfails): in the pinned
``ovos-common-query-pipeline-plugin`` (1.1.13a1), ``handle_question`` iterates
``session.blacklisted_skills`` unconditionally. Under ``ovos-bus-client>=2.4``
that field defaults to ``None`` (not ``[]``) when unset, so every winning-contest
path raises ``TypeError: 'NoneType' object is not iterable`` and the contest
never completes — the answer is never collected, no ``Match`` is built, nothing
is spoken. The poll (ping/pong, §6) runs at plugin load (discovery) and is
observable; the answer phase (§7) onward is not reachable in this stack.
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_utils.log import LOG
from ovos_workshop.skills.ovos import OVOSSkill

from ovoscope import get_minicroft

from ._conformance import (
    PADACIOSO_HIGH,
    capture,
    first,
    reset_namespace,
    types,
    use_spec_namespace,
    utterance,
)

# Normative clauses that are not bus-observable from the integrated stack and so
# are not asserted here:
# not bus-observable: §6.2 the pong is a fast LOCAL decision (no network/IO) —
#   skill-internal timing, not visible on the bus.
# not bus-observable: §5.1/§5.2 early-start cache keying/eviction — plugin-internal
#   state with no distinct bus surface.
# not bus-observable: §7.2 collection-window sizing from latency_ms — internal
#   timing of the (here-crashing) collection phase.
# not bus-observable: §8 filtering/selection ORDER (conf -> denylist -> fast-win
#   -> rank) — internal to the contest; only the selected answer would surface.
# not bus-observable: §2.1 blocking-match — observable only as match latency.

# The common-query pipeline plugin id (entry point of the same name) and the
# fallback stages that must remain reachable when the contest finds no answer.
CQ_PIPELINE = "ovos-common-query-pipeline-plugin"
FALLBACK_LOW = "ovos-fallback-pipeline-plugin-low"
FALLBACK_HIGH = "ovos-fallback-pipeline-plugin-high"
UNKNOWN_ID = "ovos-skill-fallback-unknown.openvoiceos"

# Pipeline placing common query before fallback, per §12: a winning contest
# answers; a contest with no winner returns None and fallback still fires.
PIPELINE = [PADACIOSO_HIGH, CQ_PIPELINE, FALLBACK_HIGH, FALLBACK_LOW]

# A factual question that passes the plugin's question gate (§4): >= 3 words and
# carries a QuestionWord, so the contest actually runs.
QUESTION = "what is the capital of France"
ANSWER = "Paris is the capital of France."

WIKI_ID = "ovos-tskill-fakewiki.test"


class _FakeWikiSkill(OVOSSkill):
    """A common-query answering skill (the §11 skill-side role), wired directly on
    the bus so it is independent of any framework base class.

    Spec-conformant skill behaviour is the goal: it claims on the spec poll
    (``ovos.common_query.ping`` -> ``ovos.common_query.pong``) and emits its
    answer on the spec response topic ``<own_skill_id>.common_query.response``
    (§11). It ALSO mirrors the legacy ``question:*`` flow the installed plugin
    actually drives, so the poll/registration path runs end-to-end while the spec
    answer-collection topics can be asserted (xfail) against the same run.
    """

    def initialize(self):
        # spec + legacy poll
        self.add_event("ovos.common_query.ping", self.handle_ping)
        # legacy full-answer request (what the installed plugin sends)
        self.add_event("question:query", self.handle_query)
        # spec full-answer request (what COMMON-QUERY-1 §7.1 mandates)
        self.add_event(f"{self.skill_id}:common_query", self.handle_spec_query)
        # announce ourselves: the plugin registers a skill the moment it sees a
        # pong, so emit one on load (the plugin's own startup ping already fired
        # before this fixture was wired up).
        self.bus.emit(Message("ovos.common_query.pong",
                              {"skill_id": self.skill_id, "is_classic_cq": False},
                              {"skill_id": self.skill_id}))

    def handle_ping(self, message):
        """§6.2: claim on the spec pong, echoing the utterance and skill_id."""
        utt = message.data.get("utterance", "")
        self.bus.emit(message.reply(
            "ovos.common_query.pong",
            {"utterance": utt, "skill_id": self.skill_id,
             "can_answer": True, "is_classic_cq": False, "latency_ms": 50}))

    def handle_query(self, message):
        """Legacy full-answer flow: answer on ``question:query.response`` so the
        installed plugin selects and speaks. ALSO emit the spec response topic so
        §7.1 can be asserted against the same contest."""
        phrase = message.data.get("phrase", "")
        self.bus.emit(message.reply(
            "question:query.response",
            {"phrase": phrase, "skill_id": self.skill_id,
             "answer": ANSWER, "conf": 0.9, "searching": False,
             "callback_data": {"query": phrase, "answer": ANSWER}}))
        self.bus.emit(message.reply(
            f"{self.skill_id}.common_query.response",
            {"utterance": phrase, "skill_id": self.skill_id,
             "answer": ANSWER, "conf": 0.9}))

    def handle_spec_query(self, message):
        """§7.1: respond to the spec full-answer request on
        ``<own_skill_id>.common_query.response``."""
        utt = message.data.get("utterance", "")
        self.bus.emit(message.reply(
            f"{self.skill_id}.common_query.response",
            {"utterance": utt, "skill_id": self.skill_id,
             "answer": ANSWER, "conf": 0.9}))


_MC = None


def setUpModule():
    global _MC
    LOG.set_level("ERROR")
    use_spec_namespace()
    try:
        _MC = get_minicroft([UNKNOWN_ID], extra_skills={WIKI_ID: _FakeWikiSkill})
        # let the plugin's startup ping/pong register the fixture as a CQ skill
        time.sleep(3)
    except BaseException:
        reset_namespace()
        raise


def tearDownModule():
    try:
        if _MC is not None:
            _MC.stop()
    finally:
        reset_namespace()


def _cq(session_id: str, text: str = QUESTION, timeout: float = 8.0):
    return capture(_MC, utterance(text, session_id, PIPELINE), timeout)


# ─────────────────────────────────────────────────────────────────────────────
# §6 — The wants-to-answer poll (ping/pong)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec6Poll(TestCase):
    """§6: the plugin runs a fast broadcast poll — ``ovos.common_query.ping`` out,
    ``ovos.common_query.pong`` back — to filter the skill set down to plausible
    answerers. In the pinned plugin the poll is a load-time discovery broadcast."""

    def test_ping_broadcast(self):
        """§6.1 MUST: the plugin broadcasts the wants-to-answer poll on
        ``ovos.common_query.ping`` (observed as the plugin's discovery broadcast
        on the boot bus)."""
        boot = [m.msg_type for m in _MC.boot_messages]
        self.assertIn("ovos.common_query.ping", boot)

    def test_pong_claim(self):
        """§6.2 MUST: a skill that believes it can answer responds on
        ``ovos.common_query.pong`` — the plugin records the claimant in its
        ``common_query_skills`` registry."""
        plug = _MC.intents.pipeline_plugins.get(CQ_PIPELINE)
        self.assertIsNotNone(plug, "common-query pipeline plugin not loaded")
        self.assertIn(WIKI_ID, plug.common_query_skills)

    @pytest.mark.xfail(strict=False,
                       reason="COMMON-QUERY-1 §6.1 MUST broadcast the ping for each "
                              "accepted utterance (gate -> poll -> collect); the pinned "
                              "plugin pings only once at load for discovery and never "
                              "re-broadcasts during match, so no per-utterance ping is "
                              "observable")
    def test_ping_rebroadcast_per_utterance(self):
        """§6.1 MUST: each accepted utterance triggers a fresh poll broadcast on
        ``ovos.common_query.ping``."""
        seq = types(_cq("cq-ping-perutt"))
        self.assertIn("ovos.common_query.ping", seq)


# ─────────────────────────────────────────────────────────────────────────────
# §3 — Reserved intent_name `common_query` / dispatch topic
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3ReservedIntent(TestCase):
    """§3: the reserved intent_name ``common_query`` dispatches on
    ``<pipeline_id>:common_query`` — the plugin's own handler speaks the answer
    selected during ``match`` (§10)."""

    @pytest.mark.xfail(strict=False,
                       reason="COMMON-QUERY-1 §3 MUST dispatch the winning contest on "
                              "'<pipeline_id>:common_query'; the pinned plugin would "
                              "dispatch legacy 'question:action.<skill_id>', and in this "
                              "stack the contest crashes (blacklisted_skills None) before "
                              "any dispatch")
    def test_dispatch_topic_is_reserved_common_query(self):
        """§3 MUST: a winning contest is dispatched on the reserved topic
        ``<pipeline_id>:common_query`` (pipeline_id = the plugin's id)."""
        seq = types(_cq("cq-dispatch-topic"))
        self.assertIn(f"{CQ_PIPELINE}:common_query", seq)


# ─────────────────────────────────────────────────────────────────────────────
# §7 — Answer collection (full-answer request / response)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec7AnswerCollection(TestCase):
    """§7.1: after the poll closes, the plugin requests full answers by sending
    ``<skill_id>:common_query`` to each claimant; each skill emits its result on
    ``<skill_id>.common_query.response`` (dotted form, via ``reply``)."""

    @pytest.mark.xfail(strict=False,
                       reason="COMMON-QUERY-1 §7.1 MUST request full answers via "
                              "'<skill_id>:common_query'; the pinned plugin uses legacy "
                              "broadcast 'question:query', and the contest crashes "
                              "(blacklisted_skills None) before requesting anyway")
    def test_full_answer_request_topic(self):
        """§7.1 MUST: the plugin requests the full answer on
        ``<skill_id>:common_query`` for the claiming skill."""
        seq = types(_cq("cq-answer-request"))
        self.assertIn(f"{WIKI_ID}:common_query", seq)

    def test_full_answer_response_collected(self):
        """§7.1 MUST: the plugin collects answers on
        ``<skill_id>.common_query.response`` and selects a winner (observable as a
        spoken answer)."""
        recs = _cq("cq-answer-response")
        self.assertIn(f"{WIKI_ID}.common_query.response", types(recs))
        spoken = [m.data.get("utterance", "") for m in recs
                  if m.msg_type == "ovos.utterance.speak"]
        self.assertTrue(any(ANSWER in s for s in spoken))


# ─────────────────────────────────────────────────────────────────────────────
# §9 / §10 — Match construction and the handler (winning contest)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec9And10WinningContest(TestCase):
    """§9/§10: when an answer wins, ``match`` returns a ``Match`` whose handler
    speaks the selected answer (§10) on ``ovos.utterance.speak``, carrying
    ``skill_id`` = the plugin's own ``pipeline_id`` and ``slots.answer`` = the
    selected answer string."""

    def test_winning_contest_speaks(self):
        """§10 MUST: the plugin handler speaks the selected answer via
        ``ovos.utterance.speak``."""
        recs = _cq("cq-speak")
        spoken = [m.data.get("utterance", "") for m in recs
                  if m.msg_type == "ovos.utterance.speak"]
        self.assertTrue(any(ANSWER in s for s in spoken),
                        f"selected answer not spoken; spoke {spoken}")

    @pytest.mark.xfail(strict=False,
                       reason="COMMON-QUERY-1 §9 MUST set Match.skill_id = the plugin's "
                              "own pipeline_id; the pinned plugin sets skill_id = the "
                              "answering skill, and the contest crashes "
                              "(blacklisted_skills None) before any dispatch")
    def test_match_skill_id_is_pipeline_id(self):
        """§9 MUST: a winning ``Match`` carries ``skill_id`` = the plugin's own
        ``pipeline_id`` — observable as the dispatch context skill_id."""
        recs = _cq("cq-match-skillid")
        dispatch = first(recs, f"{CQ_PIPELINE}:common_query")
        self.assertIsNotNone(dispatch, "no reserved common_query dispatch emitted")
        self.assertEqual(dispatch.context.get("skill_id"), CQ_PIPELINE)

    @pytest.mark.xfail(strict=False,
                       reason="COMMON-QUERY-1 §9 MUST carry slots.answer = the selected "
                              "answer string; the pinned plugin carries the answer in "
                              "match_data/callback_data, and the contest crashes "
                              "(blacklisted_skills None) before any dispatch")
    def test_match_slots_answer(self):
        """§9 MUST: a winning ``Match`` carries ``slots.answer`` = the selected
        answer string — the only field the handler needs (§10)."""
        recs = _cq("cq-slots-answer")
        dispatch = first(recs, f"{CQ_PIPELINE}:common_query")
        self.assertIsNotNone(dispatch, "no reserved common_query dispatch emitted")
        slots = dispatch.data.get("slots") or {}
        self.assertEqual(slots.get("answer"), ANSWER)


# ─────────────────────────────────────────────────────────────────────────────
# §9 / §14 — No winner: match returns None, fallback still reached
# ─────────────────────────────────────────────────────────────────────────────

class TestSec9NoWinnerReachesFallback(TestCase):
    """§9 / §14: when no answer survives, the contest has no winner — ``match``
    returns ``None`` and the orchestrator proceeds to the next pipeline stage,
    including fallback. Common query never blocks fallback (§2)."""

    def test_non_question_falls_through_to_fallback(self):
        """§4/§9 MUST: a non-question utterance is gated out (no contest winner);
        the pipeline reaches the fallback catch-all, which answers (§9, §14)."""
        seq = types(_cq("cq-nowin-fallback", text="zxqw blah blah"))
        self.assertIn(f"ovos.skills.fallback.{UNKNOWN_ID}.request", seq)
        self.assertIn("ovos.utterance.handled", seq)

    def test_no_winner_does_not_speak_an_answer(self):
        """§9 MUST: a contest with no winner produces no spoken common-query
        answer — only the fallback path runs."""
        recs = _cq("cq-nowin-noanswer", text="zxqw blah blah")
        spoken = [m.data.get("utterance", "") for m in recs
                  if m.msg_type == "ovos.utterance.speak"]
        self.assertFalse(any(ANSWER in s for s in spoken),
                         f"common-query answer leaked on a no-winner contest: {spoken}")

    def test_non_question_terminates_once(self):
        """§9/§14: a gated-out (no-winner) utterance still terminates with exactly
        one ``ovos.utterance.handled`` end-marker — the stage never blocks the
        pipeline."""
        seq = types(_cq("cq-nowin-eof", text="zxqw blah blah"))
        self.assertEqual(seq.count("ovos.utterance.handled"), 1)
