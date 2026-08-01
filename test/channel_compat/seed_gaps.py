"""Write a channel known-gaps file from a pytest JSON report.

Usage:

    pytest test/ --json-report --json-report-file=report.json ...
    python3 test/channel_compat/seed_gaps.py stable report.json

Every node that failed or errored becomes a known-gap line. Read the diff before
committing it: a line here says "this channel does not implement this clause
yet", and each one should be true for that reason and not because the run was
flaky or the install was broken.
"""
import argparse
import json
import os

HEADER = """\
# Known conformance gaps on the OVOS distro "{channel}" release channel.
#
# Each line is a pytest node id that FAILS when the conformance suite runs
# against the package versions {channel} pins. These are real spec gaps in the
# shipped stack, not harness problems, so the channel-compat job xfails exactly
# these and stays green — anything NOT listed here that breaks turns the job
# red, which is the whole point of the file.
#
# The xfails are strict. A listed node that starts PASSING also turns the job
# red: the channel caught up and the line must be deleted. A listed node that
# no longer exists fails the run too, so a renamed test cannot rot in here.
#
# Regenerate after a channel bump:
#
#   test/channel_compat/install_channel.sh {channel}
#   pytest test/ --json-report --json-report-file=report.json --tb=no -q
#   python3 test/channel_compat/seed_gaps.py {channel} report.json
#
# Seeded from a real run of the {channel} channel stack:
{versions}
#
# Sections:
#   [modules]  files that do not import at all on this channel
#   [tests]    individual node ids that fail
#   [xpass]    node ids the suite marks xfail(strict) for a dev-stack reason
#              that does not hold here, so they pass; the marker is relaxed
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("channel", choices=("stable", "testing"))
    ap.add_argument("report")
    ap.add_argument("--versions", default="",
                    help="newline-separated 'pkg==ver' lines to record in the "
                         "header comment")
    args = ap.parse_args()

    with open(args.report) as f:
        report = json.load(f)

    bad, xpass = set(), set()
    for t in report.get("tests", []):
        if t.get("outcome") not in ("failed", "error"):
            continue
        longrepr = str((t.get("call") or {}).get("longrepr") or "")
        (xpass if longrepr.startswith("[XPASS(strict)]") else bad).add(
            t["nodeid"])
    bad, xpass = sorted(bad), sorted(xpass)
    collectors = sorted({c["nodeid"] for c in report.get("collectors", [])
                         if c.get("outcome") == "failed" and c.get("nodeid")})

    versions = "\n".join(f"#   {line.strip()}"
                         for line in args.versions.splitlines() if line.strip())
    out = os.path.join(os.path.dirname(__file__), "..", "channel_gaps",
                       f"{args.channel}.txt")
    with open(os.path.abspath(out), "w") as f:
        f.write(HEADER.format(channel=args.channel, versions=versions or "#   (unrecorded)"))
        f.write("\n[modules]\n")
        f.writelines(f"{c}\n" for c in collectors)
        f.write("\n[tests]\n")
        f.writelines(f"{n}\n" for n in bad)
        f.write("\n[xpass]\n")
        f.writelines(f"{n}\n" for n in xpass)
    print(f"wrote {os.path.abspath(out)}: {len(collectors)} modules, "
          f"{len(bad)} tests, {len(xpass)} xpass")


if __name__ == "__main__":
    main()
