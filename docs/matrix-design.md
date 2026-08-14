# The mixed-version matrix — axis model and pruning rules

`test/backcompat/` proves the spec stack survives being installed at *two
different vintages at once* — an old skill talking to a new core, a new
matcher plugin under an old core, and so on. This page is the normative
source for that matrix's design: the axes, why the naive cartesian product
is pruned down, and how to add a cell. `test/backcompat/cells.py`,
`test/backcompat/conftest.py`, `test/backcompat/driver.py`,
`test/backcompat/findings.py`, `test/backcompat/test_mixed_version_matrix.py`
and [`ci.md`](ci.md) all cite section numbers on this page — keep them in
sync when you change the shape of the matrix.

This page vendors only what the code depends on. It does not carry the
original spec-boundary archaeology (commit-by-commit evidence for each
version boundary) or CI-budget projections — those were investigation notes,
not part of the running design.

## §1.1 — spec-boundary pins are commit-verified, not guessed

Every `==`/`>=` pin in [`build_venvs.sh`](../test/backcompat/build_venvs.sh)
marks a real behaviour boundary — a specific commit, verified against
`origin/dev` of the pinned repo, that changed what's observable on the bus.
`build_venvs.sh`'s header comment carries the one-line reason for each pin;
this page does not duplicate it. If you're re-pinning a boundary (a release
moved, a fix landed), verify the new boundary commit yourself — walking
`git log --ancestry-path <commit>..origin/dev --grep="Increment Version"` to
find the first release containing it — and update both the pin and its
header comment together.

## §1.2 — components that cannot drift independently

`converse`, `fallback`, and `stop` are not separate packages — they ship
inside `ovos-core` as `opm.pipeline` entry points
(`ovos_core/intent_services/*_service.py`). A container is resolved as a
unit, so anything living in the same distribution as `ovos-core`, or pulled
in by one of its floors, moves with it. There is no reachable "new core, old
stop pipeline" cell — that mix cannot be installed, not just isn't tested.
This is why the matrix has a **core stack** axis (`ovos-core` + its in-core
pipelines + whatever bus-client version its floor resolves), not one axis
per pipeline.

## §1.3 — bus-client floors are lower bounds, never ceilings

Every `ovos-bus-client` dependency in the fleet (`ovos-workshop`,
`ovos-audio`, the matcher plugins) is declared as a floor
(`ovos_bus_client>=X`), never capped. A boundary-pin container therefore
always resolves a *current* `ovos-bus-client` when it's rebuilt — there is
no real deployment where an old skill container also carries an old bus
client, short of a distro constraints file forcing one. That's exactly what
the 4 channel cells are for (§2.5): they're the only place an old client is
reachable at all. This is also why `venv_skill_old` in `build_venvs.sh`
deliberately leaves `ovos-bus-client` unpinned rather than freezing it —
pinning it away would hide the real deployment shape the matrix exists to
observe.

## §2.1 — the four axes and why the naive cartesian is out

Eight named components crossed pairwise would be 256 cells. Three rules
collapse that:

- **R1 — coherent stacks.** Anything resolved as one distribution collapses
  onto one axis (§1.2 is the concrete case: core + in-core pipelines +
  resolved bus-client).
- **R2 — drop the spec-inert axis.** `ovos-messagebus` never depends on
  `ovos-spec-tools` and only changes transport (tornado vs. websockets, TLS).
  Crossing it against every cell buys nothing; it runs once, as a transport
  smoke variant on the reference cell, not as a matrix axis.
- **R3 — prune version-inert (axis, scenario) pairs.** A scenario is only
  crossed against an axis that can actually change its outcome — see the
  pruning table in §2.4.

That leaves four axes, each independently reachable by real package
resolution (not a contrivance — a deployer can actually end up running this
combination):

| Axis | `old` | `new` | Independently reachable? |
|---|---|---|---|
| **S — skill container** | `ovos-workshop==9.3.1a2` | `ovos-workshop @ dev` | yes — a frozen skill image is the whole premise of this matrix |
| **C — core stack** (core + in-core converse/fallback/stop + resolved bus-client) | `ovos-core==2.5.5a2` | `ovos-core @ dev` | yes |
| **M — matcher plugins** (padatious + adapt) | `ovos-padatious==2.0.0a1`, `ovos-adapt-parser==1.3.4a1` | `ovos-padatious>=2.0.1a2`, `ovos-adapt-parser>=1.4.0a1` | yes for padatious in both directions — `ovos-core`'s runtime `dependencies` name neither matcher package, only its `[test]` extra does, so both old-matcher/new-core and new-matcher/old-core are real deployments. Adapt's old vintage does **not** co-resolve with either core pin this matrix uses (its `ovos-spec-tools` cap is below both core floors) — see `build_venvs.sh`'s header for the verbatim resolver error. So the old side of the M axis is padatious-only, and adapt appears only via the skew sub-cells below. |
| **A — audio side** | pre-#165 `ovos-audio` 1.x contract (behavioural, via the `audio_process.py` simulator) | AUDIO-1 §5 contract | yes — `ovos-audio` is not a runtime dependency of core (`mycroft` extra only) |

`2×2×2×2 = 16` boundary cells, plus the 4 channel cells (§2.5), which pin
the whole stack off a live OVOS distro constraints file instead of crossing
individual axes.

## §2.2 — reachable mixes, and the matcher skew

| Candidate mix | Reachable by real resolution? | Verdict |
|---|---|---|
| old S / new C | yes — frozen skill image, upgraded host | IN (the historic red cell) |
| new S / old C | yes — new skill installed into an old host | IN (the ovos-workshop#500 tripwire) |
| new C / old M | yes — matchers are deployer-installed, no floor from core | IN — the padatious 2.0.0a1 cell |
| old C / new M | yes — `ovos-padatious>=2.0.1a2` has no core ceiling | IN — canonical dispatch from an *old* core |
| padatious-new / adapt-old skew (and inverse) | yes, but only affects registration spelling | IN, registration/dispatch scenario only — **and only in the padatious-old/adapt-new direction**: the inverse does not co-resolve with either core pin this matrix uses (§2.1's M row) |
| old S with an old bus-client | no — every bus-client floor in the fleet is a lower bound, so a real container always resolves a current client. Only reachable via a distro constraints file. | OUT of the boundary tier; covered by the 4 channel cells |
| any mix × old messagebus | reachable but semantically inert (R2) | OUT — becomes a transport smoke variant |
| old C / new in-core pipeline | impossible — same distribution (§1.2) | OUT |

## §2.4 — the pruning table

`X` = cross this scenario against this axis. `–` = inert for this scenario;
run once on the reference cell only. This is what
[`conftest.py`](../test/backcompat/conftest.py)'s `pytest_collection_modifyitems`
hook applies via each test's `@pytest.mark.axes(...)` marker
(`cells.is_redundant` is the underlying predicate).

| Scenario | S (skill) | C (core) | M (matchers) | A (audio) |
|---|---|---|---|---|
| register/dispatch | **X** | **X** | **X** | – |
| converse | **X** | **X** | – | – |
| get_response (answer) | **X** | **X** | – | – |
| get_response (timeout) | **X** | **X** | – | **X** (a missed listen-flag / `ovos.mic.listen` changes the timeout path) |
| speak + wait_while_speaking | **X** | – | – | **X** |
| session + CONTEXT-1 round-trip | **X** | **X** | – | – |
| common_query fan-out | **X** | **X** | – | – |
| fallback | **X** | **X** | – | – |
| stop | **X** | **X** | – | – |

Two guards sit on top of the plain "all crossed axes are reference" pruning
rule (`cells.is_redundant`'s docstring has the full reasoning):

- **the all-reference cell is never redundant, for anything.** Pruning
  means "don't re-prove what an already-crossed axis showed elsewhere"; it
  is never license to drop the positive control itself (Part 4 rule 5).
- **an axis with no live probe wired never counts as reference.** Axis A is
  nominally `"new"` in every alias, but the audio probe only produces a real
  observation while `audio_process.py` is actually running for that test —
  see `cells.UNPROBED_AXES`.

## §2.5 — cell identity and adding a new cell

A cell is a 4-tuple, one vintage per axis:

```
S{old|new}-C{old|new}-M{old|new}-A{old|new}
```

`cells.py` is the single source of truth for cell identity — `cell_id()`
builds one, `axis_values()` parses one back apart, `is_redundant()` decides
which scenarios a cell actually needs to run. The original four combo names
(`old-skill/old-core`, `old-skill/new-core`, `new-skill/old-core`,
`new-skill/new-core`) are kept as aliases in `cells.BOUNDARY_ALIASES`
resolving to a 4-tuple, so `BACKCOMPAT_COMBO` and the CI matrix entries
don't need to change names. The worked example:

```python
"old-skill/old-core": cell_id("old", "old", "old", "new"),
#                                S      C      M      A
# M is "old" here even though the combo name only varies S and C:
# today's core_old pin also pins padatious 2.0.0a1 (its contemporary
# release), so the M axis is welded to C for this particular alias.
```

Channel cells (`stable-skill/dev-core`, `dev-skill/stable-core`,
`testing-skill/dev-core`, `dev-skill/testing-core`) are a separate tier —
they pin the whole stack off a live OVOS distro constraints file rather than
crossing individual axes, so `cells.resolve_cell()` returns `None` for them
and axis pruning does not apply.

**To add a new cell:**

1. **Pick the axis values.** Decide which of S/C/M/A move and which stay at
   `REFERENCE` ("new"/dev). Check §2.2's reachability table first — a mix
   that cannot really be installed is not a cell, however interesting it
   would be to test.
2. **Add a `build_venvs.sh` venv** for any axis combination that isn't
   already built. Follow the existing `mkvenv` calls: an exact `==` pin on
   the `old` side, a `>=` floor (or `@dev`/`$CORE_SPEC`) on the `new` side.
   Add the venv name to `ALL_BOUNDARY_VENVS` (or `ALL_CHANNEL_VENVS` if it's
   a channel venv) and document the pin choice — which commit crossed the
   boundary, why the old side stops there — in the script's header comment
   block, next to the existing pins.
3. **Add the `COMBOS` entry** in `test_mixed_version_matrix.py`, pointing at
   the venv pair (or triple, with audio) `build_venvs.sh` now builds. Follow
   the file's existing worked comments for how a combo's expected-vintage
   values are read off real symbols (`hasattr(opm, "_dealias_intent_name")`,
   `skill.bound_topics`), never off a version string — a version-string
   check can't tell a stale pin from a real regression.
4. **Add the alias to `cells.BOUNDARY_ALIASES`** (or `cells.CHANNEL_CELLS`
   for a channel combo), resolving your combo name to the 4-tuple cell id
   from step 1. If the cell also needs a matcher skew (padatious and adapt
   at different vintages), record the adapt vintage in `cells.MATCHER_SKEW`
   too — see the skew note in `cells.py`.
5. **Pin the venv cohort.** A cell's venvs must be internally consistent —
   don't let two `old` pins on the same axis drift apart between two combos
   that both claim `Sold-...`. Reuse an existing venv rather than building a
   near-duplicate whenever the pin is identical.
6. **Name the boundary.** Every test exercising the new cell needs an
   `xfail` (if it's expected to fail) whose reason names the real boundary
   commit/PR it's blocked on — never a bare "known issue". See Part 4 rule 5
   and `findings.py` for how that reason string becomes a findings-feed
   record.
7. **Verify collection.** `pytest test/backcompat/ --collect-only` should
   show your new combo's tests with the markers you expect, and
   `test_cells.py` should still pass — it's the adversarial check that a
   mislabeled or unwired cell fails loudly instead of silently agreeing with
   whatever the fixture expects.

## §2.6 — the audio axis uses a simulator, not real `ovos-audio`

Standing up real `ovos-audio` needs a TTS plugin and a sound device.
Instead, `test/backcompat/audio_process.py` runs as a third process in a
third venv (`venv_audio`, pinning only `ovos-bus-client`) and implements
only the AUDIO-1 §5 output lifecycle contract at a chosen vintage:

- `A=old` — subscribes to the legacy `speak` topic, emits
  `recognizer_loop:audio_output_start` / `..._end` (the pre-#165
  `ovos-audio` 1.x contract).
- `A=new` — subscribes to `SpecMessage.SPEAK`, emits
  `SpecMessage.AUDIO_OUTPUT_STARTED` / `..._ENDED`, and `SpecMessage.MIC_LISTEN`
  on the listen flag (today's `ovos_audio/playback.py` behaviour).

Because the axis is behavioural rather than a package pin, `venv_audio` also
doubles as the knob for testing `OVOS_BUS_EMIT_LEGACY=false` end to end —
the same kill-switch pattern the intent-registration tests already use.

## §3.1 / §3.2 — CI budget notes

Building every venv in every job is wasteful once there are more than a
couple of cells: `build_venvs.sh <target> [venv-name ...]` accepts specific
venv names so a CI job builds only the pair (or triple) its cell actually
needs, instead of the whole set — see the script's own header comment for
the full venv list and the caching rule (boundary venvs are cacheable on the
script's hash; channel venvs must never be cached, since re-resolving live
distro constraints every run is their entire purpose). [`ci.md`](ci.md)
documents the trigger tiers actually wired up in
[`backcompat_matrix.yml`](../.github/workflows/backcompat_matrix.yml) today
— that's the operational source of truth, not this page.

## Part 2 / Part 4 rule 5 — positive controls are mandatory per cell

A red cell is only trustworthy if a green cell would have been believable.
Every cell — including the all-reference one, which never gets pruned (see
the guard in §2.4) — needs its own positive control alongside its `xfail`s:
`test_core_dispatches_the_topic_this_combo_expects`,
`test_pins_are_the_intended_vintage`, and their per-scenario equivalents.
Without a positive control, a silently broken fixture reads as a compat
finding instead of a fixture bug.

The rest of the xfail discipline (`xfail(strict=True)` always, never a bare
skip, structured reasons, never deleting a red cell to make a PR green) is
enforced in `driver.py`'s `boundary_xfail` helper and `CONTRIBUTING.md`; see
those for the mechanics.

## §4.2 — the findings feed

`test/backcompat/conftest.py`'s `pytest_terminal_summary` hook calls
`test/backcompat/findings.py` to write one JSON record per `xfail`ed or
`xpass`ed test in a cell's run:

```json
{
  "cell": "Sold-Cnew-Mnew-Anew",
  "scenario": "test/backcompat/test_mixed_version_matrix.py::test_the_skill_handler_runs",
  "axes": ["S", "C", "M"],
  "boundary": "<the xfail reason's boundary= field, or a best-effort parse of free text>",
  "blocked_on": "ovos-bus-client#271",
  "owner": "ovos-bus-client",
  "outcome": "xfail"
}
```

Each CI job uploads its file as a `backcompat-findings-<cell>` artifact. A
final `summarize` job downloads all of them, groups by **boundary** (a
boundary is a unit of compat work; a cell is not), and renders
`FINDINGS/SPRINT.md`, with an XPASS section first — those are the free wins,
a fix that already shipped and just needs its marker dropped. `summarize`
makes no GitHub writes; it only uploads the file and echoes it into
`$GITHUB_STEP_SUMMARY`. See [`ci.md`](ci.md#the-findings-feed-and-findingssprintmd)
for how this fits into the wider workflow.

---
[← CI](ci.md) · [Home](../README.md) · [Testing branch combinations →](testing-combos.md)
