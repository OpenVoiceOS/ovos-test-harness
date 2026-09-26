"""The shipped ovos-solver-BM25-plugin wheel, loaded through OPM.

This is a packaging cell, not a spec-conformance one. It answers a question
the plugin's own suite cannot: does the BUILT wheel register entry points OPM
can resolve? A plugin's tests import its classes directly and pass whatever
the pyproject says, so an entry point that names a class the module does not
define is invisible to them and fatal to every consumer.

That is not hypothetical. ``ovos-evidence-solver-bm25`` named
``BM25SolverPlugin`` while the class was ``BM25EvidenceSolverPlugin``. The
plugin's suite was green throughout. A gate found it (T-4723), and
ovos-solver-BM25-plugin#34 repaired it on 2026-09-25. The
``test_every_entry_point_resolves_to_a_class_that_exists`` cell below is that
defect generalized: it fails for any of the five, not only the one that was
wrong.

Skips as a whole when the plugin is absent. That guard is load-bearing. With
no wheel installed every loader returns ``None``, so a cell asserting ``None``
would pass while measuring nothing at all.
"""
import importlib.metadata as md

import pytest

pytest.importorskip("ovos_bm25_solver",
                    reason="ovos-solver-BM25-plugin is not installed")
pytest.importorskip("ovos_plugin_manager.solvers")

from ovos_plugin_manager.solvers import (  # noqa: E402
    load_multiple_choice_solver_plugin,
    load_question_solver_plugin,
    load_reading_comprehension_solver_plugin,
    load_tldr_solver_plugin,
)

QUERY = "what is the capital of Portugal"
OPTIONS = ["Lisbon is the capital of Portugal",
           "Madrid is the capital of Spain",
           "the weather is sunny today"]

#: One row per entry point the wheel publishes: loader, entry-point name, the
#: class it must resolve to, and the OPM group it is registered under.
ENTRY_POINTS = [
    (load_question_solver_plugin, "ovos-solver-bm25-squad-plugin",
     "BM25SquadQASolver", "opm.solver.question"),
    (load_question_solver_plugin, "ovos-solver-bm25-freebase-plugin",
     "BM25FreebaseQASolver", "opm.solver.question"),
    (load_tldr_solver_plugin, "ovos-summarizer-bm25",
     "BM25SummarizerPlugin", "opm.solver.summarization"),
    (load_multiple_choice_solver_plugin, "ovos-choice-solver-bm25",
     "BM25MultipleChoiceSolver", "opm.solver.multiple_choice"),
    (load_reading_comprehension_solver_plugin, "ovos-evidence-solver-bm25",
     "BM25EvidenceSolverPlugin", "opm.solver.reading_comprehension"),
]

IDS = [name for _, name, _, _ in ENTRY_POINTS]


@pytest.mark.parametrize("loader,name,cls_name,group",
                         ENTRY_POINTS, ids=IDS)
def test_entry_point_loads(loader, name, cls_name, group):
    """Through OPM's loader, which is how every consumer reaches it."""
    cls = loader(name)
    assert cls is not None, f"{name} did not load through OPM"
    assert cls.__name__ == cls_name, (
        f"{name} resolved to {cls.__name__}, expected {cls_name}")


@pytest.mark.parametrize("group", sorted({g for _, _, _, g in ENTRY_POINTS}))
def test_every_entry_point_resolves_to_a_class_that_exists(group):
    """The #34 defect, generalized to every group the wheel publishes.

    ``EntryPoint.load()`` is what raises when the target is missing, so this
    asks the metadata directly rather than going through OPM: a loader that
    swallows the error and returns None would hide exactly this.
    """
    published = [e for e in md.entry_points(group=group)
                 if e.value.startswith("ovos_bm25_solver")]
    assert published, f"the wheel publishes nothing under {group}"
    for entry in published:
        try:
            target = entry.load()
        except (AttributeError, ImportError) as exc:
            pytest.fail(f"{entry.name} = {entry.value} does not resolve: {exc}")
        assert target.__name__ == entry.value.rsplit(":", 1)[1]


def test_the_five_published_names_are_exactly_what_this_cell_pins():
    """A new entry point that nothing here exercises is a gap in this cell,
    and a disappeared one is a break for consumers. Either way the cell must
    be edited rather than quietly stay green."""
    found = set()
    for group in {g for _, _, _, g in ENTRY_POINTS}:
        found |= {e.name for e in md.entry_points(group=group)
                  if e.value.startswith("ovos_bm25_solver")}
    assert found == set(IDS), (
        f"the wheel's entry points moved: only in wheel {found - set(IDS)}, "
        f"only in this cell {set(IDS) - found}")


def test_bm25_ranks_a_real_query():
    """One real ranking, with real scores, so the load cells above are not the
    whole story: a class that imports but cannot rank is still broken."""
    solver = load_multiple_choice_solver_plugin("ovos-choice-solver-bm25")()
    ranked = solver.rerank(QUERY, OPTIONS, lang="en-us")
    scores = [float(s) for s, _ in ranked]
    assert scores == sorted(scores, reverse=True), scores
    assert scores[0] > scores[1] > 0.0, scores
    assert scores[-1] == 0.0, (
        f"the unrelated option scored {scores[-1]}, so the ranking is not "
        f"discriminating: {scores}")
    assert str(ranked[0][1]) == OPTIONS[0]


def test_select_answer_returns_the_top_option():
    solver = load_multiple_choice_solver_plugin("ovos-choice-solver-bm25")()
    assert str(solver.select_answer(QUERY, OPTIONS, lang="en-us")) == OPTIONS[0]


def test_summarizer_returns_every_sentence():
    solver = load_tldr_solver_plugin("ovos-summarizer-bm25")()
    doc = ("Mycroft is a free and open source voice assistant. "
           "OpenVoiceOS is a continuation of the Mycroft project. "
           "The weather today is sunny and warm in Lisbon.")
    out = solver.tldr(doc, lang="en-us")
    assert isinstance(out, str) and out
    assert "Mycroft is a free and open source voice assistant." in out
