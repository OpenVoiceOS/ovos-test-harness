"""Row-isolation guarantees of the fleet routing harness itself.

``test_fleet_routing.py`` drives ~582 parametrized rows through ONE
long-lived MiniCroft, so anything a row leaves behind is visible to the next
row. These tests pin the two isolation properties that keep the fleet result
attributable to the row that produced it. They exercise the harness's own
helpers directly and never boot a fleet, so they run in the ordinary suite.

Neither property weakens wrong-skill detection: each isolation assertion is
paired with a positive control asserting that a genuine same-session thief
is still reported.
"""
import pytest
from ovos_bus_client.message import Message

from .test_fleet_routing import (_capture, _claimant, _own_session,
                                 _session_of)

ROW = "fleet-00042"
OTHER = "default"
FLEET = {"ovos-skill-application-launcher.openvoiceos",
         "ovos-skill-dictation.openvoiceos"}


def _msg(msg_type, session_id=None, **ctx):
    context = dict(ctx)
    if session_id is not None:
        context["session"] = {"session_id": session_id}
    return Message(msg_type, {}, context)


class TestSessionAttribution:
    """A message belongs to the session it was dispatched on."""

    def test_session_of_reads_per_message_carriage(self):
        assert _session_of(_msg("x", ROW)) == ROW
        # no session context at all -> un-attributable, not "the row's"
        assert _session_of(_msg("x")) == ""

    def test_own_session_drops_foreign_keeps_sessionless(self):
        recs = [_msg("a", ROW), _msg("b", OTHER), _msg("c")]
        kept = [m.msg_type for m in _own_session(recs, ROW)]
        assert kept == ["a", "c"]


class TestClaimantIsSessionScoped:
    """A claim is attributed to the row whose session carried it."""

    def test_foreign_session_dispatch_is_not_a_claim(self):
        """The regression: another session's dispatch topic landing in this
        row's capture window must not be read as this row being stolen.

        Concretely observed on a real fleet boot: ``ovos-skill-naptime``
        emits a bare ``Message("recognizer_loop:sleep")`` whose whole
        downstream chain arrives under the ``default`` session, inside
        whichever row's window is open at the time.
        """
        recs = [
            _msg("recognizer_loop:utterance", ROW),
            _msg("ovos-skill-dictation.openvoiceos:stop_dictation", OTHER),
            _msg("ovos.utterance.handled", ROW),
        ]
        assert _claimant(recs, FLEET, ROW) is None

    def test_same_session_dispatch_is_still_a_claim(self):
        """Positive control: real theft is on the row's own session."""
        recs = [
            _msg("recognizer_loop:utterance", ROW),
            _msg("ovos-skill-dictation.openvoiceos:stop_dictation", ROW),
            _msg("ovos.utterance.handled", ROW),
        ]
        assert _claimant(recs, FLEET, ROW) == "ovos-skill-dictation.openvoiceos"

    def test_foreign_unmatched_does_not_mask_a_real_claim(self):
        """``ovos.intent.unmatched`` is authoritative only for its own row."""
        recs = [
            _msg("recognizer_loop:utterance", ROW),
            _msg("ovos.intent.unmatched", OTHER),
            _msg("ovos-skill-dictation.openvoiceos:stop_dictation", ROW),
        ]
        assert _claimant(recs, FLEET, ROW) == "ovos-skill-dictation.openvoiceos"

    def test_own_unmatched_is_still_authoritative(self):
        recs = [
            _msg("recognizer_loop:utterance", ROW),
            _msg("ovos.intent.unmatched", ROW),
        ]
        assert _claimant(recs, FLEET, ROW) is None

    def test_speak_fallback_is_session_scoped_too(self):
        foreign = [_msg("speak", OTHER,
                        skill_id="ovos-skill-dictation.openvoiceos")]
        own = [_msg("speak", ROW,
                    skill_id="ovos-skill-dictation.openvoiceos")]
        assert _claimant(foreign, FLEET, ROW) is None
        assert _claimant(own, FLEET, ROW) == "ovos-skill-dictation.openvoiceos"


class _FakeBus:
    """Minimal stand-in: echoes the emitted turn back as a terminal event."""

    def __init__(self):
        self._handlers = []
        self.emitted = []

    def on(self, _topic, handler):
        self._handlers.append(handler)

    def remove(self, _topic, handler):
        self._handlers.remove(handler)

    def emit(self, message):
        self.emitted.append(message)
        session = (message.context or {}).get("session") or {}
        terminal = Message("ovos.utterance.handled", {},
                           {"session": session})
        for handler in list(self._handlers):
            handler(message)
            handler(terminal)


class TestPerRowSession:
    """Each captured turn gets its own session, whatever it says."""

    @pytest.fixture
    def bus(self, monkeypatch):
        from . import test_fleet_routing as mod
        fake = _FakeBus()
        monkeypatch.setattr(mod, "_MC",
                            type("MC", (), {"bus": fake})())
        return fake

    def test_repeated_utterance_text_gets_distinct_sessions(self, bus):
        """The regression: the session id used to be
        ``hash(utterance_text)``, so the corpus's repeated utterances (e.g.
        "remind me to go to work weekday mornings at 8", which appears
        twice) replayed into the SAME session -- inheriting its
        ``active_skills``, adapt ``intent_context`` and any skill-side
        per-session bookkeeping from the earlier occurrence.
        """
        _, first = _capture("remind me to go to work weekday mornings at 8")
        _, second = _capture("remind me to go to work weekday mornings at 8")
        assert first != second

    def test_session_travels_on_the_message_context(self, bus):
        _, session_id = _capture("terminate something")
        turn = bus.emitted[0]
        assert turn.context["session"]["session_id"] == session_id
        # per-message carriage only: the harness pushes no session anywhere
        assert [m.msg_type for m in bus.emitted] == ["recognizer_loop:utterance"]
