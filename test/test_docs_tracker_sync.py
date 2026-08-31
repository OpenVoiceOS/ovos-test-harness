"""Meta-test: the human-facing trackers must not omit a spec or an xfail.

`docs/coverage.md` claims to be "the authoritative record of which specs the
harness proves conformance against" and `docs/known-gaps.md` claims to
catalogue every clause "where the specs mandate one behavior but the current
ovos-core stack still does the legacy thing." Both are hand-maintained
Markdown, so they drift: a new conformance module ships with no matching
`## OVOS-<ID>` detail section, or a new `xfail` marker lands with no matching
known-gap entry.

This test parses each conformance module's leading docstring for the
`OVOS-<ID>` spec identifier it declares, and separately counts its
xfail-marked tests (mirroring the counting logic of
``test_docstring_xfail_sync.py``). It fails when a declared spec identifier
has no `## OVOS-<ID>` heading in `docs/coverage.md`, or when a module carries
at least one xfail and its spec identifier has no `## OVOS-<ID>` heading in
`docs/known-gaps.md`.

The section-presence checks above are necessary but not sufficient: a
section can exist and still misrepresent a clause it lists as an
unqualified green when the underlying test is `xfail`. A third check closes
that gap: every `xfail`-marked test function (or, for a mark placed on a
whole `TestCase` class, the class) must be named, by its own bare name,
somewhere inside its spec's `## OVOS-<ID>` section of `docs/coverage.md`.
This does not verify the row's prose is accurate, only that the reader can
find the test id at all and see it is not just called green.
"""
import ast
import pathlib
import re

import pytest

CONFORMANCE = pathlib.Path(__file__).parent / "conformance"
CHANNEL_GAPS_DIRS = [
    pathlib.Path(__file__).parent / "conformance",
    pathlib.Path(__file__).parent / "channel_gaps",
]
DOCS = pathlib.Path(__file__).parent.parent / "docs"

SPEC_ID = re.compile(r"OVOS-[A-Z]+(?:-[A-Z]+)*-\d+")
HEADING = re.compile(r"^##\s+.*$", re.MULTILINE)


def _module_files():
    return sorted(CONFORMANCE.glob("test_*_conformance.py"))


def _module_spec_ids(tree):
    """The OVOS-<ID>(s) the module declares as its own, not every spec it
    happens to mention in passing.

    Every module here opens its docstring naming the spec it encodes
    (``"OVOS-<ID> conformance suite"``); a later sentence may reference a
    *different* spec incidentally (e.g. CONTEXT-1's suite describing its
    carrier as "a field of the OVOS-SESSION-1 session"), which is not this
    module's own identity and must not be treated as one. The one documented
    exception is a suite that explicitly covers more than one spec's bus
    contract in the same breath, e.g. "(OVOS-PERSONA-1 and OVOS-FALLBACK-1)"
    — both named together in the same sentence — which is why this returns
    every id from the first sentence rather than only the first match."""
    doc = ast.get_docstring(tree) or ""
    head = doc.split("Coverage map", 1)[0]
    first_sentence = re.split(r"\.\s", head, maxsplit=1)[0]
    return set(SPEC_ID.findall(first_sentence))


def _xfail_alias_names(tree):
    aliases = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if "xfail" in ast.unparse(node.value.func):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases.add(target.id)
    return aliases


def _is_xfail_decorator(dec, aliases):
    text = ast.unparse(dec)
    if text.split("(")[0].endswith("xfail"):
        return True
    return text in aliases


def _has_xfail(tree, aliases):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if any(_is_xfail_decorator(d, aliases) for d in node.decorator_list):
                return True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_") and any(
                    _is_xfail_decorator(d, aliases) for d in node.decorator_list):
                return True
    return False


def _xfail_identifiers(tree, aliases):
    """The bare name of every xfail-marked test — the class name for a
    class-level mark, the function name for a function-level mark."""
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if any(_is_xfail_decorator(d, aliases) for d in node.decorator_list):
                names.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_") and any(
                    _is_xfail_decorator(d, aliases) for d in node.decorator_list):
                names.append(node.name)
    return names


def _sections(doc_name):
    """{heading_line: body_text} for every '## ' heading in the doc."""
    text = (DOCS / doc_name).read_text()
    lines = text.split("\n")
    idx = [i for i, l in enumerate(lines) if l.startswith("## ")]
    idx.append(len(lines))
    return {lines[idx[i]]: "\n".join(lines[idx[i] + 1:idx[i + 1]])
            for i in range(len(idx) - 1)}


def _section_text_for(spec_id, sections):
    return "\n".join(body for heading, body in sections.items() if spec_id in heading)


def _headings(doc_name):
    text = (DOCS / doc_name).read_text()
    return HEADING.findall(text)


@pytest.mark.parametrize("path", _module_files(), ids=lambda p: p.name)
def test_every_declared_spec_has_a_coverage_section(path):
    """A module that names an OVOS-<ID> spec has a matching coverage.md section."""
    tree = ast.parse(path.read_text())
    headings = _headings("coverage.md")
    for spec_id in _module_spec_ids(tree):
        assert any(spec_id in h for h in headings), (
            f"{path.name} declares {spec_id} but docs/coverage.md has no "
            f"'## ...{spec_id}...' section for it.")


@pytest.mark.parametrize("path", _module_files(), ids=lambda p: p.name)
def test_every_xfailing_spec_has_a_known_gap_section(path):
    """A module with at least one xfail has a matching known-gaps.md section."""
    tree = ast.parse(path.read_text())
    aliases = _xfail_alias_names(tree)
    if not _has_xfail(tree, aliases):
        pytest.skip(f"{path.name} carries no xfail")
    headings = _headings("known-gaps.md")
    for spec_id in _module_spec_ids(tree):
        assert any(spec_id in h for h in headings), (
            f"{path.name} carries an xfail for {spec_id} but "
            f"docs/known-gaps.md has no '## ...{spec_id}...' section for it.")


@pytest.mark.parametrize("path", _module_files(), ids=lambda p: p.name)
def test_every_xfailing_test_is_named_in_its_coverage_section(path):
    """An xfail-marked test/class is named by its bare name in the section."""
    tree = ast.parse(path.read_text())
    aliases = _xfail_alias_names(tree)
    identifiers = _xfail_identifiers(tree, aliases)
    if not identifiers:
        pytest.skip(f"{path.name} carries no xfail")
    sections = _sections("coverage.md")
    for spec_id in _module_spec_ids(tree):
        section_text = _section_text_for(spec_id, sections)
        if not section_text:
            continue
        for name in identifiers:
            assert name in section_text, (
                f"{path.name}: {name} is xfail but does not appear by name "
                f"in docs/coverage.md's {spec_id} section — the row for its "
                f"clause cannot be an unqualified 'green'.")


CHANNEL_GAPS = pathlib.Path(__file__).parent / "channel_gaps"
REPO_ROOT = pathlib.Path(__file__).parent.parent


def _channel_gap_node_ids(path):
    """Every non-comment, non-section-header line in a channel-gaps tracker.

    Lines under ``[modules]`` are bare module paths; lines under ``[tests]``
    and ``[xpass]`` are full pytest node ids (``module.py::Class::test``).
    Either way the leading ``module.py`` segment (before the first ``::``,
    if any) is what has to still exist on disk — resolving the rest of the
    node id (class/test name) needs the full conformance stack imported,
    which this meta-test does not have, so module-file existence is as far
    as it checks.
    """
    ids = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        ids.append(line)
    return ids


@pytest.mark.parametrize("path", sorted(CHANNEL_GAPS.glob("*.txt")),
                          ids=lambda p: p.name)
def test_channel_gap_node_ids_reference_existing_modules(path):
    """A known-gap tracker must not list a node id from a deleted module.

    ``test_user_id1_conformance.py`` was deleted (a rejected spec proposal,
    #47) but stayed listed in ``stable.txt``/``testing.txt`` afterward,
    which made the channel-compat job hard-fail at collection ("no tests
    ran") instead of ever reaching the real conformance run. This only
    checks the module file still exists, not that the specific class/test
    the node id names is still inside it — that needs the full conformance
    import stack this meta-test does not build.
    """
    missing = set()
    for node_id in _channel_gap_node_ids(path):
        module = node_id.split("::", 1)[0]
        if not (REPO_ROOT / module).is_file():
            missing.add(module)
    assert not missing, (
        f"{path.name} lists node ids under a module that no longer exists: "
        f"{sorted(missing)}")
