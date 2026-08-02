# Coverage — spec-to-suite traceability matrix

This is the authoritative record of which
[`OpenVoiceOS/architecture`](https://github.com/OpenVoiceOS/architecture)
specs the harness proves conformance against. For each implemented suite it
lists which spec sections are asserted and at what status.

Status legend:

- **green** — the pinned stack satisfies the clause. The test asserts the
  spec behavior and passes.
- **xfail** — a documented conformance gap (see [known-gaps.md](known-gaps.md)).
  The test asserts the spec behavior. The current implementation still does
  the legacy thing. It flips to a pass automatically when the implementation
  lands.
- **skip-guarded** — green when the relevant producer or session field is
  installed, and skipped cleanly when it is not (probed at runtime).

## Top-level matrix

The architecture `dev` branch carries 21 specs. All 21 are covered by 21
conformance suites. SESSION-1 and SESSION-2 share one suite. INTENT-4 is
covered by both an orchestrator suite and a per-plugin
registration-compliance suite.

| Architecture spec | Spec ID | Suite | Status |
|-------------------|---------|-------|--------|
| Utterance Lifecycle and Pipeline | OVOS-PIPELINE-1 | `test_pipeline1_conformance.py` | implemented |
| Stop Pipeline Plugin | OVOS-STOP-1 | `test_stop1_conformance.py` | implemented |
| Intent & Entity Registration Bus Contract | OVOS-INTENT-4 | `test_intent4_conformance.py` (orchestrator) + `test_intent4_plugins_conformance.py` (per-plugin) | implemented |
| Active Handlers & Interactive Response | OVOS-CONVERSE-1 | `test_converse1_conformance.py` | implemented |
| Fallback Pipeline Plugin | OVOS-FALLBACK-1 | `test_fallback1_conformance.py` | implemented |
| Session Specification | OVOS-SESSION-1 | `test_session_conformance.py` | implemented |
| Session Lifecycle & State Ownership | OVOS-SESSION-2 | `test_session_conformance.py` | implemented |
| Bus Message | OVOS-MSG-1 | `test_msg1_conformance.py` | implemented |
| Audio Input Service | OVOS-AUDIO-IN-1 | `test_audio_in_conformance.py` | implemented |
| Audio Output Service | OVOS-AUDIO-1 | `test_audio_out_conformance.py` | implemented |
| Bus Bridge & Opaque Relay | OVOS-BRIDGE-1 | `test_bridge1_conformance.py` | implemented |
| Common Query Pipeline Plugin | OVOS-COMMON-QUERY-1 | `test_common_query1_conformance.py` | implemented |
| GUI Display Subsystem | OVOS-GUI-1 | `test_gui1_conformance.py` | implemented |
| Sentence Template Grammar | OVOS-INTENT-1 | `test_intent1_conformance.py` | implemented |
| Locale Resource Formats | OVOS-INTENT-2 | `test_intent2_conformance.py` | implemented |
| Intent Definition | OVOS-INTENT-3 | `test_intent3_conformance.py` | implemented |
| Intent Context | OVOS-CONTEXT-1 | `test_context1_conformance.py` | implemented |
| OVOS Common Playback (OCP) | OVOS-OCP-1 | `test_ocp1_conformance.py` | implemented |
| Persona Pipeline Plugin | OVOS-PERSONA-1 | `test_persona1_conformance.py` | implemented |
| Transformer Plugins | OVOS-TRANSFORM-1 | `test_transform1_conformance.py` | implemented |
| User Identity Resolution | OVOS-USER-ID-1 | `test_user_id1_conformance.py` | implemented |

---

## OVOS-PIPELINE-1 — `test_pipeline1_conformance.py`

*Utterance Lifecycle and Pipeline Specification.* Asserts the §11
conformance clauses and the message-shape rules against the ovos-core
orchestrator. During the namespace transition, both the legacy and the spec
topics are emitted, so every clause is green.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec5EffectivePipeline` | §5.1 | A known stage in `session.pipeline` matches & dispatches. An unknown `pipeline_id` is skipped, not aborted. | green |
| `TestSec53BlacklistBackstop` | §5.3 | A match whose `skill_id` is in `session.blacklisted_skills` is suppressed (orchestrator backstop). Utterance still terminates. | green |
| `TestSec95EndMarker` | §6.4, §9.5 | Exactly one `ovos.utterance.handled` per utterance on the no-match and stop terminal paths. | green |
| `TestSec7Dispatch` | §7, §7.1 | Dispatch topic is exactly `<skill_id>:<intent_name>`. `data.utterance` forwarded verbatim. `context.skill_id` and `context.pipeline_id` stamped. | green |
| `TestSec8HandlerTrio` | §8.1 | A handler invocation is wrapped by `ovos.intent.handler.start` + exactly one `ovos.intent.handler.complete`. | skip-guarded (workshop) |
| `TestSec91Entry` | §9.1 | An utterance fed on `ovos.utterance.handle` runs the lifecycle to the end-marker. | green |
| `TestSec92Matched` | §9.2 | A successful match emits `ovos.intent.matched`. | green |
| `TestSec93Unmatched` | §9.3 | No-match emits `ovos.intent.unmatched` before the end-marker. | green |
| `TestSec96Speak` | §9.6 | A speaking handler emits on `ovos.utterance.speak`. | skip-guarded (workshop) |
| `TestSec64Cancelled` | §6.4 | A `context['canceled']` utterance emits `ovos.utterance.cancelled`, terminates once, and never dispatches. | green |
| `TestSec81HandlerError` | §8.1 | A raising handler emits `ovos.intent.handler.error`. The utterance still terminates with exactly one end-marker. | skip-guarded (workshop) / green |

## OVOS-STOP-1 — `test_stop1_conformance.py`

*Stop Pipeline Plugin Specification.* Asserts the §9 conformance clauses
and the §8 bus surface against ovos-core's in-process stop pipeline.
Deterministic on a `FakeBus`.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec5GlobalStop` | §4.1 step 1, §5.1, §5.3 | A generic `stop` with empty active handlers terminates once and broadcasts `ovos.stop`. | green |
| `TestSec5GlobalStop.test_global_stop_dispatch_topic` | §3.1, §5.2 | Global stop dispatched on `<stop_plugin_id>:global_stop`. | **xfail** (core emits legacy `stop:global`) |
| `TestSec42PingPong` | §4.1 step 2, §4.2 | With active handlers, the stop plugin broadcasts `ovos.stop.ping` and collects `ovos.stop.pong`. The stoppable skill is then told to stop. | green |
| `TestSec43PerSkillStop` | §4.1 step 3, §4.3, §4 | An active skill yields a targeted `<skill_id>.stop` (not the broadcast). No active skill escalates to the `ovos.stop` global. | green |
| `TestSec2ReservedName` | §2 (+ INTENT-4 §5.3 / PIPELINE-1 §7.3) | A registration naming the reserved `stop` is malformed and must not become matchable. | **xfail** (core does not reject it) |

## OVOS-INTENT-4 — `test_intent4_conformance.py`

*Intent and Entity Registration Bus Contract.* Asserts the §11 conformance
clauses and the §4 registration bus surface. ovos-core does not yet expose
this bus contract. Registration is the legacy in-process
`padatious:register_intent`, and introspection is the legacy
`intent.service.intent.get`. Most registration clauses are xfail and flip
green when the contract lands.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec2FireAndForget` | §2 | A registration is fire-and-forget — no `.response`, ack, or error event. | green |
| `TestSec5KeywordRegistration` | §5 | `ovos.intent.register.keyword` makes an intent matchable. | **xfail** (legacy `padatious:register_intent`) |
| `TestSec6TemplateRegistration` | §6 | `ovos.intent.register.template` makes an intent matchable. | **xfail** (legacy `padatious:register_intent`) |
| `TestSec7EntityRegistration` | §7, §2 | `ovos.entity.register` value-set hint is accepted with no ack/error. | green |
| `TestSec82Deregister` | §8.2 | `ovos.intent.deregister` removes one intent. | green |
| `TestSec83EntityDeregister` | §8.3 | `ovos.entity.deregister` removes one entity. | green |
| `TestSec84SkillDeregister` | §8.4 | `ovos.skill.deregister` removes a whole skill's intents. | green |
| `TestSec85Disable` | §8.5 | `ovos.intent.disable` suppresses an intent. | **xfail** |
| `TestSec85Enable` | §8.5 | `ovos.intent.enable` re-arms a disabled intent. | green |
| `TestSec10Introspection` | §10.1, §10.2 | `ovos.intent.list` / `ovos.intent.describe` introspection responds. | **xfail** (legacy `intent.service.intent.get`) |
| `TestSec53MalformedRejection` | §2, §3.2, §5.3, §6.2 | A malformed registration (no `samples` / empty value-set) draws no ack/error and is not indexed; a later well-formed registration on the same skill still matches (no crash/corruption). The §5.3 WARN-log rule is not bus-observable. | green |
| `TestSec8DeregisterUnregistered` | §8 | Deregistering a never-registered skill is a no-op — no ack/error, and a later well-formed registration still matches. | green |

## OVOS-INTENT-4 (per-plugin) — `test_intent4_plugins_conformance.py`

*Per-plugin registration compliance.* Where the orchestrator suite above
asserts the INTENT-4 bus contract against ovos-core, this data-driven suite
asserts it against each individual intent-pipeline plugin: that the matcher
consumes the INTENT-4 spec registration topic (§5 keyword / §6 template) and
becomes matchable, and that the legacy registration path still matches
(back-compat). One `E2EPipelineHarness` subclass is generated per plugin
from the module-level `PLUGINS` registry. A plugin absent from the
installed combo skips its own case.

Engine kind selects the spec topic. Keyword engines (adapt, palavreado)
consume `ovos.intent.register.keyword`. Template engines (padacioso,
nebulento, padatious, m2v, linha-fina, markov) consume
`ovos.intent.register.template`.

| Plugin | Engine | `test_spec_registration_is_matchable` | `test_legacy_registration_still_matches` |
|--------|--------|----------------------------------------|-------------------------------------------|
| adapt | keyword | **xfail** (kept `@dev`, load-bearing for the INTENT-3 suite. §5 consumer not on `@dev`) | green |
| palavreado | keyword | green (`@dev`, adoption merged) | green |
| padacioso | template | **xfail** (kept `@dev`, load-bearing `PADACIOSO_HIGH` driver. §6 consumer not on `@dev`) | green |
| nebulento | template | green (`@dev`, adoption merged) | green |
| padatious | template | green (`@feat/intent-4-adoption`) | green |
| m2v | template | green (`@feat/intent-4-adoption`, prototype mode, real `minishlab/potion-base-2M`) | green |
| linha-fina | template | green (`@dev`, adoption merged) | green |
| markov | template | green (`@dev`, adoption merged) | green |

Only the adapt and padacioso spec tests are xfail. Both are deliberately
kept `@dev` because they are load-bearing for the orchestrator suites.

## OVOS-CONVERSE-1 — `test_converse1_conformance.py`

*Active Handlers and Interactive Response Specification.* Driven by the
real `ovos-skill-parrot` fixture against ovos-core's in-process converse
pipeline.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec3Activation` | §3 | Dispatching to a converse-capable skill records it as an active converse owner of the session. | green |
| `TestSec4ConverseRoundTrip` | §4, §6.4 | An active owner consumes the follow-up via `converse:skill` before normal matching. Parrot echoes it. Terminates once. | green |
| `TestSec4Decline` | §4 | With no active owner, converse declines and the utterance falls through to the normal pipeline (no `converse:skill`). | green |
| `TestSec21OwnerOrdering.test_most_recent_owner_first` | §2.1 | Re-activating an owner moves it to the head of `active_skills` (index 0). | green |
| `TestSec21OwnerOrdering.test_converse_handlers_reflects_owner` | §2.1 | `session.converse_handlers` carries the active owner head-first. | skip-guarded (bus-client field) |

## OVOS-FALLBACK-1 — `test_fallback1_conformance.py`

*Fallback Pipeline Plugin Specification.* Driven by the real
`ovos-skill-fallback-unknown` priority-100 catch-all, pinned after the
matcher so it only runs on a no-match.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec5FallbackOrdering` | §5, §6.4, §6 | Fallback fires only after matchers decline. The query (ping) precedes any handler dispatch. | green |
| `TestSec6QueryResponse` | §6.1, §6.2, §6.4 | The query cycle emits `ovos.skills.fallback.ping`/`.pong`. The chosen skill emits `<skill_id>.response`. Terminates once. | green |
| `TestSec5Priority` | §5 | The pool is queried in registered-priority ascending order (lower number = higher confidence first). | green |
| `TestSec4Registration.test_spec_register_topic_consumed` | §4 | Registering on `ovos.fallback.register` makes the handler poolable. | **xfail** (core consumes `ovos.skills.fallback.register`) |
| `TestSec4Registration.test_fallback_handlers_session_field` | §4 | `session.fallback_handlers` orders the pool. | skip-guarded (bus-client field) |

## OVOS-SESSION-1 / OVOS-SESSION-2 — `test_session_conformance.py`

*Session Specification* and *Session Lifecycle and State Ownership
Specification.* A cross-cutting suite over the session-resident state that
PIPELINE-1, CONVERSE-1, and FALLBACK-1 each own, asserting the orchestrator
carries, updates, and echoes the session correctly. Spec session-field
names are probed at runtime. Clauses on the legacy carrier are green.
Clauses naming the spec field skip until `ovos-bus-client` populates it.

| Class | Owning spec clause | Asserts | Status |
|-------|--------------------|---------|--------|
| `TestActiveHandlerRecency` | PIPELINE-1 §7.1 | Dispatch records the skill in the session's active list (echoed on the response). Re-activation is head-first dedup. | green |
| `TestActiveHandlerRecency.test_active_handlers_spec_field` | PIPELINE-1 §7.1 | `session.active_handlers` carries the dispatched skill head-first. | skip-guarded |
| `TestConverseOwnerOrdering` | CONVERSE-1 §2.1 | Converse owners ordered most-recently-activated first. | green |
| `TestConverseOwnerOrdering.test_converse_handlers_spec_field` | CONVERSE-1 §2.1 | `session.converse_handlers` mirrors that ordering. | skip-guarded |
| `TestResponseMode.test_get_response_enable_sets_response_state` | CONVERSE-1 §2.2 | Enabling get-response marks the skill RESPONSE. Disabling clears it back to INTENT. | green |
| `TestResponseMode.test_response_mode_spec_field` | CONVERSE-1 §2.2 | `session.response_mode` names the owner holding response mode. | skip-guarded |
| `TestFallbackHandlersField` | FALLBACK-1 §4 | `session.fallback_handlers` is carried on the session. | skip-guarded |
| `TestUpdatedSessionEcho` | SESSION-2 §2, §2.6 | The echoed session keeps the entry `session_id`. A pipeline-side mutation rides forward on the response. | green |
| `TestSec21OmissionAndNull` | SESSION-1 §2.1 | An omitted field resolves to the deployment default; an explicit `null` is treated as omitted (not a deferral sentinel) and is not rejected. | green |
| `TestSec31SessionIdentity` | SESSION-1 §3.1 | An empty/absent session resolves to `session_id: "default"`. | **xfail** (bus-client mints a random uuid) |
| `TestSec31PerSessionKeying` | SESSION-1 §3.1 (spec §227) | Per-session state is keyed on `session_id` — an active handler in session A is not visible to session B. | green |
| `TestSec21BusStateless` | SESSION-2 §2.1 (spec §543) | The bus leaves `session` byte-identical in transit — it does not interpret, mutate, or persist it. | green |

---

## OVOS-GUI-1 — `test_gui1_conformance.py`

*GUI Display Subsystem Specification.* A bus-protocol spec with two
observable surfaces: the producer wire shape (driven through the real
`ovos_bus_client.apis.gui.GUIInterface` on a `FakeBus`) and the GUI service
contract (driven through `ovos_gui.namespace.NamespaceManager` on the core
bus). Rendering, adapter fan-out, and the QML client transport are not
bus-observable and are excluded with `# not bus-observable` notes.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec2VoiceFirst` | §2.3 | The producer emits its wire protocol with no display/adapter attached (functions headless). | green |
| `TestSec3ClosedVocabulary` | §3.1, §3.2 | A producer names only closed-vocabulary `SYSTEM_*` templates. The emitted name has the `SYSTEM_` prefix. | xfail (legacy `SYSTEM_*Frame` names) / green (prefix) |
| `TestSec33TypingRules` | §3.3 | A producer omits absent optional keys rather than emitting JSON `null`. | xfail (`__idle: null`, `None` content keys) |
| `TestSec35ImageDelivery` | §3.5 | `http(s)` image URLs pass through. A local asset is resolved to a `data:` URI, never a bare filesystem path. | green (http) / xfail (local→fs path) |
| `TestSec41ReservedKeys` | §4.1 | Every GUI Message carries `__from` naming the producing namespace. | green |
| `TestSec42Messages` | §4.2 | `gui.value.set` carries the flat content map + `__from`. `gui.page.show` carries `page_names`/`index` with a `SYSTEM_*` first entry. `gui.clear.namespace` carries `__from`. | green |
| `TestSec81ProducerConformance` | §8.1 | Producer-MUST roll-up: `gui.page.show` present. All template names in the closed vocabulary. | green / xfail (vocabulary) |
| `TestSec32ServiceTemplateGate` | §3.2, §4.2, §8.3 | The service dispatches only `SYSTEM_*` page names. A non-`SYSTEM_` page is not loaded as a namespace. | xfail (loads any page) / green (SYSTEM_ loads) |
| `TestSec41ServiceStripsReservedKeys` | §4.1 | The service declares the reserved `__from`/`__idle` keys it strips. | green |
| `TestSec43Sec5PerSessionRouting` | §4.3, §5.1, §8.3 | The service maintains an independent namespace stack per `session_id`. | xfail (single global stack) |
| `TestSec83ServiceConformance` | §8.3, §6.1, §4.3 | The service starts with zero adapters (headless). Emits `gui.namespace.removed` on clear. | green |
| `TestSec72InteractionResponse` | §7.2 | Interaction response carries the originating `session_id`. | skip (adapter-emitted, not bus-observable) |

Not encoded (excluded with `# not bus-observable` notes): §6.1–§6.9 adapter
discovery, construction, fan-out, degradation, exception isolation, state
query, connection-status, and idle-display ownership, plus §7.1 media
transport, all of which live inside an adapter or on the backend's QML
client transport.

---

## OVOS-BRIDGE-1 — `test_bridge1_conformance.py`

*Bus Bridge and Opaque Relay Specification.* BRIDGE-1 is mostly emergent:
behaviors that arise when MSG-1, SESSION-1, and SESSION-2 compose across a
bus boundary. No bridge component is in the stack (the reference is
HiveMind), so the suite asserts the bus-observable composition primitives
the bridge relies on against the real ovos-core orchestrator, and documents
the bridge-only MUSTs with `# not bus-observable (no bridge in stack)`
skips.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec31SourceStamping` | §3.1 | Unique `context.source` stamped per inbound. A present `source` is honoured for response routing. | green (routing) / skip (stamping needs a bridge) |
| `TestSec32OutboundRouting` | §3.2 | The orchestrator `.reply()`s with `destination` set to the inbound `source`. MSG-1 derivations swap/preserve source/destination. | green |
| `TestSec33SiteId` | §3.3 | `site_id` survives the orchestrator round and every derivation unchanged. Opaque string round-trips. Absent yields no default. | green / xfail (defaults to `'unknown'`) |
| `TestSec34SessionPreservation` | §3.4, §3.4.2 | Inbound session is authoritative for the round. Responses include the session. Managing-mode synthesis needs a bridge. | green / skip (synthesis) |
| `TestSec44SatelliteRegistration` | §4.4 | `ovos.skill.deregister` is the spec-named deregister topic. Disconnect emission needs a bridge. | green / skip (emission) |
| `TestSec5Ordering` | §5 | Grace-period discard and FIFO ordering. | skip (bridge-internal, not bus-observable) |
| `TestSec6Msg1Conformance` | §6 | Every orchestrator emission is a valid MSG-1 envelope. The carried session is a valid SESSION-1 object. | green |

---

## OVOS-USER-ID-1 — `test_user_id1_conformance.py`

*User Identity Resolution Specification.* Asserts the §9 conformance
clauses. No recognition plugin and no bridge is installed, so the
producer-side clauses (§3 level derivation, §5 resolution, §5.1
persistence, §6 Layer-2 injection) carry a `# not bus-observable` skip. The
consumer-side MUSTs run end-to-end against the orchestrator: an absent
`user_id` is a guest, an absent `auth_level` reads as `0`, and no component
errors on either.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec2IdentityFields` | §2, §9 | An unresolved identity leaves `user_id` absent (no sentinel). Per-signal fields absent until a recognizer sets them. The carrier declares the fields. | green / xfail (conditional: bus-client Session lacks the fields) |
| `TestSec3AuthLevel` | §3, §9 | A consumer reads an absent `auth_level` as `0`. An anonymous session presents `0`. A carried level survives the round unchanged. | green / skip (level derivation needs a plugin) |
| `TestSec5And6Resolution` | §5, §5.1, §6 | The plugin writes its fields before the pipeline. Identity persists across utterances. A bridge may inject directly. | skip (no recognition plugin, no bridge) |
| `TestSec7GuestFallback` | §7, §9 | An anonymous utterance completes the round with no error event, terminates exactly once, and never invents a `user_id`. | green |
| `TestSec9Consumers` | §9, MSG-1 §5 | Identity fields ride every forward/reply/response derivation unchanged. An identified utterance completes the round like an anonymous one. | green |

---

## Mixed-version back-compat matrix (`test/backcompat/`)

Not a conformance suite: no specification mandates the legacy suffixed intent
topic. OVOS-MSG-1 §2.1.1 (the identifier-separator rule that makes a
`<skill_id>:<intent_name>` dispatch topic unambiguously parseable) is covered
by `test_msg1_conformance.py::TestSec211IdentifierSeparator`, not here. This
suite pins **transitional** behaviour — that a stack in the middle of the
INTENT-4 topic migration does not silently drop skill containers built before
it.

It is the only suite here that runs two package sets at once, so it is the
only one that can observe a cross-version break at all.

| Cell | Skill venv | Core venv | Asserts | Status |
|------|-----------|-----------|---------|--------|
| `old-skill/old-core` | `ovos-workshop==9.3.1a2` | `ovos-core==2.5.5a2` + `ovos-padatious==2.0.0a1` | suffixed dispatch reaches the suffixed binding | green (control) |
| `old-skill/new-core` | `ovos-workshop==9.3.1a2` | `ovos-core@dev` + `ovos-padatious>=2.0.1a2` | canonical dispatch must reach a suffixed-only binding | **xfail(strict)** — needs [bus-client#271](https://github.com/OpenVoiceOS/ovos-bus-client/pull/271) |
| `new-skill/old-core` | `ovos-workshop@dev` | `ovos-core==2.5.5a2` + `ovos-padatious==2.0.0a1` | suffixed dispatch reaches the dual binding | green (control; goes red on [workshop#500](https://github.com/OpenVoiceOS/ovos-workshop/pull/500)) |
| `new-skill/new-core` | `ovos-workshop@dev` | `ovos-core@dev` + `ovos-padatious>=2.0.1a2` | canonical dispatch fires the handler exactly once | green (control + double-fire guard) |

Every cell also asserts its own pins: the bindings the skill venv actually
made, and whether the core venv canonicalizes at registration. A release that
quietly changes either fails as a wrong-vintage error rather than turning the
red cell green.

---

## See also

- [known-gaps.md](known-gaps.md) — the live `xfail` clauses, with the
  spec-vs-impl detail.
- [writing-conformance-tests.md](writing-conformance-tests.md) — how a
  clause becomes a row in this table.

---
[← Writing conformance tests](writing-conformance-tests.md) · [Home](../README.md) · [CI →](ci.md)
