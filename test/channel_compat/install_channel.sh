#!/usr/bin/env bash
# Install the conformance stack as one OVOS distro release channel ships it.
#
# Usage:  test/channel_compat/install_channel.sh <stable|testing|alpha> [work-dir]
#
# The constraints file is fetched LIVE, never vendored: this gate is supposed to
# track the fleet, so the day the distro bumps a pin the next run sees it. The
# fetched file is written to <work-dir>/constraints-<channel>.txt and is meant
# to be uploaded as a CI artifact, so a red run can be traced back to exactly
# what the channel pinned that day.
#
# Install precedence (see test/channel_compat/resolve.py for the long form):
#
#   1. Every package the constraints file names is installed BY NAME under
#      `-c <constraints>`. The channel decides the version. This is the whole
#      point of the job, so it happens first and nothing later may move it.
#   2. Plain requirements.txt lines the channel does not name (ovos-spec-tools,
#      pytest...) are installed next, still under `-c`, so their transitive
#      deps cannot climb above the channel either.
#   3. Git-URL requirements.txt lines the channel does not name are installed
#      with --no-deps. Their metadata pins the dev stack; honouring it would
#      undo step 1.
#
# `pip install -c constraints.txt -r requirements.txt` is NOT equivalent and
# does not work here: requirements.txt is almost all direct git URLs, and pip
# does not apply constraints to a direct URL.
set -euo pipefail

CHANNEL="${1:?usage: install_channel.sh <stable|testing|alpha> [work-dir]}"
WORK="${2:-${RUNNER_TEMP:-/tmp}/channel-compat}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

case "$CHANNEL" in
  stable|testing|alpha) ;;
  *) echo "unknown channel: $CHANNEL (want stable, testing, or alpha)" >&2; exit 2 ;;
esac

BASE_URL="${CHANNEL_CONSTRAINTS_BASE_URL:-https://raw.githubusercontent.com/OpenVoiceOS/OpenVoiceOS/main}"
URL="$BASE_URL/constraints-$CHANNEL.txt"

mkdir -p "$WORK"
CFILE="$WORK/constraints-$CHANNEL.txt"
echo "==> fetching $URL"
curl -fsSL --retry 5 --retry-all-errors --retry-delay 3 "$URL" -o "$CFILE"

PLAN="$WORK/plan-$CHANNEL"
python3 "$REPO_ROOT/test/channel_compat/resolve.py" \
  --requirements "$REPO_ROOT/requirements.txt" \
  --constraints "$CFILE" \
  --out-dir "$PLAN"

PIP=(python3 -m pip install --disable-pip-version-check)

echo "==> [1/4] channel-pinned packages"
xargs -a "$PLAN/covered.txt" -r "${PIP[@]}" -c "$CFILE" --

echo "==> [2/4] leftovers the channel does not pin"
if [ -s "$PLAN/uncovered_plain.txt" ]; then
  "${PIP[@]}" -c "$CFILE" -r "$PLAN/uncovered_plain.txt"
fi
# setuptools<81 for the same reason test/backcompat/build_venvs.sh pins it: the
# older channel stacks still `import pkg_resources`, which setuptools 81 removed.
# Without this the run cannot even start — ovoscope ships a pytest11 entry point,
# so the ImportError happens while pytest loads plugins, before any test exists
# to mark as a known gap.
"${PIP[@]}" -c "$CFILE" pytest-timeout "setuptools<81"

echo "==> [3/4] git leftovers, without deps"
if [ -s "$PLAN/uncovered_git.txt" ]; then
  "${PIP[@]}" --no-deps -r "$PLAN/uncovered_git.txt"
fi

# ovos-media is the OVOS-OCP-1 Virtual Media Player. No channel names it and it
# pins an incompatible ovos-bus-client, so it is installed the same way
# integration.yml installs it: --no-deps plus the leaf deps ovos_media.player
# actually imports.
#
# ovos-gui-api-client's only PyPI release pins ovos-bus-client<2.0. The
# stable/testing constraints allow that, so they install the leaf deps under -c
# as before. The alpha constraints (bus-client>=2.7.2a1) make it unsatisfiable
# under -c, so alpha installs the leaf deps unconstrained (as integration.yml
# does) and with --no-deps for the client itself, so the resolver never tries to
# downgrade the alpha bus-client 2.x already installed for the core.
echo "==> [4/4] ovos-media (OCP-1 harness)"
"${PIP[@]}" --no-deps ovos-media
if [ "$CHANNEL" = "alpha" ]; then
  "${PIP[@]}" --no-deps ovos-gui-api-client
  "${PIP[@]}" dbus_next json-database
else
  "${PIP[@]}" -c "$CFILE" ovos-gui-api-client dbus_next json-database
fi

echo
echo "==> resolved channel versions"
python3 - <<'EOF'
from importlib.metadata import version, PackageNotFoundError
for p in ("ovos-core", "ovos-workshop", "ovos-bus-client", "ovos-padatious",
          "ovos-adapt-parser", "ovos-plugin-manager", "ovos-config",
          "ovos-spec-tools", "ovoscope"):
    try:
        print(f"    {p}=={version(p)}")
    except PackageNotFoundError:
        print(f"    {p}: NOT INSTALLED")
EOF
