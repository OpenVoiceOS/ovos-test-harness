"""Findings feed for the mixed-version back-compat matrix (design §4.2).

Collects one record per ``xfail``/``xpass`` test observed in a pytest run of
``test/backcompat/`` and writes ``backcompat-findings-<cell>.json`` so a CI
workflow can aggregate red boundaries across cells without re-running
anything (see ``.github/workflows/backcompat_matrix.yml``'s ``summarize``
job).

Field provenance, per the design doc:

* ``cell`` / ``scenario`` come from the test's own context: ``cell`` from
  ``BACKCOMPAT_COMBO`` (resolved through ``cells.resolve_cell`` when it is a
  boundary alias, else the raw combo name for a channel cell), ``scenario``
  from the test's nodeid (module stem + test name) -- no separate scenario
  fixture exists today, so the nodeid is the closest thing to a directly
  observed value rather than a guess.
* ``axes`` comes from the test's own ``@pytest.mark.axes(...)`` marker, the
  same marker ``conftest.py``'s pruning hook already reads.
* ``boundary`` / ``blocked_on`` / ``owner`` come from the xfail reason
  string.

As of this writing (2026-08), ``driver.py`` does not define a
``boundary_xfail()`` helper -- ``test_mixed_version_matrix.py``'s xfail
reasons are hand-written prose (see e.g. ``_XFAIL_REASON`` there), not the
structured ``boundary_xfail(boundary=..., axes=..., blocked_on=...,
owner=..., note=...)`` call the design doc sketches as a future convention.
``parse_reason`` below therefore does two things, in order:

1. tries to match the *future* structured-call form, in case a later PR
   (owned outside this change's scope -- see ``CONTRIBUTING.md``) starts
   rendering reasons that way;
2. falls back to a heuristic extraction over today's free-text reasons: an
   ``owner#123``-shaped token becomes ``blocked_on`` (and its ``owner``
   prefix becomes ``owner``), and the reason text itself becomes
   ``boundary`` since there is no structured boundary field to pull out yet.

This keeps the findings feed useful today without inventing or editing the
``boundary_xfail`` helper itself -- that stays out of scope for this change
(owned by PR #32 / the in-flight T2.5 branch, per the driver.py module this
file only ever imports read-only).
"""
import json
import os
import re
from typing import Dict, List, Optional

#: Matches a future structured ``boundary_xfail(boundary="...", axes=(...),
#: blocked_on="..." | None, owner="...", note="...")`` reason, if one is ever
#: rendered verbatim into a reason string. Fields are matched independently
#: (not order-locked) since a renderer is free to lay out kwargs however it
#: likes.
_STRUCTURED_FIELD_RE = {
    "boundary": re.compile(r"""boundary\s*=\s*(['"])(?P<val>.*?)\1"""),
    "blocked_on": re.compile(
        r"""blocked_on\s*=\s*(?:(['"])(?P<val>.*?)\1|(?P<none>None))"""),
    "owner": re.compile(r"""owner\s*=\s*(['"])(?P<val>.*?)\1"""),
}

#: Heuristic fallback: an ``<owner>#<issue-number>`` token in free prose,
#: e.g. "ovos-bus-client#271" or "ovos-workshop#500". Owner names in this
#: repo's reasons are lowercase, hyphenated package/repo names.
_ISSUE_REF_RE = re.compile(r"\b([a-z][a-z0-9-]*)#(\d+)\b")


def _is_structured(reason: str) -> bool:
    return "boundary_xfail(" in reason


def parse_reason(reason: str) -> Dict[str, Optional[str]]:
    """Best-effort extraction of ``{boundary, blocked_on, owner}`` from an
    xfail ``reason`` string. See the module docstring for why this is a
    two-tier (structured-then-heuristic) parse rather than a single regex."""
    if _is_structured(reason):
        out: Dict[str, Optional[str]] = {}
        for field, pattern in _STRUCTURED_FIELD_RE.items():
            m = pattern.search(reason)
            if not m:
                out[field] = None
                continue
            if field == "blocked_on" and m.group("none"):
                out[field] = None
            else:
                out[field] = m.group("val")
        return out

    m = _ISSUE_REF_RE.search(reason)
    blocked_on = m.group(0) if m else None
    owner = m.group(1) if m else None
    return {"boundary": reason, "blocked_on": blocked_on, "owner": owner}


def resolve_cell_label(combo: str) -> str:
    """The ``cell`` field for a findings record: the resolved 4-tuple
    boundary-cell id when ``combo`` is one of the boundary aliases, else the
    raw combo name (channel cells, or anything ``cells.py`` doesn't
    recognize -- an unrecognized combo is itself worth recording as-is
    rather than dropping the finding silently)."""
    from .cells import resolve_cell
    return resolve_cell(combo) or combo


def _findings_filename(cell: str) -> str:
    # combo/cell names like "old-skill/new-core" contain "/", which is not
    # safe in a bare filename (and would be read as a subdirectory).
    safe = cell.replace("/", "-")
    return f"backcompat-findings-{safe}.json"


#: Matches the summary line pytest's own xfail plugin writes into
#: ``report.longrepr`` for a STRICT xpass -- e.g. ``"[XPASS(strict)] <reason
#: text>"``. This is the fallback source for the reason on a strict xpass:
#: verified live (this module's own T2.6 smoke test, run against
#: pytest 9.1.1) that ``report.wasxfail`` is **not** populated on the
#: ``call``-phase report for a strict xpass -- only ``report.longrepr``
#: carries the reason at that point, unlike the genuine-xfail path where
#: ``wasxfail`` is set directly. Kept as a fallback (checked only when
#: ``wasxfail`` is absent) rather than the primary path, since a future
#: pytest could restore ``wasxfail`` there and the direct attribute is the
#: more stable contract when present.
_STRICT_XPASS_LONGREPR_RE = re.compile(r"^\[XPASS\(strict\)\]\s*(?P<reason>.*)",
                                       re.S)

#: One record per xfailed/xpassed test, populated by ``pytest_runtest_
#: logreport`` in real time as the run proceeds (see conftest.py). A
#: terminal-summary-time pass over ``terminalreporter.stats`` was tried
#: first and dropped: on pytest 9.1.1 a strict-xpass's ``call`` report
#: carries ``wasxfail=None`` by the time stats are consulted, only
#: ``report.longrepr`` still has the reason -- collecting records live, one
#: report at a time, is what makes both paths (genuine xfail and strict
#: xpass) reachable the same way.
_RECORDS: List[dict] = []
#: nodeids already recorded this session, guarding against a double record
#: if a node somehow produced an xfail outcome on more than one phase.
_RECORDED_NODEIDS: set = set()


def reset_records() -> None:
    """Clear accumulated records. Called at the start of a session so a
    findings feed from a previous ``pytest.main()`` call in the same
    process (e.g. this module's own test-suite) never leaks into the next
    one."""
    _RECORDS.clear()
    _RECORDED_NODEIDS.clear()


def record_report(report, axes_by_nodeid: Dict[str, tuple]) -> None:
    """Inspect one test report and, if it carries an xfail outcome (genuine
    xfail or xpass, strict or not), append a record. Called from
    ``pytest_runtest_logreport`` for every report; non-xfail reports are
    no-ops.

    Both the ``call`` and ``setup`` phases are considered: an xfail whose
    real failure happens inside a fixture (verified live -- this cell's own
    ``stack`` fixture raises long before any test body runs, when the venv
    pair it needs isn't built) is reported by pytest against the ``setup``
    report, not ``call``; only genuinely passing-until-the-body-runs cases
    reach ``call``. A node only ever produces one of the two, so there is no
    double-counting risk in checking both.
    """
    if getattr(report, "when", None) not in ("call", "setup"):
        return

    reason = getattr(report, "wasxfail", None)
    if reason is not None:
        # report.skipped + wasxfail => genuine xfail (the expected failure
        # was raised; pytest represents that outcome as a skip).
        # report.passed + wasxfail => non-strict xpass.
        outcome = "xfail" if report.skipped else "xpass"
    elif report.failed:
        # strict xpass: pytest deliberately fails the test, and (verified
        # live against pytest 9.1.1 -- see _STRICT_XPASS_LONGREPR_RE above)
        # does not populate wasxfail on this report; the reason only
        # survives in longrepr's "[XPASS(strict)] <reason>" line.
        m = _STRICT_XPASS_LONGREPR_RE.match(str(report.longrepr or "").strip())
        if not m:
            return
        reason = m.group("reason").strip()
        outcome = "xpass"
    else:
        return

    if report.nodeid in _RECORDED_NODEIDS:
        return
    _RECORDED_NODEIDS.add(report.nodeid)

    combo = os.environ.get("BACKCOMPAT_COMBO", "")
    cell = resolve_cell_label(combo) if combo else "<no-combo>"
    parsed = parse_reason(reason)
    _RECORDS.append({
        "cell": cell,
        "scenario": report.nodeid,
        "axes": list(axes_by_nodeid.get(report.nodeid, ())),
        "boundary": parsed["boundary"],
        "blocked_on": parsed["blocked_on"],
        "owner": parsed["owner"],
        "outcome": outcome,
    })


def write_findings(out_dir: str = ".",
                    exitstatus: Optional[int] = None) -> Optional[str]:
    """Write ``backcompat-findings-<cell>.json`` for this run, from records
    accumulated in ``_RECORDS`` over the session. Returns the path written,
    or ``None`` when there was no combo selected at all (a bare ``pytest
    test/backcompat/`` with no ``BACKCOMPAT_COMBO`` -- nothing cell-scoped
    to report).

    ``exitstatus`` is pytest's own ``pytest_terminal_summary`` exitstatus
    argument, threaded through from ``conftest.py``'s hook. It is recorded
    verbatim in the written file so a cell that died at collection (e.g. an
    import-time ``assert`` in ``test_mixed_version_matrix.py``) produces a
    file distinguishable from a clean run -- prior to this, this function
    wrote a bare ``[]`` records list with no run-status field at all, so a
    cell that exploded before a single test ran looked byte-identical to a
    cell that passed cleanly with zero xfail/xpass records (both empty
    lists). The file is now an object, ``{"cell", "combo", "exitstatus",
    "records"}``, so the ``summarize`` job in
    ``.github/workflows/backcompat_matrix.yml`` can tell the two apart and
    render a "cells that did not complete" section. ``combo`` (the raw
    ``BACKCOMPAT_COMBO`` value, distinct from ``cell`` which is the
    *resolved* boundary-cell id for boundary combos) is what lets that job
    detect a cell that produced NO findings file at all -- a venv build
    failure before pytest ever runs uploads nothing, and
    ``download-artifact`` with a ``pattern:`` succeeds on zero matches, so
    that case was previously invisible; ``generate-matrix``'s own
    ``combos`` output is diffed against every downloaded file's ``combo``
    to catch it. ``None`` means the caller didn't have an exitstatus to
    give (kept optional so direct/older callers -- e.g. this module's own
    tests -- don't have to supply one)."""
    combo = os.environ.get("BACKCOMPAT_COMBO", "")
    if not combo:
        return None
    cell = resolve_cell_label(combo)
    path = os.path.join(out_dir, _findings_filename(cell))
    payload = {
        "cell": cell,
        "combo": combo,
        "exitstatus": exitstatus,
        "records": _RECORDS,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    return path
