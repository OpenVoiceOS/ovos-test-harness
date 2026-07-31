"""Pytest bootstrap for the OVOS cross-repo conformance harness.

Ensures the repository root is importable so the conformance suites resolve
their ``test.conformance`` package (the suites use relative imports against the
``_conformance`` helper module).

It also enforces the collection floor: on a run that claims to install the full
stack (``OVOS_CONFORMANCE_EXPECT_FULL=1``, set by the integration workflow), a
conformance module that collects zero tests is an install failure, not a quiet
green. See ``test/test_install_floor.py`` for the import-level companion.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

CONFORMANCE_DIR = os.path.join(os.path.dirname(__file__), "test", "conformance")


def _expected_conformance_modules():
    """Every ``test_*_conformance.py`` file that must yield tests."""
    if not os.path.isdir(CONFORMANCE_DIR):
        return set()
    return {name for name in os.listdir(CONFORMANCE_DIR)
            if name.startswith("test_") and name.endswith(".py")}


def pytest_collection_modifyitems(session, config, items):
    """Fail the run when a conformance module contributed no tests."""
    if os.environ.get("OVOS_CONFORMANCE_EXPECT_FULL") != "1":
        return
    if config.option.keyword or config.option.markexpr:
        return  # a filtered run is expected to collect a subset
    collected = {os.path.basename(str(item.fspath)) for item in items}
    missing = sorted(_expected_conformance_modules() - collected)
    if missing:
        raise pytest.UsageError(
            "OVOS_CONFORMANCE_EXPECT_FULL=1 but these conformance modules "
            f"collected no tests (broken install?): {missing}")
