"""The gate probe provider stays wired.

The probe (``test/instruments/gate_probe_provider``) is the instrument that
makes the OCP in-process MediaProvider dispatch reachable. Its whole value is
that OPM discovers it: a probe that installs but does not register is worse
than none, because the drive then measures a dead branch and reads the silence
as agreement between two trees. That is the exact mistake the gate on
ovos-ocp-pipeline-plugin#175 made before the probe existed.

These cells are cheap and offline. They do not install anything. They check
the two things that rot: the entry point and the contract.
"""
import ast
import json
from pathlib import Path

import pytest

from test.instruments import probe

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / probe.PACKAGE
SOURCE = PKG / "gate_probe_provider" / "__init__.py"
PYPROJECT = PKG / "pyproject.toml"

#: OPM's own group for media providers
#: (``ovos_plugin_manager.utils.PluginTypes.MEDIA_PROVIDER``).
GROUP = "opm.media.provider"


def _class_names(path):
    tree = ast.parse(path.read_text())
    return [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]


def test_the_entry_point_names_a_class_that_exists():
    """The rename trap. A class renamed in the source and not in the
    pyproject installs cleanly and is never discovered."""
    text = PYPROJECT.read_text()
    assert f'[project.entry-points."{GROUP}"]' in text, (
        f"the probe must register under {GROUP}, or OPM never finds it:\n{text}")
    line = [l for l in text.splitlines()
            if l.strip().startswith(f"{probe.PROVIDER_NAME} =")]
    assert line, f"no entry point named {probe.PROVIDER_NAME}:\n{text}"
    target = line[0].split("=", 1)[1].strip().strip('"')
    module, _, clazz = target.partition(":")
    assert module == "gate_probe_provider", target
    assert clazz in _class_names(SOURCE), (
        f"the entry point points at {clazz}, which the source does not "
        f"define: {_class_names(SOURCE)}")


def test_the_provider_name_agrees_in_both_files():
    """The helper asserts on this name and the pyproject registers it. If the
    two drift, ``is_discovered`` answers False for a probe that is loaded."""
    assert probe.PROVIDER_NAME in PYPROJECT.read_text()
    assert f'PROVIDER_NAME = "{probe.PROVIDER_NAME}"' in SOURCE.read_text()


def test_search_returns_nothing_so_the_probe_cannot_change_a_match():
    """The property that makes the probe safe to install in a tree under
    measurement: it observes, it never competes."""
    tree = ast.parse(SOURCE.read_text())
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "search"]
    assert len(fn) == 1, "expected exactly one search method"
    returns = [n for n in ast.walk(fn[0]) if isinstance(n, ast.Return)]
    assert len(returns) == 1, "search must have one return"
    value = returns[0].value
    assert isinstance(value, ast.List) and not value.elts, (
        "search must return a literal empty list, so the probe can never "
        "promote a release or move a confidence")


def test_read_log_reads_what_the_provider_writes(tmp_path):
    """The reader and the writer agree on the format, checked against a line
    the provider's own code path produces rather than a hand-written one."""
    row = {"lang": "en-us", "title": "music music", "medium": "None",
           "role": "None", "session_id": None}
    log = tmp_path / "probe.jsonl"
    log.write_text(json.dumps(row, ensure_ascii=False) + "\n")
    assert probe.read_log(log) == [row]
    assert probe.titles(probe.read_log(log)) == ["music music"]


def test_a_missing_log_is_no_searches_not_an_error(tmp_path):
    """A dead dispatch branch writes no file at all. That is a measurement,
    and the caller must be able to assert on it."""
    assert probe.read_log(tmp_path / "never-written.jsonl") == []


def test_a_truncated_last_line_does_not_lose_the_rows_before_it(tmp_path):
    """A killed drive leaves a half-written final line."""
    log = tmp_path / "probe.jsonl"
    log.write_text('{"title": "one"}\n{"title": "tw')
    assert probe.titles(probe.read_log(log)) == ["one"]


def test_the_instrument_is_not_installed_by_the_harness_requirements():
    """The probe is an instrument, not a member of the stack under test. If
    it ever appears in requirements.txt it would be installed into every tree
    a verdict is recorded against."""
    assert "gate-probe-provider" not in (ROOT / "requirements.txt").read_text()
