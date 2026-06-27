# Testing branch combinations

The reason `ovos-test-harness` exists is to **prove a combination of cross-repo
branches conforms** to the [`OpenVoiceOS/architecture`](https://github.com/OpenVoiceOS/architecture)
specs *before* any of those branches merges. This page is the workflow for doing
that.

## Why you can't do this anywhere else

An architecture spec clause is almost never satisfied by a change in one repo. A
typical clause is a *contract between a producer and a consumer*:

- **INTENT-4 §5/§6** — `ovos-workshop` must *emit* the registration topics
  (`ovos.intent.register.keyword` / `.template`) **and** `ovos-core` must *consume*
  them. Neither side alone makes the clause pass.
- **SESSION-1/2** — `ovos-bus-client` must carry the spec session fields
  (`active_handlers`, `converse_handlers`, …) **and** `ovos-core` must populate
  them.

You cannot prove either from inside `ovos-core`'s CI or `ovos-workshop`'s CI: each
installs its own package plus a PyPI-resolved everything-else, and pip is free to
drop the sibling branch you care about (see
[how-it-works.md](how-it-works.md#the-problem-it-solves-resolver-downgrade)). The
harness owns the cross-repo surface so the combination can be pinned and proven.

## The PR-driven workflow

1. **Pick the combination.** Decide which (possibly unmerged) branches across the
   stack you want to certify together.
2. **Edit `requirements.txt`.** Set each repo's ref to the branch under test.
3. **Open a PR** against the harness `dev`. The `integration` workflow installs
   that exact stack and runs the full spec conformance suite against it — see
   [ci.md](ci.md).
4. **Read the verdict** in the PR's check: which clauses pass, which are `xfail`
   (documented gaps), which fail.
5. **Flip to `@dev` as branches merge.** Once a branch lands upstream, change its
   ref back to `@dev` so the harness continues to certify the merged trunk.

The PR diff *is* the statement of which stack is being certified — reviewable,
versioned, and reproducible.

## Worked example: proving the INTENT-4 producer/consumer contract

Suppose `ovos-workshop` has a branch `feat/intent-4-producer` that emits the
INTENT-4 registration topics, and `ovos-core` has `feat/intent-4-consumer` that
consumes them. Neither is merged. To prove they interoperate:

```diff
 # core consumes the INTENT-4 registration topics
-git+https://github.com/OpenVoiceOS/ovos-core@dev
+git+https://github.com/OpenVoiceOS/ovos-core@feat/intent-4-consumer
 # workshop emits ovos.intent.register.*
-git+https://github.com/OpenVoiceOS/ovos-workshop@dev
+git+https://github.com/OpenVoiceOS/ovos-workshop@feat/intent-4-producer
```

Open the PR. CI installs that exact pair (plus the rest of the pinned stack) and
runs `test_intent4_conformance.py`. Today, the §5/§6/§7/§8 registration clauses
are marked `xfail` because trunk core consumes the *legacy* `padatious:register_intent`
(see [known-gaps.md](known-gaps.md)). When this pair is installed and genuinely
implements the contract, those `xfail` tests **xpass** — a signal that the gap is
closed and the markers should be removed once the branches merge.

Once both branches land:

```diff
-git+https://github.com/OpenVoiceOS/ovos-core@feat/intent-4-consumer
+git+https://github.com/OpenVoiceOS/ovos-core@dev
-git+https://github.com/OpenVoiceOS/ovos-workshop@feat/intent-4-producer
+git+https://github.com/OpenVoiceOS/ovos-workshop@dev
```

…and the `xfail` markers on the now-passing clauses are dropped, converting them
to plain green conformance against trunk.

## Handling intra-stack version caps

A branch under test often carries a version cap that conflicts with another branch
you also want — e.g. a pipeline plugin pins `ovos-workshop<9` while the workshop
branch you're proving is `9.x`. Do **not** ask pip to resolve this; that
reintroduces the downgrade problem. Instead pin a small branch that *lifts the
cap* and include it in the combination, exactly as the live file does:

```
git+https://github.com/OpenVoiceOS/ovos-adapt-pipeline-plugin@fix/allow-ovos-workshop-9
git+https://github.com/OpenVoiceOS/ovos-skill-parrot@fix/allow-ovos-workshop-10
```

Every package in the combination is named with an exact ref, so the install is
still deterministic.

## The single-ref-per-repo limitation

pip installs **one package per name**, so `requirements.txt` can carry only **one
ref per repo**. Two branches of the *same* repo cannot both be installed —
there is exactly one `ovos-core` in the environment at a time.

This matters when you want to A/B two branches of one repo, or when the change you
are proving is split across two branches of the same repo. Work around it by
**combining the branches into one integration branch** and pinning that single
ref. The live file does exactly this for core:

```
# core with STOP-1 + PIPELINE-1 conformance source (combined integration branch)
git+https://github.com/OpenVoiceOS/ovos-core@test/spec-stack-integration-proof
```

`test/spec-stack-integration-proof` is itself the merge of the separate core-side
changes, pinned as one ref so the single-ref rule is satisfied. To compare two
candidate branches of one repo head-to-head, run **two PRs** (or two
`requirements.txt` revisions) and compare their conformance verdicts.

## See also

- [how-it-works.md](how-it-works.md) — why the install is structured this way.
- [known-gaps.md](known-gaps.md) — the `xfail` clauses a combo PR aims to flip green.
- [ci.md](ci.md) — what the PR check actually runs.
</content>
