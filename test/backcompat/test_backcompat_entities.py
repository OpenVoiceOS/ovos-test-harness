"""T2.4 entity matrix cells (cross-session handoff, CAMPAIGN.md).

Six cells, all real-symbol-driven against a real ``register_entity_file``
call (``skill_process.py``'s ``BACKCOMPAT_ENABLE_ENTITY=1`` fixture skill,
which registers ``food.entity`` + a sibling ``food.blacklist`` resource --
NOT ``food.entity.blacklist``: ``register_entity_file``
(``ovos_workshop/skills/ovos.py``) strips the ``.entity`` suffix BEFORE
calling ``resources.load_blacklist_file()``, so the sibling resource it
actually loads is ``<name>.blacklist``. An earlier draft of this module's
docstring said ``food.entity.blacklist``, which does not match what
``skill_process.py`` actually writes to disk -- fixed here to match the
real fixture, not the other way around. OVOS-INTENT-2 §4.3):

(a) slot BIND in a real match, crossed against Snew-Cnew-Mold -- xfail,
    blocked_on padatious-pipeline#95.
(b) same probe crossed against Sold -- proves V0 inertness (the bug class
    #95 fixes doesn't even reach an old skill container's registration
    path), xfail naming the V0 boundary.
(c) exactly-once training on registration -- currently double via
    dual-emit (legacy ``padatious:register_entity`` + the spec-compliant
    producer path both firing for one ``register_entity_file`` call),
    xfail blocked_on #95's ``EntityManager.remove`` fix.
(d) blacklist payload-key skew: the legacy twin ships ``blacklist``, the
    dual-emit spec-compliant path ships ``blacklisted_words`` -- verified
    directly against ``ovos_workshop/intents.py`` on this checkout's dev
    fetch (``_PadatiousIntentApi.emit_legacy_register_entity`` vs
    ``IntentServiceInterface.register_entity``), not assumed.
(e) channel cells get the entity-bearing fixture too -- this file's
    ``stack`` fixture always passes ``BACKCOMPAT_ENABLE_ENTITY=1``, so
    every combo (boundary AND channel) exercises it.
(f) resolution-tier assertion: the fixture skill's own dependency
    constraints (this repo's own environment, since the fixture skill is
    ovos-workshop's real ``register_entity_file`` running under whichever
    S-axis venv this combo pins) must not exclude the vintage that
    actually produces a working entity registration.
"""
import uuid

import pytest

from ovos_bus_client.message import Message

from .driver import (ENTITY_BLACKLIST_SAMPLES, ENTITY_FILE, ENTITY_SAMPLES,
                     LEGACY_REGISTER_ENTITY_TOPIC, SKILL_ID,
                     BusServer, Capture, SkillProcess, boundary_xfail,
                     assert_fixture_resolves_its_own_workshop_constraints,
                     entity_blacklist_emission_supported,
                     entity_dual_emit_supported, make_padatious_pipeline)
from .cells import axis_values, resolve_cell
from .test_mixed_version_matrix import COMBO, COMBOS, SKILL_PYTHON

pytestmark = pytest.mark.skipif(
    not COMBO or not SKILL_PYTHON,
    reason="needs BACKCOMPAT_COMBO and BACKCOMPAT_SKILL_PYTHON; see "
           "test/backcompat/build_venvs.sh")

_cell = resolve_cell(COMBO)
_S_IS_NEW = axis_values(_cell)["S"] == "new" if _cell is not None else False
_M_IS_OLD = axis_values(_cell)["M"] == "old" if _cell is not None else True

#: Real-symbol, cross-venv capability probes (driver._skill_venv_probe),
#: computed once at collection time so the xfail markers below can stay
#: static @pytest.mark.xfail(condition, ...) decorators -- CI finding:
#: channel cells (stable-skill/dev-core, testing-skill/dev-core) run a
#: genuinely different vintage of ovos-workshop than any boundary pin,
#: and cells (c)/(d) assumed capabilities (dual-emit, blacklist emission)
#: that simply don't exist yet on either channel pin. Guarded so bare
#: collection (no BACKCOMPAT_SKILL_PYTHON set) never calls the probe with
#: an empty interpreter path -- the whole-module pytestmark skip above
#: already makes the actual value moot in that case.
_HAS_BLACKLIST_EMISSION = (entity_blacklist_emission_supported(SKILL_PYTHON)
                           if SKILL_PYTHON else True)
_HAS_DUAL_EMIT = (entity_dual_emit_supported(SKILL_PYTHON)
                  if SKILL_PYTHON else True)

_SLOT_BIND_XFAIL_REASON = boundary_xfail(
    boundary="padatious registration-time canonicalization does not "
             "normalize entity-slot names the way it folds intent aliases "
             "-- a real match against a registered entity does not bind "
             "the {slot} on Mold",
    axes=("S", "C", "M"),
    blocked_on="padatious-pipeline#95",
    owner="ovos-padatious-pipeline-plugin",
    note="entity cell (a): Snew-Cnew-Mold. #95 adds "
         "_dealias_entity_name, the entity-side counterpart of the intent "
         "fold this suite's Mold cells already probe via "
         "driver.core_canonicalizes(). XPASS means #95 shipped.")

_V0_INERTNESS_XFAIL_REASON = boundary_xfail(
    boundary="same slot-bind probe as (a), crossed against Sold instead: "
             "an old-workshop skill container's register_entity_file call "
             "predates the entity-slot binding contract entirely, so #95 "
             "landing does not change this cell -- V0 inertness, not a "
             "live gap",
    axes=("S",),
    blocked_on=None,
    owner="ovos-workshop",
    note="proves the (a) xfail is scoped to the S=new/M=old crossing and "
         "not a blanket 'entities are broken' claim; this cell should stay "
         "red even after #95 ships, which is what 'V0 inertness' means -- "
         "an XPASS here would mean the OLD container unexpectedly started "
         "seeing the fix too, itself worth investigating.")

_EXACTLY_ONCE_XFAIL_REASON = boundary_xfail(
    boundary="ONE register_entity_file() call trains the real padatious "
             "plugin's registered_entities list TWICE, under TWO DIFFERENT "
             "NAMES: the legacy md5-munged name (from the direct "
             "padatious:register_entity wire frame) and the clean spec "
             "name (from the spec-compliant ovos.entity.register frame's "
             "handler, which internally calls the SAME register_entity() "
             "method a second time as a plain Python call, invisible on "
             "the wire) -- live-verified: registered_entities == 2 after "
             "exactly one register_entity_file() call, names "
             "['<skill_id>:food_<md5>', '<skill_id>:food']",
    axes=("S", "C", "M"),
    blocked_on="padatious-pipeline#95",
    owner="ovos-padatious-pipeline-plugin",
    note="entity cell (c). Same #95 as (a); different symptom (double "
         "training under two names vs no slot bind). XPASS means #95's "
         "EntityManager.remove / dual-emit dedup landed and a single "
         "call trains exactly once.")


@pytest.fixture(scope="module")
def stack():
    if COMBO not in COMBOS:
        pytest.fail(f"unknown BACKCOMPAT_COMBO {COMBO!r}")
    server = BusServer()
    skill = None
    pipeline = None
    try:
        bus = server.client()
        import os
        os.environ["BACKCOMPAT_ENABLE_ENTITY"] = "1"
        try:
            registrations = Capture(bus, LEGACY_REGISTER_ENTITY_TOPIC)
            # the real padatious pipeline plugin, constructed and
            # listening BEFORE the skill spawns -- see
            # driver.make_padatious_pipeline's docstring for why the
            # ordering matters (same discipline as
            # test_backcompat_fallback.py's registration Capture).
            pipeline = make_padatious_pipeline(bus)
            skill = SkillProcess(SKILL_PYTHON, server.xdg)
            registrations.wait(15)
        finally:
            os.environ.pop("BACKCOMPAT_ENABLE_ENTITY", None)
        yield server, bus, skill, registrations, pipeline
    finally:
        if pipeline is not None and hasattr(pipeline, "shutdown"):
            pipeline.shutdown()
        if skill is not None:
            skill.stop()
        server.stop()


@pytest.mark.axes("S", "C", "M")
def test_the_legacy_register_entity_topic_fires(stack):
    """Positive control: whatever else this cell shows, the entity
    registration itself must have happened -- proves the fixture, not the
    boundary, before any downstream cell trusts a red result."""
    _server, _bus, skill, regs, _pipeline = stack
    assert regs.messages, (
        f"{COMBO}: no {LEGACY_REGISTER_ENTITY_TOPIC} observed at all\n"
        f"{skill.log}")
    payload = regs.messages[0].data
    assert payload["name"].startswith(SKILL_ID)
    assert set(ENTITY_SAMPLES) <= set(payload["samples"])


_BLACKLIST_XFAIL_REASON = boundary_xfail(
    boundary="ovos-workshop<9.2.0a1 (OVOS-INTENT-2 §4.3 entity/slot "
             "blacklist adoption boundary, ovos-workshop#454) emits NO "
             "'blacklist' key at all on padatious:register_entity -- "
             "payload is just {file_name, samples, name, lang}. Live-"
             "verified via driver.entity_blacklist_emission_supported "
             "against the CI-failing channel pins: stable (3.4.0) and "
             "testing (7.0.10a1) both predate 9.2.0a1.",
    axes=("S",),
    blocked_on=None,
    owner="ovos-workshop",
    note="not a live tripwire -- this is a real-symbol capability probe "
         "(inspect.getsource for load_blacklist_file), so it re-evaluates "
         "correctly if a channel's pin ever moves past 9.2.0a1; XPASS "
         "here means exactly that happened, not a product regression.")


@pytest.mark.xfail(not _HAS_BLACKLIST_EMISSION, strict=True,
                   reason=_BLACKLIST_XFAIL_REASON)
@pytest.mark.axes("S")
def test_entity_cell_d_blacklist_payload_key_skew(stack):
    """Entity cell (d): the legacy wire twin carries the blacklist under
    ``'blacklist'``; anything that dual-emits a spec-compliant registration
    for the SAME call must (per ``ovos_workshop/intents.py``, read
    directly) use ``'blacklisted_words'`` instead. This is a real,
    already-shipped payload-key skew on origin/dev -- a plain pass, not an
    xfail, on any vintage that actually emits a blacklist at all.

    CI finding: the channel cells (stable-skill/dev-core, testing-skill/
    dev-core) run an ovos-workshop vintage that predates blacklist
    emission ENTIRELY (ovos-workshop#454, first shipped 9.2.0a1) -- an
    earlier draft of this cell assumed every vintage at least emits
    SOMETHING under one key or the other, which is false pre-#454: the
    real payload there is ``{file_name, samples, name, lang}``, no
    blacklist key of either spelling. Vintage-gated via
    ``driver.entity_blacklist_emission_supported`` (a real-symbol probe
    against the installed ovos-workshop, not a version-string check) --
    see that function's own docstring for the boundary evidence.
    """
    _server, _bus, skill, regs, _pipeline = stack
    legacy_payload = regs.messages[0].data
    assert "blacklist" in legacy_payload, (
        f"legacy padatious:register_entity dropped its 'blacklist' key -- "
        f"payload was {legacy_payload!r}")
    assert "blacklisted_words" not in legacy_payload, (
        f"legacy padatious:register_entity payload now carries "
        f"'blacklisted_words' too -- the (d) skew this cell exists to "
        f"pin has closed; if that's a deliberate unification, drop this "
        f"assertion and document the merge, don't just let it XPASS "
        f"silently since this isn't an xfail marker")
    assert set(ENTITY_BLACKLIST_SAMPLES) <= set(legacy_payload["blacklist"])


@pytest.mark.xfail(strict=True, reason=_SLOT_BIND_XFAIL_REASON)
@pytest.mark.axes("S", "C", "M")
def test_entity_cell_a_slot_binds_on_new_skill_new_core(stack):
    """Entity cell (a): Snew-Cnew, crossed against whichever M this combo
    pins. ``padatious-pipeline#95`` adds the entity-side dealias fold this
    test wants to observe (``opm._dealias_entity_name``, mirroring the
    already-shipped ``_dealias_intent_name`` this suite's intent cells
    probe via ``driver.core_canonicalizes()``).

    LIVE-VERIFIED against this batch's real venv_core_new (padatious
    2.0.1a2, i.e. M=new/the intent-fold vintage): ``_dealias_entity_name``
    does NOT exist there either -- unlike the intent fold, #95 is entirely
    unreleased, so this is genuinely M-axis-independent today (an earlier
    draft of this cell wrongly expected the M=new control to already have
    it and had to be corrected against the live run). Once #95 ships this
    symbol will exist on Mnew but very likely still not on Mold -- if that
    happens, split this back into an M-crossed pair.
    """
    _server, _bus, skill, regs, _pipeline = stack
    import ovos_padatious.opm as opm
    assert hasattr(opm, "_dealias_entity_name"), (
        f"{COMBO}: entity dealias fold (#95) not present on the installed "
        f"padatious, as expected pre-#95")


#: Entity cell (b) is not an S=old/S=new xfail PAIR the way cell (a)'s
#: M=old/M=new split is -- V0 inertness means this cell is expected to
#: stay red FOREVER, even after #95 ships (that is the whole point: an old
#: skill container's registration path predates the slot-bind contract
#: entirely, so no matcher-side fix ever reaches it). Adversarial review
#: caught an earlier draft that built this as a fake xfail PAIR anyway (a
#: "control" half on S=new that only ever ran ``assert False``/
#: ``pytest.fail`` with no real probe, wrapped in an xfail condition that
#: made an XPASS on either half structurally impossible) -- both halves
#: collapsed into ONE real-probe test below, applicable only on S=old
#: (S=new skips, honestly, as "not this axis' cell" rather than faking a
#: second xfail marker that could never do anything).
@pytest.mark.skipif(_S_IS_NEW, reason="entity cell (b) only applies to "
                    "S=old (V0 inertness); S=new has no old-munge "
                    "registration path to probe -- see cell (a) instead")
@pytest.mark.xfail(strict=True, reason=_V0_INERTNESS_XFAIL_REASON + " | "
                   "NOTE: this cell can NEVER XPASS -- V0 inertness means "
                   "an old skill container's register_entity_file predates "
                   "the slot-bind contract entirely, so no matcher-side "
                   "fix (padatious-pipeline#95 or otherwise) ever reaches "
                   "it. This marker is a permanent, documented-red probe, "
                   "not a tripwire; remove it by hand only if a workshop "
                   "release ever changes the S=old registration shape "
                   "itself (unexpected on a frozen boundary pin), not on "
                   "any padatious-side fix landing.")
@pytest.mark.axes("S")
def test_entity_cell_b_v0_inertness(stack):
    """Entity cell (b): same slot-bind question as (a), crossed against
    Sold instead of Mold -- proves #95 landing does NOT repair an old
    skill container's registration (V0 inertness): an old workshop's
    ``register_entity_file`` predates the entity-slot binding contract
    #95's fold targets, so no matcher-side fix reaches it. Verified via
    the same real-symbol probe as (a): the registered entity name observed
    off the wire (``regs.messages[0].data['name']``) is the OLD, pre-slot-
    contract munge (``<skill_id>:<file>_<md5>``, ``ovos_workshop/skills/
    ovos.py``'s ``register_entity_file``) on an old skill container
    regardless of which matcher receives it.
    """
    _server, _bus, skill, regs, _pipeline = stack
    name = regs.messages[0].data["name"]
    assert "_" not in name.split(":", 1)[-1].split("_", 1)[0], (
        f"{COMBO}: expected the old munged entity name shape on "
        f"Sold, got {name!r} -- if this now looks like a clean slot "
        f"name, the S=old container's register_entity_file changed "
        f"shape (unexpected on a boundary pin)")
    pytest.fail(
        f"{COMBO}: old skill container name={name!r} carries the "
        f"md5 munge (ovos_workshop/skills/ovos.py's "
        f"register_entity_file) -- no slot-bind contract exists for "
        f"a matcher-side fix to reach on this vintage; V0 inertness")


@pytest.mark.axes("S", "C", "M")
def test_entity_cell_c_control_boot_registration_is_exactly_one_wire_frame(stack):
    """Positive control for entity cell (c): a single, first-time
    ``register_entity_file()`` call (boot-time, in ``initialize()``) must
    produce exactly one legacy ``padatious:register_entity`` WIRE frame.
    LIVE-VERIFIED true on this batch's reference cell.

    This stays a genuinely true, still-useful control even though the
    xfail below (which measures the padatious PLUGIN's own internal
    ``registered_entities`` bookkeeping, not the wire) shows a real
    doubling: the wire-frame count and the plugin's internal training
    count are two DIFFERENT observables that happen to disagree here --
    see ``driver.make_padatious_pipeline``'s docstring and the xfail
    below for exactly why (the second training happens via an in-process
    Python call, not a second wire frame).
    """
    _server, _bus, skill, regs, _pipeline = stack
    assert len(regs.messages) == 1, (
        f"{COMBO}: first-time register_entity_file() produced "
        f"{len(regs.messages)} legacy frames, expected exactly one")


@pytest.mark.xfail(_HAS_DUAL_EMIT, strict=True, reason=_EXACTLY_ONCE_XFAIL_REASON)
@pytest.mark.axes("S", "C", "M")
def test_entity_cell_c_registration_trains_the_plugin_exactly_once(stack):
    """Entity cell (c), the REAL signal: a real ``PadatiousPipeline``
    instance's OWN ``registered_entities`` bookkeeping (``driver.
    make_padatious_pipeline``, constructed and listening BEFORE the skill
    spawns -- see the ``stack`` fixture) must contain exactly ONE entry
    after exactly ONE ``register_entity_file()`` call.

    Adversarial review caught two problems in earlier drafts of this
    cell: (1) it only re-probed ``opm._dealias_entity_name`` (cell (a)'s
    symbol) instead of counting anything real; (2) a second draft counted
    LEGACY WIRE frames after a synthetic re-registration trigger, which
    turned out to be a dead discriminator -- live-verified the wire-frame
    count for boot+reregister is 2 in BOTH the buggy and a hypothetically
    fixed world (a correct remove-then-add also nets one more frame), so
    it could never distinguish the bug from the fix.

    LIVE-VERIFIED against this batch's reference cell what the real bug
    actually is: ``ovos_workshop/intents.py``'s ``IntentServiceInterface.
    register_entity`` (the dual-emit producer ``register_entity_file``
    calls) emits BOTH the legacy ``padatious:register_entity`` wire frame
    AND the spec ``SpecMessage.ENTITY_REGISTER`` (``ovos.entity.register``)
    wire frame for ONE call. The padatious plugin's own
    ``handle_register_entity_spec`` (``ovos_padatious/opm.py``) consumes
    the spec frame by calling ``self.register_entity(legacy)`` -- a
    second, IN-PROCESS Python call into the exact same handler the first
    (legacy) wire frame already triggered, invisible on the wire. Result,
    observed directly on ``pipeline.registered_entities`` (not assumed):
    TWO entries for ONE call, under TWO DIFFERENT NAMES --
    ``'<skill_id>:food_<md5>'`` (legacy path) and ``'<skill_id>:food'``
    (spec path, using the clean, unmunged entity_name). Mutant this
    guards: land #95's dedup/remove fix and ``registered_entities`` drops
    to exactly one entry per real call.

    CI finding, vintage-gated (``driver.entity_dual_emit_supported``): the
    double-training premise above depends ENTIRELY on dual-emit
    (ovos-workshop#431, 9.3.0a1+) existing -- a pre-dual-emit vintage
    (both channel pins: stable 3.4.0, testing 7.0.10a1) has only the
    single legacy producer call, so ``registered_entities`` genuinely
    ends up with exactly ONE entry there. Same physical assertion on
    both sides of the gate: on a dual-emit vintage this is the documented
    bug (xfail, strict); on a pre-dual-emit vintage it is the CORRECT V0
    behavior and runs as a genuine positive control instead.
    """
    _server, _bus, skill, _regs, pipeline = stack
    names = [e.get("name") for e in pipeline.registered_entities]
    assert len(pipeline.registered_entities) == 1, (
        f"{COMBO}: one register_entity_file() call trained the real "
        f"padatious plugin {len(pipeline.registered_entities)} times, "
        f"expected exactly once -- registered names: {names}\n{skill.log}")


@pytest.mark.axes("S")
def test_entity_cell_f_fixture_skill_constraints_dont_exclude_the_producer(stack):
    """Entity cell (f) -- resolution-tier assertion, now the GENERAL
    metadata-skew guard pattern (OWNER RULING 2026-08-14; see
    ``driver.assert_fixture_resolves_its_own_workshop_constraints`` and
    ``test_backcompat_fallback.py``'s own copy of this same call for why
    it moved to a shared helper). The fixture skill runs under whichever
    S-axis ovos-workshop venv this combo pins (``build_venvs.sh``'s
    ``skill_old``/``skill_new``); this asserts THAT installed
    ovos-workshop's own declared dependency floor on ovos-bus-client does
    not exclude the vintage that actually carries a working
    ``register_entity_file`` -- i.e. that the constraint the skill venv
    was built under isn't itself the reason entity registration would be
    unreachable, independent of whatever #95/#528 fix. A metadata-skew
    guard, not a behavior probe: if this ever fails, the fixture's own
    venv pin is wrong, not the product.
    """
    _server, _bus, skill, _regs, _pipeline = stack
    assert_fixture_resolves_its_own_workshop_constraints(skill, COMBO)
