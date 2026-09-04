"""Read a channel known-gaps file.

The file lives at ``test/channel_gaps/<channel>.txt`` and has two sections::

    [modules]
    test/conformance/test_transform1_conformance.py

    [tests]
    test/conformance/test_gui1_conformance.py::TestX::test_y

``[modules]`` lists suites that do not even import on that channel, because the
channel ships a package version the suite's imports predate. Those cannot be
xfailed one test at a time — there are no tests to mark — so the harness skips
collecting them and asserts separately that they still fail to import.

``[tests]`` lists node ids that collect but fail. Those get a strict xfail.
This also covers a module that imports fine but whose module-level
``setUpModule()`` raises before any test runs: pytest reports that as an
``ERROR`` against every test in the module, and a strict xfail marker on each
of those node ids catches it the same way it catches an ordinary assertion
failure — just list every affected test individually here.

``[xpass]`` lists node ids the SUITE already marks ``xfail(strict=True)`` for a
dev-stack reason, and which PASS on this channel. The channel is behind dev, so
this is normal: the clause regressed after the channel froze. A strict xfail
turns that pass into a failure, so these node ids get the marker relaxed to
non-strict instead of being expected to fail.

Blank lines and ``#`` comments are ignored.
"""
import os

GAPS_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "channel_gaps")


def gaps_file(channel):
    return os.path.join(GAPS_DIR, f"{channel}.txt")


def read_gaps(channel):
    """Return (modules, tests, xpass) for ``channel``, three sets of strings."""
    path = gaps_file(channel)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"OVOS_CHANNEL={channel} but there is no known-gaps file at "
            f"{path}. Seed one with test/channel_compat/seed_gaps.py.")
    modules, tests, xpass = set(), set(), set()
    sections = {"[modules]": modules, "[tests]": tests, "[xpass]": xpass}
    section = None
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if line in sections:
                section = sections[line]
                continue
            if section is None:
                raise ValueError(f"{path}: line before any section: {line!r}")
            section.add(line)
    return modules, tests, xpass
