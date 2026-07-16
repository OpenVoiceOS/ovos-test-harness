# Known conformance gaps

This page catalogues the clauses where the
[`OpenVoiceOS/architecture`](https://github.com/OpenVoiceOS/architecture) specs
mandate one behavior but the current ovos-core stack still does the legacy thing.
Each is recorded in the suite as `@pytest.mark.xfail(strict=False, reason=...)`,
asserting the **spec** behavior, with a `reason` that cites the legacy topic and
the spec clause. Because the markers are `strict=False`, a gap **xpasses** (and so
flags itself for marker removal) the moment the implementation catches up — see
[ci.md](ci.md#interpreting-results).

The framing for every gap is the same: **the spec mandates X; current core emits /
consumes the legacy Y. The test asserts X, is marked `xfail`, and will flip to a
pass when X is implemented.** The harness never records Y as conformant.

These reasons are the canonical record of the gap; they are kept verbatim from the
test decorators so this page stays accurate.

## OVOS-STOP-1

> §3.1/§5.2 (global stop dispatched on `<stop_plugin_id>:global_stop`) is now
> **green** against the STOP-1 conformance branch and no longer listed here;
> `TestSec5GlobalStop.test_global_stop_dispatch_topic` is plain conformance.
> The per-skill stop clauses (§4.2/§4.3 — pong collection, `<skill_id>:stop`
> dispatch, active-vs-global selection) are green.

### §2 — reserved intent name `stop`
- **Spec mandates:** a registration naming the reserved `stop` is malformed and
  MUST NOT be indexed, so it never becomes matchable (STOP-1 §2, with INTENT-4
  §5.3 / PIPELINE-1 §7.3).
- **Current core:** does not reject such a registration.
- **Test:** `TestSec2ReservedName.test_reserved_stop_registration_not_dispatched`
- **`reason`:** *"ovos-core does not reject registrations naming the reserved
  'stop'; STOP-1 §2 / INTENT-4 §5.3 MUST"*

## OVOS-INTENT-4

INTENT-4 defines a fixed registration/introspection bus contract under
`ovos.intent.*` / `ovos.entity.*`. Against the `ovos-workshop`
INTENT-4-producer branch + the ovos-core INTENT-4 §10 manifest consumer + the
padacioso §6 template consumer (@dev), most of it is now **green**: §6 template
registration, §8.5 `ovos.intent.disable`, and §10.1/§10.2 introspection
(`ovos.intent.list` / `ovos.intent.describe`) all pass and are no longer listed.
Only the §5 keyword-registration spec topic remains a gap — the driver in the
suite is `PADACIOSO_HIGH` (a template engine), so keyword registration via the
spec topic is not matchable through it, and core still consumes keyword
registration via the legacy path.

| Clause | Spec mandates | Current core (the `reason`) | Test |
|--------|---------------|------------------------------|------|
| §5 | `ovos.intent.register.keyword` makes an intent matchable | consumes keyword registration via the legacy `padatious:register_intent`/`register_intent` | `TestSec5KeywordRegistration` |

> §2 (registrations are fire-and-forget — no ack/`.response`) is **green**: the
> current core already satisfies it. The deregistration / re-arm consumer has
> landed, so §7 (`ovos.entity.register`), §8.2 (`ovos.intent.deregister`),
> §8.3 (`ovos.entity.deregister`), §8.4 (`ovos.skill.deregister`) and §8.5
> `ovos.intent.enable` are now **green** and no longer listed above.

### OVOS-INTENT-4 — per-plugin registration compliance (`test_intent4_plugins_conformance.py`)

The per-plugin suite proves each matcher consumes the spec registration topic
(§5 keyword / §6 template) and stays back-compatible. A plugin's spec test is
xfail when its installed ref does not yet carry the INTENT-4 consumer.

| Plugin | Test | `reason` |
|--------|------|----------|
| adapt | `…_adapt.test_spec_registration_is_matchable` | *"adapt INTENT-4 adoption pending on @dev (kept @dev — load-bearing for the INTENT-3 suite)"* — adapt is pinned `@dev` because its `@dev` carries the #47 None-blacklist guard the INTENT-3 orchestrator suite needs; the §5 spec consumer lives only on its `feat/intent-4-adoption` branch. |
| padacioso | `…_padacioso.test_spec_registration_is_matchable` | *"padacioso INTENT-4 adoption pending on @dev (kept @dev — load-bearing PADACIOSO_HIGH driver)"* — padacioso is pinned `@dev` because it is the `PADACIOSO_HIGH` driver with the unhashable-Session lru_cache fix the orchestrator suites depend on; the §6 spec consumer lives only on its `feat/intent-4-adoption` branch. |

> Only the adapt and padacioso **spec** tests are xfail (both deliberately kept
> `@dev` because they are load-bearing for the orchestrator suites). Every other
> per-plugin case is **green**: the spec test for palavreado / nebulento / markov
> / linha-fina / padatious / m2v (INTENT-4 adoption merged to `@dev`), and the
> legacy back-compat test for all eight plugins.

## OVOS-CONTEXT-1

The **carrier** clauses (§2 entry/`session.intent_context` field, §3 key shapes,
§4.1 forward/reply propagation, §8 read-only carry-through) are **green** — they
ride on `ovos-bus-client`'s spec session.

The **engine gating** clauses (§6 `requires_context`, §6.1 `excludes_context`)
are now **green** too: against the merged per-engine gating (padacioso `@dev` +
`ovos-spec-tools` `gate_satisfied`), `TestSec6RequiresContext` and
`TestSec61ExcludesContext` register an intent carrying the gate declaration
inline and assert **both** directions — suppression when the gate is unsatisfied
and a match when it is satisfied — so a pass cannot come from an engine that
never consults the gate.

The remaining gaps are **orchestrator-side** (ovos-core still uses the legacy
frame-based `IntentContextManager`; the flat decaying `session.intent_context`
model is not yet consumed — awaiting the CONTEXT-1 store PR):

| Clause | Spec mandates | Test |
|--------|---------------|------|
| §5.3 | `ovos.session.sync` merges `intent_context` entry-by-entry (set / null-delete) | `TestSec53SessionSyncMerge` |
| §4 | per-utterance decay: prune dead entries before match, decrement `turns_remaining` after | `TestSec4Decay` |
| §7 | a `requires_context` key naming an unfilled slot is promoted into `Match.slots` | `TestSec7ContextSuppliedSlot` |

## OVOS-FALLBACK-1

### §4 — registration topic name
- **Spec mandates:** a fallback skill registers on `ovos.fallback.register`.
- **Current core:** consumes `ovos.skills.fallback.register`.
- **Test:** `TestSec4Registration.test_spec_register_topic_consumed`
- **`reason`:** *"ovos-core consumes 'ovos.skills.fallback.register'; FALLBACK-1
  §4 defines 'ovos.fallback.register'"*

### §4 — `session.fallback_handlers` field
- **Spec mandates:** `session.fallback_handlers` orders the pool when present.
- **Current bus-client:** does not yet carry the field; the clause is **skip-guarded**
  (probed at runtime) and runs once `ovos-bus-client` populates it.
- **Test:** `TestSec4Registration.test_fallback_handlers_session_field`

### §6.1 — broadcast vs per-skill query
- **Spec view:** the query cycle is expressed per-skill (`<skill_id>.fallback.ping`).
- **Current core:** uses a single broadcast `ovos.skills.fallback.ping` /
  `ovos.skills.fallback.pong` query plus a per-skill `.response`. The suite's
  §6 query/response tests assert the **broadcast** topics core emits today and are
  therefore green; the per-skill-query shape is tracked in the suite's coverage map
  as the pending FALLBACK-1 §6.1 form, to be asserted when core moves to it.

## OVOS-CONVERSE-1

### §2.1 — `session.converse_handlers` field
- **Spec mandates:** `session.converse_handlers` carries the active converse owner,
  head-first.
- **Current core:** models converse ownership with the legacy `session.active_skills`
  list; the spec field is not yet populated. The clause is **skip-guarded** (probed
  at runtime) and runs once `ovos-bus-client`'s `feat/session-spec-fields` is pinned
  in.
- **Test:** `TestSec21OwnerOrdering.test_converse_handlers_reflects_owner`

## OVOS-SESSION-1 / OVOS-SESSION-2 (spec session fields)

The session suite asserts the legacy carriers green and the spec field *names*
under a runtime probe, skipping cleanly until `ovos-bus-client` populates them
(`feat/session-spec-fields`). The pending spec fields:

| Spec field | Owning clause | Current legacy carrier | Test |
|------------|---------------|------------------------|------|
| `active_handlers` | PIPELINE-1 §7.1 | `session.active_skills` | `TestActiveHandlerRecency.test_active_handlers_spec_field` |
| `converse_handlers` | CONVERSE-1 §2.1 | `session.active_skills` | `TestConverseOwnerOrdering.test_converse_handlers_spec_field` |
| `response_mode` | CONVERSE-1 §2.2 | `session.utterance_states` (RESPONSE) | `TestResponseMode.test_response_mode_spec_field` |
| `fallback_handlers` | FALLBACK-1 §4 | (none) | `TestFallbackHandlersField.test_fallback_handlers_spec_field` |

These skip rather than `xfail` because the field's mere presence — not a behavior
change — is what is missing; once the bus-client branch is pinned in, they run and
go green.

## OVOS-GUI-1

The GUI-1 suite asserts the spec wire shape against the installed `GUIInterface`
producer and the `ovos_gui.namespace.NamespaceManager` service. The current impl
predates the closed-vocabulary and per-session-routing model of GUI-1:

### §3.1 / §8.1 — closed template vocabulary
- **Spec mandates:** a producer names only the `SYSTEM_*` templates of the closed
  §3.4 catalogue (`SYSTEM_text`, `SYSTEM_image`, `SYSTEM_face`, …).
- **Current impl:** `GUIInterface` emits legacy CamelCase frame names
  (`SYSTEM_TextFrame`, `SYSTEM_ImageFrame`, `SYSTEM_Face`, …) outside the catalogue.
- **Tests:** `TestSec3ClosedVocabulary.test_show_{text,image,face}_names_closed_vocabulary_template`,
  `TestSec81ProducerConformance.test_all_template_names_in_closed_vocabulary`
- **`reason`:** *"GUI-1 §3.1 MUST name only closed-vocabulary templates; …emits
  the legacy 'SYSTEM_*Frame' …not the spec 'SYSTEM_*'"*

### §3.3 — absent optional keys omitted, never null
- **Spec mandates:** a producer omits an absent optional key rather than emitting it
  as JSON `null`.
- **Current impl:** `GUIInterface` emits `'__idle': None` and sets unset optional
  content keys (`title`/`caption`/`fill`…) to `None`.
- **Test:** `TestSec33TypingRules.test_absent_optional_keys_are_omitted_not_null`

### §3.5 — local image resolved to a `data:` URI
- **Spec mandates:** a producer resolves a local asset to a `data:` URI and MUST NOT
  place a bare filesystem path on the wire.
- **Current impl:** `GUIInterface.show_image` resolves a local file to its absolute
  filesystem path and emits that path verbatim on `image`.
- **Test:** `TestSec35ImageDelivery.test_local_image_resolved_to_data_uri`

### §3.2 / §4.2 / §8.3 — service dispatches only `SYSTEM_*` templates
- **Spec mandates:** the GUI service recognises a template by the `SYSTEM_` prefix
  and MUST NOT dispatch a `gui.page.show` whose first page is not `SYSTEM_*`.
- **Current impl:** `NamespaceManager.handle_show_page` validates only that
  `page_names` is a list with `__from`, and loads any page name as a namespace.
- **Test:** `TestSec32ServiceTemplateGate.test_non_system_page_not_loaded_as_template`

### §4.3 / §5.1 / §8.3 — independent namespace stack per `session_id`
- **Spec mandates:** the GUI service maintains an independent namespace stack per
  `session_id` and routes a GUI Message solely by its `session_id`.
- **Current impl:** `NamespaceManager` keeps a single flat
  `loaded_namespaces`/`active_namespaces` and never reads `context.session` — two
  sessions collide on one global stack.
- **Test:** `TestSec43Sec5PerSessionRouting.test_independent_stack_per_session`

## OVOS-BRIDGE-1

The bus-observable composition primitives the bridge relies on (MSG-1 `.reply()`
source/destination swap, `site_id` survival through derivations, session
preservation across the orchestrator round) are already conformant in the stack.
One gap:

### §3.3 — absent `site_id` MUST NOT infer a default
- **Spec mandates:** when neither client nor bridge supplies a `site_id` the field
  is absent; consumers treat absence as an unknown group and MUST NOT infer a
  default.
- **Current impl:** `ovos-bus-client` `Session` defaults `site_id` to the sentinel
  string `'unknown'` instead of leaving the field absent.
- **Test:** `TestSec33SiteId.test_absent_site_id_yields_no_default`
- **`reason`:** *"BRIDGE-1 §3.3 MUST NOT infer a default: an unsupplied site_id is
  absent; ovos-bus-client Session defaults site_id to the sentinel string
  'unknown' instead of leaving the field absent"*

The bridge's own MUSTs that require a bridge component to exist (§3.1 source
stamping, §3.4.2 managing-mode synthesis, §4.4 disconnect deregister emission, §5
grace-period discard) are not executable here — no bridge is installed (the
reference implementation is HiveMind) — and are recorded as `# not bus-observable
(no bridge in stack)` skips rather than gaps.

## How a gap closes

1. Pin the implementation branch(es) that close the gap in `requirements.txt`
   ([testing-combos.md](testing-combos.md)).
2. Open a PR; CI runs the suite. The closed clauses report **xpassed** (or, for
   skip-guarded field clauses, **passed**).
3. After the impl branch merges and the ref is flipped to `@dev`, remove the
   `xfail` marker so the clause becomes a plain green conformance requirement.

## See also

- [coverage.md](coverage.md) — every clause and its status.
- [writing-conformance-tests.md](writing-conformance-tests.md#the-xfail-discipline) —
  the discipline these markers follow.
</content>
