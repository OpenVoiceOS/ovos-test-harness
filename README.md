# ovos-test-harness

Cross-repo **integration & conformance** tests for the OVOS spec stack.

This repo is the single place where the OVOS spec implementation is exercised
*end to end, across repos at once*. It encodes the normative **Conformance**
clauses of the OVOS formal specifications (`PIPELINE-1`, `STOP-1`, `INTENT-4`,
`CONVERSE-1`, `FALLBACK-1`, `SESSION-1`) as
[ovoscope](https://github.com/TigreGotico/ovoscope) end-to-end assertions
against a live `minicroft` orchestrator.

## Why it exists

The spec stack spans a dozen repos (`ovos-core`, `ovos-workshop`,
`ovos-bus-client`, the pipeline plugins, fixture skills, `ovos-spec-tools`,
`ovoscope`, …). A given spec clause is only satisfied when a *combination* of
branches across those repos lines up. Validating that combination from inside
any one repo is impossible — its CI only installs its own package plus
PyPI-resolved deps, and pip is free to downgrade a sibling out of the
combination you are trying to prove.

This harness solves that:

- **`requirements.txt` is the combo selector.** Every line is an explicit git
  ref (or a published pin) for one repo in the stack. CI installs *exactly*
  that, with no `pip install .[test]` of a local package, so the resolver is
  never handed the freedom to re-resolve or downgrade anything.
- **The conformance suites live here, not in any product repo.** They assert
  the spec topic names / message shapes and carry `xfail` markers for the
  clauses the implementation has not yet caught up to, so the suite flips from
  red to green automatically as the impl branches land.

## Workflow

1. Pick the combination of (possibly unmerged) branches you want to validate.
2. Edit `requirements.txt` — set each repo's ref to the branch under test.
3. Open a PR. The `integration` workflow installs that exact stack and runs the
   full spec conformance suite against it.
4. As each branch merges upstream, flip its ref back to `@dev`.

```
git+https://github.com/OpenVoiceOS/ovos-core@test/spec-stack-integration-proof
git+https://github.com/OpenVoiceOS/ovos-workshop@feat/intent-4-producer
...
```

### Limitation

Two branches of the **same** repo cannot both be installed — pip installs one
package per name. Pick one ref per repo. To compare two branches of one repo,
run two PRs (or two `requirements.txt` revisions).

## Running locally

Padatious needs `swig` and `libfann`:

```bash
sudo apt-get install -y swig libfann-dev
pip install -r requirements.txt
pytest test/ -v --tb=short
```

## Layout

```
requirements.txt                  # the stack under test (the combo selector)
test/conformance/
  _conformance.py                 # shared ovoscope capture helpers
  test_pipeline1_conformance.py   # PIPELINE-1
  test_stop1_conformance.py       # STOP-1
  test_intent4_conformance.py     # INTENT-4
  test_converse1_conformance.py   # CONVERSE-1
  test_fallback1_conformance.py   # FALLBACK-1
  test_session_conformance.py     # SESSION-1 (cross-cutting session evolution)
.github/workflows/integration.yml # installs requirements.txt, runs the suite
```
