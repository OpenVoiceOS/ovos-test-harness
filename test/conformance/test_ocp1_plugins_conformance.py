"""OVOS-OCP-1 per-implementer conformance suite — the discovery extractor.

Where ``test_ocp1_conformance.py`` asserts the OCP-1 §3/§4.3/§4.4 state-machine
against the ovos-media Virtual **Media Player** (via ``OCPPlayerHarness`` +
``MockOCPBackend``), this suite asserts the §4.1 / §4.2 **discovery** contract
against the shipped OVOS-org OCP **extractor** — the media keyword/search plugin
that turns a spoken "play …" request into a search broadcast. Player and
extractor are the two halves of OCP-1 (§4.2 discovery upstream of the pipeline;
§3/§4.3/§4.4 transport in the player), so together the two suites cover both.

Driver model
------------
The reference extractor is ``ovos-ocp-pipeline-plugin`` (``OCPPipelineMatcher``,
the ``opm.pipeline`` entry point a default stack loads for media). It is inert
until at least one OCP media skill registers (``match_high`` returns ``None``
with no ``skill_aliases``), so the suite instantiates the real plugin on a
``FakeBus`` with fast search timeouts, registers a fixture OCP music skill
through the plugin's own ``ovos.common_play.announce`` handler, then drives ONE
search and records the wire. This exercises the production search-broadcast path
of the shipped plugin without a MiniCroft boot — the component-level analogue of
``test_transform1_plugins_conformance.py``'s service-level driving. The fixture
skill need not answer: ``search.start`` / the ``query`` poll / ``search.end`` are
emitted to *discover* answerers regardless of whether any reply, which is exactly
the §4.2 discovery contract under test.

Every assertion has a positive control: the namespace check first requires the
search bracket to be present (traffic really happened), so it can never pass
vacuously on an inert extractor. ``importorskip`` guards the plugin.

Out of scope (no bus-only reference implementer): the OCP **audio backends**
(``opm.media.audio`` — Music Assistant) and **media providers**
(``opm.media.provider``) ship only as network-backed plugins, and no
stream-extractor (``opm.ocp``) plugin ships in the default stack; none is
exercisable on a bus-only harness, the same reason STT/TTS get no per-plugin
suite. The deprecated Mycroft-CPS legacy extractor
(``ovos-ocp-pipeline-plugin-legacy``) drives a different, superseded mechanism
(``ocp:legacy_cps`` / ``mycroft.audio.service.*``) and is not covered.

xfail discipline follows ``_conformance.py``.
"""
import unittest

import pytest

from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from ovos_bus_client.message import Message

from ._conformance import capture_emissions, types

# The OCP-1 media-type vocabulary lives in ovos_utils.ocp; a bus-only harness
# needs only the enum to register a fixture music skill.
from ovos_utils.ocp import MediaType

CP_PREFIX = "ovos.common_play."

# §4.2 discovery bracket + the broadcast willingness poll.
SEARCH_START = "ovos.common_play.search.start"
SEARCH_END = "ovos.common_play.search.end"
QUERY_POLL = "ovos.common_play.query"

# Fast search timeouts so the (unanswered) discovery poll returns promptly; a
# single search still emits the full discovery bracket.
_FAST_CFG = {"min_timeout": 0.1, "max_timeout": 0.3, "search_fallback": False}


def setUpModule():
    LOG.set_level("ERROR")


# ---------------------------------------------------------------------------
# Registry — one entry per shipped OCP discovery-extractor implementer.
# ---------------------------------------------------------------------------

OCP_EXTRACTORS = {
    "ovos-ocp-pipeline": {
        "module": "ocp_pipeline.opm",
        "cls": "OCPPipelineMatcher",
    },
}

_METHODS = ("test_search_bracket_emitted",
            "test_broadcasts_discovery_poll",
            "test_all_traffic_is_common_play_namespaced")


def _missing_case(key, module, exc):
    reason = f"{key} ({module}) not installed; skipping its OCP-1 case ({exc})"

    class _Missing(unittest.TestCase):
        pass

    for name in _METHODS:
        setattr(_Missing, name, unittest.skip(reason)(lambda self: None))
    return _Missing


def _build_case(key, spec):
    try:
        module = __import__(spec["module"], fromlist=[spec["cls"]])
    except ImportError as exc:
        LOG.exception("OCP-1 extractor %s (%s) not importable; case will skip",
                      key, spec["module"])
        return _missing_case(key, spec["module"], exc)

    plugin_cls = getattr(module, spec["cls"])

    class _Case(unittest.TestCase):
        LANG = "en-US"
        _seq = None  # cached ordered topic list from the single search

        @classmethod
        def _run_search_once(cls):
            if cls._seq is not None:
                return cls._seq
            plugin = plugin_cls(bus=FakeBus(), config=dict(_FAST_CFG))
            # Register a fixture OCP music skill through the plugin's OWN
            # announce handler so the extractor is no longer inert.
            plugin.bus.emit(Message("ovos.common_play.announce", {
                "skill_id": "fake.ocp.test",
                "skill_name": "Fake OCP Test",
                "media_types": [MediaType.MUSIC],
                "aliases": ["Fake OCP Test"],
            }, {"skill_id": "fake.ocp.test"}))
            assert plugin.skill_aliases.get("fake.ocp.test"), \
                "fixture OCP skill did not register (extractor still inert)"

            msg = Message("recognizer_loop:utterance", {},
                          {"session": {"session_id": "ocp-conf"}})
            recs = capture_emissions(
                plugin.bus,
                lambda: plugin._search("some jazz music", MediaType.MUSIC,
                                       cls.LANG, message=msg),
                settle=0.3, prefix=CP_PREFIX)
            cls._seq = types(recs)
            return cls._seq

        def setUp(self):
            self.seq = self._run_search_once()

        def test_search_bracket_emitted(self):
            """§4.2 MUST: a search announces its lifecycle on the reserved
            namespace — ``search.start`` opens and ``search.end`` closes the
            discovery window, in that order."""
            self.assertIn(SEARCH_START, self.seq,
                          f"{key}: no search.start (extractor did not search)")
            self.assertIn(SEARCH_END, self.seq,
                          f"{key}: no search.end (discovery window not closed)")
            self.assertLess(self.seq.index(SEARCH_START),
                            self.seq.index(SEARCH_END),
                            f"{key}: search.end preceded search.start")

        def test_broadcasts_discovery_poll(self):
            """§4.2 MUST: the extractor broadcasts the willingness poll on
            ``ovos.common_play.query`` to discover answering OCP skills — the
            discovery step every OCP skill consumes."""
            self.assertIn(QUERY_POLL, self.seq,
                          f"{key}: no ovos.common_play.query discovery broadcast")

        def test_all_traffic_is_common_play_namespaced(self):
            """§4.1 MUST: every message the extractor emits during discovery
            rides the reserved ``ovos.common_play.`` prefix. Positive control:
            the search bracket is present, so real traffic occurred — the check
            is not vacuous on an inert extractor."""
            self.assertIn(SEARCH_START, self.seq,
                          f"{key}: no discovery traffic captured (positive "
                          f"control failed)")
            off = [t for t in self.seq if not t.startswith(CP_PREFIX)]
            self.assertEqual(off, [],
                             f"{key}: extractor emitted off-namespace topics "
                             f"{off}")

    _Case.__name__ = f"TestOCP1Extractor_{key.replace('-', '_')}"
    _Case.__qualname__ = _Case.__name__
    _Case.__doc__ = (f"OCP-1 §4.1/§4.2 discovery conformance for the {key} "
                     f"extractor ({spec['cls']}).")
    return _Case


# Generate and register one TestCase per implementer in module globals.
for _key, _spec in OCP_EXTRACTORS.items():
    _cls = _build_case(_key, _spec)
    globals()[_cls.__name__] = _cls

del _key, _spec, _cls
