#!/usr/bin/env bash
# Build the four venvs the mixed-version back-compat matrix runs against.
#
# Two venvs are alive per combo: one holds the skill's packages, one holds the
# core's. They talk over a real websocket, which is the only way one test run
# can observe two different package sets.
#
# Usage:  test/backcompat/build_venvs.sh <target-dir> [venv-name ...]
#
# With no venv-name arguments, ALL of them are built (this is what keeps any
# existing caller that just passes a target dir working unchanged, e.g.
# `docs/ci.md`'s usage example). Name one or more of the venvs below to build
# only those — this is what lets each CI matrix job build exactly the pair (or
# triple) its cell needs instead of the whole set:
#
#   venv_skill_old venv_skill_new venv_core_old venv_core_new venv_audio
#   venv_core_new_matchers_old venv_core_old_matchers_new
#   venv_core_skew_padatious_old_adapt_new
#   venv_skill_stable venv_skill_testing venv_core_stable venv_core_testing
#
# An unrecognized name is a hard error (not a silent no-op), since a typo'd
# name would otherwise build nothing and look like a build that just skipped
# fast.
#
# Layout note: the four *boundary* venvs (venv_skill_old/new, venv_core_old/
# new) live directly under $TARGET, unchanged from before this script gained
# venv-name filtering. The four *channel* venvs (venv_skill_stable/testing,
# venv_core_stable/testing) live under $TARGET/channel/ instead.
#
# NOT a cache boundary: these venvs are NOT safe to cache across CI runs.
# venv_skill_new and venv_core_new install `@dev` git refs, so "already built"
# does not mean "still current". venv_skill_old deliberately leaves
# ovos-bus-client unpinned — that float is what makes it the ovos-bus-client
# #271 XPASS tripwire (a real frozen skill container resolving a *current*
# client); pinning it away would permanently disarm the signal this suite
# exists to raise. venv_core_old's test deps (pytest, pytest-timeout,
# ovos-messagebus) are unpinned too. None of the four venvs this script builds
# are exact enough to cache safely; see the pins list below for what is and
# is not pinned in each.
#
# Rebuild safety: each mkvenv call only skips a directory that has a
# `.build-complete` marker written after a fully successful install. A
# directory that exists WITHOUT the marker (e.g. a prior run killed mid-build)
# is removed and rebuilt, so a half-built venv is never mistaken for a
# finished one. mkvenv_channel always rebuilds unconditionally — it must, so
# it re-resolves the live distro constraints every call; that's the whole
# point of a channel venv.
#
# This harness installs no package of its own (see docs/how-it-works.md), so
# the "new core" side is pinned to a ref the way requirements.txt pins the rest
# of the stack.
#
# Pins, and why each one is where it is:
#
#   skill_old  ovos-workshop==9.3.1a2
#              The newest release that binds the handler to the suffixed
#              `<skill_id>:<file>.intent` topic ONLY. 9.3.2a1 added the
#              canonical binding alongside it (ovos-workshop#497), which hides
#              the breakage, so the pin must stay below that line.
#              ovos-bus-client is deliberately NOT pinned: a real frozen
#              container resolves the workshop floor and gets a current client,
#              and the repair in ovos-bus-client#271 depends on exactly that.
#
#   skill_new  ovos-workshop @ dev
#              Binds both spellings today. ovos-workshop#500 makes it
#              canonical-only, which is what will turn the new-skill/old-core
#              cell red.
#
#   core_old   ovos-core==2.5.5a2 + ovos-padatious==2.0.0a1
#              + ovos-workshop==9.2.3a1 + ovos-bus-client==2.7.0a1
#              The newest padatious release BEFORE registration-time
#              canonicalization (`_dealias_intent_name`, added in 2.0.1a1), so
#              this side dispatches whatever the skill registered. ovos-core is
#              pinned to its contemporary release; core itself forwards
#              `match.match_type` verbatim, so the pipeline plugin is the part
#              that decides the spelling.
#              ovos-workshop and ovos-bus-client are WHOLE-COHORT pins, not a
#              belated ceiling on today's specific break: ovos-core's own
#              `dependencies` list floats both (`ovos-workshop<10.0.0,
#              >=9.0.2a1`, `ovos_bus_client<3.0.0,>=2.6.0a1`), so this venv
#              silently resolves whatever is newest on PyPI at BUILD time, not
#              whatever was current when 2.5.5a2 shipped. That is exactly what
#              let ovos-workshop 9.3.12a1 (2026-08-13, workshop#500 — dropped
#              the suffixed `<skill_id>:<file>.intent` binding) resolve into
#              this nominally-old-core venv and flip
#              `backcompat.mixed.test:food.order` (actual) against
#              `...food.order.intent` (expected) on 2026-08-13 (CI run
#              31746623405), across every venv that pins ovos-core==2.5.5a2 --
#              see HANDOFF.md's "Harness defect found by the #39 review:
#              venv_core_old workshop drift". Both pins are each package's
#              latest PyPI release at or before 2.5.5a2's own release
#              (2026-07-17T19:10:10Z): ovos-workshop 9.2.3a1 (released
#              2026-07-17T17:08:18Z) and ovos-bus-client 2.7.0a1 (released
#              2026-07-16T22:06:56Z) -- i.e. what pip would actually have
#              resolved on the day this core vintage shipped, not a version
#              picked to merely dodge today's specific flip. Every OTHER
#              floating dependency of ovos-core (ovos-utils, ovos-config,
#              ovos-plugin-manager, ovos-spec-tools, rapidfuzz, ...) is left
#              unpinned: pinning the whole transitive graph would make this
#              venv a frozen snapshot instead of a "same-vintage container",
#              and none of those packages are on `test_mixed_version_matrix.
#              py`'s dispatch-spelling critical path the way workshop and the
#              bus client are. ovos-padatious keeps its exact pin (unchanged
#              by this fix) since it was already pinned, not floating.
#
#   core_new   ovos-core @ dev + ovos-padatious>=2.0.1a2
#              Folds at registration, so it dispatches the canonical topic.
#
#   venv_core_new_matchers_old / venv_core_old_matchers_new  (T2.5, the M axis)
#              ovos-core @ dev      + ovos-padatious==2.0.0a1
#              ovos-core==2.5.5a2   + ovos-padatious>=2.0.1a2 + ovos-adapt-parser>=1.4.0a1
#              The matcher plugins are DEPLOYER-installed: ovos-core's runtime
#              `dependencies` list names neither package (only its [test] extra
#              mentions them), so both of these mixes are reachable by real
#              resolution, not contrivances. Until T2.5 every core venv above
#              welded its padatious vintage to its ovos-core vintage, which made
#              the matrix unable to say WHICH of the two packages a red cell was
#              actually attributable to. These two venvs are what let it say
#              that. Same pin syntax as core_old/core_new above (an exact `==`
#              on the old side, a `>=` floor on the new side).
#
#              WHY THE OLD SIDE PINS NO ovos-adapt-parser (verified, T2.5):
#              the adapt half of the M axis is NOT independently reachable in
#              the old direction. `ovos-adapt-parser==1.3.4a1` (the last release
#              before the 1.4.0a1 boundary) caps `ovos-spec-tools<1.0.0`, while
#              ovos-core floors it far above that on BOTH pins this matrix uses
#              — 2.5.5a2 needs spec-tools>=1.5.0a1, dev needs >=1.6.1a1. uv
#              refuses both mixes as unsatisfiable, verbatim:
#
#                Because ovos-adapt-parser==1.3.4a1 depends on
#                ovos-spec-tools>=0.16.1a2,<1.0.0 and ovos-core==2.6.3a1 depends
#                on ovos-spec-tools[langcodes]>=1.6.1a1,<2.0.0, we can conclude
#                that ovos-adapt-parser==1.3.4a1 and ovos-core==2.6.3a1 are
#                incompatible.
#
#              So old-adapt does not co-resolve with either core vintage this
#              matrix pins. It is not unreachable in general — it resolves fine
#              against ovos-core<=2.2.x, which is BELOW this matrix's C-old
#              boundary (2.5.5a2) and therefore outside the axis space entirely.
#              Design §2.1's "matchers are deployer-installed, any mix is real"
#              holds for ovos-padatious against both core pins, and for
#              ovos-adapt-parser only in the new direction. Rather than invent a
#              cell no venv here can build, the old side of M is padatious-only
#              — exactly what venv_core_old already is — and adapt is pinned
#              only where it actually resolves.
#
#   venv_core_skew_padatious_old_adapt_new  (T2.5, design §2.2's skew sub-cells)
#              ovos-core @ dev + ovos-padatious==2.0.0a1 + ovos-adapt-parser>=1.4.0a1
#              The two matchers at OPPOSITE vintages, on a current core.
#              Design §2.2 asks for the skew in both directions (4 sub-cells);
#              only this direction exists, for the resolver reason above — the
#              padatious-new/adapt-old inverse does not co-resolve with either
#              core pin, so it is not built and not claimed.
#
#              venv_core_old_matchers_new ALSO pins ovos-core==2.5.5a2 (an
#              "old" C-vintage venv, same as venv_core_old above), so it gets
#              the same ovos-workshop==9.2.3a1 + ovos-bus-client==2.7.0a1
#              whole-cohort pins for the same reason -- see venv_core_old's
#              entry above for the full rationale and evidence. Its M-axis
#              packages (padatious/adapt) stay on their existing `>=` floors
#              deliberately: M=new on this venv means "track current/latest
#              matchers", the same floating-latest posture as every C=new
#              venv, and is not itself the drift this fix closes.
#
#              venv_core_new, venv_core_new_matchers_old and
#              venv_core_skew_padatious_old_adapt_new all pin `$CORE_SPEC`
#              (ovos-core @ dev) -- the "new" C-vintage cohort, which is
#              MEANT to float latest everything by design (that is what
#              tracking dev means), so none of those three get a workshop or
#              bus-client pin here.
#              §2.2 calls the skew a registration/dispatch-scenario concern,
#              which is a statement about what the skew can CHANGE, not about
#              what these cells RUN: like every other cell they run the whole
#              suite (minus whatever axis pruning deselects). Nothing here
#              filters them down to scenario 1, and adding a -k filter would
#              cost more than the handful of seconds it would save.
#
#   venv_audio ovos-bus-client only (current)
#              Backs test/backcompat/audio_process.py (design §2.6). The
#              A-axis "vintage" is BEHAVIOURAL, not a package pin -- there is
#              no real ovos-audio installed here, and no old-vs-new
#              ovos-bus-client split either (every skill/core venv already
#              resolves a current client off its own floor, per §1.3). This
#              venv is the same knob every OVOS_BUS_EMIT_LEGACY test already
#              uses, just running the third (audio) process instead of the
#              skill or core one.
#
#   venv_skill_stable / venv_skill_testing
#   venv_core_stable  / venv_core_testing
#              Not boundary pins — fleet pins. Built by installing straight
#              off the OVOS distro's own constraint files, fetched at build
#              time (not vendored), so this gate TRACKS the fleet: the day the
#              distro bumps a pin past a behavior boundary, the affected cell
#              goes red at that exact moment, which is the point. Today both
#              channels resolve an ovos-workshop and ovos-padatious floor well
#              below the 9.3.2a1 / 2.0.1a1 boundaries above, so the *-skill
#              side is suffixed-only and the *-core side never canonicalizes
#              on either channel — see test_mixed_version_matrix.py for what
#              that implies per cell. The fetched constraints file is saved
#              into $TARGET for upload as a CI artifact, so a future red cell
#              can be traced back to exactly what was pinned that day.
set -euo pipefail

TARGET="${1:?usage: build_venvs.sh <target-dir> [venv-name ...]}"
shift
CORE_SPEC="${CORE_SPEC:-ovos-core @ git+https://github.com/OpenVoiceOS/ovos-core@dev}"

STABLE_CONSTRAINTS_URL="${BACKCOMPAT_STABLE_CONSTRAINTS_URL:-https://raw.githubusercontent.com/OpenVoiceOS/OpenVoiceOS/main/constraints-stable.txt}"
TESTING_CONSTRAINTS_URL="${BACKCOMPAT_TESTING_CONSTRAINTS_URL:-https://raw.githubusercontent.com/OpenVoiceOS/OpenVoiceOS/main/constraints-testing.txt}"

PY="${BACKCOMPAT_PYTHON:-python3.11}"

ALL_BOUNDARY_VENVS=(venv_skill_old venv_skill_new venv_core_old venv_core_new venv_audio
                    venv_core_new_matchers_old venv_core_old_matchers_new
                    venv_core_skew_padatious_old_adapt_new)
ALL_CHANNEL_VENVS=(venv_skill_stable venv_skill_testing venv_core_stable venv_core_testing)
ALL_VENVS=("${ALL_BOUNDARY_VENVS[@]}" "${ALL_CHANNEL_VENVS[@]}")

REQUESTED=("$@")
if [ "${#REQUESTED[@]}" -eq 0 ]; then
  REQUESTED=("${ALL_VENVS[@]}")
else
  for name in "${REQUESTED[@]}"; do
    known=0
    for v in "${ALL_VENVS[@]}"; do
      [ "$name" = "$v" ] && known=1 && break
    done
    if [ "$known" -eq 0 ]; then
      echo "error: unknown venv name '$name'" >&2
      echo "valid names: ${ALL_VENVS[*]}" >&2
      exit 1
    fi
  done
fi

wants() {
  local name="$1"
  for v in "${REQUESTED[@]}"; do
    [ "$name" = "$v" ] && return 0
  done
  return 1
}

mkdir -p "$TARGET" "$TARGET/channel"

have_uv() { command -v uv >/dev/null 2>&1; }

mkvenv() {
  local name="$1"; shift
  local dir="$TARGET/$name"
  if [ -f "$dir/.build-complete" ]; then
    echo "==> $name already built, skipping"
    return
  fi
  if [ -d "$dir" ]; then
    echo "==> $name exists without a completion marker (half-built), rebuilding"
    rm -rf "$dir"
  fi
  echo "==> building $name"
  if have_uv; then
    uv venv --python "$PY" "$dir" >/dev/null
    VIRTUAL_ENV="$dir" uv pip install --quiet --prerelease=allow "$@"
  else
    "$PY" -m venv "$dir"
    "$dir/bin/pip" install --quiet "pip>=24,<25"  # range pin, not an unbounded upgrade
    "$dir/bin/pip" install --quiet --pre "$@"
  fi
  echo "    $("$dir/bin/python" -c 'import sys; print(sys.version.split()[0])')"
  touch "$dir/.build-complete"
}

# Like mkvenv, but constrained by a distro constraints file fetched fresh at
# build time, and always rebuilt unconditionally (no completion marker, no
# skip) — it must re-resolve the live distro constraints every call, which is
# the whole point of a channel venv.
# $1=name $2=constraints-url $3..=packages to install
mkvenv_channel() {
  local name="$1" url="$2"; shift 2
  local dir="$TARGET/channel/$name"
  local cfile="$TARGET/channel/${name#venv_}.constraints.txt"
  echo "==> fetching constraints for $name from $url"
  curl -fsSL --retry 5 --retry-all-errors --retry-delay 3 "$url" -o "$cfile"
  echo "==> building $name (constrained)"
  if have_uv; then
    uv venv --python "$PY" "$dir" >/dev/null
    VIRTUAL_ENV="$dir" uv pip install --quiet --prerelease=allow -c "$cfile" "$@"
  else
    "$PY" -m venv "$dir"
    "$dir/bin/pip" install --quiet "pip>=24,<25"  # range pin, not an unbounded upgrade
    "$dir/bin/pip" install --quiet --pre -c "$cfile" "$@"
  fi
  echo "    $("$dir/bin/python" -c 'import sys; print(sys.version.split()[0])')"
}

wants venv_skill_old && mkvenv venv_skill_old "ovos-workshop==9.3.1a2" "setuptools<81"
wants venv_skill_new && mkvenv venv_skill_new "ovos-workshop @ git+https://github.com/OpenVoiceOS/ovos-workshop@dev" "setuptools<81"
wants venv_core_old  && mkvenv venv_core_old  "ovos-core==2.5.5a2" "ovos-padatious==2.0.0a1" "ovos-workshop==9.2.3a1" "ovos-bus-client==2.7.0a1" ovos-messagebus pytest pytest-timeout "setuptools<81"
wants venv_core_new  && mkvenv venv_core_new  "$CORE_SPEC" "ovos-padatious>=2.0.1a2" ovos-messagebus pytest pytest-timeout "setuptools<81"
# T2.5 -- the M (matcher) axis. See the pins block in this file's header for
# why each of these four is a reachable deployment and not a contrivance.
wants venv_core_new_matchers_old && mkvenv venv_core_new_matchers_old \
  "$CORE_SPEC" "ovos-padatious==2.0.0a1" \
  ovos-messagebus pytest pytest-timeout "setuptools<81"
wants venv_core_old_matchers_new && mkvenv venv_core_old_matchers_new \
  "ovos-core==2.5.5a2" "ovos-padatious>=2.0.1a2" "ovos-adapt-parser>=1.4.0a1" \
  "ovos-workshop==9.2.3a1" "ovos-bus-client==2.7.0a1" \
  ovos-messagebus pytest pytest-timeout "setuptools<81"
wants venv_core_skew_padatious_old_adapt_new && mkvenv venv_core_skew_padatious_old_adapt_new \
  "$CORE_SPEC" "ovos-padatious==2.0.0a1" "ovos-adapt-parser>=1.4.0a1" \
  ovos-messagebus pytest pytest-timeout "setuptools<81"

wants venv_audio      && mkvenv venv_audio    ovos-bus-client "setuptools<81"

wants venv_skill_stable  && mkvenv_channel venv_skill_stable  "$STABLE_CONSTRAINTS_URL"  ovos-workshop "setuptools<81"
wants venv_skill_testing && mkvenv_channel venv_skill_testing "$TESTING_CONSTRAINTS_URL" ovos-workshop "setuptools<81"
wants venv_core_stable   && mkvenv_channel venv_core_stable   "$STABLE_CONSTRAINTS_URL"  ovos-core ovos-padatious ovos-messagebus pytest pytest-timeout "setuptools<81"
wants venv_core_testing  && mkvenv_channel venv_core_testing  "$TESTING_CONSTRAINTS_URL" ovos-core ovos-padatious ovos-messagebus pytest pytest-timeout "setuptools<81"

echo
echo "resolved versions:"
for v in "${REQUESTED[@]}"; do
  dir="$TARGET/$v"
  case " ${ALL_CHANNEL_VENVS[*]} " in
    *" $v "*) dir="$TARGET/channel/$v" ;;
  esac
  echo "  $v:"
  "$dir/bin/python" - <<'EOF' || true
from importlib.metadata import version, PackageNotFoundError
for p in ("ovos-workshop", "ovos-bus-client", "ovos-core", "ovos-padatious",
          "ovos-adapt-parser", "ovos-spec-tools"):
    try:
        print(f"    {p}=={version(p)}")
    except PackageNotFoundError:
        pass
EOF
done
