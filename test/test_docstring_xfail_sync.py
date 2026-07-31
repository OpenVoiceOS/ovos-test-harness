"""Meta-test: a suite's coverage map must match its decorators.

Every conformance module opens with a *coverage map* — one line per spec
clause, ending in the clause's status against the stack under test::

    - §6.4 exactly one ``ovos.utterance.handled`` .................. green
    - §2.1 ``session.converse_handlers`` reflects the owner ........ xfail

That map is what a reader trusts when deciding whether a clause is covered.
It drifts: a clause is fixed upstream and the xfail is deleted, but the map
still says xfail — or the map claims nine xfails and the file has one.

This test parses each module's map, counts the lines marked ``xfail``, and
compares that with the number of test functions the file actually marks
xfail. Drift fails CI instead of quietly misleading the next reader.

The map is documentation, so the comparison is by count, not by clause: write
one ``xfail`` map line per xfail-marked test, or per xfail-marked class (a
class mark covers one clause however many methods it holds).
"""
import ast
import pathlib
import re

import pytest

CONFORMANCE = pathlib.Path(__file__).parent / "conformance"

#: a coverage-map line: "- §4.2 some text ..... status"
MAP_LINE = re.compile(r"^\s*-\s+\S*\s*§.*?\.{2,}\s*(?P<status>\S+)", re.MULTILINE)


def _module_files():
    return sorted(CONFORMANCE.glob("test_*_conformance.py"))


def _xfail_alias_names(tree):
    """Module-level names bound to a ``pytest.mark.xfail(...)`` mark."""
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


def _count_xfailed_tests(tree, aliases):
    """How many xfail marks the file carries.

    A mark on a test function counts once. A mark on a class counts once too:
    it states one clause, whatever number of methods the class holds.
    """
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if any(_is_xfail_decorator(d, aliases) for d in node.decorator_list):
                count += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_") and any(
                    _is_xfail_decorator(d, aliases) for d in node.decorator_list):
                count += 1
    return count


def _count_map_xfails(docstring):
    return sum(1 for m in MAP_LINE.finditer(docstring or "")
               if m.group("status").lower().startswith("xfail"))


@pytest.mark.parametrize("path", _module_files(), ids=lambda p: p.name)
def test_coverage_map_matches_decorators(path):
    """The docstring coverage map declares as many xfails as the file marks."""
    tree = ast.parse(path.read_text())
    aliases = _xfail_alias_names(tree)
    declared = _count_map_xfails(ast.get_docstring(tree))
    actual = _count_xfailed_tests(tree, aliases)
    assert declared == actual, (
        f"{path.name}: the coverage map declares {declared} xfail clause(s) "
        f"but the file carries {actual} xfail mark(s). Update the map in the "
        f"module docstring (one 'xfail' map line per xfail mark).")
