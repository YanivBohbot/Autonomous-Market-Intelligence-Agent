"""Regression test for a word-boundary leak in the voice HITL verdict
classifier: the Hebrew alternatives in `_AFFIRMATIVE`/`_NEGATIVE` were not
wrapped in `\\b`, so any unrelated utterance containing one of them as a
*substring* of an unrelated word got misclassified as an explicit yes/no —
capable of silently approving (or cancelling) a pending side-effect tool
call the user never actually authorized or refused."""
from app.voice.hitl import classify_verdict


def test_unrelated_utterance_containing_yes_substring_is_not_approved():
    # "מוכן" ("ready") ends in the letters "כן" ("yes") but is a different
    # word. The sentence never answers a yes/no prompt.
    utterance = "הצוות שלי מוכן לעבודה"  # "My team is ready for work"
    assert classify_verdict(utterance) is None


def test_unrelated_utterance_containing_no_substring_is_not_rejected():
    # "לאט" ("slowly") starts with the letters "לא" ("no") but is a
    # different word. The sentence never answers a yes/no prompt.
    utterance = "בוא נעשה את זה לאט"  # "Let's do this slowly"
    assert classify_verdict(utterance) is None


def test_standalone_hebrew_yes_still_approves():
    assert classify_verdict("כן") == "approve"
    assert classify_verdict("בטח, לך על זה") == "approve"


def test_standalone_hebrew_no_still_rejects():
    assert classify_verdict("לא") == "reject"
    assert classify_verdict("עצור, בטל את זה") == "reject"


def test_english_yes_no_unaffected():
    assert classify_verdict("yes please") == "approve"
    assert classify_verdict("no, stop") == "reject"
