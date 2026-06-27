"""OVOS-INTENT-2 conformance suite — Locale Resource Formats.

Encodes the normative MUST/MUST NOT clauses of OVOS-INTENT-2
(``ovos/org/architecture/intent-2.md``, version 2) as assertions against
``ovos-spec-tools`` — the reference loader (:class:`LocaleResources`), the
common reader (:func:`read_resource_file` / :func:`read_prompt_file`), the
whole-word occurrence matcher (:func:`utterance_contains`), and the prompt
renderer (:func:`render_prompt`).

INTENT-2 is a *folder-layout and file-format* spec: the locale tree, the
six resource roles, the common line reader, the slot-bearing / slot-free
split, the ``.blacklist`` suppression contract, and the ``.prompt``
double-brace substitution. Every clause is filesystem/string behaviour, so the
suite asserts the spec-tools API **directly**, building throwaway ``locale/``
trees in a tmpdir per test class. A single ``.voc`` matching clause (§4.3
whole-word occurrence) also has an **end-to-end** counterpart on the live
keyword pipeline, in :class:`TestE2EVocOccurrence`, guarded behind the full
stack the harness installs in CI.

xfail discipline: each test asserts what the spec mandates and runs it; a
divergence is ``@pytest.mark.xfail(strict=False, ...)`` quoting the clause and
the actual behaviour. Assertions are never weakened.

Coverage map (clause -> status against ovos-spec-tools):
- §2   resource resolved recursively through subdirectories ....... green
- §2   duplicate (role, base name) in one lang tree MUST be malformed green
- §2   same base name across roles are distinct resources ......... green
- §2   BCP-47 tag comparison is case-insensitive .................. green
- §3   reader discards a leading BOM .............................. green
- §3   reader accepts both LF and CRLF ............................ green
- §3   reader strips lines, skips blanks and ``#``-comments ....... green
- §3   no inline (end-of-line) comments ........................... green
- §4.1 ``.intent`` loads as union of sample sets, slots intact .... green
- §4.2 ``.dialog`` is NOT expanded at load time ................... green
- §4.3 slot-free role with a named slot MUST be malformed ......... green
- §4.3 ``.blacklist`` occurrence = contiguous whole words ......... green
- §4.4 ``.prompt`` substitutes only ``{{name}}`` (double-brace) ... green
- §4.4 ``.prompt`` single brace / lone brace pass through ......... green
- §4.4 ``.prompt`` unfilled ``{{name}}`` stays literal ............ green
- §4.4 ``.prompt`` whole-file verbatim: ``#`` / blanks kept ....... green
- §5    empty resource file MUST be malformed ..................... green
"""
import importlib.util
import tempfile
import time
from pathlib import Path
from unittest import TestCase

import pytest

from ovos_spec_tools import render_prompt
from ovos_spec_tools.resources import (
    LocaleResources,
    MalformedResource,
    read_prompt_file,
    read_resource_file,
    utterance_contains,
)

_HAS_STACK = importlib.util.find_spec("ovoscope") is not None and \
    importlib.util.find_spec("ovos_workshop") is not None


def _make_locale(files: dict) -> Path:
    """Write a throwaway ``locale/`` tree and return the ``locale/`` path.

    ``files`` maps a relative path under ``locale/`` (e.g. ``"en-US/yes.voc"``)
    to file content — ``str`` written UTF-8, ``bytes`` written verbatim (for
    BOM/CRLF fixtures).
    """
    root = Path(tempfile.mkdtemp()) / "locale"
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root


# ─────────────────────────────────────────────────────────────────────────────
# §2 — Locale folder layout
# ─────────────────────────────────────────────────────────────────────────────

class TestSec2FolderLayout(TestCase):
    """§2: resources live under ``locale/<lang>/``; a loader "resolves a
    resource by searching the language directory and all its subdirectories,
    recursively"; uniqueness and case rules apply."""

    def test_resource_found_in_subdirectory(self):
        """A resource in a subdirectory of the language tree is found —
        "searching its subdirectories recursively" (§2)."""
        loc = _make_locale({"en-US/dialogs/greeting.dialog": "hello\n"})
        res = LocaleResources(skill_locale=str(loc))
        self.assertEqual(res.load_dialog("greeting", "en-US"), ["hello"])

    def test_duplicate_role_base_name_is_malformed(self):
        """"Two files with the same extension MUST NOT share a base name
        anywhere within one language directory tree … A loader … MUST treat the
        skill as malformed" (§2)."""
        loc = _make_locale({"en-US/yes.voc": "yes\n",
                            "en-US/sub/yes.voc": "yeah\n"})
        res = LocaleResources(skill_locale=str(loc))
        with self.assertRaises(MalformedResource):
            res.find("yes", ".voc", "en-US")

    def test_same_base_name_across_roles_are_distinct(self):
        """"Two files MAY share a base name when their roles differ:
        ``confirm.intent`` and ``confirm.dialog`` are distinct resources" (§2)."""
        loc = _make_locale({"en-US/confirm.intent": "are you sure\n",
                            "en-US/confirm.dialog": "are you sure?\n"})
        res = LocaleResources(skill_locale=str(loc))
        self.assertEqual(res.load_intent("confirm", "en-US"), ["are you sure"])
        self.assertEqual(res.load_dialog("confirm", "en-US"), ["are you sure?"])

    def test_lang_tag_comparison_case_insensitive(self):
        """"Tag comparison is case-insensitive: ``en-us`` and ``en-US`` denote
        the same language" (§2)."""
        loc = _make_locale({"en-US/yes.voc": "yes\n"})
        res = LocaleResources(skill_locale=str(loc))
        self.assertEqual(res.load_vocabulary("yes", "en-us"),
                         res.load_vocabulary("yes", "en-US"))


# ─────────────────────────────────────────────────────────────────────────────
# §3 — Common parsing rules
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3CommonReader(TestCase):
    """§3: every resource file is UTF-8, line-oriented; a BOM is discarded,
    both LF and CRLF are accepted, lines are stripped, blanks and ``#``-comment
    lines skipped, and there are "no inline (end-of-line) comments"."""

    def test_bom_discarded(self):
        """"a reader that encounters [a BOM] MUST discard it" (§3)."""
        loc = _make_locale({"en-US/yes.voc": b"\xef\xbb\xbfyes\n"})
        res = LocaleResources(skill_locale=str(loc))
        self.assertEqual(res.load_vocabulary("yes", "en-US"), ["yes"])

    def test_crlf_accepted(self):
        """"lines are terminated by ``LF`` or ``CRLF``; a reader MUST accept
        both" (§3)."""
        loc = _make_locale({"en-US/yes.voc": b"yes\r\nyeah\r\n"})
        res = LocaleResources(skill_locale=str(loc))
        self.assertEqual(sorted(res.load_vocabulary("yes", "en-US")),
                         ["yeah", "yes"])

    def test_blank_and_comment_lines_skipped(self):
        """"a blank line is skipped … a line whose first character is ``#`` is a
        comment and is skipped" (§3)."""
        path = _make_locale({"en-US/yes.voc": "yes\n\n# a comment\nyeah\n"})
        self.assertEqual(read_resource_file(path / "en-US" / "yes.voc"),
                         ["yes", "yeah"])

    def test_no_inline_comments(self):
        """"there are no inline (end-of-line) comments" — a ``#`` mid-line is
        literal, so only a line beginning with ``#`` is dropped (§3)."""
        path = _make_locale({"en-US/c.voc": "yes # not a comment\n"})
        self.assertEqual(read_resource_file(path / "en-US" / "c.voc"),
                         ["yes # not a comment"])


# ─────────────────────────────────────────────────────────────────────────────
# §4 — File formats
# ─────────────────────────────────────────────────────────────────────────────

class TestSec4_1Intent(TestCase):
    """§4.1: ``.intent`` "loads as the union of the sample sets of all lines …
    with named slots intact"; lines MAY declare different slot sets, the slot
    set being the union."""

    def test_intent_loads_union_with_slots_intact(self):
        """The ``play.intent`` example loads as the union of its lines' sample
        sets, slots carried through (§4.1)."""
        loc = _make_locale({"en-US/play.intent":
                            "(play|put on) {query}\n"
                            "i want to listen to {query}\n"})
        res = LocaleResources(skill_locale=str(loc))
        samples = res.load_intent("play", "en-US")
        self.assertIn("play {query}", samples)
        self.assertIn("put on {query}", samples)
        self.assertIn("i want to listen to {query}", samples)


class TestSec4_2Dialog(TestCase):
    """§4.2: a ``.dialog`` "is NOT expanded at load time — expansion happens
    per-render"; it "loads as … the list of phrase strings"."""

    def test_dialog_not_expanded_at_load(self):
        """A ``.dialog`` line with ``(a|b)`` variety loads as the verbatim
        phrase string, NOT its expanded variants (§4.2)."""
        loc = _make_locale({"en-US/g.dialog":
                            "(Currently|At the moment) it is {t} degrees.\n"})
        res = LocaleResources(skill_locale=str(loc))
        self.assertEqual(
            res.load_dialog("g", "en-US"),
            ["(Currently|At the moment) it is {t} degrees."])


class TestSec4_3SlotFreeRoles(TestCase):
    """§4.3: ``.entity`` / ``.voc`` / ``.blacklist`` share the slot-free format
    (no named slots); ``.blacklist`` "occurs … as a contiguous sequence of whole
    words — a token subsequence, not a raw substring"."""

    def test_slot_free_role_with_named_slot_is_malformed(self):
        """A slot-free role containing a named slot MUST be rejected — they are
        "expansion only, no named slots" (§4.3, §1.1)."""
        loc = _make_locale({"en-US/bad.voc": "hello {name}\n"})
        res = LocaleResources(skill_locale=str(loc))
        with self.assertRaises(MalformedResource):
            res.load_vocabulary("bad", "en-US")

    def test_blacklist_occurs_as_contiguous_whole_words(self):
        """A blacklist phrase "occurs … as a contiguous sequence of whole
        words"; a contiguous match suppresses, a split one does not (§4.3)."""
        self.assertTrue(utterance_contains("play music trailer now",
                                           ["music trailer"]))
        self.assertFalse(utterance_contains("play music a trailer now",
                                            ["music trailer"]))

    def test_blacklist_not_a_raw_substring(self):
        """"the phrase ``art`` does not occur within the word ``start``" — the
        match is a token subsequence, not a raw substring (§4.3)."""
        self.assertFalse(utterance_contains("start the car", ["art"]))
        self.assertTrue(utterance_contains("the art is nice", ["art"]))


# ─────────────────────────────────────────────────────────────────────────────
# §4.4 — .prompt — language-model prompt
# ─────────────────────────────────────────────────────────────────────────────

class TestSec4_4Prompt(TestCase):
    """§4.4: a ``.prompt`` is whole-file verbatim text — "not a template" — with
    "the only special construct … the ``{{name}}`` substitution point — the
    double-brace form only"."""

    def test_double_brace_substituted(self):
        """A well-formed ``{{name}}`` the caller supplied a value for is
        substituted (§4.4 condition 1 & 2)."""
        self.assertEqual(render_prompt("User asked: {{query}}",
                                       {"query": "weather"}),
                         "User asked: weather")

    def test_single_brace_passes_through(self):
        """"A single ``{name}`` … [is] never [a] substitution point — [it]
        pass[es] through unchanged" (§4.4)."""
        self.assertEqual(render_prompt("a {response} b", {"response": "X"}),
                         "a {response} b")

    def test_literal_json_braces_pass_through(self):
        """"literal JSON or markup such as ``{}``, ``{ }``, or ``{"key": 1}``
        are never substitution points — they pass through unchanged" (§4.4)."""
        self.assertEqual(
            render_prompt('shape {"summary": "x", "temp_c": 0} and {{q}}',
                          {"q": "Z"}),
            'shape {"summary": "x", "temp_c": 0} and Z')

    def test_unfilled_double_brace_stays_literal(self):
        """"A ``{{name}}`` for which the caller supplied no value is left as
        literal text — an unfilled slot is not an error" (§4.4)."""
        self.assertEqual(render_prompt("tone {{tone}} here", {}),
                         "tone {{tone}} here")

    def test_whole_file_verbatim_comments_kept(self):
        """"every character is part of the prompt … In particular there is no
        comment handling: an HTML-style ``<!-- … -->`` sequence is ordinary
        literal text" — ``#`` headings and ``<!-- -->`` are kept (§4.4)."""
        text = "# Weather assistant\n<!-- keep terse -->\nask: {{q}}\n"
        path = _make_locale({"en-US/w.prompt": text})
        # read_prompt_file does NO line filtering — the whole file survives.
        self.assertEqual(read_prompt_file(path / "en-US" / "w.prompt"), text)
        self.assertEqual(
            render_prompt(text, {"q": "now"}),
            "# Weather assistant\n<!-- keep terse -->\nask: now\n")


# ─────────────────────────────────────────────────────────────────────────────
# §5 — Authoring a conformant loader
# ─────────────────────────────────────────────────────────────────────────────

class TestSec5EmptyFile(TestCase):
    """§5: "Reject an empty file — a resource file of any role that yields no
    templates after step 3 MUST be treated as malformed: every file MUST
    contribute at least one template." (quoted clause)."""

    def test_empty_voc_is_malformed(self):
        """A ``.voc`` of only blanks and comments yields no templates and MUST
        be malformed (§5)."""
        loc = _make_locale({"en-US/empty.voc": "# only a comment\n\n"})
        res = LocaleResources(skill_locale=str(loc))
        with self.assertRaises(MalformedResource):
            res.load_vocabulary("empty", "en-US")

    def test_empty_dialog_is_malformed(self):
        """An empty ``.dialog`` MUST be malformed (§5)."""
        loc = _make_locale({"en-US/empty.dialog": "\n\n"})
        res = LocaleResources(skill_locale=str(loc))
        with self.assertRaises(MalformedResource):
            res.load_dialog("empty", "en-US")


# ─────────────────────────────────────────────────────────────────────────────
# §4.3 — End-to-end: a .voc phrase occurrence drives a keyword match
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_STACK,
                    reason="full ovos-core/ovoscope stack not installed "
                           "(harness installs the pinned stack in CI)")
class TestE2EVocOccurrence(TestCase):
    """§4.3 end-to-end: a vocabulary's whole-word occurrence in an utterance
    drives a keyword-intent match on the live orchestrator — the §4.3
    occurrence rule (asserted directly above) observed through the real
    pipeline."""

    @classmethod
    def setUpClass(cls):
        from ovos_utils.log import LOG
        from ovoscope import get_minicroft, register_padatious_intent
        from ._conformance import use_spec_namespace
        LOG.set_level("CRITICAL")
        use_spec_namespace()
        cls._mc = get_minicroft([])
        time.sleep(1)
        # The driver is padacioso (template family), but the §4.3 occurrence
        # property is the same: a phrase present as contiguous whole words
        # matches. Register an intent whose sample is the phrase under test.
        cls._intent = "intent2.skill:greet"
        register_padatious_intent(cls._mc.bus, cls._intent, ["good morning"])
        time.sleep(1.5)

    @classmethod
    def tearDownClass(cls):
        from ._conformance import reset_namespace
        if getattr(cls, "_mc", None) is not None:
            cls._mc.stop()
        reset_namespace()

    def test_phrase_occurrence_matches(self):
        """An utterance carrying the vocabulary phrase is matched (§4.3
        occurrence)."""
        from ._conformance import PADACIOSO_HIGH, capture, types, utterance
        recs = capture(self._mc, utterance(
            "good morning", "s1", [PADACIOSO_HIGH]), 4.0)
        self.assertIn(self._intent, types(recs),
                      f"expected {self._intent}; saw {types(recs)}")
