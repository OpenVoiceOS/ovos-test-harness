# CI — running the conformance suite

The harness runs the full spec conformance suite against the exact pinned
stack in [`requirements.txt`](../requirements.txt). This page covers the
workflow, how to run it locally, and how to read the result.

## The `integration` workflow

The single workflow is [`.github/workflows/integration.yml`](../.github/workflows/integration.yml).
It deliberately does not use the shared `gh-automations` reusable workflow.
The whole point is to install this repo's own explicit, fully-pinned stack
so pip never re-resolves it (see [how-it-works.md](how-it-works.md)).

### Triggers

| Trigger | When it runs |
|---------|--------------|
| `pull_request` | Every PR. This is the conformance gate for a proposed stack combination (see [testing-combos.md](testing-combos.md)). |
| `push` to `dev` | Re-certifies trunk after a merge. |
| `workflow_dispatch` | Manual re-run. |

### Steps

1. `actions/checkout@v4`.
2. **Python 3.11** via `actions/setup-python@v5`.
3. **System deps**: `sudo apt-get install -y swig libfann-dev`. Padatious
   needs `swig` and `libfann` to build.
4. **Install the stack under test**: `pip install --upgrade pip` then
   `pip install -r requirements.txt`. This is the only install: no package,
   no `.[test]`.
5. **Run the suite**: `pytest test/ -v --tb=short`.

### The 60-minute timeout

The job sets `timeout-minutes: 60`. The cost is up front. `pip install -r
requirements.txt` builds a dozen repos from git refs, including the native
padatious/libfann path, and each conformance test stands up a live
`minicroft` orchestrator and waits on real bus timeouts (`capture(...,
timeout)` sleeps for several seconds per assertion so the full ordered bus
sequence is observed). 60 minutes is the headroom for this end-to-end,
real-stack model. These are not mocked unit tests.

## Running locally

```bash
# system deps (padatious needs swig + libfann)
sudo apt-get install -y swig libfann-dev

pip install -r requirements.txt
pytest test/ -v --tb=short
```

Run a single spec suite while iterating:

```bash
pytest test/conformance/test_pipeline1_conformance.py -v
pytest test/conformance/test_stop1_conformance.py -v
```

If padatious fails to build or import locally, install `swig` first and
make sure `libfann` is discoverable. `libfann-dev` provides the headers. On
some systems you may need `LD_LIBRARY_PATH` to point at the built library.
The pure-python `padacioso` matcher drives most of the basic flows and does
not need the native build.

## Interpreting results

A conformance run is read per clause, not just pass or fail overall.

| pytest outcome | Meaning for conformance |
|----------------|-------------------------|
| **passed** | The pinned stack satisfies that spec clause. |
| **xfailed** | A documented conformance gap: the test asserts the spec behavior, the implementation still does the legacy thing. Expected, not a failure. Catalogued in [known-gaps.md](known-gaps.md). |
| **xpassed** | A clause marked `xfail` now passes. The implementation caught up. **Action:** remove the `xfail` marker (once the impl branch merges) so the clause becomes a plain green requirement. |
| **failed** | An undocumented violation: a regression of a clause the stack previously satisfied, or a genuinely broken combination. This is the signal that fails the gate. |
| **skipped** | A skip-guarded clause whose producer or session field is absent in the installed stack (probed at runtime). It runs once that piece is pinned in. |

So the healthy steady state of a run is all green except the known
`xfail`s. A combo PR that closes a gap shows up as xpassed on the relevant
clauses, the cue to drop the markers. A red **failed** is the only true
alarm.

`pytest-json-report` is installed so a machine-readable `report.json` can be
produced (`pytest test/ --json-report`) for downstream tooling.

## The `mixed-version back-compat matrix` workflow

`integration.yml` installs one stack, so it cannot see a break between two
different stacks. `backcompat_matrix.yml` covers that: eight jobs, each
building **two** venvs and running the suite in `test/backcompat/` with a real
`ovos-messagebus` between them.

Each job selects its combo by environment, so all eight share one script:

```bash
test/backcompat/build_venvs.sh /tmp/venvs

BACKCOMPAT_COMBO=old-skill/new-core \
BACKCOMPAT_SKILL_PYTHON=/tmp/venvs/venv_skill_old/bin/python \
  /tmp/venvs/venv_core_new/bin/pytest test/backcompat/ -v -rxX
```

Four cells pin the exact releases either side of a known behavior boundary
(`old-*` / `new-*`). The other four — `stable-skill/dev-core`,
`dev-skill/stable-core`, `testing-skill/dev-core`, `dev-skill/testing-core` —
build the constrained side straight from the OVOS distro's own
`constraints-stable.txt` / `constraints-testing.txt`, fetched fresh in
`build_venvs.sh` rather than vendored. Those track the fleet: **when the
distro bumps a pin past a behavior boundary, the affected cell goes red at
that exact moment**, which is the alarm this design exists for. As pinned
today, both channels resolve an `ovos-workshop`/`ovos-padatious` floor below
the boundaries in `test_mixed_version_matrix.py`, so `stable-skill/dev-core`
and `testing-skill/dev-core` hit the same known gap as `old-skill/new-core`
and are `xfail(strict=True)` for the same reason; `dev-skill/stable-core` and
`dev-skill/testing-core` are passing controls, like `new-skill/old-core`.

Reading the result differs from the conformance suites in one way: an **XPASS
is the alarm**, not a failure to ignore. `old-skill/new-core`,
`stable-skill/dev-core`, and `testing-skill/dev-core` are `xfail(strict=True)`
while the fix is unreleased or the channel pin is old, so a green cell means
either the fix shipped or the distro moved its pin, and the marker must come
off.

Without `BACKCOMPAT_COMBO` the suite skips cleanly, so a plain `pytest test/`
is unaffected. `strategy.fail-fast` is off — one broken combination should not
hide the state of the others. Each job uploads the versions its venvs
actually resolved, plus the fetched constraints file for the channel cells, so
a surprising result can be reproduced and traced to exactly what was pinned
that day.

### Trigger tiers

The workflow's `generate-matrix` job picks which cells run from one
single-sourced list, filtered by what triggered the run:

| Trigger | Cells |
|---|---|
| `pull_request` (paths: `test/backcompat/**`, this workflow file) | 4 boundary cells (`old-skill/old-core`, `old-skill/new-core`, `new-skill/old-core`, `new-skill/new-core`) |
| `schedule` nightly (`0 3 * * *`) | 4 boundary cells (today, the same set as PR-time — there is no larger boundary tier to grow into yet) |
| `schedule` weekly (`0 4 * * 0`) | 4 boundary + 4 channel cells |
| `push: dev` / `workflow_dispatch` | 4 boundary + 4 channel cells (unchanged from before the trigger split) |

Channel cells stay off `pull_request` and the nightly run deliberately: they
fetch live distro constraints, so an unrelated PR (or an unrelated nightly
tick) should not go red because the fleet's own pins moved.

This tiering covers the *cell* dimension only. It does not yet also select
scenarios by which file a PR touched — [`matrix-design.md`](matrix-design.md)
§3.2 describes a fuller 16-boundary-cell / matcher-skew / transport-variant
matrix with per-scenario file splitting; today's suite is still one file
(`test_mixed_version_matrix.py`) covering every scenario, and standing up
the rest of that matrix needs new buildable cells in `build_venvs.sh` that
are out of scope here. Per-cell axis pruning
(`test/backcompat/conftest.py`'s `pytest_collection_modifyitems`, see its
module docstring) is what keeps each cell's actual run down to its
non-redundant scenarios today.

### The findings feed and `FINDINGS/SPRINT.md`

Every matrix job's `pytest test/backcompat/` run writes
`backcompat-findings-<cell>.json` (via `test/backcompat/conftest.py`'s
`pytest_terminal_summary` hook calling into `test/backcompat/findings.py`) —
one JSON record per `xfail`ed or `xpass`ed test in that cell:

```json
{
  "cell": "Sold-Cnew-Mnew-Anew",
  "scenario": "test/backcompat/test_mixed_version_matrix.py::test_the_skill_handler_runs",
  "axes": ["S", "C", "M"],
  "boundary": "<the reason text, or the boundary_xfail(...) boundary= field once that helper exists>",
  "blocked_on": "ovos-bus-client#271",
  "owner": "ovos-bus-client",
  "outcome": "xfail"
}
```

`boundary`/`blocked_on`/`owner` are parsed from the test's `xfail` reason
string: the structured `boundary_xfail(boundary=..., axes=..., blocked_on=...,
owner=..., note=...)` call form when a reason is written that way, or a
best-effort heuristic (an `owner#issue` token) over today's free-text
reasons otherwise — see `findings.py`'s module docstring for the exact rule
and why (`driver.py` does not define `boundary_xfail` as of this writing).

The workflow uploads each job's JSON as a `backcompat-findings-<job-index>`
artifact (`if: always()`, same shape as the `venv-freeze`/constraints
uploads above). A final `summarize` job (`needs: matrix`, `if: always()`)
downloads every findings artifact, groups the records **by boundary** (a
boundary is the unit of compat work; a cell is not), and renders
`FINDINGS/SPRINT.md`: an XPASS section first ("a fix shipped, drop the
marker"), then a table of red boundaries (`boundary | axes | cells red |
scenarios | blocked on | owner`). The same content is echoed into
`$GITHUB_STEP_SUMMARY` and uploaded as the `backcompat-sprint-findings`
artifact.

`summarize` makes **no GitHub writes** — no commits, no PR comments, no
issues. It is purely an artifact-and-step-summary report for whoever triages
the sprint backlog to read.

## The `channel compat` workflow

`integration.yml` and `backcompat_matrix.yml` both answer questions about the
dev edge. Neither answers the one the fleet cares about: **does the spec suite
hold on the versions people actually run?**

`channel_compat.yml` answers it. A *channel* is an OVOS distro release channel,
and the distro publishes one constraints file per channel:

| Channel | Constraints file | `ovos-workshop` | `ovos-core` | `ovos-bus-client` | `ovos-padatious` |
|---------|------------------|-----------------|-------------|-------------------|------------------|
| stable | [`constraints-stable.txt`](https://raw.githubusercontent.com/OpenVoiceOS/OpenVoiceOS/main/constraints-stable.txt) | `>=3.4.0,<3.5.0` | `>=1.3.1,<1.4.0` | `>=1.3.4,<1.4.0` | `>=1.4.2,<1.5.0` |
| testing | [`constraints-testing.txt`](https://raw.githubusercontent.com/OpenVoiceOS/OpenVoiceOS/main/constraints-testing.txt) | `>=7.0.6,<8.0.0` | `>=2.1.1,<3.0.0` | `>=1.3.7,<2.0.0` | `>=1.4.3,<2.0.0` |

(Read as of the run that seeded the baselines. The files move; the job fetches
them live, so the table is a snapshot and the job is not.)

### Install precedence

One rule: **the constraints file wins for every package it names, and
`requirements.txt` fills in only what the channel does not name.**

`pip install -c constraints.txt -r requirements.txt` does not implement that
rule. Almost every line of `requirements.txt` is a direct git URL, and pip does
not apply a version constraint to a direct URL, so the channel pin would
silently lose to the dev ref. [`install_channel.sh`](../test/channel_compat/install_channel.sh)
splits the install instead:

1. every constraint-named package, installed **by name** under `-c` — the
   channel decides the version;
2. plain leftovers (`ovos-spec-tools`, `pytest`, `setuptools<81`), still under
   `-c`, so their transitive deps cannot climb above the channel;
3. git leftovers (`padacioso`, `nebulento`, `palavreado`, `linha-fina`, the
   markov plugin, and on stable also `ovoscope` and `ovos-m2v-pipeline`),
   installed `--no-deps` — their metadata pins the dev stack and honouring it
   would undo step 1;
4. `ovos-media` `--no-deps` plus its leaf imports, exactly as `integration.yml`
   does it.

Locally:

```bash
test/channel_compat/install_channel.sh stable /tmp/channel-compat
OVOS_CHANNEL=stable pytest test/ -rxX --timeout=180 --ignore=test/backcompat
```

### Known-gap baselines

The channels are years of spec behind dev, so they fail a lot. That is signal,
not noise, but only if the *set* of failures is pinned down. Each channel has a
checked-in baseline:

- [`test/channel_gaps/stable.txt`](../test/channel_gaps/stable.txt)
- [`test/channel_gaps/testing.txt`](../test/channel_gaps/testing.txt)

Each file has three sections:

| Section | Meaning | What the harness does |
|---------|---------|-----------------------|
| `[modules]` | The suite does not import at all on this channel. | Not collected. `test/test_channel_gaps.py` asserts it still fails to import. |
| `[tests]` | The node id collects and fails. | `xfail(strict=True)`. |
| `[xpass]` | The suite already marks the node `xfail(strict)` for a dev-stack reason that does not hold on this channel, so it passes. | The marker is relaxed to non-strict. |

`OVOS_CHANNEL` switches this on; without it a normal dev run is unaffected. The
result:

- an unlisted failure turns the job **red** — a real regression;
- a listed failure that starts passing turns the job **red** via strict XPASS —
  the channel caught up, delete the line;
- a listed node id that no longer exists turns the job **red** — a rename cannot
  rot the baseline;
- a suite the baseline does not excuse that stops importing turns the job
  **red** — this is the channel-shaped replacement for
  `OVOS_CONFORMANCE_EXPECT_FULL`, which cannot be used here because a channel
  install is partial by construction.

Regenerate a baseline after a distro pin bump:

```bash
test/channel_compat/install_channel.sh stable /tmp/channel-compat
pytest test/ -q --tb=no --ignore=test/backcompat \
  --json-report --json-report-file=/tmp/report.json
python3 test/channel_compat/seed_gaps.py stable /tmp/report.json
```

Read the diff before committing it. A line added there is a claim that the
channel does not implement a clause; it must not be a flaky test or a broken
install. The workflow runs this same regeneration on every run and uploads the
result as an artifact, so the diff is available without a local install.

### Artifacts

Every run uploads the `pip freeze` of the installed channel stack, the
constraints file as fetched that day, and the regenerated baseline. A channel
run that is red weeks later cannot be reproduced from the URL alone, because
the URL has moved on.

## See also

- [how-it-works.md](how-it-works.md) — why the workflow installs a flat
  `requirements.txt` instead of a package.
- [testing-combos.md](testing-combos.md) — using a PR run to certify a
  combination.
- [known-gaps.md](known-gaps.md) — the `xfail` clauses you should expect to
  see.
- [matrix-design.md](matrix-design.md) — the axis model, pruning rules, and
  how to add a cell to the mixed-version matrix.

---
[← Coverage](coverage.md) · [Home](../README.md) · [Known gaps →](known-gaps.md)
