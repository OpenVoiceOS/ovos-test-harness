"""Regression coverage for adversarial-review findings against PR #33
(``feat/backcompat-findings-reporting``), across two review rounds.

Round 1:

* FIX 1 -- a cell that dies at collection (an import-time ``assert`` in
  ``test_mixed_version_matrix.py``, or any other collection error) used to
  write a ``backcompat-findings-<cell>.json`` byte-identical to a clean
  cell's (both a bare ``[]``). ``write_findings`` now threads pytest's own
  ``exitstatus`` into the file.

* FIX 2 -- ``generate-matrix``'s inline python silently drops any cell
  whose ``tier`` isn't exactly ``"boundary"`` or ``"channel"``, with exit 0
  and zero signal. It now asserts the whitelist up front.

Round 2 (re-review of the round-1 fix):

* FIX 1b -- the round-1 fix only covered a cell that ran pytest and got a
  non-zero exitstatus. A cell whose venv build fails BEFORE pytest ever
  runs uploads no findings artifact at all, and
  ``actions/download-artifact`` with a ``pattern:`` succeeds on zero
  matches -- that cell was still completely invisible. ``generate-matrix``
  now also outputs the combo names it selected (independent of whether
  each one's matrix job ever uploaded anything), and ``summarize`` diffs
  that against every ``combo`` it actually found, listing anything missing
  under "did not complete" with exitstatus ``"no artifact"``.

* FIX 2b -- the round-1 "did not complete" section lumped genuine test
  failures (exitstatus 1 -- the cell DID complete, pytest just found a
  real regression) in with cells that never produced a normal result
  (collection errors, crashes: exitstatus >= 2 or unknown). Split into
  "Cells red" (== 1) and "Cells that did not complete" (>= 2 / unknown /
  missing artifact).

* FIX 3b -- the red-boundaries table row scrubbed ``boundary``/
  ``scenarios`` for ``|``/newline but not ``blocked_on``/``owner``, which
  come from the same author-written xfail-reason source and can just as
  legally contain a ``|`` (e.g. inside a quoted structured-reason value).
  Both are now scrubbed too.

All four fixes live inside inline python embedded in the workflow YAML's
``run:`` blocks, not in an importable module, so these tests extract the
actual step scripts out of the checked-in YAML (via PyYAML) and execute
them as real subprocesses -- this exercises the exact bytes that run in
CI, not a hand-copied reimplementation that could drift from it.
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest
import yaml

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKFLOW_PATH = os.path.join(_REPO_ROOT, ".github", "workflows", "backcompat_matrix.yml")


def _load_workflow():
    with open(_WORKFLOW_PATH) as f:
        return yaml.safe_load(f)


def _step_script(job_id: str, step_name: str) -> str:
    """Pull the python heredoc body out of a named step's ``run:`` block."""
    wf = _load_workflow()
    job = wf["jobs"][job_id]
    for step in job["steps"]:
        if step.get("name") == step_name:
            run = step["run"]
            break
    else:
        raise AssertionError(f"step {step_name!r} not found in job {job_id!r}")
    # The steps in this file all follow the same
    # `python3 - <<'PYEOF' ... PYEOF` shape.
    assert "<<'PYEOF'" in run, f"step {step_name!r} isn't a python heredoc"
    body = run.split("<<'PYEOF'", 1)[1]
    body = body.rsplit("PYEOF", 1)[0]
    return textwrap.dedent(body)


def _run_summarize(script, findings_dir, tmp_path, expected_combos=None, extra_env=None):
    """Shared harness: runs the real extracted summarize script against a
    prepared ``findings/`` dir and returns (returncode, stderr,
    SPRINT.md text or None)."""
    workdir = tmp_path / "run"
    workdir.mkdir(exist_ok=True)
    link = workdir / "findings"
    if not link.exists():
        link.symlink_to(findings_dir)

    env = dict(os.environ)
    env.pop("GITHUB_STEP_SUMMARY", None)
    env["SUMMARY_DATE"] = "2026-08-13T00:00:00Z"
    env["GITHUB_SERVER_URL"] = "https://github.com"
    env["GITHUB_REPOSITORY"] = "OpenVoiceOS/ovos-test-harness"
    env["GITHUB_RUN_ID"] = "12345"
    env["EXPECTED_COMBOS"] = json.dumps(expected_combos or [])
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(workdir), env=env, capture_output=True, text=True, timeout=30,
    )
    sprint_path = workdir / "FINDINGS" / "SPRINT.md"
    sprint_md = sprint_path.read_text() if sprint_path.exists() else None
    return result.returncode, result.stderr, sprint_md


# ---------------------------------------------------------------------
# FIX 1 / FIX 1b: write_findings() records exitstatus + combo, and the
# summarizer surfaces both a non-zero exitstatus AND a missing artifact
# under "Cells that did not complete".
# ---------------------------------------------------------------------

def test_write_findings_records_exitstatus_and_combo(tmp_path, monkeypatch):
    """Unit-level: a cell that dies at collection (exitstatus != 0) writes
    a findings file distinguishable from a clean cell's, via the new
    ``exitstatus`` field -- prior to the fix both wrote a bare ``[]`` with
    no run-status field at all. Also asserts the raw ``combo`` (distinct
    from the resolved ``cell``) is now recorded, which FIX 1b's
    missing-artifact diff depends on."""
    from test.backcompat import findings

    monkeypatch.setenv("BACKCOMPAT_COMBO", "old-skill/old-core")
    findings.reset_records()

    clean_path = findings.write_findings(out_dir=str(tmp_path), exitstatus=0)
    with open(clean_path) as f:
        clean = json.load(f)

    died_path = findings.write_findings(out_dir=str(tmp_path), exitstatus=2)
    with open(died_path) as f:
        died = json.load(f)

    assert clean["exitstatus"] == 0
    assert died["exitstatus"] == 2
    assert clean["combo"] == died["combo"] == "old-skill/old-core"
    # Both have empty records (no test ever ran in the died case), so the
    # exitstatus field is the ONLY thing telling them apart -- the exact
    # defect: before the fix, `clean == died` byte-for-byte.
    assert clean["records"] == died["records"] == []
    assert clean != died


def test_conftest_hook_passes_exitstatus_to_write_findings(monkeypatch, tmp_path):
    """``pytest_terminal_summary`` must forward the ``exitstatus`` argument
    pytest hands it, not discard it (the exact bug: the hook signature
    already receives ``exitstatus`` but the old call site,
    ``findings.write_findings()``, never passed it on)."""
    import test.backcompat.conftest as bc_conftest
    import test.backcompat.findings as real_findings

    seen = {}

    def _fake_write_findings(out_dir=".", exitstatus=None):
        seen["exitstatus"] = exitstatus
        return None

    # Patch only `write_findings` on the real, already-imported module --
    # NOT the whole module object -- so `record_report` (used by this very
    # pytest session's own live conftest hooks, which import the same
    # module) keeps working while this test runs.
    monkeypatch.setattr(real_findings, "write_findings", _fake_write_findings)

    class _FakeTerminalReporter:
        def write_line(self, *a, **k):
            pass

    bc_conftest.pytest_terminal_summary(_FakeTerminalReporter(), 3, config=None)
    assert seen["exitstatus"] == 3


def test_summarize_step_lists_incomplete_cells_at_top(tmp_path):
    """Runs the ACTUAL summarize-job python (extracted from the workflow
    YAML) against fabricated findings files -- one clean, one from a cell
    that died at collection (new object shape, exitstatus=2) -- and
    asserts SPRINT.md's "did not complete" section (now second, after the
    new "Cells red" section -- see FIX 2b) calls the dead one out. Also
    feeds one old-shape (bare list) findings file through, to prove the
    backward-read tolerance still holds."""
    script = _step_script("summarize", "Render FINDINGS/SPRINT.md")

    findings_dir = tmp_path / "findings"
    findings_dir.mkdir()

    (findings_dir / "backcompat-findings-0.json").write_text(json.dumps({
        "cell": "Sold-Cold-Mold-Anew", "combo": "old-skill/old-core",
        "exitstatus": 0, "records": [],
    }))
    (findings_dir / "backcompat-findings-1.json").write_text(json.dumps({
        "cell": "Sold-Cnew-Mnew-Anew", "combo": "old-skill/new-core",
        "exitstatus": 2, "records": [],
    }))
    # old shape: a bare list, no exitstatus/combo at all -- must be
    # tolerated, not crash the summarizer.
    (findings_dir / "backcompat-findings-2.json").write_text(json.dumps([]))

    returncode, stderr, sprint_md = _run_summarize(
        script, findings_dir, tmp_path,
        expected_combos=["old-skill/old-core", "old-skill/new-core"])
    assert returncode == 0, stderr

    assert "## Cells that did not complete" in sprint_md
    assert sprint_md.index("## Cells red") < sprint_md.index(
        "## Cells that did not complete") < sprint_md.index("## XPASS")
    assert "Sold-Cnew-Mnew-Anew" in sprint_md
    # The clean cell must NOT be listed as incomplete.
    not_complete_section = sprint_md.split("## Cells that did not complete", 1)[1]
    not_complete_section = not_complete_section.split("## XPASS", 1)[0]
    assert "Sold-Cold-Mold-Anew" not in not_complete_section


def test_summarize_flags_a_cell_with_no_artifact_at_all(tmp_path):
    """FIX 1b, red-before/green-after target: `generate-matrix` selected
    TWO combos for this run (``EXPECTED_COMBOS``), but only one findings
    file was ever uploaded -- e.g. the other cell's venv build failed
    before pytest ran, so ``conftest.py``'s `write_findings()` never even
    executed for it. Prior to FIX 1b this cell was invisible: the
    "did not complete" section only reads uploaded files, and
    ``download-artifact``'s ``pattern:`` glob is happy to match zero
    files. The missing combo must now appear under "did not complete"
    with exitstatus "no artifact"."""
    script = _step_script("summarize", "Render FINDINGS/SPRINT.md")

    findings_dir = tmp_path / "findings"
    findings_dir.mkdir()
    (findings_dir / "backcompat-findings-0.json").write_text(json.dumps({
        "cell": "Sold-Cold-Mold-Anew", "combo": "old-skill/old-core",
        "exitstatus": 0, "records": [],
    }))
    # Nothing uploaded at all for "new-skill/old-core" -- simulates a
    # build failure in the `matrix` job before the "Run the combo" /
    # "Upload the findings feed" steps ever ran.

    returncode, stderr, sprint_md = _run_summarize(
        script, findings_dir, tmp_path,
        expected_combos=["old-skill/old-core", "new-skill/old-core"])
    assert returncode == 0, stderr

    not_complete_section = sprint_md.split("## Cells that did not complete", 1)[1]
    not_complete_section = not_complete_section.split("## XPASS", 1)[0]
    assert "new-skill/old-core" in not_complete_section
    assert "no artifact" in not_complete_section
    # The cell that DID report in (and passed cleanly) must not be flagged.
    assert "old-skill/old-core" not in not_complete_section


def test_summarize_puts_real_test_failures_in_cells_red_not_did_not_complete(tmp_path):
    """FIX 2b, red-before/green-after target: exitstatus 1 means pytest
    ran to completion and found a genuine failure -- that's DIFFERENT from
    a cell that never produced a result at all (collection death, crash).
    Before FIX 2b both landed under the same "did not complete" heading
    (``exitstatus not in (0, None)``), burying real regressions among
    infra flakes. exitstatus 1 must land under "Cells red" only;
    exitstatus 2 must land under "did not complete" only."""
    script = _step_script("summarize", "Render FINDINGS/SPRINT.md")

    findings_dir = tmp_path / "findings"
    findings_dir.mkdir()
    (findings_dir / "backcompat-findings-0.json").write_text(json.dumps({
        "cell": "red-cell", "combo": "old-skill/old-core",
        "exitstatus": 1, "records": [],
    }))
    (findings_dir / "backcompat-findings-1.json").write_text(json.dumps({
        "cell": "dead-cell", "combo": "old-skill/new-core",
        "exitstatus": 2, "records": [],
    }))

    returncode, stderr, sprint_md = _run_summarize(
        script, findings_dir, tmp_path,
        expected_combos=["old-skill/old-core", "old-skill/new-core"])
    assert returncode == 0, stderr

    red_section = sprint_md.split("## Cells red", 1)[1]
    red_section = red_section.split("## Cells that did not complete", 1)[0]
    not_complete_section = sprint_md.split("## Cells that did not complete", 1)[1]
    not_complete_section = not_complete_section.split("## XPASS", 1)[0]

    assert "red-cell" in red_section
    assert "red-cell" not in not_complete_section
    assert "dead-cell" in not_complete_section
    assert "dead-cell" not in red_section


# ---------------------------------------------------------------------
# FIX 3b: the red-boundaries table row must scrub `|`/newline out of
# blocked_on/owner too, not just boundary/scenarios.
# ---------------------------------------------------------------------

def test_red_boundaries_row_scrubs_blocked_on_and_owner(tmp_path):
    """Mutation-proof target for the re-reviewer's own finding that the
    first pass's 5 tests stayed green even with `_scrub(boundary)` and
    `_scrub(scenarios)` gutted back to raw interpolation -- this test
    exercises `blocked_on`/`owner` specifically, whose own scrub calls
    were the actual gap, and asserts the table stays well-formed (one row
    per boundary, correct column count) even when those fields carry a
    literal `|` and a newline -- exactly like a hand-written xfail reason
    such as ``"breaks | on old core\\nowner#123"`` would."""
    script = _step_script("summarize", "Render FINDINGS/SPRINT.md")

    findings_dir = tmp_path / "findings"
    findings_dir.mkdir()
    (findings_dir / "backcompat-findings-0.json").write_text(json.dumps({
        "cell": "Sold-Cold-Mold-Anew", "combo": "old-skill/old-core",
        "exitstatus": 0,
        "records": [{
            "cell": "Sold-Cold-Mold-Anew",
            "scenario": "test_x",
            "axes": ["S"],
            "boundary": "S axis boundary",
            "blocked_on": "owner#1|owner#2",
            "owner": "team-a|team-b\nteam-c",
            "outcome": "xfail",
        }],
    }))

    returncode, stderr, sprint_md = _run_summarize(
        script, findings_dir, tmp_path, expected_combos=["old-skill/old-core"])
    assert returncode == 0, stderr

    red_section = sprint_md.split("## Red boundaries", 1)[1]
    table_lines = [
        ln for ln in red_section.splitlines()
        if ln.startswith("|") and "boundary | axes" not in ln and "---" not in ln
    ]
    assert len(table_lines) == 1, f"expected exactly one data row, got {table_lines!r}"
    row = table_lines[0]
    # Every `|` inside a cell must be escaped as `\|` -- i.e. every `|` in
    # the row is either a real column delimiter or immediately preceded by
    # a backslash. An unescaped `|` from blocked_on/owner would introduce
    # an unescaped delimiter and misalign every column after it -- count
    # real (unescaped) delimiters and confirm it's still exactly 6 columns
    # (7 delimiters, since the row starts and ends with `|`).
    real_delimiters = 0
    i = 0
    while i < len(row):
        if row[i] == "|" and (i == 0 or row[i - 1] != "\\"):
            real_delimiters += 1
        i += 1
    assert real_delimiters == 7, (
        f"row has the wrong column count -- an unescaped `|` broke the "
        f"table: {row!r}")
    # No raw newline made it into the row (would break markdown table
    # parsing outright).
    assert "\n" not in row
    assert "owner#1\\|owner#2" in row
    assert "team-a\\|team-b team-c" in row


# ---------------------------------------------------------------------
# FIX 2: an unknown cell "tier" in generate-matrix's ALL_CELLS must fail
# the job loudly, not silently vanish from every trigger.
# ---------------------------------------------------------------------

def test_generate_matrix_script_runs_clean_on_real_cells(tmp_path):
    """Sanity: the unmodified, real generate-matrix script (today's
    ALL_CELLS, all tiers valid) must still succeed -- proves the new
    assert doesn't false-positive on legitimate input, and that the new
    `combos` output line is written too."""
    script = _step_script("generate-matrix", "Select this run's cells by trigger tier")
    out_path = tmp_path / "github_output"
    out_path.write_text("")
    env = dict(os.environ)
    env["EVENT_NAME"] = "pull_request"
    env["CRON"] = ""
    env["GITHUB_OUTPUT"] = str(out_path)

    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = out_path.read_text()
    assert "cells=" in output
    assert "combos=" in output


def test_generate_matrix_rejects_unknown_tier(tmp_path):
    """The exact defect: a typo'd tier value (e.g. ``"boundry"`` instead of
    ``"boundary"``) inside a cell's ``tiers`` list matches none of the
    trigger-tier sets on ANY trigger, so the cell silently vanishes from
    every run with exit 0 and zero signal. Mutates the real extracted
    script's first cell's tiers list to include an unknown value and
    asserts the job now fails loudly instead. (T2.7: cells now carry a
    `tiers` LIST, not a single `tier` string, so a cell can be in both
    `pr-fast` and `boundary` at once -- this test targets the list shape.)
    """
    script = _step_script("generate-matrix", "Select this run's cells by trigger tier")

    assert script.count('"tiers": ["pr-fast", "boundary"]') >= 1, (
        "generate-matrix's ALL_CELLS literal in backcompat_matrix.yml must "
        "have changed shape; update this test's replace() target")
    # Mutate just the FIRST cell's tiers to include an unrecognized value --
    # proves a single typo'd tier on one cell is enough to trip the assert.
    mutated = script.replace(
        '"tiers": ["pr-fast", "boundary"]', '"tiers": ["pr-fast", "boundry"]', 1)
    assert mutated != script

    out_path = tmp_path / "github_output"
    out_path.write_text("")
    env = dict(os.environ)
    env["EVENT_NAME"] = "pull_request"
    env["CRON"] = ""
    env["GITHUB_OUTPUT"] = str(out_path)

    result = subprocess.run(
        [sys.executable, "-c", mutated], env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0, (
        "an unknown tier value must fail the job, not exit 0 silently")
    assert "unknown tier" in result.stderr.lower() or \
        "unknown tier" in result.stdout.lower()


# ---------------------------------------------------------------------
# T2.7: the CI trigger split. `pull_request` now runs a smaller `pr-fast`
# lane (6 cells) rather than the full 10-cell `boundary` tier; nightly
# still runs all 10 boundary cells; weekly/push/dispatch run everything
# (14). Each test below runs the REAL extracted generate-matrix script
# with a specific EVENT_NAME/CRON pair and asserts the exact selected
# combo set -- mutation-proof: dropping a cell from a tier, or a typo in
# the tier name, drops (or adds) an entry from `combos` and fails these.
# ---------------------------------------------------------------------

_PR_FAST_COMBOS = {
    "old-skill/old-core",
    "old-skill/new-core",
    "new-skill/old-core",
    "new-skill/new-core",
    "old-skill/old-core-new-matchers",
    "new-skill/new-core-old-matchers",
}

_BOUNDARY_COMBOS = _PR_FAST_COMBOS | {
    "old-skill/new-core-old-matchers",
    "new-skill/old-core-new-matchers",
    "old-skill/new-core-padatious-old-adapt-new",
    "new-skill/new-core-padatious-old-adapt-new",
}

_CHANNEL_COMBOS = {
    "stable-skill/dev-core",
    "dev-skill/stable-core",
    "testing-skill/dev-core",
    "dev-skill/testing-core",
}

_ALL_COMBOS = _BOUNDARY_COMBOS | _CHANNEL_COMBOS


def _run_generate_matrix(script, event_name, cron, tmp_path):
    out_path = tmp_path / "github_output"
    out_path.write_text("")
    env = dict(os.environ)
    env["EVENT_NAME"] = event_name
    env["CRON"] = cron
    env["GITHUB_OUTPUT"] = str(out_path)

    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = out_path.read_text()
    combos_line = next(ln for ln in output.splitlines() if ln.startswith("combos="))
    combos = json.loads(combos_line[len("combos="):])
    return set(combos)


def test_pull_request_trigger_selects_the_six_cell_pr_fast_lane(tmp_path):
    """`pull_request` must select exactly the 6-cell fast lane: the 4
    original S/C aliases plus the 2 highest-value matcher cells
    (old-skill/old-core-new-matchers, new-skill/new-core-old-matchers) --
    NOT the full 10-cell boundary tier, and NOT any channel cell."""
    script = _step_script("generate-matrix", "Select this run's cells by trigger tier")
    combos = _run_generate_matrix(script, "pull_request", "", tmp_path)
    assert combos == _PR_FAST_COMBOS
    assert len(combos) == 6
    # The 4 matcher/skew cells the fast lane deliberately skips must be
    # absent -- a dropped exclusion (i.e. the fast lane silently growing
    # back to the full boundary tier) would pass a subset check but fail
    # this exact-equality one.
    assert combos.isdisjoint(_BOUNDARY_COMBOS - _PR_FAST_COMBOS)
    assert combos.isdisjoint(_CHANNEL_COMBOS)


def test_nightly_cron_selects_all_ten_boundary_cells(tmp_path):
    """The `0 3 * * *` (nightly) schedule must select all 10 boundary
    cells -- the 6 PR-fast cells PLUS the 4 matcher/skew cells the PR
    lane skips -- and no channel cell."""
    script = _step_script("generate-matrix", "Select this run's cells by trigger tier")
    combos = _run_generate_matrix(script, "schedule", "0 3 * * *", tmp_path)
    assert combos == _BOUNDARY_COMBOS
    assert len(combos) == 10
    assert combos.isdisjoint(_CHANNEL_COMBOS)


def test_weekly_cron_selects_everything_including_channel(tmp_path):
    """The `0 4 * * 0` (weekly) schedule must select all 14 cells: 10
    boundary + 4 channel."""
    script = _step_script("generate-matrix", "Select this run's cells by trigger tier")
    combos = _run_generate_matrix(script, "schedule", "0 4 * * 0", tmp_path)
    assert combos == _ALL_COMBOS
    assert len(combos) == 14


def test_workflow_dispatch_selects_everything(tmp_path):
    """`workflow_dispatch` (manual run) must also select all 14 cells --
    unchanged from before the T2.7 split, and NOT the pr-fast subset."""
    script = _step_script("generate-matrix", "Select this run's cells by trigger tier")
    combos = _run_generate_matrix(script, "workflow_dispatch", "", tmp_path)
    assert combos == _ALL_COMBOS
    assert len(combos) == 14


def test_push_dev_selects_everything(tmp_path):
    """`push` (to dev) must also select all 14 cells, matching
    workflow_dispatch and the weekly cron -- unchanged from before this
    split."""
    script = _step_script("generate-matrix", "Select this run's cells by trigger tier")
    combos = _run_generate_matrix(script, "push", "", tmp_path)
    assert combos == _ALL_COMBOS
    assert len(combos) == 14
