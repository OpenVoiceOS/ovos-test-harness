"""``ovos.common_play.*`` wire cells against the ovos-media daemon.

``ovos-media`` itself is a fresh-install component: it carries no backwards
compatibility of its own. What does need protecting is the WIRE. Old
``ovos-workshop`` OCP skills, the OCP pipeline plugin and hand-rolled bus
clients all speak ``ovos.common_play.*`` at the daemon, and that contract is
frozen. Every subscription the daemon makes lives in one registration table
(``ovos_media/bus/api.py``), so these cells drive the daemon the way those
peers do -- by emitting on the bus and reading what comes back -- and never
by calling player, catalog or skill methods directly.

The daemon side runs through ``ovoscope.OCPPlayerHarness``: a real
``OCPMediaPlayer`` on a ``FakeBus``, with a ``MockOCPBackend`` standing in
for an audio device. The player registers its full ``OCPBusApi`` table there,
so what the cells emit reaches the same handlers a real deployment reaches.

Both halves of ``ovos-media`` are always installed together at one vintage --
there is no deployment running one version for the player and another for the
catalog -- so these cells run in-process on one bus rather than across the
two-venv split ``test_mixed_version_matrix.py`` needs.
"""
import os
import time

import pytest
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

#: These cells need ovos-media and ovoscope installed. Only the integration
#: workflow installs them, so only that job sets OCP_WIRE_CELLS=1 and runs
#: them. The mixed-version matrix cells build their own venv pairs from a
#: combo's pins, which carry neither package, and would otherwise crash the
#: whole test/backcompat collection on the import below.
#:
#: The gate is the env var, never importability: in the job that DOES own
#: these cells the var is set, so a broken ovos-media install surfaces as an
#: ImportError failure here instead of a quiet skip.
OCP_WIRE_CELLS = os.environ.get("OCP_WIRE_CELLS") == "1"

pytestmark = pytest.mark.skipif(
    not OCP_WIRE_CELLS,
    reason="OCP wire cells run only in the job that installs ovos-media "
           "(set OCP_WIRE_CELLS=1)")

if OCP_WIRE_CELLS:
    from ovoscope import OCPPlayerHarness

STATUS = "ovos.common_play.status"
STATUS_RESPONSE = "ovos.common_play.status.response"
SKILL_ID = "ovos.common_play.favorites"


def setup_module(_module):
    LOG.set_level("ERROR")


@pytest.fixture
def track():
    from ovos_utils.ocp import MediaEntry, PlaybackType
    return MediaEntry(uri="http://example.com/1.mp3",
                      playback=PlaybackType.AUDIO, title="One")


# ─────────────────────────────────────────────────────────────────────────
# (a) status roundtrip
# ─────────────────────────────────────────────────────────────────────────

def test_ocp_status_query_is_answered_by_the_daemon():
    """A bare ``ovos.common_play.status`` emit is answered on
    ``ovos.common_play.status.response`` with the documented status payload.

    This is the query an old OCP skill or pipeline makes to find out what is
    playing; ``ovos_media/bus/api.py`` routes it to
    ``OCPMediaPlayer.handle_status``, which replies from the published
    snapshot. An idle daemon answers -- it does not stay silent -- and the
    reply carries ``player_state`` STOPPED and ``media_state`` NO_MEDIA,
    plus the empty title/artist an idle player reports.
    """
    from ovos_utils.ocp import MediaState, PlayerState

    with OCPPlayerHarness() as h:
        reply = h.bus.wait_for_response(Message(STATUS), timeout=3)

        assert reply is not None, "the daemon did not answer a status query"
        assert reply.msg_type == STATUS_RESPONSE
        assert reply.data["player_state"] == PlayerState.STOPPED
        assert reply.data["media_state"] == MediaState.NO_MEDIA
        assert reply.data["title"] == ""
        assert reply.data["artist"] == ""


def test_ocp_status_reports_the_playing_track(track):
    """The same query, after a play command, reports the track over the wire.

    Playing is driven by an ``ovos.common_play.play`` emit -- the topic an
    OCP skill's playback request lands on -- so title and player state in the
    reply come from the daemon's own reaction to the wire, not from state a
    test wrote into the player.
    """
    from ovos_utils.ocp import PlayerState

    with OCPPlayerHarness() as h:
        h.bus.emit(Message("ovos.common_play.play", {"media": track.as_dict}))
        time.sleep(0.5)

        reply = h.bus.wait_for_response(Message(STATUS), timeout=3)
        assert reply is not None, "the daemon did not answer a status query"
        assert reply.data["title"] == "One"
        assert reply.data["player_state"] == PlayerState.PLAYING


# ─────────────────────────────────────────────────────────────────────────
# (c) no responder is distinguishable from idle
# ─────────────────────────────────────────────────────────────────────────

def test_ocp_status_without_a_daemon_gets_no_reply():
    """With no daemon on the bus the status query times out.

    A caller must be able to tell "no player is running" from "a player is
    running and idle": the first is no reply at all, the second is the
    STOPPED/NO_MEDIA reply the cell above asserts. Collapsing the two would
    make a dead daemon read as a quiet one.
    """
    from ovos_utils.fakebus import FakeBus

    bus = FakeBus()
    try:
        assert bus.wait_for_response(Message(STATUS), timeout=1) is None
    finally:
        bus.close()


# ─────────────────────────────────────────────────────────────────────────
# (b) session gating on the playback commands
# ─────────────────────────────────────────────────────────────────────────

def test_ocp_play_is_gated_to_the_default_session(track):
    """``ovos.common_play.play`` from a non-default session is ignored; the
    same message from the default session plays.

    ``gated=True`` in the registration table routes the topic through
    ``ovos_media.utils.is_default_session``. In a HiveMind split the OCP
    pipeline runs on the server and stamps commands with the ORIGINATING
    session; a server-side daemon acting on a satellite's play command would
    start audio on the wrong device. Both directions are proven here, so a
    gate that simply drops everything fails this cell just as loudly as a
    gate that is off.
    """
    from ovos_utils.ocp import PlayerState

    with OCPPlayerHarness() as h:
        h.bus.emit(Message("ovos.common_play.play", {"media": track.as_dict},
                           {"session": {"session_id": "satellite-1"}}))
        time.sleep(0.5)
        assert h.player.state == PlayerState.STOPPED, (
            "a satellite session's play command started playback on a "
            "daemon it does not own")
        assert h.player.now_playing.uri == ""

        h.bus.emit(Message("ovos.common_play.play", {"media": track.as_dict},
                           {"session": {"session_id": "default"}}))
        time.sleep(0.5)
        assert h.player.state == PlayerState.PLAYING, (
            "the default session's play command was dropped -- a gate that "
            "refuses everything is not a session check")
        assert h.player.now_playing.uri == track.uri


def test_ocp_shuffle_set_is_gated_to_the_default_session():
    """The same gate on ``ovos.common_play.shuffle.set``: a non-default
    session cannot flip the daemon's shuffle state, the default one can."""
    with OCPPlayerHarness() as h:
        assert h.player.shuffle is False

        h.bus.emit(Message("ovos.common_play.shuffle.set", {},
                           {"session": {"session_id": "satellite-1"}}))
        time.sleep(0.3)
        assert h.player.shuffle is False, (
            "a satellite session's shuffle.set reached the daemon's state")

        h.bus.emit(Message("ovos.common_play.shuffle.set", {},
                           {"session": {"session_id": "default"}}))
        time.sleep(0.3)
        assert h.player.shuffle is True, (
            "the default session's shuffle.set was dropped")


# ─────────────────────────────────────────────────────────────────────────
# (d) stop must not advance the queue
# ─────────────────────────────────────────────────────────────────────────

def test_ocp_stop_no_advance():
    """A 2-track queue is playing; an explicit stop lands (triggered via
    ``mycroft.stop``, the external bus stop topic); a backend's own
    ``END_OF_MEDIA`` racing in right after must NOT advance the queue to
    track 2.

    This reproduces the race ``player.py`` describes: OPM backends emit
    ``END_OF_MEDIA`` from ``ocp_stop()``, which is indistinguishable from a
    track ending naturally, so an explicit stop followed by that emission
    must not read as "track finished, play the next one". The daemon tells
    them apart with a ``_stop_requested`` flag set before any backend is
    asked to stop.

    Reproduction note: emitting ``ovos.common_play.media.state`` on the bus
    would also reach other subscribers of that topic on the same synchronous
    ``FakeBus`` dispatch, which could mask the defect for an unrelated
    reason. So the racing END_OF_MEDIA is delivered straight into
    ``handle_player_media_update`` -- the exact call a real bus dispatch
    makes into the player -- at the narrow window while ``stop()`` is
    finishing and before ``reset()`` clears the queue anyway.
    """
    from ovos_utils.ocp import MediaEntry, MediaState, PlaybackType

    with OCPPlayerHarness() as h:
        t1 = MediaEntry(uri="http://example.com/1.mp3",
                        playback=PlaybackType.AUDIO, title="One")
        t2 = MediaEntry(uri="http://example.com/2.mp3",
                        playback=PlaybackType.AUDIO, title="Two")
        h.bus.emit(Message("ovos.common_play.play", {
            "media": t1.as_dict,
            "playlist": [t1.as_dict, t2.as_dict],
        }))
        # BaseMediaService.stop()'s own anti-flicker debounce
        # (`time.monotonic() - play_start_time > 1`) must clear before an
        # explicit stop is even actioned.
        time.sleep(1.2)
        assert h.player.now_playing.uri == t1.uri, "setup: track 1 not playing"

        orig_reset = h.player.reset

        def racing_reset():
            h.player.handle_player_media_update(Message(
                "ovos.common_play.media.state",
                {"state": MediaState.END_OF_MEDIA}))
            return orig_reset()

        h.player.reset = racing_reset

        h.bus.emit(Message("mycroft.stop"))
        time.sleep(0.2)

        now_uri = h.player.now_playing.uri if h.player.now_playing else None
        assert now_uri != t2.uri, (
            f"queue advanced to track 2 ({t2.uri!r}) after an explicit stop "
            f"-- 'stop must not advance' violated")


# ─────────────────────────────────────────────────────────────────────────
# (e) the voice skill's intents announce themselves on the wire
# ─────────────────────────────────────────────────────────────────────────

def test_ocp_voice_skill_registers_its_intents(tmp_path, monkeypatch):
    """The daemon's voice front-end announces its five intent files on the
    bus under the skill id ``ovos.common_play.favorites``.

    ``OCPVoiceSkill`` is an ordinary ``OVOSCommonPlaybackSkill``: its
    ``register_intent_file`` calls reach the intent service as
    ``padatious:register_intent`` messages naming
    ``<skill_id>:<intent name>``. That namespaced name is what an intent
    pipeline matches on and what a downstream consumer keys off, so the
    skill id and the five intent names are wire surface too, not internals.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    from ovos_media.catalog import LikedSongsStore
    from ovos_media.skill import OCPVoiceSkill
    from ovos_utils.fakebus import FakeBus

    bus = FakeBus()
    registered = []
    bus.on("padatious:register_intent",
           lambda m: registered.append(m.data.get("name")))

    skill = OCPVoiceSkill(bus=bus, skill_id=SKILL_ID,
                          likes=LikedSongsStore())
    try:
        time.sleep(0.5)
        expected = {f"{SKILL_ID}:{name}" for name in
                    ("WhatSong", "WhatAlbum", "WhatArtist",
                     "ShuffleOn", "ShuffleOff")}
        missing = expected - set(registered)
        assert not missing, (
            f"the voice skill did not announce: {sorted(missing)} "
            f"(saw {sorted(registered)})")
    finally:
        skill.default_shutdown()
        bus.close()
