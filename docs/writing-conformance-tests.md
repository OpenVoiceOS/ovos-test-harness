# Writing conformance tests

A conformance test in `ovos-test-harness` is a single, traceable assertion that a
running OVOS stack exhibits one behavior a
[`OpenVoiceOS/architecture`](https://github.com/OpenVoiceOS/architecture) spec
clause mandates. These conventions keep every test auditable back to the law it
enforces. Follow them when adding a clause or a new spec suite.

## One spec section per test class

Each test class maps to **one section of one spec**, and its class docstring
states which. Each test *method* checks one MUST/SHOULD clause and **quotes that
clause** in its docstring, with the section number. From the PIPELINE-1 suite:

```python
class TestSec95EndMarker(TestCase):
    """§9.5: a conformant orchestrator MUST emit exactly one
    ``ovos.utterance.handled`` per entry-topic Message, on every terminal path."""

    def test_exactly_one_handled_on_no_match(self):
        """No-match path terminates with exactly one end-marker (§6.4, §9.5)."""
        recs = capture(_MC, utterance("zxqw blah blah", "p1-eof-nm", [PADACIOSO_HIGH]), 4.0)
        self.assertEqual(types(recs).count("ovos.utterance.handled"), 1)
```

A reader can go from the test name → the quoted clause → the exact `§` in the
architecture Markdown without guessing. The suite module docstring also carries a
**coverage map** (clause → green/xfail status) so the whole spec's coverage is
visible at the top of the file.

## The `_conformance.py` helpers

All suites share [`test/conformance/_conformance.py`](../test/conformance/_conformance.py)
(leading underscore so pytest does not collect it). It provides the small,
uniform vocabulary every test is written in:

| Helper | What it does |
|--------|--------------|
| `ENTRY_TOPIC` | `SpecMessage.UTTERANCE.value` — `"ovos.utterance.handle"`. The spec entry topic the orchestrator subscribes to. |
| `use_spec_namespace()` / `reset_namespace()` | Flip `Configuration()["legacy_namespace"]` off / on. Call from `setUpModule` / `tearDownModule`. |
| `utterance(text, session_id, pipeline, **session_fields)` | Build an entry `Message` on `ENTRY_TOPIC` for one session, with an explicit `session.pipeline`. |
| `capture(mc, message, timeout)` | Emit `message` and return **every** bus `Message` seen within `timeout` (subscribes to the `FakeBus` catch-all, so the full ordered sequence is captured). |
| `types(recs)` | The ordered list of `msg_type` strings. |
| `first(recs, msg_type)` | The first captured `Message` of a type, or `None`. |
| `PADACIOSO_HIGH`, `STOP_HIGH` | The pipeline-stage ids used to drive matching and the stop cascade. |

A test is therefore almost always: build an `utterance(...)`, `capture(...)` the
bus, and assert on `types(...)` / `first(...)`.

## The spec-namespace injection model

The suites assert the **spec (`ovos.*`) topic names**, so they must run with core
in the spec namespace. `use_spec_namespace()` sets `legacy_namespace = False`, and
the `IntentService` then subscribes to the spec entry topic:

```python
ENTRY_TOPIC = SpecMessage.UTTERANCE.value  # "ovos.utterance.handle"
```

This is why the injection topic matters. Tests inject the utterance on
**`ovos.utterance.handle`**, the spec entry topic (PIPELINE-1 §9.1) — not on the
legacy `recognizer_loop:utterance`. With `legacy_namespace=False`, core handles the
utterance natively *on the spec topic*; injecting on the legacy topic would never
reach the handler, so the test would prove nothing. Injecting on the spec topic is
what makes the run an assertion about the spec contract rather than the legacy one.

## Assert against `SpecMessage`, never string literals

Topic names asserted by a conformance test must be **provably the spec's**. Import
them from `ovos-spec-tools`:

```python
from ovos_spec_tools import SpecMessage
ENTRY_TOPIC = SpecMessage.UTTERANCE.value
```

Using `SpecMessage` rather than a hard-coded `"ovos.utterance.handle"` ties the
assertion to the spec vocabulary: if the spec's canonical name changes, it changes
in `ovos-spec-tools` and the test moves with it, instead of silently asserting a
name that drifted out of the spec. A test that asserts a literal proves only that
the literal matched — not that the *spec topic* was honored.

## The `xfail` discipline

This is the most important convention, and it is what keeps the suite honest about
the difference between *the spec* and *today's implementation*.

A conformance test always asserts the **spec's** topic name / message shape. Where
the current implementation still emits a legacy `mycroft.*` (or colon-shaped) name
because the migration is pending, the test is decorated:

```python
@pytest.mark.xfail(strict=False,
                   reason="ovos-core self-dispatches the legacy 'stop:global'; "
                          "STOP-1 §3.1/§5.2 use '<stop_plugin_id>:global_stop'")
def test_global_stop_dispatch_topic(self):
    """Global stop is dispatched on ``<stop_plugin_id>:global_stop`` (§3.1, §5.2)."""
    recs = capture(_MC, utterance("stop", "stop-global-disp", [STOP_HIGH]), 4.0)
    self.assertTrue(any(t.endswith(":global_stop") for t in types(recs)))
```

The rules:

1. **The assertion is the spec behavior.** The body asserts `:global_stop` (what
   STOP-1 mandates), *never* the legacy `stop:global`. The harness must never
   record the legacy behavior as conformant.
2. **The `reason` cites both sides.** It names the legacy topic the impl currently
   emits **and** the exact spec clause it must meet. The `reason` is the canonical
   record of the gap — [known-gaps.md](known-gaps.md) is generated from these
   strings.
3. **`strict=False`** so the test **xpasses** (not errors) the moment the impl
   starts honoring the spec. An xpass is the signal to delete the marker and
   convert the clause to plain green.
4. **No `xfail` for behavior the stack already satisfies.** Those tests assert
   plainly and stay green.

For pieces supplied by a still-unreleased producer (e.g. the PIPELINE-1 §8 handler
trio emitted by `ovos-workshop`), prefer a **`skipif`** guarded on a feature probe
(`hasattr(OVOSSkill, "_intent_handler_data")`) rather than an `xfail`, so the test
*skips cleanly* when the producer is absent and *runs* when it is present:

```python
_requires_spec_workshop = pytest.mark.skipif(
    not hasattr(OVOSSkill, "_intent_handler_data"),
    reason="ovos-workshop spec bus-message dual-emit not installed",
)
```

Likewise, probe `Session("probe").serialize()` for a spec session field before
asserting on it, so SESSION-1/2 field clauses skip until `ovos-bus-client` carries
the field rather than failing.

## Drivers: keep them deterministic

The suites prefer drivers that are deterministic on a `FakeBus`:

- **Intent dispatch** is driven by the pure-python `padacioso` matcher, with
  intents registered straight on the bus via
  `ovoscope.register_padatious_intent` — no skill packages or native matchers
  required for the basic flows.
- **Stop** is driven by the in-core stop pipeline (deterministic, no external
  matcher).
- **Converse** and **fallback** use real fixture skills (`ovos-skill-parrot`,
  `ovos-skill-fallback-unknown`) because those round-trips need a real
  `can_converse` / fallback handler.

## Checklist for a new clause

- [ ] One class per spec section; class docstring names the section.
- [ ] Method docstring quotes the MUST/SHOULD clause + cites the `§`.
- [ ] Topic names come from `SpecMessage`, not literals.
- [ ] Inject on the **spec** entry topic (`use_spec_namespace()` + `ENTRY_TOPIC`).
- [ ] If the impl is behind: `xfail(strict=False)` asserting the **spec** behavior,
      `reason` citing legacy-topic + spec-clause. Never assert the legacy behavior.
- [ ] If a producer/field may be absent: `skipif` on a feature probe.
- [ ] Add the clause to the module's coverage-map docstring and to
      [coverage.md](coverage.md).

## See also

- [coverage.md](coverage.md) — the full per-clause coverage record.
- [known-gaps.md](known-gaps.md) — the live `xfail` gaps.
</content>
