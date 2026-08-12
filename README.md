# ovos-test-harness

**The executable conformance test framework for the
[`OpenVoiceOS/architecture`](https://github.com/OpenVoiceOS/architecture)
specifications.**

The `architecture` repo is the prescriptive, implementation-agnostic source of
truth for OpenVoiceOS. It holds a set of formal Markdown specifications
(OVOS-PIPELINE-1, OVOS-STOP-1, OVOS-INTENT-4, and others) that state what
**MUST** happen on the message bus. `ovos-test-harness` is the executable
counterpart. Each test asserts one observable behavior a spec mandates,
against a real running OVOS stack assembled from pinned component versions.
This is where an implementation is proven to conform to the merged
architecture specs.

If the specs are the law, this harness is the courtroom. It puts a concrete
combination of OVOS repos on trial against the law and produces a verdict for
each normative clause: pass, `xfail` (a documented gap), or fail.

---

## Table of contents

- [What & why](#what--why)
- [The model: `requirements.txt` is the stack under test](#the-model-requirementstxt-is-the-stack-under-test)
- [Quick start](#quick-start)
- [Coverage matrix](#coverage-matrix)
- [Testing branch combinations](#testing-branch-combinations)
- [How it relates to the rest of the spec ecosystem](#how-it-relates-to-the-rest-of-the-spec-ecosystem)
- [The one limitation](#the-one-limitation)
- [Mixed-version back-compat matrix](#mixed-version-back-compat-matrix)
- [Release-channel compat](#release-channel-compat)
- [Documentation](#documentation)

---

## What & why

A single architecture spec clause is satisfied only when a combination of
branches across a dozen OVOS repos lines up: `ovos-core`, `ovos-workshop`,
`ovos-bus-client`, the pipeline plugins, and the fixture skills. No single
repo can validate that combination. Each repo's CI installs only its own
package plus whatever pip resolves from PyPI, and pip is free to downgrade a
sibling out of the exact combination you are trying to prove conformant.

This harness solves that problem. It is not a package: there is no
`pip install .` and no `.[test]` extra. Instead it installs the exact stack
under test from a [`requirements.txt`](requirements.txt) of explicit git refs
and pins, so CI never re-resolves and never downgrades a component. Each
conformance test then asserts a spec-mandated bus behavior against that live
stack. It imports the spec vocabulary from
[`ovos-spec-tools`](https://github.com/OpenVoiceOS/ovos-spec-tools), so a
topic name is provably spec-defined rather than a magic string, and captures
the bus through [`ovoscope`](https://github.com/OpenVoiceOS/ovoscope).

## The model: `requirements.txt` is the stack under test

`requirements.txt` is the combo selector. Every line pins one repo in the
integrated spec stack to an exact git ref, or a published version. CI
installs that and only that, so the resolver has no freedom to re-resolve or
downgrade. The roles:

| Line | Role in the spec stack |
|------|------------------------|
| `ovos-core` | The **orchestrator under test**: the utterance lifecycle and the stop / converse / fallback in-core pipelines. Source of the PIPELINE-1 / STOP-1 / CONVERSE-1 / FALLBACK-1 behavior. |
| `ovos-workshop` | The skill base and the INTENT-4 producer, plus the PIPELINE-1 §8 handler-lifecycle and §9.6 speak dual-emit. |
| `ovos-bus-client` | `Message`, `Session`, and the SESSION-1/2 spec session fields (`active_handlers`, `converse_handlers`, `response_mode`, and others). |
| `ovos-adapt-pipeline-plugin`, `ovos-padatious-pipeline-plugin`, `padacioso` | The intent matchers that drive dispatch. `padacioso` is the deterministic pure-python matcher the suites prefer. |
| `ovos-skill-parrot`, `-fallback-unknown`, `-count`, `-hello-world` | Real fixture skills that drive the converse and fallback round-trips. |
| `ovoscope` | The end-to-end bus-capture / assertion engine the tests are built on (`get_minicroft`, `register_padatious_intent`). |
| `ovos-spec-tools` | The published spec vocabulary: the `SpecMessage` topic enum, `Session`, `Intent`. Tests import topic names from here, never as string literals. |
| `pytest`, `pytest-json-report` | The runner. |

The stack is pinned against resolver downgrade: one explicit ref per repo, so
pip never re-resolves a sibling out from under the combination under test.
Most refs are branches, not shas, so they can move between runs — a run is
not guaranteed to reproduce bit-for-bit on a later date. What IS guaranteed:
a red run is reproducible from its `pip freeze` artifact (see
[docs/ci.md](docs/ci.md)), and pinning a ref to an explicit `@<sha>` instead
of a branch name freezes that line for a certification that must reproduce
exactly. See [docs/how-it-works.md](docs/how-it-works.md) for details.

## Quick start

```bash
git clone https://github.com/OpenVoiceOS/ovos-test-harness
cd ovos-test-harness

# padatious needs swig + libfann to build
sudo apt-get install -y swig libfann-dev

pip install -r requirements.txt   # installs the EXACT pinned stack under test
pytest test/ -v --tb=short        # runs the full spec conformance suite
```

Read the result this way: **passed** means the stack conforms to that clause.
**xfailed** means a documented conformance gap (the spec mandates X, current
core still emits the legacy Y). **xpassed** means a gap has closed, and its
`xfail` marker should be removed. See [docs/ci.md](docs/ci.md).

## Coverage matrix

This is the authoritative spec-to-suite traceability record. The architecture
`dev` branch carries 21 specs, and every one has a conformance suite.
SESSION-1 and SESSION-2 share one suite, and INTENT-4 has two: an
orchestrator suite and a per-plugin registration-compliance suite. Full
per-clause detail is in [docs/coverage.md](docs/coverage.md).

| Architecture spec | Spec ID | Harness suite | Status |
|-------------------|---------|---------------|--------|
| Utterance Lifecycle and Pipeline | OVOS-PIPELINE-1 | `test_pipeline1_conformance.py` | **implemented** |
| Stop Pipeline Plugin | OVOS-STOP-1 | `test_stop1_conformance.py` | **implemented** |
| Intent & Entity Registration Bus Contract | OVOS-INTENT-4 | `test_intent4_conformance.py` (orchestrator) + `test_intent4_plugins_conformance.py` (per-plugin) | **implemented** |
| Active Handlers & Interactive Response | OVOS-CONVERSE-1 | `test_converse1_conformance.py` | **implemented** |
| Fallback Pipeline Plugin | OVOS-FALLBACK-1 | `test_fallback1_conformance.py` | **implemented** |
| Session Specification | OVOS-SESSION-1 | `test_session_conformance.py` | **implemented** |
| Session Lifecycle & State Ownership | OVOS-SESSION-2 | `test_session_conformance.py` | **implemented** |
| Bus Message | OVOS-MSG-1 | `test_msg1_conformance.py` | **implemented** |
| Audio Input Service | OVOS-AUDIO-IN-1 | `test_audio_in_conformance.py` | **implemented** |
| Audio Output Service | OVOS-AUDIO-1 | `test_audio_out_conformance.py` | **implemented** |
| Bus Bridge & Opaque Relay | OVOS-BRIDGE-1 | `test_bridge1_conformance.py` | **implemented** |
| Common Query Pipeline Plugin | OVOS-COMMON-QUERY-1 | `test_common_query1_conformance.py` | **implemented** |
| GUI Display Subsystem | OVOS-GUI-1 | `test_gui1_conformance.py` | **implemented** |
| Sentence Template Grammar | OVOS-INTENT-1 | `test_intent1_conformance.py` | **implemented** |
| Locale Resource Formats | OVOS-INTENT-2 | `test_intent2_conformance.py` | **implemented** |
| Intent Definition | OVOS-INTENT-3 | `test_intent3_conformance.py` | **implemented** |
| Intent Context | OVOS-CONTEXT-1 | `test_context1_conformance.py` | **implemented** |
| OVOS Common Playback (OCP) | OVOS-OCP-1 | `test_ocp1_conformance.py` | **implemented** |
| Persona Pipeline Plugin | OVOS-PERSONA-1 | `test_persona1_conformance.py` | **implemented** |
| Transformer Plugins | OVOS-TRANSFORM-1 | `test_transform1_conformance.py` | **implemented** |
| User Identity Resolution | OVOS-USER-ID-1 | `test_user_id1_conformance.py` | **implemented** |

## Testing branch combinations

To validate a different combination of unmerged branches across the spec
stack:

1. Pick the combination of (possibly unmerged) branches you want to prove.
2. Edit `requirements.txt`. Set each repo's ref to the branch under test.
3. Open a PR. The `integration` workflow installs that exact stack and runs
   the full spec conformance suite against it.
4. As each branch merges upstream, flip its ref back to `@dev`.

Illustrative — a worked example, not the live file:

```
git+https://github.com/OpenVoiceOS/ovos-core@test/spec-stack-integration-proof
git+https://github.com/OpenVoiceOS/ovos-workshop@feat/intent-4-producer
git+https://github.com/OpenVoiceOS/ovos-bus-client@feat/session-spec-fields
...
```

This is how a producer-side change (for example ovos-workshop emitting the
INTENT-4 registration topics) and its consumer-side change (ovos-core
consuming them) are proven to interoperate before either is merged. See the
worked example in [docs/testing-combos.md](docs/testing-combos.md).

## How it relates to the rest of the spec ecosystem

| Component | Role |
|-----------|------|
| [`OpenVoiceOS/architecture`](https://github.com/OpenVoiceOS/architecture) | **The law.** The specs themselves: what MUST happen on the bus. Implementation-agnostic Markdown. |
| [`ovos-spec-tools`](https://github.com/OpenVoiceOS/ovos-spec-tools) | **The vocabulary.** The shared Python primitives the specs define: the `SpecMessage` topic enum, `Session`, `Intent`. Tests import these so an asserted topic is provably the spec's. |
| [`ovoscope`](https://github.com/OpenVoiceOS/ovoscope) | **The instrument.** The end-to-end bus-capture / assertion engine the tests are built on. |
| **`ovos-test-harness`** (this repo) | **The courtroom.** Where a concrete stack is put on trial against the law and a per-clause verdict is produced. |

See [docs/overview.md](docs/overview.md) for the full picture.

## The one limitation

`requirements.txt` installs one ref per repo. pip installs a single package
per name, so two branches of the same repo cannot both be present. To
validate two in-flight branches of one repo together, merge them into a
single combined branch and pin that. See
[docs/testing-combos.md](docs/testing-combos.md#the-single-ref-per-repo-limitation).

## Fleet-level cross-skill intent-routing suite

Every suite above boots one skill (or none) at a time. That setup cannot
catch cross-skill intent theft: if skill B's vocabulary overlaps skill A's,
B silently wins every time A's suite runs alone, because nothing else is
loaded to lose the race to. `test/skills_fleet/` is the one suite that boots
MANY real fleet skills into a single MiniCroft against a vendored corpus of
golden utterances (`test/skills_fleet/golden_utterances.jsonl`) and asserts
each utterance still routes to the skill that authored it. Known conflicts
and coverage gaps are triaged in `test/skills_fleet/FINDINGS.md`. It runs as
its own CI job (`skills_fleet.yml`), sharded by corpus rows — never by skill
population, since the whole point is routing accuracy against the full fleet.
Booting ~31 real skills is compute-heavy enough that it does not fit inside
GitHub's per-job time ceiling on hosted runners (observed: 20-40 minutes
locally, ~5h17m-5h37m on a GitHub-hosted runner for the identical code, not
a hang — see `FINDINGS.md`), so this job runs on `workflow_dispatch` and a
weekly schedule rather than blocking every PR.

## Mixed-version back-compat matrix

One stack per run also hides a whole class of bug: a skill container frozen
months ago that talks to a current core. Two package sets must be alive at
once to see it.

`test/backcompat/` does that with two venvs and a real `ovos-messagebus`
between them. The `.github/workflows/backcompat_matrix.yml` workflow runs
eight skill/core combinations, one matrix entry each:

| Combo | Skill binds | Core dispatches | Handler runs |
|-------|-------------|-----------------|--------------|
| old skill / old core | suffixed only | suffixed | yes |
| old skill / new core | suffixed only | canonical | **no** — `xfail(strict)` |
| new skill / old core | both | suffixed | yes |
| new skill / new core | both | canonical | yes, exactly once |

Four more cells pin a live OVOS distro release channel instead of a version
boundary — the constraints are fetched fresh from
[`constraints-stable.txt`](https://github.com/OpenVoiceOS/OpenVoiceOS/blob/main/constraints-stable.txt)
/ [`constraints-testing.txt`](https://github.com/OpenVoiceOS/OpenVoiceOS/blob/main/constraints-testing.txt)
at build time, never vendored, so the gate tracks the fleet:

| Combo | Skill binds | Core dispatches | Handler runs |
|-------|-------------|-----------------|--------------|
| stable skill / dev core | suffixed only (workshop floor `>=3.4.0,<3.5.0`) | canonical | **no** — `xfail(strict)` |
| dev skill / stable core | both | suffixed (padatious floor `>=1.4.2,<1.5.0`) | yes |
| testing skill / dev core | suffixed only (workshop floor `>=7.0.6,<8.0.0`) | canonical | **no** — `xfail(strict)` |
| dev skill / testing core | both | suffixed (padatious floor `>=1.4.3,<2.0.0`) | yes |

Both channels currently float well below the `ovos-workshop` 9.3.2a1 /
`ovos-padatious` 2.0.1a1 boundary, so their skill-side cells hit the same
known gap as `old skill / new core`. The day either channel's constraints file
bumps past that boundary, the corresponding cell goes red as an XPASS — that
is the signal, not a regression.

Only three cells are broken today, and all three are the same gap reached two
different ways. The other five are passing controls that prove the harness
can see a handler fire at all, so a red cell is a real finding and not a
broken fixture.

The suite is a gate on the intent-topic compat train. When
[ovos-bus-client#271](https://github.com/OpenVoiceOS/ovos-bus-client/pull/271)
releases, the broken cell starts passing, `strict=True` turns that into a loud
XPASS failure, and the marker comes off. A PR that drops the compat must flip
these cells deliberately.

`ovos-core` runs the same four cells against its own checkout. The duplication
is intended: a breakage stays traceable to the repo that caused it.

## Release-channel compat

The two workflows above both look at the dev edge. Neither answers the
question a device owner has: **does the spec suite hold on the versions the
fleet actually runs?**

`.github/workflows/channel_compat.yml` answers it. It installs the whole
conformance stack at the versions one OVOS distro release channel pins, then
runs the full suite against it. The constraints come from the distro itself,
fetched live and uploaded as an artifact:

| Channel | `ovos-workshop` | `ovos-core` | `ovos-bus-client` | `ovos-padatious` |
|---------|-----------------|-------------|-------------------|------------------|
| stable | `>=3.4.0,<3.5.0` | `>=1.3.1,<1.4.0` | `>=1.3.4,<1.4.0` | `>=1.4.2,<1.5.0` |
| testing | `>=7.0.6,<8.0.0` | `>=2.1.1,<3.0.0` | `>=1.3.7,<2.0.0` | `>=1.4.3,<2.0.0` |

That is a long way below dev, so both channels fail a large part of the modern
spec. Those failures are the finding, so each channel has a checked-in
known-gap baseline in `test/channel_gaps/`, seeded from a real run. The suite
strict-xfails exactly the listed node ids: known gaps stay visible and green,
**new** breakage turns the job red, and a gap the channel has since closed
turns it red too, as the cue to delete the line.

```bash
test/channel_compat/install_channel.sh stable /tmp/channel-compat
OVOS_CHANNEL=stable pytest test/ -rxX --timeout=180 --ignore=test/backcompat
```

Together the three workflows read as one program: `backcompat_matrix.yml`
finds **where** a behavior changed, `channel_compat.yml` says **what the fleet
runs today**, and `integration.yml` says **where dev is going**. Full detail in
[docs/ci.md](docs/ci.md).

## Documentation

| Page | Topic |
|------|-------|
| [docs/overview.md](docs/overview.md) | The framework's role in the OVOS spec ecosystem (law / vocabulary / courtroom). |
| [docs/how-it-works.md](docs/how-it-works.md) | The `requirements.txt`-driven install model and why no-package, no-re-resolution matters. |
| [docs/testing-combos.md](docs/testing-combos.md) | The PR-driven cross-repo branch-combination workflow. |
| [docs/writing-conformance-tests.md](docs/writing-conformance-tests.md) | Conventions: one spec section per class, quoted-clause docstrings, the `_conformance.py` helpers, and the `xfail` discipline. |
| [docs/coverage.md](docs/coverage.md) | The full spec-to-suite traceability matrix and per-class clause coverage. |
| [docs/ci.md](docs/ci.md) | The `integration.yml`, `backcompat_matrix.yml`, and `channel_compat.yml` workflows, running locally, and interpreting results. |
| [docs/known-gaps.md](docs/known-gaps.md) | The conformance gaps the suite currently documents as `xfail`. |
