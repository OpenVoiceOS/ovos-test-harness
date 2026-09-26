# Spec adoption matrix

`docs/coverage.md` proves the harness holds a suite for every spec and knows
which clauses each suite asserts. It says nothing about which OVOS repos
actually put a spec's wire surface on the bus. This page answers that
question, one table per spec: which repos emit or consume the spec's
canonical topics, whether that adoption is the spec-native form or a
transitional bridge over a legacy topic, and a commit-pinned link to the line
that proves it.

Facts here come from grepping each repo's checkout at `origin/dev` (or the
repo's actual default branch, noted per row) for the spec's canonical topic
strings — never from memory, prose in `docs/coverage.md`, or the spec
document's own examples. A "not adopted" note means the grep found no
producer or consumer of that spec's topics anywhere in the swept workspace;
it is a finding, not a placeholder to be filled in later. The table for a
spec is a representative sample of the repos that implement its core verbs,
not an exhaustive census of every file that mentions a topic in passing (a
docstring, a comment, a changelog entry).

Two specs (OVOS-INTENT-1, OVOS-INTENT-3) define no wire topic at all by
design — grepping for a topic string is the wrong test for them, and their
sections say so explicitly and point at the semantic adoption path instead
(the definition model and the one-owner registration binding).

The `test_adoption_matrix_sync.py` meta-test keeps this page honest going
forward: every spec section here must exist for every spec section in
`docs/coverage.md`, every evidence link must be a commit-pinned GitHub blob
URL (never a branch URL, which drifts under the reader) whose referenced
line actually contains the topic string the row claims, and every repo named
here must resolve to a local checkout or a small allow-list.

## OVOS-PIPELINE-1

Canonical topics: `ovos.utterance.handle`, `ovos.utterance.handled`,
`ovos.utterance.cancelled`, `ovos.intent.matched`, `ovos.intent.unmatched`.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-core | emits `ovos.utterance.handled` at pipeline completion (`_emit_utterance_handled`, §9.5) | adopted | [ovos_core/intent_services/service.py#L408](https://github.com/OpenVoiceOS/ovos-core/blob/996b4483772491c0c7d19ae0c0496115446ee2ea/ovos_core/intent_services/service.py#L408) |
| ovos-audio | consumes `ovos.utterance.handled` to restore playback volume | adopted | [ovos_audio/audio.py#L190](https://github.com/OpenVoiceOS/ovos-audio/blob/8730b0770add2ea75e30badab433499a1219e227/ovos_audio/audio.py#L190) |
| ovos-gui | forwards `ovos.utterance.handled`/`ovos.utterance.cancelled` to the GUI client as spec topics | adopted | [ovos_gui/namespace.py#L466](https://github.com/OpenVoiceOS/ovos-gui/blob/4cf9823efb1280a13a8a9270eaf757f967b7fe18/ovos_gui/namespace.py#L466) |
| pyhtmx-gui-client | consumes `ovos.utterance.handled`/`.cancelled` as typed constants | adopted | [src/pyhtmx_gui/types.py#L40](https://github.com/OpenVoiceOS/pyhtmx-gui-client/blob/d7c23d8dfacf65c961504e2ae15908a5f1c04513/src/pyhtmx_gui/types.py#L40) (default branch `main`) |
| ovoscope | uses `ovos.utterance.handled` as the default end-of-flow topic in its test harness | adopted | [ovoscope/__init__.py#L33](https://github.com/OpenVoiceOS/ovoscope/blob/3243d18bdc6017be08064ff46de36d7838eaa18c/ovoscope/__init__.py#L33) |

## OVOS-STOP-1

Canonical topics: `ovos.stop`, `ovos.stop.ping`, `ovos.stop.pong`.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-audio | consumes `ovos.stop` directly; also bridges the legacy `mycroft.stop` alias at the bus-client boundary | transitional (legacy `mycroft.stop` still mirrored) | [ovos_audio/audio.py#L174](https://github.com/OpenVoiceOS/ovos-audio/blob/8730b0770add2ea75e30badab433499a1219e227/ovos_audio/audio.py#L174) |
| ovos-pydantic-models | models `ovos.stop` as the canonical stop message type | adopted | [ovos_pydantic_models/audio/audioservice.py#L443](https://github.com/OpenVoiceOS/ovos-pydantic-models/blob/bda5f4df746528a5c2e0708c0aaf2007769908be/ovos_pydantic_models/audio/audioservice.py#L443) |

## OVOS-INTENT-4

Canonical topics: `ovos.intent.register.keyword`, `ovos.intent.register.template`,
`ovos.intent.deregister`, `ovos.entity.register`/`.deregister`,
`ovos.intent.disable`/`.enable`, `ovos.intent.list`, `ovos.intent.describe`.

Per-plugin adoption for the keyword/template registration surface already
has its own detail table in `docs/coverage.md`'s OVOS-INTENT-4 (per-plugin)
section; this table only adds the framework-level rows that table omits.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-core | emits `ovos.intent.register.keyword`/`.template` as the registration bus contract | adopted | [ovos_core/intent_services/manifest.py#L36](https://github.com/OpenVoiceOS/ovos-core/blob/996b4483772491c0c7d19ae0c0496115446ee2ea/ovos_core/intent_services/manifest.py#L36) |
| ovos-workshop | skill base classes still register via the legacy `padatious:register_intent`/`register_entity` calls pending direct pipeline adoption | transitional (legacy `padatious:register_intent`) | [ovos_workshop/intents.py#L377](https://github.com/OpenVoiceOS/ovos-workshop/blob/c933068bce3809c253191f978556e3431af68120/ovos_workshop/intents.py#L377) |
| ovos-markov-pipeline-plugin | consumes `ovos.intent.register.template`, `.deregister`, `.disable` | adopted | [ovos_markov_pipeline/__init__.py#L606](https://github.com/OpenVoiceOS/ovos-markov-pipeline-plugin/blob/42601b1f1a1c7c3c0f3af44ba890363aba84c1a3/ovos_markov_pipeline/__init__.py#L606) |
| padacioso | consumes the template registration topic via the `SpecMessage.INTENT_REGISTER_TEMPLATE` enum value (`ovos.intent.register.template`, §6), alongside the legacy in-process registration path | transitional (legacy in-process `register_intent`) | [padacioso/opm.py#L84](https://github.com/OpenVoiceOS/padacioso/blob/f03d12a4b3bf422ea7d9ce6a5886ce12008605a5/padacioso/opm.py#L84) |
| ovos-control-panel | queries `ovos.intent.list` for its intent-inspection admin view | adopted (consumer) | [ovos_webui/intents.py#L58](https://github.com/OpenVoiceOS/ovos-control-panel/blob/5acd9ed153239c3e6439d06e0ea57ed866fac310/ovos_webui/intents.py#L58) |

## OVOS-CONVERSE-1

Canonical topics: `ovos.converse.ping`, `ovos.converse.pong`,
`ovos.converse.active.list`.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-workshop | skill base class answers `ovos.converse.ping` with `ovos.converse.pong` | adopted | [ovos_workshop/skills/converse.py#L60](https://github.com/OpenVoiceOS/ovos-workshop/blob/c933068bce3809c253191f978556e3431af68120/ovos_workshop/skills/converse.py#L60) |

## OVOS-FALLBACK-1

Canonical topics: `ovos.fallback.register`, `.deregister`, `.ping`, `.pong`.

No repo outside the harness's own conformance suite and spec-authoring
tooling (`ovos-spec-tools`) was found emitting or consuming these topics.
`ovos-core`'s fallback pipeline still operates purely on the legacy
in-process `FallbackSkill` registration path. **Not adopted.**

## OVOS-SESSION-1 / OVOS-SESSION-2

Canonical wire fields: `session.active_handlers`, `session.pipeline`,
`session.response_mode`, `session.intent_context` (SESSION-1); `ovos.session.start`
(SESSION-2, client-authority session creation).

SESSION-1 defines the session field registry rather than a dedicated topic,
so adoption here means a repo reads or writes these fields on the `Session`
object rather than subscribing to a topic string.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-bus-client | `session.intent_context` is the adapt-facing frame-stack registry field, held on the `Session` object | adopted | [ovos_bus_client/session.py#L411](https://github.com/OpenVoiceOS/ovos-bus-client/blob/e2acc6845d8fbd79a4652be0321aab947e2aa57f/ovos_bus_client/session.py#L411) |
| ovos-core | filters the active pipeline matchers by `session.pipeline` while dispatching | adopted | [ovos_core/intent_services/service.py#L340](https://github.com/OpenVoiceOS/ovos-core/blob/996b4483772491c0c7d19ae0c0496115446ee2ea/ovos_core/intent_services/service.py#L340) |
| ovos-workshop | skill converse handling reads `session.active_handlers` while looking for a still-active skill | adopted | [ovos_workshop/skills/converse.py#L153](https://github.com/OpenVoiceOS/ovos-workshop/blob/c933068bce3809c253191f978556e3431af68120/ovos_workshop/skills/converse.py#L153) |

SESSION-2's `ovos.session.start` topic (client-authority session creation)
had no producer or consumer anywhere in the swept workspace, including
`ovos-spec-tools` and the harness's own conformance suite. **Not adopted**
as a distinct wire event; session creation in the checked-out repos is still
implicit (first-message-creates-session), not an explicit `ovos.session.start`
emit.

## OVOS-GUI-1

Canonical topics: `gui.page.show`, `gui.value.set`, `gui.clear.namespace`.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-bus-client | emits `gui.page.show` / `gui.value.set` via the `GUIInterface` API | adopted | [ovos_bus_client/apis/gui.py#L398](https://github.com/OpenVoiceOS/ovos-bus-client/blob/e2acc6845d8fbd79a4652be0321aab947e2aa57f/ovos_bus_client/apis/gui.py#L398) |
| ovos-plugin-manager | emits `gui.clear.namespace` from the GUI plugin template | adopted | [ovos_plugin_manager/templates/gui.py#L77](https://github.com/OpenVoiceOS/ovos-plugin-manager/blob/1abb27e0ff412d9d2d8931e82d38fb821b5283c1/ovos_plugin_manager/templates/gui.py#L77) |
| ovos-gui | consumes `gui.page.show` to render pages | adopted | [ovos_gui/namespace.py#L453](https://github.com/OpenVoiceOS/ovos-gui/blob/4cf9823efb1280a13a8a9270eaf757f967b7fe18/ovos_gui/namespace.py#L453) |
| ovos-gui-api-client | consumes `gui.page.show` in its client library | adopted | [ovos_gui_api_client/__init__.py#L525](https://github.com/OpenVoiceOS/ovos-gui-api-client/blob/622486798ba92a7b7bdc3cb4f3fed58eef54c259/ovos_gui_api_client/__init__.py#L525) |
| ovos-gui-plugin-ag-ui | consumes `gui.value.set` / `gui.clear.namespace` to drive AG-UI state deltas | adopted | [ovos_gui_plugin_ag_ui/__init__.py#L258](https://github.com/OpenVoiceOS/ovos-gui-plugin-ag-ui/blob/e7a3e92ae1df1e3f3a89dbfffa68e06785f5e35a/ovos_gui_plugin_ag_ui/__init__.py#L258) |

## OVOS-BRIDGE-1

The bridge role (relaying the bus across an external transport while
preserving session and routing fields) is implemented by the HiveMind
family of repos. `hivemind-core` (published as `HiveMind-core`, org
`JarbasHiveMind`) is the reference bridge implementation.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| HiveMind-core | stamps `context["source"]`/`context["peer"]` on every message injected from an external client, the bridge identity-stamping duty (§3.1) | adopted | [hivemind_core/protocol.py#L2400](https://github.com/JarbasHiveMind/HiveMind-core/blob/8c3e7436d4f1709aac9c22c7cd85680fab5a0601/hivemind_core/protocol.py#L2400) |
| HiveMind-core | preserves `"session"` in `message.context` across the bridge boundary when relaying an inbound message | adopted | [hivemind_core/protocol.py#L2924](https://github.com/JarbasHiveMind/HiveMind-core/blob/8c3e7436d4f1709aac9c22c7cd85680fab5a0601/hivemind_core/protocol.py#L2924) |
| hivescope | asserts `context["source"]` identity in its bridge conformance test harness | adopted (consumer, test tooling) | [hivescope/assertions.py#L1015](https://github.com/JarbasHiveMind/hivescope/blob/618ea5cf35968604f6aaa0d1a93838fd3289306f/hivescope/assertions.py#L1015) |

`hm-core-v3` (a parallel rewrite under the same org) also carries a
`protocol.py` implementing this role; it is not tabled separately here
because it has not been independently diffed against the spec clauses the
way `hivemind-core` was for this page.

## OVOS-MSG-1

Canonical surface: the `Message` envelope (`type`/`data`/`context`) and its
`forward`/`reply` derivations, plus the `context.source`/`context.destination`
routing keys.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-bus-client | defines `Message`, `forward`, `reply`, and bridges legacy topic pairs via `NamespaceTranslator` | transitional (dual-emits spec + legacy topic pairs) | [ovos_bus_client/client/client.py#L29](https://github.com/OpenVoiceOS/ovos-bus-client/blob/e2acc6845d8fbd79a4652be0321aab947e2aa57f/ovos_bus_client/client/client.py#L29) |

Every other repo in the workspace that imports `ovos_bus_client.Message`
inherits this envelope by construction; this table lists only the repo that
defines and translates it, not the transitive closure of Message importers.

## OVOS-AUDIO-IN-1

Canonical topics: `ovos.listener.wakeword`, `ovos.listener.record.started`/`.ended`,
`ovos.listener.awoken`/`.sleep`, `ovos.mic.listen`, `ovos.stt.failed`.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-audio | emits `ovos.mic.listen` when a b64-audio response requests a follow-up listen | adopted | [ovos_audio/service.py#L311](https://github.com/OpenVoiceOS/ovos-audio/blob/8730b0770add2ea75e30badab433499a1219e227/ovos_audio/service.py#L311) |
| ovos-ui-enclosure-protocol | documents its handler against `ovos.listener.awoken` | adopted (consumer) | [ovos_ui_enclosure_protocol/listener.py#L45](https://github.com/OpenVoiceOS/ovos-ui-enclosure-protocol/blob/6679185bc2bb7c448980d85af8a926f62a5c18ce/ovos_ui_enclosure_protocol/listener.py#L45) |
| ovoscope | asserts `ovos.mic.listen` ordering in its test harness | adopted (consumer, test tooling) | [ovoscope/audio.py#L823](https://github.com/OpenVoiceOS/ovoscope/blob/3243d18bdc6017be08064ff46de36d7838eaa18c/ovoscope/audio.py#L823) |

`ovos-dinkum-listener` and `ovos-simple-listener` — the two listener
implementations checked out in this workspace — had no direct match on
these topic strings at `origin/dev`; their wake-word/VAD pipeline surfaces
these events through `ovos-audio`/`ovos-bus-client` rather than emitting the
topics themselves in-process.

## OVOS-AUDIO-1

Canonical topics: `ovos.audio.is_speaking`, `ovos.audio.output.started`/`.ended`,
`ovos.audio.play_sound`, `ovos.audio.queue`, `ovos.audio.speech`, `ovos.audio.stop`.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-audio | answers `ovos.audio.is_speaking` via `SpecMessage.AUDIO_IS_SPEAKING`, and dual-emits the legacy `mycroft.audio.is_speaking` reply alongside it | transitional (dual-emits legacy `mycroft.audio.is_speaking`) | [ovos_audio/service.py#L504](https://github.com/OpenVoiceOS/ovos-audio/blob/8730b0770add2ea75e30badab433499a1219e227/ovos_audio/service.py#L504) |
| ovos-media | consumes `ovos.audio.output.started`/`.ended` from ovos-audio to serialise OCP playback around TTS | adopted | [ovos_media/bus/api.py#L240](https://github.com/OpenVoiceOS/ovos-media/blob/2572bb6859f2a4cd6b158f462153e82228055ec7/ovos_media/bus/api.py#L240) |
| ovos-ui-enclosure-protocol | documents handlers against `ovos.audio.output.started`/`.ended` | adopted (consumer) | [ovos_ui_enclosure_protocol/listener.py#L43](https://github.com/OpenVoiceOS/ovos-ui-enclosure-protocol/blob/6679185bc2bb7c448980d85af8a926f62a5c18ce/ovos_ui_enclosure_protocol/listener.py#L43) |

## OVOS-COMMON-QUERY-1

Canonical topics: `ovos.common_query.ping`/`.pong`, `.request`, `.response`.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-pydantic-models | models `ovos.common_query.ping`/`.pong` as typed messages | adopted | [ovos_pydantic_models/skills/common_query.py#L75](https://github.com/OpenVoiceOS/ovos-pydantic-models/blob/bda5f4df746528a5c2e0708c0aaf2007769908be/ovos_pydantic_models/skills/common_query.py#L75) |
| ovos-workshop | CQS skill base class subscribes to `ovos.common_query.ping` and answers with `.pong` | adopted | [ovos_workshop/skills/ovos.py#L969](https://github.com/OpenVoiceOS/ovos-workshop/blob/c933068bce3809c253191f978556e3431af68120/ovos_workshop/skills/ovos.py#L969) |

## OVOS-INTENT-1

This spec defines the sentence-template grammar — an authoring syntax and a
§6 training-data wire *contract*, not a topic of its own. Grepping for a
topic string is the wrong test here; the honest adoption path is: which
repo implements the grammar's expansion algorithm, and which repo carries
expanded templates onto the wire.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-spec-tools | implements the template `expand`/`iter_expand` grammar (§3–§4) that other repos import | adopted (definition model) | [ovos_spec_tools/expansion.py#L60](https://github.com/OpenVoiceOS/ovos-spec-tools/blob/fa72252852d977e90fe972508c18f07b937812f8/ovos_spec_tools/expansion.py#L60) |
| padacioso | carries expanded templates over the §6 wire contract, consuming the template registration topic via `SpecMessage.INTENT_REGISTER_TEMPLATE` (same registration path tabled under OVOS-INTENT-4) | adopted (consumer) | [padacioso/opm.py#L84](https://github.com/OpenVoiceOS/padacioso/blob/f03d12a4b3bf422ea7d9ce6a5886ce12008605a5/padacioso/opm.py#L84) |

`confirm.dialog`/`confirm.intent` — the illustrative topic names the spec
document uses as examples, not part of the grammar itself — had no hit
outside the harness's own OVOS-INTENT-2 conformance suite, consistent with
them being examples rather than a contract this spec defines.

## OVOS-INTENT-2

Canonical topics: `confirm.dialog`, `confirm.intent`, `person.blacklist`.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-workshop | documents the `"person.blacklist"` example of the `"<entity>.blacklist"` locale-file convention, rather than emitting a dedicated bus topic | transitional (documented convention, not a dedicated bus topic yet) | [ovos_workshop/skills/ovos.py#L1557](https://github.com/OpenVoiceOS/ovos-workshop/blob/c933068bce3809c253191f978556e3431af68120/ovos_workshop/skills/ovos.py#L1557) |

## OVOS-INTENT-3

This spec is explicit that an intent "is therefore not an event... not a
message that any component may emit, and not a topic that any component may
subscribe to" (`intent-3.md` §1). Grepping for a topic string cannot find an
adopter for a spec that defines none by design; the honest adoption path is
the one-owner/one-handler registration binding the spec does mandate.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-spec-tools | defines the `Intent` model (name, required/optional slots, one bound handler) this spec's data model maps onto | adopted (definition model) | [ovos_spec_tools/intent.py#L75](https://github.com/OpenVoiceOS/ovos-spec-tools/blob/fa72252852d977e90fe972508c18f07b937812f8/ovos_spec_tools/intent.py#L75) |
| ovos-workshop | `intent_handler` decorator binds exactly one handler function to one intent, the one-owner rule this spec mandates | adopted (consumer) | [ovos_workshop/decorators/__init__.py#L64](https://github.com/OpenVoiceOS/ovos-workshop/blob/c933068bce3809c253191f978556e3431af68120/ovos_workshop/decorators/__init__.py#L64) |

## OVOS-CONTEXT-1

Canonical surface: `session.intent_context` (declarative intent context
frames) and the `ovos.intent.register.template` registration topic it rides
on.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-bus-client | `session.intent_context` is projected as the adapt-facing frame-stack view | adopted | [ovos_bus_client/session.py#L411](https://github.com/OpenVoiceOS/ovos-bus-client/blob/e2acc6845d8fbd79a4652be0321aab947e2aa57f/ovos_bus_client/session.py#L411) |
| ovos-core | consumes `ovos.intent.register.template`, the registration topic the context frames ride on | adopted | [ovos_core/intent_services/manifest.py#L37](https://github.com/OpenVoiceOS/ovos-core/blob/996b4483772491c0c7d19ae0c0496115446ee2ea/ovos_core/intent_services/manifest.py#L37) |

## OVOS-OCP-1

Canonical topics: `ovos.common_play.play`/`.pause`/`.resume`/`.stop`/`.next`/`.previous`/`.seek`,
`.search`/`.search.start`/`.search.end`, `.announce`, `.media.state`, `.player.state`, `.track.state`.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-media | full player implementation: `ovos.common_play.play` and the rest of the `ovos.common_play.*` surface are emitted and consumed | adopted | [ovos_media/player/now_playing.py#L96](https://github.com/OpenVoiceOS/ovos-media/blob/2572bb6859f2a4cd6b158f462153e82228055ec7/ovos_media/player/now_playing.py#L96) |
| ovos-plugin-manager | audio-backend template emits `ovos.common_play.player.state` | adopted | [ovos_plugin_manager/templates/audio.py#L284](https://github.com/OpenVoiceOS/ovos-plugin-manager/blob/1abb27e0ff412d9d2d8931e82d38fb821b5283c1/ovos_plugin_manager/templates/audio.py#L284) |
| ovos-workshop | `ovos.common_play.play` is emitted by the `OVOSCommonPlaybackSkill` base class | adopted | [ovos_workshop/skills/common_play.py#L458](https://github.com/OpenVoiceOS/ovos-workshop/blob/c933068bce3809c253191f978556e3431af68120/ovos_workshop/skills/common_play.py#L458) |
| ovos-bus-client | `ovos.common_play.play` is forwarded by the `OCPInterface` API | adopted | [ovos_bus_client/apis/ocp.py#L391](https://github.com/OpenVoiceOS/ovos-bus-client/blob/e2acc6845d8fbd79a4652be0321aab947e2aa57f/ovos_bus_client/apis/ocp.py#L391) |
| ovos-skill-alerts | consumes `ovos.common_play.play` to trigger an alarm's audio | adopted (consumer) | [util/media.py#L74](https://github.com/OpenVoiceOS/ovos-skill-alerts/blob/411bade969f22d4bb26eff8b00c6c2822fc0aa59/util/media.py#L74) |
| ovoscope | drives `ovos.common_play.play` and asserts the resulting state topics in its test harness | adopted (consumer, test tooling) | [ovoscope/media.py#L459](https://github.com/OpenVoiceOS/ovoscope/blob/3243d18bdc6017be08064ff46de36d7838eaa18c/ovoscope/media.py#L459) |

## OVOS-PERSONA-1

Canonical topics: `ovos.persona.query`/`.register`/`.deregister`/`.list`,
`.activated`/`.answer`/`.dismissed`.

`ovos-persona` (the pipeline plugin, distinct from `ovos-persona-server`'s
unrelated `ovos.persona.tools.*` agent-tool-discovery surface) subscribes to
and emits five of the seven canonical topics.

| Repo | Role | State | Evidence |
|------|------|-------|----------|
| ovos-persona | consumes `ovos.persona.query` to answer an out-of-band persona query | adopted | [ovos_persona/__init__.py#L136](https://github.com/OpenVoiceOS/ovos-persona/blob/b9a2a880ffc49d77852b91b96e51ed8c2bb25235/ovos_persona/__init__.py#L136) |
| ovos-persona | consumes `ovos.persona.list` and answers with `ovos.persona.list.response` | adopted | [ovos_persona/__init__.py#L137](https://github.com/OpenVoiceOS/ovos-persona/blob/b9a2a880ffc49d77852b91b96e51ed8c2bb25235/ovos_persona/__init__.py#L137) |
| ovos-persona | emits `ovos.persona.activated` / `ovos.persona.dismissed` on persona lifecycle changes | adopted | [ovos_persona/__init__.py#L733](https://github.com/OpenVoiceOS/ovos-persona/blob/b9a2a880ffc49d77852b91b96e51ed8c2bb25235/ovos_persona/__init__.py#L733) |
| ovos-persona | emits `ovos.persona.answer` in reply to a query | adopted | [ovos_persona/__init__.py#L800](https://github.com/OpenVoiceOS/ovos-persona/blob/b9a2a880ffc49d77852b91b96e51ed8c2bb25235/ovos_persona/__init__.py#L800) |

`ovos-persona`'s `register_persona`/`deregister_persona` are in-process
methods, not bus topics — `ovos.persona.register`/`.deregister` themselves
had no producer or consumer anywhere in the swept workspace. **Partially
adopted**: query/list/activated/dismissed/answer are live on the bus;
register/deregister remain in-process-only (transitional).

## OVOS-TRANSFORM-1

Canonical topics: `ovos.transformer.audio.list`, `.dialog.list`, `.intent.list`,
`.metadata.list`, `.tts.list`, `.utterance.list` (each with a `.response`
counterpart).

No producer or consumer was found in the workspace outside `architecture`
and `ovos-spec-tools`'s own message-model tests. Transformer plugin
discovery in the checked-out repos still runs through
`ovos-plugin-manager`'s in-process plugin loading rather than a bus
introspection topic. **Not adopted.**

## OVOS-SCHEDULER-1

Canonical topics: `ovos.scheduler.schedule`, `.cancel`, `.list`, `.fire`,
`.missed` (each request with a `.response` counterpart).

The harness has no suite for this spec, so nothing here was measured against a
running stack. `ovos-workshop`'s scheduled-event API and the legacy
`mycroft.scheduler.*` adapter are the surfaces a survey would start from.
**Not surveyed.**

---
[← Coverage](coverage.md) · [Home](../README.md)
