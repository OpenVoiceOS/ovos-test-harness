"""The numbers FINDINGS.md quotes must equal the numbers the suite reads.

FINDINGS.md carried its totals by hand, corrected each step from the previous
sentence rather than from `xfail_registry.json`. They drifted: the text said
28 coverage gaps and 5 conflicts where the registry held 19 and 4, and a
heading counted a struck-through row that has no registry entry.

These tests read the FLEET-COUNTS block and the two verdict tables and
compare them with the registry and the corpus, so the same drift fails the
suite instead of surviving another edit.

They need no MiniCroft and no fleet install: they read files only.
"""
import json
import os
import re
import unittest

from ._fleet import (FLEET_DIR, load_corpus, load_xfail_registry, row_key)

FINDINGS_PATH = os.path.join(FLEET_DIR, "FINDINGS.md")

_BLOCK = re.compile(r"<!-- FLEET-COUNTS:BEGIN.*?-->(.*?)<!-- FLEET-COUNTS:END -->",
                    re.S)
_ITEM = re.compile(r"^-\s*([^:]+):\s*(\d+)\s*$", re.M)


def _findings_text():
    with open(FINDINGS_PATH, encoding="utf-8") as f:
        return f.read()


def quoted_counts():
    """The FLEET-COUNTS block of FINDINGS.md as ``{label: int}``."""
    m = _BLOCK.search(_findings_text())
    assert m, ("FINDINGS.md has no FLEET-COUNTS block. It carries the totals "
               "this suite is measured by, so it must stay machine-readable.")
    return {k.strip(): int(v) for k, v in _ITEM.findall(m.group(1))}


def _table_rows(heading_prefix):
    """Data rows under a heading, excluding the separator and struck rows.

    A row written ``| ~~x~~ | ~~y~~ |`` is a verdict that was retired, kept
    for the history. It has no registry entry, so it is not counted.
    """
    lines = _findings_text().splitlines()
    start = next(i for i, l in enumerate(lines)
                 if l.startswith(heading_prefix))
    rows, seen_separator = [], False
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith("###"):
            break
        if not line.startswith("|"):
            continue
        if set(line.replace("|", "").strip()) <= set("- :"):
            seen_separator = True
            continue
        if not seen_separator:
            continue          # the header row
        if "~~" in line:
            continue          # a retired verdict
        rows.append(line)
    return rows


class TestFindingsCountsMatchTheRegistry(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rows = load_corpus()
        cls.registry = load_xfail_registry()
        cls.quoted = quoted_counts()
        cls.by_category = {}
        for entry in cls.registry.values():
            cls.by_category.setdefault(entry["category"], []).append(entry)

    def test_block_names_every_count(self):
        self.assertEqual(
            sorted(self.quoted),
            ["conflict entries", "correct", "coverage-gap entries",
             "exercised rows", "quarantined rows", "registry entries"])

    def test_exercised_rows(self):
        self.assertEqual(self.quoted["exercised rows"], len(self.rows))

    def test_registry_entries(self):
        self.assertEqual(self.quoted["registry entries"], len(self.registry))

    def test_conflict_entries(self):
        self.assertEqual(self.quoted["conflict entries"],
                         len(self.by_category.get("conflict", [])))

    def test_coverage_gap_entries(self):
        self.assertEqual(self.quoted["coverage-gap entries"],
                         len(self.by_category.get("coverage-gap", [])))

    def test_correct_is_exercised_minus_registry(self):
        self.assertEqual(self.quoted["correct"],
                         len(self.rows) - len(self.registry))

    def test_the_parts_sum_to_the_exercised_rows(self):
        # The control for the four tests above: each could match the registry
        # while the set as a whole was incoherent.
        self.assertEqual(
            self.quoted["correct"] + self.quoted["conflict entries"]
            + self.quoted["coverage-gap entries"],
            self.quoted["exercised rows"])

    def test_quarantined_rows(self):
        path = os.path.join(FLEET_DIR, "quarantine.jsonl")
        with open(path, encoding="utf-8") as f:
            n = sum(1 for line in f if line.strip())
        self.assertEqual(self.quoted["quarantined rows"], n)

    def test_every_registry_key_is_an_exercised_row(self):
        keys = {row_key(r) for r in self.rows}
        self.assertEqual(sorted(k for k in self.registry if k not in keys), [])

    def test_no_category_outside_the_two(self):
        self.assertEqual(sorted(self.by_category), ["conflict", "coverage-gap"])


class TestFindingsTablesMatchTheRegistry(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_xfail_registry()

    def _registry_count(self, category):
        return sum(1 for v in self.registry.values()
                   if v["category"] == category)

    def test_coverage_gap_table_has_one_row_per_entry(self):
        self.assertEqual(len(_table_rows("### Coverage gaps")),
                         self._registry_count("coverage-gap"))

    def test_conflict_table_has_one_live_row_per_entry(self):
        self.assertEqual(len(_table_rows("### Wrong-skill theft")),
                         self._registry_count("conflict"))

    def test_headings_quote_the_registry_numbers(self):
        text = _findings_text()
        for prefix, category in (("### Coverage gaps", "coverage-gap"),
                                 ("### Wrong-skill theft", "conflict")):
            heading = next(l for l in text.splitlines()
                           if l.startswith(prefix))
            n = int(re.search(r"—\s*(\d+)\s+rows", heading).group(1))
            self.assertEqual(n, self._registry_count(category), heading)


if __name__ == "__main__":
    unittest.main()
