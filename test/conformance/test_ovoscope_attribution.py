"""Guard: every ovoscope registration call-site carries skill_id.

ovoscope made ``skill_id`` a keyword-only argument on its registration helpers
and warns it "becomes required in 1.9.0". A registration emitted without
``skill_id`` carries no ``message.context['skill_id']`` and the engines
correctly reject it, since skill_id is intent identity (OVOS-INTENT-4 §3.2).

The set of helpers to guard is DERIVED from the installed ovoscope -- every
module-level function that takes a keyword-only ``skill_id`` -- rather than
hand-listed. A hardcoded list silently misses a helper ovoscope adds or one the
author forgot (``register_intent_case_tests`` was missed exactly that way), which
would reproduce the very bug this guard exists to prevent.
"""
import ast
import importlib
import inspect
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_FILE = TEST_ROOT / "conformance" / "_ovoscope_unattributed_allowlist.txt"


def _attributed_funcs() -> set[str]:
    """Names of every module-level ovoscope helper with a keyword-only
    ``skill_id`` parameter, read from the installed package."""
    names: set[str] = set()
    for modname in ("ovoscope", "ovoscope.e2e"):
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        for name, obj in vars(mod).items():
            if not inspect.isfunction(obj):
                continue
            try:
                param = inspect.signature(obj).parameters.get("skill_id")
            except (ValueError, TypeError):
                continue
            if param is not None and param.kind is inspect.Parameter.KEYWORD_ONLY:
                names.add(name)
    return names


def _allowlist() -> set[tuple[str, int]]:
    if not ALLOWLIST_FILE.exists():
        return set()
    out = set()
    for line in ALLOWLIST_FILE.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        rel, _, lineno = line.partition(":")
        out.add((rel.strip(), int(lineno)))
    return out


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _has_skill_id(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "skill_id" or kw.arg is None:  # kw.arg is None => **kwargs spread
            return True
    return False


def test_every_ovoscope_registration_call_carries_skill_id():
    funcs = _attributed_funcs()
    if not funcs:
        pytest.skip(
            "ovoscope's skill_id-bearing helpers are not introspectable here "
            "(e.g. the pre-1.0 testing channel with no e2e module); the "
            "conformance suite that calls them does not run in this environment "
            "either, so there is nothing to guard.")
    allow = _allowlist()
    violations = []
    for path in sorted(TEST_ROOT.rglob("*.py")):
        rel = str(path.relative_to(TEST_ROOT))
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) in funcs \
                    and not _has_skill_id(node) \
                    and (rel, node.lineno) not in allow:
                violations.append((rel, node.lineno, _call_name(node)))
    if violations:
        lines = "\n".join(
            f"  {rel}:{lineno} -> {name}(...) is missing skill_id="
            for rel, lineno, name in violations)
        pytest.fail(
            "ovoscope registration call-site(s) without skill_id= (skill_id is "
            "intent identity, OVOS-INTENT-4 §3.2; an unattributed registration is "
            "rejected). Guarded helpers derived from the installed ovoscope: "
            f"{sorted(funcs)}\n{lines}\nAdd skill_id=, or if a call deliberately "
            f"tests the rejection path, admit it in {ALLOWLIST_FILE.name}.")
