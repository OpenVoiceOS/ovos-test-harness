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

SKILL_ID = os.environ.get("BACKCOMPAT_SKILL_ID", "backcompat.mixed.test")
INTENT_FILE = "food.order.intent"
CONVERSE_TRIGGER_TOPIC = f"{SKILL_ID}:converse.trigger"
GET_RESPONSE_TRIGGER_TOPIC = f"{SKILL_ID}:get_response.trigger"
SPEAK_WAIT_TRIGGER_TOPIC = f"{SKILL_ID}:speak_wait.trigger"

#: Sample lines for the padatious resource. The matcher is never exercised —
#: the driver dispatches the registered topic directly, the way ovos-core's
#: ``_dispatch_match`` forwards ``match.match_type`` verbatim — but
#: ``register_intent_file`` refuses to register a resource it cannot read.
SAMPLES = ["order some tacos", "i am hungry", "grab some food"]


def _dist_version(name: str) -> str:
    from importlib.metadata import version
    return version(name)


def _make_skill_dir() -> str:
    """Lay out the minimal on-disk skill a real workshop install expects."""
    root = tempfile.mkdtemp(prefix="backcompat-skill-")
    locale = join(root, "locale", "en-us")
    os.makedirs(locale)
    with open(join(locale, INTENT_FILE), "w") as f:
        f.write("\n".join(SAMPLES) + "\n")
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
        self.add_event("backcompat.report_intent_state.trigger",
                       self.handle_report_intent_state)

    # -- T2.8 Cell C: enable/disable-intent round trip --------------------
    def handle_report_intent_state(self, message: Message):
        """Report this skill's LIVE ``IntentServiceInterface`` bookkeeping.

        A dedicated round trip (its own trigger/done topic pair, not a
        second listener bound to ``mycroft.skill.disable_intent`` /
        ``enable_intent`` themselves) so the driver never has to depend on
        listener registration order against workshop's own built-in
        handlers for those two topics: this skill's bus reader processes
        one message at a time in arrival order, so by the time THIS
        message is handled, any disable/enable call the driver sent before
        it has already fully run.
        """
        bound = sorted(t for t in getattr(self.bus.emitter, "_events", {})
                       if t.startswith(f"{SKILL_ID}:")
                       and not t.endswith(".trigger"))
        self.bus.emit(message.forward(
            "backcompat.report_intent_state.done",
            {"bound_topics": bound,
             "registered": [n for n, _ in self.intent_service.registered_intents],
             "detached": [n for n, _ in self.intent_service.detached_intents]}))

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


def main():
    bus = MessageBusClient()
    bus.run_in_thread()
    bus.connected_event.wait(30)

    root = _make_skill_dir()
    # Passing ``bus`` runs the full startup (including ``initialize``) inside
    # the constructor, so there is no separate ``_startup`` call to make here.
    BackCompatSkill(skill_id=SKILL_ID, bus=bus, resources_dir=root)

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
    }), flush=True)
    print("SKILL_READY", flush=True)

    # The client already owns a reader thread from ``run_in_thread`` above;
    # ``run_forever`` would try to open the same socket twice. Park instead and
    # let the driver terminate the process.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    sys.exit(main())
