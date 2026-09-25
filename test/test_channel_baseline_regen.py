"""The baseline-regeneration step must survive a collection error.

``channel_compat.yml`` runs the suite twice. The first run is the verdict and
carries ``OVOS_CHANNEL``, so ``conftest.py`` skips the suites the channel cannot
import. The second run regenerates the gaps file and deliberately runs WITHOUT
``OVOS_CHANNEL``, because ``seed_gaps.py`` has to SEE those import failures to
write the ``[modules]`` section.

That is why the second run needs ``--continue-on-collection-errors`` and the
first one must not have it:

* without the flag, the regeneration run stops at ``Interrupted: N errors
  during collection`` before one test executes. The json report carries no
  tests, so the regenerated file's ``[tests]`` and ``[xpass]`` sections come out
  EMPTY while ``[modules]`` looks right. A maintainer who commits that file
  un-gates every real gap the channel has (206 tests and 1 xpass on stable, 114
  and 2 on testing at the time this guard was written). Observed in runs
  34132803840 and 34743564533;
* WITH the flag on the FIRST run, an unexpected import failure would no longer
  stop that job, and the whole point of ``test_channel_gaps.py`` is that a suite
  the baseline does not excuse must import. The abort there is the signal.

So this guard asserts a difference between two steps, not a flag in a file.
"""
import os
import re

WORKFLOW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        ".github", "workflows", "channel_compat.yml")
FLAG = "--continue-on-collection-errors"


def _step(name):
    """Return the text of one ``- name: <name>`` step, up to the next step."""
    text = open(os.path.abspath(WORKFLOW)).read()
    start = text.find(f"- name: {name}")
    assert start != -1, f"no step named {name!r} in channel_compat.yml"
    nxt = text.find("\n      - name: ", start + 1)
    return text[start:nxt if nxt != -1 else len(text)]


def _commands(name):
    """The step's runnable lines, with every ``#`` comment dropped.

    The flag is explained in a comment inside the step it belongs to, so a
    search over the raw step text finds that explanation and passes even after
    the flag itself is deleted. The first version of this guard did exactly
    that, and a break check caught it: removing the flag left the test green.
    """
    out = []
    for line in _step(name).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        out.append(line.split(" #", 1)[0] if " #" in line else line)
    return "\n".join(out)


def test_the_regeneration_step_continues_past_a_collection_error():
    step = _commands("Regenerate the baseline for comparison")
    assert FLAG in step, (
        "the regeneration run has no " + FLAG + ": a channel that cannot "
        "import a suite aborts collection, and the regenerated gaps file then "
        "drops every [tests] and [xpass] line while looking well formed")


def test_the_verdict_run_still_aborts_on_an_unexpected_collection_error():
    step = _commands("Run the conformance suite on the ${{ matrix.channel }} channel")
    assert FLAG not in step, (
        "the verdict run carries " + FLAG + ": an import failure the baseline "
        "does not excuse would no longer stop the job, which is the signal "
        "test_channel_gaps.py depends on")


def test_the_regeneration_step_does_not_set_the_channel():
    """The premise of the flag: this step runs un-gated, so it sees the errors."""
    step = _step("Regenerate the baseline for comparison")
    # An ASSIGNMENT, not the word: the step's own comment explains why the
    # variable is absent, and a bare substring test reads that explanation and
    # fails. The first version of this guard did exactly that.
    assigned = [l for l in step.splitlines()
                if re.match(r"\s*OVOS_CHANNEL\s*:", l)]
    assert not assigned, (
        "the regeneration step sets OVOS_CHANNEL " + str(assigned) + ", so "
        "conftest.py skips the unimportable suites and seed_gaps.py writes an "
        "empty [modules] section. This guard's reasoning needs rewriting")
