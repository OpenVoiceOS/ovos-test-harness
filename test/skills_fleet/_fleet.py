"""Shared helpers for the fleet-level cross-skill intent-routing suite.

The per-skill ovoscope suites each boot a MiniCroft with a single skill
installed, so they can never catch cross-skill intent theft: a skill that
happens to steal another skill's utterance still "passes" its own suite
because nothing else was loaded to lose the race to. This suite is the one
test that CAN catch that class of bug: it boots ONE MiniCroft with every
skill named in the golden corpus and asserts each utterance routes to the
skill that authored it.

Corpus
------
``golden_utterances.jsonl`` is a vendored copy of the ovoscope golden-utterance
dataset (one JSON object per line: ``skill_id``, ``utterance``,
``intent_method``, ``intent_label``, ``intent_type``, ``expected_messages``,
``needs_manual``). Rows with ``needs_manual: true`` require a human in the
loop (audio, GUI, follow-up dialog) and are skipped here — they are not
routing assertions this harness can make unattended.

``quarantine.jsonl`` holds corpus rows pulled out because the row itself is
wrong (typo'd skill_id, an utterance that legitimately belongs to a different
skill, etc). Never delete a bad row silently: move it here with a
``_quarantine_reason`` key so the corpus stays auditable.

Entry-point id drift
---------------------
A handful of fleet skills register their ``ovos.plugin.skill`` /
``opm.skill`` entry point under an id that does not match
``<repo-name>.openvoiceos`` (the id the corpus was generated against):
``SKILL_ID_OVERRIDES`` maps the corpus id to the id the skill actually
registers under, for both booting MiniCroft and for the routing assertion.
"""
import json
import os
from typing import Dict, Iterable, List

FLEET_DIR = os.path.dirname(__file__)
CORPUS_PATH = os.path.join(FLEET_DIR, "golden_utterances.jsonl")
QUARANTINE_PATH = os.path.join(FLEET_DIR, "quarantine.jsonl")
XFAIL_PATH = os.path.join(FLEET_DIR, "xfail_registry.json")

# corpus skill_id -> actual installed ``ovos.plugin.skill`` / ``opm.skill`` id.
# Discovered by inspecting the installed dist-info entry_points.txt of each
# git+https@dev fleet install; see FINDINGS.md "entry-point id drift".
SKILL_ID_OVERRIDES: Dict[str, str] = {
    "ovos-skill-color-picker.openvoiceos": "ovos-skill-color-picker.krisgesling",
    "ovos-skill-randomness.openvoiceos": "skill-ovos-randomness.openvoiceos",
    "ovos-skill-wallpapers.openvoiceos": "skill-ovos-wallpapers.openvoiceos",
    "ovos-skill-spelling.openvoiceos": "skill-ovos-spelling.openvoiceos",
}


def installed_id(corpus_skill_id: str) -> str:
    """The id the skill actually registers under (see ``SKILL_ID_OVERRIDES``)."""
    return SKILL_ID_OVERRIDES.get(corpus_skill_id, corpus_skill_id)


def _read_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_corpus() -> List[dict]:
    """All non-manual, non-quarantined golden-utterance rows."""
    quarantined_utterances = {
        (r["skill_id"], r["utterance"]) for r in _read_jsonl(QUARANTINE_PATH)
    }
    rows = []
    for row in _read_jsonl(CORPUS_PATH):
        if row.get("needs_manual"):
            continue
        if (row["skill_id"], row["utterance"]) in quarantined_utterances:
            continue
        rows.append(row)
    return rows


def load_xfail_registry() -> Dict[str, dict]:
    """``{row_key: {"category": "conflict"|"coverage-gap", "reason": str}}``.

    ``row_key`` is ``f"{skill_id}::{utterance}"``. Populated by triage after a
    run of the suite against the real fleet; see FINDINGS.md.
    """
    if not os.path.exists(XFAIL_PATH):
        return {}
    with open(XFAIL_PATH, encoding="utf-8") as f:
        return json.load(f)


def row_key(row: dict) -> str:
    return f"{row['skill_id']}::{row['utterance']}"


def fleet_skill_ids(rows: Iterable[dict]) -> List[str]:
    """The de-duplicated, entry-point-corrected skill id list to boot."""
    seen = []
    for row in rows:
        sid = installed_id(row["skill_id"])
        if sid not in seen:
            seen.append(sid)
    return seen
