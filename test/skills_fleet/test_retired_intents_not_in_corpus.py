"""The corpus names no intent that a skill folded away or handed to another skill.

The fleet installs every skill from its dev branch. A row filed under an
intent that no longer exists asserts a claim the skill cannot make. Each name
below was removed by the skill PR in the comment beside it, and its rows
moved to the skill that answers now.

The test reads files only.
"""
import unittest

from ._fleet import load_corpus

#: (skill_id, retired intent label as the corpus spells it)
RETIRED = {
    # ovos-skill-number-facts: date and year trivia moved to ovos-skill-days-in-history
    ("ovos-skill-number-facts.openvoiceos", "date_trivia"),
    ("ovos-skill-number-facts.openvoiceos", "year_trivia"),
    # ovos-skill-icanhazdadjokes: search_joke folded into joke
    ("ovos-skill-icanhazdadjokes.openvoiceos", "search_joke.intent"),
    # ovos-skill-date-time: the weekday intents folded into weekday_for_date
    ("ovos-skill-date-time.openvoiceos", "what_weekday_is_it.intent"),
    ("ovos-skill-date-time.openvoiceos", "weekday_matches_date.intent"),
    # ovos-skill-hello-world: hello_world_intent folded into greetings
    ("ovos-skill-hello-world.openvoiceos", "hello_world_intent.intent"),
}


class TestCorpusNamesNoRetiredIntent(unittest.TestCase):

    def test_no_row_is_filed_under_a_retired_intent(self):
        filed = [(r["skill_id"], r["intent_label"], r["utterance"])
                 for r in load_corpus()
                 if (r["skill_id"], r["intent_label"]) in RETIRED]
        self.assertEqual(filed, [])

    def test_the_moved_rows_are_owned_by_days_in_history(self):
        owned = {(r["intent_label"], r["utterance"]) for r in load_corpus()
                 if r["skill_id"] == "ovos-skill-days-in-history.openvoiceos"}
        for label, utterance in (
                ("today_in_history.intent", "curiosity april aleatory"),
                ("today_in_history.intent", "curiosity april api"),
                ("year_in_history.intent", "curiosity year aleatory"),
                ("year_in_history.intent", "curiosity year api")):
            self.assertIn((label, utterance), owned)
