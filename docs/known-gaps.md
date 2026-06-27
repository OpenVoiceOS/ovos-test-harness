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

### §3.1 / §5.2 — global-stop self-dispatch topic
- **Spec mandates:** global stop is dispatched on `<stop_plugin_id>:global_stop`.
- **Current core:** self-dispatches the legacy `stop:global`.
- **Test:** `TestSec5GlobalStop.test_global_stop_dispatch_topic`
- **`reason`:** *"ovos-core self-dispatches the legacy 'stop:global'; STOP-1
  §3.1/§5.2 use '<stop_plugin_id>:global_stop'"*

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
`ovos.intent.*` / `ovos.entity.*`. ovos-core does not yet expose it: registration
is the in-process, plugin-specific `padatious:register_intent` / `register_vocab`,
and introspection is the legacy `intent.service.intent.get`. All of the following
flip green once the bus contract lands (e.g. via the `ovos-workshop`
INTENT-4-producer + an ovos-core consumer — see
[testing-combos.md](testing-combos.md)).

| Clause | Spec mandates | Current core (the `reason`) | Test |
|--------|---------------|------------------------------|------|
| §5 | `ovos.intent.register.keyword` makes an intent matchable | consumes keyword registration via the legacy `padatious:register_intent`/`register_intent` | `TestSec5KeywordRegistration` |
| §6 | `ovos.intent.register.template` makes an intent matchable | consumes registrations via the legacy `padatious:register_intent` | `TestSec6TemplateRegistration` |
| §7 | `ovos.entity.register` value-set hint accepted | consumes entity registration via the legacy `padatious:register_entity`/`register_vocab` | `TestSec7EntityRegistration` |
| §8.2 | `ovos.intent.deregister` removes one intent | does not consume `ovos.intent.deregister` | `TestSec82Deregister` |
| §8.3 | `ovos.entity.deregister` removes one entity | does not consume `ovos.entity.deregister` | `TestSec83EntityDeregister` |
| §8.4 | `ovos.skill.deregister` removes a whole skill | removes a skill's registrations via the legacy `detach_skill` | `TestSec84SkillDeregister` |
| §8.5 | `ovos.intent.disable` suppresses an intent | does not consume `ovos.intent.disable` | `TestSec85Disable` |
| §8.5 | `ovos.intent.enable` re-arms a disabled intent | does not consume `ovos.intent.disable`/`ovos.intent.enable` | `TestSec85Enable` |
| §10.1 | `ovos.intent.list` introspection responds | serves the legacy `intent.service.intent.get` | `TestSec10Introspection.test_intent_list_responds` |
| §10.2 | `ovos.intent.describe` introspection responds | does not serve `ovos.intent.describe` | `TestSec10Introspection.test_intent_describe_responds` |

> §2 (registrations are fire-and-forget — no ack/`.response`) is **green**: the
> current core already satisfies it.

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
