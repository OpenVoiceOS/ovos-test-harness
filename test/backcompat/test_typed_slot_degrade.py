"""OVOS-INTENT-1 §3.4, the degrade rule, across the S and M axes.

The skill ships ``alarm.set.intent`` with a typed placeholder,
``set an alarm in {number:offset} minutes``. Two things decide whether a
user still gets an alarm:

* **S**: what the skill container's workshop puts on the wire for that
  line. A workshop with typed slots folds the prefix and carries the type
  beside the template; an older one registers the raw line.
* **M**: what the core side's matcher does with the samples it receives.
  §3.4: "A loader that does not implement typed slots MUST treat
  ``{type:name}`` as ``{name}``: strip the prefix, keep the slot." A matcher
  that raises on the raw line, or keeps ``number:offset`` as the slot name,
  is not that loader.

The samples fed to the matcher are the ones the real skill registered on
this combo's bus, never a constant, so the cell reads the pair and not one
side of it. The matcher is this venv's own ``ovos_padatious``, whichever
engine it resolves to (fann, or the padacioso fallback).
"""
import os
import tempfile

import pytest

from .driver import Capture
from .test_mixed_version_matrix import stack  # noqa: F401  the shared bus + skill fixture
from .skill_process import SKILL_ID, TYPED_STEM

COMBO = os.environ.get("BACKCOMPAT_COMBO", "")
SKILL_PYTHON = os.environ.get("BACKCOMPAT_SKILL_PYTHON", "")

#: The same guard the shared matrix module carries. ``pytestmark`` is a
#: per-module name: importing the ``stack`` fixture from
#: ``test_mixed_version_matrix`` does NOT bring that module's skipif with
#: it. Without this line the fixture reaches its own ``pytest.fail``
#: ("unknown BACKCOMPAT_COMBO ''") in any job that sets no combo, which is
#: what the integration job does, so this file errored at setup there while
#: passing in every cell run.
pytestmark = pytest.mark.skipif(
    not COMBO or not SKILL_PYTHON,
    reason="mixed-version matrix needs BACKCOMPAT_COMBO and "
           "BACKCOMPAT_SKILL_PYTHON; see test/backcompat/build_venvs.sh")
UTTERANCE = "set an alarm in 5 minutes"
#: ovos_workshop.intents._drop_malformed_samples's log line, the S-side
#: failure mode a typed line meets on a workshop that validates slot names
#: but knows no type prefix.
_DROPPED_AS_MALFORMED = "Skipping malformed template line"


def _typed_registration(registrations: Capture):
    for m in registrations.messages:
        name = str(m.data.get("name", ""))
        if name.startswith(f"{SKILL_ID}:") and TYPED_STEM in name:
            return m
    return None


def _engine():
    """This venv's real padatious intent engine, whichever backend it has."""
    from ovos_padatious import IntentContainer
    return IntentContainer(tempfile.mkdtemp(prefix="backcompat-typed-"))


def _match(engine, utterance):
    match = engine.calc_intent(utterance)
    name = getattr(match, "name", None)
    slots = getattr(match, "matches", None)
    if slots is None:
        slots = getattr(match, "entities", None)
    return name, dict(slots or {})


@pytest.mark.axes("S", "M")
def test_typed_slot_template_degrades_to_the_bare_slot(stack):
    """The pair contract: the alarm registers and matches with slot ``offset``."""
    _server, _bus, skill, regs = stack
    regs.wait_for_count(2, 30)
    reg = _typed_registration(regs)
    if reg is None and _DROPPED_AS_MALFORMED in skill.log:
        # Failure mode S1, measured on old-skill/old-core and
        # old-skill/new-core (ovos-workshop 9.3.1a2): the workshop drops
        # every typed line as a malformed template and never registers the
        # intent, so nothing reaches any matcher. Probe-derived from the
        # skill's own log line, not a version compare: the day a workshop
        # keeps the line the registration appears and the assertions below
        # run for real.
        pytest.xfail(
            f"{COMBO}: S side, the skill container's workshop dropped the "
            f"typed lines as malformed ({_DROPPED_AS_MALFORMED!r}) and "
            f"registered no {TYPED_STEM} intent; OVOS-INTENT-1 §3.4 asks "
            f"the loader to strip the prefix and keep the slot")
    assert reg is not None, (
        f"{COMBO}: no {TYPED_STEM} registration on the wire; got "
        f"{[m.data.get('name') for m in regs.messages]}; "
        f"skill process log:\n{skill.log}")
    samples = list(reg.data.get("samples") or [])
    assert samples, f"{COMBO}: the typed registration carried no samples"

    engine = _engine()
    try:
        engine.add_intent("alarm", samples)
        engine.train()
    except Exception as e:  # the matcher broke on the template
        pytest.fail(
            f"{COMBO}: the matcher refused the typed template (§3.4 says a "
            f"loader without typed slots MUST strip the prefix and keep the "
            f"slot). samples on the wire: {samples!r}; "
            f"{type(e).__name__}: {e}")
    name, slots = _match(engine, UTTERANCE)
    assert name == "alarm", (
        f"{COMBO}: {UTTERANCE!r} did not match the alarm intent; "
        f"samples on the wire: {samples!r}, match: {name!r} {slots!r}")
    assert slots.get("offset") == "5", (
        f"{COMBO}: the slot is not named by its name: samples on the wire "
        f"{samples!r}, slots {slots!r}")
