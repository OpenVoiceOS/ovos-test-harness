"""OVOS-OCP-1 conformance suite — the Virtual Media Player.

Encodes the normative clauses of OVOS-OCP-1
(``ovos/org/architecture/ocp-1.md``) as end-to-end assertions against the real
``ovos_media.player.OCPMediaPlayer`` — the OVOS Virtual Media Player — driven on
a ``FakeBus`` through :class:`ovoscope.OCPPlayerHarness`.

Driver model
------------
OCP-1 is a property of the *player*, not of the intent orchestrator: the
``ovos.common_play.*`` state machine (§3, §4.4) lives in ``ovos-media`` /
``ovos-ocp-audio-plugin``, downstream of the OCP pipeline plugin that only does
discovery (§4.2 ``…search``). ``OCPPlayerHarness`` instantiates the real player
with a ``MockOCPBackend`` as its sole audio backend, so every control request
(§4.3) and every state report (§4.4) is exercised against the authoritative
implementation. ``OCPCaptureSession`` records the ``ovos.common_play.*`` wire
stream so the §4.4 announcements can be asserted by topic.

Coverage map (clause -> status against the installed ``ovos-media`` player):
- §3.1 PlayerState enum {STOPPED,PLAYING,PAUSED} ................ green
- §3.2 MediaState enum members ................................. green
- §3.3 loop + shuffle modes tracked ............................ green
- §3.3 single writer — idempotent same-state, no re-emit ....... green
- §4.1 ``ovos.common_play.`` namespace reservation ............. green
- §4.3 pause / resume / stop transition the player ............. green
- §4.3 next / stop are no-ops with no media ................... green
- §4.3 pause is a no-op with no media ......................... xfail (player -> PAUSED)
- §4.4 ``…player.state`` announced on transition .............. green
- §4.4 ``…media.state`` announced on media change ............. green
- §7   stop -> STOPPED ......................................... green
- §6   SEI introspection responds ............................. green (informative)

xfail discipline per ``_conformance.py``: a test asserts the clause the spec
mandates, runs it, and is marked ``xfail(strict=False)`` only where the player
diverges — citing the clause and the actual behaviour. Non-bus-observable prose
(multi-session isolation §5, the MPRIS bridge §6, arbitration §6.3) is noted but
not asserted because a single-player ``FakeBus`` harness cannot exhibit it.
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

from ovoscope import OCPPlayerHarness, OCPCaptureSession
from ovos_utils.ocp import MediaEntry, MediaState, PlayerState, PlaybackType

# The Virtual Media Player (OVOS-OCP-1 §2/§3/§4) lives in ovos-media, installed
# --no-deps by the integration workflow (it pins an incompatible bus-client; see
# requirements.txt). If it is absent the OCPPlayerHarness cannot start, so the
# whole module skips cleanly rather than erroring — the enum/contract tests that
# need only ovos-utils.ocp still run.
try:
    import ovos_media.player  # noqa: F401
    _HAS_OCP_PLAYER = True
except Exception:
    _HAS_OCP_PLAYER = False

_requires_player = pytest.mark.skipif(
    not _HAS_OCP_PLAYER,
    reason="ovos-media (the OVOS-OCP-1 Virtual Media Player) is not installed; "
           "install it with `pip install --no-deps ovos-media`",
)


def _entry(uri="http://example.com/conformance.mp3"):
    return MediaEntry(uri=uri, playback=PlaybackType.AUDIO)


def setUpModule():
    LOG.set_level("ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# §3 — State model
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3StateModel(TestCase):
    """§3: three orthogonal state axes, each a fixed enumeration; the player
    MUST NOT report a value outside its axis."""

    def test_player_state_enum_members(self):
        """§3.1 MUST: ``PlayerState`` is exactly ``{STOPPED, PLAYING, PAUSED}``."""
        names = {s.name for s in PlayerState}
        self.assertEqual(names, {"STOPPED", "PLAYING", "PAUSED"})

    def test_media_state_enum_members(self):
        """§3.2 MUST: ``MediaState`` carries at minimum ``NO_MEDIA``, ``LOADING``,
        ``LOADED``, ``BUFFERING``, ``END_OF_MEDIA``, ``INVALID_MEDIA``.

        The spec names the axis members conceptually; the implementation spells
        the transient ones with a ``_MEDIA`` suffix (``LOADING_MEDIA``,
        ``BUFFERING_MEDIA``, ``LOADED_MEDIA``). This asserts semantic presence of
        each required member, tolerating the suffix."""
        names = {s.name for s in MediaState}
        required_stems = ["NO_MEDIA", "LOADING", "LOADED", "BUFFERING",
                          "END_OF_MEDIA", "INVALID_MEDIA"]
        missing = [stem for stem in required_stems
                   if not any(stem in n for n in names)]
        self.assertFalse(missing, f"MediaState missing axis members: {missing}")

    @_requires_player
    def test_loop_and_shuffle_tracked(self):
        """§3.3 MUST: the player tracks a loop mode (≥ ``NONE``, ``REPEAT``,
        ``REPEAT_TRACK``) and a boolean shuffle mode."""
        with OCPPlayerHarness() as h:
            self.assertTrue(hasattr(h.player, "loop_state"),
                            "player exposes no loop-mode axis")
            self.assertIsInstance(h.player.shuffle, bool,
                                  "player.shuffle is not a boolean axis")

    @_requires_player
    def test_player_is_single_writer_idempotent(self):
        """§3.3 MUST: the player is the single writer of its own state. Re-issuing
        a request that does not change the authoritative state announces nothing
        — the player does not echo a no-op transition."""
        with OCPPlayerHarness() as h:
            h.play(_entry())
            self.assertEqual(h.player.state, PlayerState.PLAYING)
            with OCPCaptureSession(
                h.bus, track_prefixes=["ovos.common_play.player.state"]
            ) as s:
                # a second play while already PLAYING is a no-op transition
                h.bus.emit(Message("ovos.common_play.play",
                                   {"media": _entry().as_dict,
                                    "playlist": [_entry().as_dict]}))
                time.sleep(0.05)
            self.assertEqual(
                len(s.messages), 0,
                "player re-announced player.state for a no-op same-state set")


# ─────────────────────────────────────────────────────────────────────────────
# §4.1 — Namespace reservation
# ─────────────────────────────────────────────────────────────────────────────

@_requires_player
class TestSec41Namespace(TestCase):
    """§4.1: all player traffic is namespaced under ``ovos.common_play.``."""

    def test_all_player_traffic_is_common_play_namespaced(self):
        """§4.1 MUST: every playback-mutating / state message the player emits in
        response to a request rides the reserved ``ovos.common_play.`` prefix."""
        with OCPPlayerHarness() as h:
            with OCPCaptureSession(
                h.bus, track_prefixes=["ovos.common_play."]
            ) as s:
                h.play(_entry())
                h.pause()
                h.resume()
                h.stop()
            self.assertTrue(s.messages, "no common_play traffic captured")
            for m in s.messages:
                self.assertTrue(
                    m.msg_type.startswith("ovos.common_play."),
                    f"player emitted off-namespace topic {m.msg_type!r}")


# ─────────────────────────────────────────────────────────────────────────────
# §4.3 — Control requests
# ─────────────────────────────────────────────────────────────────────────────

@_requires_player
class TestSec43ControlRequests(TestCase):
    """§4.3: control requests act on the existing now-playing without acquiring
    new media; ``pause`` → PAUSED, ``resume`` → PLAYING, ``stop`` → STOPPED."""

    def test_pause_transitions_to_paused(self):
        """§4.3 MUST: ``ovos.common_play.pause`` drives now-playing → PAUSED."""
        with OCPPlayerHarness() as h:
            h.play(_entry())
            h.pause()
            self.assertEqual(h.player.state, PlayerState.PAUSED)

    def test_resume_transitions_to_playing(self):
        """§4.3 MUST: ``ovos.common_play.resume`` drives now-playing → PLAYING."""
        with OCPPlayerHarness() as h:
            h.play(_entry())
            h.pause()
            h.resume()
            self.assertEqual(h.player.state, PlayerState.PLAYING)

    def test_stop_transitions_to_stopped(self):
        """§4.3 MUST: ``ovos.common_play.stop`` drives now-playing → STOPPED."""
        with OCPPlayerHarness() as h:
            h.play(_entry())
            h.stop()
            self.assertEqual(h.player.state, PlayerState.STOPPED)

    def test_stop_is_noop_with_no_media(self):
        """§4.3 MUST: control requests are idempotent w.r.t. absent media —
        ``stop`` with nothing playing is a no-op (stays STOPPED), not an error."""
        with OCPPlayerHarness() as h:
            self.assertEqual(h.player.state, PlayerState.STOPPED)
            h.stop()
            self.assertEqual(h.player.state, PlayerState.STOPPED)

    def test_next_is_noop_with_no_media(self):
        """§4.3 MUST: ``next`` with nothing playing is a no-op, not an error —
        the player stays STOPPED."""
        with OCPPlayerHarness() as h:
            h.next_track()
            self.assertEqual(h.player.state, PlayerState.STOPPED)

    @pytest.mark.xfail(
        reason="OVOS-OCP-1 §4.3 MUST: 'issuing pause with nothing playing is a "
               "no-op, not an error'; the ovos-media player transitions to "
               "PAUSED on a bare pause request with no now-playing media.",
        strict=False,
    )
    def test_pause_is_noop_with_no_media(self):
        """§4.3 MUST: ``pause`` with no media present is a no-op — the player
        MUST NOT leave STOPPED for PAUSED when there is nothing to pause."""
        with OCPPlayerHarness() as h:
            self.assertEqual(h.player.state, PlayerState.STOPPED)
            h.pause()
            self.assertEqual(
                h.player.state, PlayerState.STOPPED,
                "pause with no media left the player non-STOPPED")


# ─────────────────────────────────────────────────────────────────────────────
# §4.4 — State reports
# ─────────────────────────────────────────────────────────────────────────────

@_requires_player
class TestSec44StateReports(TestCase):
    """§4.4: the player MUST announce state transitions so consumers stay
    coherent — ``…player.state`` / ``…media.state`` / ``…track.state``."""

    def test_player_state_announced_on_transition(self):
        """§4.4 MUST: a player-state transition is announced on
        ``ovos.common_play.player.state``."""
        with OCPPlayerHarness() as h:
            with OCPCaptureSession(
                h.bus, track_prefixes=["ovos.common_play.player.state"]
            ) as s:
                h.play(_entry())
            self.assertTrue(
                any(m.msg_type == "ovos.common_play.player.state"
                    for m in s.messages),
                "no player.state announced on play transition")

    def test_player_state_payload_carries_state(self):
        """§4.4 MUST: the ``…player.state`` report carries the §3.1 value."""
        with OCPPlayerHarness() as h:
            with OCPCaptureSession(
                h.bus, track_prefixes=["ovos.common_play.player.state"]
            ) as s:
                h.play(_entry())
            msg = next((m for m in s.messages
                        if m.msg_type == "ovos.common_play.player.state"), None)
            self.assertIsNotNone(msg)
            self.assertIn("state", msg.data,
                          "player.state report has no 'state' field")

    def test_media_state_announced_on_media_change(self):
        """§4.4 MUST: a loaded-media transition is announced on
        ``ovos.common_play.media.state`` — exercised by an end-of-media event."""
        with OCPPlayerHarness() as h:
            h.play(_entry())
            with OCPCaptureSession(
                h.bus, track_prefixes=["ovos.common_play.media.state"]
            ) as s:
                h.simulate_track_end()
            self.assertTrue(
                any(m.msg_type == "ovos.common_play.media.state"
                    for m in s.messages),
                "no media.state announced on end-of-media")


# ─────────────────────────────────────────────────────────────────────────────
# §6 — Introspection / SEI surface (informative; bus-observable subset)
# ─────────────────────────────────────────────────────────────────────────────

@_requires_player
class TestSec6Introspection(TestCase):
    """§6 is about the MPRIS bridge (not bus-observable on a FakeBus), but the
    player's SEI (stream-extractor-id) introspection query is bus-observable and
    demonstrates the player answers introspection pull-queries."""

    def test_sei_query_gets_a_response(self):
        """The player answers ``ovos.common_play.SEI.get`` with a response —
        a pull-query / response introspection surface (informative, supports §6)."""
        with OCPPlayerHarness() as h:
            got = []
            h.bus.on("ovos.common_play.SEI.get.response", lambda m: got.append(m))
            h.bus.emit(Message("ovos.common_play.SEI.get"))
            time.sleep(0.1)
            self.assertTrue(got, "SEI.get drew no response")


# ─────────────────────────────────────────────────────────────────────────────
# §7 — Relationship to stop
# ─────────────────────────────────────────────────────────────────────────────

@_requires_player
class TestSec7Stop(TestCase):
    """§7: when stop dispatches to the player, it MUST transition now-playing to
    STOPPED (§3.1)."""

    def test_stop_cascade_stops_playback(self):
        """§7 MUST: a stop request transitions now-playing → STOPPED and the
        backend ceases playing."""
        with OCPPlayerHarness() as h:
            h.play(_entry())
            self.assertEqual(h.player.state, PlayerState.PLAYING)
            h.stop()
            self.assertEqual(h.player.state, PlayerState.STOPPED)
            self.assertFalse(h.backend.is_playing,
                             "backend kept playing after stop")


# ─────────────────────────────────────────────────────────────────────────────
# §5 / §6 — non-bus-observable in a single-player FakeBus harness
# ─────────────────────────────────────────────────────────────────────────────
# not bus-observable: §5 per-session isolation — OCPPlayerHarness runs ONE
#   player for one (default) session; "pause for session A MUST NOT affect
#   session B" needs two concurrent player instances a single harness can't host.
# not bus-observable: §6.1/§6.2/§6.3 the MPRIS bridge (Role A export, Role B
#   external control, arbitration) is a D-Bus surface, SHOULD/MAY-level, and is
#   mocked out (OcpMprisExporter) in the harness — no session D-Bus in CI.
# not bus-observable: §2 "exactly one player per session" — structural, asserted
#   by construction (one OCPMediaPlayer == one arbitration point), not on the bus.
