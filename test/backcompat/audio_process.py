"""Standalone audio-output simulator for the mixed-version back-compat matrix.

Design: `docs/matrix-design.md <../../docs/matrix-design.md>`_ §2.6. Standing up a real
``ovos-audio`` needs a TTS plugin and a sound device; this process instead
implements ONLY the AUDIO-1 §5 output lifecycle contract, at a pinned
vintage chosen by ``BACKCOMPAT_AUDIO_VINTAGE``. It runs in its own venv
(``venv_audio`` -- ``build_venvs.sh``), which pins nothing but
``ovos-bus-client``: the vintage this file implements is BEHAVIOURAL (which
topics it emits on ``speak``), not a package pin -- there is no "old
ovos-audio" package installed anywhere in this suite.

Two vintages, both verified against real upstream source (not invented):

* ``old`` -- the pre-#165 ``ovos-audio`` 1.x contract: subscribes to the
  legacy ``speak`` topic, emits ``recognizer_loop:audio_output_start`` then,
  after a short simulated-playback delay, ``recognizer_loop:audio_output_end``.
  Verified against ``git log -S"recognizer_loop:audio_output_end"`` on
  ovos-audio (design §1.1's AUDIO-1 output-namespace row) -- this is the
  contract that existed before #165 replaced it.
* ``new`` -- today's ``ovos_audio/playback.py`` (``origin/dev``, lines
  ~78-101, ``PlaybackThread.begin_audio``/``end_audio``): subscribes to
  ``SpecMessage.SPEAK`` and emits, via ``message.forward(...)`` (so context
  -- including ``session`` -- is preserved exactly the way the real
  ``PlaybackThread`` preserves it), ``SpecMessage.AUDIO_OUTPUT_STARTED``,
  then after the same simulated delay ``SpecMessage.AUDIO_OUTPUT_ENDED``,
  and -- when the triggering message's data carries a truthy ``listen`` key,
  the same flag ``end_audio(listen, ...)`` takes -- ``SpecMessage.MIC_LISTEN``.
  Topic literals copied verbatim from ``ovos_spec_tools.messages.SpecMessage``
  (``SPEAK = "ovos.utterance.speak"``, ``AUDIO_OUTPUT_STARTED =
  "ovos.audio.output.started"``, ``AUDIO_OUTPUT_ENDED =
  "ovos.audio.output.ended"``, ``MIC_LISTEN = "ovos.mic.listen"``), not
  retyped from memory.

Follows ``skill_process.py``'s structure: a ``VERSIONS`` line on stdout
(carrying the vintage this process actually resolved to run, plus the exact
end-topic it emits -- this is what ``driver.audio_output_end_topic_probe()``
reads instead of assuming), a registration handshake (``READY`` once the
speak subscription is live), and env-driven config throughout.
"""
import json
import os
import sys
import threading
import time

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message

#: How long to pretend audio is playing between start and end. Short on
#: purpose (this is a simulator, not a latency test) but non-zero so the
#: driver's "not done before the end fires" positive control (the #26
#: mutation-proof pattern) has a real window to observe.
PLAYBACK_DELAY = float(os.environ.get("BACKCOMPAT_AUDIO_PLAYBACK_DELAY", "0.3"))

VINTAGE = os.environ.get("BACKCOMPAT_AUDIO_VINTAGE", "new")
if VINTAGE not in ("old", "new"):
    raise SystemExit(f"BACKCOMPAT_AUDIO_VINTAGE must be 'old' or 'new', got {VINTAGE!r}")

# ---- old (pre-#165 ovos-audio 1.x) contract ---------------------------------
LEGACY_SPEAK_TOPIC = "speak"
LEGACY_AUDIO_OUTPUT_START_TOPIC = "recognizer_loop:audio_output_start"
LEGACY_AUDIO_OUTPUT_END_TOPIC = "recognizer_loop:audio_output_end"

# ---- new (current ovos_audio/playback.py, AUDIO-1) contract -----------------
# Copied verbatim from ovos_spec_tools.messages.SpecMessage (origin/dev) --
# not retyped from memory, per design §2.6's instruction. Imported eagerly,
# NOT behind a try/except ImportError: venv_audio installs ovos-bus-client,
# which pulls ovos-spec-tools as its own dependency (confirmed --
# ``build_venvs.sh``'s resolved-versions listing shows ovos-spec-tools
# present in every venv this suite builds), so this import genuinely exists
# in every venv that runs this file. A silent fallback to hard-coded
# literals on ImportError would make the anti-drift point of copying these
# from SpecMessage a tautology -- if the import ever broke, the fallback
# would quietly keep passing instead of failing loudly (adversarial-review
# finding, C3).
from ovos_spec_tools.messages import SpecMessage
SPEC_SPEAK_TOPIC = SpecMessage.SPEAK
SPEC_AUDIO_OUTPUT_STARTED_TOPIC = SpecMessage.AUDIO_OUTPUT_STARTED
SPEC_AUDIO_OUTPUT_ENDED_TOPIC = SpecMessage.AUDIO_OUTPUT_ENDED
SPEC_MIC_LISTEN_TOPIC = SpecMessage.MIC_LISTEN


def _play(bus: MessageBusClient, message: Message):
    """Simulate one playback round trip for ``old`` vintage: legacy start,
    a simulated delay, legacy end -- both on the session the triggering
    ``speak`` message carried, the way a real playback would stay scoped to
    the utterance that asked for it."""
    ctx = message.context
    bus.emit(Message(LEGACY_AUDIO_OUTPUT_START_TOPIC, {}, ctx))
    time.sleep(PLAYBACK_DELAY)
    bus.emit(Message(LEGACY_AUDIO_OUTPUT_END_TOPIC, {}, ctx))


def _play_spec(bus: MessageBusClient, message: Message):
    """Simulate one playback round trip for ``new`` vintage, mirroring
    ``PlaybackThread.begin_audio``/``end_audio`` (``ovos_audio/playback.py``,
    origin/dev ~L78-101) and ``ovos_audio/service.py`` (~L366, which reads
    ``message.data.get('expect_response', False)`` as the ``listen`` flag
    ``end_audio`` takes): ``message.forward(...)`` for both start and end
    (preserves ``message.context``, exactly like the real thread does), then
    ``MIC_LISTEN`` -- also via ``forward`` -- only when the triggering
    message's data carries a truthy ``expect_response`` (the actual key
    ``OVOSSkill.speak``/``speak_dialog`` sends -- no producer in this suite
    or upstream ever sends a bare ``listen`` key; verified against
    ``ovos-audio`` and ``ovos-workshop`` ``origin/dev`` source, not assumed;
    adversarial-review finding C4)."""
    bus.emit(message.forward(SPEC_AUDIO_OUTPUT_STARTED_TOPIC))
    time.sleep(PLAYBACK_DELAY)
    bus.emit(message.forward(SPEC_AUDIO_OUTPUT_ENDED_TOPIC))
    if (message.data or {}).get("expect_response"):
        bus.emit(message.forward(SPEC_MIC_LISTEN_TOPIC))


def main():
    bus = MessageBusClient()
    bus.run_in_thread()
    bus.connected_event.wait(30)

    if VINTAGE == "old":
        speak_topic = LEGACY_SPEAK_TOPIC
        end_topic = LEGACY_AUDIO_OUTPUT_END_TOPIC
        start_topic = LEGACY_AUDIO_OUTPUT_START_TOPIC
        handler = lambda message: threading.Thread(
            target=_play, args=(bus, message), daemon=True).start()
    else:
        speak_topic = SPEC_SPEAK_TOPIC
        end_topic = SPEC_AUDIO_OUTPUT_ENDED_TOPIC
        start_topic = SPEC_AUDIO_OUTPUT_STARTED_TOPIC
        handler = lambda message: threading.Thread(
            target=_play_spec, args=(bus, message), daemon=True).start()

    bus.on(speak_topic, handler)

    # VERSIONS is what driver.audio_output_end_topic_probe() reads instead
    # of assuming an axis-A vintage from the cell id alone (design §2.6 /
    # cells.py's UNPROBED_AXES docstring) -- this is a live observation of
    # what THIS process actually subscribed to and will emit, not a
    # restatement of BACKCOMPAT_AUDIO_VINTAGE.
    print("VERSIONS " + json.dumps({
        "vintage": VINTAGE,
        "speak_topic": speak_topic,
        "audio_output_start_topic": start_topic,
        "audio_output_end_topic": end_topic,
    }), flush=True)
    print("READY", flush=True)

    # Block forever; the driver terminates this process when the test/cell
    # is done, the same lifecycle SkillProcess.stop() uses.
    threading.Event().wait()


if __name__ == "__main__":
    main()
