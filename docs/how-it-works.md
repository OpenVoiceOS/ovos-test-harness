# How it works — the `requirements.txt`-driven install model

The defining design choice of `ovos-test-harness` is that it is not a
package. There is no `setup.py`, no `pyproject.toml`, no `pip install .`, and
no `.[test]` extra. The harness installs the exact stack under test from
[`requirements.txt`](../requirements.txt), and that file is the specification
of which implementation is being proven conformant to the
[`OpenVoiceOS/architecture`](https://github.com/OpenVoiceOS/architecture)
specs.

## `requirements.txt` is the combo selector

Every line in `requirements.txt` pins one repo of the integrated spec stack
to an explicit git ref, or a published version. A representative file:

```
# core with STOP-1 + PIPELINE-1 conformance source (combined integration branch)
git+https://github.com/OpenVoiceOS/ovos-core@test/spec-stack-integration-proof
# INTENT-4 producer (emits ovos.intent.register.* etc.)
git+https://github.com/OpenVoiceOS/ovos-workshop@feat/intent-4-producer
# session spec fields (active_handlers / converse_handlers / response_mode)
git+https://github.com/OpenVoiceOS/ovos-bus-client@feat/session-spec-fields
# pipeline engines (workshop-9-compatible)
git+https://github.com/OpenVoiceOS/ovos-adapt-pipeline-plugin@fix/allow-ovos-workshop-9
git+https://github.com/OpenVoiceOS/ovos-padatious-pipeline-plugin@fix/allow-ovos-workshop-9
# fixture skills (ovos-workshop cap lifted to <10)
git+https://github.com/OpenVoiceOS/ovos-skill-parrot@fix/allow-ovos-workshop-10
git+https://github.com/OpenVoiceOS/ovos-skill-fallback-unknown@fix/allow-ovos-workshop-10
git+https://github.com/OpenVoiceOS/ovos-skill-count@fix/allow-ovos-workshop-10
git+https://github.com/OpenVoiceOS/ovos-skill-hello-world@fix/allow-ovos-workshop-10
# e2e harness lib
git+https://github.com/TigreGotico/ovoscope@fix/none-iter-guard
# published spec vocabulary
ovos-spec-tools>=0.16.1a2
# pipeline engine fallback + test deps
padacioso
pytest
pytest-json-report
```

CI installs that and only that. The combination under trial is encoded as
data, in version control, reviewable in a diff, not buried in a CI matrix or
a tox config.

## The problem it solves: resolver downgrade

The reason this is a flat `requirements.txt` rather than a package with a
`[test]` extra is the pip resolver downgrade problem.

Imagine the conformance suites shipped as `ovos-test-harness`, a package
with the stack listed under `[project.optional-dependencies].test`,
installed with `pip install .[test]`. The dependency surface would look
like this:

```
ovos-test-harness[test]
  → ovos-core@<some branch>
       → ovos-workshop (its own pinned range, e.g. <0.9)
  → ovos-workshop@<branch under test, version 0.9.x>
```

Now `ovos-core`'s metadata caps `ovos-workshop<0.9`, but the whole point of
the run is to prove the branch at `ovos-workshop 0.9.x`. pip's job is to
find a consistent set, and the cheapest consistent set is to downgrade
`ovos-workshop` to a published `<0.9`, silently dropping the branch you are
trying to prove. Your conformance run would then test a stack that does not
exist in the combination you care about, and would report green or red for
the wrong reason.

A flat `requirements.txt` of fully-pinned git refs avoids this:

- Every package the run depends on is named with an exact ref, so pip has no
  free variable to optimize. It installs the listed ref of each repo, in
  order.
- There is no local package whose metadata reintroduces a version range
  that pip could satisfy by downgrading a sibling.
- The intra-stack version caps (for example an `ovos-workshop<9` ceiling in
  a pipeline plugin) are dealt with up front by pinning a branch that lifts
  the cap. See the `fix/allow-ovos-workshop-*` refs above. The resolver
  never gets to resolve against your intent.

The resolver is never handed the freedom to re-resolve or downgrade
anything. That is the line repeated in the file's own header comment, and it
is the entire reason the harness is structured this way.

## Why determinism matters for conformance

A conformance verdict is meaningful only if it is reproducible. Because the
stack is fully pinned:

- The same refs produce the same verdict every run. A clause that passes
  today against this `requirements.txt` passes tomorrow against it.
- A change in verdict is attributable to a change in the diff (a ref you
  flipped), not to PyPI publishing a new patch release of a transitive
  dependency overnight.
- A reviewer reading a harness PR can see exactly which implementation is
  being certified, because it is the literal content of `requirements.txt`.

This is what makes the harness usable as the proof-of-conformance gate. A
green run is a statement about a named, frozen stack, not about whatever pip
happened to resolve in CI today.

## What the install actually contains

| Pinned line | What it contributes to the trial |
|-------------|----------------------------------|
| `ovos-core` | The orchestrator under test: the utterance lifecycle (PIPELINE-1) and the in-core stop / converse / fallback pipelines (STOP-1 / CONVERSE-1 / FALLBACK-1). |
| `ovos-workshop` | Skill base classes, the INTENT-4 registration producer, the PIPELINE-1 §8 handler-lifecycle trio, and the §9.6 `ovos.utterance.speak` dual-emit. |
| `ovos-bus-client` | `Message`, `Session`, and the SESSION-1/2 spec session fields the suites probe for (`active_handlers`, `converse_handlers`, `fallback_handlers`, `response_mode`). |
| `ovos-adapt-pipeline-plugin`, `ovos-padatious-pipeline-plugin` | Native intent matchers, present so the effective-pipeline ordering clauses run against real engines. |
| `padacioso` | The pure-python matcher the suites prefer, deterministic on a `FakeBus`, with no native build, registered directly with `ovoscope.register_padatious_intent`. |
| `ovos-skill-parrot`, `-fallback-unknown`, `-count`, `-hello-world` | Real fixture skills that drive the converse round-trip and the fallback catch-all. |
| `ovoscope` | The bus-capture / assertion engine (`get_minicroft`, `register_padatious_intent`) the suites are built on. |
| `ovos-spec-tools` | The published spec vocabulary. Tests import topic names from `SpecMessage` so assertions are spec-traceable. |
| `pytest`, `pytest-json-report` | The test runner and a machine-readable report format for CI. |

## The cost: one ref per repo

The same property that gives the determinism, one explicit package per
name, imposes the framework's one limitation: two branches of the same repo
cannot both be installed. pip installs a single `ovos-core`, a single
`ovos-workshop`, and so on. To compare or combine two in-flight branches of
one repo, you merge them into a combined branch and pin that. This is
covered in [testing-combos.md](testing-combos.md#the-single-ref-per-repo-limitation).

## See also

- [testing-combos.md](testing-combos.md) — using this model to validate
  cross-repo branch combinations via PRs.
- [ci.md](ci.md) — the workflow that performs the install and runs the
  suite.

---
[← Overview](overview.md) · [Home](../README.md) · [Testing branch combinations →](testing-combos.md)
