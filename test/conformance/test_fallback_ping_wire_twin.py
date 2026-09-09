"""OVOS-FALLBACK-1 §6.1 — the canonical ping must reach a legacy-only subscriber.

Every shipped ``FallbackSkill`` subscribes to the LEGACY willingness poll alone —
``ovos_workshop/skills/fallback.py`` binds ``ovos.skills.fallback.ping`` to
``_handle_fallback_ack`` and nothing binds the canonical ``ovos.fallback.ping``.
So when a modern core emits the canonical topic, the only thing that carries it to
those skills is the migration-map wire twin (spec-tools maps
``ovos.skills.fallback.ping`` <-> ``ovos.fallback.ping``). If that twin does not
fire, the skill never sees the poll and answers nothing.

The failure this cell exists to catch is NOT a doubled response — the mirror guard
already stops a double-subscribed handler running twice. It is ZERO pongs: a
legacy-only subscriber that never receives the canonical frame, so the fallback
stage matches nothing with no log line on either side. The assertion is therefore
POSITIVE — the pong must arrive exactly once — because "no duplicate response" is
satisfied just as well by a fallback that is entirely dead.

Run in both flag positions. With the legacy mirror on (testing channel) the twin
delivers and the pong arrives. With the mirror off (modern transport) a legacy-only
subscriber is expected to fall silent; that is the documented flag divergence, and
this cell is where it must show as a real result rather than be smoothed over.

HELD: not enabled until backcompat's ovoscope keep-src fix lands (ovoscope
__init__.py DEFAULT_KEEP_SRC hardcodes the legacy ping spelling, so ovoscope's
source/destination rules change meaning across the flag). This cell drives a raw
bus and a real FallbackSkill and does not use ovoscope's assertion helpers, but it
is gated with the rest of the fallback-poll matrix until the instrument is uniform.
"""
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
    through the base __init__ (fallback.py) and binds nothing canonical."""

    def can_answer(self, message):
        return True

    @fallback_handler(priority=50)
    def handle_fallback(self, message):
        return True


def _mirror_position():
    """The flag position this run is in, from the same env the bus reads."""
    return os.environ.get("OVOS_BUS_EMIT_LEGACY", "true").strip().lower() in (
        "1", "true", "yes", "on")


@pytest.mark.fallback_ping_wire_twin
class TestCanonicalPingReachesLegacyOnlySubscriber(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.pongs = []
        self.bus.on(LEGACY_PONG, self.pongs.append)
        self.skill = _LegacyOnlyFallbackSkill(bus=self.bus, skill_id="legacy.fallback.test")

    def tearDown(self):
        self.skill.default_shutdown()

    def test_skill_binds_only_the_legacy_ping(self):
        """Guard the premise: the skill must NOT bind the canonical topic, or the
        cell would prove nothing about the wire twin."""
        self.assertTrue(self.bus.ee.listeners(LEGACY_PING),
                        "shipped FallbackSkill must subscribe to the legacy ping")
        self.assertFalse(self.bus.ee.listeners(CANONICAL_PING),
                         "a legacy-only skill must not bind the canonical ping")

    def test_canonical_ping_is_answered_exactly_once(self):
        """Emit the canonical ovos.fallback.ping and require the legacy-only
        subscriber to answer it exactly once via the wire twin. Zero pongs is
        the silent-death failure this cell exists to catch."""
        self.bus.emit(Message(CANONICAL_PING,
                              {"utterance_id": "u1"},
                              {"session": {"session_id": "s1"}}))
        position = "mirror-on" if _mirror_position() else "mirror-off"
        self.assertEqual(
            len(self.pongs), 1,
            f"[{position}] canonical ping produced {len(self.pongs)} pongs; a "
            f"legacy-only FallbackSkill answered {'nothing (silent death)' if not self.pongs else 'more than once'}")
        self.assertEqual(self.pongs[0].data.get("skill_id"), "legacy.fallback.test")
        self.assertTrue(self.pongs[0].data.get("can_handle"))
