"""Pytest bootstrap for the OVOS cross-repo conformance harness.

Ensures the repository root is importable so the conformance suites resolve
their ``test.conformance`` package (the suites use relative imports against the
``_conformance`` helper module).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
