# Known conformance gaps

This page catalogues the clauses where the
[`OpenVoiceOS/architecture`](https://github.com/OpenVoiceOS/architecture)
specs mandate one behavior but the current ovos-core stack still does the
legacy thing.

Each is recorded in the suite as
`@pytest.mark.xfail(strict=False, reason=...)`, asserting the spec behavior,
with a `reason` that cites the legacy topic and the spec clause.

Because the markers are `strict=False`, a gap xpasses (and so flags itself
for marker removal) the moment the implementation catches up. See
[ci.md](ci.md#interpreting-results).

The framing for every gap is the same: the spec mandates X, current core
emits or consumes the legacy Y. The test asserts X, is marked `xfail`, and
will flip to a pass when X is implemented. The harness never records Y as
conformant.

These reasons are the canonical record of the gap. They are kept verbatim
from the test decorators so this page stays accurate.

## OVOS-STOP-1

> §3.1/§5.2 (global stop dispatched on `<stop_plugin_id>:global_stop`) is
> now green against the STOP-1 conformance branch and no longer listed
> here. `TestSec5GlobalStop.test_global_stop_dispatch_topic` is plain
> conformance. The per-skill stop clauses (§4.2/§4.3, pong collection,
> `<skill_id>:stop` dispatch, active-vs-global selection) are green.

### §2: reserved intent name `stop`

- **Spec mandates:** a registration naming the reserved `stop` is malformed
  and MUST NOT be indexed, so it never becomes matchable (STOP-1 §2, with
  INTENT-4 §5.3 / PIPELINE-1 §7.3).

- **Current core:** does not reject such a registration.

- **Test:** `TestSec2ReservedName.test_reserved_stop_registration_not_dispatched`

- **`reason`:** `"ovos-core does not reject registrations naming the reserved 'stop'; STOP-1 §2 / INTENT-4 §5.3 MUST"`

## OVOS-INTENT-4

INTENT-4 defines a fixed registration/introspection bus contract under
`ovos.intent.*` / `ovos.entity.*`. Against the `ovos-workshop`
INTENT-4-producer branch, the ovos-core INTENT-4 §10 manifest consumer, and
the padacioso §6 template consumer (@dev), most of it is now green.

§6 template registration, §8.5 `ovos.intent.disable`, and §10.1/§10.2
introspection (`ovos.intent.list` / `ovos.intent.describe`) all pass and
are no longer listed. Only the §5 keyword-registration spec topic remains a
gap.

The driver in the suite is `PADACIOSO_HIGH` (a template engine), so
keyword registration via the spec topic is not matchable through it, and
core still consumes keyword registration via the legacy path.

| Clause | Spec mandates | Current core (the `reason`) | Test |
|--------|---------------|------------------------------|------|
| §5 | `ovos.intent.register.keyword` makes an intent matchable | consumes keyword registration via the legacy `padatious:register_intent`/`register_intent` | `TestSec5KeywordRegistration` |

> §2 (registrations are fire-and-forget, no ack/`.response`) is green: the
> current core already satisfies it. The deregistration/re-arm consumer has
> landed, so §7 (`ovos.entity.register`), §8.2 (`ovos.intent.deregister`),
> §8.3 (`ovos.entity.deregister`), §8.4 (`ovos.skill.deregister`), and
> §8.5 `ovos.intent.enable` are now green and no longer listed above.

### OVOS-INTENT-4: per-plugin registration compliance (`test_intent4_plugins_conformance.py`)

The per-plugin suite proves each matcher consumes the spec registration
topic (§5 keyword / §6 template) and stays back-compatible. A plugin's spec
test is xfail when its installed ref does not yet carry the INTENT-4
consumer.

| Plugin | Test | `reason` |
|--------|------|----------|
| adapt | `…_adapt.test_spec_registration_is_matchable` | `"adapt INTENT-4 adoption pending on @dev (kept @dev, load-bearing for the INTENT-3 suite)"`. adapt is pinned `@dev` because its `@dev` carries the #47 None-blacklist guard the INTENT-3 orchestrator suite needs. The §5 spec consumer lives only on its `feat/intent-4-adoption` branch. |
| padacioso | `…_padacioso.test_spec_registration_is_matchable` | `"padacioso INTENT-4 adoption pending on @dev (kept @dev, load-bearing PADACIOSO_HIGH driver)"`. padacioso is pinned `@dev` because it is the `PADACIOSO_HIGH` driver with the unhashable-Session lru_cache fix the orchestrator suites depend on. The §6 spec consumer lives only on its `feat/intent-4-adoption` branch. |

> Only the adapt and padacioso spec tests are xfail. Both are deliberately
> kept `@dev` because they are load-bearing for the orchestrator suites.
> Every other per-plugin case is green: the spec test for palavreado /
> nebulento / markov / linha-fina / padatious / m2v (INTENT-4 adoption
> merged to `@dev`), and the legacy back-compat test for all eight plugins.

## OVOS-INTENT-3

The identity triple (§3), the keyword constraint payload (§4.2), the template
definition (§5), and the matching-semantics end-to-end clauses (§4.2, §4.3,
§6.2, §7) are green against `ovos-spec-tools` and the live adapt/padacioso
pipelines. Three gaps remain, all in the definition/validation layer that
`ovos-spec-tools`'s `IntentBuilder`/`Intent` leaves unvalidated, plus one
engine-capability gap.

### §4.2: a keyword intent MUST declare a required/one-of constraint

- **Spec mandates:** "A keyword intent MUST declare at least one required or
  one-of constraint: an intent with only optional and excluded constraints …
  is malformed."

- **Current impl:** `ovos-spec-tools` `IntentBuilder`/`Intent` is a
  dependency-light data model with no validation and builds such a
  definition without error.

- **Test:** `TestSec4KeywordDefinition.test_only_optional_and_excluded_is_malformed`

- **`reason`:** `"INTENT-3 §4.2 MUST: 'A keyword intent MUST declare at least one required or one-of constraint: an intent with only optional and excluded constraints … is malformed'; ovos-spec-tools IntentBuilder/Intent is a dependency-light data model with no validation and builds such a definition without error"`

### §4.2: a vocabulary MUST appear under at most one role

- **Spec mandates:** "A vocabulary MUST appear under at most one role within
  a single intent … [listing it twice] is contradictory and malformed."

- **Current impl:** `ovos-spec-tools` `IntentBuilder`/`Intent` performs no
  cross-role validation and accepts a vocabulary listed under two roles.

- **Test:** `TestSec4KeywordDefinition.test_vocabulary_under_two_roles_is_malformed`

- **`reason`:** `"INTENT-3 §4.2 MUST: 'A vocabulary MUST appear under at most one role within a single intent … [listing it twice] is contradictory and malformed'; ovos-spec-tools IntentBuilder/Intent performs no cross-role validation and accepts a vocabulary under two roles"`

### §5.1: template intent generalization is engine-specific

- **Spec view:** "a capable engine generalizes beyond [the templates] and
  recognizes unseen phrasings" — framed as expected/SHOULD, not a MUST
  (§1.1 leaves matching unconstrained).

- **Current impl:** the padacioso driver this suite uses is a literal
  matcher and does not generalize to an unseen phrasing; a neural engine
  (padatious) would pass this.

- **Test:** `TestE2ETemplateGeneralizes.test_unseen_phrasing_still_matches`

- **`reason`:** `"INTENT-3 §5.1: 'a capable engine generalizes beyond [the templates] and recognizes unseen phrasings'. Generalization is an engine capability the spec frames as expected/SHOULD, not a MUST (§1.1 leaves matching unconstrained); the padacioso driver this harness uses is a literal matcher and does not generalize to 'could you play something relaxing'. A neural engine (padatious) would pass this."`

## OVOS-CONTEXT-1

The carrier clauses (§2 entry/`session.intent_context` field, §3 key
shapes, §4.1 forward/reply propagation, §8 read-only carry-through) are
green. They ride on `ovos-bus-client`'s spec session.

The engine gating clauses (§6 `requires_context`, §6.1 `excludes_context`)
are now green too, against the merged per-engine gating (padacioso `@dev`
+ `ovos-spec-tools` `gate_satisfied`).

`TestSec6RequiresContext` and `TestSec61ExcludesContext` register an
intent carrying the gate declaration inline and assert both directions:
suppression when the gate is unsatisfied and a match when it is satisfied.
A pass cannot come from an engine that never consults the gate.

The remaining gaps are orchestrator-side. ovos-core still uses the legacy
frame-based `IntentContextManager`, and the flat decaying
`session.intent_context` model is not yet consumed, awaiting the
CONTEXT-1 store PR:

| Clause | Spec mandates | Test |
|--------|---------------|------|
| §5.3 | `ovos.session.sync` merges `intent_context` entry-by-entry (set / null-delete) | `TestSec53SessionSyncMerge` |
| §4 | per-utterance decay: prune dead entries before match, decrement `turns_remaining` after | `TestSec4Decay` |
| §7 | a `requires_context` key naming an unfilled slot is promoted into `Match.slots` | `TestSec7ContextSuppliedSlot` |

## OVOS-FALLBACK-1

### §4: registration topic name

- **Spec mandates:** a fallback skill registers on `ovos.fallback.register`.

- **Current core:** consumes `ovos.skills.fallback.register`.

- **Test:** `TestSec4Registration.test_spec_register_topic_consumed`

- **`reason`:** `"ovos-core consumes 'ovos.skills.fallback.register'; FALLBACK-1 §4 defines 'ovos.fallback.register'"`

### §4: `session.fallback_handlers` field

- **Spec mandates:** `session.fallback_handlers` orders the pool when
  present.

- **Current bus-client:** does not yet carry the field. The clause is
  skip-guarded (probed at runtime) and runs once `ovos-bus-client`
  populates it.

- **Test:** `TestSec4Registration.test_fallback_handlers_session_field`

### §6.1: broadcast vs per-skill query

- **Spec view:** the query cycle is expressed per-skill
  (`<skill_id>.fallback.ping`).

- **Current core:** uses a single broadcast `ovos.skills.fallback.ping` /
  `ovos.skills.fallback.pong` query plus a per-skill `.response`. The
  suite's §6 query/response tests assert the broadcast topics core emits
  today and are therefore green. The per-skill-query shape is tracked in
  the suite's coverage map as the pending FALLBACK-1 §6.1 form, to be
  asserted when core moves to it.

## OVOS-CONVERSE-1

### §2.1: `session.converse_handlers` field

- **Spec mandates:** `session.converse_handlers` carries the active
  converse owner, head-first.

- **Current core:** models converse ownership with the legacy
  `session.active_skills` list. The spec field is not yet populated. The
  clause is skip-guarded (probed at runtime) and runs once
  `ovos-bus-client`'s `feat/session-spec-fields` is pinned in.

- **Test:** `TestSec21OwnerOrdering.test_converse_handlers_reflects_owner`

## OVOS-SESSION-1 / OVOS-SESSION-2 (spec session fields)

The session suite asserts the legacy carriers green and the spec field
names under a runtime probe, skipping cleanly until `ovos-bus-client`
populates them (`feat/session-spec-fields`). The pending spec fields:

| Spec field | Owning clause | Current legacy carrier | Test |
|------------|---------------|------------------------|------|
| `active_handlers` | PIPELINE-1 §7.1 | `session.active_skills` | `TestActiveHandlerRecency.test_active_handlers_spec_field` |
| `converse_handlers` | CONVERSE-1 §2.1 | `session.active_skills` | `TestConverseOwnerOrdering.test_converse_handlers_spec_field` |
| `response_mode` | CONVERSE-1 §2.2 | `session.utterance_states` (RESPONSE) | `TestResponseMode.test_response_mode_spec_field` |
| `fallback_handlers` | FALLBACK-1 §4 | (none) | `TestFallbackHandlersField.test_fallback_handlers_spec_field` |

These skip rather than xfail because the field's mere presence, not a
behavior change, is what is missing. Once the bus-client branch is pinned
in, they run and go green.

## OVOS-GUI-1

The GUI-1 suite asserts the spec wire shape against the installed
`GUIInterface` producer and the `ovos_gui.namespace.NamespaceManager`
service. The current implementation predates the closed-vocabulary and
per-session-routing model of GUI-1.

### §3.1 / §8.1: closed template vocabulary

- **Spec mandates:** a producer names only the `SYSTEM_*` templates of the
  closed §3.4 catalogue (`SYSTEM_text`, `SYSTEM_image`, `SYSTEM_face`, and
  others).

- **Current impl:** `GUIInterface` emits legacy CamelCase frame names
  (`SYSTEM_TextFrame`, `SYSTEM_ImageFrame`, `SYSTEM_Face`, and others)
  outside the catalogue.

- **Tests:** `TestSec3ClosedVocabulary.test_show_{text,image,face}_names_closed_vocabulary_template`,
  `TestSec81ProducerConformance.test_all_template_names_in_closed_vocabulary`

- **`reason`:** `"GUI-1 §3.1 MUST name only closed-vocabulary templates; …emits the legacy 'SYSTEM_*Frame' …not the spec 'SYSTEM_*'"`

### §3.3: absent optional keys omitted, never null

- **Spec mandates:** a producer omits an absent optional key rather than
  emitting it as JSON `null`.

- **Current impl:** `GUIInterface` emits `'__idle': None` and sets unset
  optional content keys (`title`/`caption`/`fill`, and others) to `None`.

- **Test:** `TestSec33TypingRules.test_absent_optional_keys_are_omitted_not_null`

### §3.5: local image resolved to a `data:` URI

- **Spec mandates:** a producer resolves a local asset to a `data:` URI and
  MUST NOT place a bare filesystem path on the wire.

- **Current impl:** `GUIInterface.show_image` resolves a local file to its
  absolute filesystem path and emits that path verbatim on `image`.

- **Test:** `TestSec35ImageDelivery.test_local_image_resolved_to_data_uri`

### §3.2 / §4.2 / §8.3: service dispatches only `SYSTEM_*` templates

- **Spec mandates:** the GUI service recognises a template by the
  `SYSTEM_` prefix and MUST NOT dispatch a `gui.page.show` whose first page
  is not `SYSTEM_*`.

- **Current impl:** `NamespaceManager.handle_show_page` validates only that
  `page_names` is a list with `__from`, and loads any page name as a
  namespace.

- **Test:** `TestSec32ServiceTemplateGate.test_non_system_page_not_loaded_as_template`

### §4.3 / §5.1 / §8.3: independent namespace stack per `session_id`

- **Spec mandates:** the GUI service maintains an independent namespace
  stack per `session_id` and routes a GUI Message solely by its
  `session_id`.

- **Current impl:** `NamespaceManager` keeps a single flat
  `loaded_namespaces`/`active_namespaces` and never reads
  `context.session`. Two sessions collide on one global stack.

- **Test:** `TestSec43Sec5PerSessionRouting.test_independent_stack_per_session`

## OVOS-BRIDGE-1

The bus-observable composition primitives the bridge relies on (MSG-1
`.reply()` source/destination swap, `site_id` survival through
derivations, session preservation across the orchestrator round) are
already conformant in the stack. One gap remains:

### §3.3: absent `site_id` MUST NOT infer a default

- **Spec mandates:** when neither client nor bridge supplies a `site_id`
  the field is absent. Consumers treat absence as an unknown group and
  MUST NOT infer a default.

- **Current impl:** `ovos-bus-client` `Session` defaults `site_id` to the
  sentinel string `'unknown'` instead of leaving the field absent.

- **Test:** `TestSec33SiteId.test_absent_site_id_yields_no_default`

- **`reason`:** `"BRIDGE-1 §3.3 MUST NOT infer a default: an unsupplied site_id is absent; ovos-bus-client Session defaults site_id to the sentinel string 'unknown' instead of leaving the field absent"`

The bridge's own MUSTs that require a bridge component to exist (§3.1
source stamping, §3.4.2 managing-mode synthesis, §4.4 disconnect
deregister emission, §5 grace-period discard) are not executable here.

No bridge is installed (the reference implementation is HiveMind), and
they are recorded as `# not bus-observable (no bridge in stack)` skips
rather than gaps.

## OVOS-AUDIO-IN-1

### §5.1: STT input-language resolution order

- **Spec mandates:** select the STT input language as
  `session.detected_lang` > `session.request_lang` > `session.lang` (first
  present, non-empty wins), reflected on the emitted utterance's `data.lang`
  (`stt_lang` normally matches).

- **Current impl:** `OVOSDinkumVoiceService._stt_text` resolves the language
  from `stt_context.get("lang")` or the deployment config default, and never
  consults `session.detected_lang` / `session.request_lang` / `session.lang`.

- **Test:** `TestSec51LanguageResolution.test_language_resolution_precedence`

- **`reason`:** `"AUDIO-IN-1 §5.1 MUST resolve the STT input language as detected_lang > request_lang > lang from the session; OVOSDinkumVoiceService._stt_text resolves it from stt_context.get('lang') or the deployment config default and never consults session.detected_lang / session.request_lang / session.lang"`

## OVOS-OCP-1

### §5: per-session now-playing isolation

- **Spec mandates:** the Virtual Media Player is per session. An orchestrator
  serving multiple concurrent sessions MUST keep each session's now-playing,
  queue, and transport state isolated — a `pause` for session A MUST NOT
  affect session B.

- **Current impl:** the `ovos-media` `OCPMediaPlayer` holds a single global
  `NowPlaying` and one `PlayerState`, and does not read `context.session` to
  select a per-session player, so two concurrent sessions collide on one
  player. This is the design-probe counterpart of GUI-1's
  `TestSec43Sec5PerSessionRouting`: a single `OCPPlayerHarness` cannot host
  two concurrent player instances, so the test asserts the structural
  precondition isolation requires (state keyed by `session_id`).

- **Test:** `TestSec5SessionScoping.test_now_playing_is_scoped_per_session`

- **`reason`:** `"OVOS-OCP-1 §5 MUST keep each session's now-playing / queue / transport state isolated (a pause for session A MUST NOT affect session B); the ovos-media OCPMediaPlayer holds a single global NowPlaying and one PlayerState and does not read context.session to select a per-session player, so two concurrent sessions collide on one player"`

### §4.3: pause with no media MUST be a no-op

- **Spec mandates:** "issuing pause with nothing playing is a no-op, not an
  error."

- **Current impl:** the `ovos-media` `OCPMediaPlayer` transitions to PAUSED
  on a bare pause request with no now-playing media, instead of doing
  nothing.

- **Test:** `TestSec43ControlRequests.test_pause_is_noop_with_no_media`

- **`reason`:** `"OVOS-OCP-1 §4.3 MUST: 'issuing pause with nothing playing is a no-op, not an error'; the ovos-media player transitions to PAUSED on a bare pause request with no now-playing media."`

## OVOS-PERSONA-1

The summon / release / ask / list / check routes, the active-persona catch-all
(§7.2), `Match.lang` (§7.4), the handler speak contract (§8.1), and the
`ovos.persona.*` discovery / broadcast surface (§8.5, §8.7, §11) are green
against the pinned persona plugin. One behavior gap remains.

### §7.1: unsupported `persona_id` MUST decline

- **Spec mandates:** when `session.persona_id` is set to a value the plugin
  does not support, `match` returns `None` (let another stage handle it) — no
  `persona:*` dispatch fires.

- **Current impl:** the plugin still claims (`persona:query` / fallback)
  instead of declining.

- **Test:** `TestSec4NoPersonaMode.test_unsupported_persona_id_declines`

- **`reason`:** `"PERSONA-1 §7.1 MUST return None when session.persona_id is set to an UNSUPPORTED value; the plugin still claims (persona:query / fallback) instead of declining"`

## OVOS-COMMON-QUERY-1

The discovery poll (§6.1 ping / §6.2 pong), the no-winner path (§9 → fallback,
no spurious speak), and the skill-side spec response topic (§7.1
`<skill_id>.common_query.response`) are green. The answer phase (§7 onward) is
not reachable in the pinned stack: `ovos-common-query-pipeline-plugin` 1.1.13a1
iterates `session.blacklisted_skills` unconditionally, which defaults to `None`
under `ovos-bus-client>=2.4`, so every winning-contest path raises
`TypeError: 'NoneType' object is not iterable` before completing. Each clause
below therefore carries both its spec-vs-legacy divergence AND that crash.

| Clause | Spec mandates | Test | `reason` |
|--------|---------------|------|----------|
| §6.1 | broadcast the ping for each accepted utterance (gate → poll → collect) | `TestSec6Poll.test_ping_rebroadcast_per_utterance` | `"COMMON-QUERY-1 §6.1 MUST broadcast the ping for each accepted utterance (gate -> poll -> collect); the pinned plugin pings only once at load for discovery and never re-broadcasts during match, so no per-utterance ping is observable"` |
| §3 | dispatch the winning contest on `<pipeline_id>:common_query` | `TestSec3ReservedIntent.test_dispatch_topic_is_reserved_common_query` | `"COMMON-QUERY-1 §3 MUST dispatch the winning contest on '<pipeline_id>:common_query'; the pinned plugin would dispatch legacy 'question:action.<skill_id>', and in this stack the contest crashes (blacklisted_skills None) before any dispatch"` |
| §7.1 | request full answers via `<skill_id>:common_query` | `TestSec7AnswerCollection.test_full_answer_request_topic` | `"COMMON-QUERY-1 §7.1 MUST request full answers via '<skill_id>:common_query'; the pinned plugin uses legacy broadcast 'question:query', and the contest crashes (blacklisted_skills None) before requesting anyway"` |
| §9 | `Match.skill_id` = the plugin's own `pipeline_id` | `TestSec9And10WinningContest.test_match_skill_id_is_pipeline_id` | `"COMMON-QUERY-1 §9 MUST set Match.skill_id = the plugin's own pipeline_id; the pinned plugin sets skill_id = the answering skill, and the contest crashes (blacklisted_skills None) before any dispatch"` |
| §9 | `slots.answer` = the selected answer string | `TestSec9And10WinningContest.test_match_slots_answer` | `"COMMON-QUERY-1 §9 MUST carry slots.answer = the selected answer string; the pinned plugin carries the answer in match_data/callback_data, and the contest crashes (blacklisted_skills None) before any dispatch"` |

## OVOS-TRANSFORM-1

The chain semantics (§1 run-to-completion, §4 ascending-priority order), the
per-type IO contracts (§3.2 utterance, §3.3 metadata, §3.4 intent-capture
enrichment), error handling (§7), the `<type>_transformer_ids` stamp (§1.3),
and cancellation (§8.1) are green against the ovos-core transformer services.
The §5 per-session override fields are skip-guarded (bus-client field presence,
see the SESSION-fields note above). Two behavior gaps remain.

### §3.4 / §9: intent-transformer identity invariant MUST be enforced

- **Spec mandates:** if a transformer returns a `Match` whose `skill_id` or
  `intent_name` differs from its input, the orchestrator MUST treat it as a §7
  shape violation — discard the output and proceed with the prior `Match`
  unchanged.

- **Current impl:** `IntentTransformersService.transform` does not enforce the
  identity invariant — a transformer that overwrites `skill_id` is honoured.

- **Test:** `TestSec34Intent.test_skill_id_invariant_enforced`

- **`reason`:** `"OVOS-TRANSFORM-1 §3.4 / §9 MUST: if a transformer returns a Match whose skill_id or intent_name differs from its input, the orchestrator MUST treat it as a §7 shape violation, discard the output and proceed with the prior Match unchanged. IntentTransformersService.transform does not enforce the identity invariant — a transformer that overwrites skill_id is honoured."`

### §3.0: bidirectional `lang` threaded through every chain

- **Spec mandates:** the orchestrator threads a bidirectional `lang` parameter
  through the audio / utterance / dialog / TTS chains (input AND output of each
  transform call).

- **Current impl:** the installed transformer templates take no `lang`
  parameter — `UtteranceTransformer.transform(utterances, context)`,
  `DialogTransformer.transform(dialog, context)`, and so on.

- **Test:** `TestSec30Lang.test_lang_is_a_threaded_parameter`

- **`reason`:** `"OVOS-TRANSFORM-1 §3.0 MUST: the orchestrator threads a bidirectional lang parameter through the audio/utterance/dialog/TTS chains (input AND output of each transform call). The installed transformer templates take no lang parameter."`

## Follow-up: MUST-clause enumeration (INTENT-1/2/3/4, SESSION-1/2)

A spot-enumeration of each spec's MUST / MUST NOT clauses against its
conformance suite. The high-priority **[C]** clauses from the original sweep
now carry real conformance tests (or a strict-xfail where the installed stack
diverges); see the disposition below. The clauses still listed as remaining
need a capability the local stack cannot drive deterministically — a
strict-xfail added blind could XPASS on the CI stack and fail the run for the
wrong reason — so they stay documented here for a further follow-up.
Prioritized: **[C]** = correctness/security critical, **[N]** = normal.

### OVOS-INTENT-4 — malformed-registration rejection (§3.2 / §5.3 / §6.2)

**Now covered** (`test_intent4_conformance.py`):

- **[C]** §5.3 / §6.2 / §3.2 — `TestSec53MalformedRejection`: a malformed
  registration (`ovos.intent.register.template` with no `samples`,
  `ovos.entity.register` with an empty value-set) draws no `.response`/`.error`
  (§2 fire-and-forget holds for malformed too), is not indexed, and does not
  crash or corrupt the orchestrator — a subsequent well-formed registration on
  the same skill still matches (the bus-observable proxy for "MUST NOT index +
  no crash").
- **[C]** §8 — `TestSec8DeregisterUnregistered`: deregistering a
  never-registered skill is a no-op (no ack/error, a later registration still
  matches).

**Remaining** (not bus-observable / not deterministic here):

- **[C]** §5.3 WARN-log companion: "MUST log the rejection at WARN with
  `skill_id`, the offending value, and the rule violated" (spec §294, §361,
  §398, §728). A logging obligation with no bus emission — not observable
  through the harness. Would need a log-capture fixture.
- **[C]** §5.2 finer descriptors: combined `required` and `one_of` MUST NOT
  both be empty (spec §278); every vocabulary descriptor MUST carry a
  non-empty `samples` array (§284, §286). The keyword-engine §5 spec topic is
  itself still an xfail against `PADACIOSO_HIGH` (a template driver), so the
  per-descriptor keyword-rejection path is not deterministically drivable in
  this combo; the template `samples`-missing case is the one exercised above.
  The per-role overlap rule (§281) is covered as an xfail in the INTENT-3 suite.
- §2 / §11: `intent_name` MUST NOT be one reserved by another spec (§276) — the
  `stop` case **is** covered (STOP-1 §2 xfail); other reserved names
  (`common_query`, `converse`) are not enumerated.

### OVOS-SESSION-1 — wire-shape MUSTs (§2.1 / §3.1 / §5 / §6)

**Now covered** (`test_session_conformance.py`):

- **[C]** §2.1 — `TestSec21OmissionAndNull`: an omitted field resolves to the
  deployment default, and an explicit `null` is treated as omitted (not a
  deferral sentinel) — the consumer substitutes the default and does not reject
  (spec §64, §71). Green against the installed bus-client.
- **[C]** §3.1 keying (spec §227) — `TestSec31PerSessionKeying`: per-session
  state is keyed on `session_id`; an active handler in session A is not visible
  to session B. This is the generic form of the MUST the GUI-1 §5 and OCP-1 §5
  xfails track for those two consumers.
- **[C]** §3.1 identity — `TestSec31SessionIdentity`: an empty/absent session
  MUST resolve to `session_id: "default"` (spec §95, §99). **strict-xfail** —
  the installed `ovos-bus-client` mints a random uuid instead; flips loudly
  when bus-client fills the reserved value.

**Remaining** (need a capability not present / not deterministic here):

- **[C]** §6: within `session`, "numbers MUST be finite (no NaN, no
  infinities)" and "a consumer that cannot parse `session` as a JSON object
  MUST treat it as malformed" (spec §574, §578). MSG-1 covers this for the
  envelope; the session-object-specific path is not separately asserted (JSON
  cannot carry NaN on the wire, so driving it needs a crafted non-JSON payload).
- **[C]** §4.1 default materialization on derivation: a materialized default
  MUST set `session_id: "default"` and MUST NOT populate no-behaviour fields
  (spec §553). Needs an orchestrator derivation from a no-`session` source; not
  cleanly drivable in this combo.
- **[N]** §5: `secondary_langs` MUST NOT contain `lang` and MUST NOT contain
  duplicates (spec §301); `request_lang` MUST NOT be treated as a guarantee
  (§400). Language-signal invariants — unasserted.
- **[N]** §7 (derivation): "a consumer that derives a Message MUST NOT strip
  session fields it does not understand" (spec §536). BRIDGE-1 asserts session
  **preservation** through the orchestrator round; the unknown-field-preservation
  MUST on an arbitrary consumer derivation is not separately asserted.

### OVOS-SESSION-2 — ownership / statelessness MUSTs

**Now covered** (`test_session_conformance.py`):

- **[C]** §2.1 (spec §543) — `TestSec21BusStateless`: the message bus is
  stateless with respect to session — a Message carrying a session is delivered
  to a bus observer byte-identical; the bus does not interpret, mutate, or
  persist it.

**Remaining**:

- **[C]** §5.1 (spec §347, §355): "the orchestrator MUST merge
  `Message.data.session` from an in-progress round and reflect the merged
  state." Overlaps CONTEXT-1 §5.3 sync (tracked there as a strict-xfail). Not
  separately asserted for SESSION-2, and a blind strict-xfail risks XPASS on
  the CI stack, so it stays documented pending a deterministic driver.
- **[N]** a client MUST make every round self-sufficient via the session
  (spec §625); a component MUST NOT rely on async bus events for session state
  (§596). Client-contract MUSTs — no client in the stack, not bus-observable;
  listed for completeness.

### OVOS-INTENT-1 / INTENT-2 / INTENT-3

INTENT-1 (grammar) and INTENT-2 (locale formats) are asserted against
`ovos_spec_tools` clause-by-clause and are thoroughly covered (see their
coverage maps — every §2–§5 MUST/MUST NOT has a green or xfail row). INTENT-3
covers the identity triple, the four constraint roles, and the match MUSTs;
its two validation MUSTs (§4.2 declare-a-constraint, §4.2 role-overlap) are
already xfail. No additional uncovered MUSTs were found in these three beyond
the INTENT-4 registration-validation overlap noted above (INTENT-3 §5.3
required-slot rules are noted engine-specific in that suite).

## Legacy/spec topic pairs with no component cell

Every pair in `ovos_spec_tools.messages.MIGRATION_MAP` is exercised at the bus
level by `test/migration/`: whichever name a peer emits on, a subscriber on the
other name receives the event exactly once. What the pairs below still lack is
a cell that drives the pair against the service that owns the *effect*, so that
"the legacy topic still works" means the audio actually played rather than the
message merely arrived. Each is a skipped cell naming the service, so it is
counted in every run rather than silently absent, and the meta-test refuses to
let a pair sit here without a row.

| Legacy topic | Spec topic | A component cell needs |
|--------------|-----------|------------------------|
| `detach_intent` | `ovos.intent.deregister` | ovos-core's intent service to deregister a live intent |
| `detach_skill` | `ovos.skill.deregister` | ovos-core's intent service to deregister a live skill |
| `mycroft.audio.play_sound` | `ovos.audio.play_sound` | ovos-audio (PlaybackService) to play a sound file |
| `mycroft.audio.queue` | `ovos.audio.queue` | ovos-audio (PlaybackService) to queue a uri |
| `mycroft.audio.speak.status` | `ovos.audio.is_speaking` | ovos-audio (PlaybackService) to answer the speaking query |
| `mycroft.audio.speech.stop` | `ovos.audio.stop` | ovos-audio (PlaybackService) to abort playback |
| `mycroft.awoken` | `ovos.listener.awoken` | ovos-dinkum-listener to leave sleep mode |
| `mycroft.mic.listen` | `ovos.mic.listen` | ovos-audio (PlaybackService) to answer a listen request |
| `mycroft.skill.disable_intent` | `ovos.intent.disable` | ovos-core's intent service to disable a live intent |
| `mycroft.skill.enable_intent` | `ovos.intent.enable` | ovos-core's intent service to re-enable a disabled intent |
| `recognizer_loop:record_begin` | `ovos.listener.record.started` | ovos-dinkum-listener to open a recording |
| `recognizer_loop:record_end` | `ovos.listener.record.ended` | ovos-dinkum-listener to close a recording |
| `recognizer_loop:sleep` | `ovos.listener.sleep` | ovos-dinkum-listener to enter sleep mode |
| `skill.stop.pong` | `ovos.stop.pong` | a skill container (ovos-workshop) to answer the stop ping |
| `speak:b64_audio` | `ovos.utterance.speak.b64` | ovos-audio (PlaybackService) to render base64 speech |
| `speak:b64_audio.response` | `ovos.audio.speech` | ovos-audio (PlaybackService) to answer a base64 speak request |

### Fallback and converse topic divergences

`ovos.fallback.register` versus `ovos.skills.fallback.register`, the per-skill
`<skill_id>.fallback.ping` versus the broadcast query, and the converse
ownership field are divergences between a specification and what core does,
not renames the bus bridges: none of them is in `MIGRATION_MAP`, and which
name wins is an owner decision rather than a harness one. They are covered as
conformance gaps in the FALLBACK-1 and CONVERSE-1 sections above and are
deliberately out of scope for the migration-pair suite, which would otherwise
assert a bridge nobody has agreed to build.

## How a gap closes

1. Pin the implementation branch(es) that close the gap in
   `requirements.txt` ([testing-combos.md](testing-combos.md)).

2. Open a PR. CI runs the suite. The closed clauses report xpassed (or,
   for skip-guarded field clauses, passed).

3. After the impl branch merges and the ref is flipped to `@dev`, remove
   the `xfail` marker so the clause becomes a plain green conformance
   requirement.

## See also

- [coverage.md](coverage.md): every clause and its status.
- [writing-conformance-tests.md](writing-conformance-tests.md#the-xfail-discipline):
  the discipline these markers follow.

---
[← CI](ci.md) · [Home](../README.md)
