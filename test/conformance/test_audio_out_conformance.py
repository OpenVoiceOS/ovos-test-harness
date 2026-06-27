"""OVOS-AUDIO-1 conformance suite.

Encodes the normative *Conformance* clauses (§8) and bus surface (§7) of
OVOS-AUDIO-1 (``ovos/org/architecture/audio-out.md``) as end-to-end assertions
against the real audio output service (``ovos_audio.service.PlaybackService``),
driven by ovoscope's :class:`~ovoscope.audio.PlaybackServiceHarness` with a
:class:`~ovoscope.audio.MockTTS` (silent WAV, no audio device touched).

Driver model
------------
The spec fixes the *observable bus contract* of the audio output service: which
topics it subscribes to, which it emits around playback, and the shape of the
b64 / queue / play-sound / is-speaking messages. The harness runs the real
``PlaybackService`` thread on a :class:`FakeBus`; tests emit a spec topic and
assert the resulting bus traffic.

The bus runs single-namespace (``modernize=False, emit_legacy=False``) so each
assertion sees what the service *natively* subscribes to and emits. With the
FakeBus legacy↔spec bridge OFF, a service that only listens on the legacy
``mycroft.audio.*`` / ``speak:b64_audio`` name is scored honestly (xfail) rather
than being rescued by the bridge re-dispatching the spec topic to it.

Subscription assertions read ``bus.ee._events`` — the FakeBus pyee emitter's
handler registry — which is the authoritative record of what topics the
service registered a handler for.

xfail discipline
----------------
Each test asserts the topic / shape the spec MANDATES. Where the installed
``ovos-audio`` @dev diverges (it still uses legacy topic names for the
b64-delivery, queue, instant-sound, is-speaking, and audio-stop surfaces), the
test is ``@pytest.mark.xfail(strict=False, ...)`` citing the clause and the
legacy name actually used. It flips to green once ovos-audio renames the
subscription to the spec topic.

Coverage map (clause -> status against ovos-audio @dev):
- §3   subscribe ``ovos.utterance.speak``, render+play .......... green
- §5.1  emit ``ovos.audio.output.started`` on playback start .... green
- §5.2  emit ``ovos.audio.output.ended`` on playback end ........ green
- §4.4  emit ``ovos.mic.listen`` after listen:true playback ..... green
- §4.1  queue is FIFO + sequential .............................. green
- §6   subscribe ``ovos.stop`` (universal stop) ................. green
- §3.4  subscribe ``ovos.utterance.speak.b64`` ................. xfail (speak:b64_audio)
- §3.4/§4.3 emit ``ovos.audio.speech`` for b64 delivery ........ xfail (message.response)
- §4.1  subscribe ``ovos.audio.queue`` ......................... xfail (mycroft.audio.queue)
- §4.2  subscribe ``ovos.audio.play_sound`` .................... xfail (mycroft.audio.play_sound)
- §5.3  subscribe ``ovos.audio.is_speaking`` ................... xfail (mycroft.audio.speak.status)
- §6   subscribe ``ovos.audio.stop`` ........................... xfail (mycroft.audio.speech.stop)
- §3.1/§3.3 dialog/TTS transformer chains ..................... not bus-observable
"""
import base64
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_utils.log import LOG
from ovos_spec_tools import SpecMessage

from ovoscope.audio import PlaybackServiceHarness

# Spec topics with a SpecMessage member.
SPEAK = SpecMessage.SPEAK                            # ovos.utterance.speak
AUDIO_OUTPUT_STARTED = SpecMessage.AUDIO_OUTPUT_STARTED  # ovos.audio.output.started
AUDIO_OUTPUT_ENDED = SpecMessage.AUDIO_OUTPUT_ENDED  # ovos.audio.output.ended
MIC_LISTEN = SpecMessage.MIC_LISTEN                  # ovos.mic.listen
STOP = SpecMessage.STOP                              # ovos.stop

# Spec topics WITHOUT a SpecMessage member (AUDIO-1 defines them but they are
# not yet in the ovos-spec-tools enum / MIGRATION_MAP — see report). Literals
# until the enum gains them.
SPEAK_B64 = "ovos.utterance.speak.b64"   # §3.4
AUDIO_SPEECH = "ovos.audio.speech"       # §4.3
AUDIO_QUEUE = "ovos.audio.queue"         # §4.1
AUDIO_PLAY_SOUND = "ovos.audio.play_sound"  # §4.2
AUDIO_IS_SPEAKING = "ovos.audio.is_speaking"  # §5.3
AUDIO_STOP = "ovos.audio.stop"           # §6

_B64_WAV = base64.b64encode(b"RIFF\x00\x00\x00\x00WAVE").decode("utf-8")


def setUpModule():
    LOG.set_level("CRITICAL")


def _subscribed(harness, topic):
    """True if the PlaybackService registered a bus handler for ``topic``."""
    ev = harness.bus.ee._events if hasattr(harness.bus, "ee") else {}
    return topic in ev


def _no_bridge():
    """A PlaybackServiceHarness with the legacy<->spec bridge disabled."""
    return PlaybackServiceHarness(modernize=False, emit_legacy=False)


# ─────────────────────────────────────────────────────────────────────────────
# §3 — Local rendering pipeline (ovos.utterance.speak)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3LocalRendering(TestCase):
    """§3/§8: "subscribe to ``ovos.utterance.speak`` and process each Message
    through the TTS rendering pipeline for local playback"."""

    def test_subscribes_speak(self):
        """"subscribe to ``ovos.utterance.speak``" (§3, MUST)."""
        with _no_bridge() as h:
            self.assertTrue(_subscribed(h, SPEAK.value))

    def test_speak_renders_and_plays(self):
        """A received ``ovos.utterance.speak`` is synthesised and played back
        locally (§3.2 "the synthesised audio is enqueued for local playback")."""
        with _no_bridge() as h:
            h.speak("hello world", timeout=8.0)
            h.assert_spoke("hello world")


# ─────────────────────────────────────────────────────────────────────────────
# §5.1 / §5.2 — Output lifecycle signals
# ─────────────────────────────────────────────────────────────────────────────

class TestSec5LifecycleSignals(TestCase):
    """§5.1/§5.2: the service MUST emit ``ovos.audio.output.started`` when a
    playback session begins and ``ovos.audio.output.ended`` when it ends."""

    def test_output_started(self):
        """"When the first item in a playback session begins ... MUST emit
        ``ovos.audio.output.started``" (§5.1, MUST)."""
        with _no_bridge() as h:
            h.speak("starting now", timeout=8.0)
            h.assert_audio_output_started()

    def test_output_ended(self):
        """"When the queue becomes empty and the last item has completed ... MUST
        emit ``ovos.audio.output.ended``" (§5.2, MUST)."""
        with _no_bridge() as h:
            h.speak("ending now", timeout=8.0)
            h.assert_audio_output_ended()


# ─────────────────────────────────────────────────────────────────────────────
# §4.4 — Listen flag -> ovos.mic.listen
# ─────────────────────────────────────────────────────────────────────────────

class TestSec44ListenFlag(TestCase):
    """§4.4: "When a received Message carries ``listen: true``, the audio output
    service MUST emit ``ovos.mic.listen`` after all audio ... has completed and
    after ``ovos.audio.output.ended``"."""

    def test_mic_listen_after_listen_true(self):
        """"MUST emit ``ovos.mic.listen`` after ... playback" when listen:true
        (§4.4, MUST)."""
        with _no_bridge() as h:
            h.speak("answer me", expect_response=True, timeout=8.0)
            h.assert_mic_listen()

    def test_no_mic_listen_without_listen_flag(self):
        """Absent ``listen: true`` no ``ovos.mic.listen`` is emitted — the flag
        gates the re-open (§4.4)."""
        with _no_bridge() as h:
            seen = []
            h.bus.on(MIC_LISTEN.value, lambda m: seen.append(m))
            h.speak("no response wanted", expect_response=False, timeout=8.0)
            time.sleep(0.5)
            self.assertEqual(seen, [])


# ─────────────────────────────────────────────────────────────────────────────
# §6 — Stop integration
# ─────────────────────────────────────────────────────────────────────────────

class TestSec6StopIntegration(TestCase):
    """§6: "When the audio output service receives a stop signal, it clears the
    scheduled playback queue ... The stop signal topics are ``ovos.audio.stop``
    and ``ovos.stop``"."""

    def test_subscribes_universal_stop(self):
        """"``ovos.stop`` | Universal stop broadcast (OVOS-STOP-1)" (§6, MUST)."""
        with _no_bridge() as h:
            self.assertTrue(_subscribed(h, STOP.value))

    @pytest.mark.xfail(strict=False,
                       reason="AUDIO-1 §6/§7 MUST subscribe 'ovos.audio.stop'; "
                              "ovos-audio @dev subscribes legacy "
                              "'mycroft.audio.speech.stop' instead")
    def test_subscribes_audio_stop(self):
        """"``ovos.audio.stop`` | Stop audio output" (§6/§7, MUST)."""
        with _no_bridge() as h:
            self.assertTrue(_subscribed(h, AUDIO_STOP))


# ─────────────────────────────────────────────────────────────────────────────
# §3.4 / §4.3 — Remote-client rendering mode (b64)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec34RemoteRendering(TestCase):
    """§3.4: "The audio output service MUST subscribe to
    ``ovos.utterance.speak.b64`` ... the service MUST emit ``ovos.audio.speech``
    with the synthesised audio encoded as base64"."""

    @pytest.mark.xfail(strict=False,
                       reason="AUDIO-1 §3.4 MUST subscribe 'ovos.utterance.speak.b64'; "
                              "ovos-audio @dev subscribes legacy 'speak:b64_audio'")
    def test_subscribes_speak_b64(self):
        """"MUST subscribe to ``ovos.utterance.speak.b64``" (§3.4, MUST)."""
        with _no_bridge() as h:
            self.assertTrue(_subscribed(h, SPEAK_B64))

    @pytest.mark.xfail(strict=False,
                       reason="AUDIO-1 §3.4/§4.3 MUST emit 'ovos.audio.speech' for "
                              "b64 delivery; ovos-audio @dev neither subscribes the "
                              "spec b64 topic nor emits 'ovos.audio.speech' (it "
                              "answers the legacy 'speak:b64_audio' via message.response)")
    def test_emits_audio_speech_for_b64(self):
        """"the service MUST emit ``ovos.audio.speech`` (§4.3) with the
        synthesised audio encoded as base64. The audio is not enqueued and does
        not play on the local device" (§3.4, MUST)."""
        with _no_bridge() as h:
            seen = []
            h.bus.on(AUDIO_SPEECH, lambda m: seen.append(m))
            h.bus.emit(Message(SPEAK_B64,
                               {"utterance": "remote hello", "lang": "en-US"}))
            time.sleep(3.0)
            self.assertTrue(seen, "no ovos.audio.speech emitted for speak.b64")
            self.assertIn("audio", seen[0].data)


# ─────────────────────────────────────────────────────────────────────────────
# §4.1 — Scheduled playback queue (ovos.audio.queue)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec41QueuedSound(TestCase):
    """§4.1/§8: "support queued sound playback via ``ovos.audio.queue``"."""

    @pytest.mark.xfail(strict=False,
                       reason="AUDIO-1 §4.1/§7 MUST subscribe 'ovos.audio.queue'; "
                              "ovos-audio @dev subscribes legacy 'mycroft.audio.queue'")
    def test_subscribes_audio_queue(self):
        """"``ovos.audio.queue`` | any component -> audio | Queue a sound for
        scheduled playback" (§4.1/§7, MUST)."""
        with _no_bridge() as h:
            self.assertTrue(_subscribed(h, AUDIO_QUEUE))

    def test_queue_is_fifo_sequential(self):
        """"FIFO. Items are dequeued in the order they were enqueued.
        Sequential. Each item plays to completion before the next item begins"
        (§4.1, MUST). Two ``ovos.utterance.speak`` items play in enqueue order."""
        with _no_bridge() as h:
            h.speak("first sentence", timeout=8.0)
            h.speak("second sentence", timeout=8.0)
            self.assertEqual(h.mock_tts.spoken_utterances,
                             ["first sentence", "second sentence"])


# ─────────────────────────────────────────────────────────────────────────────
# §4.2 — Instant sounds (ovos.audio.play_sound)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec42InstantSound(TestCase):
    """§4.2/§8: "play instant sounds immediately on ``ovos.audio.play_sound``
    without queuing or stopping scheduled playback"."""

    @pytest.mark.xfail(strict=False,
                       reason="AUDIO-1 §4.2/§7 MUST subscribe 'ovos.audio.play_sound'; "
                              "ovos-audio @dev subscribes legacy "
                              "'mycroft.audio.play_sound'")
    def test_subscribes_play_sound(self):
        """"``ovos.audio.play_sound`` | any component -> audio | Play a sound
        immediately" (§4.2/§7, MUST)."""
        with _no_bridge() as h:
            self.assertTrue(_subscribed(h, AUDIO_PLAY_SOUND))


# ─────────────────────────────────────────────────────────────────────────────
# §5.3 — Speaking-status query (ovos.audio.is_speaking)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec53SpeakingStatus(TestCase):
    """§5.3: "A component MAY query whether the audio output service is
    currently speaking by emitting ``ovos.audio.is_speaking`` ... The service
    replies with ``{speaking: bool}``"."""

    @pytest.mark.xfail(strict=False,
                       reason="AUDIO-1 §5.3 query topic is 'ovos.audio.is_speaking'; "
                              "ovos-audio @dev answers the legacy query "
                              "'mycroft.audio.speak.status' and replies "
                              "'mycroft.audio.is_speaking'")
    def test_subscribes_is_speaking(self):
        """The service answers the ``ovos.audio.is_speaking`` query topic
        (§5.3, the query surface a component MAY use)."""
        with _no_bridge() as h:
            self.assertTrue(_subscribed(h, AUDIO_IS_SPEAKING))


# ─────────────────────────────────────────────────────────────────────────────
# §3.1 / §3.3 — Transformer chains (not bus-observable)
# ─────────────────────────────────────────────────────────────────────────────
# §3.1 (dialog-transformer chain before TTS, SHOULD) and §3.3 (TTS-transformer
# chain after synthesis, SHOULD) run in-process inside the rendering pipeline;
# a no-op chain emits no bus topic, so there is nothing to observe on the bus
# without injecting a probe transformer plugin (out of scope for a bus-contract
# suite).
# not bus-observable: §3.1 dialog-transformer chain
# not bus-observable: §3.3 TTS-transformer chain
# not bus-observable: §3.2 TTS synthesis fallback (SHOULD, deployment-internal)
#
# §4.4/§6 "suppress ovos.mic.listen when playback ends due to a stop signal"
# (MUST) is not *deterministically* observable with MockTTS: the silent WAV
# completes playback in ~0ms, so a stop signal almost always lands after the
# utterance has already finished (and after mic.listen has fired) rather than
# mid-playback. Reliably exercising the stop-during-playback path needs a TTS
# whose audio has a non-trivial, controllable duration — a harness capability
# ovoscope does not yet expose (see report). Asserting it against MockTTS would
# be a flaky race, so it is documented here rather than written as a vacuous or
# nondeterministic test.
# not reliably bus-observable (harness gap): §4.4/§6 stop suppresses ovos.mic.listen
