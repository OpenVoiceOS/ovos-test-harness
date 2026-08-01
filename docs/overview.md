# Overview: the harness's role in the OVOS spec ecosystem

`ovos-test-harness` is the executable conformance test framework for the
[`OpenVoiceOS/architecture`](https://github.com/OpenVoiceOS/architecture)
specifications. This page places it in the wider spec ecosystem.

## Three artifacts, three roles

The OVOS specification effort is split across three deliberately separate
artifacts. Keeping them apart lets the specs stay implementation-agnostic
while still being enforceable.

```
   ┌──────────────────────────────────────────────────────────────────┐
   │                  OpenVoiceOS/architecture                         │
   │                        THE LAW                                    │
   │   Prescriptive, implementation-agnostic Markdown specs.           │
   │   "On the bus, X MUST happen." No Python, no repo names.          │
   │   pipeline-1.md · stop-1.md · intent-4.md · converse.md · …       │
   └───────────────┬──────────────────────────────────────────────────┘
                   │ defines the shared primitives & topic names
                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                      ovos-spec-tools                              │
   │                      THE VOCABULARY                               │
   │   Python embodiment of the spec's nouns:                          │
   │     SpecMessage (topic enum) · Session · Intent · …               │
   │   A topic asserted via SpecMessage.UTTERANCE is provably          │
   │   the spec's topic, not a literal that drifted.                │
   └───────────────┬──────────────────────────────────────────────────┘
                   │ imported by every test
                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                      ovos-test-harness                            │
   │                       THE COURTROOM                               │
   │                                                                   │
   │   requirements.txt  ──► the STACK ON TRIAL (pinned git refs)      │
   │        │                ovos-core + workshop + bus-client + …     │
   │        ▼                                                          │
   │   test/conformance/*  ──► one assertion per normative clause      │
   │        │                  built on ovoscope (bus capture)         │
   │        ▼                                                          │
   │   VERDICT per clause:  pass · xfail (documented gap) · fail       │
   └──────────────────────────────────────────────────────────────────┘
```

### `OpenVoiceOS/architecture`: the law

The [architecture repo](https://github.com/OpenVoiceOS/architecture) holds 20
formal specifications. They are prescriptive and implementation-agnostic.
They describe the message bus contract, including topic names, message
shapes, ordering guarantees, and terminal markers, in normative MUST / SHOULD
language, without naming any Python package or referencing any line of code.

A spec such as **OVOS-PIPELINE-1** ("Utterance Lifecycle and Pipeline
Specification") says, for example, that the orchestrator MUST emit exactly
one `ovos.utterance.handled` per entry-topic message (§9.5). It does not say
which class in which repo does so.

### `ovos-spec-tools`: the vocabulary

[`ovos-spec-tools`](https://github.com/OpenVoiceOS/ovos-spec-tools) is the
Python embodiment of the nouns the specs define: the `SpecMessage` topic
enum, `Session`, `Intent`, and the shared matching and normalization
primitives. The harness imports the spec topic names from here rather than
writing them as string literals:

```python
from ovos_spec_tools import SpecMessage
ENTRY_TOPIC = SpecMessage.UTTERANCE.value  # "ovos.utterance.handle"
```

This makes the assertion traceable to the spec. If the spec's canonical
topic name ever changes, it changes in one place (`ovos-spec-tools`), and
every test that references it moves with it. A test never claims conformance
against a topic the spec vocabulary does not bless.

### `ovos-test-harness`: the courtroom

This repo is where a concrete implementation is put on trial against the
law. Two things make it a courtroom rather than a unit-test directory.

1. **The defendant is a real, pinned stack.** [`requirements.txt`](../requirements.txt)
   names the exact git refs of `ovos-core`, `ovos-workshop`, `ovos-bus-client`,
   the pipeline plugins, and the fixture skills under test. CI installs that
   exact set. See [how-it-works.md](how-it-works.md).

2. **Each test is one clause of one spec.** Suites live in
   [`test/conformance/`](../test/conformance). Each test class maps to one
   spec section, and each method's docstring quotes the MUST/SHOULD clause it
   checks, asserted end-to-end against the running stack via
   [`ovoscope`](https://github.com/OpenVoiceOS/ovoscope).

The verdict for each clause is one of three:

- **pass**: the stack conforms.

- **xfail**: a documented conformance gap. The spec mandates X, the current
  implementation still does the legacy Y. The marker cites the exact spec
  clause and the legacy behavior, and flips to a pass automatically once the
  implementation lands. See [known-gaps.md](known-gaps.md).

- **fail**: an undocumented regression. The stack violates a clause it was
  previously proven to satisfy.

## Why a separate repo at all

The conformance suites cannot live in any product repo, because no product
repo can install the combination a spec clause depends on. `ovos-core`'s own
CI installs `ovos-core` plus whatever pip resolves. It cannot pin an
unmerged `ovos-workshop` branch alongside an unmerged `ovos-bus-client`
branch and prove the three interoperate.

The harness exists to own that cross-repo, fully-pinned integration
surface. See [how-it-works.md](how-it-works.md) and
[testing-combos.md](testing-combos.md).

## Where to go next

- [how-it-works.md](how-it-works.md): the install model in depth.
- [coverage.md](coverage.md): exactly which specs and clauses are proven.
- [writing-conformance-tests.md](writing-conformance-tests.md): how to add a clause.

---
[Home](../README.md) · [How it works →](how-it-works.md)
