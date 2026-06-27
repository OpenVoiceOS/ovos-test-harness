# Coverage — spec → suite traceability matrix

This is the authoritative record of which
[`OpenVoiceOS/architecture`](https://github.com/OpenVoiceOS/architecture) specs
the harness proves conformance against, and — for each implemented suite — which
spec sections are asserted and at what status.

Status legend:

- **green** — the pinned stack satisfies the clause; the test asserts the spec
  behavior and passes.
- **xfail** — a *documented* conformance gap (see [known-gaps.md](known-gaps.md)).
  The test asserts the spec behavior; the current implementation still does the
  legacy thing. Flips to a pass automatically when the impl lands.
- **skip-guarded** — green when the relevant producer / session field is installed,
  skipped cleanly when it is not (probed at runtime).

## Top-level matrix

The architecture `dev` branch carries 20 specs. Six conformance suites are
implemented (covering seven specs — SESSION-1 and SESSION-2 share one suite); the
remaining specs are the documented roadmap.

| Architecture spec | Spec ID | Suite | Status |
|-------------------|---------|-------|--------|
| Utterance Lifecycle and Pipeline | OVOS-PIPELINE-1 | `test_pipeline1_conformance.py` | implemented |
| Stop Pipeline Plugin | OVOS-STOP-1 | `test_stop1_conformance.py` | implemented |
| Intent & Entity Registration Bus Contract | OVOS-INTENT-4 | `test_intent4_conformance.py` | implemented |
| Active Handlers & Interactive Response | OVOS-CONVERSE-1 | `test_converse1_conformance.py` | implemented |
| Fallback Pipeline Plugin | OVOS-FALLBACK-1 | `test_fallback1_conformance.py` | implemented |
| Session Specification | OVOS-SESSION-1 | `test_session_conformance.py` | implemented |
| Session Lifecycle & State Ownership | OVOS-SESSION-2 | `test_session_conformance.py` | implemented |
| Bus Message | OVOS-MSG-1 | — | roadmap |
| Audio Input Service | OVOS-AUDIO-IN-1 | — | roadmap |
| Audio Output Service | OVOS-AUDIO-1 | — | roadmap |
| Bus Bridge & Opaque Relay | OVOS-BRIDGE-1 | — | roadmap |
| Common Query Pipeline Plugin | OVOS-COMMON-QUERY-1 | — | roadmap |
| GUI Display Subsystem | OVOS-GUI-1 | — | roadmap |
| Sentence Template Grammar | OVOS-INTENT-1 | — | roadmap |
| Locale Resource Formats | OVOS-INTENT-2 | — | roadmap |
| Intent Definition | OVOS-INTENT-3 | — | roadmap |
| Intent Context | OVOS-CONTEXT-1 | — | roadmap |
| OVOS Common Playback (OCP) | OVOS-OCP-1 | — | roadmap |
| Persona Pipeline Plugin | OVOS-PERSONA-1 | — | roadmap |
| Transformer Plugins | OVOS-TRANSFORM-1 | — | roadmap |

---

## OVOS-PIPELINE-1 — `test_pipeline1_conformance.py`

*Utterance Lifecycle and Pipeline Specification.* Asserts the §11 conformance
clauses and the message-shape rules against the ovos-core orchestrator. During the
namespace transition both the legacy and the spec topics are emitted, so every
clause is green.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec5EffectivePipeline` | §5.1 | A known stage in `session.pipeline` matches & dispatches; an unknown `pipeline_id` is skipped, not aborted. | green |
| `TestSec53BlacklistBackstop` | §5.3 | A match whose `skill_id` is in `session.blacklisted_skills` is suppressed (orchestrator backstop); utterance still terminates. | green |
| `TestSec95EndMarker` | §6.4, §9.5 | Exactly one `ovos.utterance.handled` per utterance on the no-match and stop terminal paths. | green |
| `TestSec7Dispatch` | §7, §7.1 | Dispatch topic is exactly `<skill_id>:<intent_name>`; `data.utterance` forwarded verbatim; `context.skill_id` and `context.pipeline_id` stamped. | green |
| `TestSec8HandlerTrio` | §8.1 | A handler invocation is wrapped by `ovos.intent.handler.start` + exactly one `ovos.intent.handler.complete`. | skip-guarded (workshop) |
| `TestSec91Entry` | §9.1 | An utterance fed on `ovos.utterance.handle` runs the lifecycle to the end-marker. | green |
| `TestSec92Matched` | §9.2 | A successful match emits `ovos.intent.matched`. | green |
| `TestSec93Unmatched` | §9.3 | No-match emits `ovos.intent.unmatched` before the end-marker. | green |
| `TestSec96Speak` | §9.6 | A speaking handler emits on `ovos.utterance.speak`. | skip-guarded (workshop) |
| `TestSec64Cancelled` | §6.4 | A `context['canceled']` utterance emits `ovos.utterance.cancelled`, terminates once, and never dispatches. | green |
| `TestSec81HandlerError` | §8.1 | A raising handler emits `ovos.intent.handler.error`; the utterance still terminates with exactly one end-marker. | skip-guarded (workshop) / green |

## OVOS-STOP-1 — `test_stop1_conformance.py`

*Stop Pipeline Plugin Specification.* Asserts the §9 conformance clauses and the §8
bus surface against ovos-core's in-process stop pipeline. Deterministic on a
`FakeBus`.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec5GlobalStop` | §4.1 step 1, §5.1, §5.3 | A generic `stop` with empty active handlers terminates once and broadcasts `ovos.stop`. | green |
| `TestSec5GlobalStop.test_global_stop_dispatch_topic` | §3.1, §5.2 | Global stop dispatched on `<stop_plugin_id>:global_stop`. | **xfail** (core emits legacy `stop:global`) |
| `TestSec42PingPong` | §4.1 step 2, §4.2 | With active handlers, the stop plugin broadcasts `ovos.stop.ping` and collects `ovos.stop.pong`; the stoppable skill is then told to stop. | green |
| `TestSec43PerSkillStop` | §4.1 step 3, §4.3, §4 | An active skill yields a targeted `<skill_id>.stop` (not the broadcast); no active skill escalates to the `ovos.stop` global. | green |
| `TestSec2ReservedName` | §2 (+ INTENT-4 §5.3 / PIPELINE-1 §7.3) | A registration naming the reserved `stop` is malformed and must not become matchable. | **xfail** (core does not reject it) |

## OVOS-INTENT-4 — `test_intent4_conformance.py`

*Intent and Entity Registration Bus Contract.* Asserts the §11 conformance clauses
and the §4 registration bus surface. ovos-core does not yet expose this bus
contract — registration is the legacy in-process `padatious:register_intent` and
introspection is the legacy `intent.service.intent.get` — so most registration
clauses are xfail and flip green when the contract lands.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec2FireAndForget` | §2 | A registration is fire-and-forget — no `.response`, ack, or error event. | green |
| `TestSec5KeywordRegistration` | §5 | `ovos.intent.register.keyword` makes an intent matchable. | **xfail** (legacy `padatious:register_intent`) |
| `TestSec6TemplateRegistration` | §6 | `ovos.intent.register.template` makes an intent matchable. | **xfail** (legacy `padatious:register_intent`) |
| `TestSec7EntityRegistration` | §7, §2 | `ovos.entity.register` value-set hint is accepted with no ack/error. | **xfail** (legacy `register_vocab`) |
| `TestSec82Deregister` | §8.2 | `ovos.intent.deregister` removes one intent. | **xfail** |
| `TestSec83EntityDeregister` | §8.3 | `ovos.entity.deregister` removes one entity. | **xfail** |
| `TestSec84SkillDeregister` | §8.4 | `ovos.skill.deregister` removes a whole skill's intents. | **xfail** (legacy `detach_skill`) |
| `TestSec85Disable` | §8.5 | `ovos.intent.disable` suppresses an intent. | **xfail** |
| `TestSec85Enable` | §8.5 | `ovos.intent.enable` re-arms a disabled intent. | **xfail** |
| `TestSec10Introspection` | §10.1, §10.2 | `ovos.intent.list` / `ovos.intent.describe` introspection responds. | **xfail** (legacy `intent.service.intent.get`) |

## OVOS-CONVERSE-1 — `test_converse1_conformance.py`

*Active Handlers and Interactive Response Specification.* Driven by the real
`ovos-skill-parrot` fixture against ovos-core's in-process converse pipeline.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec3Activation` | §3 | Dispatching to a converse-capable skill records it as an active converse owner of the session. | green |
| `TestSec4ConverseRoundTrip` | §4, §6.4 | An active owner consumes the follow-up via `converse:skill` before normal matching; parrot echoes it; terminates once. | green |
| `TestSec4Decline` | §4 | With no active owner, converse declines and the utterance falls through to the normal pipeline (no `converse:skill`). | green |
| `TestSec21OwnerOrdering.test_most_recent_owner_first` | §2.1 | Re-activating an owner moves it to the head of `active_skills` (index 0). | green |
| `TestSec21OwnerOrdering.test_converse_handlers_reflects_owner` | §2.1 | `session.converse_handlers` carries the active owner head-first. | skip-guarded (bus-client field) |

## OVOS-FALLBACK-1 — `test_fallback1_conformance.py`

*Fallback Pipeline Plugin Specification.* Driven by the real
`ovos-skill-fallback-unknown` priority-100 catch-all, pinned *after* the matcher
so it only runs on a no-match.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec5FallbackOrdering` | §5, §6.4, §6 | Fallback fires only after matchers decline; the query (ping) precedes any handler dispatch. | green |
| `TestSec6QueryResponse` | §6.1, §6.2, §6.4 | The query cycle emits `ovos.skills.fallback.ping`/`.pong`; the chosen skill emits `<skill_id>.response`; terminates once. | green |
| `TestSec5Priority` | §5 | The pool is queried in registered-priority ascending order (lower number = higher confidence first). | green |
| `TestSec4Registration.test_spec_register_topic_consumed` | §4 | Registering on `ovos.fallback.register` makes the handler poolable. | **xfail** (core consumes `ovos.skills.fallback.register`) |
| `TestSec4Registration.test_fallback_handlers_session_field` | §4 | `session.fallback_handlers` orders the pool. | skip-guarded (bus-client field) |

## OVOS-SESSION-1 / OVOS-SESSION-2 — `test_session_conformance.py`

*Session Specification* and *Session Lifecycle and State Ownership Specification.*
A cross-cutting suite over the session-resident state that PIPELINE-1, CONVERSE-1
and FALLBACK-1 each own, asserting the orchestrator carries, updates, and echoes
the session correctly. Spec session-field names are probed at runtime; clauses on
the legacy carrier are green, clauses naming the spec field skip until
`ovos-bus-client` populates it.

| Class | Owning spec clause | Asserts | Status |
|-------|--------------------|---------|--------|
| `TestActiveHandlerRecency` | PIPELINE-1 §7.1 | Dispatch records the skill in the session's active list (echoed on the response); re-activation is head-first dedup. | green |
| `TestActiveHandlerRecency.test_active_handlers_spec_field` | PIPELINE-1 §7.1 | `session.active_handlers` carries the dispatched skill head-first. | skip-guarded |
| `TestConverseOwnerOrdering` | CONVERSE-1 §2.1 | Converse owners ordered most-recently-activated first. | green |
| `TestConverseOwnerOrdering.test_converse_handlers_spec_field` | CONVERSE-1 §2.1 | `session.converse_handlers` mirrors that ordering. | skip-guarded |
| `TestResponseMode.test_get_response_enable_sets_response_state` | CONVERSE-1 §2.2 | Enabling get-response marks the skill RESPONSE; disabling clears it back to INTENT. | green |
| `TestResponseMode.test_response_mode_spec_field` | CONVERSE-1 §2.2 | `session.response_mode` names the owner holding response mode. | skip-guarded |
| `TestFallbackHandlersField` | FALLBACK-1 §4 | `session.fallback_handlers` is carried on the session. | skip-guarded |
| `TestUpdatedSessionEcho` | SESSION-2 §2, §2.6 | The echoed session keeps the entry `session_id`; a pipeline-side mutation rides forward on the response. | green |

---

## Roadmap specs

The remaining 13 architecture specs have no conformance suite yet. They define
conformant behavior the harness intends to certify the same way:

- **OVOS-MSG-1** — Bus Message: topic-shape and identifier-component rules
  (`source`/`destination`, no central correlation id) that underpin every other
  spec's message shapes.
- **OVOS-AUDIO-IN-1** — Audio Input Service: the listener bus surface.
- **OVOS-AUDIO-1** — Audio Output Service: the TTS/playback bus surface.
- **OVOS-BRIDGE-1** — Bus Bridge and Opaque Relay.
- **OVOS-COMMON-QUERY-1** — Common Query Pipeline Plugin: the query/answer cycle.
- **OVOS-GUI-1** — GUI Display Subsystem.
- **OVOS-INTENT-1 / -2 / -3** — Sentence Template Grammar, Locale Resource Formats,
  Intent Definition.
- **OVOS-CONTEXT-1** — Intent Context.
- **OVOS-OCP-1** — OVOS Common Playback (the virtual media player).
- **OVOS-PERSONA-1** — Persona Pipeline Plugin.
- **OVOS-TRANSFORM-1** — Transformer Plugins.

## See also

- [known-gaps.md](known-gaps.md) — the live `xfail` clauses, with the spec-vs-impl
  detail.
- [writing-conformance-tests.md](writing-conformance-tests.md) — how a clause becomes
  a row in this table.
</content>
