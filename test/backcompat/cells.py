"""4-tuple cell identity for the boundary tier of the mixed-version matrix.

Design: ``backcompat-matrix-design.md`` Part 2, §2.1-§2.5 (verified against
``origin/dev`` 2026-08-12; not vendored in this checkout -- ask for the
source doc if you need the full archaeology). Four axes, each independently
reachable by real package resolution (design §2.1):

* **S** -- skill container (``ovos-workshop`` + its resolved bus-client)
* **C** -- core stack (``ovos-core`` + in-core converse/fallback/stop
  pipelines + resolved bus-client -- these cannot drift independently of
  ``ovos-core``, design §1.2, so they are not separate axes)
* **M** -- matcher plugins (``ovos-padatious`` today; ``ovos-adapt-parser``
  is part of the same axis conceptually but has no venv of its own yet --
  see ``build_venvs.sh``, unchanged by this module)
* **A** -- audio side (``ovos-audio``'s AUDIO-1 output namespace), backed
  by ``test/backcompat/audio_process.py``'s simulator (T2.3, design §2.6).

A cell id is ``S{old|new}-C{old|new}-M{old|new}-A{old|new}``. Today's four
boundary combo names (``old-skill/old-core`` etc.) are kept as *aliases*
resolving to a 4-tuple cell (design §2.5) so ``BACKCOMPAT_COMBO`` and the CI
matrix entries keep working unchanged -- the aliases ARE the compat surface.
The four channel cells (``stable-skill/dev-core`` etc.) are a separate tier:
they pin the whole stack off a live distro constraints file rather than
crossing individual axes, so they are deliberately NOT folded into this
4-tuple space (design §2.5, last paragraph).
"""
from typing import Dict, FrozenSet, Iterable, Optional

AXES = ("S", "C", "M", "A")
#: The "current dev" side of every axis. Chosen as the reference (rather
#: than "old") because it's what every boundary cell shares by default
#: (design §2.2's reachability table: every IN mix keeps at least the
#: non-crossed axes at dev) and because axis pruning (design §2.4) is
#: phrased as "cross this against non-reference vintage".
REFERENCE = "new"
OTHER = "old"

#: Axes whose nominal vintage in a cell id is an assumption (hard-coded in
#: ``BOUNDARY_ALIASES``), never a *guaranteed* observation. ``A`` (audio) is
#: the only member today: ``driver.audio_output_end_topic_probe()`` is wired
#: to a live ``audio_process.py`` subprocess (T2.3, design §2.6) and returns
#: a real observed topic whenever that process is actually running -- but
#: most scenarios never spawn one (design §2.4's pruning table: only the
#: speak-wait / get_response-timeout scenarios cross axis A), so the probe
#: is genuinely live only conditionally, not for every cell unconditionally.
#: ``is_redundant`` refuses to prune on an axis in this set -- see its
#: docstring. Remove ``"A"`` here only once every cell that carries an A
#: value also runs a scenario that spawns and probes the audio process.
UNPROBED_AXES: FrozenSet[str] = frozenset({"A"})

CellId = str


def cell_id(S: str, C: str, M: str, A: str) -> CellId:
    """Build a cell id, validating each axis value is 'old' or 'new'."""
    values = (S, C, M, A)
    for axis, val in zip(AXES, values):
        if val not in (REFERENCE, OTHER):
            raise ValueError(
                f"axis {axis} vintage {val!r} must be {REFERENCE!r} or "
                f"{OTHER!r}")
    return f"S{S}-C{C}-M{M}-A{A}"


def axis_values(cell: CellId) -> Dict[str, str]:
    """Parse ``'Sold-Cnew-Mnew-Anew'`` back into ``{'S': 'old', 'C': 'new',
    'M': 'new', 'A': 'new'}``. Raises on anything malformed rather than
    guessing, since a silently-wrong parse here would corrupt every
    downstream pruning decision."""
    out: Dict[str, str] = {}
    parts = cell.split("-")
    if len(parts) != len(AXES):
        raise ValueError(
            f"{cell!r}: expected {len(AXES)} axis segments, got {len(parts)}")
    for part in parts:
        if not part or part[0] not in AXES:
            raise ValueError(f"{cell!r}: malformed axis segment {part!r}")
        axis, val = part[0], part[1:]
        if val not in (REFERENCE, OTHER):
            raise ValueError(
                f"{cell!r}: axis {axis} has vintage {val!r}, expected "
                f"{REFERENCE!r} or {OTHER!r}")
        if axis in out:
            raise ValueError(f"{cell!r}: axis {axis} appears twice")
        out[axis] = val
    missing = set(AXES) - out.keys()
    if missing:
        raise ValueError(f"{cell!r}: missing axes {sorted(missing)}")
    return out


#: design §2.5 -- today's four boundary combo names, resolved to the
#: 4-tuple cell each one is now an alias for. ``BACKCOMPAT_COMBO`` and the
#: CI matrix keep using these names unchanged.
BOUNDARY_ALIASES: Dict[str, CellId] = {
    # today's core_old pins padatious 2.0.0a1 (last pre-fold release), so
    # M is 'old' here even though only S and C vary in the combo name --
    # see build_venvs.sh's core_old pin and design §2.5's own worked
    # example for this exact alias.
    "old-skill/old-core": cell_id("old", "old", "old", "new"),
    "old-skill/new-core": cell_id("old", "new", "new", "new"),
    "new-skill/old-core": cell_id("new", "old", "old", "new"),
    "new-skill/new-core": cell_id("new", "new", "new", "new"),
}

#: The four channel cells are a separate tier (design §2.5): built from a
#: live OVOS distro constraints file, not individual axis pins, so they are
#: not part of the 4-tuple space and axis pruning does not apply to them.
CHANNEL_CELLS: FrozenSet[str] = frozenset({
    "stable-skill/dev-core", "dev-skill/stable-core",
    "testing-skill/dev-core", "dev-skill/testing-core",
})


def resolve_cell(combo: str) -> Optional[CellId]:
    """The 4-tuple cell id ``combo`` resolves to, or ``None`` when ``combo``
    is a channel combo (see ``CHANNEL_CELLS``) or unrecognized -- callers
    that need to distinguish "channel" from "unknown" should check
    membership in ``CHANNEL_CELLS`` / ``BOUNDARY_ALIASES`` themselves;
    ``test_mixed_version_matrix.py``'s own ``COMBOS`` lookup is still what
    raises on a genuinely unknown combo name."""
    if combo in CHANNEL_CELLS:
        return None
    return BOUNDARY_ALIASES.get(combo)


def is_redundant(axes: Iterable[str], cell: CellId) -> bool:
    """True when every axis in ``axes`` is at REFERENCE vintage in
    ``cell`` -- i.e. running a scenario that only depends on ``axes``
    against this cell cannot show anything a single-vintage run wouldn't
    (design §2.4's pruning rule, R3). This is what the ``@pytest.mark.axes(
    ...)`` + conftest deselection hook applies per test.

    ``axes`` is normally a test's ``@pytest.mark.axes(...)`` args, e.g.
    ``("S", "C")`` for the converse scenario -- see the pruning table in
    design §2.4.

    Two guards on top of the plain "all crossed axes are reference" rule,
    both added after adversarial review of the first cut of this file:

    * **the all-reference cell is never redundant, for anything.**
      Pruning is about not re-proving what an *already-crossed* axis
      already showed elsewhere; it is never license to stop asserting the
      positive control itself. Design Part 4 rule 5 ("positive controls
      are mandatory per cell") means the current-everything cell must
      keep running its full scenario set -- a handler firing, converse
      firing, get_response returning, speak(wait=True) unblocking -- even
      though every axis it touches happens to be reference. Without this
      guard the reference cell would lose exactly those tests, leaving
      only the frozen old-skill/old-core pin as the one cell that ever
      asserts a handler runs at all.
    * **an axis with no live probe wired never counts as reference.**
      Axis A (audio) is hard-coded ``"new"`` in every alias today
      (``BOUNDARY_ALIASES``), but ``audio_output_end_topic_probe()`` (T2.3)
      only produces a real observation while an ``audio_process.py``
      subprocess is actually running for the current test -- most
      scenarios never spawn one, so for them the cell id's "new" label is
      still an assumption, not an observation. Treating an unprobed axis
      as reference would let a pruning decision ride on a value nobody
      actually checked for THAT test. See ``UNPROBED_AXES``.
    """
    values = axis_values(cell)
    unknown = set(axes) - set(AXES)
    if unknown:
        raise ValueError(f"not a real axis: {sorted(unknown)}")
    if not axes:
        # a scenario crossing no axis is never redundant to run -- it's
        # not part of the pruning story at all.
        return False
    if all(values[axis] == REFERENCE for axis in AXES):
        # the all-reference cell: never prune, regardless of which axes
        # this scenario crosses. See the guard note above.
        return False
    if any(axis in UNPROBED_AXES for axis in axes):
        # this scenario crosses an axis this repo cannot actually observe
        # yet (see UNPROBED_AXES) -- its nominal "new" label in the cell
        # id is an assumption, not a probed fact, so it must never be the
        # reason a scenario gets pruned.
        return False
    return all(values[axis] == REFERENCE for axis in axes)


def probed_vintage_matches(axis: str, cell: CellId,
                            observed_is_new: bool) -> bool:
    """True when a real-symbol probe's new/old-ness observation for
    ``axis`` agrees with what ``cell``'s own identity says that axis is
    pinned to. The building block ``assert_vintage`` below raises on top
    of."""
    want_new = axis_values(cell)[axis] == REFERENCE
    return want_new == observed_is_new


def assert_vintage(probe_name: str, *, cell: CellId, axis: str,
                    observed_is_new: bool) -> None:
    """Raise loudly when a real-symbol probe's new/old-ness for ``axis``
    disagrees with what ``cell``'s 4-tuple identity says.

    Factored out of the venv-dependent ``test_pins_are_the_intended_vintage``
    (which needs a live skill/core process pair) so the specific failure
    mode this exists to prevent -- a mislabeled or broken probe silently
    agreeing with whatever a cell expects, so a fixture break reads as a
    real compat finding -- has a unit-level adversarial test that needs no
    venv pair at all. See ``test_cells.py``'s
    ``test_a_mislabeled_probe_result_fails_loudly`` and design Part 4
    rule 5 / T2.2 item 4.
    """
    if not probed_vintage_matches(axis, cell, observed_is_new):
        want_new = axis_values(cell)[axis] == REFERENCE
        raise AssertionError(
            f"{probe_name}: cell {cell} pins axis {axis} to "
            f"{'reference (new)' if want_new else 'old'} vintage, but the "
            f"probe observed {'new' if observed_is_new else 'old'}-vintage "
            f"behaviour")
