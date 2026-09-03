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

The architecture `dev` branch carries 20 specs. All 20 are covered by 20
conformance suites, each with its own `## OVOS-...` detail section below.
SESSION-1 and SESSION-2 share one suite. INTENT-4 is covered by both an
orchestrator suite and a per-plugin registration-compliance suite.

`OVOS-USER-ID-1` is not tracked here: no such document exists among the
ratified `OpenVoiceOS/architecture` specs, so there is nothing to trace
suite coverage against.

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
| `TestSec42PingPong.test_ping_broadcast_topic` / `.test_pong_reply_from_active_skill` | §4.1 step 2, §4.2 | With active handlers, the stop plugin is meant to broadcast `ovos.stop.ping` and collect `ovos.stop.pong`. | **xfail** (core dispatches the per-skill `<skill_id>.stop.ping` directly and never emits the broadcast ping or `ovos.stop.pong`; ovos-core#802) |
| `TestSec43PerSkillStop` | §4.1 step 3, §4.3, §4 | An active skill yields a targeted `<skill_id>.stop` (not the broadcast). No active skill escalates to the `ovos.stop` global. | green |
| `TestSec2ReservedName.test_reserved_stop_registration_not_dispatched` | §2 (+ INTENT-4 §5.3 / PIPELINE-1 §7.3) | A registration naming the reserved `stop` is malformed and must not become matchable. | **xfail** (core does not reject it) |

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
| `TestSec5KeywordRegistration.test_spec_keyword_registration_is_matchable` | §5 | `ovos.intent.register.keyword` makes an intent matchable. | **xfail** (legacy `padatious:register_intent`) |
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
| `TestLocationTimezoneContract` | implementation-contract, not a SESSION-1 §3 field | `location` (`Session.location_preferences`) round-trips serialize/deserialize byte-stable, including nested `timezone.code`; `Session.timezone` reads that code; a per-session zone wins over the deployment-configured zone through `SessionManager.get(message)`; an absent session zone falls back to the configured one. Pins the surface `ovos-skill-alerts`#183's two-sessions-two-timezones DST differential depends on end-to-end, at the producing repo instead of only downstream. | green |

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
| `TestSec3ClosedVocabulary.test_show_text_names_closed_vocabulary_template` / `.test_show_image_names_closed_vocabulary_template` / `.test_show_face_names_closed_vocabulary_template` | §3.1, §3.2 | A producer names only closed-vocabulary `SYSTEM_*` templates. The emitted name has the `SYSTEM_` prefix. | xfail (legacy `SYSTEM_*Frame` names) / green (prefix) |
| `TestSec33TypingRules.test_absent_optional_keys_are_omitted_not_null` | §3.3 | A producer omits absent optional keys rather than emitting JSON `null`. | xfail (`__idle: null`, `None` content keys) |
| `TestSec35ImageDelivery.test_local_image_resolved_to_data_uri` | §3.5 | `http(s)` image URLs pass through. A local asset is resolved to a `data:` URI, never a bare filesystem path. | green (http) / xfail (local→fs path) |
| `TestSec41ReservedKeys` | §4.1 | Every GUI Message carries `__from` naming the producing namespace. | green |
| `TestSec42Messages` | §4.2 | `gui.value.set` carries the flat content map + `__from`. `gui.page.show` carries `page_names`/`index` with a `SYSTEM_*` first entry. `gui.clear.namespace` carries `__from`. | green |
| `TestSec81ProducerConformance.test_all_template_names_in_closed_vocabulary` | §8.1 | Producer-MUST roll-up: `gui.page.show` present. All template names in the closed vocabulary. | green / xfail (vocabulary) |
| `TestSec32ServiceTemplateGate.test_non_system_page_not_loaded_as_template` | §3.2, §4.2, §8.3 | The service dispatches only `SYSTEM_*` page names. A non-`SYSTEM_` page is not loaded as a namespace. | xfail (loads any page) / green (SYSTEM_ loads) |
| `TestSec41ServiceStripsReservedKeys` | §4.1 | The service declares the reserved `__from`/`__idle` keys it strips. | green |
| `TestSec43Sec5PerSessionRouting.test_independent_stack_per_session` | §4.3, §5.1, §8.3 | The service maintains an independent namespace stack per `session_id`. | xfail (single global stack) |
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

## OVOS-MSG-1 — `test_msg1_conformance.py`

*Bus Message Specification.* Asserts the §7 conformance clauses against the
runtime envelope, `ovos_bus_client.message.Message` — the type every
component on the bus actually exchanges — rather than the reference
`ovos_spec_tools.message.Message`. Every clause is green: the installed
bus-client envelope already conforms.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec2Envelope` | §2 | The envelope carries exactly `type`/`data`/`context`; an absent `data`/`context` is treated as empty; unknown top-level keys are rejected. | green |
| `TestSec21Type` | §2.1 | `type` is a non-empty, whitespace-free string matching the topic syntax. | green |
| `TestSec22Data` | §2.2 | `data` is a JSON object; consumers MUST NOT reject a Message on key order. | green |
| `TestSec23Context` | §2.3 | `context` is topic-independent metadata; a consumer MUST NOT reject on unrecognised keys; an empty `context` is well-formed. | green |
| `TestSec211IdentifierSeparator` | §2.1.1 | A topic assembled from colon-free component identifiers stays unambiguously parseable; an identifier containing `:` breaks that guarantee. | green |
| `TestSec3Routing` | §3.2, §3.3, §3.4 | `source`/`destination` are opaque routing strings, round-tripping verbatim; `destination` MAY be an array; absence means broadcast. | green |
| `TestSec4Session` | §4, §4.1 | `session` rides inside `Message.context`; propagation (`forward`) preserves it unchanged; a producer MUST NOT mutate an already-present session. | green |
| `TestSec51Forward` | §5.1 | `forward(T', D')` produces `{type: T', data: D', context: C}`, preserving `context` (including `source`/`destination`) unchanged. | green |
| `TestSec52Reply` | §5.2 | `reply(T', D')` copies `C` and reverses the §3 routing keys (source/destination swap); other context keys are preserved; mutating the reply's context does not affect the source. | green |
| `TestSec53Response` | §5.3 | `response(D')` is equivalent to `reply(T + '.response', D')`, delegating to the §5.2 routing swap. | green |
| `TestSec6Serialization` | §6 | A Message serializes to a single top-level UTF-8 JSON object; key order is not significant; a non-finite `data` number rejects rather than serializing; an unparseable payload is treated as malformed. | green |
| `TestSec7Conformance` | §7 | Producer MUST give `data`/`context` JSON-object values when present; consumer MUST NOT require `source`, `destination`, or other optional context keys. | green |

## OVOS-AUDIO-IN-1 — `test_audio_in_conformance.py`

*Audio Input Service Specification.* Asserts the §7 conformance clauses and
the §6.5 bus surface against the real
`ovos_dinkum_listener.service.OVOSDinkumVoiceService`, with all acquisition
plugins (mic/VAD/STT/hotwords) mocked — audio *acquisition* is out of scope
(§1). The bus runs single-namespace (no legacy bridge) so each assertion
sees what the service natively emits.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec5UtteranceEmission` | §5 | After transcription, the service emits `ovos.utterance.handle` carrying `utterances` + `lang`. | green |
| `TestSec52SessionAssignment` | §5.2 | The service assigns a session in `context.session` on every emission. | green |
| `TestSec51LanguageResolution.test_language_resolution_precedence` | §5.1 | The STT input language is resolved as `session.detected_lang` > `session.request_lang` > `session.lang` (first present wins). | **xfail** (reads `stt_context`/the deployment config, not the session) |
| `TestSec6CaptureSignals` | §6.1, §6.2 | Capture start emits `ovos.listener.record.started`; capture end emits `ovos.listener.record.ended`. | green |
| `TestSec6SleepAwoken` | §6.3, §6.4 | Sleep is requested via `ovos.listener.sleep`; waking from sleep emits `ovos.listener.awoken`. | green |
| `TestSec65BusSurface` | §6.5 | The service subscribes to `ovos.listener.sleep` and `ovos.mic.listen`. | green |

Not encoded (`# not bus-observable` note): §3/§4, the STT and
audio-transformer chains internal to acquisition.

## OVOS-AUDIO-1 — `test_audio_out_conformance.py`

*Audio Output Service Specification (audio-out).* Asserts the §8
conformance clauses and the §7 bus surface against the real
`ovos_audio.service.PlaybackService`, driven through
`ovoscope.audio.PlaybackServiceHarness` with a silent `MockTTS`. The bus
runs single-namespace (no legacy bridge) so subscriptions are read from the
service's own handler registry, not rescued by a legacy-topic bridge. Every
clause is green: the installed `ovos-audio` service already conforms.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec3LocalRendering` | §3, §8 | The service subscribes to `ovos.utterance.speak`, renders, and plays. | green |
| `TestSec5LifecycleSignals` | §5.1, §5.2 | The service emits `ovos.audio.output.started` on playback start and `ovos.audio.output.ended` on playback end. | green |
| `TestSec44ListenFlag` | §4.4 | A Message carrying `listen: true` triggers `ovos.mic.listen` after playback. | green |
| `TestSec6StopIntegration` | §6 | A stop signal on `ovos.audio.stop`/`ovos.stop` clears the queue and halts playback. | green |
| `TestSec34RemoteRendering` | §3.4 | The service subscribes to `ovos.utterance.speak.b64` and emits `ovos.audio.speech` for b64 delivery. | green |
| `TestSec41QueuedSound` | §4.1, §8 | Queued sound playback via `ovos.audio.queue` is FIFO and sequential. | green |
| `TestSec42InstantSound` | §4.2, §8 | Instant sounds play immediately on `ovos.audio.play_sound`. | green |
| `TestSec53SpeakingStatus` | §5.3 | A component may query speaking status via `ovos.audio.is_speaking`. | green |

Not encoded (`# not bus-observable` note): §3.1/§3.3, the dialog/TTS
transformer chains.

## OVOS-COMMON-QUERY-1 — `test_common_query1_conformance.py`

*Common Query Pipeline Plugin Specification.* Asserts the §14 conformance
clauses and the §13 message-shape rules as ovoscope end-to-end assertions
against ovos-core's orchestrator driving the
`ovos-common-query-pipeline-plugin` contest, with an in-process common-query
skill fixture (`_FakeWikiSkill`) as the answering skill. The discovery poll
is observable and green; the answer phase (§7 onward) is blocked by an
unrelated stack crash (the pinned plugin iterates
`session.blacklisted_skills` unconditionally, which is `None` under the
installed `ovos-bus-client`) — see [known-gaps.md](known-gaps.md) for the
full divergence note.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec6Poll.test_ping_broadcast` / `.test_pong_claim` | §6.1, §6.2 | The plugin broadcasts `ovos.common_query.ping` for discovery; a skill claims on `ovos.common_query.pong`. | green |
| `TestSec6Poll.test_ping_rebroadcast_per_utterance` | §6.1 | A NEW per-utterance contest pings before broadcasting. | **xfail** (plugin pings only at load; never re-broadcasts during match) |
| `TestSec3ReservedIntent.test_dispatch_topic_is_reserved_common_query` | §3 | The reserved `common_query` intent name dispatches on `<pipeline_id>:common_query`. | **xfail** (legacy `question:action.<skill_id>`; contest crashes) |
| `TestSec7AnswerCollection.test_full_answer_request_topic` | §7.1 | After the poll closes, the plugin requests full answers via `<skill_id>:common_query`; `.test_full_answer_response_collected` (the skill answers on `<skill_id>.common_query.response`) is green. | **xfail** (request topic; response topic is green) |
| `TestSec9And10WinningContest.test_match_skill_id_is_pipeline_id` / `.test_match_slots_answer` | §9, §10 | A winning answer yields a `Match` whose `skill_id` is the plugin's own `pipeline_id` and whose `slots.answer` carries the answer; `.test_winning_contest_speaks` (the handler speaks it) is green. | **xfail** (skill_id/slots.answer legacy shape; speak is green) |
| `TestSec9NoWinnerReachesFallback` | §9, §14 | No surviving answer yields `match` returning `None`, so the utterance reaches fallback with no spurious speak. | green |

## OVOS-INTENT-1 — `test_intent1_conformance.py`

*Sentence Template Grammar.* Asserts the §7 conformance roles (Expander,
Dialog renderer, slot model) against `ovos-spec-tools`, the reference
implementation. INTENT-1 is a file-format/grammar spec with no bus surface,
so almost every clause is asserted directly against the spec-tools API;
one class also drives an end-to-end registration/match round. Every clause
is green: `ovos-spec-tools` already conforms.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec2InputModel` | §2 | Input-direction templates are authored in normalized form; brackets cannot be literal, no escape mechanism. | green |
| `TestSec3_2Alternatives` | §3.2 | Parenthesised alternatives expand to one branch each; an empty branch contributes nothing. | green |
| `TestSec3_3Optionals` | §3.3 | `[x]` is exactly equivalent to `(x\|)`. | green |
| `TestSec3_4NamedSlots` | §3.4 | `{name}`/`{{name}}` fold to the same slot; slot names use the lowercase/digit/underscore charset with no leading digit. | green |
| `TestSec3_5Nesting` | §3.5 | Expansion groups nest without limit. | green |
| `TestSec3_6Malformed` | §3.6 | A tool MUST reject unbalanced metacharacters, single-branch groups, empty-sample templates, slot-only templates, adjacent slots, repeated slot names, and undefined/cyclic vocabulary references. | green |
| `TestSec3_7VocabularyReference` | §3.7 | `<name>` expands to its named vocabulary as alternatives. | green |
| `TestSec4Expansion` | §4 | A template expands to a finite sample set; slots stay opaque through expansion; whitespace is normalized and duplicates removed. | green |
| `TestSec5_1DialogFill` | §5.1 | A `.dialog` template with an unfilled slot MUST NOT render. | green |
| `TestSec5_5SlotConsistency` | §5.5 | A `.dialog` definition MUST NOT mix templates declaring different slot sets; an intent template MAY. | green |
| `TestE2EExpansionDrivesMatch` | §4, §6 | A template registered as training data, once expanded, actually drives an utterance match end-to-end. | green |

## OVOS-INTENT-2 — `test_intent2_conformance.py`

*Locale Resource Formats.* Asserts the normative folder-layout and
file-format clauses of INTENT-2 against `ovos-spec-tools`'s reference
loader (`LocaleResources`), common reader, whole-word matcher, and prompt
renderer, building throwaway `locale/` trees per test class. Every clause
is green.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec2FolderLayout` | §2 | Resources resolve recursively under `locale/<lang>/`; a duplicate `(role, base name)` in one lang tree is malformed; the same base name across roles is distinct; BCP-47 tags compare case-insensitively. | green |
| `TestSec3CommonReader` | §3 | The reader discards a leading BOM, accepts LF and CRLF, strips lines, skips blanks and `#`-comments, and allows no inline comments. | green |
| `TestSec4_1Intent` | §4.1 | `.intent` loads as the union of the sample sets of all its lines, slots intact. | green |
| `TestSec4_2Dialog` | §4.2 | A `.dialog` is NOT expanded at load time. | green |
| `TestSec4_3SlotFreeRoles` | §4.3 | `.entity`/`.voc`/`.blacklist` share the slot-free format; a slot-free role with a named slot is malformed; `.blacklist` occurrence is contiguous whole words. | green |
| `TestSec4_4Prompt` | §4.4 | A `.prompt` substitutes only `{{name}}` (double-brace); single/lone braces pass through; an unfilled `{{name}}` stays literal; the rest of the file is kept verbatim. | green |
| `TestSec5EmptyFile` | §5 | An empty resource file, of any role, is malformed. | green |
| `TestE2EVocOccurrence` | §4.3 | A vocabulary's whole-word occurrence in an utterance is matched end-to-end on the live keyword pipeline. | green |

## OVOS-INTENT-3 — `test_intent3_conformance.py`

*Intent Definition.* Asserts the definition/wire-shape clauses directly
against `ovos-spec-tools`'s keyword-intent data model
(`IntentBuilder`/`Intent`/`open_intent_envelope`, the §5 template
expander), and the matching-semantics clauses end-to-end against the real
adapt (keyword) and padacioso (template) pipelines. Pure-prose,
non-testable clauses are noted with a `# note: §X` comment.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec3Identity` | §3 | A qualified name parses unambiguously into two parts; an intent is identified by the triple (skill id, intent name, language). | green |
| `TestSec4KeywordDefinition.test_only_optional_and_excluded_is_malformed` / `.test_vocabulary_under_two_roles_is_malformed` | §4.2 | A keyword intent's payload exposes all four constraint roles. | green / **xfail** (no validation that at least one required/one-of constraint is declared; no validation that a vocabulary appears under at most one role) |
| `TestSec5TemplateDefinition` | §5 | A template intent is defined by sentence templates; templates in one intent share slot names. | green |
| `TestE2EKeywordConstraints` | §4.2, §4.3 | A conformant engine MUST NOT match when a required vocabulary is absent, a one-of group is unsatisfied, or an excluded vocabulary is present; each matched vocabulary doubles as a captured slot. | green |
| `TestE2ETemplateGeneralizes.test_unseen_phrasing_still_matches` | §5.1, §6.2, §7 | A capable engine generalizes beyond its templates to unseen phrasings; an engine reports at most one matched intent per utterance; a match result is `(qualified name, slots map)`. | green / **xfail** (padacioso is a literal matcher and does not generalize; padatious would pass) |

§5.3 (required-slot rules) and the registration-time "MUST be declared by
some template" rule are noted `# note: engine-specific` / `# note:
registration-time` rather than asserted — they are properties of the
engine's own registration path, exercised indirectly by the INTENT-4
per-plugin suite.

## OVOS-CONTEXT-1 — `test_context1_conformance.py`

*Intent Context.* Asserts the §8 conformance clauses and the entry / scope
/ decay / mutation / gating rules against the integrated stack. The carrier
(`session.intent_context` as an OVOS-SESSION-1 field, §2/§3/§4.1 propagation)
is exercised through the real `ovos_bus_client.Session` and is green. The
decay tick (§4) and the gating clauses (§6/§6.1) have landed against the
installed engines and are green. The `ovos.session.sync` merge (§5.3) and
context-supplied slot promotion (§7) are not yet consumed by ovos-core and
are xfail — see [known-gaps.md](known-gaps.md).

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec2EntryCarrier` | §2 | `session.intent_context` is a flat key -> entry map carried inside the session; absence is an empty map; entry fields (including a null-valued flag entry) round-trip. | green |
| `TestSec3KeyShapes` | §3 | Scope is encoded in the key — a bare key is shared, a prefixed key has exactly one separator. | green |
| `TestSec4Propagation` | §4.1 | `session.intent_context` rides forward/reply derivations and an ordinary Message unchanged. | green |
| `TestSec53SessionSyncMerge.test_sync_sets_entry` / `.test_sync_null_deletes_entry` | §5.3 | `ovos.session.sync` applies `intent_context` entry-by-entry: a co-present entry sets, a `null` entry deletes. | **xfail** (no sync-merge handler) |
| `TestSec4Decay` | §4 | Per-utterance decay: `turns_remaining` decrements after a round; a dead entry is pruned before the next match. | green (decay tick landed, ovos-core#802) |
| `TestSec6RequiresContext` | §6 | An engine MUST NOT report an intent matched unless every `requires_context` key names a live entry. | green |
| `TestSec61ExcludesContext` | §6.1 | An engine MUST NOT report an intent matched if any `excludes_context` key names a live entry. | green |
| `TestSec7ContextSuppliedSlot.test_context_value_fills_unfilled_slot` | §7 | A `requires_context` key naming an unfilled slot is promoted into `Match.slots`. | **xfail** (no context-supplied slot promotion) |
| `TestSec8ReadOnlyCarrier` | §8 | The orchestrator treats `session.intent_context` on ordinary messages as a read-only carrier. | green |

## OVOS-OCP-1 — `test_ocp1_conformance.py`

*OVOS Common Playback (the Virtual Media Player).* Asserts the OCP-1
clauses end-to-end against the real `ovos_media.player.OCPMediaPlayer`,
driven on a `FakeBus` through `ovoscope.OCPPlayerHarness` with a
`MockOCPBackend`.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec3StateModel` | §3.1, §3.2, §3.3 | `PlayerState`/`MediaState` are fixed enumerations; loop/shuffle modes are tracked; a single writer emits idempotently (no re-emit on the same state). | green |
| `TestSec41Namespace` | §4.1 | All player traffic is namespaced under `ovos.common_play.`. | green |
| `TestSec43ControlRequests.test_pause_is_noop_with_no_media` | §4.3 | Pause/resume/stop transition the player; next/stop are no-ops with no media. | green / **xfail** (pause with no media transitions to PAUSED instead of no-op) |
| `TestSec44StateReports` | §4.4 | The player announces state transitions on `…player.state` and media changes on `…media.state`. | green |
| `TestSec6Introspection` | §6 | SEI introspection responds (informative; the MPRIS bridge itself is not bus-observable on a `FakeBus`). | green |
| `TestSec7Stop` | §7 | A stop dispatch transitions now-playing to STOPPED. | green |
| `TestSec5SessionScoping.test_now_playing_is_scoped_per_session` | §5 | The Virtual Media Player is per session; a pause for one session MUST NOT affect another. | **xfail** (single global player; see [known-gaps.md](known-gaps.md)) |

## OVOS-PERSONA-1 — `test_persona1_conformance.py`

*Persona Pipeline Plugin.* Asserts the §12 conformance clauses and the
message-shape rules as ovoscope end-to-end assertions against ovos-core's
orchestrator driving the `ovos-persona-pipeline-plugin`, with a throwaway
`Alice` persona backed by the always-on `ovos-solver-failure-plugin`.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec3PersonaIdField` | §3 | `persona_id` is the session-resident field identifying the active persona. | green |
| `TestSec4NoPersonaMode.test_unsupported_persona_id_declines` | §4, §7.1 | With no persona active, the persona stage returns `None` on a neutral utterance; an unsupported `persona_id` declines. | green / **xfail** (unsupported `persona_id` still claims via `persona:query`/fallback instead of declining) |
| `TestSec5Summon` | §5, §7.1 | A summon utterance is detected and claimed during match, sets `session.persona_id`, and its dispatch is answered (confirmation spoken). | green |
| `TestSec6Dismiss` | §6, §7.1 | A release intent is detected during match and clears `session.persona_id`. | green |
| `TestSec7MatchContract` | §7.1, §7.2 | Embedded persona commands (ask/list/check) are claimed; an active persona claims a neutral (non-command) utterance; `Match.lang` is the resolved match language. | green |
| `TestSec8Handler` | §8.1 | The persona handler generates a response and emits it on `ovos.utterance.speak`. | green |
| `TestSec87Discovery` | §8.5, §8.7, §11 | The plugin responds to `ovos.persona.query`/`ovos.persona.list`, and broadcasts `ovos.persona.activated`/`ovos.persona.dismissed`. | green |
| `TestSec11DismissBroadcast` | §11 | A persona dismissed from a session broadcasts `ovos.persona.dismissed`. | green |

## OVOS-TRANSFORM-1 — `test_transform1_conformance.py`

*Transformer Plugins (the transformer-chain pattern).* Asserts the
TRANSFORM-1 clauses against the real ovos-core transformer services
(`UtteranceTransformersService`, `MetadataTransformersService`,
`IntentTransformersService`) exercised on a `FakeBus` with inline fixture
transformers injected into each service's loaded set.

| Class | Clause(s) | Asserts | Status |
|-------|-----------|---------|--------|
| `TestSec1ChainModel` | §1 | Every transformer in a chain always runs — no early exit; the last transformer's output is what proceeds. | green |
| `TestSec32Utterance` | §3.2 | The utterance chain takes an input list and returns a possibly-modified list; may mutate `Message.context`; an empty (no-transcription) list is returned as-is. | green |
| `TestSec33Metadata` | §3.3 | The metadata chain's only input and output is `Message.context`; a mutation is kept. | green |
| `TestSec34Intent.test_skill_id_invariant_enforced` | §3.4, §9 | The intent chain may enrich `Match.captures`; `Match.skill_id`/`intent_name` MUST NOT change. | green / **xfail** (identity invariant not enforced) |
| `TestSec4Ordering` | §4 | A chain runs in ascending priority order (lower number first). | green |
| `TestPerTypeContract` | §1.1 | A transformer is a `(type, transformer_id)` pair over the six defined types. | green |
| `TestSec30Lang.test_lang_is_a_threaded_parameter` | §3.0 | A bidirectional `lang` parameter is threaded through every chain (audio/utterance/dialog/TTS). | **xfail** (installed templates take no `lang` parameter) |
| `TestSec7ErrorHandling` | §7 | A raising transformer is caught and treated as if it returned its input unchanged; a wrong-shape return is treated like a raise. | green |
| `TestSec13SelfIdentification` | §1.3 | A transformer stamps its own id onto `<type>_transformer_ids` on every Message it touches. | green |
| `TestSec8Cancellation` | §8.1 | A transformer signals cancellation via `canceled`/`cancel_reason`, which propagate through the chain; the orchestrator stamps `cancel_by`. | green |
| `TestSec5PerSessionOverrides` | §5 | Six per-session `<type>_transformers` preference fields are honoured. | skip-guarded (bus-client field) |

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
- [adoption.md](adoption.md) — which OVOS repos actually adopt each spec's
  wire surface, not just which suite proves it.

---
[← Writing conformance tests](writing-conformance-tests.md) · [Home](../README.md) · [CI →](ci.md)
