"""Mixed-version back-compat matrix: a real bus, two venvs, four combos.

Why this exists
---------------

The conformance suites in ``test/conformance/`` install one stack from
``requirements.txt`` and run against it, and pip installs one package per name.
That is the harness's documented single-ref-per-repo limitation, and it makes a
whole class of bug invisible here: the breakage this suite is about is
*definitionally* cross-version, a skill container frozen months ago talking to
a stack that moved on. Seeing it needs two package sets alive at once, which
means two venvs and a real websocket between them.

This is the harness's cross-repo home for that pattern. ``ovos-core`` carries
its own copy of this suite, deliberately: a stack contract is pinned where the
stack lives, so a breakage is traceable to the repo that caused it. The two
copies are meant to run in parallel and say the same thing.

What moved
----------

OVOS-MSG-1 §2.1.1 builds the per-intent dispatch topic as
``<skill_id>:<intent_name>``. Old ``ovos-workshop`` built it from the
padatious resource **filename**, so the authoring extension leaked onto the
wire as ``<skill_id>:food.order.intent``. Two independent changes then landed:

* ``ovos-padatious >= 2.0.1a1`` folds the suffixed id onto the canonical
  ``<skill_id>:food.order`` at **registration** time, so every match — and
  therefore every dispatch, since ``ovos-core`` forwards ``match.match_type``
  verbatim — is canonical;
* ``ovos-workshop >= 9.3.2a1`` binds the handler to **both** spellings, so a
  skill built against it survives either dispatch.

The interesting cell is the one where those two miss each other: a skill built
against ``ovos-workshop == 9.3.1a2`` binds the suffixed topic **only**, and a
current core dispatches the canonical topic **only**.

The matrix
----------

===================  ==================  =================  ============
combo                skill binds         core dispatches    handler runs
===================  ==================  =================  ============
old skill/old core   suffixed only       suffixed           yes
old skill/new core   suffixed only       canonical          **no**
new skill/old core   both                suffixed           yes
new skill/new core   both                canonical          yes (once)
===================  ==================  =================  ============

Only ``old skill/new core`` is broken, and it is marked
``xfail(strict=True)``. The other three are passing controls: they prove the
harness can see a handler fire at all, so the one red cell is a real finding
and not a broken fixture.

Two channel cells reflect that same gap against the live fleet rather than a
boundary pin: ``stable-skill/dev-core`` and ``testing-skill/dev-core`` build
the skill side straight from the OVOS distro's own constraint files (fetched
fresh in ``build_venvs.sh``), and both currently resolve an ovos-workshop
below the 9.3.2a1 canonical-binding line, so they hit the identical failure
against a dev core. ``dev-skill/stable-core`` and ``dev-skill/testing-core``
are the passing mirror: a dev-workshop skill against either channel's
padatious, which never canonicalizes today, so the suffixed dispatch still
finds a bound handler.

How it gets fixed, and why the fix lands where it does
------------------------------------------------------

The old container does **not** ship an old ``ovos-bus-client``. Its workshop
pin declares a floor, not a ceiling, so a rebuilt container resolves the
current client — this suite asserts that, because the whole repair strategy
depends on it. ``ovos-bus-client#271`` bridges in both directions with no state: the
EMITTER also sends a marked ``.intent``-suffixed twin frame for every intent
topic (reaches a truly frozen image whose baked-in old client cannot be fixed
from outside), and a modern RECEIVER canonicalizes unmarked suffixed traffic
locally (serves a rebuilt container whose floor-pin resolved a new client
under old workshop). Either way the old handler runs unchanged.

Kill-switch role
----------------

These four cells are a gate on the compat train, in both directions:

* the day ``#271`` releases, ``old skill/new core`` starts passing,
  ``strict=True`` turns that into a loud XPASS failure, and the marker comes
  off — the guard is then permanent;
* ``ovos-workshop#500`` removes the suffixed binding, which turns
  ``new skill/old core`` red. That cell must not be deleted to make the PR
  green; it is the signal that the inbound direction (suffixed wire topic →
  canonical local listener) is still missing from the client;
* any PR that drops the compat must flip these deliberately.

Running it
----------

The combo is selected by environment, so one script serves all four CI matrix
entries::

    BACKCOMPAT_COMBO=old-skill/new-core \\
    BACKCOMPAT_SKILL_PYTHON=/path/to/venv_skill_old/bin/python \\
    <core-venv>/bin/pytest test/backcompat/

``test/backcompat/build_venvs.sh`` builds the four venvs with the pins above.

Design references below (``design §X.Y``) are to ``docs/matrix-design.md``.
"""
import os
import time
import uuid

import pytest

from ovos_bus_client.message import Message

from .cells import (BOUNDARY_ALIASES, CHANNEL_CELLS, MATCHER_SKEW, OTHER,
                    REFERENCE, adapt_vintage, axis_values, resolve_cell)
from .driver import (ACTIVATED_TOPIC,
                     AUDIO_OUTPUT_END_TOPIC, AUDIO_OUTPUT_START_TOPIC,
                     LEGACY_SPEAK_TOPIC,
                     CANONICAL_TOPIC, CONVERSE_FIRED_TOPIC,
                     CONVERSE_MATCH_TOPIC, CONVERSE_REQUEST_TOPIC,
                     CONVERSE_RESPONSE_TOPIC,
                     CONVERSE_TRIGGER_TOPIC, GET_RESPONSE_ANSWER_TOPIC,
                     GET_RESPONSE_DONE_TOPIC, GET_RESPONSE_TIMEOUT,
                     GET_RESPONSE_TRIGGER_TOPIC, LEGACY_TOPIC, SKILL_ID,
                     SPEAK_WAIT_DONE_TOPIC, SPEAK_WAIT_TRIGGER_TOPIC,
                     BusServer, Capture, SkillProcess, AudioProcess,
                     adapt_consumes_intent4_keywords,
                     audio_output_ended_spec_topic,
                     audio_output_started_spec_topic, speak_spec_topic,
                     mic_listen_spec_topic,
                     audio_output_end_topic_probe, converse_match,
                     core_canonicalizes, core_has_pipeline_match_api,
                     dispatch, dispatch_match, emitter_side_has_reemit_hook,
                     dispatch_topic_for, make_converse_service,
                     session_context, wait_for_active_skill,
                     wait_for_response_mode)

#: What each combo is *supposed* to be, so a silent pin drift (a new workshop
#: release changing what it binds, or the padatious fold being reverted) fails
#: as a wrong-vintage error instead of quietly turning a red cell green.
#:
#: Two kinds of cell, kept in the same table on purpose:
#:
#: * boundary-pin cells (``old-*`` / ``new-*``) pin the exact releases either
#:   side of a known behavior change (workshop 9.3.1a2 last-suffixed-only vs
#:   9.3.2a1 first-canonical; padatious 2.0.0a1 last-no-fold vs 2.0.1a1
#:   first-fold). They document WHERE the line is and fail as wrong-vintage if
#:   a release ever moves it.
#: * channel cells (``stable-*`` / ``testing-*``) pin whatever the OVOS distro
#:   constraint files resolve *today* (fetched fresh in build_venvs.sh, never
#:   vendored), so they verify the fleet reality rather than a boundary. As of
#:   this writing both constraints-stable.txt and constraints-testing.txt
#:   floor ovos-workshop and ovos-padatious well below the canonicalization
#:   boundaries above (stable: workshop>=3.4.0,<3.5.0, padatious>=1.4.2,<1.5.0;
#:   testing: workshop>=7.0.6,<8.0.0, padatious>=1.4.3,<2.0.0), so both
#:   channels behave like the "old" boundary side on both axes. A distro pin
#:   bump past a boundary flips the affected channel cell red at the moment it
#:   happens — that is the alarm this design exists for.
COMBOS = {
    # combo id                skill binds suffixed only, core canonicalizes, fires
    "old-skill/old-core":     (True, False, True),
    "old-skill/new-core":     (True, True, False),
    "new-skill/old-core":     (False, False, True),
    "new-skill/new-core":     (False, True, True),
    # T2.5 -- the M axis crossed against C. Every column below is what the
    # real-symbol probes ACTUALLY returned when these venvs were first
    # built and run (design §2.5's probe discipline; the values were read
    # off `core_canonicalizes()` and `skill.bound_topics` per venv, not
    # copied out of the design doc):
    #
    #   venv_core_new_matchers_old  ovos-core 2.6.3a1 + padatious 2.0.0a1
    #                               -> core_canonicalizes() False
    #   venv_core_old_matchers_new  ovos-core 2.5.5a2 + padatious 2.0.1a2
    #                               -> core_canonicalizes() True
    #
    # i.e. the fold really does live in the matcher package and not in
    # ovos-core -- an old core WILL dispatch canonically if the deployer
    # installed a current padatious, and a current core will NOT if they
    # did not. That is the whole reason M is its own axis.
    "old-skill/new-core-old-matchers":  (True, False, True),
    "new-skill/new-core-old-matchers":  (False, False, True),
    # Cold-Mnew: design §2.2's "canonical dispatch from an *old* core;
    # currently untested". The old-skill half reproduces the #271 gap with
    # ovos-core held at the OLD pin, which pins the blame on padatious.
    "old-skill/old-core-new-matchers":  (True, True, False),
    "new-skill/old-core-new-matchers":  (False, True, True),
    # skew sub-cells: adapt new, padatious old, on a current core. The
    # dispatch spelling must still follow padatious -- see
    # test_matcher_skew_leaves_the_dispatch_spelling_to_padatious.
    "old-skill/new-core-padatious-old-adapt-new": (True, False, True),
    "new-skill/new-core-padatious-old-adapt-new": (False, False, True),
    # channel cells: skill or core side installed per a live distro
    # constraints file, the other side at dev. See build_venvs.sh.
    "stable-skill/dev-core":  (True, True, False),
    "dev-skill/stable-core":  (False, False, True),
    "testing-skill/dev-core": (True, True, False),
    "dev-skill/testing-core": (False, False, True),
}

#: T2.2: the four boundary combo names above are now aliases resolving to a
#: 4-tuple cell (``cells.BOUNDARY_ALIASES``, design §2.5); this asserts the
#: alias table and this dict never drift apart, since ``BOUNDARY_ALIASES``
#: is what ``BACKCOMPAT_COMBO``, the axis-pruning conftest hook, and the CI
#: matrix all resolve through. Checked at import time so a typo in either
#: table is a collection-time failure, not a silent mismatch.
assert set(BOUNDARY_ALIASES) == {c for c in COMBOS if c not in CHANNEL_CELLS}
#: Channel cells stay a separate tier (design §2.5) -- not resolved to a
#: 4-tuple cell, not axis-pruned. This asserts every channel combo COMBOS
#: knows about is one ``cells.py`` also recognizes.
assert CHANNEL_CELLS == {c for c in COMBOS if c in CHANNEL_CELLS}

#: Adversarial-review finding: the two asserts above only ever compared
#: KEY sets, so a value drift -- e.g. flipping new-skill/old-core's M axis
#: to "new" in cells.py -- would pass silently. COMBOS' own columns ARE
#: the S and M axes verified against real symbols: column 0
#: (``want_suffixed_only``) is exactly what ``skill.bound_topics`` probes
#: for the S axis, and column 1 (``want_canon``) is exactly what
#: ``core_canonicalizes()`` probes for the M axis (that probe lives in the
#: padatious pipeline plugin, the M-axis package -- see
#: ``core_canonicalizes``'s own docstring). So the S/M vintage a cell
#: claims must match those columns, checked here per-alias, at import
#: time.
for _combo, _cell in BOUNDARY_ALIASES.items():
    _want_suffixed_only, _want_canon, _ = COMBOS[_combo]
    _values = axis_values(_cell)
    _want_S = OTHER if _want_suffixed_only else REFERENCE
    assert _values["S"] == _want_S, (
        f"{_combo!r}: COMBOS says want_suffixed_only={_want_suffixed_only} "
        f"(S={_want_S!r}), but cells.py's alias {_cell!r} pins S="
        f"{_values['S']!r}")
    _want_M = REFERENCE if _want_canon else OTHER
    assert _values["M"] == _want_M, (
        f"{_combo!r}: COMBOS says want_canon={_want_canon} (M={_want_M!r})"
        f", but cells.py's alias {_cell!r} pins M={_values['M']!r}")
del _combo, _cell, _want_suffixed_only, _want_canon, _values, _want_S, _want_M

#: Combos expected to fail today because the skill side is suffixed-only and
#: the core side canonicalizes — the same gap ``old-skill/new-core`` marks,
#: reached via a distro constraints pin instead of a boundary pin.
_BROKEN_CHANNEL_COMBOS = {"stable-skill/dev-core", "testing-skill/dev-core"}

COMBO = os.environ.get("BACKCOMPAT_COMBO", "")
SKILL_PYTHON = os.environ.get("BACKCOMPAT_SKILL_PYTHON", "")

pytestmark = pytest.mark.skipif(
    not COMBO or not SKILL_PYTHON,
    reason="mixed-version matrix needs BACKCOMPAT_COMBO and "
           "BACKCOMPAT_SKILL_PYTHON; see test/backcompat/build_venvs.sh")

#: True in every cell the compat train has to repair. DERIVED from COMBOS'
#: own columns rather than a hand-kept name list (T2.5): the gap is
#: definitionally "the skill bound the suffixed topic only AND the matcher
#: side canonicalizes, so the dispatch never reaches a bound handler", which
#: is exactly the (want_suffixed_only, want_canon, fires) shape below.
#:
#: This reproduces the previous hard-coded list exactly -- old-skill/new-core
#: and the two broken channel combos are precisely the entries with that
#: shape -- and it is what lets T2.5's new M-crossed cells classify
#: themselves. A hand-kept list would have silently left the new
#: `old-skill/old-core-new-matchers` cell unmarked, i.e. reported a KNOWN gap
#: as a fresh failure.
#:
#: ``.get`` rather than ``[]``: this module is imported (and this line
#: evaluated) even with no BACKCOMPAT_COMBO set, where the pytestmark skipif
#: above is what actually stops the run. The default is the "nothing broken"
#: shape so an unset combo never claims a gap.
IS_BROKEN_CELL = COMBOS.get(COMBO, (False, False, True)) == (True, True, False)

_XFAIL_REASON = (
    "old skill container (ovos-workshop==9.3.1a2, suffixed binding only) does "
    "not hear a canonical dispatch; needs the #271 bridge (wire twin from the "
    "emitter, or local canonicalization in a modern client), unreleased. XPASS here means #271 shipped — drop "
    "this marker and keep the guard."
    if COMBO not in _BROKEN_CHANNEL_COMBOS else
    f"{COMBO}: the OVOS distro constraints file pins an ovos-workshop below "
    "the 9.3.2a1 canonical-binding boundary, so this channel's skill side is "
    "suffixed-only against a dev core that canonicalizes at registration; "
    "same gap as old-skill/new-core, reached via a live fleet pin instead of "
    "a boundary pin. XPASS here means either the channel moved its pin past "
    "the boundary or #271 shipped — check which, then drop the marker.")


@pytest.fixture(scope="module")
def stack():
    """One bus and one skill process, shared by the read-only observations."""
    if COMBO not in COMBOS:
        pytest.fail(f"unknown BACKCOMPAT_COMBO {COMBO!r}; "
                    f"expected one of {sorted(COMBOS)}")
    server = BusServer()
    skill = None
    try:
        bus = server.client()
        # Capture registration before the skill exists, so the name the core
        # side would key its engine entry on is observed, never assumed.
        registrations = Capture(bus, "padatious:register_intent")
        skill = SkillProcess(SKILL_PYTHON, server.xdg)
        registrations.wait(30)
        yield server, bus, skill, registrations
    finally:
        if skill is not None:
            skill.stop()
        server.stop()


def _registered_name(registrations) -> str:
    names = [m.data.get("name") for m in registrations.messages
             if str(m.data.get("name", "")).startswith(f"{SKILL_ID}:")]
    assert names, ("the skill never registered an intent with the padatious "
                   "contract; nothing to dispatch")
    return names[0]


@pytest.fixture(scope="module")
def converse_service(stack):
    """The real, per-combo ``ConverseService`` from ``driver.
    make_converse_service``, running on the shared bus for the module's
    converse/get_response tests.

    A separate fixture (not folded into ``stack``) so the plain
    intent-dispatch tests above don't pay for it and aren't coupled to it —
    only the interactive-flow tests below ask for this.

    Skips (own reason, never the #271 marker) when this core venv's
    ``ConverseService`` predates the plugin-pipeline ``.match()`` API this
    module's helpers are built on — real today only for the "stable"
    distro channel's ``ovos-core==1.3.1`` pin. See
    ``driver.core_has_pipeline_match_api``.
    """
    if not core_has_pipeline_match_api():
        pytest.skip(
            f"{COMBO}: this core venv's ConverseService predates the "
            f"plugin-pipeline .match() API (pre ovos-core pipeline "
            f"refactor) — converse/get_response routing here uses a "
            f"different, older object model this suite does not adapt to "
            f"yet; unrelated to the #271 canonical-topic gap")
    _server, bus, _skill, _regs = stack
    service = make_converse_service(bus)
    try:
        yield service
    finally:
        service.shutdown()


def test_pins_are_the_intended_vintage(stack):
    """Fail loudly if either side is not the version this combo assumes.

    Without this, a workshop release that quietly changes what it binds would
    turn the broken cell green and be read as "the compat train landed".
    """
    _server, _bus, skill, _regs = stack
    want_suffixed_only, want_canon, _ = COMBOS[COMBO]

    suffixed_only = skill.bound_topics == [LEGACY_TOPIC]
    assert suffixed_only == want_suffixed_only, (
        f"{COMBO}: expected suffixed-only binding={want_suffixed_only}, but "
        f"the skill venv bound {skill.bound_topics}")
    if not want_suffixed_only:
        assert CANONICAL_TOPIC in skill.bound_topics
    assert core_canonicalizes() == want_canon, (
        f"{COMBO}: expected the core venv to canonicalize at registration="
        f"{want_canon}, got {core_canonicalizes()}")

    # M/adapt axis (design §2.5). T2.5 promoted this from "recorded" to
    # "asserted wherever a venv actually pins ovos-adapt-parser", which is
    # now the *-new-matchers cells and the skew sub-cells (see
    # cells.adapt_vintage). Combos that pin no adapt at all still only
    # record it -- but they assert the probe returns None, so a probe that
    # silently started answering True/False on a venv with no adapt
    # installed is a loud failure rather than an invisible one.
    adapt_probe = adapt_consumes_intent4_keywords()
    want_adapt = adapt_vintage(COMBO)
    print(f"{COMBO}: M/adapt probe "
          f"(INTENT_REGISTER_KEYWORD consumer)={adapt_probe}, cell pins "
          f"adapt={want_adapt}")
    if want_adapt is None:
        assert adapt_probe is None, (
            f"{COMBO}: this cell's venv pins no ovos-adapt-parser, but the "
            f"INTENT_REGISTER_KEYWORD probe returned {adapt_probe!r} "
            f"instead of None -- either adapt arrived as a transitive "
            f"dependency (which would make this cell's M axis a half-truth) "
            f"or the probe stopped distinguishing 'absent' from 'old'")
    else:
        # Only the REFERENCE (>=1.4.0a1) adapt vintage is reachable at all
        # -- 1.3.4a1 caps ovos-spec-tools below every core pin, so no venv
        # can install it (see cells.py / build_venvs.sh). Asserting the
        # vintage here rather than just the probe's truthiness keeps this
        # honest if that ever changes.
        assert want_adapt == REFERENCE, (
            f"{COMBO}: cells.adapt_vintage says {want_adapt!r}, but no "
            f"old-vintage ovos-adapt-parser resolves against any core pin "
            f"this suite builds -- build_venvs.sh cannot have produced this "
            f"venv")
        assert adapt_probe is True, (
            f"{COMBO}: this cell pins ovos-adapt-parser>=1.4.0a1, whose "
            f"keyword engine is supposed to consume SpecMessage."
            f"INTENT_REGISTER_KEYWORD, but the real-symbol probe returned "
            f"{adapt_probe!r}. None means adapt (or ovos-spec-tools' "
            f"INTENT_REGISTER_KEYWORD) is missing from this venv entirely; "
            f"False means the INTENT-4 boundary moved and the pin no longer "
            f"straddles it")

    # A/audio axis (design §2.6): the simulator lands in T2.3, not here.
    # The probe is wired but always returns None today; asserting that
    # keeps this file honest about not having invented the axis, and turns
    # into a loud collection-time signal if someone half-wires it without
    # also wiring a real assertion.
    audio_probe = audio_output_end_topic_probe()
    assert audio_probe is None, (
        f"{COMBO}: audio_output_end_topic_probe() returned {audio_probe!r} "
        f"instead of None -- the A axis is not backed by a real audio "
        f"simulator in this file yet (T2.3); either this was wired early "
        f"(add a real assertion here too) or the probe changed by mistake")


#: Channel cells pin the whole stack from a distro constraints file, which
#: caps ovos-bus-client too — unlike the boundary cells, where only
#: ovos-workshop is pinned and its dependency floor is left to resolve
#: whatever is current. The "frozen container still gets a modern client"
#: assumption below is therefore a boundary-cell property, not a channel-cell
#: one, and asserting it on a channel combo would just report a real fleet
#: fact (the channel's own bus-client ceiling) as if it were a broken
#: assumption.
_CHANNEL_COMBOS = {"stable-skill/dev-core", "dev-skill/stable-core",
                    "testing-skill/dev-core", "dev-skill/testing-core"}


def test_old_container_resolves_a_current_bus_client(stack):
    """The repair strategy assumes the frozen container gets a modern client.

    ``ovos-workshop``'s dependency floor is a lower bound, so even a pinned
    old workshop resolves today's ``ovos-bus-client``. If that ever stopped
    being true, only the emitter-side wire twin of ``#271`` could reach it — so the
    resolution is asserted, not assumed, and the cell documents which
    rule it exercises.

    Channel combos are exempted from the assertion (not skipped outright,
    so the version is still recorded): a distro constraints file pins
    ovos-bus-client alongside everything else, so a low client version there
    is the fleet's own ceiling, not evidence the repair design is broken. A
    real stable/testing-channel container would need a bus-client bump on top
    of a workshop bump to receive the #271 fix; that is a fleet-inventory
    finding for the maintainers, not a compat-design failure.
    """
    _server, _bus, skill, _regs = stack
    client = skill.versions.get("ovos_bus_client", "")
    assert client, f"the skill venv did not report its versions:\n{skill.log}"
    if COMBO not in _CHANNEL_COMBOS:
        assert int(client.split(".")[0]) >= 2, (
            f"the skill venv resolved ovos-bus-client {client}; the "
            f"this cell exercises #271's local canonicalization rule, which "
            f"needs a modern client in the skill process")
    elif int(client.split(".")[0]) < 2:
        print(f"{COMBO}: channel bus-client ceiling is {client} (<2), below "
              f"where #271 would land; this channel needs a bus-client bump "
              f"too, not just a workshop bump, to receive the compat fix")

    # Recorded, not asserted: this is the switch the xfail above waits for.
    # When it turns True the broken cell starts passing and strict xfail
    # converts that into the loud signal to promote the guard.
    print(f"{COMBO}: skill venv = ovos-workshop "
          f"{skill.versions.get('ovos_workshop')}, ovos-bus-client {client}, "
          f"#271 mirror present (skill-side, receive-side probe)="
          f"{skill.versions.get('has_reemit_hook')}")

    # Emitter-side probe: the twin actually fires from whichever process
    # calls emit() for the canonical dispatch, which in this suite is the
    # driver/core side, not the skill subprocess. Additive to the
    # skill-side probe above, not a replacement for it.
    print(f"{COMBO}: #271 mirror present (driver-side, emitter-side probe)="
          f"{emitter_side_has_reemit_hook()}")


def test_core_dispatches_the_topic_this_combo_expects(stack):
    """Positive control on the core half, independent of any handler.

    Proves the dispatch really went out and with which spelling, so a silent
    handler in the broken cell can only mean the handler never heard it.
    """
    _server, bus, _skill, regs = stack
    topic = dispatch_topic_for(_registered_name(regs))
    want = CANONICAL_TOPIC if core_canonicalizes() else LEGACY_TOPIC
    assert topic == want

    seen = Capture(bus, topic)
    try:
        dispatch(bus, topic, food="tacos")
        assert seen.wait(), f"the dispatch on {topic!r} never reached the bus"
    finally:
        seen.close()


def test_the_handler_binding_matches_the_probed_dispatch_topic(stack):
    """Derived from the real probes, not the ``COMBOS`` table's static
    "fires" column: whether the topic this cell's core will actually
    dispatch (``dispatch_topic_for``, itself probe-derived) is one the
    skill actually bound (``skill.bound_topics``, probed from the live
    subprocess).

    This is the T2.2 item 5 truth-fix: the ``new-skill/old-core`` COMBOS
    entry says ``fires=True`` today, correct as of #500 being unmerged
    (ovos-workshop still binds both spellings). The day
    ovos-workshop#500 lands and removes the suffixed binding, this
    assertion flips to catching that automatically -- ``dispatch_topic_for``
    for an old core still returns the suffixed name (padatious hasn't
    changed), ``skill.bound_topics`` on a post-#500 skill no longer
    contains it, so ``reaches`` goes False here without anyone touching
    this test. If that happens, the fix is to update the stale COMBOS
    entry (and IS_BROKEN_CELL / the xfail reason above it) to match --
    this test failing IS the signal to do that, not a bug to silence.
    """
    _server, _bus, skill, regs = stack
    topic = dispatch_topic_for(_registered_name(regs))
    reaches = topic in skill.bound_topics
    _want_suffixed_only, _want_canon, want_fires = COMBOS[COMBO]
    assert reaches == want_fires, (
        f"{COMBO}: COMBOS says fires={want_fires}, but the probe-derived "
        f"check says {reaches} (dispatch topic {topic!r}, skill bound "
        f"{skill.bound_topics}). If ovos-workshop#500 landed (removing the "
        f"suffixed binding) or the padatious fold changed, the COMBOS "
        f"entry for {COMBO!r} is stale and must be updated to match -- see "
        f"this test's docstring, the #500 hazard it names.")


# ---------------------------------------------------------------------------
# Matcher axis (M): scenario 1 (registration/dispatch), design §2.4 row 1
# ---------------------------------------------------------------------------
#
# T2.5. These live in this file rather than a new one on purpose: they are
# scenario-1 tests, they need the SAME module-scoped `stack` fixture (one bus,
# one skill subprocess) the other scenario-1 tests already share, and a second
# file would either duplicate that fixture -- doubling the subprocess cost of
# every cell -- or import it across modules for no gain. The M axis is a new
# column in an existing scenario, not a new scenario.


def _cell_or_skip() -> str:
    """This cell's 4-tuple id, or skip if the combo has none.

    Channel combos deliberately live outside the 4-tuple space (design §2.5):
    they pin a whole stack from a live distro constraints file, so there is no
    per-axis vintage to check a probe against. Skipping with that reason is
    honest; asserting an axis they do not have would not be.
    """
    cell = resolve_cell(COMBO)
    if cell is None:
        pytest.skip(
            f"{COMBO}: channel-tier combo, not part of the 4-tuple axis "
            f"space (design §2.5) -- no M vintage to check a probe against")
    return cell


@pytest.mark.axes("S", "C", "M")
def test_dispatch_spelling_tracks_the_matcher_axis_not_the_core_axis(stack):
    """The dispatch spelling is decided by the MATCHER vintage (M), not by
    the ovos-core vintage (C).

    This is the assertion the whole M axis exists to make, and until T2.5 no
    cell could make it: every core venv welded its padatious pin to its
    ovos-core pin, so M and C were always equal and "the fold lives in
    padatious" was an unfalsifiable claim in a docstring. The four
    ``*-matchers`` cells break that weld, and on them M != C, so a mutant
    that sourced the spelling from ovos-core instead of from the matcher
    plugin fails here while still passing on all four original aliases.

    Both halves are probe-derived, never read off the design doc:
    ``core_canonicalizes()`` reads ``ovos_padatious.opm._dealias_intent_name``
    out of the live venv, and ``dispatch_topic_for`` derives the topic from
    the name the skill subprocess REALLY registered on the wire.

    Observed when the M venvs were first built (recorded so a future drift
    reads as drift): ovos-core 2.6.3a1 + ovos-padatious 2.0.0a1 does NOT
    canonicalize, ovos-core 2.5.5a2 + ovos-padatious 2.0.1a2 DOES.
    """
    cell = _cell_or_skip()
    _server, _bus, _skill, regs = stack
    values = axis_values(cell)
    m_is_new = values["M"] == REFERENCE

    assert core_canonicalizes() is m_is_new, (
        f"{COMBO} (cell {cell}): the registration-time fold is a property of "
        f"the MATCHER package, so it must follow this cell's M axis "
        f"({values['M']}), but core_canonicalizes() returned "
        f"{core_canonicalizes()}. C is {values['C']} here -- if the probe "
        f"followed C instead, the fold does not live where this matrix says "
        f"it does and the M axis is mislabelled.")

    topic = dispatch_topic_for(_registered_name(regs))
    want = CANONICAL_TOPIC if m_is_new else LEGACY_TOPIC
    assert topic == want, (
        f"{COMBO} (cell {cell}): M={values['M']} so the dispatch topic must "
        f"be {want!r}, got {topic!r}")

    if values["C"] != values["M"]:
        # The falsifying case. Spelled out separately so the failure message
        # names the mutation it caught rather than leaving a reader to work
        # out why an M!=C cell matters.
        c_would_want = CANONICAL_TOPIC if values["C"] == REFERENCE else LEGACY_TOPIC
        assert topic != c_would_want, (
            f"{COMBO} (cell {cell}): M={values['M']} but C={values['C']}, "
            f"and the dispatch topic came out as {topic!r} -- exactly what "
            f"the CORE vintage would predict, not what the MATCHER vintage "
            f"predicts. Either ovos-core stopped forwarding "
            f"match.match_type verbatim, or the fold moved out of "
            f"ovos-padatious into ovos-core. Both would make M and C the "
            f"same axis again.")


@pytest.mark.axes("S", "C", "M")
def test_matcher_skew_leaves_the_dispatch_spelling_to_padatious(stack):
    """design §2.2's skew sub-cell contract: with the two matcher plugins at
    OPPOSITE vintages, registration/dispatch spelling follows ovos-padatious
    and is untouched by ovos-adapt-parser.

    Only the padatious-old/adapt-new direction exists -- the inverse does not
    resolve against any core pin this suite builds (see ``cells.py``'s skew
    note for uv's verbatim refusal), so it is not built and not claimed.

    What this pins that the test above does not: the two probes are
    independent. A mutant that made ``core_canonicalizes()`` answer from the
    ADAPT package (or from "any modern matcher is installed") would read True
    here -- adapt is at its new vintage -- while padatious is old and the
    wire really is suffixed, so this fails.
    """
    if COMBO not in MATCHER_SKEW:
        pytest.skip(f"{COMBO} is not a matcher-skew sub-cell "
                    f"(design §2.2); nothing skewed to observe")
    _server, _bus, _skill, regs = stack

    assert adapt_consumes_intent4_keywords() is True, (
        f"{COMBO}: a skew sub-cell must have the NEW ovos-adapt-parser "
        f"installed for the skew to exist at all")
    assert core_canonicalizes() is False, (
        f"{COMBO}: a skew sub-cell pins ovos-padatious==2.0.0a1, which "
        f"predates the registration-time fold, so core_canonicalizes() must "
        f"be False. It returned True -- the skew is not actually skewed, or "
        f"the probe is reading the wrong package.")
    topic = dispatch_topic_for(_registered_name(regs))
    assert topic == LEGACY_TOPIC, (
        f"{COMBO}: with a NEW adapt and an OLD padatious the dispatch must "
        f"still be the suffixed {LEGACY_TOPIC!r}, got {topic!r} -- the adapt "
        f"vintage is changing the padatious dispatch spelling, which design "
        f"§2.2 says it cannot")


@pytest.mark.axes("S", "C", "M")
def test_the_skill_handler_runs(stack):
    """The contract: a canonical dispatch must reach the skill's handler.

    Emitted exactly the way ``IntentService._dispatch_match`` does — the
    matched topic, forwarded with the utterance data — and observed through
    the marker the skill emits from inside the handler.
    """
    _server, bus, skill, regs = stack
    topic = dispatch_topic_for(_registered_name(regs))

    token = uuid.uuid4().hex
    handled = Capture(bus, "backcompat.skill.handled", token=token)
    spoken = Capture(bus, "speak")
    try:
        bus.emit(Message(topic, {"food": "tacos", "token": token},
                         {"session": {"session_id": "backcompat"}}))
        assert handled.wait(), (
            f"{COMBO}: dispatched {topic!r} but the skill handler never ran.\n"
            f"the skill venv bound: {skill.bound_topics}\n"
            f"skill process log:\n{skill.log}")
        assert handled.messages[0].data["topic"] in (topic, LEGACY_TOPIC)
        assert handled.messages[0].data["data"]["food"] == "tacos"
        # ovos-core on the stable/testing channels is old enough (<=2.1.x)
        # that its dialog/TTS plumbing around a bare ``self.speak()`` differs
        # from what this minimal harness sets up for the "new" core checkout,
        # independently of the intent-topic aliasing this suite exists to
        # test. The handler firing (asserted above) is the compat-relevant
        # fact; whether it also spoke is a realism check that only applies
        # where the core side is current.
        if "-core" not in COMBO or not COMBO.endswith(("stable-core",
                                                        "testing-core")):
            assert spoken.wait(), "the handler ran but never spoke"
    finally:
        handled.close()
        spoken.close()


@pytest.mark.axes("S", "C", "M")
def test_the_handler_runs_exactly_once(stack):
    """A skill bound to both spellings must not answer twice.

    ``new skill/new core`` is where this bites: the skill binds the canonical
    and the suffixed topic, so once the compat mirror of ``#271`` is live the
    same dispatch could reach the same handler down two paths. One utterance,
    one answer.
    """
    _server, bus, skill, regs = stack
    topic = dispatch_topic_for(_registered_name(regs))

    token = uuid.uuid4().hex
    handled = Capture(bus, "backcompat.skill.handled", token=token)
    try:
        bus.emit(Message(topic, {"food": "burritos", "token": token},
                         {"session": {"session_id": "backcompat-once"}}))
        assert handled.wait(), f"{COMBO}: handler never ran for {topic!r}"
        # Keep listening past the first hit for a duplicate, but exit the moment
        # a second dispatch lands: a real double-fire fails fast instead of
        # sleeping out a fixed window, and only the passing case waits the full
        # DUPLICATE_WINDOW deadline (a documented upper bound on how late a
        # duplicate could arrive over the real bus).
        DUPLICATE_WINDOW = 3.0
        handled.wait_for_count(2, timeout=DUPLICATE_WINDOW)
        assert len(handled.messages) == 1, (
            f"{COMBO}: one dispatch on {topic!r} produced "
            f"{len(handled.messages)} handler runs "
            f"(skill bound {skill.bound_topics})")
    finally:
        handled.close()


#: The interactive-flow tests below are NOT marked with the IS_BROKEN_CELL
#: xfail. That marker exists for one specific gap: an old skill binds the
#: suffixed `<skill_id>:<file>.intent` topic only, and a canonicalizing core
#: dispatches `<skill_id>:<file>` only, so registered-intent names never line
#: up. converse and get_response are routed through the real, per-combo
#: `ovos_core.intent_services.converse_service.ConverseService` (see the
#: `converse_service` fixture / `driver.make_converse_service`) — genuine
#: core-side code decides the match, the driver only forwards
#: `match.match_type` verbatim, same as `dispatch()` already does for
#: intents. That match_type is a FIXED literal
#: (`<skill_id>.converse.request` / `<skill_id>.converse.get_response`) in
#: every venv this suite builds, never derived from a registered intent
#: name, so it never touches padatious's registration-time canonicalization.
#: wait_while_speaking is legitimately audio-service territory — there is no
#: core-side code to route it through — and stays a direct simulation of
#: `recognizer_loop:audio_output_end`, also a fixed literal, also unchanged
#: across every venv checked (including the "stable" distro channel's
#: ovos-bus-client==1.3.8a4). There is no boundary pin on any of these three
#: flows, so nothing here should need the same kill switch; if a real gap
#: ever does show up on one of them, give it its own xfail with its own
#: reason instead of folding it into this one (see module docstring: "any PR
#: that drops the compat must flip these deliberately" — a borrowed marker
#: would hide the wrong signal).


def _require_converse_api(skill) -> None:
    """Skip with an honest, own reason if this vintage genuinely has no
    converse/get_response call surface at all — NOT the #271 xfail marker,
    which is about a completely different gap (suffixed vs canonical intent
    topics). Every vintage this suite currently builds against (9.3.1a2,
    dev, and both the "stable" and "testing" distro channel pins) reports
    ``has_converse_api: true`` — see ``skill_process.py``'s ``VERSIONS``
    line — so this is a safety net for a vintage nobody has pinned yet, not
    a marker anyone should expect to see flip today.
    """
    if not skill.versions.get("has_converse_api", True):
        pytest.skip(
            f"{COMBO}: ovos-workshop {skill.versions.get('ovos_workshop')} "
            f"has no converse/get_response machinery on either "
            f"ConversationalSkill or plain OVOSSkill — unrelated to the "
            f"#271 canonical-topic gap, this vintage simply predates the "
            f"call surface these tests exercise")


@pytest.mark.axes("S", "C")
def test_converse_fires_before_a_followup_utterance_matches_an_intent(
        stack, converse_service):
    """An activated skill's converse() must be offered a follow-up utterance
    ahead of intent matching.

    This is the multi-turn-dialog contract every bus-only skill container
    leans on: ``activate()`` puts the skill on the active list, and the
    pipeline is supposed to try ``converse()`` before falling through to
    intent matching. Genuinely cross-version this time: the driver calls the
    real, per-combo ``ConverseService.match()`` (see ``converse_service``
    fixture / ``driver.make_converse_service``) to decide whether and how to
    route the follow-up utterance, then forwards ``match.match_type``
    verbatim — the same shortcut ``dispatch()`` already takes for the
    food-order intent, except the topic now comes from real core code
    instead of a constant the driver assumes.
    """
    _server, bus, skill, _regs = stack
    _require_converse_api(skill)
    token = uuid.uuid4().hex
    session_id = f"backcompat-converse-{token[:8]}"
    activated = Capture(bus, ACTIVATED_TOPIC, token=token)
    # the real second hop: ConverseService.handle_converse (triggered by
    # dispatch_match below) re-emits to this exact skill-facing topic —
    # capturing it independently of the "converse_fired" marker proves the
    # WIRE contract, not just that the skill's converse() method ran.
    requested = Capture(bus, CONVERSE_REQUEST_TOPIC)
    fired = Capture(bus, CONVERSE_FIRED_TOPIC)
    responded = Capture(bus, CONVERSE_RESPONSE_TOPIC)
    try:
        # self.activate() (real workshop code, either vintage) emits the
        # real "intent.service.skills.activate" message, which the real
        # converse_service.handle_activate_skill_request (bound in its
        # __init__) puts the skill on SessionManager's live active-skills
        # list for this session_id.
        bus.emit(Message(CONVERSE_TRIGGER_TOPIC, {"token": token},
                         session_context(session_id)))
        assert activated.wait(), (
            f"{COMBO}: skill never confirmed activation:\n{skill.log}")
        # activate_skill_request is itself async over the wire (our own
        # "activated" marker races the real core-side session update it
        # rides alongside); wait for the actual evidence — the skill_id
        # showing up on the live session — rather than guessing a delay.
        assert wait_for_active_skill(session_id, SKILL_ID), (
            f"{COMBO}: skill confirmed activation but never showed up on "
            f"the live session's active-skill list")

        match = converse_match(converse_service, ["i changed my mind"],
                               "en-us", session_id)
        assert match is not None, (
            f"{COMBO}: ConverseService.match() found no active skill to "
            f"converse with — activation never reached the real core-side "
            f"session state.\nskill process log:\n{skill.log}")
        assert match.match_type == CONVERSE_MATCH_TOPIC, (
            f"{COMBO}: real ConverseService.match() picked "
            f"{match.match_type!r}, not the expected {CONVERSE_MATCH_TOPIC!r}")
        dispatch_match(bus, match)

        assert requested.wait(), (
            f"{COMBO}: real ConverseService.handle_converse never re-emitted "
            f"onto {CONVERSE_REQUEST_TOPIC!r} — the skill-facing wire hop "
            f"itself never fired, not just the marker.")
        assert fired.wait(), (
            f"{COMBO}: an activated skill's converse() was never reached by "
            f"a follow-up utterance routed through the real converse "
            f"service — a real skill container would silently lose "
            f"multi-turn dialog on this core.\nskill process log:\n"
            f"{skill.log}")
        assert fired.messages[0].data["utterances"] == ["i changed my mind"]

        assert responded.wait(), (
            f"{COMBO}: converse() ran but the skill never answered "
            f"{CONVERSE_RESPONSE_TOPIC!r}")
        assert responded.messages[0].data["result"] is True, (
            "converse() claimed the utterance (returned True) but the "
            "pipeline-facing response says it did not consume it")
    finally:
        activated.close()
        requested.close()
        fired.close()
        responded.close()


@pytest.mark.axes("S", "C")
def test_get_response_receives_the_answer_utterance(stack, converse_service):
    """A handler blocked in ``get_response()`` must unblock on the answer,
    delivered through the real core-side response-mode match.

    ``OVOSSkill.get_response`` enables response-mode over the real
    ``skill.converse.get_response.enable`` topic, which the real
    ``ConverseService.handle_get_response_enable`` uses to flip
    ``session.utterance_states[skill_id]`` — genuine per-version core state,
    not something the driver sets by hand. The driver then calls the real
    ``ConverseService.match()`` with the answer utterance, gets back
    ``match_type == f"{skill_id}.converse.get_response"`` from that real
    state, and forwards it verbatim, same as the converse test above.

    ``ConverseService.match()`` only considers a skill for
    response-mode if it is ALSO on the session's active-skill list
    (``_collect_converse_skills`` / ``get_active_skills`` gate — see
    ``match()``'s ``gr_skills`` computation) — in a real deployment this is
    implicit, since ``get_response`` is normally called from inside a
    handler for an intent that was just dispatched to this skill, which
    activates it as a side effect. This harness has no intent-dispatch
    pipeline standing that context up, so the skill is activated explicitly
    first, the same way the converse test above does.
    """
    _server, bus, skill, _regs = stack
    _require_converse_api(skill)
    token = uuid.uuid4().hex
    session_id = f"backcompat-getresp-{token[:8]}"
    activated = Capture(bus, ACTIVATED_TOPIC, token=token)
    done = Capture(bus, GET_RESPONSE_DONE_TOPIC, token=token)
    try:
        bus.emit(Message(CONVERSE_TRIGGER_TOPIC, {"token": token},
                         session_context(session_id)))
        assert activated.wait(), (
            f"{COMBO}: skill never confirmed activation:\n{skill.log}")
        assert wait_for_active_skill(session_id, SKILL_ID), (
            f"{COMBO}: skill confirmed activation but never showed up on "
            f"the live session's active-skill list")

        bus.emit(Message(GET_RESPONSE_TRIGGER_TOPIC, {"token": token},
                         session_context(session_id)))
        # get_response's real "skill.converse.get_response.enable" round
        # trip is async over the wire; wait for the actual evidence — the
        # live session's response-mode holder — rather than guessing a
        # delay long enough.
        assert wait_for_response_mode(session_id, SKILL_ID), (
            f"{COMBO}: get_response() never showed up as the live "
            f"session's response-mode holder\nskill process log:\n{skill.log}")

        match = converse_match(converse_service, ["tacos please"], "en-us",
                               session_id)
        assert match is not None, (
            f"{COMBO}: ConverseService.match() found no skill in "
            f"response-mode — get_response's enable call never reached "
            f"real core-side session state.\nskill process log:\n{skill.log}")
        assert match.match_type == GET_RESPONSE_ANSWER_TOPIC, (
            f"{COMBO}: real ConverseService.match() picked "
            f"{match.match_type!r}, not the expected "
            f"{GET_RESPONSE_ANSWER_TOPIC!r}")
        dispatch_match(bus, match)

        assert done.wait(), (
            f"{COMBO}: get_response() never returned after the real "
            f"converse-service match landed.\nskill process log:\n{skill.log}")
        assert done.messages[0].data["answer"] == "tacos please", (
            f"{COMBO}: get_response() returned "
            f"{done.messages[0].data['answer']!r} instead of the answer "
            f"utterance sent")
    finally:
        activated.close()
        done.close()


@pytest.mark.axes("S", "C", "A")
def test_get_response_completes_without_hanging_when_unanswered(stack):
    """The no-answer path must complete, not hang, within a generous bound.

    This is a plain no-hang smoke test, not a boundedness proof for any
    specific historical fix: ``get_response``'s internal poll loop
    (``__get_response``) has always been bounded by
    ``skills.get_response_timeout`` — pinned low here (see
    :data:`driver.GET_RESPONSE_TIMEOUT` / ``make_shared_config``) so this
    stays fast — regardless of the separate killable-thread stall that
    ovos-workshop 9.3.5a1 fixed for the *external abort* path
    (``mycroft.skills.abort_question`` / ``_handle_killed_wait_response``),
    which this test does not exercise. No answer is ever sent here; this
    only proves the ordinary no-answer path returns.
    """
    _server, bus, skill, _regs = stack
    _require_converse_api(skill)
    token = uuid.uuid4().hex
    session = {"session_id": f"backcompat-getresp-timeout-{token[:8]}"}
    done = Capture(bus, GET_RESPONSE_DONE_TOPIC, token=token)
    try:
        start = time.monotonic()
        bus.emit(Message(GET_RESPONSE_TRIGGER_TOPIC, {"token": token},
                         {"session": session}))
        # A generous multiple of the pinned poll window, not the window
        # itself: proves the path completes promptly without turning a
        # slightly slow CI runner into a false "it hung" failure.
        assert done.wait(timeout=GET_RESPONSE_TIMEOUT * 4), (
            f"{COMBO}: get_response() never returned with no answer sent — "
            f"looks like a hang rather than a timeout.\nskill process log:\n"
            f"{skill.log}")
        elapsed = time.monotonic() - start
        # Lower bound: catches a "get_response was never actually called"
        # false green (e.g. an instant `answer = None` short-circuit) that
        # would otherwise sail through the upper-bound hang check above.
        assert elapsed >= GET_RESPONSE_TIMEOUT * 0.8, (
            f"{COMBO}: get_response() returned in {elapsed:.2f}s, well "
            f"under its {GET_RESPONSE_TIMEOUT}s poll window — looks like "
            f"it never actually ran the bounded no-answer path.\nskill "
            f"process log:\n{skill.log}")
        assert done.messages[0].data["answer"] is None, (
            f"{COMBO}: get_response() returned "
            f"{done.messages[0].data['answer']!r} with no answer ever sent")
    finally:
        done.close()


#: ovos-workshop#526: SessionManager.bus is never connected inside a
#: standalone skill container of this vintage, so speak(wait=True) silently
#: no-ops. Module-level so every A-axis speak-wait test that hits this SAME
#: upstream gap references the ONE string (design instruction: cells
#: failing for the identical upstream reason share one reason, not a
#: character-divergent copy) -- see test_speak_wait_bridges_from_spec_only_
#: audio below, the A=new sibling of the test this decorates.
_SPEAK_WAIT_526_XFAIL_REASON = (
    "product bug, not a fixture bug: SessionManager.bus is never "
    "connected inside a standalone skill container of this workshop "
    "vintage, so SessionManager.wait_while_speaking's own "
    "'if not cls.bus: return' guard fires immediately and "
    "speak(wait=True) silently no-ops instead of blocking. Confirmed "
    "live (cls.bus is None at wait_while_speaking entry) against "
    "ovos-workshop 9.3.9a1 / ovos-bus-client 2.7.3a1. The only real "
    "caller of SessionManager.connect_to_bus() is ovos-core's own "
    "IntentService, in the CORE process (ovos_core/intent_services/"
    "service.py, 'SessionManager.connect_to_bus(self.bus)' right "
    "after building the intent dispatcher) — that wires the CORE "
    "process's own SessionManager, not a separate skill container "
    "process's. Neither ovos_workshop.skill_launcher.SkillContainer "
    "(the real standalone-container launcher) nor OVOSSkill.__init__/"
    "bind/_startup (ovos_workshop/skills/ovos.py) ever calls it for "
    "the skill's own process. This is a real gap in every standalone "
    "skill container of this vintage, not something this test's "
    "fixture can or should paper over — see a follow-up ovos-workshop "
    "issue/PR. Strict so this flips to a loud XPASS failure the day "
    "that gap is closed upstream, which is the signal to remove this "
    "marker.")


@pytest.mark.xfail(strict=True, reason=_SPEAK_WAIT_526_XFAIL_REASON)
@pytest.mark.axes("S", "A")
def test_speak_wait_unblocks_on_audio_output_end(stack):
    """``speak(..., wait=True)`` must unblock once audio output ends.

    Exercises the receive side of whatever topic the CURRENT core emits for
    output-end against whatever the OLD workshop's ``wait_while_speaking``
    listens for. Both ``venv_skill_old`` and ``venv_skill_new`` resolve the
    same current ``ovos-bus-client`` off their workshop floor (the property
    ``test_old_container_resolves_a_current_bus_client`` already asserts),
    and that client's ``SessionManager.wait_while_speaking`` is where this
    listens — reading both venvs' ``ovos_bus_client/session.py`` side by
    side shows the same literal ``recognizer_loop:audio_output_end`` topic
    in both, so there is no cross-version drift here for this suite to
    catch today. The driver plays the audio service's part the way
    ``ovoscope`` does: it does not run one, it just emits the end-of-output
    message the real one would.
    """
    _server, bus, skill, _regs = stack
    token = uuid.uuid4().hex
    session = {"session_id": f"backcompat-speakwait-{token[:8]}"}
    done = Capture(bus, SPEAK_WAIT_DONE_TOPIC, token=token)
    try:
        bus.emit(Message(SPEAK_WAIT_TRIGGER_TOPIC, {"token": token},
                         {"session": session}))
        # give speak() time to run, set is_speaking, and register its
        # audio_output_end listener before the driver plays audio-service
        # and ends the "output" — wait_while_speaking bails out immediately
        # if it does not see is_speaking already set (see session.py), so
        # firing too early would make this a false pass for the wrong
        # reason (skipped the wait entirely) rather than the wait actually
        # unblocking.
        time.sleep(0.5)
        # Positive control: if speak(wait=True) was never actually called
        # (or never actually blocked), the "done" marker would already be
        # here by now, and firing AUDIO_OUTPUT_END_TOPIC afterward would
        # prove nothing about the wait unblocking. Catch that false green
        # before triggering the real unblock signal.
        assert not done.messages, (
            f"{COMBO}: speak(wait=True) returned before audio output "
            f"ended — it never waited.\nskill process log:\n{skill.log}")
        t_end = time.monotonic()
        bus.emit(Message(AUDIO_OUTPUT_END_TOPIC, {}, {"session": session}))
        assert done.wait(), (
            f"{COMBO}: speak(wait=True) never unblocked after "
            f"{AUDIO_OUTPUT_END_TOPIC!r} fired for its session — the old "
            f"skill container would hang forever waiting for audio output "
            f"it will never see end.\nskill process log:\n{skill.log}")
        elapsed = time.monotonic() - t_end
        # SessionManager.wait_while_speaking's own timeout defaults to 15s;
        # unblocking well under that proves the bridge fired the wait open
        # rather than the call merely timing out on its own. Measured from
        # t_end (when the unblock signal fired), not from the original
        # trigger, so the deliberate 0.5s settle sleep above doesn't eat
        # into this bound.
        assert elapsed < 10, (
            f"{COMBO}: speak(wait=True) took {elapsed:.1f}s to unblock — "
            f"looks like it rode out its own internal timeout instead of "
            f"reacting to {AUDIO_OUTPUT_END_TOPIC!r}")
    finally:
        done.close()


@pytest.mark.skipif(not IS_BROKEN_CELL,
                    reason="the kill switch only has meaning where the "
                           "compat mirror is what makes the handler run")
def test_kill_switch_disables_the_compat_mirror():
    """Inverse control: with ``emit_legacy`` off, the old handler stays silent.

    This is what proves the broken cell above measures the compat bridge and
    not some accident of the fixture. It passes today for the trivial reason
    that no mirror exists; once ``#271`` ships it becomes the real negative
    half of the pair, and a compat-drop PR has to flip the cell above while
    leaving this one green.

    The kill switch is applied on BOTH sides, belt and braces, but the one
    that actually matters here is the DRIVER's: bus-client#271 rule 1 (the
    legacy ``.intent``-suffixed twin) fires inside ``emit()`` in whichever
    process calls it, and the canonical dispatch below is emitted from the
    driver's own bus client, not the skill subprocess. ``server.client(
    emit_legacy=False)`` sets ``OVOS_BUS_EMIT_LEGACY`` for that client before
    it is constructed (see ``BusServer.client``); ``SkillProcess(...,
    emit_legacy=False)`` sets the same flag in the skill subprocess's own
    environment, which matters once the skill side ever emits anything of
    its own.
    """
    server = BusServer()
    skill = None
    try:
        bus = server.client(emit_legacy=False)
        # Positive control: prove emit_legacy actually landed False on the
        # translator the driver's client will emit through, rather than
        # relying on OVOS_BUS_EMIT_LEGACY silently being ignored (e.g. by
        # an env override) and leaving this test green for the wrong
        # reason.
        assert bus._translator.emit_legacy is False, (
            "server.client(emit_legacy=False) did not disable the "
            "translator's emit_legacy flag — the kill switch is not "
            "actually wired to this client")
        skill = SkillProcess(SKILL_PYTHON, server.xdg, emit_legacy=False)
        token = uuid.uuid4().hex
        handled = Capture(bus, "backcompat.skill.handled", token=token)
        canonical = Capture(bus, CANONICAL_TOPIC, token=token)
        try:
            bus.emit(Message(CANONICAL_TOPIC, {"food": "tacos", "token": token},
                             {"session": {"session_id": "backcompat-off"}}))
            assert canonical.wait(), "the dispatch never reached the bus"
            assert not handled.wait(5), (
                "the old handler ran with emit_legacy disabled — the compat "
                "mirror is not actually gated by the kill switch")
        finally:
            handled.close()
            canonical.close()
    finally:
        if skill is not None:
            skill.stop()
        server.stop()


# ---------------------------------------------------------------------------
# Audio axis (A): speak-wait against a spec-only (AUDIO-1) audio simulator
# ---------------------------------------------------------------------------
#
# design §2.6 / T2.3. test_speak_wait_unblocks_on_audio_output_end above
# already covers A=old (the driver plays the legacy
# ``recognizer_loop:audio_output_end`` part itself, matching the OLD
# workshop's own listener with no bridge involved at all -- vintages agree,
# nothing to prove about a translator). These tests cover the A=new half of
# design §2.4's row 4: a real ``audio_process.py`` subprocess (T2.3) that
# implements ONLY today's AUDIO-1 ``ovos_audio/playback.py`` contract --
# spec-only ``SpecMessage.AUDIO_OUTPUT_ENDED`` -- talking to an old-vintage
# skill container that only ever knew the legacy topic.
#
# Two-layer design (keeps the scenario meaningful even while workshop's own
# #526 gap blocks the skill-side wait):
#
# * Layer 1 (test_speak_wait_bridges_from_spec_only_audio) drives the FULL
#   real path: skill.speak(wait=True) -> SessionManager.wait_while_speaking
#   -> unblocked by whatever topic actually reaches ITS listener. This is
#   the end-to-end proof, but it inherits the SAME upstream gap the existing
#   speak-wait test is xfailed for: ovos-workshop's SessionManager.bus is
#   never connected inside a standalone container of this vintage (#526),
#   so wait=True no-ops regardless of what audio does. Marked xfail with
#   THE SAME reason string as the sibling test above -- cells failing for
#   the identical upstream reason share one reason string, so they read as
#   one finding, not two.
# * Layer 2 (test_spec_only_audio_output_end_reaches_a_legacy_listener_via_
#   translator_bridge / its inverse control) proves the actual thing this
#   scenario is about -- that a modern ``MessageBusClient``'s receive-side
#   ``NamespaceTranslator`` really does deliver the legacy counterpart of a
#   spec-only emission to a LOCAL listener -- with a second bus client
#   standing in for "what the skill's own client would receive", entirely
#   independent of workshop's SessionManager plumbing. This keeps the
#   translator bridge itself proven and mutation-tested even while #526
#   makes Layer 1 xfail; it is what stays meaningful, and green, right now.
#
# Which process's flag matters: bus-client's own receive path
# (``MessageBusClient.on_message`` -> ``self._translator.counterpart_topics``,
# verified against ``ovos-bus-client`` origin/dev,
# ``ovos_bus_client/client/client.py`` -- the mirror is emitted to LOCAL
# listeners at message-receive time, keyed off the RECEIVING client's own
# ``self._translator``, built from THAT client's ``OVOS_BUS_EMIT_LEGACY``/
# ``OVOS_BUS_MODERNIZE`` env at construction time). So it is the flag on
# whichever client needs to see the counterpart LOCALLY that matters -- the
# emitting audio process's own flag is irrelevant to whether a *different*
# process's listener sees the mirror. Layer 2's shadow client therefore
# toggles its OWN ``emit_legacy`` to build the inverse control, not the
# audio process's.

AUDIO_PYTHON = os.environ.get("BACKCOMPAT_AUDIO_PYTHON", "")

#: SAME reason string object as test_speak_wait_unblocks_on_audio_output_end's
#: xfail above (design instruction: cells failing for the identical upstream
#: reason -- #526 -- must share ONE reason string, not a character-divergent
#: copy).
_SPEAK_WAIT_526_XFAIL_REASON_A_NEW = _SPEAK_WAIT_526_XFAIL_REASON


@pytest.fixture(scope="module")
def audio_stack(stack):
    """The shared ``stack`` fixture (bus + old-vintage skill container) plus
    a NEW-vintage (spec-only) audio simulator on the same bus. A separate
    fixture, not folded into ``stack`` itself, so the S×C scenarios above
    don't pay for an audio process they never touch.
    """
    if not AUDIO_PYTHON:
        pytest.skip("BACKCOMPAT_AUDIO_PYTHON not set")
    server, bus, skill, regs = stack
    audio = AudioProcess(AUDIO_PYTHON, server.xdg, vintage="new")
    try:
        yield server, bus, skill, audio
    finally:
        audio.stop()


@pytest.fixture(scope="module")
def audio_stack_old(stack):
    """Same shape as ``audio_stack``, but an OLD-vintage (legacy-topic)
    audio simulator -- covers the A=old half of the C1 finding (a
    legacy-vintage cell test asserting ``recognizer_loop:audio_output_start``
    /``..._end`` ordering), since A=old cells are the design's whole point
    and this branch of ``audio_process.py`` deserves the same falsifiability
    as the A=new one, not deletion as YAGNI.
    """
    if not AUDIO_PYTHON:
        pytest.skip("BACKCOMPAT_AUDIO_PYTHON not set")
    server, bus, skill, regs = stack
    audio = AudioProcess(AUDIO_PYTHON, server.xdg, vintage="old")
    try:
        yield server, bus, skill, audio
    finally:
        audio.stop()


@pytest.mark.axes("A")
def test_audio_simulator_emits_legacy_start_then_end_in_order(audio_stack_old):
    """C1 (BLOCKING, adversarial review): mutation proof that something in
    the suite actually observes an emission FROM the simulator, for the
    ``old`` vintage branch (``audio_process._play``). Drives a real legacy
    ``speak`` message onto the bus -- the topic ``audio_process.py``'s
    ``old`` vintage subscribes -- and asserts the subprocess itself emits
    ``AUDIO_OUTPUT_START_TOPIC`` then, only after ``PLAYBACK_DELAY``,
    ``AUDIO_OUTPUT_END_TOPIC``. Replacing ``_play``'s body with a bare
    ``return`` must fail this test.
    """
    _server, bus, _skill, audio = audio_stack_old
    session_id = f"backcompat-audiosim-old-{uuid.uuid4().hex[:8]}"
    session = {"session_id": session_id}
    # session_id-scoped: _play emits both legacy topics with empty `data`
    # (matching the real recognizer_loop:audio_output_{start,end} contract,
    # which carries no correlation id either), so scoping has to go through
    # `context` rather than a data-borne token.
    started = Capture(bus, AUDIO_OUTPUT_START_TOPIC, session_id=session_id)
    ended = Capture(bus, AUDIO_OUTPUT_END_TOPIC, session_id=session_id)
    try:
        assert not started.messages and not ended.messages, (
            "legacy audio-output capture already had traffic before this "
            "test's own trigger -- the capture isn't scoped correctly")
        bus.emit(Message(LEGACY_SPEAK_TOPIC, {}, {"session": session}))
        assert started.wait(10), (
            f"the old-vintage audio simulator never emitted "
            f"{AUDIO_OUTPUT_START_TOPIC!r} for a legacy speak "
            f"message.\naudio process log:\n{audio.log}")
        # Ordering, not just presence: PLAYBACK_DELAY (0.3s) means a
        # genuine simulator cannot have emitted 'end' yet immediately
        # after 'start' arrived -- a mutant that fires both at once (or
        # end-before-start) would still pass a presence-only check.
        assert not ended.messages, (
            f"{AUDIO_OUTPUT_END_TOPIC!r} arrived together with (or before) "
            f"{AUDIO_OUTPUT_START_TOPIC!r} -- the simulator isn't actually "
            f"staggering start/end by its own PLAYBACK_DELAY")
        assert ended.wait(10), (
            f"the old-vintage audio simulator emitted "
            f"{AUDIO_OUTPUT_START_TOPIC!r} but never followed with "
            f"{AUDIO_OUTPUT_END_TOPIC!r}.\naudio process log:\n{audio.log}")
    finally:
        started.close()
        ended.close()


@pytest.mark.axes("A")
def test_audio_simulator_emits_started_then_ended_in_order_for_a_spec_speak(audio_stack):
    """C1 (BLOCKING, adversarial review): the A=new counterpart of the test
    above. Mutation proof: replacing ``audio_process._play_spec``'s body
    with a bare ``return`` left the pre-fix suite byte-identical green,
    because both Layer-2 bridge tests hand-emit the spec topic themselves
    from a shadow client, and the probe test only reads the simulator's
    stdout handshake, never the bus. This test drives a real
    ``SpecMessage.SPEAK`` onto the bus and asserts the subprocess itself
    emits ``AUDIO_OUTPUT_STARTED_SPEC_TOPIC`` then, only after
    ``PLAYBACK_DELAY``, ``AUDIO_OUTPUT_ENDED_SPEC_TOPIC`` -- scoped by
    ``message.forward(...)`` preserving the trigger's token, so this can't
    pass on stale traffic from another test.
    """
    _server, bus, _skill, audio = audio_stack
    # Resolved lazily, inside the test body: driver.py's spec-topic
    # accessors defer the ovos_spec_tools import to here specifically so
    # V0-channel cells (no ovos-spec-tools installed) can still collect
    # this module -- see driver.py's module comment above _spec_message.
    started_topic = audio_output_started_spec_topic()
    ended_topic = audio_output_ended_spec_topic()
    token = uuid.uuid4().hex
    session_id = f"backcompat-audiosim-{token[:8]}"
    session = {"session_id": session_id}
    # session_id-scoped, NOT token-scoped: verified live that
    # Message.forward(topic) -- what both audio_process._play_spec and the
    # real PlaybackThread.begin_audio/end_audio use -- carries `context`
    # forward but resets `data` to `{}`, so a `token` placed in the
    # triggering SPEAK's data never survives onto the simulator's own
    # STARTED/ENDED emissions (real ovos-audio behaviour, not a simulator
    # bug). Capture's session_id matching reads message.context instead.
    started = Capture(bus, started_topic, session_id=session_id)
    ended = Capture(bus, ended_topic, session_id=session_id)
    try:
        assert not started.messages and not ended.messages, (
            "spec audio-output capture already had traffic before this "
            "test's own trigger -- the capture isn't scoped correctly")
        bus.emit(Message(speak_spec_topic(), {"token": token},
                         {"session": session}))
        assert started.wait(10), (
            f"the new-vintage audio simulator never emitted "
            f"{started_topic!r} for a spec-only speak "
            f"message.\naudio process log:\n{audio.log}")
        assert not ended.messages, (
            f"{ended_topic!r} arrived together with (or "
            f"before) {started_topic!r} -- the simulator "
            f"isn't actually staggering start/end by its own PLAYBACK_DELAY")
        assert ended.wait(10), (
            f"the new-vintage audio simulator emitted "
            f"{started_topic!r} but never followed with "
            f"{ended_topic!r}.\naudio process log:\n"
            f"{audio.log}")
    finally:
        started.close()
        ended.close()


@pytest.mark.axes("A")
def test_audio_simulator_emits_mic_listen_after_ended_when_expect_response(audio_stack):
    """C4 (adversarial review): MIC_LISTEN must be gated on ``expect_response``
    -- the key ``OVOSSkill.speak``/``speak_dialog`` actually send and
    ``ovos_audio/service.py`` (~L366) actually reads -- not a ``listen`` key
    no producer ever sends.

    Not an ordering assertion against ``ended`` (deliberately): the real
    ``end_audio(listen, ...)`` fires ENDED and MIC_LISTEN back-to-back with
    no delay between them (unlike start->end, which the simulator's
    PLAYBACK_DELAY genuinely staggers), so a "not yet arrived" check in the
    gap between the two would be racing the network round trip rather than
    proving anything -- confirmed flaky live when first written this way.
    The gate itself (this test) and its inverse (the sibling test below,
    which proves MIC_LISTEN does NOT fire without expect_response) are
    what's actually falsifiable here.
    """
    _server, bus, _skill, audio = audio_stack
    ended_topic = audio_output_ended_spec_topic()
    mic_topic = mic_listen_spec_topic()
    token = uuid.uuid4().hex
    session_id = f"backcompat-audiosim-listen-{token[:8]}"
    session = {"session_id": session_id}
    # session_id-scoped, same reason as the ordering test above:
    # Message.forward(topic) resets `data` (drops any token there) but
    # carries `context` forward -- verified live against the real
    # Message.forward implementation.
    ended = Capture(bus, ended_topic, session_id=session_id)
    mic = Capture(bus, mic_topic, session_id=session_id)
    try:
        assert not ended.messages and not mic.messages, (
            "spec audio capture already had traffic before this test's "
            "own trigger -- the capture isn't scoped correctly")
        bus.emit(Message(speak_spec_topic(),
                         {"token": token, "expect_response": True},
                         {"session": session}))
        assert ended.wait(10), (
            f"the new-vintage audio simulator never emitted "
            f"{ended_topic!r} for an expect_response "
            f"speak.\naudio process log:\n{audio.log}")
        assert mic.wait(10), (
            f"expect_response=True never produced "
            f"{mic_topic!r} after audio output ended.\naudio "
            f"process log:\n{audio.log}")
    finally:
        ended.close()
        mic.close()


@pytest.mark.axes("A")
def test_audio_simulator_does_not_emit_mic_listen_without_expect_response(audio_stack):
    """Inverse of the gate proof above: without ``expect_response``, MIC_LISTEN
    must NOT fire at all. Mutation proof for C4's fix: a mutant that reverts
    the gate back to checking a ``listen`` key (which no producer sends) --
    or drops the gate entirely -- makes this test XPASS-equivalent (MIC_LISTEN
    fires unconditionally), so this is what actually pins the gate's
    condition, not just its positive side.
    """
    _server, bus, _skill, audio = audio_stack
    ended_topic = audio_output_ended_spec_topic()
    mic_topic = mic_listen_spec_topic()
    token = uuid.uuid4().hex
    session_id = f"backcompat-audiosim-nolisten-{token[:8]}"
    session = {"session_id": session_id}
    ended = Capture(bus, ended_topic, session_id=session_id)
    mic = Capture(bus, mic_topic, session_id=session_id)
    try:
        assert not ended.messages and not mic.messages, (
            "spec audio capture already had traffic before this test's "
            "own trigger -- the capture isn't scoped correctly")
        bus.emit(Message(speak_spec_topic(), {"token": token},
                         {"session": session}))
        assert ended.wait(10), (
            f"the new-vintage audio simulator never emitted "
            f"{ended_topic!r} for a plain speak (no "
            f"expect_response).\naudio process log:\n{audio.log}")
        assert not mic.wait(3), (
            f"{mic_topic!r} fired without expect_response -- "
            f"the C4 gate is not actually gating.\naudio process log:\n"
            f"{audio.log}")
    finally:
        ended.close()
        mic.close()


@pytest.mark.axes("A")
def test_audio_probe_observes_spec_only_emission(audio_stack):
    """Positive control for the probe itself (design §2.5's real-symbol-probe
    discipline): the audio simulator's own ``VERSIONS`` handshake must say
    it emits the spec topic, not a version string this test would have to
    assume. This is what ``driver.audio_output_end_topic_probe()`` now
    reads (T2.3 wiring, replacing the old unconditional ``None``).
    """
    _server, _bus, _skill, audio = audio_stack
    ended_topic = audio_output_ended_spec_topic()
    assert audio.versions.get("vintage") == "new"
    probed = audio_output_end_topic_probe(audio)
    assert probed == ended_topic, (
        f"audio_output_end_topic_probe() observed {probed!r}, expected the "
        f"spec topic {ended_topic!r} from a 'new'-vintage "
        f"audio_process.py")


@pytest.mark.xfail(strict=True, reason=_SPEAK_WAIT_526_XFAIL_REASON_A_NEW)
@pytest.mark.axes("S", "A")
def test_speak_wait_bridges_from_spec_only_audio(audio_stack):
    """Layer 1 -- the full real path: ``speak(wait=True)`` against a
    NEW-vintage (spec-only) audio simulator, for an OLD-vintage skill
    container that only ever knew the legacy topic. Would only unblock via
    the bus-client ``NamespaceTranslator`` mirroring the spec-only emission
    onto the legacy topic locally inside the skill's own client. Currently
    unreachable regardless of the bridge, because of #526 -- see the module
    section docstring's two-layer note above; Layer 2 below proves the
    bridge itself.
    """
    _server, bus, skill, audio = audio_stack
    token = uuid.uuid4().hex
    session = {"session_id": f"backcompat-speakwait-spec-{token[:8]}"}
    done = Capture(bus, SPEAK_WAIT_DONE_TOPIC, token=token)
    try:
        bus.emit(Message(SPEAK_WAIT_TRIGGER_TOPIC, {"token": token},
                         {"session": session}))
        # Same positive-control shape as test_speak_wait_unblocks_on_audio_
        # output_end (#26's mutation-proof pattern): the audio simulator's
        # own PLAYBACK_DELAY (0.3s) means a genuinely-waiting speak() cannot
        # have unblocked yet at 0.5s. If it HAS -- #526's "SessionManager.bus
        # is never connected" no-op returns immediately, regardless of the
        # translator bridge -- this is the false green the assertion below
        # exists to catch, converting it into the expected xfail rather than
        # a silent, meaningless XPASS.
        time.sleep(0.5)
        assert not done.messages, (
            f"{COMBO}: speak(wait=True) returned before the spec-only "
            f"audio simulator's own audio-output-ended emission -- it "
            f"never waited.\nskill process log:\n{skill.log}\naudio "
            f"process log:\n{audio.log}")
        assert done.wait(15), (
            f"{COMBO}: speak(wait=True) never unblocked against a "
            f"spec-only (A=new) audio simulator.\nskill process log:\n"
            f"{skill.log}\naudio process log:\n{audio.log}")
    finally:
        done.close()


@pytest.mark.axes("A")
def test_spec_only_audio_output_end_reaches_a_legacy_listener_via_translator_bridge(audio_stack):
    """Layer 2 -- proves the translator bridge itself, decoupled from
    workshop's #526 gap: a second bus client (standing in for "what the
    skill's own client would locally receive") subscribes to the LEGACY
    ``AUDIO_OUTPUT_END_TOPIC`` with ``emit_legacy`` on (the default), a
    spec-only emission is sent, and the shadow listener must still see the
    legacy counterpart -- delivered locally by its own receiving client,
    per ``ovos_bus_client.client.client.MessageBusClient.on_message``'s
    ``counterpart_topics`` fan-out (section docstring above). Mutation-proof
    positive half of the pair; the inverse control follows.
    """
    server, _bus, _skill, _audio = audio_stack
    ended_topic = audio_output_ended_spec_topic()
    shadow = server.client(emit_legacy=True)
    try:
        assert shadow._translator.emit_legacy is True, (
            "shadow client's translator did not come up with emit_legacy "
            "True -- the positive-control setup itself is wrong")
        token = uuid.uuid4().hex
        session = {"session_id": f"backcompat-bridge-{token[:8]}"}
        legacy_seen = Capture(shadow, AUDIO_OUTPUT_END_TOPIC, token=token)
        try:
            # Positive control: nothing on the legacy topic yet, so a wait()
            # below that returns True can only be the emission this test
            # sends, never leftover traffic from an earlier test.
            assert not legacy_seen.messages, (
                "legacy listener already had traffic before the spec "
                "emission -- the capture isn't scoped correctly")
            shadow.emit(Message(ended_topic, {"token": token},
                                {"session": session}))
            assert legacy_seen.wait(10), (
                f"a spec-only {ended_topic!r} emission "
                f"never reached a local listener on the legacy "
                f"{AUDIO_OUTPUT_END_TOPIC!r} topic -- the NamespaceTranslator "
                f"receive-side bridge did not fire")
        finally:
            legacy_seen.close()
    finally:
        shadow.close()


@pytest.mark.xfail(strict=True, reason=(
    "inverse control: with the RECEIVING client's own OVOS_BUS_EMIT_LEGACY "
    "off, the receive-side NamespaceTranslator bridge in "
    "MessageBusClient.on_message never produces the legacy counterpart "
    "locally, so a listener bound only to the legacy topic must NOT see a "
    "spec-only emission. This is the flag that matters for this direction "
    "(the RECEIVING side's flag, not the emitter's -- see the section "
    "docstring's 'which process's flag matters' note above). XPASS here "
    "would mean the bridge fired anyway with the kill switch off, which is "
    "a real bug in the translator's flag gating, not a reason to drop this "
    "marker."))
@pytest.mark.axes("A")
def test_spec_only_audio_output_end_does_not_reach_a_legacy_listener_with_bridge_off(audio_stack):
    """Inverse control for the Layer 2 bridge proof above: same shape, but
    the shadow (receiving) client has ``emit_legacy=False``, so it must NOT
    locally deliver the legacy counterpart of a spec-only emission.
    """
    server, _bus, _skill, _audio = audio_stack
    ended_topic = audio_output_ended_spec_topic()
    shadow = server.client(emit_legacy=False)
    try:
        assert shadow._translator.emit_legacy is False, (
            "shadow client's translator did not come up with emit_legacy "
            "False -- the negative-control setup itself is wrong")
        token = uuid.uuid4().hex
        session = {"session_id": f"backcompat-bridge-off-{token[:8]}"}
        spec_seen = Capture(shadow, ended_topic, token=token)
        legacy_seen = Capture(shadow, AUDIO_OUTPUT_END_TOPIC, token=token)
        try:
            shadow.emit(Message(ended_topic, {"token": token},
                                {"session": session}))
            # C2 (BLOCKING, adversarial review): without this check, a
            # mutant that renames/breaks the spec topic (so
            # the spec emission itself never lands) makes legacy_seen.wait()
            # below time out for the WRONG reason -- an absent emission
            # reads identically to "the bridge correctly stayed silent".
            # Asserting the spec side actually arrived first is what proves
            # the xfail below is measuring the translator's emit_legacy
            # gate specifically, not a broken emission.
            assert spec_seen.wait(10), (
                "spec emission never reached the shadow client -- the "
                "inverse control's own emit is broken, not just the "
                "bridge (nothing to test if the emission never landed at "
                "all)")
            assert legacy_seen.wait(3), (
                "expected-failure path: the legacy listener should have "
                "stayed silent with the bridge off")
        finally:
            spec_seen.close()
            legacy_seen.close()
    finally:
        shadow.close()
