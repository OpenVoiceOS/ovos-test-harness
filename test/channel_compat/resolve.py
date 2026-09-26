"""Split the harness stack into a channel install plan.

A *channel* is an OVOS distro release channel. The distro publishes one
constraints file per channel:

    https://raw.githubusercontent.com/OpenVoiceOS/OpenVoiceOS/main/constraints-stable.txt
    https://raw.githubusercontent.com/OpenVoiceOS/OpenVoiceOS/main/constraints-testing.txt

Those files say what version of each OVOS package a real device on that channel
runs. ``requirements.txt`` in this repo says something different: the moving
``@dev`` (or PR-branch) ref of every repo in the spec stack. A channel run has
to honour both, so this module applies one precedence rule:

    **The constraints file wins for every package it names. requirements.txt
    fills in only the packages the constraints file does not name.**

Why not ``pip install -c constraints.txt -r requirements.txt``: almost every
line of ``requirements.txt`` is a direct git URL. pip refuses to apply a
version constraint to a direct URL, and where it does not refuse it simply
ignores the constraint, so the channel pin would silently lose. The split below
is explicit instead: the constraint-covered packages are installed BY NAME
(so the constraint decides the version), and only the leftovers come from
``requirements.txt``.

The output is three files in the plan directory:

``covered.txt``
    Package names to install with ``-c <constraints>``. The channel decides
    the version.
``uncovered_plain.txt``
    Plain (non-URL) requirement lines the channel does not name. Installed with
    ``-c <constraints>`` as well, so their transitive deps still cannot climb
    above the channel.
``uncovered_git.txt``
    Git-URL requirement lines the channel does not name. Installed with
    ``--no-deps``: their own metadata pins the dev stack, and honouring it would
    drag the channel packages back up to dev, which is the exact thing this job
    exists to avoid. Their real dependencies are already present from the two
    steps above; ``test/test_install_floor.py`` fails the run if that is not
    true for a suite-gating import.
"""
import argparse
import os
import re
import sys

# Repos whose distribution name is not the repo name.
DIST_NAME_OVERRIDES = {
    "ovos-adapt-pipeline-plugin": "ovos-adapt-parser",
    "ovos-padatious-pipeline-plugin": "ovos-padatious",
}

# Packages install_channel.sh installs itself, outside this plan, WHEN the
# channel's constraints file does not name them. ovoscope is this harness's
# own test driver, not a member of the device stack a channel's constraints
# file describes, so a channel that never pins it should get the harness's
# own current floor rather than requirements.txt's git leftover handling (its
# own metadata pins a dev-stack ovos-core floor that would ResolutionImpossible
# against an old channel's ovos-core pin if resolved as a plain leftover
# under -c). But a channel that DOES pin ovoscope chose that version because
# it is the one compatible with that channel's own old core/bus-client API —
# ovoscope itself calls accessors (e.g. SessionManager.get_default_session)
# that postdate old channel stacks, so "one current ovoscope everywhere" is
# wrong here. plan() below only excludes a SEPARATELY_INSTALLED name when the
# channel does not cover it; a covered name flows through normally and the
# channel's own pin wins, same as any other channel-covered package.
SEPARATELY_INSTALLED = {"ovoscope"}

GIT_RE = re.compile(r"git\+https://github\.com/[^/]+/(?P<repo>[^@#]+)"
                    r"(?:@(?P<ref>[^#\s]+))?")
NAME_RE = re.compile(r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?P<rest>[<>=!~;\[].*)?$")


def normalize(name):
    """PEP 503 normalization, so ovos-PHAL and ovos_phal are one package."""
    return re.sub(r"[-_.]+", "-", name).lower()


def constraint_names(path):
    names = set()
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            m = NAME_RE.match(line)
            if m:
                names.add(normalize(m.group("name")))
    return names


def requirement_dist_name(line):
    """The distribution name a requirements.txt line installs, or None."""
    m = GIT_RE.search(line)
    if m:
        repo = m.group("repo").removesuffix(".git")
        return normalize(DIST_NAME_OVERRIDES.get(repo, repo))
    m = NAME_RE.match(line)
    return normalize(m.group("name")) if m else None


def plan(requirements, constraints):
    covered_names = constraint_names(constraints)
    covered, uncovered_plain, uncovered_git = [], [], []
    with open(requirements) as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            dist = requirement_dist_name(line)
            if dist is None:
                print(f"warning: unparsed requirement line: {line!r}",
                      file=sys.stderr)
                continue
            if dist in SEPARATELY_INSTALLED and dist not in covered_names:
                # Not pinned by this channel: install_channel.sh installs it
                # separately, at the harness's own floor, outside this plan.
                continue
            if dist in covered_names:
                covered.append(dist)
            elif GIT_RE.search(line):
                uncovered_git.append(line)
            else:
                uncovered_plain.append(line)
    return covered, uncovered_plain, uncovered_git


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--requirements", required=True)
    ap.add_argument("--constraints", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    covered, plain, git = plan(args.requirements, args.constraints)
    os.makedirs(args.out_dir, exist_ok=True)
    for name, items in (("covered.txt", covered),
                        ("uncovered_plain.txt", plain),
                        ("uncovered_git.txt", git)):
        with open(os.path.join(args.out_dir, name), "w") as f:
            f.write("\n".join(items) + ("\n" if items else ""))
    print(f"channel-covered  ({len(covered)}): {' '.join(covered)}")
    print(f"plain leftovers  ({len(plain)}): {' '.join(plain)}")
    print(f"git leftovers    ({len(git)}): "
          f"{' '.join(requirement_dist_name(l) for l in git)}")


if __name__ == "__main__":
    main()
