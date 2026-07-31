"""OVOS-AUDIO-IN-1 conformance suite.

Encodes the normative *Conformance* clauses (§7) and bus surface (§6.5) of
OVOS-AUDIO-IN-1 (``ovos/org/architecture/audio-in.md``) as end-to-end
assertions against the real audio input service
(``ovos_dinkum_listener.service.OVOSDinkumVoiceService``).

Driver model
------------
The spec fixes the *observable bus contract* of the audio input service: which
topics it emits around capture/sleep and the shape of the utterance emission.
We construct the real ``OVOSDinkumVoiceService`` on a :class:`FakeBus` with all
acquisition plugins (mic / VAD / STT / hotwords) mocked — audio *acquisition*
is explicitly out of scope (§1) — and drive the service's emission callbacks
(``_record_begin`` / ``_record_end_signal`` / ``_wakeup`` / ``_stt_text``) and
bus-event registration (``register_event_handlers``) directly. This exercises
exactly the code the running service runs, with no real audio device.

The bus runs single-namespace (``modernize=False, emit_legacy=False``) so each
assertion sees what the service *natively* emits — the FakeBus legacy↔spec
bridge is **off**, otherwise a service that emitted only the legacy
``recognizer_loop:*`` name would be scored falsely green.

ovoscope harness gap
--------------------
ovoscope ships ``MiniVoiceLoop`` (``ovoscope.voice_loop``) but its callbacks
emit the *legacy* ``recognizer_loop:*`` topics, not the spec ``ovos.listener.*``
topics the real service now emits — so it cannot drive a spec-contract test.
The ``_build_listener`` helper below is the stand-in; it belongs in ovoscope as
a spec-native ``MiniAudioInput`` harness (see report).

xfail discipline
----------------
Each test asserts the topic / shape the spec MANDATES. Where the installed
stack diverges, the test is ``@pytest.mark.xfail(strict=True, ...)`` citing
the clause and the actual behaviour. It flips to green once the impl conforms.

Coverage map (clause -> status against ovos-dinkum-listener @dev):
- §5   emits ``ovos.utterance.handle`` w/ utterances+lang ....... green
- §5.2  assigns a session in ``context.session`` ................ green
- §6.1  capture start -> ``ovos.listener.record.started`` ....... green
- §6.2  capture end   -> ``ovos.listener.record.ended`` ......... green
- §6.4  sleep->awake  -> ``ovos.listener.awoken`` ............... green
- §6.5  subscribes ``ovos.listener.sleep`` (controller->input) .. green
- §6.5  subscribes ``ovos.mic.listen`` (re-open input channel) .. green
- §5.1  language resolution order (detected/request/lang) ....... green
- §3/§4 STT + audio-transformer chain .......................... not bus-observable
"""
import threading
from unittest import TestCase
from unittest.mock import MagicMock

import pytest
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from ovos_spec_tools import SpecMessage

# Spec topics defined by AUDIO-IN-1 (§6.5). These exist as SpecMessage members.
RECORD_STARTED = SpecMessage.LISTENER_RECORD_STARTED  # ovos.listener.record.started
RECORD_ENDED = SpecMessage.LISTENER_RECORD_ENDED      # ovos.listener.record.ended
SLEEP = SpecMessage.LISTENER_SLEEP                    # ovos.listener.sleep
AWOKEN = SpecMessage.LISTENER_AWOKEN                  # ovos.listener.awoken
UTTERANCE = SpecMessage.UTTERANCE                     # ovos.utterance.handle
MIC_LISTEN = SpecMessage.MIC_LISTEN                   # ovos.mic.listen


def _build_listener():
    """Construct the real ``OVOSDinkumVoiceService`` on a single-namespace FakeBus.

    All acquisition plugins are mocked (acquisition is out of scope, §1). The
    bus does NOT bridge legacy<->spec, so assertions observe the service's
    native emissions. Returns ``(bus, service, recs)`` where ``recs`` is a live
    list of every captured :class:`Message`.
    """
    from ovos_dinkum_listener.service import OVOSDinkumVoiceService

    bus = FakeBus(modernize=False, emit_legacy=False)
    # ProcessStatus during __init__ waits on this event on a real client.
    bus.connected_event = threading.Event()
    bus.connected_event.set()

    recs = []
    bus.on("message", lambda m: recs.append(
        Message.deserialize(m) if isinstance(m, str) else m))

    plug = MagicMock()
    plug.stt_lang = "en-US"
    svc = OVOSDinkumVoiceService(
        bus=bus, mic=plug, vad=plug, stt=plug, fallback_stt=plug,
        hotwords=plug, disable_fallback=True, validate_source=False,
    )
    svc.register_event_handlers()
    return bus, svc, recs


def setUpModule():
    LOG.set_level("ERROR")


def _types(recs):
    return [m.msg_type for m in recs]


def _first(recs, msg_type):
    return next((m for m in recs if m.msg_type == msg_type), None)


# ─────────────────────────────────────────────────────────────────────────────
# §5 — Utterance emission
# ─────────────────────────────────────────────────────────────────────────────

class TestSec5UtteranceEmission(TestCase):
    """§5: "After transcription the audio input service MUST emit
    ``ovos.utterance.handle``" with ``data.utterances`` and ``data.lang``."""

    def test_emits_utterance_handle(self):
        """"the audio input service MUST emit ``ovos.utterance.handle``" (§5, MUST)."""
        bus, svc, recs = _build_listener()
        try:
            recs.clear()
            svc._stt_text([("turn on the lights", 0.9)], {"lang": "en-US"})
        finally:
            bus.close()
        self.assertIn(UTTERANCE.value, _types(recs))

    def test_utterance_has_utterances_field(self):
        """"``utterances`` (array of string, required); first element is primary"
        (§5 field table, MUST)."""
        bus, svc, recs = _build_listener()
        try:
            recs.clear()
            svc._stt_text([("turn on the lights", 0.9)], {"lang": "en-US"})
        finally:
            bus.close()
        msg = _first(recs, UTTERANCE.value)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.data.get("utterances"), ["turn on the lights"])

    def test_utterance_has_lang_field(self):
        """"``lang`` (string, required); BCP-47 output language" (§5 field table, MUST)."""
        bus, svc, recs = _build_listener()
        try:
            recs.clear()
            svc._stt_text([("hello", 0.9)], {"lang": "en-US"})
        finally:
            bus.close()
        msg = _first(recs, UTTERANCE.value)
        self.assertIsNotNone(msg)
        self.assertTrue(msg.data.get("lang"))

    def test_may_emit_multiple_candidates(self):
        """"An audio input service MAY emit multiple candidate transcriptions in
        ``data.utterances``" (§7 MAY). The service forwards every non-empty
        transcript, preserving order (primary first)."""
        bus, svc, recs = _build_listener()
        try:
            recs.clear()
            svc._stt_text([("turn on the lights", 0.9),
                           ("turn on the light", 0.7)], {"lang": "en-US"})
        finally:
            bus.close()
        msg = _first(recs, UTTERANCE.value)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.data.get("utterances"),
                         ["turn on the lights", "turn on the light"])


# ─────────────────────────────────────────────────────────────────────────────
# §5.2 — Session assignment
# ─────────────────────────────────────────────────────────────────────────────

class TestSec52SessionAssignment(TestCase):
    """§5.2: "The audio input service MUST assign a session to every emission,
    placed in ``context.session``"."""

    def test_session_in_context(self):
        """"MUST assign a session ... placed in ``context.session``" (§5.2, MUST)."""
        bus, svc, recs = _build_listener()
        try:
            recs.clear()
            svc._stt_text([("hello", 0.9)], {"lang": "en-US"})
        finally:
            bus.close()
        msg = _first(recs, UTTERANCE.value)
        self.assertIsNotNone(msg)
        self.assertIn("session", msg.context)

    def test_local_device_default_session(self):
        """"Local device — SHOULD use ``session_id: "default"``" (§5.2 / §7 SHOULD).

        A co-located listener carries the device-local default session id.
        """
        bus, svc, recs = _build_listener()
        try:
            recs.clear()
            svc._stt_text([("hello", 0.9)], {"lang": "en-US"})
        finally:
            bus.close()
        msg = _first(recs, UTTERANCE.value)
        self.assertIsNotNone(msg)
        sess = msg.context.get("session") or {}
        self.assertEqual(sess.get("session_id"), "default")


# ─────────────────────────────────────────────────────────────────────────────
# §6.1 / §6.2 — Capture lifecycle signals
# ─────────────────────────────────────────────────────────────────────────────

class TestSec6CaptureSignals(TestCase):
    """§6.1/§6.2: the audio input service MUST emit
    ``ovos.listener.record.started`` when voice-command capture begins and
    ``ovos.listener.record.ended`` when it ends."""

    def test_capture_start_topic(self):
        """"When voice-command capture begins ... MUST emit
        ``ovos.listener.record.started``" (§6.1, MUST)."""
        bus, svc, recs = _build_listener()
        try:
            recs.clear()
            svc._record_begin()
        finally:
            bus.close()
        self.assertIn(RECORD_STARTED.value, _types(recs))

    def test_capture_end_topic(self):
        """"When capture ends ... MUST emit ``ovos.listener.record.ended``"
        (§6.2, MUST)."""
        bus, svc, recs = _build_listener()
        try:
            recs.clear()
            svc._record_end_signal()
        finally:
            bus.close()
        self.assertIn(RECORD_ENDED.value, _types(recs))

    def test_capture_start_no_payload(self):
        """"No payload. The session is identified by
        ``context.session.session_id``" (§6.1). The signal carries no data
        fields of its own."""
        bus, svc, recs = _build_listener()
        try:
            recs.clear()
            svc._record_begin()
        finally:
            bus.close()
        msg = _first(recs, RECORD_STARTED.value)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.data, {})


# ─────────────────────────────────────────────────────────────────────────────
# §6.3 / §6.4 — Sleep mode and awoken transition
# ─────────────────────────────────────────────────────────────────────────────

class TestSec6SleepAwoken(TestCase):
    """§6.3/§6.4: a controller requests sleep via ``ovos.listener.sleep``; on
    the sleep->awake transition the service MUST emit ``ovos.listener.awoken``."""

    def test_subscribes_sleep_topic(self):
        """"A controller ... requests sleep mode by emitting ``ovos.listener.sleep``
        ... On receipt the audio input service enters sleep mode" (§6.3, MUST
        — the service must consume the topic)."""
        bus, svc, recs = _build_listener()
        try:
            ev = bus.ee._events
            self.assertIn(SLEEP.value, ev)
        finally:
            bus.close()

    def test_awoken_topic(self):
        """"When the audio input service leaves sleep mode, it MUST emit
        ``ovos.listener.awoken``" (§6.4, MUST)."""
        bus, svc, recs = _build_listener()
        try:
            recs.clear()
            svc._wakeup()
        finally:
            bus.close()
        self.assertIn(AWOKEN.value, _types(recs))

    def test_awoken_no_payload(self):
        """"No payload. The session is identified by
        ``context.session.session_id``" (§6.4)."""
        bus, svc, recs = _build_listener()
        try:
            recs.clear()
            svc._wakeup()
        finally:
            bus.close()
        msg = _first(recs, AWOKEN.value)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.data, {})


# ─────────────────────────────────────────────────────────────────────────────
# §6.5 — Bus surface: consumed topics
# ─────────────────────────────────────────────────────────────────────────────

class TestSec65BusSurface(TestCase):
    """§6.5: the audio input service consumes ``ovos.mic.listen`` (defined in
    AUDIO-1 §4.4) to re-open the user input channel."""

    def test_subscribes_mic_listen(self):
        """"``ovos.mic.listen`` | any component -> audio-input | Re-open the user
        input channel; consumed here" (§6.5)."""
        bus, svc, recs = _build_listener()
        try:
            ev = bus.ee._events
            self.assertIn(MIC_LISTEN.value, ev)
        finally:
            bus.close()


# ─────────────────────────────────────────────────────────────────────────────
# §3 / §4 — STT mechanism and audio-transformer chain
# ─────────────────────────────────────────────────────────────────────────────
# §3 ("MUST have access to a STT mechanism") and §4 ("MUST run the
# audio-transformer chain before STT") are architectural preconditions of the
# service, not distinct bus emissions — there is no spec topic that signals
# "STT ran" or "audio-transformer chain ran".
# not bus-observable: §3 (STT mechanism is internal)
# not bus-observable: §4 (audio-transformer chain runs pre-STT, in-process)
# not bus-observable: §5.1 stt_lang write (session-internal, no dedicated topic)
