"""Both styles of the utterance entry, of pipeline attribution and of the
session snapshot, against one live stack.

Three places in the intent path carry a legacy and a specified shape at the
same time, and each of them is a place where a fleet splits: an old satellite
still opening a turn with ``recognizer_loop:utterance`` while core listens on
``ovos.utterance.handle``; a session whose ``pipeline`` list still names the
confidence-suffixed matcher entries while OVOS-PIPELINE-1 §3.1 requires the
attribution on ``ovos.intent.matched`` to name the bare plugin; and a session
snapshot arriving on either of the two carriers OVOS-SESSION-2 §2.7 defines.
Each pair is asserted here in one cell, because what matters is not that
either style works in isolation but that both reach the same state.

The stack is one ``get_minicroft`` on the padacioso pipeline, the same driver
model the conformance suites use, under production dual-emit.
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager

from ..conformance._conformance import (capture, first, reset_namespace, types,
                                        use_spec_namespace, utterance,
                                        wait_ready)

SKILL_ID = "migration.probe"
INTENT = f"{SKILL_ID}:probe"
SAMPLES = ["run the migration probe"]
UTTERANCE = SAMPLES[0]

#: the intake for the OVOS-SESSION-2 §2.7 primary carrier
NEEDS_BUS_CLIENT_278 = (
    "ovos.session.sync reads the snapshot off Message.context; the SESSION-2 "
    "§2.7 data carrier lands with ovos-bus-client#278")

_MC = None


def setup_module(_module):
    global _MC
    from ovos_utils.log import LOG
    from ovoscope import get_minicroft, register_padatious_intent
    LOG.set_level("ERROR")
    use_spec_namespace()
    try:
        _MC = get_minicroft([])
        wait_ready(_MC, settle=1.0)
        register_padatious_intent(_MC.bus, INTENT, SAMPLES)
        time.sleep(1.5)
    except BaseException:
        reset_namespace()
        raise


def teardown_module(_module):
    try:
        if _MC is not None:
            _MC.stop()
    finally:
        reset_namespace()


class TestUtteranceEntryBothStyles(TestCase):
    """``recognizer_loop:utterance`` and ``ovos.utterance.handle`` are the same
    turn opener, and a fleet runs both at once."""

    def _turn(self, topic, session_id):
        from ovoscope import PADACIOSO_PIPELINE
        entry = utterance(UTTERANCE, session_id, PADACIOSO_PIPELINE)
        entry.msg_type = topic
        return capture(_MC, entry, 5.0)

    def test_legacy_entry_reaches_the_intent_service(self):
        """A satellite that never migrated still gets its intent dispatched."""
        seen = types(self._turn("recognizer_loop:utterance", "legacy-entry"))
        assert INTENT in seen, (
            f"a legacy recognizer_loop:utterance did not dispatch {INTENT}; "
            f"saw {seen}")

    def test_spec_entry_reaches_the_intent_service(self):
        """The same turn on the specified topic, as the control."""
        seen = types(self._turn("ovos.utterance.handle", "spec-entry"))
        assert INTENT in seen, (
            f"ovos.utterance.handle did not dispatch {INTENT}; saw {seen}")


class TestPipelineAttribution(TestCase):
    """OVOS-PIPELINE-1 §3.1: the attribution names the plugin, while the
    session keeps naming confidence tiers."""

    def setUp(self):
        from ovoscope import PADACIOSO_PIPELINE
        self.pipeline = PADACIOSO_PIPELINE
        self.recs = capture(_MC, utterance(UTTERANCE, "attribution",
                                           self.pipeline), 5.0)

    def test_matched_carries_the_bare_pipeline_id(self):
        """The confidence suffix is a session-side selector, not an identity:
        ``ovos.intent.matched`` names the plugin without it (§3.1)."""
        matched = first(self.recs, "ovos.intent.matched")
        assert matched is not None, f"no ovos.intent.matched; saw {types(self.recs)}"
        attributed = matched.context.get("pipeline_id")
        assert attributed == "ovos-padacioso-pipeline-plugin", (
            f"attribution is {attributed!r}, not the bare plugin id")

    def test_suffixed_session_entries_still_resolve_to_the_matcher(self):
        """The very session that produced that attribution asked for the
        suffixed entries, so both styles are live in one turn."""
        assert any(entry.endswith(("-high", "-medium", "-low"))
                   for entry in self.pipeline), self.pipeline
        assert INTENT in types(self.recs), (
            f"the suffixed session pipeline {self.pipeline} matched nothing")


class TestSessionSnapshotBothStyles(TestCase):
    """A session snapshot merges into the managed session whichever way it
    arrives — the legacy default-session broadcast, or an OVOS-SESSION-2 sync."""

    def setUp(self):
        self.session_id = f"snapshot-{id(self)}"
        sess = Session(self.session_id)
        sess.intent_context = {"keep": {"value": "k"}}
        SessionManager.update(sess)

    def tearDown(self):
        SessionManager.sessions.pop(self.session_id, None)

    def _snapshot(self, entries):
        snap = SessionManager.sessions[self.session_id].serialize()
        snap["intent_context"] = entries
        return snap

    def test_legacy_default_session_update_is_observed(self):
        """``ovos.session.update_default`` is how the default session was
        broadcast before the sync topic existed, and it still lands."""
        default = SessionManager.get_default_session()
        snap = default.serialize()
        snap["lang"] = "pt-PT"
        _MC.bus.emit(Message("ovos.session.update_default",
                             {"session_data": snap}))
        time.sleep(0.5)
        assert SessionManager.get_default_session().lang == "pt-PT", (
            "the legacy default-session broadcast did not update the default "
            "working state")

    def test_sync_merges_into_the_working_session(self):
        """``ovos.session.sync`` on the legacy carrier reaches the managed
        session (OVOS-CONTEXT-1 §5.3)."""
        snap = self._snapshot({"from.sync": {"value": "s"}})
        _MC.bus.emit(Message("ovos.session.sync", context={"session": snap}))
        time.sleep(0.5)
        merged = SessionManager.sessions[self.session_id].intent_context
        assert merged.get("from.sync") == {"value": "s"}, merged

    @pytest.mark.skip(reason=NEEDS_BUS_CLIENT_278)
    def test_sync_reads_the_spec_data_carrier(self):
        """OVOS-SESSION-2 §2.7 makes ``data['session']`` the primary carrier
        and the context shape the fallback."""
        snap = self._snapshot({"from.data": {"value": "d"}})
        _MC.bus.emit(Message("ovos.session.sync", {"session": snap}))
        time.sleep(0.5)
        merged = SessionManager.sessions[self.session_id].intent_context
        assert merged.get("from.data") == {"value": "d"}, merged
