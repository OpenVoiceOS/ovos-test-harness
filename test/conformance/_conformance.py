"""Shared helpers for the OVOS architecture-spec conformance suites.

These suites encode the normative *Conformance* clauses of the OVOS formal
specifications (``ovos/org/architecture/ovos-*.md``) as ovoscope end-to-end
assertions against the ovos-core orchestrator.

The leading underscore keeps pytest from collecting this module as a test
file; it only provides capture helpers the ``test_*_conformance.py`` suites
import.

Driver model
------------
The pure-python ``padacioso`` matcher drives intent dispatch. Intents are
registered directly on the bus with :func:`ovoscope.register_padatious_intent`
so no skill packages or native matchers are required. The in-core stop
pipeline drives the stop-cascade clauses. Both are deterministic on a
``FakeBus``.

xfail discipline
----------------
A conformance test asserts the **spec's** topic name / message shape. Where
ovos-core currently emits a legacy ``mycroft.*`` (or colon-shaped) name — the
``mycroft.* -> ovos.*`` migration is pending — the test is decorated
``@pytest.mark.xfail(strict=True, reason=...)`` citing the legacy name and the
spec clause it should meet. Strict is the default: the gap is deterministic, so
an upstream fix must turn the suite red until the marker is deleted, rather
than passing quietly as an XPASS. Only a genuinely environment-dependent gap
(for example, an engine capability that a different installed matcher would
satisfy) uses ``strict=False``, and its reason must say why.

Tests with no xfail assert clauses the orchestrator already satisfies.

Each suite's module docstring carries a *coverage map* — one line per clause,
ending in ``green`` / ``xfail`` / ``skip``. ``test/test_docstring_xfail_sync.py``
fails CI when a map stops matching the file's decorators.
"""
import threading
import time
from typing import Iterable, List, Optional

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_config.config import Configuration
from ovos_spec_tools import SpecMessage

# The spec-namespace entry topic the IntentService subscribes to
# (``IntentService.bus.on(SpecMessage.UTTERANCE, ...)``). The conformance
# suites run with ``legacy_namespace=False`` (see :func:`use_spec_namespace`),
# so core handles the utterance natively on this topic — injecting on the
# legacy ``recognizer_loop:utterance`` would never reach the handler.
ENTRY_TOPIC = SpecMessage.UTTERANCE.value  # "ovos.utterance.handle"


_NAMESPACE_STACK: List[object] = []
_SENTINEL = object()


def use_spec_namespace():
    """Switch ovos-core to the spec (``ovos.*``) bus namespace.

    The conformance suites assert the spec topic names, so they flip the
    deployment ``legacy_namespace`` config off. Call from ``setUpModule``.
    The previous value is remembered so :func:`reset_namespace` can put the
    process-wide :class:`Configuration` back exactly as it was.
    """
    cfg = Configuration()
    _NAMESPACE_STACK.append(cfg.get("legacy_namespace", _SENTINEL))
    cfg["legacy_namespace"] = False


def reset_namespace():
    """Restore the bus namespace captured by :func:`use_spec_namespace`.

    Call from ``tearDownModule`` (in a ``finally``), and also from the error
    path of a ``setUpModule`` that fails after switching the namespace.
    """
    if not _NAMESPACE_STACK:
        return
    previous = _NAMESPACE_STACK.pop()
    cfg = Configuration()
    if previous is _SENTINEL:
        # Configuration.pop() does not accept a default argument
        if "legacy_namespace" in cfg:
            del cfg["legacy_namespace"]
    else:
        cfg["legacy_namespace"] = previous

PADACIOSO_HIGH = "ovos-padacioso-pipeline-plugin-high"
STOP_HIGH = "ovos-stop-pipeline-plugin-high"


def utterance(text: str, session_id: str, pipeline: List[str],
              lang: str = "en-US", **session_fields) -> Message:
    """Build a ``recognizer_loop:utterance`` entry message for one session."""
    sess = Session(session_id)
    sess.lang = lang
    sess.pipeline = pipeline
    for key, value in session_fields.items():
        setattr(sess, key, value)
    return Message(ENTRY_TOPIC,
                   {"utterances": [text], "lang": lang},
                   {"session": sess.serialize(), "source": "A", "destination": "B"})


# Terminal end-markers of one utterance turn. ``capture`` stops waiting a
# short settle window after one of these arrives instead of always burning the
# full timeout. ``complete_intent_failure`` is the legacy no-match marker some
# stack versions still emit.
DEFAULT_EOF_TYPES = (
    SpecMessage.UTTERANCE_HANDLED.value,    # ovos.utterance.handled
    SpecMessage.UTTERANCE_CANCELLED.value,  # ovos.utterance.cancelled
    "mycroft.skill.handler.complete",
    "complete_intent_failure",
)

# How long to keep collecting after an end-marker, so trailing messages
# emitted just behind the marker still land in ``recs``.
EOF_SETTLE = 0.5

DESERIALIZE_ERROR = "_deserialize_error"


def capture(mc, message: Message, timeout: float = 5.0,
            eof_types: Optional[Iterable[str]] = DEFAULT_EOF_TYPES,
            settle: float = EOF_SETTLE) -> List[Message]:
    """Emit ``message`` and return every bus Message seen.

    Subscribes to the FakeBus catch-all so the full ordered sequence — entry,
    activation, dispatch, terminal events — is captured regardless of which
    clause a given test inspects.

    ``timeout`` is the upper bound. When a topic in ``eof_types`` arrives, the
    capture keeps collecting for ``settle`` seconds and then returns, so a
    green run does not pay the full window. Pass ``eof_types=None`` for the
    old fixed-window behaviour (needed when the interaction has no end-marker
    or when the test counts messages that trail far behind one).

    A message the bus cannot deserialize is **not** dropped: a sentinel
    ``_deserialize_error`` Message is appended so the corruption shows up in
    assertions and in failure output.
    """
    recs: List[Message] = []
    eof = set(eof_types or ())
    seen_eof = threading.Event()

    def _rec(serialized):
        if isinstance(serialized, Message):
            msg = serialized
        else:
            try:
                msg = Message.deserialize(serialized)
            except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                raw = serialized if isinstance(serialized, str) else repr(serialized)
                recs.append(Message(DESERIALIZE_ERROR,
                                    {"error": str(exc), "raw": raw[:200]}))
                return
        recs.append(msg)
        if msg.msg_type in eof:
            seen_eof.set()

    mc.bus.on("message", _rec)
    try:
        deadline = time.monotonic() + timeout
        mc.bus.emit(message)
        if not eof:
            time.sleep(timeout)
        else:
            remaining = deadline - time.monotonic()
            if seen_eof.wait(timeout=max(0.0, remaining)):
                # settle window, but never run past the caller's timeout
                time.sleep(max(0.0, min(settle, deadline - time.monotonic())))
    finally:
        mc.bus.remove("message", _rec)
    return recs


def assert_absent(recs: List[Message], msg_type: str, *,
                  positive_control: Optional[Iterable[str]] = DEFAULT_EOF_TYPES):
    """Assert ``msg_type`` never appeared — without the assertion being vacuous.

    A bare ``assertNotIn`` passes when the interaction never happened at all
    (boot failure, wrong entry topic, capture window too short). This helper
    first requires a *positive control*: at least one of ``positive_control``
    must be present, proving the turn really ran end to end. Pass
    ``positive_control=None`` only when the interaction has no end-marker, and
    then only with a non-empty capture.
    """
    seq = types(recs)
    if not recs:
        raise AssertionError(
            f"vacuous negative assertion for {msg_type!r}: no bus traffic was "
            f"captured at all")
    if positive_control:
        controls = ([positive_control] if isinstance(positive_control, str)
                    else list(positive_control))
        if not any(c in seq for c in controls):
            raise AssertionError(
                f"vacuous negative assertion for {msg_type!r}: none of the "
                f"positive controls {controls} arrived, so the turn did not "
                f"run to a terminal state; saw {seq}")
    if msg_type in seq:
        raise AssertionError(f"{msg_type!r} was emitted but must not be; saw {seq}")


def deserialize_errors(recs: List[Message]) -> List[Message]:
    """Sentinel records for bus messages that failed to deserialize."""
    return [m for m in recs if m.msg_type == DESERIALIZE_ERROR]


def types(recs: List[Message]) -> List[str]:
    """The ordered list of ``msg_type`` strings."""
    return [m.msg_type for m in recs]


def first(recs: List[Message], msg_type: str) -> Optional[Message]:
    """First captured Message of ``msg_type``, or ``None``."""
    return next((m for m in recs if m.msg_type == msg_type), None)
