"""A real ``FallbackSkill`` in its own venv, on the shared bus.

Runs in the **skill venv**, exactly like ``skill_process.py``: whatever
``ovos-workshop`` and ``ovos-bus-client`` that venv resolved are what this
process runs on, and the driver observes what they do rather than asserting a
version.

The skill is written the way a skill author writes one. It declares a fallback
handler and binds nothing itself, so which poll topic it ends up subscribed to
is entirely the shipped ``FallbackSkill.__init__``'s doing. That is the point:
the driver reads ``BOUND_TOPICS`` back and can see whether this vintage
listens for the legacy poll, the canonical one, or both.
"""
import json
import os
import tempfile

from ovos_bus_client.client import MessageBusClient
from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill

SKILL_ID = os.environ.get("BACKCOMPAT_SKILL_ID", "backcompat.fallback.test")


def _dist_version(name: str) -> str:
    from importlib.metadata import version
    try:
        return version(name)
    except Exception:
        return "absent"


class BackCompatFallbackSkill(FallbackSkill):
    """Answers the fallback query, and says so on a topic of its own so the
    driver can tell a handled utterance from a mere poll answer."""

    def can_answer(self, message):
        """Required, not optional: on the testing-channel workshop the base
        implementation raises NotImplementedError, so a skill that omits this
        never answers the poll and fails silently."""
        return True

    @fallback_handler(priority=50)
    def handle_fallback(self, message):
        self.bus.emit(message.forward("backcompat.fallback.handled",
                                      {"skill_id": SKILL_ID}))
        return True


def main():
    bus = MessageBusClient()
    bus.run_in_thread()
    bus.connected_event.wait(30)

    root = tempfile.mkdtemp(prefix="backcompat-fallback-")
    os.makedirs(os.path.join(root, "locale", "en-us"), exist_ok=True)
    BackCompatFallbackSkill(skill_id=SKILL_ID, bus=bus, resources_dir=root)

    # Which poll spelling this vintage actually subscribed to. The driver
    # asserts on this rather than on a version number.
    events = getattr(bus.emitter, "_events", {})
    bound = sorted(t for t in events if "fallback" in t)
    print("BOUND_TOPICS " + json.dumps(bound), flush=True)
    print("VERSIONS " + json.dumps({
        "ovos_workshop": _dist_version("ovos-workshop"),
        "ovos_bus_client": _dist_version("ovos-bus-client"),
        "ovos_spec_tools": _dist_version("ovos-spec-tools"),
        # The send-side twin lives on the EMITTER's client, so a skill that
        # lacks it can still be reached by an emitter that has it.
        "has_namespace_twin": hasattr(MessageBusClient,
                                      "_send_legacy_namespace_twin"),
    }), flush=True)
    print("SKILL_READY", flush=True)

    import threading
    threading.Event().wait()


if __name__ == "__main__":
    main()
