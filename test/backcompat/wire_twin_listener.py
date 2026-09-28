"""Standalone OLD-vintage bus listener for the wire-twin gap
(``ovos-bus-client#286``).

Design: this fills the gap ``docs/matrix-design.md``'s axis model does not
cover -- none of S/C/M/A vary the SKILL/CORE/MATCHER/AUDIO container's own
``ovos-bus-client`` (every one of those floors it, per §1.3, so a rebuilt
container always resolves a current client). The wire-twin gap is instead
about a client vintage that predates ``ovos_spec_tools.messages.
NamespaceTranslator`` entirely -- a genuinely frozen satellite whose own
bus-client cannot bridge ANY namespace, old or new. ``ovos-bus-client==
1.5.0`` is that vintage (verified live: no ``NamespaceTranslator``,
``MIGRATION_MAP``, or ``ovos_spec_tools`` reference anywhere in its
installed ``client/client.py`` -- the last PyPI release entirely
pre-spec-tools; see ``build_venvs.sh``'s ``venv_wire_twin_old`` pin and
``driver.py``'s ``wait_for_response_mode`` docstring, which already leans on
this exact same vintage's ``ovos-bus-client==1.5.0`` floor for a different
reason).

This process does nothing but subscribe to the legacy ``speak`` topic (the
only spelling a client this old can ever know about -- it has no receive-side
translator to bridge a canonical frame locally) and report every message it
receives on stdout, keyed by the token the driver stamped into the payload.
No workshop, no core, no padatious: this is a bare listener, the wire-twin
equivalent of ``audio_process.py``'s handshake shape (a ``VERSIONS`` line,
then ``READY``), not a skill or an audio simulator.
"""
import json
import os
import sys

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message

LEGACY_SPEAK_TOPIC = "speak"

#: Which legacy topics this process subscribes to. ``speak`` alone by
#: default, so the ovos-bus-client#286 cell that owns this script is
#: unchanged. ``WIRE_TWIN_TOPICS`` is a comma-separated list, used by the
#: FALLBACK-1 quadrant cells to put the same genuinely-old client on the four
#: ``ovos.skills.fallback.*`` legacy names. The topics are reported back in
#: VERSIONS so a cell asserts what the live process subscribed to rather than
#: what it meant to ask for.
TOPICS = [t.strip() for t in
          os.environ.get("WIRE_TWIN_TOPICS", LEGACY_SPEAK_TOPIC).split(",")
          if t.strip()]

_received = []


def _handle(message: Message):
    """Report the token AND the topic the frame arrived on.

    The topic matters once more than one is subscribed: a cell that asserts
    "the old client heard the legacy spelling" must be able to tell which
    legacy spelling, or a bridge that delivered the wrong twin would pass.
    The context session travels too, because FALLBACK-1 §3.2/§3.4 key the
    registry by ``context.session.session_id`` and a twin that drops the
    context breaks that clause without changing any payload.
    """
    data = message.data or {}
    session = ((message.context or {}).get("session") or {}).get("session_id")
    print("RECEIVED " + json.dumps({
        "token": data.get("token"),
        "topic": message.msg_type,
        "data": data,
        "session_id": session,
    }), flush=True)


def main():
    bus = MessageBusClient()
    bus.run_in_thread()
    if not bus.connected_event.wait(30):
        print("ERROR could not connect to messagebus", flush=True)
        sys.exit(1)

    for topic in TOPICS:
        bus.on(topic, _handle)

    # VERSIONS reports what this process actually resolved, live -- not an
    # assumption from the vintage this script was told to run under. A drift
    # in the pin (build_venvs.sh's venv_wire_twin_old) would otherwise let a
    # stale/mislabeled venv silently agree with what the test expects.
    from importlib.metadata import version, PackageNotFoundError
    try:
        bus_client_version = version("ovos-bus-client")
    except PackageNotFoundError:
        bus_client_version = None
    try:
        import ovos_spec_tools  # noqa: F401
        has_spec_tools_importable = True
    except ImportError:
        has_spec_tools_importable = False
    # The real thing this process depends on is not "ovos-spec-tools is
    # uninstalled" (1.5.0's OWN dependency graph may still pull it in
    # transitively via something else) but "this client's own client.py
    # never imports/uses it" -- checked once, directly against the loaded
    # module's source, the same real-symbol-over-version-string discipline
    # the rest of this suite already applies (see driver.core_canonicalizes).
    import inspect
    import ovos_bus_client.client.client as _client_mod
    client_src = inspect.getsource(_client_mod)
    has_namespace_translator = "NamespaceTranslator" in client_src

    print("VERSIONS " + json.dumps({
        "ovos_bus_client_version": bus_client_version,
        "ovos_spec_tools_importable": has_spec_tools_importable,
        "client_has_namespace_translator": has_namespace_translator,
        "speak_topic": LEGACY_SPEAK_TOPIC,
        "subscribed_topics": TOPICS,
    }), flush=True)
    print("READY", flush=True)

    import threading
    threading.Event().wait()


if __name__ == "__main__":
    main()
