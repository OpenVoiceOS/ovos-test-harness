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

## See also

- [how-it-works.md](how-it-works.md) — why the workflow installs a flat
  `requirements.txt` instead of a package.
- [testing-combos.md](testing-combos.md) — using a PR run to certify a
  combination.
- [known-gaps.md](known-gaps.md) — the `xfail` clauses you should expect to
  see.

---
[← Coverage](coverage.md) · [Home](../README.md) · [Known gaps →](known-gaps.md)
