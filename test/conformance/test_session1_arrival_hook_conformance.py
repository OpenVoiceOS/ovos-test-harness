"""OVOS-SESSION-1 §2 / SESSION-2 §2.6, §6.1: a wrong-typed ``session_id`` on the
wire is reported once per act of interpretation, and the inbound carrier is
never rewritten on arrival.

The cell is a real ``MessageBusClient`` subscriber on a real
``ovos-messagebus`` (``test.backcompat.driver.BusServer``) and a bare websocket
emitter. The emitter is not a ``MessageBusClient`` on purpose: the bus
broadcasts to every connection, and a client emitter would run its own
arrival path on the echo and add records of its own to the count. It sends
the exact wire payload ``{"session": {"session_id": 7}}`` (no client-side
stamping). The subscriber's handler calls ``SessionManager.get(message)``, the
consumer act SESSION-1 §2 names.

What the counts pin, from ovos-bus-client#370 (the arrival hook reads only the
carrier's type, SESSION-2 §2.6):

- on a plain topic, exactly ONE ``OVOS-SESSION-1 §2`` WARN record: the
  handler's own read;
- on ``recognizer_loop:utterance`` (a topic with a namespace counterpart),
  exactly TWO: ``Message.forward`` re-stamping the derived counterpart, then
  the handler's read. Before #370 the arrival hook added a third read on both
  topics (3 and 2).
- the carrier dict the handler sees is the dict that was sent, and ``lang``
  is not folded into it (SESSION-1 §3.2.7).

Coverage map (clause -> status against the installed stack):
- SESSION-1 §2    wrong-typed session_id logged once per consumer act ..... green
- SESSION-2 §2.6  the arrival hook does not mutate the carrier .............. green
- SESSION-1 §3.2.7 lang is not written into the inbound carrier ............. green
"""
import copy
import json
import logging
import threading
import time
from unittest import TestCase

from ovos_bus_client.session import SessionManager
from websocket import create_connection

from test.backcompat.driver import BusServer

PLAIN_TOPIC = "harness.session1.plain"
MIGRATED_TOPIC = "recognizer_loop:utterance"
WIRE_PAYLOAD = {"utterances": ["hello there"], "lang": "en-US"}
WIRE_CARRIER = {"session_id": 7}


class _SessionWarnCapture(logging.Handler):
    """Collects the SESSION-1 WARN records, one handler on the root only so a
    named logger's propagation is not counted twice."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records = []

    def emit(self, record):
        msg = record.getMessage()
        if "OVOS-SESSION-1" in msg and "session_id" in msg:
            self.records.append(msg)


class TestSession1ArrivalHook(TestCase):

    @classmethod
    def setUpClass(cls):
        cls.bus = BusServer()
        cls.subscriber = cls.bus.client()  # already running and connected
        cls.emitter = create_connection(f"ws://127.0.0.1:{cls.bus.port}/core", timeout=10)
        cls.capture = _SessionWarnCapture()
        root = logging.getLogger()
        root.addHandler(cls.capture)
        for name in ("OVOS", "ovos_bus_client", "ovos_spec_tools"):
            logging.getLogger(name).setLevel(logging.DEBUG)
            logging.getLogger(name).propagate = True

    @classmethod
    def tearDownClass(cls):
        logging.getLogger().removeHandler(cls.capture)
        cls.emitter.close()
        cls.subscriber.close()
        cls.bus.stop()

    def _deliver(self, topic):
        """Send the wire payload on ``topic`` and return (seen, warn records)."""
        seen = []
        done = threading.Event()

        def handler(message):
            before = copy.deepcopy(message.context.get("session"))
            sess = SessionManager.get(message)
            seen.append({"carrier": before,
                         "carrier_after_get": copy.deepcopy(message.context.get("session")),
                         "resolved": sess.session_id})
            done.set()

        self.subscriber.on(topic, handler)
        try:
            self.capture.records.clear()
            self.emitter.send(json.dumps(
                {"type": topic, "data": WIRE_PAYLOAD, "context": {"session": WIRE_CARRIER}}))
            self.assertTrue(done.wait(15), f"{topic}: the handler never ran")
            time.sleep(0.5)
            return seen[0], list(self.capture.records)
        finally:
            self.subscriber.remove(topic, handler)

    def test_plain_topic_one_record_per_consumer_act(self):
        seen, records = self._deliver(PLAIN_TOPIC)
        self.assertEqual(len(records), 1, records)
        self.assertIn("wrong type for `session_id`", records[0])
        self.assertEqual(seen["resolved"], "default")

    def test_migrated_topic_two_records_forward_and_handler(self):
        seen, records = self._deliver(MIGRATED_TOPIC)
        self.assertEqual(len(records), 2, records)
        self.assertEqual(seen["resolved"], "default")

    def test_inbound_carrier_is_the_dict_that_was_sent(self):
        for topic in (PLAIN_TOPIC, MIGRATED_TOPIC):
            with self.subTest(topic=topic):
                seen, _ = self._deliver(topic)
                self.assertEqual(seen["carrier"], WIRE_CARRIER)
                self.assertEqual(seen["carrier_after_get"], WIRE_CARRIER)
                self.assertNotIn("lang", seen["carrier"])
