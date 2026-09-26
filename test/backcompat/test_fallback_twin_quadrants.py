"""FALLBACK-1 back-compat cells: the four MIGRATION_MAP fallback twins, per
quadrant.

``test_fallback_namespace_twin.py`` already drives these four twins in one
vintage: two current clients on a real bus, both directions, plus a raw
websocket reader and a flags-off control. That answers "does the bridge
deliver", and it is not enough for two of the four quadrants the backcompat
lane's Round 2 brief names, because:

* a raw websocket reader is not a client. It sees literal frames and has no
  subscription semantics, so it cannot show that a *genuinely old*
  ``MessageBusClient`` dispatches the frame to a handler. Receive-side
  counterpart delivery is a property of the SUBSCRIBER's client, so the cell
  that matters pins the subscriber to the oldest deployed bus-client
  (``ovos-bus-client==1.5.0``, ``build_venvs.sh``'s ``venv_wire_twin_old``)
  and the emitter to the current one. Two copies of the same version prove
  nothing about the pairing.
* no cell asserted the FALLBACK-1 *registry* clauses. A twin that delivers
  twice, or delivers with the context session stripped, breaks §3.1/§3.2/§3.4
  without changing a single payload field, and a delivery-count cell cannot
  see it.

Quadrants (backcompat's Round 2 table, from the T-1331 ruling
``knowledge/wiki/audits/architecture/fallback1-twins.md``):

===  =========================================  =============================
Q1   modern client emits the CANONICAL name     real 1.5.0 listener on the
                                                LEGACY name hears it once
Q2   a LEGACY emit                              canonical-only modern
                                                listener hears it once, with
                                                the context session
Q3   a LEGACY emit                              consumer whose spec-tools
                                                predates the entry: NOT
                                                delivered. Strict xfail that
                                                names the vintage.
Q4   double delivery of both spellings          §3.1/§3.2/§3.4 registry state
                                                is unchanged
===  =========================================  =============================

Clauses asserted in Q4, quoted from OpenVoiceOS/architecture ``fallback.md``
at fd48a09 through the ruling:

* §3.1 "The plugin adds the skill to its registry. Re-registration with the
  same ``skill_id`` replaces the prior entry."
* §3.2 "Removes the skill from the registry. Unknown ``skill_id`` is a
  no-op." and "The plugin **MUST** key the removal by
  ``context.session.session_id`` of the deregistration Message -- never by a
  ``session_id`` carried in ``Message.data``".
* §3.4 "the plugin keys each entry by ``context.session.session_id`` of the
  registration Message."

What each quadrant here does NOT drive, said plainly so no reader
over-reads it:

* Q2's emitter is a real ``MessageBusClient`` on the legacy name, not the
  shipped ``ovos-workshop`` ``FallbackSkill`` that owns that emit today
  (``skills/fallback.py:175``, ``:195``, ``:203``, ``:113``). The Round 2
  table allows "any client" for this quadrant's emitter, and what the
  quadrant tests is the CONSUMER's receive-side bridge. A cell that boots a
  real FallbackSkill belongs with the skill-container venvs and is a
  separate piece of work; `test_mixed_version_matrix.py` owns that shape.
* Q3 needs a consumer whose ``ovos-spec-tools`` predates 1.12.0a1, which is a
  venv this repository does not build yet. It is a strict xfail that names
  the vintage and the missing venv, never a pass and never a skip -- the
  ruling is explicit that this quadrant must not read green.

Gating: ``FALLBACK_TWIN_CELLS=1`` for the quadrants that need a real
``ovos-messagebus`` (Q2, Q4), and ``BACKCOMPAT_WIRE_TWIN_PYTHON`` for Q1's
old listener, the same two gates the modules those cells extend already use.
Never importability: a broken install must fail a cell, not skip it.
"""
import os
import time
import uuid

import pytest

#: legacy topic -> spec topic. Spelled out, both spellings, so
#: ``test/meta/test_migration_map_cells.py`` counts these four as driven and
#: its allowlist ratchet cannot be satisfied by a cell that names one side.
FALLBACK_TWINS = {
    "ovos.skills.fallback.register": "ovos.fallback.register",
    "ovos.skills.fallback.deregister": "ovos.fallback.deregister",
    "ovos.skills.fallback.ping": "ovos.fallback.ping",
    "ovos.skills.fallback.pong": "ovos.fallback.pong",
}

LEGACY_TOPICS = list(FALLBACK_TWINS)
SPEC_TOPICS = list(FALLBACK_TWINS.values())

#: The session every cell stamps, so §3.4's "keyed by
#: context.session.session_id" is checked against a value the cell chose.
SAT = "sat-1"
OTHER_SAT = "sat-2"

#: Wait after an emit before counting. A duplicate delivery lands inside this
#: window, so a count read after it closes is a real count and not a race.
SETTLE = 0.8

BUS_CELLS = os.environ.get("FALLBACK_TWIN_CELLS") == "1"
WIRE_TWIN_PYTHON = os.environ.get("BACKCOMPAT_WIRE_TWIN_PYTHON", "")

needs_bus = pytest.mark.skipif(
    not BUS_CELLS,
    reason="needs a real ovos-messagebus; set FALLBACK_TWIN_CELLS=1 where it "
           "is installed")
needs_old_client = pytest.mark.skipif(
    not WIRE_TWIN_PYTHON,
    reason="needs BACKCOMPAT_WIRE_TWIN_PYTHON, a genuinely pre-spec-tools "
           "ovos-bus-client; build it with "
           "test/backcompat/build_venvs.sh venv_wire_twin_old")


def _msg(topic, data, session_id):
    from ovos_bus_client.message import Message
    return Message(topic, dict(data),
                   {"session": {"session_id": session_id}})


def test_map_still_pairs_these_four():
    """Everything below is only about MIGRATION_MAP while the map still
    pairs these spellings. Without this, a rename would turn every cell in
    this module into a silent timeout instead of a named failure."""
    from ovos_spec_tools.messages import MIGRATION_MAP
    for legacy, spec in FALLBACK_TWINS.items():
        assert legacy in MIGRATION_MAP, f"{legacy} left MIGRATION_MAP"
        assert MIGRATION_MAP[legacy].value == spec, (
            f"MIGRATION_MAP now pairs {legacy} with "
            f"{MIGRATION_MAP[legacy].value}, not {spec}")


# ---------------------------------------------------------------------------
# Q1: a modern canonical emit reaches a real 1.5.0 listener on the legacy name
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def old_listener_stack():
    """One real bus, one genuinely-old client subscribed to all four LEGACY
    fallback names."""
    from .driver import BusServer, WireTwinListener
    server = BusServer()
    listener = None
    try:
        listener = WireTwinListener(WIRE_TWIN_PYTHON, server.xdg,
                                   topics=LEGACY_TOPICS)
        yield server, listener
    finally:
        if listener is not None:
            listener.stop()
        server.stop()


@needs_old_client
def test_q1_listener_is_genuinely_pre_spec_tools_and_subscribed(old_listener_stack):
    """Adversarial guard, before any Q1 assertion is trusted.

    Two things a drifted venv would hide: a listener that DOES carry
    ``NamespaceTranslator`` would bridge locally and make Q1 pass for the
    wrong reason, and a listener that silently ignored ``WIRE_TWIN_TOPICS``
    would sit on ``speak`` while Q1 read "no delivery" as a bridge failure.
    Both are read off the live process's own VERSIONS line."""
    _, listener = old_listener_stack
    assert listener.versions.get("client_has_namespace_translator") is False, (
        f"the pinned listener carries NamespaceTranslator, so it is not the "
        f"pre-spec-tools vintage this quadrant needs; "
        f"versions={listener.versions}")
    assert listener.versions.get("subscribed_topics") == LEGACY_TOPICS, (
        f"the live listener subscribed to "
        f"{listener.versions.get('subscribed_topics')!r}, not the four legacy "
        f"fallback names; every Q1 assertion below would measure the wrong "
        f"subscription")


@needs_old_client
@pytest.mark.parametrize("legacy", LEGACY_TOPICS)
def test_q1_positive_control_old_listener_hears_its_own_spelling(
        old_listener_stack, legacy):
    """Positive control: a plain LEGACY emit must reach the old listener.
    Without it, "the canonical emit did not arrive" cannot be told apart
    from "this subscription was never alive"."""
    server, listener = old_listener_stack
    bus = server.client()
    try:
        token = uuid.uuid4().hex
        bus.emit(_msg(legacy, {"token": token}, SAT))
        assert listener.wait_for_token(token), (
            f"the old listener never received a plain {legacy!r} emit, so its "
            f"subscription is dead and no Q1 cell can be trusted.\n"
            f"listener log:\n{listener.log}")
    finally:
        bus.close()


@needs_old_client
@pytest.mark.parametrize("legacy,spec", list(FALLBACK_TWINS.items()),
                         ids=[f"{s}->{l}" for l, s in FALLBACK_TWINS.items()])
def test_q1_canonical_emit_reaches_the_old_legacy_listener_once(
        old_listener_stack, legacy, spec):
    """Q1, the production path: a current client emits the CANONICAL name and
    a pre-spec-tools client subscribed to the LEGACY name receives it exactly
    once, with the payload intact and the context session kept.

    Exactly once matters as much as at least once: the send-side wire twin
    and any receive-side bridge must not both deliver to the same handler.
    """
    server, listener = old_listener_stack
    bus = server.client()
    try:
        token = uuid.uuid4().hex
        payload = {"token": token, "skill_id": "fb.test", "priority": 50}
        bus.emit(_msg(spec, payload, SAT))
        assert listener.wait_for_token(token), (
            f"a canonical {spec!r} emit never reached the old client listening "
            f"on {legacy!r}: the legacy wire twin is the only thing that still "
            f"reaches this vintage.\nlistener log:\n{listener.log}")
        time.sleep(SETTLE)
        records = listener.received_for(token)
        assert len(records) == 1, (
            f"the old listener received {len(records)} frames for one "
            f"canonical {spec!r} emit, expected exactly 1: "
            f"{[r.get('topic') for r in records]}")
        record = records[0]
        assert record["topic"] == legacy, (
            f"the frame arrived on {record['topic']!r}, not the legacy "
            f"{legacy!r} the old client subscribed to")
        assert record["data"].get("skill_id") == "fb.test"
        assert record["data"].get("priority") == 50, (
            f"payload changed across the twin: {record['data']}")
        assert record["session_id"] == SAT, (
            f"the twin delivered with session_id {record['session_id']!r}, not "
            f"{SAT!r}: FALLBACK-1 §3.4 keys the registry by the context "
            f"session, so a twin that drops it breaks the clause with an "
            f"intact payload")
    finally:
        bus.close()


# ---------------------------------------------------------------------------
# Q2: a legacy emit reaches a canonical-only modern listener, session kept
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def modern_stack():
    from .driver import BusServer
    server = BusServer()
    try:
        yield server
    finally:
        server.stop()


@needs_bus
@pytest.mark.parametrize("legacy,spec", list(FALLBACK_TWINS.items()),
                         ids=[f"{l}->{s}" for l, s in FALLBACK_TWINS.items()])
def test_q2_legacy_emit_reaches_a_canonical_only_listener_once(
        modern_stack, legacy, spec):
    """Q2: the shipped direction. Every fallback emit on ``origin/dev`` still
    uses the legacy spelling (ovos-workshop ``skills/fallback.py:175``,
    ``:195``, ``:203``, ``:113``; ovos-core ``fallback_service.py:229``), and
    a consumer written against the spec subscribes to the canonical name
    only. The consumer's own client must bridge it, once, with the context
    session intact."""
    from .driver import Capture
    server = modern_stack
    emitter, consumer = server.client(), server.client()
    try:
        token = uuid.uuid4().hex
        cap_spec = Capture(consumer, spec, token=token)
        cap_legacy = Capture(consumer, legacy, token=token)
        try:
            emitter.emit(_msg(legacy, {"token": token, "skill_id": "fb.test",
                                       "priority": 50}, SAT))
            time.sleep(SETTLE)
            assert len(cap_spec.messages) == 1, (
                f"a canonical-only consumer received {len(cap_spec.messages)} "
                f"frames on {spec!r} for one legacy {legacy!r} emit, expected "
                f"exactly 1")
            got = cap_spec.messages[0]
            assert got.data.get("skill_id") == "fb.test"
            assert got.data.get("priority") == 50, (
                f"payload changed across the twin: {got.data}")
            session = ((got.context or {}).get("session") or {}).get("session_id")
            assert session == SAT, (
                f"the bridged frame carries session_id {session!r}, not "
                f"{SAT!r}: §3.2 and §3.4 key registry state by the context "
                f"session of the Message")
            assert len(cap_legacy.messages) == 1, (
                f"the literal {legacy!r} frame was delivered "
                f"{len(cap_legacy.messages)} times; a consumer subscribed to "
                f"both spellings must still see each frame once")
        finally:
            cap_spec.close()
            cap_legacy.close()
    finally:
        emitter.close()
        consumer.close()


# ---------------------------------------------------------------------------
# Q3: a consumer whose spec-tools predates the entry is NOT reached
# ---------------------------------------------------------------------------

SPEC_TOOLS_OLD_PYTHON = os.environ.get("BACKCOMPAT_SPEC_TOOLS_OLD_PYTHON", "")


@pytest.mark.xfail(strict=True, reason=(
    "Q3, the ruling's no-bridge quadrant: a LEGACY emit gets no wire twin "
    "(the send side skips a topic already in MIGRATION_MAP) and a consumer "
    "whose ovos-spec-tools predates 1.12.0a1 -- 1.11.2a1 is the vintage the "
    "brief names -- has no entry for these four, so its client cannot bridge "
    "either. Nothing delivers, and that is correct behaviour rather than a "
    "defect. This repository builds no venv pinned to spec-tools 1.11.2a1 "
    "yet, so the quadrant is recorded as a strict xfail naming the vintage "
    "and the missing venv. It must never read as a pass: the day a "
    "venv_spec_tools_old exists, the body below becomes a real cell and this "
    "marker is removed. Owner: harness lane, brief T-0243 Round 2 Q3."))
@pytest.mark.parametrize("legacy,spec", [(l, s) for l, s in
                                         FALLBACK_TWINS.items()][:1],
                         ids=["register"])
def test_q3_old_spec_tools_consumer_is_not_reached(legacy, spec):
    """Q3 is unrun, deliberately and visibly.

    The assertion is written out so the shape is reviewable and so the cell
    starts working the moment the venv exists, but the venv is absent, so the
    cell fails here rather than anywhere that could be mistaken for a
    measurement. A skip would let the quadrant disappear from a green run,
    which is exactly what the ruling forbids.
    """
    assert SPEC_TOOLS_OLD_PYTHON, (
        f"Q3 for {legacy} <-> {spec} needs a consumer pinned to "
        f"ovos-spec-tools 1.11.2a1 (BACKCOMPAT_SPEC_TOOLS_OLD_PYTHON). No "
        f"such venv is built by test/backcompat/build_venvs.sh; see this "
        f"module's docstring")


# ---------------------------------------------------------------------------
# Q4: the FALLBACK-1 registry clauses under double delivery
# ---------------------------------------------------------------------------

class _Registry:
    """The smallest thing that can hold FALLBACK-1 §3.4 state: entries keyed
    by ``(context.session.session_id, skill_id)``.

    It is deliberately a local model rather than the shipped plugin. The
    question these cells ask is whether the TWIN preserves what the clauses
    key on, and a model makes the state readable frame by frame. A cell that
    booted the real plugin would answer a different and also useful question
    -- whether that plugin implements the clauses -- which belongs to the
    skills-side suite, not to a bus back-compat cell.
    """

    def __init__(self):
        self.entries = {}
        self.deliveries = 0

    def register(self, message):
        self.deliveries += 1
        session = ((message.context or {}).get("session") or {}).get("session_id")
        skill_id = (message.data or {}).get("skill_id")
        # §3.1: re-registration with the same skill_id replaces the entry.
        self.entries[(session, skill_id)] = (message.data or {}).get("priority")

    def deregister(self, message):
        self.deliveries += 1
        # §3.2 MUST: key the removal by the CONTEXT session, never by a
        # session_id in data. An unknown skill_id is a no-op.
        session = ((message.context or {}).get("session") or {}).get("session_id")
        skill_id = (message.data or {}).get("skill_id")
        self.entries.pop((session, skill_id), None)


@needs_bus
def test_q4_register_is_idempotent_under_double_delivery(modern_stack):
    """§3.1 and §3.4: a consumer subscribed to BOTH spellings sees each frame
    once, so one registration leaves ONE entry keyed by the context session,
    and a re-registration replaces it rather than adding a second."""
    server = modern_stack
    emitter, consumer = server.client(), server.client()
    registry = _Registry()
    legacy, spec = ("ovos.skills.fallback.register", "ovos.fallback.register")
    consumer.on(legacy, registry.register)
    consumer.on(spec, registry.register)
    try:
        emitter.emit(_msg(spec, {"skill_id": "fb.test", "priority": 50}, SAT))
        time.sleep(SETTLE)
        assert registry.entries == {(SAT, "fb.test"): 50}, (
            f"one canonical registration delivered to a both-spellings "
            f"consumer left {registry.entries}, expected one entry keyed by "
            f"the context session ({registry.deliveries} deliveries)")

        # §3.1: same skill_id, new priority, replaces.
        emitter.emit(_msg(spec, {"skill_id": "fb.test", "priority": 70}, SAT))
        time.sleep(SETTLE)
        assert registry.entries == {(SAT, "fb.test"): 70}, (
            f"re-registration did not replace the prior entry: "
            f"{registry.entries}")
    finally:
        emitter.close()
        consumer.close()


@needs_bus
def test_q4_deregister_keys_on_the_context_session_not_the_payload(modern_stack):
    """§3.2: two satellites register the same ``skill_id``; a deregistration
    under ``sat-1`` removes only that entry, a second delivery of the same
    frame is a no-op, and a ``session_id`` planted in ``data`` is ignored."""
    server = modern_stack
    emitter, consumer = server.client(), server.client()
    registry = _Registry()
    legacy = "ovos.skills.fallback.deregister"
    spec = "ovos.fallback.deregister"
    consumer.on("ovos.skills.fallback.register", registry.register)
    consumer.on("ovos.fallback.register", registry.register)
    consumer.on(legacy, registry.deregister)
    consumer.on(spec, registry.deregister)
    try:
        emitter.emit(_msg("ovos.fallback.register",
                          {"skill_id": "fb.test", "priority": 50}, SAT))
        emitter.emit(_msg("ovos.fallback.register",
                          {"skill_id": "fb.test", "priority": 50}, OTHER_SAT))
        time.sleep(SETTLE)
        assert set(registry.entries) == {(SAT, "fb.test"),
                                         (OTHER_SAT, "fb.test")}, (
            f"the two satellites did not both register: {registry.entries}")

        # The planted data session_id names the OTHER satellite. §3.2 says the
        # context session decides, so sat-2's entry must survive.
        emitter.emit(_msg(spec, {"skill_id": "fb.test",
                                 "session_id": OTHER_SAT}, SAT))
        time.sleep(SETTLE)
        assert set(registry.entries) == {(OTHER_SAT, "fb.test")}, (
            f"deregistration under context session {SAT!r} left "
            f"{registry.entries}: §3.2 requires the removal to be keyed by "
            f"the context session and the data session_id to be ignored")

        # A repeat of the same frame is an unknown-skill_id no-op (§3.2).
        before = dict(registry.entries)
        emitter.emit(_msg(spec, {"skill_id": "fb.test"}, SAT))
        time.sleep(SETTLE)
        assert registry.entries == before, (
            f"a second deregistration changed state: {registry.entries}")
    finally:
        emitter.close()
        consumer.close()


@needs_bus
def test_q4_pong_collector_lists_a_skill_once_and_orders_by_priority(modern_stack):
    """§6.1 with PIPELINE-1 §4.5's payload: a collector subscribed to both
    pong spellings lists each ``skill_id`` once under double delivery, and
    the handler order follows ``priority``, not arrival order."""
    server = modern_stack
    emitter, consumer = server.client(), server.client()
    seen = {}
    order = []

    def collect(message):
        data = message.data or {}
        skill_id = data.get("skill_id")
        order.append(skill_id)
        if skill_id not in seen:
            seen[skill_id] = data.get("priority")

    consumer.on("ovos.skills.fallback.pong", collect)
    consumer.on("ovos.fallback.pong", collect)
    try:
        emitter.emit(_msg("ovos.fallback.pong",
                          {"skill_id": "fb.low", "can_handle": True,
                           "priority": 90}, SAT))
        emitter.emit(_msg("ovos.fallback.pong",
                          {"skill_id": "fb.high", "can_handle": True,
                           "priority": 10}, SAT))
        time.sleep(SETTLE)
        assert sorted(seen) == ["fb.high", "fb.low"], (
            f"a both-spellings collector listed {order}, so a skill was "
            f"counted more than once or one never arrived")
        by_priority = sorted(seen, key=lambda s: seen[s])
        assert by_priority == ["fb.high", "fb.low"], (
            f"handler order {by_priority} does not follow priority "
            f"{seen}; arrival order was {order}")
        assert order[:2] == ["fb.low", "fb.high"], (
            f"arrival order was {order[:2]}, so this cell is not actually "
            f"measuring order-by-priority against a different arrival order")
    finally:
        emitter.close()
        consumer.close()
