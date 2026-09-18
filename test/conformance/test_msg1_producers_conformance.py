"""OVOS-MSG-1 §3.3 producer cells: ``destination`` on the wire is a string.

MSG-1 §3.3 lets ``context.destination`` be a string or an array of strings.
A run of producers used to put a one-element list where a string belongs
(ovos-bus-client#368, ovos-dinkum-listener#258, ovos-docker#189,
ovos-gui-api-client#7, HiveMind-baresip-bridge#37, T-2650). Each fix was
proven with an ad hoc script on a real ``ovos-messagebus``. These cells make
that check a harness run: one cell per producer family in the pinned stack,
each reading the literal frame a raw websocket reader saw. Two cells,
labelled below, read the producer's own context object instead: the
enclosure source message and the transformers default context. They check
the stamp at its source; the wire cell of the same family checks the frame.

Families and the producer each cell drives:

============================  ==========================================
family                        producer
============================  ==========================================
enclosure API                 ``ovos_bus_client.apis.enclosure.EnclosureAPI``
listener context              ``ovos_dinkum_listener`` hotword path and
                              ``AudioTransformersService.default_context``
docker healthcheck            ``base/files/ovos-hc.py`` of ovos-docker
============================  ==========================================

The HiveMind bridge family (``HiveMind-baresip-bridge`` ``CallCallbacks``)
needs a real hivemind-core between the producer and the OVOS bus. That stack
is not pinned here, so its cell belongs to hivemind-test-harness.

Gates. ``MSG1_PRODUCER_CELLS=1`` turns the bus cells on; the integration job
sets it where ``ovos-messagebus`` is installed, so a broken install fails the
cells instead of skipping them. The docker cells also need
``OVOS_DOCKER_HC`` naming the healthcheck script, which the job checks out
from ovos-docker@dev. Under the gate a missing script is a failure, not a
skip, so a moved or renamed script in ovos-docker reddens the job instead
of thinning it. The script opens its own raw websocket at ``--url``, so
the cell hands it the server's private port.
"""
import json
import os
import subprocess
import sys
import threading
import time

import pytest
from ovos_bus_client.message import Message

pytestmark = pytest.mark.skipif(
    os.environ.get("MSG1_PRODUCER_CELLS") != "1",
    reason="MSG-1 producer cells need a real ovos-messagebus; set "
           "MSG1_PRODUCER_CELLS=1 where it is installed")

#: How long a cell waits after the producer emits before it reads the wire.
SETTLE = 1.0


class _WireReader:
    """A raw websocket client on the bus. It records every literal frame and
    has no namespace translator, so what it holds is what crossed the wire."""

    def __init__(self, port: int):
        import websocket
        self.frames = []
        self._lock = threading.Lock()
        self._open = threading.Event()
        self.ws = websocket.WebSocketApp(
            f"ws://127.0.0.1:{port}/core",
            on_open=lambda _ws: self._open.set(),
            on_message=self._on_message)
        threading.Thread(target=self.ws.run_forever, daemon=True).start()
        if not self._open.wait(30):
            raise RuntimeError("raw wire reader could not connect to the bus")

    def _on_message(self, _ws, raw):
        frame = json.loads(raw)
        with self._lock:
            self.frames.append(frame)

    def frames_of(self, topic: str) -> list:
        with self._lock:
            return [f for f in self.frames if f.get("type") == topic]

    def wait_for(self, topic: str, timeout: float = 10.0) -> list:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            got = self.frames_of(topic)
            if got:
                time.sleep(SETTLE)
                return self.frames_of(topic)
            time.sleep(0.1)
        return []

    def close(self):
        self.ws.close()


@pytest.fixture(scope="module")
def bus_server():
    from test.backcompat.driver import BusServer
    server = BusServer()
    wire = None
    try:
        wire = _WireReader(server.port)
        yield server, wire
    finally:
        if wire is not None:
            wire.close()
        server.stop()


@pytest.fixture(scope="module")
def producer_bus(bus_server):
    server, _ = bus_server
    bus = server.client()
    yield bus
    bus.close()


def _assert_string_destination(frame: dict, expected: str):
    """§3.3: the frame's ``context.destination`` is the string ``expected``,
    not a one-element list holding it."""
    ctx = frame.get("context") or {}
    dest = ctx.get("destination")
    assert isinstance(dest, str), (
        f"MSG-1 §3.3: destination on the wire is {type(dest).__name__} "
        f"{dest!r}, a string {expected!r} was expected; context={ctx!r}")
    assert dest == expected


# ─────────────────────────────────────────────────────────────────────────────
# enclosure API (ovos-bus-client#368)
# ─────────────────────────────────────────────────────────────────────────────

def _enclosure_api():
    """The producer under test is the bus-client copy, the one #368 fixed.
    ovos-bus-client 3.0.0 removes it (DeprecationWarning at import today);
    ovos-gui-api-client carries the same class from then on (#7 fixed it
    there)."""
    try:
        from ovos_bus_client.apis.enclosure import EnclosureAPI
    except ImportError:
        from ovos_gui_api_client.enclosure import EnclosureAPI
    return EnclosureAPI


class TestEnclosureAPI:

    def test_source_message_destination_is_a_string(self, producer_bus):
        """Context object, not a frame: ``EnclosureAPI._get_source_message``
        stamps the context every enclosure command inherits. Off the bus, no
        inbound message to reuse."""
        EnclosureAPI = _enclosure_api()
        api = EnclosureAPI(producer_bus, skill_id="msg1.producer.harness")
        ctx = api._get_source_message().context
        assert isinstance(ctx.get("destination"), str), ctx
        assert ctx["destination"] == "enclosure"

    def test_register_frame_destination_is_a_string(self, bus_server, producer_bus):
        """``register()`` puts ``enclosure.active_skill`` on the wire with the
        source message's context."""
        EnclosureAPI = _enclosure_api()
        _, wire = bus_server
        api = EnclosureAPI(producer_bus, skill_id="msg1.enclosure.harness")
        api.register()
        frames = [f for f in wire.wait_for("enclosure.active_skill")
                  if (f.get("data") or {}).get("skill_id") == "msg1.enclosure.harness"]
        assert frames, "enclosure.active_skill never crossed the wire"
        for frame in frames:
            _assert_string_destination(frame, "enclosure")


# ─────────────────────────────────────────────────────────────────────────────
# listener context (ovos-dinkum-listener#258)
# ─────────────────────────────────────────────────────────────────────────────

def _listener_service(bus):
    """The voice service object with only the attributes ``_hotword_audio``
    reads. ``__init__`` opens microphones and loads plugins, none of which a
    context cell needs."""
    from ovos_dinkum_listener.service import OVOSDinkumVoiceService
    svc = object.__new__(OVOSDinkumVoiceService)
    svc.bus = bus
    svc.config = {"listener": {"record_wake_words": False}}
    return svc


class TestListenerContext:

    def test_transformers_default_context_destination_is_a_string(self, producer_bus):
        """Context object, not a frame: the default context every audio
        transformer stamps on what it emits."""
        from ovos_dinkum_listener.transformers import AudioTransformersService
        ctx = AudioTransformersService(bus=producer_bus).default_context
        assert isinstance(ctx.get("destination"), str), ctx
        assert ctx["destination"] == "skills"

    def test_hotword_utterance_frame_destination_is_a_string(self, bus_server, producer_bus):
        """A wake word with an inline utterance goes to the skills service as
        ``recognizer_loop:utterance`` with ``destination`` ``"skills"``."""
        _, wire = bus_server
        token = "msg1 listener harness utterance"
        _listener_service(producer_bus)._hotword_audio(
            b"", {"key_phrase": "hey_mycroft", "utterance": token,
                  "stt_lang": "en-us"})
        frames = [f for f in wire.wait_for("recognizer_loop:utterance")
                  if token in ((f.get("data") or {}).get("utterances") or [])]
        assert frames, "recognizer_loop:utterance never crossed the wire"
        for frame in frames:
            _assert_string_destination(frame, "skills")
            assert frame["context"].get("source") == "audio"

    def test_hotword_sound_frame_destination_is_a_string(self, bus_server, producer_bus):
        """A wake word with a listen sound asks the audio service to play it
        with ``destination`` ``"audio"``."""
        _, wire = bus_server
        uri = "snd/msg1-listener-harness.wav"
        _listener_service(producer_bus)._hotword_audio(
            b"", {"key_phrase": "hey_mycroft", "sound": uri})
        frames = [f for f in wire.wait_for("mycroft.audio.play_sound")
                  if (f.get("data") or {}).get("uri") == uri]
        assert frames, "mycroft.audio.play_sound never crossed the wire"
        for frame in frames:
            _assert_string_destination(frame, "audio")


# ─────────────────────────────────────────────────────────────────────────────
# docker healthcheck (ovos-docker#189)
# ─────────────────────────────────────────────────────────────────────────────

class TestDockerHealthcheck:
    """``ovos-hc.py -s <svc>`` asks ``mycroft.<svc>.is_ready`` and exits 0 when
    a consumer answers. The frame it puts on the wire names the service as a
    string ``destination``."""

    @pytest.fixture(autouse=True)
    def _script(self):
        # the gate is on (module skipif passed), so a missing script is a
        # broken checkout, not an opt-out: fail, never skip
        self.script = os.environ.get("OVOS_DOCKER_HC")
        assert self.script, ("MSG1_PRODUCER_CELLS=1 but OVOS_DOCKER_HC is unset; "
                             "the job must name ovos-docker's base/files/ovos-hc.py")
        assert os.path.isfile(self.script), (
            f"OVOS_DOCKER_HC names {self.script!r}, which is not a file; the "
            "ovos-docker checkout moved or lost base/files/ovos-hc.py")

    def _responder(self, bus, topic):
        def answer(message):
            bus.emit(message.response({"status": True}))
        bus.on(topic, answer)
        return lambda: bus.remove(topic, answer)

    def test_healthcheck_frame_destination_is_a_string(self, bus_server, producer_bus):
        server, wire = bus_server
        remove = self._responder(producer_bus, "mycroft.audio.is_ready")
        try:
            proc = subprocess.run(
                [sys.executable, "-W", "default", self.script, "-s", "audio",
                 "--url", f"ws://127.0.0.1:{server.port}/core"],
                capture_output=True, text=True, timeout=60)
        finally:
            remove()
        frames = wire.wait_for("mycroft.audio.is_ready")
        assert frames, f"mycroft.audio.is_ready never crossed the wire; {proc.stdout} {proc.stderr}"
        for frame in frames:
            _assert_string_destination(frame, "audio")
            assert frame["context"].get("source") == "docker"
        assert proc.returncode == 0, (proc.stdout, proc.stderr)

    def test_healthcheck_fails_when_nobody_answers(self, bus_server):
        """Control: the same script with no consumer exits non-zero, so the
        green cell above is the responder's answer, not a script that always
        passes."""
        server, wire = bus_server
        proc = subprocess.run(
            [sys.executable, "-W", "default", self.script, "-s", "skills", "-t", "3",
             "--url", f"ws://127.0.0.1:{server.port}/core"],
            capture_output=True, text=True, timeout=60)
        assert proc.returncode != 0, (proc.stdout, proc.stderr)
        for frame in wire.wait_for("mycroft.skills.is_ready"):
            _assert_string_destination(frame, "skills")
