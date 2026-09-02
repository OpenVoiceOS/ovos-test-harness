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
#: ConverseService`` (see ``make_intent_service`` below) — real per-version
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
#: of the driver process's bus handler thread, entirely between when the
#: enable wait times out and the disable check that follows it -- a real
#: round trip the event wait still never catches mid-flight. A wider window
#: does not fix that (it is a scheduling race, not a slowness budget), but it
#: does make it rarer, and the retry path below uses the enable/disable
#: events themselves as the actual evidence for that remaining race.
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


def core_supports_utterance_dispatch() -> bool:
    """Whether this core venv's real dispatch path stamps
    ``session.converse_handlers`` (OVOS-CONVERSE-1 §3.1) on a matched
    utterance, as opposed to only pushing the older
    ``session.active_handlers`` recency list (OVOS-PIPELINE-1 §7.1) — the
    boundary the converse/get_response tests need before they can rely on a
    real intent dispatch instead of falling back to their
    ``self.activate()``-only setup.

    ``ovos_bus_client.session.Session`` has carried both an
    ``active_handlers`` and a ``converse_handlers`` field for as long as this
    combo's venvs go back, so a Session-side ``hasattr`` cannot tell the two
    apart — the split is enforced by whether the CORE side's real dispatch
    code actually calls ``Session.add_converse_handler``, not by what the
    session object it calls it on is capable of. That is a fact about
    ``IntentService._dispatch_match`` (private, never called by this
    driver), read directly off its own compiled bytecode's referenced names
    (``__code__.co_names``) rather than assumed from a version pin or a
    source-text grep (the latter is exactly what makes the pre-existing adapt
    M-axis probe fragile) — a real installed-surface fact, just one that
    lives on a private method instead of a public one.
    """
    try:
        _spec_message()
    except RuntimeError:
        return False
    from ovos_core.intent_services.service import IntentService
    return "add_converse_handler" in IntentService._dispatch_match.__code__.co_names


def make_intent_service(bus: MessageBusClient):
    """Instantiate the CORE side's own, real per-version ``IntentService``
    (``ovos_core.intent_services.service.IntentService``) with its real
    pipeline plugins (padatious, converse, fallback, stop) loaded — the
    same installed plugin set a real deployment loads, discovered through
    ``OVOSPipelineFactory`` exactly the way ``IntentService`` itself does.

    Loading is forced synchronously via a direct call to
    ``handle_reload_pipelines`` — a normal bus-handler method, public, just
    invoked directly instead of round-tripping the
    ``"intent.service.pipelines.reload"`` message it otherwise handles —
    so every plugin (including the padatious one
    :func:`dispatch_utterance`'s callers need) is guaranteed loaded by the
    time this returns, rather than racing that message's own async
    delivery.

    ``IntentService.__init__`` calls ``SessionManager.connect_to_bus(bus)``,
    which sets the process-global ``SessionManager.bus`` class attribute —
    and ``IntentService.shutdown()`` only removes its own bus handlers, never
    unbinds that class attribute. Left alone, a torn-down instance leaves
    ``SessionManager.bus`` pointed at this module's already-closed client for
    every later test module in the same pytest process. Returns
    ``(service, teardown)``; the caller must call ``teardown()`` (instead of
    ``service.shutdown()`` directly) once done with the service, which shuts
    it down and then restores ``SessionManager.bus`` to what it was before
    this call.
    """
    from ovos_bus_client.session import SessionManager
    from ovos_core.intent_services.service import IntentService
    prior_bus = SessionManager.bus
    service = IntentService(bus=bus, config={}, preload_pipelines=False)
    service.handle_reload_pipelines(Message('intent.service.pipelines.reload'))

    def teardown():
        service.shutdown()
        SessionManager.bus = prior_bus

    return service, teardown


def register_padatious_intents(intent_service, bus: MessageBusClient,
                               registrations: "Capture",
                               timeout: float = SKILL_BOOT_TIMEOUT) -> None:
    """Give ``intent_service``'s own real padatious pipeline plugin the
    fixture skill's already-registered intent, and block until it has
    actually compiled it.

    The fixture skill registered over the wire during the ``stack``
    fixture's own setup, before this (separately constructed)
    ``intent_service`` existed to hear it — its real padatious pipeline
    plugin's container never saw that original broadcast. Replaying the
    exact real ``"padatious:register_intent"`` message(s) ``registrations``
    already captured (the actual wire traffic the skill sent, not
    reconstructed data) is what lets this instance's container learn about
    it after the fact, the same way any late-joining pipeline consumer
    would. ``PadatiousPipeline.wait_until_trained`` is the plugin's own
    documented "test/tooling synchronization helper" for the async
    compile step that follows — not a private method, and not a poll this
    driver invented.

    ``wait_until_trained`` itself is a later addition (the vintage this
    combo's "old-core" boundary pin resolves, ``ovos-padatious==2.0.0a1``,
    trains fully synchronously inside ``register_intent``'s own handler and
    has no such method at all): where it is absent, the ``bus.emit`` loop
    above has already blocked until training finished, so there is nothing
    left to wait for.

    A no-op if this core has no padatious pipeline plugin loaded (an
    install gap unrelated to what these tests probe).
    """
    padatious = intent_service.pipeline_plugins.get("ovos-padatious-pipeline-plugin")
    if padatious is None:
        return
    for message in registrations.messages:
        bus.emit(message)
    if hasattr(padatious, "wait_until_trained"):
        padatious.wait_until_trained(timeout)


def dispatch_utterance(bus: MessageBusClient, topic: str, session_id: str,
                       utterance: str, lang: str = "en-us",
                       session: Optional[dict] = None,
                       timeout: float = DISPATCH_TIMEOUT) -> Optional[dict]:
    """Send ``utterance`` through the real orchestrator exactly the way a
    real recognizer would, then read the resulting dispatch off the wire.

    This emits the real ``SpecMessage.UTTERANCE`` topic
    (``"ovos.utterance.handle"``) that ``IntentService.handle_utterance``
    — a real bus handler bound in :func:`make_intent_service`, never
    called directly — already subscribes to, and lets its real installed
    padatious pipeline plugin match the utterance against the fixture
    skill's real registered intent (see :func:`register_padatious_intents`
    for how that plugin's container learns about the registration at
    all). ``IntentService._dispatch_match`` (private, never called by this
    driver) is what then performs both OVOS-PIPELINE-1 §7.1's
    ``active_handlers`` push and OVOS-CONVERSE-1 §3.1's
    ``converse_handlers`` stamp, and its dispatch Message
    (``context["session"]`` already carrying both) is what
    ``IntentDispatcher.dispatch`` puts on ``topic`` verbatim — the same
    message the real skill handler receives, so capturing it here is real
    wire evidence that a stamping core's carrier shows ``converse_handlers``
    directly, needing no separate vintage probe of its own.

    Returns the observed session dict (for the caller to carry forward via
    :func:`session_context`) on success, or ``None`` on timeout/mismatch
    (no match, or the matcher picked a different topic than expected).
    """
    capture = Capture(bus, topic, session_id=session_id)
    try:
        message = Message(_spec_message().UTTERANCE,
                          {"utterances": [utterance], "lang": lang},
                          session_context(session_id, session))
        bus.emit(message)
        if not capture.wait(timeout):
            return None
        return (capture.messages[-1].context or {}).get("session") or {}
    finally:
        capture.close()


def _handler_skill_ids(session: dict) -> list:
    """The active skill ids a serialized session carries, spanning both
    vintages this driver forwards.

    OVOS-PIPELINE-1 §7.1 makes ``active_handlers`` (a list of dispatch
    records) the canonical field. Older cores (e.g. ``ovos-core==2.5.5a2``,
    which predates that spec) only ever serialized the legacy
    ``active_skills`` projection — ``[skill_id, activated_at]`` pairs — so
    that is read as a fallback, never assumed to be the primary shape.
    """
    handlers = session.get("active_handlers")
    if handlers is not None:
        return [h.get("skill_id") for h in handlers]
    return [pair[0] for pair in session.get("active_skills") or []]


def session_context(session_id: str, session: Optional[dict] = None) -> dict:
    """Message context carrying the current session's full state.

    OVOS-SESSION-2 §2.2: "the registry holds only the default session" — a
    named session (``session_id != "default"``) is client-owned, and the
    orchestrator keeps no live object for one that a later lookup could
    recover. This driver plays that client role, so it is the one on the
    hook for carrying a named session's state forward between messages:
    ``session`` is whatever a caller last observed on the wire (e.g. via
    :func:`wait_for_active_skill`), and gets serialized onto the next
    message verbatim. With no prior state (the first message of a flow),
    an empty ``Session`` is used instead — there is nothing to carry yet.
    """
    from ovos_bus_client.session import Session
    if session is None:
        session = Session(session_id=session_id).serialize()
    return {"session": session}


def wait_for_active_skill(activation: "Capture", skill_id: str,
                          timeout: float = DISPATCH_TIMEOUT) -> Optional[dict]:
    """Confirm ``skill_id`` shows up as active, from the wire evidence an
    already-subscribed ``Capture`` on ``"intent.service.skills.activated"``
    sees — never a poll of ``SessionManager.sessions``, which OVOS-SESSION-2
    §2.2 never populates for a named ``session_id``.

    OVOS-PIPELINE-1 §7.1: "the activation push writes
    session.active_handlers and that session rides the orchestrator's own
    emissions" — concretely, ``ConverseService.activate_skill`` forwards the
    triggering message onto this exact topic with a freshly serialized
    session in its context (``ovos_core.intent_services.converse_service``).
    That forwarded message is the real evidence; ``activation`` must already
    be subscribed *before* the action that triggers it (same requirement as
    every other ``Capture`` in this module), or the emission can be missed
    entirely.

    Returns the observed session dict (for the caller to carry forward via
    :func:`session_context`) on success, or ``None`` on timeout/mismatch.

    This is a dispatch-recency check only (``active_handlers``, OVOS-
    PIPELINE-1 §7.1's own field). It says nothing about converse
    eligibility (``converse_handlers``, OVOS-CONVERSE-1 §2.1) — that is a
    genuinely separate list, stamped only by a real intent dispatch
    (:func:`dispatch_utterance`), never by ``self.activate()`` alone. On a
    core new enough to keep the two lists apart
    (:func:`core_supports_utterance_dispatch`), this helper's
    ``self.activate()``-only path is not sufficient converse-candidacy
    setup by itself; see the two tests that use it for how each vintage is
    set up.
    """
    if not activation.wait(timeout):
        return None
    session = (activation.messages[-1].context or {}).get("session") or {}
    if skill_id not in _handler_skill_ids(session):
        return None
    return session


def wait_for_response_mode(enabled: "Capture", skill_id: str, session: dict,
                           timeout: float = DISPATCH_TIMEOUT) -> Optional[dict]:
    """Confirm ``skill_id`` entered response-mode, from the wire evidence an
    already-subscribed ``Capture`` on ``GET_RESPONSE_ENABLE_TOPIC`` sees —
    never a poll of ``SessionManager.sessions`` (OVOS-SESSION-2 §2.2: never
    populated for a named ``session_id``). Returns the session dict with
    response-mode applied (for the caller to carry forward via
    :func:`session_context`/:func:`converse_match`), or ``None`` on
    timeout/mismatch.

    ``ConverseService.handle_get_response_enable``'s own mutation lands on a
    transient ``Session`` built from whatever the enable message carried,
    and is discarded once the handler returns — nothing derives a reply or
    forward from it, so unlike activation (§7.1's ``active_handlers`` push,
    which does ride a real forwarded message) there is no further wire
    carrier proving what the mutated state became. Once the enable message
    itself (the trigger for that mutation) is confirmed on the wire, this
    driver — playing the session-owning client OVOS-SESSION-2 assumes —
    applies the exact same real, per-version ``Session.enable_response_mode``
    the handler just ran, onto its own already-observed copy of the session
    (``session``, from :func:`wait_for_active_skill`), so the state carried
    forward next is what the real handler would have produced, not a
    codepath this driver invented independently.
    """
    from ovos_bus_client.session import Session
    if not enabled.wait_for_count(1, timeout):
        return None
    if enabled.messages[-1].data.get("skill_id") != skill_id:
        return None
    updated = Session.deserialize(session)
    updated.enable_response_mode(skill_id)
    return updated.serialize()


def converse_match(converse_service, utterances, lang: str, session_id: str,
                   session: Optional[dict] = None):
    """Ask the real converse service to match, the way ``IntentService`` would
    before falling through to intent matching.

    Returns the ``IntentHandlerMatch`` (or ``None``) straight from the real
    per-version core code — nothing here decides the topic.

    OVOS-SESSION-2 §2.2 gives the orchestrator no live named-session object
    to read back, so ``session`` must be whatever the caller already
    observed on the wire (see :func:`wait_for_active_skill`) — the same
    discipline :func:`session_context` documents. A bare ``{"session_id":
    session_id}`` snapshot — the shorthand ``dispatch()`` uses for the
    stateless intent-dispatch case — would build a session with no active
    skills/response-mode at all, and ``.match()`` would find nothing to
    converse with.
    """
    message = Message("recognizer_loop:utterance",
                      {"utterances": utterances, "lang": lang},
                      session_context(session_id, session))
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

    def client(self, emit_legacy: Optional[bool] = None,
              modernize: Optional[bool] = None) -> MessageBusClient:
        """A driver-side bus client, optionally overriding #271's rule 1
        and/or rule 2.

        bus-client#271 rule 1 (the legacy ``.intent``-suffixed twin) fires
        inside ``MessageBusClient.emit()``, in whichever process calls
        ``emit`` — for every dispatch this suite drives, that is the
        driver/core side, not the skill side. The flag is read from
        ``OVOS_BUS_EMIT_LEGACY`` at ``MessageBusClient`` construction time
        (see ``ovos_bus_client.client.client._bus_flag``), so overriding it
        for one client means setting the env var in THIS process just before
        building that client. Restored immediately after, so it does not
        leak into any client built after this one returns.

        ``modernize`` is the RULE 2 counterpart (T2.8): receive-side
        canonicalization, gated by ``OVOS_BUS_MODERNIZE`` /
        ``self._translator.modernize`` and applied inside
        ``MessageBusClient.on_message`` -> ``_modernize_intent_topic`` for
        whichever client RECEIVES a suffixed intent frame without the RULE 1
        twin marker. It is the RECEIVING client's own flag that matters here
        (same "which process's flag matters" principle the A-axis section
        above documents for the audio bridge) — a shadow client built with
        ``modernize=False`` and a canonical-only ``bus.on(...)`` listener is
        how T2.8's RULE 2 kill-switch cell (Cell B) proves the switch is
        load-bearing: ``SkillProcess`` has no ``modernize`` knob to thread
        through, so there is no way to build a real canonical-only skill
        container with RULE 2 turned off, even though ovos-workshop#500 (the
        release that makes a skill canonical-only) has since merged and
        published PyPI alphas (9.3.11a2/9.3.12a1) — Cell A in
        ``test_mixed_version_matrix.py``'s RULE 2 section runs against a
        real ``SkillProcess`` built from one of those, and its own docstring
        explains why Cell B still cannot.
        """
        prev_legacy = os.environ.get("OVOS_BUS_EMIT_LEGACY")
        prev_modernize = os.environ.get("OVOS_BUS_MODERNIZE")
        if emit_legacy is not None:
            os.environ["OVOS_BUS_EMIT_LEGACY"] = str(emit_legacy).lower()
        if modernize is not None:
            os.environ["OVOS_BUS_MODERNIZE"] = str(modernize).lower()
        try:
            bus = MessageBusClient(host="127.0.0.1", port=self.port, route="/core")
            bus.run_in_thread()
            if not bus.connected_event.wait(30):
                raise RuntimeError("driver could not connect to the messagebus")
            return bus
        finally:
            if emit_legacy is not None:
                if prev_legacy is None:
                    os.environ.pop("OVOS_BUS_EMIT_LEGACY", None)
                else:
                    os.environ["OVOS_BUS_EMIT_LEGACY"] = prev_legacy
            if modernize is not None:
                if prev_modernize is None:
                    os.environ.pop("OVOS_BUS_MODERNIZE", None)
                else:
                    os.environ["OVOS_BUS_MODERNIZE"] = prev_modernize

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

    def reset(self) -> None:
        """Clear captured messages and rearm :meth:`wait` together.

        Clearing ``messages`` alone leaves ``_seen`` set from whatever already
        landed, so a caller retrying after this would see :meth:`wait` return
        immediately without the new message it is actually waiting for.
        """
        self.messages = []
        self._seen.clear()

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


WIRE_TWIN_SCRIPT = os.path.join(HERE, "wire_twin_listener.py")
#: Boot budget for the wire-twin listener. Cheaper than the skill boot (no
#: workshop resource loading, no core) but, like every other boot timeout in
#: this module, generous rather than tight -- a slow CI runner must never
#: read as "the wire twin is broken".
WIRE_TWIN_BOOT_TIMEOUT = 60


class WireTwinListener:
    """The ovos-bus-client#286 gap's OLD-vintage listener, as a third kind
    of child process (mirrors ``AudioProcess``'s handshake shape: a
    ``VERSIONS`` line, then ``READY``). Runs ``wire_twin_listener.py`` under
    whichever python ``build_venvs.sh``'s ``venv_wire_twin_old`` resolved --
    a genuinely pre-spec-tools ``ovos-bus-client==1.5.0``, not a current
    client with the namespace-bridge flags turned off (see that script's
    module docstring for why the distinction matters).
    """

    def __init__(self, python: str, xdg: str):
        env = dict(os.environ, XDG_CONFIG_HOME=xdg, PYTHONUNBUFFERED="1")
        self.lines = []
        self.versions = {}
        self.proc = subprocess.Popen(
            [python, WIRE_TWIN_SCRIPT],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env)
        self._wait_ready()
        # A background reader keeps draining stdout after READY, so
        # wait_for_token can poll self.lines instead of calling a blocking
        # readline() with no timeout of its own (a listener that never
        # receives anything must still let the caller's deadline fire).
        import threading as _threading
        self._reader_thread = _threading.Thread(
            target=self._drain_stdout, daemon=True)
        self._reader_thread.start()

    def _drain_stdout(self):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return
            self.lines.append(line.rstrip())

    def _wait_ready(self):
        deadline = time.time() + WIRE_TWIN_BOOT_TIMEOUT
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    raise RuntimeError(
                        "wire-twin listener died before registering:\n"
                        + self.log)
                continue
            self.lines.append(line.rstrip())
            if line.startswith("VERSIONS "):
                self.versions = json.loads(line[len("VERSIONS "):])
            if line.startswith("READY"):
                return
        raise RuntimeError(
            f"wire-twin listener never reported ready:\n{self.log}")

    def received_tokens(self) -> list:
        """Tokens of every ``speak`` message this process has reported
        receiving so far, parsed live from its stdout log -- not a count
        cached at handshake time, since messages keep arriving after
        ``READY``."""
        tokens = []
        for line in self.lines:
            if line.startswith("RECEIVED "):
                tokens.append(json.loads(line[len("RECEIVED "):]).get("token"))
        return tokens

    def wait_for_token(self, token: str, timeout: float = DISPATCH_TIMEOUT) -> bool:
        """Poll this process's own stdout log (drained live by the
        background reader thread) until ``token`` shows up in a
        ``RECEIVED`` line, or ``timeout`` elapses."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if token in self.received_tokens():
                return True
            time.sleep(0.02)
        return token in self.received_tokens()

    @property
    def log(self) -> str:
        return "\n".join(self.lines)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
#: T2.8 Cell C -- the topic pair ``skill_process.py``'s
#: ``_report_intent_state`` binds. A dedicated round trip rather than
#: reusing ``mycroft.skill.disable_intent``/``enable_intent`` themselves:
#: this lets the driver read the skill's ``IntentServiceInterface``
#: bookkeeping (``registered_intents``/``detached_intents``) in a message
#: that is guaranteed to be processed AFTER whichever disable/enable call
#: preceded it (the skill's bus reader dispatches one message at a time, in
#: arrival order), instead of racing a second listener bound to the same
#: topic against workshop's own built-in handler -- listener registration
#: order across two different ``add_event`` calls for the identical topic is
#: not a contract this suite should lean on.
REPORT_INTENT_STATE_TRIGGER_TOPIC = "backcompat.report_intent_state.trigger"
REPORT_INTENT_STATE_DONE_TOPIC = "backcompat.report_intent_state.done"


def report_intent_state(bus: MessageBusClient, timeout: float = DISPATCH_TIMEOUT) -> dict:
    """Round-trip the skill's live intent-registry bookkeeping.

    Returns the ``{"bound_topics": [...], "registered": [...], "detached":
    [...]}`` dict the skill subprocess reports, straight from its own
    ``IntentServiceInterface.registered_intents`` / ``.detached_intents`` --
    real per-vintage state, never inferred from a dispatch side effect.
    """
    cap = Capture(bus, REPORT_INTENT_STATE_DONE_TOPIC)
    try:
        bus.emit(Message(REPORT_INTENT_STATE_TRIGGER_TOPIC, {}))
        assert cap.wait(timeout), (
            "backcompat.report_intent_state.trigger got no "
            "backcompat.report_intent_state.done reply -- the skill process "
            "may have died or the reporting hook is missing")
        return cap.messages[-1].data
    finally:
        cap.close()


def wait_for_intent_state(bus: MessageBusClient, bare_name: str,
                          want_registered: bool,
                          timeout: float = DISPATCH_TIMEOUT) -> dict:
    """Poll ``report_intent_state`` until ``bare_name`` lands in
    ``registered`` (``want_registered=True``) or ``detached``
    (``want_registered=False``), returning the state dict the moment it
    does.

    ``OVOSSkill``'s event dispatch does not run ``handle_disable_intent`` /
    ``handle_enable_intent`` synchronously on the bus reader thread that
    received the triggering message (confirmed empirically: a
    ``report_intent_state`` round trip sent immediately after
    ``mycroft.skill.disable_intent`` reliably observes the PRE-disable
    state, and only a second round trip after a short wait observes the
    real one) -- so a single immediate round trip races the skill's own
    handler and is not a reliable read. Same polling discipline as
    ``wait_for_active_skill``/``wait_for_response_mode`` above: real
    evidence of the transition, not a fixed guessed sleep.

    Returns the last state observed once it matches, or once ``timeout``
    elapses (in which case the caller's own assertion on the returned dict
    is what reports the failure, with the real final state attached).
    """
    deadline = time.monotonic() + timeout
    state = report_intent_state(bus)
    while True:
        is_registered = bare_name in state["registered"]
        is_detached = bare_name in state["detached"]
        if want_registered and is_registered:
            return state
        if not want_registered and is_detached:
            return state
        if time.monotonic() >= deadline:
            return state
        time.sleep(0.1)
        state = report_intent_state(bus)


def dispatch(bus: MessageBusClient, topic: str, **data) -> str:
    """Emit an intent dispatch the way ``IntentService._dispatch_match`` does.

    Returns the correlation token stamped into the payload so a capture can
    attribute the answer to this dispatch and no other.
    """
    token = uuid.uuid4().hex
    bus.emit(Message(topic, dict(data, token=token),
                     {"session": {"session_id": f"backcompat-{token[:8]}"}}))
    return token
