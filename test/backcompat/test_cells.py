"""Unit-level tests for ``cells.py`` -- no venv pair, no bus, no
``BACKCOMPAT_*`` env needed. Deliberately NOT gated by
``test_mixed_version_matrix.py``'s whole-module skipif (it needs
``BACKCOMPAT_COMBO``/``BACKCOMPAT_SKILL_PYTHON``; this file needs neither),
so these collect and run in any plain ``pytest test/backcompat/`` — that's
the point of factoring the 4-tuple/pruning/probe-comparison logic out of
the venv-dependent test module in the first place.
"""
import pytest

from .cells import (AXES, BOUNDARY_ALIASES, CHANNEL_CELLS, MATCHER_SKEW,
                    OTHER, REFERENCE, adapt_vintage, assert_vintage,
                    axis_values, cell_id, is_redundant, probed_vintage_matches,
                    resolve_cell)


#: The exact worked example in design §2.5 -- the four combo names that
#: existed before the M axis got its own cells. These are the compat surface
#: (``BACKCOMPAT_COMBO`` values, CI matrix entries), so their mapping is
#: pinned exactly; T2.5 adds cells ALONGSIDE them and must not move them.
_DESIGN_2_5_ALIASES = {
    "old-skill/old-core": "Sold-Cold-Mold-Anew",
    "old-skill/new-core": "Sold-Cnew-Mnew-Anew",
    "new-skill/old-core": "Snew-Cold-Mold-Anew",
    "new-skill/new-core": "Snew-Cnew-Mnew-Anew",
}


def test_alias_table_matches_design_section_2_5():
    """The four original aliases keep their exact §2.5 mapping.

    A subset check, not an equality one, since T2.5 added M-axis cells to
    the same table -- but the four names below are the ones CI and every
    existing caller pass, so each must still resolve to the exact cell it
    always did. An added cell is fine; a MOVED alias is a compat break.
    """
    for combo, cell in _DESIGN_2_5_ALIASES.items():
        assert BOUNDARY_ALIASES[combo] == cell


def test_the_m_axis_cells_actually_cross_m_against_c():
    """T2.5: the point of the ``*-matchers`` cells is that M != C in them.

    Without this, someone could add a cell named ``-old-matchers`` that
    quietly pinned M to the same vintage as C, and the M axis would be back
    to being unfalsifiable while looking covered.
    """
    crossed = {c for c in BOUNDARY_ALIASES if c.endswith(("-old-matchers",
                                                          "-new-matchers"))}
    assert len(crossed) == 4, (
        f"expected the four M-crossed cells (design §2.4's S×C×M cube minus "
        f"the four original aliases), got {sorted(crossed)}")
    for combo in crossed:
        values = axis_values(BOUNDARY_ALIASES[combo])
        assert values["M"] != values["C"], (
            f"{combo!r} resolves to {BOUNDARY_ALIASES[combo]!r}, where M "
            f"equals C -- it does not cross the matcher axis at all")


def test_skew_sub_cells_declare_an_adapt_vintage_and_share_a_cell_id():
    """T2.5 / design §2.2: skew sub-cells are NOT a fifth axis.

    Each one carries the PADATIOUS vintage in its cell id (so it prunes
    identically to the non-skewed cell it shares that id with) and records
    the adapt half separately. Only the adapt-new direction is reachable --
    ``ovos-adapt-parser==1.3.4a1`` caps ``ovos-spec-tools`` below every core
    pin -- so an OTHER value appearing here would mean somebody added a cell
    no venv can build.
    """
    assert MATCHER_SKEW, "the skew sub-cells vanished"
    for combo, adapt in MATCHER_SKEW.items():
        assert adapt == REFERENCE, (
            f"{combo!r} claims adapt={adapt!r}; the old adapt vintage does "
            f"not resolve against any core pin build_venvs.sh uses")
        assert adapt_vintage(combo) == adapt
        cell = BOUNDARY_ALIASES[combo]
        assert axis_values(cell)["M"] == OTHER, (
            f"{combo!r} skews padatious OLD against adapt NEW, so its cell "
            f"id's M (the padatious half) must be {OTHER!r}, got {cell!r}")
        # shares its id with a non-skew cell: that is what "sub-cell" means
        assert [c for c in BOUNDARY_ALIASES
                if BOUNDARY_ALIASES[c] == cell and c != combo], (
            f"{combo!r} is the only combo resolving to {cell!r}; a skew "
            f"sub-cell is supposed to shadow a real cell, not invent one")


def test_combos_that_pin_no_adapt_report_no_adapt_vintage():
    """``adapt_vintage`` must not invent a vintage for a venv that installs
    no ``ovos-adapt-parser`` -- the four original aliases and the
    ``*-old-matchers`` cells (whose old adapt pin is unreachable) all pin
    none, and a test that asserted a vintage there would be asserting
    against a package that is not in the venv."""
    for combo in list(_DESIGN_2_5_ALIASES) + [
            c for c in BOUNDARY_ALIASES if c.endswith("-old-matchers")]:
        assert adapt_vintage(combo) is None, combo
    for combo in CHANNEL_CELLS:
        assert adapt_vintage(combo) is None, combo


def test_channel_combos_are_not_4_tuple_cells():
    for combo in CHANNEL_CELLS:
        assert resolve_cell(combo) is None


def test_unknown_combo_resolves_to_none():
    assert resolve_cell("not-a-real-combo") is None


@pytest.mark.parametrize("combo,cell", list(BOUNDARY_ALIASES.items()))
def test_axis_values_round_trips_every_alias(combo, cell):
    assert resolve_cell(combo) == cell
    values = axis_values(cell)
    assert set(values) == set(AXES)
    # every value the cell reports must reappear verbatim in the id string
    assert cell_id(**{axis: values[axis] for axis in AXES}) == cell


def test_axis_values_rejects_malformed_cell_ids():
    with pytest.raises(ValueError):
        axis_values("garbage")
    with pytest.raises(ValueError):
        axis_values("Sold-Cnew-Mnew")  # missing A
    with pytest.raises(ValueError):
        axis_values("Sold-Cnew-Mnew-Aweird")  # not old/new
    with pytest.raises(ValueError):
        axis_values("Sold-Sold-Mnew-Anew")  # S twice, C missing


@pytest.mark.parametrize("axes,cell,want", [
    # genuinely partial-reference cells (not the all-reference cell, and
    # crossing no UNPROBED_AXES): the plain "all crossed axes reference"
    # rule applies.
    (("S", "C"), "Snew-Cnew-Mold-Anew", True),        # S,C both reference; M/A uncrossed, don't matter
    (("S", "C"), "Sold-Cnew-Mnew-Anew", False),       # S crossed, not reference
    (("S", "C", "M"), "Snew-Cold-Mold-Anew", False),  # C,M crossed, not reference
    (("S", "C", "M"), "Snew-Cnew-Mnew-Aold", True),   # S,C,M all reference; A uncrossed, all-4 NOT reference (A old)
    ((), "Sold-Cold-Mold-Anew", False),               # crossing nothing: never redundant
    # item 1 (adversarial review): the all-reference cell is NEVER
    # redundant, for any axes, even ones that look fully "satisfied".
    (("S", "C"), "Snew-Cnew-Mnew-Anew", False),
    (("S", "C", "M"), "Snew-Cnew-Mnew-Anew", False),
    ((), "Snew-Cnew-Mnew-Anew", False),
    # item 3 (adversarial review): any axis in UNPROBED_AXES (today: A)
    # never contributes to a "redundant" verdict, even on a cell where its
    # nominal label is "new" and every OTHER crossed axis really is
    # reference -- because nothing actually probed it.
    (("S", "A"), "Sold-Cnew-Mnew-Anew", False),  # S also crossed and old -> already False anyway
    (("S", "A"), "Snew-Cold-Mold-Anew", False),  # S=new, A=new(unprobed) -> must NOT be pruned
    (("S", "C", "A"), "Snew-Cnew-Mold-Anew", False),  # S,C new, A new(unprobed) -> must NOT be pruned
])
def test_is_redundant_matches_the_pruning_table(axes, cell, want):
    assert is_redundant(axes, cell) is want


def test_is_redundant_rejects_an_unreal_axis():
    with pytest.raises(ValueError):
        is_redundant(("S", "Q"), "Snew-Cnew-Mnew-Anew")


def test_is_redundant_never_prunes_the_all_reference_cell():
    """Adversarial-review item 1: no matter which axes a scenario crosses
    (including none), the fully-new-everything cell must keep running it.
    Pruning exists to skip *redundant* re-proof of an already-crossed
    axis; it must never silence the one cell that is the positive control
    for "does anything work at all" (design Part 4 rule 5)."""
    all_reference_cell = "Snew-Cnew-Mnew-Anew"
    for axes in (("S",), ("C",), ("M",), ("A",), ("S", "C"), ("S", "C", "M"),
                 ("S", "C", "M", "A"), ()):
        assert is_redundant(axes, all_reference_cell) is False, axes


def test_is_redundant_never_prunes_on_an_unprobed_axis():
    """Adversarial-review item 3: axis A has no live probe (see
    UNPROBED_AXES / driver.audio_output_end_topic_probe). A scenario
    crossing it must never be deselected on the strength of A's nominal
    (unverified) "new" label, even when every other crossed axis really
    is reference."""
    cell_with_S_C_reference_but_not_all = "Snew-Cnew-Mold-Anew"
    assert is_redundant(("S", "C"), cell_with_S_C_reference_but_not_all) is True
    assert is_redundant(("S", "C", "A"),
                        cell_with_S_C_reference_but_not_all) is False


def test_a_mislabeled_probe_result_fails_loudly():
    """Prove a fixture break cannot masquerade as a compat finding (design
    Part 4 rule 5 / T2.2 item 4): feed the vintage-check machinery a
    deliberately wrong probe observation for a known cell and confirm it
    is rejected, not silently accepted.
    """
    cell = BOUNDARY_ALIASES["old-skill/new-core"]  # Sold-Cnew-Mnew-Anew
    assert axis_values(cell)["S"] == "old"

    # correctly-labeled: a real S-axis probe on this cell should observe
    # "old" vintage (observed_is_new=False) -- that must match.
    assert probed_vintage_matches("S", cell, observed_is_new=False) is True
    assert_vintage("S axis probe (correct)", cell=cell, axis="S",
                   observed_is_new=False)  # must not raise

    # mislabeled: a probe wrongly reporting the skill side as new-vintage
    # on a cell whose identity pins it old. If this were accepted, a
    # broken probe (e.g. a stub that always returns True, or a copy-paste
    # that reads the wrong axis) could sail through
    # test_pins_are_the_intended_vintage and get misread as "the #271/#500
    # boundary moved" instead of a fixture bug.
    assert probed_vintage_matches("S", cell, observed_is_new=True) is False
    with pytest.raises(AssertionError):
        assert_vintage("S axis probe (mislabeled)", cell=cell, axis="S",
                       observed_is_new=True)

    # same check on the reference cell in the opposite direction, so this
    # isn't just testing one hard-coded polarity.
    ref_cell = BOUNDARY_ALIASES["new-skill/new-core"]  # all axes 'new'
    assert probed_vintage_matches("C", ref_cell, observed_is_new=False) is False
    with pytest.raises(AssertionError):
        assert_vintage("C axis probe (mislabeled)", cell=ref_cell, axis="C",
                       observed_is_new=False)
