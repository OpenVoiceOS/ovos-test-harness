"""The ovos-bus-client#286 wire-twin gap: a canonical emit through a real
``MessageBusClient.emit()`` must still reach a genuinely OLD, pre-spec-tools
listener over the wire.

Why this is not just another mixed-version-matrix cell
--------------------------------------------------------

Every existing scenario in ``test_mixed_version_matrix.py`` crosses one of
the four S/C/M/A axes (``docs/matrix-design.md`` §2.1) -- skill container,
core stack, matcher plugins, audio side. None of those axes vary the
bus-client a satellite actually runs: §1.3 is explicit that every fleet
component floors ``ovos-bus-client`` rather than capping it, so a rebuilt
container always resolves a *current* client, and the four boundary venvs
this suite already builds (``venv_skill_old``, ``venv_audio``'s A=old
simulator) all do exactly that -- an old workshop/audio-vintage BEHAVIOUR on
top of a current bus-client package. That is real and correctly tested
elsewhere, but it cannot see this gap: a client that still HAS
``NamespaceTranslator`` can bridge locally regardless of what hit the wire.

The gap this file closes needs a client that has no translator to bridge
with at all -- a satellite frozen before ``ovos_spec_tools`` existed on the
bus-client side. ``ovos-bus-client==1.5.0`` is that vintage (see
``wire_twin_listener.py``'s docstring and ``build_venvs.sh``'s
``venv_wire_twin_old`` pin for the verification). No existing test/
sender-vintage combination this suite drives can build that shape, so it
gets its own venv and its own module rather than a new S/C/M/A cell.

The gap itself
---------------

``MessageBusClient.emit()`` puts exactly one wire frame down for a plain
namespace emit -- the RECEIVE side already bridges both spellings locally
in every process that has a translator (``on_message``'s
``counterpart_topics()`` loop). That is not enough for a client with no
translator at all: it never receives anything but a literal frame on a
topic it is subscribed to. Before ``ovos-bus-client#286``, a canonical
``ovos.utterance.speak`` emit from a MODERN client put only that one frame
on the wire -- an old 1.5.0 listener subscribed to the legacy ``speak``
topic never saw it. ``#286`` adds a real SEND-side legacy twin
(``MessageBusClient._send_legacy_namespace_twin``, gated by the same
``OVOS_BUS_EMIT_LEGACY`` flag ``#271``'s intent twin already uses) for every
:data:`ovos_spec_tools.messages.MIGRATION_MAP` topic, marker-deduped
(``NAMESPACE_COMPAT_TWIN_KEY``) so a receiver that DOES understand the
bridge never double-delivers.

Running it
----------

Needs a real old-vintage python to run the listener under::

    BACKCOMPAT_WIRE_TWIN_PYTHON=/path/to/venv_wire_twin_old/bin/python \\
    pytest test/backcompat/test_wire_twin_old_listener.py

``test/backcompat/build_venvs.sh venv_wire_twin_old`` builds that venv. The
DRIVER side (the ``MessageBusClient`` that does the emitting) is whatever
``ovos-bus-client`` is installed in the interpreter running pytest itself --
this repo's own ``requirements.txt`` floors it at ``>=2.4.0a1``, so a fresh
install picks up whatever is newest, including the ``#286`` fix once it is
published. See the PR description for the exact before/after pins this was
verified against (released ``2.8.2a1`` red, ``2.8.3a1`` green).

As of the ``#286`` follow-up (``2.8.4a1``, in progress), the send-side
namespace twin is gated by ``OVOS_BUS_WIRE_LEGACY_TWINS`` -- an ESCAPE
HATCH that defaults ``true``, not an opt-in default-``false`` flag: compat
targets stable releases, and the latest stable (``ovos-bus-client==1.5.0``,
this module's own listener vintage) is exactly who the twin protects, so
it stays on by default. Mid-vintage alphas that would double-deliver a
migrated topic are unsupported and expected to update, not accommodated by
flipping the default off. This module's wire-twin test still sets the
flag explicitly on the sender for the duration of its own emit -- not to
opt in to a default-off behaviour, but as defensive pinning against any
future default change. Green on any RELEASED version today does not
require the flag at all.
"""
import os
import uuid

import pytest

from ovos_bus_client.message import Message

from .driver import BusServer, WireTwinListener, LEGACY_SPEAK_TOPIC

WIRE_TWIN_PYTHON = os.environ.get("BACKCOMPAT_WIRE_TWIN_PYTHON", "")

pytestmark = pytest.mark.skipif(
    not WIRE_TWIN_PYTHON,
    reason="wire-twin gap needs BACKCOMPAT_WIRE_TWIN_PYTHON; see "
           "test/backcompat/build_venvs.sh venv_wire_twin_old")


@pytest.fixture(scope="module")
def wire_twin_stack():
    """One bus, one genuinely-old (1.5.0, no NamespaceTranslator) listener."""
    server = BusServer()
    listener = None
    try:
        listener = WireTwinListener(WIRE_TWIN_PYTHON, server.xdg)
        yield server, listener
    finally:
        if listener is not None:
            listener.stop()
        server.stop()


def test_pinned_listener_is_genuinely_pre_spec_tools(wire_twin_stack):
    """Adversarial guard against a drifted or mislabeled
    ``venv_wire_twin_old`` pin: assert the LIVE process reports no
    ``NamespaceTranslator`` in its own loaded ``client/client.py`` source --
    the real-symbol probe, not a version-string assumption (same discipline
    ``driver.core_canonicalizes`` already applies elsewhere in this suite).
    A silently-upgraded listener would make every other test in this module
    pass for the wrong reason: a modern client's own receive-side bridge,
    not the ``#286`` send-side wire twin this file exists to prove."""
    _, listener = wire_twin_stack
    assert listener.versions.get("client_has_namespace_translator") is False, (
        f"venv_wire_twin_old resolved a client that DOES carry "
        f"NamespaceTranslator -- this is no longer the genuinely pre-spec-"
        f"tools vintage the wire-twin gap needs; versions={listener.versions}")


def test_positive_control_old_listener_receives_a_legacy_emit(wire_twin_stack):
    """Positive control (mandatory per design Part 4 rule 5's discipline,
    applied here even though this module sits outside the S/C/M/A cell
    system): a plain legacy-spelled ``speak`` emit must reach the old
    listener. Without this, a dead/miswired listener subscription would let
    the real assertion below false-green -- "the canonical test passed"
    could mean either "the twin worked" or "nothing was ever checked"."""
    server, listener = wire_twin_stack
    bus = server.client()
    try:
        token = uuid.uuid4().hex
        bus.emit(Message(LEGACY_SPEAK_TOPIC, {"token": token}))
        assert listener.wait_for_token(token), (
            f"old listener never received a plain legacy-spelled {LEGACY_SPEAK_TOPIC!r} "
            f"emit -- the listener subscription itself is dead, so nothing "
            f"below this test can be trusted.\nlistener log:\n{listener.log}")
    finally:
        bus.close()


def test_modern_canonical_emit_reaches_old_listener_via_wire_twin(wire_twin_stack):
    """The real finding: drive a canonical ``ovos.utterance.speak`` dispatch
    through a real, MODERN ``MessageBusClient.emit()`` -- not a hand-emitted
    legacy frame, which is what every OTHER test in this repo that touches
    ``speak`` already does, and exactly the thing that let the original gap
    ship unnoticed (no test drove the send side). The old 1.5.0 listener,
    subscribed only to the legacy spelling, must still receive it -- which
    is only possible if ``emit()`` itself put a second, legacy-spelled wire
    frame down (``ovos-bus-client#286``'s ``_send_legacy_namespace_twin``),
    since this listener has no translator to conjure one locally.

    As of ``ovos-bus-client#286``'s follow-up (2.8.4a1, in progress) the
    namespace wire twin is gated by ``OVOS_BUS_WIRE_LEGACY_TWINS`` -- an
    ESCAPE HATCH that defaults ``true``, not an opt-in flag: compat targets
    stable releases, and the latest stable (``ovos-bus-client==1.5.0``,
    this test's own listener) is exactly who the twin protects, so it stays
    on unless explicitly turned off. A mid-vintage alpha receiver that would
    double-deliver a migrated topic is unsupported and expected to update,
    not accommodated by a default-off twin. This test still sets the flag
    explicitly on the SENDER for the duration of the emit -- not to opt in
    to something off by default, but as defensive pinning against any
    future default change; green here does not depend on this line on any
    released version today. ``ovos-bus-client==2.8.3a1`` predates the flag
    entirely, so it has no idea what ``OVOS_BUS_WIRE_LEGACY_TWINS`` means
    and the twin simply always fires there regardless of this env var --
    the flag is inertly ignored on that release, not read as false."""
    server, listener = wire_twin_stack
    # Pin the sender's twin behaviour explicitly for this test, restored
    # immediately after -- defensive against a future default change, not
    # an opt-in: the flag defaults true (escape hatch) as of 2.8.4a1.
    prev = os.environ.get("OVOS_BUS_WIRE_LEGACY_TWINS")
    os.environ["OVOS_BUS_WIRE_LEGACY_TWINS"] = "true"
    try:
        bus = server.client(emit_legacy=True)
    finally:
        if prev is None:
            os.environ.pop("OVOS_BUS_WIRE_LEGACY_TWINS", None)
        else:
            os.environ["OVOS_BUS_WIRE_LEGACY_TWINS"] = prev
    try:
        from ovos_spec_tools.messages import SpecMessage
        canonical_topic = SpecMessage.SPEAK
        assert canonical_topic == "ovos.utterance.speak"

        token = uuid.uuid4().hex
        bus.emit(Message(canonical_topic, {"token": token},
                         {"session": {"session_id": f"wiretwin-{token[:8]}"}}))
        assert listener.wait_for_token(token), (
            f"old (bus-client 1.5.0, no NamespaceTranslator) listener never "
            f"received the legacy 'speak' wire twin of a modern canonical "
            f"{canonical_topic!r} emit with OVOS_BUS_WIRE_LEGACY_TWINS=true "
            f"-- ovos-bus-client#286's send-side legacy namespace twin is "
            f"missing or not firing for this topic even with the escape-"
            f"hatch flag explicitly pinned true. A rebuilt but still-frozen satellite (this "
            f"listener's own shape) would silently never hear a real "
            f"ovos-core instance say anything at all.\n"
            f"listener log:\n{listener.log}")
    finally:
        bus.close()
