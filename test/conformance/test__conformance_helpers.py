"""Unit coverage for the shared conformance capture helpers.

The ``test_*_conformance.py`` suites lean on ``_conformance.capture`` /
``assert_absent`` / the namespace push-pop and the small ``first`` / ``types``
accessors for every assertion they make. A bug in one of those helpers would
weaken *every* suite at once — silently, because a broken helper tends to fail
open (drop a message, pass a vacuous negative). These direct unit tests pin the
helper contracts so that class of regression is caught here instead of leaking
into a false-green conformance run.

The filename is deliberately ``test__conformance_helpers.py`` (double
underscore, not ending in ``_conformance.py``) so the coverage-map / xfail-sync
meta-test — which globs ``test_*_conformance.py`` — does not sweep it.
"""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from . import _conformance
from ._conformance import (
    DESERIALIZE_ERROR,
    assert_absent,
    capture,
    capture_emissions,
    deserialize_errors,
    first,
    record_into,
    reset_namespace,
    types,
    use_spec_namespace,
)


def _mc():
    """A minimal orchestrator stand-in: ``capture`` needs only ``mc.bus``."""
    return SimpleNamespace(bus=FakeBus())


class TestDeserializeGuard(TestCase):
    """A payload the bus cannot deserialize is recorded as a sentinel, never
    dropped and never raised."""

    def test_message_passes_through(self):
        recs = []
        m = Message("a.b")
        self.assertIs(_conformance._deserialize_guarded(m, recs), m)
        self.assertEqual(recs, [])

    def test_bad_payload_yields_sentinel(self):
        recs = []
        self.assertIsNone(
            _conformance._deserialize_guarded("this is not json {", recs))
        errs = deserialize_errors(recs)
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0].msg_type, DESERIALIZE_ERROR)
        self.assertIn("raw", errs[0].data)

    def test_record_into_injects_sentinel(self):
        bus = FakeBus()
        recs = []
        cb = record_into(bus, recs)
        try:
            cb("not json {")          # a corrupt emission
            cb(Message("ok.topic"))   # a good one
        finally:
            bus.remove("message", cb)
        self.assertEqual(types(recs), [DESERIALIZE_ERROR, "ok.topic"])


class TestCapture(TestCase):
    """``capture`` emits one message and records the ordered response stream."""

    def test_fixed_window_eof_none_collects_everything(self):
        """``eof_types=None`` is the fixed-window mode: no early return on an
        end-marker; the emitted message is captured."""
        mc = _mc()
        recs = capture(mc, Message("some.topic", {"x": 1}),
                       timeout=0.2, eof_types=None)
        self.assertIn("some.topic", types(recs))

    def test_empty_run_returns_empty(self):
        """A topic no handler answers and that is not itself an end-marker
        yields only the entry echo — capture never hangs past the timeout."""
        mc = _mc()
        recs = capture(mc, Message("lonely.topic"),
                       timeout=0.2, eof_types=None)
        self.assertEqual(types(recs), ["lonely.topic"])

    def test_eof_marker_is_captured(self):
        """When the emitted topic is itself an end-marker, capture returns it
        (and does not burn the full timeout)."""
        mc = _mc()
        recs = capture(mc, Message("ovos.utterance.handled"), timeout=2.0)
        self.assertIn("ovos.utterance.handled", types(recs))


class TestCaptureEmissions(TestCase):
    """``capture_emissions`` records everything an action emits, guarded, and
    filters by prefix."""

    def test_records_action_emissions_with_prefix(self):
        bus = FakeBus()

        def action():
            bus.emit(Message("gui.value.set", {"a": 1}))
            bus.emit(Message("other.topic"))

        recs = capture_emissions(bus, action, prefix="gui.")
        self.assertEqual(types(recs), ["gui.value.set"])

    def test_no_prefix_returns_all(self):
        bus = FakeBus()
        recs = capture_emissions(
            bus, lambda: bus.emit(Message("x.one")), prefix=None)
        self.assertIn("x.one", types(recs))


class TestAssertAbsent(TestCase):
    """``assert_absent`` refuses to pass vacuously."""

    def test_empty_recs_is_vacuous(self):
        with self.assertRaises(AssertionError) as cm:
            assert_absent([], "nope.topic")
        self.assertIn("vacuous", str(cm.exception))

    def test_missing_positive_control_is_vacuous(self):
        """Records exist, but none is a positive control, so the turn never
        reached a terminal state — a negative assertion here proves nothing."""
        recs = [Message("some.mid.topic")]
        with self.assertRaises(AssertionError) as cm:
            assert_absent(recs, "nope.topic")
        self.assertIn("vacuous", str(cm.exception))

    def test_present_control_absent_type_passes(self):
        recs = [Message("some.mid.topic"), Message("ovos.utterance.handled")]
        assert_absent(recs, "nope.topic")  # must not raise

    def test_present_type_raises(self):
        recs = [Message("bad.topic"), Message("ovos.utterance.handled")]
        with self.assertRaises(AssertionError) as cm:
            assert_absent(recs, "bad.topic")
        self.assertIn("must not be", str(cm.exception))

    def test_positive_control_none_allows_non_empty(self):
        recs = [Message("only.topic")]
        assert_absent(recs, "nope.topic", positive_control=None)


class TestNamespacePushPop(TestCase):
    """``use_spec_namespace`` / ``reset_namespace`` restore Configuration
    exactly, including the ``_SENTINEL`` (key-was-absent) path.

    The live ``Configuration`` is a layered singleton — a default layer always
    carries ``legacy_namespace``, so the key can never be made genuinely absent
    on it. To exercise the key-absent (``_SENTINEL``) branch these tests patch
    ``_conformance.Configuration`` with a plain-dict factory, isolating the
    push/pop logic from the real config.
    """

    def test_sentinel_restore_deletes_absent_key(self):
        fake = {}  # legacy_namespace absent -> use_spec_namespace pushes _SENTINEL
        with patch.object(_conformance, "Configuration", lambda: fake):
            use_spec_namespace()
            self.assertIs(fake["legacy_namespace"], False)
            reset_namespace()
            self.assertNotIn("legacy_namespace", fake)

    def test_value_restore_puts_prior_value_back(self):
        fake = {"legacy_namespace": True}
        with patch.object(_conformance, "Configuration", lambda: fake):
            use_spec_namespace()
            self.assertIs(fake["legacy_namespace"], False)
            reset_namespace()
            self.assertIs(fake["legacy_namespace"], True)


class TestFirstAndTypes(TestCase):
    """``first`` / ``types`` accessors."""

    def test_types_is_ordered_msg_types(self):
        recs = [Message("a"), Message("b"), Message("a")]
        self.assertEqual(types(recs), ["a", "b", "a"])

    def test_first_returns_first_match_or_none(self):
        recs = [Message("a", {"n": 1}), Message("a", {"n": 2})]
        self.assertEqual(first(recs, "a").data, {"n": 1})
        self.assertIsNone(first(recs, "missing"))
