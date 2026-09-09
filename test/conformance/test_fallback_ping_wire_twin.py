"""OVOS-FALLBACK-1 §6.1 — the canonical ping, the wire twin, and the ordering trigger.

Every shipped ``FallbackSkill`` subscribes to the LEGACY willingness poll alone
(``ovos_workshop/skills/fallback.py`` binds ``ovos.skills.fallback.ping`` to
``_handle_fallback_ack``; nothing binds the canonical ``ovos.fallback.ping``).

Today this is safe and flag-independent, and the first test pins WHY: ovos-core's
fallback service still EMITS the legacy spelling
(``intent_services/fallback_service.py`` forwards ``ovos.skills.fallback.ping``),
so core-legacy matches workshop-legacy directly with no bridge involved. The flag
suppresses the legacy twin of a *canonical* emit, and there is no canonical emit to
twin. A cell that drove core's stage and asserted "pongs arrive" would therefore
bank a green meaning "core still emits the old name", not "the flag is safe".

The risk has not vanished, it has a named trigger: the day core switches that emit
to the canonical ``ovos.fallback.ping``, the migration-map wire twin becomes the
ONLY thing reaching every shipped FallbackSkill — and that twin needs both the flag
ON and the map entry present (spec-tools#146). With the flag OFF and core emitting
canonical, fallback dies silently on both sides. So the ordering constraint is:
workshop must bind BOTH spellings before core switches the fallback-ping emit — not
before the flag flips.

This cell therefore does two things:
  1. GUARD the premise loudly: core still emits the legacy spelling. When core
     adopts the canonical topic this test fails, which is the signal that the
     danger window has opened and workshop's dual-binding must already be in place.
  2. TEST THE BRIDGE directly, independent of core's current emit: emit the
     canonical spelling explicitly and require the wire twin to carry it to the
     legacy-only subscriber. This proves the twin is the sole future path, and
     that it is flag-dependent — pong arrives with the mirror on, and does NOT
     with the mirror off, which is exactly what makes flag-OFF unsafe once core
     goes canonical.

HELD: the flag-dependent bridge test is not enabled in the both-positions matrix
until backcompat's ovoscope keep-src fix makes the source/destination rule uniform
across the flag. It drives a raw bus and does not use ovoscope, but it belongs to
the fallback-poll matrix and runs with it.
"""
import ast
import inspect
import os
import unittest

import pytest
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill

CANONICAL_PING = "ovos.fallback.ping"
LEGACY_PING = "ovos.skills.fallback.ping"
LEGACY_PONG = "ovos.skills.fallback.pong"


class _LegacyOnlyFallbackSkill(FallbackSkill):
    """A FallbackSkill exactly as shipped: it subscribes to the legacy ping
    through the base __init__ and binds nothing canonical."""

    def can_answer(self, message):
        return True

    @fallback_handler(priority=50)
    def handle_fallback(self, message):
        return True


def _mirror_on():
    """The flag position, read from the same env the bus resolves it from."""
    return os.environ.get("OVOS_BUS_EMIT_LEGACY", "true").strip().lower() in (
        "1", "true", "yes", "on")


class TestCoreFallbackEmitSpelling(unittest.TestCase):
    """Premise guard: this whole cell is meaningful only while core emits the
    legacy spelling. If core adopts the canonical topic, this fails LOUDLY so the
    cell can never silently become a test of the wrong thing — and so the ordering
    trigger (workshop must dual-bind first) is caught in CI rather than in a
    silent-fallback field report."""

    def test_core_still_emits_the_legacy_fallback_ping(self):
        from ovos_core.intent_services import fallback_service
        src = inspect.getsource(fallback_service)
        emits = set()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and node.value in (CANONICAL_PING, LEGACY_PING):
                emits.add(node.value)
        self.assertIn(LEGACY_PING, emits,
                      "core's fallback service no longer references the legacy ping")
        self.assertNotIn(
            CANONICAL_PING, emits,
            "core now references the canonical ovos.fallback.ping — the danger "
            "window is OPEN: every shipped FallbackSkill binds the legacy spelling "
            "only, so workshop MUST bind both spellings before this lands, or a "
            "flag-off deployment loses fallback silently. Update this guard once "
            "workshop dual-binds.")


@pytest.mark.fallback_ping_wire_twin
class TestCanonicalPingReachesLegacyOnlySubscriber(unittest.TestCase):
    """Bridge test — independent of core's current emit. Emits the canonical
    spelling explicitly and requires the wire twin to deliver it to a legacy-only
    subscriber. HELD in the matrix pending the ovoscope keep-src fix."""

    def setUp(self):
        self.bus = FakeBus()
        self.pongs = []
        self.bus.on(LEGACY_PONG, self.pongs.append)
        self.skill = _LegacyOnlyFallbackSkill(bus=self.bus, skill_id="legacy.fallback.test")

    def tearDown(self):
        self.skill.default_shutdown()

    def test_skill_binds_only_the_legacy_ping(self):
        self.assertTrue(self.bus.ee.listeners(LEGACY_PING),
                        "shipped FallbackSkill must subscribe to the legacy ping")
        self.assertFalse(self.bus.ee.listeners(CANONICAL_PING),
                         "a legacy-only skill must not bind the canonical ping")

    def test_canonical_ping_reaches_the_legacy_subscriber_via_the_twin(self):
        self.bus.emit(Message(CANONICAL_PING, {"utterance_id": "u1"},
                              {"session": {"session_id": "s1"}}))
        position = "mirror-on" if _mirror_on() else "mirror-off"
        # With the mirror on the twin carries the canonical emit to the legacy
        # subscriber and the pong arrives; with the mirror off nothing does. The
        # off-position zero is not a bug today (core emits legacy) — it is proof
        # that once core goes canonical, flag-off breaks fallback for every
        # legacy-only skill absent workshop dual-binding.
        self.assertEqual(
            len(self.pongs), 1,
            f"[{position}] canonical ping produced {len(self.pongs)} pongs "
            f"(expected exactly 1 via the wire twin); "
            f"{'zero = the twin did not deliver, fallback silent' if not self.pongs else 'more than one = doubled'}")
        self.assertEqual(self.pongs[0].data.get("skill_id"), "legacy.fallback.test")
        self.assertTrue(self.pongs[0].data.get("can_handle"))
