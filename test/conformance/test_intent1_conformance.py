"""OVOS-INTENT-1 conformance suite — the Sentence Template Grammar.

Encodes the normative MUST/MUST NOT clauses of OVOS-INTENT-1
(``ovos/org/architecture/intent-1.md``, version 2) as assertions against
``ovos-spec-tools`` — the reference implementation of the spec's three
conformance roles (§7): the **Expander** (:func:`ovos_spec_tools.expand`), the
**Dialog renderer** (:func:`ovos_spec_tools.render`), and the slot model.

INTENT-1 is a *file-format / grammar* spec: it defines the tokens, the
expansion algorithm, the malformed-form rejection rules, and the slot fill
modes — none of which involve the bus. Almost every clause is therefore best
asserted by calling the spec-tools API **directly**, which is the bulk of this
suite. A handful of clauses also have an **end-to-end** counterpart — that a
template, once expanded and registered, actually drives an utterance match —
captured in :class:`TestE2EExpansionDrivesMatch`, guarded behind the full
ovos-core stack the harness installs in CI.

xfail discipline (see ``_conformance.py``): each test asserts what the spec
*mandates* and runs it against spec-tools; where the implementation diverges
the test is ``@pytest.mark.xfail(strict=True, ...)`` quoting the clause and
the actual behaviour, flipping to a pass when the impl is corrected. Assertions
are never weakened to make a divergence pass.

Coverage map (clause -> status against ovos-spec-tools):
- §2   input model: brackets cannot be literal / no escape ........ green (note)
- §3.2 alternatives expand to one branch each ..................... green
- §3.2 empty branch contributes nothing .......................... green
- §3.3 ``[x]`` is exactly ``(x|)`` ............................... green
- §3.4 ``{{name}}`` folds to ``{name}`` (equivalent) ............. green
- §3.4 slot name charset (lowercase/digit/_, no leading digit) ... green
- §3.5 groups nest without limit ................................. green
- §3.6 unbalanced metacharacters rejected ........................ green
- §3.6 single-branch group rejected .............................. green
- §3.6 empty-sample template rejected ............................ green
- §3.6 slot-only template rejected ............................... green
- §3.6 adjacent slots rejected (surface + expanded) .............. green
- §3.6 repeated slot name rejected ............................... green
- §3.6 undefined vocabulary reference rejected ................... green
- §3.6 cyclic vocabulary reference rejected ...................... green
- §3.7 ``<name>`` expands to its vocabulary as alternatives ...... green
- §4.1 slots opaque through expansion ............................ green
- §4.1 whitespace normalized / duplicates removed ................ green
- §4.2 worked example sample set exact ........................... green
- §5.1 dialog: unfilled slot MUST NOT render ..................... green
- §5.5 dialog: mixed slot sets MUST be rejected .................. xfail (load_dialog)
- §5.5 intent: mixed slot sets MUST be accepted .................. green
"""
import importlib.util
import time
from unittest import TestCase

import pytest

from ovos_spec_tools import (
    MalformedTemplate,
    UnfilledSlot,
    expand,
    render,
)

# ── e2e stack probe ──────────────────────────────────────────────────────────
# The grammar clauses are pure spec-tools API. The e2e match counterpart needs
# the full ovos-core stack the harness pins in requirements.txt; skip it
# wholesale when that stack is absent so the direct-API suite still runs.
_HAS_STACK = importlib.util.find_spec("ovoscope") is not None and \
    importlib.util.find_spec("ovos_workshop") is not None


# ─────────────────────────────────────────────────────────────────────────────
# §2 — Input model
# ─────────────────────────────────────────────────────────────────────────────

class TestSec2InputModel(TestCase):
    """§2: input-direction templates are authored in normalized form; the
    metacharacters ``( ) [ ] { } | < >`` "cannot occur as literal input … and
    no escape mechanism is needed or provided"."""

    def test_no_escape_mechanism_brackets_are_structural(self):
        """A literal ``(`` has no escape and is parsed structurally — a bare
        ``(`` is unbalanced and MUST be rejected (§2 "no escape mechanism is
        … provided"; §3.6 unbalanced metacharacters)."""
        with self.assertRaises(MalformedTemplate):
            expand("turn ( on")

    # note: §2 normalization (lowercasing, punctuation stripping) is performed
    # "upstream of the intent engine and is out of scope for this grammar" — the
    # expander "MAY assume its input already satisfies the contract", so there
    # is no normalization behaviour of the expander to assert here.


# ─────────────────────────────────────────────────────────────────────────────
# §3.2 — Alternatives ( | )
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3_2Alternatives(TestCase):
    """§3.2: parentheses enclose branches separated by ``|``; each combination
    "takes exactly one branch from each group"."""

    def test_each_branch_yields_one_sample(self):
        """``(a|b|c)`` yields one sample per branch (§3.2)."""
        self.assertEqual(
            sorted(expand("(turn on|switch on|enable) the lights")),
            ["enable the lights", "switch on the lights", "turn on the lights"],
        )

    def test_empty_branch_contributes_nothing(self):
        """"A branch MAY be empty. An empty branch contributes nothing" (§3.2)."""
        self.assertEqual(
            sorted(expand("(please|) turn on the lights")),
            ["please turn on the lights", "turn on the lights"],
        )

    def test_single_branch_group_is_malformed(self):
        """"A group MUST contain at least one ``|`` … a group with no ``|`` is
        malformed" (§3.2, §3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("(word) the lights")


# ─────────────────────────────────────────────────────────────────────────────
# §3.3 — Optional segments [ ]
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3_3Optionals(TestCase):
    """§3.3: ``[x]`` is "exactly equivalent to the alternative group ``(x|)``"."""

    def test_optional_equivalent_to_alternative_with_empty(self):
        """``[x]`` expands to {with-x, without-x}, identical to ``(x|)`` (§3.3)."""
        self.assertEqual(
            sorted(expand("turn on [the] lights")),
            sorted(expand("turn on (the|) lights")),
        )


# ─────────────────────────────────────────────────────────────────────────────
# §3.4 — Named slots { }
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3_4NamedSlots(TestCase):
    """§3.4: the single-brace ``{name}`` and double-brace ``{{name}}`` forms
    are "exactly equivalent"; a slot name is lowercase ASCII letters, digits and
    underscores, never beginning with a digit."""

    def test_double_brace_folds_to_single_brace(self):
        """"a conformant tool folds ``{{name}}`` to ``{name}`` and treats them
        identically" — the sample sets are identical (§3.4)."""
        self.assertEqual(expand("(buy|sell) {{item}}"),
                         expand("(buy|sell) {item}"))

    def test_slot_carried_through_unchanged(self):
        """A slot is "not written out but filled" — it survives expansion as an
        opaque ``{name}`` term (§3.4, §4.1)."""
        self.assertEqual(expand("buy {item}"), ["buy {item}"])

    def test_slot_name_must_not_begin_with_digit(self):
        """A slot name "MUST NOT begin with a digit" (§3.4)."""
        with self.assertRaises(MalformedTemplate):
            expand("buy {1item}")

    def test_slot_name_charset_lowercase_only(self):
        """A slot name is "lowercase ASCII letters, digits, and underscores"
        only — uppercase is rejected (§3.4)."""
        with self.assertRaises(MalformedTemplate):
            expand("buy {Item}")

    def test_slot_name_no_whitespace(self):
        """A slot name "MUST NOT contain whitespace inside the braces" (§3.4)."""
        with self.assertRaises(MalformedTemplate):
            expand("buy {two words}")

    def test_slot_inside_group(self):
        """A slot "MAY appear anywhere a literal word may, including inside an
        alternative" (§3.4)."""
        self.assertEqual(
            sorted(expand("(buy|sell) {item}")),
            ["buy {item}", "sell {item}"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# §3.5 — Nesting
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3_5Nesting(TestCase):
    """§3.5: "Expansion groups MAY be nested without limit." (quoted clause)."""

    def test_nested_optional_and_alternatives(self):
        """A nested ``[(all|every) ]light[s]`` expands fully (§3.5)."""
        self.assertEqual(
            sorted(expand("turn on [(all|every) ]light[s]")),
            ["turn on all light", "turn on all lights",
             "turn on every light", "turn on every lights",
             "turn on light", "turn on lights"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# §3.6 — Malformed forms (a tool MUST reject each)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3_6Malformed(TestCase):
    """§3.6: "a tool MUST reject any template that contains" any of the
    enumerated malformed forms."""

    def test_unbalanced_paren_rejected(self):
        """"Unbalanced metacharacters — an unmatched ``(`` …" MUST be rejected
        (§3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("(a|b the lights")

    def test_unbalanced_brace_rejected(self):
        """An unmatched ``{`` MUST be rejected (§3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("buy {item the thing")

    def test_unbalanced_angle_rejected(self):
        """An unmatched ``<`` MUST be rejected (§3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("buy <thing the item")

    def test_empty_group_rejected(self):
        """The empty ``()`` is a single-branch group and MUST be rejected
        (§3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("x ()")

    def test_empty_sample_template_rejected(self):
        """"Empty sample — a template whose sample set … contains the empty
        string" MUST be rejected; ``[x]`` is the simplest case (§3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("[x]")

    def test_slot_only_template_rejected(self):
        """"Slot-only template — a template that is a single named slot and
        nothing else" MUST be rejected (§3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("{name}")

    def test_adjacent_slots_rejected_on_surface(self):
        """"Adjacent slots — two named slots with no literal word between them"
        MUST be rejected (§3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("{a} {b}")

    def test_adjacent_slots_rejected_in_expanded_sample(self):
        """"the check applies to the expanded sample set … not only the template
        surface": ``{a} [foo] {b}``'s empty-foo branch yields adjacent slots and
        MUST be rejected (§3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("{a} [foo] {b}")

    def test_repeated_slot_name_rejected(self):
        """"Repeated slot name — using the same ``{name}`` more than once in one
        template" MUST be rejected (§3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("{x} and {x}")

    def test_undefined_vocabulary_reference_rejected(self):
        """"Undefined vocabulary reference — a ``<name>`` … for which no
        vocabulary … is available" MUST be rejected (§3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("say <greeting> there")

    def test_cyclic_vocabulary_reference_rejected(self):
        """"Cyclic vocabulary reference — a chain … that includes itself" MUST
        be rejected (§3.6)."""
        with self.assertRaises(MalformedTemplate):
            expand("say <a>", {"a": ["<a>"]})


# ─────────────────────────────────────────────────────────────────────────────
# §3.7 — Inline vocabulary reference < >
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3_7VocabularyReference(TestCase):
    """§3.7: ``<name>`` "is replaced by a named vocabulary … exactly as if those
    members had been written as an alternative group in its place"."""

    def test_reference_expands_to_alternatives(self):
        """The §3.7 worked example: ``<greeting> [there] {name}`` with greeting
        = {hello, hi, good morning}."""
        self.assertEqual(
            sorted(expand("<greeting> [there] {name}",
                          {"greeting": ["hello", "hi", "good morning"]})),
            sorted(expand("(hello|hi|good morning) [there] {name}")),
        )

    def test_reference_recurses(self):
        """"a referenced vocabulary MAY contain further ``<…>`` references;
        resolution recurses" (§3.7, §4.1 step 1)."""
        self.assertEqual(
            sorted(expand("say <a> now",
                          {"a": ["<b>", "x"], "b": ["y", "z"]})),
            ["say x now", "say y now", "say z now"],
        )

    def test_vocabulary_reference_name_charset(self):
        """``name`` "obeys the same charset as a slot name" — a leading digit is
        rejected (§3.7)."""
        with self.assertRaises(MalformedTemplate):
            expand("say <1greeting>", {"1greeting": ["hi"]})


# ─────────────────────────────────────────────────────────────────────────────
# §4 — Expansion
# ─────────────────────────────────────────────────────────────────────────────

class TestSec4Expansion(TestCase):
    """§4: a template "expands to a sample set: a finite set of sample
    sentences" by the §4.1 reference enumeration."""

    def test_slots_never_expanded(self):
        """"Named slots ``{...}`` are opaque throughout: they are carried
        through unchanged and are never expanded" (§4.1)."""
        out = expand("(buy|sell) {item} now")
        self.assertEqual(sorted(out), ["buy {item} now", "sell {item} now"])

    def test_whitespace_normalized(self):
        """"Normalize whitespace … replace every run of one or more spaces with
        a single space, and strip leading and trailing spaces" (§4.1 step 4)."""
        # the empty branch leaves a double space which MUST collapse to one
        self.assertEqual(expand("a (b|) c"), ["a b c", "a c"])
        self.assertIn("turn on the lights",
                      expand("(please|) turn on the lights"))

    def test_duplicates_removed(self):
        """"Remove duplicates. The remaining distinct strings are the sample
        set" (§4.1 step 5)."""
        self.assertEqual(expand("(a|a) x"), ["a x"])

    def test_worked_example_exact(self):
        """§4.2 worked example: ``(turn|switch) [the] (light|fan)`` → exactly
        eight samples."""
        self.assertEqual(
            sorted(expand("(turn|switch) [the] (light|fan)")),
            ["switch fan", "switch light", "switch the fan", "switch the light",
             "turn fan", "turn light", "turn the fan", "turn the light"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# §5 — Named slots: fill modes and consistency
# ─────────────────────────────────────────────────────────────────────────────

class TestSec5_1DialogFill(TestCase):
    """§5.1: caller-supplied fill (``.dialog``): "The caller MUST supply a value
    for every slot in the chosen phrase; a phrase with an unfilled slot MUST NOT
    be sent to TTS." (quoted clause)."""

    def test_filled_slot_renders(self):
        """A dialog slot the caller supplies is rendered into the phrase (§5.1)."""
        self.assertEqual(
            render(["it is {temperature} degrees"], {"temperature": "18"}),
            "it is 18 degrees",
        )

    def test_unfilled_slot_must_not_render(self):
        """An unfilled dialog slot MUST NOT be rendered — the renderer raises
        rather than emit it (§5.1)."""
        with self.assertRaises(UnfilledSlot):
            render(["it is {temperature} degrees"], {})


class TestSec5_5SlotConsistency(TestCase):
    """§5.5: "A ``.dialog`` definition MUST NOT mix templates that declare
    different slots … A tool MUST reject a ``.dialog`` definition whose
    templates do not all declare the same slot set." A ``.intent`` definition,
    by contrast, "MAY declare different slot sets … A tool MUST NOT reject" it."""

    def test_dialog_mixed_slot_sets_rejected(self):
        """A ``.dialog`` whose phrases declare different slot sets MUST be
        rejected by a dialog renderer — the §5.5 verification is a property of
        the *definition* (the phrase set), not of which phrase is chosen (§5.5).
        ``render`` takes the whole phrase set as its definition; a conformant
        renderer refuses a mixed set before choosing."""
        phrases = ["say {greeting}", "say hello to {name}"]
        # supplying both slot values so the only possible failure is the §5.5
        # mixed-slot-set rejection, not an UnfilledSlot for the chosen phrase.
        with self.assertRaises((ValueError, MalformedTemplate)):
            for _ in range(16):
                render(phrases, {"greeting": "hi", "name": "sam"})

    def test_intent_mixed_slot_sets_accepted(self):
        """"Templates in one ``.intent`` file MAY declare different slot sets …
        A tool MUST NOT reject" it — each template expands independently (§5.5)."""
        # the play.intent example: {query} vs {query}+{engine}
        a = expand("(play|put on) {query}")
        b = expand("(play|put on) {query} (on|using) {engine}")
        self.assertEqual(sorted(a), ["play {query}", "put on {query}"])
        self.assertIn("play {query} on {engine}", b)


# ─────────────────────────────────────────────────────────────────────────────
# §4 / §6 — End-to-end: an expanded template drives an utterance match
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_STACK,
                    reason="full ovos-core/ovoscope stack not installed "
                           "(harness installs the pinned stack in CI)")
class TestE2EExpansionDrivesMatch(TestCase):
    """§4/§6 end-to-end: a template registered as training data — once expanded
    per §4 — actually drives an intent match through the real pipeline. The
    grammar clauses above assert the *sample set*; this asserts the spec's
    promise that "an engine consumes the expanded sample set as training data"
    (§4) on the live orchestrator."""

    @classmethod
    def setUpClass(cls):
        from ovos_utils.log import LOG
        from ovoscope import get_minicroft, register_padatious_intent
        from ._conformance import reset_namespace, use_spec_namespace
        LOG.set_level("ERROR")
        use_spec_namespace()
        try:
            cls._mc = get_minicroft([])
            time.sleep(1)
            # register an intent from a template whose expansion includes the
            # utterance we will send (§4.2-style expansion → samples).
            cls._intent = "intent1.skill:lights"
            cls._samples = expand("(turn on|switch on) [the] lights")
            register_padatious_intent(cls._mc.bus, cls._intent, cls._samples)
            time.sleep(1.5)
        except BaseException:
            reset_namespace()
            raise

    @classmethod
    def tearDownClass(cls):
        from ._conformance import reset_namespace
        try:
            if getattr(cls, "_mc", None) is not None:
                cls._mc.stop()
        finally:
            reset_namespace()

    def test_expanded_branch_matches(self):
        """An utterance equal to one expanded branch (§4.2) is matched and
        dispatched to ``skill_id:intent_name`` (§4 training-data contract)."""
        from ._conformance import PADACIOSO_HIGH, capture, types, utterance
        recs = capture(self._mc, utterance(
            "switch on the lights", "s1", [PADACIOSO_HIGH]), 4.0)
        self.assertIn(self._intent, types(recs),
                      f"expected {self._intent} dispatch; saw {types(recs)}")
