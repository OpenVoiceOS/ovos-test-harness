"""OVOS-GUI-1 conformance suite.

Encodes the normative *Conformance* clauses (§8) and the wire protocol (§4),
template vocabulary (§3), routing (§5), and adapter contract (§6) of
OVOS-GUI-1 (``ovos/org/architecture/gui-1.md``) as assertions against the
real GUI subsystem in the integrated stack.

GUI-1 is a **bus-protocol** spec with two bus-observable surfaces:

1. **The producer wire shape** — what a conforming producer emits on the
   ``gui.*`` topics (``gui.value.set`` / ``gui.page.show`` /
   ``gui.clear.namespace``). Driven here through the real
   ``ovos_bus_client.apis.gui.GUIInterface`` (the installed producer helper)
   on a ``FakeBus``; every message it emits is captured and its structure
   asserted against §4.1 / §4.2 / §8.1.

2. **The GUI service contract** — the parts of §3.2 / §4.1 / §4.3 / §5 / §8.3
   that the ``ovos_gui.namespace.NamespaceManager`` exposes on the **core
   bus** (namespace activation/removal, ``SYSTEM_`` prefix gating, per-session
   stack). Driven by instantiating the service against a ``FakeBus`` and
   inspecting both its core-bus emissions and its loaded-namespace state.

What is **not** bus-observable is excluded with an explicit ``# not
bus-observable`` note: all *rendering* (§3 visuals, §6.5 degradation), the
backend↔client transport (§5.2, §6.2), the ``opm.gui_adapter`` entry-point
fan-out and adapter exception/threading isolation (§6.1, §6.3, §6.4, §6.6,
§6.7, §6.8), since those run inside an adapter / over the QML websocket and
never reach the core bus a conformance test can observe.

xfail discipline (see ``docs/writing-conformance-tests.md``): every assertion
states what the spec **mandates**; where the installed producer/service
diverges the test is ``@pytest.mark.xfail(strict=True, reason=...)`` citing
the spec clause + the actual behaviour, so it flips green the moment the impl
conforms. Assertions are never weakened to the legacy behaviour.

Coverage map (MUST clause -> status against the installed stack):
- §2.3  producer functions headless (no display required) ........ green
- §3.1  producer names only closed-vocabulary templates .......... xfail (SYSTEM_TextFrame…)
- §3.2  template name begins with reserved ``SYSTEM_`` prefix ..... xfail (mixed-case frame names)
- §3.2/§4.2 service MUST NOT dispatch a non-``SYSTEM_`` page ...... xfail (dispatches any)
- §3.3  producer omits absent optional keys, never JSON null ...... xfail (emits __idle: null + None keys)
- §3.5  producer never places a bare filesystem path on the wire .. xfail (show_image resolves to fs path)
- §4.1  every GUI Message carries ``__from`` ...................... green
- §4.1  service strips reserved ``__``-prefixed keys .............. green (RESERVED_KEYS)
- §4.2  ``gui.page.show`` first page is a ``SYSTEM_*`` template ... xfail (frame names)
- §4.2  ``gui.value.set`` carries the flat content map + __from ... green
- §4.2  ``gui.clear.namespace`` carries ``__from`` ............... green
- §4.3  service maintains a per-``session_id`` namespace stack .... xfail (single global stack)
- §5.1  GUI Message routed solely by ``session_id`` .............. xfail (service ignores session)
- §7.2  interaction response carries the originating session_id .. not bus-observable (adapter-emitted)
- §8.1  producer-MUST roll-up (vocabulary/__from/routing) ........ mixed (see classes)
- §8.3  service-MUST roll-up (SYSTEM_ gate / strip / per-session) . mixed (see classes)
"""
import sys
import time
from unittest import TestCase

import pytest
from ovos_bus_client.apis.gui import GUIInterface
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG

# ── Reserved protocol keys (§4.1) and the closed template vocabulary (§3.4) ──
GUI_VALUE_SET = "gui.value.set"
GUI_PAGE_SHOW = "gui.page.show"
GUI_CLEAR = "gui.clear.namespace"

RESERVED_PREFIX = "__"
SYSTEM_PREFIX = "SYSTEM_"

# The closed §3.4 catalogue — the only template names a conforming producer
# may emit and the only ones a conforming service may dispatch (§3.1, §3.2).
CLOSED_VOCABULARY = {
    "SYSTEM_idle", "SYSTEM_loading", "SYSTEM_status", "SYSTEM_error",
    "SYSTEM_text", "SYSTEM_image", "SYSTEM_animated_image", "SYSTEM_list",
    "SYSTEM_grid", "SYSTEM_table", "SYSTEM_html", "SYSTEM_url",
    "SYSTEM_audio_player", "SYSTEM_video_player", "SYSTEM_media_player",
    "SYSTEM_clock", "SYSTEM_timer", "SYSTEM_weather", "SYSTEM_map",
    "SYSTEM_face", "SYSTEM_confirm", "SYSTEM_select",
}

SKILL_ID = "weather.openvoiceos"


# ─────────────────────────────────────────────────────────────────────────────
# Producer-side capture helper
# ─────────────────────────────────────────────────────────────────────────────

def _capture_producer(emit):
    """Run ``emit(gui, bus)`` against a fresh FakeBus + real GUIInterface and
    return the ordered list of ``gui.*`` Messages the producer emitted."""
    bus = FakeBus()
    recs = []

    def _rec(m):
        recs.append(Message.deserialize(m) if isinstance(m, str) else m)

    bus.on("message", _rec)
    gui = GUIInterface(SKILL_ID, bus=bus)
    emit(gui)
    time.sleep(0.2)
    return [m for m in recs if m.msg_type.startswith("gui.")]


def _first(recs, msg_type):
    return next((m for m in recs if m.msg_type == msg_type), None)


# =============================================================================
# §2 — Voice-first invariants
# =============================================================================

class TestSec2VoiceFirst(TestCase):
    """§2.3: a render backend is optional; the producer functions with no
    display attached and the §4 wire protocol is still emitted (observed by
    nobody when headless)."""

    def test_producer_emits_without_any_adapter(self):
        """§2.3 MUST: an application functions with no display attached — the
        producer emits its ``gui.*`` wire protocol even when no GUI service /
        adapter is listening (here: a bare FakeBus)."""
        recs = _capture_producer(lambda g: g.show_text("hello", "Title"))
        self.assertTrue(recs, "producer emitted nothing on the wire")
        self.assertIn(GUI_PAGE_SHOW, [m.msg_type for m in recs])


# =============================================================================
# §3 — The template vocabulary
# =============================================================================

class TestSec3ClosedVocabulary(TestCase):
    """§3.1/§3.2: the template vocabulary is a closed set; a producer MUST name
    only templates from §3.4, and every template name MUST begin with the
    reserved ``SYSTEM_`` prefix and appear verbatim in the catalogue."""

    @pytest.mark.xfail(strict=True,
                       reason="GUI-1 §3.1 MUST name only closed-vocabulary "
                              "templates; GUIInterface.show_text emits the "
                              "legacy 'SYSTEM_TextFrame', not the spec "
                              "'SYSTEM_text'")
    def test_show_text_names_closed_vocabulary_template(self):
        """§3.1 MUST: a producer names only templates from the closed §3.4
        vocabulary; ``show_text`` must request ``SYSTEM_text``."""
        recs = _capture_producer(lambda g: g.show_text("hi", "T"))
        page = _first(recs, GUI_PAGE_SHOW)
        self.assertIsNotNone(page)
        self.assertIn(page.data["page_names"][0], CLOSED_VOCABULARY)

    @pytest.mark.xfail(strict=True,
                       reason="GUI-1 §3.1 MUST name only closed-vocabulary "
                              "templates; show_image emits 'SYSTEM_ImageFrame' "
                              "not the spec 'SYSTEM_image'")
    def test_show_image_names_closed_vocabulary_template(self):
        """§3.1 MUST: ``show_image`` must request the spec ``SYSTEM_image``."""
        recs = _capture_producer(
            lambda g: g.show_image("https://example.org/a.png"))
        page = _first(recs, GUI_PAGE_SHOW)
        self.assertIsNotNone(page)
        self.assertIn(page.data["page_names"][0], CLOSED_VOCABULARY)

    @pytest.mark.xfail(strict=True,
                       reason="GUI-1 §3.1 MUST name only closed-vocabulary "
                              "templates; show_face emits 'SYSTEM_Face' not "
                              "the spec 'SYSTEM_face'")
    def test_show_face_names_closed_vocabulary_template(self):
        """§3.1 MUST: ``show_face`` must request the spec ``SYSTEM_face``."""
        recs = _capture_producer(lambda g: g.show_face(awake=True))
        page = _first(recs, GUI_PAGE_SHOW)
        self.assertIsNotNone(page)
        self.assertIn(page.data["page_names"][0], CLOSED_VOCABULARY)

    def test_emitted_template_name_has_system_prefix(self):
        """§3.2 MUST: a template name is a string beginning with the reserved
        ``SYSTEM_`` prefix — the discriminator the service uses to recognise a
        template intent. (Case/spelling of the suffix is checked by the
        closed-vocabulary tests above.)"""
        recs = _capture_producer(lambda g: g.show_text("hi", "T"))
        page = _first(recs, GUI_PAGE_SHOW)
        self.assertIsNotNone(page)
        self.assertTrue(page.data["page_names"][0].startswith(SYSTEM_PREFIX))


class TestSec33TypingRules(TestCase):
    """§3.3: a producer MUST NOT emit an absent optional key as JSON ``null``
    to mean "absent" — it omits the key instead."""

    @pytest.mark.xfail(strict=True,
                       reason="GUI-1 §3.3 MUST omit absent optional keys "
                              "rather than emit null; GUIInterface emits "
                              "'__idle': None and sets unset optional content "
                              "keys (title/caption/fill…) to None")
    def test_absent_optional_keys_are_omitted_not_null(self):
        """§3.3 MUST: a producer omits absent optional keys; no GUI Message
        carries a key whose value is JSON ``null``."""
        recs = _capture_producer(lambda g: g.show_text("hi"))  # no title
        for m in recs:
            nulls = [k for k, v in m.data.items() if v is None]
            self.assertEqual(nulls, [],
                             f"{m.msg_type} carried null keys: {nulls}")


class TestSec35ImageDelivery(TestCase):
    """§3.5: an image-bearing key carries an ``http(s)`` URL or a ``data:``
    URI; a producer MUST resolve a local asset to a ``data:`` URI before
    emission and MUST NOT place a bare filesystem path on the wire."""

    def test_http_image_url_passes_through(self):
        """§3.5: an ``http(s)`` URL is carried as-is on the ``image`` key."""
        recs = _capture_producer(
            lambda g: g.show_image("https://example.org/cat.png"))
        vals = _first(recs, GUI_VALUE_SET)
        self.assertIsNotNone(vals)
        self.assertEqual(vals.data.get("image"), "https://example.org/cat.png")

    @pytest.mark.xfail(strict=True,
                       reason="GUI-1 §3.5 MUST resolve a local asset to a "
                              "data: URI and MUST NOT place a filesystem path "
                              "on the wire; GUIInterface.show_image resolves a "
                              "local file to its absolute filesystem path and "
                              "emits that path verbatim on 'image'")
    def test_local_image_resolved_to_data_uri(self):
        """§3.5 MUST: a local asset is resolved to a ``data:`` URI; no
        ``image`` value is a bare filesystem path."""
        # a producer holding a local asset
        recs = _capture_producer(
            lambda g: g.show_image(__file__))  # an existing local file
        vals = _first(recs, GUI_VALUE_SET)
        self.assertIsNotNone(vals)
        img = vals.data.get("image", "")
        self.assertTrue(
            img.startswith("http") or img.startswith("data:"),
            f"image key carried a non-URL/non-data value: {img!r}")


# =============================================================================
# §4 — Wire protocol
# =============================================================================

class TestSec41ReservedKeys(TestCase):
    """§4.1: ``__from`` carries the producing namespace and every GUI Message a
    producer emits MUST carry it; reserved ``__``-prefixed keys are protocol
    metadata, not session data."""

    def test_every_message_carries_from(self):
        """§4.1 MUST: every GUI Message a producer emits carries ``__from``."""
        recs = _capture_producer(lambda g: (g.__setitem__("current_temp", 22),
                                            g.show_text("hi", "T"),
                                            g.clear()))
        self.assertTrue(recs)
        for m in recs:
            self.assertIn("__from", m.data,
                          f"{m.msg_type} is missing the __from namespace key")

    def test_from_equals_producing_namespace(self):
        """§4.1: ``__from`` names the producing namespace (the skill_id)."""
        recs = _capture_producer(lambda g: g.show_text("hi", "T"))
        for m in recs:
            self.assertEqual(m.data.get("__from"), SKILL_ID)


class TestSec42Messages(TestCase):
    """§4.2: the ``gui.value.set`` / ``gui.page.show`` / ``gui.clear.namespace``
    message shapes."""

    def test_value_set_carries_flat_content_map(self):
        """§4.2 ``gui.value.set``: ``data`` is the flat content map plus
        ``__from``."""
        recs = _capture_producer(lambda g: (g.show_text("hi", "T")))
        vals = _first(recs, GUI_VALUE_SET)
        self.assertIsNotNone(vals, "no gui.value.set emitted")
        self.assertIn("__from", vals.data)
        self.assertEqual(vals.data.get("text"), "hi")

    def test_page_show_carries_page_names_and_index(self):
        """§4.2 ``gui.page.show``: ``data`` carries ``page_names`` (a list) and
        an ``index`` selecting the active entry."""
        recs = _capture_producer(lambda g: g.show_text("hi", "T"))
        page = _first(recs, GUI_PAGE_SHOW)
        self.assertIsNotNone(page)
        self.assertIsInstance(page.data.get("page_names"), list)
        self.assertIn("index", page.data)

    def test_clear_namespace_carries_from(self):
        """§4.2 ``gui.clear.namespace``: ``data`` carries ``__from``."""
        recs = _capture_producer(lambda g: g.clear())
        clear = _first(recs, GUI_CLEAR)
        self.assertIsNotNone(clear, "no gui.clear.namespace emitted")
        self.assertIn("__from", clear.data)

    def test_page_show_first_entry_is_system_template(self):
        """§4.2 MUST: the first entry of ``page_names`` is a ``SYSTEM_*``
        template name."""
        recs = _capture_producer(lambda g: g.show_text("hi", "T"))
        page = _first(recs, GUI_PAGE_SHOW)
        self.assertIsNotNone(page)
        self.assertTrue(page.data["page_names"][0].startswith(SYSTEM_PREFIX))


# =============================================================================
# §8.1 — A conforming producer MUST (roll-up)
# =============================================================================

class TestSec81ProducerConformance(TestCase):
    """§8.1: the producer-MUST roll-up — name only closed-vocabulary templates,
    emit ``gui.page.show`` with a ``SYSTEM_*`` first page, include ``__from`` on
    every message, deliver image content as URL/data URI, omit null keys."""

    def test_page_show_present_for_template_request(self):
        """§8.1 MUST: a producer emits ``gui.page.show`` to present a
        template."""
        recs = _capture_producer(lambda g: g.show_text("hi", "T"))
        self.assertIn(GUI_PAGE_SHOW, [m.msg_type for m in recs])

    @pytest.mark.xfail(strict=True,
                       reason="GUI-1 §8.1 MUST name only the closed §3.4 "
                              "vocabulary; GUIInterface emits legacy "
                              "'SYSTEM_*Frame' page names outside the catalogue")
    def test_all_template_names_in_closed_vocabulary(self):
        """§8.1 MUST: every ``page_names`` entry a producer emits is a name
        from the closed §3.4 vocabulary."""
        recs = _capture_producer(lambda g: (g.show_text("hi", "T"),
                                            g.show_face(),
                                            g.show_image("https://x/y.png")))
        for m in recs:
            if m.msg_type == GUI_PAGE_SHOW:
                for name in m.data.get("page_names", []):
                    self.assertIn(name, CLOSED_VOCABULARY)


# =============================================================================
# §3.2 / §4.2 / §4.3 / §5 / §8.3 — GUI service contract (core-bus observable)
# =============================================================================

def _service_available():
    """Whether the GUI service is importable.

    Only ImportError counts as "not installed"; any other exception is a
    broken install and must propagate. The skip it produces is itself a CI
    failure — see test/test_install_floor.py.
    """
    try:
        import ovos_gui.namespace  # noqa: F401
        return True
    except ImportError:
        LOG.exception("ovos-gui is not importable; the GUI-1 service clauses "
                      "will skip")
        return False


_requires_gui_service = pytest.mark.skipif(
    not _service_available(),
    reason="ovos-gui (the GUI service / NamespaceManager) is not installed in "
           "the stack under test",
)

# A single shared GUI service for the whole module: NamespaceManager binds the
# backend GUI websocket on construction, so one instance is reused across every
# service test (a second instance would collide on the port). Built lazily on
# first use so the producer-side suites run even when ovos-gui is absent.
_NM = None


def _gui_service():
    """The shared module-level NamespaceManager, built once on a FakeBus."""
    global _NM
    if _NM is None:
        from ovos_gui.namespace import NamespaceManager
        _NM = NamespaceManager(FakeBus())
    return _NM


def _reset_gui_service():
    """Clear the shared service's namespace state.

    NamespaceManager binds the backend GUI websocket on construction, so the
    module reuses one instance and its namespace maps are shared mutable
    state: without this reset one test's page stays loaded and the next test's
    assertion about ``loaded_namespaces`` reads the previous test's result.
    """
    if _NM is None:
        return
    _NM.loaded_namespaces.clear()
    del _NM.active_namespaces[:]


def tearDownModule():
    """Drop the shared GUI service so it cannot leak into another module."""
    global _NM
    _reset_gui_service()
    _NM = None


def _run_service(emits):
    """Replay ``emits`` (a list of Messages) on a clean shared service's core
    bus and return (manager, core_recs)."""
    nm = _gui_service()
    _reset_gui_service()
    recs = []

    def _rec(m):
        recs.append(Message.deserialize(m) if isinstance(m, str) else m)

    nm.core_bus.on("message", _rec)
    try:
        for msg in emits:
            nm.core_bus.emit(msg)
            time.sleep(0.2)
    finally:
        nm.core_bus.remove("message", _rec)
    return nm, recs


def _show(page, frm="sk", session_id=None, idle=True):
    ctx = {"session": {"session_id": session_id}} if session_id else {}
    return Message(GUI_PAGE_SHOW,
                   {"__from": frm, "page_names": [page], "index": 0,
                    "__idle": idle}, ctx)


@_requires_gui_service
class TestSec32ServiceTemplateGate(TestCase):
    """§3.2/§4.2: a conforming GUI service recognises a template intent by the
    ``SYSTEM_`` prefix and MUST NOT dispatch a ``gui.page.show`` whose first
    page name is not a ``SYSTEM_*`` template."""

    @pytest.mark.xfail(strict=True,
                       reason="GUI-1 §3.2/§4.2/§8.3 MUST dispatch only "
                              "SYSTEM_* page names as templates; "
                              "NamespaceManager.handle_show_page validates only "
                              "that page_names is a list with __from and loads "
                              "any page name (e.g. 'RandomPage') as a namespace")
    def test_non_system_page_not_loaded_as_template(self):
        """§3.2/§4.2 MUST: a non-``SYSTEM_`` first page name is not dispatched
        as a template — the service must not load it as an active namespace."""
        nm, _ = _run_service([_show("RandomPage", frm="legacy.skill")])
        self.assertNotIn("legacy.skill", list(nm.loaded_namespaces.keys()),
                         "service loaded a non-SYSTEM_ page as a namespace")

    def test_system_page_is_loaded(self):
        """§4.3: a ``gui.page.show`` with a valid ``SYSTEM_*`` template
        activates the producing namespace."""
        nm, _ = _run_service([_show("SYSTEM_text", frm="weather.sk")])
        self.assertIn("weather.sk", list(nm.loaded_namespaces.keys()))


@_requires_gui_service
class TestSec41ServiceStripsReservedKeys(TestCase):
    """§4.1: the GUI service MUST strip ``__from`` / ``__idle`` (and any other
    reserved ``__``-prefixed key) before delivering session data to an adapter —
    an adapter receives content keys only."""

    def test_reserved_keys_declared(self):
        """§4.1 MUST: the service recognises the reserved ``__``-prefixed keys
        so it can strip them from adapter-facing session data.

        The post-strip adapter payload travels over the backend's QML
        transport, not the core bus (# not bus-observable). What *is* checkable
        is that the service declares the reserved set it strips."""
        from ovos_gui import namespace as ns
        self.assertIn("__from", ns.RESERVED_KEYS)
        self.assertIn("__idle", ns.RESERVED_KEYS)


@_requires_gui_service
class TestSec43Sec5PerSessionRouting(TestCase):
    """§4.3/§5.1: the lifecycle is per session — each ``session_id`` owns an
    independent namespace stack, and a GUI Message is routed solely by its
    ``session_id`` (an absent/empty session defaulting to ``"default"``)."""

    @pytest.mark.xfail(strict=True,
                       reason="GUI-1 §4.3/§5.1/§8.3 MUST maintain an "
                              "independent namespace stack per session_id; "
                              "NamespaceManager keeps a single flat "
                              "loaded_namespaces/active_namespaces and never "
                              "reads context.session — two sessions collide on "
                              "one global stack")
    def test_independent_stack_per_session(self):
        """§4.3/§5.1 MUST: activating a namespace in session A must not place it
        on session B's stack. With per-session stacks, a page shown only in
        session ``A`` is absent from session ``B``'s active stack."""
        nm, _ = _run_service([
            _show("SYSTEM_text", frm="skA", session_id="A"),
            _show("SYSTEM_text", frm="skB", session_id="B"),
        ])
        # The service exposes no per-session view, so probe the design: a
        # conforming service keys its stacks by session_id.
        per_session = (
            isinstance(getattr(nm, "loaded_namespaces", None), dict)
            and all(isinstance(v, dict) for v in nm.loaded_namespaces.values())
        )
        self.assertTrue(
            per_session,
            "service maintains a single global namespace stack, not one per "
            "session_id")


@_requires_gui_service
class TestSec83ServiceConformance(TestCase):
    """§8.3: the GUI-service-MUST roll-up. The observable parts: dispatch only
    ``SYSTEM_*`` templates (§3.2), route per ``session_id`` (§5.1), and run
    headless with zero adapters (§6.1)."""

    def test_service_starts_with_zero_adapters(self):
        """§8.3/§6.1 MUST: the GUI service starts and operates with zero
        adapters installed (headless no-op) — construction must not raise and
        the service is live on the bus."""
        nm = _gui_service()
        self.assertIsNotNone(nm)
        self.assertTrue(hasattr(nm, "core_bus"))

    def test_namespace_removed_emitted_on_clear(self):
        """§4.3: on ``gui.clear.namespace`` the service removes the namespace
        from the active stack (observable on the core bus as
        ``gui.namespace.removed``)."""
        nm, recs = _run_service([
            _show("SYSTEM_text", frm="sk.clearme"),
            Message(GUI_CLEAR, {"__from": "sk.clearme"}),
        ])
        self.assertIn("gui.namespace.removed", [m.msg_type for m in recs])


# =============================================================================
# §6 / §7 — adapter contract and interaction path
# =============================================================================
#
# The following GUI-1 MUSTs are deliberately NOT encoded as bus assertions
# because their behaviour lives entirely inside an adapter or on the backend's
# private client transport, never on the core bus a conformance test observes:
#
# not bus-observable: §6.1 adapter discovery via the opm.gui_adapter
#   entry-point group and skip-and-log of a failing adapter (in-process
#   plugin enumeration; no bus surface).
# not bus-observable: §6.2 adapter constructed quickly / non-blocking on a
#   background thread (timing of an in-process constructor).
# not bus-observable: §6.3/§6.4 every adapter receives every event / fan-out
#   (adapter-facing dispatch goes over the QML websocket, not the core bus).
# not bus-observable: §6.5 graceful degradation of an unrenderable template
#   (rendering decision inside an adapter).
# not bus-observable: §6.6 adapter exception/threading isolation and
#   no-shared-state-mutation (in-adapter control flow).
# not bus-observable: §6.7 read-only state query surface (backend-facing,
#   non-normative API).
# not bus-observable: §6.8 connection-status aggregation (can_use_gui probe
#   is request/response but the report shape is backend-internal).
# not bus-observable: §6.9 idle/resting-display ownership by the backend
#   (a property of the rendering surface, not a bus message).
# not bus-observable: §7.1 media transport controls act on the media
#   subsystem (owned by the media spec, out of scope here).


class TestSec72InteractionResponse(TestCase):
    """§7.2: when the user acts on an interactive companion the render backend
    SHOULD emit an interaction event back to the originating namespace carrying
    the originating ``session_id``."""

    def test_interaction_response_session_id_is_adapter_emitted(self):
        """§7.2 MUST (the one normative invariant of the input path): an
        interaction response carries its originating ``session_id`` so the
        application routes the answer to the correct session.

        # not bus-observable: the interaction event is emitted by a render
        backend (an adapter) in response to a *user* gesture on a rendered
        widget; no adapter and no user gesture exist in a headless conformance
        run, and the exact topic/payload is explicitly non-normative (§7.2).
        Documented here for traceability; the session-carrying invariant is
        exercised by the MSG-1 / SESSION-1 derivation suites."""
        self.skipTest("not bus-observable: §7.2 interaction event is "
                      "adapter-emitted on a user gesture; topic is non-normative")
