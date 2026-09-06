"""Meta-test: the spec corpus drives the trackers, not the other way round.

`test_docs_tracker_sync.py` walks the harness's own conformance modules, so a
spec the harness never noticed is invisible to it — an entire document can be
ratified upstream and leave every tracker green. These cells walk the pinned
architecture corpus instead.

Two things are asserted. Every spec the corpus README indexes has a
`## OVOS-<ID>` section in `docs/coverage.md`, so a spec cannot exist without a
row stating what the harness does about it. And every numbered section of every
spec is either cited by that spec's conformance suite, admitted in
`docs/known-gaps.md`, or listed in `uncited-sections.txt` — a ratchet whose
entries can only be removed. Citing a section is a weak signal (a suite that
names §4.2 once may assert one of its thirteen clauses), so the ratchet is a
floor on honesty, not a coverage measure.
"""
import pathlib
import re

from .spec_corpus import sections, specs

HERE = pathlib.Path(__file__).parent
DOCS = HERE.parent.parent / "docs"
CONFORMANCE = HERE.parent / "conformance"
ALLOWLIST = HERE / "uncited-sections.txt"

_SUITE = re.compile(r"`(test_\w+\.py)`")


def _coverage_sections():
    """`{spec_id: section text}` for each `## OVOS-<ID>` block of coverage.md."""
    return _doc_sections(DOCS / "coverage.md")


def _doc_sections(path):
    out = {}
    current = []
    for line in path.read_text().split("\n"):
        if line.startswith("## "):
            current = re.findall(r"OVOS-[A-Z0-9-]+", line)
            for spec_id in current:
                out.setdefault(spec_id, [])
        elif current:
            for spec_id in current:
                out[spec_id].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def _matrix_suites():
    """`{spec_id: [suite path]}` read off the coverage.md top-level matrix."""
    out = {}
    for line in (DOCS / "coverage.md").read_text().split("\n"):
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 5 or not cells[2].startswith("OVOS-"):
            continue
        out[cells[2]] = [CONFORMANCE / name for name in _SUITE.findall(cells[3])]
    return out


def _cited(text, number):
    """True if `text` cites section `number` — `§4.1` does not match `§4.10`."""
    return re.search(rf"§{re.escape(number)}(?![\d.]|\.\d)", text) is not None


def _uncited():
    suites = _matrix_suites()
    gaps = _doc_sections(DOCS / "known-gaps.md")
    out = []
    for spec_id, path in sorted(specs().items()):
        cited = "\n".join(p.read_text() for p in suites.get(spec_id, [])
                          if p.is_file())
        admitted = gaps.get(spec_id, "")
        for number in sections(path):
            if not (_cited(cited, number) or _cited(admitted, number)):
                out.append(f"{path.name} §{number}")
    return out


def _allowlist():
    return [line.strip() for line in ALLOWLIST.read_text().split("\n")
            if line.strip() and not line.startswith("#")]


def test_every_spec_has_a_coverage_section():
    documented = _coverage_sections()
    missing = sorted(set(specs()) - set(documented))
    assert not missing, (
        f"architecture specs with no `## <id>` section in docs/coverage.md: "
        f"{missing}")


def test_coverage_matrix_counts_the_corpus():
    """The matrix's prose count is the corpus count, not a remembered one."""
    text = (DOCS / "coverage.md").read_text()
    assert f"carries {len(specs())} specs" in text, (
        f"docs/coverage.md does not state the corpus size "
        f"({len(specs())} specs)")


def test_no_new_uncited_section():
    new = sorted(set(_uncited()) - set(_allowlist()))
    assert not new, (
        f"spec sections cited by no suite and admitted in no known-gaps "
        f"entry: {new}. Assert them, add a known-gaps row, or — if the clause "
        f"is genuinely not observable — say so in the suite and cite the "
        f"section there.")


def test_uncited_allowlist_only_shrinks():
    stale = sorted(set(_allowlist()) - set(_uncited()))
    assert not stale, (
        f"test/meta/uncited-sections.txt lists sections that are now covered: "
        f"{stale}. Drop them from the file — the list is a ratchet.")
