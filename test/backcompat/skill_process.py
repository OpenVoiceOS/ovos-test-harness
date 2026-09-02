"""Standalone skill process for the mixed-version back-compat matrix.

Runs in the **skill venv** (its own ``ovos-workshop`` + whatever
``ovos-bus-client`` that workshop's dependency floor resolves to), never in the
venv the test driver runs in. That separation is the whole point: the two
package sets have to be able to differ, which one process cannot do.

The script builds a throwaway skill directory with a single
``food.order.intent`` resource, brings up an ``OVOSSkill`` against the real
websocket bus, and registers the intent through ``register_intent_file`` — the
exact call whose topic spelling changed across workshop releases.

When the handler runs it emits two things:

* ``backcompat.skill.handled`` — a precise marker carrying the topic that
  actually fired, so the driver can tell the canonical dispatch from the
  suffixed twin and count firings (a double-fire is a failure, not a pass);
* a normal ``speak`` — the realistic "the skill answered" signal.

``SKILL_READY`` on stdout means registration finished and the driver may
dispatch. Everything else on stdout is diagnostic and is echoed by the driver
when an assertion fails.
"""
import json
import os
import sys
import tempfile
import threading
import time
from os.path import join

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message

# The converse/activate/get_response call surface used below
# (can_converse, converse, activate, get_response, speak) is present on
# EVERY workshop vintage this suite builds against, but its home class
# moved: current and dev workshop split it into a ``ConversationalSkill``
# mixin; the "stable" distro channel pin (ovos-workshop==3.4.0) predates
# that split and carries the same methods directly on ``OVOSSkill``. Import
# whichever exists rather than assuming — vintage-tolerant by the real
# symbol, the same principle ``driver.core_canonicalizes()`` already uses
# for the padatious fold, not a version-string guess.
try:
    from ovos_workshop.skills.converse import ConversationalSkill as _SkillBase
    HAS_CONVERSE_MIXIN = True
except ImportError:
    from ovos_workshop.skills.ovos import OVOSSkill as _SkillBase
    HAS_CONVERSE_MIXIN = False

#: FallbackSkill exists on every workshop vintage this suite pins -- what
#: changed (workshop 9.3.9a1, #523) is whether ``can_answer`` is abstract,
#: not whether the class itself exists. Imported unconditionally: a missing
#: FallbackSkill would be a genuinely new gap this suite has never observed
#: on any pinned vintage, and a bare ImportError here is louder than a
#: silent skip.
from ovos_workshop.skills.fallback import FallbackSkill

SKILL_ID = os.environ.get("BACKCOMPAT_SKILL_ID", "backcompat.mixed.test")
INTENT_FILE = "food.order.intent"
CONVERSE_TRIGGER_TOPIC = f"{SKILL_ID}:converse.trigger"
GET_RESPONSE_TRIGGER_TOPIC = f"{SKILL_ID}:get_response.trigger"
SPEAK_WAIT_TRIGGER_TOPIC = f"{SKILL_ID}:speak_wait.trigger"
CONTEXT_SET_TRIGGER_TOPIC = f"{SKILL_ID}:context.set.trigger"
CONTEXT_SET_DONE_TOPIC = "backcompat.skill.context.set.done"
CONTEXT_UTTERANCE_TRIGGER_TOPIC = f"{SKILL_ID}:context.probe.trigger"
CONTEXT_UTTERANCE_DONE_TOPIC = "backcompat.skill.context.probe.done"
CQ_QUERY_TOPIC = "question:query"
CQ_RESPONSE_TOPIC = "question:query.response"
CQ_PING_TOPIC = "ovos.common_query.ping"
CQ_PONG_TOPIC = "ovos.common_query.pong"
ENTITY_FILE = "food.entity"
ENTITY_SAMPLES = ["tacos", "burritos", "nachos"]
ENTITY_BLACKLIST_SAMPLES = ["them", "it"]

#: T2.4 opt-in flags (default off, so the pre-existing intent/converse/
#: get_response/speak-wait scenarios this process already serves stay
#: byte-for-byte unchanged). One process, one skill_id, several toggles --
#: matches the STRUCTURE RULE (driver/skill_process.py stays the shared
#: layer; new SCENARIOS get new test files, not a new process type).
ENABLE_FALLBACK = os.environ.get("BACKCOMPAT_ENABLE_FALLBACK") == "1"
ENABLE_CQ = os.environ.get("BACKCOMPAT_ENABLE_CQ") == "1"
ENABLE_ENTITY = os.environ.get("BACKCOMPAT_ENABLE_ENTITY") == "1"

#: Sample lines for the padatious resource. The matcher is never exercised —
#: the driver dispatches the registered topic directly, the way ovos-core's
#: ``_dispatch_match`` forwards ``match.match_type`` verbatim — but
#: ``register_intent_file`` refuses to register a resource it cannot read.
SAMPLES = ["order some tacos", "i am hungry", "grab some food"]


def _dist_version(name: str) -> str:
    from importlib.metadata import version
    return version(name)


def _requires_dist(name: str):
    from importlib.metadata import requires
    return requires(name) or []


def _make_skill_dir() -> str:
    """Lay out the minimal on-disk skill a real workshop install expects."""
    root = tempfile.mkdtemp(prefix="backcompat-skill-")
    locale = join(root, "locale", "en-us")
    os.makedirs(locale)
    with open(join(locale, INTENT_FILE), "w") as f:
        f.write("\n".join(SAMPLES) + "\n")
    if ENABLE_ENTITY:
        # register_entity_file (ovos_workshop/skills/ovos.py) also loads a
        # sibling "<entity>.blacklist" file via resources.load_blacklist_file
        # (OVOS-INTENT-2 §4.3) -- real on-disk resource, not a stubbed
        # blacklist list, so entity cell (d)'s payload-key assertion is
        # observing the real registration codepath end to end.
        with open(join(locale, ENTITY_FILE), "w") as f:
            f.write("\n".join(ENTITY_SAMPLES) + "\n")
        # register_entity_file (ovos_workshop/skills/ovos.py) strips the
        # ".entity" suffix BEFORE calling resources.load_blacklist_file(),
        # so the sibling resource this loads is "food.blacklist", not
        # "food.entity.blacklist" -- confirmed live (an earlier attempt at
        # this fixture used the wrong sibling name and silently loaded an
        # empty blacklist).
        with open(join(locale, "food.blacklist"), "w") as f:
            f.write("\n".join(ENTITY_BLACKLIST_SAMPLES) + "\n")
    return root


class BackCompatSkill(_SkillBase):
    """One intent, registered the ordinary way, plus the three interactive
    flows an old bus-only skill container leans on: converse, get_response,
    and a blocking ``speak(..., wait=True)``.

    Nothing here is version-aware except the base-class selection above
    (``_SkillBase``): the call surface itself — ``can_converse``,
    ``converse``, ``activate``, ``get_response``, ``speak``/
    wait_while_speaking — is identical across every workshop vintage this
    suite builds against, checked directly: 9.3.1a2, dev, the "testing"
    channel pin (7.0.10a1, has the ``ConversationalSkill`` split) and the
    "stable" channel pin (3.4.0, predates the split — same methods live
    directly on ``OVOSSkill``). The skill is written exactly as a skill
    author would write it, and the matrix observes what each workshop
    release does with it.
    """

    def initialize(self):
        self.register_intent_file(INTENT_FILE, self.handle_order)
        self.add_event(CONVERSE_TRIGGER_TOPIC, self.handle_converse_trigger)
        self.add_event(GET_RESPONSE_TRIGGER_TOPIC,
                       self.handle_get_response_trigger)
        self.add_event(SPEAK_WAIT_TRIGGER_TOPIC, self.handle_speak_wait_trigger)
        self.add_event(CONTEXT_SET_TRIGGER_TOPIC, self.handle_context_set_trigger)
        self.add_event(CONTEXT_UTTERANCE_TRIGGER_TOPIC,
                       self.handle_context_probe_trigger)
        if ENABLE_CQ:
            # real ovos_commonqa.opm.CommonQAService wire contract -- see
            # driver.py's module comment for why this binds the plugin's
            # actual topics directly instead of a (non-existent)
            # CommonQuerySkill base class.
            self.add_event(CQ_QUERY_TOPIC, self.handle_cq_query)
            self.add_event("ovos.common_query.ping", self.handle_cq_ping)
        if ENABLE_ENTITY:
            self.register_entity_file(ENTITY_FILE)
            # NOTE: an earlier draft also wired a second, re-register
            # trigger here to test entity cell (c)'s "exactly-once"
            # claim via a synthetic re-registration. Adversarial review
            # found the real bug fires on the FIRST call already (a
            # dual-emit producer path that trains the padatious plugin
            # twice per call, under two different names -- see
            # test_backcompat_entities.py's cell (c) docstring and
            # driver.make_padatious_pipeline), so the re-register trigger
            # was unnecessary and removed.

    # -- session/CONTEXT-1 ------------------------------------------------
    def handle_context_set_trigger(self, message: Message):
        """Mutate context through the real ``OVOSSkill.set_context`` API --
        never a hand-rolled ``add_context`` emit -- then report done so the
        driver can assert the NEXT utterance (a fresh dispatch, not this
        handler) sees it via the real intent-context surface."""
        word = message.data.get("word", "tacos")
        context_key = message.data.get("context", "food")
        self.set_context(context_key, word, origin=SKILL_ID)
        self.bus.emit(message.forward(CONTEXT_SET_DONE_TOPIC,
                                      {"skill_id": SKILL_ID,
                                       "context": context_key,
                                       "word": word,
                                       "token": message.data.get("token")}))

    def handle_context_probe_trigger(self, message: Message):
        """Report what THIS skill's own gate dialect
        (``self.alphanumeric_skill_id + context``) resolves to, so a test
        can compare the write dialect (set_context) against the gate
        dialect without guessing at either from outside the skill."""
        context_key = message.data.get("context", "food")
        gated_key = self.alphanumeric_skill_id + context_key
        self.bus.emit(message.forward(CONTEXT_UTTERANCE_DONE_TOPIC,
                                      {"skill_id": SKILL_ID,
                                       "gated_key": gated_key,
                                       "token": message.data.get("token")}))

    # -- common_query -------------------------------------------------
    def handle_cq_ping(self, message: Message):
        self.bus.emit(message.reply(
            CQ_PONG_TOPIC, {"skill_id": SKILL_ID, "is_classic_cq": False}))

    def handle_cq_query(self, message: Message):
        phrase = (message.data or {}).get("phrase", "")
        if "capital of taco" in phrase.lower():
            self.bus.emit(message.reply(
                CQ_RESPONSE_TOPIC,
                {"phrase": phrase, "skill_id": SKILL_ID,
                 "answer": "Tacoville", "conf": 0.9}))
        else:
            self.bus.emit(message.reply(
                CQ_RESPONSE_TOPIC,
                {"phrase": phrase, "skill_id": SKILL_ID, "answer": None}))

    def handle_order(self, message: Message):
        self.bus.emit(message.forward(
            "backcompat.skill.handled",
            {"topic": message.msg_type,
             "skill_id": SKILL_ID,
             "data": message.data}))
        self.speak("ordering tacos")

    # -- converse -----------------------------------------------------
    def can_converse(self, message: Message) -> bool:
        # Gating happens through activation (see handle_converse_trigger),
        # not here: a real skill almost always returns True unconditionally
        # and relies on the active-skill list to decide whether converse is
        # even offered the utterance.
        return True

    def converse(self, message: Message) -> bool:
        utterances = (message.data or {}).get("utterances", [])
        self.bus.emit(message.forward(
            "backcompat.skill.converse_fired",
            {"utterances": utterances, "skill_id": SKILL_ID}))
        return True  # claims the utterance, exactly like a real skill would

    def handle_converse_trigger(self, message: Message):
        self.activate()
        self.bus.emit(message.forward(
            "backcompat.skill.activated",
            {"skill_id": SKILL_ID, "token": message.data.get("token")}))

    # -- get_response ---------------------------------------------------
    def handle_get_response_trigger(self, message: Message):
        token = message.data.get("token")

        # ``msg`` is a real parameter (not a closure lookup) so that
        # ``dig_for_message()`` — a stack walk for a Message-typed local —
        # still finds the *trigger's* message (and therefore its session)
        # from inside this new thread's own frame. A closure variable
        # wouldn't show up: dig_for_message only inspects each frame's own
        # arguments, and a bare closure isn't one.
        def _run(msg: Message):
            # dialog='' skips speak_dialog (no dialog resource exists for
            # this throwaway skill) and goes straight to listening, per
            # OVOSSkill.get_response. num_retries=0 means: one poll window
            # (skills.get_response_timeout, pinned low by the driver's
            # shared config) and then give up — this is the bounded
            # no-answer/timeout path.
            answer = self.get_response(dialog="", num_retries=0, message=msg)
            self.bus.emit(Message(
                "backcompat.skill.get_response.done",
                {"answer": answer, "skill_id": SKILL_ID, "token": token}))

        threading.Thread(target=_run, args=(message,), daemon=True).start()

    # -- speak(wait=True) / audio-output bridging ------------------------
    def handle_speak_wait_trigger(self, message: Message):
        token = message.data.get("token")

        def _run(msg: Message):
            # Blocks inside SessionManager.wait_while_speaking until a
            # recognizer_loop:audio_output_end for this session lands on
            # the bus. Run off the bus's own dispatch thread so that this
            # client's reader keeps servicing incoming messages (including
            # that audio_output_end) while the call is parked — calling
            # this synchronously from the dispatch thread would deadlock,
            # since the same thread would need to be free to receive the
            # message it is waiting for.
            # Emitted right before the real call so the driver-side test
            # can anchor its "did it actually block" settle window to the
            # moment speak() genuinely started, instead of a fixed sleep
            # from trigger dispatch — this worker thread getting scheduled
            # at all is not bounded under a starved/pinned runner.
            self.bus.emit(Message(
                "backcompat.skill.speak_wait.started",
                {"skill_id": SKILL_ID, "token": token}))
            self.speak("ordering tacos", wait=True)
            self.bus.emit(Message(
                "backcompat.skill.speak_wait.done",
                {"skill_id": SKILL_ID, "token": token}))

        threading.Thread(target=_run, args=(message,), daemon=True).start()


def _build_skill_class():
    """Pick the class the driver actually instantiates. Fallback support is
    layered on via a dynamically-built subclass rather than always mixing
    ``FallbackSkill`` in, so the pre-existing intent/converse/get_response/
    speak-wait scenarios keep exercising the exact same class they always
    have (``BackCompatSkill`` unmodified) when ``BACKCOMPAT_ENABLE_FALLBACK``
    is unset.

    OWNER RULING (2026-08-14): a skill and the ovos-workshop it is tested
    against are NOT independently reachable versions -- a skill pins
    min/max ovos-workshop and resolves as a unit with it, the same way S
    (the skill container) already collapses workshop + its resolved
    bus-client into one axis (design §2.1's R1). There is therefore no
    "pre-can_answer skill running under a can_answer-abstract workshop"
    cell to build here: that mix is not independently reachable by real
    resolution, so this file only ever builds ONE fallback skill shape --
    a real ``can_answer`` override, exercised under whichever S-axis
    workshop vintage this combo already pins. (A stripped-down
    no-can_answer variant used to be built here for exactly that
    cross-vintage cell; removed per the ruling -- see
    ``test_backcompat_fallback.py``'s module docstring for the PR-body
    note.)
    """
    if not ENABLE_FALLBACK:
        return BackCompatSkill

    class _FallbackBackCompatSkill(FallbackSkill, BackCompatSkill):
        def can_answer(self, message: Message) -> bool:
            return True

        def initialize(self):
            BackCompatSkill.initialize(self)
            self.register_fallback(self.handle_fallback, priority=50)

        def handle_fallback(self, message: Message) -> bool:
            self.bus.emit(message.forward(
                "backcompat.skill.fallback_fired",
                {"skill_id": SKILL_ID}))
            return True

    return _FallbackBackCompatSkill


def main():
    bus = MessageBusClient()
    bus.run_in_thread()
    bus.connected_event.wait(30)

    root = _make_skill_dir()
    skill_cls = _build_skill_class()
    # Passing ``bus`` runs the full startup (including ``initialize``) inside
    # the constructor, so there is no separate ``_startup`` call to make here.
    skill_cls(skill_id=SKILL_ID, bus=bus, resources_dir=root)

    # Report what this workshop actually bound for the INTENT topic, so a
    # failing combo says which spellings existed rather than only that
    # nothing fired. The interactive-flow trigger topics
    # (converse/get_response/speak_wait .trigger) are bound on the same
    # skill_id prefix but aren't intent registrations and aren't subject to
    # the suffixed-vs-canonical drift this list exists to catch, so they're
    # filtered out here rather than turning test_pins_are_the_intended_
    # vintage's exact-match assertion into a superset check.
    bound = sorted(t for t in getattr(bus.emitter, "_events", {})
                   if t.startswith(f"{SKILL_ID}:") and not t.endswith(".trigger"))
    print("BOUND_TOPICS " + json.dumps(bound), flush=True)

    # The versions actually resolved inside THIS venv, and whether the
    # receive-side compat mirror of ovos-bus-client#271 is present. The driver
    # asserts on these: the repair strategy only works if a container pinned to
    # an old workshop still resolves a client new enough to carry the mirror.
    print("VERSIONS " + json.dumps({
        "ovos_workshop": _dist_version("ovos-workshop"),
        "ovos_bus_client": _dist_version("ovos-bus-client"),
        # The shipped #271 symbol is `_send_legacy_intent_twin` (RULE 1, the
        # send-side twin) — `_modernize_intent_topic` is RULE 2 (receive-side
        # canonicalization), also added by #271, both on MessageBusClient.
        # `_reemit_legacy_intent` was never the real name; probing for it
        # would report the mirror absent even once #271 ships.
        "has_reemit_hook": hasattr(MessageBusClient, "_send_legacy_intent_twin"),
        # which class actually supplied converse/activate/get_response —
        # the split ConversationalSkill mixin (current/dev/testing-channel
        # workshop), or the pre-split OVOSSkill (stable-channel workshop).
        "has_converse_mixin": HAS_CONVERSE_MIXIN,
        # whether this vintage has the converse/get_response call surface
        # AT ALL, on whichever base class was actually selected. Both
        # observed vintages do (see BackCompatSkill's docstring), but this
        # is the real capability check the driver's tests gate on, in case
        # some future or unobserved vintage genuinely has neither.
        "has_converse_api": hasattr(_SkillBase, "converse")
                            and hasattr(_SkillBase, "get_response"),
        # entity cell (f): this venv's OWN ovos-workshop metadata, read from
        # inside the venv that actually has it installed (a driver/core
        # process never does -- it only pins ovos-core/-padatious). A bare
        # "requires_dist" scrape, not an assumption about the string shape.
        "workshop_requires_dist": _requires_dist("ovos-workshop"),
    }), flush=True)
    print("SKILL_READY", flush=True)

    # The client already owns a reader thread from ``run_in_thread`` above;
    # ``run_forever`` would try to open the same socket twice. Park instead and
    # let the driver terminate the process.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    sys.exit(main())
