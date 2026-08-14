"""Shared plumbing for the mixed-version back-compat matrix.

The driver process **is** the core side of a combo: it runs under the core
venv, so ``ovos-core`` / ``ovos-padatious`` / ``ovos-bus-client`` here are the
versions that combo pins. The skill side lives in a separate venv and is
reached only over a real websocket, which is what makes two package sets
observable at once.

Nothing in this module mocks the bus. A real ``ovos-messagebus`` is started on
a free port and both sides connect to it.

Design references below (``design §X.Y``) are to ``docs/matrix-design.md``.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from threading import Event
from typing import Optional

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message

SKILL_ID = "backcompat.mixed.test"
INTENT_FILE = "food.order.intent"
LEGACY_TOPIC = f"{SKILL_ID}:{INTENT_FILE}"
CANONICAL_TOPIC = f"{SKILL_ID}:food.order"

#: Interactive-flow topics. converse and get_response are genuinely routed
#: through the CORE side's own ``ovos_core.intent_services.converse_service.
#: ConverseService`` (see ``make_converse_service`` below) — real per-version
#: core code decides the match and its topic, the same way ``dispatch()``
#: already gets the intent topic from the real padatious module rather than
#: assuming it. These constants are the *expected* topics, asserted against
#: what the real service actually produces, not substituted for it.
#: wait_while_speaking is legitimately audio-service territory with nothing
#: core-side to route through, so it stays a direct simulation.
CONVERSE_TRIGGER_TOPIC = f"{SKILL_ID}:converse.trigger"
#: What ``ConverseService.handle_converse`` forwards to an active skill —
#: asserted, not assumed, against ``match.match_type`` from the real
#: converse-service ``.match()`` call. A fixed literal, not derived from a
#: registered intent name, so it never touches padatious's registration-time
#: canonicalization.
#: What ``ConverseService.match()`` itself returns as ``match_type`` for a
#: converse candidate — the pipeline-facing dispatch topic, bound in
#: ``ConverseService.__init__`` (``self.bus.on("converse:skill",
#: self.handle_converse)``). ``handle_converse`` is what then re-emits the
#: SKILL-facing ``CONVERSE_REQUEST_TOPIC`` below; the two are different hops
#: of the same real round trip.
CONVERSE_MATCH_TOPIC = "converse:skill"
CONVERSE_REQUEST_TOPIC = f"{SKILL_ID}.converse.request"
CONVERSE_RESPONSE_TOPIC = "skill.converse.response"
CONVERSE_FIRED_TOPIC = "backcompat.skill.converse_fired"
ACTIVATED_TOPIC = "backcompat.skill.activated"
GET_RESPONSE_TRIGGER_TOPIC = f"{SKILL_ID}:get_response.trigger"
#: What ``ConverseService.match()`` returns as ``match_type`` once a skill
#: has entered response-mode (``OVOSSkill.get_response`` -> ``skill.converse.
#: get_response.enable`` -> ``ConverseService.handle_get_response_enable`` ->
#: ``session.enable_response_mode``) — asserted against the real match, not
#: assumed. Also the literal topic ``OVOSSkill.__handle_get_response`` binds
#: on the skill side (``self.add_event(f"{skill_id}.converse.get_response",
#: ...)``), unchanged across every venv this suite builds.
GET_RESPONSE_ANSWER_TOPIC = f"{SKILL_ID}.converse.get_response"
GET_RESPONSE_DONE_TOPIC = "backcompat.skill.get_response.done"
#: The two real bus events that bracket a single get_response round trip on
#: the skill side (``OVOSSkill.get_response`` emits both directly, via
#: ``message.forward(...)`` -- see ovos_workshop/skills/ovos.py). Watching
#: these as actual event evidence, instead of only sampling
#: ``SessionManager.sessions`` on a timer, is what lets the receiving test
#: tell "the round trip never happened" apart from "it happened, but the
#: sampling window closed before a poll landed inside it".
GET_RESPONSE_ENABLE_TOPIC = "skill.converse.get_response.enable"
GET_RESPONSE_DISABLE_TOPIC = "skill.converse.get_response.disable"
SPEAK_WAIT_TRIGGER_TOPIC = f"{SKILL_ID}:speak_wait.trigger"
SPEAK_WAIT_DONE_TOPIC = "backcompat.skill.speak_wait.done"
#: Emitted by the skill subprocess right before it calls ``self.speak(...,
#: wait=True)`` (see ``skill_process.py``'s ``handle_speak_wait_trigger``).
#: The positive control below (proving speak(wait=True) has not already
#: returned) needs to anchor its settle window to the real moment the call
#: began, not to a fixed sleep measured from the trigger dispatch: under a
#: starved/pinned runner the worker thread itself can take longer than a
#: fixed sleep just to get SCHEDULED, which would let the positive control
#: pass for the wrong reason (nothing had happened yet, rather than the call
#: genuinely blocking) — see test_speak_wait_unblocks_on_audio_output_end.
SPEAK_WAIT_STARTED_TOPIC = "backcompat.skill.speak_wait.started"
#: What ``SessionManager.wait_while_speaking`` listens for in both venvs
#: (``ovos_bus_client.session``, identical topic in the old and new skill
#: venvs since both resolve a current bus-client off the workshop floor —
#: the same "old container still gets a modern client" property the rest of
#: this suite depends on). This is the CURRENT core's audio-output-end
#: contract; the driver plays audio-service here.
AUDIO_OUTPUT_END_TOPIC = "recognizer_loop:audio_output_end"
#: The legacy ``begin`` counterpart, and the topic ``audio_process.py``'s
#: ``old`` vintage subscribes ``speak`` and emits both of these against.
AUDIO_OUTPUT_START_TOPIC = "recognizer_loop:audio_output_start"
LEGACY_SPEAK_TOPIC = "speak"
#: The spec-side counterparts (design §2.6 / AUDIO-1), for the A=new bridge
#: scenarios: an old-vintage skill container's ``SessionManager.
#: wait_while_speaking`` never subscribes to ``AUDIO_OUTPUT_END_TOPIC``'s
#: spec counterpart directly -- the only way it unblocks against a
#: spec-only emitter is the bus-client ``NamespaceTranslator``'s
#: receive-side modernize/emit_legacy bridge (design §1.1's bus-client
#: namespace-dual-emit row). Copied verbatim from
#: ``ovos_spec_tools.messages.SpecMessage`` (same source ``audio_process.py``
#: copies from) -- LAZILY, unlike the legacy topics above. driver.py is
#: imported at collection time by every cell, INCLUDING the four channel
#: cells (``venv_core_stable``/``venv_core_testing``, ``build_venvs.sh``'s
#: ``mkvenv_channel`` calls): those install only
#: ``ovos-core ovos-padatious ovos-messagebus`` off the OVOS distro's own
#: V0 (pre-spec) constraints file, with NO ``ovos-spec-tools`` guaranteed --
#: that is the whole point of a V0 cell (confirmed live: CI collection of
#: ``dev-skill/stable-core`` failed with ``ModuleNotFoundError:
#: No module named 'ovos_spec_tools'`` when this was a top-level import,
#: adversarial-review follow-up to C3). A bare ``except ImportError:
#: <hard-coded literal>`` fallback would silently restore the exact
#: tautology C3 removed, so the fix is NOT to resurrect that fallback --
#: it's to defer the import to the functions that actually need a spec
#: topic (only ever called from A=new scenarios, which V0-channel cells
#: never reach), and raise loudly, naming the missing package, if one ever
#: is reached without ovos-spec-tools installed.
def _spec_message():
    """Lazy accessor for ``ovos_spec_tools.messages.SpecMessage``. Raises a
    clear ``RuntimeError`` (not a tautological hard-coded fallback) naming
    the current cell and the missing package if called somewhere
    ovos-spec-tools genuinely isn't installed -- see the module comment
    above for why this must be lazy, not why it should be silent."""
    try:
        from ovos_spec_tools.messages import SpecMessage
    except ImportError as e:
        combo = os.environ.get("BACKCOMPAT_COMBO", "<unset>")
        raise RuntimeError(
            f"cell {combo!r} tried to resolve a spec-side (AUDIO-1) audio "
            f"topic, which needs ovos_spec_tools.messages.SpecMessage, but "
            f"ovos-spec-tools is not installed in this venv. V0-channel "
            f"cells (stable/testing constraints) predate the spec surface "
            f"entirely and must never reach an A=new scenario -- if this "
            f"fired, either a V0 cell's test selection is wrong, or "
            f"ovos-spec-tools is unexpectedly missing from a boundary "
            f"cell's venv.") from e
    return SpecMessage


def audio_output_ended_spec_topic() -> str:
    """The spec-side ``AUDIO_OUTPUT_ENDED`` topic (design §2.6). Lazy -- see
    the module comment above ``_spec_message``."""
    return _spec_message().AUDIO_OUTPUT_ENDED


def audio_output_started_spec_topic() -> str:
    """The spec-side ``AUDIO_OUTPUT_STARTED`` topic, needed by the C1
    simulator-emission tests (test_mixed_version_matrix.py): they drive a
    real ``SPEAK`` message onto the bus and assert the audio_process.py
    subprocess itself -- not the test -- is what emits these, in order."""
    return _spec_message().AUDIO_OUTPUT_STARTED


def speak_spec_topic() -> str:
    """The spec-side ``SPEAK`` topic (``SpecMessage.SPEAK``)."""
    return _spec_message().SPEAK


def mic_listen_spec_topic() -> str:
    """The spec-side ``MIC_LISTEN`` topic (``SpecMessage.MIC_LISTEN``)."""
    return _spec_message().MIC_LISTEN

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_SCRIPT = os.path.join(HERE, "skill_process.py")

#: How long to wait for the skill venv to import workshop and register. A cold
#: interpreter plus resource loading is slow; this is not a latency assertion.
SKILL_BOOT_TIMEOUT = 120
#: How long to wait for a handler to answer once the dispatch is on the wire.
#: Generous on purpose — a short window would turn CI jitter into a fake
#: "compat is broken" result, and this suite must only fail for real reasons.
DISPATCH_TIMEOUT = 10
#: get_response's own poll window (see ``make_shared_config``), and the
#: no-answer test's timeout budget derives from it. Short but not adversarial
#: — long enough that a slow CI runner's 0.1s poll loop still lands inside it.
#: Raised from 2s to 6s (see test_get_response_receives_the_answer_utterance's
#: event-based re-arm logic): a starved runner could get the skill's real
#: enable->disable round trip processed back-to-back, in one scheduling burst
#: of the driver process's bus handler thread, entirely between two of the
#: test's 50ms polls of SessionManager.sessions -- a real round trip the
#: sampled poll still never catches mid-flight. A wider window does not fix
#: that (it is a scheduling race, not a slowness budget), but it does make it
#: rarer, and the retry path below uses the enable/disable events themselves
#: as the actual evidence for that remaining race.
GET_RESPONSE_TIMEOUT = 6


def free_port() -> int:
    """Grab a port the messagebus can own for one test run."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def core_canonicalizes() -> bool:
    """Whether the core-side stack folds the suffixed intent id at registration.

    This is the single behaviour that decides which topic a combo puts on the
    wire, and it lives in the padatious **pipeline plugin**, not in ovos-core:
    ``ovos-core`` forwards ``match.match_type`` verbatim
    (``IntentService._dispatch_match``), so the spelling is whatever the engine
    registry holds.

    ``ovos-padatious >= 2.0.1a1`` folds ``<skill_id>:<file>.intent`` onto
    ``<skill_id>:<file>`` inside ``register_intent``, so every match is
    canonical by construction. Older releases keep whatever the skill sent.

    The probe is the real symbol rather than a version string, so the matrix
    keeps telling the truth if the fold ever moves or is reverted.
    """
    import ovos_padatious.opm as opm
    return hasattr(opm, "_dealias_intent_name")


def emitter_side_has_reemit_hook() -> bool:
    """Whether THIS (driver/core-side) ``MessageBusClient`` carries #271's
    emitter-side twin symbol.

    ``skill_process.py`` already probes ``hasattr(MessageBusClient,
    "_send_legacy_intent_twin")`` on the SKILL-side client, but the actual
    canonical dispatches this suite drives are emitted from the DRIVER's own
    client (``server.client()`` / ``dispatch``/``dispatch_match``), not the
    skill subprocess's. The skill-side probe therefore proves nothing about
    where the twin actually fires; this is the equivalent check on the
    process that really calls ``emit()`` for those dispatches.
    """
    return hasattr(MessageBusClient, "_send_legacy_intent_twin")


def adapt_consumes_intent4_keywords():
    """Whether the installed ovos-adapt-parser's keyword engine subscribes
    to the INTENT-4 keyword registration topic (design §2.5's M/adapt
    probe): the real symbol is ``SpecMessage.INTENT_REGISTER_KEYWORD``
    handling inside the installed ``ovos_adapt``, not a version string.

    Returns ``None`` -- not ``True``/``False`` -- when ``ovos-adapt-parser``
    or ``ovos-spec-tools`` are not importable in this venv. None of the
    venvs ``build_venvs.sh`` builds today pin ``ovos-adapt-parser`` (only
    ``ovos-padatious`` -- see its header comment); standing up a real
    M/adapt axis cell is out of this file's scope. This probe exists so
    ``test_pins_are_the_intended_vintage`` can record what it sees today
    without inventing an axis that isn't reachable yet.
    """
    try:
        import ovos_adapt.opm as adapt_opm
    except ImportError:
        return None
    try:
        from ovos_spec_tools.messages import SpecMessage
    except ImportError:
        return None
    topic = getattr(SpecMessage, "INTENT_REGISTER_KEYWORD", None)
    if topic is None:
        return None
    import inspect
    try:
        src = inspect.getsource(adapt_opm)
    except (OSError, TypeError):
        return None
    return topic in src


def audio_output_end_topic_probe(audio: Optional["AudioProcess"] = None):
    """The A/audio axis's real-symbol probe (design §2.6), now wired to a
    live ``audio_process.py`` subprocess instead of the T2.3 placeholder.

    ``audio`` is an already-started :class:`AudioProcess` -- its own
    ``VERSIONS`` line (read at startup, the same handshake
    ``SkillProcess`` uses) is what this returns, i.e. the end-topic THAT
    PROCESS actually subscribed to emit, not an assumption derived from
    the cell id.

    Returns ``None`` -- never a guess -- when no audio process is running
    for this test (most scenarios don't spawn one; only the speak-wait
    scenario does, design §2.4's pruning table). Callers must keep
    treating ``None`` as "axis not exercised in this test", never as a
    pass or a fail. This is why ``"A"`` stays in ``cells.UNPROBED_AXES``:
    the probe is genuinely live only while the audio process is actually
    running, not for every cell unconditionally (design instruction:
    "probe live when the process runs, axis stays unprobed otherwise").
    """
    if audio is None:
        return None
    return audio.versions.get("audio_output_end_topic")


def dispatch_topic_for(registered_name: str) -> str:
    """The topic this core stack would dispatch for ``registered_name``."""
    if not core_canonicalizes():
        return registered_name
    import ovos_padatious.opm as opm
    return opm._dealias_intent_name(registered_name)


def make_converse_service(bus: MessageBusClient):
    """Instantiate the CORE side's own converse pipeline plugin on ``bus``.

    This is real, per-version ``ovos-core`` code — ``ConverseService`` is the
    plugin ``ovos-core``'s ``IntentService`` actually asks to match converse
    and get_response candidates — running in the driver process, i.e. under
    whichever core venv this combo pins. Deciding the match and its topic is
    left entirely to this object; the driver only forwards ``match.match_type``
    verbatim afterwards, the same shortcut ``dispatch()`` already takes for
    intents (``IntentService._dispatch_match`` also forwards verbatim).

    An empty config is deliberate: every knob ``ConverseService`` reads has a
    sane built-in default (see its own ``self.config.get(..., default)``
    calls), and pulling a real ``ovos_config.Configuration()`` here would tie
    this fixture to the driver process's ambient config instead of the
    throwaway one this suite already builds per-run.

    Imported lazily, like ``core_canonicalizes()`` imports ``ovos_padatious``
    lazily: ``ovos-core`` is a core-venv-only dependency, and this keeps a
    bare ``pytest --collect-only`` (no combo selected, no core venv) from
    failing at collection.

    The constructor signature itself is not stable across the vintages this
    suite spans: ``ovos-core==1.3.1`` (the "stable" channel pin) takes only
    ``bus`` and pulls a real ``Configuration()`` internally — no ``config``
    kwarg exists yet (added later alongside the plugin-pipeline refactor).
    Probe the real signature rather than assuming one, the same principle
    ``core_canonicalizes()`` already applies to the padatious fold.
    """
    import inspect
    from ovos_core.intent_services.converse_service import ConverseService
    if "config" in inspect.signature(ConverseService.__init__).parameters:
        return ConverseService(bus=bus, config={})
    return ConverseService(bus=bus)


def core_has_pipeline_match_api() -> bool:
    """Whether this core venv's ``ConverseService`` exposes the ``.match()``
    plugin-pipeline API the rest of this module's converse/get_response
    helpers are built on.

    ``ovos-core==1.3.1`` (the "stable" distro channel core pin) predates the
    plugin-pipeline refactor entirely: it has no ``.match()`` at all, and
    its own converse/get_response entry points
    (``ConverseService.converse`` / ``.converse_with_skills``) block
    synchronously and drive the bus round trip internally, rather than
    handing back an ``IntentHandlerMatch`` for the caller to forward. That
    is a different object model, not a smaller version of this one — real
    per-version behavior discovered directly from that release's source,
    not assumed. Adapting ``converse_match``/``dispatch_match`` to also
    speak that older shape is future work; for now this is the real
    capability gate the converse/get_response tests skip on, with their own
    reason (see ``_require_pipeline_match_api`` in the test module) —
    deliberately NOT the ``#271`` xfail marker, which is about something
    else entirely.
    """
    from ovos_core.intent_services.converse_service import ConverseService
    return hasattr(ConverseService, "match")


def session_context(session_id: str) -> dict:
    """Message context carrying the CURRENT live session's full state.

    This is the fix for a real discovery, not cosmetic: ``SessionManager.
    _store`` folds an incoming snapshot onto the live singleton by fully
    rebuilding it from ``other.serialize()``
    (``Session.update_from``) — a bare ``{"session_id": ...}`` context wipes
    every other field (``active_skills``, ``response_mode``, ...) back to
    defaults, it does not merge additively. In a real deployment this is
    harmless: every message a skill forwards already carries the FULL
    session forward, because the message that reached the skill in the
    first place (an intent dispatch, a ``.converse.request``) was built by
    core code that always serializes the live session onto it (see
    ``ConverseService.handle_converse``: ``message.context["session"] =
    session.serialize()`` before it ever reaches the skill). The driver has
    to reproduce that same discipline for its own trigger messages, or it
    would be testing an artifact of a thin fixture message, not the real
    session contract.
    """
    from ovos_bus_client.session import Session, SessionManager
    session = SessionManager.sessions.get(session_id)
    if session is None:
        # first message of a flow: no state yet, just the id the flow will
        # accumulate state under from here on.
        session = Session(session_id=session_id)
    return {"session": session.serialize()}


def wait_for_active_skill(session_id: str, skill_id: str,
                          timeout: float = DISPATCH_TIMEOUT) -> bool:
    """Poll the live session until ``skill_id`` shows up as active.

    A fixed sleep before calling ``converse_match`` was flaky under load
    (this suite runs several combos back to back, and CI/dev-machine
    scheduling jitter is real): ``intent.service.skills.activate`` is a bus
    round trip like everything else here, so wait for the actual evidence
    instead of guessing a delay long enough.
    """
    from ovos_bus_client.session import SessionManager
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session = SessionManager.sessions.get(session_id)
        if session is not None and skill_id in [s[0] for s in session.active_skills]:
            return True
        time.sleep(0.05)
    return False


def wait_for_response_mode(session_id: str, skill_id: str,
                           timeout: float = DISPATCH_TIMEOUT) -> bool:
    """Poll the live session until ``skill_id`` is the response-mode holder.

    Same rationale as :func:`wait_for_active_skill`: real evidence instead
    of a fixed sleep ahead of a real ``get_response`` enable round trip.

    Session's response-mode storage is not the same shape across every
    ``ovos-bus-client`` this suite pairs a core venv with: the structured
    single-holder ``response_mode`` dict (OVOS-CONVERSE-1 §2.2) is a later
    field. The "testing" distro channel's core pin resolves
    ``ovos-bus-client==1.5.0``, old enough that ``Session`` has no
    ``response_mode`` attribute at all — only the older ``utterance_states``
    dict (``{skill_id: "RESPONSE"}``), which ``enable_response_mode`` still
    writes on that vintage. Check for the real attribute rather than
    assuming the new shape, same principle as
    ``core_has_pipeline_match_api()``.
    """
    from ovos_bus_client.session import SessionManager
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session = SessionManager.sessions.get(session_id)
        if session is not None:
            response_mode = getattr(session, "response_mode", None)
            if response_mode and response_mode.get("skill_id") == skill_id:
                return True
            if not hasattr(session, "response_mode"):
                # pre-OVOS-CONVERSE-1 Session: utterance_states is a plain
                # dict, not the modern derived view. UtteranceState.RESPONSE
                # serializes to the lowercase string "response" on this
                # vintage (checked directly against ovos-bus-client==1.5.0's
                # installed source) — not the class attribute name.
                states = getattr(session, "utterance_states", {}) or {}
                if states.get(skill_id) == "response":
                    return True
        time.sleep(0.05)
    return False


def converse_match(converse_service, utterances, lang: str, session_id: str):
    """Ask the real converse service to match, the way ``IntentService`` would
    before falling through to intent matching.

    Returns the ``IntentHandlerMatch`` (or ``None``) straight from the real
    per-version core code — nothing here decides the topic.

    Deliberately does NOT build a message carrying only ``{"session_id":
    session_id}``: ``SessionManager._store`` folds an incoming snapshot onto
    the live singleton with *last-writer-wins* semantics
    (``Session.update_from``), so a bare session_id snapshot — the same
    shorthand ``dispatch()`` uses for the stateless intent-dispatch case —
    would silently reset ``active_skills``/response-mode back to empty right
    before ``.match()`` reads them. This pulls the live, already-mutated
    session (the one ``handle_activate_skill_request`` /
    ``handle_get_response_enable`` updated in place) and serializes ITS
    current state onto the outbound message instead.
    """
    message = Message("recognizer_loop:utterance",
                      {"utterances": utterances, "lang": lang},
                      session_context(session_id))
    return converse_service.match(utterances, lang, message)


def dispatch_match(bus: MessageBusClient, match) -> None:
    """Forward a real ``IntentHandlerMatch`` the way ``IntentService.
    _dispatch_match`` forwards ``match.match_type`` verbatim — no topic
    assumption, just relaying what the real core-side match already decided.
    """
    session_id = None
    if getattr(match, "updated_session", None) is not None:
        session_id = match.updated_session.session_id
    context = {"session": {"session_id": session_id}} if session_id else {}
    bus.emit(Message(match.match_type, match.match_data, context))


def make_shared_config(port: int) -> str:
    """Write a throwaway ``mycroft.conf`` pinning the bus to ``port``.

    Neither the bus server nor the client reads a port from the environment,
    and both venvs must agree on one. An ``XDG_CONFIG_HOME`` pointed at this
    directory is the one knob that reaches every process regardless of which
    venv it runs in, and it keeps the run off the developer's real bus.
    """
    root = tempfile.mkdtemp(prefix="backcompat-xdg-")
    conf_dir = os.path.join(root, "mycroft")
    os.makedirs(conf_dir)
    with open(os.path.join(conf_dir, "mycroft.conf"), "w") as f:
        json.dump({"websocket": {"host": "127.0.0.1", "port": port,
                                 "route": "/core", "ssl": False},
                   # get_response's internal poll defaults to 20s
                   # (skills.get_response_timeout); pinned low here so the
                   # no-answer / timeout-path test stays a tight bound
                   # instead of a 20s sleep per combo.
                   "skills": {"get_response_timeout": GET_RESPONSE_TIMEOUT}}, f)
    return root


class BusServer:
    """A real ``ovos-messagebus`` on a private port."""

    def __init__(self):
        self.port = free_port()
        self.xdg = make_shared_config(self.port)
        env = dict(os.environ, XDG_CONFIG_HOME=self.xdg)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "ovos_messagebus"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env)
        self._wait_until_accepting()

    def _wait_until_accepting(self, timeout: int = 60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    "messagebus died during startup:\n"
                    + (self.proc.stdout.read() if self.proc.stdout else ""))
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.25)
        raise RuntimeError(f"messagebus never accepted on port {self.port}")

    def client(self, emit_legacy: Optional[bool] = None) -> MessageBusClient:
        """A driver-side bus client, optionally overriding #271's rule 1.

        bus-client#271 rule 1 (the legacy ``.intent``-suffixed twin) fires
        inside ``MessageBusClient.emit()``, in whichever process calls
        ``emit`` — for every dispatch this suite drives, that is the
        driver/core side, not the skill side. The flag is read from
        ``OVOS_BUS_EMIT_LEGACY`` at ``MessageBusClient`` construction time
        (see ``ovos_bus_client.client.client._bus_flag``), so overriding it
        for one client means setting the env var in THIS process just before
        building that client. Restored immediately after, so it does not
        leak into any client built after this one returns.
        """
        prev = os.environ.get("OVOS_BUS_EMIT_LEGACY")
        if emit_legacy is not None:
            os.environ["OVOS_BUS_EMIT_LEGACY"] = str(emit_legacy).lower()
        try:
            bus = MessageBusClient(host="127.0.0.1", port=self.port, route="/core")
            bus.run_in_thread()
            if not bus.connected_event.wait(30):
                raise RuntimeError("driver could not connect to the messagebus")
            return bus
        finally:
            if emit_legacy is not None:
                if prev is None:
                    os.environ.pop("OVOS_BUS_EMIT_LEGACY", None)
                else:
                    os.environ["OVOS_BUS_EMIT_LEGACY"] = prev

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class SkillProcess:
    """The other venv's skill, as a child process on the same bus.

    ``emit_legacy`` is threaded through as an environment flag for this
    process too — belt and braces — but the mirror's actual send-side rule
    (bus-client#271 rule 1, the legacy ``.intent``-suffixed twin) runs in
    whichever process calls ``bus.emit()`` for the dispatch, which in this
    suite is the DRIVER/core side (see ``BusServer.client``), not here. This
    process's own ``OVOS_BUS_EMIT_LEGACY`` only gates rule 2 (receive-side
    canonicalization) for traffic this process itself emits, which none of
    these tests currently do.
    """

    def __init__(self, python: str, xdg: str, emit_legacy: bool = True):
        env = dict(os.environ,
                   XDG_CONFIG_HOME=xdg,
                   OVOS_BUS_EMIT_LEGACY=str(emit_legacy).lower(),
                   BACKCOMPAT_SKILL_ID=SKILL_ID,
                   PYTHONUNBUFFERED="1")
        self.lines = []
        self.bound_topics = []
        #: versions resolved inside the skill venv, reported by the child
        self.versions = {}
        self.proc = subprocess.Popen(
            [python, SKILL_SCRIPT],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env)
        self._wait_ready()

    def _wait_ready(self):
        deadline = time.time() + SKILL_BOOT_TIMEOUT
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    raise RuntimeError(
                        "skill process died before registering:\n" + self.log)
                continue
            self.lines.append(line.rstrip())
            if line.startswith("BOUND_TOPICS "):
                self.bound_topics = json.loads(line[len("BOUND_TOPICS "):])
            if line.startswith("VERSIONS "):
                self.versions = json.loads(line[len("VERSIONS "):])
            if line.startswith("SKILL_READY"):
                return
        raise RuntimeError(f"skill process never reported ready:\n{self.log}")

    @property
    def log(self) -> str:
        return "\n".join(self.lines)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()


AUDIO_SCRIPT = os.path.join(HERE, "audio_process.py")
#: How long to wait for the audio simulator to import ovos-bus-client (and,
#: for 'new' vintage, ovos-spec-tools) and subscribe. Cheaper than the skill
#: boot (no workshop resource loading), but generous for the same reason
#: SKILL_BOOT_TIMEOUT is: a slow CI runner should never read as "the bridge
#: is broken".
AUDIO_BOOT_TIMEOUT = 60


class AudioProcess:
    """The audio-axis simulator (``audio_process.py``), as a third child
    process on the same bus (design §2.6). Mirrors ``SkillProcess``'s
    handshake shape (a ``VERSIONS`` line, then a ready marker) so the two
    classes stay easy to read side by side.
    """

    def __init__(self, python: str, xdg: str, vintage: str):
        if vintage not in ("old", "new"):
            raise ValueError(f"vintage must be 'old' or 'new', got {vintage!r}")
        env = dict(os.environ,
                   XDG_CONFIG_HOME=xdg,
                   BACKCOMPAT_AUDIO_VINTAGE=vintage,
                   PYTHONUNBUFFERED="1")
        if vintage == "old":
            # The old-vintage simulator's own client must NOT locally
            # deliver "speak" as the receive-side counterpart of an
            # incoming spec-only SPEAK -- a real pre-#165 ovos-audio
            # predates the NamespaceTranslator concept entirely and would
            # never react to a spec-only producer. counterpart_topics()
            # (ovos_spec_tools.messages.NamespaceTranslator) gates a
            # RECEIVED spec topic's legacy counterpart on ``emit_legacy``,
            # not ``modernize`` (modernize is the other direction: a
            # received LEGACY topic's spec counterpart) -- confirmed by
            # reading the implementation, not assumed; an earlier attempt
            # at this fix disabled the wrong flag (modernize) and the
            # cross-talk persisted. Disabling both here is deliberate:
            # neither direction of the migration bridge should exist on a
            # process simulating a pre-migration vintage. Leaving either
            # flag at its default (True, since venv_audio only ever pins a
            # CURRENT bus-client -- design §2.6, the vintage is behavioural,
            # not a package pin) makes an A=old simulator react to A=new
            # traffic too, which is both unrealistic and -- confirmed live
            # -- silently masked a gutted ``_play_spec`` behind the
            # still-alive old process's own (unmutated) ``_play`` reacting
            # to the bridged counterpart whenever an ``audio_stack_old`` and
            # an ``audio_stack`` fixture were alive on the same bus at once
            # (adversarial-review mutation testing, C1 follow-up).
            env["OVOS_BUS_MODERNIZE"] = "false"
            env["OVOS_BUS_EMIT_LEGACY"] = "false"
        self.vintage = vintage
        self.lines = []
        self.versions = {}
        self.proc = subprocess.Popen(
            [python, AUDIO_SCRIPT],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env)
        self._wait_ready()

    def _wait_ready(self):
        deadline = time.time() + AUDIO_BOOT_TIMEOUT
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    raise RuntimeError(
                        "audio process died before registering:\n" + self.log)
                continue
            self.lines.append(line.rstrip())
            if line.startswith("VERSIONS "):
                self.versions = json.loads(line[len("VERSIONS "):])
            if line.startswith("READY"):
                return
        raise RuntimeError(f"audio process never reported ready:\n{self.log}")

    @property
    def log(self) -> str:
        return "\n".join(self.lines)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class Capture:
    """Collect messages seen on a topic, with a wait-for-first helper.

    ``token`` narrows the capture to one dispatch. The bus is shared by the
    whole module and a handler's answer can land after the test that triggered
    it has moved on, so counting everything that ever appeared on a topic would
    charge one test for another test's traffic — and a duplicate-firing check
    has to be able to tell those apart.

    ``session_id`` is the same narrowing, but keyed off ``message.context``
    instead of ``message.data``: needed for anything downstream of
    ``Message.forward(topic)`` (both ``audio_process.py``'s ``_play_spec``
    and the real ``PlaybackThread.begin_audio``/``end_audio`` use exactly
    this), because ``forward()`` carries ``context`` (verified live) but
    resets ``data`` to ``{}`` (also verified live, NOT the same as
    ``context`` -- confirmed by reading the actual return value, not
    assumed) -- a ``token`` placed in a triggering message's ``data`` never
    reaches a topic reached only via ``forward()``.
    """

    def __init__(self, bus: MessageBusClient, topic: str,
                 token: Optional[str] = None,
                 session_id: Optional[str] = None):
        self.bus = bus
        self.topic = topic
        self.token = token
        self.session_id = session_id
        self.messages = []
        self._seen = Event()
        bus.on(topic, self._handle)

    def _matches(self, message: Message) -> bool:
        if self.session_id is not None:
            ctx_session = (message.context or {}).get("session") or {}
            if ctx_session.get("session_id") != self.session_id:
                return False
        if self.token is None:
            return True
        data = message.data or {}
        # the marker echoes the dispatch payload under "data"; the dispatch
        # itself carries the token at the top level
        return (data.get("token") == self.token
                or (data.get("data") or {}).get("token") == self.token)

    def _handle(self, message: Message):
        if not self._matches(message):
            return
        self.messages.append(message)
        self._seen.set()

    def wait(self, timeout: float = DISPATCH_TIMEOUT) -> bool:
        return self._seen.wait(timeout)

    def wait_for_count(self, count: int, timeout: float) -> bool:
        """Wait until at least ``count`` matching messages have been captured.

        Returns ``True`` the moment the threshold is reached (early exit), or
        ``False`` if ``timeout`` elapses first. The duplicate-dispatch check
        uses this to fail fast on a second hit instead of always sleeping out a
        fixed window: a real duplicate returns as soon as it lands, and only the
        passing (no-duplicate) case pays the full deadline.
        """
        deadline = time.monotonic() + timeout
        while len(self.messages) < count:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)
        return True

    def close(self):
        self.bus.remove(self.topic, self._handle)


def dispatch(bus: MessageBusClient, topic: str, **data) -> str:
    """Emit an intent dispatch the way ``IntentService._dispatch_match`` does.

    Returns the correlation token stamped into the payload so a capture can
    attribute the answer to this dispatch and no other.
    """
    token = uuid.uuid4().hex
    bus.emit(Message(topic, dict(data, token=token),
                     {"session": {"session_id": f"backcompat-{token[:8]}"}}))
    return token
